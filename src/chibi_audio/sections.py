from __future__ import annotations

from typing import Any


class SectionMapError(ValueError):
    """Raised when named section metadata is ambiguous or invalid."""


def build_section_map(locator_report: dict[str, Any]) -> dict[str, Any]:
    locators = sorted(
        [item for item in locator_report.get("locators", []) if not item.get("truncated")],
        key=lambda item: (float(item.get("time", 0.0)), int(item.get("index", 0))),
    )
    last_event_time = float(locator_report.get("last_event_time") or 0.0)
    song_length = float(locator_report.get("song_length") or last_event_time)
    arrangement_end = max(
        last_event_time,
        max((float(item.get("time", 0.0)) for item in locators), default=0.0),
    )

    sections: list[dict[str, Any]] = []
    for index, locator in enumerate(locators):
        start = float(locator.get("time", 0.0))
        end = (
            float(locators[index + 1].get("time", start))
            if index + 1 < len(locators)
            else arrangement_end
        )
        if end < start:
            raise SectionMapError("locator times are not monotonic")
        sections.append(
            {
                "index": index,
                "name": str(locator.get("name") or ""),
                "start_beat": start,
                "end_beat": end,
                "duration_beats": end - start,
                "start_locator_id": locator.get("id"),
                "end_locator_id": (
                    locators[index + 1].get("id") if index + 1 < len(locators) else None
                ),
            }
        )

    leading_unlabeled = None
    if locators and float(locators[0].get("time", 0.0)) > 0.0:
        first_time = float(locators[0]["time"])
        leading_unlabeled = {
            "start_beat": 0.0,
            "end_beat": first_time,
            "duration_beats": first_time,
        }

    return {
        "set_signature": locator_report.get("set_signature"),
        "current_song_time": float(locator_report.get("current_song_time") or 0.0),
        "last_event_time": last_event_time,
        "song_length": song_length,
        "arrangement_end_beat": arrangement_end,
        "leading_unlabeled": leading_unlabeled,
        "sections": sections,
    }


def resolve_section(
    section_map: dict[str, Any], name: str, occurrence: int | None = None
) -> dict[str, Any]:
    wanted = name.strip().casefold()
    if not wanted:
        raise SectionMapError("section name must not be empty")
    matches = [
        item
        for item in section_map.get("sections", [])
        if str(item.get("name") or "").strip().casefold() == wanted
    ]
    if not matches:
        raise SectionMapError(f"No locator-defined section named {name!r}")
    if occurrence is None:
        if len(matches) != 1:
            raise SectionMapError(
                f"Section name {name!r} is ambiguous; provide occurrence 1..{len(matches)}"
            )
        return matches[0]
    if occurrence < 1 or occurrence > len(matches):
        raise SectionMapError(
            f"occurrence must be between 1 and {len(matches)} for section {name!r}"
        )
    return matches[occurrence - 1]


def position_context(section_map: dict[str, Any], beat: float | None = None) -> dict[str, Any]:
    position = float(section_map.get("current_song_time") if beat is None else beat)
    sections = section_map.get("sections", [])
    active = None
    previous = None
    upcoming = None
    for section in sections:
        start = float(section["start_beat"])
        end = float(section["end_beat"])
        if start <= position < end or (start == end == position):
            active = section
            break
        if start <= position:
            previous = section
        elif start > position and upcoming is None:
            upcoming = section
    if active is not None:
        idx = int(active["index"])
        previous = sections[idx - 1] if idx > 0 else None
        upcoming = sections[idx + 1] if idx + 1 < len(sections) else None
    return {
        "beat": position,
        "active_section": active,
        "previous_section": previous,
        "next_section": upcoming,
    }
