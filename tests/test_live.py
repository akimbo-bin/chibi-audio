import pytest
from chibi_audio.live import LiveBridgeClient, LiveBridgeError, READ_ONLY_METHODS


def test_read_only_surface_excludes_generic_mutation():
    assert "set" not in READ_ONLY_METHODS
    assert "call" not in READ_ONLY_METHODS
    assert "parameter_set" not in READ_ONLY_METHODS


def test_client_refuses_unknown_method_before_network():
    client = LiveBridgeClient(port=1)
    with pytest.raises(LiveBridgeError, match="read-only client"):
        client.call("set", {"property": "mute", "value": True})
