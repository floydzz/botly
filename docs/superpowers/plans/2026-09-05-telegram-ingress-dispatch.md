# botly Telegram 通道、入站管线与出站派发实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通第一条端到端链路 —— 一个真实的 Telegram webhook 进来,经过验签、去重、落库、快速 ACK、队列、runtime、出站派发,最后变成一条发回 Telegram 的消息。

**Architecture:** 构建顺序第 3 步之所以选 Telegram,是因为它没有审批门槛:一个 BotFather token 加一个 webhook 就能跑通。所以这一步真正的交付物不是"一个 Telegram 适配器",而是**适配器周围的那整套通用管线** —— ingress、去重、队列、runtime、dispatcher。Telegram 只是第一个证明这套管线成立的具体通道。WhatsApp 之后接入时应当只需要写一个适配器类和一个四方法的 conformance 子类,不需要动管线的任何一行。

大脑这一步是 stub(`EchoBrain`)。LangGraph 与 RAG 有它自己的计划,不在这里;但 `Brain` Protocol 在这里定死,后面换实现是换一个类,不是改管线。

**Tech Stack:** Python 3.12、FastAPI、SQLModel、SQLAlchemy 2 (asyncio) + asyncpg、Alembic、PostgreSQL 17、Redis、Celery、httpx、pytest + pytest-asyncio(`asyncio_mode = auto`,异步测试不需要 marker)。

**Spec:** `docs/superpowers/specs/2026-09-02-botly-architecture-design.md`(第 4、6、7、10、11 节)

**前置计划:** `docs/superpowers/plans/2026-09-05-channel-adapter-protocol.md`(已执行完毕)。本计划全程消费它定下的 `ChannelAdapter` Protocol、`app/channels/types.py` 里的值对象,以及 `test/conformance.py` 里的共享契约套件。

---

## Global Constraints

- **`app/channels/<provider>/` 之外的任何代码都不得对 provider 名字分支。** `test/test_architecture.py` 已经把这条从约定变成了会失败的测试,它扫描 `app/` 下每个模块的**字符串字面量**(docstring 除外)。这条约束在本计划里有一个非显然的后果,见下方"Telegram 的 API 地址不能进 config"。
- **`ChannelConnection.provider` 保持普通 `String(32)` 列。** 不是 enum。新增一个通道不得需要一次迁移。
- **每个外部服务都藏在 Protocol 后面,并配一个 fake。** 本计划新增三个外部依赖 —— Telegram Bot API、Redis 去重、Redis 令牌桶 —— 每一个都必须是 Protocol + 真实实现 + fake。**任何测试都不许碰网络。**
- **时间一律是带时区的 UTC。** `DateTime(timezone=True)` 列,`app/models/base.py::utcnow` 作为默认值。永远不用 `datetime.utcnow`,永远不用 naive datetime。
- **租户 ID 一律 `BigInteger` identity 主键。**
- **能力差异只住在 manifest 里,绝不进 dispatcher。** dispatcher 提问,不按名字 switch。这条是本计划第 9 个 task 的全部要点。
- **入站 ACK 必须在 100ms 以内返回 200。** 这不是性能优化,是正确性要求:Meta 和 Telegram 都会激进重投,慢 ACK 直接变成重复投递。所以 ingress 里不许有 LLM 调用、不许有出站 HTTP、不许等 Celery 结果。
- **验签必须针对原始字节。** 签名覆盖的是发出去的那串 bytes,把解析过的 dict 重新序列化不会得到同样的字节。ingress 用 `await request.body()`,不用 FastAPI 的自动 JSON 解析。
- 每个 task 结束提交一次。Conventional commit 前缀(`feat:`、`test:`、`chore:`、`docs:`)。

### Telegram 的 API 地址不能进 config

这是执行时最容易踩的坑,先说清楚。

很自然的做法是在 `app/core/config.py` 里加一行 `TELEGRAM_API_BASE: str = "https://api.telegram.org"`。**这会让 `test_no_module_outside_channels_names_a_provider` 失败**,因为那个字符串字面量的值里含 `telegram`,而 `app/core/` 不在 `app/channels/` 下。变量名不受检查,值受检查。

正确做法:API 基地址作为 `HttpTelegramApi.__init__` 的默认参数,定义在 `app/channels/telegram/api.py` 里。需要覆盖时(本地代理、测试网关)走 `ChannelConnection.config` 这个 JSONB 字段,键名用 provider 中立的 `api_base`。

这不是为了迁就一个测试。它正是那条规则在兑现价值:Telegram 特有的知识全部关在 Telegram 的目录里,别的地方一个字都不知道。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `app/channels/telegram/__init__.py` | 导出 `TelegramAdapter` |
| `app/channels/telegram/api.py` | `TelegramApi` Protocol、`HttpTelegramApi`(httpx)、`FakeTelegramApi`、`TelegramApiResponse` |
| `app/channels/telegram/adapter.py` | `TelegramAdapter` —— 验签、解析 Update、发送、setWebhook/deleteWebhook |
| `app/channels/registry.py` | `build_adapter(conn)` —— provider 名字到适配器的唯一映射。住在 `app/channels/` 下,所以允许 import 具体适配器 |
| `app/models/inbound_event.py` | `InboundEvent`、`InboundEventStatus` |
| `app/models/failed_job.py` | `FailedJob` |
| `app/models/__init__.py` | 追加两个新模型的 import(漏掉就等于从所有迁移里消失,且无声) |
| `app/ingress/__init__.py` | 空包标记 |
| `app/ingress/dedupe.py` | `DedupeStore` Protocol、`RedisDedupeStore`、`InMemoryDedupeStore` |
| `app/ingress/queue.py` | `InboundQueue` Protocol、`InMemoryInboundQueue`。**不含** Celery 实现 —— ingress 不该 import 一个 broker |
| `app/api/webhooks.py` | `POST /webhooks/{provider}/{connection_id}` |
| `app/worker/__init__.py` | 空包标记 |
| `app/worker/celery_app.py` | Celery 实例与配置 |
| `app/worker/tasks.py` | `process_inbound_event` —— 一层薄壳,真逻辑在 runtime |
| `app/worker/queue.py` | `CeleryInboundQueue` —— `InboundQueue` 的生产实现 |
| `test/conformance.py` | 追加 `body_is_authenticated()` 钩子与 `test_rejects_a_forged_credential`(Task 2) |
| `app/runtime/__init__.py` | 空包标记 |
| `app/runtime/brain.py` | `DraftReply`、`Brain` Protocol、`EchoBrain` |
| `app/runtime/pipeline.py` | `run_inbound_pipeline` —— 事件到回复的编排 |
| `app/dispatch/__init__.py` | 空包标记 |
| `app/dispatch/ratelimit.py` | `RateLimiter` Protocol、`RedisTokenBucket`、`InMemoryTokenBucket` |
| `app/dispatch/dispatcher.py` | `chunk_text`、`DispatchResult`、`OutboundDispatcher` |
| `app/main.py` | 注册 webhooks 路由 |
| `app/core/config.py` | 追加 Celery 与限流设置 |
| `test/test_telegram_api.py` | HTTP 层:成功、429、4xx、网络错误 |
| `test/test_telegram_adapter.py` | conformance 子类 + Telegram 特有行为 |
| `test/test_registry.py` | 未知 provider、凭据装配、生产环境拒绝 fake |
| `test/test_inbound_models.py` | 两张新表的约束与去重唯一键 |
| `test/test_dedupe.py` | 去重语义,fake 与真实 Redis 各跑一遍 |
| `test/test_webhooks.py` | ingress:验签失败、重复、落库、ACK 快 |
| `test/test_worker_tasks.py` | Celery task 已注册且名字稳定 |
| `test/test_brain.py` | `EchoBrain` 与 `DraftReply` 约束 |
| `test/test_dispatcher.py` | 能力驱动:分片、窗口拒绝、媒体拒绝、限流、重试、failed_job |
| `test/test_pipeline_end_to_end.py` | webhook 进 → 回复出,全程 fake,零网络 |

---

### Task 1: Telegram Bot API 客户端

Telegram 的 HTTP 细节先单独关起来,适配器才可能在没有网络的情况下被测试。

**Files:**
- Create: `app/channels/telegram/__init__.py`, `app/channels/telegram/api.py`
- Test: `test/test_telegram_api.py`

**Interfaces:**
- Consumes: 无(本 task 是这条链路的最底层)
- Produces:
  - `TelegramApiResponse(ok: bool, result: dict | None = None, error_code: int | None = None, description: str | None = None, retry_after: int | None = None)`
  - `TelegramApi` Protocol:`async def call(self, token: str, method: str, payload: dict) -> TelegramApiResponse`
  - `HttpTelegramApi(api_base: str = "https://api.telegram.org", timeout: float = 10.0, client: httpx.AsyncClient | None = None)`
  - `FakeTelegramApi()` —— 属性 `calls: list[tuple[str, str, dict]]`、`responses: list[TelegramApiResponse]`(按序弹出)、`default_response: TelegramApiResponse`

- [x] **Step 1: 建包标记**

```bash
mkdir -p app/channels/telegram
touch app/channels/telegram/__init__.py
```

先留空。Task 2 写完适配器后再填导出。

- [x] **Step 2: 写会失败的测试 —— `test/test_telegram_api.py`**

```python
import httpx
import pytest

from app.channels.telegram.api import (
    FakeTelegramApi,
    HttpTelegramApi,
    TelegramApiResponse,
)


def _transport(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_a_successful_call_returns_the_result_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 77}})

    api = HttpTelegramApi(client=_transport(handler))
    response = await api.call("tok", "sendMessage", {"chat_id": "1", "text": "hi"})

    assert response.ok is True
    assert response.result == {"message_id": 77}


async def test_the_token_goes_in_the_path_and_never_in_the_query():
    """A token in a query string lands in every proxy and access log there is."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {}})

    api = HttpTelegramApi(client=_transport(handler))
    await api.call("secret-token", "getMe", {})

    assert seen[0].url.path == "/botsecret-token/getMe"
    assert "secret-token" not in str(seen[0].url.query)


async def test_a_rate_limit_surfaces_retry_after():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests: retry after 7",
                "parameters": {"retry_after": 7},
            },
        )

    api = HttpTelegramApi(client=_transport(handler))
    response = await api.call("tok", "sendMessage", {})

    assert response.ok is False
    assert response.error_code == 429
    assert response.retry_after == 7


async def test_a_rejected_request_reports_its_error_code():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, json={"ok": False, "error_code": 403, "description": "bot was blocked"}
        )

    api = HttpTelegramApi(client=_transport(handler))
    response = await api.call("tok", "sendMessage", {})

    assert response.ok is False
    assert response.error_code == 403
    assert "blocked" in response.description


async def test_a_transport_error_becomes_a_response_not_an_exception():
    """The dispatcher records outcomes. A raised exception would bypass it."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns went away")

    api = HttpTelegramApi(client=_transport(handler))
    response = await api.call("tok", "sendMessage", {})

    assert response.ok is False
    assert response.error_code is None
    assert "dns went away" in response.description


async def test_malformed_json_does_not_raise():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway</html>")

    api = HttpTelegramApi(client=_transport(handler))
    response = await api.call("tok", "sendMessage", {})

    assert response.ok is False
    assert response.description


async def test_the_fake_records_calls_and_replays_queued_responses():
    api = FakeTelegramApi()
    api.responses.append(TelegramApiResponse(ok=True, result={"message_id": 5}))

    first = await api.call("tok", "sendMessage", {"chat_id": "9"})
    second = await api.call("tok", "sendMessage", {"chat_id": "9"})

    assert first.result == {"message_id": 5}
    # Queue exhausted -> the default, so a test only queues what it cares about.
    assert second.ok is True
    assert api.calls == [
        ("tok", "sendMessage", {"chat_id": "9"}),
        ("tok", "sendMessage", {"chat_id": "9"}),
    ]


async def test_a_failed_response_must_carry_a_description():
    with pytest.raises(ValueError):
        TelegramApiResponse(ok=False)
```

- [x] **Step 3: 跑测试确认它失败**

```bash
.venv/bin/python -m pytest test/test_telegram_api.py -q
```

预期:`ModuleNotFoundError: No module named 'app.channels.telegram.api'`。

- [x] **Step 4: 写 `app/channels/telegram/api.py`**

```python
"""The HTTP half of the Telegram channel, isolated so the adapter is testable.

Nothing here knows about envelopes or connections. It turns a Bot API method
call into a structured response and never raises for an operational failure --
a blocked bot and a dead DNS server are both outcomes the dispatcher has to
record, not exceptions it has to catch.
"""

from typing import Any, ClassVar, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, model_validator

# Telegram's own host. It lives here rather than in app/core/config.py because
# no module outside app/channels/<provider>/ may name a provider -- and the
# hostname is the provider's name. Override per connection via
# ChannelConnection.config["api_base"].
DEFAULT_API_BASE = "https://api.telegram.org"


class TelegramApiResponse(BaseModel):
    """One Bot API outcome, success or failure, never an exception."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    result: dict[str, Any] | None = None
    # None means the call never reached Telegram: DNS, TLS, timeout.
    error_code: int | None = None
    description: str | None = None
    retry_after: int | None = None

    @model_validator(mode="after")
    def _failures_explain_themselves(self) -> "TelegramApiResponse":
        if not self.ok and not self.description:
            raise ValueError("a failed TelegramApiResponse must carry a description")
        return self


class TelegramApi(Protocol):
    """One Bot API call. Implementations must not raise for network failure."""

    async def call(
        self, token: str, method: str, payload: dict[str, Any]
    ) -> TelegramApiResponse: ...


class HttpTelegramApi:
    def __init__(
        self,
        api_base: str = DEFAULT_API_BASE,
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._timeout = timeout
        # An injected client is how tests reach a MockTransport. Owning one
        # per adapter instance would also leak a connection pool per webhook.
        self._client = client

    async def call(
        self, token: str, method: str, payload: dict[str, Any]
    ) -> TelegramApiResponse:
        # The token is a path segment, not a query parameter: query strings are
        # written to proxy and access logs, and this token is the whole bot.
        url = f"{self._api_base}/bot{token}/{method}"
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            raw = await client.post(url, json=payload, timeout=self._timeout)
        except httpx.HTTPError as exc:
            return TelegramApiResponse(ok=False, description=str(exc))
        finally:
            if self._client is None:
                await client.aclose()

        try:
            body = raw.json()
        except ValueError:
            return TelegramApiResponse(
                ok=False,
                error_code=raw.status_code,
                description=f"non-JSON response ({raw.status_code})",
            )

        if body.get("ok"):
            return TelegramApiResponse(ok=True, result=body.get("result") or {})

        return TelegramApiResponse(
            ok=False,
            error_code=body.get("error_code", raw.status_code),
            description=body.get("description") or f"HTTP {raw.status_code}",
            retry_after=(body.get("parameters") or {}).get("retry_after"),
        )


class FakeTelegramApi:
    """In-memory Bot API. Records every call; replays queued responses in order."""

    default_response: ClassVar[TelegramApiResponse] = TelegramApiResponse(
        ok=True, result={"message_id": 1}
    )

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.responses: list[TelegramApiResponse] = []

    async def call(
        self, token: str, method: str, payload: dict[str, Any]
    ) -> TelegramApiResponse:
        self.calls.append((token, method, payload))
        if self.responses:
            return self.responses.pop(0)
        return self.default_response
```

