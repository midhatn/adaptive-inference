# Real IQ3_S Hermes parent/child acceptance

On 2026-10-24, an actual Hermes parent read `orders.csv` and created `report.json`
using its native file tools. A host-created production child independently read
the source and report and wrote `verification.json`. An external deterministic
check recomputed all counts and totals and compared both artifacts exactly.

The result was **4 rows, 17 units and 4,350 cents**, including the per-item totals.
Five actual file-tool calls and six real model requests completed. The canonical
plugin left three parent requests normal and marked three child requests as
background. Response request IDs matched the same gateway's recorded history.
Neither the harness nor a prompt manually injected scheduling metadata.

Every request used `qwen3.8-flash-next-iq3_s-adaptive-media-beta`, a 65,536-token
context, output allowance 10,923, high reasoning, explicit reasoning budget
8,192, speed projection disabled and nested PCIe fraction 0.37. The existing
backend retained CPU vision and MTP disabled. No model or quality reduction was
used. The gateway's installed modules matched the published v0.2.0 wheel bytes.

The agent workflow took 208.63 seconds; gateway execution and cleanup took 212.76
seconds. These are observations from one task, not comparative performance results.
The gateway ended idle with six completed requests, no pending requests and no
uncertain backend completion. Agent child processes were gone; all seven retained
backend process identities had confirmed exits. Both owned listeners were absent
after cleanup. The user's other installed services/profiles were not modified.

The [receipt](result.json) records source/native identities, every request's quality
fields and content hashes, exact artifact hashes, scoped timing and cleanup.
Full transcripts, model reasoning and private paths are not published. The CSV
and two JSON artifacts contain only this synthetic task. Their exact bytes are
preserved beside the receipt.

The later [parameterized reproduction runner](../../examples/validation/hermes_tool_task/README.md)
retains the same task and quality contract, with explicit local paths. It has its
own fixture-only qualification; the real receipt here records the original run.
The [exact Hermes source supplement](../../integrations/hermes/current-source/README.md)
preserves the SDK revision locally for offline source restoration.

This test qualifies one **serial, explicitly orchestrated parent/child workflow**.
It does not prove autonomous delegation decisions, foreground responsiveness under
gaming/video load, native memory leases, preemption, physical-reboot survival or
automatic startup. The established idle-unload/reload failure remains a separate
unresolved result in the main evidence ledger. Model weights were checked by
recorded size/mtime, not a fresh full-content hash.
