from sqlalchemy import BigInteger, Column, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import SoftDeleteMixin, TimestampMixin


class Bot(TimestampMixin, SoftDeleteMixin, SQLModel, table=True):
    """Persona + knowledge base + enabled tools. There is no flow graph: the
    spec cuts the visual flow builder from v1 deliberately."""

    __tablename__ = "bots"

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    shop_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("shops.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    name: str = Field(sa_column=Column(String(255), nullable=False))
    persona: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    llm_provider: str = Field(
        default="anthropic",
        sa_column=Column(String(64), nullable=False, server_default="anthropic"),
    )
    enabled_tools: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
    )
    # How many replies the bot may make to an unresolved question before the
    # conversation goes to a person. Per bot because a bot answering delivery
    # questions can afford more attempts than one handling complaints.
    escalation_max_bot_turns: int = Field(
        default=3, sa_column=Column(Integer, nullable=False, server_default="3")
    )
