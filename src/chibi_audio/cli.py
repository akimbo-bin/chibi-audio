from __future__ import annotations

import argparse

from .als import dumps_report, inspect_set


def main() -> None:
    parser = argparse.ArgumentParser(prog="chibi-audio")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect-set", help="Read an Ableton .als file without modifying it")
    inspect.add_argument("path")

    args = parser.parse_args()
    if args.command == "inspect-set":
        print(dumps_report(inspect_set(args.path)))


if __name__ == "__main__":
    main()
