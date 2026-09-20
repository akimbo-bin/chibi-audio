from __future__ import annotations

import gzip
from pathlib import Path

from chibi_audio.als import SET_MAP_SCHEMA_VERSION, inspect_set
from chibi_audio.plugins import (
    PLUGIN_CATALOG_SCHEMA_VERSION,
    catalog_dict,
    classify_plugin,
    discover_plugins,
    group_logical_products,
    logical_product_key,
    normalize_plugin_name,
    reconcile_plugin_references,
)


def _write_als(path: Path) -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Ableton>
  <LiveSet>
    <Tracks>
      <GroupTrack Id="10">
        <Name>
          <UserName Value="DRUMS" />
          <EffectiveName Value="DRUMS" />
        </Name>
        <Color Value="3" />
        <TrackGroupId Value="-1" />
        <DeviceChain>
          <Devices>
            <Eq8>
              <On><Manual Value="true" /></On>
            </Eq8>
          </Devices>
          <ArrangerAutomation>
            <Events />
          </ArrangerAutomation>
        </DeviceChain>
      </GroupTrack>
      <AudioTrack Id="11">
        <Name>
          <UserName Value="Kick Layer" />
          <EffectiveName Value="Kick Layer" />
        </Name>
        <Color Value="4" />
        <TrackGroupId Value="10" />
        <DeviceChain>
          <Devices>
            <PluginDevice>
              <On><Manual Value="true" /></On>
              <PluginDesc>
                <BrowserContentPath Value="query:Plugins#VST3:oeksound:soothe%202" />
              </PluginDesc>
            </PluginDevice>
          </Devices>
          <ArrangerAutomation>
            <Events>
              <AudioClip Time="32">
                <CurrentStart Value="32" />
                <CurrentEnd Value="40" />
                <Disabled Value="false" />
              </AudioClip>
            </Events>
          </ArrangerAutomation>
        </DeviceChain>
      </AudioTrack>
    </Tracks>
  </LiveSet>
