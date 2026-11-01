# Case17: bounded installed handover acceptance

The [accepted result](result.json) records one installed Windows/Strata/Hermes
IQ3_S trial. Both original terminal audits passed on the **same run**: 99
primary recovery/handover checks and the first-admitted-cycle foreground and
saved-read lineage supplement. The installed runtime remains source
`7306a53085ddc31d53d2ba50e91975c80cfc0014`.

Genuine document work closed admission while the first request drained. The
saved input read and original inventory objective survived safe resource-wait
expiry and one explicit Continue. The inventory output matched the independent
23-unit oracle. A distinct welcome task completed in the same controller, then
one Stop released the retained resources. **Welcome acceptance is format-only**;
its prose has no semantic oracle. Six cumulative provider calls produced two
physical writes. All three executions retained 900 seconds, the outer bound
was 2,700 seconds, and quality and the original 8/32 accounting limits remained
unchanged.

The public projection preserves 25 foreground actions, 24 wholly preseal, the
54.6808717-second maximum adjacent start-to-next-end interval, fourteen misses
of the 30-second operating target, and zero failures of the strict
less-than-60-second coverage gate. The 37.453106-second final tail is retained;
the postseal action contributes no coverage. It also records the rejected
file-picker value-setting attempt and recovery without another task control.

The parent joined with exit 0. The observer joined with exit 1 after three
post-shutdown connection errors, with the terminal result present and 1,618
valid responses in 1,621 samples. Cleanup follows the retained worker, native,
GUI, listener and transport evidence, never those connection errors. The final
job observation had no child members; its remaining runner subsequently joined.

This is a bounded private physical result. It does not complete M2, qualify
arbitrary desktop/media use, demonstrate restart or reboot recovery, measure
responsiveness or speedup, or turn earlier failed cases into passes.

## Public checks and private replay

From a complete checkout or source distribution, run the focused portable
checks with Python 3.11 or later:

```console
python -m unittest discover -s provenance -p test_task_handover_acceptance.py -v
```

These eight synthetic checks cover public projection, privacy, unchanged
counters and controls, preserved unsuccessful input and target misses, strict
JSON, fixed role selection, definition loading and fresh-output refusal. They
do not require private evidence and do not establish a new physical acceptance.

A custodian with the **33 exact retained inputs** can reproduce the public
result without installing the agent or running a model:

```console
python provenance/task-handover/acceptance/export.py --repository . --selection /private/selection.json --output /private/new-output
```

The selection object has exactly `scope` and `inputs`. `scope` must be
`installed-task-handover-case17`; `inputs` maps every role in
[bindings.json](bindings.json) to an explicit local filename. Each file must
match its fixed role hash. The destination must not exist and its parent must
exist. Missing or different evidence is refused before output creation.
Selection filenames are relocatable; retained private strings inside the files
are neither rewritten nor followed as filesystem paths.

The required roles include both original audits, the independent terminal
review and actual joins, closed task/UI/foreground/observer evidence, original
task inputs and output artifacts, and the exact wheel/build/installation records.
A public clone supplies the exporter and source references, **not those private
inputs**. The runtime wheel alone is also insufficient: replay needs the complete
public source closure and the custodian's exact retained files. Fresh-run
preparation is a separate [qualification workflow](../../../examples/validation/task_handover/README.md).

Actual replay and replay with all 33 inputs relocated produced identical
`result.json` and `manifest.json` bytes. The relocated replay blocked database,
process, network and shell calls: none were attempted, and no runtime module was
imported. The exporter does not rerun either original terminal auditor, query a
database, install a package, activate bindings, or operate a service or UI.

## Source and privacy boundary

[export.py](export.py) reuses the unchanged
[explicit-continuation exporter](../../explicit-continuation/acceptance/export.py)
and its pinned strict JSON, bounded file reader, type/hash, encoder and privacy
helpers. The historical 19-role export remains unchanged. The wheel and source
checks follow its existing pattern, adapted to this actual 60-module build.

[tested-build-source.json](tested-build-source.json) retains all 1,084 hashes of
the earlier reviewed build and its 60-module runtime map. Replay compares the
runtime map with the exact wheel and current unchanged runtime files. The
original source review, metadata bridge and independent archive review bind
the whole earlier build. Later reporting documents and this publication overlay
are not represented as bytes of that tested build.

The exact original `check_handover`, corrected author04 `check_safe_wait`,
`check_onset` and `check_lineage` predicates are evaluated only against selected
in-memory records. Their source bodies are unchanged. The existing AST-definition
selection convention excludes database/runtime imports; the required digest
and receipt-field constant come from hash-bound runtime source definitions.
Original native-path resolution remains bound by the original foreground audit;
replay preserves and hashes its raw argument and rechecks saved-read lineage
without accessing that private path. Exact source identities and reuse are in
[source-references.json](source-references.json).

Only explicit public outcome fields, hashes and relative durations are emitted.
No private paths, process/window/task/session identities, prompts, conversations,
input/output prose, absolute clocks or credentials are published. Private
rejected-input text is converted to a fixed public description. The manifest
binds the generated result and exporter; fixed support hashes bind its selectors
and source references.

These mechanisms are Apache-2.0 project code; existing Hermes notices stay with
the qualification source closure. The
[PyPA wheel specification](https://packaging.python.org/en/latest/specifications/binary-distribution-format/)
defines the wheel archive/RECORD context, while the
[source distribution specification](https://packaging.python.org/en/latest/specifications/source-distribution-format/)
explains the distinct source artifact. The existing independent package review
checks those artifacts; this export does not rebuild them. Test discovery follows
the [Python unittest contract](https://docs.python.org/3.11/library/unittest.html#test-discovery).
