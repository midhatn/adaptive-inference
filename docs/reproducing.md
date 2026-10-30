# Reproduce and use

## Software-only acceptance

Use a clean clone and Python3.11+. Create a virtual environment, install `requirements.lock`, then install this project with `python -m pip install --no-deps -e .`. The README gives Windows and POSIX activation commands. No existing installation is modified.

```text
python -m unittest discover -s tests -v
python -m unittest discover -s provenance -p "test_*.py" -v
adaptive-inference demo --output demo-result.json
python -m build
python provenance/check_distribution.py
```

The demo starts its own loopback simulated backend and gateway on temporary ports, exercises real HTTP, and closes both. It needs no model/GPU/account. The JSON result labels simulation explicitly. Tests cover observable contracts and failure cases; they do not claim native engine performance.

## Expected identity for installed checks

After building from the current checkout, the existing distribution check can
also write the expected package identity used by the installed SDK checks:

```powershell
python -m build
python provenance/check_distribution.py --output ../package-check-01
```

Choose a new output directory. The checker verifies source-archive contents,
the complete wheel module set, package name/version, every wheel RECORD hash
and size, and the existing license files. On success it writes `result.json`
and `installed-identity.json`. The identity comes from the verified wheel, so
it is independent of the installation being tested. A failed check writes a
failed result and does not emit an identity; rerunning into an existing output
directory is refused.

Install that exact wheel using the normal installation instructions. With the
full worker interpreter and [installed desktop profile](installed-desktop.md)
already configured, the existing SDK check consumes the generated identity:

```powershell
& $WorkerPython -I -B ./examples/validation/hermes_pause_dispatch/check_sdk.py --mode installed --profile $Profile --installed-identity ../package-check-01/installed-identity.json --output ../sdk-check-01
```

`$WorkerPython` and `$Profile` refer to the operator's actual interpreter and
profile. This checks the installed SDK dispatch boundary; it does not run the
model or prove a full task handover. The package check also does not prove that
tests ran before the build or that the checkout stayed unchanged during it.
The remaining host/worker, shared-clock and native-resource qualification inputs
are still separate requirements.

This extends the existing archive checker with the release verifier's module
and RECORD comparisons. It follows PyPA's
[wheel format](https://packaging.python.org/en/latest/specifications/binary-distribution-format/),
[core metadata](https://packaging.python.org/en/latest/specifications/core-metadata/)
and [project-name normalization](https://packaging.python.org/en/latest/specifications/name-normalization/).
It supports this repository's known pure-Python wheel layout and does not add
an installer or attempt to validate every possible third-party wheel layout.

## Explicit continuation qualification

The [standalone workflow sources](../examples/validation/explicit_continuation/README.md)
provide the fresh-trial entrypoints, explicit local bindings, real-window steps
and terminal audit. Their public helper-path adaptation has source/fixture
validation, distinct from the original installed trial.

The [Continue saved task guide](explicit-continuation.md#reproduction-and-evidence)
uses the existing software suites above and the full-interpreter
[installed desktop profile](installed-desktop.md). Both host and worker need the
same reviewed regular wheel, pinned SDK and fresh same-boot execution-clock
checks. Model qualification uses IQ3_S and the unchanged quality contract.

The [accepted continuation record and replay instructions](../provenance/explicit-continuation/acceptance/README.md)
bind one actual installed case. Custodian replay needs the retained private
terminal inputs; public synthetic checks do not repeat the model/GUI trial.
Do not substitute the historical expiry replay for this result. The exact tested
qualification source/wheel are distinguished from later release documentation.

## Real engine

1. Install and start the desired backend according to its official documentation in [integrations.md](integrations.md).
2. Copy that backend's example configuration to an ignored local directory. Set its actual API base and loaded model in your client. Keep backend credentials in an environment variable referenced by `backend.api_key_env`.
3. Run `adaptive-inference doctor --config <your-config.json>` to check the actual model-list endpoint without generating text.
4. Run `adaptive-inference serve --config <your-config.json>` and keep this process running. Stop with Ctrl+C; the gateway does not own or terminate your model server.
5. Set the client base URL to `http://127.0.0.1:18100/v1` or the shared `/background/v1` route. A client that requires an API-key value may use a placeholder only when your gateway is loopback-only and has no configured key.

Two routes do not create two independent queues. Native servers can still receive traffic that bypasses this gateway; observed scheduling claims apply only to requests routed through it.

## Configuration controls

`scheduler` controls the pending bound, queue/capacity timeout and bounded class/cost offsets. `resources.min_available_ram_gib` enables a read-only host admission floor; default0 disables it. `limits` controls request/response size and upstream total/read timeouts. Defaults are documented by `Config` and are validated before serving.

For sustained recovery after memory pressure, enable `resources.adaptive_headroom` with a positive floor. The [portable policy guide](portable-policies.md) includes a complete example, all defaults and `adaptive-inference budget` usage. Both mechanisms are optional and keep the caller's generation settings unchanged.

`listen.api_key_env` enables gateway authentication and is required for a non-loopback listen address. A reverse proxy is needed for HTTPS deployment. This initial release is primarily a local deployment; it is not a multi-tenant service.

Changing the backend/model/runtime requires restarting the gateway to avoid learning from stale runtime identity. An ambiguous upstream failure also requires checking the backend and restarting. No automatic retry or model reload is performed.

## Native predecessor reproduction

See [legacy-reproduction.md](legacy-reproduction.md) for pinned Strata and Hermes source reconstruction from locally preserved inputs. It verifies source and patch bytes and the resulting files in a new checkout. Native compilation, model acquisition and hardware-dependent testing are separate steps. Never treat a reproduced source tree as a reproduced model benchmark. The [preservation contract](source-of-truth.md) explains source archives, external prerequisites and preparing Python dependencies for offline installation.

## Reporting results

Record the project commit, dependency versions, backend commit/version, model identity, platform, quality settings, workload, exact command and result. State whether tests used a fixture, installed client, actual model or native resource operation. Avoid publishing prompts, credentials, absolute personal paths or private transcripts. Keep failures alongside successes and link the canonical issue or commit here. Link an upstream PR only when that result concerns its implementation.
