# Remaining engine submission status

Policy and source check: **24 October 2026, 01:11 UTC**. This is the canonical
project's status record, not an upstream submission or a statement of maintainer
acceptance. No human review, contributor agreement, or DCO signature is asserted.

| Engine | Available integration in this project | Upstream submission boundary |
|---|---|---|
| llama.cpp | `src/adaptive_inference/adapters.py`, `examples/engines/llamacpp.json`; standard OpenAI-compatible routes through the existing gateway | The policy says, “It is strictly prohibited to use AI to write your posts for you”. Human-authored public communication and the required actual manual review are outstanding. Features require prior issue discussion; fixes need a failing-before/passing-after regression. New contributors are limited to one open PR and trivial fixes are excluded. [Policy](https://github.com/ggml-org/llama.cpp/blob/edc353842c1be9b4ebc27460a1da4526a026d3a9/CONTRIBUTING.md#L9-L40), [agent guidance](https://github.com/ggml-org/llama.cpp/blob/edc353842c1be9b4ebc27460a1da4526a026d3a9/AGENTS.md#L48-L70). |
| MLX-LM | `src/adaptive_inference/adapters.py`, `examples/engines/mlx_lm.json`; chat, text completions and model listing; no embeddings declaration | The policy says, “It is strictly prohibited to use AI to write your posts for you”. Public communication needs a human author; AI assistance in code must be disclosed. Code changes need tests that fail on main, and performance changes need comparison benchmarks. No native MLX qualification is claimed on the current Windows host. [Policy](https://github.com/ml-explore/mlx-lm/blob/4cfc6478473b0668ede3eb0cc93f2a9181a15052/CONTRIBUTING.md#L6-L14), [test requirements](https://github.com/ml-explore/mlx-lm/blob/4cfc6478473b0668ede3eb0cc93f2a9181a15052/CONTRIBUTING.md#L60-L66). |
| vLLM | `src/adaptive_inference/adapters.py`, `examples/engines/vllm.json`; standard compatible routes; caller fields remain unchanged | The policy says, “Do not submit "pure agent" PRs.” A human submitter must review changed lines, validate behavior and run relevant tests. DCO agreement/sign-off and AI disclosure/commit attribution are required. None is fabricated or inferred from authorization to work. A useful concrete change remains to be demonstrated. [Policy and DCO](https://github.com/vllm-project/vllm/blob/debcf228431f0b04ee8f12cfc410b0fe3c34a4f7/docs/contributing/README.md#L183-L214). |

These profiles and `tests/test_adapters.py` are configuration/protocol support.
They do not establish native model execution, active GPU preemption, shutdown
ownership, full agent-task survival, or upstream acceptance for these engines.
Preserve the existing IQ3_S quality baseline for any proposed matched native
check; do not substitute a different model or quantization to claim equivalence.

## Concrete source seams

- **llama.cpp**, revision `edc353842c1be9b4ebc27460a1da4526a026d3a9`:
  `tools/server/README.md`, `tools/server/README-dev.md`,
  `tools/server/server-stream.h`, `tools/server/server-stream.cpp`, and
  `tools/server/tests/unit/test_stream.py`. Its existing opt-in resumable SSE
  uses `X-Conversation-Id`, a bounded replay buffer, reattachment and explicit
  cancellation. The current gateway does not forward that header or implement
  its additional routes. This is a future protocol adapter opportunity, not
  delivered durable agent/tool resume or reboot recovery. Complex external-API
  agent loops belong outside llama-server's stated scope.
  [Scope and resumable streaming](https://github.com/ggml-org/llama.cpp/blob/edc353842c1be9b4ebc27460a1da4526a026d3a9/tools/server/README-dev.md).
- **MLX-LM**, revision `4cfc6478473b0668ede3eb0cc93f2a9181a15052`:
  `mlx_lm/server.py` routes `/v1/chat/completions`, `/v1/completions` and
  `/v1/models`; `tests/test_server.py` is the existing regression surface.
  Native checks require a supported Apple/MLX environment and suitable existing
  assets; a fixture response cannot establish that support.
  [Server source](https://github.com/ml-explore/mlx-lm/blob/4cfc6478473b0668ede3eb0cc93f2a9181a15052/mlx_lm/server.py).
- **vLLM**, revision `debcf228431f0b04ee8f12cfc410b0fe3c34a4f7`:
  `vllm/entrypoints/openai/chat_completion/api_router.py`, `serving.py` and
  `protocol.py`; `tests/entrypoints/openai/chat_completion/test_chat.py` and
  `test_chat_completion.py`. Server-side `generation_config.json` can supply
  defaults, so future comparisons must record the actual deployed configuration
  and preserve explicit caller values. No new scheduler or speculative defect is
  proposed without a reproducible gap.
  [OpenAI server guide](https://github.com/vllm-project/vllm/blob/debcf228431f0b04ee8f12cfc410b0fe3c34a4f7/docs/serving/online_serving/openai_compatible_server.md).

The project can continue improving its own recipes, fixtures and adapters while
these submission conditions remain outstanding. No upstream post or PR for these
three engines was made during this review.

