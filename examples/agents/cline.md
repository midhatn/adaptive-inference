# Cline

In Settings select **OpenAI Compatible**, then set Base URL to
`http://127.0.0.1:18100/v1`, API key to `local`, and Model ID to the exact ID
already served by the backend. Keep its verified context window, output limit,
and model capabilities. Choose Chat Completions if your version exposes an API
mode selector. This gateway does not translate Responses or Anthropic Messages.

A dedicated unattended Cline instance can instead use
`http://127.0.0.1:18100/background/v1`. That path makes all its requests
background requests in the same gateway queue; it does not infer intent from
individual prompts or change Cline's own tool permissions.

Official reference: https://docs.cline.bot/provider-config/openai-compatible

Status: documented settings recipe, not an extension-specific plugin or an
app-verified integration. Tool capability still needs the actual model/server.
