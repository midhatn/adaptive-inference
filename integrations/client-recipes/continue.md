# Continue through its existing OpenAI provider

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

For a dedicated background-worker configuration, use:

```yaml
name: Local background worker
version: 0.0.1
schema: v1
models:
  - name: Local IQ3_S background
    provider: openai
    model: qwen3.8-flash-next-iq3_s-adaptive-media-beta
    apiBase: http://127.0.0.1:18100/background/v1
    apiKey: ${{ secrets.ADAPTIVE_GATEWAY_KEY }}
    roles: [chat, edit, apply]
    useResponsesApi: false
    useLegacyCompletionsEndpoint: false
    defaultCompletionOptions:
      contextLength: 65536
      maxTokens: 10923
    requestOptions:
      extraBodyProperties:
        reasoning_effort: high
        reasoning_budget_tokens: 8192
        experimental_speed_projection: false
```

Use `/v1` in the interactive configuration. Select the appropriate configuration
explicitly; this recipe does not automatically label every background operation
inside the extension. The configured context length describes the existing
backend limit; it does not reserve memory or change native context allocation.

The current model schema and OpenAIApi JSON/SSE paths were exercised with a
fixture key and preserved nested paths, the exact body extensions, output limit
and tool schema. Secret resolution, VS Code selection and a full agent task were
not exercised. The `reasoningBudgetTokens` generic completion option is not used
as a substitute for Strata's exact `reasoning_budget_tokens` wire field.
