from __future__ import annotations

import hashlib
from importlib import metadata, util
import math
import os
from pathlib import Path
from typing import Any

from .io import AnalysisContext, _np, decode_audio_segment
from .models import AnalysisCapability, AnalysisCost, AnalyzerDescriptor


_MODEL_DIR_ENV = "CHIBI_AUDIO_CLAP_MODEL_DIR"
_MODEL_SHA_ENV = "CHIBI_AUDIO_CLAP_MODEL_SHA256"


def _normalize_sha256(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        return None
    return normalized


def _model_weight_path(model_dir: Path) -> Path | None:
    for name in ("model.safetensors", "pytorch_model.bin"):
        candidate = model_dir / name
        if candidate.is_file():
            return candidate
    return None


def _model_identity_sha256(model_dir: Path) -> str:
    relevant_names = (
        "config.json",
        "preprocessor_config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "vocab.json",
        "merges.txt",
        "model.safetensors",
        "pytorch_model.bin",
    )
    digest = hashlib.sha256()
    found = 0
    for name in relevant_names:
        path = model_dir / name
        if not path.is_file():
            continue
        found += 1
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    if found == 0:
        raise RuntimeError("local CLAP model directory contains no identity-bearing files")
    return digest.hexdigest()


def hf_clap_descriptor() -> AnalyzerDescriptor:
    reasons: list[str] = []
    versions: list[str] = []
    for module_name, package_name in (("torch", "torch"), ("transformers", "transformers")):
        if util.find_spec(module_name) is None:
            reasons.append(f"{package_name} is not installed")
            continue
        try:
            versions.append(f"{package_name}-{metadata.version(package_name)}")
        except metadata.PackageNotFoundError:
            reasons.append(f"{package_name} package metadata is unavailable")

    model_dir_value = os.environ.get(_MODEL_DIR_ENV)
    model_dir = Path(model_dir_value).expanduser() if model_dir_value else None
    if model_dir is None:
        reasons.append(f"{_MODEL_DIR_ENV} is not configured")
    elif not model_dir.is_dir():
        reasons.append(f"{_MODEL_DIR_ENV} does not point to a local directory")
    else:
        if not (model_dir / "config.json").is_file():
            reasons.append("local CLAP model directory is missing config.json")
        if not (model_dir / "preprocessor_config.json").is_file():
            reasons.append("local CLAP model directory is missing preprocessor_config.json")
        if _model_weight_path(model_dir) is None:
            reasons.append("local CLAP model directory is missing a supported single-file weight checkpoint")

    declared_sha = _normalize_sha256(os.environ.get(_MODEL_SHA_ENV))
    if declared_sha is None:
        reasons.append(f"{_MODEL_SHA_ENV} must contain the exact local CLAP model identity SHA-256")

    version = "+".join(versions) if versions else "unavailable"
    if declared_sha is not None:
        version = f"{version}+model-{declared_sha[:16]}"

    return AnalyzerDescriptor(
        name="hf_clap_semantic",
        version=version,
        capabilities=frozenset({AnalysisCapability.SEMANTIC}),
        cost=AnalysisCost.EXPENSIVE,
        implementation="deterministic-window local Hugging Face CLAP audio/text cosine evidence",
        upstream="huggingface/transformers + LAION CLAP",
        license="Apache-2.0",
        available=not reasons,
        unavailable_reason="; ".join(reasons) if reasons else None,
    )


def _window_starts(frame_count: int, window_size: int, max_windows: int, np) -> list[int]:
    if frame_count <= window_size:
        return [0]
    needed = math.ceil(frame_count / window_size)
    count = min(max_windows, needed)
    max_start = frame_count - window_size
    if count == 1:
        return [max_start // 2]
    return [int(round(value)) for value in np.linspace(0, max_start, count)]


class HfClapSemanticAnalyzer:
    def __init__(self) -> None:
        self._processor = None
        self._model = None
        self._verified_model_sha: str | None = None

    @property
    def descriptor(self) -> AnalyzerDescriptor:
        return hf_clap_descriptor()

    def _load(self):
        descriptor = self.descriptor
        if not descriptor.available:
            raise RuntimeError(descriptor.unavailable_reason or "local CLAP runtime is unavailable")

        model_dir = Path(os.environ[_MODEL_DIR_ENV]).expanduser()
        expected_sha = _normalize_sha256(os.environ.get(_MODEL_SHA_ENV))
        weight_path = _model_weight_path(model_dir)
        if expected_sha is None or weight_path is None:
            raise RuntimeError("local CLAP model identity is incomplete")
        if self._verified_model_sha != expected_sha:
            actual_sha = _model_identity_sha256(model_dir)
            if actual_sha != expected_sha:
                raise RuntimeError(
                    "local CLAP model identity does not match CHIBI_AUDIO_CLAP_MODEL_SHA256"
                )
            self._verified_model_sha = actual_sha

        if self._processor is None or self._model is None:
            from transformers import AutoProcessor, ClapModel

            processor = AutoProcessor.from_pretrained(
                model_dir,
                local_files_only=True,
            )
            model = ClapModel.from_pretrained(
                model_dir,
                local_files_only=True,
            )
            enable_fusion = bool(getattr(model.config.audio_config, "enable_fusion", False))
            if enable_fusion:
                raise RuntimeError(
                    "Chibi semantic analysis currently requires an unfused CLAP checkpoint "
                    "so deterministic rand_trunc preprocessing can be guaranteed"
                )
            model.eval()
            self._processor = processor
            self._model = model

        return self._processor, self._model, expected_sha

    def analyze(self, context: AnalysisContext) -> dict[str, Any]:
        processor, model, model_sha = self._load()
        import torch

        np = _np()
        feature_extractor = processor.feature_extractor
        sample_rate = int(feature_extractor.sampling_rate)
        max_samples = int(feature_extractor.nb_max_samples)

        decoded = decode_audio_segment(
            context.path,
            context.request,
            sample_rate=sample_rate,
            channels=1,
        )
        mono = decoded[:, 0].astype(np.float32, copy=False)
        starts = _window_starts(
            len(mono),
            max_samples,
            context.request.semantic_max_windows,
            np,
        )
        queries = list(context.request.semantic_queries)

        text_inputs = processor(
            text=queries,
            padding=True,
            return_tensors="pt",
        )
        with torch.inference_mode():
            text_features = model.get_text_features(**text_inputs)
            text_features = torch.nn.functional.normalize(text_features, dim=-1)

            per_window = []
            for start in starts:
                window = mono[start : start + max_samples]
                audio_inputs = processor(
                    audio=window,
                    sampling_rate=sample_rate,
                    truncation="rand_trunc",
                    padding="repeatpad",
                    return_tensors="pt",
                )
                audio_features = model.get_audio_features(**audio_inputs)
                audio_features = torch.nn.functional.normalize(audio_features, dim=-1)
                similarity = audio_features @ text_features.T
                per_window.append(similarity[0].detach().cpu())

        matrix = torch.stack(per_window, dim=0)
        mean_scores = matrix.mean(dim=0)
        rankings = torch.argsort(mean_scores, descending=True).tolist()
        absolute_start = context.absolute_start_seconds
        entries = []
        for rank, query_index in enumerate(rankings, start=1):
            scores = matrix[:, query_index]
            strongest_index = int(torch.argmax(scores).item())
            window_start = starts[strongest_index]
            window_end = min(window_start + max_samples, len(mono))
            entries.append(
                {
                    "rank": rank,
                    "query": queries[query_index],
                    "mean_cosine_similarity": float(mean_scores[query_index].item()),
                    "min_window_cosine_similarity": float(torch.min(scores).item()),
                    "max_window_cosine_similarity": float(torch.max(scores).item()),
                    "strongest_window": {
                        "start_seconds": absolute_start + window_start / sample_rate,
                        "end_seconds": absolute_start + window_end / sample_rate,
                    },
                }
            )

        return {
            AnalysisCapability.SEMANTIC.value: {
                "queries_ranked": entries,
                "window_count": len(starts),
                "window_duration_seconds_max": max_samples / sample_rate,
                "sampling_rate": sample_rate,
                "window_selection": "deterministic evenly spaced windows over the exact requested range",
                "model_identity_sha256": model_sha,
                "embedding_output": "not returned; only cosine evidence is exposed",
                "interpretation_note": (
                    "semantic cosine similarity is relative signal evidence for the supplied text queries; "
                    "it is not a calibrated probability or a subjective quality score"
                ),
            }
        }
