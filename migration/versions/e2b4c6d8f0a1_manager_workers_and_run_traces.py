"""manager workers, pending actions, and monthly LangGraph traces

Revision ID: e2b4c6d8f0a1
Revises: d7a3c8149b20
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "e2b4c6d8f0a1"
down_revision = "d7a3c8149b20"
branch_labels = None
depends_on = None


def _month_start(value: datetime) -> datetime:
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(value: datetime) -> datetime:
    if value.month == 12:
        return value.replace(year=value.year + 1, month=1)
    return value.replace(month=value.month + 1)


def _create_partitions(prefix: str) -> None:
    """Create this and next month's partitions for a fresh deployment."""
    month = _month_start(datetime.now(timezone.utc))
    for _ in range(2):
        next_month = _next_month(month)
        suffix = month.strftime("%Y_%m")
        op.execute(
            sa.text(
                f"CREATE TABLE {prefix}_{suffix} PARTITION OF {prefix} "
                f"FOR VALUES FROM ('{month.isoformat()}') TO ('{next_month.isoformat()}')"
            )
        )
        month = next_month


def upgrade():
    op.add_column(
        "bots",
        sa.Column(
            "tool_write_mode",
            sa.String(length=32),
            nullable=False,
            server_default="confirm_customer",
        ),
    )
    op.create_table(
        "worker_definitions",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint("key", name="uq_worker_definitions_key"),
    )
    workers = (
        ("rag", "Knowledge retrieval", "Searches the bot's approved knowledge sources."),
        ("ocr", "Document reader", "Extracts text from supported attachments."),
        ("voice", "Voice transcription", "Transcribes supported customer audio."),
        ("tools", "Customer tools", "Calls approved customer API actions."),
    )
    op.bulk_insert(
        sa.table(
            "worker_definitions",
            sa.column("key", sa.String()),
            sa.column("name", sa.String()),
            sa.column("description", sa.Text()),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        [{"key": key, "name": name, "description": description, "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)} for key, name, description in workers],
    )
    op.create_table(
        "bot_workers",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("bot_id", sa.BigInteger(), nullable=False),
        sa.Column("worker_definition_id", sa.BigInteger(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["worker_definition_id"], ["worker_definitions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("bot_id", "worker_definition_id", name="uq_bot_workers_bot_worker"),
    )
    op.create_index("ix_bot_workers_bot_id", "bot_workers", ["bot_id"])
    op.create_table(
        "pending_tool_actions",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("merchant_id", sa.BigInteger(), nullable=False),
        sa.Column("bot_id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("intent", sa.String(length=128), nullable=False),
        sa.Column("tool_name", sa.String(length=191)),
        sa.Column("required_fields", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("collected_fields", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("proposed_arguments", postgresql.JSONB()),
        sa.Column("next_question", sa.Text()),
        sa.Column("confirmation_required", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("idempotency_key", sa.String(length=191), nullable=False, unique=True),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("error", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_pending_tool_actions_merchant_id", "pending_tool_actions", ["merchant_id"])
    op.create_index("ix_pending_tool_actions_conversation_id", "pending_tool_actions", ["conversation_id"])
    op.create_index("ix_pending_tool_actions_status", "pending_tool_actions", ["status"])
    op.create_table(
        "llm_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("merchant_id", sa.BigInteger(), nullable=False),
        sa.Column("bot_id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("source_message_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("final_response", sa.Text()),
        sa.Column("selected_workers", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("event_count_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("event_count_persisted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("event_count_dropped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("event_summary", sa.Text()),
        sa.Column("total_input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_output_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_cost", sa.String(length=64), nullable=False, server_default="0"),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", "created_at"),
        postgresql_partition_by="RANGE (created_at)",
    )
    op.create_index("ix_llm_runs_merchant_id", "llm_runs", ["merchant_id"])
    op.create_index("ix_llm_runs_conversation_id", "llm_runs", ["conversation_id"])
    op.create_index("ix_llm_runs_source_message_id", "llm_runs", ["source_message_id"])
    op.create_index("ix_llm_runs_status", "llm_runs", ["status"])
    op.create_table(
        "llm_run_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("run_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("worker_key", sa.String(length=32)),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("input_summary", sa.Text()),
        sa.Column("output_summary", sa.Text()),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.CheckConstraint("sequence_number BETWEEN 1 AND 20", name="ck_llm_run_event_sequence"),
        sa.ForeignKeyConstraint(
            ["run_id", "run_created_at"],
            ["llm_runs.id", "llm_runs.created_at"],
            name="fk_llm_run_events_run",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", "created_at"),
        sa.UniqueConstraint("run_id", "run_created_at", "sequence_number", "created_at", name="uq_llm_run_event_sequence"),
        postgresql_partition_by="RANGE (created_at)",
    )
    op.create_index("ix_llm_run_events_run_id", "llm_run_events", ["run_id"])
    _create_partitions("llm_runs")
    _create_partitions("llm_run_events")


def downgrade():
    # Parent tables may have partitions from months after this migration was
    # applied. CASCADE removes all of them, rather than assuming two months.
    op.execute("DROP TABLE llm_run_events CASCADE")
    op.execute("DROP TABLE llm_runs CASCADE")
    op.drop_index("ix_pending_tool_actions_status", table_name="pending_tool_actions")
    op.drop_index("ix_pending_tool_actions_conversation_id", table_name="pending_tool_actions")
    op.drop_index("ix_pending_tool_actions_merchant_id", table_name="pending_tool_actions")
    op.drop_table("pending_tool_actions")
    op.drop_index("ix_bot_workers_bot_id", table_name="bot_workers")
    op.drop_table("bot_workers")
    op.drop_table("worker_definitions")
    op.drop_column("bots", "tool_write_mode")
