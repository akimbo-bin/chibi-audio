from chibi_audio.section_capture import build_section_capture_plan
from chibi_audio.sections import build_section_map


def section_map():
    return build_section_map(
        {
            "set_signature": "sig-sections",
            "current_song_time": 20.0,
            "last_event_time": 64.0,
            "song_length": 65.0,
            "locators": [
                {"index": 0, "id": 1, "name": "Intro", "time": 0.0},
                {"index": 1, "id": 2, "name": "Build", "time": 16.0},
                {"index": 2, "id": 3, "name": "Drop 1", "time": 32.0},
                {"index": 3, "id": 4, "name": "Bridge", "time": 48.0},
            ],
        }
    )


def test_section_capture_plan_is_not_started_and_capture_session_compatible():
    plan = build_section_capture_plan(
        section_map(),
        "drop 1",
        tap_specs=("1:Main:master", "2:BASS_PRE:pre_fx:BASS", "3:DRUMS:DRUMS"),
    )
    assert plan["effect_state"] == "NOT_STARTED"
    assert plan["set_signature"] == "sig-sections"
    assert plan["section"]["name"] == "Drop 1"
    assert plan["capture_request"]["start_beat"] == 32.0
    assert plan["capture_request"]["end_beat"] == 48.0
    assert plan["capture_request"]["duration_beats"] == 16.0
    assert plan["capture_request"]["taps"] == [
        {"tap_id": 1, "source_label": "Main", "target": "master", "signal_point": "post_fx"},
        {"tap_id": 2, "source_label": "BASS_PRE", "target": "BASS", "signal_point": "pre_fx"},
        {"tap_id": 3, "source_label": "DRUMS", "target": "DRUMS", "signal_point": "post_fx"},
    ]
    assert plan["ready_to_execute"] is True


def test_section_capture_plan_without_taps_stays_incomplete_but_exact():
    plan = build_section_capture_plan(section_map(), "Bridge")
    assert plan["effect_state"] == "NOT_STARTED"
    assert plan["capture_request"]["start_beat"] == 48.0
    assert plan["capture_request"]["end_beat"] == 64.0
    assert plan["capture_request"]["taps"] == []
    assert plan["ready_to_execute"] is False
