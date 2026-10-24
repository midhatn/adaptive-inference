# Installed Python client conformance

This checks the shipped LangGraph, CrewAI and retained AutoGen factories using
their actual installed SDKs and a loopback HTTP fixture. It does not run a model,
the adaptive gateway, an agent task or a native backend. The IQ3_S model ID and
quality settings are request data only in this test.

The recorded environment is Windows, Python 3.11.9, with LangGraph 1.2.16,
langchain-openai 1.7.2, CrewAI 1.15.29, AutoGen 0.7.5 and OpenAI Python 2.54.0.
The complete installed dependency list is in `requirements-windows.lock`; it
is a version lock for this Windows qualification, not a cross-platform lock or
an archive of third-party wheels. Dependencies remain under their own licenses.

From the repository root, using a separate Python 3.11 virtual environment:

```text
python -m pip install -r provenance/python-clients/requirements-windows.lock
python -m pip install --no-deps -e .
python provenance/python-clients/check_clients.py --output client-result-new.json
```

Choose a new output filename. The script refuses to overwrite a previous
receipt. Without `--output` it prints the receipt. It tests fifteen actual
client requests: normal/background text, normal/background SSE, and a
background request carrying an explicit strict function schema for each SDK.
It also refuses six nested model/authorization overrides before any HTTP
dispatch. Those negative cases are separate from the fifteen successful requests.
It checks the nested API base path, separate gateway credential, model,
10,923-token output allowance, high reasoning, 8,192 reasoning-token request,
disabled speed projection, 0.37 PCIe fraction and sampling value. The tool is
serialized and never executed. Non-loopback socket connections are refused;
the accepted run attempted none. This is a process-level test guard, not an
operating-system sandbox.

Two client behaviors matter for integration:

- LangChain emits `max_completion_tokens` for the supplied `max_tokens` while
  retaining the same numerical allowance. The recorded Strata source accepts
  that alias. Its generic OpenAI client does not preserve all vendor reasoning
  response fields; use a suitable provider client when those fields are needed.
- CrewAI converts function schemas to strict OpenAI schemas, including
  `additionalProperties: false`. This suite supplies an already-strict schema.
  Arbitrary caller schemas are not claimed byte-identical through CrewAI.

The first expanded fixture used nonstandard usage-bearing content chunks and
an unconstrained tool schema. CrewAI returned no content for those chunks and
normalized the schema, so three assertions failed. The accepted fixture now
uses ordinary SSE content chunks with null usage and a separate usage-only
chunk, and the test states its strict-schema boundary. No gateway or client
code was changed to conceal those client behaviors. The earlier six text-only
checks also passed, but did not cover these cases.

[result.json](result.json) records exact emitted fixture payloads, installed
versions, source hashes, outcomes and limitations. Credential values in this
receipt are explicit dummy fixture strings. AutoGen is retained for existing
users; passing these client checks does not imply its upstream is maintained.

Primary interfaces: [LangChain ChatOpenAI](https://docs.langchain.com/oss/python/integrations/chat/openai),
[CrewAI LLM configuration](https://docs.crewai.com/v1.15.29/en/concepts/llms),
[AutoGen OpenAI client](https://microsoft.github.io/autogen/stable/reference/python/autogen_ext.models.openai.html).
