# Adaptive Inference

**A shared adaptive layer for inference engines and AI agents.**

[![CI](https://github.com/midhatn/adaptive-inference/actions/workflows/ci.yml/badge.svg)](https://github.com/midhatn/adaptive-inference/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0%20%2B%20MIT-blue)](LICENSE)

Adaptive Inference queues user and agent requests, learns from completed execution times, and supplies feedback to applications that can check and correct their results. It runs in front of an existing OpenAI-compatible model server. Model weights, token budgets, tools and generated responses remain under the application and backend's control.

This repository is the **canonical source for new development**. Earlier Strata and Hermes work is retained as pinned, reconstructable integration patches. Upstream PRs remain focused consumers of this project, with their own review and merge decisions.

## Start in five minutes

Python 3.11 or later; no GPU or model is required for the reproducible demo.

```bash
git clone https://github.com/midhatn/adaptive-inference.git
cd adaptive-inference
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell instead: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
adaptive-inference demo
```

The demo uses an explicitly simulated model server over real HTTP. It checks queue ordering, learned timing feedback and correction after a failed acceptance check. It is a reproducible software check, not an LLM benchmark.

To use an already running model server:

```bash
adaptive-inference doctor --config examples/engines/llamacpp.json
adaptive-inference serve --config examples/engines/llamacpp.json
```

Point a compatible client at `http://127.0.0.1:18100/v1`. For background agent work, use `http://127.0.0.1:18100/background/v1`. Both routes share the same queue and backend. Use a model name actually returned by that backend's `/v1/models`; examples deliberately do not select or download a model for you.

See [reproduction instructions](docs/reproducing.md), [engine and agent setup](docs/integrations.md), and the [development plan](PLAN.md).

## What works

| Capability | Implementation |
| --- | --- |
| User/background scheduling | Bounded pending queue; stable arrival-offset ordering; one active upstream HTTP request |
| Online timing feedback | Context-separated Peak EWMA plus empirical p90, three-sample minimum, expiry and failure invalidation |
| OpenAI-compatible serving | Chat, text completion and embeddings where the selected backend advertises them; model listing; SSE forwarding |
| Conservative admission | Optional observed RAM/Windows-commit floor, bounded queue/response/time limits |
| Outcome-based correction | `run_with_feedback`: retain the original prompt, use caller-provided acceptance feedback, stop on success or attempt limit |
| Existing native integration | Pinned Strata memory/parking/lease patches and Hermes intent-tagging patches, with reconstruction verification |

Engine profiles cover **Strata, llama.cpp, vLLM, SGLang, Ollama, LM Studio, MLX-LM and TGI**. Client recipes cover **Hermes, OpenClaw, Aider, OpenHands, Continue, Cline, Roo Code, LangGraph, AutoGen and CrewAI**. The [compatibility matrix](docs/integrations.md) distinguishes protocol contracts, documented configuration and actual application/native evidence. A profile is not a native GPU-memory plugin.

## Architecture

```mermaid
flowchart LR
    U[User applications] --> G[Adaptive gateway]
    A[Agent applications] --> G
    G --> Q[Bounded queue and admission]
    Q --> B[Backend adapter]
    B --> E[Existing model server]
    E --> L[Completed timing observations]
    L --> Q
    E --> V[Application acceptance check]
    V -->|Correction feedback| A
```

The gateway never retries a generation on its own. Queued disconnected clients are removed; active disconnected requests are drained before another request is dispatched. If upstream completion becomes uncertain, the gateway stops dispatching and reports the state. It does not assume that closing an HTTP connection freed GPU memory.

Generic profiles do not resize a backend's cache, move KV state or preempt native generation. These require explicit backend capabilities and native verification. Strata's richer resource controls are preserved in its integration, with separate evidence. See [architecture](docs/architecture.md) and [evidence](docs/evidence.md).

## Evidence and lineage

The initial Windows/Strata predecessor completed eight correct real-model requests, learned timing estimates for both request classes, and released all eight owned processes. Its startup planner selected a 23.9375 GiB cache from measured capacity. That is historical evidence for that exact composition; it is not a speed claim for this gateway or every listed backend.

Portable gateway tests and CI are the acceptance evidence for this repository. Read the [evidence ledger](docs/evidence.md) before comparing results. The [upstream PR index](docs/upstream-prs.md) records earlier work, including closed and superseded PRs.

## Research and contributions

Research references and reuse decisions live in [docs/research.md](docs/research.md) and [REFERENCES.bib](REFERENCES.bib). [NOTICE](NOTICE) and `third_party/` preserve source attribution and licenses. [CITATION.cff](CITATION.cff) describes how to cite this project.

Contributions should start here, pass the common contract tests, and then be offered upstream as narrowly scoped adapters or fixes. See [CONTRIBUTING.md](CONTRIBUTING.md). The goal is useful task completion with feedback and recoverable mistakes; optimizations follow measured need.
