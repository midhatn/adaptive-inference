# Private v5 arithmetic correction decision

24 October 2026. This successor changes qualification harness arithmetic only.
Controlled-09 remains a failed run; its successful startup/foreground handoff
components do not make its rejected model answer acceptable. No model run,
runtime change, public source update or publication is represented here.

## Research before implementation

- Madaan et al., [Self-Refine, arXiv:2303.17651v2](https://arxiv.org/abs/2303.17651v2),
  25 May 2023: iterative feedback and revision retains the original problem and
  earlier answers. We reuse the project's existing loop, not a new framework.
- Huang et al., [Large Language Models Cannot Self-Correct Reasoning Yet,
  arXiv:2310.01798v2](https://arxiv.org/abs/2310.01798v2), 14 March 2024:
  unaided self-correction can fail or degrade reasoning. The model's confidence
  therefore cannot accept this arithmetic task; the independent exact check does.
- Zou et al., [AMTFV, arXiv:2607.29549v1](https://arxiv.org/abs/2607.29549v1),
  31 July 2026: exact computational verification supports answer correction.
  Its mathematical agent/tool machinery is unnecessary for this fixed CSV;
  the already independently specified EXPECTED object is sufficient.
- Kwok et al., [LLM-as-a-Verifier, arXiv:2607.05391v2](https://arxiv.org/abs/2607.05391v2),
  7 July 2026: learned scoring and criteria decomposition are current verifier
  approaches. A probabilistic judge adds no benefit to this exact small integer
  acceptance contract and is not adopted. No new model dependency is added.

The papers were reopened at their primary arXiv pages before editing; a bounded
read-only worker independently checked the 2026 references and the helper's
failure boundaries. These are paraphrased design references, not copied code or
evidence of improvement on the local IQ3_S model. No upstream implementation is
vendored. The reused executable mechanism is the existing Apache-2.0 project
module `adaptive_inference.feedback.run_with_feedback` and `Verdict`; its code
and current citations remain unchanged, and its actual runtime file is hashed
by `runtime_sources()`.

## Exact change and acceptance boundary

`generations()` still performs two logical arithmetic tasks using the identical
original PROMPT, MODEL, QUALITY and background request class. Each task invokes
`run_with_feedback(..., max_attempts=3)`. The helper retains the original user
prompt and appends every rejected assistant answer and validator feedback to
the actual next request. A second logical task begins with the original prompt,
not the previous task's correction history.

The unchanged independent EXPECTED values remain the acceptance oracle. The
validator additionally requires exactly the requested top-level and item keys,
actual JSON integer types (not floats or booleans), no duplicate keys, no fences
or extra text, and `finish_reason == stop`. Feedback identifies formatting or
arithmetic checks and asks for recomputation from the original CSV. It never
includes expected values, differences or replacement answers.

Only a recognizable completed response with textual content reaches this
validator. Explicit known terminal reasons `length`, `content_filter` and
`tool_calls` are rejected, even if arithmetic matches, and may consume another
attempt within the same bound. No returned tool call is executed. Missing,
null or unrecognized finish information is an unknown completion outcome and
is fatal. HTTP failure, transport failure, malformed/ambiguous response envelope,
wrong model or wrong background class also escape generation without retry.
Three rejected attempts exhaust that logical task and fail the whole workflow.
There are at most six request attempts; success of an earlier task cannot hide
exhaustion or a fatal failure in the later one.

The exact answer check is stronger than v4's plain Python dictionary equality,
which would accept equal-valued floats. The JSON-only rule now matches the
unchanged prompt rather than silently stripping Markdown fences.

## Private evidence and timing semantics

- `task-N-attempt-A-request.private.json` stores the exact request object before
  sending. Its model, messages and quality controls are the object passed to
  the HTTP client. `request_sha256` hashes its sorted JSON serialization; this
  is a reproducible object hash, not a claim about aiohttp's wire formatting.
- `task-N-attempt-A-response.private.bin` preserves raw received bytes before
  parsing; a valid parsed envelope is additionally saved as `.private.json`.
  A transport failure may have no response file and remains explicitly fatal.
- `inference-attempts.private.json` preserves every attempted request, timestamps,
  response identity/class, raw-response hash, verdict or fatal error. A fatal
  attempt has `verdict: null`, because no independent answer verdict was reached.
  `retryable` is false on acceptance, fatal failure or the final allowed rejection.
- `inference-tasks.private.json` distinguishes the two logical tasks from the
  actual `request_count`, including pending, accepted, exhausted and fatal states.
  Request count denotes initiated client attempts, not proof of backend dispatch.
- `inference-receipts.json` contains accepted logical-task receipts only.
  `requested_at` is the first attempt's request time; `completed_at` is the final
  accepted attempt's response time. Their difference is **logical task duration**,
  including rejected attempts and waits. `request_sha256`, usage, finish reason
  and accepted answer refer to the **last accepted request**. Per-request timing
  remains in the attempt ledger. `attempt_request_indices` links all attempts.

Rejected artifacts are never overwritten by a later accepted answer. Any
public export must validate the attempt ledger and accepted task receipts,
including failures, source binding and counts; it cannot reuse v4's assumption
of two first-attempt responses or make a first-pass performance claim.

## Source closure and validation

The new private directory copied 26 source/documentation/pin files from frozen
successor-v4. It excludes runtime configurations, private outputs, logs and
bytecode. `predecessor-source-manifest.json` records every original SHA-256.
All copied helpers remain byte-identical. In the harness, only `generations`,
`runtime_sources` and the import of the existing feedback helper change.
All other functions, model/prompt/quality/expected constants and full foreground,
handoff, protected video, Hermes recovery, cleanup and final acceptance gates
remain unchanged. The 1800-second outer watchdog is unchanged; more correction
requests can use more of that existing bound, not silently extend it.

`test_arithmetic_feedback.py` exercises the actual harness function with a fake
HTTP transport and real canonical feedback helper. It checks wrong-to-correct
history in emitted requests, exact integer/JSON acceptance, three-rejection
exhaustion, two-task/six-request bounds, terminal finish rejection, preservation
of an earlier accepted task, hard-failure no-retry behavior, raw evidence, and
AST/helper identity against frozen v4. These are CPU contract tests, not real
inference or proof that this model corrects its answer. Root must independently
review and seal this successor before any scheduled IQ3_S validation.
