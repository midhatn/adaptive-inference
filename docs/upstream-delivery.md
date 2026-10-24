# Integration delivery and qualification

The canonical implementation lives in this repository. Upstream changes consume
its public contracts or correct a specific client behavior. A submitted PR is
not a merged integration, and a configuration/schema test is not a completed
agent task or native engine qualification.

The shared [integration contract](integration-contract.md) covers host-selected
normal/background work, unchanged quality settings, bounded admission, explicit
capabilities and durable task continuation. The [integration matrix](integrations.md)
contains the engine profiles and client entry points. All actual inference
qualification uses the established IQ3_S model; fixture responses are labeled
separately. No smaller model or reduced reasoning allowance substitutes for it.

## Delivery sequence

1. Preserve the implementation, exact source inputs, licenses and runnable checks here.
2. Review each target's public extension/configuration path and existing PRs.
3. Test the smallest integration against the actual client or host contract.
4. Submit a focused change with a canonical commit and scoped evidence. Reuse an
   existing relevant PR where possible. Respect required issue approval, human
   review and contributor agreements without claiming they have occurred.
5. Record public links and exact head revisions in the upstream registry. Native
   resource handoff and accepted agent artifacts remain separate qualification steps.

## Target disposition

Checked on 2026-10-24. This table describes the delivery path, not acceptance by
the maintainers. The [machine-readable ledger](../upstream/delivery.json) records
publication status and the relevant source-policy references.
The [remaining engine submission requirements](upstream-submission-requirements.md)
retain exact policy references and native adapter opportunities for llama.cpp,
MLX-LM and vLLM.

| Target | Concrete integration | Delivery path |
| --- | --- | --- |
| Strata | Native resource leases plus nested route-control serialization correction | Update existing #1493; retain #3399 as the separate Windows identity fix |
| llama.cpp | Existing OpenAI-compatible server profile and preserved native source inputs | Human-authored upstream submission required by its contribution policy |
| vLLM | Existing compatible server profile; no duplicate provider | Human validation and DCO required before an upstream submission |
| SGLang | Executable shared-admission guide preserving the existing server configuration | Focused documentation PR |
| Ollama | Executable guide using its existing OpenAI-compatible interface | Focused documentation PR |
| LM Studio | Correct JavaScript SDK `baseURL` option; separately tested gateway recipe | Small reproduced bug-fix PR |
| MLX-LM | Existing compatible server profile | Human-authored submission and Apple-host qualification remain necessary |
| TGI | Retained legacy profile | Repository archived; no new upstream PR possible |
| Hermes | Optional public-hook plugin for host-known child/background work | Catalog entry pinned to this repository; existing core proposals stay separate |
| OpenClaw | Existing provider/subagent defaults with a preserving configuration composer | Issue-first documentation proposal |
| Aider | Existing API-base/model configuration with tested prefixed transport | Focused documentation PR; contributor agreement remains distinct |
| OpenHands | Existing SDK LLM configuration for explicit worker routes | SDK draft and companion documentation; human-only template section stays for its author |
| Continue | Existing provider/API-base and explicit request options | Focused documentation PR; contributor agreement remains distinct |
| Cline | Existing compatible provider; explicit missing budget-field finding | Route documentation PR plus separate feature proposal for the observed gap |
| Roo Code | Retained legacy configuration | Repository archived; no new upstream PR possible |
| LangGraph | Existing ChatOpenAI client, explicit graph/worker route | Approved and assigned issue required before an external PR |
| AutoGen | Existing client factory with explicit capabilities | Maintainers declare it unmaintained; preserve compatibility here |
| CrewAI | Existing `LLM(custom_openai=True)` configuration, four documentation languages | Issue-linked documentation PR with AI-authorship disclosure |

## Evidence levels

- **Core contracts:** request preservation, queue behavior, durable continuation,
  route validation and copy/refusal behavior in the portable test suite.
- **Actual SDK/host fixtures:** installed client serialization, public plugin
  loading and exact host schema validation with synthetic inputs. No model runs.
- **Gateway composition:** actual client through the released gateway to a local
  fake backend, preserving paths, bodies, streaming and explicit refusal behavior.
- **Real IQ3_S qualification:** exact runtime/model configuration, task acceptance
  and cleanup receipts. Earlier results qualify only their recorded compositions.
- **Native always-on qualification:** foreground responsiveness, resource return,
  tool completion and recovery across application/computer restart. This remains
  a separate milestone; the current routing integrations do not establish it.

Canonical source archives retain required upstream integration baselines and
licensed reference inputs. Package dependencies remain separately acquired using
their recorded locks. Source-code preservation is not an offline package registry,
model-weight redistribution or a claim that every target can run on this host.
