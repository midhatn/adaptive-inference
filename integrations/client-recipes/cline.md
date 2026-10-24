# Cline: existing route support, explicit quality-policy limit

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

In a dedicated background Cline instance, choose **OpenAI Compatible**, set
**Base URL** to `http://127.0.0.1:18100/background/v1`, enter the gateway credential
and select `qwen3.8-flash-next-iq3_s-adaptive-media-beta`. Keep the established
context/output settings and high reasoning effort. Use `/v1` for the interactive
instance. Do not create a new branded provider to accomplish this routing.

The current SDK gateway successfully sent both prefixed routes, the model name,
`max_tokens: 10923`, high reasoning effort and tool schema, then completed SSE.
This was an SDK transport check, not a rendered UI or task test.

**Do not treat this as full Strata request-policy parity.** Even when the SDK
request explicitly supplied `reasoning.budgetTokens: 8192`, the generic
OpenAI-compatible wire omitted `reasoning_budget_tokens`. Strata's explicit
projection control also has no tested configuration route. Do not rely on the
high-effort label to imply either property, and do not switch to a smaller
budget/model to hide the gap. Full policy qualification needs an approved
explicit request-option path or separately verified server-side policy.

A focused upstream feature proposal is prepared. Cline requires approval before
feature implementation; the independent API-base documentation clarification is
within its documentation contribution scope.
