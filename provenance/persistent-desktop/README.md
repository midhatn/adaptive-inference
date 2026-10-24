# Accepted M1 runtime preservation

`m1-runtime/src/adaptive_inference/` preserves all 17 Python modules from accepted
M1 publication head `124b8ef2430a67e69e0e177f014a6fdc393c16a2`, together with its
original handoff tests. Its full native/foreground/Hermes validation sources remain
under `examples/validation/windows_handoff/` and accepted evidence under
`provenance/windows-handoff/controlled-11/`.

These files retain the accepted source identity while the current runtime evolves.
For historical reproduction, use this preserved package on the Python import path
with the unchanged M1 examples and their documented dependencies. Confirm imported
module paths and receipt hashes before qualification. Current TaskStore software
tests do not requalify the historical real-model run under changed runtime bytes.

`m1-source-manifest.json` records every preserved file. Existing repository and
third-party licenses and notices apply. No models, binaries or private histories
are included.
