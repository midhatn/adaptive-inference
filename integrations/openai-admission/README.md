# OpenAI client admission recipes

These standalone sections contain the executable examples proposed for SGLang
and Ollama. They use the released Adaptive Inference gateway and retain the
caller's existing model request. The surrounding upstream documentation and
private development checkouts are not required.

Install this repository and the fixture dependencies in a fresh Python 3.11+
environment, then run from the repository root:

```sh
python -m pip install .
python -m pip install -r integrations/openai-admission/requirements.txt
python -m unittest discover -s integrations/openai-admission -p test_recipes.py -v
```

The six tests extract and execute the actual Python and JSON blocks in
`sglang.md` and `ollama.md`. A deterministic loopback HTTP fixture stands in for
the model engine. The tests cover normal/background admission, preserved
generation fields, tools/images, SGLang reasoning-template controls, SSE,
nested backend paths, foreign-control rejection and no retry on HTTP 503.
They start neither SGLang nor Ollama, acquire no model weights, and demonstrate
no native inference, batching benefit or GPU memory control.

`evidence.json` records the tested release, upstream revisions, dependency
versions, documentation checks and content hashes. The corresponding upstream
diffs are in `upstream/patches/`. The examples are optional external admission
recipes; existing native batching and scheduling remain the appropriate path
when concurrent native execution is required.
