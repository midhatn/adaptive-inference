# Source before the orderly-shutdown correction

These exact source and test bytes produced the controlled-10 composition.
The workflow completed its arithmetic, GPU artifact and installed-agent restart
stages, but independent final acceptance refused a controller fault during
shutdown. It remains an unaccepted whole run despite its original harness
reporting success.

When the host intentionally closed its scheduler during an already-awaited
native release, `_gateway_open()` treated `closing` as uncertain completion.
The release still confirmed all retained process exits; the controller then
latched a fault. The harness also captured its handoff events before awaiting
close and did not reject the final controller fault. A successor must preserve
real uncertainty checks, wait for owned transitions, capture the final ledger
and verify the terminal controller state. Its own complete qualification is
required; these original records are not relabeled.

`manifest.json` binds these files. They are historical sources, not replacement
runtime modules or additional current test discovery targets. The original
arithmetic test retains its private preparation layout; the current portable
test and its repository-relative predecessor archive are under examples and
the adjacent arithmetic-feedback archive. Existing project/upstream licenses
and attribution remain applicable.
