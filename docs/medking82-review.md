# Review of medking82's Strata contributions

Reviewed on **2026-10-24** for Adaptive Inference. This review covers **20 upstream PRs, one merged PR into our Strata fork, and 17 public fork branches**. It identifies **80 distinct commits authored as medking82: 70 non-merge commits and 10 merge commits**. The complete reachable inventory contains 1,232 commits, largely because historical PRs still carry pre-reset upstream history. That total is an ancestry inventory, not a claim that 1,232 implementations were independently audited.

Two useful mechanisms have now been adapted into this project: fresh-observation pressure recovery and small-context output-room planning. Their portable behavior, configuration, limits and checks are documented in [portable-policies.md](portable-policies.md). Older live-cache resizing and learned-profile parking behavior were already present in the optional Strata source export; they were verified instead of reimplemented. Attribution and license references remain in [NOTICE](../NOTICE), [REFERENCES.bib](../REFERENCES.bib) and [the retained Strata MIT license](../third_party/strata/LICENSE).

The machine-readable [review inventory](../provenance/medking82-review.json) contains every PR's base/head, complete commit SHA list, all 1,232 distinct commit titles and parents, the 80 contributor commit records with changed files, all fork branch heads, discussion links, review levels, reuse decisions and source identity checks. We reviewed live metadata, changed-file inventories and discussions for all 21 PRs, then reviewed representative implementations and tests by feature family. Inherited upstream commits were enumerated, not individually audited.

## What is already incorporated

