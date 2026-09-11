# Merchant credits, models and Telegram

Botly has one prepaid credit wallet per merchant, shared by every shop and bot.
Botly pays the provider; merchants select an operator-published model and spend
credits. Provider API keys and Telegram bot tokens are separate credentials.

## Calculation

All catalog rates are USD per one million tokens. Input includes cache reads;
cache reads are subtracted before applying the normal input rate:

```text
provider cost USD = ((input - cached - cache writes) × input rate
                    + cached × cache read rate
                    + cache writes × cache write rate
                    + output × output rate) / 1,000,000
merchant credits = ceil_to_6_decimals(provider cost USD × model multiplier × credits per USD)
```

The default denomination is 1,000 credits per USD. Keep this constant once wallets
are funded; changing it changes the purchasing power of existing balances.
Each usage row snapshots the rates, multiplier and denomination. Updating the
catalog changes subsequent calls only. Decimal arithmetic preserves cost precision.

For an illustrative $0.003 provider cost and 2× multiplier, the merchant spends
6 credits. A 2× multiplier gives 50% gross margin on model cost, before hosting,
payment fees, taxes, support, free grants or other expenses. A 1.5× multiplier gives
33.33%, not 50%. Pick commercial multipliers based on total operating cost.

## Operator setup

1. Add provider keys to `.env`: `OPENAI_API_KEY`, `GEMINI_API_KEY`,
   `ANTHROPIC_API_KEY`, `QWEN_API_KEY`. Configure `QWEN_BASE_URL` using your
   Alibaba Cloud workspace and region. Leave unused keys blank.
2. Set `PUBLIC_WEBHOOK_BASE_URL` to the public HTTPS API origin, without `/api`
   unless your reverse proxy really serves `/api/webhooks/...`. Localhost cannot
   receive Telegram webhooks; use your deployment or an HTTPS tunnel.
3. Rebuild: `docker compose up -d --build`. API startup applies the migration;
   the worker waits for the API to be healthy. Existing merchant/bot data remains.
4. Prepare a JSON array of model configurations and import it with the command
   below. Add as many models per provider as needed. Use exact provider model IDs
   and prices from your account's region/usage tier, not subscription-plan prices.

This is an **illustrative configuration**, not a current provider price quote.
Replace its model ID and all rates before enabling it:

```json
[
  {
    "provider": "openai",
    "model_code": "replace-with-your-model-id",
    "name": "Customer support — standard",
    "enabled": false,
    "input_usd_per_million": "2.00",
    "output_usd_per_million": "8.00",
    "cached_usd_per_million": "0.50",
    "cache_write_usd_per_million": "2.50",
    "multiplier": "2.00",
    "max_input_tokens": 8192,
    "max_output_tokens": 1024
  }
]
```

```bash
# With a local Python environment:
python -m app.llm.admin models /absolute/path/model-catalog.json
python -m app.llm.admin top-up 1 10000 --reference payment-2026-001 --note 'Verified payment'

# Or mount the catalog into a one-off Docker container:
docker compose run --rm --no-deps -v /absolute/path/model-catalog.json:/tmp/models.json:ro api python -m app.llm.admin models /tmp/models.json
docker compose exec -T api python -m app.llm.admin top-up 1 10000 --reference payment-2026-001 --note 'Verified payment'
```

Top-ups require a positive amount, a unique merchant-scoped reference, and an
audit note. Repeating the same reference and amount is a no-op. This CLI records
an externally verified payment or authorized grant; it does not collect payment.
There is no merchant-accessible mint/top-up endpoint. Model imports upsert by
provider/model ID; set `enabled` to false to withdraw a model. No catalog or
credits are silently seeded into real merchant accounts.

## Merchant flow

- **Bots:** create a bot under an existing shop; edit its persona, choose an
  available model, and set the handoff threshold. Unconfigured bots hand off;
  the echo responder is now only an explicitly injected development/test brain.
- **Channels:** enter the BotFather token and choose a Botly bot. Setup verifies
  the token, encrypts it, registers a random webhook secret, and records the
  result. Reconnecting replaces the upstream webhook. Other merchants cannot
  claim an already-connected bot, even with its token.
- **Credits & usage:** inspect available/held credits and paginated usage.
  Provider costs, platform multipliers, request snapshots and raw responses are
  not exposed by merchant APIs.

