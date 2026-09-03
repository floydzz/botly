# botly Skeleton & Tenancy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the botly FastAPI skeleton with a PostgreSQL 17 + pgvector datastore, Alembic wired to SQLModel metadata, and the four tenancy tables (`Merchant → Shop → Bot → ChannelConnection`) with encrypted channel credentials.

**Architecture:** Modular monolith. `app/` is a single package: `core/` holds config, database, and crypto; `models/` holds SQLModel tables; `api/` holds routers. Async SQLAlchemy over `asyncpg`. Alembic autogenerates against `SQLModel.metadata`, so every model must be imported in `app/models/__init__.py` or it silently vanishes from migrations. Tests run against a real Postgres container — no SQLite substitute, because the schema uses `jsonb`, `vector`, and Postgres-specific defaults.

**Tech Stack:** Python 3.12, Poetry, FastAPI, SQLModel, SQLAlchemy 2 (asyncio) + asyncpg, Alembic, PostgreSQL 17 + pgvector, Redis, Celery, pytest + pytest-asyncio, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-02-botly-architecture-design.md`

## Global Constraints

- **Datastore is PostgreSQL 17 + pgvector.** Not MySQL, not Qdrant. Docker image: `pgvector/pgvector:pg17`.
- **Redis stays** for dedupe keys and token buckets; it is not the system of record.
- **Every external service sits behind a Protocol with a fake.** No test may touch the network.
- **No code outside `app/channels/<provider>/` may branch on a provider name.** This plan creates no adapters, but `ChannelConnection.provider` is a plain string column and nothing in `app/models/` or `app/core/` may switch on its value.
- **`ENVIRONMENT=production` gating fails hard.** Unsupported aliases (`prod`, `Production`) must not silently run in development mode. Ported verbatim in behaviour from `aib-backend/app/core/config.py::Settings.is_production`.
- **Timestamps are timezone-aware UTC everywhere.** `DateTime(timezone=True)` columns, `datetime.now(timezone.utc)` defaults. Never `datetime.utcnow`, never naive.
- **Tenancy IDs are `BigInteger` identity primary keys.**
- Commit after every task. Conventional-commit prefixes (`feat:`, `chore:`, `test:`).

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | Poetry project, dependencies, tool config |
| `pytest.ini` | pytest paths, asyncio mode, markers |
| `docker-compose.yml` | Postgres 17 + pgvector, Redis |
| `.env.example` | Every setting the app reads, with safe local values |
| `app/main.py` | FastAPI app factory, router registration, startup gate |
| `app/core/config.py` | `Settings` (pydantic-settings), `is_production`, fail-hard validation |
| `app/core/database.py` | Async engine, session factory, `get_db` dependency |
| `app/core/crypto.py` | Fernet encrypt/decrypt for channel credentials |
| `app/api/health.py` | `/healthz` router |
| `app/models/base.py` | `utcnow()`, `TimestampMixin`, `SoftDeleteMixin` |
| `app/models/merchant.py` | `Merchant` |
| `app/models/shop.py` | `Shop` |
| `app/models/bot.py` | `Bot` |
| `app/models/channel_connection.py` | `ChannelConnection`, `ChannelConnectionStatus` |
| `app/models/__init__.py` | Imports every model so `SQLModel.metadata` is complete |
| `migration/env.py` | Alembic async env bound to `SQLModel.metadata` |
| `alembic.ini` | Alembic config, `script_location = %(here)s/migration` |
| `test/conftest.py` | Test engine, per-test transaction rollback, schema creation |
| `test/test_config.py` | Production gating tests |
| `test/test_health.py` | `/healthz` test |
| `test/test_crypto.py` | Credential encryption tests |
| `test/test_tenancy_models.py` | Tenancy hierarchy, cascade, constraint tests |
| `test/test_migrations.py` | Migration-vs-models drift test |

---

### Task 1: Project skeleton, settings, and the production gate

**Files:**
- Create: `pyproject.toml`, `pytest.ini`, `docker-compose.yml`, `.env.example`, `app/__init__.py`, `app/core/__init__.py`, `app/core/config.py`, `test/__init__.py`
- Test: `test/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `app.core.config.Settings`, module-level `settings: Settings`, `Settings.is_production -> bool`, `Settings.DATABASE_URL: str`, `Settings.TEST_DATABASE_URL: str`, `Settings.REDIS_URL: str`, `Settings.CREDENTIALS_ENCRYPTION_KEY: str`, `Settings.ENVIRONMENT: str`, `Settings.SQL_ECHO: bool`.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[tool.poetry]
name = "botly"
version = "0.1.0"
description = "Multi-channel chatbot platform for Southeast Asian commerce sellers"
authors = []
readme = "README.md"
packages = [{include = "app"}]

