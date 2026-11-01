# Source preservation for sequential desktop task handover

This source-only outer layer preserves the exact changed predecessor modules and
touched existing tests from commit `c3f8726712bdd845abab8a9cdf111282d1a5f858`.
The source map pins every current runtime module by complete bytes and the existing
cross-version AST fingerprint. It constructs the exact earlier fifty-nine-module
view before applying the existing task-contract historical projection.

The layer reuses [task-contract source preservation](../task-contract/README.md)
and the complete-file projection in `tests/thread_pause_lineage.py`. The original
task-contract manifest, thirty-one earlier source/acceptance JSON files, historical
expected hashes and accepted receipts remain byte-for-byte unchanged. Saved test
and helper files preserve the previous assertions as source; this layer does not
execute predecessor code. The repository already contains the earlier standalone
source snapshots and their licensed upstream sources, so replay does not require
fetching a pull request or a network dependency to reconstruct these predecessors.

The task chooser imports `TaskSpec`, which imports `Verdict` from `feedback`.
Python executes module code when loading these imports, so the installed child
source pins include `task_spec.py` and `feedback.py`, with their actual module
origins checked before the chooser opens a dialog or reads a file.
See the [Python import-system reference](https://docs.python.org/3.11/reference/import.html#loading).
A strict source assertion requires the launcher's only code change to be those
two additions to `CHILD_SOURCES`; the original installation assertions still use
their unchanged historical expected hashes.

All saved files remain Apache-2.0 project source, including their original notices
and citations. See the repository [license](../../LICENSE),
[task-contract research](../../docs/task-spec.md), and
[existing continuation lineage](../explicit-continuation/source-lineage.json).

Current behavioral tests qualify current code separately. A passing historical
projection is not installed-agent, model, native-resource, GUI handover, performance
or restart acceptance. This source layer changes none of those historical claims.
