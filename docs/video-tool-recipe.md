# Agent-requested GPU video recipe

An explicitly enabled agent task can ask for a small GPU video clip, receive
checked artifact facts in its saved conversation, and use those facts to finish
the task. The [public example](../examples/tasks/video-testclip/README.md) shows
how to select installed tools, enable the capability and submit the task.

The source connects this recipe to the existing task, resource handoff and
Hermes tool path. The [real IQ3_S foreground trial](../provenance/video-tool/physical-foreground-video-2026-11-02.json)
passed all 47 primary checks: foreground activity held admission closed through
model release; the tool then encoded, probed and decoded the clip; a restored
model consumed the saved result and completed the task. All owned processes
closed normally. The separate observer's shutdown connection errors remain
unresolved. The [first trial](../provenance/video-tool/physical-video-evidence-2026-11-02.json)
completed the useful work but missed the planned foreground action.

Separate [local checks](../provenance/video-tool/local-validation-2026-11-02.json),
[installed SDK evidence](../provenance/video-tool/installed-sdk-evidence-2026-11-02.json)
and [native component evidence](../provenance/video-tool/native-component-2026-11-02.json)
retain their own scope. The SDK gate used scripted provider replies and resource
observations; the physical trials used actual IQ3_S inference. No result here
qualifies H3, audio synchronization, sustained performance or reboot recovery.

## Task and agent connection

The `adaptive.task-spec.v3` contract opts into `nvenc-testclip.v1` and bounds the
number of operations. Setup accepts `--video-settings` with the two selected
executable paths, their SHA-256 values and an explicit environment. The first
increment enables one useful-tool family per deployment: video or compiler.
Existing file tasks remain available. Multi-tool-family workflows remain a
later integration step.

The registered `encode_and_check_video` tool passes only the fixed recipe ID
through the existing worker-to-host capability binding. The host saves the
original call identity and intent before requesting resources. It saves the
terminal result before the worker may request another model response. The
typed dispatcher selects compiler or video validation while retaining the
existing lifecycle owner and cleanup path.

Completion requires the stored successful operation, artifact and probe hashes,
exact media facts and confirmed child exits. Saved-task review verifies that
evidence again. A task cannot acquire video authority from its final answer or
from a file-only installation. Admission checks the deployment's capability
before reserving a video task; Stop uses the retained operation owner.

## Fixed operation and ownership

`desktop.video_recipe.VideoRecipe` prepares one host-approved recipe,
`nvenc-testclip.v1`. The agent selects that identifier; it cannot supply a shell,
command arguments, encoder, output filename, duration or input media. The host
provides SHA-256-pinned FFmpeg and FFprobe executables, an explicit environment,
and a fresh output directory. A consumed directory cannot be reused.

The recipe requests one `HandoffController` grant with the historical video
capacity requirements: 8 GiB available RAM, 12 GiB available commit and 6000 MiB
available VRAM. Its 90-second maximum includes waiting for the grant and is
clamped to the task's existing execution deadline. It does not extend a task.
The shared compiler recipe process owner supplies Windows Job Object ownership,
gated child creation, retained process handles, joined exits and bounded cleanup.
The default job commit cap is 2048 MiB. Native release, fresh resource checks and
restoration remain the existing controller's responsibility.

The three fixed commands preserve the earlier `protected_video` implementation
in [the Windows handoff validation runner](../examples/validation/windows_handoff/run_validation.py):

1. Encode `testsrc2` as a silent, three-second, 1280×720, 30-fps H.264 clip with
   `h264_nvenc`, `yuv420p` and overwrite refusal. There is no CPU encoder fallback.
2. Use FFprobe's frame-counting JSON output to require exactly one selected video
   stream with H.264, 1280×720 and 90 decoded frames.
3. Decode the clip to FFmpeg's null output. The command must exit zero and its
   error-level log must be empty.

