# Adaptive-Hermes-Media-Autonomous Test

**Status: planned qualification for the canonical implementation; not passed.**

This is the named end-to-end media workload for roadmap M4. The capabilities
needed to run it are being qualified through smaller M2/M3 tests. M6 later
combines it with measured foreground activity and lifecycle recovery. A file-task
test or a supervisor-triggered video encode does not pass this autonomous test.

The scenario carries forward the retained 17 October 2026 desktop media test.
The requirements below are a self-contained specification. Historical scripts,
paths, receipts and successes must not be treated as qualification of the current
canonical package; adapters, source identities and hardware prerequisites need
fresh verification before execution.

## What the user should receive

A locally generated, playable racing-car video: a red and a blue car on a closed
circuit in daylight, with a coherent tracking shot, believable movement, tires
and shadows, and engine/tire sound. Avoid people, logos, captions, crashes,
changing car identities and slideshow-like motion. Retain the reference image,
video, sampled frames, diagnostics and concise final report.

## Fixed model and quality requirements

| Component | Required baseline |
| --- | --- |
| Hermes supervisor and workers | Existing IQ3_S LLM, 64K context capacity, high reasoning, experimental speed projection disabled; one inference server and at most one delegated worker running at a time |
| Supervisor visual review | Actual image pixels through the supported Strata vision path, with the retained CPU-vision baseline; no unsupported raw video input |
| Reference image | Genuine Unsloth Qwen Image 2.1 Turbo Q8_0, from this attempt, using the approved isolated adapter; 1024 × 576, eight official sigma intervals, Euler sampler and CFG 1 |
| Video | MiniMax-H3 Ref2VA Q8, 960 × 544, 141 frames at 24 fps (about 5.9 seconds), 20 steps and native audio |
| Creative choices | Hermes chooses and records the prompts and fixed seeds, within the required model/workflow baseline |

Q8 describes the diffusion weights, not every support component. The retained
image encoder is INT8 with a BF16 VAE; H3 uses the Q4_K_M text encoder, INT8 video
VAE and FP32 audio VAE. Preserve those exact support assets and identities. The
retained Comfy memory reserves are 1.0 GiB for image generation and 0.5 GiB for
video generation; these are distinct from the actual free-memory admission checks.

The later task and media instructions require Turbo Q8_0. An older generic
checklist allowed Hermes to choose a quantization. For this named baseline,
Hermes assesses whether the required Q8_0 bundle fits and explains its decision;
it must not substitute a smaller quantization to obtain a pass. Autonomous
quantization selection is a separately named future variant. FP16 experiments
or a changed driver configuration are also separate from this quality baseline.

## Autonomous execution and resource handoff

1. Hermes owns the plan, delegation, prompts, asset preparation, reference
   selection, visual review, corrections and final report. Codex prepares and
   validates generic infrastructure beforehand, observes the run and independently
   reviews its outcome. During an attempt, Codex does not supply missing prompts,
   fabricated tool results, a manually generated image or step-by-step repairs.
2. While Strata can still reason, Hermes obtains a fresh forecast of resources
   available after yielding. It initiates the pinned CPU-only preparation of the
   required image bundle and retains this attempt's preparation receipt. Hash the
   complete bundle. Any reused compatible support weights must be identified as
   cached, rather than reported as a new Hermes download.
3. The supervisor authorizes the protected media workload before delegation.
   A worker cannot grant itself resources or inspect broker credentials. Before
   GPU loading, the host verifies release of its native inference and vision
   processes and keeps inference suspended. There is one cooperating GPU owner.
4. A forecast is not a reservation. Recheck actual RAM, commit and usable CUDA
   capacity after yielding and before loading. The historical initial envelope
   is twice the stored bundle bytes plus 7 GiB for both available RAM and commit,
   and 6,500 MiB available GPU memory. Revalidate its applicability before a new
   run; do not silently change it during an attempt.
5. The image worker runs the protected tool synchronously, waits for completion,
   and returns only after the host confirms that its owned media processes have
   exited. The protected tool must not call back into the model whose resources
   it holds. Inference can resume only after verified release.
6. Hermes reviews the actual reference image through vision. An unsuitable image
   must be corrected within the attempt allowance before video generation.
7. The video worker uses that same accepted image and its exact identity. Its H3
   prompt explicitly associates both cars with the reference and describes one
   coherent shot and the required sound. Preserve `subject_definitions`, a
   `summary` starting with `[reference generation]`, `retention_analysis`,
   `detailed_description`, `overall_soundscape` and `non_diegetic_music`.
   It follows the same grant, release,
   completion and verified-cleanup sequence.
