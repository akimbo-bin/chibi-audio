from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


SCHEMA_VERSION = "chibi-audio-analysis/v1"


class AnalysisCapability(StrEnum):
    METADATA = "audio.metadata"
    LEVELS = "audio.levels"
    ACTIVITY = "audio.activity"
    STEREO = "audio.stereo"
    SPECTRUM = "audio.spectrum"
    TRANSIENTS = "audio.transients"
    TEXTURE = "audio.texture"
    STEREO_BANDS = "audio.stereo.bands"
    LOUDNESS = "audio.loudness"
    MIR_ONSETS = "audio.mir.onsets"
    MIR_BEATS = "audio.mir.beats"
    MIR_TONAL = "audio.mir.tonal"
    MIR_KEY = "audio.mir.key"
    MIR_STRUCTURE = "audio.mir.structure"
    MIR_PITCH = "audio.mir.pitch"
    MIR_TRANSCRIPTION = "audio.mir.transcription"
    SEMANTIC = "audio.semantic"


class AnalysisCost(StrEnum):
    CHEAP = "CHEAP"
    MODERATE = "MODERATE"
    EXPENSIVE = "EXPENSIVE"

    @property
    def rank(self) -> int:
        return {
            AnalysisCost.CHEAP: 0,
            AnalysisCost.MODERATE: 1,
            AnalysisCost.EXPENSIVE: 2,
        }[self]


BASIC_CAPABILITIES = frozenset(
    {
        AnalysisCapability.METADATA,
        AnalysisCapability.LEVELS,
        AnalysisCapability.ACTIVITY,
        AnalysisCapability.STEREO,
    }
)


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    capabilities: frozenset[AnalysisCapability] = BASIC_CAPABILITIES
    max_cost: AnalysisCost = AnalysisCost.CHEAP
    start_seconds: float | None = None
    end_seconds: float | None = None
    sample_rate: int = 48000
    silence_threshold_dbfs: float = -60.0
    spectral_window_size: int = 4096
    spectral_max_windows: int = 16
    spectral_rolloff_fraction: float = 0.85
    semantic_queries: tuple[str, ...] = ()
    semantic_max_windows: int = 12
    transcription_max_notes: int = 512

    def __post_init__(self) -> None:
        capabilities = frozenset(AnalysisCapability(value) for value in self.capabilities)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "max_cost", AnalysisCost(self.max_cost))

        semantic_queries = tuple(str(value).strip() for value in self.semantic_queries)
        object.__setattr__(self, "semantic_queries", semantic_queries)

        if not capabilities:
            raise ValueError("at least one analysis capability is required")
        if self.start_seconds is not None and self.start_seconds < 0:
            raise ValueError("start_seconds must be >= 0")
        if self.end_seconds is not None and self.end_seconds < 0:
            raise ValueError("end_seconds must be >= 0")
        if (
            self.start_seconds is not None
            and self.end_seconds is not None
            and self.end_seconds <= self.start_seconds
        ):
            raise ValueError("end_seconds must be greater than start_seconds")
        if self.sample_rate < 8000 or self.sample_rate > 384000:
            raise ValueError("sample_rate is outside the supported range")
        if not -160.0 <= self.silence_threshold_dbfs <= 0.0:
            raise ValueError("silence_threshold_dbfs must be between -160 and 0")
        if self.spectral_window_size < 64 or self.spectral_window_size & (self.spectral_window_size - 1):
            raise ValueError("spectral_window_size must be a power of two >= 64")
        if not 1 <= self.spectral_max_windows <= 256:
            raise ValueError("spectral_max_windows must be between 1 and 256")
        if not 0.5 <= self.spectral_rolloff_fraction < 1.0:
            raise ValueError("spectral_rolloff_fraction must be in [0.5, 1.0)")
        if len(semantic_queries) > 64:
            raise ValueError("semantic_queries is limited to 64 prompts")
        if any(not value for value in semantic_queries):
            raise ValueError("semantic_queries cannot contain empty prompts")
        if any(len(value) > 240 for value in semantic_queries):
            raise ValueError("each semantic query is limited to 240 characters")
        if AnalysisCapability.SEMANTIC in capabilities and not semantic_queries:
            raise ValueError("audio.semantic requires at least one semantic query")
        if not 1 <= self.semantic_max_windows <= 64:
            raise ValueError("semantic_max_windows must be between 1 and 64")
        if not 1 <= self.transcription_max_notes <= 4096:
            raise ValueError("transcription_max_notes must be between 1 and 4096")

    def cache_payload(self) -> dict[str, Any]:
        return {
            "capabilities": sorted(value.value for value in self.capabilities),
            "max_cost": self.max_cost.value,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "sample_rate": self.sample_rate,
            "silence_threshold_dbfs": self.silence_threshold_dbfs,
            "spectral_window_size": self.spectral_window_size,
            "spectral_max_windows": self.spectral_max_windows,
            "spectral_rolloff_fraction": self.spectral_rolloff_fraction,
            "semantic_queries": list(self.semantic_queries),
            "semantic_max_windows": self.semantic_max_windows,
            "transcription_max_notes": self.transcription_max_notes,
        }


@dataclass(frozen=True, slots=True)
class AnalyzerDescriptor:
    name: str
    version: str
    capabilities: frozenset[AnalysisCapability]
    cost: AnalysisCost
    implementation: str
    upstream: str | None = None
    license: str | None = None
    available: bool = True
    unavailable_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "capabilities": sorted(value.value for value in self.capabilities),
            "cost": self.cost.value,
            "implementation": self.implementation,
            "upstream": self.upstream,
            "license": self.license,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
        }


@dataclass(slots=True)
class AnalysisReport:
    source_name: str
    source_size_bytes: int
    requested_capabilities: list[str]
    executed_analyzers: list[dict[str, Any]]
    measurements: dict[str, Any]
    content_sha256: str | None = None
    analysis_key: str | None = None
    cache_hit: bool = False
    schema_version: str = SCHEMA_VERSION
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AnalysisReport":
        return cls(**value)
