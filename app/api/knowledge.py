"""Tenant-scoped local document uploads for the RAG worker."""

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select

from app.api.bots import load_bot
from app.api.deps import TenantScope, tenant
from app.core.config import settings
from app.core.database import get_db
from app.knowledge.service import SUPPORTED_SUFFIXES, digest, storage_path
from app.models.knowledge import KnowledgeDocument, KnowledgeDocumentStatus
from app.worker.tasks import ingest_knowledge_document

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def out(document: KnowledgeDocument) -> dict:
    return {key: getattr(document, key) for key in ("id", "bot_id", "brand_id", "filename", "media_type", "status", "embedding_model", "chunk_count", "error", "created_at")}


@router.get("/documents")
async def documents(bot_id: int, scope: TenantScope = Depends(tenant), db=Depends(get_db)):
    await load_bot(db, scope, bot_id)
    rows = (await db.execute(select(KnowledgeDocument).where(KnowledgeDocument.bot_id == bot_id, KnowledgeDocument.merchant_id == scope.merchant_id).order_by(KnowledgeDocument.id.desc()))).scalars()
    return [out(row) for row in rows]


@router.post("/documents", status_code=201)
async def upload_document(bot_id: int = Form(...), file: UploadFile = File(...), scope: TenantScope = Depends(tenant), db=Depends(get_db)):
    bot = await load_bot(db, scope, bot_id)
    filename = Path(file.filename or "document").name
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(422, "supported files are txt, md, csv, json, html, pdf, and docx")
    content = await file.read(settings.KNOWLEDGE_MAX_UPLOAD_BYTES + 1)
    if not content or len(content) > settings.KNOWLEDGE_MAX_UPLOAD_BYTES:
        raise HTTPException(422, "document must be between 1 byte and 25 MB")
    path = storage_path(scope.merchant_id, bot.brand_id, bot.id, suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    document = KnowledgeDocument(
        merchant_id=scope.merchant_id, brand_id=bot.brand_id, bot_id=bot.id,
        filename=filename, media_type=file.content_type or "application/octet-stream",
        storage_key=str(path), sha256=digest(content), embedding_model=settings.OPENAI_EMBEDDING_MODEL,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    ingest_knowledge_document.delay(document.id)
    return out(document)
