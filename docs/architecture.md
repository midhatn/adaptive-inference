# Architecture and contracts

The portable component is a single-backend HTTP gateway. Multiple application types share one queue and one active upstream HTTP request. `/background/v1` is a demoted route into that same queue, not a second server with independent capacity accounting.

## Queue and feedback

Rank is arrival time plus a bounded background offset plus a bounded estimated execution cost. Unknown costs use the maximum cost offset. Rank is fixed at enqueue and sequence breaks ties. Requests older by more than the combined offset cannot be overtaken by a later arrival; this is an ordering bound, not a completion-time guarantee.

The cost model reuses the tested Strata module: Peak EWMA responds immediately to slow measurements, while empirical p90 supplies a conservative tail heuristic. Three recent observations are required. State is bounded to128 groups and32 observations per group, expires after900 seconds and starts cold after restart. Failures invalidate the affected group. This is not statistical confidence or an answer-quality score.

For a successful duration `d`, previous peak estimate `p` and elapsed observation time `dt`, the update uses `w = exp(-dt / 60)`. If `d > p`, the new peak is `d`; otherwise it is `p*w + d*(1-w)`. The prediction is the larger of this peak and the retained observations' nearest-rank p90. Reads do not decay the estimate. The implementation and exact cold/expiry rules are in [costs.py](../src/adaptive_inference/costs.py); the formula's original credit is retained even when its external page is unavailable.

Cost identity separates backend kind/address/operator revision, endpoint, workload class, payload-size bucket and non-content controls. Random seeds are pooled without changing outgoing generation seeds. Byte buckets approximate workload shape; they are not tokenizer measurements. Restart the gateway when changing model weights, backend runtime or hardware under the same name, or change `backend.revision` and restart. The generic HTTP protocol does not expose a trustworthy native-process identity for every server.

## Transport and ownership

The gateway strips only its scheduling metadata, preserves quality and tool fields, and streams SSE bytes without rewriting events. It does not retry requests, replay tools, select another model or reduce token budgets. Backend authentication comes from a named environment variable; incoming gateway credentials are not forwarded.

Pending clients that disconnect are removed before dispatch. An active client that disconnects has its upstream response drained under the same admission ownership. A timeout, truncated upstream transfer or oversized response leaves completion uncertain, so future dispatch is blocked. Check the backend's actual state and restart the gateway to recover. This behavior favors explicit recovery over silently overlapping unknown work. It is not native cancellation or a GPU reservation.

Queue waits and upstream operations have configurable deadlines. Response/request sizes and metric history are bounded. Only successful, structurally complete responses train timing feedback; output correctness belongs to a task acceptance check. The metrics endpoint contains request IDs, classes, counters and timing, never prompts, outputs or credentials.

## Resource controls

The generic optional resource floor reads physical RAM and, on Windows, commit availability before dispatch. It does not reserve capacity, observe every backend's GPU use, or resize native caches. Existing backend allocation checks remain authoritative.

The optional `adaptive_headroom` mode adds hysteresis: low or unavailable headroom closes new admission immediately; reopening requires advancing fresh samples above the floor plus a recovery margin for a configured duration. A gateway-owned sampler runs during idle and active periods, with another fresh read before dispatch. Replayed samples cannot earn recovery time, and gaps reset it. The sampler is canceled and awaited on cleanup. This is a read-only admission policy; it never interrupts an active owner or reports an applied native allocation. It adapts medking82's pinned [PR #726](https://github.com/Niko1221/Strata/pull/726) observation rules. [Configuration and examples](portable-policies.md).

`plan_context_budget` is an explicit host-side planner based on the safety margin in medking82's [PR #3684](https://github.com/Niko1221/Strata/pull/3684). The caller supplies the effective context and full rendered prompt count. The planner preserves total output, reasoning and answer reservations, reports infeasibility, and calculates a compaction target. It is never an implicit gateway payload transformation. The host must perform compaction, recount, and retain the engine's own admission check.

Pinned Strata overlays preserve richer memory, parking and lease controls. The historical Windows owner applied fresh startup cache planning and owned process cleanup; it is documented as a platform-specific predecessor, not silently claimed by the portable proxy. Native ports require explicit capability adapters and proof of acknowledgement/ownership before exposing equivalent operations.

## Outcome-based correction

`run_with_feedback` holds the original user prompt, calls an application-provided generator, and passes the result to an explicit validator. A rejection adds feedback for a bounded corrective attempt. Only the validator can accept the result; attempt exhaustion remains failure. The helper neither executes tools nor retries external side effects. Applications should validate real artifacts and retain their own action authorization.

## Durable task state

The [task store](../src/adaptive_inference/task_store.py) and [resumable runner](../src/adaptive_inference/feedback.py) are separate from transient HTTP queue state. Each task retains its original prompt, host identity, attempt budget, messages, outputs and feedback. One cooperating local runner holds the OS task lock. SQLite transactions check the expected revision and owner epoch before committing a transition and its history entry.

The runner commits operation intent before calling generation or validation, commits generated text before validating it, and commits a verdict before another attempt. After process death, committed safe boundaries can resume; an unfinished operation requires explicit reconciliation. A host may explicitly retry pure text generation while retaining its consumed attempt. The store cannot determine the outcome of an arbitrary external action, so an uncertain effect is never automatically replayed. Accepted and exhausted tasks return their saved result without callbacks. See the complete [task survival contract](task-survival.md) and runnable process-restart example.

## Citations

Queue design, Finagle reuse, resource-control research and framework documentation are recorded in [research.md](research.md), [../REFERENCES.bib](../REFERENCES.bib), and [../NOTICE](../NOTICE). The HTTP implementation uses [aiohttp's documented disconnect and shutdown behavior](https://docs.aiohttp.org/en/stable/web_advanced.html). Handler cancellation is disabled intentionally so an active upstream response can drain; the application tracks ownership until completion or a reported uncertain state.
