# botly — Architecture Design

**Date:** 2026-09-02
**Status:** Approved for planning
**Scope:** v1 architecture for a multi-tenant chatbot platform serving Southeast Asian
commerce sellers.

---

## 1. Problem and Positioning

Southeast Asian commerce sellers answer the same handful of questions all day, across
several platforms at once: where is my parcel, is this in stock, what size should I buy,
can I return this. They answer them on WhatsApp, on Shopee's in-platform chat, on
Instagram, and increasingly on RedNote — from a phone, in a mix of English, Malay and
Chinese, often within one sentence.

botly is a platform where a seller configures one bot and connects it to the channels they
already sell on. The bot answers from the seller's real order and catalogue data, and hands
off to a human the moment it is out of its depth.

**This is deliberately not a general-purpose bot builder.** The generic market (ManyChat,
Chatfuel, Botpress, Voiceflow, Tidio, WATI) is saturated. The wedge is the specific channel
mix — Shopee + WhatsApp + RedNote — which is a Southeast Asian commerce stack, not a
Western support-desk stack. That positioning drives every decision below: the product's
centre of gravity is the commerce data connector and the seller inbox, not the flow editor.

### Non-goals for v1

- A visual flow builder. Bot configuration is persona + knowledge base + enabled tools.
  A flow editor is a multi-month frontend project that competitors have already won, and
  order-status bots do not need one.
- White-labelling, export/report registries, and diagnostic-case tooling. These exist in
  `aib-backend` and are not carried over until a customer asks.
- Any capability that lets the bot take an action costing money (issue a refund, cancel an
  order, change a price). v1 is read-only against commerce systems.

---

## 2. Channel Reality

Channel access, not bot logic, is the dominant constraint on this project. The six named
targets are wildly unequal:

| Channel | Access reality | Effort |
|---|---|---|
| Telegram | Open Bot API, token from BotFather, webhooks, no gatekeeper | Days |
| Facebook Messenger | Graph API, `pages_messaging`, App Review + Business Verification. 24h window, then tags only | Weeks |
| Instagram DM | Same Graph API family as Messenger — largely one integration and one review. Business/Pro accounts only | Shared with Messenger |
| WhatsApp | Cloud API. Business verification, pre-approved templates, 24h service window, per-conversation billing | Weeks + recurring cost |
| Shopee | Open Platform seller chat APIs exist but partner registration is gated and region-scoped. Acts on behalf of a shop, not a page | Weeks + approval risk |
| RedNote (小红书) | No generally-available third-party DM API. The merchant/customer-service side is gated and typically requires a Chinese entity. Browser automation would violate ToS and risk bans on **customer** accounts | Blocked / high risk |

**Design consequence:** the adapter interface is designed for all six. v1 implements **two
channel adapters** (Telegram, WhatsApp) plus a **Shopee data client** that is not a channel
adapter — it is a read-only commerce connector consumed by the bot's tools. Shopee's chat
channel adapter, the Meta family, and RedNote are v2 or later.

**Critical-path consequence:** for this audience Shopee is simultaneously a *channel* and
the *order database*. A WhatsApp-only bot still needs Shopee Open Platform access to answer
"where is my parcel". Shopee API approval therefore sits on the critical path regardless of
which channel ships first, and it is approval-gated — so it must be probed early rather
than assumed.

**RedNote is explicitly out of scope for implementation in v1.** The adapter interface
accommodates it; no adapter is written until a legitimate API path exists. We will not ship
browser automation, because the account that gets banned belongs to the customer.

---

## 3. Relationship to Existing Code

botly is a **greenfield repository that ports selectively** from `~/Documents/aib-backend`
(AICS). It is not a fork and not a new branch of that system.

### Port — proven and genuinely generic

- `orchestration/types.py::StandardizedInput` and the input router (attachment, vision and
  OCR normalization). Its own docstring already describes it as the locked ingress schema
  that every modality normalizes to; that is exactly botly's message envelope.
- The tool registry shape, and the `/tools` capability-metadata-only exposure pattern.
- RAG retrieval over Qdrant, together with its scope-evidence test approach.
- Celery task patterns and the `failed_job` model.
- Observability wiring (Langfuse / Grafana / Tempo).
- The `ENVIRONMENT=production` startup gating, where unsupported aliases fail hard so
  security controls cannot silently run in development mode.

### Rebuild — commerce-shaped, or too fused to AICS

- Tenancy: `Merchant → Shop → Bot → ChannelConnection` (AICS's merchant model has no shop
  layer, and commerce credentials belong to a shop).
