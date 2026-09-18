"""Celery tasks.

Each one is a thin shell. The logic lives in app/runtime/, which is plain async
code with no Celery import -- so it is testable without a broker, and the queue
stays a replaceable seam rather than a framework the business logic is welded
to.
"""

import asyncio

from app.worker.celery_app import celery_app

# The name travels inside every enqueued message. Renaming it strands whatever
# is already in the queue.
INBOUND_TASK_NAME = "botly.process_inbound_event"
KNOWLEDGE_INGEST_TASK_NAME = "botly.ingest_knowledge_document"


@celery_app.task(name=INBOUND_TASK_NAME, bind=True, max_retries=3)
def process_inbound_event(self, event_id: int) -> None:
    """Run one stored inbound event through the runtime.

    The payload is a row id, never the message itself: a queue holding customer
    text is a second copy to secure, and it is stale the moment the row moves.
    """
    from app.runtime.pipeline import run_inbound_pipeline

    async def run():
        from app.core.database import engine
        try:
            await run_inbound_pipeline(event_id)
        finally:
            # Celery calls asyncio.run per task. Do not reuse asyncpg connections
            # whose previous event loop has already closed.
            await engine.dispose()

    asyncio.run(run())


@celery_app.task(name=KNOWLEDGE_INGEST_TASK_NAME, bind=True, max_retries=3)
def ingest_knowledge_document(self, document_id: int) -> None:
    """Extract, chunk and embed a locally stored knowledge document."""
    from sqlalchemy import delete
    from app.core.database import AsyncSessionLocal, engine
    from app.knowledge.service import OpenAIEmbeddings, QdrantKnowledgeStore, chunks, extract_text, namespace
    from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeDocumentStatus
    from pathlib import Path
    from uuid import uuid4

    async def run():
        try:
            async with AsyncSessionLocal() as db:
                document = await db.get(KnowledgeDocument, document_id)
                if document is None or document.status == KnowledgeDocumentStatus.READY:
                    return
                document.status = KnowledgeDocumentStatus.PROCESSING
                document.error = None
                db.add(document)
                await db.commit()
                try:
                    parts = chunks(extract_text(Path(document.storage_key)))
                    if not parts:
                        raise ValueError("no readable text was found in the document")
                    vectors: list[list[float]] = []
                    embedder = OpenAIEmbeddings()
                    for index in range(0, len(parts), 64):
                        vectors.extend(await embedder.embed(parts[index:index + 64], document.embedding_model))
                    await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id))
                    ids = [str(uuid4()) for _ in parts]
                    await QdrantKnowledgeStore().upsert(
                        model=document.embedding_model,
                        scope=namespace(document.merchant_id, document.brand_id, document.bot_id),
                        document_id=document.id,
                        chunks_with_ids=list(zip(ids, parts)), vectors=vectors,
                    )
                    db.add_all([KnowledgeChunk(document_id=document.id, ordinal=index, qdrant_point_id=point_id, text=text, character_count=len(text)) for index, (point_id, text) in enumerate(zip(ids, parts))])
                    document.status = KnowledgeDocumentStatus.READY
                    document.chunk_count = len(parts)
                except Exception:
                    document.status = KnowledgeDocumentStatus.FAILED
                    document.error = "Document processing failed. Check the file and OpenAI/Qdrant configuration."
                db.add(document)
                await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(run())
