# Reproducing the earlier Strata/Hermes components

The working local prototype combined a patched Strata backend, a native CUDA build, Windows process ownership, external model assets and an optional Hermes client. This repository publishes the reproducible **source integrations**, rather than copying that workstation's installation. The new generic gateway has its own implementation and tests. Historical backend results do not automatically qualify it.

## What is reconstructible here

| Component | Public base | Overlay reference | Export |
| --- | --- | --- | --- |
| Strata engine/server | [v0.2.3.1 baseline 7ddc17a3](https://github.com/Niko1221/Strata/commit/7ddc17a38fe7f31637e895ecfba58c2cd43d65ec) | `c6b23493b01028a18a9eb685d0bb6435c6976316` | Runtime/native/test changes and attribution, plus separate Windows process-rights fix |
| Hermes host intent | [2587d823](https://github.com/NousResearch/hermes-agent/commit/2587d8231fc7e0f3e846acafa46eb5b67cdc70c8) | `eaa9b473e5fab3fa94258f17ed6941aabba73d2d` | All seven files of the opt-in intent change |

Run `python integrations/strata/setup.py --output ../strata-adaptive-source` and, if needed, `python integrations/hermes/setup.py --output ../hermes-intent-source`. Each output must be a new directory with an existing parent. The scripts use only their fixed public URLs/revisions, verify patches and resulting file hashes, and refuse existing destinations without modifying them. They run Git only, not model code, dependency installers or build commands. Failure retains the new output for inspection.

The expected source trees and patch checksums are in [provenance/reconstruction.json](../provenance/reconstruction.json). File hashes represent canonical Git blobs, using LF line endings. A Windows working copy with CRLF may have a different raw file hash while preserving the same Git content. The local reference commits need not be fetchable: the public base plus the included patches and expected hashes reconstruct the selected source.

The Strata overlay omits 44 changes: historical benchmark records, old environment-specific documentation, old CI edits and the historical Hermes private-hook resource plugin. These exclusions are listed explicitly in its source lock. No model weights, native executables, journals, credentials, personal prompts, private run trees or machine paths are published.

## Build and test

Follow [Strata integration instructions](../integrations/strata/README.md) for CPU regressions and a pinned native build. Its CMake dependency is llama.cpp `3cf03257f219afbe7334045ff7c6a06ac68c627d`; it is fetched separately under its own license. The recorded historical CUDA result used Windows / MSVC 14.44 / CUDA 13.4, architecture 89 and a portable AVX2 build. This source export did not rerun a native build or qualify HIP, SYCL or Metal. No hardware executable is redistributed.

Follow [Hermes integration instructions](../integrations/hermes/README.md) for the intent regression. Hermes remains optional. The old resource-feedback plugin depended on private hooks absent from this version and is excluded. Host intent is a scheduling hint, not permission to bypass resource leases.

## Assets and quality

Acquire compatible model weights, tokenizer, pack and vision projector yourself using the pinned upstream documentation and their respective licenses. Acquisition or conversion may require substantial disk, RAM and GPU capacity. The repository contains only explicit local-asset placeholders; setup does not acquire or redistribute models.

The earlier main-request baseline was IQ3_S, context 65,536, high reasoning, total output cap 10,923, reasoning budget 8,192, CPU vision, no MTP and no speed projection. The portable examples preserve these declared settings but do not promise that this model or resource layout fits every computer. Auxiliary compression has a separate budget and is not represented by the main-request example.

The previous standalone Windows supervisor calculated startup resident cache from fresh physical RAM/commit, subtracting a 14 GiB startup allowance and at least 4 GiB headroom, capping at 32 GiB and rounding down to 32 MiB. It refused residual room below 1 GiB. The successful local run selected 23.9375 GiB. That supervisor and its process-containment code are not part of these overlays; the backend's eager initial load does not gain that preflight merely by applying the c6b patch. An operator must size and own the backend independently. A smaller cache changes residency/performance, not model bytes or precision, and no fixed minimum is claimed.

The historical Hermes parent/child acceptance explicitly passed `max_tokens=10923` into the parent constructor and inherited the wire override for its production child. A provider YAML wire cap alone does not yet set the ordinary CLI compressor's reserve. Do not infer the earlier 46,421 compression threshold from the example profile. No persistent Hermes CLI or full leased-tool workflow is qualified by this source export.

## History retained without merging separate claims

The native-qualified common ancestor is `a69684f1f2609da46c82f9719d5159f5f9b307dc`, after merging public v0.2.3.1. Public progress head [b580e627](https://github.com/midhatn/Strata/commit/b580e6270c0e8d2756b0ca9e15cbed4e57ba21ab) is its report-only child. The local scheduler path is a sibling: `a69684f1 -> a31586cc -> 9eff986f -> c6b23493`. b580e627 is not an ancestor of c6b. Native C++ sources are unchanged along the local scheduler path; new Python behavior has separate checks. [Strata PR1493](https://github.com/Niko1221/Strata/pull/1493) and [PR3399](https://github.com/Niko1221/Strata/pull/3399) remain upstream discussion/provenance, not evidence that all local integration work is merged.

See [evidence.md](evidence.md) for current reconstruction results, historical local measurements and unqualified claims.
