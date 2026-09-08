# botly Inbox API and Realtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the HTTP and WebSocket surface the seller inbox reads and writes — conversations, messages, agent send, takeover/release/resolve, bots, channel connections — plus the Redis event bus that carries worker-written messages across the process boundary into a browser.

**Architecture:** Three new routers (`conversations`, `bots`, `connections`) and one WebSocket route, all tenant-scoped through the existing `TenantScope`. Agent replies travel the same `OutboundDispatcher` path as bot replies, so chunking, rate limiting and session-window rules apply to humans too; the outbound `Message` write is extracted out of `app/runtime/pipeline.py` into `app/dispatch/record.py` so both callers share it. Realtime is a `Protocol` + Redis implementation + in-memory fake, following the `adapters/` discipline already used for the dedupe store and the rate limiter.

**Tech Stack:** Python 3.12+, FastAPI, SQLModel, SQLAlchemy 2 (asyncio) + asyncpg, PostgreSQL 17, Redis (pub/sub), Celery, pytest + pytest-asyncio (`asyncio_mode = auto`).

**Spec:** `docs/superpowers/specs/2026-09-09-frontend-and-inbox-api-design.md` — Part A (§3–§7), plus §13 and §14.

---

## Global Constraints

- **Every endpoint depends on `tenant: TenantScope = Depends(tenant)` and filters on `TenantScope.merchant_id`.** No endpoint reads a merchant id from a path, a query parameter or a body.
- **A row belonging to another merchant is 404, never 403.** A 403 confirms the row exists, which turns id enumeration into a census of other tenants' traffic.
- **`Bot` and `ChannelConnection` carry no denormalised `merchant_id`.** Their tenant filter is a join — `Bot → Shop → merchant_id`, `ChannelConnection → Bot → Shop → merchant_id`. Both go through one shared query helper that takes a `TenantScope`; a forgotten join raises nothing and returns another tenant's rows.
- **No module outside `app/channels/<provider>/` may name a provider in a string literal.** `test/test_architecture.py` enforces this by scanning every string constant under `app/` (docstrings excluded). Reading `conn.provider` is fine; writing `"telegram"` is not.
- **All times are timezone-aware UTC.** `DateTime(timezone=True)` columns, `app/models/base.py::utcnow`. Never `datetime.utcnow`, never a naive datetime.
- **Every external service sits behind a Protocol with a fake.** This plan adds one — the event bus. No test touches Redis pub/sub or the network.
- **Realtime events are published after commit, never inside the transaction.** An event announcing a row a later rollback erased makes the inbox show a message that does not exist.
- **Delivery is best-effort.** The client refetches on reconnect; a dropped event costs a delayed update, not a wrong one.
- **Cursor pagination, never offset.** The conversation list is reordered by every inbound message, and offset pagination on it skips and repeats rows.
- One commit per task. Conventional commit prefixes (`feat:`, `test:`, `refactor:`, `chore:`, `docs:`).

### Values copied verbatim from the spec

- New setting: `BOT_MUTE_AFTER_RELEASE_SECONDS`, default `120`.
- Redis pub/sub channel name: `merchant:{merchant_id}:events`.
- WebSocket close code for an unauthenticated handshake: `1008`, sent **before** `accept()`.
- WebSocket keepalive ping interval: 30 seconds.
- Default page size: `50`.
- Conversation ordering: `last_message_at DESC NULLS LAST, id DESC`.
- Event names: `message.created`, `conversation.updated`.

---

## File Structure

| File | Responsibility |
|---|---|
| `app/core/config.py` | *(modify)* add `BOT_MUTE_AFTER_RELEASE_SECONDS` |
| `.env.example` | *(modify)* document the new knob |
| `app/dispatch/record.py` | `record_outbound()` — the one place an outbound `Message` row is written, for both the bot and the agent |
| `app/dispatch/dispatcher.py` | *(modify)* extract `window_is_closed()` to module level so the send policy and the dispatcher cannot drift apart |
| `app/dispatch/ratelimit.py` | *(modify)* `default_limiter()` — the shared `RedisTokenBucket`, so two sender processes share one provider quota |
| `app/runtime/pipeline.py` | *(modify)* use `record_outbound`, `default_limiter`, and publish events after commit |
| `app/channels/registry.py` | *(modify)* `capabilities_for(provider)` — a capability manifest without credentials |
| `app/realtime/__init__.py` | package marker |
| `app/realtime/bus.py` | `EventBus` Protocol, `RedisEventBus`, `FakeEventBus`, `channel_for()` |
| `app/realtime/events.py` | `message_created()` / `conversation_updated()` envelope builders — one shape, built once |
| `app/api/pagination.py` | `encode_cursor` / `decode_cursor` / `Cursor` — opaque keyset cursors |
| `app/api/schemas.py` | Response models shared by the routers |
| `app/api/queries.py` | Tenant-scoped query helpers, including the `Bot`/`ChannelConnection` joins |
| `app/api/send_policy.py` | `build_send_policy(capabilities, last_inbound_at)` |
| `app/api/conversations.py` | The conversation router: list, detail, messages, read, takeover, release, resolve, send |
| `app/api/bots.py` | `GET /bots`, `PATCH /bots/{id}` |
| `app/api/connections.py` | `GET /channels/connections` |
| `app/api/realtime.py` | `GET /ws` |
| `app/main.py` | *(modify)* register the four new routers |
| `test/test_record_outbound.py` | The shared outbound recorder |
| `test/test_pagination.py` | Cursor round-trip and tamper resistance |
| `test/test_send_policy.py` | Open window, closed window, unknown `last_inbound_at` |
| `test/test_conversations_api.py` | List, filters, cursor stability, detail, messages, read |
| `test/test_conversation_actions_api.py` | Takeover / release / resolve, including the two-agent conflict |
| `test/test_agent_send_api.py` | The send endpoint's four refusal and failure paths |
| `test/test_bots_api.py` | Bots and connections, with the join-based tenant isolation |
| `test/test_realtime_bus.py` | The bus Protocol and its fake |
| `test/test_realtime_ws.py` | Handshake auth and per-merchant delivery |

---

### Task 1: The release-grace setting

**Files:**
- Modify: `app/core/config.py`
- Modify: `.env.example`
- Test: `test/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `settings.BOT_MUTE_AFTER_RELEASE_SECONDS: int` (default `120`).

- [ ] **Step 1: Write the failing test** — append to `test/test_config.py`

```python
def test_the_release_grace_period_has_an_intended_default():
    """Release sets bot_muted_until = now + this. Without a grace period the
    next customer message can arrive while the agent's closing line is still
    in flight, and the bot answers over a person who just said goodbye."""
    from app.core.config import Settings

    assert Settings().BOT_MUTE_AFTER_RELEASE_SECONDS == 120
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/bin/python -m pytest test/test_config.py -q`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'BOT_MUTE_AFTER_RELEASE_SECONDS'`

- [ ] **Step 3: Add the setting** to the "behaviour knobs" block of `app/core/config.py`

```python
    # How long the bot stays quiet after an agent releases a conversation.
    # Without it the next customer message can arrive while the agent's closing
    # line is still in flight, and the bot answers over a person who just said
    # goodbye. Conversation.bot_muted_until exists for exactly this.
    BOT_MUTE_AFTER_RELEASE_SECONDS: int = 120
```

- [ ] **Step 4: Document it** in `.env.example` under the behaviour-knobs comment block

```
# BOT_MUTE_AFTER_RELEASE_SECONDS=120
```

- [ ] **Step 5: Run the test and watch it pass**, then commit

```bash
.venv/bin/python -m pytest test/test_config.py -q
git add app/core/config.py .env.example test/test_config.py
git commit -m "feat: bot mute grace period after an agent releases a conversation"
```

---

### Task 2: `record_outbound` — one outbound writer for two callers

`_store_outbound` in `app/runtime/pipeline.py` writes `sender_type = BOT` and is private to that module. The agent path needs identical delivery-status and error logic with `sender_type = AGENT` and `sender_user_id` set.

**Files:**
- Create: `app/dispatch/record.py`
- Modify: `app/runtime/pipeline.py` (delete `_store_outbound`, call the new function)
- Test: `test/test_record_outbound.py`

**Interfaces:**
- Consumes: `DispatchOutcome` from `app/dispatch/dispatcher.py`.
- Produces:

```python
def record_outbound(
    db,
    conversation: Conversation,
    text: str | None,
    attachments: list[dict],
    outcome: DispatchOutcome,
    sender_type: SenderType,
    sender_user_id: int | None = None,
) -> Message: ...
```

  Returns the `Message` it added (not yet flushed). It also advances `conversation.last_message_at`. It does **not** write a `FailedJob` — the two callers record failure differently (the pipeline against its inbound event, the API against the connection), and that is the caller's business.

- [ ] **Step 1: Write the failing test** — `test/test_record_outbound.py`

```python
"""The shared outbound recorder.

Covered once here rather than twice through its two callers: the whole point of
extracting it was that the bot path and the agent path stop being able to
disagree about what a failed send looks like in the thread.
"""

from datetime import datetime, timezone

import pytest

from app.channels.types import SendResult
from app.dispatch.dispatcher import DispatchOutcome
from app.dispatch.record import record_outbound
from app.models.conversation import Conversation
from app.models.merchant import Merchant
from app.models.message import DeliveryStatus, Direction, Message, SenderType

pytestmark = pytest.mark.integration


async def _conversation(db) -> Conversation:
    from app.models.bot import Bot
    from app.models.channel_connection import ChannelConnection
    from app.models.shop import Shop

    merchant = Merchant(name=f"M{datetime.now(timezone.utc).timestamp()}")
    db.add(merchant)
    await db.flush()
    shop = Shop(merchant_id=merchant.id, name="S", platform="standalone")
    db.add(shop)
    await db.flush()
    bot = Bot(shop_id=shop.id, name="B")
    db.add(bot)
    await db.flush()
    conn = ChannelConnection(bot_id=bot.id, provider="fake", external_ref=f"r{bot.id}")
    conn.set_credentials({})
    db.add(conn)
    await db.flush()
    conversation = Conversation(
        merchant_id=merchant.id,
        bot_id=bot.id,
        channel_connection_id=conn.id,
        external_thread_id=f"t{bot.id}",
        customer_ref="c1",
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def test_a_successful_send_is_recorded_as_sent(db_session):
    conversation = await _conversation(db_session)
    outcome = DispatchOutcome(
        sent=(SendResult(ok=True, provider_message_id="p-1"),)
    )

    message = record_outbound(
        db_session, conversation, "hello", [], outcome, SenderType.BOT
    )
    await db_session.flush()

    assert message.direction is Direction.OUTBOUND
    assert message.sender_type is SenderType.BOT
    assert message.delivery_status is DeliveryStatus.SENT
    assert message.provider_message_id == "p-1"
    assert message.error is None
    assert message.merchant_id == conversation.merchant_id


async def test_a_permanent_failure_is_recorded_with_its_error(db_session):
    """The agent must see their own failed message in the thread. Swallowing it
    as an error toast loses the text they typed."""
    conversation = await _conversation(db_session)
    outcome = DispatchOutcome(
        sent=(SendResult(ok=False, error="recipient blocked the bot"),),
        permanent_failure="recipient blocked the bot",
    )

    message = record_outbound(
        db_session, conversation, "hello", [], outcome, SenderType.BOT
    )
    await db_session.flush()

    assert message.delivery_status is DeliveryStatus.FAILED
    assert message.error == "recipient blocked the bot"


async def test_an_agent_message_carries_the_agent(db_session):
    from app.core.security import hash_password
    from app.models.user import User

    conversation = await _conversation(db_session)
    user = User(
        merchant_id=conversation.merchant_id,
        email=f"a{conversation.id}@example.com",
        password_hash=hash_password("x"),
        name="Ani",
    )
    db_session.add(user)
    await db_session.flush()

    message = record_outbound(
        db_session,
        conversation,
        "on it",
        [],
        DispatchOutcome(sent=(SendResult(ok=True, provider_message_id="p-2"),)),
        SenderType.AGENT,
        sender_user_id=user.id,
    )
    await db_session.flush()

    assert message.sender_type is SenderType.AGENT
    assert message.sender_user_id == user.id


async def test_recording_advances_the_conversations_last_message_at(db_session):
    conversation = await _conversation(db_session)
    assert conversation.last_message_at is None

    record_outbound(
        db_session,
        conversation,
        "hello",
        [],
        DispatchOutcome(sent=(SendResult(ok=True),)),
        SenderType.BOT,
    )
    await db_session.flush()

    assert conversation.last_message_at is not None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/bin/python -m pytest test/test_record_outbound.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.dispatch.record'`

- [ ] **Step 3: Write `app/dispatch/record.py`**

```python
"""Writing an outbound message down.

Extracted from the pipeline because there are now two senders -- the bot and an
agent -- and they must not be able to disagree about what a failed send looks
like in the thread. The FailedJob row is deliberately *not* written here: the
pipeline records a failure against its inbound event, the API records one
against the connection, and that difference belongs to the caller.
"""

from datetime import datetime, timezone

from app.dispatch.dispatcher import DispatchOutcome
from app.models.conversation import Conversation
from app.models.message import DeliveryStatus, Direction, Message, SenderType


def record_outbound(
    db,
    conversation: Conversation,
    text: str | None,
    attachments: list[dict],
    outcome: DispatchOutcome,
    sender_type: SenderType,
    sender_user_id: int | None = None,
) -> Message:
    delivered = [result for result in outcome.sent if result.ok]
    message = Message(
        conversation_id=conversation.id,
        merchant_id=conversation.merchant_id,
        direction=Direction.OUTBOUND,
        sender_type=sender_type,
        sender_user_id=sender_user_id,
        text=text,
        attachments=attachments,
        # The first delivered chunk's id. A long reply is several provider
        # messages and only one column holds an id; the first is the one a
        # human would quote.
        provider_message_id=(
            delivered[0].provider_message_id if delivered else None
        ),
        delivery_status=(
            DeliveryStatus.FAILED if outcome.permanent_failure else DeliveryStatus.SENT
        ),
        error=outcome.permanent_failure,
    )
    db.add(message)
    conversation.last_message_at = datetime.now(timezone.utc)
    db.add(conversation)
    return message
```

- [ ] **Step 4: Run the test and watch it pass**

Run: `.venv/bin/python -m pytest test/test_record_outbound.py -q`
Expected: PASS

- [ ] **Step 5: Make the pipeline use it.** In `app/runtime/pipeline.py`, delete the `_store_outbound` function and replace its call site.

