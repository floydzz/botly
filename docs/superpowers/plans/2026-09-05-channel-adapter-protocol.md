# botly Channel Adapter Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define the `ChannelAdapter` Protocol, the normalised message envelopes it moves, a working fake adapter, and one shared conformance suite that every future adapter must pass.

**Architecture:** `app/channels/` becomes the only place in the codebase that knows a provider by name. `types.py` holds provider-neutral value objects (capability manifest, inbound envelope, outbound message, send result). `base.py` holds the Protocol itself. `fake/` holds a real, in-memory adapter — not a mock — so the conformance suite has something honest to prove itself against before Telegram exists. The suite lives in `test/conformance.py` as a plain base class with no pytest imports, subclassed once per adapter.

**Tech Stack:** Python 3.12, Pydantic 2, `typing.Protocol` + `runtime_checkable`, pytest + pytest-asyncio (`asyncio_mode = auto`, so async tests need no marker).

**Spec:** `docs/superpowers/specs/2026-09-02-botly-architecture-design.md` (sections 4, 6, 7, 10, 11)

## Global Constraints

- **No code outside `app/channels/<provider>/` may branch on a provider name.** Task 5 turns this from a convention into a failing test.
- **`ChannelConnection.provider` stays a plain `String(32)` column.** Not an enum. Adding a channel must not require a migration.
- **Every external service sits behind a Protocol with a fake.** No test may touch the network — this plan adds no HTTP client of any kind.
- **Datetimes are timezone-aware UTC.** `app/models/base.py` documents why: a prior system mixed naive and aware time bases in one row. Envelopes carry the same rule and enforce it at construction.
- **Capability differences live in the manifest, never in the dispatcher.** The dispatcher asks a question; it does not switch on a name.
- This plan adds **no** database tables, **no** migration, **no** HTTP routes, and **no** Celery tasks.

## File Structure

| File | Responsibility |
|---|---|
| `app/channels/__init__.py` | Exports the Protocol and the types; imports no concrete adapter |
| `app/channels/types.py` | `Attachment`, `ChannelCapabilities`, `InboundEnvelope`, `OutboundMessage`, `SendResult` |
| `app/channels/base.py` | The `ChannelAdapter` Protocol |
| `app/channels/fake/__init__.py` | Exports `FakeAdapter` |
| `app/channels/fake/adapter.py` | `FakeAdapter` — HMAC-signed webhooks, in-memory send log |
| `test/conformance.py` | `ChannelAdapterConformance` — the shared contract, subclassed per adapter |
| `test/test_channel_types.py` | Validation rules on the value objects |
| `test/test_fake_adapter.py` | Runs the conformance suite against `FakeAdapter`, plus fake-specific behaviour |
| `test/test_architecture.py` | Fails if any module outside `app/channels/` names a provider in a string literal |

---

### Task 1: Value objects — capability manifest and message envelopes

**Files:**
- Create: `app/channels/__init__.py`, `app/channels/types.py`
- Test: `test/test_channel_types.py`

**Interfaces:**
- Consumes: nothing (this is the base of the feature)
- Produces: `Attachment(kind, url, mime_type=None, size_bytes=None)`; `ChannelCapabilities(supports_media, max_text_len, session_window=None, requires_template_outside_window=False, supports_typing_indicator=False)`; `InboundEnvelope(provider, external_thread_id, provider_update_id, sender_ref, sent_at, provider_message_id=None, text=None, attachments=(), raw={})`; `OutboundMessage(text=None, attachments=(), template_name=None, template_variables={})`; `SendResult(ok, provider_message_id=None, error=None, retryable=False)`

- [ ] **Step 1: Create the package marker**

```bash
mkdir -p app/channels
cat > app/channels/__init__.py <<'EOF'
EOF
```

Leave it empty for now; Task 2 fills in the exports once the Protocol exists.

- [ ] **Step 2: Write the failing test — `test/test_channel_types.py`**

