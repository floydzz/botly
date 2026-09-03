import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import app.models  # noqa: F401  -- registers every table on SQLModel.metadata
from app.core.config import settings


@pytest.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(settings.TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine) -> AsyncSession:
    """A session whose work is always rolled back.

    The outer transaction is owned by the fixture, not the test, so a test that
    calls ``session.commit()`` commits only to the savepoint and still leaves
    the database as it found it.
    """

    async with test_engine.connect() as connection:
        transaction = await connection.begin()
        maker = async_sessionmaker(
            bind=connection,
            class_=AsyncSession,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        async with maker() as session:
            yield session
        await transaction.rollback()
