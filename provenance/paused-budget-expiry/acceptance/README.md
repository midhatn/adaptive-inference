# Accepted installed Pause-budget expiry

The third installed trial passed independent acceptance. After one genuine Resume
and one genuine Pause, the original 900-second execution budget expired. The
application saved an expiry seal without changing the agent's pending task or
native conversation history, released the inference process, kept its status
service available, and closed cleanly after one genuine Stop. The task remains
**pending and paused**, not completed. Continuing it after expiry is a separate
milestone requiring an explicit new budget decision.

The [selected result](result.json) records two real IQ3_S requests, one correct
report write, zero report-validation rejections, and task revision 26 to 27 for
the seal only. The same GUI stayed available. Fifty-five complete status requests
were observed between verified expiry and Stop. All five retained native children
exited, the native server and GUI exited normally, the worker exited with the
documented paused-expiry code 5, and the listener/transport closed. The independent
terminal audit has 46 passing predicates. The external observer's three final
connection errors remain inconclusive about cleanup; retained lifecycle evidence
supplies the cleanup result.

This is bounded Windows installed-agent evidence with the unchanged IQ3_S model
and quality settings. It is not a task-completion, automatic deadline-renewal,
reboot recovery, gaming/video overlap, performance or complete M2 claim. The
969.453-second supervisor duration is a qualification observation, not a speed
measurement. The task/request/readiness/outer limits remain 900 seconds, 8
requests, 240 seconds and 1800 seconds.

## Exact source and evidence boundary

The reviewed wheel is
`b28aeb0b09db16d38a8ab9a9af3ed6467fc33181f45caca92bda5fa722660f80`.
Its 54 runtime files match both installed interpreters and the reviewed source.
The thread repair changes five modules and preserves 49; its predecessor and the
earlier clock repair remain in the adjacent provenance records. The successful
result does not reclassify either earlier installed trial:

- Trial 01 failed because host and worker monotonic timestamps used different
  Windows clock domains. Two model requests and one write did not make that
  rejected expiry proof acceptable.
- Trial 02 failed because a constructor-thread guard rejected a legitimate SDK
  tool-worker callback. One request, zero writes and an unresolved tool call did
  not establish expiry or clean Stop.

The independent source suite contains 105 distinct tests. The author ran 104
focused source tests on each of Python 3.11 and 3.12; these overlapping suites are
reported separately. Three actual pinned SDK dispatch cases passed from source,
and the same three passed in the installed Python 3.14.7 worker with exact package
origins. Those cases use reduced native fixtures and no model; the real IQ3_S
trial is separate. Package review has 91 predicates, deployment review has nine,
and the actual installed host/worker checks number 254/307. Twenty SDK dependency
files are pinned. No full model-content hash or resource reservation is claimed.

`reviewed-source.json` preserves the original 120-file source freeze. Only its
historical `docs/paused-budget-expiry.md` entry resolves to
[`reviewed-support/paused-budget-expiry.md`](reviewed-support/paused-budget-expiry.md),
whose original bytes and hash are retained. That archived document describes the
pre-acceptance state; its relative links retain their original repository context.
The current [feature document](../../../docs/paused-budget-expiry.md) records the
accepted result. The exporter does not redirect any other reviewed file or update
historical hashes. Main documentation outside that freeze may evolve independently.

## Reproduce the selection

The repository is self-contained for reading the result and running the offline
selector tests. Run from its root with Python 3.11 or newer:

```console
python -m unittest discover -s provenance -p test_paused_expiry_acceptance.py -v
```

The private raw receipts are intentionally not published: they contain local
paths, prompts, conversation state and process identities. An evidence custodian
can independently replay the original selection by providing the 31 exact inputs
listed under `private_input_sha256` in `bindings.json`. Create a private JSON file
with `scope` set to `installed-paused-expiry-03` and an `inputs` object mapping
every listed label to an explicit existing file path. Paths may point to relocated
copies; file contents must match the fixed role hashes. Include the wheel as a
binary file and the trace/effect receipts as their original JSONL files. Run:

```console
python provenance/paused-budget-expiry/acceptance/export.py --repository . --selection /path/to/private-selection.json --output /path/to/new-output
```

The output directory must not exist and its parent must exist. The command reads
only terminal evidence and writes `result.json` and `manifest.json`; it does not
start agents, contact a service, install a package or run inference. It rejects
missing, altered, swapped or mismatched inputs. A future trial needs a separately
reviewed evidence binding; changing this binding cannot turn it into the original
accepted trial. Without the private inputs, public users can validate source and
selector contracts, but cannot independently reproduce this particular live
observation merely from its hashes.

`selection.py` and `gates.py` reuse the reviewed pure selectors. `export.py` reuses
the retained [control-intent exporter](../../desktop-control-intent/acceptance/export_acceptance.py),
[installed-desktop exporter](../../installed-desktop/export_acceptance.py) and
[strict sanitizer](../../windows-handoff/sanitizer/sanitize_milestone_v7.py), with
their exact source hashes. It does not modify historical globals or call their
old package/deployment gates. The small wheel identity selector adapts the
existing implementation to the accepted 54-module wheel. Package check names
include relative module paths, so their complete fixed set and strict Boolean
values are checked directly. Public output uses explicit fields and omits raw
prompts, transcripts, absolute paths, process/window identities, API responses
and absolute clock readings.

## Adopted work and attribution

The repair uses the adapter's existing Recovery lock and task claim, Python's
standard performance counter, and the pinned Hermes tool-dispatch, context and
interruption interfaces. The upstream bounded submit barrier is also used in the
actual SDK fixture. Adopted Hermes work is from Nous Research's MIT-licensed
[revision 14e1e43](https://github.com/NousResearch/hermes-agent/tree/14e1e43a23761b369641208e204365cd6cb9399d),
with exact source hashes and citations retained in the
[thread repair record](../thread-successor/README.md),
[clock repair record](../clock-successor/README.md) and their `sdk-references.json`
files. The public runtime does not copy the SDK implementation. Project source,
selectors and preserved project predecessors are Apache-2.0. This acceptance
record introduces no new third-party implementation.
