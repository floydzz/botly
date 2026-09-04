from app.channels import ChannelAdapter, ChannelCapabilities

_CAPS = ChannelCapabilities(supports_media=False, max_text_len=100)


class _Complete:
    provider = "complete"
    capabilities = _CAPS

    def verify_webhook(self, headers, raw_body): ...
    def parse_inbound(self, payload): ...
    async def send(self, conn, out): ...
    async def connect(self, conn): ...
    async def disconnect(self, conn): ...


class _MissingDisconnect:
    provider = "partial"
    capabilities = _CAPS

    def verify_webhook(self, headers, raw_body): ...
    def parse_inbound(self, payload): ...
    async def send(self, conn, out): ...
    async def connect(self, conn): ...


class _MissingManifest:
    provider = "manifestless"

    def verify_webhook(self, headers, raw_body): ...
    def parse_inbound(self, payload): ...
    async def send(self, conn, out): ...
    async def connect(self, conn): ...
    async def disconnect(self, conn): ...


def test_a_complete_implementation_satisfies_the_protocol():
    assert isinstance(_Complete(), ChannelAdapter)


def test_a_missing_method_fails_the_protocol():
    assert not isinstance(_MissingDisconnect(), ChannelAdapter)


def test_a_missing_capability_manifest_fails_the_protocol():
    # Non-method members count: isinstance checks provider and capabilities
    # too, so an adapter cannot ship without declaring what it can do.
    assert not isinstance(_MissingManifest(), ChannelAdapter)


def test_the_protocol_checks_the_manifest_and_the_five_methods():
    assert sorted(ChannelAdapter.__protocol_attrs__) == [
        "capabilities",
        "connect",
        "disconnect",
        "parse_inbound",
        "provider",
        "send",
        "verify_webhook",
    ]


def test_the_protocol_is_exported_from_the_package_root():
    import app.channels as channels

    assert "ChannelAdapter" in channels.__all__
