"""Platform model catalog and merchant accounting. Amounts are Decimal, never float."""

from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin


class LlmModel(TimestampMixin, SQLModel, table=True):
    __tablename__ = "llm_models"
    __table_args__ = (
        UniqueConstraint("provider", "model_code", name="uq_llm_model_provider_code"),
        CheckConstraint("input_usd_per_million >= 0 AND output_usd_per_million >= 0 AND cached_usd_per_million >= 0 AND cache_write_usd_per_million >= 0", name="ck_llm_prices"),
        CheckConstraint("multiplier >= 1 AND max_input_tokens > 0 AND max_output_tokens > 0", name="ck_llm_limits"),
    )
    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True))
    provider: str = Field(sa_column=Column(String(32), nullable=False))
    model_code: str = Field(sa_column=Column(String(191), nullable=False))
    name: str = Field(sa_column=Column(String(255), nullable=False))
    enabled: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default="false"))
    input_usd_per_million: Decimal = Field(sa_column=Column(Numeric(20, 10), nullable=False))
    output_usd_per_million: Decimal = Field(sa_column=Column(Numeric(20, 10), nullable=False))
    cached_usd_per_million: Decimal = Field(sa_column=Column(Numeric(20, 10), nullable=False))
    cache_write_usd_per_million: Decimal = Field(sa_column=Column(Numeric(20, 10), nullable=False))
    multiplier: Decimal = Field(sa_column=Column(Numeric(12, 6), nullable=False))
    max_input_tokens: int = Field(default=8192, sa_column=Column(Integer, nullable=False))
    max_output_tokens: int = Field(default=1024, sa_column=Column(Integer, nullable=False))


class CreditWallet(TimestampMixin, SQLModel, table=True):
    __tablename__ = "credit_wallets"
    __table_args__ = (CheckConstraint("balance >= 0 AND reserved >= 0 AND reserved <= balance", name="ck_wallet_funds"),)
    merchant_id: int = Field(sa_column=Column(BigInteger, ForeignKey("merchants.id"), primary_key=True))
    balance: Decimal = Field(default=Decimal(0), sa_column=Column(Numeric(24, 6), nullable=False, server_default="0"))
    reserved: Decimal = Field(default=Decimal(0), sa_column=Column(Numeric(24, 6), nullable=False, server_default="0"))


class LlmUsage(TimestampMixin, SQLModel, table=True):
    __tablename__ = "llm_usage"
    __table_args__ = (UniqueConstraint("inbound_event_id", "update_id", name="uq_llm_usage_event_update"),)
    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True))
    merchant_id: int = Field(sa_column=Column(BigInteger, ForeignKey("merchants.id"), nullable=False, index=True))
    bot_id: int = Field(sa_column=Column(BigInteger, ForeignKey("bots.id"), nullable=False))
    inbound_event_id: int = Field(sa_column=Column(BigInteger, ForeignKey("inbound_events.id"), nullable=False))
    update_id: str = Field(sa_column=Column(String(191), nullable=False))
    model_id: int = Field(sa_column=Column(BigInteger, ForeignKey("llm_models.id"), nullable=False))
    # reserved -> settled | released | uncertain. Never automatically repeat an uncertain call.
    status: str = Field(default="reserved", sa_column=Column(String(32), nullable=False, index=True))
    pricing: dict = Field(sa_column=Column(JSONB, nullable=False))
    request_context: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False, server_default="{}"))
    reserved_credits: Decimal = Field(sa_column=Column(Numeric(24, 6), nullable=False))
    charged_credits: Decimal = Field(default=Decimal(0), sa_column=Column(Numeric(24, 6), nullable=False, server_default="0"))
    provider_cost_usd: Decimal | None = Field(default=None, sa_column=Column(Numeric(30, 16)))
    input_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))
    output_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))
    cached_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))
    cache_write_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))
    raw_usage: dict | None = Field(default=None, sa_column=Column(JSONB))
    provider_request_id: str | None = Field(default=None, sa_column=Column(String(255)))
    response_text: str | None = Field(default=None, sa_column=Column(Text))
    error: str | None = Field(default=None, sa_column=Column(Text))


class CreditEntry(TimestampMixin, SQLModel, table=True):
    __tablename__ = "credit_entries"
    __table_args__ = (UniqueConstraint("merchant_id", "reference", name="uq_credit_entry_reference"),)
    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True))
    merchant_id: int = Field(sa_column=Column(BigInteger, ForeignKey("merchants.id"), nullable=False, index=True))
    reference: str = Field(sa_column=Column(String(191), nullable=False))
    kind: str = Field(sa_column=Column(String(32), nullable=False))
    amount: Decimal = Field(sa_column=Column(Numeric(24, 6), nullable=False))
    note: str = Field(sa_column=Column(Text, nullable=False))
