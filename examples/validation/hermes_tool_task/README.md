# Reproduce the bounded Hermes file task

This Windows-only test uses the real Hermes agent, native file tools, a host-created production child, and the optional routing plugin. It never starts or stops a gateway or model service. It uses a fresh task directory and Hermes home; it does not modify an existing user profile.

The parent reads a four-row synthetic CSV, computes integer totals and writes `report.json`. The production child independently reads the input and report, verifies them, and writes `verification.json`. Exact file contents, successful native read/write outcomes, natural stops, actual serialized requests, and gateway history are checked. The host chooses to create the child; this is not evidence of autonomous delegation, contention performance, a resource lease, restart recovery, or general task correctness.

## Requirements

- Windows, Git, and an existing Python environment containing the dependencies of Hermes commit `14e1e43a23761b369641208e204365cd6cb9399d`. Python 3.14.7 was used in the measured run. This recipe installs nothing.
- A clean checkout of that exact Hermes commit. The checked-in source preservation mechanism can restore it offline; ordinary package dependencies remain separate requirements.
- The canonical `plugins/hermes` directory from commit `d6f4e201ba28602189872746922e527c58ed0cbd`. Both executable plugin code and its manifest are hash checked before preparing the task.
- For a real run, an independently owned, fresh, idle Adaptive Inference gateway backed by the existing IQ3_S Strata model. The permitted model ID is `qwen3.8-flash-next-iq3_s-adaptive-media-beta`; no substitute model is accepted. The model ID check is not a weight-identity proof: the service owner must retain native/model/config attestation separately.

Both parent and child must retain context 65,536, configured compression threshold 0.8, native threshold 46,421, output reserve/cap 10,923, high reasoning with 8,192 reasoning tokens, projection disabled and PCIe fraction 0.37. The test does not lower quality to fit. The endpoint must be an explicit `http://127.0.0.1:PORT/v1` URL. Caller authentication is the local fixture value; this is not a remote or authenticated gateway recipe.

## Prepare and run

Use local paths appropriate to your system. Run `prepare` once for each **new** output directory:

```powershell
& $HermesPython -I -B examples/validation/hermes_tool_task/run_task.py prepare `
  --run $NewRunDirectory --hermes-source $HermesSource --python $HermesPython `
  --plugin plugins/hermes --gateway-url http://127.0.0.1:18100/v1
```

First exercise the same SDK/tool path without network or a model:

```powershell
& $HermesPython -I -B examples/validation/hermes_tool_task/run_task.py run --run $NewRunDirectory --fixture
```

The fixture supplies six synthetic completions through the real SDK, including five actual native file-tool operations. Passing it establishes wiring and guard behavior; it does not establish model quality. A `RUN-CLAIM` makes each directory single-use. Prepare a different directory before a real run.

For a real run, the operator first starts and identifies the owned backend and a fresh gateway. It must have empty history, no pending/active work and no uncertain backend completion. Keep all unrelated callers off that gateway. Retain the backend identity, unchanged IQ3_S quality and native configuration before running the same command **without** `--fixture`.

After either command, require `result.json.passed`, zero exit without timeout in `outer-result.json`, and `owned_children_empty`. Inspect all three `work/` files and the recorded tool outcomes. For real runs, gateway instance, ordered request IDs and normal/background classes must match the six observed requests (the bounds permit up to eight per phase/sixteen total). The operator then drains/closes the gateway and stops the backend through its owner, retaining separate cleanup evidence. Agent success cannot prove service shutdown. Never call the same model while holding its resource lease.

## Bounds, privacy and evidence

The supervising process joins a Windows kill-on-close job before starting the environment interpreter, which also contains redirectors and descendants. It has a 900-second watchdog, no duplicate serialized POST retries, and checks its owned job after ordinary completion. Timeout cleanup occurs when the supervisor exits; a timeout receipt does not claim pre-exit cleanup or backend completion. The backend may still be completing work and needs independent owner cleanup.

The fixture audit plugin uses public pre/post tool hooks to allow only the declared file reads and output writes. It is a test guard, not a general sandbox. The routing plugin alone supplies background classification. Networking is restricted to the declared gateway, apart from the standard library's internal Windows socketpair.

The runner's structured wire records contain hashes and response metadata, not raw assistant text or reasoning. Parent/child results retain only completion flags. Nevertheless, the run directory contains local paths, native tool receipts, application logs and a fresh Hermes database: **do not publish it wholesale**. Publish only an explicitly reviewed, allowlisted receipt and synthetic artifacts, following `provenance/hermes-iq3-s/result.json`.

That existing receipt records the original real-model run. This parameterized runner is a later refactor of the same test and receives fixture qualification separately; it has not been rerun against a model. Its process helper is original project code under Apache-2.0 and uses the documented Windows Job Object API. No external process-control implementation was copied.

Run the narrow CPU boundary checks with the existing environment:

```powershell
& $HermesPython -I -B examples/validation/hermes_tool_task/test_boundary.py
```