</Ableton>
"""
    with gzip.open(path, "wb") as stream:
        stream.write(xml.encode("utf-8"))


def test_set_map_has_versioned_schema_hierarchy_and_decoded_plugin_refs(tmp_path):
    source = tmp_path / "Test.als"
    _write_als(source)

    report = inspect_set(source)

    assert report["schema_version"] == SET_MAP_SCHEMA_VERSION
    assert report["effect_state"] == "NOT_STARTED"
    assert report["track_count"] == 2
    assert report["named_track_count"] == 2
    assert report["track_type_counts"] == {"AudioTrack": 1, "GroupTrack": 1}
    assert report["plugins"] == ["soothe 2"]
    assert report["plugin_count"] == 1
    assert report["group_relationships"] == [
        {"track_id": "11", "track_name": "Kick Layer", "group_id": "10"}
    ]

    group, child = report["tracks"]
    assert group["id"] == "10"
    assert group["group_id"] == "-1"
    assert child["group_id"] == "10"
    assert child["devices"][0]["plugin"] == "soothe 2"
    assert child["arrangement_clips"][0] == {
        "type": "AudioClip",
        "start_beat": 32.0,
        "end_beat": 40.0,
        "disabled": False,
    }


def test_plugin_name_normalization_preserves_versions_but_removes_arch_suffix():
    assert normalize_plugin_name("Serum%202_x64") == "Serum 2"
    assert normalize_plugin_name("FabFilter Pro-Q 3®") == "FabFilter Pro-Q 3"
    assert logical_product_key("soothe2_x64") == logical_product_key("soothe2")
    assert logical_product_key("Pro-Q 3") != logical_product_key("Pro-Q 4")


def test_kiss_processing_names_have_useful_role_categories():
    assert classify_plugin("kHs Bitcrush") == ["distortion_saturation"]
    assert classify_plugin("Tube-Tech CL 1B") == ["compressor_dynamics"]
    assert classify_plugin("API-2500 Stereo") == ["compressor_dynamics"]


def test_catalog_groups_cross_format_duplicates_into_logical_products(tmp_path):
    root = tmp_path / "plugins"
    vendor = root / "VendorA"
    vendor.mkdir(parents=True)

    vst3 = vendor / "soothe2.vst3"
    (vst3 / "Contents" / "x86_64-win").mkdir(parents=True)
    # This is an implementation DLL inside the VST3 bundle and must not become
    # a second VST2 plugin.
    (vst3 / "Contents" / "x86_64-win" / "soothe2.dll").write_bytes(b"internal")

    (vendor / "soothe2_x64.dll").write_bytes(b"vst2")
    (vendor / "soothe2.clap").write_bytes(b"clap")
    (vendor / "Pro-L 2.vst3").mkdir()
    (vendor / "Serum%202.clap").write_bytes(b"clap")

    entries = discover_plugins([root])
    catalog = catalog_dict(entries)

    assert catalog["schema_version"] == PLUGIN_CATALOG_SCHEMA_VERSION
    assert catalog["effect_state"] == "NOT_STARTED"
    assert catalog["plugin_count"] == 5
    assert catalog["logical_product_count"] == 3

    products = {item["product_key"]: item for item in catalog["products"]}
    soothe = products[logical_product_key("soothe2")]
    assert soothe["name"] == "soothe2"
    assert soothe["entry_count"] == 3
    assert soothe["formats"] == ["VST3", "CLAP", "VST2/DLL"]
    assert len(soothe["paths"]) == 3
    assert soothe["vendor_hints"] == ["VendorA"]
    assert soothe["categories"] == ["spectral_cleanup"]
    assert soothe["roles"] == ["mixing", "mastering"]

    limiter = products[logical_product_key("Pro-L 2")]
    assert limiter["categories"] == ["limiter_clipper"]
    assert limiter["roles"] == ["mastering"]
    instrument = products[logical_product_key("Serum 2")]
    assert instrument["name"] == "Serum 2"
    assert instrument["categories"] == ["instrument"]
    assert instrument["roles"] == ["instrument"]

    assert catalog["role_counts"]["mixing"] >= 1
    assert catalog["role_counts"]["mastering"] >= 1
    assert catalog["role_counts"]["instrument"] >= 1
    assert catalog["role_counts"]["modulation"] == 0

    # Backward-compatible raw category counts still reflect physical entries,
    # while logical counts are product-level and do not overcount formats.
    assert catalog["category_counts"]["spectral_cleanup"] == 3
    assert catalog["logical_category_counts"]["spectral_cleanup"] == 1
    assert catalog["logical_category_counts"]["limiter_clipper"] == 1
    assert catalog["logical_category_counts"]["instrument"] == 1


def test_same_name_with_different_format_naming_punctuation_still_groups(tmp_path):
    root = tmp_path / "plugins"
    root.mkdir()
    (root / "Trackspacer 2.5.vst3").mkdir()
    (root / "Trackspacer_2.5_x64.dll").write_bytes(b"vst2")

    catalog = catalog_dict(discover_plugins([root]))

    assert catalog["plugin_count"] == 2
    assert catalog["logical_product_count"] == 1
    assert catalog["products"][0]["formats"] == ["VST3", "VST2/DLL"]
    assert catalog["products"][0]["categories"] == ["spectral_cleanup"]


def test_saved_references_reconcile_to_direct_and_vendor_prefixed_products(tmp_path):
    root = tmp_path / "plugins"
    fabfilter = root / "FabFilter"
    wavesfactory = root / "Wavesfactory"
    fabfilter.mkdir(parents=True)
    wavesfactory.mkdir(parents=True)

    (fabfilter / "FabFilter Saturn 2.vst3").mkdir()
    (fabfilter / "FabFilter Saturn 2_x64.dll").write_bytes(b"vst2")
    (wavesfactory / "Trackspacer25.vst3").mkdir()
    (wavesfactory / "Trackspacer25.dll").write_bytes(b"vst2")
    (root / "Serum2.vst3").mkdir()

    products = group_logical_products(discover_plugins([root]))
    result = reconcile_plugin_references(
        ["Saturn 2", "Trackspacer 2.5", "Serum 2", "Missing Plugin"],
        products,
    )

    assert result["schema_version"] == "chibi-audio-plugin-reconciliation/v1"
    assert result["effect_state"] == "NOT_STARTED"
    assert result["reference_count"] == 4
    assert result["resolved_count"] == 3
    assert result["ambiguous_count"] == 0
    assert result["unresolved_count"] == 1

    resolved = {item["reference"]: item for item in result["resolved"]}
    assert resolved["Saturn 2"]["product_name"] == "FabFilter Saturn 2"
    assert resolved["Saturn 2"]["formats"] == ["VST3", "VST2/DLL"]
    assert resolved["Saturn 2"]["roles"] == ["mixing", "mastering"]
    assert resolved["Trackspacer 2.5"]["product_name"] == "Trackspacer25"
    assert resolved["Serum 2"]["product_name"] == "Serum2"
    assert resolved["Serum 2"]["roles"] == ["instrument"]
    assert result["unresolved"][0]["reference"] == "Missing Plugin"
