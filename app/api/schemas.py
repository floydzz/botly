"""Shared inbox response shapes."""

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel

from app.api.send_policy import SendPolicy
from app.models.conversation import HandoffState
from app.models.message import DeliveryStatus, Direction, SenderType

T = TypeVar("T")


class UserRef(BaseModel):
    id: int
    name: str


class BotRef(BaseModel):
    id: int
    name: str


class ConversationSummary(BaseModel):
    id: int
    customer_name: str | None
    customer_ref: str
    provider: str
    connection_id: int
    bot: BotRef
    handoff_state: HandoffState
    escalation_reason: str | None
    assignee: UserRef | None
    last_message_at: datetime | None
    last_message_preview: str | None
    unread: bool
    has_failed_delivery: bool


class ConversationDetail(ConversationSummary):
    send_policy: SendPolicy


class MessageOut(BaseModel):
    id: int
    direction: Direction
    sender_type: SenderType
    sender: UserRef | None
    text: str | None
    attachments: list
    provider_message_id: str | None
    delivery_status: DeliveryStatus
    error: str | None
    created_at: datetime


class ConversationCounts(BaseModel):
    all: int
    needs_attention: int
    mine: int
    unread: int
    resolved: int


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