```python
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.channels.types import (
    Attachment,
    ChannelCapabilities,
    InboundEnvelope,
    OutboundMessage,
    SendResult,
)


def _envelope(**overrides):
    base = dict(
        provider="fake",
        external_thread_id="thread-1",
        provider_update_id="update-1",
        sender_ref="customer-1",
        text="hello",
        sent_at=datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return InboundEnvelope(**base)


class TestChannelCapabilities:
    def test_a_channel_that_never_closes_needs_no_template_rule(self):
        caps = ChannelCapabilities(
            supports_media=True, max_text_len=4096, session_window=None
        )
        assert caps.session_window is None
        assert caps.requires_template_outside_window is False

    def test_a_windowed_channel_may_require_templates(self):
        caps = ChannelCapabilities(
            supports_media=True,
            max_text_len=4096,
            session_window=timedelta(hours=24),
            requires_template_outside_window=True,
        )
        assert caps.session_window == timedelta(hours=24)

    def test_template_rule_without_a_window_is_incoherent(self):
        # There is no "outside" of a window that never closes. Catching this at
        # construction stops an adapter shipping a manifest the dispatcher
        # cannot act on.
        with pytest.raises(ValidationError):
            ChannelCapabilities(
                supports_media=True,
                max_text_len=4096,
                session_window=None,
                requires_template_outside_window=True,
            )

    def test_max_text_len_must_be_positive(self):
        with pytest.raises(ValidationError):
            ChannelCapabilities(supports_media=True, max_text_len=0)


class TestInboundEnvelope:
    def test_a_text_message_round_trips(self):
        env = _envelope()
        assert env.text == "hello"
        assert env.attachments == ()

    def test_an_attachment_only_message_is_valid(self):
        env = _envelope(
            text=None,
            attachments=(Attachment(kind="image", url="https://example.invalid/a.png"),),
        )
        assert env.text is None
        assert env.attachments[0].kind == "image"

    def test_a_message_with_neither_text_nor_attachment_is_rejected(self):
        with pytest.raises(ValidationError):
            _envelope(text=None, attachments=())

    def test_naive_timestamps_are_rejected(self):
        # app/models/base.py documents the cost of mixing time bases in one row.
        # The envelope refuses to be the place a naive datetime enters.
        with pytest.raises(ValidationError):
            _envelope(sent_at=datetime(2026, 9, 5, 12, 0))

    def test_dedupe_key_is_required_and_non_empty(self):
        # Ingress dedupes on (provider, provider_update_id). An empty key would
        # collapse every delivery into one row.
        with pytest.raises(ValidationError):
            _envelope(provider_update_id="")


class TestOutboundMessage:
    def test_plain_text_is_valid(self):
        assert OutboundMessage(text="hi").text == "hi"

    def test_a_template_reference_is_valid_without_text(self):
        out = OutboundMessage(template_name="order_update", template_variables={"n": "7"})
        assert out.template_name == "order_update"

    def test_an_empty_message_is_rejected(self):
        with pytest.raises(ValidationError):
            OutboundMessage()


class TestSendResult:
    def test_success_carries_a_provider_id(self):
        r = SendResult(ok=True, provider_message_id="m-1")
        assert r.ok and r.provider_message_id == "m-1"

    def test_a_failure_must_explain_itself(self):
        # "delivery failed" shows in the seller inbox; an agent needs the reason.
        with pytest.raises(ValidationError):
            SendResult(ok=False)

    def test_a_success_cannot_be_retryable(self):
        with pytest.raises(ValidationError):
            SendResult(ok=True, retryable=True)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `poetry run pytest test/test_channel_types.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.channels.types'`

- [ ] **Step 4: Write `app/channels/types.py`**

