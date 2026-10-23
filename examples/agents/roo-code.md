# Roo Code

In Settings select **OpenAI Compatible**. Set Base URL to
`http://127.0.0.1:18100/v1`, API key to `local`, and Model to the exact existing
backend model ID. Preserve its verified context, output limit and capabilities.
Use `http://127.0.0.1:18100/background/v1` only for an explicitly background
worker/profile. Both URL paths share the same scheduler.

Roo Code's documented current provider requires native OpenAI-compatible tool
calling. A text-only chat pass does not establish Roo Code compatibility. Verify
the selected backend's chat template/tool parser and a real tool round trip.
The gateway preserves tool definitions and streamed tool arguments; it does not
synthesize tool support or change Roo's approval policy.

Official reference: https://roocodeinc.github.io/Roo-Code/providers/openai-compatible/

Status: documented settings recipe; no Roo Code application run is claimed.
