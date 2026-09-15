from __future__ import annotations

import json
import socket
from dataclasses import dataclass
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


class LiveBridgeError(RuntimeError):
    """Raised when the local Live bridge cannot safely satisfy a request."""


@dataclass(slots=True)
class LiveBridgeClient:
    host: str = "127.0.0.1"
    port: int = 18765
    timeout: float = 10.0
    max_response_bytes: int = 8 * 1024 * 1024

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if method not in READ_ONLY_METHODS:
            raise LiveBridgeError(f"Method is not available through the read-only client: {method}")

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
