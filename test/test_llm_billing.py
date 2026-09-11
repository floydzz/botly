import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.channels.fake.adapter import FakeAdapter
from app.dispatch.ratelimit import InMemoryTokenBucket
from app.llm.billing import BillingError, price, pricing_snapshot, reserve, settle, top_up
from app.llm.providers import Completion, ProviderError, TokenUsage
from app.models.billing import CreditEntry, CreditWallet, LlmModel, LlmUsage
from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection
from app.models.conversation import Conversation, HandoffState
from app.models.inbound_event import InboundEvent, InboundEventStatus
from app.models.merchant import Merchant
from app.models.message import Message, SenderType
from app.models.shop import Shop
from app.runtime.pipeline import run_inbound_pipeline


def model(**values):
    return LlmModel(provider="openai", model_code=f"test-{uuid4().hex}", name="Test model", enabled=True,
                    input_usd_per_million=Decimal("2"), output_usd_per_million=Decimal("8"),
                    cached_usd_per_million=Decimal("0.5"), cache_write_usd_per_million=Decimal("2.5"), multiplier=Decimal("2"),
                    max_input_tokens=4096, max_output_tokens=1024, **values)


def test_exact_cost_weighted_credits_include_cache_and_round_up():
    snapshot = pricing_snapshot(model())
    cost, credits = price(TokenUsage(input_tokens=1000, output_tokens=200, cached_tokens=400, cache_write_tokens=100), snapshot)
    assert cost == Decimal("0.00305")
    assert credits == Decimal("6.1")
    snapshot["input_usd_per_million"] = "0.00001"
    assert price(TokenUsage(input_tokens=1, output_tokens=0), snapshot)[1] == Decimal("0.000001")


async def graph(db):
    merchant = Merchant(name=f"credits-{uuid4().hex}")
    db.add(merchant); await db.flush()
    shop = Shop(merchant_id=merchant.id, name="Shop", platform="standalone")
    db.add(shop); await db.flush()
    choice = model()
    db.add(choice); await db.flush()
    bot = Bot(shop_id=shop.id, name="Bot", llm_model_id=choice.id)
    db.add(bot); await db.flush()
    channel = ChannelConnection(bot_id=bot.id, provider="fake", external_ref=uuid4().hex)
    channel.set_credentials({})
    db.add(channel); await db.flush()
    event = InboundEvent(connection_id=channel.id, provider="fake", provider_update_id="u1", payload={"updates": [{"update_id": "u1", "thread": "customer-thread", "from": "c1", "ts": 1757000000, "text": "hello"}]})
    db.add(event); await db.flush()
    return merchant, bot, choice, event


async def hold(db, merchant, bot, choice, event):
    return await reserve(db, merchant_id=merchant.id, bot_id=bot.id, event_id=event.id, update_id=event.provider_update_id, model=choice)


@pytest.mark.integration
async def test_reserve_settle_snapshot_and_duplicate_idempotency(db_session):
    merchant, bot, choice, event = await graph(db_session)
    await top_up(db_session, merchant.id, Decimal(100), "payment-1", "verified")
    await top_up(db_session, merchant.id, Decimal(100), "payment-1", "verified")
    record, fresh = await hold(db_session, merchant, bot, choice, event)
    assert fresh
    held = record.reserved_credits
    assert held > 0
    again, fresh = await hold(db_session, merchant, bot, choice, event)
    assert not fresh and again.id == record.id
    choice.multiplier = Decimal(20)
    result = Completion("hello", TokenUsage(input_tokens=1000, output_tokens=200, cached_tokens=400), {"test": True}, "req-1")
    await settle(db_session, record.id, result=result)
    await settle(db_session, record.id, result=result)
    wallet = await db_session.get(CreditWallet, merchant.id)
    assert wallet.balance == Decimal("94") and wallet.reserved == 0
    assert record.provider_cost_usd == Decimal("0.003")
    assert record.pricing["multiplier"] == "2"
    assert (await db_session.execute(select(func.count()).select_from(CreditEntry))).scalar_one() == 2


@pytest.mark.integration
async def test_insufficient_credits_prevent_reservation(db_session):
    merchant, bot, choice, event = await graph(db_session)
    with pytest.raises(BillingError, match="insufficient"):
        await hold(db_session, merchant, bot, choice, event)
    assert (await db_session.execute(select(func.count()).select_from(LlmUsage))).scalar_one() == 0


