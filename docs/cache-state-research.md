# Cache state: endurance, reuse and task recovery

Assessment dates: 25–26 October 2026. This is an adopted design and qualification
plan, not an enabled cache backend or a performance result. The active
[continuation milestone](../PLAN.md#next-execution-packet) keeps priority.

## Decisions from the two papers

**Gandalf is useful for the storage-efficiency lane.** Irawan et al.,
[arXiv:2610.30791v1](https://arxiv.org/html/2610.30791v1), distinguish reusable
full-attention prefixes from shorter-lived linear/sliding state. Their placement
policy weighs reuse, capacity, SSD writes and displaced entries together.
The reported average 7.3-fold endurance improvement is an estimate from their
workloads and storage model, not a measured lifetime extension for our SSD.
We adopt the decision factors and the requirement to measure writes; we have
not reproduced Gandalf or located an author-linked implementation in the paper
and LMCache repository searches inspected for this assessment.

**Cross-model transfer remains a separate research option.** Heo et al.,
[arXiv:2608.03893v1](https://arxiv.org/html/2608.03893v1), fit per-head ridge
mappings using selected source layers and RoPE factoring. Their six tested
pairs use dense full attention with matched KV geometry; hybrid/recurrent
models are outside scope. Four pairs retain 73–98% of standalone accuracy,
while two degrade sharply. Mapper timings omit inter-process cache shipping.
This cannot qualify our single-model, hybrid IQ3_S baseline. A model switch
and approximate state conversion need their own scope, calibration and task
quality evidence; matching tensor dimensions alone is insufficient.

Both papers are version 1 preprints and identify CC BY 4.0 licenses. We cite
their ideas; no paper text, figures, weights or implementation have been copied.

## AKV: agent-directed cache operations

**Useful for a later cache-capable adapter; not enabled in the current runtime.**
The user-supplied [AKV implementation](https://github.com/thu-nics/AKV/tree/c567a429a058f1abce3b2879e69978b09e0fda4c)
was inspected at `c567a429a058f1abce3b2879e69978b09e0fda4c` on 26 October 2026.
Its root license is Apache-2.0 with SGLang attribution; the inspected reposition
kernel has a separate MIT notice that must also survive any reuse. Fu et al.'s
[Cache Engineering for Agents](https://arxiv.org/html/2610.28577v1)
introduces selective KV removal and position compaction while keeping the text
trajectory. Retained cache can be reused, but removal changes future attention;
this is not lossless context retention. Cache identity must include the ordered
operation history, not merely the tokens and final positions. The paper's serving
experiment uses GPT-OSS-120B in BF16 on eight A800 80-GB GPUs with trajectory
replay; its reported gains are not our laptop measurements or autonomous media
qualification. The paper and software have separate licenses; no source or
paper material is copied here.

The current [system contract](https://github.com/thu-nics/AKV/blob/c567a429a058f1abce3b2879e69978b09e0fda4c/akv/system/README.md)
requires its modified SGLang backend, one-token pages and a supported attention
backend. Its Drop/Reposition architecture list omits our hybrid
Qwen3.8-Flash-Next; ordinary Qwen3 support does not imply that hybrid support.
These requests also exclude HiCache and external/session caches. Forwarding the
new JSON fields to Strata would not implement their semantics. The public
interface uses `drop_message` and `reposition`; the paper's illustrative nested
`cache` field is not a substitute for the implementation's API.

The [actual capability gate](https://github.com/thu-nics/AKV/blob/c567a429a058f1abce3b2879e69978b09e0fda4c/akv/system/sglang/srt/context_system/capabilities.py)
confirms those architecture limits and requires FP16/BF16 execution and
unquantized KV; those dtype checks alone do not prohibit every form of quantized
weights. The supplied [build path](https://github.com/thu-nics/AKV/blob/c567a429a058f1abce3b2879e69978b09e0fda4c/akv/system/_build.py)
imports Unix-only `fcntl`/`flock`, so it is not a native Windows installation path
as written. These are source findings, not a completed portability test.

Adopt two requirements for a future adapter: preserve the complete conversation
and cache-operation history beside the existing task checkpoint, and advertise
cache operations only after exact backend/model capability checks. TaskStore
remains authoritative for completed effects, budgets and the original objective.
A cache reconstruction must reproduce the declared operation history; silently
reverting to ordinary full-context prefill is a different policy. An incompatible
cache must never cause a tool effect to be replayed.

Treat cache relief as one optional action alongside existing release/restore.
Measure actual RAM/VRAM returned, temporary-copy peaks, restoration cost and
completed-task quality. A smaller attention context does not prove that model
weights were unloaded or enough memory was released for H3. First resolve native
support for the unchanged IQ3_S assets, then compare a frozen full-workflow
baseline with the declared cache policy. Qualification must retain IQ3_S quality;
M2 recovery remains the immediate priority.

## Existing mechanisms to reuse

The [retained Strata source](../integrations/strata/README.md) already contains
same-model session files. At local reference revision
`c6b23493b01028a18a9eb685d0bb6435c6976316`, `serve/server.py`
provides `POST /slots/0?action=save|restore`, enabled by a configured
`--slot-save-path`. It rejects parallel-request mode and serializes access
through its existing FIFO. The `include/strata/core/conversation_file.hpp` contract
binds saved state to model/configuration identity and includes running state,
checkpoints and authoritative attention data. Its checksums detect corruption;
they are not authentication. Start the native feasibility experiment here,
preserving Strata authorship and existing license notices. Source inspection
does not qualify save/restore through our installed controller. Its retained
`docs/DETAILS.md` records unqualified Windows native behavior and possible later
token divergence after restart; preserving state bytes does not guarantee
identical future tokens. Use the bundled source reconstruction, not a presumed
public URL for this local revision.
Native model fingerprints sample file size and edge regions, and the config
identity uses an engine version rather than a binary hash. The adapter must
independently bind its reviewed asset/build manifest; these native checks alone
do not prove exact model contents or executable identity.

For a later vLLM port, the official
[LMCache Qwen3.8-Flash-Next recipe](https://docs.lmcache.ai/recipes/qwen3_8_flash_next.html)
already describes separate hybrid object groups and aligned recurrent-state
caching. It also identifies non-cacheable scratch state, engine/kernel layout
constraints and limits to output equivalence. Its multi-GPU validation is not
our IQ3_S Windows result. LMCache's
[lazy offload](https://docs.lmcache.ai/mp/lazy_offload.html)
is another existing mechanism to evaluate: it defers stores, but does not
guarantee that an idle tail is persisted. It is not Gandalf and not a durable
task checkpoint. Recheck current connector versions before any port.

An independent Apache-2.0 implementation,
[`alesha-pro/vllm-cross-model-kv`](https://github.com/alesha-pro/vllm-cross-model-kv/tree/2e27fb4bcadcbe07136a79480d50ef7d81a2e1dc),
exists at revision `2e27fb4bcadcbe07136a79480d50ef7d81a2e1dc` and targets
vLLM 0.26.0. It is a reuse candidate if cross-model research becomes applicable,
not an NVIDIA release or a dependency of this project. We inspected its README
and repository identity; we have not audited or executed its connector.

## Integration into this project's contracts

TaskStore remains the authority for the original objective, completed tools,
accepted outputs, request/attempt accounting and uncertain operations. Native
cache state is an optional acceleration artifact. Removing every optional
cache must leave the durable task recoverable through its existing safe
boundaries. A cache miss may recompute model context; it may not replay a
confirmed tool effect, renew a budget or clear an unfinished-operation fence.

The first implementation target is an owned, same-model save/restore adapter
using the existing native API, after Continue saved task is qualified. It must
bind an artifact to the exact model/quantization, tokenizer/rendered prefix,
backend/layout, context settings and safe task checkpoint. All required hybrid
state must describe the same prefix. A checksum-valid full-attention cache
without compatible recurrent state is not a usable checkpoint.

Cache ownership follows the existing native owner and handoff. Drain requests
before capture; retain any asynchronous store until completion is known;
never delay urgent foreground release indefinitely to save optional state.
After restore refusal, use a clean native context before normal re-prefill;
do not infer that partial mutation was rolled back from an HTTP error alone.
Reuse the upstream atomic file path and existing controller locks rather than
introducing another recovery database or lease service.

Only after complete same-model restore passes should placement be split by
cache type. Whole-session native files are not a per-layer admission API.
The controller cannot implement Gandalf by dropping pieces of such a file or
passing invented controls through the OpenAI-compatible gateway. A suitable
adapter must first expose object groups, dependencies, sizes, reusable prefix
boundaries and confirmed copy completion.

## Qualification sequence

1. Finish the current continuation flow, retaining its no-duplicate-effect and
   cleanup gates. Cache optimization must not become a prerequisite for it.
2. Check the pinned native save/restore path with the existing IQ3_S model and
   unchanged quality settings. Compare fresh prefill with save, full owned
   unload, reload and restore; verify the original task's actual artifact and
   effect ledger. Do not substitute another quantization or model.
3. Exercise missing, corrupt, truncated, stale and incompatible files, plus
   interruption during save/restore and renewed foreground pressure. Verify
   truthful fallback and retained ownership. Qualify reboot separately.
4. Record host bytes written/read, cache bytes retained, copy time, complete
   resume time, peak RAM/VRAM, foreground delay and task outcome. Measure
   NAND/device writes separately if reliable counters are available; do not
   equate host bytes with flash wear or infer the drive's endurance rating.
5. Compare re-prefill, bounded RAM retention, existing whole-session save and
   only then type-aware admission on the same workload. Predeclare capacity,
   I/O and quality budgets, include short sessions and sustained pressure,
   and keep the restored baseline control. An unchanged-quality regression
   outweighs a mapper-only or cache-hit-rate improvement.

No new cache algorithm, secondary model, SSD-writing service or upstream PR
update is enabled by this document. The implementation gap is the qualified
native/controller integration, not a missing general-purpose cache framework.
