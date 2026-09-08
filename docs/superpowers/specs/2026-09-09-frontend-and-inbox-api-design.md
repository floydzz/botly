# botly — Frontend and Inbox API Design

**Date:** 2026-09-09
**Status:** Approved for planning
**Scope:** Build-order steps 4 (the missing half) and 7 — the seller inbox API with
realtime, and the Nuxt frontend including the marketing landing page.

---

## 1. Why this document exists

The architecture spec's build order puts the frontend at step 7 and the inbox API at
step 4. Step 4 shipped its models in `4eaecb2` and stopped there. As of today the
entire HTTP surface is:

| Endpoint | Source |
|---|---|
| `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` | `app/api/auth.py` |
| `GET /healthz` | `app/api/health.py` |
| `POST /webhooks/{provider}/{connection_id}` | `app/api/webhooks.py` |

There is no conversations API, no WebSocket, and no CRUD for bots or channel
connections. A frontend built today could render a login form and nothing else.

This document therefore covers both halves: the API the inbox needs, and the
frontend that consumes it — plus the landing page, which depends on neither.

## 2. Phases

Three separable pieces. The landing page is the stated priority and has no backend
dependency, so it goes first; the app UI cannot start before the API it reads.

| Phase | Contents | Depends on |
|---|---|---|
| **1. Frontend foundation + landing** | Nuxt app, design tokens, the 3D convergence scene, scroll motion system, login page against the existing `/auth/*` | nothing |
| **2. Inbox API + realtime** | Conversations, messages, agent send, takeover/release, bots, connections, WebSocket, Redis event bus | nothing |
| **3. App UI** | Inbox, bot settings, channels, wired to Phase 2 | Phases 1 and 2 |

Each phase gets its own implementation plan. Phases 1 and 2 are genuinely parallel.

---

# Part A — Inbox API (Phase 2)

## 3. Tenancy rule

Every endpoint below depends on `tenant: TenantScope = Depends(tenant)` and filters on
`TenantScope.merchant_id`. No endpoint reads a merchant id from a path, a query
parameter or a body — the rule `app/api/deps.py` already states, restated here because
this is the first set of endpoints large enough to make breaking it easy.

A conversation belonging to another merchant returns **404, not 403**. A 403 confirms
the row exists, which turns id enumeration into a census of other tenants' traffic.

## 4. Endpoints

All under new routers `app/api/conversations.py`, `app/api/bots.py`,
`app/api/connections.py`, registered in `create_app()`.

### 4.1 Conversations

```
GET /conversations
  ?state=bot|pending_human|human|resolved   (repeatable)
  &provider=telegram                        (repeatable)
  &assignee=me|unassigned|<user_id>
  &unread=true
  &cursor=<opaque>&limit=50
```

Ordered `last_message_at DESC NULLS LAST, id DESC`. `last_message_at` is nullable on
a conversation that has been created but whose first message write has not landed, so
the null ordering is explicit rather than left to the default.

The cursor is an opaque base64 of `(last_message_at, id)`, not an offset. Offset
pagination on a list reordered by every inbound message skips and repeats rows.

Item shape:

```json
{
  "id": 41,
  "customer_name": "Siti",
  "customer_ref": "88213441",
  "provider": "telegram",
  "connection_id": 3,
  "bot": {"id": 2, "name": "Order bot"},
  "handoff_state": "pending_human",
  "escalation_reason": "the customer asked for a person",
  "assignee": null,
  "last_message_at": "2026-09-09T04:12:55Z",
  "last_message_preview": "so where is my parcel",
  "unread": true,
  "has_failed_delivery": false
}
```

`unread` is derived — `last_message_at > agent_last_read_at` — never a stored counter,
matching the reasoning already written on `Conversation.agent_last_read_at`.
`has_failed_delivery` is true when the conversation's most recent outbound message has
`delivery_status = failed`, so the list can mark a thread whose last send failed without
the client fetching every message. Computed in the list query as a lateral join on the
newest outbound row, not as a per-row follow-up query.