- [x] **Step 5: 跑测试确认通过**

```bash
.venv/bin/python -m pytest test/test_telegram_api.py -q
```

预期:8 passed。

- [x] **Step 6: 提交**

```bash
git add app/channels/telegram/ test/test_telegram_api.py
git commit -m "feat: telegram bot api client behind a protocol with a fake"
```

---

### Task 2: Telegram 适配器

**Files:**
- Create: `app/channels/telegram/adapter.py`
- Modify: `app/channels/telegram/__init__.py`, `test/conformance.py`
- Test: `test/test_telegram_adapter.py`

**Interfaces:**
- Consumes: Task 1 的 `TelegramApi`、`TelegramApiResponse`、`FakeTelegramApi`;`app/channels/types.py` 的 `Attachment`、`ChannelCapabilities`、`InboundEnvelope`、`OutboundMessage`、`SendResult`;`test/conformance.py` 的 `ChannelAdapterConformance`
- Produces: `TelegramAdapter(token: str, secret_token: str, api: TelegramApi | None = None, webhook_url: str | None = None, api_base: str = DEFAULT_API_BASE)`,`provider = "telegram"`,`SECRET_HEADER = "x-telegram-bot-api-secret-token"`,`FILE_URI_SCHEME = "tg-file://"`,`async def resolve_file_url(attachment_url: str) -> str | None`

**三个必须先讲清楚的设计决定:**

**1. 验签用的是 secret token,不是 HMAC。** Telegram 不给 webhook 请求签名。它的机制是:`setWebhook` 时提交一个 `secret_token`,之后每次投递都在 `X-Telegram-Bot-Api-Secret-Token` 头里原样回传。所以"验签"其实是常数时间的字符串比对 —— 但仍然必须用 `hmac.compare_digest`,因为 `==` 会在第一个不同字节处短路,把 token 泄漏成一个计时侧信道。

**2. 于是 conformance 套件里有一条 Telegram 过不了 —— 而且它不该过。** `test_rejects_a_tampered_body` 假定验签覆盖 payload 字节。对 HMAC 方案(Meta、Shopee)成立,对 Telegram 不成立:一个被回传的 token 证明的是"谁在调用",不是"他说了什么"。

**这条不能靠削弱套件来解决**,否则真正签名的适配器就失去了保护。正确做法是把这个差异**声明出来**:给套件加一个 `body_is_authenticated()` 钩子,默认 `True`,Telegram 显式覆盖成 `False`。这跟能力清单是同一个思路 —— 通道之间的分歧要被声明,不能被藏起来。

顺带记下这个差异的安全含义,因为它是真实的:Telegram 通道的全部保护就是 TLS 加上那个 secret token。谁拿到 token 谁就能伪造任意 payload。所以 token 必须是高熵随机串,而且和 bot token 一样按凭据对待。

**3. 附件在解析阶段拿不到 URL。** Telegram 的 webhook 只给 `file_id`,换成可下载的 URL 需要一次 `getFile` 调用 —— 那是网络 IO,而 `parse_inbound` 必须是纯函数(conformance 套件里的 `test_parse_is_pure` 就是在守这条,而且 ingress 在重放时会再解析一次同一个 payload)。

所以解析出的 `Attachment.url` 装的是 `tg-file://<file_id>`,由适配器自己的 `resolve_file_url()` 在真正要下载时兑现。这个 scheme 只有 Telegram 适配器认识,它不泄漏到管线的任何其他地方 —— 这正是通道差异应该被关住的方式。

- [x] **Step 1: 给 conformance 套件加上 body 认证钩子 —— `test/conformance.py`**

把 `test_rejects_a_tampered_body` 那一段替换成下面这三段(`test_accepts_an_authentic_delivery` 和 `test_rejects_a_delivery_with_no_headers` 保持原样,它们对两种方案都成立):

```python
    def body_is_authenticated(self) -> bool:
        """True when this adapter's scheme covers the payload bytes.

        An HMAC signature does; a secret token the provider merely echoes back
        does not -- it proves who is calling, not what they said. Declaring the
        difference is the same move as the capability manifest: channels
        disagree, and the disagreement belongs somewhere visible.
        """
        return True

    def test_rejects_a_tampered_body(self):
        if not self.body_is_authenticated():
            return
        headers, body = self.make_signed_webhook()
        assert self.make_adapter().verify_webhook(headers, body + b" ") is False

    def test_rejects_a_forged_credential(self):
        """Universal, unlike the one above. Whatever the scheme proves, a
        delivery that fails to prove it must be refused."""
        headers, body = self.make_signed_webhook()
        forged = {k: v + "x" for k, v in headers.items()}
        assert self.make_adapter().verify_webhook(forged, body) is False
```

- [x] **Step 2: 确认现有的 fake 适配器仍然通过**

`FakeAdapter` 用的是真 HMAC,所以默认的 `body_is_authenticated() -> True` 对它成立,不需要改 `test/test_fake_adapter.py`。

```bash
.venv/bin/python -m pytest test/test_fake_adapter.py -q
```

预期:全绿,并且比之前多一项(新增的 `test_rejects_a_forged_credential`)。

- [x] **Step 3: 写会失败的测试 —— `test/test_telegram_adapter.py`**

```python
from datetime import timezone

import pytest

from app.channels.telegram.adapter import SECRET_HEADER, TelegramAdapter
from app.channels.telegram.api import FakeTelegramApi, TelegramApiResponse
from app.channels.types import OutboundMessage
from app.models.channel_connection import ChannelConnection
from test.conformance import ChannelAdapterConformance

SECRET = "s3cr3t-token"


def make_adapter(api: FakeTelegramApi | None = None) -> TelegramAdapter:
    return TelegramAdapter(
        token="123:ABC",
        secret_token=SECRET,
        api=api or FakeTelegramApi(),
        webhook_url="https://example.test/webhooks/telegram/1",
    )


def text_update(update_id: int = 900) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 42,
            "date": 1_757_000_000,
            "chat": {"id": -100123, "type": "private"},
            "from": {"id": 555, "is_bot": False, "first_name": "Siti"},
            "text": "where is my parcel",
        },
    }


class TestTelegramConformance(ChannelAdapterConformance):
    """The shared contract. Four hooks, and Telegram is held to the same
    definition of correct as every other channel."""

    def make_adapter(self):
        return make_adapter()

    def make_connection(self) -> ChannelConnection:
        return ChannelConnection(
            id=1, bot_id=1, provider="telegram", external_ref="@botly_test_bot"
        )

    def make_signed_webhook(self) -> tuple[dict[str, str], bytes]:
        return {SECRET_HEADER: SECRET}, b'{"update_id": 1}'

    def make_inbound_payload(self) -> dict:
        return text_update()

    def body_is_authenticated(self) -> bool:
        # Telegram signs nothing. It echoes the secret_token given to
        # setWebhook, which proves who is calling and not what they said.
        return False


# --- Telegram-specific behaviour -------------------------------------------


def test_a_wrong_secret_is_rejected():
    assert make_adapter().verify_webhook({SECRET_HEADER: "wrong"}, b"{}") is False


def test_a_tampered_body_with_a_valid_secret_is_accepted():
    """Documented, not desired.

    Telegram's scheme does not cover the payload, so anyone holding the secret
    token can send any body. The protection is TLS plus the secrecy of that
    token -- which is why it must be high-entropy and treated as a credential.
    This test exists so the property is written down rather than discovered.
    """
    adapter = make_adapter()
    assert adapter.verify_webhook({SECRET_HEADER: SECRET}, b'{"anything": true}')


def test_the_secret_header_is_matched_case_insensitively():
    """Header casing is not guaranteed across proxies; the value is exact."""
    adapter = make_adapter()
    assert adapter.verify_webhook({"X-Telegram-Bot-Api-Secret-Token": SECRET}, b"{}")


def test_a_text_message_parses_into_one_envelope():
    [envelope] = make_adapter().parse_inbound(text_update())

    assert envelope.provider == "telegram"
    assert envelope.external_thread_id == "-100123"
    assert envelope.provider_update_id == "900"
    assert envelope.provider_message_id == "42"
    assert envelope.sender_ref == "555"
    assert envelope.text == "where is my parcel"
    assert envelope.sent_at.tzinfo is not None
    assert envelope.sent_at.astimezone(timezone.utc).year == 2025


def test_the_raw_update_is_kept_on_the_envelope():
    """Ingress persists it, and a parser bug found next month is only
    debuggable against the bytes that actually arrived."""
    payload = text_update()
    [envelope] = make_adapter().parse_inbound(payload)

    assert envelope.raw == payload


def test_an_edited_message_is_parsed_too():
    payload = {
        "update_id": 901,
        "edited_message": {
            "message_id": 43,
            "date": 1_757_000_100,
            "chat": {"id": 7, "type": "private"},
            "from": {"id": 8},
            "text": "actually, order 12345",
        },
    }
    [envelope] = make_adapter().parse_inbound(payload)

    assert envelope.text == "actually, order 12345"


def test_a_photo_becomes_an_attachment_carrying_the_largest_file_id():
    """Telegram sends one entry per resolution. The last is the biggest, and
    OCR on a thumbnail reads nothing."""
    payload = {
        "update_id": 902,
        "message": {
            "message_id": 44,
            "date": 1_757_000_200,
            "chat": {"id": 7, "type": "private"},
            "from": {"id": 8},
            "photo": [
                {"file_id": "small", "width": 90},
                {"file_id": "large", "width": 1280},
            ],
        },
    }
    [envelope] = make_adapter().parse_inbound(payload)
    [attachment] = envelope.attachments

    assert attachment.kind == "image"
    assert attachment.url == "tg-file://large"


def test_a_document_becomes_an_attachment_with_its_mime_type():
    payload = {
        "update_id": 903,
        "message": {
            "message_id": 45,
            "date": 1_757_000_300,
            "chat": {"id": 7, "type": "private"},
            "from": {"id": 8},
            "document": {
                "file_id": "doc1",
                "mime_type": "application/pdf",
                "file_size": 2048,
            },
        },
    }
    [envelope] = make_adapter().parse_inbound(payload)
    [attachment] = envelope.attachments

    assert attachment.kind == "file"
    assert attachment.url == "tg-file://doc1"
    assert attachment.mime_type == "application/pdf"
    assert attachment.size_bytes == 2048


def test_a_non_message_update_yields_nothing_rather_than_failing():
    """A delivery receipt is not an error. Returning [] is how the adapter
    says 'nothing actionable', and ingress must still ACK 200."""
    payload = {"update_id": 904, "poll_answer": {"poll_id": "p", "option_ids": [1]}}

    assert make_adapter().parse_inbound(payload) == []


def test_an_empty_message_with_no_text_and_no_media_yields_nothing():
    """Chat-member joins arrive as a message with nothing in it. An envelope
    with neither text nor attachment cannot be constructed, and should not be."""
    payload = {
        "update_id": 905,
        "message": {
            "message_id": 46,
            "date": 1_757_000_400,
            "chat": {"id": 7, "type": "private"},
            "from": {"id": 8},
            "new_chat_members": [{"id": 99}],
        },
    }

    assert make_adapter().parse_inbound(payload) == []


async def test_send_posts_a_message_and_reports_the_provider_id():
    api = FakeTelegramApi()
    api.responses.append(TelegramApiResponse(ok=True, result={"message_id": 4321}))
    conn = ChannelConnection(id=1, bot_id=1, provider="telegram", external_ref="@b")

    result = await make_adapter(api).send(
        conn, OutboundMessage(text="your parcel is out for delivery")
    )

    assert result.ok is True
    assert result.provider_message_id == "4321"
    token, method, payload = api.calls[0]
    assert method == "sendMessage"
    assert payload["text"] == "your parcel is out for delivery"


async def test_send_targets_the_thread_from_the_connection_config():
    api = FakeTelegramApi()
    conn = ChannelConnection(
        id=1, bot_id=1, provider="telegram", external_ref="@b",
        config={"chat_id": "-100123"},
    )

    await make_adapter(api).send(conn, OutboundMessage(text="hi"))

    assert api.calls[0][2]["chat_id"] == "-100123"


async def test_a_rate_limited_send_is_retryable():
    api = FakeTelegramApi()
    api.responses.append(
        TelegramApiResponse(
            ok=False, error_code=429, description="Too Many Requests", retry_after=3
        )
    )
    conn = ChannelConnection(id=1, bot_id=1, provider="telegram", external_ref="@b")

    result = await make_adapter(api).send(conn, OutboundMessage(text="hi"))

    assert result.ok is False
    assert result.retryable is True


async def test_a_blocked_bot_is_not_retryable():
    """Retrying a 403 forever is how a queue dies. It belongs in failed_job."""
    api = FakeTelegramApi()
    api.responses.append(
        TelegramApiResponse(ok=False, error_code=403, description="bot was blocked")
    )
    conn = ChannelConnection(id=1, bot_id=1, provider="telegram", external_ref="@b")

    result = await make_adapter(api).send(conn, OutboundMessage(text="hi"))

    assert result.ok is False
    assert result.retryable is False


async def test_a_transport_failure_is_retryable():
    api = FakeTelegramApi()
    api.responses.append(TelegramApiResponse(ok=False, description="connection reset"))
    conn = ChannelConnection(id=1, bot_id=1, provider="telegram", external_ref="@b")

    result = await make_adapter(api).send(conn, OutboundMessage(text="hi"))

    assert result.retryable is True


async def test_connect_registers_the_webhook_with_the_secret():
    api = FakeTelegramApi()
    conn = ChannelConnection(id=1, bot_id=1, provider="telegram", external_ref="@b")

    await make_adapter(api).connect(conn)

    _, method, payload = api.calls[0]
    assert method == "setWebhook"
    assert payload["secret_token"] == SECRET
    assert payload["url"] == "https://example.test/webhooks/telegram/1"


async def test_connect_without_a_webhook_url_is_refused_loudly():
    """A silent no-op here means a bot that is 'connected' and deaf."""
    adapter = TelegramAdapter(token="1:A", secret_token=SECRET, api=FakeTelegramApi())
    conn = ChannelConnection(id=1, bot_id=1, provider="telegram", external_ref="@b")

    with pytest.raises(ValueError):
        await adapter.connect(conn)


async def test_disconnect_deletes_the_webhook():
    api = FakeTelegramApi()
    conn = ChannelConnection(id=1, bot_id=1, provider="telegram", external_ref="@b")

    await make_adapter(api).disconnect(conn)

    assert api.calls[0][1] == "deleteWebhook"


async def test_resolve_file_url_exchanges_a_file_id_for_a_download_url():
    api = FakeTelegramApi()
    api.responses.append(
        TelegramApiResponse(ok=True, result={"file_path": "photos/x.jpg"})
    )

    url = await make_adapter(api).resolve_file_url("tg-file://large")

    assert url == "https://api.telegram.org/file/bot123:ABC/photos/x.jpg"
    assert api.calls[0][2] == {"file_id": "large"}


async def test_resolve_file_url_returns_none_when_the_file_is_gone():
    api = FakeTelegramApi()
    api.responses.append(TelegramApiResponse(ok=False, description="file not found"))

    assert await make_adapter(api).resolve_file_url("tg-file://gone") is None
```

