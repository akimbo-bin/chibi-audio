from __future__ import annotations

import json
from pathlib import Path


def _max_arg(value: str | Path) -> str:
    text = str(value).replace("\\", "/")
    return f'"{text.replace(chr(34), chr(92)+chr(34))}"' if any(c.isspace() for c in text) else text


def patched_maxpat(source: str | Path, command_file: str | Path) -> bytes:
    patch = json.loads(Path(source).read_text(encoding="utf-8"))
    replacement = "js agent_audio_tap.js " + _max_arg(command_file)
    found = False
    for item in patch["patcher"]["boxes"]:
        box = item.get("box", {})
        if box.get("text") == "js agent_audio_tap.js":
            box["text"] = replacement
            found = True
            break
    if not found:
        raise ValueError("AgentAudioTap source is missing the JS command box")
    return (json.dumps(patch, indent=2) + "\n").encode("utf-8") + b"\x00"


def replace_ptch_chunk(container: bytes, payload: bytes) -> bytes:
    index = container.find(b"ptch")
    if index < 0:
        raise ValueError("AMXD template is missing a ptch chunk")
    size_start = index + 4
    size_end = size_start + 4
    old_size = int.from_bytes(container[size_start:size_end], "little")
    payload_start = size_end
    payload_end = payload_start + old_size
    if payload_end > len(container):
        raise ValueError("AMXD template has a truncated ptch chunk")
    return container[:size_start] + len(payload).to_bytes(4, "little") + payload + container[payload_end:]


def render_agent_audio_tap(template: str | Path, source: str | Path, command_file: str | Path) -> bytes:
    payload = patched_maxpat(source, command_file)
    return replace_ptch_chunk(Path(template).read_bytes(), payload)


def build_agent_audio_tap(template: str | Path, source: str | Path, output: str | Path, command_file: str | Path) -> Path:
    output_path = Path(output)
    data = render_agent_audio_tap(template, source, command_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)
    return output_path
