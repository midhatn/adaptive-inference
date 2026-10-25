# Installed command-retention acceptance

The retained-command successor passed separate installed cold and full trials
on the qualified Windows reference deployment. One Pause click and one Stop
click worked in the cold trial. In the full trial, each Resume used one click,
the agent completed the correct IQ3_S report across a controlled worker restart,
and one Stop click initiated normal shutdown.

The [selected result](result.json) and [file manifest](manifest.json) bind this
evidence to wheel SHA-256
`17fd683bb43e60d91851e1e6efce315cfa04627e50d2b8816e45afbac5c69fbb`
and client SHA-256
`2cb2fb52bbf8bc420d6030b1753c0494552b6e73c60aa9b32d9ed415103711d5`.
Exactly 51 other runtime Python modules match the previous installed package.
The original [source-successor record](../README.md) preserves that comparison.

| Evidence | Observed result | Scope |
| --- | --- | --- |
| Targeted software review | 168 distinct Python 3.11 checks, including the 165-check GUI subset and three independent edge cases; 13 Python 3.12 source checks | Deterministic fixtures and retained worker-thread ordering; no model or GUI benchmark |
| Actual installation | 252 host and 305 worker predicates; identical 52-module package contents | Regular installed packages and direct full interpreters |
| Cold trial | One Pause click acknowledged; one Stop click; zero model calls, native launches, or file effects; task remains paused and unfinished | 38 independent checks; normal retained-parent exit and owned cleanup |
| Full trial | Three IQ3_S provider calls, one correct report write, two acknowledged GUI Resumes, controlled worker replacement, and one Stop click | 50 independent checks of task/native databases, source identity, complete ledgers, process exits and cleanup |

The cold task ledger contains three Pause commands: initial setup, the genuine
GUI Pause, and the service's Stop protocol. It does not represent three manual
clicks. The full trial kept the same GUI window across worker replacement.
Its first native-owner generation retained eight child processes and its
second retained seven; all exited. This record preserves that actual eight-plus-
seven count instead of copying the prior trial's seven-plus-seven count.

The report contains four rows, 17 units, and 4,350 cents, with the unchanged
per-item oracle. The full run had no report-validation rejection, so it does
not claim observed real-model correction. The original task deadline and safe
checkpoint survived the retained worker replacement. Task quality, the
eight-request limit, original 900-second task deadline, 240-second readiness
bound, and 1,800-second external guard remain unchanged.

## What these results establish

The software fixtures prove that an eligible command can wait locally behind
an outstanding status request, then dispatch exactly once after its result is
consumed and cleanup/eligibility are checked. The real trials separately prove
the observed single clicks, acknowledgements, original task completion/restart,
and normal owned shutdown for this installation.

Neither real trial observed the locally waiting message or established that a
physical click overlapped a status exchange. These observations therefore do
not replace the deterministic ordering tests or establish universal input
reliability. The cold successor trial did not repeat minimize/restore. No
performance improvement is claimed: elapsed trial time includes manual input
and is not a comparable benchmark.

The cold API observer had 49 samples with 46 valid responses; the full observer
had 418 samples with 415 valid responses. Both ended after three request errors.
Those observations remain **inconclusive** about cleanup. The independent
terminal audits, retained process exits, joined handles and lifecycle receipts
supply the cleanup proof.

The [historical installed acceptance](../../installed-desktop/acceptance/README.md)
and its exporter remain unchanged. That earlier full trial still records a
missed first Stop click followed by a successful second click. This successor
record applies to the newly identified client and wheel; it does not relabel
the earlier run.

## Selection and reproduction

`export_acceptance.py` reads an explicit private selection of terminal receipts
and writes a fresh output directory. It pins the independent source/package,
actual installation, cold and full audits; checks their result/UI bindings;
and selects only explicit fields. It reuses the unchanged historical strict
JSON reader, type/hash checks, policy-summary selector and privacy checker.
It does not modify the old exporter's wheel, qualifier, case, or missed-click
gates, and it does not execute models, services, GUI automation or databases.

Nineteen selector mutation tests reject changed wheel/receipt pins, source
modules, click counts, task quality, report/effect counts, restart identities,
incomplete audits and failed cleanup. They also preserve the observer's limited
scope and exclude private unknown fields. Run them without private trial data:

```text
python provenance/desktop-control-intent/acceptance/test_export_acceptance.py
```

The public result excludes private paths, prompts, conversation contents,
process/window IDs, coordinates and raw API traces. The private selection and
raw receipts are not committed. Their hashes remain in the selected record so
an authorized reviewer with those inputs can reproduce the export. Software
source and fixtures are included in this repository; reproducing the real trial
also requires the separately supplied model/runtime assets and explicit
deployment profile described in [the installed desktop guide](../../../docs/installed-desktop.md).

This remains one bounded Windows/reference-task qualification. It does not
establish reboot survival, arbitrary task support, game responsiveness, or
all-agent deployment. The [behavior and primary Tk references](../../../docs/desktop-control-intent.md)
explain the client change and its limits.