The output name is fixed to `handoff-video.mp4`. Successful receipts use schema
`video-recipe.v1` and include the tool pins, original/effective deadline, stage
arguments and exit codes, artifact size and SHA-256, probe facts and log hashes,
owned child records and final job accounting. The artifact is bounded to 64 MiB;
probe output is bounded to 1 MiB. Tool errors, invalid media, interruption and
timeouts retain failed receipts. Cancellation propagates after cleanup. If exit
ownership cannot be confirmed, `RecipeCleanupError` retains the owner and receipt
and the controller keeps inference closed.

The host must persist tool intent before execution and the terminal receipt
before another model generation. Component tests use inert files and a simulated
process owner with the real handoff controller; they never run FFmpeg or a GPU.
They verify commands, output checks, one-grant ownership, the shared deadline,
interruption, cancellation and uncertain cleanup. These tests do not establish
physical NVENC operation, agent continuation, H3 quality, audio synchronization,
playback quality, reboot recovery or performance. Physical qualification must
retain its own exact executable, model, source and hardware identities.

## Safe worker restart and the next recovery boundary

The [installed restart gate](../provenance/video-tool/installed-worker-restart-2026-11-02.json)
verified that completed video work survives a cooperative worker stop. The
first worker stored the actual recipe result and native feedback before exiting;
the replacement worker continued the same task/session from that checkpoint.
It consumed the exact saved result without another video dispatch. A fresh owner
replaced the joined worker's retired binding, while the original deadline and
cumulative request count stayed intact. Independent review passed 58 checks.
Provider replies and resource observations were scripted in this SDK gate.

Unexpected worker loss before that checkpoint remains the next implementation
boundary. The existing recovery path refuses unresolved effects or feedback
awaiting a native flush. The planned extension will reconcile a retained exact
receipt through the existing native lease and operation journal, append missing
feedback once and keep ambiguous effects fenced. It must not repeat completed
work or grant a new time allowance. Active-tool interruption, actual-model
restart and computer restart need their own qualification.

This sequence uses the existing local recovery mechanisms. The design draws on
[Temporal's activity idempotency guidance](https://docs.temporal.io/activity-definition#idempotency)
and [LangGraph's saved-result and resumption guidance](https://docs.langchain.com/oss/python/langgraph/functional-api).
These references informed the checkpoint/reconciliation boundary; no framework
dependency, implementation copy or inherited exactly-once guarantee is claimed.
Their inspected source revisions and licenses are recorded in
[REFERENCES.bib](../REFERENCES.bib).

## Sources and licensing

The commands and media oracle reuse this repository's `protected_video` work;
process ownership reuses [compiler_recipe.py](../src/adaptive_inference/desktop/compiler_recipe.py)
without introducing a second process manager. Before implementation, the primary
vendor references were checked against the retained commands:

- [NVIDIA: Using FFmpeg with NVIDIA GPU Hardware Acceleration, SDK 13.1](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.1/ffmpeg-with-nvidia-gpu/index.html)
  documents `h264_nvenc`, the separate encode/decode engines and the need to match
  the FFmpeg/SDK build with a compatible driver. This recipe uses NVENC encoding;
  its decode check does not claim NVDEC use.
- [FFmpeg command reference](https://www.ffmpeg.org/ffmpeg-all.html) and
  [FFprobe reference](https://www.ffmpeg.org/ffprobe.html) document the filter,
  encoder, frame-counting, stream selection and JSON output options. The FFprobe
  page refresh timed out in the implementation session; no new flags were inferred
  from that failed fetch. The exact previously checked arguments were retained.
- [FFmpeg license](https://ffmpeg.org/doxygen/trunk/md_LICENSE.html): FFmpeg is
  principally LGPL 2.1-or-later; optional components/build configuration can change
  the applicable license. This component invokes separately installed binaries
  and does not copy or distribute FFmpeg/NVIDIA source or binaries. Distributors
  must retain the notices and obligations of their selected build.
