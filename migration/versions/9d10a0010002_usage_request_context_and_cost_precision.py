"""Preserve usage request context and provider-cost precision.

Revision ID: 9d10a0010002
Revises: 9d10a0010001
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "9d10a0010002"
down_revision = "9d10a0010001"
branch_labels = None
depends_on = None


def upgrade():
    # Some development databases ran the unpublished first revision while it
    # briefly contained these fields. Inspecting makes that local upgrade safe;
    # released databases and fresh installs still take the normal DDL path.
    columns = {column["name"]: column for column in sa.inspect(op.get_bind()).get_columns("llm_usage")}
    if "request_context" not in columns:
        op.add_column(
            "llm_usage",
            sa.Column(
                "request_context",
                postgresql.JSONB(),
                nullable=False,
                server_default="{}",
            ),
        )
    cost_type = columns["provider_cost_usd"]["type"]
    if cost_type.precision != 30 or cost_type.scale != 16:
        op.alter_column(
            "llm_usage",
            "provider_cost_usd",
            existing_type=cost_type,
            type_=sa.Numeric(30, 16),
            existing_nullable=True,
        )


def downgrade():
    op.alter_column(
        "llm_usage",
        "provider_cost_usd",
        existing_type=sa.Numeric(30, 16),
        type_=sa.Numeric(24, 12),
        existing_nullable=True,
    )
    op.drop_column("llm_usage", "request_context")
