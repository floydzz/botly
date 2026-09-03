import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

import app.models  # noqa: F401
from app.core.config import settings

pytestmark = pytest.mark.integration


def test_there_is_exactly_one_head():
    """Two heads mean two branches of history and a merge nobody noticed."""

    script = ScriptDirectory.from_config(Config("alembic.ini"))

    assert len(script.get_heads()) == 1


async def test_migrations_produce_the_same_schema_as_the_models():
    """The drift guard.

    A model edited without a migration passes every other test in this suite --
    the test harness builds its schema from metadata -- and then fails on
    deploy. This is the only test that would notice.
    """

    from alembic import command

    engine = create_async_engine(settings.TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", settings.TEST_DATABASE_URL)

    def _upgrade_and_diff(sync_conn):
        cfg.attributes["connection"] = sync_conn
        command.upgrade(cfg, "head")
        context = MigrationContext.configure(sync_conn, opts={"compare_type": True})
        return compare_metadata(context, SQLModel.metadata)

    async with engine.begin() as conn:
        diff = await conn.run_sync(_upgrade_and_diff)
    await engine.dispose()

    assert diff == [], f"models and migrations disagree: {diff}"
