# Focused upstream proposals

These patches preserve prepared contributions beside canonical integration code.
The delivery ledger records their actual public state; a patch here is not proof
that it was submitted, reviewed or merged.

`strata-route-wire.patch` is the narrow correction on existing Strata PR #1493:
the route advisor must write `pcie_frac` inside `strata_tune`, where the native
wire serializer reads it, while preserving an explicit caller choice.

`strata-scheduler-reconciliation.patch` is a separate, larger reconciliation
candidate retained for inspection. It was not pushed into #1493 as part of the
narrow correction and is not represented as that PR's content. The canonical
integration's own source lock and overlays remain the reconstruction authority.

The other patches correspond to scoped documentation, catalog or reproduced
client fixes. Their executable checks and retained source inputs are linked from
`docs/integration-evidence.md`. Native-model or application qualification must
refer to a separate exact runtime receipt.

`hermes-routing-catalog.patch` preserves the 26-line catalog entry published at
Hermes PR #143827, commit `2c1411b3b12a36ac740a734f345e289faf077c3d`.
`openclaw-provider-example.patch` preserves the 46-line documentation addition
published at OpenClaw PR #182080, commit `f64d74b04b90dd123c5a1bf7cf36de7543a74309`.
Both retain public commit authorship; their original hosts are MIT-licensed.
The executable plugin, configuration composer, licenses and their exact host
interface fixtures live in the canonical paths linked by the delivery ledger.

OpenClaw #182080 was closed **unmerged** on 30 October 2026 after the same
documentation request landed through [#182565](https://github.com/openclaw/openclaw/pull/182565),
authored by SC-10749, at merge commit
`45fc29dcf159095be6251dba21c249af08a5d05a` on 27 October. The maintainer's
[landing confirmation](https://github.com/openclaw/openclaw/pull/182565#issuecomment-6450243999)
and [source audit](https://github.com/openclaw/openclaw/pull/182565#issuecomment-6449975512)
are recorded in the ledger. The merged
[provider example](https://github.com/openclaw/openclaw/blob/45fc29dcf159095be6251dba21c249af08a5d05a/docs/gateway/config-tools/provider-examples.md)
has Git blob `a5f42dff0ea4b04a7ffb820750ee9173a27265fe` and retains its upstream
MIT license. It also clarifies picker aliases and endpoint precedence when the
transport is unchanged. The original patch here remains byte-for-byte historical
source; it is not relabeled as the merged implementation or its validation.
This records documentation acceptance, not runtime scheduling, resource handoff,
agent-task completion or performance qualification.
