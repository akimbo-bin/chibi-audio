from __future__ import annotations

import argparse
import json
from pathlib import Path

from .als import dumps_report, inspect_set
from .ab_compare import create_level_matched_ab
from .audio import analyze_audio
from .harshness import analyze_harshness
from .capture import CaptureError
from .capture_finalize import TapCaptureInput, finalize_aligned_captures
from .capture_session import CaptureSessionTap, parse_session_tap, run_capture_session
from .library import places_dict, read_user_places
from .live import LiveBridgeClient
from .organization import build_project_context, load_organization_schema, write_project_context
from .plugins import catalog_dict, discover_plugins
from .reference_library import ReferenceLibrary
from .reference_separation import DemucsSeparatorBackend, analyze_separated_stems, demucs_capability
from .reference_stem_compare import compare_stem_analyses


def _tap_capture_arg(value: str) -> TapCaptureInput:
    try:
        tap_text, label, path = value.split(":", 2)
        tap_id = int(tap_text)
        return TapCaptureInput(tap_id, label, Path(path))
    except (ValueError, CaptureError) as exc:
        raise argparse.ArgumentTypeError(
            "tap must use TAP_ID:LABEL:PATH, for example 1:Main:C:/captures/main.wav"
        ) from exc


def _session_tap_arg(value: str) -> CaptureSessionTap:
    try:
        return parse_session_tap(value)
    except CaptureError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def main() -> None:
    parser = argparse.ArgumentParser(prog="chibi-audio")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect-set", help="Read an Ableton .als file without modifying it")
    inspect.add_argument("path")

    organize = sub.add_parser("organize", help="Build a read-only project organization/context plan")
    organize.add_argument("path", help="Ableton .als file to inspect")
    organize.add_argument("--schema", default="PROJECT_ORGANIZATION.md")
    organize.add_argument("--output", help="Optional durable JSON context output path")

    plugins = sub.add_parser("scan-plugins", help="Read installed audio plugin locations without modifying them")
    plugins.add_argument("--root", action="append", default=None, help="Optional plugin root; repeat to scan multiple roots")

    places = sub.add_parser("scan-ableton-places", help="Read user Places from Ableton Library.cfg")
    places.add_argument("library_cfg")

    live_status = sub.add_parser("live-status", help="Read the local Chibi Audio bridge status")
    live_status.add_argument("--host", default="127.0.0.1")
    live_status.add_argument("--port", type=int, default=18765)

    live_summary = sub.add_parser("live-summary", help="Read a structured summary of the currently open Live Set")
    live_summary.add_argument("--host", default="127.0.0.1")
    live_summary.add_argument("--port", type=int, default=18765)
    live_summary.add_argument("--track-limit", type=int, default=140)
    live_summary.add_argument("--device-limit", type=int, default=24)

    audio = sub.add_parser("analyze-audio", help="Measure a local audio file without modifying it")
    audio.add_argument("path")
    audio.add_argument("--window-seconds", type=float, default=12.0)

    harshness = sub.add_parser("analyze-harshness", help="Rank time-localized bright/attack-heavy events")
    harshness.add_argument("path")
    harshness.add_argument("--top-events", type=int, default=12)
    level_match = sub.add_parser("level-match-ab", help="Create downward-only integrated-loudness-matched A/B listening artifacts")
    level_match.add_argument("left")
    level_match.add_argument("right")
    level_match.add_argument("--output-dir", required=True)
    level_match.add_argument("--comparison-id", required=True)
    level_match.add_argument("--left-label", default="A")
    level_match.add_argument("--right-label", default="B")

    reference_register = sub.add_parser("reference-register", help="Register a local reference track by content SHA without copying audio")
    reference_register.add_argument("path")
    reference_register.add_argument("--library-root", required=True)
    reference_register.add_argument("--name")
    reference_register.add_argument("--project")
    reference_register.add_argument("--set-name")
    reference_register.add_argument("--window-seconds", type=float, default=12.0)

    reference_set = sub.add_parser("reference-set", help="List a named local reference set")
    reference_set.add_argument("--library-root", required=True)
    reference_set.add_argument("--project", required=True)
    reference_set.add_argument("--set-name", default="default")

    reference_verify = sub.add_parser("reference-verify", help="Reconcile a registered reference against its content SHA")
    reference_verify.add_argument("content_sha256")
    reference_verify.add_argument("--library-root", required=True)

    reference_compare = sub.add_parser("reference-compare", help="Compare one local candidate against a named reference set")
    reference_compare.add_argument("candidate")
    reference_compare.add_argument("--library-root", required=True)
    reference_compare.add_argument("--project", required=True)
    reference_compare.add_argument("--set-name", default="default")
    reference_compare.add_argument("--label")
    reference_compare.add_argument("--window-seconds", type=float, default=12.0)

    separator_status = sub.add_parser("reference-separator-status", help="Report local Demucs stem-separation capability")

    reference_separate = sub.add_parser("reference-separate", help="Run local Demucs separation into a SHA-keyed cache")
    reference_separate.add_argument("path")
    reference_separate.add_argument("--output-root", required=True)
    reference_separate.add_argument("--model", default="htdemucs")
    reference_separate.add_argument("--device")

    reference_stems = sub.add_parser("reference-analyze-stems", help="Analyze a verified four-stem separation manifest")
    reference_stems.add_argument("manifest")
    reference_stems.add_argument("--cache-dir")

    reference_stem_compare = sub.add_parser("reference-compare-stems", help="Compare two verified four-stem analysis reports")
    reference_stem_compare.add_argument("baseline")
    reference_stem_compare.add_argument("candidate")
    reference_stem_compare.add_argument("--baseline-label", default="baseline")
    reference_stem_compare.add_argument("--candidate-label", default="candidate")

    finalize = sub.add_parser(
        "finalize-capture",
        help="Crop aligned ChibiTap WAVs to an exact beat range and write an experiment manifest",
    )
    finalize.add_argument("--experiment-id", required=True)
    finalize.add_argument("--tap", action="append", type=_tap_capture_arg, required=True, help="Repeat TAP_ID:LABEL:PATH")
    finalize.add_argument("--output-dir", required=True)
    finalize.add_argument("--start-beat", type=float, required=True)
    finalize.add_argument("--end-beat", type=float, required=True)
    finalize.add_argument("--tempo", type=float, required=True)
    finalize.add_argument("--sample-rate", type=int, default=48000)
    finalize.add_argument("--channels", type=int, default=2)
    finalize.add_argument("--transport-start-beat", type=float)
    finalize.add_argument("--transport-stop-beat", type=float)
    finalize.add_argument("--no-analysis", action="store_true")

    capture_session = sub.add_parser(
        "capture-session",
        help="Run one aligned ChibiTap session and finalize it to an exact beat range",
    )
    capture_session.add_argument("--experiment-id", required=True)
    capture_session.add_argument(
        "--tap",
        action="append",
        type=_session_tap_arg,
        required=True,
        help=(
            "Repeat TAP_ID:LABEL:TARGET (defaults to post_fx) or "
            "TAP_ID:LABEL:SIGNAL_POINT:TARGET; SIGNAL_POINT is post_fx, pre_fx, "
            "or post_instrument and TARGET is master/Main or an exact Live track name"
        ),
    )
    capture_session.add_argument("--output-dir", required=True)
    capture_session.add_argument("--start-beat", type=float, required=True)
    capture_session.add_argument("--end-beat", type=float, required=True)
    capture_session.add_argument("--host", default="127.0.0.1")
    capture_session.add_argument("--port", type=int, default=18765)
    capture_session.add_argument("--capture-root")
    capture_session.add_argument("--poll-interval", type=float, default=0.05)
    capture_session.add_argument("--settle-seconds", type=float, default=0.6)
    capture_session.add_argument("--timeout-margin", type=float, default=8.0)
    capture_session.add_argument("--no-analysis", action="store_true")

    args = parser.parse_args()
    if args.command == "inspect-set":
        print(dumps_report(inspect_set(args.path)))
    elif args.command == "organize":
        report = inspect_set(args.path)
        schema = load_organization_schema(args.schema)
        context = build_project_context(report, schema)
        if args.output:
            write_project_context(args.output, context)
        print(json.dumps(context, indent=2, ensure_ascii=False))
    elif args.command == "scan-plugins":
        print(json.dumps(catalog_dict(discover_plugins(args.root)), indent=2, ensure_ascii=False))
    elif args.command == "scan-ableton-places":
        print(json.dumps(places_dict(read_user_places(args.library_cfg)), indent=2, ensure_ascii=False))
    elif args.command == "live-status":
        client = LiveBridgeClient(host=args.host, port=args.port)
        print(json.dumps(client.status(), indent=2, ensure_ascii=False))
    elif args.command == "live-summary":
        client = LiveBridgeClient(host=args.host, port=args.port)
        print(json.dumps(client.set_summary(track_limit=args.track_limit, device_limit=args.device_limit), indent=2, ensure_ascii=False))
    elif args.command == "analyze-audio":
        print(json.dumps(analyze_audio(args.path, window_seconds=args.window_seconds), indent=2, ensure_ascii=False))
    elif args.command == "analyze-harshness":
        print(json.dumps(analyze_harshness(args.path, top_events=args.top_events), indent=2, ensure_ascii=False))
    elif args.command == "level-match-ab":
        manifest_path = create_level_matched_ab(
            left=args.left,
            right=args.right,
            output_dir=args.output_dir,
            comparison_id=args.comparison_id,
            left_label=args.left_label,
            right_label=args.right_label,
        )
        print(manifest_path.read_text(encoding="utf-8"), end="")
    elif args.command == "reference-register":
        result = ReferenceLibrary(args.library_root).register(
            args.path,
            display_name=args.name,
            project=args.project,
            set_name=args.set_name,
            loudest_window_seconds=args.window_seconds,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "reference-set":
        rows = ReferenceLibrary(args.library_root).reference_set(args.project, args.set_name)
        print(json.dumps({"effect_state": "NOT_STARTED", "project": args.project, "set_name": args.set_name, "references": rows}, indent=2, ensure_ascii=False))
    elif args.command == "reference-verify":
        print(json.dumps(ReferenceLibrary(args.library_root).verify(args.content_sha256), indent=2, ensure_ascii=False))
    elif args.command == "reference-compare":
        result = ReferenceLibrary(args.library_root).compare_candidate(
            args.candidate,
            project=args.project,
            set_name=args.set_name,
            candidate_label=args.label,
            loudest_window_seconds=args.window_seconds,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "reference-separator-status":
        print(json.dumps(demucs_capability(), indent=2, ensure_ascii=False))
    elif args.command == "reference-separate":
        result = DemucsSeparatorBackend(model=args.model, device=args.device).separate(args.path, output_root=args.output_root)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "reference-analyze-stems":
        result = analyze_separated_stems(args.manifest, cache_dir=args.cache_dir)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "reference-compare-stems":
        result = compare_stem_analyses(
            args.baseline,
            args.candidate,
            baseline_label=args.baseline_label,
            candidate_label=args.candidate_label,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "finalize-capture":
        manifest_path = finalize_aligned_captures(
            experiment_id=args.experiment_id,
            inputs=args.tap,
            output_dir=args.output_dir,
            start_beat=args.start_beat,
            end_beat=args.end_beat,
            tempo_bpm=args.tempo,
            sample_rate=args.sample_rate,
            channels=args.channels,
            transport_start_beat=args.transport_start_beat,
            transport_stop_beat=args.transport_stop_beat,
            include_analysis=not args.no_analysis,
        )
        print(manifest_path.read_text(encoding="utf-8"), end="")


    elif args.command == "capture-session":
        manifest_path = run_capture_session(
            experiment_id=args.experiment_id,
            taps=args.tap,
            output_dir=args.output_dir,
            start_beat=args.start_beat,
            end_beat=args.end_beat,
            host=args.host,
            port=args.port,
            capture_root=args.capture_root,
            include_analysis=not args.no_analysis,
            poll_interval=args.poll_interval,
            settle_seconds=args.settle_seconds,
            timeout_margin=args.timeout_margin,
        )
        print(manifest_path.read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()
