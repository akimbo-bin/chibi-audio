from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import chibi_audio.reference_separation as separation
from chibi_audio.reference_separation import (
    DemucsSeparatorBackend,
    SEPARATION_MANIFEST_SCHEMA_VERSION,
    STEM_ANALYSIS_SCHEMA_VERSION,
    StemSeparationError,
    analyze_separated_stems,
)


class FakeReport:
    def __init__(self, role: str, digest: str):
        self.role = role
        self.digest = digest

    def to_dict(self):
        return {"schema_version": "chibi-audio-analysis/v1", "content_sha256": self.digest, "role": self.role}


class FakeService:
    def __init__(self):
        self.calls = []

    def analyze(self, path, request, *, cache_dir=None, content_sha256=None):
        role = Path(path).stem
        self.calls.append((role, content_sha256, cache_dir))
        return FakeReport(role, content_sha256)


def test_demucs_backend_reports_unavailable_explicitly(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(separation.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(separation.shutil, "which", lambda name: None)
    backend = DemucsSeparatorBackend(runtime_root=tmp_path / "missing-runtime")
    capability = backend.capability()
    assert capability["available"] is False
    assert "not installed" in capability["reason"]
    with pytest.raises(StemSeparationError, match="not installed"):
        backend._command(Path("x.wav"), Path("out"))


def test_demucs_separation_is_sha_cached_and_preserves_source(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "reference.wav"
    source.write_bytes(b"reference-source")
    original = source.read_bytes()
    monkeypatch.setattr(separation.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(separation.shutil, "which", lambda name: None)
    calls = []

    def fake_run(command, check, capture_output, text):
        calls.append(command)
        output_root = Path(command[command.index("-o") + 1])
        bundle = output_root / "htdemucs" / source.stem
        bundle.mkdir(parents=True, exist_ok=True)
        for role in separation.EXPECTED_STEMS:
            (bundle / f"{role}.wav").write_bytes(f"{role}-estimated".encode())
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(separation.subprocess, "run", fake_run)
    backend = DemucsSeparatorBackend(model="htdemucs")
    first = backend.separate(source, output_root=tmp_path / "separated")
    second = backend.separate(source, output_root=tmp_path / "separated")

    assert first["schema_version"] == SEPARATION_MANIFEST_SCHEMA_VERSION
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert len(first["stems"]) == 4
    assert [row["role"] for row in first["stems"]] == list(separation.EXPECTED_STEMS)
    assert len(calls) == 1
    assert source.read_bytes() == original
    assert "model estimates" in first["interpretation_note"]


def test_stem_analysis_verifies_hashes_and_returns_structured_reports(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "reference.wav"
    source.write_bytes(b"reference-source")
    monkeypatch.setattr(separation.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(separation.shutil, "which", lambda name: None)

    def fake_run(command, check, capture_output, text):
        output_root = Path(command[command.index("-o") + 1])
        bundle = output_root / "htdemucs" / source.stem
        bundle.mkdir(parents=True, exist_ok=True)
        for role in separation.EXPECTED_STEMS:
            (bundle / f"{role}.wav").write_bytes(f"{role}-estimated".encode())
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(separation.subprocess, "run", fake_run)
    backend = DemucsSeparatorBackend()
    result = backend.separate(source, output_root=tmp_path / "separated")
    service = FakeService()
    analysis = analyze_separated_stems(result["manifest"], service=service, cache_dir=tmp_path / "cache")

    assert analysis["schema_version"] == STEM_ANALYSIS_SCHEMA_VERSION
    assert analysis["effect_state"] == "NOT_STARTED"
    assert [row["role"] for row in analysis["stems"]] == list(separation.EXPECTED_STEMS)
    assert len(service.calls) == 4

    first_stem = Path(analysis["stems"][0]["path"])
    first_stem.write_bytes(b"tampered")
    with pytest.raises(StemSeparationError, match="identity does not verify"):
        analyze_separated_stems(result["manifest"], service=service)


def test_incomplete_demucs_bundle_fails_closed(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "reference.wav"
    source.write_bytes(b"source")
    monkeypatch.setattr(separation.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(separation.shutil, "which", lambda name: None)

    def fake_run(command, check, capture_output, text):
        output_root = Path(command[command.index("-o") + 1])
        bundle = output_root / "htdemucs" / source.stem
        bundle.mkdir(parents=True, exist_ok=True)
        (bundle / "drums.wav").write_bytes(b"drums")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(separation.subprocess, "run", fake_run)
    with pytest.raises(StemSeparationError, match="complete"):
        DemucsSeparatorBackend().separate(source, output_root=tmp_path / "separated")


def test_demucs_backend_discovers_managed_runtime(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(separation.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(separation.shutil, "which", lambda name: None)
    runtime = tmp_path / "runtime"
    scripts = runtime / "Scripts"
    scripts.mkdir(parents=True)
    executable = scripts / "demucs.exe"
    executable.write_bytes(b"managed-demucs")
    python_executable = scripts / "python.exe"
    python_executable.write_bytes(b"managed-python")

    backend = DemucsSeparatorBackend(runtime_root=runtime)
    capability = backend.capability()
    assert capability["available"] is True
    assert capability["execution_mode"] == "managed_runtime"
    assert capability["executable"] == str(executable)
    assert capability["python_executable"] == str(python_executable)
    command = backend._command(Path("source.wav"), Path("out"))
    assert command[0] == str(executable)


def test_invalid_demucs_executable_override_fails_closed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(separation.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(separation.shutil, "which", lambda name: None)
    missing = tmp_path / "missing-demucs.exe"
    monkeypatch.setenv("CHIBI_AUDIO_DEMUCS_EXECUTABLE", str(missing))
    capability = separation.demucs_capability(runtime_root=tmp_path / "runtime")
    assert capability["available"] is False
    assert capability["execution_mode"] == "invalid_override"
    assert "does not point to a file" in capability["reason"]
