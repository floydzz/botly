"""Persistent configuration and audit records for the manager graph."""

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import EnumString, TimestampMixin, utcnow


class WorkerKey(str, Enum):
    RAG = "rag"
    OCR = "ocr"
    VOICE = "voice"
    TOOLS = "tools"


class ToolWriteMode(str, Enum):
    CONFIRM_CUSTOMER = "confirm_customer"
    AUTO_EXECUTE = "auto_execute"


class PendingToolActionStatus(str, Enum):
    COLLECTING_INPUT = "collecting_input"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    EXECUTING = "executing"
    COMPLETED = "completed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"


class LlmRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    AWAITING_CUSTOMER = "awaiting_customer"
    ESCALATED = "escalated"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class WorkerDefinition(TimestampMixin, SQLModel, table=True):
    """The fixed catalog of worker implementations registered by the app."""

    __tablename__ = "worker_definitions"
    __table_args__ = (UniqueConstraint("key", name="uq_worker_definitions_key"),)

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True))
    key: WorkerKey = Field(sa_column=Column(EnumString(WorkerKey, 32), nullable=False))
    name: str = Field(sa_column=Column(String(128), nullable=False))
    description: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))


class BotWorker(TimestampMixin, SQLModel, table=True):
    """One bot's enablement and safe configuration for one worker."""

    __tablename__ = "bot_workers"
    __table_args__ = (
        UniqueConstraint("bot_id", "worker_definition_id", name="uq_bot_workers_bot_worker"),
    )

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True))
    bot_id: int = Field(sa_column=Column(BigInteger, ForeignKey("bots.id", ondelete="CASCADE"), nullable=False, index=True))
    worker_definition_id: int = Field(sa_column=Column(BigInteger, ForeignKey("worker_definitions.id", ondelete="CASCADE"), nullable=False))
    enabled: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default="false"))
    config: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False, server_default="{}"))


class ToolDefinition(TimestampMixin, SQLModel, table=True):
    """A merchant-owned API action definition. Credentials stay out of this row."""

    __tablename__ = "tool_definitions"
    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True))
    merchant_id: int = Field(sa_column=Column(BigInteger, ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True))
    name: str = Field(sa_column=Column(String(128), nullable=False))
    description: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    endpoint: str = Field(sa_column=Column(String(2048), nullable=False))
    method: str = Field(default="GET", sa_column=Column(String(12), nullable=False, server_default="GET"))
    input_schema: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False, server_default="{}"))
    enabled: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, server_default="true"))


class PendingToolAction(TimestampMixin, SQLModel, table=True):
    """Durable, channel-neutral state while a tool request needs customer input."""

    __tablename__ = "pending_tool_actions"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True))
    merchant_id: int = Field(sa_column=Column(BigInteger, ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True))
    bot_id: int = Field(sa_column=Column(BigInteger, ForeignKey("bots.id", ondelete="CASCADE"), nullable=False))
    conversation_id: int = Field(sa_column=Column(BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True))
    status: PendingToolActionStatus = Field(default=PendingToolActionStatus.COLLECTING_INPUT, sa_column=Column(EnumString(PendingToolActionStatus, 32), nullable=False, index=True))
    intent: str = Field(sa_column=Column(String(128), nullable=False))
    tool_name: str | None = Field(default=None, sa_column=Column(String(191), nullable=True))
    required_fields: list[str] = Field(default_factory=list, sa_column=Column(JSONB, nullable=False, server_default="[]"))
    collected_fields: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False, server_default="{}"))
    proposed_arguments: dict | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    next_question: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    confirmation_required: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, server_default="true"))
    idempotency_key: str = Field(sa_column=Column(String(191), nullable=False, unique=True))
    result: dict | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    expires_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True), nullable=True)


class LlmRun(SQLModel, table=True):
    """One complete manager turn, partitioned by its creation month."""

    __tablename__ = "llm_runs"
    __table_args__ = {"postgresql_partition_by": "RANGE (created_at)"}

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    # A partitioned PostgreSQL table must include its partition key in every
    # unique/primary constraint. Together these identify the run everywhere.
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True), primary_key=True))
    updated_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False, onupdate=utcnow))
    merchant_id: int = Field(sa_column=Column(BigInteger, ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True))
    bot_id: int = Field(sa_column=Column(BigInteger, ForeignKey("bots.id", ondelete="CASCADE"), nullable=False))
    conversation_id: int = Field(sa_column=Column(BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True))
    source_message_id: int = Field(sa_column=Column(BigInteger, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True))
    status: LlmRunStatus = Field(default=LlmRunStatus.RUNNING, sa_column=Column(EnumString(LlmRunStatus, 32), nullable=False, index=True))
    final_response: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    selected_workers: list[str] = Field(default_factory=list, sa_column=Column(JSONB, nullable=False, server_default="[]"))
    event_count_total: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default="0"))
    event_count_persisted: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default="0"))
    event_count_dropped: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default="0"))
    event_summary: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    total_input_tokens: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default="0"))
    total_output_tokens: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default="0"))
    total_cost: str = Field(default="0", sa_column=Column(String(64), nullable=False, server_default="0"))
    finished_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True), nullable=True)


class LlmRunEvent(SQLModel, table=True):
    """The retained, priority-selected trace events for one manager turn."""

    __tablename__ = "llm_run_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "run_created_at"],
            ["llm_runs.id", "llm_runs.created_at"],
            name="fk_llm_run_events_run",
            ondelete="CASCADE",
        ),
        UniqueConstraint("run_id", "run_created_at", "sequence_number", "created_at", name="uq_llm_run_event_sequence"),
        CheckConstraint("sequence_number BETWEEN 1 AND 20", name="ck_llm_run_event_sequence"),
        {"postgresql_partition_by": "RANGE (created_at)"},
    )

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    # Stored in the run's partition to make the per-run sequence constraint
    # enforceable on PostgreSQL partitioned tables.
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), primary_key=True))
    updated_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False, onupdate=utcnow))
    run_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    run_created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    sequence_number: int = Field(sa_column=Column(Integer, nullable=False))
    occurred_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True), nullable=False)
    event_type: str = Field(sa_column=Column(String(128), nullable=False))
    worker_key: str | None = Field(default=None, sa_column=Column(String(32), nullable=True))
    priority: int = Field(sa_column=Column(Integer, nullable=False))
    input_summary: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    output_summary: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    metadata_json: dict = Field(default_factory=dict, sa_column=Column("metadata", JSONB, nullable=False, server_default="{}"))