[tool.poetry.dependencies]
python = "^3.12"
fastapi = "*"
uvicorn = {extras = ["standard"], version = "*"}
sqlmodel = "*"
sqlalchemy = {extras = ["asyncio"], version = "*"}
asyncpg = "*"
alembic = "*"
pgvector = "*"
redis = {extras = ["hiredis"], version = "*"}
celery = {extras = ["redis"], version = "*"}
pydantic = "^2"
pydantic-settings = "*"
cryptography = "*"
httpx = "*"
greenlet = "*"

[tool.poetry.group.dev.dependencies]
pytest = "*"
pytest-asyncio = "*"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

- [ ] **Step 2: Create `pytest.ini`**

```ini
[pytest]
pythonpath = .
testpaths = test
asyncio_mode = auto
markers =
    integration: requires the local Postgres container
```

- [ ] **Step 3: Create `docker-compose.yml`**

`pgvector/pgvector:pg17` is the Postgres image with the extension already built; plain `postgres:17` would need the extension compiled in. Port 5433 on the host so a house MySQL/Postgres from another project does not collide.

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_USER: botly
      POSTGRES_PASSWORD: botly
      POSTGRES_DB: botly
    ports:
      - "5433:5432"
    volumes:
      - botly_pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U botly"]
      interval: 5s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    ports:
      - "6380:6379"

volumes:
  botly_pgdata:
```

- [ ] **Step 4: Create `.env.example`**

```dotenv
ENVIRONMENT=development
SQL_ECHO=false
DATABASE_URL=postgresql+asyncpg://botly:botly@localhost:5433/botly
TEST_DATABASE_URL=postgresql+asyncpg://botly:botly@localhost:5433/botly_test
REDIS_URL=redis://localhost:6380/0
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
CREDENTIALS_ENCRYPTION_KEY=
```

- [ ] **Step 5: Create `.gitignore` additions and package markers**

```bash
cd /Users/floyd/Documents/botly
printf '.env\n__pycache__/\n*.pyc\n.pytest_cache/\n.venv/\n' >> .gitignore
mkdir -p app/core app/api app/models test
touch app/__init__.py app/core/__init__.py app/api/__init__.py test/__init__.py
```

- [ ] **Step 6: Write the failing test — `test/test_config.py`**

```python
import pytest

from app.core.config import Settings


def _settings(**overrides) -> Settings:
    base = {
        "ENVIRONMENT": "development",
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5433/botly",
        "CREDENTIALS_ENCRYPTION_KEY": "x" * 44,
    }
    base.update(overrides)
    return Settings(**base)


def test_production_is_exact_match():
    assert _settings(ENVIRONMENT="production").is_production is True


def test_production_tolerates_case_and_whitespace():
    assert _settings(ENVIRONMENT=" Production ").is_production is True


def test_prod_alias_is_rejected_at_construction():
    """An alias must fail loudly rather than quietly meaning "development".

    aib-backend answered "am I in production?" four different ways, so a deploy
    that set ENVIRONMENT=prod switched several security gates off at once and
    said nothing. Here the value itself is validated, so the alias never gets
    the chance to be misread downstream.
    """
    with pytest.raises(ValueError, match="ENVIRONMENT"):
        _settings(ENVIRONMENT="prod")


def test_development_is_not_production():
    assert _settings().is_production is False


def test_production_requires_an_encryption_key():
    with pytest.raises(ValueError, match="CREDENTIALS_ENCRYPTION_KEY"):
        _settings(ENVIRONMENT="production", CREDENTIALS_ENCRYPTION_KEY="")