- [x] **Step 4: 跑测试确认它失败**

```bash
.venv/bin/python -m pytest test/test_telegram_adapter.py -q
```

预期:`ModuleNotFoundError: No module named 'app.channels.telegram.adapter'`。

- [x] **Step 5: 写 `app/channels/telegram/adapter.py`**

```python
"""The Telegram channel. The only module in the codebase that knows what a
Telegram Update looks like.

Telegram is build-order step 3 because it has no gatekeeper: a BotFather token
and a webhook. That makes it the channel that proves the whole pipeline while
the Shopee and WhatsApp approvals are still in a queue somewhere.
"""

import hmac
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, ClassVar

from app.channels.telegram.api import (
    DEFAULT_API_BASE,
    HttpTelegramApi,
    TelegramApi,
)
from app.channels.types import (
    Attachment,
    ChannelCapabilities,
    InboundEnvelope,
    OutboundMessage,
    SendResult,
)
from app.models.channel_connection import ChannelConnection

SECRET_HEADER = "x-telegram-bot-api-secret-token"

# Attachments arrive as file_ids, not URLs. Resolving one costs a getFile call,
# and parse_inbound must stay pure -- ingress reparses the stored payload on
# replay. So the file_id travels under a scheme only this module understands,
# and resolve_file_url() cashes it in when something actually needs the bytes.
FILE_URI_SCHEME = "tg-file://"

# The update keys that can carry a customer message. Anything else -- poll
# answers, chat member changes, delivery receipts -- is not actionable.
_MESSAGE_KEYS = ("message", "edited_message", "channel_post", "edited_channel_post")


class TelegramAdapter:
    provider: ClassVar[str] = "telegram"
    capabilities: ClassVar[ChannelCapabilities] = ChannelCapabilities(
        supports_media=True,
        # Bot API hard limit on sendMessage text.
        max_text_len=4096,
        # Telegram never closes. No window, so no template rule either.
        session_window=None,
        requires_template_outside_window=False,
        supports_typing_indicator=True,
    )

    def __init__(
        self,
        token: str,
        secret_token: str,
        api: TelegramApi | None = None,
        webhook_url: str | None = None,
        api_base: str = DEFAULT_API_BASE,
    ) -> None:
        self._token = token
        self._secret_token = secret_token
        self._api = api or HttpTelegramApi(api_base=api_base)
        self._webhook_url = webhook_url
        self._api_base = api_base.rstrip("/")

    # --- webhook verification ---------------------------------------------

    def verify_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        """Telegram does not sign deliveries. It echoes the secret_token given
        to setWebhook, so authenticity is a constant-time string compare.

        compare_digest rather than ``==``: equality short-circuits on the first
        differing byte, which turns the token into a timing oracle.
        """
        offered = next(
            (v for k, v in headers.items() if k.lower() == SECRET_HEADER), None
        )
        if offered is None:
            return False
        return hmac.compare_digest(offered, self._secret_token)

    # --- parsing ------------------------------------------------------------

    def parse_inbound(self, payload: dict[str, Any]) -> list[InboundEnvelope]:
        """One Update in, zero or one envelope out.

        Zero is a normal, expected answer. Telegram sends plenty of updates
        that are not a customer saying something.
        """
        message = next(
            (payload[key] for key in _MESSAGE_KEYS if isinstance(payload.get(key), dict)),
            None,
        )
        if message is None:
            return []

        text = message.get("text") or message.get("caption")
        attachments = self._attachments(message)
        if text is None and not attachments:
            # A join notice, a pinned-message event: a message object with no
            # message in it. An envelope cannot represent that, and shouldn't.
            return []

        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        return [
            InboundEnvelope(
                provider=self.provider,
                external_thread_id=str(chat.get("id", "")),
                provider_update_id=str(payload["update_id"]),
                provider_message_id=str(message["message_id"]),
                sender_ref=str(sender.get("id") or chat.get("id", "")),
                text=text,
                attachments=attachments,
                sent_at=datetime.fromtimestamp(message["date"], tz=timezone.utc),
                raw=payload,
            )
        ]

    def _attachments(self, message: dict[str, Any]) -> tuple[Attachment, ...]:
        found: list[Attachment] = []

        photos = message.get("photo")
        if photos:
            # One entry per resolution, ascending. OCR on a thumbnail reads
            # nothing, so take the last.
            largest = photos[-1]
            found.append(
                Attachment(
                    kind="image",
                    url=FILE_URI_SCHEME + largest["file_id"],
                    size_bytes=largest.get("file_size"),
                )
            )

        for key, kind in (("video", "video"), ("voice", "audio"), ("audio", "audio")):
            item = message.get(key)
            if isinstance(item, dict) and item.get("file_id"):
                found.append(
                    Attachment(
                        kind=kind,
                        url=FILE_URI_SCHEME + item["file_id"],
                        mime_type=item.get("mime_type"),
                        size_bytes=item.get("file_size"),
                    )
                )

        document = message.get("document")
        if isinstance(document, dict) and document.get("file_id"):
            found.append(
                Attachment(
                    kind="file",
                    url=FILE_URI_SCHEME + document["file_id"],
                    mime_type=document.get("mime_type"),
                    size_bytes=document.get("file_size"),
                )
            )

        return tuple(found)

    async def resolve_file_url(self, attachment_url: str) -> str | None:
        """Cash a tg-file:// reference in for a real download URL."""
        file_id = attachment_url.removeprefix(FILE_URI_SCHEME)
        response = await self._api.call(self._token, "getFile", {"file_id": file_id})
        if not response.ok:
            return None
        file_path = (response.result or {}).get("file_path")
        if not file_path:
            return None
        return f"{self._api_base}/file/bot{self._token}/{file_path}"

    # --- sending ------------------------------------------------------------

    async def send(self, conn: ChannelConnection, out: OutboundMessage) -> SendResult:
        chat_id = (conn.config or {}).get("chat_id") or conn.external_ref
        response = await self._api.call(
            self._token,
            "sendMessage",
            {"chat_id": chat_id, "text": out.text or ""},
        )
        if response.ok:
            return SendResult(
                ok=True,
                provider_message_id=str((response.result or {}).get("message_id", "")),
            )

        # error_code is None when the call never reached Telegram. A rate limit
        # and a 5xx are worth backing off on; a 403 from a blocked bot is not,
        # and retrying it forever is how a queue dies.
        code = response.error_code
        retryable = code is None or code == 429 or code >= 500
        return SendResult(ok=False, error=response.description, retryable=retryable)

    # --- lifecycle ----------------------------------------------------------

    async def connect(self, conn: ChannelConnection) -> None:
        if not self._webhook_url:
            raise ValueError(
                "TelegramAdapter needs a webhook_url to connect; without one "
                "setWebhook would silently leave the bot deaf."
            )
        await self._api.call(
            self._token,
            "setWebhook",
            {
                "url": self._webhook_url,
                "secret_token": self._secret_token,
                "allowed_updates": list(_MESSAGE_KEYS),
                # Idempotent: re-registering the same URL is a no-op upstream.
                "drop_pending_updates": False,
            },
        )

    async def disconnect(self, conn: ChannelConnection) -> None:
        # Safe before connect and safe twice: deleteWebhook on a bot with no
        # webhook returns ok.
        await self._api.call(self._token, "deleteWebhook", {})
```

- [x] **Step 6: 填 `app/channels/telegram/__init__.py`**

```python
"""The Telegram channel."""

from app.channels.telegram.adapter import TelegramAdapter

__all__ = ["TelegramAdapter"]
```

- [x] **Step 7: 跑测试确认通过**

```bash
.venv/bin/python -m pytest test/test_telegram_adapter.py -q
```

预期:conformance 套件的 18 项 + Telegram 特有的 20 项全绿。

- [x] **Step 8: 跑整个套件,确认架构守卫没被触发**

```bash
.venv/bin/python -m pytest -q
```

预期:全绿。特别确认 `test_no_module_outside_channels_names_a_provider` 仍然通过 —— 如果它红了,说明有个 `telegram` 字面量跑到 `app/channels/` 外面去了,把它挪回适配器目录,不要去改守卫。

- [x] **Step 9: 提交**

```bash
git add app/channels/telegram/ test/conformance.py test/test_telegram_adapter.py
git commit -m "feat: telegram channel adapter passing the conformance suite"
```

---

### Task 3: 适配器注册表

管线需要从一个 `ChannelConnection` 拿到一个能用的适配器。这个查表动作是整个系统里唯一一处按 provider 名字分发的地方,所以它必须住在 `app/channels/` 下。

**Files:**
- Create: `app/channels/registry.py`
- Test: `test/test_registry.py`

**Interfaces:**
- Consumes: `TelegramAdapter`(Task 2)、`FakeAdapter`、`ChannelConnection`
- Produces: `build_adapter(conn: ChannelConnection, webhook_url: str | None = None) -> ChannelAdapter`、`UnknownProvider(LookupError)`、`MissingCredentials(ValueError)`

- [x] **Step 1: 写会失败的测试 —— `test/test_registry.py`**

```python
import pytest

from app.channels.fake.adapter import FakeAdapter
from app.channels.registry import (
    MissingCredentials,
    UnknownProvider,
    build_adapter,
)
from app.channels.telegram.adapter import TelegramAdapter
from app.models.channel_connection import ChannelConnection


def telegram_connection() -> ChannelConnection:
    conn = ChannelConnection(
        id=1, bot_id=1, provider="telegram", external_ref="@botly_test_bot"
    )
    conn.set_credentials({"bot_token": "123:ABC", "secret_token": "s3cr3t"})
    return conn


def test_a_telegram_connection_builds_a_telegram_adapter():
    adapter = build_adapter(telegram_connection())

    assert isinstance(adapter, TelegramAdapter)
    assert type(adapter).provider == "telegram"


def test_the_webhook_url_is_passed_through_so_connect_works():
    adapter = build_adapter(
        telegram_connection(), webhook_url="https://example.test/webhooks/telegram/1"
    )

    assert adapter._webhook_url == "https://example.test/webhooks/telegram/1"


def test_an_unknown_provider_is_a_named_error_not_a_keyerror():
    conn = ChannelConnection(id=1, bot_id=1, provider="carrier-pigeon", external_ref="x")

    with pytest.raises(UnknownProvider) as exc:
        build_adapter(conn)

    assert "carrier-pigeon" in str(exc.value)


def test_missing_credentials_are_a_named_error_not_a_keyerror():
    """A KeyError raised inside a builder must not be mistaken for an unknown
    provider -- that is the classic dict.get-versus-try/except bug, and it
    would report a configuration problem as a missing channel."""
    conn = ChannelConnection(id=1, bot_id=1, provider="telegram", external_ref="@b")
    conn.set_credentials({"bot_token": "123:ABC"})  # secret_token absent

    with pytest.raises(MissingCredentials) as exc:
        build_adapter(conn)

    assert "secret_token" in str(exc.value)


def test_a_fake_connection_builds_the_fake_adapter():
    """Registered on purpose: the end-to-end test must exercise the real
    lookup path, not tiptoe around it."""
    conn = ChannelConnection(id=1, bot_id=1, provider="fake", external_ref="x")

    assert isinstance(build_adapter(conn), FakeAdapter)


def test_production_refuses_to_build_the_fake_adapter(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(type(settings), "is_production", property(lambda self: True))
    conn = ChannelConnection(id=1, bot_id=1, provider="fake", external_ref="x")

    with pytest.raises(UnknownProvider):
        build_adapter(conn)
```

- [x] **Step 2: 跑测试确认它失败**

```bash
.venv/bin/python -m pytest test/test_registry.py -q
```

预期:`ModuleNotFoundError: No module named 'app.channels.registry'`。

- [x] **Step 3: 写 `app/channels/registry.py`**

