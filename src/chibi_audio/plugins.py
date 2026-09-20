"""Read-only discovery and logical cataloging of installed audio plugins."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import os
import re
import unicodedata
from urllib.parse import unquote


PLUGIN_CATALOG_SCHEMA_VERSION = "chibi-audio-plugin-catalog/v1"

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
    ("compressor_dynamics", ("compressor", "pro-c", "glue", "mpressor", "dynamics", "opto", "drawmer", "punctuate", "transmod", "transient", "cl 1b", "cl1b", "api-2500")),
    ("distortion_saturation", ("saturn", "saturator", "distort", "overdrive", "thermal", "rift", "trash", "inflator", "faturator", "karacter", "tape", "decapitator", "spectre", "bitcrush")),
    ("reverb", ("reverb", "room", "plate", "shimmer", "supermassive", "megaverb")),
    ("delay_echo", ("delay", "echo", "timeless")),
    ("modulation", ("chorus", "flanger", "phaser", "trem", "autopan", "panpot", "rotary", "vibrato")),
    ("stereo_imaging", ("imager", "midside", "mid side", "wider", "stereomaker", "shredspread")),
    ("spectral_cleanup", ("soothe", "spectral shaper", "stabilizer", "refinement", "spiff", "trackspacer", "de-esser", "deesser", "supresser")),
    ("pitch_vocal", ("auto-tune", "autotune", "melodyne", "vocal tuner", "vocal harmonizer", "pitch")),
    ("instrument", ("serum", "diva", "omnisphere", "vital", "phase plant", "synplant", "repro", "m1", "generate", "quanta", "kontakt")),
)

PLUGIN_ROLE_CATEGORIES: dict[str, frozenset[str]] = {
    "mixing": frozenset(
        {
            "eq_filter",
            "compressor_dynamics",
            "distortion_saturation",
            "reverb",
            "delay_echo",
            "stereo_imaging",
            "spectral_cleanup",
            "pitch_vocal",
        }
    ),
    "mastering": frozenset(
        {
            "analyzer",
            "limiter_clipper",
            "eq_filter",
            "compressor_dynamics",
            "distortion_saturation",
            "stereo_imaging",
            "spectral_cleanup",
        }
    ),
    "modulation": frozenset({"modulation"}),
    "instrument": frozenset({"instrument"}),
}

_FORMAT_ORDER = {"VST3": 0, "CLAP": 1, "VST2/DLL": 2}
_ARCH_SUFFIX = re.compile(
    r"(?:[\s._-]+(?:x64|64|64[\s._-]*bit|win64|amd64))$",
    re.IGNORECASE,
)


@dataclass(slots=True)
class PluginInfo:
    name: str
    format: str
    path: str
    vendor_hint: str | None
    categories: list[str]


@dataclass(slots=True)
class PluginProduct:
    product_key: str
    name: str
    formats: list[str]
    paths: list[str]
    vendor_hints: list[str]
    categories: list[str]
    roles: list[str]
    entry_count: int


def normalize_plugin_name(value: str) -> str:
    """Normalize one filesystem/browser plugin label without erasing versions."""
    decoded = unquote(str(value or "")).strip()
    decoded = unicodedata.normalize("NFKC", decoded)
    decoded = decoded.replace("™", "").replace("®", "").strip()
    decoded = _ARCH_SUFFIX.sub("", decoded).strip(" ._-")
    return " ".join(decoded.split())


def logical_product_key(name: str) -> str:
    """Return a conservative format-neutral key for one logical plugin product."""
    normalized = normalize_plugin_name(name).casefold()
    # Keep letters and version digits, but make punctuation/spacing differences
    # irrelevant across VST2/VST3/CLAP package naming.
    return re.sub(r"[^a-z0-9]+", "", normalized)


def _clean_name(path: Path) -> str:
    name = path.stem if path.suffix else path.name
    return normalize_plugin_name(name)


def classify_plugin(name: str) -> list[str]:
    haystack = f" {normalize_plugin_name(name).casefold()} "
    categories = [
        category
        for category, needles in CATEGORY_PATTERNS
        if any(needle in haystack for needle in needles)
    ]
    return categories or ["uncategorized"]


def plugin_roles(categories: list[str]) -> list[str]:
    values = set(categories)
    return [
        role
        for role, role_categories in PLUGIN_ROLE_CATEGORIES.items()
        if values & role_categories
    ]


def _vendor_hint(path: Path, root: Path) -> str | None:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) < 2:
        return None
    candidate = normalize_plugin_name(parts[0])
    if candidate.casefold() in {"contents", "resources", "x86_64-win"}:
        return None
    return candidate or None


def discover_plugins(roots: list[str | Path] | None = None) -> list[PluginInfo]:
    roots = (
        [Path(root) for root in roots]
        if roots
        else list(WINDOWS_PLUGIN_ROOTS if os.name == "nt" else [])
    )
    discovered: dict[tuple[str, str], PluginInfo] = {}

    for root in roots:
        if not root.exists():
            continue

        # VST3 plugins are normally bundles/directories. Do not descend into a
        # discovered bundle or internal DLLs become false plugin entries.
        for bundle in root.rglob("*.vst3"):
            if any(parent.suffix.casefold() == ".vst3" for parent in bundle.parents):
                continue
            name = _clean_name(bundle)
            info = PluginInfo(
                name=name,
                format="VST3",
                path=str(bundle),
                vendor_hint=_vendor_hint(bundle, root),
                categories=classify_plugin(name),
            )
            discovered[(info.format, info.path.casefold())] = info

        for suffix, fmt in (("*.clap", "CLAP"), ("*.dll", "VST2/DLL")):
            for file in root.rglob(suffix):
                if any(parent.suffix.casefold() == ".vst3" for parent in file.parents):
                    continue
                name = _clean_name(file)
                info = PluginInfo(
                    name=name,
                    format=fmt,
                    path=str(file),
                    vendor_hint=_vendor_hint(file, root),
                    categories=classify_plugin(name),
                )
                discovered[(info.format, info.path.casefold())] = info

    return sorted(
        discovered.values(),
        key=lambda item: (item.name.casefold(), item.format, item.path.casefold()),
    )


def group_logical_products(plugins: list[PluginInfo]) -> list[PluginProduct]:
    groups: dict[str, list[PluginInfo]] = {}
    for plugin in plugins:
        key = logical_product_key(plugin.name)
        if not key:
            # Keep strange/empty labels distinct by exact path instead of
            # accidentally coalescing unrelated filesystem entries.
            key = f"path:{plugin.path.casefold()}"
        groups.setdefault(key, []).append(plugin)

    products: list[PluginProduct] = []
    for key, entries in groups.items():
        ordered = sorted(
            entries,
            key=lambda item: (
                _FORMAT_ORDER.get(item.format, 99),
                len(item.name),
                item.name.casefold(),
                item.path.casefold(),
            ),
        )
        display_name = ordered[0].name
        formats = sorted(
            {item.format for item in entries},
            key=lambda fmt: (_FORMAT_ORDER.get(fmt, 99), fmt),
        )
        paths = sorted({item.path for item in entries}, key=str.casefold)
        vendors = sorted(
            {item.vendor_hint for item in entries if item.vendor_hint},
            key=str.casefold,
        )
        categories = sorted(
            {category for item in entries for category in item.categories},
            key=str.casefold,
        )
        categories = categories or ["uncategorized"]
        products.append(
            PluginProduct(
                product_key=key,
                name=display_name,
                formats=formats,
                paths=paths,
                vendor_hints=vendors,
                categories=categories,
                roles=plugin_roles(categories),
                entry_count=len(entries),
            )
        )

    return sorted(products, key=lambda item: (item.name.casefold(), item.product_key))


def _product_alias_keys(product: PluginProduct) -> set[str]:
    keys = {product.product_key}
    for vendor in product.vendor_hints:
        vendor_key = logical_product_key(vendor)
        if (
            vendor_key
            and product.product_key.startswith(vendor_key)
            and len(product.product_key) > len(vendor_key)
        ):
            keys.add(product.product_key[len(vendor_key) :])
    return keys


def reconcile_plugin_references(
    references: list[str],
    products: list[PluginProduct],
) -> dict:
    alias_index: dict[str, list[PluginProduct]] = {}
    for product in products:
        for alias in _product_alias_keys(product):
            alias_index.setdefault(alias, []).append(product)

    resolved = []
    unresolved = []
    ambiguous = []
    for reference in references:
        normalized = normalize_plugin_name(reference)
        key = logical_product_key(normalized)
        matches = alias_index.get(key, [])
        if len(matches) == 1:
            product = matches[0]
            resolved.append(
                {
                    "reference": reference,
                    "normalized_reference": normalized,
                    "reference_key": key,
                    "product_key": product.product_key,
                    "product_name": product.name,
                    "formats": list(product.formats),
                    "categories": list(product.categories),
                    "roles": list(product.roles),
                }
            )
        elif len(matches) > 1:
            ambiguous.append(
                {
                    "reference": reference,
                    "normalized_reference": normalized,
                    "reference_key": key,
                    "candidates": [
                        {
                            "product_key": product.product_key,
                            "product_name": product.name,
                            "formats": list(product.formats),
                        }
                        for product in matches
                    ],
                }
            )
        else:
            unresolved.append(
                {
                    "reference": reference,
                    "normalized_reference": normalized,
                    "reference_key": key,
                }
            )

    return {
        "schema_version": "chibi-audio-plugin-reconciliation/v1",
        "effect_state": "NOT_STARTED",
        "reference_count": len(references),
        "resolved_count": len(resolved),
        "ambiguous_count": len(ambiguous),
        "unresolved_count": len(unresolved),
        "resolved": resolved,
        "ambiguous": ambiguous,
        "unresolved": unresolved,
    }


def _category_counts(rows: list[PluginInfo | PluginProduct]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        for category in row.categories:
            counts[category] = counts.get(category, 0) + 1
    return dict(sorted(counts.items()))


def catalog_dict(plugins: list[PluginInfo]) -> dict:
    products = group_logical_products(plugins)
    return {
        "schema_version": PLUGIN_CATALOG_SCHEMA_VERSION,
        "effect_state": "NOT_STARTED",
        # Backward-compatible raw-entry keys.
        "plugin_count": len(plugins),
        "category_counts": _category_counts(plugins),
        "plugins": [asdict(plugin) for plugin in plugins],
        # Stable logical-product layer for planning/reasoning.
        "logical_product_count": len(products),
        "logical_category_counts": _category_counts(products),
        "role_counts": {
            role: sum(role in product.roles for product in products)
            for role in PLUGIN_ROLE_CATEGORIES
        },
        "products": [asdict(product) for product in products],
    }
