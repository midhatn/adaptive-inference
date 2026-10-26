# Hermes saved-conversation request rebuild

This optional component check verifies how explicit Continue rebuilds a provider
request from the saved conversation. It runs the pinned Hermes turn prologue,
chat-completions request builder and public LLM middleware with Adaptive
Inference's Recovery and AdmissionProvider, using real task and native-history
SQLite files.

The two checks establish that:

- The saved conversation prefix and original objective remain unchanged, one
  explicit Continue user turn is appended, and a new request reaches the
  scripted transport with the same model, tool scope and quality options. The
  declared cumulative request/attempt counts advance from one to two.
- Changing the saved native-history prefix is refused before the transport runs.
  The preserved pending-request evidence remains unchanged in both cases.

The external response is scripted **for the newly rebuilt request**. No saved
response is injected into a different request, and no old message is removed or
rewritten. The initial count of one is an explicit test seed, not a real model
call. The test creates no output artifact or physical file-write effect.

This is a source-mode component check. It does not instantiate the full AIAgent,
exercise its complete turn lease/watchdog, call an inference model, prove native
resource release, launch a GUI or qualify an installed worker. There is no
installed-mode option or installed-runtime fallback.

## Run it

Use a matching repository checkout or extracted source distribution, the existing
[Windows deployment profile](../../../docs/installed-desktop.md), and the exact
worker interpreter named in that profile. The profile supplies the local Hermes
source and dependency directories. Dependencies must already be available; this
check downloads, installs and launches nothing.

```powershell
& 'C:\path\to\worker\python.exe' -I -B 'C:\path\to\adaptive-inference\examples\validation\hermes_saved_history\check_sdk.py' --profile 'C:\path\to\deployment.json' --source-root 'C:\path\to\adaptive-inference' --output 'C:\evidence\fresh-saved-history'
```

The adjacent `source-manifest.json` is used by default. An explicit
`--source-manifest FILE` may select a separately reviewed successor manifest;
changing it changes the claimed source identity. The supplied manifest verifies
all 60 runtime modules and the existing `tests/test_desktop_report_feedback.py`
NativeDB support before imports. A different, missing or additional runtime
source file is refused. The result includes the exact manifest hash and relative
runtime source hashes, so it cannot be mistaken for an installed-wheel identity.

The SDK must match revision
`14e1e43a23761b369641208e204365cd6cb9399d`. The existing production map checks
21 interfaces, including `agent/turn_context.py`; the manifest additionally
checks the upstream test fixture before loading it. The interpreter, source
hashes and imported module origins are verified. Network connects and child
process launches are refused during the SDK component check.

The pinned IQ3_S configuration remains unchanged: model
`qwen3.8-flash-next-iq3_s-adaptive-media-beta`, maximum output 10,923 tokens, high
reasoning with an 8,192-token budget, and the existing quality options. The test
does not load that model or measure speed, resource use or answer quality.

Every invocation requires a fresh output directory. `tests.private.json` records
the result, source/SDK inputs, runtime identity, interpreter and exact scope;
`tests.private.log` records both cases. Keep unsuccessful output. Generated
evidence contains local paths and synthetic request/history data and should be
treated as private; none of it is required as a checked-in prerequisite.

## Reused SDK mechanism and license

The component uses the upstream `_FakeAgent` and `_build` boundary from
[Hermes turn-context tests](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/tests/agent/test_turn_context.py),
which calls the real
[saved-conversation prologue](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/agent/turn_context.py).
It then uses the actual
[chat-completions builder](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/agent/transports/chat_completions.py)
and [middleware](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/hermes_cli/middleware.py).
Hermes is Copyright (c) 2025 Nous Research and
[MIT licensed](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/LICENSE).
The fixture is loaded from the user's pinned checkout; its source and license
hashes are retained in the manifest rather than copying upstream code here.
This repository's runner is Apache-2.0 licensed.