```
GET  /conversations/{id}            → detail + send_policy (§5)
GET  /conversations/{id}/messages   ?cursor=&limit=50, newest first
POST /conversations/{id}/read       → stamps agent_last_read_at = now, 204
POST /conversations/{id}/takeover   → 200 with the updated conversation
POST /conversations/{id}/release    → 200
POST /conversations/{id}/resolve    → 200
POST /conversations/{id}/messages   → 201 with the created message, or 409 (§6)
```

Message shape mirrors the model: `id, direction, sender_type, sender: {id, name} | null,
text, attachments, provider_message_id, delivery_status, error, created_at`.

**Takeover** sets `handoff_state = human`, `assignee_id = current user`, and clears
`bot_muted_until`. Muting is unnecessary here — `_bot_must_stay_quiet` in
`app/runtime/pipeline.py` already treats `human` as silent.

Takeover on a conversation another agent holds returns **409** with the current
assignee's name. Silently stealing it means two agents type into the same thread.

**Release** sets `handoff_state = bot`, clears `assignee_id`, and sets
`bot_muted_until = now + BOT_MUTE_AFTER_RELEASE_SECONDS` (new setting, default 120).
Without the grace period the next customer message can arrive while the agent's
closing line is still in flight, and the bot answers over a person who just said
goodbye. The mute field exists for exactly this and is currently unused by any writer.

**Resolve** sets `handoff_state = resolved` and clears `assignee_id`. The pipeline
already reopens a resolved conversation when a new message arrives, so resolve is not
a terminal state and the UI must not present it as one.

### 4.2 Bots and connections

```
GET   /bots                → id, name, shop, persona, llm_provider,
                             enabled_tools, escalation_max_bot_turns
PATCH /bots/{id}           → persona, llm_provider, enabled_tools,
                             escalation_max_bot_turns
GET   /channels/connections → id, provider, external_ref, status, bot, capabilities
```

`Bot` and `ChannelConnection` carry no denormalised `merchant_id`, unlike `Conversation`
and `Message`. Their tenant filter is therefore a **join** — `Bot → Shop → merchant_id`,
and `ChannelConnection → Bot → Shop → merchant_id` — which is exactly the shape the
architecture spec warns about, since a forgotten join raises nothing and simply returns
another tenant's rows. Both routers get the join in a single shared query helper that
takes a `TenantScope`, and the isolation test in §14 covers these two endpoints
specifically for that reason.

Connections are **read-only in v1**. Creating one means accepting a bot token over
HTTP and calling `adapter.connect()` to register a webhook — a credential-handling
surface that deserves its own design rather than a paragraph here. `scripts/seed_telegram.py`
remains the way a connection is created.

`capabilities` on a connection is the adapter's `ChannelCapabilities` serialised, so
the channels screen can state each channel's real limits instead of hardcoding them.

## 5. `send_policy` — the composer's contract

Architecture spec §9: *"a human replying on WhatsApp outside the 24-hour window cannot
send free-form text either. The UI must surface that constraint explicitly rather than
letting the send fail silently."*

`GET /conversations/{id}` therefore returns:

```json
"send_policy": {
  "can_send_freeform": false,
  "reason": "the session window has closed and this channel requires an approved template",
  "max_text_len": 4096,
  "supports_media": true,
  "window_closes_at": "2026-09-10T04:12:55Z"
}
```

Computed from `type(adapter).capabilities` and `conversation.last_inbound_at`, using the
same rule as `OutboundDispatcher._window_is_closed` — including its treatment of an
unknown `last_inbound_at` as closed rather than open.

This is advisory. The dispatcher still enforces the rule independently on send; the
policy exists so the UI can disable the composer with an explanation instead of
letting an agent type a paragraph into a box that will reject it.

## 6. Agent send

`POST /conversations/{id}/messages` routes through `OutboundDispatcher`, not directly
to the adapter — architecture spec §9 requires agent replies to travel the same path,
which is what makes chunking, rate limiting and window rules apply to humans too.

Sequence:

1. Load the conversation tenant-scoped; 404 if it is not this merchant's.
2. Reject with **409** if `handoff_state` is not `human`, or if `assignee_id` is not
   the current user. An agent sending into a thread the bot still owns produces two
   voices in one conversation.
3. Build the adapter via `build_adapter(connection)`; a `MissingCredentials` or
   `UnknownProvider` is a **502** naming the connection, not a 500.
