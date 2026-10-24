# Owned native resource handoff

This Windows adapter exposes a previously qualified Strata owner's lifecycle to
the shared handoff controller. It closes no unrelated process, runs no tool,
changes no generation quality setting, and performs no automatic retry of an
uncertain transition. The caller owns queue admission and competing work.

```python
adapter = NativeOwnerAdapter(
    package=operator_package_directory,
    manifest_sha256=operator_manifest_pin,
    provenance_sha256=operator_provenance_pin,
    max_runtime_seconds=900,
)
initial = await adapter.status()
# The shared controller first closes admission and drains its active request.
proof = await adapter.stop(initial)
capacity = await adapter.fresh_capacity()
# Only the caller may decide to start its separately owned competing work.
# After that work's exact processes exit and recovery is sustained:
replacement = await adapter.start()
await adapter.close()
```

`status()` and `start()` return `owner_id`, `ready`, `loaded`, the retained owner
creation identity, and the package owner's status. `stop()` accepts that full
status, its compact `identity`, or its previously observed `owner_id`. It returns
`released`, `cleanup_confirmed`, `retained_processes`,
`confirmed_process_exits`, `port_free`, and independently retained exit records.
The normal server drain must finish with exit zero. Emergency owner termination
is a failure receipt, never permission to run a tool.

The adapter keeps the package's existing `state/start.lock` locked from stop
through the entire parked interval and replacement readiness. Cooperating
ordinary starts therefore cannot race the competing task. A caller that elects
to leave the engine stopped must first prove its competing work has exited,
then explicitly call `close(release_parked=True)`. Closing the coordinator
process releases the operating-system lock; durable recovery must reconcile
any interrupted external work before it starts a new controller. The adapter
does not claim exclusion against arbitrary programs or another direct `_host`
invocation that deliberately ignores the cooperative start contract.

`fresh_capacity()` returns a monotonic acquisition-start timestamp,
`complete`, `available_ram_gib`, `available_commit_gib`, and
`available_vram_mib`. It uses the preserved NVML/Windows readers. A valid low
reading is observable and may recover; invalid, delayed or stale sensing fails
closed. This sampler does not change the live owner's emergency guard. Free
capacity is an observation, not an operating-system reservation.

## Standalone source and prerequisites

`owner_source/` preserves all five original owner/helper modules. Its inventory
records both original and preserved SHA-256 values. The only portability edit
is that `engine.py` reads `dependencies.strata_python` from the operator's
`PROVENANCE.json` instead of a personal directory constant. The existing live
installation is not edited. The source snapshot is sufficient to review the
complete process-control implementation without a historical benchmark folder.

This is a Windows, single RTX 4070 Laptop GPU adapter. The NVML reader explicitly
checks that device and its 8-GiB capacity range. Other devices need a separately
reviewed reader rather than bypassing this check. The owner needs Python 3.11
and `psutil`, a suitable Strata Python environment, and the operator's NVIDIA
driver. Neither environment binaries nor models are redistributed here.

To construct a new operator package:

1. Restore the canonical `integrations/strata` offline source and overlays into
   a new `runtime/Strata` directory. This preserves the working `c6b23493` source
   composition plus the separate private-file access correction. Keep the
   Strata and dependency licenses. Follow `docs/legacy-reproduction.md` and the
   restored source's native build instructions to build CUDA native executables
   into `runtime/native`. A build on another machine is a new qualification;
   the recorded historical executable hash is evidence, not a supplied binary.
2. Place these five owner sources at the package root. Supply
   `config/server-template.json`, `runtime/expert-profile.seed.bin`, and
   `runtime/tokenizer` assets using explicit local paths. Acquire the licensed model and
   CPU vision projector separately. Do not copy historical runs or credentials.
3. Write `PROVENANCE.json` with explicit `dependencies.strata_python`,
   `dependencies.owner_python` (the actual base interpreter), and
   `dependencies.nvml`. Pin those interpreters, applicable runtime DLLs and
   virtual-environment configuration under `dependencies_sha256`. Record model
   assets under `asset_metadata` with exact byte size and modification time;
   this inherited contract does not hash their full contents. Record the native
   executable hash. All these paths are operator input, never downloaded code.
4. Preserve the qualified settings: loopback port 18098, IQ3_S, context 65536,
   high reasoning with 8192 reasoning tokens, main request cap 10923, projection
   disabled, MTP disabled, and CPU vision. Set `idle_unload_s=0`: the handoff
   adapter rejects an independently enabled native idle timer. The owner chooses a conservative
   resident-cache allowance from fresh RAM/commit observations, with unchanged
   14-GiB overhead and 4-GiB headroom. The selected allowance is a per-run cap.
   The owner verifies its source/native paths, context and quality settings
   before launch and binds final config and arguments to the server's launch
   attestation. Clients remain responsible for the explicit 10923 request cap.
5. Write `MANIFEST.json` with `files`, a mapping of each package-relative source,
   config, tokenizer and native path to SHA-256, including `PROVENANCE.json`.
   Supply the manifest and provenance SHA-256 values explicitly to the adapter.
   `engine.py verify --json` performs the inherited package validation without
   starting the model. Do not include mutable `state/` or `runs/` in that seal.

