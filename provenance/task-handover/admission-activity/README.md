# Admission-wait activity: current behavior and preserved history

The current bridge reports a verified, operation-free resource wait to the
already pinned Hermes activity writer. It preserves the original task deadline,
logical owner, live SDK lease, interruption checks and 15-second cadence. This
does not report generated tokens or completed tools. Source tests and any later
installed IQ3_S qualification have separate scopes.

This archive retains the exact predecessor activity module and two source-test
readers from `aec8d9070f1509268e7d9b3e9944c14c3f374e75`. The existing complete-file
byte/AST projection exposes those predecessors to historical checks. Only a
declared complete successor is transformed; unknown inputs continue into the
unchanged historical validators and are refused. The two reader changes reverse
byte-for-byte, preserving every previous assertion and historical manifest.
The other 59 runtime modules retain their recorded identities. No retained
runtime is executed by source projection.

The implementation reuses the repository's existing source-preservation pattern
and cross-version AST fingerprint. Python's [AST documentation](https://docs.python.org/3.11/library/ast.html)
explains why the syntax representation is version-specific; the existing
normalizer still permits only its declared empty-field difference. New runtime
behavior is covered by the separate admission-activity and existing recovery
tests. A preserved historical pass does not validate this changed module.

Research examined Hermes's [activity configuration](https://hermes-agent.nousresearch.com/docs/user-guide/configuration#turn-liveness-watchdog)
and [merged MoA activity bridge](https://github.com/NousResearch/hermes-agent/pull/131916),
which credits PR110056 by kokhlo and PR110041 by KoNit-K. Those sources informed
forwarding verified activity to the existing watchdog, not disabling the
watchdog. MoA code was not copied. The adapter relies on the existing pinned
private SDK interface at `14e1e43a23761b369641208e204365cd6cb9399d`; it does not
claim a public plugin API. Hermes retains its MIT authorship and license. The
new bridge and source-preservation helpers are repository-authored Apache-2.0.

Use ordinary unittest discovery for `test_admission_activity_lineage.py` and
`test_desktop_admission_activity.py`, followed by the affected historical source
and recovery suites. The existing [PyPA build frontend](https://build.pypa.io/en/stable/)
and `provenance/check_distribution.py` verify a fresh source archive and wheel.
Installation and native acceptance require their own current results.
