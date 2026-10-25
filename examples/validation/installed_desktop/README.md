# Installed desktop qualification

This validation script consumes the ordinary installed `adaptive-inference` package. It uses the same `DesktopComposition` as the product, with the accepted cold and full task scenarios added through its lifecycle seams. It contains no alternative host, native owner, or GUI implementation.

The first supported deployment is the explicit Windows orders-report profile documented in [installed desktop](../../../docs/installed-desktop.md). The host and GUI use the same full CPython 3.11.9 installation; the worker uses the exact full interpreter, Hermes source/dependencies, native-owner package and hashes in that profile. A virtual-environment redirector is not a substitute for the retained GUI process identity.

Run from outside the source tree with that interpreter and a fresh evidence directory. Use an absolute path to this validation script and the reviewed profile:

```powershell
& 'C:\path\to\full-python\python.exe' -I -B 'C:\path\to\installed_desktop\qualify.py' --case cold --profile 'C:\path\to\deployment.json' --run 'D:\evidence\fresh-cold-case'
& 'C:\path\to\full-python\python.exe' -I -B 'C:\path\to\installed_desktop\qualify.py' --case full --profile 'C:\path\to\deployment.json' --run 'D:\evidence\fresh-full-case'
```

A separate retained parent must verify the source-manifest hash before starting, enforce the 1800-second qualification lifetime, retain the child and all logs, and confirm normal exit zero after event-loop/interpreter teardown. Exit 124 is emergency failure. A result file alone does not prove the parent observed normal process exit. The package/profile/source identity must remain unchanged throughout the trial.

For `cold`, use the actual GUI Pause button, observe its owner acknowledgement, and then use Stop engine. Do not Resume. The terminal gate checks zero provider requests, zero dispatched file effects, no native model launch, unchanged original task/quality/deadline, owner release and complete child/control/native cleanup. Clicking X minimizes to the taskbar; taskbar restoration must use the same window and binding. It does not stop the engine or count as a Stop action.

For `full`, use the actual GUI Resume button. After the valid report is durably checkpointed, the scenario pauses and deliberately kills only its exact retained first worker at that verified safe boundary. This is a test injection, not product Stop. Wait for the replacement-ready phase, Resume through the same GUI again, and use Stop after task completion. The original single-write/report oracle, native history, exact IQ3_S model and quality, eight-request limit, immutable 900-second task deadline, 240-second readiness bound and retained cleanup gates are preserved. The full scenario enables the existing qualification report hold; ordinary product sessions do not enable it.

`source-lineage.json` carries predecessor source hashes, the declared integration changes and normalized method digests. `source-manifest.json` pins the complete adjacent validation material. These are local content evidence and do not depend on a private predecessor checkout remaining available. The product package independently verifies its ordinary installed distribution and deployment contents.

The fixture tests use real SQLite task/mailbox state and fake lifecycle objects. Run `python -m unittest discover -s tests -p test_installed_desktop_qualification.py -v` from the repository test environment, or the equivalent regular-installed-wheel test environment. Fixture success does not qualify live Tk behavior, installed native integration, or model output; those require the cold/full trials and external parent evidence.

The packaging adaptation follows the official [Python isolated mode](https://docs.python.org/3.11/using/cmdline.html#cmdoption-I), [module execution](https://docs.python.org/3.11/using/cmdline.html#cmdoption-m), and [installed package RECORD specification](https://packaging.python.org/en/latest/specifications/recording-installed-packages/).
