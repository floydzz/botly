from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from app.api.deps import TenantScope, tenant
from app.channels.management import channel_api
from app.channels.telegram.api import FakeTelegramApi, TelegramApiResponse
from app.core.config import settings
from app.core.database import get_db
from app.llm.billing import top_up
from app.main import app
from app.models.billing import LlmUsage
from app.models.channel_connection import ChannelConnection
from app.models.user import User
from test.test_llm_billing import graph

pytestmark = pytest.mark.integration


@pytest.fixture
async def configured(db_session, monkeypatch):
    own = await graph(db_session)
    other = await graph(db_session)
    user = User(merchant_id=own[0].id, email="settings@test.example", name="Operator", password_hash="unused")
    db_session.add(user); await db_session.flush()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[tenant] = lambda: TenantScope(user)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("test-key"))
    monkeypatch.setattr(settings, "PUBLIC_WEBHOOK_BASE_URL", "https://hooks.example.test")
    yield own, other
    app.dependency_overrides.clear()


def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_bot_selection_is_tenant_scoped_and_prices_are_not_editable(db_session, configured):
    own, other = configured
    async with client() as api:
        listed = await api.get("/bots")
        assert [row["id"] for row in listed.json()] == [own[1].id]
        assert (await api.patch(f"/bots/{other[1].id}", json={"persona": "attack"})).status_code == 404
        assert (await api.post("/bots", json={"shop_id": other[1].shop_id, "name": "attack"})).status_code == 404
        assert (await api.patch(f"/bots/{own[1].id}", json={"multiplier": 0})).status_code == 422
        assert (await api.patch(f"/bots/{own[1].id}", json={"llm_model_id": own[2].id})).status_code == 200
        response = await api.patch(f"/bots/{own[1].id}", json={"persona": "Kind and concise"})
        assert response.json()["llm_model_id"] == own[2].id
        response = await api.patch(f"/bots/{own[1].id}", json={"llm_model_id": None})
        assert response.json()["llm_model_id"] is None
        assert (await api.patch(f"/bots/{own[1].id}", json={"persona": None})).status_code == 422


async def test_wallet_and_history_hide_other_merchants_and_provider_cost(db_session, configured):
    own, other = configured
    await top_up(db_session, own[0].id, Decimal(50), "mine", "private note")
    await top_up(db_session, other[0].id, Decimal(900), "theirs", "private note")
    for values in (own, other):
        merchant, bot, model, event = values
        db_session.add(LlmUsage(merchant_id=merchant.id, bot_id=bot.id, model_id=model.id, inbound_event_id=event.id, update_id="u1", pricing={"provider": "openai", "model_code": "test", "multiplier": "2"}, reserved_credits=Decimal(1), provider_cost_usd=Decimal(".1"), response_text="private response"))
    await db_session.flush()
    async with client() as api:
        assert Decimal((await api.get("/billing/wallet")).json()["balance"]) == 50
        entries = (await api.get("/billing/entries")).json()
        assert len(entries) == 1 and "note" not in entries[0]
        usage = (await api.get("/billing/usage")).json()
        assert len(usage) == 1 and usage[0]["bot_id"] == own[1].id
        assert not {"provider_cost_usd", "pricing", "response_text"}.intersection(usage[0])
        models = (await api.get("/models")).json()
        assert all("input_usd_per_million" not in row and "multiplier" not in row for row in models)
        assert (await api.post("/billing/top-up", json={"credits": 1000000})).status_code == 404


async def test_unavailable_model_cannot_be_selected(db_session, configured, monkeypatch):
    own, _ = configured
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr(""))
    async with client() as api:
        assert (await api.patch(f"/bots/{own[1].id}", json={"llm_model_id": own[2].id})).status_code == 422
    own[2].enabled = False
    await db_session.flush()
    async with client() as api:
        assert own[2].id not in [row["id"] for row in (await api.get("/models")).json()]


async def test_telegram_setup_encrypts_credentials_and_registers_secret(db_session, configured):
    own, _ = configured
    fake = FakeTelegramApi()
    fake.responses.append(TelegramApiResponse(ok=True, result={"id": 1234, "is_bot": True, "username": "sample_bot"}))
    app.dependency_overrides[channel_api] = lambda: fake
    async with client() as api:
        response = await api.post("/channels/telegram", json={"bot_id": own[1].id, "bot_token": "1234:secret-token"})
        assert response.status_code == 201, response.text
        assert response.json()["status"] == "active"
        assert "secret-token" not in response.text
        channel = await db_session.get(ChannelConnection, response.json()["id"])
        assert "secret-token" not in channel.credentials_encrypted
        assert channel.get_credentials()["bot_token"] == "1234:secret-token"
        method, payload = fake.calls[1][1:]
        assert method == "setWebhook"
        assert payload["url"] == f"https://hooks.example.test/webhooks/telegram/{channel.id}"
        assert payload["secret_token"] == channel.get_credentials()["secret_token"]
        assert "credentials_encrypted" not in (await api.get("/channels")).text


async def test_telegram_cannot_connect_to_another_merchants_bot(configured):
    _, other = configured
    fake = FakeTelegramApi()
    app.dependency_overrides[channel_api] = lambda: fake
    async with client() as api:
        response = await api.post("/channels/telegram", json={"bot_id": other[1].id, "bot_token": "1234:secret-token"})
    assert response.status_code == 404 and not fake.calls


async def test_telegram_cannot_steal_another_connection(db_session, configured):
    own, other = configured
    row = ChannelConnection(bot_id=other[1].id, provider="telegram", external_ref="1234")
    db_session.add(row); await db_session.flush()
    fake = FakeTelegramApi()
    fake.responses.append(TelegramApiResponse(ok=True, result={"id": 1234, "is_bot": True}))
    app.dependency_overrides[channel_api] = lambda: fake
    async with client() as api:
        response = await api.post("/channels/telegram", json={"bot_id": own[1].id, "bot_token": "1234:secret-token"})
    assert response.status_code == 409
    assert len(fake.calls) == 1


async def test_failed_webhook_registration_is_not_reported_active(db_session, configured):
    own, _ = configured
    fake = FakeTelegramApi()
    fake.responses.extend([TelegramApiResponse(ok=True, result={"id": 1234, "is_bot": True}), TelegramApiResponse(ok=False, error_code=400, description="invalid webhook")])
    app.dependency_overrides[channel_api] = lambda: fake
    async with client() as api:
        response = await api.post("/channels/telegram", json={"bot_id": own[1].id, "bot_token": "1234:secret-token"})
    assert response.status_code == 502
    channel = (await db_session.execute(select(ChannelConnection).where(ChannelConnection.provider == "telegram"))).scalar_one()
    assert channel.status == "degraded"
