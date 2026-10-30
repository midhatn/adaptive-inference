# Paused-execution observation race

The control poll can observe a safe pause and then encounter a newly admitted
Resume before reading the execution's pause state. That ordinary state change
must not be mistaken for corruption or permission to seal the execution. The
current repair distinguishes this normal observation race while retaining the
existing integrity, ownership and final sealing checks.

This source record covers only `control_mailbox.py` and
`desktop/hermes/control_bridge.py`, with three declared method changes. The
exact preceding runtime bytes already exist in the repository's reviewed bf70
snapshot and are reused by explicit path and hash. No duplicate runtime archive
or new executor is introduced. `Mailbox.seal_paused_execution` remains unchanged.

The existing alias-lineage helper validates the current complete byte/AST
identity before presenting those two exact predecessors to the unchanged c99
manifest. Its other 58 current runtime files retain their existing identities.
Three scratch-closure fixtures copy the explicit extra source inputs; their
assertions remain unchanged. The CI-diagnostic assertion explicitly removes
that one declared copy-input line before its original byte comparison. The
modified helper and four source tests are retained byte-for-byte here, and
new checks require their exact restoration.

Run the focused current behavioral and preservation checks from the checkout:

```powershell
python -B -m unittest discover -s tests -p test_paused_observation_race.py
python -B -m unittest discover -s tests -p test_pause_observation_lineage.py
python -B -m unittest discover -s tests -p "test_*lineage.py"
```

These source/SQLite fixtures are distinct from installed agent, model, GUI and
native-resource qualification. A changed runtime requires a new built package
and installation identity before a fresh IQ3_S task can qualify it. Previous
failed CI and live attempts remain failed; their records are not overwritten.

The repair reuses SQLite's existing
[isolation](https://www.sqlite.org/isolation.html) and
[transaction](https://www.sqlite.org/lang_transaction.html) semantics and the
existing poll loop, consistent with Python's
[condition-loop guidance](https://docs.python.org/3.12/library/threading.html#condition-objects).

The preservation reuses this repository's existing byte/AST projection and
cross-version fingerprint. Code is Apache-2.0; existing license and citation
records remain in force. Exact current behavior is tested separately from the
historical source view, and retained historical runtime code is never executed
by these preservation helpers.