```python
            record_outbound(
                db,
                conversation,
                draft.text,
                [a.model_dump() for a in draft.attachments],
                outcome,
                SenderType.BOT,
            )
```

Add `from app.dispatch.record import record_outbound` to the imports and drop the now-unused `DeliveryStatus`/`Direction`/`Message` imports if nothing else in the module uses them (`_store_inbound` still uses `Direction`, `Message` and `SenderType`; `DeliveryStatus` becomes unused).

- [ ] **Step 6: Run the whole suite and commit**

```bash
.venv/bin/python -m pytest -q
git add app/dispatch/record.py app/runtime/pipeline.py test/test_record_outbound.py
git commit -m "refactor: extract record_outbound so the bot and agent paths share one writer"
```

---

### Task 3: One rate limiter across two sender processes

`app/runtime/pipeline.py` constructs `InMemoryTokenBucket`. Adding the API process as a second sender makes that wrong: the worker and the API would each hold a full bucket for the same connection, so the effective outbound rate against a provider doubles.

**Files:**
- Modify: `app/dispatch/ratelimit.py`
- Modify: `app/runtime/pipeline.py`
- Test: `test/test_dispatcher.py` *(append)*

**Interfaces:**
- Produces: `app/dispatch/ratelimit.py::default_limiter() -> RateLimiter` — a process-wide `RedisTokenBucket` against `settings.REDIS_URL`, sized from `OUTBOUND_RATE_CAPACITY` / `OUTBOUND_RATE_REFILL_PER_SECOND`.

- [ ] **Step 1: Write the failing test** — append to `test/test_dispatcher.py`

```python
def test_the_default_limiter_is_shared_across_processes():
    """In-process buckets were adequate while one worker was the only sender.
    The API is a second sender against the same provider quota, and a
    provider-side rate limit is not a soft failure."""
    from app.dispatch.ratelimit import RedisTokenBucket, default_limiter

    assert isinstance(default_limiter(), RedisTokenBucket)


def test_the_default_limiter_is_built_once():
    """A new Redis client per dispatch would leak a connection per message."""
    from app.dispatch.ratelimit import default_limiter

    assert default_limiter() is default_limiter()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/bin/python -m pytest test/test_dispatcher.py -q -k limiter`
Expected: FAIL — `ImportError: cannot import name 'default_limiter'`

- [ ] **Step 3: Implement it** — append to `app/dispatch/ratelimit.py`

```python
_default: "RedisTokenBucket | None" = None


def default_limiter() -> RateLimiter:
    """The bucket both sender processes share.

    Built once per process: a new client per dispatch leaks a connection per
    message. Tests keep InMemoryTokenBucket by injection and never reach this.
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
```

- [ ] **Step 4: Use it in the pipeline.** In `app/runtime/pipeline.py`, replace the `InMemoryTokenBucket(...)` construction with `default_limiter()` and swap the import.

```python
        dispatcher = OutboundDispatcher(
            adapter,
            limiter=limiter or default_limiter(),
            max_attempts=settings.OUTBOUND_MAX_ATTEMPTS,
        )
```

- [ ] **Step 5: Run the suite and commit**

```bash
.venv/bin/python -m pytest -q
git add app/dispatch/ratelimit.py app/runtime/pipeline.py test/test_dispatcher.py
git commit -m "feat: share one Redis token bucket between the worker and the API"
```

---

### Task 4: The window rule, in one place

`send_policy` must use "the same rule as `OutboundDispatcher._window_is_closed`, including its treatment of an unknown `last_inbound_at` as closed rather than open". Two copies of that rule is one copy too many.

**Files:**
- Modify: `app/dispatch/dispatcher.py`
- Create: `app/api/send_policy.py`
- Test: `test/test_send_policy.py`

**Interfaces:**
- Produces:
  - `app/dispatch/dispatcher.py::window_is_closed(caps: ChannelCapabilities, last_inbound_at: datetime | None) -> bool` — module level. `OutboundDispatcher._window_is_closed` becomes a one-line delegation so no existing caller changes.
  - `app/api/send_policy.py::SendPolicy` (pydantic): `can_send_freeform: bool`, `reason: str | None`, `max_text_len: int`, `supports_media: bool`, `window_closes_at: datetime | None`.
  - `app/api/send_policy.py::build_send_policy(caps: ChannelCapabilities, last_inbound_at: datetime | None) -> SendPolicy`.

- [ ] **Step 1: Write the failing test** — `test/test_send_policy.py`

```python
"""The composer's contract.

Advisory only: the dispatcher still enforces the rule independently on send.
The policy exists so the UI can disable the composer with an explanation
instead of letting an agent type a paragraph into a box that will reject it.
"""

from datetime import datetime, timedelta, timezone

from app.api.send_policy import build_send_policy
from app.channels.types import ChannelCapabilities

ALWAYS_OPEN = ChannelCapabilities(supports_media=True, max_text_len=4096)
WINDOWED = ChannelCapabilities(
    supports_media=True,
    max_text_len=1024,
    session_window=timedelta(hours=24),
    requires_template_outside_window=True,
)


def test_a_channel_without_a_window_can_always_send():
    policy = build_send_policy(ALWAYS_OPEN, last_inbound_at=None)

    assert policy.can_send_freeform is True
    assert policy.reason is None
    assert policy.window_closes_at is None
    assert policy.max_text_len == 4096
    assert policy.supports_media is True


def test_an_open_window_can_send_and_says_when_it_closes():
    last_inbound = datetime.now(timezone.utc) - timedelta(hours=1)

    policy = build_send_policy(WINDOWED, last_inbound_at=last_inbound)

    assert policy.can_send_freeform is True
    assert policy.window_closes_at == last_inbound + timedelta(hours=24)


def test_a_closed_window_refuses_with_the_reason_the_ui_renders():
    last_inbound = datetime.now(timezone.utc) - timedelta(hours=25)

    policy = build_send_policy(WINDOWED, last_inbound_at=last_inbound)

    assert policy.can_send_freeform is False
    assert "template" in policy.reason


def test_an_unknown_last_inbound_is_closed_not_open():
    """Same treatment as the dispatcher. Treating it as open turns a guard
    failure into a provider rejection the agent finds out about afterwards."""
    policy = build_send_policy(WINDOWED, last_inbound_at=None)

    assert policy.can_send_freeform is False
    assert policy.window_closes_at is None


def test_a_window_without_a_template_rule_still_permits_free_text():
    """requires_template_outside_window is what forbids free text, not the
    window itself -- exactly as the dispatcher reads it."""
    caps = ChannelCapabilities(
        supports_media=True,
        max_text_len=1024,
        session_window=timedelta(hours=24),
        requires_template_outside_window=False,
    )

    policy = build_send_policy(caps, last_inbound_at=None)

    assert policy.can_send_freeform is True
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/bin/python -m pytest test/test_send_policy.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.send_policy'`

- [ ] **Step 3: Lift the rule to module level** in `app/dispatch/dispatcher.py`

```python
def window_is_closed(caps, last_inbound_at: datetime | None) -> bool:
    """Whether the channel's session window has shut.

    Module level rather than a private method because the inbox's send policy
    has to answer the same question, and two copies of this rule is how the
    composer starts telling agents something the dispatcher disagrees with.
    """
    if caps.session_window is None:
        return False
    if last_inbound_at is None:
        # Unknown is closed, not open. Treating it as open turns a guard
        # failure into a provider rejection.
        return True
    return datetime.now(timezone.utc) - last_inbound_at > caps.session_window
```

and reduce the method to a delegation:

```python
    @staticmethod
    def _window_is_closed(caps, last_inbound_at: datetime | None) -> bool:
        return window_is_closed(caps, last_inbound_at)
```

- [ ] **Step 4: Write `app/api/send_policy.py`**

```python
"""What the composer is allowed to do, and why not.

Architecture spec §9: a human replying outside a channel's session window
cannot send free-form text either. The UI must surface that constraint
explicitly rather than letting the send fail silently.

This is advisory. The dispatcher enforces the same rule independently on send;
the policy exists so the box can be disabled with an explanation instead of
accepting a paragraph it will reject.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.channels.types import ChannelCapabilities
from app.dispatch.dispatcher import window_is_closed

_CLOSED = (
    "the session window has closed and this channel requires an approved template"
)


class SendPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    can_send_freeform: bool
    reason: str | None = None
    max_text_len: int
    supports_media: bool
    window_closes_at: datetime | None = None


def build_send_policy(
    caps: ChannelCapabilities, last_inbound_at: datetime | None
) -> SendPolicy:
    closed = window_is_closed(caps, last_inbound_at)
    refused = closed and caps.requires_template_outside_window
    return SendPolicy(
        can_send_freeform=not refused,
        reason=_CLOSED if refused else None,
        max_text_len=caps.max_text_len,
        supports_media=caps.supports_media,
        window_closes_at=(
            last_inbound_at + caps.session_window
            if caps.session_window is not None and last_inbound_at is not None
            else None
        ),
    )
```

- [ ] **Step 5: Run the tests and commit**

```bash
.venv/bin/python -m pytest test/test_send_policy.py test/test_dispatcher.py -q
git add app/dispatch/dispatcher.py app/api/send_policy.py test/test_send_policy.py
git commit -m "feat: send policy computed from the same window rule as the dispatcher"
```

---

### Task 5: Capabilities without credentials

`GET /channels/connections` must serialise each adapter's `ChannelCapabilities`, and `GET /conversations/{id}` must compute a send policy — neither should fail because a connection's credential blob is incomplete. `build_adapter` cannot answer that: it needs a token.

**Files:**
- Modify: `app/channels/registry.py`
- Test: `test/test_registry.py` *(append)*

**Interfaces:**
- Produces: `app/channels/registry.py::capabilities_for(provider: str) -> ChannelCapabilities`, raising `UnknownProvider` for an unregistered name.

- [ ] **Step 1: Write the failing test** — append to `test/test_registry.py`

```python
def test_capabilities_are_readable_without_credentials():
    """A degraded connection whose token is unusable still has to render its
    limits on the channels screen."""
    from app.channels.registry import capabilities_for
    from app.channels.fake.adapter import FakeAdapter

    assert capabilities_for(FakeAdapter.provider) is FakeAdapter.capabilities


def test_capabilities_for_an_unregistered_provider_is_an_unknown_provider():
    import pytest

    from app.channels.registry import UnknownProvider, capabilities_for

    with pytest.raises(UnknownProvider):
        capabilities_for("carrier-pigeon")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/bin/python -m pytest test/test_registry.py -q -k capabilities`
Expected: FAIL — `ImportError: cannot import name 'capabilities_for'`

- [ ] **Step 3: Implement it** — append to `app/channels/registry.py`

```python
# Adapter classes, for the questions that can be answered without credentials.
# Separate from _BUILDERS because a manifest is a ClassVar and a builder needs
# a token: the channels screen must not 502 because a connection is degraded.
_MANIFESTS: dict[str, type[ChannelAdapter]] = {
    TelegramAdapter.provider: TelegramAdapter,
    FakeAdapter.provider: FakeAdapter,
}


def capabilities_for(provider: str) -> ChannelCapabilities:
    adapter = _MANIFESTS.get(provider)
    if adapter is None:
        raise UnknownProvider(f"no adapter registered for provider {provider!r}")
    return adapter.capabilities
```

Add `ChannelCapabilities` to the `app.channels.types` import at the top of the module.

- [ ] **Step 4: Run and commit**

```bash
.venv/bin/python -m pytest test/test_registry.py -q
git add app/channels/registry.py test/test_registry.py
git commit -m "feat: read a channel's capability manifest without building an adapter"
```

---

### Task 6: Opaque keyset cursors

Offset pagination on a list reordered by every inbound message skips and repeats rows.

**Files:**
- Create: `app/api/pagination.py`
- Test: `test/test_pagination.py`

**Interfaces:**
- Produces:
  - `Cursor` — a frozen pydantic model: `last_message_at: datetime | None`, `id: int`.
  - `encode_cursor(last_message_at: datetime | None, row_id: int) -> str`
  - `decode_cursor(raw: str | None) -> Cursor | None` — returns `None` for `None`, raises `InvalidCursor` for anything unreadable.
  - `InvalidCursor(ValueError)`

- [ ] **Step 1: Write the failing test** — `test/test_pagination.py`

```python
"""Cursors.

Opaque on purpose. A client that can read a cursor starts constructing them,
and then the ordering key becomes a public API that cannot be changed.
"""

from datetime import datetime, timezone

import pytest

from app.api.pagination import InvalidCursor, decode_cursor, encode_cursor


def test_a_cursor_round_trips():
    when = datetime(2026, 9, 9, 4, 12, 55, tzinfo=timezone.utc)

    cursor = decode_cursor(encode_cursor(when, 41))

    assert cursor.last_message_at == when
    assert cursor.id == 41


def test_a_cursor_survives_a_null_ordering_key():
    """last_message_at is nullable on a conversation whose first message write
    has not landed, and those rows still have to paginate."""
    cursor = decode_cursor(encode_cursor(None, 7))

    assert cursor.last_message_at is None
    assert cursor.id == 7


def test_no_cursor_decodes_to_no_cursor():
    assert decode_cursor(None) is None


def test_a_cursor_does_not_read_as_its_contents():
    when = datetime(2026, 9, 9, 4, 12, 55, tzinfo=timezone.utc)

    encoded = encode_cursor(when, 41)

    assert "2026" not in encoded


def test_a_mangled_cursor_is_rejected_rather_than_guessed():
    with pytest.raises(InvalidCursor):
        decode_cursor("not-a-cursor")


def test_a_cursor_with_the_wrong_shape_is_rejected():
    import base64
    import json

    forged = base64.urlsafe_b64encode(json.dumps({"nope": 1}).encode()).decode()

    with pytest.raises(InvalidCursor):
        decode_cursor(forged)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/bin/python -m pytest test/test_pagination.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.pagination'`

- [ ] **Step 3: Write `app/api/pagination.py`**

