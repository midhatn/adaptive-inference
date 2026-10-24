# Aider through the existing OpenAI-compatible client

These recipes target the existing adaptive-inference 0.2.0 Chat Completions
gateway. Keep your backend process/model in its established configuration; the
gateway queues requests and does not preempt active GPU generation. Normal is
`http://127.0.0.1:18100/v1`; background is
`http://127.0.0.1:18100/background/v1`. Use the gateway credential, distinct from
its backend credential. A background route is an explicit client choice, not
proof of user-versus-agent identity. Do not point embedding, rerank, autocomplete
or Responses traffic at endpoints the gateway does not implement.

The examples use the previously qualified IQ3_S model identifier. Substitute
only the exact model identifier your established backend exposes, and validate
its own supported parameters. No actual model was run for these client recipes.
The published transport receipts are fixture evidence, not application-task or
model-quality acceptance.

Set `OPENAI_API_KEY` in this process through your usual secret mechanism. Avoid
persistently changing a shared environment merely to start a background worker.
For a dedicated worker session:

```sh
aider --model openai/qwen3.8-flash-next-iq3_s-adaptive-media-beta --openai-api-base http://127.0.0.1:18100/background/v1 --model-settings-file ./strata.model.settings.yml
```

Use `/v1` for the interactive session. Aider's `openai/` routing prefix is not
sent as part of the backend model name. Keep weak/editor model choices explicit
if those modes are used; this test covers the main model request only.

`strata.model.settings.yml`:

```yaml
- name: openai/qwen3.8-flash-next-iq3_s-adaptive-media-beta
  extra_params:
    max_tokens: 10923
    num_retries: 0
    extra_body:
      reasoning_effort: high
      reasoning_budget_tokens: 8192
      experimental_speed_projection: false
```

These extension fields are for the Strata backend profile, not a promise about
every OpenAI-compatible server. The actual Aider configuration loader and
Model→LiteLLM→OpenAI path preserved all these fields and a tool schema over both
JSON and SSE fixture requests. `num_retries: 0` controls LiteLLM retries for this
call; it does not disable every Aider agent-level retry or task continuation.
