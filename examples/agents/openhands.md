# OpenHands

This is an application settings recipe, not an importable OpenHands configuration.

In the model settings, enable the custom/advanced OpenAI-compatible route. Set
the model to `openai/YOUR_EXISTING_MODEL_ID`, Base URL to
`http://127.0.0.1:18100/v1`, and API key to `local` for this loopback gateway.
Keep the existing model's verified context and output settings. Use
`http://127.0.0.1:18100/background/v1` for a separate unattended worker.

Replace the model marker with the exact existing backend ID. The `openai/`
prefix is OpenHands/LiteLLM's provider selector, not part of the upstream model
ID. If OpenHands is containerized, its `127.0.0.1` refers to the container.
Configure a reachable host route explicitly and review gateway bind/auth settings;
the shipped loopback listener is intentionally not exposed to containers or LAN.

Official reference: https://docs.openhands.dev/openhands/usage/llms/local-llms

Status: documented route; this repository's protocol fixtures do not launch the
OpenHands app or prove task completion, model capability, or native tool execution.
