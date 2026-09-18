"""Local source storage, OpenAI embeddings, and Qdrant retrieval."""

import hashlib
import re
from pathlib import Path
from uuid import uuid4

import httpx
from docx import Document as DocxDocument
from pypdf import PdfReader
from qdrant_client import AsyncQdrantClient, models

from app.core.config import settings
from app.llm.providers import ProviderError, provider_ready

SUPPORTED_SUFFIXES = {".txt", ".md", ".csv", ".json", ".html", ".pdf", ".docx"}


def namespace(merchant_id: int, brand_id: int, bot_id: int) -> str:
    return f"{merchant_id}:{brand_id}:{bot_id}"


def collection_for(model: str) -> str:
    return "knowledge_" + re.sub(r"[^a-zA-Z0-9_]", "_", model.lower())


def dimensions_for(model: str) -> int:
    return {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072}.get(model, 1536)


def chunks(text: str, size: int = 1_200, overlap: int = 180) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    result: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            boundary = text.rfind(" ", start + size // 2, end)
            if boundary > start:
                end = boundary
        part = text[start:end].strip()
        if part:
            result.append(part)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return result


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".json", ".html"}:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    if suffix == ".docx":
        return "\n".join(paragraph.text for paragraph in DocxDocument(path).paragraphs)
    raise ValueError("unsupported document type")


class OpenAIEmbeddings:
    async def embed(self, inputs: list[str], model: str) -> list[list[float]]:
        if not provider_ready("openai"):
            raise ProviderError("OpenAI embeddings are not configured", uncertain=False)
        key = settings.OPENAI_API_KEY.get_secret_value()
        async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": model, "input": inputs, "encoding_format": "float"},
            )
        if response.status_code >= 400:
            raise ProviderError(f"OpenAI embeddings returned HTTP {response.status_code}", uncertain=response.status_code >= 500)
        body = response.json()
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list) or len(data) != len(inputs):
            raise ProviderError("OpenAI embeddings returned an invalid response")
        return [item["embedding"] for item in sorted(data, key=lambda item: item["index"])]


class QdrantKnowledgeStore:
    def __init__(self, client: AsyncQdrantClient | None = None):
        self.client = client or AsyncQdrantClient(url=settings.QDRANT_URL)

    async def ensure_collection(self, model: str) -> str:
        collection = collection_for(model)
        if not await self.client.collection_exists(collection):
            await self.client.create_collection(
                collection,
                vectors_config=models.VectorParams(size=dimensions_for(model), distance=models.Distance.COSINE),
            )
            await self.client.create_payload_index(collection, "scope", models.PayloadSchemaType.KEYWORD)
        return collection

    async def upsert(self, *, model: str, scope: str, document_id: int, chunks_with_ids: list[tuple[str, str]], vectors: list[list[float]]) -> None:
        collection = await self.ensure_collection(model)
        await self.client.upsert(
            collection,
            points=[models.PointStruct(id=point_id, vector=vector, payload={"scope": scope, "document_id": document_id, "ordinal": ordinal, "text": text}) for ordinal, ((point_id, text), vector) in enumerate(zip(chunks_with_ids, vectors))],
            wait=True,
        )

    async def search(self, *, model: str, scope: str, vector: list[float], limit: int = 30) -> list[dict]:
        collection = await self.ensure_collection(model)
        points = await self.client.query_points(
            collection_name=collection,
            query=vector,
            query_filter=models.Filter(must=[models.FieldCondition(key="scope", match=models.MatchValue(value=scope))]),
            limit=limit,
            with_payload=True,
        )
        return [{"score": point.score, **(point.payload or {})} for point in points.points]


def storage_path(merchant_id: int, brand_id: int, bot_id: int, suffix: str) -> Path:
    root = Path(settings.KNOWLEDGE_STORAGE_DIR)
    return root / str(merchant_id) / str(brand_id) / str(bot_id) / f"{uuid4()}{suffix.lower()}"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
