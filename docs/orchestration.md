# Telegram-first orchestration

All channels enter through `POST /webhooks/{provider}/{connection_id}`. The
route passes the raw delivery to `app.ingress.receiver.CentralReceiver`, which
is the shared receiver module:

```text
Telegram / future channel
  → verify with the connection's adapter
  → normalize into InboundEnvelope
  → persist receipts (connection + provider + update ID)
  → enqueue receipt IDs
  → lock receipt and select its matching message
  → resolve merchant, bot and conversation
  → check human handoff / mute
  → Brain → escalation policy → outbound dispatcher
  → original channel and incoming conversation
```

The adapter owns provider payloads, authentication and delivery. The shared
runtime owns conversation state, handoff and reply orchestration. Adding another
platform means implementing the adapter protocol and registering its factory;
it does not require another runtime. Conversations remain separate per connection
and external thread; cross-platform identity linking is not implemented.

## Current behavior

- Telegram text replies target the incoming chat, even when the connection has a
  different default chat configured.
- Duplicate IDs on different connections are independent. The database unique
  constraint is authoritative; webhook receipt processing no longer needs Redis
  dedupe availability. Redis still backs the Celery queue.
- Every actionable message in a batch has one receipt. Workers process only the
  matching update, not the entire batch again.
- Receipts are committed before publication. Queue failures return 503; redelivery
  retries unpublished receipts. `enqueued_at` records successful publication.
- A database row lock serializes workers handling the same receipt. Completed
  receipts are no-ops on redelivery.
- The brain remains `EchoBrain`; media-only input and handoff conditions escalate
  through the existing policy. No LLM or commerce integration is enabled.

## Run locally

Follow the README setup, including `poetry run alembic upgrade head`, then run the
API and Celery worker. With `TELEGRAM_BOT_TOKEN` set in the shell, the existing
seed script can register a bot against a public HTTPS origin:

```bash
poetry run python scripts/seed_telegram.py --webhook-url https://YOUR_PUBLIC_ORIGIN
```

The script appends the connection-specific webhook path. This registration is a
separate live operation; local tests use fake provider APIs and send no messages.

## Remaining reliability work

This foundation does not promise exactly-once external delivery. A process crash
after a provider accepts a send but before the database commits can cause a repeat
reply. Publication can also be repeated if a crash occurs before `enqueued_at` is
committed; the worker lock/status check handles completed events. Recovery of
unpublished receipts currently depends on provider redelivery, rather than a
scheduled database sweeper. Different receipts in the same conversation still
need ordering/serialization before increasing worker concurrency. Durable inbound
message checkpoints and a delivery outbox are the next reliability layer.
