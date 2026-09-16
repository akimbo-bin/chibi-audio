# Chibi Audio ChatGPT app alpha

This is the product-facing deployment contract for the first internal Chibi Audio app in ChatGPT.

The backend already exists as a reviewed MCP surface. The first alpha should expose that surface as a **custom ChatGPT app through Secure MCP Tunnel**, without adding a second workflow authority or exposing Ableton's localhost bridge to the network.

## Product shape

Start with two deliberately separate app/runtime profiles rather than one app whose authority silently changes:

1. **Chibi Audio — Read Only**
   - first internal alpha;
   - safe to use for normal project inspection, Locator/section understanding, artifact analysis, evidence comparison and planning;
   - no Live mutations, transport/capture effects or artifact creation actions.
2. **Chibi Audio — Write Enabled**
   - later reviewed alpha/revision;
   - starts the same MCP server with the explicit `-AllowWrites` launcher flag;
   - adds bounded Live mutations, managed section capture/evidence and artifact creation such as level-matched A/B pairs.

Chibi Core remains the eventual workflow authority. The ChatGPT app is a specialist production interface/executor, not its own scheduler or task database.

## Connection topology

```text
ChatGPT custom app
        |
        | Secure MCP Tunnel
        v
AKIMB0-PC tunnel-client
        |
        | stdio
        v
chibi-audio-mcp
        |
        | 127.0.0.1:18765 only
        v
Ableton Live Remote Script
```

Do not expose `127.0.0.1:18765` over LAN or the public Internet. Do not put the tunnel runtime API key, tunnel profile, or workspace credentials in Git, prompts, Live device state, or model-visible output.

## Read-only alpha tool catalog

After ChatGPT analyzes the tools for the read-only profile, the expected catalog is exactly the reviewed non-effect surface below (ordering is irrelevant):

- `status`
- `project_snapshot`
- `device_parameters`
- `track_mixer_state`
- `parameter_snapshot`
- `diff_parameter_snapshots`
- `plan_audition`
- `analyze_artifact`
- `analyze_harshness_artifact`
- `get_locators`
- `get_sections`
- `resolve_section`
- `get_song_position`
- `plan_section_capture`
- `plan_section_evidence`
- `list_audio_analyzers`
- `analyze_audio`
- `analyze_capture_manifest`
- `compare_analysis_reports`

The read-only app must **not** expose any of these effect-producing tools:

- track/device setters or rename/color operations;
- `capture_section`;
- `capture_section_evidence`;
- `create_level_matched_ab`.

If an unexpected generic shell, filesystem, arbitrary Python/eval, generic Live Object Model caller/setter, raw JSON-RPC, GUI-control or write capability appears, stop the app review rather than publishing it.

## Write-enabled additions

Only after the read-only app has been proven from an ordinary ChatGPT conversation should a separate write-enabled profile/revision be reviewed. Its expected additions are:

- `set_track_volume`
- `set_track_pan`
- `set_track_mute`
- `set_track_solo`
- `rename_track`
- `set_track_color`
- `set_device_enabled`
- `set_device_parameter`
- `capture_section`
- `capture_section_evidence`
- `create_level_matched_ab`

`create_level_matched_ab` is an artifact-producing action, not a Live mutation. It accepts only artifact-root-relative inputs, refuses overwrite/unaligned pairs, never boosts either variant, never modifies source WAVs, and returns only artifact-root-confined references plus provenance.

## ChatGPT custom-app creation boundary

OpenAI's current custom-app flow uses Developer Mode to create/test an MCP-backed app. The workspace/user creating it must have the necessary custom-app/developer permissions.

For the first alpha:

1. Create a **dedicated Chibi Audio Secure MCP Tunnel profile** on AKIMB0-PC whose stdio command runs the reviewed launcher **without** `-AllowWrites`.
2. Run the tunnel client's health/doctor flow and confirm the profile points at the intended reviewed checkout.
3. In ChatGPT's app creation flow, create an internal custom app named **Chibi Audio** (or **Chibi Audio — Read Only** while both profiles coexist).
4. Configure the MCP connection/authentication using the dedicated tunnel, then use **Analyze tools**.
5. Compare the analyzed action list against the exact read-only catalog above before creating/publishing the app.
6. From an ordinary ChatGPT conversation, prove `status`, a project/Locator read, analyzer discovery, and one confined artifact-analysis call.
7. Keep writes disabled until this ordinary-conversation proof is complete.

The tunnel ID, runtime API key/principal and explicit ChatGPT workspace association are external deployment inputs. This repository deliberately does not invent, discover or store those credentials.

## Apps SDK UI: later, not a blocker for the first alpha

The first internal alpha can be a custom MCP app with no custom visual component. The Apps SDK is the preferred follow-on when we want a polished in-ChatGPT interface.

Useful first UI surfaces would be:

- current Set/section status card;
- capture/evidence progress and exact effect state;
- analyzer provenance/details on demand;
- side-by-side as-produced and level-matched A/B artifact cards;
- experiment journal timeline with exact accepted/rejected changes;
- explicit keep / reject / refine artist controls.

Do not delay the first ordinary-conversation MCP proof just to build those widgets.

## Definition of the first product milestone

The alpha milestone is complete when a normal ChatGPT conversation can select Chibi Audio and, without CUA or a public Ableton port:

1. inspect the active Live Set and named sections;
2. request bounded analysis of existing ChibiTap evidence;
3. explain the evidence with artifact-relative provenance;
4. show that all mutation/capture/artifact-creation tools are absent in the read-only app.

The next milestone is the separately reviewed write-enabled app proving one guarded reversible parameter operation, one named-section capture/evidence operation, and one confined level-matched A/B artifact workflow.
