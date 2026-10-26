# Hermes Pause and tool-thread dispatch regression

This optional check executes the pinned Hermes sequential dispatcher, daemon
worker pool, context propagation and interruption registry against the real
Adaptive Inference recovery middleware. It verifies a read and exactly one report
write, a tool timeout while its callback remains active, and refusal of concurrent
cleanup or expiry sealing. Every captured fixture future and thread is joined.

It uses a real TaskStore and a reduced SQLite native-history fixture. It does not
construct a full agent, call a model, open a GUI or start a native backend. These
checks cannot establish complete installed-agent or paused-expiry qualification.

Use a checkout or extracted source distribution, the existing
[Windows deployment profile](../../../docs/installed-desktop.md), and its exact
worker interpreter. The profile supplies the Hermes source and dependency
directories; the check verifies the interpreter hash, existing SDK source pins,
the additional dispatch references and imported origins. Dependency setup is the
same as the documented installed worker. No dependency or SDK is downloaded here.

For explicit source-checkout validation:

```powershell
& 'C:\path\to\worker\python.exe' -I -B 'C:\path\to\adaptive-inference\examples\validation\hermes_pause_dispatch\check_sdk.py' --mode source --profile 'C:\path\to\deployment.json' --output 'D:\evidence\fresh-sdk-source'
```

For a regular installed wheel, save its expected `package_identity()` result from
the existing deployment audit and supply that JSON file:

```powershell
& 'C:\path\to\worker\python.exe' -I -B 'C:\path\to\adaptive-inference\examples\validation\hermes_pause_dispatch\check_sdk.py' --mode installed --profile 'C:\path\to\deployment.json' --installed-identity 'D:\evidence\expected-package-identity.json' --output 'D:\evidence\fresh-sdk-installed'
```

Installed mode has no source-runtime fallback. It verifies the complete ordinary
installed package and its imported origins before and after the checks. The
existing repository test helpers are loaded explicitly in both modes; their
source hashes, the complete runtime, script, profile and SDK references accompany
the result. Treat the generated output as private because it contains local paths.
Use a fresh output directory for each invocation and retain unsuccessful results.

The fixture reuses the event-synchronized submit technique from the MIT-licensed
[Hermes timeout tests](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/tests/agent/test_sequential_tool_timeout.py).
Its test-only timeout starts after the callback reaches the intended blocked
safe point. The actual executor, context transfer, interrupt registry and timeout
branch remain in use. The innermost middleware hook forwards into the production
Recovery tool method; model dispatch and UI policy hooks are outside this test.
Source attribution and exact references are in the
[thread-successor provenance](../../../provenance/paused-budget-expiry/thread-successor/README.md).
