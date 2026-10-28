# Qualifying useful heterogeneous inference

Assessment date: 28 October 2026. This guide makes the existing
[hardware-expansion milestone](../PLAN.md#m9--expand-hardware-only-where-it-helps)
reviewable. It enables no accelerator, changes no admission policy and reports
no new Adaptive Inference performance result. The
[gateway contract](integrations.md) remains an HTTP and task boundary; forwarding
a request does not grant control of an engine's device scheduling or memory.

## Choose a complete-work objective

Optimize the time to an accepted task result under declared quality, context
and responsiveness constraints. Record inference, tools, child joins and final
validation. For multiple agents, measure per-task latency and the elapsed time
until all required tasks finish. Preserve the same model assets, expert count,
reasoning allowance, output limits, tools and required vision capability.

Low GPU utilization, DRAM bandwidth or SSD throughput identifies an observation,
not a spare resource that another accelerator necessarily fixes. Measure the
dependency causing the wait: ready work, reads, copies, synchronization or
compute. Report fresh prefill, reused-prefix work, decode and task completion
separately. A faster stage can coexist with a slower complete task.
Spare measured DRAM bandwidth is a reason to test overlap; sharing that memory
is not evidence of saturation. Compare the same useful work sequentially and
concurrently, including device-specific transfer and completion latency.

## Counterevidence worth preserving

[Gufo PR #568](https://github.com/gufo-org/gufo/pull/568), still open at inspected
head `cb708e10f7b2c96c012d30fa7a69d9ae0568a650`, targets XDNA2 prefill.
A [contributor report from a separate 0.18 port](https://github.com/gufo-org/gufo/pull/568#issuecomment-6295731394)
describes roughly 8% better whole-mode prefill alongside speculative acceptance
falling from 91% to 70–72% and decode falling from 72–75 to 45–47 tokens/s.
These are results from that contributor's modified port on Strix Halo, not a
reproduction of the inspected PR head here or evidence against every NPU
implementation.

The separate [Phoenix/CUDA report](https://github.com/mikealanni/gufo/blob/12a2bbda30388fe67d0194ea288103224d795ca4/docs/models/qwen3.8-flash-next/PHOENIX_CUDA_NPU_REPORT.md)
records a Windows Strata adaptation, not a Gufo benchmark. Its final NPU
candidate increased fresh-prefill latency in all three confirmation pairs at
each tested length: median paired increases of 2.35% at 2,667 tokens and 3.61%
at 7,805 tokens. Physical execution and arithmetic checks did not establish
acceleration. Its configured 65,536-token capacity was not a full-context test.
These public observations motivate acceptance gates, not replay of consumed
experiments or replacement of a working baseline.

## Qualify evidence in stages

1. **Identify the environment.** Record exact device generation, discrete or
   shared memory topology, OS, driver, firmware, loaded runtime libraries,
   engine/build and artifact hashes. Bind observations to boot and sleep/wake
   transitions. A device listed as healthy or a context successfully allocated
   is not proof of kernel execution. Compare original fault identities and
   event times with later publications; retained metadata must be labelled
   retained. Windows [0x141 documentation](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/bug-check-0x141---video-engine-timeout-detected)
   identifies a live dump, not by itself the responsible GPU or NPU driver.
2. **Check actual arithmetic.** Use changing inputs, complete output checks,
   execution counters and explicit completion. Distinguish a labelled
   no-dispatch sentinel control from an injected device failure. Verify the
   installed artifact's supported shapes, layouts and arithmetic. BF16 operands
   do not establish accumulation precision or equivalence to quantized-model
   execution; the [precision assessment](precision-research.md) explains those
   separate choices.
   Audit the instruction binary actually submitted, not an adjacent generated
   intermediate that may belong to a different build. Preserve their identities
   separately when they disagree.
3. **Check model work.** Use actual operator inputs and the original native
   reference. Declare numerical tolerances and test downstream logits or task
   quality where rounding changes. Sampled rows padded to a fixed kernel shape
   can test arithmetic; duplicated samples do not measure natural full-chunk
   throughput. Verify the timed path actually dispatches the candidate.
4. **Compare complete tasks.** Alternate matched control/candidate runs and
   retain failures. Record actual input, reused and generated token counts,
   observed context occupancy and configured capacity separately. Check tool
   outcomes, joined child ordering, final output, complete transport and owned
   cleanup. Token budgets alone do not make generated workloads equal; report
   differences and use a separate fixed-work comparison when needed.
5. **Decide within resource limits.** Include setup, transfers, padding,
   synchronization, decode, cache transitions and fallback in elapsed time.
   Observe available RAM, process memory, dedicated VRAM, paging and I/O
   throughout startup and concurrent work. Stop an owned trial at its declared
   resource floor; an aborted or incomplete run remains unsuccessful. A
   component pass cannot promote an untested backend capability.

## A shared-expert hypothesis, with an explicit memory budget

Reuse native mechanisms before designing another scheduler.
[Gufo's GLM executor](https://github.com/mikealanni/gufo/blob/46408c0533a8e4a0e1787b1f1200b21e6ce7171e/src/models/glm53_flash/kernels/rocm/executor.cpp)
queues shared gate/up work before routed experts and joins afterward; activation
and shared down work stay on the GPU. It retains original quantized weights,
so this pattern alone does not prove permanent GPU-memory relief.

Moving a shared expert could free useful GPU capacity only if its original
allocations can actually be removed. Account for expanded host weights,
persistent buffers, copies and fallback storage. Declare how single-token
decode, tails and concurrent contexts work: retaining GPU weights forfeits
that memory saving, while reloading them adds transition cost. Fixed large
matrix shapes can spend most decode work on padding. Mapped host buffers still
require traffic to a discrete GPU.

Preserve native dependencies and accumulation order. In the inspected
[Strata source](https://github.com/Niko1221/Strata/blob/a42cc3d7df70d1940de82cd0882f03e1f5dfc741/src/dsv41/ds4_model.cu),
shared output initializes the accumulator before routed contributions; simply
joining last changes that order. An NPU wait must also preserve read/copy
progress. This remains a hypothesis requiring arithmetic, memory-lifecycle and
complete-task evidence, not a recommended placement or implemented adapter.

## Source and reuse boundaries

| Inspected primary source | Identity and permitted use |
| --- | --- |
| Gufo GLM executor above | MIT, `46408c0533a8e4a0e1787b1f1200b21e6ce7171e`; dependency and ownership reference, not a Phoenix binary |
| Strata model implementation above | MIT, `a42cc3d7df70d1940de82cd0882f03e1f5dfc741`; accumulation and allocation reference, not an update to this repository's retained overlay |
| [Phoenix queue examples](https://github.com/AbhiramJayasankar/ryzenai-npu-lab/blob/a9531b87b770fd3142164b61254fb6f74fed2d22/experiments/pk_engine.py) | MIT, `a9531b87b770fd3142164b61254fb6f74fed2d22`; existing bounded DMA/queue checks, not attribution of another machine's faults |
| [AMD NPU architecture](https://docs.kernel.org/accel/amdxdna/amdnpu.html) | Official Linux driver documentation, checked 28 October 2026; NPU graph/firmware model, not a Windows ABI or permission to schedule external CUDA/SSD work |

Only research references are added here; no upstream implementation is copied
or installed. Future code reuse follows the
[source-preservation contract](source-of-truth.md), including exact licensed
sources. Publish sanitized measurements and scope limits, never private prompts,
personal paths or raw workstation logs.
