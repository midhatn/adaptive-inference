# Existing client configuration and transport checks

These checks use each client's existing OpenAI-compatible path. They exercise actual
HTTP to a loopback fixture; no real model, editor UI, full coding task, or native
engine is exercised. They do not themselves run the adaptive-inference gateway.
The source-level checks bundle unchanged client sources and keep installed
dependencies external. This is not a full upstream production build. Original
source attribution and licenses are included; see [source preservation](sources/README.md).

## Recorded sources

| Client | Source revision | Exercised entry point |
|---|---|---|
| Aider | `5dc9490bb35f9729ef2c95d00a19ccd30c26339c` | `Model`, settings/metadata registration, `send_completion`, LiteLLM/OpenAI transport |
| Continue | `5522c6f44ca0ac3528b37244818fbfa39b5af470` | current `OpenAIApi` and model configuration schema |
| Cline | `c7db4bfbd2643425e3c185367cb8c8b4bc468c4f` | current `createGateway` and generic OpenAI-compatible provider |

The separate published-package check uses `@continuedev/openai-adapters@1.32.0`
and `@cline/llms@0.0.95`. Same package version does **not** establish source
identity: the current-source result is recorded separately. Dependency versions
are in the lockfiles. In particular, Continue's Zod 3 schema is bundled with its
own declared dependency rather than Cline's Zod 4 dependency.

## Reproduce

All required upstream adapter source inputs and original licenses are preserved
in `sources/`, with exact revision/blob/SHA-256 metadata in `source-manifest.json`.
No Git clone, Git executable, upstream checkout, or live GitHub access is required.
Python 3.11 and Node 24.14.0 were used. Bun 1.3.14 installed the isolated test dependencies;
this does not qualify Cline's prescribed Bun 1.4.2 full-monorepo build.

```sh
python -m venv .venv
# Use .venv/Scripts/python.exe on Windows.
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python verify-sources.py
.venv/bin/python check-aider.py
cd js
bun install --frozen-lockfile --ignore-scripts
node build-current.mjs
node check-clients.mjs --current-source
node check-clients.mjs
```

The tests use dummy keys and bind ephemeral loopback ports. Aider additionally
refuses external socket connections; Windows asyncio loopback IPC is allowed.
No real credentials should be supplied. `source-pins.json` records the inputs
used for current-source bundling. Generated bundles are not distributed here.

## Results and limit

All clients preserve `/v1` and `/background/v1` when appending
`/chat/completions`, preserve the selected IQ3_S model name, 10923 output cap,
high reasoning effort and the tool input schema. Aider and Continue additionally
carry `reasoning_budget_tokens: 8192` and `experimental_speed_projection: false`
through their explicit server-specific request settings.

The Cline generic OpenAI-compatible path does not serialize the explicitly
requested `reasoning.budgetTokens: 8192` into `reasoning_budget_tokens`.
It also has no tested route for Strata's projection field. Its successful
stream is route/standard-option evidence, **not** full native quality-policy
parity. No model quality or tool execution result is claimed.

The initial Aider harness overrestricted Windows asyncio socketpair IPC;
the corrected guard permits loopback and still denies external connections.
The initial current-source schema check omitted the mandatory model `name`;
the corrected fixture includes it. These were harness corrections, not client
code fixes. No client runtime source was changed.
