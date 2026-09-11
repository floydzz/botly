"""Read-only merchant wallet, history and sell prices. Provider costs stay private."""

from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import TenantScope, tenant
from app.core.config import settings
from app.core.database import get_db
from app.llm.providers import provider_ready
from app.models.billing import CreditEntry, CreditWallet, LlmModel, LlmUsage

router = APIRouter(tags=["billing"])


@router.get("/models")
async def models(scope: TenantScope = Depends(tenant), db=Depends(get_db)):
    rows = (await db.execute(select(LlmModel).where(LlmModel.enabled.is_(True)).order_by(LlmModel.provider, LlmModel.id))).scalars().all()
    return [{"id": row.id, "provider": row.provider, "model_code": row.model_code, "name": row.name,
             "available": provider_ready(row.provider), "max_input_tokens": row.max_input_tokens, "max_output_tokens": row.max_output_tokens,
             "input_credits_per_million": str(row.input_usd_per_million * row.multiplier * settings.BILLING_CREDITS_PER_USD),
             "output_credits_per_million": str(row.output_usd_per_million * row.multiplier * settings.BILLING_CREDITS_PER_USD),
             "cached_credits_per_million": str(row.cached_usd_per_million * row.multiplier * settings.BILLING_CREDITS_PER_USD)} for row in rows]


@router.get("/billing/wallet")
async def wallet(scope: TenantScope = Depends(tenant), db=Depends(get_db)):
    row = await db.get(CreditWallet, scope.merchant_id)
    balance, held = (row.balance, row.reserved) if row else (Decimal(0), Decimal(0))
    return {"balance": str(balance), "reserved": str(held), "available": str(balance - held), "credits_per_usd": str(settings.BILLING_CREDITS_PER_USD)}


@router.get("/billing/usage")
async def usage(scope: TenantScope = Depends(tenant), db=Depends(get_db), before_id: int | None = Query(default=None, gt=0), limit: int = Query(default=50, ge=1, le=100)):
    query = select(LlmUsage).where(LlmUsage.merchant_id == scope.merchant_id)
    if before_id:
        query = query.where(LlmUsage.id < before_id)
    rows = (await db.execute(query.order_by(LlmUsage.id.desc()).limit(limit))).scalars().all()
    # Never expose provider costs, prompts, raw responses or platform markup here.
    return [{"id": row.id, "bot_id": row.bot_id, "provider": row.pricing["provider"], "model": row.pricing["model_code"], "status": row.status,
             "input_tokens": row.input_tokens, "output_tokens": row.output_tokens, "cached_tokens": row.cached_tokens,
             "charged_credits": str(row.charged_credits), "reserved_credits": str(row.reserved_credits), "created_at": row.created_at} for row in rows]


@router.get("/billing/entries")
async def entries(scope: TenantScope = Depends(tenant), db=Depends(get_db), before_id: int | None = Query(default=None, gt=0), limit: int = Query(default=50, ge=1, le=100)):
    query = select(CreditEntry).where(CreditEntry.merchant_id == scope.merchant_id)
    if before_id:
        query = query.where(CreditEntry.id < before_id)
    rows = (await db.execute(query.order_by(CreditEntry.id.desc()).limit(limit))).scalars().all()
    return [{"id": row.id, "kind": row.kind, "amount": str(row.amount), "created_at": row.created_at} for row in rows]