- The channel layer. `aib-backend/app/channels/telegram/service.py` is 1,129 lines with
  generic pipeline logic (pairing, dedupe, queueing, retry, thread-to-conversation mapping)
  fused into Telegram specifics. botly extracts that generic half into the adapter Protocol
  and the runtime, and keeps only Telegram-specific code in the Telegram adapter.
- Conversation and message models, shaped around handoff state from the start.
- The seller inbox.

### Leave behind

The loan/application domain, diagnostic cases, the export/report registry, and
white-labelling.

### House conventions carried over

FastAPI + SQLModel + Alembic + MySQL + Redis + Celery + Qdrant + LangGraph, Docker Compose,
pytest. Every external service sits behind a Protocol with a fake, following the `adapters/`
discipline in the Kira project.

---

## 4. Architecture

**Shape: a modular monolith with one adapter per channel, a per-channel capability manifest,
and a queue between ingress and runtime.**

```
Channel webhooks
      │
      ▼
  Ingress  ── verify signature, dedupe, persist raw, ACK 200 (<100ms)
      │
      ▼
   Queue (Redis / Celery)          ◄── the pre-cut seam
      │
      ▼
  Bot Runtime ── handoff check → StandardizedInput → LangGraph brain
      │                              (RAG + deterministic tools) → DraftReply
      ▼
  Outbound Dispatcher ── capability check, window/template rules,
      │                  chunking, rate limit, retry
      ▼
   Adapters ──► Telegram | WhatsApp | (Shopee, Meta, RedNote later)

  Seller Inbox ◄──► WebSocket ◄──► Conversation state (takeover, mute, release)
```

### Why this shape

Two alternatives were considered and rejected for v1:

- **A split ingress-gateway and runtime (two services).** Correct under Meta's aggressive
  webhook retries and scales the cheap half independently, but costs two deploys, two
  configurations, and distributed tracing on day one — real operational expense before
  there is a single paying seller.
- **A full plugin registry where channels self-register.** Its central benefit is the
  capability manifest, which we adopt directly; the rest is indirection that does not pay
  for itself at three channels.

The chosen shape takes the capability manifest from the plugin approach and pre-cuts the
seam for the split: **the queue is the seam.** When webhook volume justifies separating
ingress from runtime, it becomes a deployment change rather than a rewrite.

### Why the capability manifest earns its keep immediately

The channels genuinely disagree with each other. Telegram will send anything at any time.
WhatsApp refuses free-form text outside a 24-hour window and demands a pre-approved
template. Shopee has its own reply constraints. Without a manifest, that is three special
cases in the dispatcher and a fourth when RedNote arrives — and those special cases leak
into the runtime, the inbox, and eventually the frontend. With one, the rules live in one
place and the dispatcher asks a question instead of branching on a provider name.

---

## 5. Domain Model

```
Merchant                       tenant, billing, subscription
 └─ Shop                       a Shopee shop or a brand; holds commerce credentials
     └─ Bot                    persona, knowledge base, enabled tools, LLM provider
         └─ ChannelConnection  provider + encrypted credentials + status

Conversation   bot_id, channel_connection_id, external_thread_id,
               handoff_state, assignee_id, last_inbound_at, bot_muted_until
 └─ Message    direction, sender_type (customer | bot | agent), content,
               attachments, provider_message_id, delivery_status
```

`Shop` is separate from `Merchant` because a merchant may run several Shopee shops or
brands, and commerce credentials belong to the shop rather than the tenant. One `Bot` may
serve several channels of the same shop.

`Conversation.handoff_state` is the pivotal v1 field:
`bot | pending_human | human | resolved`, alongside `bot_muted_until`.

Supporting tables: `inbound_event` (raw payload plus dedupe key), `failed_job`,
`message_template` (per-connection, tracking provider approval status).

---

## 6. Channel Adapter Interface

```python
class ChannelCapabilities(BaseModel):
    supports_media: bool
    max_text_len: int
    session_window: timedelta | None          # None = always open (Telegram)
    requires_template_outside_window: bool
    supports_typing_indicator: bool

class ChannelAdapter(Protocol):
    provider: ClassVar[str]
    capabilities: ClassVar[ChannelCapabilities]

    def verify_webhook(self, headers, raw_body) -> bool: ...
    def parse_inbound(self, payload) -> list[InboundEnvelope]: ...
    async def send(self, conn, out: OutboundMessage) -> SendResult: ...
    async def connect(self, conn) -> None: ...      # register webhook, validate credentials
    async def disconnect(self, conn) -> None: ...
```

Every adapter ships with a fake. Channel differences are confined inside adapters: no code
outside `app/channels/<provider>/` may branch on a provider name.

---

## 7. Message Flow

### Inbound