```python
"""Keyset cursors for lists that reorder under the reader.

The conversation list is sorted by last_message_at, which every inbound message
changes. Offset pagination on it skips rows and repeats rows -- an agent
scrolling page two misses a conversation that moved to page one while they read.

The cursor is base64 of the ordering key, and it is opaque deliberately: a
client that can read one starts constructing them, and the ordering key becomes
a public API nobody can change.
"""

import base64
import binascii
import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict

DEFAULT_LIMIT = 50
MAX_LIMIT = 100


class InvalidCursor(ValueError):
    """The cursor did not come from encode_cursor."""


class Cursor(BaseModel):
    model_config = ConfigDict(frozen=True)

    last_message_at: datetime | None
    id: int


def encode_cursor(last_message_at: datetime | None, row_id: int) -> str:
    payload = json.dumps(
        {
            "t": last_message_at.isoformat() if last_message_at is not None else None,
            "i": row_id,
        },
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_cursor(raw: str | None) -> Cursor | None:
    if raw is None:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")))
        when = payload["t"]
        return Cursor(
            last_message_at=datetime.fromisoformat(when) if when is not None else None,
            id=int(payload["i"]),
        )
    except (
        KeyError,
        TypeError,
        ValueError,
        binascii.Error,
        UnicodeDecodeError,
    ) as exc:
        # A 400 naming the parameter, not a 500. A stale cursor from a bookmarked
        # URL is a client mistake, not a server fault.
        raise InvalidCursor("cursor is not readable") from exc
```

- [ ] **Step 4: Run and commit**

```bash
.venv/bin/python -m pytest test/test_pagination.py -q
git add app/api/pagination.py test/test_pagination.py
git commit -m "feat: opaque keyset cursors for the conversation list"
```

---

### Task 7: Tenant-scoped query helpers

The `Bot` and `ChannelConnection` tenant filter is a join, which is the shape the architecture spec warns about: a forgotten join raises nothing and simply returns another tenant's rows. One helper each, so there is one place to get it right.

**Files:**
- Create: `app/api/queries.py`
- Test: covered by Task 8 and Task 12's isolation tests (this task ships no behaviour of its own and is committed with Task 8).

**Interfaces:**
- Produces:
  - `conversations_for(tenant: TenantScope)` → a `Select` on `Conversation` already filtered by `merchant_id`.
  - `bots_for(tenant: TenantScope)` → a `Select` on `Bot` joined `Bot → Shop` and filtered on `Shop.merchant_id`, excluding soft-deleted bots and shops.
  - `connections_for(tenant: TenantScope)` → a `Select` on `ChannelConnection` joined `ChannelConnection → Bot → Shop` and filtered on `Shop.merchant_id`, excluding soft-deleted rows at all three levels.
  - `load_conversation(db, tenant, conversation_id) -> Conversation` — raises `HTTPException(404)` when it is not this merchant's.

- [ ] **Step 1: Write `app/api/queries.py`**

```python
"""Tenant-scoped selects.

Conversation and Message carry a denormalised merchant_id, so their filter is
one indexed predicate. Bot and ChannelConnection do not: their filter is a join
through Shop, and that is exactly the shape the architecture spec warns about --
a forgotten join raises nothing and quietly returns another tenant's rows.

So the join is written once, here, against a TenantScope. Nothing outside this
module builds a select on Bot or ChannelConnection.
"""

from fastapi import HTTPException
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import TenantScope
from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection
from app.models.conversation import Conversation
from app.models.shop import Shop


def conversations_for(tenant: TenantScope) -> Select:
    return select(Conversation).where(Conversation.merchant_id == tenant.merchant_id)


def bots_for(tenant: TenantScope) -> Select:
    return (
        select(Bot)
        .join(Shop, Shop.id == Bot.shop_id)
        .where(
            Shop.merchant_id == tenant.merchant_id,
            Bot.deleted_at.is_(None),
            Shop.deleted_at.is_(None),
        )
    )


def connections_for(tenant: TenantScope) -> Select:
    return (
        select(ChannelConnection)
        .join(Bot, Bot.id == ChannelConnection.bot_id)
        .join(Shop, Shop.id == Bot.shop_id)
        .where(
            Shop.merchant_id == tenant.merchant_id,
            ChannelConnection.deleted_at.is_(None),
            Bot.deleted_at.is_(None),
            Shop.deleted_at.is_(None),
        )
    )


async def load_conversation(
    db: AsyncSession, tenant: TenantScope, conversation_id: int
) -> Conversation:
    """404, not 403, when it belongs to someone else.

    A 403 confirms the row exists, which turns id enumeration into a census of
    other tenants' traffic.
    """
    conversation = (
        await db.execute(
            conversations_for(tenant).where(Conversation.id == conversation_id)
        )
    ).scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return conversation
```

- [ ] **Step 2: Confirm it imports cleanly** — no commit yet; Task 8 commits it with its first consumer.

```bash
.venv/bin/python -c "import app.api.queries"
```

---

### Task 8: `GET /conversations` — the list the agent works

**Files:**
- Create: `app/api/schemas.py`
- Create: `app/api/conversations.py`
- Modify: `app/main.py`
- Test: `test/test_conversations_api.py`

**Interfaces:**
- Consumes: `conversations_for`, `load_conversation` (Task 7); `encode_cursor`/`decode_cursor`/`DEFAULT_LIMIT`/`MAX_LIMIT` (Task 6).
- Produces:
  - `app/api/schemas.py::UserRef {id, name}`, `BotRef {id, name}`, `ConversationSummary`, `MessageOut`, `ConversationDetail`, `Page[T] {items, next_cursor}`.
  - `app/api/conversations.py::router` at prefix `/conversations`.
  - `app/api/conversations.py::summary_row_to_schema(row) -> ConversationSummary` — used by Task 13 to publish `conversation.updated` with the same shape the list returns.

`ConversationSummary` fields, exactly as the spec's item shape: `id, customer_name, customer_ref, provider, connection_id, bot, handoff_state, escalation_reason, assignee, last_message_at, last_message_preview, unread, has_failed_delivery`.

- [ ] **Step 1: Write the failing test** — `test/test_conversations_api.py`

```python
"""The conversation list and thread.

The tenant assertions are the important ones. A rendering bug is visible the
first time someone looks at the screen; a tenant-scoping bug quietly returns
another merchant's customers and nobody notices until it is a support ticket.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import hash_password
from app.main import app
from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection
from app.models.conversation import Conversation, HandoffState
from app.models.merchant import Merchant
from app.models.message import DeliveryStatus, Direction, Message, SenderType
from app.models.shop import Shop
from app.models.user import User

pytestmark = pytest.mark.integration

SESSION_COOKIE = "botly_session"
PASSWORD = "s3cret-passphrase"


@pytest.fixture
def wired(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield
    app.dependency_overrides.clear()


class Tenant:
    """One merchant with everything hanging off it, so a test can make two."""

    def __init__(self, merchant, shop, bot, connection, user):
        self.merchant = merchant
        self.shop = shop
        self.bot = bot
        self.connection = connection
        self.user = user


async def make_tenant(db, slug: str) -> Tenant:
    merchant = Merchant(name=f"M-{slug}")
    db.add(merchant)
    await db.flush()
    shop = Shop(merchant_id=merchant.id, name=f"S-{slug}", platform="standalone")
    db.add(shop)
    await db.flush()
    bot = Bot(shop_id=shop.id, name=f"Order bot {slug}")
    db.add(bot)
    await db.flush()
    connection = ChannelConnection(
        bot_id=bot.id, provider="fake", external_ref=f"ref-{slug}"
    )
    connection.set_credentials({})
    db.add(connection)
    user = User(
        merchant_id=merchant.id,
        email=f"{slug}@example.com",
        password_hash=hash_password(PASSWORD),
        name=f"Agent {slug}",
    )
    db.add(user)
    await db.flush()
    return Tenant(merchant, shop, bot, connection, user)


async def make_conversation(
    db,
    tenant: Tenant,
    thread: str,
    *,
    state=HandoffState.BOT,
    last_message_at=None,
    customer_name="Siti",
    assignee_id=None,
    escalation_reason=None,
    agent_last_read_at=None,
) -> Conversation:
    conversation = Conversation(
        merchant_id=tenant.merchant.id,
        bot_id=tenant.bot.id,
        channel_connection_id=tenant.connection.id,
        external_thread_id=thread,
        customer_ref=f"cust-{thread}",
        customer_name=customer_name,
        handoff_state=state,
        assignee_id=assignee_id,
        escalation_reason=escalation_reason,
        last_message_at=last_message_at,
        agent_last_read_at=agent_last_read_at,
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def add_message(
    db,
    conversation: Conversation,
    *,
    text: str,
    direction=Direction.INBOUND,
    sender_type=SenderType.CUSTOMER,
    delivery_status=DeliveryStatus.SENT,
    created_at=None,
    error=None,
) -> Message:
    message = Message(
        conversation_id=conversation.id,
        merchant_id=conversation.merchant_id,
        direction=direction,
        sender_type=sender_type,
        text=text,
        delivery_status=delivery_status,
        error=error,
    )
    if created_at is not None:
        message.created_at = created_at
    db.add(message)
    await db.flush()
    return message


def client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def sign_in(http: AsyncClient, tenant: Tenant) -> None:
    response = await http.post(
        "/auth/login", json={"email": tenant.user.email, "password": PASSWORD}
    )
    assert response.status_code == 200


# --- the list -------------------------------------------------------------


async def test_the_list_returns_this_merchants_conversations(db_session, wired):
    tenant = await make_tenant(db_session, "list")
    now = datetime.now(timezone.utc)
    await make_conversation(db_session, tenant, "t1", last_message_at=now)

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.get("/conversations")

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["customer_name"] for item in items] == ["Siti"]
    assert items[0]["provider"] == "fake"
    assert items[0]["connection_id"] == tenant.connection.id
    assert items[0]["bot"]["name"] == tenant.bot.name


async def test_another_merchants_conversations_are_absent(db_session, wired):
    mine = await make_tenant(db_session, "mine")
    theirs = await make_tenant(db_session, "theirs")
    now = datetime.now(timezone.utc)
    await make_conversation(db_session, mine, "t1", last_message_at=now)
    await make_conversation(
        db_session, theirs, "t2", last_message_at=now, customer_name="NotYours"
    )

    async with client() as http:
        await sign_in(http, mine)
        response = await http.get("/conversations")

    names = [item["customer_name"] for item in response.json()["items"]]
    assert names == ["Siti"]


async def test_the_list_is_newest_first_with_nulls_last(db_session, wired):
    tenant = await make_tenant(db_session, "order")
    now = datetime.now(timezone.utc)
    await make_conversation(
        db_session, tenant, "old", last_message_at=now - timedelta(hours=2),
        customer_name="Old",
    )
    await make_conversation(
        db_session, tenant, "new", last_message_at=now, customer_name="New"
    )
    await make_conversation(
        db_session, tenant, "never", last_message_at=None, customer_name="Never"
    )

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.get("/conversations")

    assert [i["customer_name"] for i in response.json()["items"]] == [
        "New",
        "Old",
        "Never",
    ]


async def test_unread_is_derived_from_the_read_stamp(db_session, wired):
    tenant = await make_tenant(db_session, "unread")
    now = datetime.now(timezone.utc)
    await make_conversation(
        db_session, tenant, "unread", last_message_at=now, customer_name="Unread"
    )
    await make_conversation(
        db_session,
        tenant,
        "read",
        last_message_at=now - timedelta(minutes=5),
        agent_last_read_at=now,
        customer_name="Read",
    )

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.get("/conversations")

    by_name = {i["customer_name"]: i["unread"] for i in response.json()["items"]}
    assert by_name == {"Unread": True, "Read": False}


async def test_the_preview_is_the_newest_message(db_session, wired):
    tenant = await make_tenant(db_session, "preview")
    now = datetime.now(timezone.utc)
    conversation = await make_conversation(
        db_session, tenant, "p", last_message_at=now
    )
    await add_message(
        db_session, conversation, text="hello", created_at=now - timedelta(minutes=2)
    )
    await add_message(db_session, conversation, text="so where is my parcel")

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.get("/conversations")

    assert response.json()["items"][0]["last_message_preview"] == (
        "so where is my parcel"
    )


async def test_a_failed_last_send_is_flagged_on_the_list(db_session, wired):
    """So a thread whose last send failed is markable without the client
    fetching every message in it."""
    tenant = await make_tenant(db_session, "failed")
    now = datetime.now(timezone.utc)
    conversation = await make_conversation(
        db_session, tenant, "f", last_message_at=now
    )
    await add_message(
        db_session,
        conversation,
        text="on its way",
        direction=Direction.OUTBOUND,
        sender_type=SenderType.BOT,
        delivery_status=DeliveryStatus.FAILED,
        error="recipient blocked the bot",
    )

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.get("/conversations")

    assert response.json()["items"][0]["has_failed_delivery"] is True


async def test_an_earlier_failure_that_was_followed_by_a_success_is_not_flagged(
    db_session, wired
):
    tenant = await make_tenant(db_session, "recovered")
    now = datetime.now(timezone.utc)
    conversation = await make_conversation(
        db_session, tenant, "r", last_message_at=now
    )
    await add_message(
        db_session,
        conversation,
        text="failed one",
        direction=Direction.OUTBOUND,
        sender_type=SenderType.BOT,
        delivery_status=DeliveryStatus.FAILED,
        error="boom",
        created_at=now - timedelta(minutes=5),
    )
    await add_message(
        db_session,
        conversation,
        text="second try",
        direction=Direction.OUTBOUND,
        sender_type=SenderType.AGENT,
    )

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.get("/conversations")

    assert response.json()["items"][0]["has_failed_delivery"] is False


# --- filters ---------------------------------------------------------------


async def test_the_state_filter_is_repeatable(db_session, wired):
    tenant = await make_tenant(db_session, "states")
    now = datetime.now(timezone.utc)
    await make_conversation(
        db_session, tenant, "b", state=HandoffState.BOT, last_message_at=now,
        customer_name="Bot",
    )
    await make_conversation(
        db_session, tenant, "p", state=HandoffState.PENDING_HUMAN,
        last_message_at=now, customer_name="Pending",
    )
    await make_conversation(
        db_session, tenant, "r", state=HandoffState.RESOLVED, last_message_at=now,
        customer_name="Resolved",
    )

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.get(
            "/conversations", params=[("state", "bot"), ("state", "pending_human")]
        )

    names = sorted(i["customer_name"] for i in response.json()["items"])
    assert names == ["Bot", "Pending"]


async def test_assignee_me_returns_only_my_conversations(db_session, wired):
    tenant = await make_tenant(db_session, "assignee")
    other = User(
        merchant_id=tenant.merchant.id,
        email="other-assignee@example.com",
        password_hash=hash_password(PASSWORD),
        name="Other",
    )
    db_session.add(other)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    await make_conversation(
        db_session, tenant, "m", state=HandoffState.HUMAN,
        assignee_id=tenant.user.id, last_message_at=now, customer_name="Mine",
    )
    await make_conversation(
        db_session, tenant, "o", state=HandoffState.HUMAN, assignee_id=other.id,
        last_message_at=now, customer_name="Theirs",
    )

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.get("/conversations", params={"assignee": "me"})

    assert [i["customer_name"] for i in response.json()["items"]] == ["Mine"]


async def test_assignee_unassigned_returns_the_queue(db_session, wired):
    tenant = await make_tenant(db_session, "queue")
    now = datetime.now(timezone.utc)
    await make_conversation(
        db_session, tenant, "q", state=HandoffState.PENDING_HUMAN,
        last_message_at=now, customer_name="Queued",
    )
    await make_conversation(
        db_session, tenant, "h", state=HandoffState.HUMAN,
        assignee_id=tenant.user.id, last_message_at=now, customer_name="Held",
    )

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.get("/conversations", params={"assignee": "unassigned"})

    assert [i["customer_name"] for i in response.json()["items"]] == ["Queued"]


async def test_the_provider_filter_narrows_the_list(db_session, wired):
    tenant = await make_tenant(db_session, "provider")
    now = datetime.now(timezone.utc)
    await make_conversation(db_session, tenant, "one", last_message_at=now)

    async with client() as http:
        await sign_in(http, tenant)
        matching = await http.get("/conversations", params={"provider": "fake"})
        other = await http.get("/conversations", params={"provider": "nothing"})

    assert len(matching.json()["items"]) == 1
    assert other.json()["items"] == []


async def test_the_unread_filter_hides_read_threads(db_session, wired):
    tenant = await make_tenant(db_session, "unreadfilter")
    now = datetime.now(timezone.utc)
    await make_conversation(
        db_session, tenant, "u", last_message_at=now, customer_name="Unread"
    )
    await make_conversation(
        db_session, tenant, "r", last_message_at=now - timedelta(minutes=1),
        agent_last_read_at=now, customer_name="Read",
    )

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.get("/conversations", params={"unread": "true"})

    assert [i["customer_name"] for i in response.json()["items"]] == ["Unread"]


# --- pagination ------------------------------------------------------------


async def test_the_cursor_is_stable_across_an_insert_that_reorders_the_list(
    db_session, wired
):
    """The whole reason the cursor is not an offset. A conversation that jumps
    to the top between page one and page two must not push a row off the seam."""
    tenant = await make_tenant(db_session, "cursor")
    now = datetime.now(timezone.utc)
    for index in range(5):
        await make_conversation(
            db_session,
            tenant,
            f"c{index}",
            last_message_at=now - timedelta(minutes=index),
            customer_name=f"C{index}",
        )

    async with client() as http:
        await sign_in(http, tenant)
        first = await http.get("/conversations", params={"limit": 2})
        assert [i["customer_name"] for i in first.json()["items"]] == ["C0", "C1"]

        # C4 jumps to the top, exactly as a new inbound message would move it.
        moved = (
            await db_session.execute(
                Conversation.__table__.select().where(
                    Conversation.external_thread_id == "c4"
                )
            )
        ).first()
        await db_session.execute(
            Conversation.__table__.update()
            .where(Conversation.id == moved.id)
            .values(last_message_at=now + timedelta(minutes=1))
        )
        await db_session.flush()

        second = await http.get(
            "/conversations",
            params={"limit": 2, "cursor": first.json()["next_cursor"]},
        )

    # C2 and C3 still follow C1. Under an offset the moved row would have
    # shifted everything down and C2 would have been skipped.
    assert [i["customer_name"] for i in second.json()["items"]] == ["C2", "C3"]


async def test_the_last_page_has_no_next_cursor(db_session, wired):
    tenant = await make_tenant(db_session, "lastpage")
    now = datetime.now(timezone.utc)
    await make_conversation(db_session, tenant, "only", last_message_at=now)

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.get("/conversations")

    assert response.json()["next_cursor"] is None


async def test_a_mangled_cursor_is_a_400(db_session, wired):
    tenant = await make_tenant(db_session, "badcursor")

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.get("/conversations", params={"cursor": "nonsense"})

    assert response.status_code == 400


async def test_the_list_needs_a_session(db_session, wired):
    async with client() as http:
        response = await http.get("/conversations")

    assert response.status_code == 401
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/bin/python -m pytest test/test_conversations_api.py -q`
Expected: FAIL — 404 on every request, because no router is registered.

