from __future__ import annotations

import argparse
import json

from .als import dumps_report, inspect_set
from .library import places_dict, read_user_places
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

    args = parser.parse_args()
    if args.command == "inspect-set":
        print(dumps_report(inspect_set(args.path)))
    elif args.command == "scan-plugins":
        print(json.dumps(catalog_dict(discover_plugins(args.root)), indent=2, ensure_ascii=False))
    elif args.command == "scan-ableton-places":
        print(json.dumps(places_dict(read_user_places(args.library_cfg)), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
