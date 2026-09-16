"""Connection-scoped receipts and queue publication tracking."""
from alembic import op
import sqlalchemy as sa

revision = "d7a3c8149b20"
# The current migration chain already scopes receipt deduplication by
# connection. This migration only records successful queue publication.
down_revision = "9d10a0010002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "inbound_events",
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("inbound_events", "enqueued_at")
