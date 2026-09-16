import pytest

from chibi_audio.sections import SectionMapError, build_section_map, position_context, resolve_section


def report(*locators, current=0.0, end=64.0):
    return {
        "set_signature": "sig",
        "current_song_time": current,
        "last_event_time": end,
        "song_length": end + 1.0,
        "locators": [
            {"index": i, "id": 100 + i, "name": name, "time": time}
            for i, (name, time) in enumerate(locators)
        ],
    }


def test_build_section_map_uses_next_locator_and_last_event():
    sections = build_section_map(
        report(("Intro", 0.0), ("Build", 16.0), ("Drop 1", 32.0), ("Bridge", 48.0))
    )
    assert [(s["name"], s["start_beat"], s["end_beat"]) for s in sections["sections"]] == [
        ("Intro", 0.0, 16.0),
        ("Build", 16.0, 32.0),
        ("Drop 1", 32.0, 48.0),
        ("Bridge", 48.0, 64.0),
    ]


def test_resolve_section_refuses_ambiguous_duplicate_name():
    sections = build_section_map(report(("Drop", 0.0), ("Break", 16.0), ("Drop", 32.0)))
    with pytest.raises(SectionMapError, match="ambiguous"):
        resolve_section(sections, "drop")
    assert resolve_section(sections, "drop", 2)["start_beat"] == 32.0


def test_position_context_uses_current_song_time():
    sections = build_section_map(
        report(("Intro", 0.0), ("Build", 16.0), ("Drop", 32.0), current=20.0)
    )
    context = position_context(sections)
    assert context["active_section"]["name"] == "Build"
    assert context["previous_section"]["name"] == "Intro"
    assert context["next_section"]["name"] == "Drop"


def test_leading_unlabeled_region_is_preserved():
    sections = build_section_map(report(("Intro", 8.0), ("Build", 16.0)))
    assert sections["leading_unlabeled"] == {
        "start_beat": 0.0,
        "end_beat": 8.0,
        "duration_beats": 8.0,
    }
