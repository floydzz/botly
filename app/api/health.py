from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness only. It must not touch Postgres or Redis: a health check that
    queries the database turns a slow database into a restart loop."""

    return {"status": "ok", "environment": settings.ENVIRONMENT}