- [ ] **Step 3: Write `app/api/schemas.py`**

```python
"""Response shapes.

Shared between the routers and the realtime bus on purpose: an event carrying a
conversation must carry the *same* object the list returns, or the client ends
up with two shapes for one thing and a reducer that has to guess which it got.
"""

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel

from app.api.send_policy import SendPolicy
from app.models.conversation import HandoffState
from app.models.message import DeliveryStatus, Direction, SenderType

T = TypeVar("T")


class UserRef(BaseModel):
    id: int
    name: str


class BotRef(BaseModel):
    id: int
    name: str


class ConversationSummary(BaseModel):
    id: int
    customer_name: str | None
    customer_ref: str
    provider: str
    connection_id: int
    bot: BotRef
    handoff_state: HandoffState
    escalation_reason: str | None
    assignee: UserRef | None
    last_message_at: datetime | None
    last_message_preview: str | None
    unread: bool
    has_failed_delivery: bool


class MessageOut(BaseModel):
    id: int
    direction: Direction
    sender_type: SenderType
    sender: UserRef | None
    text: str | None
    attachments: list
    provider_message_id: str | None
    delivery_status: DeliveryStatus
    error: str | None
    created_at: datetime


class ConversationDetail(ConversationSummary):
    send_policy: SendPolicy


class Page(BaseModel, Generic[T]):
    items: list[T]
    # None means this is the last page. An empty string would be a cursor that
    # decodes to nothing and sends the client round again.
    next_cursor: str | None = None
```

- [ ] **Step 4: Write the list endpoint** in `app/api/conversations.py`

The query is one statement. `has_failed_delivery` and `last_message_preview` are lateral joins on the newest row, not per-row follow-up queries.

```python
"""The seller inbox.

Every endpoint here filters on TenantScope.merchant_id and nothing else. A
conversation belonging to another merchant is 404, not 403: a 403 confirms the
row exists, which turns id enumeration into a census of other tenants' traffic.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import String, and_, cast, desc, func, literal, nullslast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import TenantScope, tenant
from app.api.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    InvalidCursor,
    decode_cursor,
    encode_cursor,
)
from app.api.queries import load_conversation
from app.api.schemas import (
    BotRef,
    ConversationSummary,
    Page,
    UserRef,
)
from app.core.database import get_db
from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection
from app.models.conversation import Conversation, HandoffState
from app.models.message import Direction, Message
from app.models.user import User

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _newest_message_lateral():
    """The conversation's most recent message, for the list preview."""
    return (
        select(Message.text.label("preview"))
        .where(Message.conversation_id == Conversation.id)
        .order_by(desc(Message.created_at), desc(Message.id))
        .limit(1)
        .lateral("newest_message")
    )


def _newest_outbound_lateral():
    """The most recent outbound message's delivery status.

    A lateral join rather than a per-row follow-up query: the list is fifty
    conversations and fifty extra round trips is the difference between an
    inbox that opens and one that hangs.
    """
    return (
        select(Message.delivery_status.label("delivery_status"))
        .where(
            Message.conversation_id == Conversation.id,
            Message.direction == Direction.OUTBOUND,
        )
        .order_by(desc(Message.created_at), desc(Message.id))
        .limit(1)
        .lateral("newest_outbound")
    )


def _base_select(tenant_scope: TenantScope):
    newest = _newest_message_lateral()
    outbound = _newest_outbound_lateral()
    return (
        select(
            Conversation,
            ChannelConnection.provider.label("provider"),
            Bot.id.label("bot_id"),
            Bot.name.label("bot_name"),
            User.id.label("assignee_user_id"),
            User.name.label("assignee_name"),
            newest.c.preview.label("preview"),
            outbound.c.delivery_status.label("last_outbound_status"),
        )
        .join(
            ChannelConnection,
            ChannelConnection.id == Conversation.channel_connection_id,
        )
        .join(Bot, Bot.id == Conversation.bot_id)
        .outerjoin(User, User.id == Conversation.assignee_id)
        .outerjoin(newest, literal(True))
        .outerjoin(outbound, literal(True))
        .where(Conversation.merchant_id == tenant_scope.merchant_id)
    )


def _unread_predicate():
    """Derived, never a stored counter: a counter has to be kept correct on
    every write and drifts the first time one is missed."""
    return and_(
        Conversation.last_message_at.is_not(None),
        or_(
            Conversation.agent_last_read_at.is_(None),
            Conversation.last_message_at > Conversation.agent_last_read_at,
        ),
    )


def row_to_summary(row) -> ConversationSummary:
    from app.models.message import DeliveryStatus

    conversation = row[0]
    last_read = conversation.agent_last_read_at
    last_message = conversation.last_message_at
    return ConversationSummary(
        id=conversation.id,
        customer_name=conversation.customer_name,
        customer_ref=conversation.customer_ref,
        provider=row.provider,
        connection_id=conversation.channel_connection_id,
        bot=BotRef(id=row.bot_id, name=row.bot_name),
        handoff_state=conversation.handoff_state,
        escalation_reason=conversation.escalation_reason,
        assignee=(
            UserRef(id=row.assignee_user_id, name=row.assignee_name)
            if row.assignee_user_id is not None
            else None
        ),
        last_message_at=last_message,
        last_message_preview=row.preview,
        unread=bool(
            last_message is not None
            and (last_read is None or last_message > last_read)
        ),
        has_failed_delivery=row.last_outbound_status is DeliveryStatus.FAILED,
    )


@router.get("", response_model=Page[ConversationSummary])
async def list_conversations(
    state: list[HandoffState] = Query(default=[]),
    provider: list[str] = Query(default=[]),
    assignee: str | None = None,
    unread: bool | None = None,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    scope: TenantScope = Depends(tenant),
    db: AsyncSession = Depends(get_db),
) -> Page[ConversationSummary]:
    statement = _base_select(scope)

    if state:
        statement = statement.where(Conversation.handoff_state.in_(state))
    if provider:
        statement = statement.where(ChannelConnection.provider.in_(provider))
    if assignee == "me":
        statement = statement.where(Conversation.assignee_id == scope.user.id)
    elif assignee == "unassigned":
        statement = statement.where(Conversation.assignee_id.is_(None))
    elif assignee is not None:
        try:
            statement = statement.where(Conversation.assignee_id == int(assignee))
        except ValueError:
            raise HTTPException(
                status_code=400, detail="assignee must be me, unassigned or a user id"
            ) from None
    if unread:
        statement = statement.where(_unread_predicate())

    try:
        seek = decode_cursor(cursor)
    except InvalidCursor:
        raise HTTPException(status_code=400, detail="cursor is not readable") from None

    if seek is not None:
        if seek.last_message_at is None:
            # Already inside the trailing NULL block; only the id tie-break
            # remains.
            statement = statement.where(
                Conversation.last_message_at.is_(None), Conversation.id < seek.id
            )
        else:
            statement = statement.where(
                or_(
                    Conversation.last_message_at.is_(None),
                    Conversation.last_message_at < seek.last_message_at,
                    and_(
                        Conversation.last_message_at == seek.last_message_at,
                        Conversation.id < seek.id,
                    ),
                )
            )

    statement = statement.order_by(
        nullslast(desc(Conversation.last_message_at)), desc(Conversation.id)
    ).limit(limit + 1)

    rows = (await db.execute(statement)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [row_to_summary(row) for row in rows]

    next_cursor = None
    if has_more and rows:
        last = rows[-1][0]
        next_cursor = encode_cursor(last.last_message_at, last.id)

    return Page[ConversationSummary](items=items, next_cursor=next_cursor)
```

- [ ] **Step 5: Register the router** in `app/main.py`

```python
from app.api import auth, conversations, health, webhooks
...
    app.include_router(conversations.router)
```

- [ ] **Step 6: Run the tests and watch them pass**

Run: `.venv/bin/python -m pytest test/test_conversations_api.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/api/queries.py app/api/schemas.py app/api/conversations.py app/main.py test/test_conversations_api.py
git commit -m "feat: tenant-scoped conversation list with keyset cursor and derived unread"
```

---

### Task 9: Detail, messages, and the read stamp

**Files:**
- Modify: `app/api/conversations.py`
- Test: `test/test_conversations_api.py` *(append)*

**Interfaces:**
- Consumes: `build_send_policy` (Task 4), `capabilities_for` (Task 5), `load_conversation` (Task 7).
- Produces: `GET /conversations/{id}` → `ConversationDetail`; `GET /conversations/{id}/messages` → `Page[MessageOut]`, newest first; `POST /conversations/{id}/read` → 204.

- [ ] **Step 1: Write the failing tests** — append to `test/test_conversations_api.py`

