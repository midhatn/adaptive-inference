"""Write the declared synthetic 1s -> 6s -> 1s execution trace; no live data."""
import argparse
import hashlib
import json
from pathlib import Path
import random


def make_trace():
    rng = random.Random(80399)
    runtime = hashlib.sha256(b"synthetic-runtime-A").hexdigest()
    cohort = hashlib.sha256(b"synthetic-request-A").hexdigest()
    return {
        "schema": "adaptive.latency-drift.trace.v1",
        "units": "seconds",
        "duration_scope": "completed_execution_excluding_queue_and_admission",
        "records": [
            {"runtime_id": runtime, "request_cohort": cohort, "observed_at_s": i * 10,
             "outcome": "success", "execution_s": level + rng.uniform(-.02, .02)}
            for i, level in enumerate([1] * 120 + [6] * 120 + [1] * 120)
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(make_trace(), stream, indent=2, allow_nan=False)
        stream.write("\n")

