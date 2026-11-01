# Prospective deadline arithmetic correction

The working explicit-Continue checker now verifies the exact calculation used
by the existing producer: `deadline == authorized_at + 900`. It also requires
finite numeric values and a deadline greater than the authorization time.
The payload budget remains exactly 900; no tolerance or runtime clock change
is introduced.

A retained failed run exposed the issue at `authorized_at = 16108.3548623`:
the producer stores `17008.354862300002`, but subtracting the authorization
time yields `900.0000000000018`. The existing complete synthetic fixture now
exercises that actual value, alongside focused refusal checks. This validates
the prospective checker, not a new model run. The failed run remains failed.

`predecessor/` preserves the six affected or related working-source records
from commit `d39eb00269ea652fc6a7f8556dd70d2f11f1472f`;
`predecessor-files.json` records their hashes. `source-lineage.json` records
the exact reversible expression change and producer identity. Historical
`../acceptance/` sources, manifests and accepted evidence are unchanged.
The existing source tests and fixture are also byte-identical.

Run the existing portable wrapper from the repository root:

```console
python -B -m unittest discover -s provenance -p test_explicit_continuation_harness.py -v
```

The correction follows the existing Apache-2.0 producer and checker. Python's
[floating-point explanation](https://docs.python.org/3.11/tutorial/floatingpoint.html)
explains rounding in arithmetic; its
[`perf_counter` documentation](https://docs.python.org/3.11/library/time.html#time.perf_counter)
identifies the clock used by this project. Microsoft's
[high-resolution timestamp guidance](https://learn.microsoft.com/en-us/windows/win32/sysinfo/acquiring-high-resolution-time-stamps)
describes Windows QPC. These are explanatory citations, not imported code.
