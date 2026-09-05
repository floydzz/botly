from app.worker.celery_app import celery_app
from app.worker.tasks import INBOUND_TASK_NAME


class CeleryInboundQueue:
    """The production InboundQueue. send_task by name rather than importing
    the task function, so ingress does not drag the runtime into its process."""

    async def enqueue(self, event_id: int) -> None:
        celery_app.send_task(INBOUND_TASK_NAME, (event_id,))