```python
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AttachmentKind = Literal["image", "video", "audio", "file"]


class Attachment(BaseModel):
    """One media item on a message, already resolved to a fetchable URL."""

    model_config = ConfigDict(frozen=True)

    kind: AttachmentKind
    url: str = Field(min_length=1)
    mime_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)


class ChannelCapabilities(BaseModel):
    """What one channel will and will not accept.

    The channels genuinely disagree: Telegram sends anything at any time,
    WhatsApp refuses free-form text once its 24-hour window closes. Without a
    manifest that is a special case in the dispatcher per provider, and those
    special cases leak into the runtime and the inbox. With one, the dispatcher
    asks a question instead of branching on a name.
    """

    model_config = ConfigDict(frozen=True)

    supports_media: bool
    max_text_len: int = Field(gt=0)
    # None means the channel never closes -- Telegram.
    session_window: timedelta | None = None
    requires_template_outside_window: bool = False
    supports_typing_indicator: bool = False

    @model_validator(mode="after")
    def _template_rule_needs_a_window(self) -> "ChannelCapabilities":
        if self.requires_template_outside_window and self.session_window is None:
            raise ValueError(
                "requires_template_outside_window=True is meaningless without a "
                "session_window: there is no 'outside' of a window that never closes."
            )
        return self


class InboundEnvelope(BaseModel):
    """One customer message, normalised out of a provider's webhook payload.

    Not frozen, unlike the value objects above: it carries ``raw`` as a dict, and
    a frozen model advertises a ``__hash__`` that would raise the moment anyone
    tried to use it. Mutability here is the lesser trap.
    """

    provider: str = Field(min_length=1)
    # The provider's own conversation key -- a chat id, a thread id.
    external_thread_id: str = Field(min_length=1)
    # Unique per delivery. Ingress dedupes on (provider, provider_update_id)
    # against both Redis and the inbound_event table, because Meta retries
    # aggressively and will deliver the same update more than once.
    provider_update_id: str = Field(min_length=1)
    provider_message_id: str | None = None
    sender_ref: str = Field(min_length=1)
    text: str | None = None
    attachments: tuple[Attachment, ...] = ()
    sent_at: datetime
    raw: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> "InboundEnvelope":
        if self.text is None and not self.attachments:
            raise ValueError(
                "an inbound envelope needs text or at least one attachment"
            )
        if self.sent_at.tzinfo is None or self.sent_at.utcoffset() is None:
            raise ValueError(
                "sent_at must be timezone-aware; a naive timestamp puts two time "
                "bases in one conversation"
            )
        return self


class OutboundMessage(BaseModel):
    """What the dispatcher asks an adapter to deliver.

    Carries a template reference rather than resolved text, because whether a
    template is required is the channel's business, not the brain's.
    """

    text: str | None = None
    attachments: tuple[Attachment, ...] = ()
    template_name: str | None = None
    template_variables: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _must_carry_something(self) -> "OutboundMessage":
        if self.text is None and not self.attachments and self.template_name is None:
            raise ValueError(
                "an outbound message needs text, an attachment, or a template"
            )
        return self


class SendResult(BaseModel):
    """The outcome of one delivery attempt.

    ``retryable`` separates a rate limit from a rejected recipient: the first is
    worth backing off on, the second belongs in failed_job where an agent sees
    "delivery failed" in the inbox.
    """

    model_config = ConfigDict(frozen=True)

    ok: bool
    provider_message_id: str | None = None
    error: str | None = None
    retryable: bool = False

    @model_validator(mode="after")
    def _check(self) -> "SendResult":
        if not self.ok and not self.error:
            raise ValueError("a failed SendResult must carry an error")
        if self.ok and self.retryable:
            raise ValueError("a successful send is not retryable")
        return self
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `poetry run pytest test/test_channel_types.py -q`
Expected: PASS, 15 tests

- [ ] **Step 6: Commit**

```bash
git add app/channels/__init__.py app/channels/types.py test/test_channel_types.py
git commit -m "feat: channel capability manifest and message envelopes"
```

---

### Task 2: The ChannelAdapter Protocol

**Files:**
- Create: `app/channels/base.py`
- Modify: `app/channels/__init__.py`
- Test: `test/test_channel_protocol.py`

**Interfaces:**
- Consumes: every type from Task 1
- Produces: `ChannelAdapter` Protocol with `provider: ClassVar[str]`, `capabilities: ClassVar[ChannelCapabilities]`, and five members — `verify_webhook(headers, raw_body) -> bool`, `parse_inbound(payload) -> list[InboundEnvelope]`, `async send(conn, out) -> SendResult`, `async connect(conn) -> None`, `async disconnect(conn) -> None`

- [ ] **Step 1: Write the failing test — `test/test_channel_protocol.py`**

> **Note for the implementer:** `runtime_checkable` protocols in Python 3.12
> check *non-method* members too. `ChannelAdapter.__protocol_attrs__` is
> `{provider, capabilities, verify_webhook, parse_inbound, send, connect,
> disconnect}`, so a test double must declare `capabilities` or `isinstance`
> returns False for a reason that has nothing to do with its methods.

```python
from app.channels import ChannelAdapter, ChannelCapabilities

_CAPS = ChannelCapabilities(supports_media=False, max_text_len=100)


class _Complete:
    provider = "complete"
    capabilities = _CAPS

    def verify_webhook(self, headers, raw_body): ...
    def parse_inbound(self, payload): ...
    async def send(self, conn, out): ...
    async def connect(self, conn): ...
    async def disconnect(self, conn): ...


class _MissingDisconnect:
    provider = "partial"
    capabilities = _CAPS

    def verify_webhook(self, headers, raw_body): ...
    def parse_inbound(self, payload): ...
    async def send(self, conn, out): ...
    async def connect(self, conn): ...


