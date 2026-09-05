from app.worker.celery_app import celery_app
from app.worker.queue import CeleryInboundQueue
from app.worker.tasks import INBOUND_TASK_NAME, process_inbound_event


def test_the_task_is_registered_under_a_stable_name():
    """The name travels in the queue payload. Renaming it strands every
    message already enqueued under the old name."""
    assert INBOUND_TASK_NAME == "botly.process_inbound_event"
    assert INBOUND_TASK_NAME in celery_app.tasks


def test_the_task_name_carries_no_provider():
    """One task processes every channel. A per-provider task name would be
    provider branching wearing a hat."""
    for name in ("telegram", "whatsapp", "shopee"):
        assert name not in INBOUND_TASK_NAME


def test_late_acknowledgement_is_on():
    """acks_late: a worker killed mid-task must return the message to the
    queue, not lose the customer's message."""
    assert celery_app.conf.task_acks_late is True


def test_the_task_accepts_only_an_event_id():
    """The payload is a row id, never the message. A queue holding customer
    text is a second copy to secure, and it goes stale the moment the row
    changes."""
    import inspect

    parameters = list(inspect.signature(process_inbound_event).parameters)

    assert parameters == ["event_id"]


async def test_the_celery_queue_sends_the_id_to_the_named_task(monkeypatch):
    sent: list[tuple] = []
    monkeypatch.setattr(
        celery_app, "send_task", lambda name, args: sent.append((name, args))
    )

    await CeleryInboundQueue().enqueue(4321)

    assert sent == [(INBOUND_TASK_NAME, (4321,))]
