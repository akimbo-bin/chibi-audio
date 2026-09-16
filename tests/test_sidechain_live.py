from chibi_audio.live import READ_ONLY_METHODS, LiveBridgeClient


class FakeClient(LiveBridgeClient):
    def __init__(self):
        super().__init__()
        self.calls = []

    def _request(self, method, params=None):
        self.calls.append((method, params or {}))
        return {"method": method, "params": params or {}}


def test_sidechain_graph_is_read_only_and_has_bounded_typed_client():
    assert "sidechain_graph" in READ_ONLY_METHODS
    client = FakeClient()
    result = client.sidechain_graph(
        track_limit=88,
        max_devices=1234,
        max_depth=9,
        include_return_tracks=False,
        include_master_track=True,
    )
    assert result["method"] == "sidechain_graph"
    assert client.calls[-1] == (
        "sidechain_graph",
        {
            "track_limit": 88,
            "max_devices": 1234,
            "max_depth": 9,
            "include_return_tracks": False,
            "include_master_track": True,
        },
    )