```python
"""Connection to adapter. The one dispatch point on a provider name.

It lives inside app/channels/ deliberately: this is the single place allowed to
import concrete adapters and to know their names. Everything upstream -- the
webhook route, the worker, the dispatcher -- takes an adapter and asks it
questions.

Note that app/channels/__init__.py still imports no concrete adapter. Importing
this module is an explicit act.
"""

from collections.abc import Callable

from app.channels.base import ChannelAdapter
from app.channels.fake.adapter import FakeAdapter
from app.channels.telegram.adapter import TelegramAdapter
from app.channels.telegram.api import DEFAULT_API_BASE
from app.core.config import settings
from app.models.channel_connection import ChannelConnection


class UnknownProvider(LookupError):
    """No adapter is registered for this connection's provider."""


class MissingCredentials(ValueError):
    """The connection exists but its credential blob is incomplete."""


def _require(credentials: dict, key: str, provider: str) -> str:
    try:
        return credentials[key]
    except KeyError:
        raise MissingCredentials(
            f"{provider} connection is missing {key!r} in its credentials"
        ) from None


def _build_telegram(
    conn: ChannelConnection, webhook_url: str | None
) -> ChannelAdapter:
    credentials = conn.get_credentials()
    return TelegramAdapter(
        token=_require(credentials, "bot_token", TelegramAdapter.provider),
        secret_token=_require(credentials, "secret_token", TelegramAdapter.provider),
        webhook_url=webhook_url,
        # Provider-neutral key, so the pipeline never learns whose base it is.
        api_base=(conn.config or {}).get("api_base") or DEFAULT_API_BASE,
    )


def _build_fake(conn: ChannelConnection, webhook_url: str | None) -> ChannelAdapter:
    if settings.is_production:
        raise UnknownProvider(
            "the in-memory channel is not available in production"
        )
    return FakeAdapter()


_BUILDERS: dict[str, Callable[[ChannelConnection, str | None], ChannelAdapter]] = {
    TelegramAdapter.provider: _build_telegram,
    FakeAdapter.provider: _build_fake,
}


def build_adapter(
    conn: ChannelConnection, webhook_url: str | None = None
) -> ChannelAdapter:
    # .get() then an explicit check, not try/except KeyError around the call:
    # a KeyError raised *inside* a builder is a missing credential, and
    # wrapping the call would report it as an unknown provider.
    builder = _BUILDERS.get(conn.provider)
    if builder is None:
        raise UnknownProvider(f"no adapter registered for provider {conn.provider!r}")
    return builder(conn, webhook_url)
```

- [x] **Step 4: 跑测试确认通过**

```bash
.venv/bin/python -m pytest test/test_registry.py -q
```

预期:6 passed。

- [x] **Step 5: 提交**

```bash
git add app/channels/registry.py test/test_registry.py
git commit -m "feat: adapter registry, the one dispatch point on a provider name"
```

---

### Task 4: `inbound_event` 与 `failed_job` 两张表

**Files:**
- Create: `app/models/inbound_event.py`, `app/models/failed_job.py`
- Modify: `app/models/__init__.py`
- Create: `migration/versions/<autogenerated>_inbound_events_and_failed_jobs.py`
- Test: `test/test_inbound_models.py`

**Interfaces:**
- Consumes: `app/models/base.py` 的 `TimestampMixin`、`utcnow`
- Produces:
  - `InboundEventStatus`(`PENDING`/`PROCESSED`/`FAILED`)
  - `InboundEvent(connection_id, provider, provider_update_id, payload, status, processed_at, error)`,唯一约束 `(provider, provider_update_id)`
  - `FailedJob(kind, connection_id, inbound_event_id, payload, error, attempts)`

- [x] **Step 1: 写会失败的测试 —— `test/test_inbound_models.py`**

```python
import pytest
from sqlalchemy.exc import IntegrityError

from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection
from app.models.failed_job import FailedJob
from app.models.inbound_event import InboundEvent, InboundEventStatus
from app.models.merchant import Merchant
from app.models.shop import Shop

pytestmark = pytest.mark.integration


async def _connection(db_session) -> ChannelConnection:
    merchant = Merchant(name="Kedai Siti")
    db_session.add(merchant)
    await db_session.flush()
    shop = Shop(merchant_id=merchant.id, name="Kedai Siti Official", platform="standalone")
    db_session.add(shop)
    await db_session.flush()
    bot = Bot(shop_id=shop.id, name="Siti Bot")
    db_session.add(bot)
    await db_session.flush()
    conn = ChannelConnection(bot_id=bot.id, provider="telegram", external_ref="@siti_bot")
    db_session.add(conn)
    await db_session.flush()
    return conn


async def test_an_inbound_event_stores_its_raw_payload(db_session):
    conn = await _connection(db_session)
    event = InboundEvent(
        connection_id=conn.id,
        provider="telegram",
        provider_update_id="900",
        payload={"update_id": 900, "message": {"text": "hi"}},
    )
    db_session.add(event)
    await db_session.flush()

    assert event.id is not None
    assert event.status is InboundEventStatus.PENDING
    assert event.payload["message"]["text"] == "hi"
    assert event.processed_at is None


async def test_the_same_update_cannot_be_stored_twice(db_session):
    """The second line of dedupe defence. Redis is the fast one and Redis can
    be flushed; this constraint is what makes a double-delivery impossible
    rather than merely unlikely."""
    conn = await _connection(db_session)
    for _ in range(2):
        db_session.add(
            InboundEvent(
                connection_id=conn.id,
                provider="telegram",
                provider_update_id="901",
                payload={},
            )
        )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_two_providers_may_share_an_update_id(db_session):
    """Update ids are only unique within a provider."""
    conn = await _connection(db_session)
    db_session.add(
        InboundEvent(
            connection_id=conn.id, provider="telegram", provider_update_id="1", payload={}
        )
    )
    db_session.add(
        InboundEvent(
            connection_id=conn.id, provider="fake", provider_update_id="1", payload={}
        )
    )

    await db_session.flush()


async def test_created_timestamps_are_timezone_aware(db_session):
    conn = await _connection(db_session)
    event = InboundEvent(
        connection_id=conn.id, provider="telegram", provider_update_id="902", payload={}
    )
    db_session.add(event)
    await db_session.flush()

    assert event.created_at.utcoffset() is not None


async def test_a_failed_job_records_the_payload_and_the_error(db_session):
    conn = await _connection(db_session)
    job = FailedJob(
        kind="outbound",
        connection_id=conn.id,
        payload={"text": "your parcel is out for delivery"},
        error="bot was blocked",
        attempts=3,
    )
    db_session.add(job)
    await db_session.flush()

    assert job.id is not None
    assert job.attempts == 3


async def test_a_failed_job_survives_its_connection(db_session):
    """Deleting a connection must not erase the record of what went wrong on
    it -- that history is the whole point of the table."""
    conn = await _connection(db_session)
    job = FailedJob(kind="outbound", connection_id=conn.id, payload={}, error="boom")
    db_session.add(job)
    await db_session.flush()

    await db_session.delete(conn)
    await db_session.flush()
    await db_session.refresh(job)

    assert job.connection_id is None
    assert job.error == "boom"
```

- [x] **Step 2: 跑测试确认它失败**

```bash
.venv/bin/python -m pytest test/test_inbound_models.py -q
```

预期:`ModuleNotFoundError: No module named 'app.models.inbound_event'`。

- [x] **Step 3: 写 `app/models/inbound_event.py`**

```python
from datetime import datetime
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin


class InboundEventStatus(str, Enum):
    PENDING = "pending"
    PROCESSED = "processed"
    # The worker gave up. The row stays, and a FailedJob points at it.
    FAILED = "failed"


class InboundEvent(TimestampMixin, SQLModel, table=True):
    """One webhook delivery, stored raw before it is acted on.

    No soft delete: this is an event log, and an event that arrived cannot
    later not have arrived. The raw payload is kept because a parser bug found
    next month is only debuggable against the bytes that actually came in.
    """

    __tablename__ = "inbound_events"
    __table_args__ = (
        # The second line of dedupe defence, behind Redis. Redis is the fast
        # path and Redis can be flushed; this makes double-processing
        # impossible rather than merely unlikely.
        UniqueConstraint(
            "provider", "provider_update_id", name="uq_inbound_events_dedupe"
        ),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    connection_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("channel_connections.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    provider: str = Field(sa_column=Column(String(32), nullable=False))
    provider_update_id: str = Field(sa_column=Column(String(191), nullable=False))
    payload: dict = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    status: InboundEventStatus = Field(
        default=InboundEventStatus.PENDING,
        sa_column=Column(
            String(16), nullable=False, server_default="pending", index=True
        ),
    )
    processed_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True), nullable=True
    )
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
```

- [x] **Step 4: 写 `app/models/failed_job.py`**

```python
from sqlalchemy import BigInteger, Column, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin


class FailedJob(TimestampMixin, SQLModel, table=True):
    """Work that will not be retried again, kept so a human can see it.

    A permanent send failure has to reach the seller inbox as "delivery
    failed"; a poison inbound event has to leave the queue without blocking it.
    Both land here.
    """

    __tablename__ = "failed_jobs"

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    # "inbound" | "outbound". A plain string: a new kind of job must not need
    # a migration.
    kind: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    # SET NULL, not CASCADE: deleting a connection must not erase the record of
    # what went wrong on it.
    connection_id: int | None = Field(
        default=None,
        sa_column=Column(
            BigInteger,
            ForeignKey("channel_connections.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    inbound_event_id: int | None = Field(
        default=None,
        sa_column=Column(
            BigInteger,
            ForeignKey("inbound_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    payload: dict = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    error: str = Field(sa_column=Column(Text, nullable=False))
    attempts: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
```

- [x] **Step 5: 在 `app/models/__init__.py` 里登记两个新模型**

漏掉这一步的后果是:表从 `SQLModel.metadata` 里消失,于是从每一次 autogenerate 里消失 —— 而且没有任何报错。

```python
"""Model registry.

Importing a model class is what registers its table on ``SQLModel.metadata``.
Alembic autogenerate reads that metadata, so a model missing from this file is
a model missing from every migration -- and the omission is silent.
"""

from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection, ChannelConnectionStatus
from app.models.failed_job import FailedJob
from app.models.inbound_event import InboundEvent, InboundEventStatus
from app.models.merchant import Merchant
from app.models.shop import Shop

__all__ = [
    "Bot",
    "ChannelConnection",
    "ChannelConnectionStatus",
    "FailedJob",
    "InboundEvent",
    "InboundEventStatus",
    "Merchant",
    "Shop",
]
```

- [x] **Step 6: 跑模型测试确认通过**

```bash
.venv/bin/python -m pytest test/test_inbound_models.py -q
```

预期:6 passed。测试用的 schema 是从 metadata 直接建的,所以这时候还没有迁移也能过 —— 下一步补迁移,`test_migrations.py` 是唯一会发现缺迁移的测试。

- [x] **Step 7: 生成迁移**

```bash
.venv/bin/python -m alembic revision --autogenerate -m "inbound events and failed jobs"
```

- [x] **Step 8: 读一遍生成的迁移**

autogenerate 会猜错东西,不要盲签。打开 `migration/versions/` 里新出现的文件,确认 `upgrade()` 大致是这样:

```python
def upgrade() -> None:
    op.create_table(
        "inbound_events",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("connection_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_update_id", sa.String(length=191), nullable=False),
        sa.Column("payload", postgresql.JSONB(...), server_default="{}", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["connection_id"], ["channel_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_update_id", name="uq_inbound_events_dedupe"),
    )
    op.create_index(..., "inbound_events", ["connection_id"], unique=False)
    op.create_index(..., "inbound_events", ["status"], unique=False)
    op.create_table(
        "failed_jobs",
        ...
        sa.ForeignKeyConstraint(["connection_id"], ["channel_connections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["inbound_event_id"], ["inbound_events.id"], ondelete="SET NULL"),
    )
```

必须逐项核对的三件事:

1. **建表顺序**:`inbound_events` 要在 `failed_jobs` 之前,后者外键指向前者。autogenerate 按字母序排,会把 `failed_jobs` 排在前面 —— **这会让 upgrade 直接报错**。如果顺序反了,手工把两个 `create_table` 调换。
2. **两个 `ondelete`**:`CASCADE` 和 `SET NULL` 各自在对的位置上。
3. **`down_revision`** 指向 `243f3fa1ee04`。

- [x] **Step 9: 跑迁移漂移测试**

```bash
.venv/bin/python -m pytest test/test_migrations.py -q
```

预期:2 passed。`test_migrations_produce_the_same_schema_as_the_models` 会把库推倒重建再 upgrade,然后对比 metadata —— 它红了就说明迁移和模型不一致,改迁移,别改模型。

- [x] **Step 10: 跑整个套件并提交**

```bash
.venv/bin/python -m pytest -q
git add app/models/ migration/versions/ test/test_inbound_models.py
git commit -m "feat: inbound_event and failed_job tables"
```

---

### Task 5: 去重存储

**Files:**
- Create: `app/ingress/__init__.py`, `app/ingress/dedupe.py`
- Modify: `app/core/config.py`
- Test: `test/test_dedupe.py`

**Interfaces:**
- Consumes: `settings.REDIS_URL`
- Produces:
  - `DedupeStore` Protocol:`async def claim(self, key: str) -> bool`
  - `RedisDedupeStore(client, ttl_seconds: int = 86_400)`
  - `InMemoryDedupeStore()` —— 属性 `claimed: set[str]`
  - `dedupe_key(provider: str, provider_update_id: str) -> str`

- [ ] **Step 1: 写会失败的测试 —— `test/test_dedupe.py`**

```python
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
```

- [ ] **Step 2: 跑测试确认它失败**

```bash
.venv/bin/python -m pytest test/test_dedupe.py -q
```

预期:`ModuleNotFoundError: No module named 'app.ingress'`。

- [ ] **Step 3: 写 `app/ingress/dedupe.py`**

```python
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
```

`app/ingress/__init__.py` 留空。

- [ ] **Step 4: 在 config 里加去重 TTL**

在 `app/core/config.py` 的 `Settings` 里,`CREDENTIALS_ENCRYPTION_KEY` 那一行下面加:

```python
    # One day. Long enough to outlive any provider's retry schedule, short
    # enough that the keyspace does not grow without bound.
    DEDUPE_TTL_SECONDS: int = 86_400
```

- [ ] **Step 5: 跑测试确认通过**

```bash
.venv/bin/python -m pytest test/test_dedupe.py -q
```

预期:7 passed(Redis 容器在跑的话)。

