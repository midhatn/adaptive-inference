# Timing measurements across model replacement

A persistent controller can outlive the model process. When the restored
process has a different memory/cache plan, its request timings must start from
fresh observations. The optional runtime timing mode reuses the existing cost
model for each verified native owner. Model precision, context, output allowance
and generation options are unchanged.

This is a portable, tested component. The native host must explicitly wire it
before a new complete IQ3_S qualification. It makes no speed improvement claim.

## Integration contract

Construct `Gateway` or `create_app` with `runtime_timing=True`, and bind the
handoff controller's `on_verified_owner` callback to `gateway.activate_runtime`.
The trusted host supplies its already-verified native identity; this is not an
HTTP endpoint or a caller-controlled priority/identity field. Keep the existing
`scheduler.capacity is controller` binding.

Gateway startup establishes the owning event loop. Warm controller initialization
must follow it. Cold parked initialization does not activate a runtime; a later
verified restore activates timing after the demand/open checks and immediately
before readiness. There is no await between this binding and the ready-state
decision. Activation failure keeps native ownership for cleanup and closes
admission through the controller fault.

Activation requires closed admission and no active, uncertain or closing
scheduler. The same current owner retains its measurements. A different owner
gets a new bounded learner with the same limits; an old owner label returning
later cannot restore discarded samples. Unknown or unavailable runtime context
exposes a cold prediction rather than an old estimate.

When a request actually acquires its scheduler ticket, it captures that runtime's
learner before any upstream await. Both successful and failed observations use
the captured learner. A delayed completion cannot train a replacement runtime.
Missing execution context refuses before contacting the backend, trains nothing
and releases only the known-unstarted ticket. It does not issue a new
non-dispatch/retry proof or hide a release failure.

Queued work retains its arrival time, ticket, rank and deadline. A prediction
made under an earlier runtime remains a historical ordering hint. Metrics label
the prediction and execution generations separately; they do not relabel that
prediction as a measurement of the new runtime. This increment does not rerank
the queue or change fairness.

The option is disabled by default. Existing status/history shapes remain
unchanged in that mode. Enabled status exposes bounded generations and reasons,
without native owner IDs, process IDs, profile paths, prompts or responses.

## Reuse and validation

This adapts the lifecycle pattern in pinned [Finagle Peak EWMA](https://github.com/twitter/finagle/blob/9cc08d15216497bb03a1cafda96b7266cfbbcff1/finagle-core/src/main/scala/com/twitter/finagle/loadbalancer/PeakEwma.scala):
the metric belongs to its endpoint and request completion retains that metric.
The existing attributed Peak EWMA/p90 learner is unchanged, including its
three-sample minimum, expiry, failure invalidation and bounds. Finagle's existing
Apache-2.0 license and notice remain included. No new statistical algorithm is
introduced. [aiohttp lifecycle guidance](https://docs.aiohttp.org/en/stable/web_advanced.html#background-tasks)
informs the owning-loop and retained-work requirements.

Nineteen component fixtures and four independent regression cases use actual
aiohttp/scheduler behavior with local fake backends. They cover queued owner
changes, cold and same-owner behavior, delayed success/failure, partial streams,
cancellation, callback failure and cleanup ownership. The unchanged gateway,
cost-model and handoff suites remain compatibility checks. No fixture response
substitutes for real-model quality or native-resource validation.

Run `python -m unittest discover -s tests -p "test_runtime_timing*.py" -v`.
The [reviewed inputs and promotion lineage](../provenance/persistent-desktop/reviewed-timing/README.md)
remain in this source archive. The [complete accepted M1 runtime](../provenance/persistent-desktop/README.md)
stays available under its original hashes; current runtime changes do not alter
that historical result's source identity.
