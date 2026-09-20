from __future__ import annotations

import json

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
from .sidechain_compare import compare_sidechain_captures
from .sidechain_configure import configure_sidechain_targets
from .sidechain_intent import propose_sidechain_intents
from .sidechain_verify import verify_sidechain_capture
from .workflow_commands import (
    WorkflowCommandError,
    build_workflow_command,
    load_project_context,
)


class FacadeError(RuntimeError):
    """Raised when a model-facing facade request cannot be satisfied safely."""


_TRACK_IDENTITY_PROPERTIES = {
    "track_index": {"type": "integer", "minimum": 0},
    "expected_track_name": {"type": "string", "minLength": 1},
    "expected_track_id": {"type": "integer"},
    "expected_set_signature": {"type": "string", "minLength": 1},
}

_DEVICE_TARGET_PROPERTIES = {
    "placement": {"enum": ["track", "master"], "default": "track"},
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
    "plan_workflow": {
        "description": (
            "Build a stable organize/mix/sidechain/master workflow command from a persisted "
            "project-context artifact. Planning only: no Live reads or writes are performed."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["context_artifact", "intent", "project_ref", "workflow_id", "goal"],
            "properties": {
                "context_artifact": {"type": "string", "minLength": 1},
                "intent": {"enum": ["organize", "mix", "sidechain", "master"]},
                "project_ref": {"type": "string", "minLength": 1},
                "workflow_id": {"type": "string", "minLength": 1},
                "parent_workflow_id": {"type": "string", "minLength": 1},
                "goal": {"type": "string", "minLength": 1},
                "mode": {"enum": ["plan", "bounded_wave", "run_until_boundary"]},
                "set_signature": {"type": "string", "minLength": 1},
                "guardrails": {"type": "object"},
                "budget": {
                    "type": "object",
                    "properties": {
                        "max_mutations": {"type": "integer", "minimum": 0},
                        "max_renders": {"type": "integer", "minimum": 0},
                        "max_child_jobs": {"type": "integer", "minimum": 0}
                    },
                    "additionalProperties": True
                }
            },
            "additionalProperties": False
        },
    },
    "sidechain_audit": {
        "description": (
            "Read the exact native Compressor sidechain graph for the current Live Set. "
            "Third-party plugin routes remain explicitly unsupported rather than inferred."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "track_limit": {"type": "integer", "minimum": -1, "maximum": 1000},
                "max_devices": {"type": "integer", "minimum": 1, "maximum": 20000},
                "max_depth": {"type": "integer", "minimum": 0, "maximum": 32},
                "include_return_tracks": {"type": "boolean"},
                "include_master_track": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    },
    "verify_sidechain_capture": {
        "description": (
            "Measure rendered event-correlated ducking from aligned trigger, target-pre and target-post ChibiTap evidence. "
            "This is analysis-only and does not trust plugin gain-reduction meters."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["manifest", "trigger_label", "target_pre_label", "target_post_label"],
            "properties": {
                "manifest": {"type": "string", "minLength": 1},
                "trigger_label": {"type": "string", "minLength": 1},
                "target_pre_label": {"type": "string", "minLength": 1},
                "target_post_label": {"type": "string", "minLength": 1},
                "trigger_threshold_dbfs": {"type": "number", "minimum": -160, "maximum": 0},
                "min_event_gap_ms": {"type": "number", "exclusiveMinimum": 0},
                "target_active_floor_dbfs": {"type": "number", "minimum": -160, "maximum": 0},
                "target_activity_margin_db": {"type": "number", "exclusiveMinimum": 0},
                "depth_threshold_db": {"type": "number", "exclusiveMinimum": 0},
            },
            "additionalProperties": False,
        },
    },
    "compare_sidechain_captures": {
        "description": (
            "Compare two same-trigger sidechain capture manifests, normalize each target-post against its own target-pre render, "
            "and create a downward-only level-matched target-post A/B under the configured artifact root."
        ),
        "inputSchema": {
            "type": "object",
            "required": [
                "baseline_manifest",
                "candidate_manifest",
                "trigger_label",
                "target_pre_label",
                "target_post_label",
                "output_dir",
                "comparison_id",
            ],
            "properties": {
                "baseline_manifest": {"type": "string", "minLength": 1},
                "candidate_manifest": {"type": "string", "minLength": 1},
                "trigger_label": {"type": "string", "minLength": 1},
                "target_pre_label": {"type": "string", "minLength": 1},
                "target_post_label": {"type": "string", "minLength": 1},
                "output_dir": {"type": "string", "minLength": 1},
                "comparison_id": {"type": "string", "minLength": 1},
            },
            "additionalProperties": False,
        },
    },
    "propose_sidechain_intents": {
        "description": (
            "Use a persisted capture-analysis report to propose transparent sidechain processing classes for one source against candidate targets. "
            "This is analysis-only; every heuristic threshold is returned with the evidence."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["capture_analysis", "source_label"],
            "properties": {
                "capture_analysis": {"type": "string", "minLength": 1},
                "source_label": {"type": "string", "minLength": 1},
                "target_labels": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "uniqueItems": True,
                },
                "time_tolerance_seconds": {"type": "number", "minimum": 0, "maximum": 5},
                "max_moments_per_pair": {"type": "integer", "minimum": 1, "maximum": 16},
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
            "required": ["track_name", "device_index", "device_name", "device_id"],
            "properties": {
                "placement": {"enum": ["track", "master"], "default": "track"},
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
    "configure_sidechain_intent": {
        "description": (
            "Configure existing native sidechain consumers from one track-level intent. The command discovers exact Compressor2 targets from the live sidechain graph, preflights every target before mutation, and requires no device ids or manual plugin routing."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["source_track_name", "intent"],
            "properties": {
                "source_track_name": {"type": "string", "minLength": 1},
                "intent": {"enum": ["ensure_active", "ensure_inactive"]},
                "target_track_names": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "uniqueItems": True,
                },
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
                "expected_track_name",
                "device_index",
                "expected_device_name",
                "parameter_index",
                "expected_parameter_name",
                "expected_current_value",
                "value",
            ],
            "properties": {
                **_DEVICE_TARGET_PROPERTIES,
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
    "set_device_parameter_ref": {
        "description": (
            "Set one exact recursively contained device parameter by Live object id with track/device/parameter identity and before-state guards."
        ),
        "inputSchema": {
            "type": "object",
            "required": [
                "expected_track_name",
                "expected_device_name",
                "expected_device_id",
                "parameter_index",
                "expected_parameter_name",
                "expected_current_value",
                "value",
            ],
            "properties": {
                "placement": {"enum": ["track", "master"], "default": "track"},
                "track_index": {"type": "integer", "minimum": 0},
                "expected_track_name": {"type": "string", "minLength": 1},
                "expected_track_id": {"type": "integer"},
                "expected_set_signature": {"type": "string", "minLength": 1},
                "expected_device_name": {"type": "string", "minLength": 1},
                "expected_device_id": {"type": "integer"},
                "expected_device_class_name": {"type": "string", "minLength": 1},
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
                "expected_track_name",
                "device_index",
                "expected_device_name",
                "parameter_index",
                "expected_parameter_name",
                "expected_current_value",
            ],
            "properties": {
                **_DEVICE_TARGET_PROPERTIES,
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
            "plan_workflow": self._plan_workflow,
            "project_snapshot": lambda a: self.read.set_summary(
                track_limit=int(a.get("track_limit", 140)),
                device_limit=int(a.get("device_limit", 24)),
            ),
            "sidechain_audit": lambda a: self.read.call(
                "sidechain_graph",
                {
                    "track_limit": int(a.get("track_limit", 256)),
                    "max_devices": int(a.get("max_devices", 4096)),
                    "max_depth": int(a.get("max_depth", 8)),
                    "include_return_tracks": bool(a.get("include_return_tracks", True)),
                    "include_master_track": bool(a.get("include_master_track", True)),
                },
            ),
            "verify_sidechain_capture": self._verify_sidechain_capture,
            "compare_sidechain_captures": self._compare_sidechain_captures,
            "propose_sidechain_intents": self._propose_sidechain_intents,
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
            "configure_sidechain_intent": self._configure_sidechain_intent,
            "analyze_harshness_artifact": lambda a: analyze_harshness(
                self._resolve_artifact(a["artifact"]),
                top_events=int(a.get("top_events", 12)),
            ),
            "set_track_volume": lambda a: self.write.set_track_volume(**a),
            "set_track_pan": lambda a: self.write.set_track_pan(**a),
            "set_track_property": lambda a: self.write.set_track_property(**a),
            "set_device_parameter": lambda a: self.write.set_device_parameter(**a),
            "set_device_parameter_ref": lambda a: self.write.set_device_parameter_ref(**a),
            "set_device_enabled": lambda a: self.write.set_device_enabled(**a),
        }
        if name not in handlers:
            raise KeyError(f"Unknown Chibi Audio facade tool: {name}")
        return handlers[name](args)

    def _plan_workflow(self, args: dict[str, Any]) -> dict[str, Any]:
        context_source = self._resolve_artifact(str(args["context_artifact"]))
        try:
            context = load_project_context(context_source)
            return build_workflow_command(
                context,
                intent=str(args["intent"]),
                project_ref=str(args["project_ref"]),
                workflow_id=str(args["workflow_id"]),
                parent_workflow_id=(
                    None
                    if args.get("parent_workflow_id") is None
                    else str(args["parent_workflow_id"])
                ),
                goal=str(args["goal"]),
                mode=str(args.get("mode", "plan")),
                set_signature=args.get("set_signature"),
                guardrails=dict(args.get("guardrails") or {}),
                budget=dict(args.get("budget") or {}),
            )
        except WorkflowCommandError as exc:
            raise FacadeError(str(exc)) from exc

    def _verify_sidechain_capture(self, args: dict[str, Any]) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "trigger_label": str(args["trigger_label"]),
            "target_pre_label": str(args["target_pre_label"]),
            "target_post_label": str(args["target_post_label"]),
        }
        for key in (
            "trigger_threshold_dbfs",
            "min_event_gap_ms",
            "target_active_floor_dbfs",
            "target_activity_margin_db",
            "depth_threshold_db",
        ):
            if key in args:
                kwargs[key] = float(args[key])
        return verify_sidechain_capture(self._resolve_artifact(str(args["manifest"])), **kwargs)

    def _compare_sidechain_captures(self, args: dict[str, Any]) -> dict[str, Any]:
        summary = compare_sidechain_captures(
            self._resolve_artifact(str(args["baseline_manifest"])),
            self._resolve_artifact(str(args["candidate_manifest"])),
            trigger_label=str(args["trigger_label"]),
            target_pre_label=str(args["target_pre_label"]),
            target_post_label=str(args["target_post_label"]),
            output_dir=self._resolve_artifact_dir(str(args["output_dir"])),
            comparison_id=str(args["comparison_id"]),
        )
        payload = json.loads(summary.read_text(encoding="utf-8"))
        root = self.artifact_root.resolve() if self.artifact_root is not None else None
        if root is None:
            raise FacadeError("artifact analysis is unavailable because artifact_root is not configured")
        payload["comparison_artifact"] = summary.relative_to(root).as_posix()
        ab = Path(str(payload["level_matched_ab_manifest"])).resolve()
        payload["level_matched_ab_manifest"] = ab.relative_to(root).as_posix()
        return payload

    def _propose_sidechain_intents(self, args: dict[str, Any]) -> dict[str, Any]:
        source = self._resolve_artifact(str(args["capture_analysis"]))
        try:
            payload = json.loads(source.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FacadeError(f"could not read capture-analysis artifact: {source}") from exc
        if not isinstance(payload, dict):
            raise FacadeError("capture-analysis artifact must contain a JSON object")
        targets = args.get("target_labels")
        return propose_sidechain_intents(
            payload,
            source_label=str(args["source_label"]),
            target_labels=None if targets is None else [str(value) for value in targets],
            time_tolerance_seconds=float(args.get("time_tolerance_seconds", 0.08)),
            max_moments_per_pair=int(args.get("max_moments_per_pair", 6)),
        )

    def _configure_sidechain_intent(self, args: dict[str, Any]) -> dict[str, Any]:
        targets = args.get("target_track_names")
        return configure_sidechain_targets(
            self.read,
            self.write,
            source_track_name=str(args["source_track_name"]),
            intent=str(args["intent"]),
            target_track_names=None if targets is None else [str(value) for value in targets],
        )

    def _track_mixer_state(self, args: dict[str, Any]) -> dict[str, Any]:
        index = int(args["track_index"])
        result: dict[str, Any] = {}
        for parameter in ("volume", "panning"):
            result[parameter] = self.read.call(
                "get",
                {
                    "ref": {"path": f"song tracks {index} mixer_device {parameter}"},
                    "properties": ["name", "value", "min", "max"],
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
            track_index=int(args["track_index"]) if args.get("track_index") is not None else None,
            track_name=str(args["track_name"]),
            placement=str(args.get("placement", "track")),
            device_index=int(args["device_index"]),
            device_name=str(args["device_name"]),
            device_id=int(args["device_id"]),
            parameters=list(parameters),
            set_signature=args.get("set_signature"),
        )

    def _resolve_artifact_dir(self, artifact: str) -> Path:
        if self.artifact_root is None:
            raise FacadeError("artifact analysis is unavailable because artifact_root is not configured")
        relative = Path(artifact)
        if relative.is_absolute():
            raise FacadeError("artifact directory must be relative to the configured artifact root")
        root = self.artifact_root.resolve()
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise FacadeError("artifact directory escapes the configured artifact root") from exc
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate

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
