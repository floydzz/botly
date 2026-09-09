from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The only spellings that mean anything. An unrecognised value is a
# configuration error, not a silent fallback to development.
_VALID_ENVIRONMENTS = ("development", "staging", "test", "production")


class Settings(BaseSettings):
    """Every value the process needs, read from the environment.

    Two kinds of setting live here and they are treated differently.

    **Anything carrying a credential or naming a backing service has no
    default.** A missing DATABASE_URL must stop the process at startup, not
    quietly point it at a localhost that happens to be a developer's machine --
    and a default written here is a credential in git, whatever its value. They
    come from ``.env`` (see ``.env.example`` for the full list); the failure
    when one is absent is a pydantic "Field required" naming the key.

    **Behaviour knobs keep their defaults**, because there is nothing secret in
    a retry count and every deployment wanting the same number should not have
    to restate it.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    ENVIRONMENT: str = "development"
    SQL_ECHO: bool = False

    # --- credentials and service addresses: no defaults, see the docstring ---

    DATABASE_URL: str
    TEST_DATABASE_URL: str
    REDIS_URL: str
    # Fernet key for channel_connections.credentials_encrypted. Losing it means
    # every stored bot token is unrecoverable; rotating it means re-encrypting
    # every row. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    CREDENTIALS_ENCRYPTION_KEY: str
    # Separate Redis databases from the dedupe keys: flushing a stuck queue must
    # not also erase the dedupe keyspace and replay every recent webhook.
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str

    # --- behaviour knobs: defaults are the intended value everywhere ---

    # One day. Long enough to outlive any provider's retry schedule, short
    # enough that the keyspace does not grow without bound.
    DEDUPE_TTL_SECONDS: int = 86_400

    # Per connection. Telegram's own guidance is roughly 30 messages/second
    # overall and about 1/second into a single chat; the conservative number
    # here is a floor that every channel can live with.
    # Two weeks. Long enough that an agent is not re-typing a password
    # every morning, short enough that a forgotten laptop stops mattering.
    SESSION_TTL_SECONDS: int = 1_209_600

    OUTBOUND_RATE_CAPACITY: int = 20
    OUTBOUND_RATE_REFILL_PER_SECOND: float = 1.0
    OUTBOUND_MAX_ATTEMPTS: int = 3

    # How long the bot stays quiet after an agent releases a conversation back
    # to it. Without a grace period the next customer message can arrive while
    # the agent's closing line is still in flight, and the bot answers over a
    # person who has just said goodbye. Two minutes covers a goodbye; much
    # longer and a genuinely new question sits unanswered.
    BOT_MUTE_AFTER_RELEASE_SECONDS: int = 120

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
