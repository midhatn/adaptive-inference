# Explicit clock and verified Pause activity successor

The first installed paused-expiry trial is a preserved failure. Its wheel hash is
`74aa5c1be1214a0dd79b589fffdef78440af996785581af71b2d0610bd01c74e`.
Its worker produced an expiry receipt, but the host's strict future-seal check
rejected it. Both had saved the same numerical deadline; CPython3.11.9 used
GetTickCount64 for monotonic time while CPython 3.14.7 used QPC. Separately, Hermes
reported a committed watchdog abort during the long deliberate Pause. Neither
observation is hidden or converted into a passed installed trial.

This record preserves the seven changed predecessor files under `sources/`, hashes
the 45 unchanged runtime files, and pins the two added modules. It layers on the
existing expiry provenance instead of replacing its historical fingerprints.
The restoration helper first validates each exact clock-successor AST seam,
restores it to the failed predecessor, and then runs the earlier complete-source
comparisons. New module hashes and semantic mutation cases remain explicit.

The final origin-pin check adds five adopted SDK interfaces to the existing
disk/import-origin map (14 to 19 entries). This closes a mixed-preloaded-SDK gap
without changing the existing checker or loader. The provisional clock repair
and its independent 449-check result remain preserved; only this declared pin
map and its focused origin/preservation tests follow that review.

The correction uses Python's standard performance counter and an explicit saved
clock domain. It keeps the original 900-second execution deadline, strict
pre-Pause/expiry ordering, 8-request limit, 240-second readiness limit, 1800-second
qualification guard, IQ3_S quality and exactly-one-effect report acceptance.
Local elapsed timers are not converted into another domain. There is no automatic
budget renewal or reboot continuation.

Pause activity uses the existing owner thread and pinned Hermes activity method
after successful safe-state and lease reads. It is not a second scheduler or a
background heartbeat. The SDK's 600-second watchdog and 15-second polling remain
unchanged. A verified normal SDK return has a distinct post-turn guard state;
aborted or unknown turns cannot enter it by merely having no lease holder.

All project predecessor and successor files are Apache-2.0. The exact adopted
Hermes source references are from Nous Research's MIT-licensed Hermes Agent,
copyright 2025 Nous Research, commit
`14e1e43a23761b369641208e204365cd6cb9399d`; their hashes are in
`sdk-references.json`. No SDK implementation is copied into the public runtime.
Primary clock and SDK references are linked in the
[feature document](../../../docs/paused-budget-expiry.md).

CPU fixtures and bounded executions of actual pinned SDK watchdog/activity/lease
methods validate these contracts without a model or GUI. They do not replace the
required independent acceptance of a fresh installed 900-second expiry trial.
