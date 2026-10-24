# Original qualification-filter fixtures

These are the exact original v5/v6/v7 CPU fixture sources used before the public
macOS and hosted Windows CI runs exposed a temporary-path spelling mismatch in
their positive package fixture.
The manifest preserves their byte identities. They are historical source, not
standalone test entry points; run the adjacent current test files instead.

The only change in each current test file is resolving the fixture's existing
temporary root with `Path.resolve(strict=True)` before constructing package/run
paths and serializing its synthetic effective configuration. On macOS an
unresolved temporary path can use a different spelling from its resolved path.
The real exporter already resolves package and owner paths, so the original
fixture's log path failed exact template comparison. Python documents this
existing operation in [Path.resolve](https://docs.python.org/3.12/library/pathlib.html#pathlib.Path.resolve).

All assertions, exporter implementations, frozen source selections, native
runtime code and accepted result bytes are unchanged. No platform is skipped,
no path check is weakened, and no failed hardware run is reclassified. The
initial failures are recorded in PR #11's macOS and Windows jobs at head
`16907d8b662df39c66fc661ab783cec458ce20af`.

These are original Apache-2.0 project tests under the repository LICENSE/NOTICE.
