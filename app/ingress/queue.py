"""The seam between ingress and runtime.

The spec calls the queue "the pre-cut seam": when webhook volume justifies
splitting ingress from the runtime into two services, this is where the cut
happens, and it becomes a deployment change rather than a rewrite. Keeping the
route's dependency on it this thin is what preserves that.
"""

from typing import Protocol


class InboundQueue(Protocol):
    async def enqueue(self, event_id: int) -> None:
        """Hand a persisted event to the runtime. Must not block on a result."""
        ...


class InMemoryInboundQueue:
    """Records ids instead of dispatching. The end-to-end test drains it."""

    def __init__(self) -> None:
        self.enqueued: list[int] = []

    async def enqueue(self, event_id: int) -> None:
        self.enqueued.append(event_id)
