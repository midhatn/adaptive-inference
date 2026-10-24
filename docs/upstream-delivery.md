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

Checked on **2026-10-24 at 01:41 UTC**. Eleven new pull requests are open and
the existing Strata #1493 draft has been updated. None is represented as merged.
Three related issues and one feature discussion are tracked separately. The
18-target scope is unchanged. The delivery release is v0.3.0; retained gateway
qualification used v0.2.0, as recorded separately in the ledger. The [machine-readable ledger](../upstream/delivery.json)
records full head revisions, check results, outstanding conditions and the original
source-policy references; the [registry](../upstream/registry.json) preserves the
historical PR inventory alongside this refresh.
The [remaining engine submission requirements](upstream-submission-requirements.md)
retain exact policy references and native adapter opportunities for llama.cpp,
MLX-LM and vLLM.

| Target | Submitted or retained integration | Current delivery status |
| --- | --- | --- |
| Strata | [Existing #1493](https://github.com/Niko1221/Strata/pull/1493), head `06ba725d8b9bb42b457302f71dd85204e9760c32` | Draft updated with the narrow nested route-control correction; 46 CPU/fake-engine checks. `metal-link` is failed; native/public-workflow gates remain open. [#3399](https://github.com/Niko1221/Strata/pull/3399) stays separate. |
| llama.cpp | Existing OpenAI-compatible server profile and preserved native source inputs | Human-authored upstream submission required by its contribution policy |
| vLLM | Existing compatible server profile; no duplicate provider | Human validation and DCO required before an upstream submission |
| SGLang | [#46199](https://github.com/sgl-project/sglang/pull/46199), head `c3aaf7ec` | Ready for review; corrected title check passed and fresh CI is queued. Older gate failures refer to its prior draft state. Six shared gateway/SDK fixture checks are not native SGLang qualification. |
| Ollama | [#19255](https://github.com/ollama/ollama/pull/19255), head `c3304299` | Ready for review; OpenAI-compatible admission guide with fixture evidence only. |
| LM Studio | [#267](https://github.com/lmstudio-ai/docs/pull/267), head `5a28a355` | One-line JavaScript SDK `baseURL` fix. CLA check remains failed despite a `CLA signed` label; agreement/check state is unresolved. |
| MLX-LM | Existing compatible server profile | Human-authored submission and Apple-host qualification remain necessary |
| TGI | Retained legacy profile | Repository archived; no new upstream PR possible |
| Hermes | [Catalog #143827](https://github.com/NousResearch/hermes-agent/pull/143827), head `2c1411b3` | Open catalog-only PR pins `d6f4e201` and `plugins/hermes`; public-hook/admission evidence is scoped separately from the real IQ3_S task receipt. No hosted checks reported. |
| OpenClaw | [Docs #182080](https://github.com/openclaw/openclaw/pull/182080), head `f64d74b0`, linked to [issue #182077](https://github.com/openclaw/openclaw/issues/182077) | Draft provider/subagent route guide. Source/schema checks and single-page MDX sanity passed; hosted autoreview was not run, docs CI is skipped, and upstream auto-response automation fails. |
| Aider | [#5899](https://github.com/Aider-AI/aider/pull/5899), head `d5e113fb` | Open base-path clarification, distinct from existing runtime-normalization #5488. No hosted checks reported. |
| OpenHands | [SDK #6180](https://github.com/OpenHands/software-agent-sdk/pull/6180), head `415785b5`, and [docs #997](https://github.com/OpenHands/docs/pull/997), head `4ef32371` | Both drafts. The SDK's human-only template section remains unchanged; companion docs should land with or after the example. SDK and gateway checks use HTTP fixtures. |
| Continue | [#13415](https://github.com/continuedev/continue/pull/13415), head `12eba630` | Open base-path guide. CLA, Snyk quota, FFmpeg setup and aggregate checks remain unresolved; formatting passed. |
| Cline | [Docs #15308](https://github.com/cline/cline/pull/15308), head `cbbc9626`, plus [feature discussion #15309](https://github.com/cline/cline/discussions/15309) | Open route clarification; fork preview needs maintainer approval. Explicit budget-field support is proposed separately and not implemented. |
| Roo Code | Retained legacy configuration | Repository archived; no new upstream PR possible |
| LangGraph | Existing ChatOpenAI client and [proposal #9419](https://github.com/langchain-ai/langgraph/issues/9419) | Issue open, no assignment or approval recorded; external PR waits for that required step. |
| AutoGen | Existing client factory with explicit capabilities | Maintainers declare it unmaintained; preserve compatibility here |
| CrewAI | [#8481](https://github.com/crewAIInc/crewAI/pull/8481), head `34302500`, linked to [issue #8480](https://github.com/crewAIInc/crewAI/issues/8480) | Open four-language guide. Required `llm-generated` label needs maintainer permissions; full-site validation retains an unchanged upstream Korean frontmatter failure. |

The two reported CLA checks are not treated as signed agreements. No signature
or human-review declaration was posted by this workflow. Continue's additional
JetBrains failure occurred while extracting the setup action's FFmpeg download,
before its tests; the Snyk service reports exhausted private-test quota. OpenClaw's
auto-response failure is an `undefined.owner` exception in its unchanged bot.
These diagnoses do not turn failed or skipped checks into passes. Strata's
`metal-link` job failed at compilation against Xcode 15.4's missing Metal4/mathMode
declarations; the affected Metal source and workflow match its base revision.
SGLang's older failed title run remains visible alongside its newer successful
title check. SGLang and Ollama were subsequently marked ready with unchanged
heads; their fork previews still require maintainer approval.

OpenHands's [SDK template](https://github.com/OpenHands/software-agent-sdk/blob/acd96e6fa424c02432304395b9208f99be24b54d/.github/PULL_REQUEST_TEMPLATE.md)
reserves the HUMAN section for its author. CrewAI's [contribution guide](https://github.com/crewAIInc/crewAI/blob/07361f6dc5f96d22efe565ff89297d22bce4a90f/.github/CONTRIBUTING.md)
requires its AI-authorship label, and LangGraph's [PR template](https://github.com/langchain-ai/langgraph/blob/4897c51365d3c82a3808da2bdb7ef2d55daba1a9/.github/PULL_REQUEST_TEMPLATE.md)
requires an approved issue and assignment. Cline's proposal follows its designated
Feature Requests discussion route; the documentation exception does not approve
the proposed budget feature. Required policy steps remain explicit rather than
being inferred from publication or local test success.

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
