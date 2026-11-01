# Fixture Stop verification before cleanup

This test-only correction follows the original Windows/Python 3.12 push failure
at `81fd7a28ee2c3b600017b55070b7fdbd5008f7a2`:
[run 41318388842, job 124883207088](https://github.com/midhatn/adaptive-inference/actions/runs/41318388842/job/124883207088).
The original push/PR pair finished with 13 successful jobs and one failed job;
11 distribution checks passed and the failed job's distribution check was
skipped. Those outcomes remain unchanged.

The failing timeout-diagnostic case reached its injected timeout and recorded
both retained children joined, without cleanup kills. The fixture directory
still existed afterward. Its exact Windows removal exception was not retained,
so the original failure's precise cause remains unknown. Source review found a
concrete cleanup race: a process join can finish while its retained Stop task
still verifies the process's saved result and task history. Nested seed cleanup
callbacks also hid their cleanup errors from the outer test result.

The correction joins that retained verification before removing the fixture,
reports nested seed cleanup failures, and closes the fixture-owned SQLite
connections exposed by that reporting. It preserves the original injected timeout,
task/process identity checks and directory-removal assertion. It changes no
runtime, model, execution deadline or physical qualification. The exact fixture
implementation and its focused validation are reviewed separately; this archive
preserves the source boundary used by historical tests.

## Exact historical input mapping

`source-lineage.json` pins complete predecessor and successor bytes and the
repository's existing cross-version AST fingerprint for four files: the two
corrected fixtures, `continuation_timeout_lineage.py`, and
`test_task_preparation_lineage.py`. All predecessor files are copied byte-for-byte
from the named original commit. They are parsed as source, never executed.

The mapping runs first in the existing `preparation_predecessor` entry point.
This also covers historical readers that call that entry directly. Only the
declared complete successor is mapped to its retained predecessor. Unknown bytes
pass through unchanged to the original historical assertions; they cannot borrow
a known file's acceptance. Legacy disposable roots without this archive likewise
receive no mapping. Retained path, byte or AST changes are refused.

The existing preparation, timeout, readiness and earlier diagnostic records are
not modified. The older runtime closure and every older assertion remain in
place. The one changed historical reader obtains the approved outer view before
running its original byte assertions. The new tests check this four-file mapping,
unchanged manifests, predecessor/successor tampering, unknown input and legacy
roots. The dependency list includes this record and all four predecessor files
for existing relocated-source consumers.

This reuses the existing complete-file projection and
`paused_expiry_lineage.fingerprint`; it adds no separate recovery or validation
framework. Python's [hashlib documentation](https://docs.python.org/3.11/library/hashlib.html)
describes the byte digest, while its [AST documentation](https://docs.python.org/3.11/library/ast.html)
describes parsing source without executing it and notes grammar differences
between Python releases. The existing project fingerprint handles those
differences. No external implementation is copied; the project Apache-2.0
license applies.

Focused lineage results have their own retained receipt. They establish source
preservation only, not a successful repeat of the original hosted job, a product
performance improvement, or installed restart/foreground qualification.