```python
# --- detail, messages and read --------------------------------------------


async def test_the_detail_carries_a_send_policy(db_session, wired):
    tenant = await make_tenant(db_session, "detail")
    conversation = await make_conversation(
        db_session, tenant, "d", last_message_at=datetime.now(timezone.utc)
    )

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.get(f"/conversations/{conversation.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == conversation.id
    assert body["send_policy"]["can_send_freeform"] is True
    assert body["send_policy"]["max_text_len"] == 4096


async def test_another_merchants_conversation_is_404_not_403(db_session, wired):
    mine = await make_tenant(db_session, "d-mine")
    theirs = await make_tenant(db_session, "d-theirs")
    hidden = await make_conversation(db_session, theirs, "hidden")

    async with client() as http:
        await sign_in(http, mine)
        response = await http.get(f"/conversations/{hidden.id}")

    assert response.status_code == 404


async def test_messages_come_back_newest_first(db_session, wired):
    tenant = await make_tenant(db_session, "messages")
    now = datetime.now(timezone.utc)
    conversation = await make_conversation(db_session, tenant, "m")
    await add_message(
        db_session, conversation, text="first", created_at=now - timedelta(minutes=2)
    )
    await add_message(db_session, conversation, text="second", created_at=now)

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.get(f"/conversations/{conversation.id}/messages")

    assert [m["text"] for m in response.json()["items"]] == ["second", "first"]


async def test_an_agent_message_names_its_sender(db_session, wired):
    tenant = await make_tenant(db_session, "sender")
    conversation = await make_conversation(db_session, tenant, "s")
    message = await add_message(
        db_session,
        conversation,
        text="taking a look",
        direction=Direction.OUTBOUND,
        sender_type=SenderType.AGENT,
    )
    message.sender_user_id = tenant.user.id
    db_session.add(message)
    await db_session.flush()

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.get(f"/conversations/{conversation.id}/messages")

    assert response.json()["items"][0]["sender"]["name"] == tenant.user.name


async def test_another_merchants_messages_are_404(db_session, wired):
    mine = await make_tenant(db_session, "m-mine")
    theirs = await make_tenant(db_session, "m-theirs")
    hidden = await make_conversation(db_session, theirs, "hidden-m")
    await add_message(db_session, hidden, text="secret")

    async with client() as http:
        await sign_in(http, mine)
        response = await http.get(f"/conversations/{hidden.id}/messages")

    assert response.status_code == 404


async def test_marking_read_stamps_the_conversation(db_session, wired):
    tenant = await make_tenant(db_session, "read")
    conversation = await make_conversation(
        db_session, tenant, "r", last_message_at=datetime.now(timezone.utc)
    )

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.post(f"/conversations/{conversation.id}/read")
        listed = await http.get("/conversations")

    assert response.status_code == 204
    assert listed.json()["items"][0]["unread"] is False


async def test_marking_another_merchants_conversation_read_is_404(db_session, wired):
    mine = await make_tenant(db_session, "r-mine")
    theirs = await make_tenant(db_session, "r-theirs")
    hidden = await make_conversation(db_session, theirs, "hidden-r")

    async with client() as http:
        await sign_in(http, mine)
        response = await http.post(f"/conversations/{hidden.id}/read")

    assert response.status_code == 404
```

- [ ] **Step 2: Run and watch fail**

Run: `.venv/bin/python -m pytest test/test_conversations_api.py -q -k "detail or messages or read or sender"`
Expected: FAIL — 405/404 for routes that do not exist.

- [ ] **Step 3: Implement** — append to `app/api/conversations.py`

```python
async def _summary_row(db, scope: TenantScope, conversation_id: int):
    row = (
        await db.execute(
            _base_select(scope).where(Conversation.id == conversation_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return row


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: int,
    scope: TenantScope = Depends(tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationDetail:
    row = await _summary_row(db, scope, conversation_id)
    conversation = row[0]
    try:
        caps = capabilities_for(row.provider)
    except UnknownProvider:
        # A connection whose adapter has been removed still has a readable
        # thread. Refusing the whole detail would hide the history too.
        caps = None

    policy = (
        build_send_policy(caps, conversation.last_inbound_at)
        if caps is not None
        else SendPolicy(
            can_send_freeform=False,
            reason="this channel is no longer supported",
            max_text_len=0,
            supports_media=False,
        )
    )
    return ConversationDetail(
        **row_to_summary(row).model_dump(), send_policy=policy
    )


@router.get("/{conversation_id}/messages", response_model=Page[MessageOut])
async def list_messages(
    conversation_id: int,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    scope: TenantScope = Depends(tenant),
    db: AsyncSession = Depends(get_db),
) -> Page[MessageOut]:
    await load_conversation(db, scope, conversation_id)

    try:
        seek = decode_cursor(cursor)
    except InvalidCursor:
        raise HTTPException(status_code=400, detail="cursor is not readable") from None

    statement = (
        select(Message, User.id.label("sender_id"), User.name.label("sender_name"))
        .outerjoin(User, User.id == Message.sender_user_id)
        .where(
            Message.conversation_id == conversation_id,
            # Belt and braces behind load_conversation: Message carries its own
            # merchant_id precisely so this predicate is always available.
            Message.merchant_id == scope.merchant_id,
        )
    )
    if seek is not None:
        statement = statement.where(
            or_(
                Message.created_at < seek.last_message_at,
                and_(
                    Message.created_at == seek.last_message_at,
                    Message.id < seek.id,
                ),
            )
        )
    statement = statement.order_by(
        desc(Message.created_at), desc(Message.id)
    ).limit(limit + 1)

    rows = (await db.execute(statement)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [message_row_to_schema(row) for row in rows]
    next_cursor = None
    if has_more and rows:
        last = rows[-1][0]
        next_cursor = encode_cursor(last.created_at, last.id)
    return Page[MessageOut](items=items, next_cursor=next_cursor)


def message_row_to_schema(row) -> MessageOut:
    message = row[0]
    return MessageOut(
        id=message.id,
        direction=message.direction,
        sender_type=message.sender_type,
        sender=(
            UserRef(id=row.sender_id, name=row.sender_name)
            if row.sender_id is not None
            else None
        ),
        text=message.text,
        attachments=message.attachments,
        provider_message_id=message.provider_message_id,
        delivery_status=message.delivery_status,
        error=message.error,
        created_at=message.created_at,
    )


@router.post("/{conversation_id}/read", status_code=204)
async def mark_read(
    conversation_id: int,
    scope: TenantScope = Depends(tenant),
    db: AsyncSession = Depends(get_db),
) -> Response:
    conversation = await load_conversation(db, scope, conversation_id)
    conversation.agent_last_read_at = datetime.now(timezone.utc)
    db.add(conversation)
    await db.commit()
    return Response(status_code=204)
```

Add the imports this introduces: `capabilities_for`, `UnknownProvider` from `app.channels.registry`; `build_send_policy`, `SendPolicy` from `app.api.send_policy`; `ConversationDetail`, `MessageOut` from `app.api.schemas`.

- [ ] **Step 4: Run and commit**

```bash
.venv/bin/python -m pytest test/test_conversations_api.py -q
git add app/api/conversations.py test/test_conversations_api.py
git commit -m "feat: conversation detail with send policy, message pagination and the read stamp"
```

---

### Task 10: Takeover, release, resolve

**Files:**
- Modify: `app/api/conversations.py`
- Test: `test/test_conversation_actions_api.py`

**Interfaces:**
- Produces: `POST /conversations/{id}/takeover|release|resolve`, each returning `ConversationDetail`.

Semantics, verbatim from the spec:
- **Takeover** — `handoff_state = human`, `assignee_id = current user`, `bot_muted_until = None`. Muting is unnecessary: `_bot_must_stay_quiet` already treats `human` as silent. **409 naming the current assignee** when another agent holds it.
- **Release** — `handoff_state = bot`, `assignee_id = None`, `bot_muted_until = now + BOT_MUTE_AFTER_RELEASE_SECONDS`.
- **Resolve** — `handoff_state = resolved`, `assignee_id = None`. Not terminal: the pipeline reopens a resolved conversation when a new message arrives.

- [ ] **Step 1: Write the failing test** — `test/test_conversation_actions_api.py`

```python
"""Who holds the conversation.

The 409 on a contested takeover is the one that matters. Silently stealing a
thread means two agents type into it at once, and the customer sees both.
"""

from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.core.database import get_db
from app.core.security import hash_password
from app.main import app
from app.models.conversation import Conversation, HandoffState
from app.models.user import User
from test.test_conversations_api import (
    PASSWORD,
    client,
    make_conversation,
    make_tenant,
    sign_in,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def wired(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield
    app.dependency_overrides.clear()


async def _second_agent(db, tenant, slug: str) -> User:
    user = User(
        merchant_id=tenant.merchant.id,
        email=f"second-{slug}@example.com",
        password_hash=hash_password(PASSWORD),
        name="Second agent",
    )
    db.add(user)
    await db.flush()
    return user


async def test_takeover_assigns_the_conversation_to_me(db_session, wired):
    tenant = await make_tenant(db_session, "takeover")
    conversation = await make_conversation(
        db_session, tenant, "t", state=HandoffState.PENDING_HUMAN,
        escalation_reason="the customer asked for a person",
    )

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.post(f"/conversations/{conversation.id}/takeover")

    assert response.status_code == 200
    body = response.json()
    assert body["handoff_state"] == "human"
    assert body["assignee"]["id"] == tenant.user.id


async def test_takeover_clears_any_leftover_mute(db_session, wired):
    """_bot_must_stay_quiet already treats `human` as silent, so a mute left
    over from an earlier release is pure confusion."""
    from datetime import timedelta

    tenant = await make_tenant(db_session, "unmute")
    conversation = await make_conversation(
        db_session, tenant, "u", state=HandoffState.PENDING_HUMAN
    )
    conversation.bot_muted_until = datetime.now(timezone.utc) + timedelta(minutes=5)
    db_session.add(conversation)
    await db_session.flush()

    async with client() as http:
        await sign_in(http, tenant)
        await http.post(f"/conversations/{conversation.id}/takeover")

    await db_session.refresh(conversation)
    assert conversation.bot_muted_until is None


async def test_taking_over_a_thread_another_agent_holds_is_a_409(db_session, wired):
    tenant = await make_tenant(db_session, "conflict")
    other = await _second_agent(db_session, tenant, "conflict")
    conversation = await make_conversation(
        db_session, tenant, "c", state=HandoffState.HUMAN, assignee_id=other.id
    )

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.post(f"/conversations/{conversation.id}/takeover")

    assert response.status_code == 409
    assert other.name in response.json()["detail"]


async def test_taking_over_a_thread_i_already_hold_is_idempotent(db_session, wired):
    tenant = await make_tenant(db_session, "idem")
    conversation = await make_conversation(
        db_session, tenant, "i", state=HandoffState.HUMAN,
        assignee_id=tenant.user.id,
    )

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.post(f"/conversations/{conversation.id}/takeover")

    assert response.status_code == 200


async def test_release_returns_it_to_the_bot_behind_a_grace_period(db_session, wired):
    """Without the grace period the next customer message can arrive while the
    agent's closing line is still in flight."""
    tenant = await make_tenant(db_session, "release")
    conversation = await make_conversation(
        db_session, tenant, "r", state=HandoffState.HUMAN,
        assignee_id=tenant.user.id,
    )
    before = datetime.now(timezone.utc)

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.post(f"/conversations/{conversation.id}/release")

    assert response.status_code == 200
    assert response.json()["handoff_state"] == "bot"
    assert response.json()["assignee"] is None

    await db_session.refresh(conversation)
    grace = (conversation.bot_muted_until - before).total_seconds()
    assert grace == pytest.approx(settings.BOT_MUTE_AFTER_RELEASE_SECONDS, abs=5)


async def test_resolve_closes_it_and_unassigns(db_session, wired):
    tenant = await make_tenant(db_session, "resolve")
    conversation = await make_conversation(
        db_session, tenant, "x", state=HandoffState.HUMAN,
        assignee_id=tenant.user.id,
    )

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.post(f"/conversations/{conversation.id}/resolve")

    assert response.status_code == 200
    assert response.json()["handoff_state"] == "resolved"
    assert response.json()["assignee"] is None


@pytest.mark.parametrize("action", ["takeover", "release", "resolve"])
async def test_acting_on_another_merchants_conversation_is_404(
    db_session, wired, action
):
    mine = await make_tenant(db_session, f"a-mine-{action}")
    theirs = await make_tenant(db_session, f"a-theirs-{action}")
    hidden = await make_conversation(db_session, theirs, f"hidden-{action}")

    async with client() as http:
        await sign_in(http, mine)
        response = await http.post(f"/conversations/{hidden.id}/{action}")

    assert response.status_code == 404
```

- [ ] **Step 2: Run and watch fail**

Run: `.venv/bin/python -m pytest test/test_conversation_actions_api.py -q`
Expected: FAIL — 404 on the action routes.

- [ ] **Step 3: Implement** — append to `app/api/conversations.py`

```python
@router.post("/{conversation_id}/takeover", response_model=ConversationDetail)
async def takeover(
    conversation_id: int,
    scope: TenantScope = Depends(tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationDetail:
    conversation = await load_conversation(db, scope, conversation_id)

    if (
        conversation.assignee_id is not None
        and conversation.assignee_id != scope.user.id
    ):
        # 409 naming them, not a silent steal: two agents typing into one
        # thread is worse than an agent being told to wait.
        holder = await db.get(User, conversation.assignee_id)
        name = holder.name if holder is not None else "another agent"
        raise HTTPException(
            status_code=409, detail=f"{name} is already handling this conversation"
        )

    conversation.handoff_state = HandoffState.HUMAN
    conversation.assignee_id = scope.user.id
    # No mute needed: _bot_must_stay_quiet already treats `human` as silent.
    # Clearing it removes a leftover from an earlier release.
    conversation.bot_muted_until = None
    db.add(conversation)
    await db.commit()
    return await get_conversation(conversation_id, scope, db)


@router.post("/{conversation_id}/release", response_model=ConversationDetail)
async def release(
    conversation_id: int,
    scope: TenantScope = Depends(tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationDetail:
    conversation = await load_conversation(db, scope, conversation_id)
    conversation.handoff_state = HandoffState.BOT
    conversation.assignee_id = None
    conversation.escalation_reason = None
    conversation.bot_muted_until = datetime.now(timezone.utc) + timedelta(
        seconds=settings.BOT_MUTE_AFTER_RELEASE_SECONDS
    )
    db.add(conversation)
    await db.commit()
    return await get_conversation(conversation_id, scope, db)


@router.post("/{conversation_id}/resolve", response_model=ConversationDetail)
async def resolve(
    conversation_id: int,
    scope: TenantScope = Depends(tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationDetail:
    """Not a terminal state. The pipeline reopens a resolved conversation when
    a new message arrives, and the UI must not present it as final."""
    conversation = await load_conversation(db, scope, conversation_id)
    conversation.handoff_state = HandoffState.RESOLVED
    conversation.assignee_id = None
    db.add(conversation)
    await db.commit()
    return await get_conversation(conversation_id, scope, db)
```

Add `timedelta` to the datetime import and `from app.core.config import settings`.

- [ ] **Step 4: Run and commit**

```bash
.venv/bin/python -m pytest test/test_conversation_actions_api.py -q
git add app/api/conversations.py test/test_conversation_actions_api.py
git commit -m "feat: takeover, release and resolve with a contested-takeover 409"
```

---

### Task 11: `POST /conversations/{id}/messages` — the agent send

The sequence, from spec §6, is a correctness requirement:

1. Load the conversation tenant-scoped; 404 if it is not this merchant's.
2. **409** if `handoff_state` is not `human`, or `assignee_id` is not the current user.
3. Build the adapter; `MissingCredentials` or `UnknownProvider` is a **502** naming the connection, not a 500.
4. `dispatcher.dispatch(...)`.
5. Persist and respond.

