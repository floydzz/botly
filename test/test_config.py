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
