# Portable resource and context policies

These additions adapt the observation/recovery rules from medking82's [Strata #726](https://github.com/Niko1221/Strata/pull/726) and context-margin arithmetic from [#3684](https://github.com/Niko1221/Strata/pull/3684). They apply independently of the selected compatible engine or agent. They are development additions after v0.1.0; use a checkout containing them. Exact source pins and MIT attribution are retained in [NOTICE](../NOTICE) and [REFERENCES.bib](../REFERENCES.bib).

## Recover from host memory pressure

Copy [the example configuration](../examples/resources/adaptive-headroom.json), set the real backend address, and run:

```text
adaptive-inference serve --config examples/resources/adaptive-headroom.json
```

The example enables this policy:

```json
{
  "resources": {
    "min_available_ram_gib": 4,
    "adaptive_headroom": true,
    "recovery_margin_gib": 1,
    "recovery_seconds": 30,
    "max_sample_age_s": 5
  }
}
```

On the first healthy observation, at least 4 GiB admits work. An observation below 4 GiB, invalid telemetry or an observation gap closes new admission. After that, at least 5 GiB must be continuously observed for 30 seconds before the queue reopens. A dip below the recovery threshold resets that duration. These numbers are configurable examples, not a model-specific memory estimate.

The sampler runs at the shorter of one second or half `max_sample_age_s`, during idle time and active requests. Each dispatch also makes a fresh observation. This avoids treating an idle interval as evidence of recovery. Timestamps use a monotonic clock; missing, stale, conflicting and regressing data cannot earn recovery. Operating-system suspension or a stalled event loop may therefore require a new recovery interval.

An active request keeps ownership until its normal completion/drain rules release it. Waiting requests retain the existing queue deadline and can time out during prolonged pressure. `/status` exposes observed headroom, the admission reason and recovery progress. A status report is not a memory reservation. Only physical RAM and Windows commit headroom are sampled; GPU memory, cache sizing and native cancellation remain engine-specific.

Defaults preserve v0.1.0 behavior: `adaptive_headroom=false`; `min_available_ram_gib=0` disables host admission completely. A positive floor without adaptive mode resumes immediately when it is satisfied and creates no background sampler. Adaptive mode requires a positive floor. Recovery defaults are 1 GiB/30 seconds, maximum sample age 5 seconds. An explicitly selected zero recovery duration still requires the recovery margin.

## Plan context without reducing requested output

Use an engine/tokenizer's **complete rendered prompt count**, including chat templates, tools and multimodal tokens. A character estimate or messages-only count does not establish this input. Specify the engine's actual effective context, rather than a marketing maximum.

```text
adaptive-inference budget --context-tokens 8192 --prompt-tokens 6545 --required-output-tokens 4096
```

This returns `needs_compaction`, keeps `required_output_tokens=4096`, and reports `prompt_target_tokens=3584` and `tokens_to_remove=2961`. The current safety margin is 512 tokens and current output room is 1135; the planner does not silently turn the requested 4096 into 1135 or one token. Its exact target recomputes the changing safety margin, rather than subtracting the current deficit.

Exit codes support host scripts: **0** means `ready`, **1** means `needs_compaction` or `no_room`, and **2** means invalid input. `no_room` means even an empty prompt cannot fit the unchanged output reservation under this policy. In that case there is no compaction target. No command sends a model request or edits an agent conversation.

The Python API is `adaptive_inference.context_budget.plan_context_budget`. Optional `reasoning_tokens` and `answer_tokens` are reservations **within** `required_output_tokens`; their sum cannot exceed it. Zero means unspecified. An effort label is not translated into a token budget. If a backend uses different budget semantics, the host must express a truthful total before calling the helper.

The original small-context safety margin is retained: below 65,536 tokens, use the minimum of 4096, one-sixteenth of the context, and half the remaining room (nonnegative, integer counts). At or above 65,536, use 4096. This is a planning heuristic, not a certified tokenizer-error bound. `ready` is arithmetic feasibility, not backend admission or answer-quality assurance. A host must compact while preserving task intent, recount, plan again and keep the backend's own final check.

## Reproduce the checks

```text
python -m unittest discover -s tests -p "test_resource*.py" -v
python -m unittest discover -s tests -p "test_context_budget.py" -v
python -m unittest discover -s tests -p "test_cli.py" -v
```

The resource integration test uses real loopback HTTP with synthetic headroom and a simulated backend. It verifies idle sampling, active-owner preservation, delayed dispatch, recovery, unchanged request fields and sampler cleanup. The context tests verify small/large windows, moving-margin compaction boundaries, impossible reservations and unchanged output ceilings. These checks do not execute a GPU cache resize, installed agent or new model benchmark.
