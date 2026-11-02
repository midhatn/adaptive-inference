# Let Hermes hand resources to a compiler

Status: source, local package/installation and actual SDK/compiler feedback are
verified at the scopes below. Model-driven physical handoff remains open.
This is the first small useful-tool increment in
[M4](../PLAN.md#m4--let-the-agent-hand-resources-to-useful-tools); the separately
reboot installation remains fixed. The first physical restart preserved saved
work but expired before continuation; it does not qualify successful recovery.

The agent requests a prepared build and test operation, the controller makes
room for it, the compiler and tests finish under retained ownership, and their
result returns to the same conversation. The next IQ3_S request can proceed
only after confirmed resource release or a truthful failure. The original model,
context, quality, task allowance and consumed work remain unchanged.

## Reuse and scope

The existing `HandoffController.acquire_tool`, `ToolGrant.interruption` and
`complete_tool` supply the native resource boundary. The recipe reuses those
APIs, CMake and CTest, and the existing Windows child-launch and job mechanisms.
It does not add a scheduler or build system.

Trusted preparation supplies executable identities, a source manifest, build
destination, generator, parallelism, memory requirements and duration. The agent
selects the recipe and supplies bounded C++17 source. A trusted template owns
CMake, the test oracle and all output locations; the agent supplies no shell
command, build-system code or executable path. Configure,
build and test share the remaining original deadline. CTest's `--no-tests=error`
rejects an empty test set. Successful exit codes do not replace artifact and
test-result checks.

The complete compiler subtree belongs to its own retained Windows job, with
containment established before child execution. Interruption acts only on that
subtree; it must never kill the controller's job. The grant remains unavailable
for inference until owned exits are confirmed. Declared free-memory requirements
and an enforced job memory cap are different facts. Unknown cleanup remains
fenced rather than being reported as resource release.

The worker and controller are separate processes. A narrow recipe route on the
existing host HTTP application uses a distinct worker capability and binds the
selected task, durable operation and native tool-call identity. The host owns
the grant and compiler children. The worker uses the existing TaskStore effect
and native-history path. Repeated identical submission returns the same retained
operation/result; a disconnect does not authorize another build. GUI authority
remains separate, and no arbitrary shell endpoint is added.

The file-only route retains its existing capabilities and receipt contract.
Compiler binaries are recipe artifacts, not fictitious `write_file` outputs.
Known compiler errors become durable feedback the agent can use; uncertain
dispatch or cleanup must not be automatically replayed.

## First real compiler finding

The first bounded MSVC experiment configured the project successfully in 2.2
seconds, but an owned `MSPDBSRV.EXE` descendant remained after CMake exited.
The original 90-second recipe allowance expired; cleanup then confirmed the
entire job empty. The attempt failed before build/test, and its intentionally
broken-source case was never reached. It remains a failed attempt.

The retained compiler-probe command used `/Zi /FS` and debug linking even though
the outer build selected Release. Microsoft's [/FS documentation](https://learn.microsoft.com/en-us/cpp/build/reference/fs-force-synchronous-pdb-writes?view=msvc-170)
identifies the PDB service used by those options. The fixed recipe therefore
uses CMake's documented [Embedded debug-information selection](https://cmake.org/cmake/help/latest/variable/CMAKE_MSVC_DEBUG_INFORMATION_FORMAT.html),
[CMP0141 NEW policy](https://cmake.org/cmake/help/latest/policy/CMP0141.html), and
[Release compiler-probe configuration](https://cmake.org/cmake/help/latest/variable/CMAKE_TRY_COMPILE_CONFIGURATION.html).
The [MSVC-Wine project's existing explanation](https://github.com/mstorsjo/msvc-wine/blob/master/README.md#does-it-work-with-cmake)
also describes this Release-versus-probe distinction. This reuses documented
configuration; it neither extends the deadline nor treats a still-running
descendant as released. The next attempt removed that PDB helper, but an owned
VCTIP helper remained until the same limit. That attempt also failed.

The [retained component record](../provenance/compiler/component-validation-2026-11-02.json)
then qualifies the existing LLVM `clang-cl`/`lld-link` route with the same MSVC
headers/libraries. After fixing CMake's Windows path serialization, actual
configure/build/CTest completed in 5.404 seconds, producing a checked executable
and `units=17`. All three stage children exited normally and the owned job was
empty. The original private checker still failed because it expected LF in an
exit-code record that contained CRLF. Independent closed review accepted the
actual recipe result without replaying it; the original overall failure remains.
A separate deliberately broken source then produced a checked compilation error,
no CTest run or executable, and normal owned cleanup in 2.457 seconds.

These were real compiler processes with scripted resource/foreground inputs.
They do not establish agent dispatch, actual model release or desktop performance.
The newer agent-facing template uses exact stdout bytes and an exit record
without a newline. Its [separate actual native run](../provenance/compiler/template-native-validation-2026-11-02.json)
passed configure/build/CTest, produced exactly `23 units`, and verified the
production receipt projection and artifacts. All compiler children joined and
the owned job was empty. Resource and foreground samples remained scripted;
another test suite ran concurrently, so no performance comparison is claimed.
The [local validation](../provenance/compiler/local-validation-2026-11-02.json)
separately passed 1,499 core tests, all provenance checks, the remaining workflow
gates, package verification and fresh installation.

The [installed SDK evidence](../provenance/compiler/installed-sdk-evidence-2026-11-02.json)
then verified three scripted provider requests with real Hermes dispatch: invalid
source, the persisted compiler error, corrected source, persisted CTest success,
and final completion. Both compiler operations and the worker finished within
the original task. An independent 54-check closed audit verified their original
operations, exact feedback, artifact and normal process joins without replay.

The original full harness still exited 1 at its final whole-tree comparison.
Its readonly native-history reader could create SQLite WAL sidecars. A copied
database experiment reproduced the exact empty WAL and shared-memory bytes while
preserving the database and logical history; the original before/after inventory
was not retained, so its complete historical delta cannot be reconstructed.
This separates the accepted workflow evidence from that failed checker. Use
verified closed copies for immutable audit reads; never mark a live database
immutable or discard a nonempty WAL. See [SQLite's readonly WAL documentation](https://sqlite.org/wal.html#read_only_databases).
The next physical gate uses unchanged IQ3_S and real foreground activity.

## Authorization and Stop

At inspected Hermes revision `b7ab3f7d85448e3a586510a4d6844b745f563ce7`, general
`tool_execution` middleware surrounds `_authorized_dispatch`, which then performs
scope, hooks and guardrail checks. Resource acquisition therefore belongs inside
the registered tool handler after authorization reaches it. Middleware entry
alone is insufficient. An adapter-owned call binding carries the verified
native call ID to the generic handler without changing Hermes internals.

The existing recovery safe point refuses an inflight effect. Result polling
must not bypass that rule. Host Stop or worker death first interrupts and joins
the retained recipe. A known terminal receipt can then complete the effect and
reach the normal native-history flush; unknown cleanup continues to block work.

## Acceptance sequence

Use the [public compiler task and setup instructions](../examples/tasks/compiler-stdout/README.md)
to prepare a local compiler-enabled profile with the ordinary setup helper's
optional `--compiler-settings` argument. Its [nine focused checks and actual setup generation](../provenance/compiler/setup-validation-2026-11-02.json)
passed without launching a task. Default file-only setup remains unchanged.

The source integration uses an optional `compiler` deployment entry with schema
`adaptive.compiler-settings.v1`. It supplies pinned `cmake`, `ctest`, `compiler`,
`ninja` and `linker` paths/hashes plus an explicit build environment. This first
recipe uses the configured `clang-cl.exe`/`lld-link.exe` pair, two requested build
jobs, a 2,048 MiB job committed-memory limit and a 90-second recipe cap within
the original task deadline. These settings are host inputs, never model tool
arguments. File-only profiles expose no build capability.

The selected worker receives a private launch binding; a distinct HTTP
capability does not enter the prompt or tool schema. The host verifies the
already durable native call and source before preparing an operation. Known
compiler failures become task feedback. Completed receipt verification reuses
the original TaskStore operation history and artifacts, including after an
explicit continuation; it does not rerun a build to reconstruct proof.

The host's native-history reader reuses Hermes' public readonly `SessionDB`.
Hermes import/setup requires its installed dependencies and can initialize
configuration files. The dedicated host therefore supplies an explicit fresh
SDK home inside its application run; saved task databases are opened readonly.
The SDK dependency check, component fixtures and real compiler measurements
remain distinct evidence from an installed, agent-driven build.

Review corrected two ordinary-path integration gaps: the serialized provider
request audit must accept the opted-in compiler tool, and continuation must
include its completed effect receipts. Source checks exercise both. Stop also
joins compiler operations before the worker and native host; failure cleanup
retains the same obligations. The installed SDK/compiler feedback path is now
verified by the separate closed audit above; its original full-harness failure
remains recorded. Stop during compilation and explicit continuation still have
source-level evidence, while IQ3_S physical handoff remains open.

1. Check fixed commands, input identity, the original deadline, real retained
   subtree ownership and failure/interruption cleanup with focused tests.
2. Connect actual pinned SDK dispatch to a real bounded compile and test,
   durable feedback and the following provider request. Scripted responses are
   sufficient for this integration gate, not model reasoning.
3. Qualify an IQ3_S task with unchanged quality and a real compiler artifact,
   including foreground interruption and normal restoration. Preserve failed
   attempts; only the later physical run qualifies installed model handoff.

The autonomous media workflow retains its separate latest-version, individual
engine tuning, unattended baseline, co-optimization and quality requirements.
This compiler increment does not waive them or complete M4.

## Sources inspected before implementation

- [Hermes registration](https://github.com/NousResearch/hermes-agent/blob/b7ab3f7d85448e3a586510a4d6844b745f563ce7/hermes_cli/plugins.py#L463),
  [authorization order](https://github.com/NousResearch/hermes-agent/blob/b7ab3f7d85448e3a586510a4d6844b745f563ce7/agent/tool_executor.py#L689),
  [registry](https://github.com/NousResearch/hermes-agent/blob/b7ab3f7d85448e3a586510a4d6844b745f563ce7/tools/registry.py),
  and [pinned dispatcher](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/model_tools.py):
  MIT APIs and source behavior; existing attribution remains. Research does not
  silently upgrade the installed SDK.
- The installed revision's [plugin registration](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/hermes_cli/plugins.py)
  and [readonly session storage](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/hermes_state.py)
  supply the actual consumer interfaces. The source integration calls these
  APIs; no separate native-history format or SDK implementation is copied.
- [CMake CLI](https://cmake.org/cmake/help/latest/manual/cmake.1.html) and
  [CTest CLI](https://cmake.org/cmake/help/latest/manual/ctest.1.html): configure,
  build, parallelism, timeouts and test reports. No build-system implementation
  is copied. Local CMake/CTest 4.4.3 inventory is not a successful build or a
  claim that the entire participating stack is newest.
- [Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects):
  existing containment and retained-handle pattern; actual validation must prove
  resource limits and complete subtree exit.
- [aiohttp routing](https://docs.aiohttp.org/en/stable/web_quickstart.html#handler)
  and [retained Python tasks](https://docs.python.org/3.11/library/asyncio-task.html#shielding-from-cancellation):
  use the existing listener while keeping host operations independent of a
  single HTTP caller's lifetime.
- [Hermes advanced delegation](https://hermes-agent.nousresearch.com/docs/plugins/advanced-delegation):
  model/profile selection for later use; it does not provide hardware grants.

Research date: 1 November 2026. These sources support the integration design,
not a passed end-to-end compiler or physical-resource test.