- [ ] **Step 6: 提交**

```bash
git add app/ingress/ app/core/config.py test/test_dedupe.py
git commit -m "feat: redis-backed inbound dedupe behind a protocol"
```

---

### Task 6: 入站队列抽象与 webhook 路由

这是"100ms 内 ACK"这条要求真正落地的地方。

**Files:**
- Create: `app/ingress/queue.py`, `app/api/webhooks.py`
- Modify: `app/main.py`
- Test: `test/test_webhooks.py`

**Interfaces:**
- Consumes: Task 3 的 `build_adapter`/`UnknownProvider`;Task 4 的 `InboundEvent`;Task 5 的 `DedupeStore`/`dedupe_key`
- Produces:
  - `InboundQueue` Protocol:`async def enqueue(self, event_id: int) -> None`
  - `InMemoryInboundQueue()` —— 属性 `enqueued: list[int]`
  - webhook 路由,以及 `get_dedupe_store`/`get_inbound_queue` 两个可被测试覆盖的 FastAPI 依赖

`get_inbound_queue` 会 import `app.worker.queue.CeleryInboundQueue`,那个模块要到 Task 7 才存在。这是**故意**的顺序:import 写在函数体内,而本 task 的每个测试都覆盖了这个依赖,所以那行永远不会执行。如果它执行了并报 `ModuleNotFoundError`,说明有测试忘了覆盖依赖 —— 那正是应该立刻知道的事,而不是让一个真的 Celery 客户端在测试里被构造出来。

- [ ] **Step 1: 写 `app/ingress/queue.py`**

```python
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
```

- [ ] **Step 2: 写会失败的测试 —— `test/test_webhooks.py`**

```python
import time

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.channels.telegram.adapter import SECRET_HEADER
from app.core.database import get_db
from app.ingress.dedupe import InMemoryDedupeStore
from app.ingress.queue import InMemoryInboundQueue
from app.main import app
from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection
from app.models.inbound_event import InboundEvent
from app.models.merchant import Merchant
from app.models.shop import Shop

pytestmark = pytest.mark.integration

SECRET = "s3cr3t"


async def _connection(db_session) -> ChannelConnection:
    merchant = Merchant(name="Kedai Ahmad")
    db_session.add(merchant)
    await db_session.flush()
    shop = Shop(merchant_id=merchant.id, name="Ahmad Store", platform="standalone")
    db_session.add(shop)
    await db_session.flush()
    bot = Bot(shop_id=shop.id, name="Ahmad Bot")
    db_session.add(bot)
    await db_session.flush()
    conn = ChannelConnection(bot_id=bot.id, provider="telegram", external_ref="@ahmad_bot")
    conn.set_credentials({"bot_token": "123:ABC", "secret_token": SECRET})
    db_session.add(conn)
    await db_session.flush()
    return conn


@pytest.fixture
def wired(db_session):
    """The app with its database, dedupe store and queue swapped for the
    test's own, so the route under test is the real one."""
    from app.api.webhooks import get_dedupe_store, get_inbound_queue

    store, queue = InMemoryDedupeStore(), InMemoryInboundQueue()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_dedupe_store] = lambda: store
    app.dependency_overrides[get_inbound_queue] = lambda: queue
    yield store, queue
    app.dependency_overrides.clear()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _update(update_id: int = 900) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 42,
            "date": 1_757_000_000,
            "chat": {"id": 7, "type": "private"},
            "from": {"id": 8},
            "text": "where is my parcel",
        },
    }


async def test_an_authentic_delivery_is_stored_and_enqueued(db_session, wired):
    _store, queue = wired
    conn = await _connection(db_session)

    async with _client() as client:
        response = await client.post(
            f"/webhooks/telegram/{conn.id}",
            json=_update(),
            headers={SECRET_HEADER: SECRET},
        )

    assert response.status_code == 200
    stored = (await db_session.execute(select(InboundEvent))).scalars().all()
    assert len(stored) == 1
    assert stored[0].provider_update_id == "900"
    assert stored[0].payload["message"]["text"] == "where is my parcel"
    assert queue.enqueued == [stored[0].id]


async def test_a_bad_secret_is_refused_and_stores_nothing(db_session, wired):
    _store, queue = wired
    conn = await _connection(db_session)

    async with _client() as client:
        response = await client.post(
            f"/webhooks/telegram/{conn.id}",
            json=_update(),
            headers={SECRET_HEADER: "wrong"},
        )

    assert response.status_code == 403
    assert (await db_session.execute(select(InboundEvent))).scalars().all() == []
    assert queue.enqueued == []


async def test_a_replayed_delivery_is_acknowledged_but_not_re_enqueued(
    db_session, wired
):
    """The provider must see 200 or it retries forever. It must also not get a
    second reply to the customer."""
    _store, queue = wired
    conn = await _connection(db_session)

    async with _client() as client:
        for _ in range(2):
            response = await client.post(
                f"/webhooks/telegram/{conn.id}",
                json=_update(),
                headers={SECRET_HEADER: SECRET},
            )
            assert response.status_code == 200

    assert len(queue.enqueued) == 1
    stored = (await db_session.execute(select(InboundEvent))).scalars().all()
    assert len(stored) == 1


async def test_a_duplicate_that_slips_past_redis_is_caught_by_the_constraint(
    db_session, wired
):
    """Redis can be flushed. The unique index is what makes this impossible
    rather than merely unlikely, and hitting it must still ACK 200."""
    _store, queue = wired
    conn = await _connection(db_session)
    db_session.add(
        InboundEvent(
            connection_id=conn.id,
            provider="telegram",
            provider_update_id="900",
            payload={},
        )
    )
    await db_session.flush()

    async with _client() as client:
        response = await client.post(
            f"/webhooks/telegram/{conn.id}",
            json=_update(),
            headers={SECRET_HEADER: SECRET},
        )

    assert response.status_code == 200
    assert queue.enqueued == []


async def test_a_non_actionable_update_is_acknowledged_and_stored(db_session, wired):
    """A poll answer yields no envelope. It is still a delivery that happened,
    and the provider still needs its 200."""
    _store, queue = wired
    conn = await _connection(db_session)
    payload = {"update_id": 904, "poll_answer": {"poll_id": "p", "option_ids": [1]}}

    async with _client() as client:
        response = await client.post(
            f"/webhooks/telegram/{conn.id}", json=payload, headers={SECRET_HEADER: SECRET}
        )

    assert response.status_code == 200
    assert queue.enqueued == []


async def test_an_unknown_connection_is_404(db_session, wired):
    async with _client() as client:
        response = await client.post(
            "/webhooks/telegram/999999", json=_update(), headers={SECRET_HEADER: SECRET}
        )

    assert response.status_code == 404


async def test_a_provider_that_does_not_match_the_connection_is_404(db_session, wired):
    """The provider in the path is not decoration. A mismatch means a
    misconfigured webhook, and guessing which one is right is worse than 404."""
    conn = await _connection(db_session)

    async with _client() as client:
        response = await client.post(
            f"/webhooks/fake/{conn.id}", json=_update(), headers={SECRET_HEADER: SECRET}
        )

    assert response.status_code == 404


async def test_malformed_json_is_refused_without_a_500(db_session, wired):
    conn = await _connection(db_session)

    async with _client() as client:
        response = await client.post(
            f"/webhooks/telegram/{conn.id}",
            content=b"<html>",
            headers={SECRET_HEADER: SECRET, "content-type": "application/json"},
        )

    assert response.status_code == 400


async def test_the_ack_is_fast(db_session, wired):
    """Not a benchmark -- a guard. If someone later puts an LLM call or an
    outbound send in this path, this test is what notices."""
    conn = await _connection(db_session)

    async with _client() as client:
        started = time.perf_counter()
        await client.post(
            f"/webhooks/telegram/{conn.id}", json=_update(), headers={SECRET_HEADER: SECRET}
        )
        elapsed = time.perf_counter() - started

    assert elapsed < 0.5
```

- [ ] **Step 3: 跑测试确认它失败**

```bash
.venv/bin/python -m pytest test/test_webhooks.py -q
```

预期:`ModuleNotFoundError: No module named 'app.api.webhooks'`。

- [ ] **Step 4: 写 `app/api/webhooks.py`**

```python
"""Channel ingress.

The order of operations here is a correctness requirement, not a style: verify
the signature against the raw bytes, dedupe, persist raw, ACK 200, and only
then enqueue. Nothing slow is allowed in this function -- no LLM call, no
outbound HTTP, no waiting on a task result. A slow ACK makes the provider
retry, and a retry is a second reply to the customer.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.registry import UnknownProvider, build_adapter
from app.core.config import settings
from app.core.database import get_db
from app.ingress.dedupe import DedupeStore, RedisDedupeStore, dedupe_key
from app.ingress.queue import InboundQueue
from app.models.channel_connection import ChannelConnection
from app.models.inbound_event import InboundEvent

router = APIRouter(tags=["webhooks"])

_redis_client: Redis | None = None


def get_dedupe_store() -> DedupeStore:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(settings.REDIS_URL)
    return RedisDedupeStore(_redis_client, ttl_seconds=settings.DEDUPE_TTL_SECONDS)


def get_inbound_queue() -> InboundQueue:
    from app.worker.queue import CeleryInboundQueue

    return CeleryInboundQueue()


@router.post("/webhooks/{provider}/{connection_id}")
async def receive_webhook(
    provider: str,
    connection_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    dedupe: DedupeStore = Depends(get_dedupe_store),
    queue: InboundQueue = Depends(get_inbound_queue),
) -> Response:
    connection = (
        await db.execute(
            select(ChannelConnection).where(
                ChannelConnection.id == connection_id,
                # The provider in the path must agree with the row. A mismatch
                # is a misconfigured webhook, and guessing is worse than 404.
                ChannelConnection.provider == provider,
                ChannelConnection.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if connection is None:
        raise HTTPException(status_code=404, detail="unknown connection")

    try:
        adapter = build_adapter(connection)
    except UnknownProvider:
        raise HTTPException(status_code=404, detail="unknown connection") from None

    # Raw bytes, not the parsed body: a signature covers the exact bytes sent,
    # and re-serialising a parsed dict will not reproduce them.
    raw_body = await request.body()
    if not adapter.verify_webhook(request.headers, raw_body):
        raise HTTPException(status_code=403, detail="bad signature")

    try:
        payload = json.loads(raw_body)
    except ValueError:
        raise HTTPException(status_code=400, detail="malformed payload") from None

    envelopes = adapter.parse_inbound(payload)
    if not envelopes:
        # A delivery receipt or a poll answer. Nothing to run, but it did
        # arrive, and the provider still needs its 200.
        return Response(status_code=200)

    for envelope in envelopes:
        if not await dedupe.claim(
            dedupe_key(envelope.provider, envelope.provider_update_id)
        ):
            continue

        event = InboundEvent(
            connection_id=connection.id,
            provider=envelope.provider,
            provider_update_id=envelope.provider_update_id,
            payload=payload,
        )
        db.add(event)
        try:
            await db.flush()
        except IntegrityError:
            # Redis missed it -- flushed, or a race. The unique constraint is
            # the backstop, and losing that race is a duplicate, not an error.
            await db.rollback()
            continue

        await db.commit()
        await queue.enqueue(event.id)

    return Response(status_code=200)
```

**关于 `db.commit()`:** 测试的 `db_session` fixture 把整个测试包在一个外层事务里,`commit()` 只提交到 savepoint,测试结束仍然整体回滚。生产里这个 commit 是必须的 —— Celery worker 是另一个连接,它必须能看到这一行,否则任务拿到一个查不到的 id。

- [ ] **Step 5: 在 `app/main.py` 里注册路由**

```python
from fastapi import FastAPI

from app.api import health, webhooks
from app.core.config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="botly",
        version="0.1.0",
        # No interactive docs in production: the schema names every route
        # before there is any auth in front of them.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
    )
    app.include_router(health.router)
    app.include_router(webhooks.router)
    return app


app = create_app()
```

- [ ] **Step 6: 跑测试确认通过**

```bash
.venv/bin/python -m pytest test/test_webhooks.py -q
```

预期:9 passed。`get_inbound_queue` 里 import 的 `app.worker.queue` 在 Task 7 才存在 —— 但测试全都覆盖了这个依赖,所以那行 import 不会被执行。如果它被执行了,说明有测试漏了覆盖,那正是要知道的事。

- [ ] **Step 7: 跑整个套件并提交**

```bash
.venv/bin/python -m pytest -q
git add app/ingress/queue.py app/api/webhooks.py app/main.py test/test_webhooks.py
git commit -m "feat: webhook ingress with dedupe, raw persistence and fast ack"
```

---

### Task 7: Celery 应用与任务

**Files:**
- Create: `app/worker/__init__.py`, `app/worker/celery_app.py`, `app/worker/queue.py`, `app/worker/tasks.py`
- Modify: `app/core/config.py`, `.env.example`, `README.md`
- Test: `test/test_worker_tasks.py`

**Interfaces:**
- Consumes: Task 6 的 `InboundQueue` Protocol
- Produces:
  - `celery_app`
  - `CeleryInboundQueue()`
  - Celery 任务 `botly.process_inbound_event`,签名 `process_inbound_event(event_id: int)`

- [ ] **Step 1: 在 config 里加 Celery 设置**

在 `Settings` 里 `DEDUPE_TTL_SECONDS` 下面加:

```python
    # A separate Redis database from the dedupe keys: flushing a stuck queue
    # must not also erase the dedupe keyspace and replay every recent webhook.
    CELERY_BROKER_URL: str = "redis://localhost:6380/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6380/2"
```

- [ ] **Step 2: 写会失败的测试 —— `test/test_worker_tasks.py`**

