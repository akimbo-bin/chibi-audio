"""Read-only discovery and logical cataloging of installed audio plugins."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import os
import re
import unicodedata
from urllib.parse import unquote


PLUGIN_CATALOG_SCHEMA_VERSION = "chibi-audio-plugin-catalog/v1"
PLUGIN_INTENT_QUERY_SCHEMA_VERSION = "chibi-audio-plugin-intent-query/v1"
PLUGIN_SEMANTICS_SOURCE = "chibi-audio-curated-pilot/v1"

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


class PluginIntentError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PluginIntentRule:
    product_key: str
    confidence: str
    capabilities: tuple[str, ...]
    why_candidate: str
    caveats: tuple[str, ...] = ()


PLUGIN_INTENTS: dict[str, dict[str, object]] = {
    "transparent_clipping": {
        "aliases": (
            "transparent clipping",
            "transparent clipper",
            "transparent clippers",
            "clean clipping",
            "clean clipper",
            "dedicated clipper",
        ),
        "goal": (
            "Find installed dedicated clipping/peak-control tools that are plausible "
            "for low-coloration peak shaving when configured conservatively."
        ),
        "global_caveats": (
            "Transparency is a usage goal, not an intrinsic property proved by the plugin name.",
            "Any candidate still requires level-matched A/B and peak/distortion evidence at the intended settings.",
        ),
        "rules": (
            PluginIntentRule(
                product_key="standardclip",
                confidence="high",
                capabilities=("dedicated_clipping", "peak_control"),
                why_candidate=(
                    "Curated pilot semantics identify StandardCLIP as a dedicated clipping/peak-control tool."
                ),
                caveats=("Clip mode/amount and oversampling choices can materially change coloration.",),
            ),
            PluginIntentRule(
                product_key="newfangledsaturate",
                confidence="high",
                capabilities=("dedicated_clipping", "peak_control"),
                why_candidate=(
                    "Curated pilot semantics identify Newfangled Saturate as a dedicated saturation/clipping peak-control tool."
                ),
                caveats=("Saturation/clip settings may intentionally add color; transparent use must be verified.",),
            ),
            PluginIntentRule(
                product_key="gclip",
                confidence="medium",
                capabilities=("dedicated_clipping", "peak_control"),
                why_candidate=(
                    "Curated pilot semantics identify GClip as a dedicated clipping/peak-control tool."
                ),
                caveats=("Transparency is setting-dependent and is not inferred from installation alone.",),
            ),
        ),
    },
    "dynamic_space": {
        "aliases": (
            "dynamic space",
            "dynamically create space",
            "create space dynamically",
            "dynamic masking space",
            "spectral ducking",
            "frequency selective ducking",
            "frequency-selective ducking",
        ),
        "goal": (
            "Find installed processors that can support time-varying or frequency-selective "
            "masking relief, while distinguishing source-aware spectral space from generic dynamic control."
        ),
        "global_caveats": (
            "Installed capability does not prove that the current Live routing exposes the desired sidechain/control path.",
            "The specific band, source-target relation, depth and timing still require project evidence and bounded A/B verification.",
        ),
        "rules": (
            PluginIntentRule(
                product_key="trackspacer25",
                confidence="high",
                capabilities=("source_aware_spectral_space", "dynamic_masking_relief"),
                why_candidate=(
                    "Curated pilot semantics identify Trackspacer as a source-aware spectral-space processor."
                ),
                caveats=("Requires a valid source-target routing relationship for source-aware use.",),
            ),
            PluginIntentRule(
                product_key="fabfilterproq3",
                confidence="high",
                capabilities=("dynamic_eq", "frequency_selective_control"),
                why_candidate=(
                    "Curated pilot semantics identify FabFilter Pro-Q 3 as a dynamic-EQ candidate for selective masking relief."
                ),
                caveats=("A dynamic-EQ candidate is not automatically source-aware; verify the intended trigger/routing mode.",),
            ),
            PluginIntentRule(
                product_key="ozone10dynamiceq",
                confidence="high",
                capabilities=("dynamic_eq", "frequency_selective_control"),
                why_candidate=(
                    "Curated pilot semantics identify Ozone 10 Dynamic EQ as a dynamic-EQ candidate for selective masking relief."
                ),
                caveats=("Use as a dynamic-EQ candidate; do not infer external source triggering from inventory alone.",),
            ),
            PluginIntentRule(
                product_key="bxdynEQv2".casefold(),
                confidence="medium",
                capabilities=("dynamic_eq", "frequency_selective_control"),
                why_candidate=(
                    "Curated pilot semantics identify bx_dynEQ V2 as a dynamic-EQ candidate for selective masking relief."
                ),
                caveats=("Verify the exact installed variant and routing before treating it as source-driven.",),
            ),
            PluginIntentRule(
                product_key="soothe2",
                confidence="medium",
                capabilities=("dynamic_resonance_control", "spectral_cleanup"),
                why_candidate=(
                    "Curated pilot semantics identify soothe2 as dynamic resonance/spectral control that can reduce masking or harsh buildup."
                ),
                caveats=("This is not equivalent to source-target spectral ducking by default.",),
            ),
        ),
    },
}

# Normalize rule keys once, including human-readable literals above.
PLUGIN_INTENTS = {
    name: {
        **definition,
        "rules": tuple(
            PluginIntentRule(
                product_key=logical_key,
                confidence=rule.confidence,
                capabilities=rule.capabilities,
                why_candidate=rule.why_candidate,
                caveats=rule.caveats,
            )
            for rule in definition["rules"]
            for logical_key in (re.sub(r"[^a-z0-9]+", "", rule.product_key.casefold()),)
        ),
    }
    for name, definition in PLUGIN_INTENTS.items()
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


def supported_plugin_intents() -> list[dict[str, object]]:
    return [
        {
            "intent": name,
            "goal": str(definition["goal"]),
            "aliases": list(definition["aliases"]),
            "global_caveats": list(definition["global_caveats"]),
        }
        for name, definition in sorted(PLUGIN_INTENTS.items())
    ]


def resolve_plugin_intent(request: str) -> str:
    raw = str(request or "").strip()
    if not raw:
        raise PluginIntentError("plugin intent request must not be empty")
    normalized = " ".join(re.sub(r"[^a-z0-9]+", " ", raw.casefold()).split())
    direct = raw.casefold().strip()
    if direct in PLUGIN_INTENTS:
        return direct

    matches: list[str] = []
    padded = f" {normalized} "
    for intent, definition in PLUGIN_INTENTS.items():
        for alias in definition["aliases"]:
            alias_normalized = " ".join(
                re.sub(r"[^a-z0-9]+", " ", str(alias).casefold()).split()
            )
            if f" {alias_normalized} " in padded:
                matches.append(intent)
                break
    unique = sorted(set(matches))
    if len(unique) == 1:
        return unique[0]
    supported = ", ".join(sorted(PLUGIN_INTENTS))
    if not unique:
        raise PluginIntentError(
            f"unsupported plugin intent request; supported intents: {supported}"
        )
    raise PluginIntentError(
        "plugin intent request is ambiguous across reviewed intents: "
        + ", ".join(unique)
    )


def query_installed_plugins(
    plugins: list[PluginInfo],
    request: str,
    *,
    limit: int = 12,
) -> dict[str, object]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise PluginIntentError("limit must be an integer between 1 and 50")

    intent = resolve_plugin_intent(request)
    definition = PLUGIN_INTENTS[intent]
    products = group_logical_products(plugins)
    by_key = {product.product_key: product for product in products}
    candidates: list[dict[str, object]] = []

    confidence_order = {"high": 0, "medium": 1, "low": 2}
    for rule_order, rule in enumerate(definition["rules"]):
        product = by_key.get(rule.product_key)
        if product is None:
            continue
        candidates.append(
            {
                "product_key": product.product_key,
                "product_name": product.name,
                "formats": list(product.formats),
                "paths": list(product.paths),
                "vendor_hints": list(product.vendor_hints),
                "categories": list(product.categories),
                "roles": list(product.roles),
                "physical_entry_count": product.entry_count,
                "confidence": rule.confidence,
                "capabilities": list(rule.capabilities),
                "why_candidate": rule.why_candidate,
                "caveats": [*definition["global_caveats"], *rule.caveats],
                "evidence": {
                    "inventory": "installed_logical_product",
                    "semantics_source": PLUGIN_SEMANTICS_SOURCE,
                },
                "_rule_order": rule_order,
            }
        )

    candidates.sort(
        key=lambda item: (
            confidence_order.get(str(item["confidence"]), 99),
            int(item["_rule_order"]),
            str(item["product_name"]).casefold(),
        )
    )
    for rank, item in enumerate(candidates[:limit], start=1):
        item.pop("_rule_order", None)
        item["rank"] = rank

    selected = candidates[:limit]
    return {
        "schema_version": PLUGIN_INTENT_QUERY_SCHEMA_VERSION,
        "effect_state": "NOT_STARTED",
        "request": request,
        "resolved_intent": intent,
        "intent_goal": definition["goal"],
        "global_caveats": list(definition["global_caveats"]),
        "semantics_source": PLUGIN_SEMANTICS_SOURCE,
        "inventory": {
            "physical_entry_count": len(plugins),
            "logical_product_count": len(products),
        },
        "candidate_count": len(selected),
        "candidates": selected,
        "interpretation_note": (
            "Candidates are the intersection of the local installed logical-product inventory "
            "and a small reviewed pilot semantics table. Absence from this list does not prove "
            "a plugin lacks the capability, and inclusion does not authorize a Live mutation."
        ),
    }
