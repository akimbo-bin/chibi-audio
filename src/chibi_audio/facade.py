from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .live import LiveBridgeClient, LivePilotWriteClient

TOOL_NAMES = (
    "status",
    "project_snapshot",
    "device_parameters",
    "track_mixer_state",
    "set_track_volume",
    "set_track_pan",
    "set_track_property",
    "set_device_parameter",
    "set_device_enabled",
)


@dataclass(slots=True)
class ChibiAudioFacade:
    """Transport-agnostic tool facade intended to sit behind a secure MCP/connector."""

    read: LiveBridgeClient
    write: LivePilotWriteClient

    @classmethod
    def local(cls, host: str = "127.0.0.1", port: int = 18765) -> "ChibiAudioFacade":
        return cls(
            LiveBridgeClient(host=host, port=port),
            LivePilotWriteClient(host=host, port=port),
        )

    def tool_names(self) -> tuple[str, ...]:
        return TOOL_NAMES

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        args = arguments or {}
        handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            "status": lambda _a: self.read.status(),
            "project_snapshot": lambda a: self.read.set_summary(
                track_limit=int(a.get("track_limit", 140)),
                device_limit=int(a.get("device_limit", 24)),
            ),
            "device_parameters": lambda a: self.read.call(
                "device_parameters",
                {"ref": {"id": int(a["device_id"])}, "limit": int(a.get("limit", 256))},
            ),
            "track_mixer_state": self._track_mixer_state,
            "set_track_volume": lambda a: self.write.set_track_volume(**a),
            "set_track_pan": lambda a: self.write.set_track_pan(**a),
            "set_track_property": lambda a: self.write.set_track_property(**a),
            "set_device_parameter": lambda a: self.write.set_device_parameter(**a),
            "set_device_enabled": lambda a: self.write.set_device_enabled(**a),
        }
        if name not in handlers:
            raise KeyError(f"Unknown Chibi Audio facade tool: {name}")
        return handlers[name](args)

    def _track_mixer_state(self, args: dict[str, Any]) -> dict[str, Any]:
        index = int(args["track_index"])
        result: dict[str, Any] = {}
        for parameter in ("volume", "panning"):
            result[parameter] = self.read.call(
                "get",
                {
                    "ref": {"path": f"song tracks {index} mixer_device {parameter}"},
                    "properties": ["name", "value", "min", "max", "display_value"],
                },
            )
        return {"track_index": index, "mixer": result}
