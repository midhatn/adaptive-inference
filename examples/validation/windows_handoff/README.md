# Reproduce foreground handoff and installed-agent restart

This is the complete bounded Windows qualification source. It composes the
portable `adaptive_inference.handoff` runtime, the preserved native owner and
the installed Hermes SDK. Every real inference request uses the operator's
existing `qwen3.8-flash-next-iq3_s-adaptive-media-beta` with context 65,536,
output allowance 10,923, high reasoning, an 8,192 reasoning-token budget,
projection disabled, PCIe fraction 0.37, vision on the CPU and MTP disabled.

Use a dedicated worker process and fresh private output directories. Install
this repository's locked Python dependencies first. These examples do not
install or replace the user's ordinary agent profile or model server.

1. Follow [native prerequisites](native/README.md) to construct or select the
   pinned owned package. Write a private owner configuration with `package`,
   `manifest_sha256`, `provenance_sha256` and `max_runtime_seconds` (900 in the
   qualification). Verify its package hashes and confirm it is stopped. The
   adapter refuses to adopt a live owner.
2. Restore the pinned current Hermes source using this repository's
   `integrations/hermes/current-source/restore_delta.py`, and provide an existing
   interpreter with its exact dependencies. Prepare the isolated task using
   [the recovery instructions](hermes/README.md); omit `--fixture` for a real run.
3. Run the [foreground baseline](foreground/README.md) with the same 45-second,
   60-Hz settings used by the comparison. Activate the actual window normally
   and leave it visible. No model runs during this baseline.
4. Launch `foreground/quiet_window.py` in its own bounded process and activate
   it as the quiet desktop phase. It performs no recurring work and closes
   automatically after 30 minutes. The policy still observes genuine OS
   signals. A busy foreground application can legitimately hold startup or
   recovery; do not replace that observation with fabricated idle data.
5. Run `run_validation.py --case uncontrolled --run NEW_DIRECTORY
   --owner-config PRIVATE_OWNER_JSON`. The harness starts its own model owner,
   submits two logical arithmetic tasks and launches the foreground window.
   Each task allows at most three completed-response attempts, so the whole
   arithmetic stage permits at most six requests. The original CSV, model,
   quality settings and independent integer checks remain unchanged.
   Activate the animation window normally, make one ordinary interaction, then
   let it close. After both accepted responses, the owner exits with a release
   receipt.
6. Run the same harness with `--case controlled`, a different new output
   directory, and additional arguments `--hermes-run PREPARED_REAL_RUN
   --ffmpeg EXISTING_FFMPEG --ffprobe EXISTING_FFPROBE`. The controller samples
   actual foreground activity, drains inference, parks and reloads its owner.
   It then admits a three-second NVENC encode, checks all 90 frames by probing
   and decoding the artifact, restores inference, and performs the installed
   Hermes process-restart test. Activate the first animation window and interact
   once just as in the uncontrolled condition. A second 45-second animation
   appears during the first Hermes generation; activate and interact with that
   window too. The harness requires the same agent dispatch to remain active at
   its visible readiness, then independently observes a durable resource wait
   before the safe checkpoint and restart. Keep the quiet window available
   after each animation closes. Do not run another model or change quality.
7. Compare the three foreground `result.json` files with
   `foreground/compare_runs.py`. Inspect independent tool, task, controller and
   cleanup receipts as well. A good frame result alone does not prove handoff;
   an accepted task alone does not prove responsiveness. Raw responses and
   transcripts remain private. Close the quiet window when finished.

The containing process has a finite deadline and owns its descendants through
a Windows job. It also retains and waits for each foreground/tool/agent child.
The restart test terminates only the exact worker whose durable checkpoint has
been verified, then starts a distinct worker from the same native session and
task. It verifies one report write before and after restart. It does not reboot
the operating system or install an automatic login service.

Orderly shutdown closes admission while retained native transitions finish.
Known closing does not itself imply uncertain completion; actual uncertainty
still prevents acceptance. The harness records its complete handoff ledger
after awaiting host close, then checks both controller and scheduler: no fault,
active request, pending request or uncertain completion may remain. A primary
operation failure remains the raised error if cleanup also fails, and the
separate cleanup error is retained in the private receipt.

Window activation and input are different observations. After selecting and
activating the exact owned test window, make the declared ordinary interaction
(for example, one Space key directed to that window), then check its recorded
session input age. Do not assume activation changed the last-input timer. A
quiet animation below the CPU threshold may correctly produce no handoff when
input is omitted. Keep such an attempt failed; do not inject a late substitute
event, change the thresholds, or combine it with a different successful run.

The agent uses [immediate admission](../../../docs/resource-waiting.md), while
the standalone background arithmetic attempts retain ordinary queueing.
The existing bounded feedback runner includes a rejected answer and trusted
validator feedback in the next actual request. Every attempt is retained.
Unknown transport, HTTP or response-envelope outcomes fail the workflow;
they are not ordinary correction attempts. Logical-task duration includes all
attempts and waits; its final request hash and token usage describe only the
accepted last attempt. A run accepted on first attempts does not demonstrate
real-model correction after rejection.
The supervisor binds both agent workers to the actual gateway instance and the
same 900-second task deadline. Waiting happens outside provider execution; a
known non-dispatch can be attempted again with identical bytes, while an unknown
outcome cannot. The successful model-request ledger and the non-dispatch ledger
are separate. The inherited SDK request timeout is preserved; the retained
process supervisor supplies the hard total qualification deadline.

For a reusable bounded controller without this qualification task, run
`native/windows_host.py --owner-config PRIVATE_OWNER_JSON --gateway-config
GATEWAY_JSON --run NEW_DIRECTORY --max-runtime-seconds 900`. The gateway config
uses the ordinary schema, loopback Strata at `http://127.0.0.1:18098/v1`, and a
different loopback listener port (18100 in the qualification). Applications can
then use its ordinary OpenAI-compatible routes. Tool admission is a trusted
Python host integration; the host exposes no process-execution HTTP endpoint.

## Checks without a model

```text
python -m unittest discover -s tests -p test_handoff.py -v
python -m unittest discover -s examples/validation/windows_handoff/foreground -v
python -m unittest discover -s examples/validation/windows_handoff/native -v
python -m unittest discover -s examples/validation/windows_handoff -p test_arithmetic_feedback.py -v
python -m unittest discover -s examples/validation/windows_handoff -p test_shutdown_receipts.py -v
python -m unittest discover -s provenance/windows-handoff/sanitizer -p "test_*.py" -v
```

These are policy, ownership and loopback/fixture tests. The separate Hermes
fixture command in its README uses the actual SDK and process termination with
synthetic provider responses. Installed hardware evidence and fixture evidence
remain distinct in the [evidence ledger](../../../docs/evidence.md).
