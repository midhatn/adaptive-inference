# CPU-fixture readiness observation

Hosted Windows Python 3.12 job
[121770731323](https://github.com/midhatn/adaptive-inference/actions/runs/40379261349/job/121770731323)
on `24713ab3bf3e0a632f08b0aa9fdcd1a6aa05f3a6` failed in test setup:
the CPU child's readiness file existed but opening it raised `PermissionError`.
The log does not identify which handle prevented the read. Windows documents
[file-sharing restrictions](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
that can prevent an open while another handle is held.

Reuse the existing bounded observation loop. Only `FileNotFoundError` and
`PermissionError` from reading the marker are retried; each retry still checks
the retained child's exit and original 30-second startup deadline. Malformed
JSON, incorrect PID/work guard and other I/O errors remain failures. No child
restart, product behavior, 15-second work guard or installed deadline changed.

The deterministic transient-denial reproduction failed before the change and
passed afterward. New tests also cover permanent denial, child exit, missing
publication, invalid content and an actual Windows exclusive file handle which
is released before a second read. Python 3.12 passed all 50 focused source and
actual CPU-child cases, with no failures, errors or skips. These are test-fixture
checks, not installed-agent, SDK, model or native-engine acceptance.

The complete prior fixture is retained byte-for-byte, SHA-256
`9aba2b541f1b08bca5a07fe3283d887bd53d01e4d48ae2679986aa5a20a1504d`.
`source-lineage.json` binds the predecessor, successor and sole changed helper
by bytes and AST. The diagnostic lineage first verifies this outer change,
then runs its existing historical checks on the exact prior source. Old
provenance manifests are unchanged; every runtime module matches `24713ab3`.

The first publication at `c3d99c1` missed a historical test-reader dependency.
Hosted [job 121783343642](https://github.com/midhatn/adaptive-inference/actions/runs/40382845538/job/121783343642)
correctly rejected the changed diagnostic test's source identity. The earlier
50-case run and independent focused review did not cover that consumer. Preserve
those results at their original scope; they did not establish complete CI.

`support-source-lineage.json` now records the exact dependency chain through
the diagnostic, pause-observation and safe-wait tests, retaining all three prior
files and their explicit source-reader transformations. Existing assertions and
historical manifests remain unchanged. A regression restores each complete
prior test byte-for-byte and rejects unknown edits. All 69 source-lineage and
readiness checks passed on Python 3.12 with no skips; this broader selection
includes the previously omitted consumers. The runtime and actual-child helper
are unchanged by this follow-up.

Reproduce with the repository installed and `tests` on the Python module path:

```text
python -m unittest test_continuation_readiness test_continuation_diagnostics_lineage test_task_file_alias_lineage test_continuation_host -v
python -m unittest discover -s tests -p "test_*lineage.py" -v
```

Actual retained-child host cases and the file-sharing check require Windows.
The complete platform suite remains the separate hosted CI gate.
