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

    # One day. Long enough to outlive any provider's retry schedule, short
    # enough that the keyspace does not grow without bound.
    DEDUPE_TTL_SECONDS: int = 86_400

    # A separate Redis database from the dedupe keys: flushing a stuck queue
    # must not also erase the dedupe keyspace and replay every recent webhook.
    CELERY_BROKER_URL: str = "redis://localhost:6380/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6380/2"

    # Per connection. Telegram's own guidance is roughly 30 messages/second
    # overall and about 1/second into a single chat; the conservative number
    # here is a floor that every channel can live with.
    OUTBOUND_RATE_CAPACITY: int = 20
    OUTBOUND_RATE_REFILL_PER_SECOND: float = 1.0
    OUTBOUND_MAX_ATTEMPTS: int = 3

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
