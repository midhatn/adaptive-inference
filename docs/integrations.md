# Engine and agent integrations

Adaptive Inference is an OpenAI-compatible gateway in front of an existing
model server. Choose an engine profile, retain the server's existing model and
quality configuration, and point the agent's compatible client at the gateway.
These are configuration routes and small client factories, not native engine
plugins or replacements for the applications' own model clients.

The interactive base URL is `http://127.0.0.1:18100/v1`. The background base URL
is `http://127.0.0.1:18100/background/v1`. Both enter **the same queue and backend**.
The latter forces the background class. A host can also attach
`X-Adaptive-Class: background` or a top-level
`adaptive_scheduling: {"class": "background"}` to a request. The gateway also
recognizes `strata_scheduling.class` for the existing Hermes/Strata client seam.
Class selection belongs to the calling host, not prompt text or a guessed user
identity. These hints do not grant authorization or operating-system priority.

The gateway resolves and validates scheduling metadata, then removes both
scheduling fields before forwarding. It does not send a second priority request
to the backend. It preserves model IDs, messages, images, tool definitions,
tool-call arguments, sampling, explicit token budgets and stream data. It does
not reduce a budget to make a request fit. A backend can reject an unsupported
field or a context overflow. Unknown vendor fields remain the backend's
responsibility; there is no general schema or quality translator.

## Engine profiles

Files in [`examples/engines`](../examples/engines) are complete gateway
configurations. Choose **one**, and set its backend URL to the actual server.
Ports below are example endpoints, not discovery or a claim that a server is
running. Keep the backend on a different port from the gateway.

