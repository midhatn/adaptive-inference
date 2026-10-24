# Queued-provider predecessor: retained failed source

These files preserve the exact harness and Hermes consumer used by the earlier
`controlled-03` attempt. That attempt completed the native owner handoff and
protected video-tool phases, but **did not complete real-agent restart
acceptance**. Hermes' 180-second stale-provider watchdog expired while a request
waited behind closed desktop admission. The task retained an unresolved
generation; a safe restart boundary was not reached. Final owned cleanup was
verified separately. This archive does not turn that failed attempt into a pass.

`source-manifest.json` binds the original bytes. The harness hash matches the
failed run's receipt; the four Hermes files match their original export manifest.
`runtime/gateway.py` and `runtime/scheduler.py` also match the exact Git blobs at
`ed261587234ec9938f680acc460bfdef26ceb419`, the preceding published main revision.
The manifest pins the remaining unchanged core, native and foreground helpers
at their canonical paths.
No source text was rewritten. The source contains the authored synthetic CSV
tasks and a `local-no-key` placeholder. Private run logs, database contents,
machine configurations, transcripts, credentials, model assets and binaries are
not included.

The successor uses explicit immediate admission and durable waiting outside the
provider call. Its source and evidence belong to the current
[Windows handoff example](../../../examples/validation/windows_handoff/README.md).
The predecessor's ordinary queued calls must not be described as having that
successor behavior.

## Source layout and prerequisites

To inspect or exercise this historical consumer, create a **new private working
directory**. Copy this directory's `run_validation.py` and `hermes/` into it, then
copy the unchanged `native/` and `foreground/` helpers from
`examples/validation/windows_handoff/` into sibling directories. Do not overwrite
the current example. The harness resolves these sibling paths from its own file.

Restore Hermes revision `14e1e43a23761b369641208e204365cd6cb9399d` through
[the preserved current-source supplement](../../../integrations/hermes/current-source/README.md).
Use the current example's explicit dependency, owned-native-package and model
prerequisites. Operator-supplied paths, a fresh private run directory and the
existing qualified IQ3_S model are still required for any hardware execution.
The source does not fetch a model or install an ordinary user profile.

`hermes/test_recovery.py --help` describes the explicit arguments for its
CPU-only actual-SDK/process fixtures. Those fixtures use synthetic provider
responses and remain separate from the failed model run. Inspect the archived
source before any historical execution; rerunning it is not a required setup
step for the successor.

This directory preserves the failed **consumer source and prior queue/gateway**,
not the operator's installed environment. For source comparison, place the two
`runtime/` files at `src/adaptive_inference/` in a separate private repository
copy and verify every shared dependency against the manifest; leave the current
repository unchanged. Merely running the old harness against a current gateway
does not reproduce the historical combination. Neither source restoration nor
the recorded hashes recreate hardware timing or an installed dependency runtime.
Do not infer a historical pass, speedup, reboot survival or arbitrary-tool
exactly-once behavior from this source archive.

Original Adaptive Inference integration code is Apache-2.0. Hermes' public
interfaces are consumed under the upstream MIT license retained with the source
supplement; no Hermes implementation source is copied into this directory.
