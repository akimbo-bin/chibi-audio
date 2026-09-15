from __future__ import annotations

import argparse
import json

from .als import dumps_report, inspect_set
from .audio import analyze_audio
from .library import places_dict, read_user_places
from .live import LiveBridgeClient
from .plugins import catalog_dict, discover_plugins


def main() -> None:
    parser = argparse.ArgumentParser(prog="chibi-audio")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect-set", help="Read an Ableton .als file without modifying it")
    inspect.add_argument("path")

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

    args = parser.parse_args()
    if args.command == "inspect-set":
        print(dumps_report(inspect_set(args.path)))
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


if __name__ == "__main__":
    main()
