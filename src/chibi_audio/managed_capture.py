from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .capture import CaptureError
from .capture_session import CaptureSessionTap, run_capture_session
from .capture_topology import (
    CaptureTopologyLease,
    prepare_capture_topology,
    restore_capture_topology,
)
from .live import LiveBridgeClient, LiveCaptureClient


@dataclass(frozen=True, slots=True)
class ManagedCaptureResult:
    manifest_path: Path
    topology: CaptureTopologyLease
    restore: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "manifest_path": str(self.manifest_path),
            "topology": self.topology.as_dict(),
            "restore": self.restore,
        }


def run_managed_capture_session(
    *,
    experiment_id: str,
    taps: Iterable[CaptureSessionTap],
    output_dir: str | Path,
    start_beat: float,
    end_beat: float,
    expected_set_signature: str | None = None,
    remove_created_after: bool = False,
    host: str = "127.0.0.1",
    port: int = 18765,
    capture_root: str | Path | None = None,
    include_analysis: bool = True,
    poll_interval: float = 0.05,
    settle_seconds: float = 0.6,
    timeout_margin: float = 8.0,
    read_client: LiveBridgeClient | None = None,
    capture_client: LiveCaptureClient | None = None,
    capture_runner: Callable[..., Path] = run_capture_session,
) -> ManagedCaptureResult:
    specs = list(taps)
    lease = prepare_capture_topology(
        specs,
        expected_set_signature=expected_set_signature,
        host=host,
        port=port,
        read_client=read_client,
        capture_client=capture_client,
    )

    manifest_path: Path | None = None
    try:
        manifest_path = Path(
            capture_runner(
                experiment_id=experiment_id,
                taps=lease.session_specs(),
                output_dir=output_dir,
                start_beat=start_beat,
                end_beat=end_beat,
                host=host,
                port=port,
                capture_root=capture_root,
                include_analysis=include_analysis,
                poll_interval=poll_interval,
                settle_seconds=settle_seconds,
                timeout_margin=timeout_margin,
                expected_set_signature=lease.final_set_signature,
            )
        )
    except Exception as capture_exc:
        try:
            restore_capture_topology(
                lease,
                remove_created=True,
                expected_set_signature=lease.final_set_signature,
                host=host,
                port=port,
                read_client=read_client,
                capture_client=capture_client,
            )
        except Exception as cleanup_exc:  # noqa: BLE001 - preserve both failures.
            raise CaptureError(
                f"managed capture failed and topology restore was incomplete: {cleanup_exc}"
            ) from capture_exc
        raise

    try:
        restore = restore_capture_topology(
            lease,
            remove_created=remove_created_after,
            expected_set_signature=lease.final_set_signature,
            host=host,
            port=port,
            read_client=read_client,
            capture_client=capture_client,
        )
    except Exception as cleanup_exc:
        raise CaptureError(
            f"capture finalized at {manifest_path} but topology restore was incomplete: {cleanup_exc}"
        ) from cleanup_exc

    return ManagedCaptureResult(
        manifest_path=manifest_path,
        topology=lease,
        restore=restore,
    )