```

- [ ] **Step 7: Run the test to verify it fails**

Run: `poetry run pytest test/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.config'`

- [ ] **Step 8: Write `app/core/config.py`**

```python
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The only spellings that mean anything. An unrecognised value is a
# configuration error, not a silent fallback to development.
_VALID_ENVIRONMENTS = ("development", "staging", "test", "production")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    ENVIRONMENT: str = "development"
    SQL_ECHO: bool = False

    DATABASE_URL: str = "postgresql+asyncpg://botly:botly@localhost:5433/botly"
    TEST_DATABASE_URL: str = (
        "postgresql+asyncpg://botly:botly@localhost:5433/botly_test"
    )
    REDIS_URL: str = "redis://localhost:6380/0"

    CREDENTIALS_ENCRYPTION_KEY: str = ""

    @property
    def is_production(self) -> bool:
        """The single place that decides what "production" means."""

        return self.ENVIRONMENT.strip().lower() == "production"

    @model_validator(mode="after")
    def _validate(self) -> "Settings":
        normalized = self.ENVIRONMENT.strip().lower()
        if normalized not in _VALID_ENVIRONMENTS:
            raise ValueError(
                f"ENVIRONMENT={self.ENVIRONMENT!r} is not one of "
                f"{_VALID_ENVIRONMENTS}. Aliases such as 'prod' are rejected "
                "so a misspelling cannot silently disable production gating."
            )
        if normalized == "production" and not self.CREDENTIALS_ENCRYPTION_KEY:
            raise ValueError(
                "CREDENTIALS_ENCRYPTION_KEY must be set in production; "
                "channel credentials are stored encrypted at rest."
            )
        return self


settings = Settings()
```

- [ ] **Step 9: Run the test to verify it passes**

Run: `poetry install && poetry run pytest test/test_config.py -v`
Expected: PASS — 5 passed

- [ ] **Step 10: Commit**

```bash
cd /Users/floyd/Documents/botly
git add pyproject.toml poetry.lock pytest.ini docker-compose.yml .env.example .gitignore app test
git commit -m "feat: project skeleton with settings and hard production gating"
```

---

### Task 2: FastAPI app and health endpoint

**Files:**
- Create: `app/main.py`, `app/api/health.py`
- Test: `test/test_health.py`

**Interfaces:**
- Consumes: `app.core.config.settings`.
- Produces: `app.main.create_app() -> FastAPI`, `app.main.app: FastAPI`, `app.api.health.router: APIRouter` serving `GET /healthz`.

- [ ] **Step 1: Write the failing test — `test/test_health.py`**

```python
from fastapi.testclient import TestClient

from app.main import create_app


def test_healthz_reports_ok_and_environment():
    client = TestClient(create_app())

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "development"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `poetry run pytest test/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Write `app/api/health.py`**

```python
from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness only. It must not touch Postgres or Redis: a health check that
    queries the database turns a slow database into a restart loop."""

    return {"status": "ok", "environment": settings.ENVIRONMENT}
```

- [ ] **Step 4: Write `app/main.py`**

```python
from fastapi import FastAPI

from app.api import health
from app.core.config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="botly",
        version="0.1.0",
        # No interactive docs in production: the schema names every route
        # before there is any auth in front of them.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
    )
    app.include_router(health.router)
    return app


app = create_app()
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `poetry run pytest test/test_health.py -v`
Expected: PASS — 1 passed

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/api/health.py test/test_health.py
git commit -m "feat: FastAPI app factory with health endpoint"
```

---

### Task 3: Database engine, session, and the real-Postgres test harness

**Files:**
- Create: `app/core/database.py`, `test/conftest.py`, `app/models/__init__.py`
- Test: `test/test_database.py`

**Interfaces:**
- Consumes: `app.core.config.settings`.
- Produces: `app.core.database.engine`, `app.core.database.AsyncSessionLocal`, `app.core.database.get_db()` (async generator yielding `AsyncSession`). Test fixtures: `db_session` (function-scoped `AsyncSession`, rolled back after each test), `test_engine` (session-scoped `AsyncEngine`).

- [ ] **Step 1: Start the database**