4. `dispatcher.dispatch(connection, DraftReply(text=...), last_inbound_at=...)`.
5. Persist and respond.

**The escalation return needs special handling.** `dispatch()` signals a refused send
by returning `DispatchOutcome(escalated=True, reason=...)` — for a closed session
window, or media on a text-only channel. In the pipeline that correctly means "give it
to a person". Here the conversation *is already with a person*, so escalating again is
meaningless. The endpoint maps `outcome.escalated` to **409 with `outcome.reason`**,
which the composer renders inline. No message row is written: nothing was said.

`outcome.permanent_failure` is different — the send was attempted and failed. A
`Message` row is written with `delivery_status = failed` and `error` set, a `FailedJob`
is recorded, and the endpoint returns **201** with that message. The agent must see
their own failed message in the thread; swallowing it as an error toast loses the text
they typed.

### 6.1 Shared outbound recording

`_store_outbound` in `app/runtime/pipeline.py` writes `sender_type = BOT` and is
private to that module. The agent path needs the same delivery-status and error logic
with `sender_type = AGENT` and `sender_user_id` set. Rather than duplicate it, extract
`app/dispatch/record.py::record_outbound(db, conversation, text, attachments, outcome,
sender_type, sender_user_id=None)` and have both callers use it. This is a targeted
improvement to code the work touches, not a general refactor.

### 6.2 Rate limiting across processes

`app/runtime/pipeline.py` constructs `InMemoryTokenBucket`. `RedisTokenBucket` exists
in `app/dispatch/ratelimit.py`, with the Lua script and the comment explaining why —
*"two workers share one provider quota"* — and nothing constructs it.

In-process buckets were adequate while one worker was the only sender. Adding the API
process as a second sender makes them wrong: the worker and the API would each hold a
full bucket for the same connection, so the effective outbound rate against a provider
doubles, and a provider-side rate limit is not a soft failure.

Both call sites therefore construct `RedisTokenBucket` against `settings.REDIS_URL`.
Tests keep `InMemoryTokenBucket` by injection, exactly as they do now.

## 7. Realtime

### 7.1 The process boundary

Messages are written by the Celery worker. WebSockets live in the uvicorn process.
They are different processes, so an in-memory broadcast registry delivers nothing in
production while passing every single-process test — a failure mode that only appears
under `docker compose`.

A Redis pub/sub bus carries events across the boundary. Redis is already a dependency
and the architecture spec keeps it for precisely this class of state.

`app/realtime/bus.py`:

```python
class EventBus(Protocol):
    async def publish(self, merchant_id: int, event: dict) -> None: ...
    def subscribe(self, merchant_id: int) -> AsyncIterator[dict]: ...
```

`RedisEventBus` publishes to channel `merchant:{merchant_id}:events`; `FakeEventBus`
is an in-memory queue for tests. Per the `adapters/` discipline: a Protocol with a fake.

The channel is keyed by merchant, so a subscriber can only ever receive its own
tenant's events. The tenant boundary is in the channel name, not in a filter the
consumer has to remember to apply.

### 7.2 Events

Published by the pipeline after commit, and by the conversation endpoints after theirs:

| Event | Payload | Emitted when |
|---|---|---|
| `message.created` | conversation_id, the message object | inbound stored, bot reply stored, agent reply stored |
| `conversation.updated` | the conversation summary object | handoff state, assignee, or last_message_at changes |

Published **after** commit, never inside the transaction. An event announcing a row
that a later rollback erased makes the inbox show a message that does not exist.

Delivery is best-effort and the client does not depend on it for correctness: the
inbox refetches on reconnect. A dropped event costs a delayed update, not a wrong one.

### 7.3 The WebSocket

`GET /ws` in `app/api/realtime.py`. Authentication reuses the session cookie — the
browser sends it on the WebSocket handshake, and the token is never placed in a query
string where it would land in access logs.

`current_user` raises `HTTPException`, which a WebSocket route cannot return. The route
resolves the session with the same query and, on failure, calls
`websocket.close(code=1008)` before accepting. Refusing before `accept()` means an
unauthenticated client never reaches a connected state.

Each connection subscribes to its own merchant's channel and forwards frames as JSON.
A ping every 30s keeps intermediaries from idling the socket out.

---

# Part B — Frontend (Phases 1 and 3)

