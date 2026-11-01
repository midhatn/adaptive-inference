# Saved-task reopening and preserved source history

The [source record](source-lineage.json) describes the prospective saved-task
reopening change from `72ac717dbbcb11684e2687a2992a462a0f078f39`. Its merged
baseline, `c348398089e544bf54add2beaaf73550f8951efc`, has the same tree. The change
adds `desktop/saved_tasks.py` and changes `desktop/composition.py` and
`desktop/hermes/run_recovery.py`. This record does not qualify the changed
package for the earlier physical experiments.

The existing [outer source reader](../../tests/continuation_timeout_lineage.py)
checks the exact addition and the complete changed-file hashes before supplying
the retained predecessor bytes to the historical checks. The predecessor files
are copied byte-for-byte from that baseline and have both byte and syntax-tree
identities in the record. They are parsed, never executed. The existing
[cross-version AST representation](../../tests/ast_preservation.py) is reused;
there is no second test or runtime framework. Python's official
[AST documentation](https://docs.python.org/3/library/ast.html) and
[hashlib documentation](https://docs.python.org/3/library/hashlib.html) describe
the underlying standard-library interfaces.

Only the declared new module is removed from the historical input view. The
current 62-module package projects to its 61-module predecessor, after which
the unchanged [task-preparation record](../task-preparation/source-lineage.json)
and earlier checks recover their exact 60-module runtime. All previous source
records, retained files, module membership assertions and physical receipts stay
unchanged. Unknown bytes, syntax changes, missing or extra modules and altered
predecessor identities are not accepted as historical source.

The first focused batch ran 77 checks and had one failure. A historical test in
`test_safe_wait_lineage.py` parsed current `composition.py` directly, bypassing
the outer source view, before comparing it with its older declared changes.
The correction applies that same exact projection at this one read. Its
original assertions remain unchanged, and the original reader is retained
alongside the other four predecessor files. The failed batch remains a failed
attempt; subsequent validation applies to the corrected source.

Current reopening behavior is tested separately in
[the saved-task checks](../../tests/test_desktop_saved_tasks.py). Source-history
checks do not establish installed application restart, reboot survival, model
correctness, resource handoff or the absence of duplicate real tool effects.

The admission-wait correction refreshes only the declared `saved_tasks.py`
addition identity. Its [original source](admission-wait-predecessor/saved_tasks.py)
from `1af6d4a2b5a4431f66ac828318d60be7d6198670` remains byte-for-byte preserved,
with the old byte/AST pins recorded in `superseded_additions`. The original
[validation record](validation-2026-11-01.json) is unchanged. The existing
62-to-61 module check and all predecessor assertions remain strict; no new
projection or recovery framework was introduced. The separate
[correction record](admission-wait-validation-2026-11-01.json) describes the
ordinary wait → acknowledged Stop → reopen regression and its limits.

To run the affected source-history modules from this checkout with Python 3.11
or newer and the repository's locked dependencies, use PowerShell:

```powershell
$env:PYTHONPATH = 'src;tests'
$modules = @(
  'test_task_preparation_lineage', 'test_continuation_timeout_lineage',
  'test_continuation_diagnostics_lineage', 'test_admission_activity_lineage',
  'test_safe_wait_lineage', 'test_pause_observation_lineage',
  'test_task_file_alias_lineage', 'test_task_handover_lineage',
  'test_task_contract_lineage', 'test_continuation_lineage',
  'test_thread_pause_lineage', 'test_execution_clock_lineage',
  'test_paused_expiry_lineage', 'test_desktop_source_lineage'
)
python -B -m unittest -v $modules
```

The existing source-distribution rules include this record and every predecessor
file. Release validation must still run the ordinary distribution checker on
the actual built archive and wheel.
