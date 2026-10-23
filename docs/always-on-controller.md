# The always-on agent vision

Adaptive Inference exists to make it practical to leave an AI agent running on a computer that its owner is actively using. The user should be able to launch the agent, give it an objective, and continue browsing, gaming, watching video or working without manually juggling model servers and resource settings.

The same controller should help the agent coordinate its own tools. A C++ compiler needs CPU and RAM; another language model may need memory currently held by the first; ComfyUI or a video model such as H3 may need most of the available GPU memory. The agent should be able to make room, run the tool, verify its result, and return to inference with its task intact.

This document defines the destination and acceptance criteria. It does not claim that every behavior below is already implemented.

## Two demands, one resource coordinator

**The user's activity has priority.** The controller needs to observe actual contention and foreground responsiveness, then reduce, defer or pause background work. It should recover gradually when the user's demand subsides instead of repeatedly competing for newly available capacity. A process name alone cannot establish whether the user is active or whether an application needs resources.

**The agent's workflow also changes demand.** Before a resource-intensive tool starts, the host should declare its requirements. The controller should coordinate the cooperating inference and tool owners, choose a supported way to release capacity, and confirm the release before allowing protected work. When a compiler or video job finishes, actual process completion and fresh observations should govern the return to inference.

Human demand and agent demand must be evaluated together. A tool grant must not make the agent ignore a game that starts afterward. Every participating engine needs an explicit capability contract for the adjustments it can safely perform. Unsupported operations must remain unavailable.

## What stays on

The lightweight agent/controller service remains available. Its task state retains the original objective, completed work, pending steps, tool results, and the evidence used to accept or reject a result. The large inference model may continue at reduced resource use, pause, park, or unload when necessary. Resume should be automatic when the state and capacity checks allow it.

A model unload does not itself preserve warm KV state. A backend may support a real snapshot; another may require rebuilding context from durable conversation and task state. Those are different capabilities with different costs. Neither path may silently change the model, reasoning allowance, output budget or task objective to appear successful. Changing a declared quality setting belongs to an explicit host/user policy.

The service also needs graceful recovery from a tool failure, unavailable model, canceled task or interrupted resource transition. It must not repeat a completed external action merely because inference resumed. Error correction should use the original objective and explicit outcome checks.

## Example experience

1. Start Hermes with a model served by Strata and give it a task. Adaptive Inference begins background work using the available capacity.
2. Start a game. The controller detects contention and reduces or pauses participating AI work. If necessary and supported, it parks or unloads the model while keeping the agent's task.
3. Return capacity to the agent. It resumes after fresh observations show sustained headroom.
4. The agent reaches a video-production step. It requests the needed resources, inference releases supported allocations, and the tool starts only after the cooperating owner confirms the transition and capacity is observed.
5. The video tool finishes. The agent checks the artifact, restores inference when it fits, and continues the original task. Foreground user activity remains a constraint throughout.

This sequence is a target scenario, not a report of a completed end-to-end test.

## Required capabilities and present evidence

| Capability | Present position | Required next proof |
| --- | --- | --- |
| Shared user/agent scheduling | Working portable HTTP queue and timing feedback | Useful artifact-producing agent tasks under changing foreground demand |
| Observe pressure and recover conservatively | Optional host RAM/Windows-commit gate; fresh-sample recovery policy | Continuous CPU/GPU/VRAM contention signals and measured foreground responsiveness on the supported platform |
| Release inference resources | Richer mechanisms retained in the pinned Strata integration | Exact native adapter acknowledgements, fresh capacity checks and failure handling across a complete workflow |
| Coordinate protected tools | Earlier lease and host-middleware work provides integration points | Compiler and video/model tools acquire, release and reconcile ownership reliably, including failures and user activity changes |
| Preserve and resume the agent task | Explicit feedback helper retains the original task through bounded corrections | Durable task checkpoints, identity-bound resume and no duplicate external effects across unload/reload or process restart |
| Support multiple engines and agents | Eight engine API profiles and ten client recipes | Native/resource and task-continuation adapters with their own acceptance evidence; API compatibility alone is insufficient |

The current memory sampler observes the host; it does not resize GPU caches or implement the full controller. [Evidence](evidence.md), [integration scope](integrations.md) and the [development plan](../PLAN.md) retain those distinctions.

## Acceptance: useful coexistence and completed work

Evaluate a supported composition against the same foreground workload without background AI, and with an uncontrolled background baseline where appropriate. Record exact hardware, engine/model revisions, quality settings, task, transition history and failures.

- **Foreground responsiveness:** measure relevant latency or frame-time/video-playback behavior against a declared acceptable budget. Report stalls and worst cases as well as averages.
- **Background progress:** show that the agent completes a meaningful artifact with an independent acceptance check, retaining its original objective through interruptions.
- **Resource handoff:** confirm actual release and acquisition for CPU/RAM and GPU/VRAM where the backend supports control. Requested settings, observed headroom, granted ownership and applied native allocations must be distinguished.
- **Recovery:** exercise tool failure, canceled pending work, missing/stale telemetry, model unload/reload, controller restart and resumed foreground activity. Preserve task state and avoid duplicate tool effects.
- **Quality and ownership:** retain declared generation settings and enforce one responsible owner for each transition. Do not report a tool as safe to start merely because an HTTP request or native process was asked to stop.
- **Long-running behavior:** complete a mixed-activity soak test with bounded queues, logs and state, then verify that owned processes and resources are released on shutdown.

Shared hardware cannot provide unlimited work with literally zero contention. The functional target is automatic, recoverable cooperation within measured responsiveness and resource budgets, with honest waiting when those budgets cannot be met. Performance tuning can follow once this complete loop works.

## Contribution direction

The next milestone is one reproducible always-on workflow on a supported machine, including foreground interruption, a resource-intensive tool, verified return to inference, and a completed artifact. Broader engine and agent ports should reuse that contract.

[Research references](research.md), [REFERENCES.bib](../REFERENCES.bib) and [NOTICE](../NOTICE) preserve the sources behind the design and reused code. Attribution belongs with the mechanism that uses it.
