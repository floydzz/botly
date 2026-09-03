import pytest
from sqlalchemy import text


@pytest.mark.integration
async def test_session_talks_to_postgres_with_pgvector_available(db_session):
    version = (await db_session.execute(text("SHOW server_version_num"))).scalar_one()
    assert int(version) >= 170000, "spec pins PostgreSQL 17"

    available = (
        await db_session.execute(
            text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
        )
    ).scalar_one_or_none()
    assert available == 1, "pgvector must be installable; use pgvector/pgvector:pg17"
