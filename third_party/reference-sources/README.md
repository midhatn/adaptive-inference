# Preserved source references

This directory preserves the exact upstream files behind mechanisms used by Adaptive Inference. The project can retain its implementation history, attribution and comparison material even if a remote branch, pull request or repository becomes unavailable.

These are **unmodified archival references**, not runtime dependencies. Adaptive Inference executes its own modules under [src/adaptive_inference](../../src/adaptive_inference). The archived Python, JavaScript, Scala and Rust files are not imported, executed or compiled by the package. They are not complete upstream projects or runnable upstream test suites.

## Local source index

| Mechanism used here | Preserved original source | Adaptation boundary |
| --- | --- | --- |
| Spike-sensitive latency feedback | Twitter Finagle [PeakEwma.scala](finagle/9cc08d15216497bb03a1cafda96b7266cfbbcff1/finagle-core/src/main/scala/com/twitter/finagle/loadbalancer/PeakEwma.scala), revision `9cc08d15216497bb03a1cafda96b7266cfbbcff1`; [license](finagle/9cc08d15216497bb03a1cafda96b7266cfbbcff1/LICENSE), [original notice](finagle/9cc08d15216497bb03a1cafda96b7266cfbbcff1/NOTICE) | The arithmetic informs [costs.py](../../src/adaptive_inference/costs.py). Context groups, minimum samples, expiry and empirical p90 are local safeguards. Finagle endpoint selection, pending-request accounting and decay-on-read behavior are not included. |
| Fresh resource observations and gradual recovery | Strata [resource_presets.py](strata/15a59d4785f492b4df3fb78862373a5383696450/serve/resource_presets.py) and [memory_policy.py](strata/15a59d4785f492b4df3fb78862373a5383696450/serve/memory_policy.py), revision `15a59d4785f492b4df3fb78862373a5383696450`; [license](strata/15a59d4785f492b4df3fb78862373a5383696450/LICENSE) | These medking82 contributions inform [resource_policy.py](../../src/adaptive_inference/resource_policy.py). The portable dispatch policy does not reproduce the upstream native allocator. |
| Context safety margin | Strata [harness-budget.mjs](strata/f273ef65e8f4548125f3e72833cd61019b82080f/apps/desktop/scripts/harness-budget.mjs) and [reference tests](strata/f273ef65e8f4548125f3e72833cd61019b82080f/apps/host/tests/harness-budget.test.mjs), revision `f273ef65e8f4548125f3e72833cd61019b82080f`; [license](strata/f273ef65e8f4548125f3e72833cd61019b82080f/LICENSE) | This medking82 contribution informs [context_budget.py](../../src/adaptive_inference/context_budget.py). The portable planner preserves requested output rather than applying the upstream output clamp. The archived test references upstream fixtures and dependencies that are not included here. |
| SQLite transaction and revision checks | Strata [chat_archive.py](strata/64d119cd602ddc439c311dedf61fda460f2785ef/serve/chat_archive.py), revision `64d119cd602ddc439c311dedf61fda460f2785ef`; [license](strata/64d119cd602ddc439c311dedf61fda460f2785ef/LICENSE) | This medking82 contribution informs [task_store.py](../../src/adaptive_inference/task_store.py). Task ownership, the execution ledger, uncertain-effect reconciliation and the durable feedback runner are local additions. A conversation archive alone does not resume agent execution. |
| Bounded arrival-offset scheduling | NVIDIA Dynamo [policy_queue.rs](dynamo/868de572ad9e10e2effb16bb0cff57f3973ca1e8/lib/kv-router/src/scheduling/policy_queue.rs), revision `868de572ad9e10e2effb16bb0cff57f3973ca1e8`; [license](dynamo/868de572ad9e10e2effb16bb0cff57f3973ca1e8/LICENSE) | A design reference for the independently implemented [scheduler.py](../../src/adaptive_inference/scheduler.py). No Dynamo implementation is part of the runtime. The preserved Rust source is comparison material only. |

Strata originals retain the MIT license and the copyright of Niko1221 and the Strata contributors. Finagle and the selected Dynamo queue are Apache-2.0 licensed. The Dynamo repository license mentions a separate MIT exception for model test data; no files from that exception are included. Finagle's original project NOTICE is preserved verbatim, including its project-wide notices.

## Offline verification

The Windows handoff owner additionally adapts psutil's narrow missing-process
classification from [proc_utils.c](psutil/a1e3067965a075c40b79971cfda51501e80da685/psutil/arch/windows/proc_utils.c),
revision `a1e3067965a075c40b79971cfda51501e80da685`, under its retained
[BSD-3-Clause license](psutil/a1e3067965a075c40b79971cfda51501e80da685/LICENSE).
The independently implemented tracker permits only an `OpenProcess` error 87
with independently confirmed PID absence; access denial and other observation
errors remain failures. No C implementation is compiled or copied into the
runtime, and no process exit count is fabricated for a vanished unretained PID.

From the repository or source-distribution root, run:

`python third_party/reference-sources/verify.py`

The verifier uses only the Python standard library. It reads the archive, checks file sizes and SHA-256 hashes, reconstructs Git blob SHA-1 identities, and verifies source and license relationships. It does not contact GitHub or execute the archived files. Success establishes consistency with the local manifest; it does not authenticate upstream authorship or prove runtime behavior.

[manifest.json](manifest.json) records each original repository, complete revision, source path, permanent source URL, Git blob identity, SHA-256, byte count and local license path. The source bytes come directly from canonical Git objects or GitHub's base64 Git-file response, not from newline-converted working copies. The scoped [.gitattributes](.gitattributes) disables text normalization for archived originals.

The source distribution includes these references. The runtime wheel does not need to ship executable copies of them. Project-level attribution and adaptation notices remain in [NOTICE](../../NOTICE), [REFERENCES.bib](../../REFERENCES.bib) and the [research notes](../../docs/research.md).
