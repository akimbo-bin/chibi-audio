from __future__ import annotations

import pytest

from chibi_audio.plugins import (
    PLUGIN_INTENT_QUERY_SCHEMA_VERSION,
    PluginInfo,
    PluginIntentError,
    classify_plugin,
    query_installed_plugins,
    resolve_plugin_intent,
    supported_plugin_intents,
)


def _plugin(name: str, fmt: str, path: str, vendor: str | None = None) -> PluginInfo:
    return PluginInfo(
        name=name,
        format=fmt,
        path=path,
        vendor_hint=vendor,
        categories=classify_plugin(name),
    )


def _inventory() -> list[PluginInfo]:
    return [
        _plugin("StandardCLIP", "VST3", "C:/VST3/StandardCLIP.vst3", "SIR Audio Tools"),
        _plugin("StandardCLIP_x64", "VST2/DLL", "C:/VST2/StandardCLIP_x64.dll", "SIR Audio Tools"),
        _plugin("Newfangled Saturate", "VST3", "C:/VST3/Newfangled Saturate.vst3", "Newfangled Audio"),
        _plugin("Random Limiter", "VST3", "C:/VST3/Random Limiter.vst3", "Example"),
        _plugin("Trackspacer25", "VST3", "C:/VST3/Trackspacer25.vst3", "Wavesfactory"),
        _plugin("Trackspacer25_x64", "VST2/DLL", "C:/VST2/Trackspacer25_x64.dll", "Wavesfactory"),
        _plugin("FabFilter Pro-Q 3", "VST3", "C:/VST3/FabFilter Pro-Q 3.vst3", "FabFilter"),
        _plugin("Ozone 10 Dynamic EQ", "VST3", "C:/VST3/Ozone 10 Dynamic EQ.vst3", "iZotope"),
        _plugin("bx_dynEQ V2", "VST3", "C:/VST3/bx_dynEQ V2.vst3", "Brainworx"),
        _plugin("soothe2", "VST3", "C:/VST3/soothe2.vst3", "oeksound"),
    ]


def test_resolve_plugin_intent_accepts_reviewed_natural_language_aliases():
    assert resolve_plugin_intent("what transparent clippers do I own?") == "transparent_clipping"
    assert resolve_plugin_intent("which installed tool can dynamically create space here?") == "dynamic_space"
    assert resolve_plugin_intent("dynamic_space") == "dynamic_space"


def test_unknown_plugin_intent_fails_closed_with_supported_intents():
    with pytest.raises(PluginIntentError, match="supported intents: dynamic_space, transparent_clipping"):
        resolve_plugin_intent("make everything warmer somehow")


def test_transparent_clipping_query_is_installed_only_and_deduplicated():
    result = query_installed_plugins(_inventory(), "what transparent clippers do I own?")

    assert result["schema_version"] == PLUGIN_INTENT_QUERY_SCHEMA_VERSION
    assert result["effect_state"] == "NOT_STARTED"
    assert result["resolved_intent"] == "transparent_clipping"
    assert result["inventory"] == {
        "physical_entry_count": 10,
        "logical_product_count": 8,
    }

    names = [item["product_name"] for item in result["candidates"]]
    assert names == ["StandardCLIP", "Newfangled Saturate"]
    assert "Random Limiter" not in names

    standard = result["candidates"][0]
    assert standard["formats"] == ["VST3", "VST2/DLL"]
    assert standard["physical_entry_count"] == 2
    assert standard["confidence"] == "high"
    assert standard["capabilities"] == ["dedicated_clipping", "peak_control"]
    assert standard["evidence"] == {
        "inventory": "installed_logical_product",
        "semantics_source": "chibi-audio-curated-pilot/v1",
    }
    assert any("Transparency is a usage goal" in caveat for caveat in standard["caveats"])


def test_dynamic_space_query_preserves_capability_distinctions_and_order():
    result = query_installed_plugins(
        _inventory(),
        "which installed tool can dynamically create space here?",
    )

    assert result["resolved_intent"] == "dynamic_space"
    assert [item["product_name"] for item in result["candidates"]] == [
        "Trackspacer25",
        "FabFilter Pro-Q 3",
        "Ozone 10 Dynamic EQ",
        "bx_dynEQ V2",
        "soothe2",
    ]
    assert result["candidates"][0]["capabilities"] == [
        "source_aware_spectral_space",
        "dynamic_masking_relief",
    ]
    assert result["candidates"][1]["capabilities"] == [
        "dynamic_eq",
        "frequency_selective_control",
    ]
    assert result["candidates"][-1]["capabilities"] == [
        "dynamic_resonance_control",
        "spectral_cleanup",
    ]
    assert any(
        "not equivalent to source-target spectral ducking" in caveat
        for caveat in result["candidates"][-1]["caveats"]
    )


def test_plugin_intent_limit_is_bounded_and_deterministic():
    result = query_installed_plugins(_inventory(), "dynamic_space", limit=2)
    assert result["candidate_count"] == 2
    assert [item["rank"] for item in result["candidates"]] == [1, 2]
    assert [item["product_name"] for item in result["candidates"]] == [
        "Trackspacer25",
        "FabFilter Pro-Q 3",
    ]

    with pytest.raises(PluginIntentError, match="between 1 and 50"):
        query_installed_plugins(_inventory(), "dynamic_space", limit=0)


def test_supported_plugin_intents_are_small_and_explicit():
    intents = supported_plugin_intents()
    assert [item["intent"] for item in intents] == [
        "dynamic_space",
        "transparent_clipping",
    ]
    assert all(item["global_caveats"] for item in intents)
