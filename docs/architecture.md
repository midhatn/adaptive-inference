# Architecture and contracts

The portable component is a single-backend HTTP gateway. Multiple application types share one queue and one active upstream HTTP request. `/background/v1` is a demoted route into that same queue, not a second server with independent capacity accounting.

## Queue and feedback

Rank is arrival time plus a bounded background offset plus a bounded estimated execution cost. Unknown costs use the maximum cost offset. Rank is fixed at enqueue and sequence breaks ties. Requests older by more than the combined offset cannot be overtaken by a later arrival; this is an ordering bound, not a completion-time guarantee.

The cost model reuses the tested Strata module: Peak EWMA responds immediately to slow measurements, while empirical p90 supplies a conservative tail heuristic. Three recent observations are required. State is bounded to128 groups and32 observations per group, expires after900 seconds and starts cold after restart. Failures invalidate the affected group. This is not statistical confidence or an answer-quality score.

Cost identity separates backend kind/address/operator revision, endpoint, workload class, payload-size bucket and non-content controls. Random seeds are pooled without changing outgoing generation seeds. Byte buckets approximate workload shape; they are not tokenizer measurements. Restart the gateway when changing model weights, backend runtime or hardware under the same name, or change `backend.revision` and restart. The generic HTTP protocol does not expose a trustworthy native-process identity for every server.

## Transport and ownership

The gateway strips only its scheduling metadata, preserves quality and tool fields, and streams SSE bytes without rewriting events. It does not retry requests, replay tools, select another model or reduce token budgets. Backend authentication comes from a named environment variable; incoming gateway credentials are not forwarded.

Pending clients that disconnect are removed before dispatch. An active client that disconnects has its upstream response drained under the same admission ownership. A timeout, truncated upstream transfer or oversized response leaves completion uncertain, so future dispatch is blocked. Check the backend's actual state and restart the gateway to recover. This behavior favors explicit recovery over silently overlapping unknown work. It is not native cancellation or a GPU reservation.

Queue waits and upstream operations have configurable deadlines. Response/request sizes and metric history are bounded. Only successful, structurally complete responses train timing feedback; output correctness belongs to a task acceptance check. The metrics endpoint contains request IDs, classes, counters and timing, never prompts, outputs or credentials.

## Resource controls

The generic optional resource floor reads physical RAM and, on Windows, commit availability before dispatch. It does not reserve capacity, observe every backend's GPU use, or resize native caches. Existing backend allocation checks remain authoritative.

Pinned Strata overlays preserve richer memory, parking and lease controls. The historical Windows owner applied fresh startup cache planning and owned process cleanup; it is documented as a platform-specific predecessor, not silently claimed by the portable proxy. Native ports require explicit capability adapters and proof of acknowledgement/ownership before exposing equivalent operations.

## Outcome-based correction

`run_with_feedback` holds the original user prompt, calls an application-provided generator, and passes the result to an explicit validator. A rejection adds feedback for a bounded corrective attempt. Only the validator can accept the result; attempt exhaustion remains failure. The helper neither executes tools nor retries external side effects. Applications should validate real artifacts and retain their own action authorization.

## Citations

Queue design, Finagle reuse, resource-control research and framework documentation are recorded in [research.md](research.md), [../REFERENCES.bib](../REFERENCES.bib), and [../NOTICE](../NOTICE). The HTTP implementation uses [aiohttp's documented disconnect and shutdown behavior](https://docs.aiohttp.org/en/stable/web_advanced.html). Handler cancellation is disabled intentionally so an active upstream response can drain; the application tracks ownership until completion or a reported uncertain state.
