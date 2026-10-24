# Controlled-11: bounded desktop handoff and installed-agent recovery

Validated on 24 October 2026 on Windows with an RTX 4070 Laptop 8 GiB, the existing IQ3_S model, and the pinned Strata/Hermes composition. This folder contains the exact sanitized receipts for **Controlled-11 / Hermes-real-03**, plus this explanation. The complete workflow passed the independent fail-closed exporter; earlier attempts remain excluded in `result.json`.

This is a bounded M1 qualification: real foreground-triggered resource handoff, a protected hardware-video-encoding task, and one installed Hermes process restart at a verified durable boundary. It is not an always-on service, OS reboot, power-loss, arbitrary-tool exactly-once, or long-duration qualification.

## What this run demonstrates

| Check | Observed result |
| --- | --- |
| First foreground workload | A dedicated visible 45-second GDI workload; foreground fraction 1.0; paint-interval p95 **17.4944 ms**, below the fixed 25 ms limit; no measured intervals over 50 ms. |
| Safe resource release | The active inference response completed normally. Native release was confirmed **7.375 s later**, **38.922 s after window start**, within the first foreground window. This is not instantaneous preemption. |
| Original arithmetic tasks | Both fixed tasks produced the exact expected JSON on their first attempt in this run. Two HTTP requests were observed; the bounded feedback implementation allowed at most three attempts per task. The live correction path was not needed. |
| Protected video task | A three-second **1280×720 H.264 NVENC** test-pattern video with **90 decoded frames**. Encode, probe, and decode processes each exited with code 0. |
| Second foreground workload during Hermes inference | Another dedicated 45-second GDI workload; foreground fraction 1.0; paint-interval p95 **18.6084 ms**; no measured intervals over 50 ms. It became visible during the same active normal-class agent request. |
| Durable resource wait | **780 observations over 81.375 s**, all at safe task revision 10 with no active dispatch or unresolved operation. States were releasing (56 samples), parked (216), and restoring (508). |
| Installed Hermes restart | First worker deliberately terminated at `safe_after_write`, revision 15; replacement worker exited 0 and reached accepted revision 21. Original task identity, prompt hash, transcript prefix, deadline, report, and file-effect receipt were preserved. |
| Final cleanup | Host closed; admission closed; no active or pending request; no scheduler uncertainty; controller fault absent. Final native cleanup verified all **8 retained process exits** and a free backend listener. |

Each foreground workload received one ordinary Space input directed to its verified dedicated window. The private operator audit verified the window identity and corresponding activity signal; no raw window handles, process IDs, application paths, or desktop images are included here. These are synthetic desktop measurements, not a gaming or video-playback assessment. GDI paint-submission/message timing is not physical display or input latency.

## Timing and recovery interpretation

The 81.375-second wait ran from monotonic time 6565.109 to 6646.484. The second visible foreground window ran from 6518.281 to 6563.281. **The recorded safe-wait interval begins 1.828 seconds after that window ends; it does not overlap the visible animation.** It demonstrates durable waiting through release and restoration following foreground demand. All 780 observations were checked; there were no pre-window samples counted toward acceptance.

The first worker made two provider calls before the verified restart boundary; the resumed worker made one further call. The final transcript contains seven rows. The shared task deadline remained 7412.093 across waiting, the safe checkpoint, and resumption. The report contains four rows, 17 units, and a total of 4,350 cents. Exactly one `write_file` effect receipt was observed, and its bytes and the report hash were unchanged across restart. This does not establish arbitrary-effect exactly-once behavior or recovery from termination during an uncertain write.

There were **zero live proven immediate-admission deferrals**. The safe wait is real runtime evidence, but the narrow prepare/send admission-race path remains separately tested fixture behavior. Never use this run to claim that an unknown operation was automatically reconciled.

The first arithmetic request took 31.687 seconds; the second took 150.907 seconds including admission/resource waiting. Those are end-to-end request times, not isolated token-generation measurements.

## Evidence and source identity

