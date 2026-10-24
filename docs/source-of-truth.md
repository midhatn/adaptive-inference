# The canonical source and preservation contract

Adaptive Inference is developed, documented, tested and released in this repository. A contributor should be able to understand its behavior, inspect the implementation and reproduce its source from a clone or complete source distribution. Following an old pull-request conversation is not a build step.

## Where authoritative information lives

| Question | Canonical material |
| --- | --- |
| What are we trying to build? | [Always-on goal and acceptance criteria](always-on-controller.md), [development plan](../PLAN.md) |
| What works now? | [README](../README.md), [architecture and contracts](architecture.md), [compatibility matrix](integrations.md) |
| What code implements it? | [Portable package](../src/adaptive_inference), [native integration inputs](../integrations) |
| How do I reproduce it? | [Reproduction guide](reproducing.md), [native source guide](legacy-reproduction.md), runnable examples and tests in this checkout |
| What was actually checked? | [Evidence ledger](evidence.md) and source-bound JSON receipts under [provenance](../provenance) |
| Where did a reused mechanism come from? | [Research and reuse decisions](research.md), [bibliography](../REFERENCES.bib), [NOTICE](../NOTICE), retained licenses and source references under [third_party](../third_party) |
| How does this relate to another project? | Timestamped [upstream registry](upstream-prs.md); upstream PRs are delivery and discussion records |

The behavior in a release is defined by its source, tests and documentation at that tag. `main` continues development. Use an exact commit or release when reporting a result; a mutable web page or PR title is insufficient to identify an implementation.

## What survives a missing upstream repository

The portable controller, policy modules, checkpoint store, feedback runner, examples and tests live here. Optional Strata and Hermes integration inputs include their pinned source baselines and our patches, with checksums and expected output identities. The native Strata dependency has its own pinned local source input. Reconstruction uses these local inputs and does not require the original PR branch or repository to remain reachable.

Original source files for mechanisms actually adapted into the portable package are preserved with their revision, path, checksum, license and credit. These are archival references, not additional plugins that execute when the package is imported. Research papers and documentation that only inform a design remain cited with a local explanation of the relevant idea and our decision. We do not redistribute unrelated discussions or copyrighted publications merely to preserve a link.

The [local reference index](../third_party/reference-sources/README.md) explains each actual reuse. Check it with `python third_party/reference-sources/verify.py`. Check integration inputs with `python integrations/strata/setup.py --verify-only` and `python integrations/hermes/setup.py --verify-only`. Run the complete no-network restoration gate with `python provenance/offline_acceptance.py --output ../offline-proof-01`, choosing a new output directory. After building the release, `python provenance/check_distribution.py` verifies that its source archive contains the same files as the checkout, including bundles, licenses and references, and that its runtime wheel contains the matching Python modules and notices.

Historical integration exports have explicit scope: the Strata overlay retains selected runtime/build/test work, while excluding old private hooks, workstation configuration and historical report files. Preserving that reproducible input does not make those excluded artifacts part of a release. Earlier measurements whose complete environment is not distributed remain historical observations in the evidence ledger.

The current [Hermes source supplement](../integrations/hermes/current-source/README.md) separately preserves commit `14e1e43a23761b369641208e204365cd6cb9399d`, used for the public-hook plugin and real IQ3_S task. Its 47,850,166-byte Git object delta reuses the existing Hermes archive and restores the complete 20,897-file target snapshot, including its license. It retains original commit/tree identities and checks each tracked file; it does not promise complete upstream history. Run `python integrations/hermes/current-source/restore_delta.py --repository . --output ../hermes-current-proof-01` with a new output directory. Both Git transports and Python network calls are denied, with positive controls. This supplement is newer than v0.2.0 and is included in subsequent source builds from `main`.

The SDK and native-schema fixtures also retain the particular licensed source files they execute, exact revisions, dependency locks and receipts. These bounded closures are identified as such; they are not complete snapshots of all eighteen upstream repositories. The [delivery ledger](upstream-delivery.md) links each public proposal back to canonical code and evidence. If an upstream PR disappears, the shared implementation, scoped test and preserved proposal remain reviewable here.

## Dependencies and the meaning of standalone

The project owns its adaptation and task-continuation logic. Using the gateway does not require installing Strata, Hermes, CoS, Jev or Laya. It does require Python and the pinned Python libraries; a real inference run also requires a compatible model server and separately acquired model assets. Optional native builds require a suitable compiler, SDK and their declared dependencies. This repository does not include a full inference model, proprietary SDK or user credentials.

Complete upstream snapshots retain their already-tracked support/test assets: these include tokenizer-vocabulary GGUF fixtures and Strata's small 483,520-byte experimental projection artifact. They are preserved to keep the baseline exact, with upstream notices, and are not executed by restoration. They neither supply the user's IQ3_S inference model nor count as a test of it. Models used for actual inference must still be acquired and identified separately.

Offline **source reconstruction** and offline **installation** are different checks. The bundled integration sources can be restored without network access. To install Python dependencies without the network, first prepare a wheel directory for the target operating system and Python version on a connected machine:

```text
python -m pip download --only-binary=:all: -r requirements.lock --dest wheelhouse
python -m pip download --only-binary=:all: "setuptools>=77,<83" --dest wheelhouse
```

Copy the complete source distribution and wheel directory to the target. Record checksums of the downloaded wheels in that deployment's own manifest. In a fresh environment, install with `python -m pip install --no-index --find-links wheelhouse -r requirements.lock`, install the downloaded build backend, then use `python -m pip install --no-deps --no-build-isolation .`. A wheel directory prepared for one platform is not guaranteed to work on another. This is an operator preparation recipe; our source-reconstruction checks do not certify an offline package supply chain.

## Release and fork rules

1. Keep the complete source distribution or Git clone, including local integration inputs, license notices and reference-source manifests. The small runtime wheel installs the portable package; it is not the full research/integration archive.
2. Run the documented checks from that copy. Keep the resulting receipts with the exact source identity and workload. A stored receipt reports an earlier run; rerunning the command establishes a result for your environment.
3. Develop shared changes here or in a fork of this repository. Propose engine/agent changes as consumers of a versioned contract, and record their source and validation separately.
4. Update preserved inputs explicitly: review the license and source delta, regenerate checksums, verify reconstruction and tests, and document changed behavior. Never silently retarget a source lock to a mutable branch.
5. Preserve original authorship when adapting or moving code. Add citations when their work is used; a contributor inventory is not required for unused work.

To preserve Git history independently of GitHub, make a local backup with `git bundle create adaptive-inference-backup.bundle --all` and verify it with `git bundle verify adaptive-inference-backup.bundle`. A complete source distribution preserves the release files without its full Git history. Keep backups somewhere other than the only working disk; the repository cannot protect its sole copy from storage loss.

Maintainers can regenerate a baseline from an already complete local upstream checkout with `python provenance/preserve_source.py --repository LOCAL_CHECKOUT --revision FULL_COMMIT --upstream-url ORIGINAL_PUBLIC_URL --output-prefix NEW_PREFIX`. Both output files must be new. The tool reads committed Git objects, refuses missing blobs/LFS/submodules/unsupported entries, and does not fetch or include working-tree changes. Review the license and tracked assets before publishing. Update the source lock explicitly, then run reconstruction and its acceptance gate.
