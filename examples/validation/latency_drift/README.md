# Offline latency-change replay

This optional example adds **advisory change detection** to an offline trace of
completed execution durations. It calls the actual released River
PageHinkley; it does not implement a detector, collect live telemetry,
dispatch requests, alter the existing cost model, or change an agent, model,
precision, queue, lease, resource allocation or configuration.

The purpose is M8 investigation: can a cheap statistical signal reveal a change
within one explicitly comparable workload? An alarm is a reason to investigate,
not a diagnosis or permission to act. No alarm does not establish stability.
This is not evidence of lower latency, GPU compatibility, improved task quality
or autonomous control.

## Reproduce the tested environment

The author replay used Windows x86_64, Python 3.11.9 and published binary wheels:
River 0.26.1, NumPy 2.4.6, SciPy 1.17.1 and Narwhals 2.27.1. These are optional
example dependencies. The main repository requirements and installed inference
environments do not need to change.

From the repository root, use a fresh environment and fresh output filenames:

~~~powershell
py -3.11 -m venv .venv-latency-drift
& .\.venv-latency-drift\Scripts\python.exe -I -B -m pip install --only-binary=:all: --require-hashes -r examples/validation/latency_drift/requirements-windows-py311.txt
& .\.venv-latency-drift\Scripts\python.exe -I -B -m unittest discover -s examples/validation/latency_drift -p test_replay.py -v
& .\.venv-latency-drift\Scripts\python.exe -I -B examples/validation/latency_drift/make_synthetic_trace.py --output synthetic-trace.json
& .\.venv-latency-drift\Scripts\python.exe -I -B examples/validation/latency_drift/replay.py --repository . --trace synthetic-trace.json --output synthetic-result.json
~~~

The wheel lock deliberately describes the tested Windows/Python 3.11 platform.
Other platforms need separately reviewed binary wheels, dependency hashes and
a fresh replay; the code's portability is not an unperformed platform test.
Do not compile River from source as an implicit fallback. River includes compiled
components even though this Page-Hinkley implementation is Python.

The source lock records the published wheel, release commit, three executed
source identities, upstream test provenance, license and exact existing cost
model source. Source verification permits only CRLF/LF differences, useful across
wheel platforms. A changed baseline or detector source refuses replay and requires
a reviewed repin. This small source check is not an audit of every dependency.

## Measurement contract

Input is one JSON object with exactly schema, units, duration_scope and
records, as emitted by make_synthetic_trace.py. Each record has exactly:

| Field | Meaning |
| --- | --- |
| runtime_id | Opaque lowercase SHA-256 label for the runtime/configuration cohort. |
| request_cohort | Opaque lowercase SHA-256 label for comparable request shape/workload. |
| observed_at_s | Finite, nonnegative observation clock in seconds, nondecreasing within the cohort. |
| outcome | success, error or missing. |
| execution_s | Positive completed execution seconds, at most 86,400, for success; ignored for error/missing. |

The required scope string is
**completed_execution_excluding_queue_and_admission**. No queue/admission duration,
prompt, response, file path, user identity or free-form metadata is admitted.
Opaque labels must not be credentials. A producer must change the cohort when
the actual runtime, sampling, route, request shape or workload changes.
The example cannot prove that an external producer measured the intended phase.

Raw **seconds** enter the detector; there is no normalization by a changing
prediction and no comparison of unrelated cohorts. There are at most 128 cohorts,
100,000 rows and 32 MiB per JSON input. Invalid clocks, backward per-cohort time,
unknown schemas/fields and nonfinite JSON constants refuse the trace. Successful
zero, negative, nonnumeric or out-of-range durations are excluded, never learned.
Direct in-process callers also exclude nonfinite durations. Error/missing events
are never treated as quick successes.

Each cohort owns its own detector and an instance of the unchanged
RequestCostModel from src/adaptive_inference/costs.py: decay 60 seconds,
TTL 900 seconds, at least three baseline samples and at most 32 retained rows.
The detector resets after a gap strictly greater than 900 seconds since its last
accepted measurement, and on excluded measurements or error/missing events.
Invalid success leaves the baseline's existing prediction unchanged, matching
its rejection behavior. Error/missing resets that cohort's baseline to cold,
an explicit conservative offline prefilter that needs no invented failure
duration. This is prediction comparison, not reproduction of global model
rejection/eviction counters. Detector alarms never alter the baseline.

Default PH parameters are the released defaults: minimum 30 accepted samples,
delta 0.005 seconds, threshold 50 seconds, alpha 0.9999 and mode both.
The cumulative-deviation threshold is not a probability or a 50-second latency
limit. The --parameters argument accepts an exact five-field JSON override:
minimum 30–100,000, delta 0–86,400, threshold greater than zero and at most
8,640,000,000, alpha in (0, 1], mode up, down or both.
Numeric parameters must be finite and not booleans; bounds prevent accumulator
overflow within the declared trace size. Parameters are recorded in every
result, not fitted or deployed by this example. River resets on the next
measurement following an alarm; sparse new segments remain explicitly marked.

## Source, tests and limits

The discovery lead was [River's paper](https://arxiv.org/abs/2012.04740) through
the Papers with Code index. The executable source is the
[official River 0.26.1 release](https://github.com/online-ml/river/tree/64285b9dd6c606804753235fe992bcf25b9856ee),
not an index label. See the [Page-Hinkley API](https://riverml.xyz/latest/api/drift/PageHinkley/)
for the public interface; online documentation may describe a newer branch.

The separately inspected main commit
950984786649806bfdc446062fcc830235f8131b is **not** equivalent to the release.
In particular, released Page-Hinkley initializes its maximum decrease to -1;
the inspected main uses negative infinity. This example preserves the release
behavior and does not patch River.

The upstream_page_hinkley.py file retains the exact released data-stream expression,
test function and helper for three upstream mode expectations, with the original
seed. It is covered by the adjacent [BSD-3-Clause license](LICENSE.river).
Other example code is original repository code. The tests also use separate
deterministic synthetic streams: stable noise, an upward step and recovery,
cohort separation, missing/failure exclusion, expiry, clock/parameter guards,
source identity and a matched-trace comparison against the actual baseline.

These checks describe their finite fixtures only. The default parameters were
not tuned to a real workload. A synthetic false-alarm count is not a false-alarm
rate guarantee, and synthetic change detection does not establish causal
diagnosis, task correctness or a useful live adaptation policy.

