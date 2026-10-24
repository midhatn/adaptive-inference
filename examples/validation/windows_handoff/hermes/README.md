# Installed Hermes process restart recovery with explicit admission

This opt-in integration uses the unmodified Hermes SDK at
`14e1e43a23761b369641208e204365cd6cb9399d`, its public `AIAgent`, `SessionDB`,
`llm_execution` and `tool_execution` interfaces, and the canonical Adaptive
Inference `TaskStore`. It has no service start/stop capability and never touches
an ordinary Hermes profile. Use a fresh private run directory.

The bounded task reads `orders.csv`, computes its totals and writes `report.json`.
Acceptance requires four rows, seventeen units, 4,350 cents, and exact per-item
totals. The original objective is immutable in TaskStore and retained verbatim in
the native conversation. A restarted agent receives native durable history plus
an explicit host continuation instruction, not a substituted original task.

This v2 successor preserves the failed predecessor unchanged. In that prior
attempt a second Hermes request waited behind resource handoff and the private
nonstream stale watchdog closed its connection after 180 seconds. Its exact
per-call request option was actually `timeout=1800`, not 180: these are different
timers. The predecessor remains uncertain and is not automatically reconciled.

The opt-in public `llm_execution` middleware now short-circuits that private
transport and uses the same installed OpenAI SDK to return a genuine response
to native Hermes conversation, response, tool and transcript handling. It never
calls the middleware's single-use `next_call`. Its private watchdog, transport
relay, provider-specific fallback and streaming paths are outside this adapter.
Only this pinned local nonstream chat-completions route is admitted.

## Waiting and request proof

- Before a provider operation starts, the immutable request is saved with phase
  `waiting_admission`, no in-flight operation and no reconciliation requirement.
  Polling the same gateway's metrics observes resource admission, active/pending
  work and uncertainty. This observation is not a reservation.
- Every prepared SDK POST carries `X-Adaptive-Admission: immediate` and a unique
  `X-Adaptive-Attempt-Id`. The final pre-send boundary checks the exact endpoint,
  attempt headers, unchanged raw body SHA-256 and admission deadline. A deadline
  consumed by durable intent storage prevents the send and conservatively leaves
  that operation unresolved.
- A raced deferral is retryable only for HTTP503 with the exact typed
  `admission_deferred` error and a complete matching no-dispatch proof in both
  JSON and four response headers: dispatch flag, trusted gateway instance,
  attempt ID and SHA-256 of the actual prepared HTTP body. Backend proof headers
  are stripped by the gateway. Partial, duplicate or mismatched proof refuses.
- After a valid proof, the operation is committed as not dispatched and the
  identical request body may be tried after waiting again. Unknown HTTP errors,
  lost responses, changed instance, transport failure, or changed retry bytes
  never trigger a retry. The normal SDK retry count is zero.
- All caller request options are passed unchanged except the two added host
  admission headers. Model, quality, messages, tools, caller headers and finite
  caller timeout are checked; unsupported options fail rather than disappear.
  The exact endpoint forbids query/prefix routing changes, and the local-only
  credential is fixed. This is not a generic provider transport replacement.
- The native request's finite 1800-second HTTP operation timeout is preserved.
  It is not a total inference deadline; slow-drip responses can outlive a read
  timeout. A trusted external owner retains the real worker process handle and
  enforces one 900-second total recovery deadline across both worker processes.
  The same `--deadline-monotonic` value is stored and cannot reset on resume.
  This is same-boot process restart, not reboot survival. It must not be reused
  after reboot without a separate explicit recovery policy.
- At most eight successful provider calls and 32 admission attempts are allowed
  across the task. `wire-observations.json` retains successful provider calls
  (an unknown failed call remains an unfinished audit row). Proven deferrals are
  removed from that list and recorded in `admission-attempts.json` and the
  append-only `admission-events.jsonl`; those records are not model executions.

Same-process proof retries preserve exact HTTP body bytes. A restart at a known
safe waiting boundary uses native saved history and the explicit continuation
instruction, so its newly constructed request is not claimed byte-identical to
the previous process's request. Original objective and completed tools remain
verified. An unfinished dispatched operation still requires reconciliation.

## Recovery contract

- One stable TaskStore OS lock remains held throughout each worker. A concurrent
  cooperating worker cannot construct an agent or execute a tool. Use the same
  canonical local store path; this does not fence unrelated programs.
- Hermes persists each tool-call intent before tool execution. The adapter checks
  that exact native intent, commits its own operation intent, calls the public
  middleware continuation once, then commits the actual outcome.
- Before another provider request, the adapter checks that every completed tool
  receipt is exactly present in native history and commits the safe checkpoint.
  The `safe_after_write` pause occurs here, before dispatching the final request.
- A killed process with an unfinished effect, incomplete cross-database commit,
  changed transcript or changed artifact stops before agent construction. There
  is no automatic effect or validation replay. This runner deliberately does not
  expose even the TaskStore library's optional pure-generation retry mechanism.
- An explicit `reconcile` command requires the exact operation ID, observed native
  success receipt and current file content/hash. It appends a missing tool result
  through the native SessionDB API under its native turn lease, then resolves the
  TaskStore operation. If interrupted between these commits, a repeated explicit
  reconciliation recognizes the exact existing row. Conflicting rows refuse.
- An identical already-completed write may return its saved result without
  invoking the tool again. An unreceipted or changed destination cannot be
  overwritten. Other effects are outside this adapter's admitted capability.
- Hermes deliberately fails open for ordinary middleware exceptions. Admission
  failures therefore short-circuit tools with a structured refusal and set a
  fatal latch; provider refusal uses `RecoveryStop(BaseException)` to escape that
  fail-open boundary. Tests execute the real public middleware dispatcher.

