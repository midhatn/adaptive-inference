# Research discovery through Papers with Code

Reviewed 26 October 2026; integrated example verified 30 October 2026. The useful near-term addition is an **offline timing
change detector** using River's existing implementation. Native prefill
preemption remains a separate backend experiment. Neither changes the current
IQ3_S model, foreground policy, resource ownership or task-recovery contracts.

## What was searched and verified

The supplied [Hugging Face Papers with Code repository](https://github.com/huggingface/paperswithcode/tree/885539fec00ed12c19baca8f7a08f5355b8ef7cd)
is an Apache-2.0 catalog application with import jobs, search and a public API.
Its local database starts empty; cloning the application does not preserve the
hosted catalog. We inspected its public API contract and used bounded anonymous
keyword searches for GPU sharing, LLM preemption, adaptive inference and drift
detection, followed by selected paper records. This is a discovery source, not
a guarantee of complete coverage, correct attribution or reproducible results.

For each selected lead, the paper, implementation owner, source revision,
license, relevant code, tests and compatibility constraints were checked
separately. The source pins below identify that inspection; they are not claims
that a whole external project has passed a security audit or our hardware tests.
Previously assessed AKV, Gandalf and LMCache mechanisms remain in the
[cache-state guide](cache-state-research.md).

| Lead | Inspected implementation | Decision for this project |
| --- | --- | --- |
| [River](https://arxiv.org/abs/2012.04740), catalog record 4702 | [`online-ml/river`, `950984786649806bfdc446062fcc830235f8131b`](https://github.com/online-ml/river/tree/950984786649806bfdc446062fcc830235f8131b), BSD-3-Clause; Page-Hinkley, mean accumulator, detector base and upstream drift tests inspected | Reuse the public detector API in an isolated offline comparison. No dependency added to the installed controller. |
| [FlowPrefill](https://arxiv.org/abs/2602.16603v1), catalog record 56294 | [Author repository, `d8a1c417c04469287c39abb63e8d3a3791c70f1a`](https://github.com/ChiachiHsieh/FlowPrefill/tree/d8a1c417c04469287c39abb63e8d3a3791c70f1a), root Apache-2.0; scheduler, platform selection and transfer prerequisites inspected | Keep a native-capability experiment in M3/M8. Current Windows/IQ3_S compatibility is unqualified. |
| [Andes](https://arxiv.org/abs/2404.16283v2), catalog record 30759 | The catalog's implementation link pointed to [`just-curieous/curie`](https://github.com/just-curieous/curie), whose README identifies a different project and paper | Reject that link as implementation attribution. Keep Andes as a paper-level lead; no code was adopted from the mismatched repository. |

## River: detect when timing observations stop describing current behavior

Suppose a class of requests usually takes five seconds, then takes twenty
seconds after the workload changes. Our existing Peak-EWMA estimate responds to
the high measurements, and its empirical tail and expiry rules remain useful.
A separate change detector can help assess whether this is an isolated spike
or a sustained shift that deserves a new calibration period.

River's [Page-Hinkley implementation](https://github.com/online-ml/river/blob/950984786649806bfdc446062fcc830235f8131b/river/drift/page_hinkley.py)
maintains a running mean and cumulative deviations. It can detect increases,
decreases or both; it resets on the update following an alarm. We reuse its API
rather than implementing another detector. This is a maintained implementation
of an established method, not a claim to have selected the newest or universally
best statistical test. The [optional reproducible example](../examples/validation/latency_drift/README.md)
uses the released package identified below and keeps the baseline estimator unchanged.

The published Windows package is audited separately. River 0.26.1 corresponds
to release commit [`64285b9dd6c606804753235fe992bcf25b9856ee`](https://github.com/online-ml/river/tree/64285b9dd6c606804753235fe992bcf25b9856ee).
Its detector, mean accumulator and detector base match that release's source
after normalizing line endings; they do not all byte-match current GitHub main.
In particular, the release initializes the decreasing-sum maximum to `-1`, while
the inspected main initializes it to negative infinity. The offline example
must identify and test the actual released implementation rather than silently
substituting main's identity. No change is made to River's implementation.

The isolated Windows/Python 3.11 example passed 22 tests, including the released
upstream increase/decrease/both-mode regression. Independent review added two
behavioral checks: each alarm and post-alarm sample count matches the released
detector, and baseline predictions match the existing estimator across invalid
measurements and the next valid update. The finite synthetic trace changes from
one to six seconds and back to one second; alarms occur at zero-based samples
130 and 250. A separate 600-sample stable fixture produces no alarms. These are
reproducible software checks, not real-workload false-alarm rates or speedups.
The example preserves the BSD-3-Clause notice, exact release/source identities,
hash-locked optional dependencies and commands to reproduce the comparison.

The audit found practical constraints:

- Input validity and context separation belong outside the detector. Its
  inspected update method does not itself reject every nonfinite measurement.
  Failed or incomplete work must not appear as a fast successful execution.
- Durations must measure completed execution, excluding queue and admission
  waiting. Keep separate streams for explicit runtime/request cohorts; changing
  models, configuration or request shape must not look like unexplained drift.
- Parameters depend on the units and workload. The default minimum is 30
  observations, so an eight-request task cannot qualify the default detector.
  An absence of alarms on sparse data is not stability evidence.
- An alarm is advisory. It proves neither a cause nor unsafe resource use, and
  it cannot authorize admission, change precision, renew a task budget or clear
  an unresolved operation.

The M8 comparison uses unchanged input traces for the current cost estimator
and the additional detector. Predeclare parameters, then retain stable streams,
upward/downward shifts, isolated spikes, recovery, context changes and invalid
observations. Report false alarms, detection delay, sample counts and overhead.
Synthetic checks establish reproducible software behavior; later held-out real
traces are necessary to select a useful policy. Live resource control remains
unchanged until a separately reviewed comparison demonstrates benefit.

## FlowPrefill: interruption needs native support

FlowPrefill separates where execution may safely yield from when the scheduler
reconsiders work. This is relevant when a long prefill delays an interactive
request, but the inspected code changes native request/KV state inside a modified
vLLM implementation. A generic HTTP gateway cannot supply those controls.

The inspected setup selects an empty target on native Windows. Its README limits
KV transfer to NIXL and states that the paper's colocation/baseline code is not
included. We found benchmark scripts and test requirements, but no general
`tests/` tree in the inspected revision. These limits do not establish a working
hybrid IQ3_S composition on this single-GPU laptop. We did not install it, change
models or reproduce its reported throughput results.

The reusable requirement is to measure the **actual native interruption bound**
and its overhead before treating suspension as an alternative to full unloading.
Compare complete task progress and foreground response with the existing drain
policy. Native capability, saved-state identity, quality and release verification
remain prerequisites. Fairness or starvation handling must never force work
through a failed feasibility or ownership check.

## Reproducibility and continuing research

Record the query date and selected catalog identifiers, then pin each useful
implementation and retain the applicable license with reused code. Recheck the
primary source when acting on a later version. Preserve our own decisions,
parameters, tests and results here so the reasoning survives an external link
changing or disappearing. A catalog listing or an upstream benchmark is never
substituted for validation of this project's exact integration.