def test_a_complete_implementation_satisfies_the_protocol():
    assert isinstance(_Complete(), ChannelAdapter)


def test_a_missing_method_fails_the_protocol():
    assert not isinstance(_MissingDisconnect(), ChannelAdapter)


def test_the_protocol_is_exported_from_the_package_root():
    import app.channels as channels

    assert "ChannelAdapter" in channels.__all__
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `poetry run pytest test/test_channel_protocol.py -q`
Expected: FAIL — `ImportError: cannot import name 'ChannelAdapter'`

- [ ] **Step 3: Write `app/channels/base.py`**

```python
from collections.abc import Mapping
from typing import Any, ClassVar, Protocol, runtime_checkable

from app.channels.types import (
    ChannelCapabilities,
    InboundEnvelope,
    OutboundMessage,
    SendResult,
)
from app.models.channel_connection import ChannelConnection


@runtime_checkable
class ChannelAdapter(Protocol):
    """Everything a channel must implement, and the only place its name appears.

    ``runtime_checkable`` compares method *names* and nothing else -- not
    signatures, not return types, not whether ``send`` is actually a coroutine.
    An ``isinstance`` check here is a smoke test. The real contract is the
    conformance suite in ``test/conformance.py``, which every adapter runs.
    """

    provider: ClassVar[str]
    capabilities: ClassVar[ChannelCapabilities]

    def verify_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        """Authenticate a webhook delivery against the raw, unparsed body.

        Takes bytes rather than a parsed dict on purpose: signatures cover the
        exact bytes sent, and re-serialising a parsed payload will not reproduce
        them.
        """
        ...

    def parse_inbound(self, payload: dict[str, Any]) -> list[InboundEnvelope]:
        """Normalise one delivery into zero or more envelopes.

        A list because providers batch: one Telegram request can carry several
        updates. Zero is valid and means "nothing actionable here" -- a delivery
        receipt, a status change -- not an error.
        """
        ...

    async def send(
        self, conn: ChannelConnection, out: OutboundMessage
    ) -> SendResult:
        """Deliver one message, returning an outcome rather than raising.

        Send failure is an expected operational state that must reach the inbox,
        so it is a return value the dispatcher can record, not an exception it
        has to catch.
        """
        ...

    async def connect(self, conn: ChannelConnection) -> None:
        """Register the webhook and validate credentials. Idempotent."""
        ...

    async def disconnect(self, conn: ChannelConnection) -> None:
        """Deregister the webhook. Idempotent, and safe on a dead connection."""
        ...
```

- [ ] **Step 4: Write `app/channels/__init__.py`**

```python
"""Channel adapters.

The only package permitted to know a provider by name. Nothing here imports a
concrete adapter -- importing one would put its provider name in every module
that touches the package root.
"""

from app.channels.base import ChannelAdapter
from app.channels.types import (
    Attachment,
    ChannelCapabilities,
    InboundEnvelope,
    OutboundMessage,
    SendResult,
)

__all__ = [
    "Attachment",
    "ChannelAdapter",
    "ChannelCapabilities",
    "InboundEnvelope",
    "OutboundMessage",
    "SendResult",
]
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `poetry run pytest test/test_channel_protocol.py -q`
Expected: PASS, 5 tests

- [ ] **Step 6: Commit**

```bash
git add app/channels/base.py app/channels/__init__.py test/test_channel_protocol.py
git commit -m "feat: ChannelAdapter protocol"
```

---

### Task 3: The fake adapter

**Files:**
- Create: `app/channels/fake/__init__.py`, `app/channels/fake/adapter.py`
- Test: `test/test_fake_adapter.py` (fake-specific half; Task 4 adds the conformance half)

**Interfaces:**
- Consumes: `ChannelAdapter`, all Task 1 types, `ChannelConnection`
- Produces: `FakeAdapter(secret=b"fake-secret")` with `provider == "fake"`, public attributes `sent: list[tuple[int | None, OutboundMessage]]`, `connected: set[int | None]`, `fail_next_send: str | None`, and helper `sign(raw_body: bytes) -> str`; module constant `SIGNATURE_HEADER = "x-fake-signature"`

- [ ] **Step 1: Write the failing test — `test/test_fake_adapter.py`**

```python
import pytest

from app.channels import ChannelAdapter, OutboundMessage
from app.channels.fake import SIGNATURE_HEADER, FakeAdapter
from app.models.channel_connection import ChannelConnection


