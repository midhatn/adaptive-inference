# Explicit continuation source lineage

`source-lineage.json` records eight changed, 46 unchanged, and three new runtime
modules. The changed predecessors are the exact files already retained in the
[reviewed expiry repository](../paused-budget-expiry/reviewed-repository-bf70a2ac/).
The current tests exercise current behavior. The separate historical projection
in `tests/continuation_lineage.py` checks the entire current file or AST before
reversing the declared edits and applying the existing thread, clock, expiry,
and intent preservation checks. Their original expected hashes remain intact.
The projection neither executes old runtime code nor proves installed operation.

The seven files in `qualification-predecessor/` retain the exact prior installed
qualifier and its source closure, including the qualifier digest bound by the
published expiry acceptance. The current qualifier differs only in looking up a
retained wait by its exact child object rather than its reusable process ID.
Its adjacent fixtures and source manifest explicitly describe that compatibility
successor. The historical acceptance still refers to the original bytes.

Run the normal discovery command from the repository root:

```console
python -m unittest discover -s tests -v
```

Discovery uses Python's existing [unittest discovery and loading
protocol](https://docs.python.org/3.11/library/unittest.html#test-discovery).
No new test runner or archival execution framework is required. CPU/SQLite
component tests and source preservation are separate from installed SDK, native
engine, window, and model validation; this directory alone claims none of those.
