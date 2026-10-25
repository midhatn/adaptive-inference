# Installed Windows qualification: cold01 and full01

The [receipt](result.json) records two independently accepted cases using the
same regular installed Adaptive Inference wheel, explicit Windows profile,
retained GUI, pinned Strata owner and Hermes SDK. This is a bounded installed
reference composition, not completion of the always-on roadmap.

| Case | Observed result | Independent terminal checks |
| --- | --- | --- |
| Cold Pause/Stop | Actual GUI Pause, no Resume, no model launch/request/file effect; pending task remained paused; normal joined Stop | 35 |
| Full report/restart | Two actual GUI Resume acknowledgements, three real IQ3_S requests, one correct report write, retained worker replacement and normal joined Stop | 47 |

The full report has **4 rows, 17 units and 4,350 cents**, including folder 1,100,
notebook 2,250 and pen 1,000 cents. The first worker was deliberately ended at a
verified safe checkpoint and joined; its distinct replacement completed the
original task without repeating the write. Both native owner generations
released their retained processes. Task, native-history, effect, control and
actual database records were checked independently. Neither the mere existence
of a terminal file nor the observer's eventual connection errors supplied
cleanup proof.

**Known UI limitation:** after completion, the first observed Stop click did not
register. The second click produced normal shutdown. This result does not prove
single-click Stop reliability. The cause was not established by that live
observation. The earlier cold case also observed X minimizing and supported
window activation restoring the same window; it did not test a literal taskbar
click, destroyed-window reopening or a computer restart.

## Exact tested scope

- Wheel SHA-256: `c3f85f7d4b5047a170c2ee8f4fd14111bb902cff9951c9bbb53e9a787ae3a99a`.
  The receipt lists all 52 installed Python source hashes. Host and worker
  imported regular installations with matching contents, without checkout fallback.
- Qualification source manifest: `ebb7582477b901058e0840cd20a2f7d9c815bcd6af74e024cae46fd08e4ad06e`.
  The actual [installed qualifier](../../../examples/validation/installed_desktop/README.md)
  uses the same product composition and preserves its original acceptance gates.
- Model: `qwen3.8-flash-next-iq3_s-adaptive-media-beta`; context 65,536;
  output allowance 10,923; high reasoning with 8,192 tokens; speed projection
  disabled; PCIe fraction 0.37. Model files were metadata-bound, not fully content-hashed.
- Qualification bounds: 900-second task budget, at most eight provider
  requests, 240-second readiness waits and a separate 1,800-second outer guard.
  Observed parent durations were 79.578 seconds for cold and 590.141 seconds
  for full. Both exited zero without emergency termination.
- Policy: explicitly selected `cooperative-owned-foreground.v1`, with its
  complete unchanged thresholds in the receipt. Both readiness observations
  identified the owned foreground GUI and current worker, with admission open.
  GUI CPU was 0.046137 cores at both observations; host CPU fractions were
  0.067961 and 0.189474. These two samples do not demonstrate admission above
  the older 0.05-core threshold or establish a performance improvement.
- Final host control-progress totals were 319 successful exchanges and 317
  pairs. Maximum observed exchange duration was 0.016 seconds and maximum
  arrival gap was 1.062 seconds. These are authenticated control-connection
  measurements, not physical input/display/GPU latency. Commanded resets and
  all fixed invalidation counters remain in the receipt.

The report had zero validator rejections, so this run does not demonstrate
real-model self-correction. It does not establish physical reboot recovery,
safe pending-task expiry, arbitrary agents/tasks/tools, foreign foreground
switches or pressure injection under this new installed policy. Those remain
separate roadmap items. A completed ordinary host can remain parked until Stop;
this finite qualification does not impose its outer lifetime on the product.

## Software checks and reproduction

The pretrial source passed 985 required software checks: 698 core, 22 provenance,
12 Hermes boundary, 11 foreground, 64 native contracts, 11 arithmetic feedback,
9 shutdown receipts and 158 existing sanitizer tests. The focused 174 product,
141 GUI and 33 qualification-adapter cases are already included in the 698,
not additional tests. Independent regular-wheel validation repeated those 348
selected cases outside the checkout. Actual host/worker/binding installation
audits separately checked 248/301/19 predicates. Software tests do not substitute
for the two live cases above.

Follow the [deployment guide](../../../docs/installed-desktop.md), build a regular
wheel, install its same bytes into the explicitly selected full interpreters,
and run both existing cold/full qualification scenarios with a fresh local state
directory. Keep the original model, quality, deadlines and ownership checks.
The profile example has placeholders; local runtime/model/SDK locations and
their hashes must be supplied deliberately. No model weights or private runtime
installation are distributed here.

The managed worker initially refused installation under PEP 668; no override or
marker removal was used. A separately owned official PBS distribution solved
that deployment boundary. The first unstripped archive matched its official
archive digest but not the existing executable pin and was not executed. The
official `3.14.7+20260901` stripped artifact matched the existing executable and
uv 0.12.16 download metadata. The original managed environment was preserved.
The [deployment guide](../../../docs/installed-desktop.md) retains the primary
sources and exact supported procedure. An initial build without isolation also
failed against older build tooling; the repository's normal isolated build
succeeded without changing requirements. These failed attempts are deployment
lessons, not additional model or scheduling results.

## Evidence selection and privacy

[The selector](../export_acceptance.py) reuses the unchanged historical v7
sanitizer's bounded strict-JSON reader, type checks, hashes, deterministic encoder
and privacy check. It does not reuse that historical run's acceptance selection.
It binds these actual terminal inputs and independent audits by hash and exports
explicit field allowlists. [The manifest](manifest.json) binds this selected
receipt to the selector and reused helper. The separate selection regressions
run through the existing provenance CI discovery:

```text
python -m unittest discover -s provenance -p "test_*.py" -v
```

The 20 added tests reject changed outcomes, quality/budgets, missing audits,
wrong installed/worker/foreground identity, uncleared obligations, false cold
inference claims, nonfinite data and hiding the missed Stop click. Strict JSON
behavior follows [Python's documented duplicate/nonfinite handling](https://docs.python.org/3/library/json.html#standard-compliance-and-interoperability);
the existing selection exclusions align with [OWASP's logging guidance](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html#data-to-exclude).

Private input hashes identify the audited local records. They do not reconstruct
undistributed prompts, responses, reasoning, credentials, process/window/session
identities, paths or logs. The source, contract and reproduction runner are
available locally in this repository; the receipt reports a specific audited
observation rather than asking readers to trust a mutable upstream PR.
