# Reusable two-task and foreground qualification source

The [public workflow](../../../examples/validation/task_handover/README.md)
promotes the exact author04 harness and case17 foreground helpers. Case17's
accepted installed run remains a separate historical result; the public path
adaptation has source and synthetic local-binding checks, not another model run.

`source-references.json` pins preserved project source, empty templates and one
existing synthetic fixture. `predecessor/harness/` retains the accepted harness
and seven baseline sources. `predecessor/foreground/` retains the actual helper
sources. No private run logs, databases, observations, prompts or machine paths
are included. The preserved sources are references; do not execute their old
workstation-relative entrypoints.

The example's `source-lineage.json` identifies exact unchanged files and the
five narrowly reversible helper adaptations. Imports now resolve colocated
modules; an explicitly supplied local disabled declaration selects the case;
enabled bindings have a documented sibling filename; audit directories derive
from that case. Source checks use the published manifest and preserved relative
source references. The original predicates, quality, clock, budgets, capture
rules, actual-observation requirements and result formats are unchanged.

This reuses the existing `examples/validation/explicit_continuation` publication
pattern and Apache-2.0 source. The example retains the Hermes MIT notice for its
saved-read lineage. The import/path/discovery mechanics follow official Python
[path resolution](https://docs.python.org/3.11/library/pathlib.html#pathlib.Path.resolve),
[direct source loading](https://docs.python.org/3.11/library/importlib.html#importing-a-source-file-directly)
and [test discovery](https://docs.python.org/3.11/library/unittest.html#test-discovery),
rechecked on 1 November 2026. No external implementation was copied for this
path adaptation.

```console
python -B -m unittest discover -s provenance -p test_task_handover_reproduction.py -v
```

The wrapper runs the same focused tests once. They verify exact original bytes,
reverse only declared location changes, reuse the complete synthetic foreground
fixture, and exercise relocated source/local declarations and refusal. These
checks neither activate a binding nor run the installed agent/model, native
engine, GUI or historical terminal audits. Actual deployment receipts and model
assets remain external prerequisites described in the workflow.
