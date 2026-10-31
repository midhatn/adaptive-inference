# Contributing

New contributors and AI workers should first read [AGENTS.md](AGENTS.md),
[HANDOFF.md](HANDOFF.md) and the [collaboration workflow](docs/multi-agent-collaboration.md).
Use its bounded task/return records to coordinate parallel work and preserve
continuation state. The same workflow works with one contributor or several.

Develop shared policy here, then contribute minimal changes to upstream engines and agents. Before editing, inspect [PLAN.md](PLAN.md), the relevant compatibility row and the [source preservation contract](docs/source-of-truth.md). Consult [upstream/registry.json](upstream/registry.json) when touching an upstream-specific integration; it is historical context, not a prerequisite for portable development.

1. Reproduce the problem with a focused observable contract.
2. Implement the smallest useful change without changing model quality or replaying side effects.
3. Run the relevant existing checks for the changed contract and the required milestone/CI gates. Runtime changes normally include `python -m unittest discover -s tests -v` and `adaptive-inference demo` in a clean environment; use the reproduction guide for integration-specific checks. Documentation-only work needs content/link and applicable source-package checks, not a fresh model trial. Retain exact commands, source identity, results and unexecuted checks.
4. Update documentation, compatibility/evidence status and research attribution when relevant.
5. Open a PR here. Name any actual backend/client run separately from fixture tests.

New algorithms or borrowed implementations need their primary citation, source revision, license and reuse explanation in `docs/research.md`, `REFERENCES.bib` and `NOTICE` as appropriate. Preserve the actually reused source reference locally when its license permits redistribution; add its identity and checksum to the reference manifest. Keep all existing notices when moving code. Do not vendor model weights or machine-specific runtimes. Required integration source inputs must be included in the complete source distribution and reconstructible without fetching an old PR.

Upstream PRs should name the canonical commit/release and carry only the engine/agent-specific change. Preserve maintainers' templates and review decisions. Closed or superseded PRs are historical links, not implied merges. Update the registry after publication and after a state change. Never attach unrelated maintenance work to an adaptive-engine progress claim.
