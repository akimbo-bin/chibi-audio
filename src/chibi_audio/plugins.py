"""Read-only discovery and coarse classification of installed audio plugins."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import os
import re
from urllib.parse import unquote

WINDOWS_PLUGIN_ROOTS = (
    Path(r"C:\Program Files\Common Files\VST3"),
    Path(r"C:\Program Files\VstPlugins"),
    Path(r"C:\Program Files\Steinberg\VstPlugins"),
    Path(r"C:\Program Files\Common Files\VST2"),
    Path(r"C:\VstPlugins"),
    Path(r"C:\Program Files\Common Files\CLAP"),
)

CATEGORY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("analyzer", ("span", "youlean", "insight", "meter", "signalizer", "tonal balance")),
    ("limiter_clipper", ("pro-l", "limiter", "standardclip", "gclip", "elevate", "saturate")),
    ("eq_filter", ("pro-q", " eq", "eq ", "filter", "cleansweep", "museq", "equivocate")),
    ("compressor_dynamics", ("compressor", "pro-c", "glue", "mpressor", "dynamics", "opto", "drawmer", "punctuate", "transmod", "transient")),
    ("distortion_saturation", ("saturn", "saturator", "distort", "overdrive", "thermal", "rift", "trash", "inflator", "faturator", "karacter", "tape", "decapitator", "spectre")),
    ("reverb", ("reverb", "room", "plate", "shimmer", "supermassive", "megaverb")),
    ("delay_echo", ("delay", "echo", "timeless")),
    ("modulation", ("chorus", "flanger", "phaser", "trem", "autopan", "panpot")),
    ("stereo_imaging", ("imager", "stereo", "midside", "wider", "stereomaker", "shredspread")),
    ("spectral_cleanup", ("soothe", "spectral shaper", "stabilizer", "refinement", "spiff", "trackspacer", "de-esser", "deesser", "supresser")),
    ("pitch_vocal", ("auto-tune", "autotune", "melodyne", "vocal tuner", "vocal harmonizer", "pitch")),
    ("instrument", ("serum", "diva", "omnisphere", "vital", "phase plant", "synplant", "repro", "m1", "generate", "quanta")),
)


@dataclass(slots=True)
class PluginInfo:
    name: str
    format: str
    path: str
    vendor_hint: str | None
    categories: list[str]


def _clean_name(path: Path) -> str:
    name = path.stem if path.suffix else path.name
    return unquote(name).strip()


def classify_plugin(name: str) -> list[str]:
    haystack = f" {name.casefold()} "
    categories = [category for category, needles in CATEGORY_PATTERNS if any(needle in haystack for needle in needles)]
    return categories or ["uncategorized"]


def _vendor_hint(path: Path, root: Path) -> str | None:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) < 2:
        return None
    candidate = parts[0]
    if candidate.casefold() in {"contents", "resources", "x86_64-win"}:
        return None
    return candidate


def discover_plugins(roots: list[str | Path] | None = None) -> list[PluginInfo]:
    roots = [Path(root) for root in roots] if roots else list(WINDOWS_PLUGIN_ROOTS if os.name == "nt" else [])
    discovered: dict[tuple[str, str], PluginInfo] = {}

    for root in roots:
        if not root.exists():
            continue

        # VST3 plugins are normally bundles/directories. Do not descend into a
        # discovered bundle or internal DLLs become false plugin entries.
        for bundle in root.rglob("*.vst3"):
            if any(parent.suffix.casefold() == ".vst3" for parent in bundle.parents):
                continue
            info = PluginInfo(
                name=_clean_name(bundle),
                format="VST3",
                path=str(bundle),
                vendor_hint=_vendor_hint(bundle, root),
                categories=classify_plugin(_clean_name(bundle)),
            )
            discovered[(info.format, info.path.casefold())] = info

        for suffix, fmt in (("*.clap", "CLAP"), ("*.dll", "VST2/DLL")):
            for file in root.rglob(suffix):
                if any(parent.suffix.casefold() == ".vst3" for parent in file.parents):
                    continue
                info = PluginInfo(
                    name=_clean_name(file),
                    format=fmt,
                    path=str(file),
                    vendor_hint=_vendor_hint(file, root),
                    categories=classify_plugin(_clean_name(file)),
                )
                discovered[(info.format, info.path.casefold())] = info

    return sorted(discovered.values(), key=lambda item: (item.name.casefold(), item.format, item.path.casefold()))


def catalog_dict(plugins: list[PluginInfo]) -> dict:
    by_category: dict[str, int] = {}
    for plugin in plugins:
        for category in plugin.categories:
            by_category[category] = by_category.get(category, 0) + 1
    return {
        "plugin_count": len(plugins),
        "category_counts": dict(sorted(by_category.items())),
        "plugins": [asdict(plugin) for plugin in plugins],
    }
