"""Provider-neutral LangGraph manager and worker contracts.

The manager decides which enabled specialists to call. Workers return data and
trace events only; the customer-facing reply remains the manager's job.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from app.channels.types import InboundEnvelope
from app.models.orchestration import WorkerKey
from app.orchestration.tracing import TraceEvent
from app.knowledge.service import OpenAIEmbeddings, QdrantKnowledgeStore, namespace
from app.llm.providers import HttpTextProvider, ProviderError, provider_ready


class Worker(Protocol):
    key: WorkerKey

    async def run(self, envelope: InboundEnvelope, config: dict) -> "WorkerResult": ...


@dataclass(frozen=True)
class WorkerResult:
    event: TraceEvent
    data: dict


class NotConfiguredWorker:
    """Safe placeholder until a RAG store, OCR service, or API connector exists."""

    def __init__(self, key: WorkerKey) -> None:
        self.key = key

    async def run(self, envelope: InboundEnvelope, config: dict) -> WorkerResult:
        return WorkerResult(
            event=TraceEvent(
                "worker.skipped",
                worker_key=self.key.value,
                output_summary="worker is enabled but no provider is configured",
            ),
            data={},
        )


class RagWorker:
    """Builds a retrieval query, recalls 30 scoped chunks, then reranks to 3."""

    key = WorkerKey.RAG

    async def run(self, envelope: InboundEnvelope, config: dict) -> WorkerResult:
        if not envelope.text:
            return WorkerResult(TraceEvent("worker.skipped", worker_key=self.key.value, output_summary="no text query"), {})
        query = envelope.text
        model = str(config.get("openai_model", "gpt-4.1-mini"))
        if provider_ready("openai"):
            try:
                completion = await HttpTextProvider("openai").complete(
                    model,
                    "Rewrite the customer message as one concise knowledge-base search query. Return only the query. Do not answer the customer.",
                    [{"role": "user", "content": envelope.text}], 160,
                )
                query = completion.text.strip() or query
            except ProviderError:
                pass
        try:
            embedding_model = str(config.get("embedding_model", "text-embedding-3-small"))
            vector = (await OpenAIEmbeddings().embed([query], embedding_model))[0]
            candidates = await QdrantKnowledgeStore().search(
                model=embedding_model,
                scope=namespace(config["merchant_id"], config["brand_id"], config["bot_id"]),
                vector=vector, limit=30,
            )
        except Exception:
            return WorkerResult(TraceEvent("worker.failed", worker_key=self.key.value, output_summary="knowledge retrieval unavailable"), {})
        chosen = candidates[:3]
        if candidates and provider_ready("openai"):
            listing = "\n\n".join(f"[{index}] {item.get('text', '')[:1800]}" for index, item in enumerate(candidates))
            try:
                ranked = await HttpTextProvider("openai").complete(
                    str(config.get("reranker_model", model)),
                    "Rank knowledge snippets for answering the query. Return only a JSON array of up to three numeric snippet indexes. Prefer direct factual support; do not invent facts.",
                    [{"role": "user", "content": f"Query: {query}\n\nSnippets:\n{listing}"}], 80,
                )
                import json
                indexes = json.loads(ranked.text)
                if isinstance(indexes, list):
                    selected = [candidates[index] for index in indexes[:3] if isinstance(index, int) and 0 <= index < len(candidates)]
                    if selected:
                        chosen = selected
            except (ProviderError, ValueError, TypeError):
                pass
        context = "\n\n".join(f"Source {index + 1}: {item.get('text', '')}" for index, item in enumerate(chosen))
        return WorkerResult(
            TraceEvent("worker.completed", worker_key=self.key.value, output_summary=f"retrieved {len(candidates)} candidates and selected {len(chosen)}"),
            {"query": query, "context": context, "candidate_count": len(candidates), "source_count": len(chosen)},
        )


class ManagerPlanner(Protocol):
    def plan(self, envelope: InboundEnvelope, enabled_workers: set[WorkerKey]) -> list[WorkerKey]: ...


class SafeDefaultPlanner:
    """Deterministic routing until a structured LLM planner is enabled.

    It only routes media to its matching reader. Calling customer APIs based on
    a keyword would be unsafe, so Tools awaits a registered structured planner.
    """

    def plan(self, envelope: InboundEnvelope, enabled_workers: set[WorkerKey]) -> list[WorkerKey]:
        planned: list[WorkerKey] = []
        kinds = {attachment.kind for attachment in envelope.attachments}
        if WorkerKey.VOICE in enabled_workers and "audio" in kinds:
            planned.append(WorkerKey.VOICE)
        if WorkerKey.OCR in enabled_workers and kinds.intersection({"image", "file"}):
            planned.append(WorkerKey.OCR)
        if WorkerKey.RAG in enabled_workers and envelope.text:
            planned.append(WorkerKey.RAG)
        return planned


class ManagerState(TypedDict):
    envelope: InboundEnvelope
    enabled_configs: dict[str, dict]
    pending_workers: list[str]
    planned: bool
    results: dict[str, dict]
    events: list[TraceEvent]


@dataclass(frozen=True)
class ManagerOutcome:
    worker_results: Mapping[str, dict]
    events: tuple[TraceEvent, ...]


class LangGraphManager:
    """Runs the manager/worker graph for one message turn."""

    def __init__(self, workers: Mapping[WorkerKey, Worker] | None = None, planner: ManagerPlanner | None = None) -> None:
        self._workers = dict(workers or {key: NotConfiguredWorker(key) for key in WorkerKey})
        if workers is None:
            self._workers[WorkerKey.RAG] = RagWorker()
        self._planner = planner or SafeDefaultPlanner()
        graph = StateGraph(ManagerState)
        graph.add_node("manager", self._manager)
        for key in WorkerKey:
            graph.add_node(key.value, self._worker_node(key))
        graph.add_edge(START, "manager")
        graph.add_conditional_edges("manager", self._next_node, {**{key.value: key.value for key in WorkerKey}, "finish": END})
        for key in WorkerKey:
            graph.add_edge(key.value, "manager")
        self._graph = graph.compile()

    async def run(self, envelope: InboundEnvelope, enabled_configs: Mapping[WorkerKey, dict]) -> ManagerOutcome:
        state = await self._graph.ainvoke(
            {
                "envelope": envelope,
                "enabled_configs": {key.value: config for key, config in enabled_configs.items()},
                "pending_workers": [],
                "planned": False,
                "results": {},
                "events": [TraceEvent("run.started")],
            }
        )
        events = list(state["events"])
        events.append(TraceEvent("run.completed"))
        return ManagerOutcome(worker_results=state["results"], events=tuple(events))

    def _manager(self, state: ManagerState) -> dict:
        if state["planned"]:
            return {}
        enabled = {WorkerKey(key) for key in state["enabled_configs"]}
        planned = self._planner.plan(state["envelope"], enabled)
        return {
            "pending_workers": [key.value for key in planned],
            "planned": True,
            "events": [
                *state["events"],
                TraceEvent("manager.plan", output_summary=", ".join(key.value for key in planned) or "no worker needed"),
            ],
        }

    @staticmethod
    def _next_node(state: ManagerState) -> str:
        return state["pending_workers"][0] if state["pending_workers"] else "finish"

    def _worker_node(self, key: WorkerKey):
        async def node(state: ManagerState) -> dict:
            result = await self._workers[key].run(state["envelope"], state["enabled_configs"][key.value])
            remaining = state["pending_workers"][1:]
            return {
                "pending_workers": remaining,
                "results": {**state["results"], key.value: result.data},
                "events": [*state["events"], TraceEvent("worker.started", worker_key=key.value), result.event],
            }
        return node