```bash
cd /Users/floyd/Documents/botly
docker compose up -d postgres redis
docker compose exec -T postgres psql -U botly -d botly -c "CREATE DATABASE botly_test;" || true
```

- [ ] **Step 2: Create the empty model registry — `app/models/__init__.py`**

Alembic autogenerate only sees tables whose classes have been imported. This file is that guarantee; every later task appends to it.

```python
"""Model registry.

Importing a model class is what registers its table on ``SQLModel.metadata``.
Alembic autogenerate reads that metadata, so a model missing from this file is
a model missing from every migration -- and the omission is silent.
"""

__all__: list[str] = []
```

- [ ] **Step 3: Write the failing test — `test/test_database.py`**

```python
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
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `poetry run pytest test/test_database.py -v`
Expected: FAIL — `fixture 'db_session' not found`

- [ ] **Step 5: Write `app/core/database.py`**

```python
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.SQL_ECHO,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
```

- [ ] **Step 6: Write `test/conftest.py`**

Each test runs inside a transaction that is rolled back, so tests share one schema without leaking rows into each other. The schema is built from metadata (fast); Task 6 tests the migrations separately.

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text
from sqlmodel import SQLModel

import app.models  # noqa: F401  -- registers every table on SQLModel.metadata
from app.core.config import settings


@pytest.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(settings.TEST_DATABASE_URL, poolclass=None)
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
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `poetry run pytest test/test_database.py -v`
Expected: PASS — 1 passed

- [ ] **Step 8: Commit**

```bash
git add app/core/database.py app/models/__init__.py test/conftest.py test/test_database.py
git commit -m "feat: async Postgres engine and rollback-per-test harness"
```

---

### Task 4: Credential encryption

**Files:**
- Create: `app/core/crypto.py`
- Test: `test/test_crypto.py`

**Interfaces:**
- Consumes: `app.core.config.settings.CREDENTIALS_ENCRYPTION_KEY`.
- Produces: `app.core.crypto.encrypt_credentials(payload: dict) -> str`, `app.core.crypto.decrypt_credentials(token: str) -> dict`. Both raise `CredentialsCryptoError` on a missing key or a token that fails authentication.

- [ ] **Step 1: Write the failing test — `test/test_crypto.py`**

```python
import pytest
from cryptography.fernet import Fernet