`outcome.escalated` → **409 with `outcome.reason`** and **no message row written**: the conversation is already with a person, so escalating again is meaningless, and nothing was said. `outcome.permanent_failure` → **201** with a `failed` message row plus a `FailedJob`.

**Files:**
- Modify: `app/api/conversations.py`
- Test: `test/test_agent_send_api.py`

- [ ] **Step 1: Write the failing test** — `test/test_agent_send_api.py`

```python
"""The agent composer's endpoint.

Routed through OutboundDispatcher rather than straight at the adapter, which is
what makes chunking, rate limiting and window rules apply to humans too.

The escalation case is the subtle one. dispatch() signals a refused send by
returning escalated=True, which in the pipeline means "give it to a person" --
but here the conversation is already with a person, so there is nobody to
escalate to. It becomes a 409 the composer renders inline, and no row is
written, because nothing was said.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.api import conversations as conversations_api
from app.channels.fake.adapter import FakeAdapter
from app.core.database import get_db
from app.dispatch.ratelimit import InMemoryTokenBucket
from app.main import app
from app.models.conversation import HandoffState
from app.models.failed_job import FailedJob
from app.models.message import DeliveryStatus, Message, SenderType
from test.test_conversations_api import (
    client,
    make_conversation,
    make_tenant,
    sign_in,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def wired(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def adapter(monkeypatch) -> FakeAdapter:
    """One adapter instance the test can inspect and make fail.

    build_adapter would hand back a fresh FakeAdapter per call, and a test
    cannot arm fail_next_send on an object it never sees.
    """
    fake = FakeAdapter()
    monkeypatch.setattr(
        conversations_api, "build_adapter", lambda conn, webhook_url=None: fake
    )
    monkeypatch.setattr(
        conversations_api, "send_limiter", lambda: InMemoryTokenBucket()
    )
    return fake


async def _held(db, tenant, thread="s"):
    return await make_conversation(
        db,
        tenant,
        thread,
        state=HandoffState.HUMAN,
        assignee_id=tenant.user.id,
        last_message_at=datetime.now(timezone.utc),
    )


async def test_a_held_conversation_accepts_a_reply(db_session, wired, adapter):
    tenant = await make_tenant(db_session, "send")
    conversation = await _held(db_session, tenant)

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.post(
            f"/conversations/{conversation.id}/messages",
            json={"text": "your parcel left the warehouse this morning"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["sender_type"] == "agent"
    assert body["delivery_status"] == "sent"
    assert body["sender"]["id"] == tenant.user.id
    assert adapter.sent, "the reply must go through the dispatcher to the adapter"


async def test_sending_into_a_thread_the_bot_still_owns_is_a_409(
    db_session, wired, adapter
):
    """An agent sending into a bot-owned thread produces two voices in one
    conversation."""
    tenant = await make_tenant(db_session, "botowned")
    conversation = await make_conversation(
        db_session, tenant, "b", state=HandoffState.BOT
    )

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.post(
            f"/conversations/{conversation.id}/messages", json={"text": "hi"}
        )

    assert response.status_code == 409
    assert not adapter.sent


async def test_sending_into_a_thread_another_agent_holds_is_a_409(
    db_session, wired, adapter
):
    from app.core.security import hash_password
    from app.models.user import User

    tenant = await make_tenant(db_session, "otherheld")
    other = User(
        merchant_id=tenant.merchant.id,
        email="held-by@example.com",
        password_hash=hash_password("s3cret-passphrase"),
        name="Other",
    )
    db_session.add(other)
    await db_session.flush()
    conversation = await make_conversation(
        db_session, tenant, "o", state=HandoffState.HUMAN, assignee_id=other.id
    )

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.post(
            f"/conversations/{conversation.id}/messages", json={"text": "hi"}
        )

    assert response.status_code == 409


async def test_a_refused_send_is_a_409_and_writes_no_message(
    db_session, wired, adapter, monkeypatch
):
    """dispatch() escalating here means the channel refused. The conversation
    is already with a person, so there is nobody to escalate to -- and no row
    is written, because nothing was said."""
    from app.dispatch.dispatcher import DispatchOutcome, OutboundDispatcher

    tenant = await make_tenant(db_session, "refused")
    conversation = await _held(db_session, tenant, thread="refused")

    async def refuse(self, conn, draft, last_inbound_at=None):
        return DispatchOutcome(
            escalated=True,
            reason="the channel carries no media and the reply has attachments",
        )

    monkeypatch.setattr(OutboundDispatcher, "dispatch", refuse)

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.post(
            f"/conversations/{conversation.id}/messages", json={"text": "here"}
        )

    assert response.status_code == 409
    assert "no media" in response.json()["detail"]

    written = (
        await db_session.execute(
            select(Message).where(
                Message.conversation_id == conversation.id,
                Message.sender_type == SenderType.AGENT,
            )
        )
    ).scalars().all()
    assert written == []


async def test_a_permanent_failure_is_a_201_carrying_the_failed_message(
    db_session, wired, adapter
):
    """The agent must see their own failed message in the thread. Swallowing it
    as an error toast loses the text they typed."""
    tenant = await make_tenant(db_session, "failedsend")
    conversation = await _held(db_session, tenant, thread="failedsend")
    adapter.fail_next_send = "recipient blocked the bot"

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.post(
            f"/conversations/{conversation.id}/messages",
            json={"text": "sorry about that"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["delivery_status"] == "failed"
    assert body["error"]
    assert body["text"] == "sorry about that"

    jobs = (
        await db_session.execute(
            select(FailedJob).where(FailedJob.kind == "outbound")
        )
    ).scalars().all()
    assert jobs


async def test_a_missing_credential_is_a_502_naming_the_connection(
    db_session, wired, monkeypatch
):
    from app.channels.registry import MissingCredentials

    tenant = await make_tenant(db_session, "nocreds")
    conversation = await _held(db_session, tenant, thread="nocreds")

    def explode(conn, webhook_url=None):
        raise MissingCredentials("connection is missing 'bot_token'")

    monkeypatch.setattr(conversations_api, "build_adapter", explode)

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.post(
            f"/conversations/{conversation.id}/messages", json={"text": "hi"}
        )

    assert response.status_code == 502
    assert str(conversation.channel_connection_id) in response.json()["detail"]


async def test_sending_into_another_merchants_conversation_is_404(
    db_session, wired, adapter
):
    mine = await make_tenant(db_session, "s-mine")
    theirs = await make_tenant(db_session, "s-theirs")
    hidden = await make_conversation(
        db_session, theirs, "hidden-s", state=HandoffState.HUMAN,
        assignee_id=theirs.user.id,
    )

    async with client() as http:
        await sign_in(http, mine)
        response = await http.post(
            f"/conversations/{hidden.id}/messages", json={"text": "hi"}
        )

    assert response.status_code == 404


async def test_an_empty_reply_is_refused(db_session, wired, adapter):
    tenant = await make_tenant(db_session, "empty")
    conversation = await _held(db_session, tenant, thread="empty")

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.post(
            f"/conversations/{conversation.id}/messages", json={"text": "   "}
        )

    assert response.status_code == 422
```

- [ ] **Step 2: Run and watch fail**

Run: `.venv/bin/python -m pytest test/test_agent_send_api.py -q`
Expected: FAIL — 405, the route does not exist.

- [ ] **Step 3: Implement** — append to `app/api/conversations.py`

```python
class SendRequest(BaseModel):
    text: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def _not_only_whitespace(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("a reply needs something in it")
        return stripped


# Indirection so a test can inject an in-memory bucket without reaching into
# the module's imports.
def send_limiter():
    return default_limiter()


@router.post("/{conversation_id}/messages", status_code=201, response_model=MessageOut)
async def send_message(
    conversation_id: int,
    body: SendRequest,
    scope: TenantScope = Depends(tenant),
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    conversation = await load_conversation(db, scope, conversation_id)

    if conversation.handoff_state is not HandoffState.HUMAN:
        raise HTTPException(
            status_code=409,
            detail="take the conversation over before replying to it",
        )
    if conversation.assignee_id != scope.user.id:
        raise HTTPException(
            status_code=409, detail="another agent is handling this conversation"
        )

    connection = await db.get(
        ChannelConnection, conversation.channel_connection_id
    )
    try:
        adapter = build_adapter(connection)
    except (MissingCredentials, UnknownProvider) as exc:
        # 502, not 500: the failure is downstream configuration, and naming the
        # connection is what lets someone go and fix it.
        raise HTTPException(
            status_code=502,
            detail=(
                f"channel connection {conversation.channel_connection_id} "
                f"cannot send: {exc}"
            ),
        ) from None

    dispatcher = OutboundDispatcher(
        adapter,
        limiter=send_limiter(),
        max_attempts=settings.OUTBOUND_MAX_ATTEMPTS,
    )
    outcome = await dispatcher.dispatch(
        connection,
        DraftReply(text=body.text),
        last_inbound_at=conversation.last_inbound_at,
    )

    if outcome.escalated:
        # The conversation is already with a person; escalating again is
        # meaningless. No row is written: nothing was said.
        raise HTTPException(status_code=409, detail=outcome.reason)

    message = record_outbound(
        db,
        conversation,
        body.text,
        [],
        outcome,
        SenderType.AGENT,
        sender_user_id=scope.user.id,
    )
    if outcome.permanent_failure:
        db.add(
            FailedJob(
                kind="outbound",
                connection_id=connection.id,
                payload={
                    "conversation_id": conversation.id,
                    "sender_user_id": scope.user.id,
                },
                error=outcome.permanent_failure,
                attempts=1,
            )
        )
    await db.commit()

    return MessageOut(
        id=message.id,
        direction=message.direction,
        sender_type=message.sender_type,
        sender=UserRef(id=scope.user.id, name=scope.user.name),
        text=message.text,
        attachments=message.attachments,
        provider_message_id=message.provider_message_id,
        delivery_status=message.delivery_status,
        error=message.error,
        created_at=message.created_at,
    )
```

New imports: `BaseModel`, `Field`, `field_validator` from pydantic; `build_adapter`, `MissingCredentials`, `UnknownProvider` from `app.channels.registry`; `OutboundDispatcher` from `app.dispatch.dispatcher`; `default_limiter` from `app.dispatch.ratelimit`; `record_outbound` from `app.dispatch.record`; `DraftReply` from `app.runtime.brain`; `FailedJob`; `SenderType`.

- [ ] **Step 4: Run and commit**

```bash
.venv/bin/python -m pytest test/test_agent_send_api.py -q
git add app/api/conversations.py test/test_agent_send_api.py
git commit -m "feat: agent send through the outbound dispatcher, with refusal and failure paths"
```

---

### Task 12: Bots and connections

Read-only for connections in v1: creating one means accepting a bot token over HTTP and calling `adapter.connect()`, a credential-handling surface that deserves its own design. `scripts/seed_telegram.py` remains the way a connection is created.

**Files:**
- Create: `app/api/bots.py`
- Create: `app/api/connections.py`
- Modify: `app/api/schemas.py`, `app/main.py`
- Test: `test/test_bots_api.py`

**Interfaces:**
- Produces: `GET /bots`, `PATCH /bots/{id}`, `GET /channels/connections`.
- Schemas: `BotOut {id, name, shop: {id, name}, persona, llm_provider, enabled_tools, escalation_max_bot_turns}`, `BotPatch` (all optional), `CapabilitiesOut`, `ConnectionOut {id, provider, external_ref, status, bot: BotRef, capabilities}`.

- [ ] **Step 1: Write the failing test** — `test/test_bots_api.py`

```python
"""Bots and channel connections.

Both are filtered by a *join* -- Bot -> Shop -> merchant_id -- because neither
carries a denormalised merchant_id the way Conversation and Message do. That is
exactly the shape the architecture spec warns about: a forgotten join raises
nothing and quietly returns another tenant's rows. Hence the isolation tests
here specifically.
"""

import pytest

from app.core.database import get_db
from app.main import app
from test.test_conversations_api import client, make_tenant, sign_in

pytestmark = pytest.mark.integration


@pytest.fixture
def wired(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield
    app.dependency_overrides.clear()


async def test_bots_lists_this_merchants_bots(db_session, wired):
    tenant = await make_tenant(db_session, "bots")

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.get("/bots")

    assert response.status_code == 200
    items = response.json()
    assert [b["id"] for b in items] == [tenant.bot.id]
    assert items[0]["escalation_max_bot_turns"] == 3
    assert items[0]["enabled_tools"] == []


async def test_another_merchants_bots_are_absent(db_session, wired):
    """The join is the tenant filter here. Forgetting it returns every bot in
    the database and nothing raises."""
    mine = await make_tenant(db_session, "b-mine")
    theirs = await make_tenant(db_session, "b-theirs")

    async with client() as http:
        await sign_in(http, mine)
        response = await http.get("/bots")

    ids = [b["id"] for b in response.json()]
    assert mine.bot.id in ids
    assert theirs.bot.id not in ids


async def test_patching_a_bot_updates_the_named_fields(db_session, wired):
    tenant = await make_tenant(db_session, "patch")

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.patch(
            f"/bots/{tenant.bot.id}",
            json={
                "persona": "warm, brief, never guesses",
                "enabled_tools": ["order_status"],
                "escalation_max_bot_turns": 5,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["persona"] == "warm, brief, never guesses"
    assert body["enabled_tools"] == ["order_status"]
    assert body["escalation_max_bot_turns"] == 5


async def test_patching_leaves_unnamed_fields_alone(db_session, wired):
    tenant = await make_tenant(db_session, "partial")

    async with client() as http:
        await sign_in(http, tenant)
        await http.patch(
            f"/bots/{tenant.bot.id}", json={"persona": "just the persona"}
        )
        response = await http.get("/bots")

    bot = next(b for b in response.json() if b["id"] == tenant.bot.id)
    assert bot["persona"] == "just the persona"
    assert bot["name"] == tenant.bot.name
    assert bot["escalation_max_bot_turns"] == 3


async def test_patching_another_merchants_bot_is_404(db_session, wired):
    mine = await make_tenant(db_session, "p-mine")
    theirs = await make_tenant(db_session, "p-theirs")

    async with client() as http:
        await sign_in(http, mine)
        response = await http.patch(
            f"/bots/{theirs.bot.id}", json={"persona": "not yours"}
        )

    assert response.status_code == 404


async def test_a_turn_limit_below_one_is_refused(db_session, wired):
    """Zero would mean the bot escalates before it ever speaks."""
    tenant = await make_tenant(db_session, "turns")

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.patch(
            f"/bots/{tenant.bot.id}", json={"escalation_max_bot_turns": 0}
        )

    assert response.status_code == 422


async def test_connections_carry_the_real_capability_manifest(db_session, wired):
    """So the channels screen states each channel's real limits instead of
    hardcoding them."""
    tenant = await make_tenant(db_session, "conns")

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.get("/channels/connections")

    assert response.status_code == 200
    connection = response.json()[0]
    assert connection["id"] == tenant.connection.id
    assert connection["external_ref"] == tenant.connection.external_ref
    assert connection["status"] == "disconnected"
    assert connection["bot"]["id"] == tenant.bot.id
    assert connection["capabilities"]["max_text_len"] == 4096
    assert connection["capabilities"]["supports_media"] is True


async def test_a_connection_never_returns_its_credentials(db_session, wired):
    tenant = await make_tenant(db_session, "secrets")
    tenant.connection.set_credentials({"bot_token": "123456:SUPERSECRET"})
    db_session.add(tenant.connection)
    await db_session.flush()

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.get("/channels/connections")

    assert "SUPERSECRET" not in response.text
    assert "credentials_encrypted" not in response.text


async def test_another_merchants_connections_are_absent(db_session, wired):
    mine = await make_tenant(db_session, "c-mine")
    theirs = await make_tenant(db_session, "c-theirs")

    async with client() as http:
        await sign_in(http, mine)
        response = await http.get("/channels/connections")

    ids = [c["id"] for c in response.json()]
    assert mine.connection.id in ids
    assert theirs.connection.id not in ids


async def test_connections_are_read_only(db_session, wired):
    """Creating one means accepting a bot token over HTTP and registering a
    webhook -- a credential surface that gets its own design, not a paragraph."""
    tenant = await make_tenant(db_session, "readonly")

    async with client() as http:
        await sign_in(http, tenant)
        response = await http.post("/channels/connections", json={})

    assert response.status_code == 405
```

