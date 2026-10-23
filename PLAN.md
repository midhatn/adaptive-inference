# Development and upstream delivery plan

## Objective

Provide one maintainable adaptive control layer that helps users and agents complete their original tasks across model servers. Accept useful corrective iterations. Preserve model quality settings and distinguish a completed task from an unverified assertion of success.

This repository owns shared policy, contracts, reproducible tests, documentation and citations. Engine repositories own native execution capabilities; agent repositories own tools, permissions and application workflows. Upstream changes should reuse the shared contracts rather than create unrelated forks of policy.

## Delivery stages

| Stage | Deliverable | Acceptance |
| --- | --- | --- |
| 1. Publish a reproducible core | Installable Python gateway, bounded queue, timing model, feedback helper, local HTTP demo, CI and provenance | Fresh environment install; protocol tests and demo pass; no private machine dependencies |
| 2. Broad protocol integrations | Eight engine profiles and ten agent configuration/SDK recipes | Each profile passes applicable endpoint/metadata/quality contracts; recipes cite official configuration sources |
| 3. Preserve working native work | Pinned Strata and Hermes bases, hashed overlays, clean reconstruction scripts and evidence ledger | A fresh public clone reconstructs every shipped changed file; no binaries, credentials or model weights bundled |
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

- Use the normal endpoint for interactive work and the shared background route for autonomous/background work.
- Preserve tools, structured outputs, model choices and output allowances. Do not infer user intent from prompt text when host task metadata exists.
- Provide an optional feedback helper with an application-supplied validator. The helper cannot authorize tools or guarantee its validator is correct.
- Exercise ordinary clients using documented provider configuration before requesting upstream changes. Offer host-derived priority, exact output reservation or capability fixes upstream only where a public configuration is insufficient.
- Keep each task's original objective and acceptance check through corrections. Bound attempts and report unresolved failure rather than claiming success.

## Reproduction and release policy

Every release includes source, dependency pins, CI, a runnable no-model demo, example configurations, a versioned compatibility matrix, citations and an evidence ledger. Hardware-dependent checks name exact source/model/runtime/platform and retain failures. Model weights remain separately acquired under their own terms.

Default CI covers Windows, Linux and macOS on supported Python versions. Native backends require distinct jobs or published operator receipts. An API fixture passing does not turn into an installed-agent or native-performance claim.

## Upstream workflow

1. Develop and review the shared change here with a concrete problem and acceptance result.
2. Update applicable contracts, examples, citations and the evidence ledger.
3. Cut a version/tag so downstream PRs can refer to stable code.
4. Extract the smallest upstream-specific patch. Link the canonical implementation and exact evidence; avoid bulk unrelated changes.
5. Record PR state, tested revision, reviewer feedback and merge/replacement links in `upstream/registry.json`.
6. When upstream accepts an equivalent fix, retire the local overlay only after comparing behavior and passing the relevant contracts.

The existing Strata1493 public branch is not assumed to contain newer local descendants. Reconcile ancestry explicitly before pushing code. Publication comments must distinguish an implementation in this repository from a change already present in an upstream PR.
