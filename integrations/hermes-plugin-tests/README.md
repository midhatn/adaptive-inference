# Explicit Hermes SDK contract checks

Use an existing Hermes environment with pytest, httpx and its normal runtime dependencies. This runner does not install dependencies or models. Pass the actual SDK source and plugin directories explicitly:

```text
python run_contracts.py --source /path/to/hermes --plugin /path/to/adaptive-inference/plugins/hermes --output /new/private/result-directory
python validate_plugin.py --source /path/to/hermes --plugin /path/to/adaptive-inference/plugins/hermes --out /new/private/admission.json
```

`run_contracts.py` creates a new private Hermes home, runs bounded CPU tests and denies socket connections in the tests. Child agent construction and HTTP responses are fixtures; plugin loading, middleware, SDK serialization and host lifecycle call sites are real. `validate_plugin.py` invokes the official admission function and does not synchronize or install dependencies. For catalog submission, Hermes's own CI additionally runs `hermes plugins validate ... --install-deps`.

For the archived SDK, the canonical source bundle in `integrations/hermes/source` retains commit `2587d8231fc7e0f3e846acafa46eb5b67cdc70c8`. The ordinary offline restoration entry point `python integrations/hermes/setup.py --output /new/hermes` reconstructs that source plus its declared integration overlay. The plugin's contracts were independently exercised on the original pinned source. No additional SDK snapshot is needed. Its optional cron identity API is absent, so that one test is explicitly skipped; the missing-capability behavior is tested.

Current SDK source is pinned in the plugin SOURCE_LOCK and preserved in the separate [current-source supplement](../hermes/current-source/README.md). It reuses the existing baseline bundle and adds the exact target's changed source objects; offline restoration needs no upstream fetch. Dependencies remain separately installed. These plugin contract checks use fixtures; the [real IQ3_S parent/child task](../../provenance/hermes-iq3-s/README.md) has its own acceptance receipt.
