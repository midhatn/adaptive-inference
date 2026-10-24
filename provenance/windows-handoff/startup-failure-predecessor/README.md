# Source preceding the startup diagnostics correction

These exact source files preserve the Windows owner and adapter used by a
failed qualification on 24 October 2026. Startup stopped before generation
with an access-denied error; the original collector operation was not recorded,
and a later cleanup/owner-state error obscured that failure. This is retained
failure provenance, not a successful lifecycle or recovery result.

`manifest.json` records each file's SHA-256. `engine.py`, `ownership.py` and
`source-pins.json` belong in the native example's `owner_source/` directory;
`native_owner_adapter.py` and `windows_host.py` belong in its `native/` directory.
Unchanged surrounding code is in the [Windows handoff example](../../../examples/validation/windows_handoff/README.md).
No private configuration, task history, credentials, runtime binaries or model
assets are included here. Preserve the normal source reconstruction and exact
operator prerequisite checks before any reproduction attempt.

The original Windows API references and project authorship remain in the
sources. The diagnostic successor must not reinterpret this failed run as
successful or replace access checks with assumptions about process exit.