## 8. Stack and layout

Nuxt 3 following `ai-customer-support/frontend`: Tailwind, Pinia, `@nuxt/icon`. Added
for this project: `three` and `gsap`.

```
frontend/
  nuxt.config.ts
  app.vue
  assets/css/tokens.css
  pages/
    index.vue                 marketing
    login.vue
    app/inbox/[[id]].vue      list and thread in one route
    app/bots/index.vue  app/bots/[id].vue
    app/channels/index.vue
  layouts/            marketing.vue · app.vue
  components/
    landing/          ConvergenceCanvas · HeroSection · ChannelsSection · …
    inbox/            ConversationList · MessageThread · Composer · EscalationBanner
    ui/               Button · Field · StatusDot · Panel
  composables/        useConvergenceScene · useScrollMotion · useRealtime · useApi
  stores/             auth.ts · inbox.ts
  middleware/         auth.ts
```

`routeRules`: marketing routes prerendered for SEO, `/app/**` with `ssr: false` — an
authenticated inbox has nothing to gain from server rendering and would need the
session cookie forwarded through Nitro to get it.

**Dev proxy.** Nitro `devProxy` maps `/api` → `http://localhost:8000`. The session
cookie is `httponly` and `samesite=lax` (`app/api/auth.py`), so a cross-origin
frontend would not send it and every authenticated request would 401. Same-origin is
a requirement, not a convenience. In production the same path is served by the
reverse proxy.

`middleware/auth.ts` is a global middleware guarding `/app/**`: it calls `GET /auth/me`
once, hydrates the auth store, and redirects to `/login` on 401.

**There is no registration endpoint, deliberately** — `app/api/auth.py` says so. The
landing CTA is therefore **"Request access"**, not "Sign up": a form that collects an
email and does not pretend an account was created. A sign-up button leading to a login
form with no way to obtain credentials is worse than no button.

## 9. Visual direction

Dark cinematic with a warm accent. Particles read against dark; a light ground would
require an entirely different scene treatment for a fraction of the impact.

Tokens live in `assets/css/tokens.css` as CSS custom properties consumed by the
Tailwind config, so a light theme later is a second `:root` block rather than a rewrite.

```
ground        #08090B      surface     #101216      raised   #171A20
border        #23262E      border-lit  #333844
text          #F4F5F7      text-dim    #9BA1AC      text-mute #5C626D
accent        #F0A24B      accent-lit  #FFC978      accent-dim rgba(240,162,75,.14)
ok #3FD07A    warn #F0A24B    danger #E0523F

channel hues (particles and status dots)
telegram #2FA8E0   whatsapp #3FD07A   shopee #F1642E   instagram #C64BB4
```

Type: **Inter Tight** for display, **Inter** for body, **JetBrains Mono** for eyebrows,
labels, ids and timestamps. All three are open-licensed and self-hosted — a
`fonts.googleapis.com` request on a landing page whose whole point is fluidity is a
render-blocking round trip.

Scale `clamp()`-driven: display 3.5–6rem, h2 2–3rem, body 1rem/1.6, mono-label
0.75rem/0.14em tracking. Spacing on a 4px base. Radii 6/10/16. Motion: 180ms for state,
420ms for entrance, `cubic-bezier(.16,1,.3,1)` as the house ease.

The app inherits the same tokens with a lifted panel surface, staying dark. A light
theme for agents working long shifts is a reasonable later request; the token structure
allows it and v1 does not ship it.

## 10. The convergence scene

`composables/useConvergenceScene.ts`, mounted client-only by
`components/landing/ConvergenceCanvas.vue`. The canvas is `position: fixed` behind the
whole marketing page and sections scroll over it — that persistence is what makes the
page read as one continuous motion rather than a hero widget that dies after the fold.

### Geometry

One `THREE.Points` of 60k particles, one `ShaderMaterial`, one draw call. Per-particle
attributes: `aChannel` (0–3), `aPhase`, `aSpeed`, `aSpread`.

The **vertex shader** evaluates a cubic Bézier from the particle's channel node to the
core at `t = fract(uTime * aSpeed + aPhase)`, with control points bowed outward so the
paths arc rather than converge as straight spokes. Curl-noise displacement scaled by
`aSpread * (1.0 - t)` adds drift that decays to zero at arrival, so the flow is
turbulent at the edges and clean at the centre. Positions are never computed on the
CPU; the per-frame JS cost is a handful of uniform writes.

