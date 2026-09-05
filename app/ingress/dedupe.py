"""Inbound dedupe.

Providers retry aggressively and will deliver the same update more than once.
The dedupe-plus-fast-ACK pair is a correctness requirement, not an
optimisation: without it a retried webhook becomes a second reply to the
customer.

Redis is the fast path. The unique constraint on inbound_events is the second
line, because Redis is disposable state and can be flushed.
"""

from typing import Protocol

DEDUPE_PREFIX = "ingress:dedupe"


def dedupe_key(provider: str, provider_update_id: str) -> str:
    # Namespaced by provider: update ids are only unique within one.
    return f"{DEDUPE_PREFIX}:{provider}:{provider_update_id}"


class DedupeStore(Protocol):
    async def claim(self, key: str) -> bool:
        """True if this caller is the first to see the key, False if it is a
        duplicate."""
        ...


class RedisDedupeStore:
    def __init__(self, client, ttl_seconds: int = 86_400) -> None:
        self._client = client
        self._ttl = ttl_seconds

    async def claim(self, key: str) -> bool:
        # SET NX EX: one atomic round trip. GET-then-SET would let two
        # concurrent deliveries of the same update both observe "absent" and
        # both proceed.
        # redis-py returns True on success and None when NX finds the key.
        return await self._client.set(key, "1", nx=True, ex=self._ttl) is True


class InMemoryDedupeStore:
    """For tests and for the in-process fake pipeline. Not for two workers."""

    def __init__(self) -> None:
        self.claimed: set[str] = set()

    async def claim(self, key: str) -> bool:
        if key in self.claimed:
            return False
        self.claimed.add(key)
        return True
