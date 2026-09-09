"""Outbound rate limiting.

A token bucket per connection. Redis in production because two workers share
one provider quota; in-memory in tests because a bucket that needs a container
makes the dispatcher tests slow and flaky.
"""

import time
from typing import Protocol

RATE_PREFIX = "dispatch:bucket"


def bucket_key(connection_id: int | None) -> str:
    return f"{RATE_PREFIX}:{connection_id}"


class RateLimiter(Protocol):
    async def acquire(self, key: str) -> bool:
        """True if a token was available. False means back off; the caller
        decides whether that is a retry or a failure."""
        ...


class InMemoryTokenBucket:
    def __init__(
        self,
        capacity: int = 20,
        refill_per_second: float = 1.0,
        now=time.monotonic,
    ) -> None:
        self._capacity = capacity
        self._refill = refill_per_second
        self._now = now
        self._state: dict[str, tuple[float, float]] = {}

    async def acquire(self, key: str) -> bool:
        now = self._now()
        tokens, last = self._state.get(key, (float(self._capacity), now))
        tokens = min(self._capacity, tokens + (now - last) * self._refill)
        if tokens < 1:
            self._state[key] = (tokens, now)
            return False
        self._state[key] = (tokens - 1, now)
        return True


# Atomic in one round trip. Read-modify-write from Python would let two workers
# both read the same token count and both spend it.
_LUA_TOKEN_BUCKET = """
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil then tokens = capacity; ts = now end
tokens = math.min(capacity, tokens + (now - ts) * refill)
local allowed = 0
if tokens >= 1 then tokens = tokens - 1; allowed = 1 end
redis.call('HMSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', KEYS[1], 3600)
return allowed
"""


class RedisTokenBucket:
    def __init__(
        self, client, capacity: int = 20, refill_per_second: float = 1.0
    ) -> None:
        self._client = client
        self._capacity = capacity
        self._refill = refill_per_second

    async def acquire(self, key: str) -> bool:
        allowed = await self._client.eval(
            _LUA_TOKEN_BUCKET, 1, key, self._capacity, self._refill, time.time()
        )
        return bool(allowed)


_default: "RedisTokenBucket | None" = None


def default_limiter() -> RateLimiter:
    """The bucket both sender processes share.

    The worker and the API each send on behalf of the same connection. Two
    in-process buckets would each hold a full allowance, so the effective rate
    against the provider would be double what was configured -- and a
    provider-side rate limit is not a soft failure.

    Built once per process: a new client per dispatch leaks a connection per
    message. Tests keep InMemoryTokenBucket by injection and never reach here.
    """
    global _default
    if _default is None:
        from redis.asyncio import Redis

        from app.core.config import settings

        _default = RedisTokenBucket(
            Redis.from_url(settings.REDIS_URL),
            capacity=settings.OUTBOUND_RATE_CAPACITY,
            refill_per_second=settings.OUTBOUND_RATE_REFILL_PER_SECOND,
        )
    return _default