def _conn(conn_id: int = 1) -> ChannelConnection:
    # Constructed in memory, never persisted: adapters must not need a session.
    return ChannelConnection(
        id=conn_id, bot_id=1, provider="fake", external_ref="fake-endpoint"
    )


def _payload():
    return {
        "updates": [
            {
                "update_id": "u-1",
                "thread": "t-1",
                "from": "c-1",
                "message_id": "m-1",
                "text": "where is my order",
                "ts": 1788609600,
            }
        ]
    }


def test_the_fake_satisfies_the_protocol():
    assert isinstance(FakeAdapter(), ChannelAdapter)


def test_a_correct_signature_verifies():
    a = FakeAdapter()
    body = b'{"updates":[]}'
    assert a.verify_webhook({SIGNATURE_HEADER: a.sign(body)}, body) is True


def test_a_tampered_body_fails_verification():
    a = FakeAdapter()
    sig = a.sign(b'{"updates":[]}')
    assert a.verify_webhook({SIGNATURE_HEADER: sig}, b'{"updates":[1]}') is False


def test_a_missing_signature_header_fails_verification():
    a = FakeAdapter()
    assert a.verify_webhook({}, b"anything") is False


def test_a_foreign_secret_fails_verification():
    body = b'{"updates":[]}'
    forged = FakeAdapter(secret=b"not-the-secret").sign(body)
    assert FakeAdapter().verify_webhook({SIGNATURE_HEADER: forged}, body) is False


def test_parse_inbound_normalises_one_update():
    env = FakeAdapter().parse_inbound(_payload())[0]
    assert env.provider == "fake"
    assert env.external_thread_id == "t-1"
    assert env.provider_update_id == "u-1"
    assert env.sender_ref == "c-1"
    assert env.text == "where is my order"
    assert env.sent_at.tzinfo is not None


def test_parse_inbound_returns_empty_for_a_non_message_delivery():
    assert FakeAdapter().parse_inbound({"updates": []}) == []


async def test_send_records_the_message_and_reports_success():
    a = FakeAdapter()
    result = await a.send(_conn(), OutboundMessage(text="on its way"))
    assert result.ok is True
    assert result.provider_message_id is not None
    assert a.sent == [(1, OutboundMessage(text="on its way"))]


async def test_a_scripted_failure_is_reported_not_raised():
    a = FakeAdapter()
    a.fail_next_send = "rate limited"
    result = await a.send(_conn(), OutboundMessage(text="hi"))
    assert result.ok is False
    assert result.error == "rate limited"
    assert result.retryable is True
    # The failure is consumed, so the next send succeeds.
    assert (await a.send(_conn(), OutboundMessage(text="hi"))).ok is True


async def test_connect_and_disconnect_are_idempotent():
    a, conn = FakeAdapter(), _conn()
    await a.connect(conn)
    await a.connect(conn)
    assert a.connected == {1}
    await a.disconnect(conn)
    await a.disconnect(conn)
    assert a.connected == set()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `poetry run pytest test/test_fake_adapter.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.channels.fake'`

- [ ] **Step 3: Write `app/channels/fake/adapter.py`**

