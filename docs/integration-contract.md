# Integration contract v1

This is the common boundary for engine and agent integrations. The canonical
implementation lives here; upstream contributions configure an existing client,
use a supported host hook, or supply a small native adapter. They do not need to
copy the scheduling algorithm or depend on a historical PR.

The HTTP contract is available in [v0.2.0](https://github.com/midhatn/adaptive-inference/releases/tag/v0.2.0).
Version 0.3.0 adds the configurable Python routing helper, protected generation
options and public-hook/plugin recipes. Consumers must pin the release or commit
containing the files they use; a model receipt identifies its own tested composition.

## Agent-facing HTTP boundary

| Concern | Contract | Host responsibility |
| --- | --- | --- |
| Interactive route | `GATEWAY/v1` | Select an explicitly configured endpoint and the existing served model ID. |
| Background route | `GATEWAY/background/v1` | Select it for a known worker, auxiliary job or explicitly background session. This route cannot promote a request to normal. |
| Per-request class | `X-Adaptive-Class: background` or `adaptive_scheduling: {"class": "background"}` | Use host task metadata. Never classify or authorize from model-produced prompt text. Conflicting hints are errors. |
| Generation | Chat Completions, text completions and embeddings only where the engine profile supports them | Keep the model, precision, context, explicit output/reasoning limits, sampling, tools and media settings. Verify model-specific support. |
| Response | JSON and SSE forwarded; routing fields removed before backend dispatch | Verify the client preserves fields essential to the task. Some clients omit vendor reasoning fields even when the gateway forwards them. |
| Authentication | A configured gateway key is separate from backend credentials | Resolve credentials from operator configuration, never from model output. Do not log or publish keys. |
| Queue | One shared bounded queue and one active upstream inference request | Use a client timeout that includes the configured queue wait and inference duration. This design can reduce native batching throughput. |
| Retry | No automatic generation retry in the gateway | Disable automatic retries where an ambiguous completion could duplicate work. Reconcile the operation before a deliberate new attempt. |
| Cancellation | A queued request can leave the queue; a disconnected active request is drained | Do not claim native cancellation or released resources from a closed HTTP connection. An uncertain backend completion blocks dispatch until reconciled and the gateway restarted. |

`normal` is a queue class, not real-time priority or an authorization level.
The gateway's configured background default also prevents promotion. Queue
ordering uses bounded arrival offsets and observed execution costs; it cannot
interrupt an active model request. There is no guaranteed wall-clock deadline.

Responses API, Anthropic Messages, downloads, model management, GPU preemption,
tool resource leases and arbitrary native lifecycle calls are outside this HTTP
contract. Native adapters may add separately documented controls only after
their own acknowledgement and ownership checks are implemented and tested.

## Reusable Python route selection

On a revision containing `adaptive_inference.client_routing`, use:

```python
from adaptive_inference.client_routing import gateway_client_options

route = gateway_client_options(
    base_url="http://127.0.0.1:18100/v1",
    background=True,
    # api_key_env="ADAPTIVE_GATEWAY_KEY",  # when the listener requires a key
)
```

Pass `route` to the existing client's constructor alongside the actual model
and its verified generation settings. The helper returns only `base_url` and
`api_key`; it does not construct a client or send a request. An already-background
base stays background. Custom ports, IPv6 and an explicit reverse-proxy path
prefix are preserved. The operator must map that prefix to the gateway routes.
Credentials are read only when the helper is called, and an explicitly missing
key fails. The returned dictionary contains a credential and must not be logged.

The LangGraph, CrewAI and retained AutoGen recipes accept `gateway_base_url`,
`api_key_env`, `background` and `generation_options`. They reject route/client
overrides in generation settings instead of silently overriding the selected
transport. Without a key reference, `local` is a placeholder for SDKs that
require a value; it is not authorization to an authenticated listener.

## Native resource boundary

Readiness is an observation, not a reservation. An adapter claiming a native
handoff must verify its own process/operation identity, drain or cancel active
work with an acknowledgement, release the requested resources, obtain a fresh
capacity reading, and reserve or otherwise protect the tool's admission. It
must release its ownership after success, failure or cancellation and verify
the resources before resuming inference. Unsupported capabilities remain
unavailable. A compatible `/v1` endpoint alone does not satisfy these steps.

The preserved Strata resource work is documented separately in the
[native reproduction guide](legacy-reproduction.md). No generic recipe inherits
those capabilities merely by using the Strata engine profile.

## Durable task boundary

The host keeps the original objective, acceptance check, completed outputs and
feedback. The [task store](task-survival.md) can preserve those checkpoints and
enforce one cooperating local owner. A host must distinguish pure generation
from effects, persist before an effect, and reconcile an uncertain interrupted
effect before retrying. The gateway does not replay agent tools or restore
arbitrary applications after an operating-system restart.

## Acceptance for a new integration

1. Pin the canonical source and the tested host/engine version. Use existing
   public configuration or extension points before changing core behavior.
2. Run an actual client against a local fixture and inspect the emitted route,
   model, output allowance, vendor controls, tools and streaming behavior used
   by the integration. Label unsupported and untested paths explicitly.
3. Run a bounded real task on the deployed model, check its output independently,
   and retain failures. For this project's current hardware qualification, all
   actual inference runs use the existing IQ3_S model and its recorded quality
   settings; a fixture response is not model evidence.
4. Exercise the added lifecycle behavior, including pending and active failure
   cases. A configuration recipe need not claim native resource lifecycle.
5. Preserve source, reproduction instructions, attribution for actual reuse,
   and the exact evidence here. Record upstream delivery separately, including
   archived projects and maintainer conditions that prevent submission.
