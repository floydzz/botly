from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "botly",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # A worker killed mid-task returns the message to the queue instead of
    # losing it. Combined with the dedupe table, a redelivery is safe.
    task_acks_late=True,
    # One message at a time per worker process. The default of four means a
    # slow LLM call blocks three other customers behind it.
    worker_prefetch_multiplier=1,
)
