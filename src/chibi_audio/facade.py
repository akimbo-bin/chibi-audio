from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .audio import analyze_audio
from .control import (
    build_audition_plan,
    diff_parameter_snapshots,
    parameter_snapshot,
    snapshot_track_controls,
)
from .harshness import analyze_harshness
from .live import LiveBridgeClient, LivePilotWriteClient


class FacadeError(RuntimeError):
    """Raised when a model-facing facade request cannot be satisfied safely."""


_TRACK_IDENTITY_PROPERTIES = {
    "track_index": {"type": "integer", "minimum": 0},
    "expected_track_name": {"type": "string", "minLength": 1},
    "expected_track_id": {"type": "integer"},
    "expected_set_signature": {"type": "string", "minLength": 1},
}

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "status": {
        "description": "Read Chibi Audio bridge health and explicit capability classes.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "project_snapshot": {
        "description": "Read a structured snapshot of the currently open Live Set.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "track_limit": {"type": "integer", "minimum": 1, "maximum": 1000},
                "device_limit": {"type": "integer", "minimum": 0, "maximum": 256},
            },
            "additionalProperties": False,
        },
    },
    "device_parameters": {
        "description": "Read exposed parameters for one freshly resolved Live device object id.",
        "inputSchema": {
            "type": "object",
            "required": ["device_id"],
            "properties": {
                "device_id": {"type": "integer"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 4096},
            },
            "additionalProperties": False,
        },
    },
    "track_mixer_state": {
        "description": "Read exact volume and panning parameter state for one track index.",
        "inputSchema": {
            "type": "object",
            "required": ["track_index"],
            "properties": {"track_index": {"type": "integer", "minimum": 0}},
            "additionalProperties": False,
        },
    },
    "plan_audition": {
        "description": "Build a reversible mute/solo audition plan from a fresh Set snapshot without executing it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "solo_track_indices": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0},
                    "uniqueItems": True,
                },
                "mute_track_indices": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0},
                    "uniqueItems": True,
                },
            },
            "additionalProperties": False,
        },
    },
    "parameter_snapshot": {
        "description": "Capture a compact exact device-parameter snapshot for experiment provenance.",
        "inputSchema": {
            "type": "object",
            "required": ["track_index", "track_name", "device_index", "device_name", "device_id"],
            "properties": {
                "track_index": {"type": "integer", "minimum": 0},
                "track_name": {"type": "string", "minLength": 1},
                "device_index": {"type": "integer", "minimum": 0},
                "device_name": {"type": "string", "minLength": 1},
                "device_id": {"type": "integer"},
                "set_signature": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 4096},
            },
            "additionalProperties": False,
        },
    },
    "diff_parameter_snapshots": {
        "description": "Diff two exact parameter snapshots and return only changed parameters.",
        "inputSchema": {
            "type": "object",
            "required": ["before", "after"],
            "properties": {
                "before": {"type": "object"},
                "after": {"type": "object"},
            },
            "additionalProperties": False,
        },
    },
    "analyze_artifact": {
        "description": "Run deterministic audio measurements on a file below the configured artifact root.",
        "inputSchema": {
            "type": "object",
            "required": ["artifact"],
            "properties": {
                "artifact": {"type": "string", "minLength": 1},
                "window_seconds": {"type": "number", "exclusiveMinimum": 0},
            },
            "additionalProperties": False,
        },
    },
    "analyze_harshness_artifact": {
        "description": "Rank time-localized bright/attack-heavy events in an artifact; evidence only, not a quality score.",
        "inputSchema": {
            "type": "object",
            "required": ["artifact"],
            "properties": {
                "artifact": {"type": "string", "minLength": 1},
                "top_events": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "additionalProperties": False,
        },
    },
    "set_track_volume": {
        "description": "Set one exact track volume with identity and expected-before-state guards.",
        "inputSchema": {
            "type": "object",
            "required": ["track_index", "expected_track_name", "expected_current_value", "value"],
            "properties": {
                **_TRACK_IDENTITY_PROPERTIES,
                "expected_current_value": {"type": "number"},
                "value": {"type": "number"},
            },
            "additionalProperties": False,
        },
    },
    "set_track_pan": {
        "description": "Set one exact track pan with identity and expected-before-state guards.",
        "inputSchema": {
            "type": "object",
            "required": ["track_index", "expected_track_name", "expected_current_value", "value"],
            "properties": {
                **_TRACK_IDENTITY_PROPERTIES,
                "expected_current_value": {"type": "number"},
                "value": {"type": "number"},
            },
            "additionalProperties": False,
        },
    },
    "set_track_property": {
        "description": "Set one exact mute/solo/name/color_index property with identity and before-state guards.",
        "inputSchema": {
            "type": "object",
            "required": ["track_index", "expected_track_name", "property", "expected_current_value", "value"],
            "properties": {
                **_TRACK_IDENTITY_PROPERTIES,
                "property": {"enum": ["mute", "solo", "name", "color_index"]},
                "expected_current_value": {},
                "value": {},
            },
            "additionalProperties": False,
        },
    },
    "set_device_parameter": {
        "description": "Set one exact exposed device parameter with track/device/parameter identity and before-state guards.",
        "inputSchema": {
            "type": "object",
            "required": [
                "track_index",
                "expected_track_name",
                "device_index",
                "expected_device_name",
                "parameter_index",
                "expected_parameter_name",
                "expected_current_value",
                "value",
            ],
            "properties": {
                **_TRACK_IDENTITY_PROPERTIES,
                "device_index": {"type": "integer", "minimum": 0},
                "expected_device_name": {"type": "string", "minLength": 1},
                "expected_device_id": {"type": "integer"},
                "parameter_index": {"type": "integer", "minimum": 0},
                "expected_parameter_name": {"type": "string", "minLength": 1},
                "expected_parameter_id": {"type": "integer"},
                "expected_current_value": {"type": "number"},
                "value": {"type": "number"},
                "coerce": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    },
    "set_device_enabled": {
        "description": "Toggle an exact host-exposed device on/off parameter with identity and before-state guards.",
        "inputSchema": {
            "type": "object",
            "required": [
                "enabled",
                "track_index",
                "expected_track_name",
                "device_index",
                "expected_device_name",
                "parameter_index",
                "expected_parameter_name",
                "expected_current_value",
            ],
            "properties": {
                **_TRACK_IDENTITY_PROPERTIES,
                "enabled": {"type": "boolean"},
                "device_index": {"type": "integer", "minimum": 0},
                "expected_device_name": {"type": "string", "minLength": 1},
                "expected_device_id": {"type": "integer"},
                "parameter_index": {"type": "integer", "minimum": 0},
                "expected_parameter_name": {"type": "string", "minLength": 1},
                "expected_parameter_id": {"type": "integer"},
                "expected_current_value": {"type": "number"},
            },
            "additionalProperties": False,
        },
    },
}

TOOL_NAMES = tuple(TOOL_SCHEMAS)


@dataclass(slots=True)
class ChibiAudioFacade:
    """Transport-agnostic model-facing boundary for a secure MCP/connector server."""

    read: LiveBridgeClient
    write: LivePilotWriteClient
    artifact_root: Path | None = None

    @classmethod
    def local(
        cls,
        host: str = "127.0.0.1",
        port: int = 18765,
        *,
        artifact_root: str | Path | None = None,
    ) -> "ChibiAudioFacade":
        return cls(
            LiveBridgeClient(host=host, port=port),
            LivePilotWriteClient(host=host, port=port),
            Path(artifact_root).resolve() if artifact_root is not None else None,
        )

    def tool_names(self) -> tuple[str, ...]:
        return TOOL_NAMES

    def tools(self) -> list[dict[str, Any]]:
        return [
            {"name": name, **schema}
            for name, schema in TOOL_SCHEMAS.items()
        ]

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
            "plan_audition": self._plan_audition,
            "parameter_snapshot": self._parameter_snapshot,
            "diff_parameter_snapshots": lambda a: diff_parameter_snapshots(a["before"], a["after"]),
            "analyze_artifact": lambda a: analyze_audio(
                self._resolve_artifact(a["artifact"]),
                window_seconds=float(a.get("window_seconds", 12.0)),
            ),
            "analyze_harshness_artifact": lambda a: analyze_harshness(
                self._resolve_artifact(a["artifact"]),
                top_events=int(a.get("top_events", 12)),
            ),
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

    def _plan_audition(self, args: dict[str, Any]) -> dict[str, Any]:
        summary = self.read.set_summary(track_limit=1000, device_limit=0)
        snapshot = snapshot_track_controls(summary)
        return build_audition_plan(
            snapshot,
            solo_track_indices=args.get("solo_track_indices", ()),
            mute_track_indices=args.get("mute_track_indices", ()),
        )

    def _parameter_snapshot(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = self.read.call(
            "device_parameters",
            {
                "ref": {"id": int(args["device_id"])},
                "limit": int(args.get("limit", 256)),
            },
        )
        if isinstance(payload, dict):
            parameters = payload.get("parameters") or payload.get("items") or []
        elif isinstance(payload, list):
            parameters = payload
        else:
            raise FacadeError("device_parameters returned an unsupported payload")
        return parameter_snapshot(
            track_index=int(args["track_index"]),
            track_name=str(args["track_name"]),
            device_index=int(args["device_index"]),
            device_name=str(args["device_name"]),
            device_id=int(args["device_id"]),
            parameters=list(parameters),
            set_signature=args.get("set_signature"),
        )

    def _resolve_artifact(self, artifact: str) -> Path:
        if self.artifact_root is None:
            raise FacadeError("artifact analysis is unavailable because artifact_root is not configured")
        relative = Path(artifact)
        if relative.is_absolute():
            raise FacadeError("artifact must be relative to the configured artifact root")
        root = self.artifact_root.resolve()
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise FacadeError("artifact path escapes the configured artifact root") from exc
        if not candidate.is_file():
            raise FacadeError(f"artifact does not exist: {artifact}")
        return candidate