from app.core import crypto
from app.core.crypto import CredentialsCryptoError


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setattr(
        crypto.settings, "CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )


def test_roundtrip_preserves_the_payload():
    payload = {"bot_token": "123:ABC", "shop_id": 99}

    assert crypto.decrypt_credentials(crypto.encrypt_credentials(payload)) == payload


def test_ciphertext_does_not_contain_the_secret():
    token = crypto.encrypt_credentials({"bot_token": "123:ABC"})

    assert "123:ABC" not in token


def test_each_encryption_produces_a_distinct_token():
    payload = {"bot_token": "123:ABC"}

    assert crypto.encrypt_credentials(payload) != crypto.encrypt_credentials(payload)


def test_tampered_token_is_rejected_rather_than_decoded():
    token = crypto.encrypt_credentials({"bot_token": "123:ABC"})
    tampered = token[:-2] + ("AA" if not token.endswith("AA") else "BB")

    with pytest.raises(CredentialsCryptoError):
        crypto.decrypt_credentials(tampered)


def test_missing_key_fails_loudly(monkeypatch):
    monkeypatch.setattr(crypto.settings, "CREDENTIALS_ENCRYPTION_KEY", "")

    with pytest.raises(CredentialsCryptoError, match="CREDENTIALS_ENCRYPTION_KEY"):
        crypto.encrypt_credentials({"bot_token": "123:ABC"})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `poetry run pytest test/test_crypto.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.crypto'`

- [ ] **Step 3: Write `app/core/crypto.py`**

```python
import json

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class CredentialsCryptoError(RuntimeError):
    """Raised when credentials cannot be encrypted or trusted."""


def _cipher() -> Fernet:
    key = settings.CREDENTIALS_ENCRYPTION_KEY
    if not key:
        raise CredentialsCryptoError(
            "CREDENTIALS_ENCRYPTION_KEY is not set; refusing to handle channel "
            "credentials. Generate one with Fernet.generate_key()."
        )
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise CredentialsCryptoError(
            "CREDENTIALS_ENCRYPTION_KEY is not a valid Fernet key."
        ) from exc


def encrypt_credentials(payload: dict) -> str:
    """Encrypt a channel credential blob for storage.

    Fernet is authenticated, so a row edited in the database fails to decrypt
    instead of yielding attacker-chosen credentials that we then send to a
    provider.
    """

    return _cipher().encrypt(json.dumps(payload, sort_keys=True).encode()).decode()


def decrypt_credentials(token: str) -> dict:
    try:
        return json.loads(_cipher().decrypt(token.encode()))
    except InvalidToken as exc:
        raise CredentialsCryptoError(
            "Stored credentials failed authentication; they were tampered with "
            "or encrypted under a different key."
        ) from exc
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `poetry run pytest test/test_crypto.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: Commit**

```bash
git add app/core/crypto.py test/test_crypto.py
git commit -m "feat: authenticated encryption for channel credentials"
```

---

### Task 5: Tenancy models — Merchant, Shop, Bot, ChannelConnection

**Files:**
- Create: `app/models/base.py`, `app/models/merchant.py`, `app/models/shop.py`, `app/models/bot.py`, `app/models/channel_connection.py`
- Modify: `app/models/__init__.py`
- Test: `test/test_tenancy_models.py`

**Interfaces:**
- Consumes: `app.core.crypto.encrypt_credentials`, `app.core.crypto.decrypt_credentials`, the `db_session` fixture.
- Produces:
  - `app.models.base.utcnow() -> datetime`, `TimestampMixin` (`created_at`, `updated_at`), `SoftDeleteMixin` (`deleted_at`)
  - `Merchant(id, name, status, created_at, updated_at, deleted_at)`, table `merchants`
  - `Shop(id, merchant_id, name, platform, external_shop_id, created_at, updated_at, deleted_at)`, table `shops`
  - `Bot(id, shop_id, name, persona, llm_provider, enabled_tools, created_at, updated_at, deleted_at)`, table `bots`
  - `ChannelConnection(id, bot_id, provider, external_ref, credentials_encrypted, config, status, created_at, updated_at, deleted_at)`, table `channel_connections`; `ChannelConnectionStatus` enum with `ACTIVE`, `DEGRADED`, `DISCONNECTED`; methods `set_credentials(dict) -> None` and `get_credentials() -> dict`

- [ ] **Step 1: Write the failing test — `test/test_tenancy_models.py`**

```python
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core import crypto
from app.models import Bot, ChannelConnection, ChannelConnectionStatus, Merchant, Shop

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setattr(
        crypto.settings, "CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )


async def _hierarchy(db_session) -> ChannelConnection:
    merchant = Merchant(name="Kopi Co")
    db_session.add(merchant)
    await db_session.flush()

    shop = Shop(
        merchant_id=merchant.id,
        name="Kopi Co Official",
        platform="shopee",
        external_shop_id="112233",
    )
    db_session.add(shop)
    await db_session.flush()

    bot = Bot(shop_id=shop.id, name="Kopi Bot", persona="Friendly barista")
    db_session.add(bot)
    await db_session.flush()

    connection = ChannelConnection(bot_id=bot.id, provider="telegram", external_ref="botly_kopi_bot")
    connection.set_credentials({"bot_token": "123:ABC"})
    db_session.add(connection)
    await db_session.flush()
    return connection


async def test_full_hierarchy_persists(db_session):
    connection = await _hierarchy(db_session)

    assert connection.id is not None
    assert connection.status is ChannelConnectionStatus.DISCONNECTED


async def test_timestamps_are_timezone_aware_utc(db_session):
    merchant = Merchant(name="Tz Co")
    db_session.add(merchant)
    await db_session.flush()

    assert merchant.created_at.tzinfo is not None
    assert merchant.created_at.utcoffset().total_seconds() == 0


async def test_merchant_name_is_unique(db_session):
    db_session.add(Merchant(name="Dupe Co"))
    await db_session.flush()
    db_session.add(Merchant(name="Dupe Co"))

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_credentials_are_not_stored_in_plaintext(db_session):
    connection = await _hierarchy(db_session)

    stored = (
        await db_session.execute(
            text(
                "SELECT credentials_encrypted FROM channel_connections WHERE id = :id"
            ).bindparams(id=connection.id)
        )
    ).scalar_one()

    assert "123:ABC" not in stored
    assert connection.get_credentials() == {"bot_token": "123:ABC"}


async def test_one_provider_reference_cannot_be_connected_twice(db_session):
    """Two connections on the same provider ref would both receive the same
    webhook and answer the customer twice."""

    connection = await _hierarchy(db_session)
    duplicate = ChannelConnection(
        bot_id=connection.bot_id, provider="telegram", external_ref="botly_kopi_bot"
    )
    duplicate.set_credentials({"bot_token": "123:ABC"})
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_config_is_jsonb_and_queryable_by_path(db_session):
    """The spec chose Postgres for exactly this: querying into a payload field
    nobody anticipated must not require a migration."""

    connection = await _hierarchy(db_session)
    connection.config = {"webhook_secret_set": True, "locale": "ms-MY"}
    await db_session.flush()

    found = (
        await db_session.execute(
            text("SELECT id FROM channel_connections WHERE config ->> 'locale' = 'ms-MY'")
        )
    ).scalar_one()

    assert found == connection.id


async def test_deleting_a_merchant_cascades_to_its_channel_connections(db_session):
    connection = await _hierarchy(db_session)
    merchant = (await db_session.execute(select(Merchant))).scalars().first()

    await db_session.delete(merchant)
    await db_session.flush()

    remaining = (
        await db_session.execute(
            text("SELECT count(*) FROM channel_connections WHERE id = :id").bindparams(
                id=connection.id
            )
        )
    ).scalar_one()
    assert remaining == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `poetry run pytest test/test_tenancy_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'Bot' from 'app.models'`

- [ ] **Step 3: Write `app/models/base.py`**

```python
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime
from sqlmodel import Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    """Aware UTC on both columns.

    aib-backend mixed naive ``datetime.now`` defaults with aware UTC writes on
    update, so one row held two time bases and ``updated_at`` could sort before
    ``created_at``. One base, set here, for every table.
    """

    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, onupdate=utcnow),
    )


