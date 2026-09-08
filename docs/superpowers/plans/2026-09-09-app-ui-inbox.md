# botly App UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the authenticated app — the three-pane inbox with realtime, bot settings, and the channels screen — against the Phase 2 API.

**Architecture:** A Pinia store holds the conversation list and the open thread; realtime events are reducers over that store, never a second source of truth. The WebSocket is an accelerator: the inbox refetches the visible page on reconnect and on window focus rather than trusting that no event was missed while disconnected.

**Tech Stack:** Nuxt 3, Vue 3, TypeScript, Tailwind, Pinia, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-09-frontend-and-inbox-api-design.md` — §12, §13, §14.

**Prerequisites:** `docs/superpowers/plans/2026-09-09-frontend-foundation-and-landing.md` (Phase 1) and `docs/superpowers/plans/2026-09-09-inbox-api-and-realtime.md` (Phase 2), both executed.

---

## Global Constraints

- **The WebSocket is never the source of truth.** Refetch on reconnect and on window focus. A dropped event costs a delayed update, not a wrong one.
- **A bot reply is visibly labelled as the bot's.** An agent picking up a conversation needs to know what the customer has already been told before they add to it.
- **A failed message renders inline with its `error` text and a retry action.** Retry re-submits the same text through `POST /conversations/{id}/messages`, producing a *new* message row rather than mutating the failed one, so the thread keeps an honest record of both attempts.
- **A `pending_human` conversation shows `escalation_reason` at the top of the thread**, next to the Take over button — not buried in a list subtitle.
- **The composer is disabled with the explanation shown**, never silently, when `send_policy.can_send_freeform` is false; and it shows a live character count against `max_text_len` with the chunk boundary marked.
- **Never clear a box the send did not leave.** On a 409 the composer keeps the typed text and shows the channel's reason.
- **`resolved` is not terminal.** The pipeline reopens a resolved conversation when a new message arrives, and the UI must not present resolve as final.
- Error handling follows spec §13 exactly: 401 → clear the store and redirect to `/login` with a return path; 409 on takeover → inline notice naming the current assignee, list refetches; WebSocket drop → exponential reconnect to 30s with a quiet indicator and a full refetch on resume.

---

## File Structure

| File | Responsibility |
|---|---|
| `frontend/types/inbox.ts` | The API's shapes, in TypeScript |
| `frontend/stores/inbox.ts` | List, filters, open thread, and the event reducers |
| `frontend/composables/useRealtime.ts` | Socket lifecycle, backoff, refetch-on-resume |
| `frontend/composables/useComposer.ts` | Send-policy state, character count, chunk boundary |
| `frontend/components/inbox/FilterRail.vue` | State / assignee / provider / unread filters with counts |
| `frontend/components/inbox/ConversationList.vue` | The paginated list |
| `frontend/components/inbox/MessageThread.vue` | Customer / bot / agent messages, failures, retry |
| `frontend/components/inbox/EscalationBanner.vue` | The reason plus Take over |
| `frontend/components/inbox/Composer.vue` | The box, its policy and its counter |
| `frontend/pages/app/inbox/[[id]].vue` | List and thread in one route |
| `frontend/pages/app/bots/index.vue`, `[id].vue` | Bot settings |
| `frontend/pages/app/channels/index.vue` | Connection cards |
| `frontend/test/inbox-store.spec.ts` | The event reducers |
| `frontend/test/composer.spec.ts` | Send-policy and chunk logic |
| `frontend/e2e/inbox.spec.ts` | The Playwright smoke |

---

### Task 1: Types and the inbox store

**Files:**
- Create: `frontend/types/inbox.ts`, `frontend/stores/inbox.ts`
- Test: `frontend/test/inbox-store.spec.ts`

**Interfaces:**
- Produces `useInboxStore()` with:
  - state `conversations: ConversationSummary[]`, `nextCursor: string | null`, `openId: number | null`, `detail: ConversationDetail | null`, `messages: MessageOut[]`, `filters: Filters`, `connected: boolean`
  - actions `fetchList(reset?: boolean)`, `openConversation(id)`, `fetchMessages()`, `takeover(id)`, `release(id)`, `resolve(id)`, `send(text)`, `markRead(id)`
  - reducers `applyMessageCreated(event)`, `applyConversationUpdated(event)`

- [ ] **Step 1: Write the failing test** — `frontend/test/inbox-store.spec.ts`

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useInboxStore } from '../stores/inbox'

const summary = (over = {}) => ({
  id: 41,
  customer_name: 'Siti',
  customer_ref: '88213441',
  provider: 'telegram',
  connection_id: 3,
  bot: { id: 2, name: 'Order bot' },
  handoff_state: 'pending_human',
  escalation_reason: 'the customer asked for a person',
  assignee: null,
  last_message_at: '2026-09-09T04:12:55Z',
  last_message_preview: 'so where is my parcel',
  unread: true,
  has_failed_delivery: false,
  ...over,
})

describe('the inbox store reducers', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('appends a message to the open thread', () => {
    const store = useInboxStore()
    store.openId = 41
    store.messages = []

    store.applyMessageCreated({ type: 'message.created', conversation_id: 41, message: { id: 9, text: 'hi' } })

    expect(store.messages.map((m) => m.id)).toEqual([9])
  })

  it('ignores a message for a thread that is not open', () => {
    const store = useInboxStore()
    store.openId = 41
    store.messages = []

    store.applyMessageCreated({ type: 'message.created', conversation_id: 99, message: { id: 9 } })

    expect(store.messages).toEqual([])
  })

  it('does not duplicate a message the send already added', () => {
    // The sender receives its own event back. Without this the agent sees
    // their reply twice.
    const store = useInboxStore()
    store.openId = 41
    store.messages = [{ id: 9, text: 'hi' }]

    store.applyMessageCreated({ type: 'message.created', conversation_id: 41, message: { id: 9, text: 'hi' } })

    expect(store.messages).toHaveLength(1)
  })

  it('replaces a conversation row in place', () => {
    const store = useInboxStore()
    store.conversations = [summary()]

    store.applyConversationUpdated({
      type: 'conversation.updated',
      conversation: summary({ handoff_state: 'human', assignee: { id: 5, name: 'Ani' } }),
    })

    expect(store.conversations[0].handoff_state).toBe('human')
    expect(store.conversations).toHaveLength(1)
  })

  it('moves an updated conversation to the top when its last message moved', () => {
    const store = useInboxStore()
    store.conversations = [summary({ id: 1, last_message_at: '2026-09-09T05:00:00Z' }), summary({ id: 41 })]

    store.applyConversationUpdated({
      type: 'conversation.updated',
      conversation: summary({ id: 41, last_message_at: '2026-09-09T06:00:00Z' }),
    })

    expect(store.conversations.map((c) => c.id)).toEqual([41, 1])
  })

  it('inserts a conversation it has never seen', () => {
    const store = useInboxStore()
    store.conversations = []

    store.applyConversationUpdated({ type: 'conversation.updated', conversation: summary() })

    expect(store.conversations).toHaveLength(1)
  })

  it('drops a conversation the current filter excludes', () => {
    const store = useInboxStore()
    store.filters = { state: ['pending_human'], provider: [], assignee: null, unread: false }
    store.conversations = [summary()]

    store.applyConversationUpdated({
      type: 'conversation.updated',
      conversation: summary({ handoff_state: 'resolved' }),
    })

    expect(store.conversations).toEqual([])
  })

  it('keeps the typed text when a send is refused', async () => {
    const store = useInboxStore()
    store.openId = 41
    store.$api = { post: vi.fn().mockRejectedValue({ status: 409, detail: 'the session window has closed' }) }

    await expect(store.send('a long reply')).rejects.toMatchObject({ status: 409 })
    expect(store.messages).toEqual([])
  })

  it('adds a failed message to the thread rather than hiding it', async () => {
    const store = useInboxStore()
    store.openId = 41
    store.messages = []
    store.$api = {
      post: vi.fn().mockResolvedValue({ id: 12, text: 'sorry', delivery_status: 'failed', error: 'blocked' }),
    }

    await store.send('sorry')

    expect(store.messages[0].delivery_status).toBe('failed')
  })
})
```

