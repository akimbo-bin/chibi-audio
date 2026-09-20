from chibi_audio.set_reconcile import reconcile_saved_live


def saved_track(name, *, kind="AudioTrack", devices=None, track_id=None):
    return {
        "id": track_id,
        "type": kind,
        "name": name,
        "color": None,
        "group_id": None,
        "devices": devices or [],
    }


def live_track(name, *, index=0, track_id=100, foldable=False, devices=None):
    return {
        "id": track_id,
        "class": "Track",
        "index": index,
        "name": name,
        "is_foldable": foldable,
        "devices": devices or [],
    }


def test_unique_exact_name_binds_and_reports_fresh_live_identity():
    saved = {
        "path": "song.als",
        "tracks": [saved_track("BASS", track_id="17")],
    }
    live = {
        "result": {
            "set_signature": "abc123",
            "tracks": [live_track("BASS", index=4, track_id=9981)],
            "return_tracks": [],
        }
    }

    result = reconcile_saved_live(saved, live)

    assert result["effect_state"] == "NOT_STARTED"
    assert result["status"] == "RECONCILED"
    assert result["set_signature"] == "abc123"
    assert result["matched_count"] == 1
    assert result["matches"][0]["basis"] == "UNIQUE_NAME"
    assert result["matches"][0]["saved_id"] == "17"
    assert result["matches"][0]["live_id"] == 9981
    assert result["matches"][0]["live_index"] == 4


def test_unique_name_refuses_group_type_contradiction():
    saved = {"tracks": [saved_track("DRUMS", kind="GroupTrack")]}
    live = {"tracks": [live_track("DRUMS", foldable=False)], "return_tracks": []}

    result = reconcile_saved_live(saved, live)

    assert result["matched_count"] == 0
    assert result["contradiction_count"] == 1
    assert result["contradictions"][0]["reason"] == "TYPE_OR_PLACEMENT_CONTRADICTION"
    assert result["status"] == "PARTIAL"


def test_return_track_must_come_from_return_collection():
    saved = {"tracks": [saved_track("A", kind="ReturnTrack")]}

    wrong_collection = {
        "tracks": [live_track("A")],
        "return_tracks": [],
    }
    right_collection = {
        "tracks": [],
        "return_tracks": [live_track("A", track_id=501)],
    }

    assert reconcile_saved_live(saved, wrong_collection)["contradiction_count"] == 1
    matched = reconcile_saved_live(saved, right_collection)
    assert matched["matched_count"] == 1
    assert matched["matches"][0]["live_collection"] == "return_tracks"


def test_duplicate_names_remain_ambiguous_without_unique_device_evidence():
    saved = {
        "tracks": [
            saved_track("Audio", track_id="1"),
            saved_track("Audio", track_id="2"),
        ]
    }
    live = {
        "tracks": [
            live_track("Audio", index=0, track_id=101),
            live_track("Audio", index=1, track_id=102),
        ],
        "return_tracks": [],
    }

    result = reconcile_saved_live(saved, live)

    assert result["matched_count"] == 0
    assert result["ambiguous_count"] == 1
    assert len(result["ambiguous"][0]["saved_candidates"]) == 2
    assert len(result["ambiguous"][0]["live_candidates"]) == 2


def test_duplicate_names_disambiguate_only_by_unique_exact_nonempty_fingerprint():
    saved = {
        "tracks": [
            saved_track(
                "Audio",
                track_id="1",
                devices=[{"type": "Eq8", "plugin": None, "enabled": True}],
            ),
            saved_track(
                "Audio",
                track_id="2",
                devices=[{"type": "PluginDevice", "plugin": "soothe2", "enabled": True}],
            ),
        ]
    }
    live = {
        "tracks": [
            live_track(
                "Audio",
                index=9,
                track_id=109,
                devices=[
                    {
                        "id": 1,
                        "class": "PluginDevice",
                        "name": "soothe2",
                        "class_name": "PluginDevice",
                    }
                ],
            ),
            live_track(
                "Audio",
                index=3,
                track_id=103,
                devices=[
                    {
                        "id": 2,
                        "class": "Eq8Device",
                        "name": "EQ Eight",
                        "class_name": "Eq8",
                    }
                ],
            ),
        ],
        "return_tracks": [],
    }

    result = reconcile_saved_live(saved, live)

    assert result["status"] == "RECONCILED"
    assert result["matched_count"] == 2
    assert result["ambiguous_count"] == 0
    assert [item["basis"] for item in result["matches"]] == [
        "DEVICE_FINGERPRINT",
        "DEVICE_FINGERPRINT",
    ]
    assert [item["live_id"] for item in result["matches"]] == [103, 109]


def test_chibitap_is_ignored_when_comparing_device_fingerprints():
    saved = {
        "tracks": [
            saved_track(
                "Layer",
                track_id="1",
                devices=[{"type": "Eq8", "plugin": None, "enabled": True}],
            ),
            saved_track(
                "Layer",
                track_id="2",
                devices=[{"type": "PluginDevice", "plugin": "Saturn 2", "enabled": True}],
            ),
        ]
    }
    live = {
        "tracks": [
            live_track(
                "Layer",
                index=0,
                track_id=10,
                devices=[
                    {
                        "class": "Eq8Device",
                        "name": "EQ Eight",
                        "class_name": "Eq8",
                    },
                    {
                        "class": "PluginDevice",
                        "name": "ChibiTap",
                        "class_name": "PluginDevice",
                    },
                ],
            ),
            live_track(
                "Layer",
                index=1,
                track_id=11,
                devices=[
                    {
                        "class": "PluginDevice",
                        "name": "Saturn 2",
                        "class_name": "PluginDevice",
                    }
                ],
            ),
        ],
        "return_tracks": [],
    }

    result = reconcile_saved_live(saved, live)

    assert result["matched_count"] == 2
    assert result["ambiguous_count"] == 0
    assert result["matches"][0]["device_fingerprint"] == ["native:eq8"]


def test_unmatched_tracks_are_explicit_and_never_guessed():
    saved = {"tracks": [saved_track("Saved Only", track_id="1")]}
    live = {
        "set_signature": "sig",
        "tracks": [live_track("Live Only", track_id=77)],
        "return_tracks": [],
    }

    result = reconcile_saved_live(saved, live)

    assert result["status"] == "PARTIAL"
    assert result["saved_only_count"] == 1
    assert result["live_only_count"] == 1
    assert result["saved_only"][0]["saved_name"] == "Saved Only"
    assert result["live_only"][0]["live_id"] == 77


def test_blank_names_remain_explicit_unmatched_tracks():
    saved = {"tracks": [saved_track("", track_id="1")]}
    live = {
        "tracks": [live_track("", track_id=77)],
        "return_tracks": [],
    }

    result = reconcile_saved_live(saved, live)

    assert result["matched_count"] == 0
    assert result["saved_only_count"] == 1
    assert result["live_only_count"] == 1
    assert result["status"] == "PARTIAL"