API routes are `/shops`, `/bots`, `/bots/{id}`, `/models`, `/channels`,
`/channels/telegram`, `/billing/wallet`, `/billing/usage`, `/billing/entries`.
The frontend adds `/api` through its existing reverse proxy. All these routes
require the existing merchant session; bot/channel mutations follow the existing
merchant-wide permissions model. Owner/staff role separation is not yet present.

## Execution and recovery

The runtime atomically claims each event, stores the incoming message, and checks
handoff rules before spending credits. Conversation locks serialize generation
and delivery; a separate billing transaction commits the credit hold before the
provider call and settlement before sending the response. Dedupe is scoped to
connection/provider/update, and each reply is addressed to its incoming chat.

Reservations cover the model's configured input/output ceiling. This intentionally
requires more available credits than a typical short reply ultimately costs.
Final settlement releases unused reserved credits. Genuine generation usage is
charged even if the model hands off, returns no usable text, or channel delivery
later fails. Deterministic handoff rules and insufficient funds skip generation.

Provider HTTP rejection releases the hold. Transport errors, ambiguous server
errors and malformed usage keep it reserved as `uncertain`. Usage exceeding the
hold is recorded and held for review. Calls are never automatically retried or
silently moved to a different model. A worker crash can leave an event in
`processing` and a usage row `reserved`; a duplicate worker will not call again.
Monitor old processing events and reserved/uncertain usage, not only failed jobs.

```bash
docker compose exec -T api python -m app.llm.admin pending
# Stop any worker still handling this usage, then verify provider billing.
docker compose exec -T api python -m app.llm.admin reconcile 42 --no-charge --note 'Provider confirmed no charge; ticket ABC'
# To settle a verified charge, pass a JSON file with input_tokens, output_tokens,
# cached_tokens, cache_write_tokens; all counts must be nonnegative integers.
docker compose run --rm --no-deps -v /absolute/path/usage.json:/tmp/usage.json:ro api python -m app.llm.admin reconcile 42 --usage-json /tmp/usage.json --note 'Verified against provider request ID'
```

Reconciliation only adjusts billing. It does not resend a possibly delivered
message. Inspect the conversation and let an inbox agent answer if needed. If a
verified charge exceeds its original hold, reconciliation requires enough
unreserved funds; otherwise investigate the catalog/input limits and fund the
wallet explicitly. Never reset a processing event to pending merely to retry it.

Each usage has a request snapshot, provider/model identity, pricing snapshot,
raw usage, response text, status, error and request ID when available. Logs record
usage/merchant/model IDs and settlement amounts without customer text or keys.
Protect usage snapshots like conversation data and include them in your retention
policy. A disabled model or missing provider key causes handoff, not fallback.

## Current boundaries and API references

This release handles text support replies. Retrieval, verified commerce tools,
image/audio generation, tool charges, payment checkout, and automatic provider
invoice reconciliation are separate work. A system instruction requests handoff
for unavailable merchant facts; it is not an evidence validator or a guarantee
against hallucinations. Existing human/refund/turn-limit rules still apply.

The catalog currently uses flat text rates. Keep the configured input limit inside
the selected provider pricing tier. Do not publish a model requiring unsupported
modalities, special billing dimensions, or a different API contract. Smoke-test
each exact model with your provider account before publishing it.

- [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat):
  counts completion tokens once, including reasoning; separates cached input.
- [Gemini generateContent](https://ai.google.dev/api/generate-content) and
  [thinking limits](https://ai.google.dev/gemini-api/docs/generate-content/thinking?hl=en):
  accounts for thoughts plus candidate output; filters thought text from replies.
- [Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create):
  input usage adds cache reads. This release does not request explicit cache
  writes; unexpected writes require reconciliation rather than assuming a TTL rate.
- [Qwen OpenAI-compatible Chat](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-chat-completions):
  workspace/region base URL is operator-configured; this release requests
  non-thinking text mode.
- [Telegram Bot API](https://core.telegram.org/bots/api): uses `getMe`, `setWebhook`
  with a secret token, and `sendMessage` to the conversation's chat ID.

The migration adds accounting tables and a nullable bot model selection. It does
not seed balances or charge existing history. Downgrade deletes accounting tables
and may fail when separate connections now share provider update IDs; export
accounting data and plan rollback before downgrading.
