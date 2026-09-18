"""Bridge the LangGraph manager to Botly's existing metered response brain."""

from sqlalchemy import select

from app.models.orchestration import BotWorker, LlmRunStatus, WorkerDefinition, WorkerKey
from app.models.billing import LlmModel
from app.orchestration.graph import LangGraphManager
from app.orchestration.tracing import RunTraceRecorder, TraceEvent
from app.orchestration.auditor import audit
from app.runtime.brain import Brain, DraftReply


async def enabled_worker_configs(db, bot_id: int) -> dict[WorkerKey, dict]:
    rows = (
        await db.execute(
            select(BotWorker, WorkerDefinition)
            .join(WorkerDefinition, WorkerDefinition.id == BotWorker.worker_definition_id)
            .where(BotWorker.bot_id == bot_id, BotWorker.enabled.is_(True))
        )
    ).all()
    # Scope is supplied by the trusted runtime, never by a browser worker config.
    # Keep operator options in the JSON config, with these identity values layered on.
    return {definition.key: dict(row.config) for row, definition in rows}


class LangGraphBrain:
    """One graph-managed turn followed by the existing metered answer model.

    The first worker implementations are deliberately safe placeholders. Their
    contracts and trace flow are live now; provider-specific RAG, OCR, voice,
    and third-party API implementations can replace them without changing the
    receiver or conversation pipeline.
    """

    def __init__(self, *, db, bot, conversation, inbound_message_id: int, responder: Brain, manager: LangGraphManager | None = None) -> None:
        self._db = db
        self._bot = bot
        self._conversation = conversation
        self._inbound_message_id = inbound_message_id
        self._responder = responder
        self._manager = manager or LangGraphManager()

    async def respond(self, envelope) -> DraftReply:
        recorder = RunTraceRecorder(self._db)
        run = await recorder.start(
            merchant_id=self._conversation.merchant_id,
            bot_id=self._bot.id,
            conversation_id=self._conversation.id,
            source_message_id=self._inbound_message_id,
        )
        events: list[TraceEvent] = []
        try:
            configs = await enabled_worker_configs(self._db, self._bot.id)
            for config in configs.values():
                config.update({
                    "merchant_id": self._conversation.merchant_id,
                    "brand_id": self._bot.brand_id,
                    "bot_id": self._bot.id,
                })
            if self._bot.llm_model_id:
                model = await self._db.get(LlmModel, self._bot.llm_model_id)
                if model and model.provider == "openai":
                    for config in configs.values():
                        config.setdefault("openai_model", model.model_code)
            outcome = await self._manager.run(envelope, configs)
            events.extend(outcome.events)
            rag = outcome.worker_results.get(WorkerKey.RAG.value, {})
            context = rag.get("context", "") if isinstance(rag, dict) else ""
            if context and hasattr(self._responder, "set_manager_context"):
                self._responder.set_manager_context(context)
            draft = await self._responder.respond(envelope)
            if self._bot.auditor_enabled:
                audited = audit(draft, customer_text=envelope.text or "", knowledge_context=context)
                if audited.escalate and not draft.escalate:
                    events.append(TraceEvent("auditor.blocked", output_summary=audited.reason))
                else:
                    events.append(TraceEvent("auditor.approved", output_summary="reply passed knowledge policy"))
                draft = audited
        except Exception as exc:
            # Do not put provider exception details in a customer-facing reply
            # or trace. The trace records the category and the manager hands it
            # to the existing escalation path.
            events.append(TraceEvent("run.failed", output_summary="manager execution failed"))
            await recorder.finish(run, events, status=LlmRunStatus.FAILED)
            return DraftReply(escalate=True, reason="the manager could not complete this request")

        status = LlmRunStatus.ESCALATED if draft.escalate else LlmRunStatus.COMPLETED
        if draft.escalate:
            events.append(TraceEvent("run.escalated", output_summary=draft.reason))
        await recorder.finish(
            run,
            events,
            status=status,
            final_response=draft.text,
            selected_workers=list(outcome.worker_results),
        )
        return draft
