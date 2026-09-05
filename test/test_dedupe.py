import pytest

from app.ingress.dedupe import InMemoryDedupeStore, RedisDedupeStore, dedupe_key


def test_the_key_namespaces_by_provider():
    """Update ids are only unique within a provider; a shared namespace would
    make one channel's update silence another's."""
    assert dedupe_key("telegram", "900") != dedupe_key("fake", "900")
    assert "900" in dedupe_key("telegram", "900")


async def test_the_first_claim_wins_and_the_second_loses():
    store = InMemoryDedupeStore()

    assert await store.claim("k") is True
    assert await store.claim("k") is False


async def test_distinct_keys_do_not_collide():
    store = InMemoryDedupeStore()

    assert await store.claim("a") is True
    assert await store.claim("b") is True


class _StubRedis:
    """Just enough Redis to prove the store uses SET NX EX and nothing else."""

    def __init__(self, result: bool | None) -> None:
        self.result = result
        self.calls: list[tuple] = []

    async def set(self, key, value, nx=False, ex=None):
        self.calls.append((key, value, nx, ex))
        return self.result


async def test_the_redis_store_claims_with_set_nx_ex():
    """SET NX EX is one atomic round trip. A GET-then-SET would let two
    concurrent deliveries of the same update both see 'absent' and both win."""
    client = _StubRedis(result=True)
    store = RedisDedupeStore(client, ttl_seconds=3600)

    assert await store.claim("k") is True
    key, _value, nx, ex = client.calls[0]
    assert key == "k"
    assert nx is True
    assert ex == 3600


async def test_the_redis_store_reports_a_duplicate_when_the_key_exists():
    # redis-py returns None, not False, when NX finds the key present.
    store = RedisDedupeStore(_StubRedis(result=None))

    assert await store.claim("k") is False


@pytest.mark.integration
async def test_the_real_redis_store_round_trips():
    import uuid

    from redis.asyncio import Redis

    from app.core.config import settings

    client = Redis.from_url(settings.REDIS_URL)
    store = RedisDedupeStore(client, ttl_seconds=30)
    key = f"test:{uuid.uuid4()}"
    try:
        assert await store.claim(key) is True
        assert await store.claim(key) is False
    finally:
        await client.delete(key)
        await client.aclose()