```python
from app.worker.celery_app import celery_app
from app.worker.queue import CeleryInboundQueue
from app.worker.tasks import INBOUND_TASK_NAME, process_inbound_event


def test_the_task_is_registered_under_a_stable_name():
    """The name travels in the queue payload. Renaming it strands every
    message already enqueued under the old name."""
    assert INBOUND_TASK_NAME == "botly.process_inbound_event"
    assert INBOUND_TASK_NAME in celery_app.tasks


def test_the_task_name_carries_no_provider():
    """One task processes every channel. A per-provider task name would be
    provider branching wearing a hat."""
    for name in ("telegram", "whatsapp", "shopee"):
        assert name not in INBOUND_TASK_NAME


def test_late_acknowledgement_is_on():
    """acks_late: a worker killed mid-task must return the message to the
    queue, not lose the customer's message."""
    assert celery_app.conf.task_acks_late is True


def test_the_task_accepts_only_an_event_id():
    """The payload is a row id, never the message. A queue holding customer
    text is a second copy to secure, and it goes stale the moment the row
    changes."""
    import inspect

    parameters = list(inspect.signature(process_inbound_event).parameters)

    assert parameters == ["event_id"]


async def test_the_celery_queue_sends_the_id_to_the_named_task(monkeypatch):
    sent: list[tuple] = []
    monkeypatch.setattr(
        celery_app, "send_task", lambda name, args: sent.append((name, args))
    )

    await CeleryInboundQueue().enqueue(4321)

    assert sent == [(INBOUND_TASK_NAME, (4321,))]
```

- [ ] **Step 3: 跑测试确认它失败**

```bash
.venv/bin/python -m pytest test/test_worker_tasks.py -q
```

预期:`ModuleNotFoundError: No module named 'app.worker'`。

- [ ] **Step 4: 写 `app/worker/celery_app.py`**

```python
from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "botly",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # A worker killed mid-task returns the message to the queue instead of
    # losing it. Combined with the dedupe table, a redelivery is safe.
    task_acks_late=True,
    # One message at a time per worker process. The default of four means a
    # slow LLM call blocks three other customers behind it.
    worker_prefetch_multiplier=1,
)
```

- [ ] **Step 5: 写 `app/worker/tasks.py`**

```python
"""Celery tasks.

Each one is a thin shell. The logic lives in app/runtime/, which is plain async
code with no Celery import -- so it is testable without a broker, and the queue
stays a replaceable seam rather than a framework the business logic is welded
to.
"""

import asyncio

from app.worker.celery_app import celery_app

# The name travels inside every enqueued message. Renaming it strands whatever
# is already in the queue.
INBOUND_TASK_NAME = "botly.process_inbound_event"


@celery_app.task(name=INBOUND_TASK_NAME, bind=True, max_retries=3)
def process_inbound_event(self, event_id: int) -> None:
    """Run one stored inbound event through the runtime.

    The payload is a row id, never the message itself: a queue holding customer
    text is a second copy to secure, and it is stale the moment the row moves.
    """
    from app.runtime.pipeline import run_inbound_pipeline

    asyncio.run(run_inbound_pipeline(event_id))
```

- [ ] **Step 6: 写 `app/worker/queue.py`**

```python
from app.worker.celery_app import celery_app
from app.worker.tasks import INBOUND_TASK_NAME


class CeleryInboundQueue:
    """The production InboundQueue. send_task by name rather than importing
    the task function, so ingress does not drag the runtime into its process."""

    async def enqueue(self, event_id: int) -> None:
        celery_app.send_task(INBOUND_TASK_NAME, (event_id,))
```

`app/worker/__init__.py` 留空。

- [ ] **Step 7: 更新 `.env.example`**

```bash
cat > .env.example <<'ENVEOF'
ENVIRONMENT=development
SQL_ECHO=false
DATABASE_URL=postgresql+asyncpg://botly:botly@localhost:5433/botly
TEST_DATABASE_URL=postgresql+asyncpg://botly:botly@localhost:5433/botly_test
REDIS_URL=redis://localhost:6380/0
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
CREDENTIALS_ENCRYPTION_KEY=
DEDUPE_TTL_SECONDS=86400
# Separate Redis databases: flushing a stuck queue must not erase the dedupe
# keyspace and replay every recent webhook.
CELERY_BROKER_URL=redis://localhost:6380/1
CELERY_RESULT_BACKEND=redis://localhost:6380/2
ENVEOF
```

- [ ] **Step 8: 在 README 的本地启动步骤里补上 worker**

在 `poetry run uvicorn app.main:app --reload` 那一行后面加一行:

```
poetry run celery -A app.worker.celery_app.celery_app worker --loglevel=info
```

- [ ] **Step 9: 跑测试确认通过**

```bash
.venv/bin/python -m pytest test/test_worker_tasks.py -q
```

预期:5 passed。注意这些测试不需要 broker —— 它们检查的是注册和配置,不投递任何消息。

- [ ] **Step 10: 提交**

```bash
git add app/worker/ app/core/config.py .env.example README.md test/test_worker_tasks.py
git commit -m "feat: celery app and the inbound event task"
```

---

### Task 8: 大脑(stub)

**Files:**
- Create: `app/runtime/__init__.py`, `app/runtime/brain.py`
- Test: `test/test_brain.py`

**Interfaces:**
- Consumes: `app/channels/types.py` 的 `Attachment`、`InboundEnvelope`
- Produces:
  - `DraftReply(text: str | None = None, attachments: tuple[Attachment, ...] = (), escalate: bool = False, reason: str | None = None)`
  - `Brain` Protocol:`async def respond(self, envelope: InboundEnvelope) -> DraftReply`
  - `EchoBrain(prefix: str = "botly received: ")`

这是本计划里唯一一个刻意留白的地方,所以把边界说清楚:**Protocol 是最终形态,实现不是。** LangGraph 的大脑、RAG 检索、商务工具各有各的计划。`EchoBrain` 存在的意义是让第 3 步能证明管线通了,而不是让它看起来像个能用的机器人。

- [ ] **Step 1: 写会失败的测试 —— `test/test_brain.py`**

```python
from datetime import datetime, timezone

import pytest

from app.channels.types import InboundEnvelope
from app.runtime.brain import Brain, DraftReply, EchoBrain


def envelope(text: str = "where is my parcel") -> InboundEnvelope:
    return InboundEnvelope(
        provider="fake",
        external_thread_id="7",
        provider_update_id="1",
        sender_ref="8",
        text=text,
        sent_at=datetime.now(timezone.utc),
    )


def test_a_draft_must_say_something_or_escalate():
    """A reply that is neither text nor an escalation is a customer left on
    read."""
    with pytest.raises(ValueError):
        DraftReply()


def test_an_escalation_needs_no_text():
    draft = DraftReply(escalate=True, reason="tool failure")

    assert draft.escalate is True
    assert draft.text is None


def test_an_escalation_must_carry_a_reason():
    """The reason is what the agent reads when the conversation lands in the
    inbox. An unexplained handoff wastes their first minute."""
    with pytest.raises(ValueError):
        DraftReply(escalate=True)


def test_the_echo_brain_satisfies_the_protocol():
    assert isinstance(EchoBrain(), Brain)


async def test_the_echo_brain_repeats_the_message():
    draft = await EchoBrain().respond(envelope())

    assert draft.text == "botly received: where is my parcel"
    assert draft.escalate is False


async def test_the_echo_brain_escalates_a_message_it_cannot_read():
    """A photo with no caption is exactly the case the real brain will hand to
    vision. Until that exists, guessing is the one thing forbidden -- facts
    come from tools, never from the model."""
    from app.channels.types import Attachment

    media_only = InboundEnvelope(
        provider="fake",
        external_thread_id="7",
        provider_update_id="2",
        sender_ref="8",
        attachments=(Attachment(kind="image", url="tg-file://x"),),
        sent_at=datetime.now(timezone.utc),
    )

    draft = await EchoBrain().respond(media_only)

    assert draft.escalate is True
    assert draft.reason
```

- [ ] **Step 2: 跑测试确认它失败**

```bash
.venv/bin/python -m pytest test/test_brain.py -q
```

预期:`ModuleNotFoundError: No module named 'app.runtime'`。

- [ ] **Step 3: 写 `app/runtime/brain.py`**

```python
"""The bot's brain, behind a Protocol.

The implementation here is a stub and is meant to be replaced. The Protocol is
not: the pipeline, the dispatcher and every test around them are written
against DraftReply, so swapping EchoBrain for the LangGraph brain is one class,
not a refactor.

The rule the real brain will have to keep, recorded here where its author will
read it: facts come from tools, never from the model. When a tool fails the bot
says it cannot check and escalates. A hallucinated order status is a refund
dispute.
"""

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, model_validator

from app.channels.types import Attachment, InboundEnvelope


class DraftReply(BaseModel):
    """What the brain produced, before the channel has had its say.

    Deliberately not an OutboundMessage: the brain does not know whether the
    channel needs a template, how long its messages may be, or whether it takes
    media. That is the dispatcher's job, and keeping them separate is what
    stops channel rules leaking into the runtime.
    """

    model_config = ConfigDict(frozen=True)

    text: str | None = None
    attachments: tuple[Attachment, ...] = ()
    escalate: bool = False
    reason: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "DraftReply":
        if not self.escalate and self.text is None and not self.attachments:
            raise ValueError(
                "a draft reply must carry text, an attachment, or escalate; "
                "otherwise the customer is left on read"
            )
        if self.escalate and not self.reason:
            raise ValueError(
                "an escalation must carry a reason -- it is what the agent "
                "reads when the conversation lands in the inbox"
            )
        return self


@runtime_checkable
class Brain(Protocol):
    async def respond(self, envelope: InboundEnvelope) -> DraftReply: ...


class EchoBrain:
    """Repeats what it was told. Proves the pipeline, answers nothing.

    Build-order step 3 exists to prove ingress -> queue -> runtime -> dispatch
    works end to end. A real brain here would make that proof depend on an LLM
    provider, a knowledge base and a Shopee approval that has not arrived.
    """

    def __init__(self, prefix: str = "botly received: ") -> None:
        self._prefix = prefix

    async def respond(self, envelope: InboundEnvelope) -> DraftReply:
        if envelope.text is None:
            # Vision and OCR are a later plan. Until then, a message this brain
            # cannot read goes to a human rather than getting a guess.
            return DraftReply(
                escalate=True,
                reason="the message carries only media and cannot be read yet",
            )
        return DraftReply(text=f"{self._prefix}{envelope.text}")
```

`app/runtime/__init__.py` 留空。

- [ ] **Step 4: 跑测试确认通过**

```bash
.venv/bin/python -m pytest test/test_brain.py -q
```

预期:6 passed。

- [ ] **Step 5: 提交**

```bash
git add app/runtime/ test/test_brain.py
git commit -m "feat: brain protocol with a stub echo implementation"
```

---

### Task 9: 出站派发器

本计划的核心 task。规格第 4 节说得很直白:*"the dispatcher asks a question instead of branching on a provider name."* 这个 task 就是把那句话变成代码和测试。

**Files:**
- Create: `app/dispatch/__init__.py`, `app/dispatch/ratelimit.py`, `app/dispatch/dispatcher.py`
- Modify: `app/core/config.py`
- Test: `test/test_dispatcher.py`

**Interfaces:**
- Consumes: `ChannelAdapter`、`ChannelCapabilities`、`OutboundMessage`、`SendResult`;Task 8 的 `DraftReply`;`FailedJob`
- Produces:
  - `RateLimiter` Protocol:`async def acquire(self, key: str) -> bool`;`InMemoryTokenBucket(capacity, refill_per_second)`;`RedisTokenBucket(client, capacity, refill_per_second)`
  - `chunk_text(text: str, limit: int) -> list[str]`
  - `DispatchOutcome(sent, escalated, reason, permanent_failure)`
  - `OutboundDispatcher(adapter, limiter=None, sleep=asyncio.sleep, max_attempts=3)`,方法 `async def dispatch(self, conn, draft, last_inbound_at=None) -> DispatchOutcome`

**窗口检查为什么要传 `last_inbound_at` 而不是自己去查:** `Conversation` 模型属于第 4 步。派发器需要知道会话窗口有没有关,而那个时间戳将来住在 `Conversation.last_inbound_at`。把它做成参数,派发器现在就能完整实现并测试窗口规则,不必等一张还不存在的表;第 4 步接上真实会话时,改的是调用方,不是派发器。

- [ ] **Step 1: 在 config 里加限流设置**

```python
    # Per connection. Telegram's own guidance is roughly 30 messages/second
    # overall and about 1/second into a single chat; the conservative number
    # here is a floor that every channel can live with.
    OUTBOUND_RATE_CAPACITY: int = 20
    OUTBOUND_RATE_REFILL_PER_SECOND: float = 1.0
    OUTBOUND_MAX_ATTEMPTS: int = 3
```

- [ ] **Step 2: 写 `app/dispatch/ratelimit.py`**

```python
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
    def __init__(self, client, capacity: int = 20, refill_per_second: float = 1.0) -> None:
        self._client = client
        self._capacity = capacity
        self._refill = refill_per_second

    async def acquire(self, key: str) -> bool:
        allowed = await self._client.eval(
            _LUA_TOKEN_BUCKET, 1, key, self._capacity, self._refill, time.time()
        )
        return bool(allowed)
```

- [ ] **Step 3: 写会失败的测试 —— `test/test_dispatcher.py`**

