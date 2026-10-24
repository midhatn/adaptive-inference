**Shared local inference for background workers:**

When interactive and autonomous agents share one local model server, an optional external admission gateway can distinguish their waiting requests. [Adaptive Inference v0.2.0](https://github.com/midhatn/adaptive-inference/releases/tag/v0.2.0) exposes `/v1` and `/background/v1` through one queue. Configure and start the gateway separately using its release instructions; keep the existing model server and quality settings.

Set `ADAPTIVE_GATEWAY_ROOT` to the gateway listener root, for example `http://127.0.0.1:18100`, without `/v1`. Supply its key through `ADAPTIVE_GATEWAY_KEY` if authentication is enabled. `llm-settings.json` contains your existing `model` and verified generation arguments, including explicit output/reasoning allowances and supported `extra_body`; it does not contain routing or credentials.

```python Code
import json
import os
from pathlib import Path

from crewai import LLM

# Keep the existing served model and its verified generation settings.
settings = json.loads(Path("llm-settings.json").read_text(encoding="utf-8"))
reserved = {"base_url", "api_key", "custom_openai", "max_retries"}
if reserved.intersection(settings):
    raise ValueError("Keep gateway routing separate from model settings")
gateway = os.environ["ADAPTIVE_GATEWAY_ROOT"].rstrip("/")
key = os.environ.get("ADAPTIVE_GATEWAY_KEY", "local")

interactive_llm = LLM(
    **settings, custom_openai=True, base_url=gateway + "/v1",
    api_key=key, max_retries=0,
)
background_llm = LLM(
    **settings, custom_openai=True, base_url=gateway + "/background/v1",
    api_key=key, max_retries=0,
)
```

Pass `interactive_llm` or `background_llm` as an Agent's `llm` according to the role chosen by your application. This is explicit host routing; it does not infer priority from prompts or classify every child automatically. The external queue admits one upstream request at a time, which can reduce native batching throughput. It cannot preempt an active generation, unload a model or reserve GPU memory. Disable automatic retries for ambiguous completions and set the client timeout to cover the configured queue and execution limits. Use Chat Completions; this gateway does not expose Responses or native management routes.

Retain the backend's supported fields rather than translating controls between engines. CrewAI's OpenAI client converts function schemas to strict mode; ensure that behavior fits your tools. Configuration/HTTP fixture checks do not establish native model quality or resource handoff. [Reproduction and compatibility limits](https://github.com/midhatn/adaptive-inference/blob/v0.2.0/docs/integrations.md).