```python
import hashlib
import hmac
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, ClassVar

from app.channels.types import (
    Attachment,
    ChannelCapabilities,
    InboundEnvelope,
    OutboundMessage,
    SendResult,
)
from app.models.channel_connection import ChannelConnection

SIGNATURE_HEADER = "x-fake-signature"


class FakeAdapter:
    """An in-memory channel, used by the conformance suite and by runtime tests.

    Deliberately a real implementation rather than a mock. The suite that will
    later prove Telegram correct has to prove itself against something first,
    and a mock agrees with every assertion made of it -- which proves nothing.
    So the signature check is real HMAC, and the parser really parses.
    """

    provider: ClassVar[str] = "fake"
    capabilities: ClassVar[ChannelCapabilities] = ChannelCapabilities(
        supports_media=True,
        max_text_len=4096,
        session_window=None,
        requires_template_outside_window=False,
        supports_typing_indicator=True,
    )

    def __init__(self, secret: bytes = b"fake-secret") -> None:
        self._secret = secret
        self.sent: list[tuple[int | None, OutboundMessage]] = []
        self.connected: set[int | None] = set()
        # Set to an error string to make exactly the next send fail.
        self.fail_next_send: str | None = None

    def sign(self, raw_body: bytes) -> str:
        return hmac.new(self._secret, raw_body, hashlib.sha256).hexdigest()

    def verify_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        offered = headers.get(SIGNATURE_HEADER)
        if offered is None:
            return False
        # compare_digest, not ==, so a wrong signature costs the same time as a
        # right one. The habit belongs in the fake too, because adapters get
        # written by copying this one.
        return hmac.compare_digest(offered, self.sign(raw_body))

    def parse_inbound(self, payload: dict[str, Any]) -> list[InboundEnvelope]:
        envelopes: list[InboundEnvelope] = []
        for update in payload.get("updates", []):
            raw_message_id = update.get("message_id")
            envelopes.append(
                InboundEnvelope(
                    provider=self.provider,
                    external_thread_id=str(update["thread"]),
                    provider_update_id=str(update["update_id"]),
                    provider_message_id=(
                        str(raw_message_id) if raw_message_id is not None else None
                    ),
                    sender_ref=str(update["from"]),
                    text=update.get("text"),
                    attachments=tuple(
                        Attachment(**a) for a in update.get("attachments", [])
                    ),
                    sent_at=datetime.fromtimestamp(update["ts"], tz=timezone.utc),
                    raw=update,
                )
            )
        return envelopes

    async def send(
        self, conn: ChannelConnection, out: OutboundMessage
    ) -> SendResult:
        if self.fail_next_send is not None:
            error, self.fail_next_send = self.fail_next_send, None
            return SendResult(ok=False, error=error, retryable=True)
        self.sent.append((conn.id, out))
        return SendResult(ok=True, provider_message_id=f"fake-{len(self.sent)}")

    async def connect(self, conn: ChannelConnection) -> None:
        self.connected.add(conn.id)

    async def disconnect(self, conn: ChannelConnection) -> None:
        self.connected.discard(conn.id)
```

- [ ] **Step 4: Write `app/channels/fake/__init__.py`**

```python
from app.channels.fake.adapter import SIGNATURE_HEADER, FakeAdapter

__all__ = ["SIGNATURE_HEADER", "FakeAdapter"]
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `poetry run pytest test/test_fake_adapter.py -q`
Expected: PASS, 10 tests

- [ ] **Step 6: Commit**

```bash
git add app/channels/fake test/test_fake_adapter.py
git commit -m "feat: in-memory fake channel adapter"
```

---

### Task 4: The shared conformance suite

**Files:**
- Create: `test/conformance.py`
- Modify: `test/test_fake_adapter.py` (append the subclass that runs the suite)

**Interfaces:**
- Consumes: `ChannelAdapter`, `ChannelCapabilities`, `InboundEnvelope`, `OutboundMessage`, `SendResult`, `ChannelConnection`
- Produces: `ChannelAdapterConformance` — a base class with four hooks a subclass must implement: `make_adapter() -> ChannelAdapter`, `make_connection() -> ChannelConnection`, `make_signed_webhook() -> tuple[dict[str, str], bytes]`, `make_inbound_payload() -> dict`. Every future adapter subclasses it.

> `test/conformance.py` does not match pytest's `test_*.py` collection pattern, so pytest never runs it on its own. The class name deliberately lacks a `Test` prefix for the same reason. A subclass named `TestXConformance` in a `test_*.py` file inherits and runs every check.

- [ ] **Step 1: Write `test/conformance.py`**

```python
"""The contract every ChannelAdapter must satisfy.

Subclass it once per adapter. The point is that Telegram, WhatsApp and every
later channel are held to one definition of correct rather than to whatever
their own author remembered to test.

No pytest import: pytest.ini sets asyncio_mode = auto, so async methods here
need no marker, and plain asserts need no helper.
"""

from datetime import datetime, timedelta

from app.channels import (
    ChannelAdapter,
    ChannelCapabilities,
    InboundEnvelope,
    OutboundMessage,
    SendResult,
)
from app.models.channel_connection import ChannelConnection


