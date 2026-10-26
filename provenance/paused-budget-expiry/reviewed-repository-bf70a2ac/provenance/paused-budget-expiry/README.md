# Paused execution expiry source successor

This additive record starts at merged commit
`d3b6b006afa84bf7d246ffbcd2b427f5c2f23df6`. It preserves ten changed runtime
predecessors byte for byte in `sources/` and hashes the other 42 runtime files.
Historical acceptance records and historical expected AST fingerprints are not
relabelled or replaced.

`source-lineage.json` declares the exact changed imports, constants, functions
and methods. `tests/paused_expiry_lineage.py` checks each changed AST node against
its declared successor fingerprint before reversing only that edit for the
earlier preservation assertions. Every outside-seam statement remains in the
comparison. Mutations inside a declared seam are rejected before restoration;
unrelated queue, request-budget and watchdog mutations remain visible. Existing
GUI intent, rendering, installation and worker-source comparisons still run.

The changed files implement one boundary: atomic control append/seal; strict
marker and known refusal; pre-deadline safe Pause observation; final native
history verification under the existing owner; released-worker exit-5 proof;
host waiting and UI presentation. They do not change model quality, report
acceptance, the 900-second execution budget, eight-request budget, 240-second
readiness bound, 1800-second qualification guard, native owner implementation,
GUI launch/pipe ownership or the existing recovery effect path.

Source files in this successor and their retained predecessors are from this
Apache-2.0 project. The external Hermes APIs actually used are from Nous
Research's **MIT-licensed** Hermes Agent, copyright 2025 Nous Research, commit
`14e1e43a23761b369641208e204365cd6cb9399d`. No external SDK implementation is copied
into this directory. Its exact inspected files are:

| Hermes source | SHA-256 |
| --- | --- |
| `run_agent.py` | `8c215df03f32493f72992db0c0ccaddb811436f9025451e3f1e8f535dc9cda5d` |
| `hermes_state.py` | `e507ebd78b870364fd2fced94212592380cd26d0d39eec67547ed9bc233ebb98` |
| `hermes_state_usage.py` | `559ec5de3d1713318e0f9aa9f7a7023d0d101fb2d83af4aa3f6eeaca11e15527` |
| `hermes_state_messages.py` | `b3c5ad76a6d1a63c2800a0eca0c36240ad3098999a248568e46a7c3649cf9136` |
| `hermes_state_sessions.py` | `1eddb7aadd63ca88d366cfe10d9ba3a709f044eb7d6dcb60dbdd699167f7300e` |

The primary research references and why each was used are in
[the feature document](../../docs/paused-budget-expiry.md). CPU/SQLite fixtures
and a fake SDK lifecycle projection validate component contracts; they are not
an installed Hermes, real model, GUI, reboot or billing acceptance claim. The
separate installed expiry scenario must supply that narrower live evidence.
