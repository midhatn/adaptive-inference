# Preserved source for task-local file aliases

This layer preserves the exact two runtime predecessors and four original
test/helper files from `febfce7afacb6f3d11cf09d774c1b9b0163b7c30`. That revision's
60 runtime modules are identical to the task-handover implementation built at
`e9fbb053f24661fe83976483be644ab23ccb4a5a`.

The repair lets the declared flat task files use either their basename or an
equivalent path rooted in that task's work directory. It preserves the raw tool
arguments and physical effect receipts; it does not grant access to other files.
Existing input hashes, output declarations, validation feedback, oracle and
reconciliation obligations remain applicable. The original basename-only test is
retained here; the current test exercises the expanded, bounded path capability.

The source map pins two changed and 58 unchanged modules. The exact prior bytes
are exposed to the existing [handover source view](../README.md), then the
[task-contract view](../../task-contract/README.md). Those original manifests and
the earlier expected hashes are not rewritten. No archived runtime is executed
by this projection, and no network access is required to reconstruct its source.
Only the two changed runtime files are copied as predecessors.

A separately labeled `test_only_deltas` entry preserves the original continuation
host fixture. Its correction calls the existing admission fence before teardown
waits, including after a failed transition has left the retained transition set.
One regression retains the original body error while requiring completed cleanup.
The source assertion removes only that pinned regression and the one prepended
fence call, then requires exact equality with the entire original fixture AST.
All previous assertions and budgets remain intact. This changes no production
cleanup rule, raises no CI timeout and does not turn cancelled hosted jobs into
passes. The underlying exception in those cancelled jobs was not captured;
fresh CI is required to report it or pass. This follows the existing
[unittest async cleanup lifecycle](https://docs.python.org/3.12/library/unittest.html#unittest.IsolatedAsyncioTestCase)
and [asyncio cancellation guidance](https://docs.python.org/3.12/library/asyncio-task.html#task-cancellation).

The implementation reuses the existing full-file byte/AST projection and
`tests/ast_preservation.py` across Python 3.11/3.12. Python documents that AST
structure can change between releases; the existing normalizer handles only the
previously declared representation difference and refuses new syntax outside
that boundary. See the [Python AST reference](https://docs.python.org/3.11/library/ast.html).
All retained project files remain Apache-2.0, with their original notices and
citations; see the repository [license](../../../LICENSE).

In a prepared source-test environment, run these from the repository root:

```text
python -m unittest discover -s tests -p test_task_file_alias_lineage.py -v
python -m unittest discover -s tests -p test_task_handover_lineage.py -v
python -m unittest discover -s tests -p test_task_contract_lineage.py -v
python -m unittest discover -s tests -p test_task_file_aliases.py -v
python -m unittest discover -s tests -p test_task_spec.py -v
python -m unittest discover -s tests -p test_task_spec_recovery.py -v
```

The ordinary `MANIFEST.in` includes this archive and the tests in the source
distribution. `python provenance/check_distribution.py` compares actual built
source/runtime/license bytes with the checkout; it does not substitute for
runtime qualification. The existing [Setuptools distribution mechanism](https://setuptools.pypa.io/en/latest/userguide/miscellaneous.html)
is reused without a separate packaging system.

Current filesystem/SQLite behavior tests and historical source assertions have
different scopes. Neither turns an earlier failed installed trial into a pass.
A repaired wheel requires fresh deployment identities and a new IQ3_S task trial;
old accepted evidence, failed cases, and their source bindings remain unchanged.
This layer makes no new installed-agent, GUI handover, native-resource, reboot,
FP16 or performance claim.
