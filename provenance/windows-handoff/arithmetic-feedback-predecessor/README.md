# Arithmetic-feedback predecessor source

This archive preserves the v4 harness and its executable helper/test/source-pin
closure before bounded arithmetic correction was added. The current example
preserves the v6 harness, including the later shutdown correction; the exact v5
harness is retained in the adjacent `shutdown-predecessor` archive. The example's
`predecessor-source-manifest.json` checks these 20 exact predecessor files and
requires every helper other than `run_validation.py` to remain identical.

`private-preparation-inventory.json` is the original 26-file preparation
inventory, preserved byte for byte as historical metadata. Six entries are not
members of the executable closure: four preparation documents and two earlier
controller review probes. Their old local paths and reviewer notes are not
runtime prerequisites and are not republished as executable helpers. Portable
usage and research documentation remain in the current example; their citations
and the root research bibliography remain authoritative.

`original-v5-test-source.py` preserves the original arithmetic test as source
evidence. The current executable test derives from the v6 original preserved
in `shutdown-test-sources`, which also accounts for the changed shutdown helper
and final receipt capture. Only its source-verification lookups were adapted
for the public archive. The original tests and preparation inventories are
historical evidence, not test entry points.

`ARITHMETIC-FEEDBACK-DECISION.md` records the research-first decision and its
preparation scope before live qualification. It is not a successful hardware
receipt. The existing project feedback helper remains the executable correction
mechanism; no paper implementation was copied. Original project source is
Apache-2.0. Retain the repository LICENSE, NOTICE, cited source revisions and
the preserved psutil BSD-3-Clause reference/license when distributing the native
owner source.
