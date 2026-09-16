import pytest

from chibi_audio.live import LiveBridgeError
from chibi_audio.locator_client import LocatorBridgeClient


class FakeLocatorClient(LocatorBridgeClient):
    def __init__(self):
        super().__init__()
        self.calls = []

    def status(self):
        return {"capabilities": {"read": ["locators"]}}

    def _request(self, method, params=None):
        self.calls.append((method, params or {}))
        return {"locators": []}


def test_locator_client_requires_advertised_read_capability():
    client = FakeLocatorClient()
    result = client.locators(limit=32)
    assert result == {"locators": []}
    assert client.calls[-1] == ("locators", {"limit": 32})


def test_locator_client_rejects_invalid_limit_before_network():
    client = FakeLocatorClient()
    with pytest.raises(LiveBridgeError, match="between 1 and 4096"):
        client.locators(limit=0)
    assert client.calls == []


def test_locator_client_refuses_unadvertised_capability():
    client = FakeLocatorClient()
    client.status = lambda: {"capabilities": {"read": []}}
    with pytest.raises(LiveBridgeError, match="does not advertise"):
        client.locators()
