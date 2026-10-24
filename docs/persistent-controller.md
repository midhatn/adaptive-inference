# Demand-aware controller component

The handoff controller can optionally observe durable task demand independently
of HTTP requests. This lets a future persistent host start cold and restore its
model for a safely waiting task. The existing bounded host keeps its prior
behavior when demand mode is omitted.

This document describes the portable component. The persistent native host,
installed-agent control hooks and user interface still need their combined live
acceptance. The accepted M1 result remains bound to its original runtime, whose
complete package source is [preserved locally](../provenance/persistent-desktop/README.md).

## Three separate decisions

1. **Restoration:** require a fresh eligible observation from the explicitly
   configured `DemandRegistry`, current foreground clearance, explicit model
   headroom floors, verified parking, an open scheduler and no active tool.
   Recheck the relevant observations after awaited work, including startup.
2. **Dispatch:** use the existing scheduler and ready native-owner admission
   gate. Do not make restoration eligibility a dispatch requirement. A prepared
   generation is already in flight in the durable ledger before sending its
   request; treating it as ineligible dispatch would deadlock the same request.
3. **Idle release:** require verified absence of demand throughout the configured
   idle grace, no active or pending scheduler request, and no tool owner. Use
   the existing drain and exact-owner release proof. Foreground/tool pressure
   can request the normal drain without waiting for idle grace.

Paused, cancelled, fulfilled or genuinely terminal tasks can establish absence.
An unresolved operation, reconciliation requirement, invalid checkpoint,
regressed revision, failed read or stale observation cannot. A busy or unknown
task is not an idle task merely because its restoration eligibility is false.

`refresh_demand()` reads only the configured registry. It never claims a task,
acknowledges cancellation or changes checkpoints. Its timestamp starts before
the read, and a retained lock serializes overlapping observations. The host
must poll independently while native start/stop awaits; it must retain and join
that observer on shutdown. A SQLite timeout is not a hard filesystem deadline.

## Optional cold initialization

Construct `HandoffController` with `demand`, explicit `restore_requirements`,
`idle_grace_s` and `demand_max_age_s`. Bind its existing scheduler, then call
`initialize(parked=True)` only with an adapter implementing `prepare_parked()`.
That adapter must prove its startup barrier is held, owner lock is idle,
backend port is free and containing process group has no other owned work.
There is no invented loaded identity or release receipt before the first load.

If an earlier owner exists, its identity and cleanup must be verified. A new
load must return a distinct exact owner. During startup, the host must continue
observing foreground activity and demand. If cancellation or pressure arrives,
retain the returned owner and use normal drain/release; never cancel an await
and assume that its native child disappeared. Unknown startup outcomes fault
closed and require reconciliation.

The native composition must also reuse the actual backend startup planner.
Headroom floors and an advisory RAM/cache estimate do not prove GPU allocation
or reserve memory. Model precision, context and request quality remain fixed.

## Required host integration

The cooperating worker must record safe demand before waiting for model
readiness. It must consume previously saved controls first, so a pre-existing
pause/cancel cannot briefly request a load. Waiting uses immediate admission
and the existing authentic non-dispatch proof; an unknown response cannot be
cleared to make demand eligible again.

The controller does not authenticate clients, install a service, manage UI
intent or migrate legacy task metadata. The first persistent composition needs
explicit trusted bindings, lifecycle ownership, bounded storage and separate
user controls. Timing history also needs a new runtime identity or reset when
a replacement owner changes the effective cache/runtime. These integration
requirements remain part of M2, not evidence supplied by component tests. The
optional [runtime timing component](runtime-timing.md) now provides the verified
owner callback and captured execution learner; the host must explicitly enable
and bind it before live qualification.

## Research and verification

This adapts the [existing durable-demand research](durable-demand.md), including
KEDA activation/cooldown and Temporal durable waiting, to this repository's
TaskStore and native handoff contracts. The separate decisions avoid replacing
the queue, database, native owner or statistical learner. Existing foreground
recovery dwell retains its attributed Strata/medking82 lineage.

Twenty-three new fixtures use the real durable ledger with fake native
acknowledgements. They cover cold startup, ticket-free demand, preparation before
dispatch, stale/unknown observations, idle grace, cancellation during capacity
measurement/startup, active work, owner replacement and shutdown fences. The
34 existing handoff tests also run with demand mode disabled. These are CPU
component tests; they do not demonstrate a real model load or desktop behavior.

Run `python -m unittest discover -s tests -p "test_handoff*.py" -v` against the
installed checkout. Source lineage and the exact accepted M1 predecessor are
preserved alongside the reviewed controller, rather than relying on an external
PR remaining available.