- [ ] **Step 2: Run and watch fail**

```bash
cd frontend && npx vitest run test/inbox-store.spec.ts
```

- [ ] **Step 3: Write `frontend/types/inbox.ts`** mirroring `app/api/schemas.py` exactly — `ConversationSummary`, `ConversationDetail`, `SendPolicy`, `MessageOut`, `Page<T>`, `Filters`.

- [ ] **Step 4: Write `frontend/stores/inbox.ts`.** Two details the tests above pin down and which are easy to get wrong:
  - `applyMessageCreated` is idempotent on `message.id`, because the sender receives its own event back.
  - `applyConversationUpdated` removes a row the active filter no longer matches, rather than leaving a stale one that disappears only on the next fetch.

- [ ] **Step 5: Run and commit**

```bash
cd frontend && npx vitest run
git add frontend/types/inbox.ts frontend/stores/inbox.ts frontend/test/inbox-store.spec.ts
git commit -m "feat: inbox store with idempotent, filter-aware realtime reducers"
```

---

### Task 2: The realtime composable

**Files:**
- Create: `frontend/composables/useRealtime.ts`
- Test: `frontend/test/realtime.spec.ts`

**Interfaces:**
- Produces: `useRealtime()` → `{ connect(), disconnect(), connected: Ref<boolean> }`, and `backoffFor(attempt: number): number`.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from 'vitest'
import { backoffFor, MAX_BACKOFF_MS } from '../composables/useRealtime'