`POST /webhooks/{provider}/{connection_id}` verifies the signature, dedupes on
`(provider, provider_update_id)` against both Redis and the `inbound_event` table, persists
the raw payload, **acknowledges 200 immediately**, and enqueues a Celery task. The fast ACK
is not an optimization: Meta retries aggressively and will duplicate-deliver, so the
dedupe-plus-fast-ACK pair is a correctness requirement.

### Runtime

The worker loads the conversation and checks `handoff_state` first.

- **`human`** — store the message, push it to the inbox over WebSocket, and **do not invoke
  the LLM**.
- **`bot`** — normalize to `StandardizedInput`, run the LangGraph brain (RAG plus
  deterministic tools), produce a `DraftReply`, apply guardrails, and pass it to the
  dispatcher.

### Outbound

The dispatcher reads the adapter's capabilities, and in order: selects an approved template
if the session window has closed and the channel requires one (escalating to a human if no
suitable template exists), chunks to `max_text_len`, applies a Redis token-bucket rate limit
per connection, retries with backoff, and records permanent failures in `failed_job`.

---

## 8. Commerce Tools

Deterministic functions, not LLM output: `get_order_status`, `track_shipment`,
`check_stock`, `get_return_policy`, `escalate_to_human`. All commerce calls go through a
Shopee Open Platform client that refreshes per-shop tokens automatically.

> **The central rule: facts come from tools, never from the model.** When a tool fails, the
> bot says it cannot check and escalates. It does not guess. A hallucinated order status is
> a refund dispute, and this rule is the guardrail that prevents one.

---

## 9. Human Takeover (v1)

- **Inbox** — conversations across all channels, filterable by state, channel and unread.
- **Takeover** — an agent takes a conversation, setting `handoff_state = human` and muting
  the bot.
- **Agent replies travel through the same outbound dispatcher.** This matters: a human
  replying on WhatsApp outside the 24-hour window cannot send free-form text either. The UI
  must surface that constraint explicitly rather than letting the send fail silently.
- **Automatic escalation triggers** — low model confidence, tool failure, an explicit
  customer request for a human, strong negative sentiment, any refund or money keyword, or
  three consecutive bot turns without the customer's question being resolved. The turn
  threshold is configurable per bot; three is the default.
- **Release** — an explicit hand-back, or automatically once resolved.
- **Realtime** — a WebSocket per agent session, following the patterns already present in
  `ai-customer-support` and `aib-backend/contracts/websocket`.

---

## 10. Error Handling

| Scenario | Handling |
|---|---|
| Duplicate webhook | Dedupe table plus Redis key; poison messages go to `failed_job` with the raw payload and never block the queue |
| Tool timeout | Per-shop circuit breaker; an open circuit escalates to a human |
| LLM failure | Multi-provider fallback, then escalate |
| Send failure | Retry with backoff; permanent failure shows in the inbox as "delivery failed" so an agent sees it |
| Credential expiry | Background refresh task; on failure the connection is marked `degraded` and the merchant is notified |

---

## 11. Testing Strategy

- A fake adapter per channel, driven by fixtures captured from real webhook payloads.
- **Contract tests:** every adapter passes one shared `ChannelAdapter` conformance suite.
- **Capability tests:** the dispatcher must refuse illegal sends, such as free-form text
  outside the WhatsApp window.
- Golden tests for the brain, plus the RAG scope-evidence approach carried over from AICS.
- No live network access in tests.

---

## 12. Build Order

1. Skeleton, tenancy models, migrations
2. `ChannelAdapter` Protocol, fake, and conformance suite
3. **Telegram adapter** — no gatekeeper, so it proves the whole pipeline end to end
4. Conversation and message models, inbox API, WebSocket, human takeover
5. Shopee data client and commerce tools
6. WhatsApp adapter, with template and window handling
7. Frontend (Nuxt, following `ai-customer-support`)

> **Start the Shopee Open Platform and WhatsApp Business verification applications on the
> same day as step 1, in parallel with the code.** These approvals are the long pole, and
> they are not engineering work. If either is refused, steps 5 and 6 need replanning
> entirely — which is an argument for finding out as early as possible.

---

## 13. Open Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Shopee Open Platform access refused or delayed | Steps 5-6 invalid; the core value proposition is gone | Apply on day 1; keep tools behind a Protocol so a manual CSV order import can substitute temporarily |
| WhatsApp Business verification refused | The primary v1 channel is lost | Apply on day 1; Telegram carries the demo meanwhile; a BSP (Twilio, 360dialog) is the fallback route |
| WhatsApp per-conversation cost exceeds seller willingness to pay | Unit economics fail | Model the cost before pricing; consider passing it through per-conversation rather than absorbing it |
| RedNote never opens a legitimate API | A marketed channel cannot ship | Do not market it until it exists; never substitute browser automation |
