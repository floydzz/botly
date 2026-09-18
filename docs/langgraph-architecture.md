# LangGraph manager architecture

Each model-backed customer message creates one LangGraph manager turn. The
manager is the only component that produces a customer-facing answer. It may
route to multiple enabled workers, which return structured data and trace
events only.

```text
manager → Voice / OCR / RAG / Tools → manager response
```

`worker_definitions` contains Botly's code-owned catalog: `rag`, `ocr`,
`voice`, and `tools`. `bot_workers` is the per-bot join table with `enabled`
and worker-specific configuration. The bot API exposes these controls at
`GET /bots/{bot_id}/workers` and `PUT /bots/{bot_id}/workers/{worker_key}`.

The current worker nodes are safe placeholders. The manager can route to them
and record the decision, but RAG providers, OCR/voice model providers, and
customer API connectors are intentionally not invented by this foundation.
Those implementations replace the worker contract without changing the graph,
receiver, or conversation pipeline.

`tool_write_mode` is configured on each bot:

- `confirm_customer` is the default for write operations.
- `auto_execute` permits approved write operations once a customer connector
  is implemented.

Read operations require no confirmation. `pending_tool_actions` holds the
durable state needed to collect missing tool fields or await confirmation;
ordinary conversational follow-ups remain in message history.

Every turn creates one row in `llm_runs`. `llm_run_events` retains at most 20
events per run. The graph collects all trace events in memory, applies stable
priority scoring, keeps the most important 20, and stores them in chronological
order. Both tables use monthly PostgreSQL partitions. The runtime creates the
current and next monthly partition before a run, so a month boundary does not
interrupt customer conversations.
