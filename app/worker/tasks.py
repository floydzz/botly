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


@celery_app.task(name=INBOUND_TASK_NAME, bind=True, max_retries=3)
def process_inbound_event(self, event_id: int) -> None:
    """Run one stored inbound event through the runtime.

    The payload is a row id, never the message itself: a queue holding customer
    text is a second copy to secure, and it is stale the moment the row moves.
    """
    from app.runtime.pipeline import run_inbound_pipeline

    asyncio.run(run_inbound_pipeline(event_id))
