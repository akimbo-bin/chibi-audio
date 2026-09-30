"""Read-only inspection of Ableton Live Set (.als) files.

Ableton Live Sets are gzip-compressed XML. This module intentionally only reads
that representation. Chibi Audio must use Live-supported control surfaces for
mutations rather than rewriting project XML.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import gzip
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

TRACK_TAGS = {"AudioTrack", "MidiTrack", "GroupTrack", "ReturnTrack"}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def direct_child(parent: ET.Element, name: str) -> ET.Element | None:
    for node in parent:
        if local_name(node.tag) == name:
            return node
    return None


def descendants(parent: ET.Element, name: str):
    for node in parent.iter():
        if local_name(node.tag) == name:
            yield node


def value(node: ET.Element | None) -> str | None:
    return None if node is None else node.attrib.get("Value")


def first_desc_value(parent: ET.Element, name: str) -> str | None:
    return next((value(node) for node in descendants(parent, name)), None)


def track_name(track: ET.Element) -> str:
    names = direct_child(track, "Name")
    if names is None:
        return ""
    user = value(direct_child(names, "UserName")) or ""
    effective = value(direct_child(names, "EffectiveName")) or ""
    return user.strip() or effective.strip()


def plugin_name(device: ET.Element) -> str | None:
    """Recover a human-readable plugin name from Live's browser source path."""
    browser_path = first_desc_value(device, "BrowserContentPath") or ""
    if not browser_path:
        return None
    # Common Live form: query:Plugins#VST3:oeksound:soothe2
    tail = browser_path.split("#", 1)[-1]
    parts = tail.split(":")
    return parts[-1].strip() if parts else tail.strip()


@dataclass(slots=True)
class DeviceInfo:
    type: str
    plugin: str | None = None
    enabled: bool | None = None


@dataclass(slots=True)
class ArrangementClipInfo:
    type: str
    start_beat: float
    end_beat: float
    disabled: bool


@dataclass(slots=True)
class LocatorInfo:
    id: str | None
    name: str
    time_beat: float
    annotation: str
    is_song_start: bool


@dataclass(slots=True)
class TrackInfo:
    index: int
    id: str | None
    type: str
    name: str
    color: int | str | None
    group_id: str | None
    devices: list[DeviceInfo]
    arrangement_clips: list[ArrangementClipInfo]
    automation_envelope_count: int
    automation_event_count: int


def parse_scalar(raw: str | None) -> int | str | None:
    if raw is None:
        return None
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    return raw


def inspect_set(path: str | Path) -> dict:
    set_path = Path(path).expanduser().resolve()
    with gzip.open(set_path, "rb") as stream:
        root = ET.parse(stream).getroot()

    tracks: list[TrackInfo] = []
    plugins: set[str] = set()
    locators: list[LocatorInfo] = []
    for node in root.iter():
        if local_name(node.tag) != "Locator":
            continue
        time_raw = value(direct_child(node, "Time"))
        if time_raw is None:
            continue
        try:
            time_beat = float(time_raw)
        except ValueError:
            continue
        locators.append(
            LocatorInfo(
                id=node.attrib.get("Id"),
                name=(value(direct_child(node, "Name")) or "").strip(),
                time_beat=time_beat,
                annotation=value(direct_child(node, "Annotation")) or "",
                is_song_start=value(direct_child(node, "IsSongStart")) == "true",
            )
        )
    locators.sort(key=lambda item: (item.time_beat, item.name, item.id or ""))

    for node in root.iter():
        kind = local_name(node.tag)
        if kind not in TRACK_TAGS:
            continue

        devices: list[DeviceInfo] = []
        device_chain = direct_child(node, "DeviceChain")
        devices_container = None
        if device_chain is not None:
            devices_container = next(descendants(device_chain, "Devices"), None)

        if devices_container is not None:
            for device in list(devices_container):
                dtype = local_name(device.tag)
                pname = plugin_name(device) if dtype == "PluginDevice" else None
                if pname:
                    plugins.add(pname)
                enabled_raw = first_desc_value(direct_child(device, "On") or device, "Manual")
                enabled = None
                if enabled_raw in {"true", "false"}:
                    enabled = enabled_raw == "true"
                devices.append(DeviceInfo(type=dtype, plugin=pname, enabled=enabled))

        arrangement_clips: list[ArrangementClipInfo] = []
        if device_chain is not None:
            for arranger in descendants(device_chain, "ArrangerAutomation"):
                events = direct_child(arranger, "Events")
                if events is None:
                    continue
                for clip in list(events):
                    clip_type = local_name(clip.tag)
                    if clip_type not in {"AudioClip", "MidiClip"}:
                        continue
                    start_raw = value(direct_child(clip, "CurrentStart")) or clip.attrib.get("Time")
                    end_raw = value(direct_child(clip, "CurrentEnd"))
                    if start_raw is None or end_raw is None:
                        continue
                    try:
                        start_beat = float(start_raw)
                        end_beat = float(end_raw)
                    except ValueError:
                        continue
                    if end_beat <= start_beat:
                        continue
                    disabled = value(direct_child(clip, "Disabled")) == "true"
                    arrangement_clips.append(ArrangementClipInfo(clip_type, start_beat, end_beat, disabled))

        automation_envelope_count = 0
        automation_event_count = 0
        for envelope in descendants(node, "AutomationEnvelope"):
            automation_envelope_count += 1
            events = next(descendants(envelope, "Events"), None)
            if events is not None:
                automation_event_count += len(list(events))

        tracks.append(
            TrackInfo(
                index=len(tracks),
                id=node.attrib.get("Id"),
                type=kind,
                name=track_name(node),
                color=parse_scalar(value(direct_child(node, "Color"))),
                group_id=value(direct_child(node, "TrackGroupId")),
                devices=devices,
                arrangement_clips=arrangement_clips,
                automation_envelope_count=automation_envelope_count,
                automation_event_count=automation_event_count,
            )
        )

    return {
        "path": str(set_path),
        "track_count": len(tracks),
        "named_track_count": sum(bool(track.name) for track in tracks),
        "plugin_count": len(plugins),
        "plugins": sorted(plugins, key=str.casefold),
        "locators": [asdict(locator) for locator in locators],
        "tracks": [asdict(track) for track in tracks],
    }


def dumps_report(report: dict) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False)
