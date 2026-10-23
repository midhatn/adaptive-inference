# Contributing

Develop shared policy here, then contribute minimal changes to upstream engines and agents. Before editing, inspect [PLAN.md](PLAN.md), the relevant compatibility row, and [upstream/registry.json](upstream/registry.json).

1. Reproduce the problem with a focused observable contract.
2. Implement the smallest useful change without changing model quality or replaying side effects.
3. Run `python -m unittest discover -s tests -v` and `adaptive-inference demo` in a clean environment.
4. Update documentation, compatibility/evidence status and research attribution when relevant.
5. Open a PR here. Name any actual backend/client run separately from fixture tests.

New algorithms or borrowed implementations need their primary citation, source revision, license and reuse explanation in `docs/research.md`, `REFERENCES.bib` and `NOTICE` as appropriate. Keep all existing notices when moving code. Do not vendor model weights or machine-specific runtimes.

Upstream PRs should name the canonical commit/release and carry only the engine/agent-specific change. Preserve maintainers' templates and review decisions. Closed or superseded PRs are historical links, not implied merges. Update the registry after publication and after a state change. Never attach unrelated maintenance work to an adaptive-engine progress claim.
