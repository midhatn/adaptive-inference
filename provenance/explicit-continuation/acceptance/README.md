# Explicit continuation evidence

The [accepted result](result.json) records one installed, same-window explicit
Continue trial using the original IQ3_S task and unchanged quality settings.
After its original 900-second execution budget expired while paused, one
Continue click authorized a successor with a new 900-second budget. The saved
objective, conversation, cumulative request accounting and completed file
effect were preserved. The successor completed the original report task.

The independently executed terminal auditor passed all 70 checks. There were
three cumulative model requests (two before Continue and one after it), one
physical report write, and one real Resume, Pause, Continue and Stop click, with
no Retry. Both retained workers were joined. This is one bounded installed
trial; it does not establish computer-restart recovery, automatic budget
renewal, broad foreground compatibility, a performance improvement or the
whole M2 milestone.

The observer received 1,147 valid responses in 1,150 samples and ended with
`three_connection_errors_after_response` after shutdown. This is sampled
availability evidence. Cleanup is established by the separate retained-worker,
native-owner, GUI and transport checks, never inferred from connection errors.

The portable tests use an explicitly synthetic fixture; they do not run a
model, open a database, or establish installed-agent acceptance.

The exporter reuses the repository's exact installed-desktop exporter and
strict JSON/privacy helper. The adjacent `checks.py` is the unchanged reviewed
continuation qualification predicate. The small additional projection selects
public outcome fields and relative elapsed times; raw prompts, conversations,
personal paths, process/window identities and absolute clock values are excluded.

Run the portable checks from the repository root:

```console
python -m unittest discover -s provenance -p test_explicit_continuation_acceptance.py -v
```

The fixed role hashes in `bindings.json` select only the accepted terminal
inputs. A custodian of those private inputs can reproduce the public result:

```console
python provenance/explicit-continuation/acceptance/export.py --repository . --selection /private/selection.json --output /private/fresh-output
```

`selection.json` has exactly two keys: `scope`, with value
`installed-explicit-continuation-01`, and `inputs`, a mapping of the 19 roles
listed in `export.py` to explicit local input files. Each selected file must
match its fixed role hash. Paths can be relocated without changing file bytes.
The output directory must not exist. Replay reads retained terminal files and
does not execute the agent, SDK, native engine, service or GUI.

Actual replay and replay with all 19 input files relocated produced identical
`result.json` and `manifest.json` bytes. Three substitutions of actual receipts
were refused before creating output. The nine portable synthetic checks cover
privacy, altered counters, duplicate effects, stale readiness, changed result
identity, strict JSON and fresh-output refusal. These checks are separate from
the real installed trial and from the earlier overlapping source-test counts
recorded in the result.

The actual terminal audit establishes equality between the recorded evidence
and its direct TaskStore/native database, file, UI and retained-process reads.
The exporter binds that audit and the exact recorded evidence, rechecks the
unchanged continuation predicate and exports only the allowed fields. Private
databases and transcripts need not be published. A custodian needs the retained
private inputs for an actual replay; public synthetic tests have no such access.

`tested-build-source.json` retains all 904 reviewed build-source hashes and the
57-module runtime map. Replay directly compares those 57 runtime files with the
exact tested wheel. Equality of the original whole build is bound to the
independent source and archive reviews; later documentation edits are not
misrepresented as bytes of that earlier tested build. Historical acceptance
records and source manifests remain unchanged.

Native-owner check labels use neutral ordinals to remove private identifiers;
their numbering does not assert native-generation chronology. Only the
explicit execution pair and verified relative timeline carry ordering claims.

The mechanisms reused here are maintained in this repository under Apache-2.0.
The retained source-reference file records their exact identities. The
[Python 3.11 unittest discovery contract](https://docs.python.org/3.11/library/unittest.html#test-discovery)
supports the normal discovery wrapper, and the
[PyPA wheel specification](https://packaging.python.org/en/latest/specifications/binary-distribution-format/)
defines the archive and RECORD checks used by the independent package review.
