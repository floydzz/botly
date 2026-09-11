"""Wallet transactions. Caller commits each transition before proceeding externally."""

from decimal import Decimal, ROUND_CEILING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.config import settings
from app.llm.providers import TokenUsage
from app.models.billing import CreditEntry, CreditWallet, LlmModel, LlmUsage

QUANTUM = Decimal("0.000001")


class BillingError(ValueError):
    pass


def pricing_snapshot(model: LlmModel) -> dict:
    return {"provider": model.provider, "model_code": model.model_code, "credits_per_usd": str(settings.BILLING_CREDITS_PER_USD), **{
        key: str(getattr(model, key)) for key in ("input_usd_per_million", "output_usd_per_million", "cached_usd_per_million", "cache_write_usd_per_million", "multiplier")
    }}


def price(usage: TokenUsage, snapshot: dict) -> tuple[Decimal, Decimal]:
    cost = (
        (usage.input_tokens - usage.cached_tokens - usage.cache_write_tokens) * Decimal(snapshot["input_usd_per_million"])
        + usage.cached_tokens * Decimal(snapshot["cached_usd_per_million"])
        + usage.cache_write_tokens * Decimal(snapshot["cache_write_usd_per_million"])
        + usage.output_tokens * Decimal(snapshot["output_usd_per_million"])
    ) / Decimal(1_000_000)
    credits = (cost * Decimal(snapshot["multiplier"]) * Decimal(snapshot["credits_per_usd"])).quantize(QUANTUM, rounding=ROUND_CEILING)
    return cost, credits


async def locked_wallet(db, merchant_id: int) -> CreditWallet:
    await db.execute(insert(CreditWallet).values(merchant_id=merchant_id).on_conflict_do_nothing())
    return (await db.execute(select(CreditWallet).where(CreditWallet.merchant_id == merchant_id).with_for_update().execution_options(populate_existing=True))).scalar_one()


async def top_up(db, merchant_id: int, amount: Decimal, reference: str, note: str) -> CreditEntry:
    if not amount.is_finite() or amount <= 0 or amount >= Decimal("1e18") or amount != amount.quantize(QUANTUM) or not reference.strip() or len(reference) > 191 or reference.startswith("usage:") or not note.strip():
        raise BillingError("top-up requires positive credits (up to 6 decimals), a reference and an audit note")
    wallet = await locked_wallet(db, merchant_id)
    existing = (await db.execute(select(CreditEntry).where(CreditEntry.merchant_id == merchant_id, CreditEntry.reference == reference))).scalar_one_or_none()
    if existing:
        if existing.amount != amount or existing.kind != "top_up":
            raise BillingError("reference already used for a different transaction")
        return existing
    wallet.balance += amount
    entry = CreditEntry(merchant_id=merchant_id, reference=reference, kind="top_up", amount=amount, note=note)
    db.add(entry)
    await db.flush()
    return entry


async def reserve(db, *, merchant_id: int, bot_id: int, event_id: int, update_id: str, model: LlmModel, request_context: dict | None = None) -> tuple[LlmUsage, bool]:
    wallet = await locked_wallet(db, merchant_id)
    existing = (await db.execute(select(LlmUsage).where(LlmUsage.inbound_event_id == event_id, LlmUsage.update_id == update_id))).scalar_one_or_none()
    if existing:
        if existing.merchant_id != merchant_id or existing.bot_id != bot_id:
            raise BillingError("usage scope mismatch")
        return existing, False
    snapshot = pricing_snapshot(model)
    # Reserve full configured limits, not a guessed tokenizer count. Cached input
    # cannot cost more than this worst input rate. Gemini thoughts are included
    # in output usage; excessive/malformed usage stays held for reconciliation.
    ceiling = dict(snapshot)
    ceiling["input_usd_per_million"] = str(max(Decimal(snapshot[k]) for k in ("input_usd_per_million", "cached_usd_per_million", "cache_write_usd_per_million")))
    _, held = price(TokenUsage(input_tokens=model.max_input_tokens, output_tokens=model.max_output_tokens), ceiling)
    if wallet.balance - wallet.reserved < held:
        raise BillingError("insufficient merchant credits")
    wallet.reserved += held
    usage = LlmUsage(merchant_id=merchant_id, bot_id=bot_id, inbound_event_id=event_id, update_id=update_id, model_id=model.id, pricing=snapshot, reserved_credits=held, request_context=request_context or {})
    db.add(usage)
    await db.flush()
    return usage, True


async def settle(db, usage_id: int, *, result=None, error: str | None = None, uncertain: bool = False, allow_overage: bool = False) -> LlmUsage:
    record = (await db.execute(select(LlmUsage).where(LlmUsage.id == usage_id).with_for_update().execution_options(populate_existing=True))).scalar_one()
    if record.status in {"settled", "released"}:
        return record
    wallet = await locked_wallet(db, record.merchant_id)
    record.error = error
    if result is not None:
        record.raw_usage = result.raw_usage
        record.provider_request_id = result.request_id
        record.response_text = result.text
        for key, value in result.usage.model_dump().items():
            setattr(record, key, value)
        cost, charge = price(result.usage, record.pricing)
        record.provider_cost_usd = cost
        if charge > record.reserved_credits and (not allow_overage or charge > wallet.balance - wallet.reserved + record.reserved_credits):
            record.status, record.error = "uncertain", "reported cost exceeds reserved limit; reconcile before further processing"
            return record
        record.charged_credits = charge
        wallet.balance -= charge
        wallet.reserved -= record.reserved_credits
        record.status = "settled"
        db.add(CreditEntry(merchant_id=record.merchant_id, reference=f"usage:{record.id}", kind="usage", amount=-charge, note="model usage settled from provider token counts"))
    elif uncertain:
        record.status = "uncertain"
    else:
        wallet.reserved -= record.reserved_credits
        record.status = "released"
    await db.flush()
    return record
