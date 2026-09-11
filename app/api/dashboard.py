"""Seller dashboard summary.

The dashboard is the first authenticated page. Every number is scoped to the
merchant derived from the signed session; callers never provide a merchant id.
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import TenantScope, tenant
from app.core.database import get_db
from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection, ChannelConnectionStatus
from app.models.conversation import Conversation, HandoffState
from app.models.message import Message
from app.models.shop import Shop

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class DashboardCounts(BaseModel):
    needs_attention: int
    unread: int
    bot_handling: int
    active_channels: int
    active_bots: int


class RecentConversation(BaseModel):
    id: int
    customer_name: str
    customer_ref: str
    provider: str
    bot_name: str
    handoff_state: HandoffState
    last_message_at: datetime | None
    last_message_preview: str | None
    unread: bool


class DashboardSummary(BaseModel):
    counts: DashboardCounts
    recent_conversations: list[RecentConversation]


@router.get("/summary", response_model=DashboardSummary)
async def summary(
    scope: TenantScope = Depends(tenant),
    db: AsyncSession = Depends(get_db),
) -> DashboardSummary:
    unread = and_(
        Conversation.last_message_at.is_not(None),
        or_(
            Conversation.agent_last_read_at.is_(None),
            Conversation.last_message_at > Conversation.agent_last_read_at,
        ),
    )

    conversation_counts = (
        await db.execute(
            select(
                func.count(Conversation.id).filter(
                    Conversation.handoff_state == HandoffState.PENDING_HUMAN
                ),
                func.count(Conversation.id).filter(unread),
                func.count(Conversation.id).filter(
                    Conversation.handoff_state == HandoffState.BOT
                ),
            ).where(Conversation.merchant_id == scope.merchant_id)
        )
    ).one()

    active_bots = (
        await db.execute(
            select(func.count(Bot.id))
            .join(Shop, Shop.id == Bot.shop_id)
            .where(
                Shop.merchant_id == scope.merchant_id,
                Shop.deleted_at.is_(None),
                Bot.deleted_at.is_(None),
            )
        )
    ).scalar_one()

    active_channels = (
        await db.execute(
            select(func.count(ChannelConnection.id))
            .join(Bot, Bot.id == ChannelConnection.bot_id)
            .join(Shop, Shop.id == Bot.shop_id)
            .where(
                Shop.merchant_id == scope.merchant_id,
                Shop.deleted_at.is_(None),
                Bot.deleted_at.is_(None),
                ChannelConnection.deleted_at.is_(None),
                ChannelConnection.status == ChannelConnectionStatus.ACTIVE,
            )
        )
    ).scalar_one()

    last_message = (
        select(Message.text)
        .where(Message.conversation_id == Conversation.id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1)
        .correlate(Conversation)
        .scalar_subquery()
    )
    recent_rows = (
        await db.execute(
            select(
                Conversation,
                ChannelConnection.provider,
                Bot.name,
                last_message.label("last_message_preview"),
            )
            .join(
                ChannelConnection,
                ChannelConnection.id == Conversation.channel_connection_id,
            )
            .join(Bot, Bot.id == Conversation.bot_id)
            .where(Conversation.merchant_id == scope.merchant_id)
            .order_by(Conversation.last_message_at.desc().nullslast(), Conversation.id.desc())
            .limit(6)
        )
    ).all()

    recent = [
        RecentConversation(
            id=conversation.id,
            customer_name=conversation.customer_name or conversation.customer_ref,
            customer_ref=conversation.customer_ref,
            provider=provider,
            bot_name=bot_name,
            handoff_state=conversation.handoff_state,
            last_message_at=conversation.last_message_at,
            last_message_preview=preview,
            unread=bool(
                conversation.last_message_at
                and (
                    conversation.agent_last_read_at is None
                    or conversation.last_message_at > conversation.agent_last_read_at
                )
            ),
        )
        for conversation, provider, bot_name, preview in recent_rows
    ]

    return DashboardSummary(
        counts=DashboardCounts(
            needs_attention=conversation_counts[0],
            unread=conversation_counts[1],
            bot_handling=conversation_counts[2],
            active_channels=active_channels,
            active_bots=active_bots,
        ),
        recent_conversations=recent,
    )
