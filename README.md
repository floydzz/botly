# botly

Multi-channel chatbot platform for Southeast Asian commerce sellers.

- Architecture: `docs/superpowers/specs/2026-09-02-botly-architecture-design.md`
- Plans: `docs/superpowers/plans/`

## Local setup

```bash
poetry install
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # -> CREDENTIALS_ENCRYPTION_KEY
docker compose up -d
docker compose exec -T postgres psql -U botly -d botly -c "CREATE DATABASE botly_test;"
poetry run alembic upgrade head
poetry run pytest
poetry run uvicorn app.main:app --reload
```

## Blocking external approvals

Shopee Open Platform partner registration and WhatsApp Business verification are
approval-gated and sit on the critical path. They are not engineering work and they
take weeks. **Neither has been started as of 2026-09-05, and the code is two build-order
steps ahead of them.** Status and application details: `docs/approvals.md`.
