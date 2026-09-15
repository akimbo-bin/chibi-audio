"""Read-only discovery of Ableton Browser places from Library.cfg."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import xml.etree.ElementTree as ET


@dataclass(slots=True)
class AbletonPlace:
    id: str | None
    name: str
    path: str


def read_user_places(library_cfg: str | Path) -> list[AbletonPlace]:
    path = Path(library_cfg).expanduser().resolve()
    root = ET.parse(path).getroot()
    places: list[AbletonPlace] = []
    for node in root.iter("UserFolderInfo"):
        places.append(
            AbletonPlace(
                id=node.attrib.get("Id"),
                name=node.attrib.get("DisplayName", ""),
                path=node.attrib.get("Path", ""),
            )
        )
    return places


def places_dict(places: list[AbletonPlace]) -> dict:
    return {"place_count": len(places), "places": [asdict(place) for place in places]}
