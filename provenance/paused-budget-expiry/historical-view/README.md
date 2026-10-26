# Reproduce the accepted paused-expiry evidence

The adjacent `reviewed-repository-bf70a2ac` directory preserves the exact small
source closure used by the accepted PR20 result: 120 reviewed inputs and three
existing helper files, 123 files and 1,594,016 bytes. Its identity comes from
the unchanged `acceptance/reviewed-source.json`, whose SHA-256 is
`bf70a2acc69cd6a1d9954ad3fe8dbd69f3c43aefa97803f079b15b5662e071db`.

This is historical evidence. It does not validate current runtime code or any
later continuation feature. The current runtime and its tests remain separate.
No models, installed runtimes, private receipts or full repository archive are
included in this snapshot. Source licenses and attribution remain in their
original files and the repository's LICENSE, NOTICE and third_party notices.

`source-map.json` explicitly maps every historical input to its preserved bytes.
The builder verifies the fixed mapping, original freeze, three helper hashes,
paths and all copied bytes before and after use. There is no Git/network lookup
or fallback to a current file that happens to resemble an older version. The
unchanged exporter, selectors, test file, bindings, result and manifest remain
under `acceptance/`.

From the repository root, run all 21 unchanged offline exporter checks:

```console
python provenance/paused-budget-expiry/historical-view/run_historical.py
```

Ordinary provenance test discovery invokes those same 21 checks through one
wrapper test. A failure retains the child test output. This nested count should
not be presented as 21 new runtime or model tests.

An authorized holder of the original private qualification receipts can repeat
the original export using an explicit selection file and fresh output path:

```console
python provenance/paused-budget-expiry/historical-view/run_historical.py --selection /path/to/selection.json --output /path/to/fresh-output
```

The output must match both published evidence files byte for byte. The temporary
view stays alive through child completion and verification. `--temporary-parent`
can select an existing directory outside the repository. Cleanup checks the owned
directory's identity; an unexpected replacement is left untouched and reported.

The implementation reuses the repository's `provenance/reconstruct.py` helpers
and Python's [temporary-directory primitive](https://docs.python.org/3.11/library/tempfile.html#tempfile.mkdtemp),
[file identity](https://docs.python.org/3.11/library/os.html#os.stat_result) and
[subprocess runner](https://docs.python.org/3.11/library/subprocess.html#subprocess.run).
These checks protect a cooperating local source tree; they are not an operating
system security boundary against a process racing filesystem changes.