describe('reconnect backoff', () => {
  it('retries quickly the first time', () => {
    expect(backoffFor(0)).toBeLessThanOrEqual(1000)
  })

  it('grows exponentially', () => {
    expect(backoffFor(3)).toBeGreaterThan(backoffFor(1))
  })

  it('never exceeds thirty seconds', () => {
    // A tab left open overnight must not end up retrying once an hour.
    expect(backoffFor(50)).toBe(MAX_BACKOFF_MS)
    expect(MAX_BACKOFF_MS).toBe(30_000)
  })
})
```

- [ ] **Step 2: Implement.** The socket opens at `` `${location.origin.replace(/^http/, 'ws')}/api/ws` `` — same origin, so the session cookie rides the handshake and no token ever enters a query string. On `close`, schedule `backoffFor(attempt)`. On `open`, reset the attempt counter **and refetch the visible page**, rather than trusting that no event was missed while disconnected. Also refetch on `window` `focus`.

- [ ] **Step 3: Run and commit**

```bash
cd frontend && npx vitest run
git add frontend/composables/useRealtime.ts frontend/test/realtime.spec.ts
git commit -m "feat: websocket lifecycle with capped backoff and refetch on resume"
```

---

### Task 3: The composer's logic

**Files:**
- Create: `frontend/composables/useComposer.ts`
- Test: `frontend/test/composer.spec.ts`

**Interfaces:**
- Produces: `chunkBoundaries(text: string, limit: number): number[]` — the indices at which the dispatcher will split, mirroring `chunk_text` in `app/dispatch/dispatcher.py` (newline first, then space, then a hard cut) — and `useComposer(policy: Ref<SendPolicy | null>)` → `{ text, disabled, disabledReason, remaining, boundaries, overLimit }`.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from 'vitest'
import { chunkBoundaries } from '../composables/useComposer'

describe('where the dispatcher will split', () => {
  it('does not split text that fits', () => {
    expect(chunkBoundaries('short', 4096)).toEqual([])
  })

  it('prefers a newline', () => {
    expect(chunkBoundaries('abc\ndefgh', 6)).toEqual([3])
  })

  it('falls back to a space', () => {
    expect(chunkBoundaries('abcde fghij', 8)).toEqual([5])
  })

  it('cuts hard when there is nowhere better', () => {
    expect(chunkBoundaries('abcdefghij', 4)).toEqual([4, 8])
  })
})
```

- [ ] **Step 2: Implement `chunkBoundaries`** as the mirror of the server's `chunk_text`, and `useComposer` exposing:
  - `disabled` — true when `policy.can_send_freeform` is false, with `disabledReason` set to `policy.reason` so the box is disabled **with the explanation shown**, not silently;
  - `remaining` — `max_text_len` minus the current length, live;
  - `boundaries` — rendered as a marker in the textarea gutter, because the dispatcher will split there and the agent should know where.

- [ ] **Step 3: Run and commit**

```bash
cd frontend && npx vitest run
git add frontend/composables/useComposer.ts frontend/test/composer.spec.ts
git commit -m "feat: composer send-policy state and a client mirror of the chunk rule"
```

---

### Task 4: The inbox screen

**Files:**
- Create: `frontend/components/inbox/FilterRail.vue`, `ConversationList.vue`, `MessageThread.vue`, `EscalationBanner.vue`, `Composer.vue`
- Create: `frontend/pages/app/inbox/[[id]].vue`

Three panes: filter rail, conversation list, thread with composer. Filters map exactly to the `GET /conversations` query parameters, with counts per state.

- [ ] **Step 1: `FilterRail.vue`** — state, assignee (`me` / `unassigned`), provider, unread. Each control writes `store.filters` and triggers a refetch; nothing filters client-side, so the counts and the list cannot disagree.

- [ ] **Step 2: `ConversationList.vue`** — one row per conversation: customer name, `StatusDot` in the channel hue, preview, relative timestamp, an unread mark, and a failed-delivery mark driven by `has_failed_delivery`. Infinite scroll via `next_cursor`.