8. Once the video worker has released its resources, Hermes reviews the complete
   contact sheet or all six sampled frames. Independent decoding checks every
   video frame and the audio stream. Technical checks, audible-content review and
   visible motion/identity review are separate requirements. D3 is an
   uncalibrated diagnostic, not proof of realism; keyframes cannot establish all
   motion quality.

Declare a supported listening/audio-review method in the fresh preflight. Audio
decoding and level measurements do not establish engine/tire sound content, and
image vision cannot substitute for listening. If that check is unavailable, keep
semantic audio acceptance incomplete rather than inventing a result.

Sampling should retain the historical operating floors of at least 3 GiB
available RAM and 250 MiB actual CUDA-free memory where measurable. Record
unobserved loading/transient windows and distinguish CUDA free memory, WDDM
budget, global device measurements and reclaimable allocator memory. These
observations are not a universal no-OOM guarantee. The historical inference-return
allowance is 256 MiB; that is a distinct mechanism from the 250 MiB sampled floor.

## Bounds, recovery and evidence

- At most two image attempts, two video attempts and four delegated workers in
  total, including retries. Workers run sequentially. The complete session has
  a four-hour limit; the protected long-running tool uses the predeclared timeout
  contract (5,700-second protected stage bound inside the 6,000-second Hermes
  terminal timeout in the retained implementation).
- Ordinary errors and poor prompts may be corrected autonomously within those
  bounds. An uncertain tool outcome must be reconciled before retrying. Do not
  repeat a possibly completed render because its response or receipt was lost.
- Work is local, in an isolated attempt directory on the designated data drive.
  No cloud inference, paid services, changes to ordinary installations, or
  replacement/deletion of existing outputs. Retain earlier unsuccessful attempts.
- Preflight must validate exact executable/source/model/profile identities,
  compatible nodes and weights, adapter failure paths, retained-child cleanup,
  long-job time limits and absence of a conflicting owner on selected ports.
- Pass requires useful real outputs, independently verified decoding and hashes,
  actual authorization and worker lineage, every owned process/job accounted for,
  verified release before inference returns, and honest semantic review. An exit
  code, generated file, model success statement or green component suite alone
  is insufficient. Unexpected approval halts, unknown cleanup or hidden failures
  prevent an unattended pass.
- The final response and report are each at most 800 words. Link the reference,
  playable video, frames, diagnostics, generation/cleanup receipts and resource
  decision. Include attempts, defects and measured times. Distinguish render time,
  complete stage time, release/reload and whole-session duration; do not add
  overlapping intervals. Use existing host integrity receipts without redundant
  rerendering, rehashing or process scans solely to repeat a verified fact.

## Relationship to the always-on goal

This baseline qualifies autonomous media handoff and completion on the declared
machine and versions. It does not by itself qualify browsing/gaming coexistence,
crash recovery or computer reboot. Successor variants must deliberately introduce
real foreground activity (M3) and separately specified interruption/restart points
(M5), preserve completed effects and finish the original media objective. Their
responsiveness and recovery budgets must be declared before running them. The
combined M6 gate requires those results, not an inference from a quiet media run.

The present M2 inventory/welcome trial is a prerequisite for durable ordinary
task use; its 15-minute example-task budget is not this media test's four-hour
budget. Neither budget is extended retroactively to rescue a failed run.

## Retained requirement identities

This specification was reconciled against the following files from the retained
`Adaptive-Media-Autonomous-Desktop-20261017-visible01` attempt. They identify the
historical requirements; these hashes are not new execution evidence. Private
paths and full operator prompts are not needed to understand the contract above.

| Retained file | SHA-256 |
| --- | --- |
| ACCEPTANCE-PLAN.txt | `2322ad5b33aa40451854f514034313df6a1d773fb7e7f766284ff06087f76946` |
| RACING-CARS-TASK.txt | `5dd2a54d67ed8038af2619bdd9e324d02ebe7b2f312657b9d815eeb2c305243a` |
| SESSION-INSTRUCTIONS.txt | `358e0ae5139c2c22d453cb230c80a2201bb035c8fd84fbbadee27f2be6396ab1` |
| MEDIA-INSTRUCTIONS.txt | `1764ef77eff1f01e7bca67bfd0af7d94c3d03e3b8bbb74dc1b765029e0549a0b` |
| image-workflow.json | `b00a9c91922f49b1aa080eb463689761ae9b7fcc838576a8677debf83ab45e13` |
| video-workflow.json | `d355d00eb272e63269e60728462f04fac2e96cfcbd22957fcdc89ad261fe5899` |

See also the [M4/M6 roadmap](../PLAN.md), [task-survival contract](task-survival.md)
and [evidence ledger](evidence.md). No historical media implementation was copied
or activated by adding this requirements document.
