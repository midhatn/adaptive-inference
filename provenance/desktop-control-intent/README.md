# Desktop command-retention successor

This directory preserves the exact client before the local-intent change.
`control_client.before.py` came from canonical commit
`9971609ca8f5960e30f1a956daadf14d8873b5d1` and has SHA-256
`5c614b6f4b568bb6837fc9360913750c574c1ec7343ef283579c79f0744f46c9`.
It is retained comparison data, not an alternate executable client. Its
Apache-2.0 notice is preserved; the repository's root LICENSE applies.

`source-lineage.json` identifies the successor hash, eight edited controller
methods, and three added helpers. Only `control_client.py` changes in runtime.
The local intent, its feedback, and dispatch eligibility reuse the existing
Request and NetworkWorker contracts. Transport framing, socket ownership,
thread ownership, Tk timers, source identity, native/agent ownership, quality
and execution budgets do not change.

The source tests first verify the full predecessor bytes. They restore only
the named controller methods and remove only the three named helpers for an
outside-seam AST comparison. Every remaining definition must match the complete
predecessor. Additional checks preserve initializer statements, the original
tick and close ownership statements, and the exact narrow poll/render changes.
Mutations of the transport queue, timer, worker start or Stop-recording logic
are rejected. The successor's complete source hash and changed-method set are
also checked. This is an explicit reviewed successor, not a new expected hash
computed in place of the original historical comparison.

The two historical GUI fingerprint tests reuse that pinned predecessor
restoration before their original comparison; their expected hashes remain
unchanged. Python 3.12's empty definition `type_params` field is normalized by
the existing narrow test helper, with nonempty parameters still rejected.

See [the user-facing behavior, research and evidence boundaries](../../docs/desktop-control-intent.md).
The original installed acceptance and its missed first Stop click are not
modified or relabeled. The separate [successor acceptance](acceptance/README.md)
records the installed cold/full trials for the new wheel. CPU and thread
fixtures remain distinct from those real-click observations.
