# Repeatable workflow commands

Chibi Audio should expose a small set of durable, resumable intent commands rather than requiring callers to manually chain low-level Ableton operations. The same logical command must be callable from CLI, MCP/ChatGPT and Chibi Core jobs.

The primary commands are:

- `organize` — understand and organize the project; normally the first plane.
- `mix` — pursue a mix goal using hierarchical analysis and bounded reversible waves.
- `sidechain` — audit or optimize explicit source -> target ducking relationships; callable directly or by `mix`.
- `master` — optimize final-bus/master behavior against an explicit goal; callable directly or by `mix`.

These are workflow intents, not permission to expose arbitrary Live setters.
## Command lifecycle

Every command should be effect-certain and resumable:

1. resolve the authorized project/lab lineage and fresh Set signature;
2. refresh the persisted project context produced by `organize`;
3. create or resume a Core-owned workflow/job ID;
4. record goal, guardrails, budget, current best state and evidence references;
5. dispatch bounded specialist investigations in parallel where useful;
6. serialize all Ableton mutations through one executor;
7. capture/render and evaluate authoritative evidence;
8. keep, refine or roll back exactly;
9. checkpoint durable state so another Chibi can resume the same job;
10. stop only at a real goal/guardrail/budget/subjective-judgment boundary.
## `organize`

`organize` is the normal first plane. It is not merely cosmetic cleanup: it dissects the project and creates the shared context that makes later workers faster and more consistent.

It should classify hierarchy, routing, semantic roles, arrangement roles, related sources, automation complexity, devices and sidechain relationships; then propose or apply naming, coloring, track order, track height, fold state and safe grouping according to `PROJECT_ORGANIZATION.md`.

Cosmetic changes may be applied as one verified reversible batch when authorized. Structural changes such as creating groups or reparenting tracks require routing-equivalence proof or explicit routing intent.

Output: durable project-context graph + organization diff + unresolved/low-confidence classifications + rollback provenance.
## `mix`

`mix` owns the overall musical optimization loop. It starts from organized project context, listens/measures top-down, ranks the largest audible/technical bottlenecks, dispatches bus/source specialists, and chooses one coherent reversible intervention per wave.

`mix` may call `sidechain` and `master` as specialist sub-workflows when their evidence is relevant. It should prefer upstream/source/bus fixes before leaning harder on the final limiter, and use short diagnostic windows before full-section acceptance renders.

Parallel workers accelerate analysis and share Core-held evidence. They never mutate Live independently; the one serialized executor owns checkpoints, writes and restores.
## `sidechain`

`sidechain` is both standalone and callable by `mix`. It audits source -> target relationships, measures actual rendered reduction/timing/overlap, proposes the smallest sufficient intervention, performs bounded experiments when authorized, and returns routing plus audio evidence to the parent workflow.

It must reason across the project hierarchy rather than cloning one sidechain amount everywhere. Kick/bass, snare/music and vocal/music relationships may require different processing classes, frequency regions and timing.

## `master`

`master` is both standalone and callable by `mix`. It owns the final-bus goal contract, reference/delivery constraints, clean-loudness knee, final dynamics/translation evidence and master-chain candidates. It must not hide upstream mix problems by blindly increasing final limiting.
## Invocation surfaces

The same intent should be reachable without inventing a separate workflow per client:

- CLI: deterministic local/operator entrypoint for development and recovery.
- MCP: any authorized Chibi/ChatGPT can request `organize`, `mix`, `sidechain` or `master` against a selected project.
- Chibi Core: durable multi-wave job authority for requests such as “take control of Ableton and work on the mix for hours.”

A short MCP request may execute one bounded wave and return. A long-running request creates/resumes a Core-owned job that can dispatch/recycle specialist workers, preserve best-so-far state and continue across chat/worker turnover without making the MCP caller the workflow authority.
## Shared command contract

Each command should expose a stable request/result envelope containing at least:

- `project_ref` / active lab lineage;
- `workflow_id` and optional `parent_workflow_id`;
- `goal` and explicit guardrails;
- `mode` (`plan`, `bounded_wave`, or `run_until_boundary`);
- fresh Set/project-context identity;
- mutation/render budget;
- current effect certainty (`NOT_STARTED`, `STARTED_CONFIRMED`, `UNKNOWN`);
- best-so-far checkpoint and evidence references;
- specialist child jobs and their status;
- applied/rejected changes and exact rollback provenance;
- stop reason and any artist decision required.

This contract is the stable layer. Low-level Live/MCP capabilities remain implementation details underneath it.