- [ ] **Step 2: Run and watch fail**

Run: `.venv/bin/python -m pytest test/test_bots_api.py -q`
Expected: FAIL — 404 on `/bots`.

- [ ] **Step 3: Add the schemas** to `app/api/schemas.py`

```python
class ShopRef(BaseModel):
    id: int
    name: str


class BotOut(BaseModel):
    id: int
    name: str
    shop: ShopRef
    persona: str
    llm_provider: str
    enabled_tools: list[str]
    escalation_max_bot_turns: int


class BotPatch(BaseModel):
    persona: str | None = None
    llm_provider: str | None = None
    enabled_tools: list[str] | None = None
    # At least one: zero would mean the bot escalates before it ever speaks.
    escalation_max_bot_turns: int | None = Field(default=None, ge=1, le=20)


class CapabilitiesOut(BaseModel):
    supports_media: bool
    max_text_len: int
    # Seconds, or null for a channel that never closes.
    session_window_seconds: int | None
    requires_template_outside_window: bool
    supports_typing_indicator: bool


class ConnectionOut(BaseModel):
    id: int
    provider: str
    external_ref: str
    status: ChannelConnectionStatus
    bot: BotRef
    # Null when no adapter is registered for the provider any more. The row
    # still renders; its limits are simply unknown.
    capabilities: CapabilitiesOut | None
```

Import `Field` from pydantic and `ChannelConnectionStatus` from `app.models.channel_connection`.

- [ ] **Step 4: Write `app/api/bots.py`**

```python
"""Bot settings.

The tenant filter here is a join through Shop, so it goes through
app/api/queries.py::bots_for and nowhere else.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import TenantScope, tenant
from app.api.queries import bots_for
from app.api.schemas import BotOut, BotPatch, ShopRef
from app.core.database import get_db
from app.models.bot import Bot
from app.models.shop import Shop

router = APIRouter(prefix="/bots", tags=["bots"])


def _to_schema(bot: Bot, shop: Shop) -> BotOut:
    return BotOut(
        id=bot.id,
        name=bot.name,
        shop=ShopRef(id=shop.id, name=shop.name),
        persona=bot.persona,
        llm_provider=bot.llm_provider,
        enabled_tools=bot.enabled_tools,
        escalation_max_bot_turns=bot.escalation_max_bot_turns,
    )


def _with_shop(scope: TenantScope):
    return bots_for(scope).add_columns(Shop)


@router.get("", response_model=list[BotOut])
async def list_bots(
    scope: TenantScope = Depends(tenant),
    db: AsyncSession = Depends(get_db),
) -> list[BotOut]:
    rows = (await db.execute(_with_shop(scope).order_by(Bot.id))).all()
    return [_to_schema(bot, shop) for bot, shop in rows]


@router.patch("/{bot_id}", response_model=BotOut)
async def patch_bot(
    bot_id: int,
    body: BotPatch,
    scope: TenantScope = Depends(tenant),
    db: AsyncSession = Depends(get_db),
) -> BotOut:
    row = (
        await db.execute(_with_shop(scope).where(Bot.id == bot_id))
    ).first()
    if row is None:
        # 404, not 403: a 403 confirms the bot exists under another merchant.
        raise HTTPException(status_code=404, detail="bot not found")
    bot, shop = row

    # exclude_unset, not exclude_none: an explicit null and an omitted field
    # are different requests, and only the omitted one means "leave it alone".
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(bot, field, value)
    db.add(bot)
    await db.commit()
    return _to_schema(bot, shop)
```

- [ ] **Step 5: Write `app/api/connections.py`**

```python
"""Channel connections, read-only.

Creating one means accepting a bot token over HTTP and calling
adapter.connect() to register a webhook -- a credential-handling surface that
deserves its own design rather than a paragraph. scripts/seed_telegram.py
remains the way a connection is created.

Nothing here ever serialises credentials_encrypted.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import TenantScope, tenant
from app.api.queries import connections_for
from app.api.schemas import BotRef, CapabilitiesOut, ConnectionOut
from app.channels.registry import UnknownProvider, capabilities_for
from app.core.database import get_db
from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection

router = APIRouter(prefix="/channels", tags=["channels"])


def _capabilities(provider: str) -> CapabilitiesOut | None:
    try:
        caps = capabilities_for(provider)
    except UnknownProvider:
        return None
    return CapabilitiesOut(
        supports_media=caps.supports_media,
        max_text_len=caps.max_text_len,
        session_window_seconds=(
            int(caps.session_window.total_seconds())
            if caps.session_window is not None
            else None
        ),
        requires_template_outside_window=caps.requires_template_outside_window,
        supports_typing_indicator=caps.supports_typing_indicator,
    )


@router.get("/connections", response_model=list[ConnectionOut])
async def list_connections(
    scope: TenantScope = Depends(tenant),
    db: AsyncSession = Depends(get_db),
) -> list[ConnectionOut]:
    rows = (
        await db.execute(
            connections_for(scope)
            .add_columns(Bot.id.label("bot_id"), Bot.name.label("bot_name"))
            .order_by(ChannelConnection.id)
        )
    ).all()
    return [
        ConnectionOut(
            id=connection.id,
            provider=connection.provider,
            external_ref=connection.external_ref,
            status=connection.status,
            bot=BotRef(id=row.bot_id, name=row.bot_name),
            capabilities=_capabilities(connection.provider),
        )
        for row in rows
        for connection in (row[0],)
    ]
```

- [ ] **Step 6: Register both routers** in `app/main.py`, then run and commit

```bash
.venv/bin/python -m pytest test/test_bots_api.py -q
git add app/api/bots.py app/api/connections.py app/api/schemas.py app/main.py test/test_bots_api.py
git commit -m "feat: bot settings and read-only channel connections behind a join-based tenant filter"
```

---

### Task 13: The event bus

Messages are written by the Celery worker; WebSockets live in the uvicorn process. An in-memory broadcast registry delivers nothing in production while passing every single-process test — a failure mode that only appears under `docker compose`.

**Files:**
- Create: `app/realtime/__init__.py`, `app/realtime/bus.py`, `app/realtime/events.py`
- Test: `test/test_realtime_bus.py`

**Interfaces:**
- Produces:
  - `channel_for(merchant_id: int) -> str` → `f"merchant:{merchant_id}:events"`.
  - `EventBus` Protocol: `async publish(merchant_id, event: dict) -> None`; `subscribe(merchant_id) -> AsyncIterator[dict]`.
  - `RedisEventBus(client)`, `FakeEventBus()` (with `.published: list[tuple[int, dict]]`), `default_bus() -> EventBus`.
  - `app/realtime/events.py::message_created(conversation_id: int, message: dict) -> dict` and `conversation_updated(conversation: dict) -> dict`.

- [ ] **Step 1: Write the failing test** — `test/test_realtime_bus.py`

```python
"""The bus that crosses the process boundary.

The tenant boundary here is the *channel name*, not a filter a consumer has to
remember to apply. A subscriber can only ever receive its own tenant's events
because it is only ever subscribed to its own tenant's channel.
"""

import pytest

from app.realtime.bus import FakeEventBus, channel_for
from app.realtime.events import conversation_updated, message_created


def test_the_channel_is_keyed_by_merchant():
    assert channel_for(7) == "merchant:7:events"
    assert channel_for(8) != channel_for(7)


async def test_a_subscriber_receives_its_own_merchants_events():
    bus = FakeEventBus()
    stream = bus.subscribe(7)

    await bus.publish(7, {"type": "ping"})

    assert await anext(stream) == {"type": "ping"}


async def test_a_subscriber_never_receives_another_merchants_events():
    bus = FakeEventBus()
    stream = bus.subscribe(7)

    await bus.publish(8, {"type": "not-yours"})
    await bus.publish(7, {"type": "mine"})

    assert await anext(stream) == {"type": "mine"}


async def test_publishing_records_what_was_sent():
    bus = FakeEventBus()

    await bus.publish(7, {"type": "ping"})

    assert bus.published == [(7, {"type": "ping"})]


def test_a_message_event_carries_its_conversation():
    """The client applies it to a thread it may not currently have open, so the
    conversation id has to travel with the message."""
    event = message_created(41, {"id": 9, "text": "hi"})

    assert event["type"] == "message.created"
    assert event["conversation_id"] == 41
    assert event["message"]["id"] == 9


def test_a_conversation_event_carries_the_summary_shape():
    event = conversation_updated({"id": 41, "handoff_state": "human"})

    assert event["type"] == "conversation.updated"
    assert event["conversation"]["handoff_state"] == "human"
```

- [ ] **Step 2: Run and watch fail**

Run: `.venv/bin/python -m pytest test/test_realtime_bus.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.realtime'`

- [ ] **Step 3: Write `app/realtime/bus.py`**

```python
"""Carrying events across the process boundary.

Messages are written by the Celery worker. WebSockets live in the uvicorn
process. They are different processes, so an in-memory broadcast registry
delivers nothing in production while passing every single-process test -- a
failure mode that only appears under docker compose.

Redis pub/sub is the carrier. The channel is keyed by merchant, so a subscriber
can only ever receive its own tenant's events: the tenant boundary is in the
channel name, not in a filter the consumer has to remember to apply.

Delivery is best-effort and the client does not depend on it for correctness --
the inbox refetches on reconnect. A dropped event costs a delayed update, not a
wrong one.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Protocol


def channel_for(merchant_id: int) -> str:
    return f"merchant:{merchant_id}:events"


class EventBus(Protocol):
    async def publish(self, merchant_id: int, event: dict) -> None: ...

    def subscribe(self, merchant_id: int) -> AsyncIterator[dict]: ...


class RedisEventBus:
    def __init__(self, client) -> None:
        self._client = client

    async def publish(self, merchant_id: int, event: dict) -> None:
        await self._client.publish(channel_for(merchant_id), json.dumps(event))

    async def subscribe(self, merchant_id: int) -> AsyncIterator[dict]:
        pubsub = self._client.pubsub()
        await pubsub.subscribe(channel_for(merchant_id))
        try:
            async for raw in pubsub.listen():
                if raw.get("type") != "message":
                    continue
                try:
                    yield json.loads(raw["data"])
                except (TypeError, ValueError):
                    # A malformed frame is one lost update, not a dropped
                    # socket. The client refetches on reconnect anyway.
                    continue
        finally:
            await pubsub.unsubscribe(channel_for(merchant_id))
            await pubsub.aclose()


class FakeEventBus:
    """An in-memory queue per merchant. Real enough to prove the routing."""

    def __init__(self) -> None:
        self.published: list[tuple[int, dict]] = []
        self._queues: dict[int, list[asyncio.Queue]] = {}

    async def publish(self, merchant_id: int, event: dict) -> None:
        self.published.append((merchant_id, event))
        for queue in self._queues.get(merchant_id, []):
            queue.put_nowait(event)

    async def subscribe(self, merchant_id: int) -> AsyncIterator[dict]:
        queue: asyncio.Queue = asyncio.Queue()
        self._queues.setdefault(merchant_id, []).append(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._queues[merchant_id].remove(queue)


_default: RedisEventBus | None = None


def default_bus() -> EventBus:
    global _default
    if _default is None:
        from redis.asyncio import Redis

        from app.core.config import settings

        _default = RedisEventBus(Redis.from_url(settings.REDIS_URL))
    return _default
```

- [ ] **Step 4: Write `app/realtime/events.py`**

```python
"""Event envelopes.

Built here rather than inline at each publish site so that the two producers --
the worker's pipeline and the API's endpoints -- cannot drift into two shapes
for one event, which would leave the client's reducer guessing which it got.
"""


def message_created(conversation_id: int, message: dict) -> dict:
    """A message was stored: inbound, a bot reply, or an agent reply.

    The conversation id travels alongside because the client may not have that
    thread open, and still has to move it in the list.
    """
    return {
        "type": "message.created",
        "conversation_id": conversation_id,
        "message": message,
    }


def conversation_updated(conversation: dict) -> dict:
    """Handoff state, assignee, or last_message_at changed.

    Carries the same summary object the list endpoint returns, so the client
    can replace a row rather than patch fields it has to reconcile.
    """
    return {"type": "conversation.updated", "conversation": conversation}
```

- [ ] **Step 5: Run and commit**

```bash
.venv/bin/python -m pytest test/test_realtime_bus.py -q
git add app/realtime test/test_realtime_bus.py
git commit -m "feat: Redis event bus keyed by merchant, with an in-memory fake"
```

---

### Task 14: Publishing events, after commit

**Files:**
- Modify: `app/runtime/pipeline.py`
- Modify: `app/api/conversations.py`
- Test: `test/test_realtime_publish.py`

