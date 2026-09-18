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
from app.models.orchestration import BotWorker, ToolWriteMode, WorkerDefinition, WorkerKey
from app.orchestration.catalog import ensure_worker_catalog
from app.models.brand import Brand

router = APIRouter(tags=["bots"])


class BotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    brand_id: int
    name: str = Field(min_length=1, max_length=255)
    persona: str = Field(default="", max_length=12000)
    llm_model_id: int | None = None
    escalation_max_bot_turns: int = Field(default=3, ge=1, le=50)
    tool_write_mode: ToolWriteMode = ToolWriteMode.CONFIRM_CUSTOMER
    auditor_enabled: bool = False


class BotPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    persona: str | None = Field(default=None, max_length=12000)
    llm_model_id: int | None = None
    escalation_max_bot_turns: int | None = Field(default=None, ge=1, le=50)
    tool_write_mode: ToolWriteMode | None = None
    auditor_enabled: bool | None = None


class BotWorkerPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    config: dict = Field(default_factory=dict)


def bot_out(bot):
    return {key: getattr(bot, key) for key in ("id", "brand_id", "name", "persona", "llm_model_id", "llm_provider", "escalation_max_bot_turns", "tool_write_mode", "auditor_enabled")}


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


@router.get("/brands")
async def brands(scope: TenantScope = Depends(tenant), db=Depends(get_db)):
    rows = (await db.execute(select(Brand).where(Brand.merchant_id == scope.merchant_id, Brand.deleted_at.is_(None)).order_by(Brand.id))).scalars().all()
    return [{"id": row.id, "name": row.name} for row in rows]


@router.get("/bots")
async def bots(scope: TenantScope = Depends(tenant), db=Depends(get_db)):
    return [bot_out(bot) for bot in (await db.execute(bots_for(scope).order_by(Bot.id))).scalars()]


@router.post("/bots", status_code=201)
async def create_bot(body: BotCreate, scope: TenantScope = Depends(tenant), db=Depends(get_db)):
    brand = (await db.execute(select(Brand).where(Brand.id == body.brand_id, Brand.merchant_id == scope.merchant_id, Brand.deleted_at.is_(None)))).scalar_one_or_none()
    if brand is None:
        raise HTTPException(404, "brand not found")
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


@router.get("/bots/{bot_id}/workers")
async def bot_workers(bot_id: int, scope: TenantScope = Depends(tenant), db=Depends(get_db)):
    await load_bot(db, scope, bot_id)
    await ensure_worker_catalog(db)
    definitions = (await db.execute(select(WorkerDefinition).order_by(WorkerDefinition.id))).scalars().all()
    configured = {
        row.worker_definition_id: row
        for row in (await db.execute(select(BotWorker).where(BotWorker.bot_id == bot_id))).scalars()
    }
    return [
        {
            "key": definition.key,
            "name": definition.name,
            "description": definition.description,
            "enabled": configured.get(definition.id).enabled if definition.id in configured else False,
            "config": configured.get(definition.id).config if definition.id in configured else {},
        }
        for definition in definitions
    ]


@router.put("/bots/{bot_id}/workers/{worker_key}")
async def configure_bot_worker(
    bot_id: int,
    worker_key: WorkerKey,
    body: BotWorkerPatch,
    scope: TenantScope = Depends(tenant),
    db=Depends(get_db),
):
    await load_bot(db, scope, bot_id)
    await ensure_worker_catalog(db)
    definition = (
        await db.execute(select(WorkerDefinition).where(WorkerDefinition.key == worker_key))
    ).scalar_one_or_none()
    if definition is None:
        raise HTTPException(404, "worker not found")
    row = (
        await db.execute(
            select(BotWorker).where(
                BotWorker.bot_id == bot_id,
                BotWorker.worker_definition_id == definition.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = BotWorker(bot_id=bot_id, worker_definition_id=definition.id)
    row.enabled = body.enabled
    row.config = body.config
    db.add(row)
    await db.commit()
    return {"key": definition.key, "enabled": row.enabled, "config": row.config}
