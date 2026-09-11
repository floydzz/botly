"""Tenant-scoped query helpers for inbox resources."""

from fastapi import HTTPException
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import TenantScope
from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection
from app.models.conversation import Conversation
from app.models.shop import Shop


def conversations_for(scope: TenantScope) -> Select:
    return select(Conversation).where(Conversation.merchant_id == scope.merchant_id)


def bots_for(scope: TenantScope) -> Select:
    return (
        select(Bot)
        .join(Shop, Shop.id == Bot.shop_id)
        .where(
            Shop.merchant_id == scope.merchant_id,
            Shop.deleted_at.is_(None),
            Bot.deleted_at.is_(None),
        )
    )


def connections_for(scope: TenantScope) -> Select:
    return (
        select(ChannelConnection)
        .join(Bot, Bot.id == ChannelConnection.bot_id)
        .join(Shop, Shop.id == Bot.shop_id)
        .where(
            Shop.merchant_id == scope.merchant_id,
            Shop.deleted_at.is_(None),
            Bot.deleted_at.is_(None),
            ChannelConnection.deleted_at.is_(None),
        )
    )


async def load_conversation(
    db: AsyncSession, scope: TenantScope, conversation_id: int
) -> Conversation:
    conversation = (
        await db.execute(
            conversations_for(scope).where(Conversation.id == conversation_id)
        )
    ).scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return conversation