```python
from datetime import datetime, timedelta, timezone

import pytest

from app.channels.fake.adapter import FakeAdapter
from app.channels.types import Attachment, ChannelCapabilities
from app.dispatch.dispatcher import OutboundDispatcher, chunk_text
from app.dispatch.ratelimit import InMemoryTokenBucket
from app.models.channel_connection import ChannelConnection
from app.runtime.brain import DraftReply


def connection() -> ChannelConnection:
    return ChannelConnection(id=1, bot_id=1, provider="fake", external_ref="x")


def adapter_with(**overrides) -> FakeAdapter:
    """A FakeAdapter wearing a different capability manifest.

    This is how a channel the dispatcher has never seen gets tested: change the
    manifest, not the dispatcher. If a test here ever needs a new provider
    name, the dispatcher has a bug.
    """
    base = FakeAdapter.capabilities.model_dump()
    base.update(overrides)

    class _Adapter(FakeAdapter):
        capabilities = ChannelCapabilities(**base)

    return _Adapter()


def dispatcher(adapter, **kwargs) -> OutboundDispatcher:
    kwargs.setdefault("limiter", InMemoryTokenBucket(capacity=100))
    return OutboundDispatcher(adapter, **kwargs)


# --- chunking ---------------------------------------------------------------


def test_short_text_is_one_chunk():
    assert chunk_text("hello", 100) == ["hello"]


def test_long_text_is_split_to_the_limit():
    chunks = chunk_text("a" * 250, 100)

    assert [len(c) for c in chunks] == [100, 100, 50]


def test_splitting_prefers_a_line_break():
    """Cutting mid-word makes the bot look broken. Cutting at a newline does
    not."""
    text = "first line\n" + "b" * 50

    chunks = chunk_text(text, 20)

    assert chunks[0] == "first line"


def test_splitting_falls_back_to_a_space_then_to_a_hard_cut():
    assert chunk_text("word " + "c" * 30, 10)[0] == "word"
    assert chunk_text("d" * 30, 10)[0] == "d" * 10


def test_chunking_never_returns_an_empty_piece():
    """An empty chunk becomes an OutboundMessage with nothing in it, which the
    envelope refuses to construct -- a crash at send time."""
    for chunk in chunk_text("a\n\n\nb", 4):
        assert chunk.strip()


# --- the capability rules ---------------------------------------------------


async def test_a_reply_is_sent_through_the_adapter():
    adapter = adapter_with()
    outcome = await dispatcher(adapter).dispatch(
        connection(), DraftReply(text="your parcel is out for delivery")
    )

    assert outcome.escalated is False
    assert len(adapter.sent) == 1
    assert adapter.sent[0][1].text == "your parcel is out for delivery"


async def test_a_long_reply_is_split_to_the_manifest_limit():
    adapter = adapter_with(max_text_len=10)

    await dispatcher(adapter).dispatch(connection(), DraftReply(text="x" * 25))

    assert len(adapter.sent) == 3
    assert all(len(sent.text) <= 10 for _, sent in adapter.sent)


async def test_a_closed_window_with_a_template_rule_escalates_without_a_template():
    """This is the WhatsApp case, expressed entirely as a manifest. The
    dispatcher has never heard of WhatsApp."""
    adapter = adapter_with(
        session_window=timedelta(hours=24), requires_template_outside_window=True
    )
    stale = datetime.now(timezone.utc) - timedelta(hours=25)

    outcome = await dispatcher(adapter).dispatch(
        connection(), DraftReply(text="hello"), last_inbound_at=stale
    )

    assert outcome.escalated is True
    assert "window" in outcome.reason
    assert adapter.sent == []


async def test_an_open_window_sends_free_text_normally():
    adapter = adapter_with(
        session_window=timedelta(hours=24), requires_template_outside_window=True
    )
    fresh = datetime.now(timezone.utc) - timedelta(minutes=5)

    outcome = await dispatcher(adapter).dispatch(
        connection(), DraftReply(text="hello"), last_inbound_at=fresh
    )

    assert outcome.escalated is False
    assert len(adapter.sent) == 1


async def test_no_inbound_at_all_counts_as_a_closed_window():
    """A conversation the bot starts has no window. Treating unknown as open
    is how a send fails at the provider instead of at the guard."""
    adapter = adapter_with(
        session_window=timedelta(hours=24), requires_template_outside_window=True
    )

    outcome = await dispatcher(adapter).dispatch(
        connection(), DraftReply(text="hello"), last_inbound_at=None
    )

    assert outcome.escalated is True


async def test_a_channel_with_no_window_ignores_the_timestamp_entirely():
    adapter = adapter_with(session_window=None)
    ancient = datetime.now(timezone.utc) - timedelta(days=400)

    outcome = await dispatcher(adapter).dispatch(
        connection(), DraftReply(text="hello"), last_inbound_at=ancient
    )

    assert outcome.escalated is False


async def test_attachments_on_a_text_only_channel_escalate():
    """Silently dropping something the customer was meant to see is worse than
    handing the conversation to a human."""
    adapter = adapter_with(supports_media=False)

    outcome = await dispatcher(adapter).dispatch(
        connection(),
        DraftReply(text="here", attachments=(Attachment(kind="image", url="u"),)),
    )

    assert outcome.escalated is True
    assert "media" in outcome.reason
    assert adapter.sent == []


async def test_an_escalating_draft_sends_nothing():
    adapter = adapter_with()

    outcome = await dispatcher(adapter).dispatch(
        connection(), DraftReply(escalate=True, reason="tool failure")
    )

    assert outcome.escalated is True
    assert outcome.reason == "tool failure"
    assert adapter.sent == []


# --- rate limiting, retry, failure ------------------------------------------


async def test_an_exhausted_bucket_stops_the_send():
    adapter = adapter_with()
    limiter = InMemoryTokenBucket(capacity=0, refill_per_second=0)

    outcome = await dispatcher(adapter, limiter=limiter).dispatch(
        connection(), DraftReply(text="hello")
    )

    assert adapter.sent == []
    assert outcome.permanent_failure is not None


async def test_a_retryable_failure_is_retried_and_can_succeed():
    adapter = adapter_with()
    adapter.fail_next_send = "429 slow down"
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    outcome = await dispatcher(adapter, sleep=fake_sleep).dispatch(
        connection(), DraftReply(text="hello")
    )

    assert outcome.permanent_failure is None
    assert len(adapter.sent) == 1
    assert slept, "a retry must back off rather than hammer the provider"


async def test_backoff_grows_between_attempts():
    class _AlwaysFails(FakeAdapter):
        async def send(self, conn, out):
            from app.channels.types import SendResult

            return SendResult(ok=False, error="429", retryable=True)

    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    await dispatcher(_AlwaysFails(), sleep=fake_sleep, max_attempts=3).dispatch(
        connection(), DraftReply(text="hello")
    )

    assert slept == sorted(slept) and slept[0] < slept[-1]


async def test_a_permanent_failure_is_not_retried():
    class _Rejects(FakeAdapter):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        async def send(self, conn, out):
            from app.channels.types import SendResult

            self.attempts += 1
            return SendResult(ok=False, error="bot was blocked", retryable=False)

    adapter = _Rejects()
    outcome = await dispatcher(adapter, max_attempts=3).dispatch(
        connection(), DraftReply(text="hello")
    )

    assert adapter.attempts == 1
    assert outcome.permanent_failure == "bot was blocked"


async def test_giving_up_after_max_attempts_reports_a_permanent_failure():
    class _AlwaysFails(FakeAdapter):
        async def send(self, conn, out):
            from app.channels.types import SendResult

            return SendResult(ok=False, error="503", retryable=True)

    async def fake_sleep(seconds: float) -> None:
        return None

    outcome = await dispatcher(
        _AlwaysFails(), sleep=fake_sleep, max_attempts=2
    ).dispatch(connection(), DraftReply(text="hello"))

    assert outcome.permanent_failure == "503"


async def test_a_failed_chunk_stops_the_rest():
    """Sending chunks 1 and 3 of a three-part answer is worse than sending one
    and escalating."""

    class _FailsSecond(FakeAdapter):
        capabilities = ChannelCapabilities(supports_media=True, max_text_len=5)

        async def send(self, conn, out):
            from app.channels.types import SendResult

            # FakeAdapter.sent only grows on success, so length 1 means the
            # first chunk went out and this is the second.
            if len(self.sent) == 1:
                return SendResult(ok=False, error="blocked", retryable=False)
            return await super().send(conn, out)

    adapter = _FailsSecond()
    outcome = await dispatcher(adapter).dispatch(
        connection(), DraftReply(text="a" * 15)
    )

    assert len(adapter.sent) == 1
    assert outcome.permanent_failure == "blocked"
```

- [ ] **Step 4: 跑测试确认它失败**

```bash
.venv/bin/python -m pytest test/test_dispatcher.py -q
```

预期:`ModuleNotFoundError: No module named 'app.dispatch'`。

- [ ] **Step 5: 写 `app/dispatch/dispatcher.py`**

```python
"""Outbound dispatch.

Everything a channel will and will not accept is read from its capability
manifest. There is no provider name in this file and there must never be one:
the moment a rule here says "if telegram", the same rule has to be repeated for
WhatsApp, and then for Shopee, and the channel layer stops containing anything.

Order of operations, from the spec: escalation short-circuits; the session
window and template rule are checked before anything is sent; text is chunked
to the manifest limit; each chunk takes a rate-limit token; retryable failures
back off; a permanent failure stops the rest and is reported so it reaches the
inbox as "delivery failed".
"""

import asyncio
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict

from app.channels.base import ChannelAdapter
from app.channels.types import OutboundMessage, SendResult
from app.dispatch.ratelimit import InMemoryTokenBucket, RateLimiter, bucket_key
from app.models.channel_connection import ChannelConnection
from app.runtime.brain import DraftReply


def chunk_text(text: str, limit: int) -> list[str]:
    """Split to the channel's limit, preferring a break a reader would choose.

    A newline first, then a space, then a hard cut. Cutting mid-word makes the
    bot look broken; cutting at a line break is invisible.
    """
    chunks: list[str] = []
    remaining = text.strip()
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        window = remaining[:limit]
        cut = window.rfind("\n")
        if cut <= 0:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit
        piece = remaining[:cut].strip()
        if piece:
            chunks.append(piece)
        remaining = remaining[cut:].strip()
    return chunks


class DispatchOutcome(BaseModel):
    """What happened, in a form the inbox can render."""

    model_config = ConfigDict(frozen=True)

    sent: tuple[SendResult, ...] = ()
    escalated: bool = False
    reason: str | None = None
    # Set when delivery is over and it did not succeed. The caller writes a
    # FailedJob and the inbox shows "delivery failed".
    permanent_failure: str | None = None


class OutboundDispatcher:
    def __init__(
        self,
        adapter: ChannelAdapter,
        limiter: RateLimiter | None = None,
        sleep=asyncio.sleep,
        max_attempts: int = 3,
    ) -> None:
        self._adapter = adapter
        self._limiter = limiter or InMemoryTokenBucket()
        # Injected so retry tests do not spend real seconds sleeping.
        self._sleep = sleep
        self._max_attempts = max_attempts

    async def dispatch(
        self,
        conn: ChannelConnection,
        draft: DraftReply,
        last_inbound_at: datetime | None = None,
    ) -> DispatchOutcome:
        caps = type(self._adapter).capabilities

        if draft.escalate:
            return DispatchOutcome(escalated=True, reason=draft.reason)

        if draft.attachments and not caps.supports_media:
            # Dropping it silently means the customer never sees something we
            # meant them to see. A human should decide what to do instead.
            return DispatchOutcome(
                escalated=True,
                reason="the channel carries no media and the reply has attachments",
            )

        if self._window_is_closed(caps, last_inbound_at):
            if caps.requires_template_outside_window:
                # No approved template selection exists yet -- message_template
                # is a later plan -- so the only correct move is a human.
                return DispatchOutcome(
                    escalated=True,
                    reason=(
                        "the session window has closed and this channel requires "
                        "an approved template outside it"
                    ),
                )

        pieces = chunk_text(draft.text or "", caps.max_text_len)
        results: list[SendResult] = []
        for piece in pieces:
            result = await self._send_with_retry(conn, OutboundMessage(text=piece))
            results.append(result)
            if not result.ok:
                # Chunks 1 and 3 of a three-part answer is worse than chunk 1
                # plus a human.
                return DispatchOutcome(
                    sent=tuple(results), permanent_failure=result.error
                )

        return DispatchOutcome(sent=tuple(results))

    @staticmethod
    def _window_is_closed(caps, last_inbound_at: datetime | None) -> bool:
        if caps.session_window is None:
            return False
        if last_inbound_at is None:
            # Unknown is closed, not open. Treating it as open turns a guard
            # failure into a provider rejection.
            return True
        return datetime.now(timezone.utc) - last_inbound_at > caps.session_window

    async def _send_with_retry(
        self, conn: ChannelConnection, out: OutboundMessage
    ) -> SendResult:
        last: SendResult | None = None
        for attempt in range(self._max_attempts):
            if not await self._limiter.acquire(bucket_key(conn.id)):
                return SendResult(
                    ok=False, error="outbound rate limit exhausted", retryable=True
                )

            last = await self._adapter.send(conn, out)
            if last.ok or not last.retryable:
                return last

            if attempt < self._max_attempts - 1:
                # Exponential: 0.5s, 1s, 2s. A provider that just rate-limited
                # us is not helped by an immediate second attempt.
                await self._sleep(0.5 * (2**attempt))

        return last
```

`app/dispatch/__init__.py` 留空。

- [ ] **Step 6: 跑测试确认通过**

```bash
.venv/bin/python -m pytest test/test_dispatcher.py -q
```

预期:19 passed。

- [ ] **Step 7: 证明"不许按 provider 分支"这条守卫在新代码上仍然成立**

```bash
.venv/bin/python -m pytest test/test_architecture.py -q
```

预期:2 passed。`app/dispatch/`、`app/runtime/`、`app/ingress/`、`app/worker/`、`app/api/` 里一个 provider 名字都不该有。红了就说明有条规则写错了地方 —— 它属于某个适配器的 manifest。

- [ ] **Step 8: 提交**

```bash
git add app/dispatch/ app/core/config.py test/test_dispatcher.py
git commit -m "feat: capability-driven outbound dispatcher with retry and rate limiting"
```

---

### Task 10: 管线编排与端到端测试

把前九个 task 接起来,然后用一个测试证明整条链路是通的。

**Files:**
- Create: `app/runtime/pipeline.py`
- Test: `test/test_pipeline_end_to_end.py`

**Interfaces:**
- Consumes: 前面全部
- Produces: `async def run_inbound_pipeline(event_id: int, session_factory=None, brain: Brain | None = None, limiter: RateLimiter | None = None) -> None`

- [ ] **Step 1: 写 `app/runtime/pipeline.py`**