| Profile | Example backend | Documented routes exposed through this gateway | Requirements and primary reference |
| --- | --- | --- | --- |
| `strata` | `http://127.0.0.1:8080/v1` | Chat, models | Existing Strata server/config. No text-completions or embeddings route is declared. [Official source](https://github.com/Niko1221/Strata/blob/main/serve/server.py). |
| `llamacpp` | `http://127.0.0.1:8080/v1` | Chat, text completions, embeddings, models | `llama-server`; chat template and embedding mode/model must match the request. [Server API](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md). |
| `vllm` | `http://127.0.0.1:8000/v1` | Chat, text completions, embeddings, models | Chat requires a template; embeddings require a suitable model/task. Server generation configuration may supply defaults. [Official API](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/). |
| `sglang` | `http://127.0.0.1:30000/v1` | Chat, text completions, embeddings, models | Use the model's chat template and configured tool/reasoning parser. Embedding support depends on the loaded model. [Completions](https://docs.sglang.io/docs/basic_usage/openai_api_completions), [embeddings](https://docs.sglang.io/docs/basic_usage/openai_api_embeddings). |
| `ollama` | `http://127.0.0.1:11434/v1` | Chat, text completions, embeddings, models | Use its OpenAI-compatible `/v1` interface, not `/api/chat`; retain the existing model tag and model context settings. [Official compatibility reference](https://docs.ollama.com/api/openai-compatibility). |
| `lmstudio` | `http://127.0.0.1:1234/v1` | Chat, text completions, embeddings, models | Start LM Studio's API server and select an existing model. Native `/api/v1/*` management routes are not proxied. [Compatibility endpoints](https://lmstudio.ai/docs/developer/openai-compat). |
| `mlx_lm` | `http://127.0.0.1:8080/v1` | Chat, text completions, models | Requires a supported Apple/MLX host and existing model. No embeddings support is claimed. [Official server source](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/server.py). |
| `tgi` | `http://127.0.0.1:3000/v1` | Chat, text completions, models | Messages API requires TGI 1.4.0 or later; this profile does not convert native `/generate` requests. [Messages API](https://huggingface.co/docs/text-generation-inference/en/messages_api), [route source](https://github.com/huggingface/text-generation-inference/blob/main/router/src/server.rs). |

Here, chat means `POST /v1/chat/completions`; text means
`POST /v1/completions`; embeddings means `POST /v1/embeddings`; models means
`GET /v1/models`. An endpoint in a profile describes the server family, not a
promise that every installed version or loaded model supports every request.
The gateway does not expose Responses, Anthropic Messages, model downloads,
model-management endpoints, or native tool-resource leases through this API.

For an already installed backend, launch using its normal command and existing
model/config. Typical entry points are `llama-server -m /path/to/existing.gguf`,
`vllm serve /path/to/existing-model`,
`python -m sglang.launch_server --model-path /path/to/existing-model`,
`ollama serve`, `lms server start`,
`python -m mlx_lm.server --model /path/to/existing-model`, and
`text-generation-launcher --model-id /path/to/existing-model`.
Set the host/port to match the chosen profile and preserve your previously
verified context, precision, memory and reasoning options. Strata uses its
existing server configuration. These examples do not install runtimes, download
models, rewrite server settings, or manage the backend's process lifetime.

If the backend needs authentication, set `backend.api_key_env` to the **name**
of an environment variable containing its key. Do not embed a production key in
the public examples. The sample agent key `local` is only a placeholder required
by some clients talking to this local listener; it is not backend credentials.

The adapter refuses known Strata controls on other profiles:
`reasoning_budget_tokens`, `experimental_speed_projection`, `pcie_frac`, and
`strata_checkpoint`, plus unknown `strata_*` controls. On the Strata profile
those values are preserved. It does not translate these into another engine's
similarly named reasoning/cache control. Standard `reasoning_effort`, tool
schemas and output limits remain untouched on all profiles; their actual
support must be checked against the deployed backend/model.

## Configure agents

First query the existing server's model listing through
`GET http://127.0.0.1:18100/v1/models`. Replace every
`YOUR_EXISTING_MODEL_ID` in an example with the exact served ID. A file containing
that marker is a template, not ready for a real request. Examples deliberately
do not invent context windows, output caps, tool or image capabilities. Merge
the route fields into the app's existing verified configuration and preserve
its quality settings. For Python factories, provide the actual model ID as an
argument and pass its verified generation settings in `generation_options`.
They construct existing upstream clients; no bespoke model protocol is introduced.
Generation options cannot override the selected base URL, model, credential, or
transport. If omitted, the upstream client's/server's defaults still apply;
the factory has not established a quality baseline for that model.

| Agent | Delivered setup | What selects background work | Primary reference |
| --- | --- | --- | --- |
| Hermes | [`hermes.yaml`](../examples/agents/hermes.yaml): main custom provider plus explicit auxiliary compression/title provider | Auxiliary slots use the background URL; delegated children are not automatically reclassified by this generic config | [Model configuration](https://hermes-agent.nousresearch.com/docs/user-guide/configuring-models) |
| OpenClaw | [`openclaw.json`](../examples/agents/openclaw.json): `models.providers`, `openai-completions`, and a default model | Host explicitly selects the separate `adaptive-background` provider for a worker | [Custom providers](https://docs.openclaw.ai/gateway/config-tools/custom-providers), [minimal custom model entries](https://docs.openclaw.ai/concepts/model-providers/custom-providers) |
| Aider | [`aider.yml`](../examples/agents/aider.yml), usable with `aider --config PATH` | Change that worker's API base to the background URL | [OpenAI-compatible APIs](https://aider.chat/docs/llms/openai-compat.html) |
| OpenHands | [`openhands.md`](../examples/agents/openhands.md): custom model and API base in the app settings | Separate worker configured with the background URL | [Local model guide](https://docs.openhands.dev/openhands/usage/llms/local-llms) |
| Continue | [`continue.yaml`](../examples/agents/continue.yaml): `provider: openai`, `apiBase`, Chat Completions mode | User/host chooses the background model entry | [Provider configuration](https://docs.continue.dev/customize/model-providers/top-level/openai), [config schema](https://docs.continue.dev/reference) |
| Cline | [`cline.md`](../examples/agents/cline.md): OpenAI Compatible settings | Dedicated background profile/instance | [Provider settings](https://docs.cline.bot/provider-config/openai-compatible) |
| Roo Code | [`roo-code.md`](../examples/agents/roo-code.md): OpenAI Compatible settings | Dedicated background profile/instance | [Provider settings and native tool requirement](https://roocodeinc.github.io/Roo-Code/providers/openai-compatible/) |
| LangGraph | [`langgraph_client.py`](../examples/agents/langgraph_client.py): one-node graph using `ChatOpenAI` | `build_graph(model_id, background=True)` | [ChatOpenAI](https://docs.langchain.com/oss/python/integrations/chat/openai), [graph API](https://docs.langchain.com/oss/python/langgraph/graph-api) |
| AutoGen | [`autogen_client.py`](../examples/agents/autogen_client.py): `OpenAIChatCompletionClient` factory | `build_client(model_id, verified_model_info, background=True)` | [Client API](https://microsoft.github.io/autogen/stable/reference/python/autogen_ext.models.openai.html) |
| CrewAI | [`crewai_client.py`](../examples/agents/crewai_client.py): existing `LLM` with `custom_openai=True` | `build_llm(model_id, background=True)` | [LLM configuration](https://docs.crewai.com/en/concepts/llms) |

These settings do not change agent tool permissions or classify individual user
messages by their content. A separate host-known worker or explicit auxiliary
slot is the practical opt-in boundary. A single agent pointed at `/v1` stays
normal unless its caller attaches scheduling metadata. A background path stays
background even if a caller tries to promote its class.

For Aider and OpenHands, `openai/` is the client provider selector; use the actual
model ID after that prefix. For other routes, retain the backend's exact ID.
AutoGen requires explicit capabilities for an unknown model: supply verified
`model_info`, including tool and structured-output support. Roo Code requires
native tool calling, so text-only success is insufficient. LangChain's generic
OpenAI client does not preserve all vendor-specific reasoning response fields;
use its appropriate provider client when those fields are essential. A gateway
that preserves the raw response cannot repair a client that drops a field.

If the app runs in Docker, WSL, another machine, or a sandbox, its loopback may
not reach the host listener. Configure the network boundary deliberately;
these examples do not silently bind the gateway to all interfaces.

## Evidence boundaries

The adapter contract tests cover immutable profiles, preserving full requests
including nested tools/images, removing only routing metadata, explicit
cross-engine control refusal without input mutation, absence of guessed caps,
and example configuration consistency. The Python examples are checked for
syntax and import-time inactivity. These are **protocol/configuration tests**;
they do not install or run the ten applications or eight model backends.

Earlier local project evidence includes actual Strata-native generations and
actual Hermes parent/child calls through the preceding direct Strata design.
That is evidence for those exact prior builds and tasks, not verification of
this new gateway with every integration. No other native engine or application
is labeled tested merely because its documentation says OpenAI-compatible.
Real application qualification still requires a request through the deployed
gateway, correct final response, streaming/tool behavior as applicable, and
clean cancellation/resource ownership. Queue ordering is not native GPU
preemption, and this gateway does not automatically unload arbitrary engines.

Official references were checked on 2026-10-24. API versions and client defaults
can change; the linked source/docs identify the configuration being reused.