- [result.json](result.json): allowlisted measurements, complete validated controller history, native release proofs, artifact hashes, task recovery lineage, excluded attempts, and source/input hashes.
- [foreground-series.json](foreground-series.json): the sanitized numerical series for the historical baseline, historical uncontrolled run, and first controlled foreground workload. The second agent-foreground series is nested in `result.json`.
- [manifest.json](manifest.json): hashes of the two exact exported data files and of the exporter that produced them.
- [Exact exporter](../sanitizer/sanitize_milestone_v7.py) and [regression tests](../sanitizer/test_sanitize_milestone_v7.py).
- [Qualification harness](../../../examples/validation/windows_handoff/run_validation.py), [native host](../../../examples/validation/windows_handoff/native/windows_host.py), and [Hermes adapter](../../../examples/validation/windows_handoff/hermes/).

The relative harness/adapter links above resolve from this directory within the repository. All source identities are also recorded as hashes; a link alone is not evidence that a future revision remains identical.

| Exact input/output | SHA-256 or pinned revision |
| --- | --- |
| `result.json` | `4fa0879ade9d24cf25a89675dfaeee46537b47bf914e13d69b22e2f72247c064` |
| `foreground-series.json` | `eb30eb34124f599cb9fb885f6e4b6e4338a7430ad12d4c2145f6984d4f37ba31` |
| `manifest.json` | `f1c9c96eda87b5924bc3ecb0bf854c983e6ba4216e2019a932bd156c147dcff6` |
| Exporter v7 | `12004621166522cb80682e2bf1e4bc6d19e2ca72aeb585d21ce6408c2a965b33` |
| Controlled harness | `0521d7c16570728e7259610f80eedec778e8039ff309323154cc308fae8bd280` |
| Core handoff controller | `5b11f25a62d27c2b7f78776a9c05a2c15c0712def9fbad52dddd319232d0ed23` |
| Native owner package manifest | `ce79f32813a632df14e043c020789b1de9260aa34518e5f62f05645323e78213` |
| Native executable | `744205e4e024b5cbba19e4b560678ffe21e6899e59050929f7af51557f3c6198` |
| Installed Hermes SDK revision | `14e1e43a23761b369641208e204365cd6cb9399d` |
| Video artifact | `8425abb7459b478c239771eefb6e8202e1f01c466775ce30d5878b124c98e7cc` |
| Report artifact | `bbc5c118d7cc3963a9d71eedf35d86a9baa61c11b7f5cd66b496aeef01ce2a2a` |

Independent review rebuilt both exported data files byte-for-byte from 130 bound private inputs, checked the final scheduler/controller state and full event history, opened the terminal SQLite task history read-only, verified the report/video hashes and single file-effect receipt, and checked the privacy allowlists. The seven recorded runtime module hashes, harness, and exporter matched the source prepared for this repository. Raw prompts, private transcript content, local configuration paths, window/process identifiers, and native logs remain private.

Both complete handoff ledgers are validated before comparison. The exact pinned native host omits optional `server_exit_code` from its public release nodes; the exporter requires that value to be zero when supplied, retains it in output evidence, and removes only that field from comparison copies. No event is dropped, truncated, or reordered to accept this run. The final direct host cleanup release is recorded separately from controller transition events.

## Limits and previous attempts

The historical baseline and uncontrolled run used different earlier harness/runtime and owner-package identities. Their numerical summaries are retained for context, with **no causal performance-improvement claim**. Neither historical success fragments nor corrected exporter logic convert an earlier failed qualification into a pass.

Controlled-10 remains explicitly unaccepted: its old harness recorded `passed: true`, but terminal controller fault and incomplete pre-close event capture failed full qualification. Its exclusion retains that original recorded value alongside `qualification_accepted: false`. Earlier failures and interruption are likewise retained in the evidence.

Capacity was freshly observed, not reserved by the operating system or continuously guaranteed. The video check exercises NVENC with a test pattern; it does not qualify ComfyUI or another generative-video model. The fixed IQ3_S profile was preserved, but model assets were metadata-bound rather than fully content-hashed. Automatic boot startup, persistent demand-driven wake/idle behavior, and integrated M2 host operation require further validation.