The **fragment shader** draws a soft radial falloff and lerps the particle's channel
hue toward `--accent` as `t → 1`, so colour convergence and spatial convergence are the
same gesture.

The core is a separate additive glow quad whose intensity is driven by arrival density.
No `UnrealBloomPass`: full postprocessing costs extra render targets for an effect a
well-authored additive sprite delivers at a fraction of the cost, and it is the first
thing that collapses on a mid-range Android.

Channel nodes are HTML labels positioned by projecting world coordinates each frame —
DOM text stays selectable, accessible and crisp, which canvas text is not.

### Scroll

GSAP ScrollTrigger scrubs a single `uProgress` uniform plus camera z, from 9.0 to 3.2.
One scrubbed timeline, not one per section: several competing ScrollTriggers on one
camera is how scroll animation becomes jittery.

| progress | beat |
|---|---|
| 0.00 | hero — nodes wide, slow drift |
| 0.20 | channels named, labels resolve |
| 0.45 | convergence tightens, flow accelerates |
| 0.70 | core blooms, inbox UI fragment fades in over it |
| 1.00 | scene recedes, CTA holds the frame |

### Budget

Non-negotiable, because a landing page that stutters undermines the exact claim it is
making:

- `renderer.setPixelRatio(Math.min(devicePixelRatio, 2))`.
- Particle count by tier: 60k desktop, 25k tablet, 12k mobile, chosen from screen width
  and `hardwareConcurrency`.
- RAF paused on `visibilitychange` and by an `IntersectionObserver` on the canvas.
- `prefers-reduced-motion: reduce` → one static composed frame at `uProgress = 0.5`, no
  RAF loop, no scrub; sections still fade in on scroll but nothing moves continuously.
- No WebGL context → a prerendered poster image. The page must be fully readable and
  the CTA fully usable with the canvas absent.
- Target: 60fps desktop, ≥30fps mid-range mobile, LCP unaffected — the canvas mounts
  after hydration and is never the LCP element.

## 11. Landing page content

Sections, in order: hero; the problem (the same questions, all day, across platforms);
**channels**; how it works (ingress → brain → dispatcher → inbox); the handoff; the
facts-from-tools guarantee; request access.

Two content rules carried from the architecture spec, recorded here because a marketing
page is exactly where they get broken:

- **The channels section states real status.** Telegram live; WhatsApp and Shopee
  pending provider approval; RedNote not offered. Spec §2 is explicit that RedNote must
  not be marketed until a legitimate API exists, and `docs/approvals.md` records that
  neither WhatsApp nor Shopee verification has been started. A grid of four logos
  implying four working integrations is a claim the product cannot honour.
- **The guarantee section states spec §8's central rule plainly**: facts come from
  tools, never from the model; when a tool fails the bot escalates rather than guesses.
  For a seller weighing a bot against refund disputes, this is the strongest thing the
  page has to say.

## 12. App UI

### Inbox — `/app/inbox/[[id]]`

Three panes: filter rail, conversation list, thread with composer. Filters map exactly
to the `GET /conversations` query parameters, with counts per state.

The thread distinguishes customer, bot and agent messages, and a bot reply is
**visibly labelled as the bot's** — an agent picking up a conversation needs to know
what the customer has already been told before they add to it.

Three behaviours that are requirements rather than polish:

- A message with `delivery_status = failed` renders inline with its `error` text and a
  retry action. Retry is not a new endpoint: it re-submits the same text through
  `POST /conversations/{id}/messages`, producing a new message row rather than mutating
  the failed one, so the thread keeps an honest record of both attempts. Spec §10
  requires a permanent send failure to be visible in the inbox;
  today it reaches `failed_jobs`, which no screen reads, and the `Message.error` column
  exists for this and is rendered nowhere.
- A `pending_human` conversation shows `escalation_reason` at the top of the thread
  with the Take over button. `app/runtime/escalation.py` states the reason is written
  for the agent who picks it up; burying it in a list subtitle wastes it.
