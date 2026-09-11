"""Merchant bot configuration. Prices and wallet funding are operator-only."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import TenantScope, tenant
from app.api.queries import bots_for
from app.core.database import get_db
from app.llm.providers import provider_ready
from app.models.billing import LlmModel
from app.models.bot import Bot
from app.models.shop import Shop

router = APIRouter(tags=["bots"])


class BotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    shop_id: int
    name: str = Field(min_length=1, max_length=255)
    persona: str = Field(default="", max_length=12000)
    llm_model_id: int | None = None
    escalation_max_bot_turns: int = Field(default=3, ge=1, le=50)


class BotPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    persona: str | None = Field(default=None, max_length=12000)
    llm_model_id: int | None = None
    escalation_max_bot_turns: int | None = Field(default=None, ge=1, le=50)


def bot_out(bot):
    return {key: getattr(bot, key) for key in ("id", "shop_id", "name", "persona", "llm_model_id", "llm_provider", "escalation_max_bot_turns")}


async def load_bot(db, scope, bot_id):
    bot = (await db.execute(bots_for(scope).where(Bot.id == bot_id))).scalar_one_or_none()
    if bot is None:
        raise HTTPException(404, "bot not found")
    return bot


async def selected_model(db, model_id):
    model = await db.get(LlmModel, model_id)
    if model is None or not model.enabled or not provider_ready(model.provider):
        raise HTTPException(422, "model is not available")
    return model


@router.get("/shops")
async def shops(scope: TenantScope = Depends(tenant), db=Depends(get_db)):
    rows = (await db.execute(select(Shop).where(Shop.merchant_id == scope.merchant_id, Shop.deleted_at.is_(None)).order_by(Shop.id))).scalars().all()
    return [{"id": row.id, "name": row.name} for row in rows]


@router.get("/bots")
async def bots(scope: TenantScope = Depends(tenant), db=Depends(get_db)):
    return [bot_out(bot) for bot in (await db.execute(bots_for(scope).order_by(Bot.id))).scalars()]


@router.post("/bots", status_code=201)
async def create_bot(body: BotCreate, scope: TenantScope = Depends(tenant), db=Depends(get_db)):
    shop = (await db.execute(select(Shop).where(Shop.id == body.shop_id, Shop.merchant_id == scope.merchant_id, Shop.deleted_at.is_(None)))).scalar_one_or_none()
    if shop is None:
        raise HTTPException(404, "shop not found")
    bot = Bot(**body.model_dump())
    if body.llm_model_id is not None:
        bot.llm_provider = (await selected_model(db, body.llm_model_id)).provider
    db.add(bot)
    await db.commit()
    return bot_out(bot)


@router.patch("/bots/{bot_id}")
async def update_bot(bot_id: int, body: BotPatch, scope: TenantScope = Depends(tenant), db=Depends(get_db)):
    bot = await load_bot(db, scope, bot_id)
    changes = body.model_dump(exclude_unset=True)
    if any(value is None for key, value in changes.items() if key != "llm_model_id"):
        raise HTTPException(422, "only llm_model_id can be null")
    if changes.get("llm_model_id") is not None:
        bot.llm_provider = (await selected_model(db, changes["llm_model_id"])).provider
    for key, value in changes.items():
        setattr(bot, key, value)
    db.add(bot)
    await db.commit()
    return bot_out(bot)
