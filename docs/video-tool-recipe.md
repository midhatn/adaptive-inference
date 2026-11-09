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

### Completed-result feedback repair

The explicit `run_recovery reconcile` path now recognizes a completed compiler
or video receipt when the worker disappeared before its native feedback was
flushed. The repair verifies the selected task, original completed operation,
deadline, native call and actual artifact. It acquires the existing Hermes native
turn lease and appends the exact missing result before saving a ready checkpoint.
If the result was already appended, a retry verifies and reuses it. Conflicting
messages, changed artifacts and live native ownership remain refused. This
completed-result route requires a durable completed operation; the separate
pending-result route below uses the host's retained evidence. Ordinary file
reconciliation retains its existing route.

The command requires the original task directory, exact saved receipt and
operation ID. It does not execute the tool, call a model, change task/request
allowances or start a replacement worker itself. The coordinator must first
join and retire the old worker's retained owner, then use ordinary startup after
repair. Automatic desktop recovery remains a later integration gate.

Ten new component tests, 49 related tests and the complete 1,557-test local core
suite passed. The component fixtures use real task storage and SQLite-backed
native history, inert tool outputs and simulated lease/append methods. A fresh
installed SDK trial now completed actual worker loss, ordinary native-lease
recovery, feedback repair and replacement under the same task/deadline. One
real video effect and two scripted provider requests were retained. Independent
closed review passed 99 checks, with 74 original files unchanged. The
[installed result](../provenance/recipe-reconciliation/installed-worker-loss-2026-11-02.json)
also preserves the first failed private checker and the correction to reuse the
pinned SDK's read-only conversation projection. This is not an actual-model or
automatic-host recovery claim.
Active-tool interruption, actual-model restart and computer restart still need
their own qualification.

This sequence uses the existing local recovery mechanisms. The design draws on
[Temporal's activity idempotency guidance](https://docs.temporal.io/activity-definition#idempotency)
and [LangGraph's saved-result and resumption guidance](https://docs.langchain.com/oss/python/langgraph/functional-api).
These references informed the checkpoint/reconciliation boundary; no framework
dependency, implementation copy or inherited exactly-once guarantee is claimed.
Their inspected source revisions and licenses are recorded in
[REFERENCES.bib](../REFERENCES.bib).

### Pending operation with a verified host result

The next increment handles an earlier worker-loss boundary: the tool host has
finished and joined its tool processes, but the worker disappeared before
recording the result. `CompilerHost.terminal_receipt(operation_id)` exports the
same canonical receipt used by normal completion. It is a host-only read and
requires the original worker to have joined. The coordinator must obtain this
receipt before stopping the mailbox runtime or retiring the host binding.

The existing explicit reconciliation command checks that receipt against the
original pending operation, authorized native call, deadline and actual output.
It repairs the effect journal and native feedback once, then records
`operation_reconciled` with resolution `completed`. If recovery itself stops
after an append, retry recognizes the exact existing record. It never dispatches
the tool again, renews the task allowance or treats an unknown outcome as success.

This path has passed 104 distinct component tests (including 15 new tests),
independent source/evidence review, 24 source-preservation checks, and the complete
[1,578-test local core suite](../provenance/pending-tool-recovery/local-validation-2026-11-02.json)
plus 16 remaining workflow commands, 1,403-file/77-module package verification and
a fresh isolated installation. The [installed SDK pending-effect trial](../provenance/pending-tool-recovery/installed-worker-loss-2026-11-02.json)
then passed an independent 99-check closed review with 74 original case files
unchanged: a worker exited with code 86 after the host finished one actual video
operation and before recording completion in the task journal; the coordinator
exported `CompilerHost.terminal_receipt`, retired the old binding, ran ordinary
reconciliation to repair both the effect journal and native feedback, and
completed the task with a replacement worker under the original 900-second
allowance. Automatic desktop recovery, loss of the host, interruption during a
running tool and unchanged-IQ3_S recovery remain separate gates. The
host-reporting pattern also draws on
[Temporal's asynchronous activity completion](https://docs.temporal.io/develop/python/activities/asynchronous-activity);
it is implemented through the existing local task journal and host ownership.

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