class SoftDeleteMixin:
    deleted_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
```

- [ ] **Step 4: Write `app/models/merchant.py`**

```python
from sqlalchemy import BigInteger, Column, String
from sqlmodel import Field, SQLModel

from app.models.base import SoftDeleteMixin, TimestampMixin


class Merchant(TimestampMixin, SoftDeleteMixin, SQLModel, table=True):
    """The billing tenant. Owns shops; holds no commerce credentials itself."""

    __tablename__ = "merchants"

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    name: str = Field(sa_column=Column(String(255), nullable=False, unique=True, index=True))
    status: str = Field(
        default="active",
        sa_column=Column(String(32), nullable=False, server_default="active"),
    )
```

- [ ] **Step 5: Write `app/models/shop.py`**

```python
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
```

- [ ] **Step 6: Write `app/models/bot.py`**

```python
from sqlalchemy import BigInteger, Column, ForeignKey, String, Text
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
```

- [ ] **Step 7: Write `app/models/channel_connection.py`**

```python
from enum import Enum

from sqlalchemy import BigInteger, Column, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.core.crypto import decrypt_credentials, encrypt_credentials
from app.models.base import SoftDeleteMixin, TimestampMixin


class ChannelConnectionStatus(str, Enum):
    ACTIVE = "active"
    # Credentials failed to refresh. The connection still exists and the inbox
    # still shows its history; sends are expected to fail until it is repaired.
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"