class ChannelAdapterConformance:
    # --- hooks a subclass must provide -------------------------------------

    def make_adapter(self) -> ChannelAdapter:
        raise NotImplementedError

    def make_connection(self) -> ChannelConnection:
        raise NotImplementedError

    def make_signed_webhook(self) -> tuple[dict[str, str], bytes]:
        """Headers and raw body that this adapter should accept as authentic."""
        raise NotImplementedError

    def make_inbound_payload(self) -> dict:
        """A parsed delivery carrying exactly one customer message."""
        raise NotImplementedError

    # --- identity ----------------------------------------------------------

    def test_declares_a_non_empty_provider_name(self):
        provider = type(self.make_adapter()).provider
        assert isinstance(provider, str) and provider

    def test_provider_name_is_lowercase_and_column_safe(self):
        # It is stored in a String(32) column and used as a URL segment in
        # POST /webhooks/{provider}/{connection_id}.
        provider = type(self.make_adapter()).provider
        assert provider == provider.lower()
        assert len(provider) <= 32
        assert provider.isidentifier()

    def test_satisfies_the_protocol(self):
        assert isinstance(self.make_adapter(), ChannelAdapter)

    # --- capability manifest ------------------------------------------------

    def test_declares_a_capability_manifest(self):
        caps = type(self.make_adapter()).capabilities
        assert isinstance(caps, ChannelCapabilities)

    def test_manifest_allows_a_usable_message_length(self):
        assert type(self.make_adapter()).capabilities.max_text_len > 0

    def test_session_window_is_a_positive_duration_when_present(self):
        window = type(self.make_adapter()).capabilities.session_window
        assert window is None or window > timedelta(0)

    # --- webhook verification -----------------------------------------------

    def test_accepts_an_authentic_delivery(self):
        headers, body = self.make_signed_webhook()
        assert self.make_adapter().verify_webhook(headers, body) is True

    def test_rejects_a_tampered_body(self):
        headers, body = self.make_signed_webhook()
        assert self.make_adapter().verify_webhook(headers, body + b" ") is False

    def test_rejects_a_delivery_with_no_headers(self):
        _, body = self.make_signed_webhook()
        assert self.make_adapter().verify_webhook({}, body) is False

    # --- parsing ------------------------------------------------------------

    def test_parse_returns_envelopes_stamped_with_its_own_provider(self):
        adapter = self.make_adapter()
        envelopes = adapter.parse_inbound(self.make_inbound_payload())
        assert envelopes, "the sample payload must yield at least one envelope"
        for env in envelopes:
            assert isinstance(env, InboundEnvelope)
            assert env.provider == type(adapter).provider

    def test_parse_is_pure(self):
        # Ingress persists the raw payload and may parse it again on replay.
        # Parsing twice must not consume, mutate, or renumber anything.
        adapter = self.make_adapter()
        payload = self.make_inbound_payload()
        first = adapter.parse_inbound(payload)
        second = adapter.parse_inbound(payload)
        assert [e.provider_update_id for e in first] == [
            e.provider_update_id for e in second
        ]

    def test_dedupe_keys_are_stable_and_non_empty(self):
        for env in self.make_adapter().parse_inbound(self.make_inbound_payload()):
            assert env.provider_update_id

    def test_parsed_timestamps_are_timezone_aware(self):
        for env in self.make_adapter().parse_inbound(self.make_inbound_payload()):
            assert isinstance(env.sent_at, datetime)
            assert env.sent_at.utcoffset() is not None

    # --- sending ------------------------------------------------------------

    async def test_send_returns_a_result_rather_than_raising(self):
        result = await self.make_adapter().send(
            self.make_connection(), OutboundMessage(text="conformance probe")
        )
        assert isinstance(result, SendResult)

    async def test_a_successful_send_reports_a_provider_message_id(self):
        result = await self.make_adapter().send(
            self.make_connection(), OutboundMessage(text="conformance probe")
        )
        if result.ok:
            assert result.provider_message_id

    # --- lifecycle ----------------------------------------------------------

    async def test_connect_is_idempotent(self):
        adapter, conn = self.make_adapter(), self.make_connection()
        await adapter.connect(conn)
        await adapter.connect(conn)

    async def test_disconnect_is_idempotent_and_safe_before_connect(self):
        adapter, conn = self.make_adapter(), self.make_connection()
        await adapter.disconnect(conn)
        await adapter.disconnect(conn)
```

- [ ] **Step 2: Append the subclass to `test/test_fake_adapter.py`**

```python
from test.conformance import ChannelAdapterConformance


class TestFakeAdapterConformance(ChannelAdapterConformance):
    def make_adapter(self):
        return FakeAdapter()

    def make_connection(self):
        return _conn()

    def make_signed_webhook(self):
        adapter = FakeAdapter()
        body = b'{"updates":[]}'
        return {SIGNATURE_HEADER: adapter.sign(body)}, body

    def make_inbound_payload(self):
        return _payload()
