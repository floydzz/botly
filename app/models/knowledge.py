"""Knowledge-base source records; Qdrant holds the derived vectors."""

from enum import Enum

from sqlalchemy import BigInteger, Column, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import EnumString, TimestampMixin


class KnowledgeDocumentStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class KnowledgeDocument(TimestampMixin, SQLModel, table=True):
    __tablename__ = "knowledge_documents"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True))
    merchant_id: int = Field(sa_column=Column(BigInteger, ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True))
    brand_id: int = Field(sa_column=Column(BigInteger, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False, index=True))
    bot_id: int = Field(sa_column=Column(BigInteger, ForeignKey("bots.id", ondelete="CASCADE"), nullable=False, index=True))
    filename: str = Field(sa_column=Column(String(255), nullable=False))
    media_type: str = Field(default="application/octet-stream", sa_column=Column(String(127), nullable=False))
    storage_key: str = Field(sa_column=Column(String(512), nullable=False, unique=True))
    sha256: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    status: KnowledgeDocumentStatus = Field(default=KnowledgeDocumentStatus.QUEUED, sa_column=Column(EnumString(KnowledgeDocumentStatus, 32), nullable=False, index=True))
    embedding_model: str = Field(sa_column=Column(String(128), nullable=False))
    chunk_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default="0"))
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    metadata_json: dict = Field(default_factory=dict, sa_column=Column("metadata", JSONB, nullable=False, server_default="{}"))


class KnowledgeChunk(TimestampMixin, SQLModel, table=True):
    __tablename__ = "knowledge_chunks"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True))
    document_id: int = Field(sa_column=Column(BigInteger, ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True))
    ordinal: int = Field(sa_column=Column(Integer, nullable=False))
    qdrant_point_id: str = Field(sa_column=Column(String(36), nullable=False, unique=True))
    text: str = Field(sa_column=Column(Text, nullable=False))
    character_count: int = Field(sa_column=Column(Integer, nullable=False))
