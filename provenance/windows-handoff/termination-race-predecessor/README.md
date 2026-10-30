# Retained-handle termination predecessor

These original Apache-2.0 project sources preserve the owner before the bounded
termination-denial observation. `manifest.json` hashes the exact ownership module
and its previous source pins. The successor lives in the Windows validation
example; historical receipts and source archives remain unchanged.

The installed predecessor failed native release with six retained processes and
five confirmed exits after a termination denial. The exact kernel timing was
not recorded. A controlled regression reproduces the zero-time observation
failure without accepting an empty process list as proof of release.

From the repository root, run this single deterministic predecessor check:

```python
import os
from pathlib import Path
import subprocess
import sys

root = Path.cwd()
environment = dict(os.environ)
environment['NATIVE_OWNER_SOURCE'] = str(
    root / 'provenance/windows-handoff/termination-race-predecessor')
result = subprocess.run(
    [sys.executable, '-m', 'unittest', '-v',
     'test_termination_race.TerminationRaceTests.'
     'test_cleanup_collects_full_six_exits_after_denied_late_exit'],
    cwd=root / 'examples/validation/windows_handoff/native', env=environment)
assert result.returncode != 0  # Expected TerminateProcess error 5, not a pass.
```

Run the same case without `NATIVE_OWNER_SOURCE` to exercise the current successor.
Its full suite also verifies that live denial, timeout and failed waits remain
failures. The supplied tests inject Windows/job/clock responses; they are separate
from installed model qualification. No private process identifiers, user prompts
or local raw receipts are redistributed here.

The older arithmetic-feedback and shutdown-receipt checks also depend on these
exact predecessor helpers. Their original test readers are preserved under
`test-readers/`, with a separate hash manifest. The current readers change only
the source selection for the two declared native helpers: both successor and
predecessor hashes must match before the historical bytes are returned. Every
original expected hash and assertion is retained, and all other helpers still
come from the current example. The companion
`test_historical_native_sources.py` suite verifies both identities, rejects
modified bytes and restores each original test reader exactly.

Hosted CI at `fc84187c124b9fbed9e115cc88a713c941eabd21` exposed the missing
historical source selection after the newer helper passed its focused checks.
That failed result remains part of the validation history; local regression
passes do not replace a subsequent hosted check of the corrected commit.
