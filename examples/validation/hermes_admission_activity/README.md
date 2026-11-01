# Pinned Hermes admission activity components

This optional validation checks the real pinned Hermes activity writer, watchdog tick, awake-idle meter, lease abort-commit callback and interrupt publication against Adaptive Inference's admission-wait activity guard. It imports the extracted components, without importing `run_agent`, constructing `AIAgent`, starting a periodic scheduler, launching a model or opening a network connection.

The three cases use controlled clocks and the existing reduced, real-SQLite admission fixture:

1. A verified resource wait advances through the SDK's 600-second inactivity bound. The actual writer updates its generation/timestamp every 15 seconds. The original 900-second controller deadline stops further activity stamps; no provider or tool executes.
2. An otherwise identical silent turn reaches 600 seconds. The actual watchdog commits a hard interrupt and deactivates its lease component. The adaptive guard refuses to revive that authority.
3. A bounded contender thread is parked immediately after the real interrupt path reserves an abort claim. The original owner thread reports a verified wait, invalidating that claim. The contender joins without publishing an interrupt.

The first case checks the actual controller deadline boundary, not the full safe-expiry finalizer. The separate `tests/test_desktop_admission_activity.py` worker fixture covers that deterministic expiry path. Neither check establishes a live-agent or real-model recovery qualification.

Use the full worker interpreter and configured SDK/site-packages from an existing validated desktop profile. No dependency installation is performed. Every output directory must be new:

```powershell
& $WorkerPython -I -B examples/validation/hermes_admission_activity/check_sdk.py `
  --profile $DesktopProfile --mode source --output $FreshSourceOutput

& $WorkerPython -I -B examples/validation/hermes_admission_activity/check_sdk.py `
  --profile $DesktopProfile --mode installed --installed-identity $InstalledIdentity `
  --output $FreshInstalledOutput
```

Installed mode verifies a regular wheel installation, its RECORD and supplied identity. It does not add the checkout's `src` directory as a fallback. Both modes verify the interpreter, pinned SDK files, imported SDK module origins and canonical import root. All relevant sources and the output log are hashed in `tests.private.json`, with before/after equality checks. The receipt also records loaded Jiter and Ruamel YAML module origins, hashes and distribution versions separately from SDK source identity.

The fixture substitutes its existing SDK lease-row getter and unsupported durable SessionDB projection. The real writer follows its ordinary no-capability branch because this SQLite fixture has no `touch_session_activity` method. This is not a durable SessionDB heartbeat or lease-renewal test. The unrelated watchdog metrics sink is replaced with a recording sink, and stack dumping is suppressed. Sampling, activity-generation changes, abort commitment and interrupt publication remain actual pinned code. Each component's `time` object is replaced separately, following upstream; the shared Python time module is not modified.

No `start()`, `build_threads()` or `schedule()` method is called. The only contender thread has bounded release/join checks. An audit hook refuses network connect/bind and external process launch. Host sleep accounting, hardware elapsed time, native-engine release, installed task continuation and full cleanup qualification remain separate tests. `_touch_activity` is a pinned private SDK API already consumed by this adapter, not a public plugin contract.

## Sources and reuse

SDK revision: `14e1e43a23761b369641208e204365cd6cb9399d`. Exact source identities, imported module mapping and fixture inputs are in [sdk-references.json](sdk-references.json).

- The bootstrap and source/installed checks reuse this repository's [Hermes Pause dispatcher validation](../hermes_pause_dispatch/check_sdk.py).
- Controlled module clocks and the release-boundary lock fixture adapt the MIT-licensed [upstream watchdog tests](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/tests/agent/test_turn_liveness_watchdog.py): `test_host_sleep_is_not_a_stalled_turn`, `_ParkingReleaseLock`, and the tests for activity resuming during abort publication.
- The components are [ActivityTrackingMixin](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/agent/activity_tracking.py), [TurnLivenessWatchdog](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/agent/turn_liveness.py), [AwakeIdleMeter](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/agent/session_activity.py), [DurableTurnLease](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/agent/turn_facade_lease.py), and [InterruptControlMixin](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/agent/interrupt_control.py).
- [Hermes PR131916](https://github.com/NousResearch/hermes-agent/pull/131916) provides the analogous existing activity-reporting approach for MoA progress; its implementation is not copied here. A verified admission wait is labelled as waiting, not generated-token or tool progress.

The following notice applies to the adapted upstream test patterns:

```text
MIT License

Copyright (c) 2025 Nous Research

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
