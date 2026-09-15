from __future__ import annotations
import json
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any
READ_ONLY_METHODS = frozenset(
    {
        "bridge_status",
        "ping",
        "set_summary",
        "get",
        "children",
        "device_parameters",
        "clip_notes",
        "clip_warp_markers",
        "browser_capabilities",
        "browser_roots",
        "browser_search",
    }
)
CAPTURE_METHODS = frozenset({"agent_audio_tap", "capture_probe_setup", "capture_probe_refresh", "capture_transport"})
BOUNDED_WRITE_METHODS = frozenset({"parameter_set"})
class LiveBridgeError(RuntimeError):
    """Raised when the local Live bridge cannot safely satisfy a request."""
@dataclass(slots=True)
class _LiveTransport:
    host: str = "127.0.0.1"
    port: int = 18765
    timeout: float = 10.0
    max_response_bytes: int = 8 * 1024 * 1024
    def _request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {},
        }
        payload = (json.dumps(request, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as client:
                client.settimeout(self.timeout)
                client.sendall(payload)
                raw = self._read_line(client)
        except OSError as exc:
            raise LiveBridgeError(
                f"Unable to reach the Chibi Audio Live bridge at {self.host}:{self.port}: {exc}"
            ) from exc
        if not raw:
            raise LiveBridgeError("Live bridge closed the connection without a response")
        try:
            response = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LiveBridgeError("Live bridge returned an invalid JSON response") from exc
        if response.get("error"):
            error = response["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise LiveBridgeError(f"Live bridge error: {message}")
        if "result" not in response:
            raise LiveBridgeError("Live bridge response did not contain a result")
        return response["result"]
    def _read_line(self, client: socket.socket) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > self.max_response_bytes:
                raise LiveBridgeError(
                    f"Live bridge response exceeded {self.max_response_bytes} bytes"
                )
            if b"\n" in chunk:
                before, _sep, _after = chunk.partition(b"\n")
                chunks.append(before)
                break
            chunks.append(chunk)
        return b"".join(chunks)
    def status(self) -> dict[str, Any]:
        return self._request("bridge_status")
    def _require_method(self, capability: str, method: str) -> dict[str, Any]:
        status = self.status()
        advertised = status.get("capabilities", {}).get(capability, [])
        if method not in advertised:
            raise LiveBridgeError(
                f"Live bridge does not advertise {capability} capability for method: {method}"
            )
        return status
@dataclass(slots=True)
class LiveBridgeClient(_LiveTransport):
    """Read-only model-facing Live client."""
    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if method not in READ_ONLY_METHODS:
            raise LiveBridgeError(f"Method is not available through the read-only client: {method}")
        return self._request(method, params)
    def status(self) -> dict[str, Any]:
        return self.call("bridge_status")
    def set_summary(
        self,
        *,
        track_limit: int = 140,
        device_limit: int = 24,
        clip_slot_limit: int = 0,
        arrangement_clip_limit: int = 0,
        include_return_tracks: bool = True,
        include_master_track: bool = True,
    ) -> dict[str, Any]:
        return self.call(
            "set_summary",
            {
                "track_limit": track_limit,
                "device_limit": device_limit,
                "clip_slot_limit": clip_slot_limit,
                "arrangement_clip_limit": arrangement_clip_limit,
                "include_return_tracks": include_return_tracks,
                "include_master_track": include_master_track,
            },
        )
@dataclass(slots=True)
class LiveCaptureClient(_LiveTransport):
    """Opt-in bounded capture control for probe setup and playback."""
    def capture(
        self,
        command: str,
        *,
        path: str | Path | None = None,
        command_id: str | None = None,
        udp: bool = False,
        tap_port: int | None = None,
        verify_capability: bool = True,
    ) -> dict[str, Any]:
        if command not in {"open", "start", "stop", "status"}:
            raise LiveBridgeError("capture command must be open, start, stop, or status")
        if command == "open" and path is None:
            raise LiveBridgeError("open capture command requires an output path")
        if verify_capability:
            self._require_method("capture", "agent_audio_tap")
        params: dict[str, Any] = {"command": command, "udp": bool(udp)}
        if path is not None:
            params["path"] = str(Path(path))
        if command_id is not None:
            params["command_id"] = command_id
        if tap_port is not None:
            params["port"] = int(tap_port)
        return self._request("agent_audio_tap", params)
    def setup_probe(
        self,
        *,
        expected_set_signature: str | None = None,
        verify_capability: bool = True,
    ) -> dict[str, Any]:
        if verify_capability:
            self._require_method("capture", "capture_probe_setup")
        params: dict[str, Any] = {"placement": "master"}
        if expected_set_signature:
            params["expected_set_signature"] = expected_set_signature
        return self._request("capture_probe_setup", params)

    def refresh_probe(
        self,
        *,
        expected_set_signature: str | None = None,
        verify_capability: bool = True,
    ) -> dict[str, Any]:
        if verify_capability:
            self._require_method("capture", "capture_probe_refresh")
        params: dict[str, Any] = {}
        if expected_set_signature:
            params["expected_set_signature"] = expected_set_signature
        return self._request("capture_probe_refresh", params)


    def transport(
        self,
        action: str = "status",
        *,
        time: float | None = None,
        expected_set_signature: str | None = None,
        verify_capability: bool = True,
    ) -> dict[str, Any]:
        if action not in {"status", "seek", "play", "stop"}:
            raise LiveBridgeError("capture transport action must be status, seek, play, or stop")
        if action == "seek" and time is None:
            raise LiveBridgeError("seek requires time")
        if time is not None and float(time) < 0:
            raise LiveBridgeError("time must be >= 0")
        if verify_capability:
            self._require_method("capture", "capture_transport")
        params: dict[str, Any] = {"action": action}
        if time is not None:
            params["time"] = float(time)
        if expected_set_signature:
            params["expected_set_signature"] = expected_set_signature
        return self._request("capture_transport", params)

@dataclass(slots=True)
class LivePilotWriteClient(_LiveTransport):
    """Narrow pilot mutations only; currently exact track-volume writes."""
    def set_track_volume(
        self,
        *,
        track_index: int,
        expected_track_name: str,
        expected_current_value: float,
        value: float,
        verify_capability: bool = True,
    ) -> dict[str, Any]:
        if track_index < 0:
            raise LiveBridgeError("track_index must be >= 0")
        if not expected_track_name:
            raise LiveBridgeError("expected_track_name is required")
        if verify_capability:
            self._require_method("bounded_write", "parameter_set")
        return self._request(
            "parameter_set",
            {
                "ref": {"path": f"song tracks {track_index} mixer_device volume"},
                "expected_track_name": expected_track_name,
                "expected_current_value": float(expected_current_value),
                "value": float(value),
            },
        )
