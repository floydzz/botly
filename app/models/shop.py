from sqlalchemy import BigInteger, Column, ForeignKey, String, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import SoftDeleteMixin, TimestampMixin


class Shop(TimestampMixin, SoftDeleteMixin, SQLModel, table=True):
    """A Shopee shop or a brand.

    Separate from Merchant because commerce credentials belong to the shop: one
    merchant may run several shops, each with its own Shopee authorisation.
    """

    __tablename__ = "shops"
    __table_args__ = (
        UniqueConstraint("platform", "external_shop_id", name="uq_shops_platform_external_id"),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    merchant_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("merchants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    name: str = Field(sa_column=Column(String(255), nullable=False))
    # "shopee", "standalone", ... A plain string, not an enum: adding a
    # commerce platform must not require a migration.
    platform: str = Field(sa_column=Column(String(32), nullable=False))
    external_shop_id: str | None = Field(
        default=None, sa_column=Column(String(128), nullable=True)
    )
