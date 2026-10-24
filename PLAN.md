# Development and upstream delivery plan

## Objective

Make an always-on AI agent practical on the user's everyday computer. The user should be able to browse, game, watch video and work while the agent automatically backs off under contention and resumes when capacity returns. The agent must also make room for its own compilers, other models and video-generation tools, then continue the original objective without manual model-server juggling.

Always on refers to continuity of the agent, controller and task state. A heavy model may need to park or unload. A shared queue and compatible API endpoints are foundations; completion requires a continuous resource coordinator, verified native handoffs and reliable task resume. The [always-on vision](docs/always-on-controller.md) defines the experience, current capability gaps and measurable acceptance criteria.

Accept useful corrective iterations, preserve declared quality settings and distinguish a completed task from an unverified assertion of success. Seek a functioning end-to-end workflow first, then optimize it.

This repository owns shared policy, contracts, reproducible tests, documentation and citations. Engine repositories own native execution capabilities; agent repositories own tools, permissions and application workflows. Upstream changes should reuse the shared contracts rather than create unrelated forks of policy.

## Delivery stages

| Stage | Deliverable | Acceptance |
| --- | --- | --- |
| 1. Publish a reproducible core | Installable Python gateway, bounded queue, timing model, feedback helper, local HTTP demo, CI and provenance | Fresh environment install; protocol tests and demo pass; no private machine dependencies |
| 2. Broad protocol integrations | Eight engine profiles and ten agent configuration/SDK recipes | Each profile passes applicable endpoint/metadata/quality contracts; recipes cite official configuration sources |
| 3. Preserve working native work | Locally archived Strata/Hermes bases and native dependency, hashed overlays, offline reconstruction scripts and evidence ledger | A complete clone/source distribution reconstructs every shipped integration source without external PRs; existing public support/test assets retained, no private artifacts or full inference model bundled |
| 4. Establish the upstream relationship | Link all relevant historical PRs in the main repo and post scoped updates to relevant authored/contribution threads | Exact posted URLs and bodies are recorded; closed PRs retain truthful status; maintainers retain merge control |
| 5. Exercise useful real agent tasks | A bounded artifact-producing task with an independent acceptance check, feedback and repair attempts | Original requested artifact passes the check; failure/attempt exhaustion is returned honestly; no tool effects replayed by the gateway |
| 6. Add native capability adapters | Explicit status, cancel/drain acknowledgement, memory/cache controls and optional resource leases | Each backend verifies its own capacity and process/operation identities; unsupported capabilities remain unavailable |
| 7. Improve policy from measurements | Calibration, workload mix, optional weighted fairness or route selection | Matched quality and reproducible workload; compare against current policy and report failures; no global speed claim from a toy test |

Stages 1–4 are the initial publication scope. Stages 5–7 are continuing development, not prerequisites for using the generic gateway. The live compatibility/evidence tables record completed checks; this plan does not itself certify a milestone.

## Engine strategy

- Share scheduling, bounded timing feedback, configuration validation and observability across all OpenAI-compatible servers.
- Keep profile capability declarations explicit. Forward only supported endpoint families; preserve request bodies except gateway scheduling metadata.
- Prefer public backend APIs and extension points. Native cache sizing, cancellation acknowledgement, leases and request migration require engine-specific implementations and tests.
- Start native ports with Strata (retained source), then llama.cpp and Ollama, then vLLM/SGLang. MLX-LM needs Apple Silicon validation; TGI and LM Studio retain their actual deployment constraints.
- Treat Jev/Laya as optional advisers only after they improve an observed task. Earlier “Maya” references were corrected to Laya; it is not an interchangeable inference server. Keep deterministic policy available.

## Agent strategy

The next end-to-end milestone combines foreground activity, background inference, a resource-intensive compiler/video/model tool, verified resource return and an independently accepted artifact. Evaluate foreground responsiveness against declared budgets and retain interruption/failure evidence. Native engine breadth follows a working shared contract, rather than replacing this acceptance target with a longer profile list.

Restart survival is a core requirement. The [durable checkpoint foundation](docs/task-survival.md) now preserves committed task progress and prevents automatic replay of ambiguous interrupted operations. Next, connect it to an installed agent's startup, model lifecycle and tool-specific reconciliation, then qualify closing/reopening the application and restarting the supported computer. An open tray window or a saved conversation alone does not satisfy task continuation.

- Use the normal endpoint for interactive work and the shared background route for autonomous/background work.
- Preserve tools, structured outputs, model choices and output allowances. Do not infer user intent from prompt text when host task metadata exists.
- Provide an optional feedback helper with an application-supplied validator. The helper cannot authorize tools or guarantee its validator is correct.
- Exercise ordinary clients using documented provider configuration before requesting upstream changes. Offer host-derived priority, exact output reservation or capability fixes upstream only where a public configuration is insufficient.
- Keep each task's original objective and acceptance check through corrections. Bound attempts and report unresolved failure rather than claiming success.

## Reproduction and release policy

Every release includes source, dependency pins, CI, a runnable no-model demo, example configurations, a versioned compatibility matrix, citations and an evidence ledger. The complete source distribution also preserves required integration baselines, overlays and licensed reference sources; the runtime wheel stays focused on the portable package. The [preservation contract](docs/source-of-truth.md) defines these boundaries. Hardware-dependent checks name exact source/model/runtime/platform and retain failures. Model weights remain separately acquired under their own terms.

Default CI covers Windows, Linux and macOS on supported Python versions. Native backends require distinct jobs or published operator receipts. An API fixture passing does not turn into an installed-agent or native-performance claim.

## Upstream workflow

1. Develop and review the shared change here with a concrete problem and acceptance result.
2. Update applicable contracts, examples, citations and the evidence ledger.
3. Cut a version/tag so downstream PRs can refer to stable code.
4. Extract the smallest upstream-specific patch. Link the canonical implementation and exact evidence; avoid bulk unrelated changes.
5. Record PR state, tested revision, reviewer feedback and merge/replacement links in `upstream/registry.json`.
6. When upstream accepts an equivalent fix, retire the local overlay only after comparing behavior and passing the relevant contracts.

The existing Strata1493 public branch is not assumed to contain newer local descendants. Reconcile ancestry explicitly before pushing code. Publication comments must distinguish an implementation in this repository from a change already present in an upstream PR.
