from __future__ import annotations

import json
import sys

from chibi_audio import cli


class FakeLibrary:
    def __init__(self, root):
        self.root = root

    def register(self, path, **kwargs):
        return {"effect_state": "NOT_STARTED", "path": path, "kwargs": kwargs, "root": self.root}

    def reference_set(self, project, set_name):
        return [{"content_sha256": "a" * 64, "names": ["Ref"]}]

    def verify(self, digest):
        return {"effect_state": "NOT_STARTED", "content_sha256": digest, "verified": True}

    def compare_candidate(self, candidate, **kwargs):
        return {"effect_state": "NOT_STARTED", "candidate": candidate, "kwargs": kwargs}


def test_reference_register_cli_routes_to_local_registry(monkeypatch, capsys):
    monkeypatch.setattr(cli, "ReferenceLibrary", FakeLibrary)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chibi-audio",
            "reference-register",
            "ref.wav",
            "--library-root",
            "refs",
            "--name",
            "Rumble",
            "--project",
            "KISS",
            "--set-name",
            "main",
        ],
    )
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["effect_state"] == "NOT_STARTED"
    assert result["path"] == "ref.wav"
    assert result["kwargs"]["display_name"] == "Rumble"
    assert result["kwargs"]["project"] == "KISS"
    assert result["kwargs"]["set_name"] == "main"


def test_reference_compare_cli_routes_named_set(monkeypatch, capsys):
    monkeypatch.setattr(cli, "ReferenceLibrary", FakeLibrary)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chibi-audio",
            "reference-compare",
            "kiss.wav",
            "--library-root",
            "refs",
            "--project",
            "KISS",
            "--set-name",
            "club",
            "--label",
            "KISS drop",
        ],
    )
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["candidate"] == "kiss.wav"
    assert result["kwargs"]["project"] == "KISS"
    assert result["kwargs"]["set_name"] == "club"
    assert result["kwargs"]["candidate_label"] == "KISS drop"


def test_separator_status_cli_is_explicit(monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "demucs_capability",
        lambda: {"backend": "demucs", "available": False, "reason": "not installed"},
    )
    monkeypatch.setattr(sys, "argv", ["chibi-audio", "reference-separator-status"])
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result == {"backend": "demucs", "available": False, "reason": "not installed"}
