"""Compare three already-finished workload receipts. Never starts a process."""
import argparse
import json
from pathlib import Path
from metrics import compare


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline", "uncontrolled", "controlled", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    reports = [json.loads(getattr(a, name).read_text(encoding="utf-8"))
               for name in ("baseline", "uncontrolled", "controlled")]
    for report in reports:
        if report.get("schema") != "adaptive.foreground-result.v1":
            raise ValueError("unexpected receipt schema")
    # Compare only the same exact workload and rules; mode labels supplied by a
    # caller cannot establish what background activity was actually running.
    for key in ("source_sha256", "duration_s", "warmup_s", "target_fps"):
        if any(r.get(key) != reports[0].get(key) for r in reports[1:]):
            raise ValueError("mismatched workload: " + key)
    result = compare(*reports)
    result["requires_external_condition_attestation"] = True
    with a.output.open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
    print(json.dumps(result))
    return 0 if result["controlled_responsiveness_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