- [ ] **Step 3: `MessageThread.vue`** — three visually distinct message kinds. A bot reply carries an explicit "Bot" label; an agent reply carries the sender's name. A message with `delivery_status = 'failed'` renders inline with its `error` and a Retry button that calls `store.send(message.text)` — producing a new row, never mutating the failed one.

- [ ] **Step 4: `EscalationBanner.vue`** — shown when `handoff_state === 'pending_human'`, carrying `escalation_reason` and the Take over button. On 409, an inline notice naming the current assignee and a list refetch.

- [ ] **Step 5: `Composer.vue`** — `useComposer`, the live counter, the chunk markers, and the disabled state with its reason. On a 409 the text stays in the box.

- [ ] **Step 6: `pages/app/inbox/[[id]].vue`** — list and thread in one route. Opening a conversation calls `openConversation(id)` and `markRead(id)`; `useRealtime().connect()` on mount, `disconnect()` on unmount.

- [ ] **Step 7: Check by hand** against a running backend: open a `pending_human` conversation, read the reason, take over, send, watch the message land, and confirm a second browser sees it without a refresh.

- [ ] **Step 8: Commit**

```bash
git add frontend/components/inbox frontend/pages/app/inbox
git commit -m "feat: the three-pane inbox with escalation reason, failure retry and a policy-aware composer"
```

---

### Task 5: Bots and channels

**Files:**
- Create: `frontend/pages/app/bots/index.vue`, `frontend/pages/app/bots/[id].vue`, `frontend/pages/app/channels/index.vue`

- [ ] **Step 1: Bots.** Persona (textarea), `llm_provider`, `enabled_tools` (toggles), and `escalation_max_bot_turns` **with its meaning spelled out**: how many times the bot may answer an unresolved question before a person takes over. A number field with no explanation is a number nobody will change on purpose.

- [ ] **Step 2: Channels.** One card per connection: provider, `external_ref`, status, and the capability summary from the manifest — real limits, not hardcoded ones. `degraded` is surfaced loudly **with its meaning**: the connection still shows history, sends are expected to fail until credentials are repaired. That is the state a merchant must act on and the one most easily missed.

- [ ] **Step 3: A note on the page** that connections are created by seeding, not here — so the absence of an "Add channel" button reads as a decision rather than a missing feature.

- [ ] **Step 4: Commit**

```bash
git add frontend/pages/app/bots frontend/pages/app/channels
git commit -m "feat: bot settings and the channels screen with real capability limits"
```

---

### Task 6: The Playwright smoke

One path, end to end: login → inbox → open a conversation → take over → send → see the message. The reference project has no frontend tests; this is the amount that pays for itself.

**Files:**
- Create: `frontend/playwright.config.ts`, `frontend/e2e/inbox.spec.ts`, `scripts/seed_demo_inbox.py`

- [ ] **Step 1: Write `scripts/seed_demo_inbox.py`** — a merchant, an agent with a known password, a bot, a `fake`-provider connection, and one `pending_human` conversation with an escalation reason and a few messages. It reuses `_get_or_create` from `scripts/seed_telegram.py`'s pattern so it is safe to re-run.

- [ ] **Step 2: Write the spec**

```ts
import { expect, test } from '@playwright/test'

test('an agent takes over a conversation and replies', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Email').fill('demo@example.com')
  await page.getByLabel('Password').fill('s3cret-passphrase')
  await page.getByRole('button', { name: 'Sign in' }).click()

  await expect(page).toHaveURL(/\/app\/inbox/)

  await page.getByRole('listitem').first().click()
  await expect(page.getByText('the customer asked for a person')).toBeVisible()

  await page.getByRole('button', { name: 'Take over' }).click()
  await page.getByRole('textbox', { name: 'Reply' }).fill('checking that for you now')
  await page.getByRole('button', { name: 'Send' }).click()

  await expect(page.getByText('checking that for you now')).toBeVisible()
})
```

- [ ] **Step 3: Run it** against a live backend and dev server, then commit.

```bash
cd frontend && npx playwright test
git add frontend/playwright.config.ts frontend/e2e scripts/seed_demo_inbox.py
git commit -m "test: playwright smoke over login, takeover and send"
```

---

### Task 7: Phase 3 verification

- [ ] **Step 1: Everything green**

```bash
.venv/bin/python -m pytest -q
cd frontend && npx vitest run && npx nuxi build
```

- [ ] **Step 2: Walk spec §13's error table by hand** — 401 redirect with a return path, 409 on takeover, 409 on send keeping the text, a 201 failed message with retry, a WebSocket drop and resume, WebGL absent, API unreachable.

- [ ] **Step 3: Commit any fixes and record the result.**
