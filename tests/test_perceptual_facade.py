from pathlib import Path
import pytest
from chibi_audio.mcp_server_perception import _resolve_artifact
def test_perceptual_artifacts_are_confined_to_configured_root(tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir()
    inside = root / "drop.wav"
    inside.write_bytes(b"fixture")
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"fixture")
    assert _resolve_artifact(root, "drop.wav") == inside.resolve()
    with pytest.raises(ValueError, match="relative"):
        _resolve_artifact(root, str(outside.resolve()))
    with pytest.raises(ValueError, match="escapes"):
        _resolve_artifact(root, "../outside.wav")
    with pytest.raises(ValueError, match="does not exist"):
        _resolve_artifact(root, "missing.wav")
