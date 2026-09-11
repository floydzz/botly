"""Merchant credits, usage accounting, model catalog and connection-scoped dedupe.

Revision ID: 9d10a0010001
Revises: c37e229a7075
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "9d10a0010001"
down_revision = "c37e229a7075"
branch_labels = None
depends_on = None


def timestamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False)]


def upgrade():
    op.create_table("llm_models", *timestamps(),
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model_code", sa.String(191), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("input_usd_per_million", sa.Numeric(20, 10), nullable=False),
        sa.Column("output_usd_per_million", sa.Numeric(20, 10), nullable=False),
        sa.Column("cached_usd_per_million", sa.Numeric(20, 10), nullable=False),
        sa.Column("cache_write_usd_per_million", sa.Numeric(20, 10), nullable=False),
        sa.Column("multiplier", sa.Numeric(12, 6), nullable=False),
        sa.Column("max_input_tokens", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.UniqueConstraint("provider", "model_code", name="uq_llm_model_provider_code"),
        sa.CheckConstraint("input_usd_per_million >= 0 AND output_usd_per_million >= 0 AND cached_usd_per_million >= 0 AND cache_write_usd_per_million >= 0", name="ck_llm_prices"),
        sa.CheckConstraint("multiplier >= 1 AND max_input_tokens > 0 AND max_output_tokens > 0", name="ck_llm_limits"),
    )
    op.add_column("bots", sa.Column("llm_model_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("fk_bots_llm_model_id", "bots", "llm_models", ["llm_model_id"], ["id"])
    op.create_table("credit_wallets", *timestamps(),
        sa.Column("merchant_id", sa.BigInteger(), sa.ForeignKey("merchants.id"), primary_key=True),
        sa.Column("balance", sa.Numeric(24, 6), nullable=False, server_default="0"),
        sa.Column("reserved", sa.Numeric(24, 6), nullable=False, server_default="0"),
        sa.CheckConstraint("balance >= 0 AND reserved >= 0 AND reserved <= balance", name="ck_wallet_funds"),
    )
    op.create_table("llm_usage", *timestamps(),
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("merchant_id", sa.BigInteger(), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("bot_id", sa.BigInteger(), sa.ForeignKey("bots.id"), nullable=False),
        sa.Column("inbound_event_id", sa.BigInteger(), sa.ForeignKey("inbound_events.id"), nullable=False),
        sa.Column("update_id", sa.String(191), nullable=False),
        sa.Column("model_id", sa.BigInteger(), sa.ForeignKey("llm_models.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("pricing", postgresql.JSONB(), nullable=False),
        sa.Column("reserved_credits", sa.Numeric(24, 6), nullable=False),
        sa.Column("charged_credits", sa.Numeric(24, 6), nullable=False, server_default="0"),
        sa.Column("provider_cost_usd", sa.Numeric(24, 12)),
        sa.Column("input_tokens", sa.BigInteger()),
        sa.Column("output_tokens", sa.BigInteger()),
        sa.Column("cached_tokens", sa.BigInteger()),
        sa.Column("cache_write_tokens", sa.BigInteger()),
        sa.Column("raw_usage", postgresql.JSONB()),
        sa.Column("provider_request_id", sa.String(255)),
        sa.Column("response_text", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.UniqueConstraint("inbound_event_id", "update_id", name="uq_llm_usage_event_update"),
    )
    op.create_index("ix_llm_usage_merchant_id", "llm_usage", ["merchant_id"])
    op.create_index("ix_llm_usage_status", "llm_usage", ["status"])
    op.create_table("credit_entries", *timestamps(),
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("merchant_id", sa.BigInteger(), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("reference", sa.String(191), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("amount", sa.Numeric(24, 6), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.UniqueConstraint("merchant_id", "reference", name="uq_credit_entry_reference"),
    )
    op.create_index("ix_credit_entries_merchant_id", "credit_entries", ["merchant_id"])
    op.drop_constraint("uq_inbound_events_dedupe", "inbound_events", type_="unique")
    op.create_unique_constraint("uq_inbound_events_dedupe", "inbound_events", ["connection_id", "provider", "provider_update_id"])


def downgrade():
    # Restoring the old constraint can fail if separate bots share update IDs.
    # Deliberately fail rather than delete events to make downgrade succeed.
    op.drop_constraint("uq_inbound_events_dedupe", "inbound_events", type_="unique")
    op.create_unique_constraint("uq_inbound_events_dedupe", "inbound_events", ["provider", "provider_update_id"])
    op.drop_table("credit_entries")
    op.drop_table("llm_usage")
    op.drop_table("credit_wallets")
    op.drop_constraint("fk_bots_llm_model_id", "bots", type_="foreignkey")
    op.drop_column("bots", "llm_model_id")
    op.drop_table("llm_models")
