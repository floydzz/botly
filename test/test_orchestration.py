from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.channels.types import Attachment, InboundEnvelope
from app.models.orchestration import WorkerKey
from app.models.bot import Bot
from app.models.conversation import Conversation
from app.models.merchant import Merchant
from app.models.message import Direction, Message, SenderType
from app.models.orchestration import LlmRunEvent, LlmRunStatus
from app.models.brand import Brand
from app.orchestration.graph import LangGraphManager, WorkerResult
from app.orchestration.tracing import RunTraceRecorder, TraceEvent, select_events


def envelope(*, text="hello", attachments=()):
    return InboundEnvelope(
        provider="fake",
        external_thread_id="thread",
        provider_update_id="update",
        sender_ref="customer",
        text=text,
        attachments=attachments,
        sent_at=datetime.now(timezone.utc),
    )


def test_trace_selection_retains_important_events_and_chronology():
    events = [TraceEvent("worker.started", worker_key="rag") for _ in range(24)]
    events.insert(3, TraceEvent("tool.write.executed", worker_key="tools"))
    selected = select_events(events)

    assert selected.total == 25
    assert len(selected.events) == 20
    assert selected.events[0].event_type == "worker.started"
    assert any(event.event_type == "tool.write.executed" for event in selected.events)
    assert selected.dropped == 5


class RecordingWorker:
    def __init__(self, key):
        self.key = key

    async def run(self, message, config):
        return WorkerResult(TraceEvent("worker.succeeded", worker_key=self.key.value), {"text": "1234"})


async def test_manager_calls_multiple_enabled_workers_once_each():
    manager = LangGraphManager(workers={
        WorkerKey.RAG: RecordingWorker(WorkerKey.RAG),
        WorkerKey.OCR: RecordingWorker(WorkerKey.OCR),
        WorkerKey.VOICE: RecordingWorker(WorkerKey.VOICE),
        WorkerKey.TOOLS: RecordingWorker(WorkerKey.TOOLS),
    })
    outcome = await manager.run(
        envelope(attachments=(Attachment(kind="image", url="https://example.test/a.png"),)),
        {WorkerKey.RAG: {}, WorkerKey.OCR: {}},
    )

    assert set(outcome.worker_results) == {"rag", "ocr"}
    assert [event.worker_key for event in outcome.events if event.event_type == "worker.succeeded"] == ["ocr", "rag"]


@pytest.mark.integration
async def test_run_recorder_persists_at_most_twenty_priority_selected_events(db_session):
    merchant = Merchant(name="Trace merchant")
    db_session.add(merchant)
    await db_session.flush()
    brand = Brand(merchant_id=merchant.id, name="Trace brand", platform="standalone")
    db_session.add(brand)
    await db_session.flush()
    bot = Bot(brand_id=brand.id, name="Trace bot")
    db_session.add(bot)
    await db_session.flush()
    conversation = Conversation(
        merchant_id=merchant.id,
        bot_id=bot.id,
        channel_connection_id=1,
        external_thread_id="trace-thread",
        customer_ref="customer",
    )
    # The trace does not use the connection relation; give the model a valid
    # fixture row through the database's normal relationship tests instead.
    from app.models.channel_connection import ChannelConnection
    connection = ChannelConnection(bot_id=bot.id, provider="fake", external_ref="trace")
    connection.set_credentials({})
    db_session.add(connection)
    await db_session.flush()
    conversation.channel_connection_id = connection.id
    db_session.add(conversation)
    await db_session.flush()
    message = Message(
        conversation_id=conversation.id,
        merchant_id=merchant.id,
        direction=Direction.INBOUND,
        sender_type=SenderType.CUSTOMER,
        text="hello",
    )
    db_session.add(message)
    await db_session.flush()

    recorder = RunTraceRecorder(db_session)
    run = await recorder.start(
        merchant_id=merchant.id,
        bot_id=bot.id,
        conversation_id=conversation.id,
        source_message_id=message.id,
    )
    events = [TraceEvent("worker.started", worker_key="rag") for _ in range(22)]
    events.extend([TraceEvent("manager.plan"), TraceEvent("tool.confirmation.requested")])
    selected = await recorder.finish(run, events, status=LlmRunStatus.AWAITING_CUSTOMER)

    assert len(selected.events) == 20
    assert run.event_count_total == 24
    assert run.event_count_dropped == 4
    assert (await db_session.execute(select(func.count()).select_from(LlmRunEvent))).scalar_one() == 20
