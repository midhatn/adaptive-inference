# Exact current Hermes source supplement

This source-only supplement preserves the unmodified NousResearch Hermes revision
`14e1e43a23761b369641208e204365cd6cb9399d`, used by the separate current-Hermes
plugin/model task evidence. It does not replace the archived `2587d823` source or
the historical host-intent overlay, and does not change the Adaptive Inference
gateway, Strata source, native executable or model assets.

The delta requires the existing `integrations/hermes/source/hermes-2587d823.bundle`
and its inventory, at their recorded SHA-256 values. It stores the exact new
commit, trees and file blobs absent from that baseline. It preserves all 20,897
tracked files and original Git modes, reusing 10,433 file blobs from the baseline.
The target Git tree is `7bdb68806cf9b8aa1f56bed34998d6d4bec90188`.

This is a source snapshot, not a complete Git history backup. Original commit
bytes and parent references are retained; missing ancestor history is explicitly
represented by a shallow boundary. The upstream MIT license is included and all
other original tracked license files remain in the complete source inventory.
Existing upstream support and test assets are retained for exact source identity.
There are no newly added model weights, dependency environments, compiled runtimes,
private prompts, service configurations or inference logs.

## Offline restoration

Use Python 3.11 or later and Git. Place this supplement in its own directory and
pass the canonical repository containing the existing source archive and reviewed
`provenance/reconstruct.py`. The output must not already exist; its parent must.

```sh
python restore_delta.py --repository /path/to/adaptive-inference --output /new/path/hermes-current
```

The helper checks both archives and inventories before creating the output,
checks the materializer's source hash before importing it, refuses an existing
output, and restores raw Git blobs without running upstream code. Python network
calls and every Git transport are disabled. Positive controls confirm that a
Python HTTPS connection and Git HTTPS transport are denied. It verifies the
complete resulting tree, every file's SHA-256, exact original commit and clean
checkout. Its JSON receipt contains no private filesystem paths.

The delta is 47,850,166 bytes (45.6 MiB); it avoids duplicating the existing
81,449,809-byte archive. The upstream gap contains 4,462 added, 346 removed and
6,032 modified paths, so this is a substantial addition rather than a small
application patch. The first build took approximately 15 seconds. A full Windows
offline restoration passed on 2026-10-24. This verifies source reproducibility,
not dependency installation, model inference or performance.

## Files to preserve

- `hermes-14e1e43a.delta.bundle`
- `hermes-14e1e43a.manifest.json`
- `source-delta-lock.json`
- `restore_delta.py`
- `UPSTREAM-LICENSE.txt`
- `README.md`
- `restore-receipt.json` and `checks.json` as separate validation evidence

Do not publish the private builder, restored checkout or machine-local probe
directories. The existing canonical archive is a prerequisite, not another copy.

Source provenance: [NousResearch/hermes-agent at the exact revision](https://github.com/NousResearch/hermes-agent/tree/14e1e43a23761b369641208e204365cd6cb9399d),
[original license](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/LICENSE).