The closed [live-memory PR #726](https://github.com/Niko1221/Strata/pull/726) is **not a merged GitHub PR**. Its original head is `15a59d4785f492b4df3fb78862373a5383696450`. Our history contains the separate [authorship-preserving port `9fe67218`](https://github.com/midhatn/Strata/commit/9fe672186f21c9d87904c691d12a3de1ded64b20), retaining medking82 as Git author. The original feature range begins at historical upstream `1735d6471df29b42c26170efaac1f1446a58640f`; the reset-era GitHub base is appropriate for reproducing GitHub's commit count, but not for attributing its thousand-plus inherited commits to this contribution. The native-memory review inspected all 15 medking-authored commits in that feature range, including two upstream merges.

A second direct contribution, [midhatn/Strata #1](https://github.com/midhatn/Strata/pull/1), **was merged** as `8689b1eefedcd5eadea1c819bd4554c88c7e238f`. It contains the learned-profile identity fix `0f424025ccf70aec27fc90d994eccefae713077b` and CI adjustment `829f7cb6e16eb2e2ef924667f5c288ff4e990adb`. Our [original independent review](https://github.com/midhatn/Strata/pull/1#issuecomment-6109310453) recorded 129 focused passing checks and retained the earlier failures and no-GPU limit. Those historical results are not new tests performed by this review.

Both the port and that merge are ancestors of the exported native reference `c6b23493b01028a18a9eb685d0bb6435c6976316`. The source export reconstructs selected runtime/build/test files on upstream `7ddc17a38fe7f31637e895ecfba58c2cd43d65ec`; it is not a complete historical branch archive. See [the source lock](../integrations/strata/source-lock.json) and [integration instructions](../integrations/strata/README.md).

This review checked canonical Git/LF bytes for `serve/routing_costs.py`, `serve/server.py` and `serve/test_parking_profile_identity.py` in an already reconstructed export. All three match both the reference revision and source-lock hashes. The learned-profile identity helper's syntax tree also matches the original contribution exactly, and the parking call explicitly selects `for_parking=True`.

That distinction matters: **parking** tolerates a valid learned profile's changed ranking order and atomic-save timestamp only when the input and save paths identify the same profile. Header layout, slot count and expert membership still participate in identity; malformed/missing profiles cannot authorize reload. Paths nested in a model asset directory are handled consistently. **Routing calibration** keeps the ordinary metadata-sensitive identity, so changed learned rankings can invalidate cost estimates. This is not permission to accept arbitrary changed model assets, retain KV across different models, or weaken all runtime identity checks.

Two further contributions already entered the default branch through maintainer-authored, explicitly coauthored ports:

| Upstream commit | Contribution retained | Remaining distinction |
| --- | --- | --- |
| [`3f812458`](https://github.com/Niko1221/Strata/commit/3f81245864cf8686cf27f10cc3c1c669706699f9) | #3362 guarded legacy model-library reuse without moving weights | The PR still being open does not mean the code is absent. |
| [`e17efa53`](https://github.com/Niko1221/Strata/commit/e17efa53ce3b0822f5c274d9f9877413b548727c) | #3578 recovered-update interruption logic and tests | The maintainer keeps the existing red alert; the PR's separate recovered-history presentation is not identical. |

Both commits are ancestors of the export base. A default-branch search limited to GitHub's author-login field returned no records; commit-message/coauthor inspection found these ports. Author search alone would therefore miss credit.

## Complete PR coverage

States are a checked snapshot, not a promise that remote discussions remain unchanged. At review time, the 20 upstream PRs comprised ten open and ten closed PRs; none was marked merged. Our fork PR #1 was merged. The commit column is **all reachable commits / medking-authored commits**, including contributor-authored merges. Full 40-character identities are in the JSON inventory.

| PR and title | State | Head | Commits | Decision |
| --- | --- | --- | ---: | --- |
| [#724](https://github.com/Niko1221/Strata/pull/724) Add local PDF, Word and Excel attachments with screenshot previews | closed | `fe2645aece45` | 629 / 1 | Historical predecessor; review and reuse decision uses rebuilt #1119. |
| [#726](https://github.com/Niko1221/Strata/pull/726) Add opt-in live cache resizing and desktop resource presets | closed | `15a59d4785f4` | 1167 / 15 | Already ported into exported native source; adapt fresh-sample pressure recovery in portable resource_policy.py. |
| [#727](https://github.com/Niko1221/Strata/pull/727) Add opt-in durable chat history, legacy import and browser compaction | closed draft | `23f4e24809cc` | 848 / 3 | Historical predecessor; review and reuse decision uses rebuilt #1136. |
| [#1075](https://github.com/Niko1221/Strata/pull/1075) web: follow streaming Thinking and preserve reading position | closed | `4b04d1ed9926` | 1153 / 1 | Historical predecessor; review uses rebuilt #1106. |
| [#1106](https://github.com/Niko1221/Strata/pull/1106) web: follow streaming Thinking and preserve reading position | closed | `2aeb31cced46` | 1 / 1 | Keep as UI-specific reference; no gateway rendering surface to patch. |
| [#1112](https://github.com/Niko1221/Strata/pull/1112) web: make MCP tool activity readable and collapsible | closed | `95b74547591f` | 1 / 1 | Keep as UI-specific reference; no engine scheduling change. |
| [#1119](https://github.com/Niko1221/Strata/pull/1119) Add local PDF, Word and Excel attachments with screenshot previews | closed | `ef2472ec007c` | 1 / 1 | Future optional local document adapter; do not add document parsers to inference scheduling. |
| [#1136](https://github.com/Niko1221/Strata/pull/1136) Add opt-in durable chat history, legacy import and browser compaction | closed draft | `64d119cd602d` | 1 / 1 | Reuse exact paginated recall and persistence/optimistic-revision principles if adding archive retrieval; do not import its entire summarizer. |
| [#1144](https://github.com/Niko1221/Strata/pull/1144) serve: add opt-in instruction skills to Chat | closed draft | `f3a22f9fc017` | 1 / 1 | Future opt-in client adapter; preserve operator-bound catalog and explicit final-user selection. |
| [#2035](https://github.com/Niko1221/Strata/pull/2035) [GUI] Add Optional Windows Tray For Local Model Control | closed | `7ca4ab66daf0` | 7 / 7 | Historical predecessor of #3365, not a second independent implementation. |
| [#3361](https://github.com/Niko1221/Strata/pull/3361) [GUI] Scope Preparation Errors To The Selected Model | open | `99bdafe332e1` | 2 / 2 | UI-only bug fix: selected-model errors scoped by exact identity. |
| [#3362](https://github.com/Niko1221/Strata/pull/3362) [GUI] Reuse Legacy Model Libraries Through A Valid Native Data Root | open | `1eae8377e7c7` | 2 / 2 | Already incorporated into current upstream base by coauthored port 3f812458; do not reimplement or move weights. |
| [#3363](https://github.com/Niko1221/Strata/pull/3363) [GUI] Forward Composer Effort To Supported API Models | open | `fe764fa1ab87` | 3 / 3 | Retain unchanged caller effort in gateway; do not copy provider-specific remapping. |
| [#3365](https://github.com/Niko1221/Strata/pull/3365) [GUI] Add Optional Windows Tray For Local Model Control | open | `558013342d27` | 6 / 6 | Optional future Windows owner/UI package; keep portable scheduler independent. |
| [#3373](https://github.com/Niko1221/Strata/pull/3373) [GUI] Add Opt-In Local Model Extension Outside The App Installation | open | `5d93f82de0a0` | 7 / 7 | Reuse requested/observed/identity distinctions, not App preload or UI injection in portable gateway. |
| [#3532](https://github.com/Niko1221/Strata/pull/3532) [GUI] Export Official App Contracts For Tray And Web Companions | open | `a251782251f6` | 3 / 3 | Reuse bounded allowlisted capability and provenance concepts; no stock App API or native admission guarantee claimed. |
| [#3578](https://github.com/Niko1221/Strata/pull/3578) [GUI] Keep Recovered Update Interruptions In History | open | `4532a840712c` | 4 / 4 | Logic/test port already in upstream base; remaining PR separation of recovered history is UI-only. |
| [#3612](https://github.com/Niko1221/Strata/pull/3612) [GUI] Add Opt-In Windows Close To Tray | open | `6b8363ad8145` | 5 / 5 | Future Windows UI option, not portable runtime/process owner replacement. |
| [#3668](https://github.com/Niko1221/Strata/pull/3668) [Docs] Share Companion Codex Reload Fix And Verified 200K Evidence | open | `4415569330ae` | 1 / 1 | Reference for explicit catalog-generation acknowledgment; no stock Strata or current gateway patch. |
| [#3684](https://github.com/Niko1221/Strata/pull/3684) [GUI] Preserve Output Room In Small Agent Contexts | open | `f273ef65e8f4` | 2 / 2 | Adapt small-context safety arithmetic in explicit host planner; preserve requested output and require compaction/recount instead of silently clamping. |
| [midhatn/Strata #1](https://github.com/midhatn/Strata/pull/1) Fix parking identity across learned expert profile saves | merged | `829f7cb6e16e` | 2 / 2 | Already merged and exported; retain parking-only membership identity and strict calibration identity. |

The explicit replacement chains are **#724 → #1119**, **#727 → #1136**, **#1075 → #1106**, and **#2035 → #3365**. The successor descriptions or author discussion establish these relationships. They are not four additional independent implementations.

The maintainer's October 6 history-reset notice on #724, #726, #727 and #1075 explicitly explains automatic closure and says it was not a rejection. For #726/#727, today's changed-file API returns an empty list even though the preserved contribution objects are nonempty. We retained that API result as a limitation and used Git ancestry and the original/rebuilt source. For other closed PRs without an explanatory discussion, this review does not invent a closure reason.

## Source review and reuse decisions

### Live memory and pressure recovery: #726

The pinned policy separates a proposed capacity from a matching native acknowledgment, tracks advancing complete observations, rejects stale/replayed data, and requires sustained recovery before relaxing pressure. Its native resizing protocol has capability checks, one pipe owner, one pending operation and request/epoch boundaries; a generic HTTP gateway cannot fabricate that actuator. The later exported descendant adds Windows commit-aware sizing, lease constraints and more general activity observations. Copying the old branch wholesale would discard those additions.

The new portable `HeadroomPolicy` adapts the temporal admission principle: pressure or unknown evidence closes new dispatch, then fresh observations above a configured margin must persist for a configured duration. The gateway samples while idle and active and rechecks before dispatch; it does not interrupt the active owner, resize a native cache, change quality settings or claim a reservation. The original author's throughput and High-thinking measurements remain their hardware-specific reports, not our performance results. [Pinned policy source](https://github.com/medking82/Strata/blob/15a59d4785f492b4df3fb78862373a5383696450/serve/resource_presets.py).

### Output room and provider capability: #3684 and #3363

#3684 fixes an actual small-context problem: fixed safety slack can leave a one-token output ceiling, including after tool replies. We reused its bounded safety-margin arithmetic in an explicit planner, while retaining the caller's full requested output. When it does not fit, the planner returns a compaction/recount target or `no_room`; it does not silently reduce reasoning or answer allowance. The target calculation recomputes the changing margin at the candidate prompt length. Complete rendered prompt counts and the backend's own admission check remain necessary. [Pinned arithmetic](https://github.com/medking82/Strata/blob/f273ef65e8f4548125f3e72833cd61019b82080f/apps/desktop/scripts/harness-budget.mjs).

#3363 forwards composer effort only after saved or host-probed capability allows it; selection-supplied capability metadata is not authority. Its OpenRouter and other OpenAI-chat mappings are protocol-specific. Our gateway already forwards explicit caller effort, so importing those mappings generically would risk changing meaning. Responses and Anthropic handling should not be inferred from that direct-chat fix. [Pinned provider implementation](https://github.com/medking82/Strata/blob/fe764fa1ab87ad76f5afec5839d4dd8e347ce0d8/apps/host/server/model-providers.mjs).

### Durable archive and instruction skills: #1136 and #1144

#1136 provides transactionally saved SQLite archives, optimistic revisions to prevent stale-tab overwrites, atomic import with existing destination IDs winning, and bounded read-only search/recall. Large records expose exact continuation offsets instead of silently losing their remainder. Historical tool calls stay data. Its browser compaction keeps recent turns and original archives, admits storage before summary calls, counts the real template, bounds chunking and refuses a still-oversized result. The 100 MB database limit includes indexing overhead; persistence does not establish backup or complete retrieval. [Archive](https://github.com/medking82/Strata/blob/64d119cd602ddc439c311dedf61fda460f2785ef/serve/chat_archive.py), [recall](https://github.com/medking82/Strata/blob/64d119cd602ddc439c311dedf61fda460f2785ef/serve/chat_memory.py), [browser compaction](https://github.com/medking82/Strata/blob/64d119cd602ddc439c311dedf61fda460f2785ef/serve/web/chat-context.js).

Exact archive addressing and transactional persistence are useful future integration pieces. The older browser implementation inserts generated history as a system message; that behavior must not be copied into a host that distinguishes current authority from historical evidence. It is not a substitute for this project's provenance-bound reference preservation, exact token admission, or unqualified multi-generation semantic fidelity.

#1144 uses an operator-bound, bounded MCP catalog and requires an explicit skill name in the final human user message. It revalidates the catalog, checks cancellation, excludes catalog/read helpers from model tools, appends instructions at user level and does not grant new tools. Counting and generation share preparation; the count endpoint explicitly rejects images. This is a client-side instruction feature, not a native scheduler capability or a universal MCP skill protocol. [Skill implementation](https://github.com/medking82/Strata/blob/f3a22f9fc0178613fc54ee18fd8d7c1765160de7/serve/skills.py).

### Attachments and readable UI: #1119, #1106, #1112 and #3361

#1119 is a bounded document-processing vertical slice: authenticated same-origin admission, strict lengths and file types, serial browser extraction, a separate worker with time/memory/concurrency limits, guarded Office ZIP/XML handling, and explicit truncation. PDF pages without text can be rendered under page/image limits; DOCX covers body paragraphs/tables and XLSX reads cached values without executing formulas. This is a reasonable optional agent attachment adapter, but adding these parser dependencies to a scheduling gateway is unnecessary. It does not establish that arbitrary hostile documents are harmless, and its reported Windows validation does not qualify Linux worker containment. [Extractor](https://github.com/medking82/Strata/blob/ef2472ec007c3aaed2099610298040f82f1dc4ca/serve/file_extract.py).

#1106 preserves a user's reading position while following streaming thinking only when already following the bottom. #1112 bounds JSON parsing, escapes displayed content, accepts only suitable HTTP(S) result links and preserves grouped disclosure/focus during repaint. #3361 scopes retained preparation errors to the selected model's identity. These are concrete UI improvements; this repository currently has no matching chat-rendering surface to patch. Their author-reported browser checks are not engine benchmarks.

### Companion ownership and capability export: #3365, #3373 and #3532

The Tray and extension form an optional Windows integration, with the managed Tray as the sole lifecycle owner. Requests drain before state changes; selected settings and observed effective settings remain separate. The extension uses fresh owner/model/API identity, one claimed request slot, durable terminal acknowledgment and no automatic mutation replay after interruption. Its UI bridge is version/shape bound, outside the official installation. It should not replace the portable gateway with Windows preload, DOM injection, or private owner-state assumptions. [Tray contract](https://github.com/medking82/Strata/blob/558013342d27bdde5e55ff05437369221d1e61b9/tools/windows-tray/README.md), [extension owner](https://github.com/medking82/Strata/blob/5d93f82de0a00e123ffc23b41315584d744f4978/tools/local-model-extension/owner_api.mjs).

#3532 inspects an explicitly trusted installed App, checks source and route anchors, fingerprints Host/Control, rechecks identity around reads and projects metadata through nested allowlists. It separates capability reporting from model residency and admission. This aligns with our source/capability boundary, but it is not an upstream universal plugin API, a permission grant, or a sandbox for hostile imported modules. Its direct child timeout is not evidence of a portable descendant-tree cleanup guarantee. [Metadata contract](https://github.com/medking82/Strata/blob/a251782251f686602e84ae7299f99168729269ab/tools/app-surface-contract/contract.mjs).

The latest #3365/#3373 reports discuss separate staged Harness tests linked to #3684. Their submitted source heads do not contain that staged Harness fix. Combined checks and receipts must not be counted twice or attributed to an unchanged production package.

### Window lifetime, updates and client reload: #3612, #3578 and #3668

#3612 hides a Windows main window only while an explicitly configured, exact executable owner remains alive; it retains the process handle rather than trusting a reusable PID. Missing/dead owner or unsuccessful hide leaves normal Close available, and explicit quit uses existing shutdown. This is a useful UI-lifetime mechanism, not a replacement for engine job containment or cross-platform ownership. The author's installed-window checks are separate from unrun logoff/updater/owner-exit cases. [Window policy](https://github.com/medking82/Strata/blob/6b8363ad8145220f23cf338d88e28339d89c1130/apps/desktop/src-tauri/src/window_lifecycle.rs).

#3578's upstream port already distinguishes a prior update interruption settled by a later finished update of the same component. The remaining PR changes the presentation to recovered history. This is neither new inference control nor a reason to suppress unresolved update errors.

#3668 documents a fix for an **external companion**, against its own base `f20a77dc7743865420d9819261de2d6f8092374d`, not stock Strata. It clears reload-needed only after stable catalog/config generation and bound Desktop-process observations agree; unknown or stale evidence retains the warning. The reported 194,560 effective tokens reflect a 204,800-token selected catalog capacity, not consumption of that many tokens or a full-window stress test. The reusable idea is explicit observed acknowledgment, not editing a live client's private configuration or importing deployment-specific startup assumptions. [Scope and evidence](https://github.com/medking82/Strata/blob/4415569330ae5f2dff8b227d41ea71a4a53161ad/docs/integrations/codex-sync-reload/README.md).

## Independent checks and limits

The team independently ran **126 unique pinned-upstream CPU/fixture tests, with two explicit skips**:

| Source | Passed | Skipped | Scope |
| --- | ---: | ---: | --- |
| #726 memory policy and resource presets | 81 | 0 | Pure policy/observation fixtures |
| #3684 small-context budget | 9 | 1 | Exact dependency fixture; installed Harness not supplied |
| #3532 asset/contract export | 19 | 0 | Source, metadata and synthetic export checks |
| #3373 owner API and bridge | 17 | 1 | Local fixture HTTP/IPC; optional cross-language Tray not supplied |

Initial audit setup failures from incomplete extracted dependencies and a changed fixture newline were retained, then resolved by restoring exact pinned source bytes without editing upstream tests. The final counts above count each unique test once. New portable-module and gateway/CLI integration checks are reported separately; they are not added to upstream author test totals.

No installed App, external client profile, GPU workload, model generation, memory-pressure benchmark or throughput comparison was performed by this review. Historical native results remain source-scoped author reports or previously recorded project evidence. Neither the metadata audit nor these tests establish general autonomy, lossless compaction, native preemption, cross-platform process cleanup, or arbitrary workload fit.

## Reproducing the inventory and next reuse

For each PR, retrieve its recorded base and head and enumerate `git log <base>..<head>` with full SHA, parents, author and subject. Deduplicate by full SHA. All 21 counts matched the live GitHub commit counts. A PR-commits API's page/size cap is insufficient for the old reset-history ranges. Compare fork branches against the pinned default head; classify multi-parent entries separately and never count their first-parent imported changes as entirely contributor-authored features. The JSON records source-review levels so metadata coverage is not confused with implementation qualification.

For a new integration, reuse the already exported identity/live-memory code first. The implemented portable recovery gate and output planner are the immediate cross-engine adaptations. Exact paginated archive retrieval, bounded document extraction, and an optional source-bound UI capability adapter remain concrete future candidates for the always-on resource coordinator described in [the controller roadmap](always-on-controller.md). These pieces should support agents yielding to foreground work and coordinating their own tools through explicit adapters, rather than require a particular desktop client. The Windows companion packages should remain optional and independently qualified.

The [collaboration invitation](https://github.com/midhatn/adaptive-inference/issues/1) credits both the live-cache port and merged profile fix. The review does not imply endorsement, maintainer agreement to a plugin API, or a commitment by the contributor to support this independent project.
