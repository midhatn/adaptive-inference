# Reviewed runtime timing sources

The four Python files here preserve the exact reviewed component gateway,
controller, producer fixtures and independent adversarial fixtures. They are
evidence inputs; the supported imports are the canonical runtime and tests.
`source-lineage.json` records their hashes and the promoted equivalents.

Promotion keeps gateway bytes unchanged and changes one controller comment.
Fixture assertions and control flow are unchanged. Private fixture imports map
to canonical `test_handoff` and `test_handoff_demand`; the four independent
methods use explicit shared setup helpers to avoid counting inherited producer
tests twice. The first focused promotion run exposed a missed function-local
fixture import; correcting that import did not change runtime behavior or checks.

The original demand controller and M1 package remain in the parent preservation
directory. Current runtime now includes the optional verified-owner callback;
the earlier comment-only demand promotion is an intermediate source record.

The reviewed private component passed 127 independent CPU tests plus four
independent adversarial probes. Its source manifest and review digests identify
that input review; the current canonical suite must still validate promotion.
These are fake-backend component results, with no native, IQ3_S, installed-agent
or performance qualification implied. Source hashes are not a substitute for
those acceptance gates.

All project files retain Apache-2.0 and the repository's existing notices. The
unchanged learner's Finagle reference, pinned source and license are described
in [runtime timing](../../../docs/runtime-timing.md) and the main research notes.
No model assets, private histories or native binaries are included.
