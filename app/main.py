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
