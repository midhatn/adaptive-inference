# ollama external admission recipe

### Share admission with background workers

When interactive clients share a local Ollama server with background workers, an external queue can decide which pending request enters the server next. This example intentionally admits one request at a time; it does not change Ollama's native scheduling or model settings.

[Adaptive Inference v0.2.0](https://github.com/midhatn/adaptive-inference/releases/tag/v0.2.0)
is one optional external gateway. Install that release in a separate Python 3.11+
environment using its release instructions. Keep your existing model server running
with its verified model, context, tool/reasoning parser and generation settings.
The gateway is an HTTP client; it needs no CUDA, ROCm or model installation of its
own and does not change your backend's hardware or parallelism configuration.

Save the following as `adaptive.json`, adjusting the backend address if needed:

```json adaptive.json
{
  "listen": {
    "host": "127.0.0.1",
    "port": 18100
  },
  "backend": {
    "kind": "ollama",
    "base_url": "http://127.0.0.1:11434/v1"
  },
  "scheduler": {
    "max_pending": 16,
    "queue_timeout_s": 300,
    "normal_boost_s": 10,
    "max_cost_delay_s": 30
  }
}
```

Run `adaptive-inference doctor --config adaptive.json` to check model discovery,
then `adaptive-inference serve --config adaptive.json`. Discovery is not an inference
test. Both client routes below share this one process and queue. For an authenticated
backend, add `backend.api_key_env` with the name of its credential environment
variable. A gateway credential, when configured with `listen.api_key_env`, is
separate from the backend credential; set it in the client's `ADAPTIVE_API_KEY`.

Save this client as `admitted_chat.py`. Install `openai` in its environment.
`request.json` must contain your existing working Chat Completions SDK arguments,
including the exact served `model`, `messages`, output budget, sampling settings,
tools and any model-specific `extra_body`. The example does not choose a model,
download weights, set a smaller output cap or disable reasoning.

```python admitted_chat.py
import argparse
import json
import os
from pathlib import Path

import httpx
from openai import OpenAI


def run_request(request_file, background=False):
    # request_file contains the same SDK keyword arguments as your working client.
    request = json.loads(Path(request_file).read_text(encoding="utf-8"))
    base = os.environ.get("ADAPTIVE_BASE_URL", "http://127.0.0.1:18100").rstrip("/")
    base += "/background/v1" if background else "/v1"
    with OpenAI(
        base_url=base,
        api_key=os.environ.get("ADAPTIVE_API_KEY", "local"),
        max_retries=0,
        timeout=httpx.Timeout(1250.0, connect=5.0),
        http_client=httpx.Client(trust_env=False),
    ) as client:
        response = client.chat.completions.create(**request)
        if request.get("stream", False):
            with response:
                for chunk in response:
                    print(chunk.model_dump_json())
        else:
            print(response.model_dump_json())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("request_file")
    parser.add_argument("--background", action="store_true")
    args = parser.parse_args()
    run_request(args.request_file, args.background)
```

Set `ADAPTIVE_BASE_URL` to the gateway listener root (without `/v1`) when using
a different address. Run `python admitted_chat.py request.json` for interactive work, or pass
`--background` in an explicitly designated worker. The host selects that class;
no prompt text is inspected. The gateway removes its scheduling metadata before
forwarding, preserves request arguments and stream bytes, and adds no native
priority field. `/v1/responses` and native management APIs are not exposed by this
gateway.

Only pending requests can be reordered or canceled before dispatch. An active
request is not preempted: on client disconnect the gateway drains it to completion,
and an ambiguous upstream timeout stops further dispatch until an operator checks
the backend and restarts the gateway. Automatic SDK retries are disabled here to
avoid replay. The 1,250-second client read timeout exceeds the example's 300-second
queue limit plus the gateway's 900-second execution limit; tune those explicit
limits together for your workload. No speedup, GPU memory reservation or native
cancellation guarantee follows from using this queue. See the gateway's
[protocol and evidence limits](https://github.com/midhatn/adaptive-inference/blob/v0.2.0/docs/integrations.md).
