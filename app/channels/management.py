"""Tenant-scoped channel setup; concrete channel details stay in this package."""

import secrets
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.bots import load_bot
from app.api.deps import TenantScope, tenant
from app.api.queries import connections_for
from app.channels.telegram.adapter import TelegramAdapter
from app.channels.telegram.api import HttpTelegramApi
from app.core.config import settings
from app.core.database import get_db
from app.models.channel_connection import ChannelConnection, ChannelConnectionStatus

router = APIRouter(prefix="/channels", tags=["channels"])


class ConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bot_id: int
    bot_token: SecretStr = Field(min_length=10, max_length=255)


def connection_out(row):
    return {"id": row.id, "bot_id": row.bot_id, "provider": row.provider, "external_ref": row.external_ref, "status": row.status, "username": (row.config or {}).get("username")}


def channel_api():
    return HttpTelegramApi()


@router.get("")
async def list_channels(scope: TenantScope = Depends(tenant), db=Depends(get_db)):
    return [connection_out(row) for row in (await db.execute(connections_for(scope).order_by(ChannelConnection.id))).scalars()]


@router.post("/telegram", status_code=201)
async def connect_channel(body: ConnectRequest, scope: TenantScope = Depends(tenant), db=Depends(get_db), api=Depends(channel_api)):
    await load_bot(db, scope, body.bot_id)
    base = settings.PUBLIC_WEBHOOK_BASE_URL.rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
        raise HTTPException(503, "public HTTPS webhook URL is not configured")
    token = body.bot_token.get_secret_value()
    # Token is a URL path component in the Bot API. Refuse path/query injection.
    if any(char not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ:_-" for char in token):
        raise HTTPException(422, "invalid bot token format")
    identity = await api.call(token, "getMe", {})
    if not identity.ok or not (identity.result or {}).get("is_bot") or not identity.result.get("id"):
        raise HTTPException(422, "bot token could not be verified")
    external_ref = str(identity.result["id"])
    existing = (await db.execute(select(ChannelConnection).where(ChannelConnection.provider == "telegram", ChannelConnection.external_ref == external_ref).with_for_update())).scalar_one_or_none()
    if existing:
        # Never overwrite another merchant's connection, even with its token.
        owned = (await db.execute(connections_for(scope).where(ChannelConnection.id == existing.id))).scalar_one_or_none()
        if owned is None or existing.bot_id != body.bot_id:
            raise HTTPException(409, "this channel account is already connected")
        if existing.status == ChannelConnectionStatus.CONNECTING:
            raise HTTPException(409, "channel setup is already in progress")
        row = owned
    else:
        row = ChannelConnection(bot_id=body.bot_id, provider="telegram", external_ref=external_ref)
    row.set_credentials({"bot_token": token, "secret_token": secrets.token_urlsafe(32)})
    row.config = {"username": identity.result.get("username")}
    row.status = ChannelConnectionStatus.CONNECTING
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "this channel account is already connected") from None
    # Persist the secret before registration so the first webhook can authenticate.
    adapter = TelegramAdapter(token=token, secret_token=row.get_credentials()["secret_token"], api=api, webhook_url=f"{base}/webhooks/telegram/{row.id}")
    try:
        await adapter.connect(row)
    except ValueError:
        row.status = ChannelConnectionStatus.DEGRADED
        await db.commit()
        raise HTTPException(502, "webhook registration failed; retry channel setup") from None
    row.status = ChannelConnectionStatus.ACTIVE
    await db.commit()
    return connection_out(row)
