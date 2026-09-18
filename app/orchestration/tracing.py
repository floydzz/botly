"""Bounded, useful LangGraph traces.

The graph may generate many low-level events. They stay in memory until the
turn completes, then deterministic scoring chooses the twenty worth retaining.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import text

from app.models.orchestration import LlmRun, LlmRunEvent, LlmRunStatus

MAX_PERSISTED_EVENTS = 20

_SCORES = {
    "run.failed": 1000,
    "run.escalated": 1000,
    "tool.write.executed": 1000,
    "tool.write.failed": 1000,
    "tool.confirmation.requested": 950,
    "tool.confirmation.received": 950,
    "manager.plan": 800,
    "worker.succeeded": 700,
    "worker.failed": 700,
    "manager.follow_up": 650,
    "tool.read.completed": 600,
    "worker.started": 200,
    "worker.skipped": 100,
}


@dataclass(frozen=True)
class TraceEvent:
    event_type: str
    worker_key: str | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    metadata: dict = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def priority(self) -> int:
        if self.event_type in _SCORES:
            return _SCORES[self.event_type]
        if self.event_type.startswith("tool.write"):
            return 900
        if self.event_type.startswith("tool."):
            return 600
        if self.event_type.startswith("worker."):
            return 500
        return 300


@dataclass(frozen=True)
class SelectedTrace:
    events: tuple[TraceEvent, ...]
    total: int
    dropped: int
    dropped_summary: str | None


def select_events(events: list[TraceEvent], limit: int = MAX_PERSISTED_EVENTS) -> SelectedTrace:
    """Choose valuable events, then restore their original time order."""
    if limit < 1:
        raise ValueError("event limit must be positive")
    ranked = sorted(enumerate(events), key=lambda item: (-item[1].priority, item[0]))
    retained_indexes = {index for index, _event in ranked[:limit]}
    retained = tuple(event for index, event in enumerate(events) if index in retained_indexes)
    dropped = [event for index, event in enumerate(events) if index not in retained_indexes]
    summary = None
    if dropped:
        counts = Counter(event.event_type for event in dropped)
        summary = ", ".join(f"{kind} × {count}" for kind, count in sorted(counts.items()))
    return SelectedTrace(retained, len(events), len(dropped), summary)


class RunTraceRecorder:
    """Writes one partitioned run and its selected event trace."""

    def __init__(self, db) -> None:
        self._db = db

    async def start(self, *, merchant_id: int, bot_id: int, conversation_id: int, source_message_id: int) -> LlmRun:
        await self._ensure_monthly_partitions()
        run = LlmRun(
            merchant_id=merchant_id,
            bot_id=bot_id,
            conversation_id=conversation_id,
            source_message_id=source_message_id,
        )
        self._db.add(run)
        await self._db.flush()
        return run

    async def _ensure_monthly_partitions(self) -> None:
        """Keep partitions available when a deployment crosses into a new month."""
        partitioned = await self._db.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_partitioned_table WHERE partrelid = 'llm_runs'::regclass)")
        )
        if not partitioned:
            # SQLModel's test schema uses ordinary tables. Production schemas
            # are created by Alembic and are partitioned.
            return
        now = datetime.now(timezone.utc)
        month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        for _ in range(2):
            following = (
                month.replace(year=month.year + 1, month=1)
                if month.month == 12
                else month.replace(month=month.month + 1)
            )
            suffix = month.strftime("%Y_%m")
            for parent in ("llm_runs", "llm_run_events"):
                await self._db.execute(
                    text(
                        f"CREATE TABLE IF NOT EXISTS {parent}_{suffix} PARTITION OF {parent} "
                        f"FOR VALUES FROM ('{month.isoformat()}') TO ('{following.isoformat()}')"
                    )
                )
            month = following

    async def finish(
        self,
        run: LlmRun,
        events: list[TraceEvent],
        *,
        status: LlmRunStatus,
        final_response: str | None = None,
        selected_workers: list[str] | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_cost: str = "0",
    ) -> SelectedTrace:
        selected = select_events(events)
        run.status = status
        run.final_response = final_response
        run.selected_workers = selected_workers or []
        run.event_count_total = selected.total
        run.event_count_persisted = len(selected.events)
        run.event_count_dropped = selected.dropped
        run.event_summary = selected.dropped_summary
        run.total_input_tokens = input_tokens
        run.total_output_tokens = output_tokens
        run.total_cost = total_cost
        run.finished_at = datetime.now(timezone.utc)
        for sequence, event in enumerate(selected.events, start=1):
            self._db.add(
                LlmRunEvent(
                    # Events use the run's month partition, which keeps the
                    # database cap constraint enforceable at a month boundary.
                    created_at=run.created_at,
                    run_id=run.id,
                    run_created_at=run.created_at,
                    sequence_number=sequence,
                    occurred_at=event.occurred_at,
                    event_type=event.event_type,
                    worker_key=event.worker_key,
                    priority=event.priority,
                    input_summary=event.input_summary,
                    output_summary=event.output_summary,
                    metadata_json=event.metadata,
                )
            )
        await self._db.flush()
        return selected