class ChannelConnection(TimestampMixin, SoftDeleteMixin, SQLModel, table=True):
    """One bot's presence on one channel.

    ``provider`` is a plain string and nothing outside ``app/channels/<provider>/``
    may branch on its value -- capability differences belong in the adapter's
    manifest, not in scattered conditionals.
    """

    __tablename__ = "channel_connections"
    __table_args__ = (
        UniqueConstraint(
            "provider", "external_ref", name="uq_channel_connections_provider_ref"
        ),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    bot_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("bots.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    provider: str = Field(sa_column=Column(String(32), nullable=False, index=True))
    # The provider's own identifier for this endpoint: a Telegram bot username,
    # a WhatsApp phone number id, a Shopee shop id.
    external_ref: str = Field(sa_column=Column(String(191), nullable=False))
    credentials_encrypted: str = Field(
        default="", sa_column=Column(Text, nullable=False, server_default="")
    )
    config: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False, server_default="{}")
    )
    status: ChannelConnectionStatus = Field(
        default=ChannelConnectionStatus.DISCONNECTED,
        sa_column=Column(String(32), nullable=False, server_default="disconnected"),
    )

    def set_credentials(self, payload: dict) -> None:
        self.credentials_encrypted = encrypt_credentials(payload)

    def get_credentials(self) -> dict:
        return decrypt_credentials(self.credentials_encrypted)
```

- [ ] **Step 8: Register the models in `app/models/__init__.py`**

```python
"""Model registry.

Importing a model class is what registers its table on ``SQLModel.metadata``.
Alembic autogenerate reads that metadata, so a model missing from this file is
a model missing from every migration -- and the omission is silent.
"""

from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection, ChannelConnectionStatus
from app.models.merchant import Merchant
from app.models.shop import Shop

__all__ = [
    "Bot",
    "ChannelConnection",
    "ChannelConnectionStatus",
    "Merchant",
    "Shop",
]
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `poetry run pytest test/test_tenancy_models.py -v`
Expected: PASS — 7 passed

- [ ] **Step 10: Run the whole suite**

Run: `poetry run pytest -v`
Expected: PASS — all tests pass

- [ ] **Step 11: Commit**

```bash
git add app/models test/test_tenancy_models.py
git commit -m "feat: tenancy models for merchant, shop, bot and channel connection"
```

---

### Task 6: Alembic wiring and the initial migration

**Files:**
- Create: `alembic.ini`, `migration/env.py`, `migration/script.py.mako`, `migration/versions/` (generated migration)
- Test: `test/test_migrations.py`

**Interfaces:**
- Consumes: `app.models` (metadata), `app.core.config.settings`.
- Produces: an Alembic environment whose `target_metadata` is `SQLModel.metadata`; one revision creating `merchants`, `shops`, `bots`, `channel_connections`.

- [ ] **Step 1: Initialize the Alembic scaffold**

`migration/` rather than `alembic/`, matching `aib-backend`'s layout.

```bash
cd /Users/floyd/Documents/botly
poetry run alembic init -t async migration
```

- [ ] **Step 2: Point `alembic.ini` at the scaffold and drop the hardcoded URL**

Edit `alembic.ini`: set `script_location = %(here)s/migration`, `prepend_sys_path = .`, and delete the `sqlalchemy.url = ...` line — the URL comes from settings so a migration can never run against a URL that disagrees with the app's.

```bash
cd /Users/floyd/Documents/botly
sed -i '' 's|^script_location = .*|script_location = %(here)s/migration|' alembic.ini
sed -i '' 's|^# prepend_sys_path = .*|prepend_sys_path = .|' alembic.ini
sed -i '' '/^sqlalchemy.url = /d' alembic.ini
```

- [ ] **Step 3: Replace `migration/env.py`**

```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlmodel import SQLModel

import app.models  # noqa: F401  -- registers every table on SQLModel.metadata
from app.core.config import settings

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Without this, a column type change autogenerates as nothing and the
        # schema silently drifts from the models.
        compare_type=True,
        compare_server_default=True,
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


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

- [ ] **Step 4: Teach the mako template to import SQLModel**

SQLModel's `AutoString` appears in autogenerated migrations; without the import the revision fails at runtime with `NameError`.

```bash
cd /Users/floyd/Documents/botly
sed -i '' 's|^import sqlalchemy as sa$|import sqlalchemy as sa\nimport sqlmodel|' migration/script.py.mako
```

- [ ] **Step 5: Write the failing test — `test/test_migrations.py`**

```python
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

    engine = create_async_engine(settings.TEST_DATABASE_URL, poolclass=None)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", settings.TEST_DATABASE_URL)
    await engine.dispose()

    def _upgrade_and_diff(sync_conn):
        cfg.attributes["connection"] = sync_conn
        command.upgrade(cfg, "head")
        context = MigrationContext.configure(
            sync_conn, opts={"compare_type": True}
        )
        return compare_metadata(context, SQLModel.metadata)

    engine = create_async_engine(settings.TEST_DATABASE_URL, poolclass=None)
    async with engine.begin() as conn:
        diff = await conn.run_sync(_upgrade_and_diff)
    await engine.dispose()

    assert diff == [], f"models and migrations disagree: {diff}"
