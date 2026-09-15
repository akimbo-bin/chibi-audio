from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from chibi_audio.probe import render_agent_audio_tap

BRIDGE = ROOT / "bridge" / "ChibiAudioBridge"
PROBE = ROOT / "bridge" / "m4l"

def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def copy_items(user_library: Path, component: str):
    items = []
    if component in {"bridge", "all"}:
        dest = user_library / "Remote Scripts" / "ChibiAudioBridge"
        for src in sorted(BRIDGE.iterdir()):
            if src.is_file() and src.suffix != ".pyc":
                items.append(("copy", src, dest / src.name))
    if component in {"probe", "all"}:
        dest = user_library / "Presets" / "Audio Effects" / "Max Audio Effect"
        for name in ("AgentAudioTap.maxpat", "agent_audio_tap.js"):
            items.append(("copy", PROBE / name, dest / name))
    return items

def generated_probe(user_library: Path, state_dir: Path):
    dest = user_library / "Presets" / "Audio Effects" / "Max Audio Effect" / "AgentAudioTap.amxd"
    command_file = state_dir / "agent_audio_tap_command.json"
    data = render_agent_audio_tap(PROBE / "AgentAudioTap.template.amxd", PROBE / "AgentAudioTap.maxpat", command_file)
    return data, dest, command_file

def install(user_library: Path, component: str, state_dir: Path, dry_run: bool, replace: bool):
    payloads = []
    for kind, src, dst in copy_items(user_library, component):
        payloads.append((kind, str(src), dst, src.read_bytes()))
    command_file = None
    if component in {"probe", "all"}:
        data, dst, command_file = generated_probe(user_library, state_dir)
        payloads.append(("generated", "AgentAudioTap.template.amxd", dst, data))
    actions = []
    for kind, source, dst, data in payloads:
        source_hash = digest_bytes(data)
        current_hash = digest_bytes(dst.read_bytes()) if dst.exists() else None
        if current_hash == source_hash:
            action = "unchanged"
        elif dst.exists() and replace:
            action = "replace"
        elif dst.exists():
            action = "conflict"
        else:
            action = "create"
        actions.append({"kind": kind, "source": source, "destination": str(dst), "action": action, "source_sha256": source_hash, "current_sha256": current_hash})
    if any(a["action"] == "conflict" for a in actions) and not dry_run:
        raise RuntimeError("refusing overwrite without --replace")
    if not dry_run:
        for (_kind, _source, dst, data), item in zip(payloads, actions):
            if item["action"] == "unchanged":
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
    return {"user_library": str(user_library), "state_dir": str(state_dir), "command_file": str(command_file) if command_file else None, "component": component, "dry_run": dry_run, "replace": replace, "touches_live_set": False, "actions": actions}

def main():
    parser = argparse.ArgumentParser(description="Install Chibi Audio bridge/probe files without launching Ableton.")
    parser.add_argument("--user-library", type=Path, default=Path.home() / "Documents" / "Ableton" / "User Library")
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".chibi-audio")
    parser.add_argument("--component", choices=("bridge", "probe", "all"), default="all")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    print(json.dumps(install(args.user_library, args.component, args.state_dir, args.dry_run, args.replace), indent=2))

if __name__ == "__main__":
    main()