@pytest.mark.integration
async def test_uncertain_hold_and_explicit_reconciliation(db_session):
    merchant, bot, choice, event = await graph(db_session)
    await top_up(db_session, merchant.id, Decimal(100), "payment-1", "verified")
    record, _ = await hold(db_session, merchant, bot, choice, event)
    await settle(db_session, record.id, error="timeout", uncertain=True)
    wallet = await db_session.get(CreditWallet, merchant.id)
    assert wallet.balance == 100 and wallet.reserved == record.reserved_credits
    assert record.status == "uncertain"
    await settle(db_session, record.id, error="operator verified no charge")
    await settle(db_session, record.id, error="repeat")
    assert wallet.reserved == 0 and wallet.balance == 100 and record.status == "released"


@pytest.mark.integration
async def test_over_budget_response_is_recorded_without_overspending(db_session):
    merchant, bot, choice, event = await graph(db_session)
    await top_up(db_session, merchant.id, Decimal(100), "payment-1", "verified")
    record, _ = await hold(db_session, merchant, bot, choice, event)
    result = Completion("x", TokenUsage(input_tokens=100000, output_tokens=100000), {})
    await settle(db_session, record.id, result=result)
    wallet = await db_session.get(CreditWallet, merchant.id)
    assert record.status == "uncertain" and record.provider_cost_usd == Decimal(1)
    assert wallet.balance == 100 and wallet.reserved > 0


@pytest.mark.integration
async def test_funding_reference_cannot_change_amount(db_session):
    merchant, *_ = await graph(db_session)
    await top_up(db_session, merchant.id, Decimal(100), "payment-1", "verified")
    with pytest.raises(BillingError, match="different transaction"):
        await top_up(db_session, merchant.id, Decimal(200), "payment-1", "verified")


@pytest.mark.integration
async def test_concurrent_wallet_reservations_cannot_overspend(test_engine):
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as db:
        merchant, bot, choice, first = await graph(db)
        second = InboundEvent(connection_id=first.connection_id, provider="fake", provider_update_id="u2", payload={})
        db.add(second)
        await top_up(db, merchant.id, Decimal(40), "payment-concurrent", "test")
        await db.commit()
    async def attempt(event):
        async with factory() as db:
            try:
                result = await hold(db, merchant, bot, choice, event)
                await db.commit()
                return result[1]
            except BillingError:
                await db.rollback()
                return False
    assert sorted(await asyncio.gather(attempt(first), attempt(second))) == [False, True]
    async with factory() as db:
        wallet = await db.get(CreditWallet, merchant.id)
        assert 0 < wallet.reserved <= wallet.balance


@pytest.mark.integration
@pytest.mark.parametrize("failure", [None, "timeout", "rejected", "empty-wallet"])
async def test_paid_pipeline_durable_usage_and_duplicate_delivery(test_engine, monkeypatch, failure):
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as db:
        merchant, bot, choice, event = await graph(db)
        if failure != "empty-wallet":
            await top_up(db, merchant.id, Decimal(100), "payment-flow", "test")
        await db.commit()
    calls, sent = [], []
    class Provider:
        async def complete(self, model, system, messages, max_output):
            calls.append(messages)
            if failure in {"timeout", "rejected"}:
                raise ProviderError("test failure", uncertain=failure == "timeout")
            return Completion("Hello customer", TokenUsage(input_tokens=100, output_tokens=10), {"prompt_tokens": 100, "completion_tokens": 10})
    class Channel(FakeAdapter):
        async def send(self, conn, out):
            sent.append(out)
            return await super().send(conn, out)
    monkeypatch.setattr("app.runtime.pipeline.build_adapter", lambda connection: Channel())
    async def run():
        await run_inbound_pipeline(event.id, session_factory=factory, billing_session_factory=factory, provider_factory=lambda provider: Provider(), limiter=InMemoryTokenBucket())
    await asyncio.gather(run(), run())
    await run()
    assert len(calls) == (0 if failure == "empty-wallet" else 1)
    async with factory() as db:
        event = await db.get(InboundEvent, event.id)
        assert event.status == InboundEventStatus.PROCESSED
        conversation = (await db.execute(select(Conversation).where(Conversation.merchant_id == merchant.id))).scalar_one()
        records = (await db.execute(select(LlmUsage).where(LlmUsage.merchant_id == merchant.id))).scalars().all()
        if failure:
            assert not sent and conversation.handoff_state == HandoffState.PENDING_HUMAN
            if failure != "empty-wallet":
                assert records[0].status == ("uncertain" if failure == "timeout" else "released")
        else:
            assert len(sent) == 1 and sent[0].external_thread_id == "customer-thread"
            assert calls[0][-1] == {"role": "user", "content": "hello"}
            assert records[0].status == "settled" and records[0].charged_credits == Decimal("0.56")
        inbound_count = (await db.execute(select(func.count()).select_from(Message).where(Message.conversation_id == conversation.id, Message.sender_type == SenderType.CUSTOMER))).scalar_one()
        assert inbound_count == 1
