# Task-store verification source record

This directory preserves the exact reviewed component, predecessors, original
test inputs and failed producer fixtures. `reviewed-prototype/source-manifest.json`
binds its 31 files. `source-lineage.json` records the canonical promotion and
four independent test inputs. The complete accepted M1 runtime is separately
preserved under `../persistent-desktop/m1-runtime/`.

The promoted TaskStore and 17 new tests are byte-identical to the final reviewed
prototype. Four independently written test methods are unchanged; their canonical
wrapper imports a fixture module and explicitly reuses its setup/hash helpers so
normal discovery runs each test once. The three archived source-preservation
checks verify the historical promotion, not a permanent prohibition on future
development. No frozen archive is imported by the installed runtime.

The supplied Windows suite passed 75 tests; an independent run repeated all 75
and added four passing probes. The original failed 48-test producer attempt is
retained under `reviewed-prototype/pre-cpu-01/`: one wrapper argument collision and
one unsupported fixture premise about physical schema-page spill. Later tests
corrected those fixture issues without claiming the stronger premise. The final
review also verified refusal of clean WAL databases without WAL/SHM creation.

To rerun the frozen component, using its own preserved source and no model:

```sh
python -I -B provenance/task-store-verification/reviewed-prototype/run_cpu_tests.py
```

Run the current code through the normal repository test suite. These are CPU
storage/OS-lock tests, not qualification of installed agents, native inference or
a computer reboot. Private diagnostic logs are not redistributed. Their absence
does not prevent reproducing these included source tests. The implementation
contract and required all-readers upgrade are in
[task-store-verification.md](../../docs/task-store-verification.md).

The source archive retains existing Apache-2.0 and attributed Strata MIT notices.
SQLite remains the recovery implementation supplied by Python; its exact pager
reference and public-domain notice are in `third_party/reference-sources/sqlite/`.
