"""The tenant-scoped seller inbox and its human-handoff actions."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, case, desc, func, nullslast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import TenantScope, tenant
from app.api.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    InvalidCursor,
    decode_cursor,
    encode_cursor,
)
from app.api.queries import load_conversation
from app.api.schemas import (
    BotRef,
    ConversationCounts,
    ConversationDetail,
    ConversationSummary,
    MessageOut,
    Page,
    UserRef,
)
from app.api.send_policy import SendPolicy, build_send_policy
from app.channels.registry import (
    MissingCredentials,
    UnknownProvider,
    build_adapter,
    capabilities_for,
)
from app.core.config import settings
from app.core.database import get_db
from app.dispatch.dispatcher import OutboundDispatcher
from app.dispatch.ratelimit import default_limiter
from app.dispatch.record import record_outbound
from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection
from app.models.conversation import Conversation, HandoffState
from app.models.failed_job import FailedJob
from app.models.message import DeliveryStatus, Direction, Message, SenderType
from app.models.user import User
from app.runtime.brain import DraftReply

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _unread_predicate():
    return and_(
        Conversation.last_message_at.is_not(None),
        or_(
            Conversation.agent_last_read_at.is_(None),
            Conversation.last_message_at > Conversation.agent_last_read_at,
        ),
    )


def _base_select(scope: TenantScope):
    newest_preview = (
        select(Message.text)
        .where(Message.conversation_id == Conversation.id)
        .order_by(desc(Message.created_at), desc(Message.id))
        .limit(1)
        .correlate(Conversation)
        .scalar_subquery()
    )
    last_outbound_status = (
        select(Message.delivery_status)
        .where(
            Message.conversation_id == Conversation.id,
            Message.direction == Direction.OUTBOUND,
        )
        .order_by(desc(Message.created_at), desc(Message.id))
        .limit(1)
        .correlate(Conversation)
        .scalar_subquery()
    )
    return (
        select(
            Conversation,
            ChannelConnection.provider.label("provider"),
            Bot.id.label("bot_id"),
            Bot.name.label("bot_name"),
            User.id.label("assignee_user_id"),
            User.name.label("assignee_name"),
            newest_preview.label("preview"),
            last_outbound_status.label("last_outbound_status"),
        )
        .join(
            ChannelConnection,
            ChannelConnection.id == Conversation.channel_connection_id,
        )
        .join(Bot, Bot.id == Conversation.bot_id)
        .outerjoin(User, User.id == Conversation.assignee_id)
        .where(Conversation.merchant_id == scope.merchant_id)
    )


def row_to_summary(row) -> ConversationSummary:
    conversation = row[0]
    last_message = conversation.last_message_at
    last_read = conversation.agent_last_read_at
    return ConversationSummary(
        id=conversation.id,
        customer_name=conversation.customer_name,
        customer_ref=conversation.customer_ref,
        provider=row.provider,
        connection_id=conversation.channel_connection_id,
        bot=BotRef(id=row.bot_id, name=row.bot_name),
        handoff_state=conversation.handoff_state,
        escalation_reason=conversation.escalation_reason,
        assignee=(
            UserRef(id=row.assignee_user_id, name=row.assignee_name)
            if row.assignee_user_id is not None
            else None
        ),
        last_message_at=last_message,
        last_message_preview=row.preview,
        unread=bool(
            last_message is not None
            and (last_read is None or last_message > last_read)
        ),
        has_failed_delivery=row.last_outbound_status == DeliveryStatus.FAILED,
    )


async def _summary_row(
    db: AsyncSession, scope: TenantScope, conversation_id: int
):
    row = (
        await db.execute(
            _base_select(scope).where(Conversation.id == conversation_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return row


@router.get("", response_model=Page[ConversationSummary])
async def list_conversations(
    state: list[HandoffState] = Query(default=[]),
    provider: list[str] = Query(default=[]),
    assignee: str | None = None,
    unread: bool | None = None,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    scope: TenantScope = Depends(tenant),
    db: AsyncSession = Depends(get_db),
) -> Page[ConversationSummary]:
    statement = _base_select(scope)
    if state:
        statement = statement.where(Conversation.handoff_state.in_(state))
    if provider:
        statement = statement.where(ChannelConnection.provider.in_(provider))
    if assignee == "me":
        statement = statement.where(Conversation.assignee_id == scope.user.id)
    elif assignee == "unassigned":
        statement = statement.where(Conversation.assignee_id.is_(None))
    elif assignee is not None:
        try:
            statement = statement.where(Conversation.assignee_id == int(assignee))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="assignee must be me, unassigned or a user id",
            ) from None
    if unread:
        statement = statement.where(_unread_predicate())

    try:
        seek = decode_cursor(cursor)
    except InvalidCursor:
        raise HTTPException(status_code=400, detail="cursor is not readable") from None
    if seek is not None:
        if seek.last_message_at is None:
            statement = statement.where(
                Conversation.last_message_at.is_(None), Conversation.id < seek.id
            )
        else:
            statement = statement.where(
                or_(
                    Conversation.last_message_at.is_(None),
                    Conversation.last_message_at < seek.last_message_at,
                    and_(
                        Conversation.last_message_at == seek.last_message_at,
                        Conversation.id < seek.id,
                    ),
                )
            )

    rows = (
        await db.execute(
            statement.order_by(
                nullslast(desc(Conversation.last_message_at)), desc(Conversation.id)
            ).limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1][0]
        next_cursor = encode_cursor(last.last_message_at, last.id)
    return Page[ConversationSummary](
        items=[row_to_summary(row) for row in rows], next_cursor=next_cursor
    )


@router.get("/counts", response_model=ConversationCounts)
async def conversation_counts(
    scope: TenantScope = Depends(tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationCounts:
    result = (
        await db.execute(
            select(
                func.count().label("all"),
                func.count().filter(
                    Conversation.handoff_state == HandoffState.PENDING_HUMAN
                ).label("needs_attention"),
                func.count().filter(
                    Conversation.assignee_id == scope.user.id
                ).label("mine"),
                func.count().filter(_unread_predicate()).label("unread"),
                func.count().filter(
                    Conversation.handoff_state == HandoffState.RESOLVED
                ).label("resolved"),
            )
            .select_from(Conversation)
            .where(Conversation.merchant_id == scope.merchant_id)
        )
    ).one()
    return ConversationCounts(**result._mapping)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: int,
    scope: TenantScope = Depends(tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationDetail:
    row = await _summary_row(db, scope, conversation_id)
    conversation = row[0]
    try:
        policy = build_send_policy(
            capabilities_for(row.provider), conversation.last_inbound_at
        )
    except UnknownProvider:
        policy = SendPolicy(
            can_send_freeform=False,
            reason="this channel is no longer supported",
            max_text_len=0,
            supports_media=False,
        )
    return ConversationDetail(**row_to_summary(row).model_dump(), send_policy=policy)


def message_row_to_schema(row) -> MessageOut:
    message = row[0]
    return MessageOut(
        id=message.id,
        direction=message.direction,
        sender_type=message.sender_type,
        sender=(
            UserRef(id=row.sender_id, name=row.sender_name)
            if row.sender_id is not None
            else None
        ),
        text=message.text,
        attachments=message.attachments,
        provider_message_id=message.provider_message_id,
        delivery_status=message.delivery_status,
        error=message.error,
        created_at=message.created_at,
    )


@router.get("/{conversation_id}/messages", response_model=Page[MessageOut])
async def list_messages(
    conversation_id: int,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    scope: TenantScope = Depends(tenant),
    db: AsyncSession = Depends(get_db),
) -> Page[MessageOut]:
    await load_conversation(db, scope, conversation_id)
    try:
        seek = decode_cursor(cursor)
    except InvalidCursor:
        raise HTTPException(status_code=400, detail="cursor is not readable") from None

    statement = (
        select(Message, User.id.label("sender_id"), User.name.label("sender_name"))
        .outerjoin(User, User.id == Message.sender_user_id)
        .where(
            Message.conversation_id == conversation_id,
            Message.merchant_id == scope.merchant_id,
        )
    )
    if seek is not None:
        if seek.last_message_at is None:
            raise HTTPException(status_code=400, detail="cursor is not readable")
        statement = statement.where(
            or_(
                Message.created_at < seek.last_message_at,
                and_(
                    Message.created_at == seek.last_message_at,
                    Message.id < seek.id,
                ),
            )
        )
    rows = (
        await db.execute(
            statement.order_by(desc(Message.created_at), desc(Message.id)).limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1][0]
        next_cursor = encode_cursor(last.created_at, last.id)
    return Page[MessageOut](
        items=[message_row_to_schema(row) for row in rows], next_cursor=next_cursor
    )


@router.post("/{conversation_id}/read", status_code=204)
async def mark_read(
    conversation_id: int,
    scope: TenantScope = Depends(tenant),
    db: AsyncSession = Depends(get_db),
) -> Response:
    conversation = await load_conversation(db, scope, conversation_id)
    conversation.agent_last_read_at = datetime.now(timezone.utc)
    db.add(conversation)
    await db.commit()
    return Response(status_code=204)


@router.post("/{conversation_id}/takeover", response_model=ConversationDetail)
async def takeover(
    conversation_id: int,
    scope: TenantScope = Depends(tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationDetail:
    conversation = await load_conversation(db, scope, conversation_id)
    if conversation.assignee_id not in (None, scope.user.id):
        holder = await db.get(User, conversation.assignee_id)
        name = holder.name if holder is not None else "another agent"
        raise HTTPException(
            status_code=409, detail=f"{name} is already handling this conversation"
        )
    conversation.handoff_state = HandoffState.HUMAN
    conversation.assignee_id = scope.user.id
    conversation.bot_muted_until = None
    db.add(conversation)
    await db.commit()
    return await get_conversation(conversation_id, scope, db)


@router.post("/{conversation_id}/release", response_model=ConversationDetail)
async def release(
    conversation_id: int,
    scope: TenantScope = Depends(tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationDetail:
    conversation = await load_conversation(db, scope, conversation_id)
    conversation.handoff_state = HandoffState.BOT
    conversation.assignee_id = None
    conversation.escalation_reason = None
    conversation.bot_muted_until = datetime.now(timezone.utc) + timedelta(
        seconds=settings.BOT_MUTE_AFTER_RELEASE_SECONDS
    )
    db.add(conversation)
    await db.commit()
    return await get_conversation(conversation_id, scope, db)


@router.post("/{conversation_id}/resolve", response_model=ConversationDetail)
async def resolve(
    conversation_id: int,
    scope: TenantScope = Depends(tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationDetail:
    conversation = await load_conversation(db, scope, conversation_id)
    conversation.handoff_state = HandoffState.RESOLVED
    conversation.assignee_id = None
    db.add(conversation)
    await db.commit()
    return await get_conversation(conversation_id, scope, db)


class SendRequest(BaseModel):
    text: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("a reply needs something in it")
        return value


def send_limiter():
    return default_limiter()


@router.post(
    "/{conversation_id}/messages", status_code=201, response_model=MessageOut
)
async def send_message(
    conversation_id: int,
    body: SendRequest,
    scope: TenantScope = Depends(tenant),
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    conversation = await load_conversation(db, scope, conversation_id)
    if conversation.handoff_state is not HandoffState.HUMAN:
        raise HTTPException(
            status_code=409, detail="take the conversation over before replying"
        )
    if conversation.assignee_id != scope.user.id:
        raise HTTPException(
            status_code=409, detail="another agent is handling this conversation"
        )

    connection = await db.get(ChannelConnection, conversation.channel_connection_id)
    try:
        adapter = build_adapter(connection)
    except (MissingCredentials, UnknownProvider) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"channel connection {conversation.channel_connection_id} cannot send: {exc}",
        ) from None

    dispatcher = OutboundDispatcher(
        adapter,
        limiter=send_limiter(),
        max_attempts=settings.OUTBOUND_MAX_ATTEMPTS,
    )
    outcome = await dispatcher.dispatch(
        connection,
        DraftReply(text=body.text),
        last_inbound_at=conversation.last_inbound_at,
        external_thread_id=conversation.external_thread_id,
    )
    if outcome.escalated:
        raise HTTPException(status_code=409, detail=outcome.reason)

    message = record_outbound(
        db,
        conversation,
        body.text,
        [],
        outcome,
        SenderType.AGENT,
        sender_user_id=scope.user.id,
    )
    if outcome.permanent_failure:
        db.add(
            FailedJob(
                kind="outbound",
                connection_id=connection.id,
                payload={
                    "conversation_id": conversation.id,
                    "sender_user_id": scope.user.id,
                },
                error=outcome.permanent_failure,
                attempts=1,
            )
        )
    await db.commit()
    return MessageOut(
        id=message.id,
        direction=message.direction,
        sender_type=message.sender_type,
        sender=UserRef(id=scope.user.id, name=scope.user.name),
        text=message.text,
        attachments=message.attachments,
        provider_message_id=message.provider_message_id,
        delivery_status=message.delivery_status,
        error=message.error,
        created_at=message.created_at,
    )
