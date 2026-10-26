# Precision and useful task performance

Assessment date: 26 October 2026. This is a source assessment and experiment
plan. No new precision mode is enabled and no IQ3_S speedup is established.
The [Continue saved task milestone](../PLAN.md#next-execution-packet) has now
passed its installed acceptance gate with unchanged precision. The separate
comparison below remains unrun.

## Decision

Use the engine's existing mixed-precision implementations before considering
new kernels. The retained Strata engine already uses FP16 or BF16 inputs with
FP32 accumulation for large dense prompt operations. Lower-precision inputs
and higher-precision running sums are compatible with Tensor Core execution;
`CUBLAS_COMPUTE_32F` does not mean that its input matrices are FP32.
[NVIDIA's cuBLAS contracts](https://docs.nvidia.com/cuda/cublas/index.html#cublascomputetype-t)
distinguish these types explicitly.

The smallest existing candidate for a separate trial is `STRATA_PF_WMMA=1`.
It changes eligible expert prompt groups to FP16 activations and dequantized
weight tiles, while retaining FP32 sums and the same IQ3_S files. It was
introduced for Volta, which lacks the integer Tensor Cores available on Ada.
That history does not predict a benefit on an RTX 4070 Laptop. Actual dispatch,
resource use, task quality and complete task time must decide adoption.

## What is already in the retained engine

The [bundled Strata integration](../integrations/strata/README.md) reconstructs
the inspected source without following an external PR. It preserves the
relevant code from local reference revision
`c6b23493b01028a18a9eb685d0bb6435c6976316`; the documented reconstruction tree is
`f2d6e86a0d49aaae47308904a1d5d9ea46e3b9a8`. Paths below are relative to that
reconstructed checkout. The earlier qualified native executable has SHA-256
`744205e4e024b5cbba19e4b560678ffe21e6899e59050929f7af51557f3c6198`;
source identity alone does not establish a new build's execution or speed.

| Part | Existing behavior | Inspect in reconstructed source |
| --- | --- | --- |
| Model weights | The IQ3_S baseline uses mixed quantized storage. It is not a full FP32 model to convert to FP16. Storage precision, activation precision and accumulation precision are separate choices. | `include/strata/artifact/gguf_reader.hpp`; native pack metadata for the operator's actual assets |
| Dense prompt work | FP16/BF16 operands with FP32 accumulation and normally FP32 output. | `src/prefill/gemm.cu`, `cublasGemmEx` calls around lines 1109–1201 |
| Prompt attention | The default CUDA INT8-KV path for this architecture uses half-input Tensor Core products and FP32 sums; some values use high/low half parts. | `src/kernels/cuda/qsa_prompt_attn.cu`, lines 48–65 and 2409–2427 |
| Optional expert prompt work | `pf_wmma()` requires an explicit opt-in and every visible CUDA device to have compute capability at least 7. Eligible grouped operations use half tiles and float accumulators. Other dispatch routes can bypass it. | `src/prefill/prefill.cpp`, lines 1166–1223 and 4608–4632; `src/kernels/cuda/iq_kernels.cu`, lines 5299–5338 and 5648–5700 |
| Other state | Recurrence, decode, transfers and control work are not all dense matrix multiplications. Some float state and architecture-specific implementations remain. | `src/kernels/cuda/native_gdn.cu`; `src/core/layer.cpp` |

The optional expert path changes activation rounding from the default q8_1
route. FP16 has higher activation precision in that comparison, but different
rounding can still change generated tokens. It is not a blanket accuracy
guarantee or a request to expand the whole model into FP16 memory.

Full FP16 accumulation is a different change. No supported global switch for
it was found in the inspected native interface. Simply replacing the cuBLAS
compute-type enum would also conflict with the current float scalar/output
contract. [PyTorch's full-half accumulation control](https://docs.pytorch.org/docs/main/notes/cuda.html#full-fp16-accumulation-in-fp16-gemms)
belongs to PyTorch's backend; it does not configure this separately compiled
C++/CUDA engine. The inspected HIP-only options and the GDN path gated to
compute capability 7.0 are also not Ada precision controls.

## GPU environment and evidence boundary

The user reports enabling the GPU unlock before resuming this work. The
[pinned public validation report](https://github.com/midhatn/gpu-unlock-ada/blob/440d22f9c84ddcf3aad41db1b5c181cf3c1321dd/docs/ad106m-windows-secure-boot.md),
submitted in [GPU-unlock PR #64](https://github.com/JustAResearcher/gpu-unlock-ada/pull/64),
reports a matched dense FP16 GEMM change from 46.75 to 77.83 TFLOPS, about
66.48%, with FP32 approximately unchanged. Its collector disables reduced
precision reductions, and full-half accumulation where the API exists.
This is a specific matrix benchmark, not an IQ3_S application result.

Treat the post-restart machine as a changed performance environment. Neither
an idle GPU query nor an enabled setting demonstrates the reported gain.
An FP16 comparison within one boot measures that candidate on the current
configuration; it does not isolate the causal benefit of the unlock.
The project does not change firmware, driver, power or global precision
settings as part of this assessment.

The model also moves data through RAM, SSD and PCIe. Faster arithmetic cannot
remove time spent waiting for data or tools. NVIDIA's
[matrix multiplication guide](https://docs.nvidia.com/deeplearning/performance/dl-performance-matrix-multiplication/index.html)
explains the distinction between compute and memory limits. Measure the
bottleneck of the actual workload before selecting an optimization.

## Reversible qualification

1. Preserve the accepted installed continuation qualification as the baseline.
   Use new experiment runs, the same IQ3_S assets, exact native build/libraries,
   request bodies and independent task validators. Preserve context 65,536,
   output allowance 10,923, high/8,192 reasoning and disabled speed projection.
2. Compare unchanged control, candidate with only `STRATA_PF_WMMA=1`, and a
   restored unchanged control. Deliver and record the option in the actual
   native child's environment: the current owner clears inherited `STRATA_`
   variables. A shell setting alone does not prove delivery. Keep existing
   MMQ grouping enabled and other precision, cache, speculative and thread
   settings unchanged.
3. Verify actual eligible kernel/branch execution. The option's presence in a
   binary is insufficient. Record effective prompt chunk, cache allocation
   and RAM/VRAM use; additional FP16 buffers can change automatic planning.
   A bypassed branch is a no-op, and a changed chunk is a separate confounder
   to report. Keep the existing resource-admission and ownership checks.
4. Use representative short and long prompts with matched seeds and unchanged
   allowances. Check report arithmetic, tool arguments, completion and one-time
   effects with existing validators. Record retries, numerical errors, prompt
   and decode time, full task time and foreground responsiveness. Changed
   tokens are not automatically wrong, and agreement alone is not a quality
   metric. Tolerance for small numerical differences does not relax task
   correctness or progress preservation.
5. Adopt only a repeatable useful improvement that survives the restored
   control and quality/resource gates. Retain slower or invalid candidates as
   evidence. Publish a relevant upstream implementation only after validating
   that exact integration; this source review is not such validation.

This assessment reuses existing Strata/ggml implementations and NVIDIA API
contracts. Their licenses and attribution remain in the bundled integration.
The external GPU report supplies context only; no implementation, driver
change or additional dependency is copied from it.
