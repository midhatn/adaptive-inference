# Installed desktop source promotion

This directory preserves the implementation inputs used to install the existing
Windows host, retained GUI and bounded Hermes report consumer as one composition.
The source packet is identified by manifest SHA-256
`c6cc2f022e7fdba157f1f19c2a644f8e69fc8d8a9eb3c665a6770fab3027b049`.
That packet supplied the accepted full06 workflow; its acceptance does not by
itself qualify a new installation or deployment profile.

`source-lineage.json` maps each promoted module to its complete preserved source
and hash. The two composition classes are preserved as class fragments because
their enclosing private launch scripts included local deployment constants.
Those constants are replaced by explicit public configuration. The actual used
class methods remain inspectable here. No private paths, credentials, model
files, compiled runtime or SDK installation are included.

The runtime changes are:

- Canonical `adaptive_inference.desktop` imports replace flat module imports.
- Host job/activity fallbacks use those same installed modules. Composition
  passes the exact already-containing job object to the host, adapter and GUI.
- `composition.py` extracts the retained preparation/readiness/disposal methods
  into one shared host. It starts with an acknowledged Pause. Native parking
  completes before worker and GUI launch. Ordinary completed-host lifetime is
  separate from the task's 900-second limit and qualification's emergency guard.
- The report worker uses regular installed package contents, explicit SDK and
  dependency inputs, and the extracted existing report contract. It no longer
  imports code from a checkout or `examples` directory. The original oracle,
  eight-request bound, quality fields, feedback and operation ledger remain.
- GUI installation changes bind both package initializers and all executed GUI
  modules, retain the exact full Python process, and verify child import origins.
  The separately reviewed terminal presentation removes an irrelevant waiting
  message after acceptance/cancellation. See the GUI source-lineage fixture.

`tests/test_desktop_source_lineage.py` checks preserved input hashes and the
declared runtime boundaries. The existing native-owner/persistent-host,
desktop-lifecycle and report tests are relocated with canonical imports.
The historical report-hold source-diff tests are replaced by the current
promotion's source checks; the actual SQLite report-hold cases are retained.

Original integration code is Apache-2.0. The retained Strata memory-policy
planner test source is MIT; both original license texts are in `licenses/`.
Existing medking82/Strata attribution remains in the root `NOTICE` and research
references. No Hermes SDK runtime code is copied: its pinned MIT source can be
reconstructed using the repository's existing current-source supplement.

Research and installed usage are documented in
[the deployment guide](../../docs/installed-desktop.md). Component tests establish
software contracts. New cold/full real-process acceptance must bind the actual
installed wheel, explicit profile and unchanged IQ3_S assets separately.

The subsequent [installed cold01/full01 acceptance record](acceptance/README.md)
now supplies that separate evidence for the exact tested wheel/profile. Its
35 cold and 47 full independent checks do not change the preserved source
lineage above. The full case retains a missed first Stop click, followed by a
successful second click and normal cleanup. `export_acceptance.py` selects the
audited terminal facts using unchanged v7 sanitization helpers; its focused
tests are exposed through `provenance/test_installed_desktop_acceptance.py` in
the existing provenance discovery. No source-promotion fixture is treated as
live acceptance, and no single-click reliability or reboot claim is made.