```python
"""Event to reply.

This is the function the Celery task calls, and it is plain async code with no
Celery import -- so it can be tested without a broker, and the queue stays a
seam rather than a framework the logic is welded to.

What is deliberately missing: the handoff check. The spec puts it first in the
runtime -- a conversation in `human` state must store the message and push it
to the inbox without invoking the LLM -- but Conversation is build-order step
4. When that model lands, the check goes in immediately after the event is
loaded and before the brain is called.
"""

from datetime import datetime, timezone

from sqlalchemy import select

from app.channels.registry import UnknownProvider, build_adapter
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.dispatch.dispatcher import OutboundDispatcher
from app.dispatch.ratelimit import InMemoryTokenBucket
from app.models.channel_connection import ChannelConnection
from app.models.failed_job import FailedJob
from app.models.inbound_event import InboundEvent, InboundEventStatus
from app.runtime.brain import Brain, EchoBrain


async def run_inbound_pipeline(
    event_id: int,
    session_factory=None,
    brain: Brain | None = None,
    limiter=None,
) -> None:
    session_factory = session_factory or AsyncSessionLocal
    brain = brain or EchoBrain()

    async with session_factory() as db:
        event = await db.get(InboundEvent, event_id)
        if event is None or event.status is not InboundEventStatus.PENDING:
            # Already handled, or the row is gone. acks_late means a worker
            # that died mid-task gets the message again; that redelivery must
            # be a no-op, not a second reply.
            return

        connection = (
            await db.execute(
                select(ChannelConnection).where(
                    ChannelConnection.id == event.connection_id
                )
            )
        ).scalar_one_or_none()
        if connection is None:
            await _fail(db, event, None, "the channel connection no longer exists")
            return

        try:
            adapter = build_adapter(connection)
        except (UnknownProvider, ValueError) as exc:
            await _fail(db, event, connection.id, str(exc))
            return

        envelopes = adapter.parse_inbound(event.payload)
        if not envelopes:
            event.status = InboundEventStatus.PROCESSED
            event.processed_at = datetime.now(timezone.utc)
            await db.commit()
            return

        dispatcher = OutboundDispatcher(
            adapter,
            limiter=limiter
            or InMemoryTokenBucket(
                capacity=settings.OUTBOUND_RATE_CAPACITY,
                refill_per_second=settings.OUTBOUND_RATE_REFILL_PER_SECOND,
            ),
            max_attempts=settings.OUTBOUND_MAX_ATTEMPTS,
        )

        for envelope in envelopes:
            draft = await brain.respond(envelope)
            outcome = await dispatcher.dispatch(
                connection, draft, last_inbound_at=envelope.sent_at
            )
            # outcome.escalated is deliberately not acted on yet: setting
            # handoff_state and pushing to the inbox needs Conversation, which
            # is build-order step 4. Until then an escalation means the bot
            # stays silent, which is the safe half of the behaviour.
            if outcome.permanent_failure:
                await _fail(db, event, connection.id, outcome.permanent_failure)
                return

        event.status = InboundEventStatus.PROCESSED
        event.processed_at = datetime.now(timezone.utc)
        await db.commit()


async def _fail(db, event: InboundEvent, connection_id: int | None, error: str) -> None:
    """Mark the event failed and leave a row a human can find.

    A poison message must leave the queue rather than block it, and it must not
    leave without a trace -- the inbox shows a permanent send failure as
    "delivery failed".
    """
    event.status = InboundEventStatus.FAILED
    event.error = error
    event.processed_at = datetime.now(timezone.utc)
    db.add(
        FailedJob(
            kind="inbound",
            connection_id=connection_id,
            inbound_event_id=event.id,
            payload=event.payload,
            error=error,
            attempts=1,
        )
    )
    await db.commit()
```

**在 `settings` 里补上 pipeline 用到的那三个键** —— Task 9 的 Step 1 已经加过 `OUTBOUND_RATE_CAPACITY`、`OUTBOUND_RATE_REFILL_PER_SECOND`、`OUTBOUND_MAX_ATTEMPTS`。确认它们在,不在就补。

- [ ] **Step 2: 写端到端测试 —— `test/test_pipeline_end_to_end.py`**

```python
"""The proof that build-order step 3 is done.

A webhook goes in at the HTTP boundary and a reply comes out at the adapter,
through the real route, the real dedupe, the real registry, the real
dispatcher. No network, no broker: the queue is drained by hand, which is
exactly what Celery would do.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.channels.fake.adapter import SIGNATURE_HEADER, FakeAdapter
from app.core.database import get_db
from app.ingress.dedupe import InMemoryDedupeStore
from app.ingress.queue import InMemoryInboundQueue
from app.main import app
from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection
from app.models.failed_job import FailedJob
from app.models.inbound_event import InboundEvent, InboundEventStatus
from app.models.merchant import Merchant
from app.models.shop import Shop
from app.runtime.pipeline import run_inbound_pipeline

pytestmark = pytest.mark.integration


async def _connection(db_session) -> ChannelConnection:
    merchant = Merchant(name="Warung Budi")
    db_session.add(merchant)
    await db_session.flush()
    shop = Shop(merchant_id=merchant.id, name="Budi Store", platform="standalone")
    db_session.add(shop)
    await db_session.flush()
    bot = Bot(shop_id=shop.id, name="Budi Bot")
    db_session.add(bot)
    await db_session.flush()
    conn = ChannelConnection(bot_id=bot.id, provider="fake", external_ref="budi-1")
    conn.set_credentials({})
    db_session.add(conn)
    await db_session.flush()
    return conn


@pytest.fixture
def wired(db_session):
    from app.api.webhooks import get_dedupe_store, get_inbound_queue

    store, queue = InMemoryDedupeStore(), InMemoryInboundQueue()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_dedupe_store] = lambda: store
    app.dependency_overrides[get_inbound_queue] = lambda: queue
    # Yields the queue: every test here asserts on what got enqueued.
    yield queue
    app.dependency_overrides.clear()


def _session_factory(db_session):
    """Hand the pipeline the test's session. A real factory would open a second
    connection and deadlock against the transaction this test holds."""

    class _Factory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *exc):
            return False

    return _Factory()


@pytest.fixture
def drain(db_session, monkeypatch):
    """Run the queued event the way a Celery worker would, with a chosen
    adapter, and hand back everything that adapter was asked to send."""
    import app.runtime.pipeline as pipeline

    async def _drain(event_id: int, adapter_class=FakeAdapter) -> list:
        sent: list = []

        class _Recording(adapter_class):
            async def send(self, connection, out):
                result = await super().send(connection, out)
                if result.ok:
                    sent.append(out)
                return result

        monkeypatch.setattr(
            pipeline, "build_adapter", lambda c, webhook_url=None: _Recording()
        )
        await run_inbound_pipeline(
            event_id, session_factory=_session_factory(db_session)
        )
        return sent

    return _drain


async def _deliver(conn_id: int, body: bytes) -> int:
    """POST one signed delivery at the real route and return its status."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/webhooks/fake/{conn_id}",
            content=body,
            headers={
                SIGNATURE_HEADER: FakeAdapter().sign(body),
                "content-type": "application/json",
            },
        )
    return response.status_code


def _update(update_id: str, **fields) -> bytes:
    import json

    return json.dumps(
        {"updates": [{"update_id": update_id, "thread": "t1", "from": "c1",
                      "ts": 1_757_000_000, **fields}]}
    ).encode()


async def test_a_webhook_becomes_a_reply(db_session, wired, drain):
    conn = await _connection(db_session)

    assert await _deliver(conn.id, _update("u1", text="where is my parcel")) == 200
    assert len(wired.enqueued) == 1

    sent = await drain(wired.enqueued[0])

    assert [m.text for m in sent] == ["botly received: where is my parcel"]
    event = (await db_session.execute(select(InboundEvent))).scalars().one()
    assert event.status is InboundEventStatus.PROCESSED
    assert event.processed_at is not None


async def test_running_the_same_event_twice_replies_once(db_session, wired, drain):
    """acks_late returns a message to the queue when a worker dies. The second
    run must be a no-op, not a second reply to the customer."""
    conn = await _connection(db_session)
    await _deliver(conn.id, _update("u2", text="hello"))

    first = await drain(wired.enqueued[0])
    second = await drain(wired.enqueued[0])

    assert len(first) == 1
    assert second == []


async def test_a_replayed_webhook_never_reaches_the_queue_twice(db_session, wired):
    """The other half of the same guarantee, one layer up."""
    conn = await _connection(db_session)
    body = _update("u3", text="hello")

    assert await _deliver(conn.id, body) == 200
    assert await _deliver(conn.id, body) == 200

    assert len(wired.enqueued) == 1


async def test_a_permanent_send_failure_lands_in_failed_jobs(db_session, wired, drain):
    conn = await _connection(db_session)
    await _deliver(conn.id, _update("u4", text="hello"))

    class _Rejects(FakeAdapter):
        async def send(self, connection, out):
            from app.channels.types import SendResult

            return SendResult(ok=False, error="recipient blocked", retryable=False)

    sent = await drain(wired.enqueued[0], adapter_class=_Rejects)

    assert sent == []
    event = (await db_session.execute(select(InboundEvent))).scalars().one()
    job = (await db_session.execute(select(FailedJob))).scalars().one()
    assert event.status is InboundEventStatus.FAILED
    assert job.kind == "inbound"
    assert job.error == "recipient blocked"
    assert job.inbound_event_id == event.id


async def test_a_media_only_message_escalates_and_sends_nothing(db_session, wired, drain):
    """The stub brain cannot read a photo, so it hands over rather than
    guessing. Facts come from tools, never from the model."""
    conn = await _connection(db_session)
    await _deliver(
        conn.id,
        _update("u5", attachments=[{"kind": "image", "url": "https://x.test/a.jpg"}]),
    )

    sent = await drain(wired.enqueued[0])

    assert sent == []
    event = (await db_session.execute(select(InboundEvent))).scalars().one()
    assert event.status is InboundEventStatus.PROCESSED
```

- [ ] **Step 3: 跑端到端测试**

```bash
.venv/bin/python -m pytest test/test_pipeline_end_to_end.py -q
```

预期:5 passed。

- [ ] **Step 4: 跑整个套件**

```bash
.venv/bin/python -m pytest -q
```

预期:全绿。Task 2 之前是 70 项,这个计划大约再加 75 项。

- [ ] **Step 5: 手工验证一次真实的 Telegram 回环(可选但强烈建议)**

自动化测试证明不了 BotFather 的 token 格式对不对、`setWebhook` 会不会拒绝你的证书。跑一次:

```bash
# 1. 向 BotFather 要一个 token
# 2. 起本地服务和一条隧道
.venv/bin/python -m uvicorn app.main:app --reload
# 另一个终端:ngrok http 8000  (或任何 https 隧道)
# 3. 在库里建一条 merchant/shop/bot/channel_connection,凭据写
#    {"bot_token": "...", "secret_token": "任意随机串"}
# 4. 用隧道地址调 adapter.connect() 注册 webhook
# 5. 给 bot 发一条消息,应当收到 "botly received: <你发的话>"
```

这一步的价值不在代码,在于它会暴露 webhook URL 必须是 https、必须公网可达这类只有真跑一次才会发现的事。

- [ ] **Step 6: 提交**

```bash
git add app/runtime/pipeline.py test/test_pipeline_end_to_end.py
git commit -m "feat: inbound pipeline wiring ingress to brain to dispatch"
```

- [ ] **Step 7: 在规格里把第 3 步勾掉**

在 `docs/superpowers/specs/2026-09-02-botly-architecture-design.md` 第 12 节 Build Order 里,把第 3 条改成:

```
3. ~~**Telegram adapter** — no gatekeeper, so it proves the whole pipeline end to end~~ ✅ 2026-09-05
```

```bash
git add docs/superpowers/specs/2026-09-02-botly-architecture-design.md
git commit -m "docs: mark build-order step 3 as executed"
```

---

## Definition of Done

- `.venv/bin/python -m pytest` 在 Postgres 与 Redis 容器运行时全绿。
- `TelegramAdapter` 通过 `test/conformance.py` 里那套共享契约套件,并且**没有削弱它** —— body 认证那一条是被显式声明为不适用的,套件本身反而多长出一条对所有通道都成立的 `test_rejects_a_forged_credential`。`FakeAdapter` 仍然全绿。
- `test_no_module_outside_channels_names_a_provider` 仍然通过 —— `app/api/`、`app/runtime/`、`app/dispatch/`、`app/ingress/`、`app/worker/`、`app/core/` 里没有任何一个 provider 名字。
- `test_migrations_produce_the_same_schema_as_the_models` 通过:两张新表既在模型里也在迁移里。
- 一次 webhook 投递两遍,只产生一条 `inbound_event` 和一条回复。
- 派发器的窗口规则与模板规则**完全由 manifest 驱动**,并且是拿一个改了 manifest 的 `FakeAdapter` 测出来的 —— 也就是说,WhatsApp 的核心约束在 WhatsApp 适配器写出来之前就已经被测过了。
- 永久性发送失败会留下一条 `failed_job`,而不是静静消失。
- 整条链路的测试里没有一次网络调用,也不需要 Celery broker。

## Not in this plan

- **`Conversation` 与 `Message` 模型、handoff 状态机、卖家 inbox、WebSocket** —— 构建顺序第 4 步。`run_inbound_pipeline` 里那个"handoff 检查放这里"的注释标了位置。
- **真正的大脑:LangGraph、RAG、`kb_document`/`kb_chunk`、pgvector 索引、hybrid RRF 检索、recall@k 测量。** 这一块目前**在七步构建顺序里根本没有位置**,需要单独排一个计划,最自然的位置是第 4 步和第 5 步之间 —— 商务工具接进大脑之前,大脑得先存在。
- **Shopee 数据客户端与商务工具**(第 5 步)、**WhatsApp 适配器**(第 6 步):两者都被外部审批卡住,状态见 `docs/approvals.md`。
- **`message_template` 表与模板选择。** 派发器现在的做法是:窗口关闭且通道要求模板时,转人工。真正的模板选择要等 WhatsApp 的模板审批流程,和第 6 步一起做。
- **附件下载、vision 与 OCR。** `resolve_file_url()` 已经就位,还没有调用方。
- **凭据过期与后台刷新任务。** 规格第 10 节要求刷新失败时把连接标成 `degraded` 并通知商家。Telegram 的 bot token 不过期,所以这一步没有能证明它的通道;它属于 Shopee(第 5 步)和 WhatsApp(第 6 步),那时才有会过期的 token 可测。`ChannelConnectionStatus.DEGRADED` 这个枚举值已经存在,等着被用。
- **Meta 系(Messenger、Instagram)与 RedNote。** RedNote 在有正当 API 之前不写,而且永远不用浏览器自动化 —— 被封的是客户的账号。
- **前端**(第 7 步)。