Native SessionDB and TaskStore are separate databases, not a distributed
transaction. Conservative refusal is intentional. Raw native transcripts,
reasoning, tool arguments/results and local paths stay in private run storage.
Publish only selected result fields/hashes. No OS reboot, power-loss, automatic
login startup or arbitrary-tool exactly-once guarantee is claimed.

## Prepare and run

These commands use explicit existing paths; they install nothing. `SDK_PYTHON`
must be the existing interpreter with the exact Hermes SDK dependencies.

```text
SDK_PYTHON -I -B run_recovery.py prepare --run NEW_RUN --hermes-source HERMES_SOURCE --canonical ADAPTIVE_SOURCE --python SDK_PYTHON --gateway-url http://127.0.0.1:18100/v1
```

Preparation creates the isolated home, native database location, original task,
source pins and quality plan. It starts no agent or backend. The model is fixed
to `qwen3.8-flash-next-iq3_s-adaptive-media-beta`; every actual outgoing request
must retain context 65,536, output cap 10,923, high effort, reasoning budget 8,192,
projection false and PCIe fraction 0.37. The native compressor is checked at
threshold 0.8, output reservation 10,923 and derived threshold 46,421. No model
substitution, hidden auxiliary request, provider fallback or uncertain transport
retry is admitted by the existing canonical wire validator.

The external owner must first observe its backend/controller ready, then write
an atomic readiness JSON containing `ready:true`, exact `model`, `quality` and
`gateway` from the plan, `gateway_instance` from the owned gateway's metrics, and
`observed_at` (Unix seconds). The worker accepts this
only within 30 seconds and checks it before constructing AIAgent. This is an
explicit trusted-owner attestation; it is not a capacity reservation.

```text
BASE_PYTHON -I -B run_recovery.py worker --run RUN --controller-ready READY_JSON --deadline-monotonic SHARED_DEADLINE --pause safe_after_write
```

Use the plan's `base_python` directly and retain its `Popen` handle. The script
adds only the explicitly prepared SDK environment's `site_packages`; this avoids
killing a Windows venv redirector while leaving the real worker alive. The
external owner must contain the worker in its job, impose a finite 900-second
total deadline, wait for `pause.json`, verify its PID equals the retained worker,
and terminate/wait that exact process. Never kill by process name. The pause has
its own finite 600-second expiry but is not the outer lifecycle watchdog.

After resource handoff ends and the same-quality backend is ready, make a fresh
readiness receipt and start the same worker command without `--pause`, retaining
the identical `--deadline-monotonic` value. Do not
repeat prepare or copy the database. The accepted run is a no-op on later starts.
The total provider budget is eight across all processes. No model request should
be sent while a tool resource lease is held. Controller/engine cleanup remains
the external owner's responsibility.

For the fixture's deliberately uncertain write only, explicitly inspect the
single saved `effect-receipts.jsonl` record and current artifact, copy that one
record to a JSON evidence file, then invoke:

```text
BASE_PYTHON -I -B run_recovery.py reconcile --run RUN --receipt OBSERVED_RECEIPT_JSON --operation-id EXACT_OPERATION_ID --deadline-monotonic SHARED_DEADLINE
```

This command does not construct an agent or call a provider.

## Verification

```text
SDK_PYTHON -I -B test_recovery.py --canonical ADAPTIVE_SOURCE --hermes-source HERMES_SOURCE --python SDK_PYTHON --output NEW_PROOF
SDK_PYTHON -I -B test_admission.py
```

The tests use synthetic provider responses through the real installed SDK, real
file tools and native SessionDB, actual subprocess termination, and retained
process handles. Network/model requests are denied. They cover safe resume,
original/native-prefix retention, one write, concurrent-owner refusal, terminal
no-op, changed-artifact refusal, two blocked uncertain resumes, wrong-operation
refusal, explicit reconciliation and the real fail-open middleware boundaries.
The test receipt records hashes of the exact sources tested. These are SDK and
process-crash tests, not real inference or a resource-handoff performance result.
The fixture includes a **synthetic clock** waiting over 180 seconds, followed by
a raced complete no-dispatch receipt and an identical-body retry; this is not
180 seconds of wall-clock waiting. The actual installed middleware/SDK and native
tools still execute, with a sentinel that raises if private
`_interruptible_api_call` is invoked. Unknown transport failure retains native
read progress and blocks the next process before provider/tool execution.
Separate SDK MockTransport tests cover complete option preservation, proof
mismatch and spoof rejection, zero ordinary retries, changed bytes blocked before
send, and deadline consumed by durable storage blocked before send. Exact final
test counts and source hashes are in `fixture-receipt.json`; no real model was
launched by this lane. Actual multi-minute foreground waiting requires a separate
root-owned real integration run.

## Source and license

Original adapter/runner/tests: Apache-2.0, matching the canonical repository.
No Hermes source is copied into this integration. Public interfaces inspected at
the exact [Hermes commit](https://github.com/NousResearch/hermes-agent/tree/14e1e43a23761b369641208e204365cd6cb9399d)
include `hermes_cli/middleware.py`, `hermes_state_messages.py`,
`hermes_state_compression.py`, `agent/turn_tool_round.py`,
`agent/turn_facade_lease.py`, `agent/turn_api_call.py` and `run_agent.py`.
Hermes retains its upstream MIT license in the canonical source preservation.
`source-lock.json` pins these inspected sources and consumed canonical helpers.
TaskStore's retained source attribution names medking82's Strata archive
transaction pattern at PR1136; the owner fencing/effect ledger are separate
Adaptive Inference additions, not upstream archive functionality.
