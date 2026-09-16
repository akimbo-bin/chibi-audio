from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable

from .capture_session import parse_session_tap
from .sections import resolve_section


def build_section_capture_plan(
    section_map: dict[str, Any],
    section_name: str,
    *,
    occurrence: int | None = None,
    tap_specs: Iterable[str] = (),
) -> dict[str, Any]:
    """Build a capture-session-compatible plan without causing any Live effects."""
    section = dict(resolve_section(section_map, section_name, occurrence))
    taps = [parse_session_tap(value) for value in tap_specs]
    start_beat = float(section["start_beat"])
    end_beat = float(section["end_beat"])
    return {
        "effect_state": "NOT_STARTED",
        "set_signature": section_map.get("set_signature"),
        "section": section,
        "capture_request": {
            "start_beat": start_beat,
            "end_beat": end_beat,
            "duration_beats": end_beat - start_beat,
            "taps": [asdict(tap) for tap in taps],
        },
        "ready_to_execute": bool(taps) and end_beat > start_beat,
        "execution_note": (
            "Pass the capture_request beat range and tap mapping to the managed ChibiTap capture executor only after explicit write authority."
        ),
    }
