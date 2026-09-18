"""rename shops to brands and add local knowledge sources

Revision ID: f30a9c7e2101
Revises: e2b4c6d8f0a1
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f30a9c7e2101"
down_revision = "e2b4c6d8f0a1"
branch_labels = None
depends_on = None


def upgrade():
    # Preserve every existing primary key and relationship while changing the
    # domain language. Historical migrations intentionally retain old names.
    op.rename_table("shops", "brands")
    op.alter_column("brands", "external_shop_id", new_column_name="external_brand_id")
    op.alter_column("bots", "shop_id", new_column_name="brand_id")
    op.execute("ALTER INDEX ix_shops_merchant_id RENAME TO ix_brands_merchant_id")
    op.execute("ALTER INDEX ix_bots_shop_id RENAME TO ix_bots_brand_id")
    op.execute("ALTER TABLE brands RENAME CONSTRAINT uq_shops_platform_external_id TO uq_brands_platform_external_id")
    op.add_column("bots", sa.Column("auditor_enabled", sa.Boolean(), nullable=False, server_default="false"))
    op.create_table(
        "knowledge_documents",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("merchant_id", sa.BigInteger(), nullable=False),
        sa.Column("brand_id", sa.BigInteger(), nullable=False),
        sa.Column("bot_id", sa.BigInteger(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(127), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False, unique=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("embedding_model", sa.String(128), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"], ondelete="CASCADE"),
    )
    for column in ("merchant_id", "brand_id", "bot_id", "sha256", "status"):
        op.create_index(f"ix_knowledge_documents_{column}", "knowledge_documents", [column])
    op.create_table(
        "knowledge_chunks",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("qdrant_point_id", sa.String(36), nullable=False, unique=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])
    op.create_table(
        "tool_definitions",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("merchant_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("endpoint", sa.String(2048), nullable=False),
        sa.Column("method", sa.String(12), nullable=False, server_default="GET"),
        sa.Column("input_schema", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_tool_definitions_merchant_id", "tool_definitions", ["merchant_id"])


def downgrade():
    op.drop_index("ix_tool_definitions_merchant_id", table_name="tool_definitions")
    op.drop_table("tool_definitions")
    op.drop_index("ix_knowledge_chunks_document_id", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    for column in ("status", "sha256", "bot_id", "brand_id", "merchant_id"):
        op.drop_index(f"ix_knowledge_documents_{column}", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
    op.drop_column("bots", "auditor_enabled")
    op.execute("ALTER TABLE brands RENAME CONSTRAINT uq_brands_platform_external_id TO uq_shops_platform_external_id")
    op.execute("ALTER INDEX ix_bots_brand_id RENAME TO ix_bots_shop_id")
    op.execute("ALTER INDEX ix_brands_merchant_id RENAME TO ix_shops_merchant_id")
    op.alter_column("bots", "brand_id", new_column_name="shop_id")
    op.alter_column("brands", "external_brand_id", new_column_name="external_shop_id")
    op.rename_table("brands", "shops")
