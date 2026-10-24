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
