"""The small, code-owned worker catalog exposed to bot configuration."""

from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert

from app.models.orchestration import WorkerDefinition, WorkerKey

WORKER_CATALOG = {
    WorkerKey.RAG: ("Knowledge retrieval", "Searches the bot's approved knowledge sources."),
    WorkerKey.OCR: ("Document reader", "Extracts text from supported attachments."),
    WorkerKey.VOICE: ("Voice transcription", "Transcribes supported customer audio."),
    WorkerKey.TOOLS: ("Customer tools", "Calls approved customer API actions."),
}


async def ensure_worker_catalog(db) -> None:
    """Seed missing definitions safely for fresh and long-lived databases."""
    now = datetime.now(timezone.utc)
    for key, (name, description) in WORKER_CATALOG.items():
        await db.execute(
            insert(WorkerDefinition)
            .values(key=key.value, name=name, description=description, created_at=now, updated_at=now)
            .on_conflict_do_nothing(constraint="uq_worker_definitions_key")
        )
    await db.flush()
