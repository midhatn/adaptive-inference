# Integration qualification receipts

These checks were completed on 2026-10-24. They extend the released v0.2.0
foundation. The optional integrations are delivered from the canonical source
commit containing this document; they are not retrospectively added to v0.2.0.

| Surface | Completed check | Scope and receipt |
| --- | --- | --- |
| Portable core | 105 tests passed on Windows/Python 3.11 | Includes route/credential validation and OpenClaw configuration copying/refusal; cross-platform CI is recorded separately |
| Source preservation | 16 tests passed | Existing preservation/reconstruction machinery; complete v0.2.0 offline restoration remains recorded in its release receipt |
| Python clients | 15 actual SDK HTTP checks passed | LangGraph, CrewAI and AutoGen; normal/background text, streaming and strict tool schemas. [Reproduce](../provenance/python-clients/README.md) |
| Hermes plugin | 41 current-SDK tests; 40 passed plus one explicit older-SDK skip; 15 official admission checks | Actual public host hooks and serialization with synthetic child/HTTP fixtures. [Independent receipt](../integrations/hermes-plugin-tests/result.json) |
| OpenClaw | 14 focused cases in six unittest methods; exact pinned agent-defaults schema accepted unchanged | No full app/provider transport. [Schema fixture](../integrations/openclaw-schema-check/README.md) |
| Aider, Continue, Cline | 2 Aider, 4 current-source JS and 4 published-package HTTP requests passed | Preserved source closure; Cline's missing explicit reasoning budget is retained as a limitation. [Reproduce](../provenance/client-config-transports/README.md) |
| SGLang/Ollama recipes | 6 actual SDK to released gateway to fixture-backend tests passed | Text, SSE, quality/parameter preservation, unsupported controls and no ambiguous retry. [Reproduce](../integrations/openai-admission/README.md) |
| LM Studio example | Original constructor fails typecheck and selects the wrong default URL; corrected `baseURL` passes | Actual JS SDK with fake fetch and zero network sockets. [Reproduce](../provenance/lmstudio-baseurl/README.md) |
| CrewAI upstream guide | Four identical localized snippets, two actual HTTP requests and four MDX compilations passed | Full-site validation encounters an unchanged upstream Korean RAG-tool frontmatter error. [Guide/check](../integrations/crewai-guide/README.md) |
| OpenHands SDK | 24 configuration/HTTP tests plus two released-gateway composition tests passed | Public `LLM` configuration; locked LiteLLM requires the existing `litellm_proxy/` provider for the tested unknown custom alias. [Reproduce](../integrations/openhands/README.md) |

All HTTP/model responses above are fixtures. IQ3_S identifiers and quality fields
in those requests verify serialization only. They are not new model-quality,
native GPU-release, full application, restart-survival or end-to-end task results.
The actual model results and retained failures are separately described in the
[evidence ledger](evidence.md). No comparative performance gain is claimed.

Hermes's current SDK tests emitted 42 warnings; the retained SDK emitted 82.
The official plugin admission check reported zero admission warnings. Its
dependency-install mode was not run. The older SDK's skipped test concerns the
absent public cron-identity API; missing-capability behavior is separately tested.

Client defaults are not interchangeable: LangChain renames the output-cap field
and can omit vendor reasoning response fields; CrewAI converts function schemas
to strict mode; Cline's standard effort control does not imply an exact reasoning
budget. Reproduction instructions retain these limits instead of silently changing
the established quality policy.