```

- [ ] **Step 6: Make `migration/env.py` reuse a caller-supplied connection**

The drift test drives `command.upgrade` on a connection it already owns. Insert this branch in `run_migrations_online`'s place — replace the last block of `migration/env.py` with:

```python
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
```

- [ ] **Step 7: Run the test to verify it fails**

Run: `poetry run pytest test/test_migrations.py -v`
Expected: FAIL — `test_there_is_exactly_one_head` fails with 0 heads; the drift test reports four missing tables.

- [ ] **Step 8: Generate the initial migration**

```bash
cd /Users/floyd/Documents/botly
docker compose exec -T postgres psql -U botly -d botly -c "CREATE EXTENSION IF NOT EXISTS vector;"
poetry run alembic upgrade head
poetry run alembic revision --autogenerate -m "initial tenancy schema"
```

- [ ] **Step 9: Read the generated revision before trusting it**

Open the file in `migration/versions/`. Confirm it creates `merchants`, `shops`, `bots`, `channel_connections` in that order (parents before children), that foreign keys carry `ondelete="CASCADE"`, that `config` and `enabled_tools` are `postgresql.JSONB`, and that both unique constraints are present. Delete any spurious `DROP` of a table this project does not own.

- [ ] **Step 10: Apply it and run the tests**

Run: `poetry run alembic upgrade head && poetry run pytest test/test_migrations.py -v`
Expected: PASS — 2 passed

- [ ] **Step 11: Run the whole suite**

Run: `poetry run pytest -v`
Expected: PASS — all tests pass

- [ ] **Step 12: Commit**

```bash
git add alembic.ini migration test/test_migrations.py
git commit -m "feat: alembic wiring and initial tenancy migration"
```

---

### Task 7: README and the day-one approval reminder

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing. Produces: nothing consumed by code.

- [ ] **Step 1: Write `README.md`**

````markdown
# botly

Multi-channel chatbot platform for Southeast Asian commerce sellers.

- Architecture: `docs/superpowers/specs/2026-09-02-botly-architecture-design.md`
- Plans: `docs/superpowers/plans/`

## Local setup

```bash
poetry install
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # -> CREDENTIALS_ENCRYPTION_KEY
docker compose up -d
docker compose exec -T postgres psql -U botly -d botly -c "CREATE DATABASE botly_test;"
poetry run alembic upgrade head
poetry run pytest
poetry run uvicorn app.main:app --reload
```

## Blocking external approvals

Shopee Open Platform partner registration and WhatsApp Business verification are
approval-gated and sit on the critical path. They are not engineering work and they
take weeks. Start both before writing step 2 of the build order; if either is refused,
build-order steps 5 and 6 need replanning.
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: local setup and approval critical path"
```

---

## Definition of Done

- `poetry run pytest` passes with the Postgres container running.
- `poetry run alembic upgrade head` on an empty database produces a schema that `test_migrations.py` finds identical to the models.
- `poetry run uvicorn app.main:app` serves `GET /healthz`.
- `ENVIRONMENT=prod` refuses to start.
- Nothing outside `app/channels/` (which does not exist yet) references a provider name.

## Not in this plan

Build-order steps 2-7 from the spec: the `ChannelAdapter` Protocol and conformance suite, the Telegram adapter, conversation/message models and the seller inbox, the Shopee data client, the WhatsApp adapter, and the Nuxt frontend. Each gets its own plan. The `kb_document`/`kb_chunk` tables and the pgvector index arrive with the RAG plan, not here — this task creates the extension, not the embeddings.
