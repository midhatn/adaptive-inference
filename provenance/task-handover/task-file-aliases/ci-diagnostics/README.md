# CI child-output diagnostics preservation

This is a test-only diagnostic successor. The existing opt-in
`CONTINUATION_TEST_RECEIPTS` output now retains the last 64 KiB of each exact
joined child's merged output after its stream is closed. It records the byte
count, truncation flag and captured-byte digest, or a bounded capture error.
It does not change the child command, work, readiness or acknowledgment
deadlines, cleanup policy, assertions, runtime modules or model settings.

The earlier fixture and alias-lineage assertions are retained byte-for-byte in
`predecessor/`. The separate `source-lineage.json` pins both sides. The small
`tests/continuation_diagnostics_lineage.py` outer view validates the complete
current fixture before presenting the exact earlier d1 source to the original
alias-lineage checks. Their assertions remain unchanged; only an import and
one explicit projection call were inserted. The c99 alias manifest remains
unchanged and continues to describe its original runtime and fixture history.

The added source tests refuse altered complete files and predecessor identities,
check the exact two inserted statements inside the existing opt-in block, and
require the remaining whole fixture AST to equal the preserved predecessor.
No retained historical test or source is executed by this projection.

Reproduce the source-preservation checks from the repository root:

```powershell
python -B -m unittest discover -s tests -p test_continuation_diagnostics_lineage.py
python -B -m unittest discover -s tests -p test_task_file_alias_lineage.py
```

This reuses the repository's existing complete-file byte/AST preservation and
cross-version fingerprint in `task_file_alias_lineage.py` and
`paused_expiry_lineage.py`. The fixture reuses its existing retained process,
log streams and opt-in receipt. Source remains under the repository's Apache-2.0
license. No new executor or CI runner is introduced.
The ordering follows Python's existing
[unittest cleanup contract](https://docs.python.org/3.12/library/unittest.html#unittest.TestCase.addCleanup);
the retained log already uses
[combined subprocess output](https://docs.python.org/3.12/library/subprocess.html#subprocess.STDOUT).

A previous Windows CI child exited with code 1 before acknowledging Resume.
The earlier receipt established that exit and cleanup, but did not retain its
traceback. This diagnostic change allows a new CI attempt to expose that cause;
it does not relabel the previous failure or establish installed/model success.
