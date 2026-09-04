from app.channels import ChannelAdapter, OutboundMessage
from app.channels.fake import SIGNATURE_HEADER, FakeAdapter
from app.models.channel_connection import ChannelConnection


def _conn(conn_id: int = 1) -> ChannelConnection:
    # Constructed in memory, never persisted: adapters must not need a session.
    return ChannelConnection(
        id=conn_id, bot_id=1, provider="fake", external_ref="fake-endpoint"
    )


def _payload():
    return {
        "updates": [
            {
                "update_id": "u-1",
                "thread": "t-1",
                "from": "c-1",
                "message_id": "m-1",
                "text": "where is my order",
                "ts": 1788609600,
            }
        ]
    }


def test_the_fake_satisfies_the_protocol():
    assert isinstance(FakeAdapter(), ChannelAdapter)


def test_a_correct_signature_verifies():
    a = FakeAdapter()
    body = b'{"updates":[]}'
    assert a.verify_webhook({SIGNATURE_HEADER: a.sign(body)}, body) is True


def test_a_tampered_body_fails_verification():
    a = FakeAdapter()
    sig = a.sign(b'{"updates":[]}')
    assert a.verify_webhook({SIGNATURE_HEADER: sig}, b'{"updates":[1]}') is False


def test_a_missing_signature_header_fails_verification():
    a = FakeAdapter()
    assert a.verify_webhook({}, b"anything") is False


def test_a_foreign_secret_fails_verification():
    body = b'{"updates":[]}'
    forged = FakeAdapter(secret=b"not-the-secret").sign(body)
    assert FakeAdapter().verify_webhook({SIGNATURE_HEADER: forged}, body) is False


def test_parse_inbound_normalises_one_update():
    env = FakeAdapter().parse_inbound(_payload())[0]
    assert env.provider == "fake"
    assert env.external_thread_id == "t-1"
    assert env.provider_update_id == "u-1"
    assert env.sender_ref == "c-1"
    assert env.text == "where is my order"
    assert env.sent_at.tzinfo is not None


def test_parse_inbound_returns_empty_for_a_non_message_delivery():
    assert FakeAdapter().parse_inbound({"updates": []}) == []


async def test_send_records_the_message_and_reports_success():
    a = FakeAdapter()
    result = await a.send(_conn(), OutboundMessage(text="on its way"))
    assert result.ok is True
    assert result.provider_message_id is not None
    assert a.sent == [(1, OutboundMessage(text="on its way"))]


async def test_a_scripted_failure_is_reported_not_raised():
    a = FakeAdapter()
    a.fail_next_send = "rate limited"
    result = await a.send(_conn(), OutboundMessage(text="hi"))
    assert result.ok is False
    assert result.error == "rate limited"
    assert result.retryable is True
    # The failure is consumed, so the next send succeeds.
    assert (await a.send(_conn(), OutboundMessage(text="hi"))).ok is True


async def test_connect_and_disconnect_are_idempotent():
    a, conn = FakeAdapter(), _conn()
    await a.connect(conn)
    await a.connect(conn)
    assert a.connected == {1}
    await a.disconnect(conn)
    await a.disconnect(conn)
    assert a.connected == set()


from test.conformance import ChannelAdapterConformance  # noqa: E402


class TestFakeAdapterConformance(ChannelAdapterConformance):
    def make_adapter(self):
        return FakeAdapter()

    def make_connection(self):
        return _conn()

    def make_signed_webhook(self):
        adapter = FakeAdapter()
        body = b'{"updates":[]}'
        return {SIGNATURE_HEADER: adapter.sign(body)}, body

    def make_inbound_payload(self):
        return _payload()