```

- [ ] **Step 3: Run the suite to verify it passes**

Run: `poetry run pytest test/test_fake_adapter.py -v`
Expected: PASS — the 10 fake-specific tests plus 17 inherited conformance tests

- [ ] **Step 4: Prove the suite has teeth**

The suite is worthless if it passes against a broken adapter. Verify it fails, then undo.

```bash
python - <<'EOF'
p = "app/channels/fake/adapter.py"
s = open(p).read()
open(p, "w").write(s.replace("hmac.compare_digest(offered, self.sign(raw_body))", "True"))
EOF
poetry run pytest test/test_fake_adapter.py -q
```

Expected: FAIL on `test_rejects_a_tampered_body` and `test_rejects_a_delivery_with_no_headers`.

```bash
git checkout app/channels/fake/adapter.py
poetry run pytest test/test_fake_adapter.py -q
```

Expected: PASS again.

- [ ] **Step 5: Run the whole suite**

Run: `poetry run pytest -q`
Expected: PASS — the 21 pre-existing tests plus everything added here

- [ ] **Step 6: Commit**

```bash
git add test/conformance.py test/test_fake_adapter.py
git commit -m "test: shared ChannelAdapter conformance suite"
```

---

### Task 5: Make the no-provider-branching rule a test

**Files:**
- Create: `test/test_architecture.py`

**Interfaces:**
- Consumes: nothing — it reads source files
- Produces: nothing importable

> Until now this rule has been enforced by reading the diff. A rule nobody can
> forget is better than a rule everybody remembers, and this one has to survive
> five more channels.

- [ ] **Step 1: Write the test — `test/test_architecture.py`**

```python
import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"

PROVIDER_NAMES = (
    "telegram",
    "whatsapp",
    "shopee",
    "rednote",
    "lazada",
    "tiktok",
    "messenger",
    "instagram",
)


def _docstring_ids(tree: ast.AST) -> set[int]:
    """Identity of every docstring node, so prose may name providers freely."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def test_no_module_outside_channels_names_a_provider():
    """Capability differences belong in a manifest, not in scattered conditionals.

    Only string literals are checked. Comments and docstrings may explain what a
    provider is; what they may not do is let code compare against the name.
    """
    offenders: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        if "channels" in path.relative_to(APP).parts:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        docstrings = _docstring_ids(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                lowered = node.value.lower()
                hit = next((n for n in PROVIDER_NAMES if n in lowered), None)
                if hit:
                    offenders.append(
                        f"{path.relative_to(APP.parent)}:{node.lineno} "
                        f"names {hit!r} in {node.value!r}"
                    )
    assert not offenders, (
        "provider names belong in app/channels/<provider>/ only:\n  "
        + "\n  ".join(offenders)
    )


def test_the_guard_would_catch_a_violation():
    """The guard above passes trivially if the walk is wrong. Prove it can fail."""
    tree = ast.parse('def route(p):\n    if p == "telegram":\n        return 1\n')
    docstrings = _docstring_ids(tree)
    found = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and id(n) not in docstrings
        and any(name in n.value.lower() for name in PROVIDER_NAMES)
    ]
    assert found == ["telegram"]
```

- [ ] **Step 2: Run it**

Run: `poetry run pytest test/test_architecture.py -q`
Expected: PASS, 2 tests. `app/models/` mentions providers only in comments and docstrings, both of which are exempt.

- [ ] **Step 3: Run the whole suite**

Run: `poetry run pytest -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add test/test_architecture.py
git commit -m "test: enforce the no-provider-branching rule"
```

---

## Definition of Done

- `poetry run pytest` passes with the Postgres container running.
- `isinstance(FakeAdapter(), ChannelAdapter)` is true, and the conformance suite runs green against it.
- Deleting the `compare_digest` check in the fake makes the conformance suite fail — the suite is proven, not assumed.
- `test_no_module_outside_channels_names_a_provider` passes, and its companion test proves the guard can fail.
- No new table, migration, route, or Celery task was added.
- A second adapter can be added by writing one class and one four-method test subclass.

## Not in this plan

The Telegram adapter (build-order step 3) and every real HTTP call. The webhook route `POST /webhooks/{provider}/{connection_id}`, the `inbound_event` table, and Redis dedupe — those arrive with ingress, which needs a real adapter to be worth testing. The outbound dispatcher, its token bucket, and template selection: the manifest defined here is what it will read, but the dispatcher is step 4 work. `Conversation` and `Message` models, and the seller inbox.
