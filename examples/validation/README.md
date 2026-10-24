# Validation examples

## Process restart and task survival

No model, GPU or external service is needed:

```text
python examples/validation/restart_survival.py --output local/restart-proof-01
```

Use a new output directory. The example starts and terminates its own worker processes, preserves the original task and rejected feedback, resumes to produce a verified JSON artifact, and checks that an interrupted external-effect fixture is not replayed. It retains results/artifacts and verifies all owned workers exit. It does not restart the computer or establish physical power-loss survival. See [task survival](../../docs/task-survival.md) for the host integration contract.

## Optional real-backend acceptance

Start your own backend before this check. The script starts a temporary loopback
gateway, sends exactly eight serial arithmetic requests, checks the actual
exact integer answers and each class's three-sample timing-learning threshold, and closes its
gateway. It does not start, stop or configure the model server. Own and stop the
backend separately, and do not share it with another workload during the check.

```bash
python examples/validation/real_backend.py --config examples/engines/strata.json --model YOUR_ADVERTISED_MODEL --generation-json examples/validation/strata-generation.json --output result.json
```

Choose an engine profile and actual `/v1/models` identifier. For another engine,
supply a JSON file containing its supported generation settings. The included
Strata settings reproduce the declared quality envelope of the predecessor;
they are not a universal model recommendation. No settings are automatically
lowered and no failed generation is retried.

The total check is bounded to 600 seconds and individual client calls to 120
seconds. Existing backend ownership should have a separate finite lifetime.
This is a functional check of HTTP integration and learned timing engagement,
not a scheduler contention benchmark, task-suite evaluation or speed comparison.
Inspect and sanitize the output before publishing; it includes model identifiers,
generation settings, token usage and full responses for these fixed arithmetic
prompts. Failures are retained with their partial observations and gateway state.
