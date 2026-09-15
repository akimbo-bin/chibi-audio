# Chibi Audio Secure MCP Tunnel deployment

This runbook exposes the reviewed `chibi-audio-mcp` tool surface to an authorized ChatGPT workspace without exposing Ableton Live or the Remote Script JSON-RPC port to the network.

## Production topology

```text
authorized ChatGPT workspace
        |
        | OpenAI Secure MCP Tunnel
        | outbound connection from AKIMB0-PC
        v
AKIMB0-PC: tunnel-client
        |
        | stdio child process
        v
AKIMB0-PC: chibi-audio-mcp
        |
        | loopback JSON-RPC only
        v
AKIMB0-PC: Ableton Live Remote Script on 127.0.0.1:18765
```

Run the tunnel client in the same Windows trust boundary as Ableton. A tunnel process on CT114 cannot reach AKIMB0-PC's `127.0.0.1:18765`; do not solve that by exposing the Live bridge over LAN or the public Internet.

The tunnel client needs outbound HTTPS to OpenAI. No inbound firewall rule, router forwarding, public DNS name, reverse proxy, or public MCP URL is required for the stdio deployment.

## Authority boundary

`chibi-audio-mcp` is a specialist executor/evidence surface, not workflow authority. It does not receive a Chibi Core service bearer and does not access Core's database.

The MCP server itself needs no OpenAI tunnel credential. Tunnel/workspace credentials belong only to the OpenAI tunnel-client runtime. Never place those credentials in GitHub, prompts, the Live Set, plugin state, or model-visible output.

The Live Remote Script remains bound to `127.0.0.1:18765`.

## Prepare the local MCP environment

From the reviewed Chibi Audio checkout on AKIMB0-PC:

```powershell
.\deploy\windows\bootstrap-chibi-audio-mcp.ps1
```

This creates `.venv-audio-mcp` and installs the checkout with the `analysis` and `mcp` extras. It does not launch Ableton, contact the Live bridge, configure a tunnel, or enable mutations.

For a local stdio protocol inspection, start the reviewed launcher:

```powershell
.\deploy\windows\run-chibi-audio-mcp.ps1
```

The launcher explicitly sets `CHIBI_AUDIO_MCP_ALLOW_WRITES=0` unless `-AllowWrites` is supplied. This overrides a permissive inherited environment and keeps the default ChatGPT surface read-only.

Only after the bounded-write surface has been reviewed and explicitly authorized should the tunnel profile invoke:

```powershell
.\deploy\windows\run-chibi-audio-mcp.ps1 -AllowWrites
```

## Tunnel client

Use a reviewed, pinned OpenAI `tunnel-client` release for Windows. At the time this runbook was written, the validated upstream release is `v0.0.14` and includes a Windows amd64 archive. Verify the downloaded archive against the release's published SHA-256 data before use.

The repository includes a download-only installer helper for that reviewed release:

```powershell
.\deploy\windows\install-openai-tunnel-client.ps1
```

The helper downloads the pinned Windows amd64 archive, verifies its embedded reviewed SHA-256 value, and copies only the verified executable into a local install directory. It does **not** create or connect a tunnel profile, store a runtime API key, configure persistence, start the client, or associate a ChatGPT workspace.

Do not commit the runtime API key or generated tunnel profile. Keep profile/runtime/secret directories outside the repository, under the Windows user/service identity that owns the tunnel process.

Use the official Secure MCP Tunnel bootstrap/connection flow to associate a dedicated audio tunnel with the intended ChatGPT workspace and configure its MCP command to execute the reviewed Windows launcher over stdio.

Conceptually, the tunnel profile's local command is:

```text
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File <reviewed-checkout>\deploy\windows\run-chibi-audio-mcp.ps1
```

For an explicitly write-enabled profile, add `-AllowWrites`. Prefer separate reviewed read-only and write-enabled profiles/app revisions rather than silently broadening an existing published tool surface.

## Expected tool surface

With default read-only startup, the server exposes production reads/evidence tools including:
- bridge/project/device/mixer reads;
- artifact analysis and high-end diagnostics;
- reversible audition planning;
- parameter snapshots/diffs;
- `get_locators`;
- `get_sections`;
- `resolve_section`;
- `get_song_position`;
- `plan_section_capture`;
- `list_audio_analyzers`;
- `analyze_audio`;
- `analyze_capture_manifest`;
- `compare_analysis_reports`.

The four reusable-analysis tools are a thin seam to the separately owned issue #8 analysis fabric. If that package is absent from the deployed checkout/runtime, `list_audio_analyzers` reports it unavailable and analysis requests fail closed. When #8 is present, callers explicitly select only the capabilities they need and a `CHEAP`, `MODERATE` or `EXPENSIVE` cost ceiling. The MCP adapter keeps direct artifacts, capture manifests and every finalized tap path confined below `CHIBI_AUDIO_ARTIFACT_ROOT`.

It must **not** enumerate bounded mutation tools or `capture_section` while writes are disabled.

With `-AllowWrites`, the reviewed bounded mutation tools become visible and `capture_section` is added. `capture_section` resolves the artist-authored Locator fresh, carries its Set signature into the capture executor, and refuses before any transport/ChibiTap effect if the Set changed after planning.

No mode exposes arbitrary Python, a shell, a generic Live Object Model caller/setter, raw JSON-RPC, filesystem-wide reads, or mouse/keyboard control.

## Workspace connection proof

After the tunnel profile is connected to the intended ChatGPT workspace:

1. Inspect the app/plugin action list before enabling it.
2. Start with the read-only launcher and confirm mutation tools are absent.
3. Call `status` and require the reviewed capability classes.
4. Call `list_audio_analyzers`. If the #8 analysis fabric is deployed, require the reviewed capability/cost catalog; otherwise require an explicit unavailable result rather than partial analyzer execution.
5. Analyze one known artifact or finalized capture manifest with an explicit small capability set/cost ceiling and verify returned artifact references remain relative to `CHIBI_AUDIO_ARTIFACT_ROOT`.
6. Add artist-authored Ableton Locators such as `Intro`, `Build`, `Drop 1`, `Bridge`.
7. Call `get_sections` and confirm exact beat ranges match the Arrangement.
8. Call `resolve_section` for one section and confirm the expected start/end beats.
9. Call `plan_section_capture` with the desired tap specs and require `effect_state=NOT_STARTED`.
10. Do not enable writes until the active Live Set is free for the coordinated bounded-write proof.
11. When writes are explicitly enabled, first prove one disposable parameter write/read-back/restore operation.
12. Then prove one named `capture_section` operation and verify the finalized manifest/artifacts stay below `CHIBI_AUDIO_ARTIFACT_ROOT`.

Stop if the tool list contains an unexpected generic capability, Live is reachable on a non-loopback interface, analysis can escape the configured artifact root, the tunnel launches a different checkout, or a write-enabled surface appears without the explicit launcher flag.

## Persistence

Do not configure Windows auto-start until the tunnel profile and tool enumeration have passed the workspace proof. When persistence is desired, supervise the pinned tunnel client under a dedicated Windows service or scheduled-at-start process identity with:
- an explicit executable path;
- an explicit profile/runtime directory;
- no repository write access beyond what deployment updates require;
- no ambient secrets in command-line arguments;
- restart-on-failure behavior;
- a single active client for the same tunnel/profile unless the upstream tunnel mode explicitly supports the intended replica topology.

The tunnel process may restart independently of Ableton. MCP tool calls should fail closed while Live/Remote Script is unavailable; the supervisor must not launch or manipulate Ableton to hide that state.
