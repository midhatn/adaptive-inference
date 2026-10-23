# Reproduce and use

## Software-only acceptance

Use a clean clone and Python3.11+. Create a virtual environment, install `requirements.lock`, then install this project with `python -m pip install --no-deps -e .`. The README gives Windows and POSIX activation commands. No existing installation is modified.

```text
python -m unittest discover -s tests -v
adaptive-inference demo --output demo-result.json
python -m build
```

The demo starts its own loopback simulated backend and gateway on temporary ports, exercises real HTTP, and closes both. It needs no model/GPU/account. The JSON result labels simulation explicitly. Tests cover observable contracts and failure cases; they do not claim native engine performance.

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

See [legacy-reproduction.md](legacy-reproduction.md) for pinned public Strata and Hermes source reconstruction. It verifies patch bytes and expected changed files in a new checkout. Native compilation, model acquisition and hardware-dependent testing are separate steps. Never treat a reproduced source tree as a reproduced model benchmark.

## Reporting results

Record the project commit, dependency versions, backend commit/version, model identity, platform, quality settings, workload, exact command and result. State whether tests used a fixture, installed client, actual model or native resource operation. Avoid publishing prompts, credentials, absolute personal paths or private transcripts. Keep failures alongside successes and link the responsible upstream PR.
