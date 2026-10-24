# Persistent-controller source preservation

`m1-runtime/src/adaptive_inference/` preserves every Python module from accepted
M1 publication head `124b8ef2430a67e69e0e177f014a6fdc393c16a2`. Its original
handoff tests are also retained. The complete M1 native/foreground/Hermes and
qualification sources remain under `examples/validation/windows_handoff/`;
the accepted evidence remains under `provenance/windows-handoff/controlled-11/`.

These files keep the accepted runtime available inside a standalone source
archive while current runtime development continues. For exact historical
reproduction, use this preserved package on the Python import path with those
unchanged M1 examples and their documented dependencies. Confirm imported module
paths and the receipt's runtime hashes before any real qualification. Using the
new optional-demand runtime does not reproduce the old source identity, even
when compatibility fixtures pass.

`reviewed-controller/` preserves the exact demand-aware controller and private
component-test input reviewed before promotion. The initial demand promotion
changed only a comment relative to that controller. Current runtime additionally
includes the separately [reviewed timing callback](reviewed-timing/README.md).
The 23 portable demand test methods are
unchanged; their imports use the canonical package and current existing handoff
fixture module, whose 34 tests run separately under normal discovery. The
historical archived test layout is retained as evidence, not an installed entry
point.

`source-lineage.json` hashes every archived file and records promotion details.
It is a component source record, not native, installed-agent or full M2
acceptance. The repository's existing Apache-2.0 and attributed MIT/Apache
notices remain applicable. No model files, private histories or binaries are
included here.
