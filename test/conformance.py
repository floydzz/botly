"""The contract every ChannelAdapter must satisfy.

Subclass it once per adapter. The point is that Telegram, WhatsApp and every
later channel are held to one definition of correct rather than to whatever
their own author remembered to test.

No pytest import: pytest.ini sets asyncio_mode = auto, so async methods here
need no marker, and plain asserts need no helper.
"""

from datetime import datetime, timedelta

from app.channels import (
    ChannelAdapter,
    ChannelCapabilities,
    InboundEnvelope,
    OutboundMessage,
    SendResult,
)
from app.models.channel_connection import ChannelConnection


class ChannelAdapterConformance:
    # --- hooks a subclass must provide -------------------------------------

    def make_adapter(self) -> ChannelAdapter:
        raise NotImplementedError

    def make_connection(self) -> ChannelConnection:
        raise NotImplementedError

    def make_signed_webhook(self) -> tuple[dict[str, str], bytes]:
        """Headers and raw body that this adapter should accept as authentic."""
        raise NotImplementedError

    def make_inbound_payload(self) -> dict:
        """A parsed delivery carrying exactly one customer message."""
        raise NotImplementedError

    # --- identity ----------------------------------------------------------

    def test_declares_a_non_empty_provider_name(self):
        provider = type(self.make_adapter()).provider
        assert isinstance(provider, str) and provider

    def test_provider_name_is_lowercase_and_column_safe(self):
        # It is stored in a String(32) column and used as a URL segment in
        # POST /webhooks/{provider}/{connection_id}.
        provider = type(self.make_adapter()).provider
        assert provider == provider.lower()
        assert len(provider) <= 32
        assert provider.isidentifier()

    def test_satisfies_the_protocol(self):
        assert isinstance(self.make_adapter(), ChannelAdapter)

    # --- capability manifest ------------------------------------------------

    def test_declares_a_capability_manifest(self):
        caps = type(self.make_adapter()).capabilities
        assert isinstance(caps, ChannelCapabilities)

    def test_manifest_allows_a_usable_message_length(self):
        assert type(self.make_adapter()).capabilities.max_text_len > 0

    def test_session_window_is_a_positive_duration_when_present(self):
        window = type(self.make_adapter()).capabilities.session_window
        assert window is None or window > timedelta(0)

    # --- webhook verification -----------------------------------------------

    def test_accepts_an_authentic_delivery(self):
        headers, body = self.make_signed_webhook()
        assert self.make_adapter().verify_webhook(headers, body) is True

    def test_rejects_a_tampered_body(self):
        headers, body = self.make_signed_webhook()
        assert self.make_adapter().verify_webhook(headers, body + b" ") is False

    def test_rejects_a_delivery_with_no_headers(self):
        _, body = self.make_signed_webhook()
        assert self.make_adapter().verify_webhook({}, body) is False

    # --- parsing ------------------------------------------------------------

    def test_parse_returns_envelopes_stamped_with_its_own_provider(self):
        adapter = self.make_adapter()
        envelopes = adapter.parse_inbound(self.make_inbound_payload())
        assert envelopes, "the sample payload must yield at least one envelope"
        for env in envelopes:
            assert isinstance(env, InboundEnvelope)
            assert env.provider == type(adapter).provider

    def test_parse_is_pure(self):
        # Ingress persists the raw payload and may parse it again on replay.
        # Parsing twice must not consume, mutate, or renumber anything.
        adapter = self.make_adapter()
        payload = self.make_inbound_payload()
        first = adapter.parse_inbound(payload)
        second = adapter.parse_inbound(payload)
        assert [e.provider_update_id for e in first] == [
            e.provider_update_id for e in second
        ]

    def test_dedupe_keys_are_stable_and_non_empty(self):
        for env in self.make_adapter().parse_inbound(self.make_inbound_payload()):
            assert env.provider_update_id

    def test_parsed_timestamps_are_timezone_aware(self):
        for env in self.make_adapter().parse_inbound(self.make_inbound_payload()):
            assert isinstance(env.sent_at, datetime)
            assert env.sent_at.utcoffset() is not None

    # --- sending ------------------------------------------------------------

    async def test_send_returns_a_result_rather_than_raising(self):
        result = await self.make_adapter().send(
            self.make_connection(), OutboundMessage(text="conformance probe")
        )
        assert isinstance(result, SendResult)

    async def test_a_successful_send_reports_a_provider_message_id(self):
        result = await self.make_adapter().send(
            self.make_connection(), OutboundMessage(text="conformance probe")
        )
        if result.ok:
            assert result.provider_message_id

    # --- lifecycle ----------------------------------------------------------

    async def test_connect_is_idempotent(self):
        adapter, conn = self.make_adapter(), self.make_connection()
        await adapter.connect(conn)
        await adapter.connect(conn)

    async def test_disconnect_is_idempotent_and_safe_before_connect(self):
        adapter, conn = self.make_adapter(), self.make_connection()
        await adapter.disconnect(conn)
        await adapter.disconnect(conn)