- The composer is **disabled with the explanation shown**, not silently, when
  `send_policy.can_send_freeform` is false, and shows a live character count against
  `max_text_len` with the chunk boundary marked — the dispatcher will split at that
  point and the agent should know where.

Realtime: `useRealtime` opens the WebSocket, applies `message.created` and
`conversation.updated` to the Pinia store, and refetches the visible page on reconnect
rather than trusting that no event was missed while disconnected.

### Bots — `/app/bots/[id]`

Persona (textarea), `llm_provider`, `enabled_tools` (toggles), and
`escalation_max_bot_turns` with its meaning spelled out: how many times the bot may
answer an unresolved question before a person takes over.

### Channels — `/app/channels`

One card per connection: provider, `external_ref`, status, and the capability summary
from the manifest. `degraded` is surfaced loudly with its meaning — the connection
still shows history, sends are expected to fail until credentials are repaired — since
that is the state a merchant must act on and the one most easily missed.

---

## 13. Error handling

| Case | Handling |
|---|---|
| 401 on any app request | auth store clears, redirect to `/login` with a return path |
| 409 on takeover | inline notice naming the current assignee; list refetches |
| 409 on send | composer keeps the typed text and shows the channel's reason. Never clear a box the send did not leave |
| 201 with `delivery_status = failed` | message appears in the thread marked failed; retry re-sends the text as a new message |
| WebSocket drop | exponential reconnect to 30s, a quiet "reconnecting" indicator, full refetch on resume |
| WebGL absent or context lost | poster image; page fully functional |
| API unreachable | app shell renders with a retry; the landing page is static and unaffected |

## 14. Testing

**Backend** — pytest, TDD, following the existing suite:

- Tenant isolation per endpoint: another merchant's conversation is 404 on read,
  takeover, release, resolve and send.
- Cursor pagination: stable across an insert that reorders the list.
- `send_policy` computed for an open window, a closed window, and an unknown
  `last_inbound_at`.
- Agent send: 409 when the state is not `human`; 409 when assigned elsewhere; 409 with
  reason on `outcome.escalated` and **no message row written**; 201 with a failed
  message row on `outcome.permanent_failure`.
- Takeover conflict between two agents.
- WebSocket: closes 1008 without a cookie, with an expired session, and with a revoked
  one; delivers an event published for its own merchant and never one published for
  another.
- `record_outbound` covered once, used by both callers.

**Frontend** — Vitest on the inbox store's event reducers and the composer's
send-policy logic, plus one Playwright smoke: login → inbox → open a conversation →
take over → send → see the message. The reference project has no frontend tests; this
is the amount that pays for itself.

The 3D scene is not unit-tested. Its correctness is visual, and a test asserting that a
shader compiled tells you nothing about whether it looks right. It gets a manual
checklist instead: the four device tiers, reduced-motion, and no-WebGL.

## 15. Out of scope

- Channel connection creation and credential entry in the UI. Seeding stays the path.
- Message templates and template selection for WhatsApp. `message_template` is a later
  plan and the dispatcher currently escalates rather than choosing one.
- Knowledge base UI. `kb_document` and `kb_chunk` do not exist yet.
- Analytics, billing, and merchant/user administration.
- A light theme, and i18n. Structure allows both; v1 ships English and dark.
- A visual flow builder — a v1 non-goal in the architecture spec.

## 16. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| The scene is heavy on mid-range Android, where much of the audience is | The page contradicts its own claim on the devices that matter most | Tiered particle counts and a device-tier check as an explicit acceptance criterion, tested on a real mid-range handset rather than a throttled desktop |
| The Redis event bus adds a failure mode where the inbox looks live but is stale | An agent replies believing they have the latest message | Refetch on reconnect and on window focus; the WebSocket is an accelerator, never the source of truth |
| Two senders against one provider quota | Provider-side rate limiting, which is not a soft failure | `RedisTokenBucket` at both call sites (§6.2), which is why that change is in this scope |
| Landing page implies channels that are not approved | A claim the product cannot honour, made to the exact buyer who would notice | §11 content rule; the channels section renders status, and `docs/approvals.md` is its source of truth |
| Phase 3 blocked if Phase 2 slips | The visible half of the work stalls | Phases 1 and 2 are independent; the landing page ships either way |
