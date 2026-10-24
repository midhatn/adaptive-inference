# Historical qualification sanitizer

These original project files preserve the reviewed controlled-09/v4 and
controlled-10/v5-v6 and controlled-11/v7 evidence filters. They validate explicit historical source and
package hashes, terminal acceptance, native cleanup, task continuity and privacy
before writing a new private output directory. The v4 source is retained because
the v5 CPU suite independently checks unchanged predecessor acceptance gates.

The v6 correction validates every waiting checkpoint within its actual worker
phase, counts only post-foreground-start observations toward the wait gate,
and requires ordered revisions before the verified safe restart. The original
collector also recorded legitimate earlier waits, which cannot supply that
gate. This changes accounting, not the saved runtime evidence.

V7 additionally checks the final controller directly and compares complete
ordered handoff histories. The native host's public history omits the optional
server exit code; both histories are independently validated before that one
field is omitted from comparison copies. A supplied exit code must still be
zero and remains in exported evidence. Events, identities, counts, timestamps
and release flags cannot be omitted or changed. Controlled-10 remains explicitly
unaccepted despite its original harness recording a pass: its final controller
fault and incomplete pre-close event snapshot are retained as the exclusion.

Run the tests from a repository environment:

```text
python -m unittest discover -s provenance/windows-handoff/sanitizer -p "test_*.py" -v
```

The tests use temporary fixtures. They need neither private run directories nor
a model. The sanitizer itself intentionally refuses absent or failed terminal
evidence. Its frozen private operator-configuration hashes and historical
directory selection make it an audit of that recorded qualification, not a
generic exporter for arbitrary machines or newly generated operator packages.
New qualification bindings require their own reviewed source selection and
acceptance; do not weaken or silently replace the historical pins.

The current v5/v6/v7 CPU tests resolve their temporary fixture root before
serializing its synthetic paths, matching the exporter's existing resolved-path
contract on every platform. The [original fixture sources and explanation](fixtures-before-path-normalization/README.md)
are preserved byte-for-byte. This portability correction changes no assertion,
exporter, runtime source or accepted receipt.

Raw model responses, original prompts, transcripts, window/process identifiers,
operator paths and live-state files are not included here. Any separately
published sanitized result must retain its exact input/source hashes and scope.
This source archive alone does not accept any run. The original v5/v6 refusals
and all earlier runtime outcomes remain distinct from a later qualification.