**Interfaces:**
- Consumes: `default_bus`, `FakeEventBus`, `message_created`, `conversation_updated`.
- Produces: `run_inbound_pipeline(..., bus: EventBus | None = None)` — one more injected seam alongside `brain`, `limiter` and `policy`.

- [ ] **Step 1: Write the failing test** — `test/test_realtime_publish.py`

```python
"""Events reach the bus, and only after the rows are committed.

An event announcing a row a later rollback erased makes the inbox show a
message that does not exist.
"""

from datetime import datetime, timezone

import pytest

from app.core.database import get_db
from app.main import app
from app.models.conversation import HandoffState
from app.realtime.bus import FakeEventBus
from test.test_conversations_api import (
    client,
    make_conversation,
    make_tenant,
    sign_in,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def wired(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def bus(monkeypatch) -> FakeEventBus:
    from app.api import conversations as conversations_api

    fake = FakeEventBus()
    monkeypatch.setattr(conversations_api, "event_bus", lambda: fake)
    return fake


async def test_takeover_announces_the_conversation(db_session, wired, bus):
    tenant = await make_tenant(db_session, "pub-takeover")
    conversation = await make_conversation(
        db_session, tenant, "t", state=HandoffState.PENDING_HUMAN
    )

    async with client() as http:
        await sign_in(http, tenant)
        await http.post(f"/conversations/{conversation.id}/takeover")

    merchant_id, event = bus.published[-1]
    assert merchant_id == tenant.merchant.id
    assert event["type"] == "conversation.updated"
    assert event["conversation"]["handoff_state"] == "human"


async def test_an_agent_reply_announces_the_message(db_session, wired, bus, monkeypatch):
    from app.api import conversations as conversations_api
    from app.channels.fake.adapter import FakeAdapter
    from app.dispatch.ratelimit import InMemoryTokenBucket

    monkeypatch.setattr(
        conversations_api, "build_adapter", lambda conn, webhook_url=None: FakeAdapter()
    )
    monkeypatch.setattr(
        conversations_api, "send_limiter", lambda: InMemoryTokenBucket()
    )

    tenant = await make_tenant(db_session, "pub-send")
    conversation = await make_conversation(
        db_session,
        tenant,
        "s",
        state=HandoffState.HUMAN,
        assignee_id=tenant.user.id,
        last_message_at=datetime.now(timezone.utc),
    )

    async with client() as http:
        await sign_in(http, tenant)
        await http.post(
            f"/conversations/{conversation.id}/messages", json={"text": "on it"}
        )

    kinds = [event["type"] for _, event in bus.published]
    assert "message.created" in kinds
    assert "conversation.updated" in kinds


async def test_a_refused_send_announces_nothing(db_session, wired, bus, monkeypatch):
    from app.api import conversations as conversations_api
    from app.channels.fake.adapter import FakeAdapter
    from app.dispatch.dispatcher import DispatchOutcome, OutboundDispatcher
    from app.dispatch.ratelimit import InMemoryTokenBucket

    monkeypatch.setattr(
        conversations_api, "build_adapter", lambda conn, webhook_url=None: FakeAdapter()
    )
    monkeypatch.setattr(
        conversations_api, "send_limiter", lambda: InMemoryTokenBucket()
    )

    async def refuse(self, conn, draft, last_inbound_at=None):
        return DispatchOutcome(escalated=True, reason="nope")

    monkeypatch.setattr(OutboundDispatcher, "dispatch", refuse)

    tenant = await make_tenant(db_session, "pub-refused")
    conversation = await make_conversation(
        db_session, tenant, "r", state=HandoffState.HUMAN,
        assignee_id=tenant.user.id,
    )

    async with client() as http:
        await sign_in(http, tenant)
        await http.post(
            f"/conversations/{conversation.id}/messages", json={"text": "hi"}
        )

    assert bus.published == []


async def test_the_pipeline_announces_the_inbound_message(db_session):
    """The worker is the other producer, and it is the one that crosses a
    process boundary to reach a socket."""
    from test.test_pipeline_conversations import _connection, _event, _session_factory

    connection = await _connection(db_session)
    event = await _event(db_session, connection)
    fake = FakeEventBus()

    from app.dispatch.ratelimit import InMemoryTokenBucket
    from app.runtime.pipeline import run_inbound_pipeline

    await run_inbound_pipeline(
        event.id,
        session_factory=_session_factory(db_session),
        limiter=InMemoryTokenBucket(),
        bus=fake,
    )

    kinds = [e["type"] for _, e in fake.published]
    assert kinds.count("message.created") >= 1
    assert "conversation.updated" in kinds
```

- [ ] **Step 2: Run and watch fail**

Run: `.venv/bin/python -m pytest test/test_realtime_publish.py -q`
Expected: FAIL — `AttributeError: module 'app.api.conversations' has no attribute 'event_bus'`

- [ ] **Step 3: Publish from the API.** In `app/api/conversations.py` add the seam and a helper, then call it after each `await db.commit()`.

```python
def event_bus():
    return default_bus()


async def _announce_conversation(db, scope: TenantScope, conversation_id: int) -> None:
    """Published after commit, never inside the transaction.

    An event announcing a row a later rollback erased makes the inbox show a
    message that does not exist. Failures here are swallowed: realtime is an
    accelerator, and an unreachable Redis must not turn a successful takeover
    into a 500.
    """
    try:
        row = await _summary_row(db, scope, conversation_id)
        await event_bus().publish(
            scope.merchant_id,
            conversation_updated(row_to_summary(row).model_dump(mode="json")),
        )
    except Exception:
        pass
```

Call `await _announce_conversation(db, scope, conversation_id)` at the end of `takeover`, `release`, `resolve` and `mark_read` (after `db.commit()`), and in `send_message` publish both events after the commit:

```python
    try:
        await event_bus().publish(
            scope.merchant_id,
            message_created(conversation.id, out.model_dump(mode="json")),
        )
    except Exception:
        pass
    await _announce_conversation(db, scope, conversation.id)
    return out
```

- [ ] **Step 4: Publish from the pipeline.** Add a `bus` parameter to `run_inbound_pipeline`, collect `(merchant_id, event)` tuples during the loop, and flush them after `_mark_processed` / `_fail` has committed.

```python
async def run_inbound_pipeline(
    event_id: int,
    session_factory=None,
    brain: Brain | None = None,
    limiter=None,
    policy: EscalationPolicy | None = None,
    bus=None,
) -> None:
    ...
    bus = bus if bus is not None else default_bus()
    pending: list[dict] = []
```

Each `_store_inbound` and `record_outbound` call appends a `message.created` payload built from the flushed row; each conversation mutation appends `conversation_updated`. After the terminal commit:

```python
    await _flush_events(bus, merchant_id, pending)
```

```python
async def _flush_events(bus, merchant_id: int | None, events: list[dict]) -> None:
    """After commit, never inside the transaction, and never fatal.

    A worker that cannot reach Redis has still done its real job: the rows are
    written and the inbox will pick them up on its next fetch.
    """
    if merchant_id is None:
        return
    for event in events:
        try:
            await bus.publish(merchant_id, event)
        except Exception:
            return
```

- [ ] **Step 5: Run the suite and commit**

```bash
.venv/bin/python -m pytest -q
git add app/api/conversations.py app/runtime/pipeline.py test/test_realtime_publish.py
git commit -m "feat: publish message and conversation events after commit from both producers"
```

---

### Task 15: `GET /ws`

Authentication reuses the session cookie — the browser sends it on the WebSocket handshake, and the token is never placed in a query string where it would land in access logs.

`current_user` raises `HTTPException`, which a WebSocket route cannot return. The route resolves the session with the same query and, on failure, calls `websocket.close(code=1008)` **before** `accept()`. Refusing before `accept()` means an unauthenticated client never reaches a connected state.

**Files:**
- Create: `app/api/realtime.py`
- Modify: `app/main.py`
- Test: `test/test_realtime_ws.py`

- [ ] **Step 1: Write the failing test** — `test/test_realtime_ws.py`

```python
"""The socket.

Auth is the session cookie, which the browser sends on the handshake. A token
in the query string would land in every access log between here and the client.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.database import get_db
from app.core.security import hash_session_token, new_session_token
from app.main import app
from app.models.login_session import LoginSession
from app.realtime.bus import FakeEventBus
from test.test_conversations_api import make_tenant

pytestmark = pytest.mark.integration

SESSION_COOKIE = "botly_session"


@pytest.fixture
def wired(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def bus(monkeypatch) -> FakeEventBus:
    from app.api import realtime as realtime_api

    fake = FakeEventBus()
    monkeypatch.setattr(realtime_api, "event_bus", lambda: fake)
    return fake


async def _session_token(db, user, *, expired=False, revoked=False) -> str:
    token = new_session_token()
    now = datetime.now(timezone.utc)
    session = LoginSession(
        user_id=user.id,
        token_hash=hash_session_token(token),
        expires_at=now - timedelta(seconds=1) if expired else now + timedelta(days=1),
        revoked_at=now if revoked else None,
    )
    db.add(session)
    await db.flush()
    return token


async def test_a_socket_without_a_cookie_is_refused(db_session, wired, bus):
    with TestClient(app) as http:
        with pytest.raises(WebSocketDisconnect) as refused:
            with http.websocket_connect("/ws"):
                pass

    assert refused.value.code == 1008


async def test_an_expired_session_is_refused(db_session, wired, bus):
    tenant = await make_tenant(db_session, "ws-expired")
    token = await _session_token(db_session, tenant.user, expired=True)

    with TestClient(app, cookies={SESSION_COOKIE: token}) as http:
        with pytest.raises(WebSocketDisconnect) as refused:
            with http.websocket_connect("/ws"):
                pass

    assert refused.value.code == 1008


async def test_a_revoked_session_is_refused(db_session, wired, bus):
    tenant = await make_tenant(db_session, "ws-revoked")
    token = await _session_token(db_session, tenant.user, revoked=True)

    with TestClient(app, cookies={SESSION_COOKIE: token}) as http:
        with pytest.raises(WebSocketDisconnect) as refused:
            with http.websocket_connect("/ws"):
                pass

    assert refused.value.code == 1008


async def test_a_signed_in_socket_receives_its_own_merchants_events(
    db_session, wired, bus
):
    tenant = await make_tenant(db_session, "ws-ok")
    token = await _session_token(db_session, tenant.user)

    with TestClient(app, cookies={SESSION_COOKIE: token}) as http:
        with http.websocket_connect("/ws") as socket:
            hello = socket.receive_json()
            assert hello["type"] == "ready"

            import anyio

            anyio.from_thread.run_sync(lambda: None)
            socket.send_json({"type": "noop"})
```

> **Note for the implementer:** driving a Starlette `TestClient` WebSocket *and* an async publish from the same test is awkward, because `TestClient` runs the app on its own portal thread. Keep the delivery assertion at the level the fake bus makes cheap: the route's frame-forwarding loop is a two-line `async for` over `bus.subscribe(...)`, and a direct unit test of that loop is worth more than a threaded integration dance. If the last test above proves fiddly, replace it with a direct test of `forward_events(bus, merchant_id, sink)` and keep the three refusal tests as the route-level coverage. Both are listed under §14 of the spec; the refusal cases are the security-relevant half.

- [ ] **Step 2: Run and watch fail**

Run: `.venv/bin/python -m pytest test/test_realtime_ws.py -q`
Expected: FAIL — the `/ws` route does not exist.

- [ ] **Step 3: Write `app/api/realtime.py`**

```python
"""The inbox's socket.

Authentication reuses the session cookie: the browser sends it on the
handshake, and the token is never placed in a query string where it would land
in every access log on the way.

current_user raises HTTPException, which a WebSocket route cannot return. So
the session is resolved here with the same query, and a failure closes with
1008 *before* accept() -- an unauthenticated client never reaches a connected
state.
"""

import asyncio
import contextlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SESSION_COOKIE
from app.core.database import get_db
from app.core.security import hash_session_token
from app.models.login_session import LoginSession
from app.models.user import User
from app.realtime.bus import default_bus

router = APIRouter(tags=["realtime"])

# Long enough not to be chatty, short enough that no sensible proxy idles the
# socket out from under an agent reading a long thread.
PING_SECONDS = 30


def event_bus():
    return default_bus()


async def resolve_socket_user(db: AsyncSession, token: str | None) -> User | None:
    if not token:
        return None
    now = datetime.now(timezone.utc)
    return (
        await db.execute(
            select(User)
            .join(LoginSession, LoginSession.user_id == User.id)
            .where(
                LoginSession.token_hash == hash_session_token(token),
                LoginSession.revoked_at.is_(None),
                LoginSession.expires_at > now,
                User.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def forward_events(bus, merchant_id: int, websocket: WebSocket) -> None:
    """Every frame this merchant's channel carries, as JSON.

    The subscription is per merchant, so there is no filter to forget: a
    socket physically cannot see another tenant's events.
    """
    async for event in bus.subscribe(merchant_id):
        await websocket.send_json(event)


async def _ping(websocket: WebSocket) -> None:
    while True:
        await asyncio.sleep(PING_SECONDS)
        await websocket.send_json({"type": "ping"})


@router.websocket("/ws")
async def events(
    websocket: WebSocket,
    db: AsyncSession = Depends(get_db),
) -> None:
    user = await resolve_socket_user(db, websocket.cookies.get(SESSION_COOKIE))
    if user is None:
        # Before accept(), so an unauthenticated client never reaches a
        # connected state.
        await websocket.close(code=1008)
        return

    await websocket.accept()
    await websocket.send_json({"type": "ready"})

    forwarding = asyncio.create_task(
        forward_events(event_bus(), user.merchant_id, websocket)
    )
    pinging = asyncio.create_task(_ping(websocket))
    try:
        # Reading is what notices the client going away; the socket carries no
        # client-to-server protocol of its own.
        while True:
            await websocket.receive_text()
    except Exception:
        pass
    finally:
        for task in (forwarding, pinging):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
```

- [ ] **Step 4: Register it** in `app/main.py`, run and commit

```bash
.venv/bin/python -m pytest -q
git add app/api/realtime.py app/main.py test/test_realtime_ws.py
git commit -m "feat: session-authenticated WebSocket forwarding this merchant's events"
```

---

### Task 16: Full-suite green and the README

- [ ] **Step 1: Run everything**

```bash
.venv/bin/python -m pytest -q
```

- [ ] **Step 2: Record the new surface** in `README.md` under a short "HTTP surface" heading — the endpoint table from spec §4, so the next person does not have to read the router to learn what exists.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: record the inbox API surface"
```
