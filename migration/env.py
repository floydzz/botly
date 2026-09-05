import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlmodel import SQLModel

import app.models  # noqa: F401  -- registers every table on SQLModel.metadata
from app.core.config import settings
from app.models.base import EnumString

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def _render_item(type_, obj, autogen_context):
    """Render our TypeDecorators as the plain types they actually are.

    A migration describes the database, not the Python layer in front of it.
    EnumString is a VARCHAR with an Enum on the Python side, so emitting
    ``app.models.base.EnumString(length=32)`` both requires an import alembic
    does not write and pins the migration to a class that may move. The DDL is
    identical either way.
    """
    if type_ == "type" and isinstance(obj, EnumString):
        return f"sa.String(length={obj.length})"
    return False


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Without this, a column type change autogenerates as nothing and the
        # schema silently drifts from the models.
        compare_type=True,
        compare_server_default=True,
        render_item=_render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_run_migrations)
    await connectable.dispose()


# A connection passed in by a caller (the drift test) wins: opening a second
# engine there would deadlock against the transaction it already holds.
existing_connection = config.attributes.get("connection")
if existing_connection is not None:
    _run_migrations(existing_connection)
elif context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
