"""Connection-scoped receipts and queue publication tracking."""
from alembic import op
import sqlalchemy as sa

revision = "d7a3c8149b20"
down_revision = "c37e229a7075"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("uq_inbound_events_dedupe", "inbound_events", type_="unique")
    op.create_unique_constraint("uq_inbound_events_dedupe", "inbound_events",
                                ["connection_id", "provider", "provider_update_id"])
    op.add_column("inbound_events", sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    # Fails safely if multiple connections now share an update ID.
    op.drop_column("inbound_events", "enqueued_at")
    op.drop_constraint("uq_inbound_events_dedupe", "inbound_events", type_="unique")
    op.create_unique_constraint("uq_inbound_events_dedupe", "inbound_events",
                                ["provider", "provider_update_id"])