These are build prerequisites, not a claim of a portable precompiled environment.
For an existing sealed owner matching the preserved helper lineage, the explicit
preparation command creates a separate new package without starting a process:

```console
python prepare_handoff_owner.py --source-package EXISTING_OWNER --source-manifest-sha256 BASE_MANIFEST_PIN --source-provenance-sha256 BASE_PROVENANCE_PIN --output NEW_OWNER_DIRECTORY
```

It verifies every reused file, copies only source/native/tokenizer/seed inputs,
uses the preserved parameterized owner helpers, relocates package paths, and
changes `idle_unload_s` to zero. Model files, environment binaries, old runs,
state and credentials are not copied. An existing destination is refused. Its
new manifest, provenance and `HANDOFF-PREPARATION.json` record the source pins,
copied bytes and exact configuration changes. The original owner is untouched.

## Why use an owner cycle

The preserved idle/lease reload path uses a measured RAM, commit and VRAM
footprint plus headroom. The earlier failed reload reported required RAM of
55,901,364,224 bytes against 50,850,979,840 bytes available. The request waited
in admission without a native generation until its client deadline. The
footprint includes a conservative 14-GiB startup overhead, then reload adds
headroom. We do not weaken that calculation. A fresh owner uses the existing
fresh-capacity startup-cache planner, then verifies the same model/context/
reasoning configuration. This is a whole-owner release/reload, not live GPU
preemption or resumption of an interrupted generation.

## Dedicated desktop host

`windows_host.py` composes the unchanged canonical gateway and handoff controller
with this adapter and the sibling `foreground/activity.py` reader. Keep that
relative layout. Run it in a dedicated worker process; it joins a Windows
kill-on-close job before it creates any model or tool children. The native owner
adds its own nested job. The host refuses to adopt an existing live backend.

```console
python windows_host.py --owner-config OPERATOR_OWNER_JSON --gateway-config OPERATOR_GATEWAY_JSON --run NEW_RUN_DIRECTORY --max-runtime-seconds 900
```

The owner JSON supplies `package`, `manifest_sha256`, `provenance_sha256`, and
an optional bounded `max_runtime_seconds`. The gateway JSON selects backend
`strata`, `http://127.0.0.1:18098/v1`, and a different loopback listening port.
Neither configuration launches arbitrary tools. The callable interface is
`DesktopHost(owner_config, gateway_config, run, policy=None)`, with async
`start()`, `wait_ready()`, and `close()`, and exposed `controller`, `adapter`,
`gateway`, and `app` for the trusted local host.

Sampling continues independently while native transitions wait. During startup,
`status.json` is written immediately and refreshed every half-second, with a
`host_phase` such as `waiting_foreground` or `native_starting` and the existing
sanitized policy/sensor snapshot. Startup first requires fresh sustained
foreground clearance. Readiness is a short-lived observation: activity can
immediately close admission afterward. The same startup deadline covers policy
waiting, native loading and controller initialization. An initiated native start
is still reconciled under the owner's independent 300-second startup bound
before cancellation propagates; if it returns after the host deadline, the host
refuses readiness and normally closes that exact owner. There is no implicit
extra readiness second. The independent finite host timer requests shutdown,
then allows 130 additional seconds before exiting its own dedicated process and
closing the containing job. This hard fallback is not a normal-drain receipt.

Normal shutdown closes gateway admission and its listener, waits for active
inference and tool grants to finish, refuses while unrelated owned workers
remain, and stops only the recorded native owner. Root callers must retain and
wait their tool/agent process handles, then complete their grant. A timeout is
not proof of tool exit. An explicit private release receipt contains full
process identities; `status.json`, `ready.json`, and `result.json` expose only
bounded observations, counts, opaque owner IDs and task-independent events.
The host does not collect window titles, paths, keyboard contents or prompts.

The original installed profile still has native `idle_unload_s=60`. After a long
clear/idle period, Strata may unload internally while the desktop controller
retains its last ready identity; the next request can reach the conservative
native reload-capacity wait described above. The handoff adapter now rejects
that profile. Its separate prepared package disables only that independent
idle timer, leaving foreground/idle lifecycle decisions with this host while
preserving native memory guards and quality. This removes the known second
controller conflict; a prepared profile is not itself a completed long-idle
hardware qualification.

## Validation scope

Run after installing the canonical Python package:

```console
python -m unittest -v test_native_owner_adapter test_windows_host test_prepare_handoff_owner
```

The fixture suite checks exact identity refusal, complete release proofs,
cooperative restart exclusion, cancellation, clean initial startup, invalid and
stale capacity, low-memory recovery, and actual `HandoffController` composition.
The predecessor adapter admitted the original installed package; the current
adapter admits the separate prepared idle-zero package and reads its stopped
status plus fresh capacity without starting or stopping any model. These are
CPU/read-only checks. Actual foreground release and reload remain a separate
hardware acceptance gate; prior owner results do not automatically qualify this
new composition.

The native job mechanism follows Microsoft's [Job Objects documentation](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).
The capacity reader follows NVIDIA's [NVML device-query API](https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceQueries.html).
The original local adapter and owner code use the canonical project's Apache-2.0
license; imported Strata code retains its existing license and source pins.
