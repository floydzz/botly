# botly

Multi-channel chatbot platform for Southeast Asian commerce sellers.

- Architecture: `docs/superpowers/specs/2026-09-02-botly-architecture-design.md`
- Plans: `docs/superpowers/plans/`
- Merchant credits, model pricing, provider keys and Telegram setup:
  [operator and merchant guide](docs/merchant-credits-and-models.md)

## Docker setup

Create the local environment file once and add a Fernet key:

```bash
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Paste that value into `CREDENTIALS_ENCRYPTION_KEY`, then start the complete stack:

```bash
docker compose up --build
```

The landing page is available at `http://localhost:3000`, FastAPI at
`http://localhost:8004`, PostgreSQL at port `5433`, and Redis at port `6380`.
The API container applies Alembic migrations before it starts; the frontend proxies
same-origin `/api/*` requests to FastAPI automatically.

For local development, Docker creates an idempotent demo account and login opens the
dashboard first:

```text
Email:    demo@botly.dev
Password: botly-demo
```

Override these before startup with `BOTLY_DEMO_EMAIL`, `BOTLY_DEMO_PASSWORD`,
`BOTLY_DEMO_NAME`, and `BOTLY_DEMO_MERCHANT`. The seed refuses to run unless
`ENVIRONMENT=development`.

Stop the stack with:

```bash
docker compose down
```

## Native development setup

```bash
poetry install
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # -> CREDENTIALS_ENCRYPTION_KEY
docker compose up -d postgres redis
docker compose exec -T postgres psql -U botly -d botly -c "CREATE DATABASE botly_test;"
poetry run alembic upgrade head
poetry run pytest
poetry run uvicorn app.main:app --reload
poetry run celery -A app.worker.celery_app.celery_app worker --loglevel=info
```

## Blocking external approvals

Shopee Open Platform partner registration and WhatsApp Business verification are
approval-gated and sit on the critical path. They are not engineering work and they
take weeks. **Neither has been started as of 2026-09-05, and the code is two build-order
steps ahead of them.** Status and application details: `docs/approvals.md`.
