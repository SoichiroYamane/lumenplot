# LumenPlot v1.0 requirement traceability

- Status: pre-alpha publication; Phase-1A/B, bounded Phase-2A/2B implementation/local contract evidence, and the Phase-3A2 private-helper one-wheel build with same-wheel CPython 3.11–3.14 runtime evidence exist, while the Phase-3B first strict-slice implementation (public strict-mode Matplotlib backend over the private whole-frame render seam, with local contract-test evidence) exists and the merged hybrid-explicit fallback slice plus its strict-style fixture reconciliation add bounded local contract-test evidence (PRs #26/#28/#29/#32), extended by bounded profile-selection and canvas-authority contract tests (`test_phase3b_profiles.py`, `test_phase3b_authority.py`), the merged native-authority seam suite (PR #41), the merged PRAC-A-D decorated-axes lane (PR #63), which adds bounded native rendering of `axison=True` axes decorations per ADR 0015 §4a (`TestDecoratedAxesSpec`, `TestDecoratedAxesEligibility`), and the merged W1 "static geometry" wave (PRs #68/#69/#70, integrated by #71), which flips `LP-FUNC-032`/`033`/`034` to implemented-with-bounded-evidence below — accelerated-native delivery, hybrid-explicit-as-default, adapter authority/revision closure, the full strict error-fixture set, mixed vector/raster output, packaged public-backend runtime evidence, benchmark, support, or release completion remain pending and are claimed for nothing. On 2026-08-25 the architecture authority (maintainer) adopted nine additional requirement rows (`LP-FUNC-032`–`LP-FUNC-039`, `LP-MPL-020`) from [`matplotlib-parity-requirements-draft.md`](matplotlib-parity-requirements-draft.md); they are recorded below with honestly pending results (`Not implemented`), and their adoption is not an implementation result. On the same date the maintainer fixed their acceptance quality bar — native rendering must match the current Matplotlib backend (Agg) output; canonized on 2026-08-26 as the Section 5.4 quality oracle of [`matplotlib-parity-requirements-draft.md`](matplotlib-parity-requirements-draft.md) and reflected in the Target cells and evidence plans below. On 2026-08-26 the W1 workstream landed LP-FUNC-032/033/034 (fill, bar, step drawstyles) with §5.4 Agg-oracle parity fixtures green (PRs #68/#69/#70; mixed-workload integration #71), flipping exactly those three result cells from `Not implemented` to bounded implemented evidence; every other adopted row remains honestly pending. On 2026-08-26 the Phase-1B view-history state substrate gained bounded local contract evidence in `crates/lumenplot/tests/history.rs`, flipping exactly `LP-FUNC-008`, `LP-UX-012`, and `LP-UX-013` below to implemented-with-bounded-evidence over the accepted [API 0001](../architecture/api-0001-native-scene-state.md) canonical-view surface; gesture routing, keyboard, and animated transitions remain pending.
- Source of truth: `docs/requirements/lumenplot-v1.0.md` and its Appendix A coverage matrix.
- This document maps every stable requirement entry to an evidence type and records the current result separately from its target. [ADR 0010](../adr/0010-phase1-native-core-facade-contract.md), its narrow [ADR 0011](../adr/0011-phase1b-facade-namespace-observation-traits.md) amendment, and the updated [API 0001](../architecture/api-0001-native-scene-state.md)/[API 0002](../architecture/api-0002-errors-capabilities-fallback.md) record the accepted Phase-1 native core/facade contract; [ADR 0012](../adr/0012-private-line-frame-and-png-contract.md) records the accepted private Phase-2A/2B line-frame and PNG contract; [ADR 0013](../adr/0013-hidden-facade-private-python-line-png.md) records the staged Phase-3A hidden facade/private helper contract. They do not change any product result below.

## Status rules

| Result | Meaning |
| --- | --- |
| `Not implemented` | The full requirement has not been closed by product implementation evidence in this bundle; a bounded Phase-1 slice may exist without closing the row. |
| `Implemented (bounded Phase-3B local contract evidence: ...)` | The bounded Phase-3B behavior is exercised by the named merged test classes in this repository; the full requirement, platform matrix, and any release claim stay open. |
| `Not measured` | A benchmark or numeric target has no product measurement in this bundle. |
| `environment required` | Platform, GPU, driver, display, or present evidence requires a declared test environment; it is not inferred from source research. |
| `Reference only` | A candidate technology or dated version is not a support claim or dependency pin. |
| `Planning only` | A phase placement is not an implementation result. |
| `Not applicable` | A non-goal is deliberately outside v1. |

## Acceptance gate vocabulary

| Gate family | Evidence expected |
| --- | --- |
| `AT-FUNC-*` | Deterministic functional test of behavior and state transition. |
| `AT-SEM-*` | Semantic, property, invariant, or topology test. |
| `AT-EXPORT-*` | Structural output, vector-content, or golden export test. |
| `AT-LIFE-*` | Lifecycle, thread, FFI, environment, device-loss, or reentrancy test. |
| `AT-SEC-*` | Static security, artifact provenance, size/overflow, license, or reproducibility review. |
| `AT-BENCH-*` | Benchmark with fixed fixture, warm-up, sample count, quantiles, and machine manifest. |
| `AT-MPL-*` | Matplotlib adapter, profile, text, or package compatibility test. |
| `AT-RELEASE-*` | Release checklist evidence review. |
| `AT-REVIEW-*` | Architecture, scope, dependency, UX, phase, or documentation review. |

Adopted 2026-08-25 with the Matplotlib major-feature rows ([`matplotlib-parity-requirements-draft.md`](matplotlib-parity-requirements-draft.md)):

| Gate family | Evidence expected |
| --- | --- |
| `AT-FUNC-FILL` | Deterministic functional test of polygon fill rendering (`fill` / `fill_between` / `stackplot`) and its state transitions. |
| `AT-FUNC-BAR` | Deterministic functional test of rectangle bar/histogram rendering (fill + stroke semantics). |
| `AT-FUNC-DRAWSTYLE` | Deterministic functional test of `steps-pre`/`steps-post`/`steps-mid` drawstyle geometry. |
| `AT-SEM-COMPOSITING` | Cross-primitive z-order and alpha compositing invariant test. |
| `AT-FUNC-POLAR` | Deterministic functional test of polar-projection transform and clip behavior. |
| `AT-FUNC-DATE-AXIS` | Deterministic functional test of unit/date-aware tick locator and formatter behavior. |
| `AT-FUNC-QUIVER` | Deterministic functional test of quiver arrow glyph geometry. |
| `AT-SEM-SCALE-EXT` | Scale-extension property/invariant test (symlog/logit transforms). |
| `AT-MPL-ELIGIBILITY` | Matplotlib strict-mode eligibility whitelist governance and growth-boundary test. |

## Accepted bounded contract records

The following records are accepted architecture/API contracts. Phase-1A/B and
the bounded Phase-2A/2B implementation have local contract evidence, and the
Phase-3A record has the Phase-3A2 private-helper one-wheel build and
same-wheel CPython 3.11–3.14 runtime evidence. None of these bounded
records changes the requirement registry's `Not implemented`, `Not measured`,
or `environment required` results.

| Contract | Record | Current status |
| --- | --- | --- |
| Phase-1 native core and minimal facade | [ADR 0010](../adr/0010-phase1-native-core-facade-contract.md) | Accepted contract; Phase-1 implementation and local contract evidence recorded |
| Phase-1B facade namespace and observation traits | [ADR 0011](../adr/0011-phase1b-facade-namespace-observation-traits.md) | Accepted amendment; Phase-1B implementation and local contract evidence recorded |
| Phase-1 Scene, view, and owned data surface | [API 0001](../architecture/api-0001-native-scene-state.md) | Accepted contract; Phase-1 local implementation evidence recorded |
| Phase-1 engine error ownership and mapping | [API 0002](../architecture/api-0002-errors-capabilities-fallback.md) | Accepted contract; Phase-1 mapping/local failure evidence recorded |
| Phase-2A/2B private line frame and deterministic PNG | [ADR 0012](../adr/0012-private-line-frame-and-png-contract.md) | Accepted amendment; bounded implementation and local evidence recorded; full-v1 export pending |
| Phase-3A hidden facade and private Python helper | [ADR 0013](../adr/0013-hidden-facade-private-python-line-png.md) + [ADR 0014](../adr/0014-phase3a2-pinned-manylinux-wheel-evidence.md) | Accepted staged contract; Phase-3A2 private-helper one-wheel build and same-wheel CPython 3.11–3.14 runtime evidence recorded in CI-local evidence; public adapter/package surface and Phase-3B public Matplotlib contract open |
| Phase-3B public Matplotlib backend first slice | [ADR 0015](../adr/0015-phase3b-public-matplotlib-adapter-contract.md) + [API 0005](../architecture/api-0005-phase3b-public-matplotlib-backend-surface.md) | Accepted contract; first strict-slice implementation merged (private `render_frame_png` whole-frame seam, public strict-mode `lumenplot_mpl.backend`, local contract and entry-point-discovery test evidence); PR #32 adds the hybrid-explicit whole-frame fallback slice, terminal-failure guards, entry-point manifest, wheel/entry-point evidence job, and reconciled strict-style fixtures as local contract-test evidence; profile-selection, authority/revision, full error-fixture, mixed-output, and packaged public-backend runtime evidence remain pending |

## Coverage summary

- Requirement entries: **232**.
- Normative `MUST`/`MUST NOT` entries requiring closure: **153**.
- Classification counts: MAY=9, MUST=116, MUST NOT=37, NON-GOAL=6, PHASE=6, REFERENCE=13, SHOULD=45.
- Stable families: `DATA` (10), `EXPORT` (10), `FUNC` (39), `LOD` (7), `MPL` (20), `PERF` (16), `PLAT` (12), `PROD` (18), `QUAL` (28), `REL` (14), `RENDER` (10), `SEC` (8), `TEXT` (7), `UX` (33).
- Evidence gates referenced: **101**.

The 2026-08-25 adoption of the Matplotlib major-feature rows added nine entries
(`LP-FUNC-032`–`LP-FUNC-039`, `LP-MPL-020`; three normative, six advisory) and nine gate names;
the pre-adoption baseline was 223 entries / 150 normative / 92 gates.

Every `MUST` and `MUST NOT` entry appears in the registry below with at least one acceptance gate. The `Result` column is not a pass/fail claim; it is the honest status of the full requirement. A bounded Phase-1 implementation does not automatically promote a row to closure.

## Complete requirement registry

| ID | Class | Target | Phase | Release | Evidence gate(s) | Result |
| --- | --- | --- | --- | --- | --- | --- |
| `LP-PROD-001` | `REFERENCE` | product identity | 0 | product review | `AT-REVIEW-PRODUCT` | Reference only — no support or implementation claim |
| `LP-PROD-002` | `MUST` | published support matrix with evidence cells | 3 | v1 | `AT-LIFE-PLATFORM` | environment required — Not implemented |
| `LP-PROD-003` | `MUST` | shared semantic frame and export checks | 2 | v1 | `AT-SEM-LAYOUT`, `AT-EXPORT-STATE` | Not implemented |
| `LP-PROD-004` | `SHOULD` | dependency review | future | non-blocking | `AT-REVIEW-DAG` | Not implemented |
| `LP-PROD-005` | `REFERENCE` | product review | 0 | product review | `AT-REVIEW-PRODUCT` | Reference only — no support or implementation claim |
| `LP-FUNC-001` | `MUST` | deterministic Line2D rendering | 1 | v1 | `AT-FUNC-LINE2D` | Not implemented |
| `LP-FUNC-002` | `MUST` | stable ordering and visibility | 1 | v1 | `AT-FUNC-SERIES` | Not implemented |
| `LP-FUNC-003` | `MUST` | axis, tick, and label correctness | 1 | v1 | `AT-FUNC-AXIS` | Not implemented (bounded Phase-3B local contract evidence: PR #63; native major-gridline/major-tick/spine rendering for eligible decorated `axison=True` axes per ADR 0015 §4a — `TestDecoratedAxesSpec`, `TestDecoratedAxesEligibility` in `test_phase3b_backend.py`; axis labels and date formatting remain unclosed) |
| `LP-FUNC-004` | `MUST` | log-axis behavior | 1 | v1 | `AT-FUNC-LOG-AXIS` | Not implemented |
| `LP-FUNC-005` | `MUST` | native interaction | 1 | v1 | `AT-FUNC-PAN-ZOOM` | Not implemented |
| `LP-FUNC-006` | `MUST` | anchor-preserving zoom | 1 | v1 | `AT-FUNC-PAN-ZOOM` | Not implemented |
| `LP-FUNC-007` | `MUST` | bounded view selection | 1 | v1 | `AT-FUNC-BOX-ZOOM` | Not implemented |
| `LP-FUNC-008` | `MUST` | deterministic history transitions | 2 | v1 | `AT-FUNC-HISTORY` | Implemented (bounded Phase-1B local contract evidence: `home_restores_the_stored_canonical_view`, `interactive_viewport_changes_leave_the_canonical_view_stable`, and the view-transition no-op/abortion fixtures in `crates/lumenplot/tests/history.rs` — stored canonical view survives pan/zoom, Home restores it, canonical replacement re-homes it, revisions advance exactly once per changed commit; gesture routing and animated transitions remain open) |
| `LP-FUNC-009` | `MUST` | Legend hit-testing and state changes | 2 | v1 | `AT-FUNC-LEGEND` | Not implemented |
| `LP-FUNC-010` | `MUST` | basic scientific inspection | 2 | v1 | `AT-FUNC-CURSOR` | Not implemented |
| `LP-FUNC-011` | `MUST` | Plot State and export consistency | 2 | v1 | `AT-FUNC-GRID` | Not implemented |
| `LP-FUNC-012` | `MUST` | annotation acceptance fixture | 2 | v1 | `AT-FUNC-ANNOTATION`, `AT-EXPORT-ANNOTATION` | Not implemented |
| `LP-FUNC-013` | `MUST` | structural PNG output | 2 | v1 | `AT-EXPORT-PNG` | Not implemented |
| `LP-FUNC-014` | `MUST` | structural PDF output | 2 | v1 | `AT-EXPORT-PDF-VECTOR` | Not implemented |
| `LP-FUNC-015` | `MUST` | package/import/FFI smoke tests | 1-2 | v1 | `AT-LIFE-FFI`, `AT-MPL-LOADER` | Not implemented |
| `LP-FUNC-016` | `MUST` | launch, interaction, close, and package tests | 1-2 | v1 | `AT-FUNC-VIEWER`, `AT-LIFE-VIEWER` | Not implemented |
| `LP-FUNC-017` | `SHOULD` | explicit capability status | 5 | v1 non-blocking | `AT-FUNC-SCATTER` | Not implemented |
| `LP-FUNC-018` | `SHOULD` | explicit capability status | 5 | v1 non-blocking | `AT-FUNC-MARKER` | Not implemented |
| `LP-FUNC-019` | `SHOULD` | scope declaration | 5 | v1 non-blocking | `AT-FUNC-ERRORBAR` | Not implemented |
| `LP-FUNC-020` | `SHOULD` | scope declaration | 5 | v1 non-blocking | `AT-FUNC-SECONDARY-AXIS` | Not implemented |
| `LP-FUNC-021` | `SHOULD` | future SVG structural output | 2 | v1 non-blocking | `AT-EXPORT-SVG` | Not implemented |
| `LP-FUNC-022` | `MAY` | future candidate | future | future | `AT-REVIEW-SCOPE` | Not implemented |
| `LP-FUNC-023` | `MAY` | future candidate | future | future | `AT-REVIEW-SCOPE` | Not implemented |
| `LP-FUNC-024` | `MAY` | future candidate | future | future | `AT-REVIEW-SCOPE` | Not implemented |
| `LP-FUNC-025` | `NON-GOAL` | scope review | future | excluded | `AT-REVIEW-SCOPE` | Not applicable — scope exclusion |
| `LP-FUNC-026` | `MAY` | future candidate | 5+ | future | `AT-REVIEW-SCOPE` | Not implemented |
| `LP-FUNC-027` | `MAY` | future candidate | future | future | `AT-REVIEW-SCOPE` | Not implemented |
| `LP-FUNC-028` | `SHOULD` | measurement tooling | 5 | v1 non-blocking | `AT-FUNC-MEASUREMENT` | Not implemented |
| `LP-FUNC-029` | `MAY` | optional capability | 5 | optional | `AT-FUNC-SERIES-PANEL` | Not implemented |
| `LP-FUNC-030` | `MUST NOT` | UX review | 2 | v1 | `AT-REVIEW-UX` | Not implemented |
| `LP-FUNC-031` | `SHOULD` | 1000-series fixture if shipped | 5 | optional | `AT-BENCH-SERIES-PANEL` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PROD-006` | `NON-GOAL` | scope review | 1 | excluded | `AT-REVIEW-MPL-SCOPE` | Not applicable — scope exclusion |
| `LP-PROD-007` | `NON-GOAL` | scope review | 1 | excluded | `AT-REVIEW-MPL-SCOPE` | Not applicable — scope exclusion |
| `LP-PROD-008` | `NON-GOAL` | scope review | future | excluded | `AT-REVIEW-SCOPE` | Not applicable — scope exclusion |
| `LP-PROD-009` | `NON-GOAL` | scope review | future | excluded | `AT-REVIEW-SCOPE` | Not applicable — scope exclusion |
| `LP-UX-001` | `MUST NOT` | UX review | 0 | v1 | `AT-REVIEW-UX` | Not implemented |
| `LP-REL-001` | `NON-GOAL` | explicit scope review | future | excluded | `AT-REVIEW-PERSISTENCE` | Not applicable — scope exclusion |
| `LP-PROD-010` | `MUST` | dependency and type scan | 0 | v1 architecture | `AT-REVIEW-CORE-DAG` | Not implemented |
| `LP-PROD-011` | `MUST` | architecture review | 0 | v1 architecture | `AT-REVIEW-FRAME-BOUNDARY` | Not implemented |
| `LP-PROD-012` | `MUST` | schema and visibility review | 0 | v1 architecture | `AT-REVIEW-PACKET` | Not implemented |
| `LP-PROD-013` | `SHOULD` | packet review | 0-1 | implementation quality | `AT-REVIEW-PACKET` | Not implemented |
| `LP-PROD-014` | `MUST` | dependency DAG | 0 | v1 architecture | `AT-REVIEW-CORE-DAG` | Not implemented |
| `LP-DATA-001` | `MUST` | f64 property tests | 0 | v1 | `AT-SEM-F64` | Not implemented |
| `LP-DATA-002` | `MUST NOT` | precision negative tests | 0 | v1 | `AT-SEM-F64` | Not implemented |
| `LP-DATA-003` | `SHOULD` | chunk ownership tests | 0 | v1 quality | `AT-SEM-CHUNK` | Not implemented |
| `LP-DATA-004` | `SHOULD` | resident/streamed measurements | 1 | v1 quality | `AT-BENCH-MEMORY` | Not measured (environment required where hardware or GPU is involved) |
| `LP-DATA-005` | `SHOULD` | documented streamed scenario | 1 | v1 quality | `AT-BENCH-MEMORY` | Not measured (environment required where hardware or GPU is involved) |
| `LP-DATA-006` | `MUST` | ownership and lifetime tests | 0-1 | v1 | `AT-SEM-CHUNK` | Not implemented |
| `LP-DATA-007` | `MUST` | append and revision tests | 0-1 | v1 | `AT-SEM-CHUNK` | Not implemented |
| `LP-DATA-008` | `MUST` | local-frame precision test | 0-1 | v1 | `AT-SEM-F64-LOCAL` | Not implemented |
| `LP-DATA-009` | `MUST NOT` | precision negative test | 0-1 | v1 | `AT-SEM-F64-LOCAL` | Not implemented |
| `LP-DATA-010` | `SHOULD` | error-bound benchmark | 0-1 | v1 quality | `AT-SEM-F64-LOCAL` | Not implemented |
| `LP-LOD-001` | `SHOULD` | 10M benchmark | 1 | v1 performance target | `AT-BENCH-LOD-10M` | Not measured (environment required where hardware or GPU is involved). Local correctness evidence for the O(W)-intent bucketed path: `lod::m4::tests::bucketed_extrema_match_the_naive_per_bucket_model`, with the dyadic index pinned by `lod::summary::tests::dyadic_block_index_matches_naive_scan_across_chunk_cuts_and_ties`; complexity itself remains unmeasured |
| `LP-LOD-002` | `MUST NOT` | negative and spike fixtures | 0-1 | v1 | `AT-SEM-LOD-MONO` | Implemented (bounded Phase-1A local contract evidence: `lod::m4::tests::topology_violation_rejects_cross_topology_selection`, `lod::m4::tests::log_scales_use_explicit_full_resolution_and_split_derived_gaps`, `lod::m4::tests::zero_bins_are_rejected_before_selection`, `lod::m4::tests::collapsed_boundaries_keep_selection_exact_against_the_oracle`, `lod::m4::tests::spike_extrema_survive_m4_decimation`) |
| `LP-LOD-003` | `MUST` | extrema and spike fixtures | 0-1 | v1 | `AT-SEM-LOD-MONO` | Implemented (bounded Phase-1A local contract evidence: `lod::m4::tests::extrema_match_bruteforce_oracle_on_generated_series`, `lod::m4::tests::bucketed_extrema_match_the_naive_per_bucket_model`, `lod::m4::tests::spike_extrema_survive_m4_decimation`, with `lod::summary::tests` direct-vs-index extrema and tie coverage) |
| `LP-LOD-004` | `MUST` | topology model tests | 0 | v1 | `AT-SEM-LOD-TOPOLOGY` | Implemented (bounded Phase-1A local contract evidence: `data::topology::tests::monotonicx_rejects_decreasing_and_arbitraryxy_accepts_it`, `data::topology::tests::monotonicx_equality_is_valid_but_append_reversal_is_not`, `data::topology::tests::append_cannot_change_a_series_topology`, plus the selection-side strict guard in `lod::m4::tests::decreasing_x_is_an_explicit_topology_violation_not_silent_repair`) |
| `LP-LOD-005` | `SHOULD` | hierarchy benchmark | 0-1 | v1 performance target | `AT-SEM-LOD-MONO`, `AT-BENCH-LOD-10M` | Not measured (environment required where hardware or GPU is involved). Local correctness evidence for the eager dyadic block hierarchy the selection leans on: `lod::summary::tests::dyadic_block_index_matches_naive_scan_across_chunk_cuts_and_ties`; hierarchy build/query cost remains unmeasured |
| `LP-LOD-006` | `MUST` | arbitrary-order and culling fixtures | 0-1 | v1 correctness | `AT-SEM-LOD-ARBITRARY` | Implemented (bounded Phase-1A local contract evidence: `lod::arbitrary::tests::arbitrary_selection_is_invariant_under_source_permutation`, `lod::arbitrary::tests::culling_is_exact_at_viewport_edges_and_epsilon_outside`, `lod::arbitrary::tests::mixed_order_multi_segment_runs_keep_source_order`, with the existing bounds-culling oracle fixtures) |
| `LP-LOD-007` | `SHOULD` | phase boundary review | 5 | v1 non-blocking | `AT-REVIEW-PHASE-BOUNDARY` | Not implemented |
| `LP-RENDER-001` | `MUST` | renderer review and goldens | 1 | v1 | `AT-SEM-RENDER-GOLDEN` | Not implemented |
| `LP-RENDER-002` | `MUST` | width fixture | 1 | v1 | `AT-SEM-RENDER-GOLDEN` | Not implemented |
| `LP-RENDER-003` | `MUST` | 1x/2x/3x matrix | 1 | v1 | `AT-SEM-HIDPI` | Not implemented |
| `LP-RENDER-004` | `MUST` | alpha fixture | 1 | v1 | `AT-SEM-COLOR` | Not implemented |
| `LP-RENDER-005` | `MUST` | clipping golden | 1 | v1 | `AT-SEM-RENDER-GOLDEN` | Not implemented |
| `LP-RENDER-006` | `MUST` | interaction golden and benchmark | 1 | v1 | `AT-FUNC-PAN-ZOOM`, `AT-BENCH-FRAME` | Not measured (environment required where hardware or GPU is involved) |
| `LP-RENDER-007` | `SHOULD` | rendering quality fixture | 1 | v1 non-blocking | `AT-SEM-RENDER-GOLDEN` | Not implemented |
| `LP-RENDER-008` | `SHOULD` | rendering quality fixture | 1 | v1 non-blocking | `AT-SEM-RENDER-GOLDEN` | Not implemented |
| `LP-RENDER-009` | `SHOULD` | rendering quality fixture | 1 | v1 non-blocking | `AT-SEM-RENDER-GOLDEN` | Not implemented |
| `LP-RENDER-010` | `MUST` | default-path review | 1 | v1 | `AT-SEM-RENDER-GOLDEN` | Not implemented |
| `LP-QUAL-001` | `SHOULD` | allocation telemetry | 1 | v1 performance target | `AT-BENCH-HOTPATH` | Not measured (environment required where hardware or GPU is involved) |
| `LP-QUAL-002` | `MUST NOT` | callback counter is zero | 1 | native v1 gate | `AT-BENCH-HOTPATH` | Not measured (environment required where hardware or GPU is involved) |
| `LP-QUAL-003` | `MUST NOT` | shader counter is zero | 1 | v1 | `AT-SEC-SHADER`, `AT-BENCH-HOTPATH` | Not measured (environment required where hardware or GPU is involved) |
| `LP-QUAL-004` | `MUST NOT` | pipeline counter is zero | 1 | v1 | `AT-BENCH-HOTPATH` | Not measured (environment required where hardware or GPU is involved) |
| `LP-QUAL-005` | `MUST NOT` | shaping counter is zero | 1-2 | v1 | `AT-SEM-LAYOUT`, `AT-BENCH-HOTPATH` | Not measured (environment required where hardware or GPU is involved) |
| `LP-QUAL-006` | `MUST NOT` | allocation telemetry | 1 | v1 | `AT-BENCH-HOTPATH` | Not measured (environment required where hardware or GPU is involved) |
| `LP-QUAL-007` | `MUST NOT` | upload-byte counter | 1 | v1 | `AT-BENCH-HOTPATH` | Not measured (environment required where hardware or GPU is involved) |
| `LP-QUAL-008` | `MUST NOT` | cache-generation counter | 1 | v1 | `AT-BENCH-HOTPATH` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PLAT-001` | `MUST` | portable backend build and runtime | 1 | v1 | `AT-LIFE-PLATFORM` | environment required — Not implemented |
| `LP-PLAT-002` | `MUST` | dependency review | 3 | v1 | `AT-BENCH-DEPENDENCY` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PLAT-003` | `MUST` | Phase 4 decision record | 4 | conditional future | `AT-BENCH-NATIVE-AB` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PLAT-004` | `REFERENCE` | candidate review | 4 | future | `AT-BENCH-NATIVE-AB` | Reference only — no support or implementation claim |
| `LP-PLAT-005` | `REFERENCE` | candidate review | 4 | future | `AT-LIFE-PLATFORM` | Reference only — no support or implementation claim |
| `LP-PLAT-006` | `MUST` | capability and startup tests | 1 | v1 architecture | `AT-REVIEW-AUTO` | Not implemented |
| `LP-PLAT-007` | `MUST NOT` | adoption review | 4 | conditional future | `AT-BENCH-NATIVE-AB` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PLAT-008` | `REFERENCE` | compatibility matrix | 1 | reference | `AT-LIFE-PLATFORM` | Reference only — no support or implementation claim |
| `LP-PLAT-009` | `MUST` | lifecycle tests | 1 | v1 | `AT-LIFE-RUNTIME` | environment required — Not implemented |
| `LP-PLAT-010` | `MUST` | lifecycle matrix | 1-3 | v1 | `AT-LIFE-RUNTIME` | environment required — Not implemented |
| `LP-QUAL-009` | `REFERENCE` | candidate review | 1 | reference | `AT-SEC-SHADER` | Reference only — no support or implementation claim |
| `LP-QUAL-010` | `MUST` | reproducible artifact build | 1 | v1 | `AT-SEC-SHADER` | Not implemented |
| `LP-QUAL-011` | `MUST` | artifact manifest | 1 | v1 | `AT-SEC-SHADER` | Not implemented |
| `LP-QUAL-012` | `MUST` | validator corpus | 1 | v1 | `AT-SEC-SHADER` | Not implemented |
| `LP-QUAL-013` | `MUST NOT` | dependency scan | 1 | v1 architecture | `AT-REVIEW-CORE-DAG` | Not implemented |
| `LP-SEC-001` | `MUST` | static unsafe scan | 0 | v1 architecture | `AT-SEC-UNSAFE` | Not implemented |
| `LP-SEC-002` | `MUST` | unsafe review | 0-3 | v1 | `AT-SEC-UNSAFE` | Not implemented |
| `LP-SEC-003` | `MUST NOT` | runtime negative test | 1 | v1 | `AT-SEC-SHADER` | Not implemented |
| `LP-SEC-004` | `MUST` | malformed-input tests | 0-1 | v1 | `AT-SEC-SIZES` | Not implemented |
| `LP-SEC-005` | `MUST` | artifact verification | 1 | v1 | `AT-SEC-SHADER` | Not implemented |
| `LP-SEC-006` | `MUST` | supply-chain review | 0-3 | v1 | `AT-SEC-SBOM` | Not implemented |
| `LP-SEC-007` | `MUST` | font license manifest | 2 | v1 | `AT-SEC-FONTS` | Not implemented |
| `LP-SEC-008` | `MUST` | publication safety scan | 0 | bundle publication | `AT-SEC-PUBLIC-DOCS` | Not implemented |
| `LP-TEXT-001` | `MUST` | shared-layout fixtures | 2 | v1 | `AT-SEM-LAYOUT` | Not implemented |
| `LP-TEXT-002` | `MUST NOT` | no-remeasurement review | 2 | v1 | `AT-SEM-LAYOUT` | Not implemented |
| `LP-TEXT-003` | `SHOULD` | text decision record | 2 | v1 quality | `AT-SEM-LAYOUT` | Not implemented |
| `LP-TEXT-004` | `MUST` | deterministic font fixture | 2 | v1 | `AT-SEM-LAYOUT` | Not implemented |
| `LP-TEXT-005` | `MUST` | PDF structural check | 2 | v1 | `AT-EXPORT-PDF-TEXT` | Not implemented |
| `LP-TEXT-006` | `MUST NOT` | PDF structural negative test | 2 | v1 | `AT-EXPORT-PDF-VECTOR` | Not implemented |
| `LP-TEXT-007` | `SHOULD` | reproducibility manifest | 2 | v1 quality | `AT-SEC-FONTS` | Not implemented |
| `LP-MPL-001` | `MUST` | package and DAG review | 1-2 | v1 | `AT-MPL-LOADER`, `AT-REVIEW-CORE-DAG` | Not implemented |
| `LP-MPL-002` | `MUST` | loader and packaging smoke tests | 1-2 | v1 | `AT-MPL-LOADER` | Implemented (bounded Phase-3B local contract evidence: PRs #26/#28/#29/#32; `EntryPointDiscoveryTests`, `DeclaredIdentityConstantsTests`, `TestModuleSurface`) |
| `LP-MPL-003` | `MUST` | profile selection tests | 1-2 | v1 | `AT-MPL-PROFILES` | Implemented (bounded Phase-3B local contract evidence: `TestProfileSelectionValues`, `TestStagedDefaultProfile`, `TestSelectionIsImmutable`, `TestSelectionDrivesDispatch`; the shipped slice pins `strict`/`hybrid` selection, explicit rejection of every other value including deferred `accelerated-native`, and the staged strict default — hybrid-explicit-as-default and accelerated-native delivery stay open) |
| `LP-MPL-004` | `MUST` | authority and revision tests | 1-2 | v1 | `AT-MPL-AUTHORITY` | Implemented (bounded Phase-3B local contract evidence: `TestRepeatedRenderIdentity`, `TestDiagnosticImmutabilityAcrossAttempts`, `TestFailureTokenStability`, `TestDerivedSnapshotIntegrity`; full Figure/Artist authority closure stays open) |
| `LP-MPL-005` | `MUST` | native authority tests | 1 | v1 | `AT-SEM-STATE-REVISION` | Implemented (bounded Phase-3B local contract evidence: PR #41; `TestRecordingStubHarness`, `TestNativeAuthorityConsequences`, and related seam classes in `test_phase3b_native_authority.py`) |
| `LP-MPL-006` | `MUST` | error fixtures | 1-2 | v1 | `AT-MPL-FALLBACK` | Not implemented |
| `LP-MPL-007` | `MUST` | fallback fixture | 1-2 | v1 | `AT-MPL-FALLBACK` | Implemented (bounded Phase-3B local contract evidence: PR #32; `TestHybridFallback`, `TestHybridTerminalFailures`) |
| `LP-MPL-008` | `MUST` | diagnostic schema and golden tests | 1-2 | v1 | `AT-MPL-FALLBACK` | Implemented (bounded Phase-3B local contract evidence: PR #32; `TestHybridFallback`, `TestHybridTerminalFailures`; schema fields also covered by strict-mode oracle classes) |
| `LP-MPL-009` | `MUST` | mixed-output structural test | 2 | v1 | `AT-EXPORT-FALLBACK` | Not implemented |
| `LP-MPL-010` | `SHOULD` | mapped-adapter review | 2 | v1 quality | `AT-MPL-FALLBACK` | Not implemented |
| `LP-MPL-011` | `MUST NOT` | separated benchmark claims | 1-3 | v1 | `AT-BENCH-PROFILE-SEPARATION` | Not measured (environment required where hardware or GPU is involved) |
| `LP-MPL-012` | `SHOULD` | versioned text matrix | 2 | v1 quality | `AT-MPL-TEXT` | Not implemented |
| `LP-MPL-013` | `MUST` | reentrancy and counter tests | 1-2 | v1 | `AT-LIFE-FFI`, `AT-BENCH-PROFILE-SEPARATION` | Not measured (environment required where hardware or GPU is involved) |
| `LP-MPL-014` | `REFERENCE` | compatibility matrix | 1-3 | reference | `AT-MPL-MATRIX` | Reference only — no support or implementation claim |
| `LP-MPL-015` | `MUST NOT` | copy and ownership tests | 1 | v1 | `AT-LIFE-FFI`, `AT-BENCH-FFI` | Not measured (environment required where hardware or GPU is involved) |
| `LP-MPL-016` | `SHOULD` | API review | future | future | `AT-REVIEW-FFI` | Not implemented |
| `LP-MPL-017` | `MUST` | dependency scan | 1 | v1 | `AT-REVIEW-DAG` | Not implemented |
| `LP-UX-002` | `SHOULD` | UX review | 1-2 | v1 quality | `AT-REVIEW-UX` | Not implemented |
| `LP-UX-003` | `MUST NOT` | UX review | 1-2 | v1 | `AT-REVIEW-UX` | Not implemented |
| `LP-UX-004` | `MUST NOT` | UX review | 1-2 | v1 | `AT-REVIEW-UX` | Not implemented |
| `LP-UX-005` | `MUST NOT` | UX review | 1-2 | v1 | `AT-REVIEW-UX` | Not implemented |
| `LP-UX-006` | `MUST NOT` | interaction usability test | 1 | v1 | `AT-FUNC-INPUT` | Not implemented |
| `LP-UX-007` | `SHOULD` | native viewer review | 2 | v1 quality | `AT-REVIEW-UX` | Not implemented |
| `LP-UX-008` | `MUST NOT` | UX review | 1 | v1 | `AT-REVIEW-UX` | Not implemented |
| `LP-UX-009` | `MUST NOT` | UX review | 1 | v1 | `AT-REVIEW-UX` | Not implemented |
| `LP-UX-010` | `MUST NOT` | UX review | 2 | v1 | `AT-REVIEW-UX` | Not implemented |
| `LP-UX-011` | `MUST NOT` | UX review | 1 | v1 | `AT-REVIEW-UX` | Not implemented |
| `LP-UX-012` | `MUST` | canonical-view fixture | 1-2 | v1 | `AT-FUNC-HISTORY` | Implemented (bounded Phase-1B local contract evidence: `home_restores_the_stored_canonical_view` in `crates/lumenplot/tests/history.rs` — Home reads the snapshot's stored canonical view, restores it as current viewport after interaction, and a replaced Home is likewise restorable) |
| `LP-UX-013` | `MUST NOT` | state and history fixture | 1-2 | v1 | `AT-SEM-STATE-REVISION` | Implemented (bounded Phase-1B local contract evidence: `interactive_viewport_changes_leave_the_canonical_view_stable`, `canonical_and_view_edits_validate_against_current_scales_atomically`, and `view_transitions_follow_noop_and_negative_zero_equality_rules` in `crates/lumenplot/tests/history.rs` — interactive viewport commits never move the stored canonical view or prior snapshots, repeat values are effective no-ops with unchanged revision, `-0.0 == 0.0`) |
| `LP-UX-014` | `MUST` | event-routing matrix | 1-2 | v1 | `AT-FUNC-INPUT` | Not implemented |
| `LP-UX-015` | `MUST` | axis-only fixture | 1 | v1 | `AT-FUNC-INPUT` | Not implemented |
| `LP-UX-016` | `MUST` | scene and layout review | 2 | v1 | `AT-SEM-LEGEND` | Not implemented |
| `LP-UX-017` | `MUST` | semantic equivalence fixture | 2 | v1 | `AT-SEM-LEGEND`, `AT-EXPORT-LEGEND` | Not implemented |
| `LP-UX-018` | `MUST NOT` | visual review | 2 | v1 | `AT-REVIEW-UX` | Not implemented |
| `LP-UX-019` | `MUST` | Legend state fixture | 2 | v1 | `AT-SEM-LEGEND` | Not implemented |
| `LP-UX-020` | `MUST` | solo/restore fixture | 2 | v1 | `AT-SEM-LEGEND` | Not implemented |
| `LP-UX-021` | `MUST` | context and export negative test | 2 | v1 | `AT-SEM-STATE-REVISION`, `AT-EXPORT-STATE` | Not implemented |
| `LP-UX-022` | `MUST` | drag/export/hit-test fixture | 2 | v1 | `AT-SEM-LEGEND`, `AT-EXPORT-LEGEND` | Not implemented |
| `LP-QUAL-014` | `MUST` | state schema review | 1-2 | v1 | `AT-SEM-STATE-REVISION` | Not implemented |
| `LP-QUAL-015` | `MUST` | export-state fixture | 2 | v1 | `AT-EXPORT-STATE` | Not implemented |
| `LP-QUAL-016` | `MUST NOT` | export negative fixture | 2 | v1 | `AT-EXPORT-STATE` | Not implemented |
| `LP-QUAL-017` | `MUST` | revision and race tests | 0-1 | v1 architecture | `AT-SEM-STATE-REVISION`, `AT-LIFE-RUNTIME` | environment required — Not implemented |
| `LP-QUAL-018` | `MUST` | cancellation and queue tests | 0-1 | v1 architecture | `AT-LIFE-CANCELLATION` | Not implemented |
| `LP-QUAL-019` | `MUST NOT` | reentrancy test | 1-2 | v1 | `AT-LIFE-FFI` | Not implemented |
| `LP-QUAL-020` | `MUST` | device-loss/OOM matrix | 1-3 | v1 | `AT-LIFE-RUNTIME` | environment required — Not implemented |
| `LP-EXPORT-001` | `MUST` | dimensions, alpha, and state fixture | 2 | v1 | `AT-EXPORT-PNG` | Not implemented |
| `LP-EXPORT-002` | `MUST` | vector/text structural fixture | 2 | v1 | `AT-EXPORT-PDF-VECTOR` | Not implemented |
| `LP-EXPORT-003` | `SHOULD` | structural SVG fixture | 2 | v1 non-blocking | `AT-EXPORT-SVG` | Not implemented |
| `LP-EXPORT-004` | `MUST` | state/export fixture | 2 | v1 | `AT-EXPORT-STATE` | Not implemented |
| `LP-EXPORT-005` | `MUST` | structural output review | 2 | v1 | `AT-EXPORT-PDF-VECTOR` | Not implemented |
| `LP-EXPORT-006` | `MUST NOT` | PDF negative test | 2 | v1 | `AT-EXPORT-PDF-VECTOR` | Not implemented |
| `LP-EXPORT-007` | `MUST` | cross-output equivalence fixture | 2 | v1 | `AT-SEM-LAYOUT`, `AT-EXPORT-LEGEND` | Not implemented |
| `LP-EXPORT-008` | `MUST NOT` | transient export negative test | 2 | v1 | `AT-EXPORT-STATE` | Not implemented |
| `LP-EXPORT-009` | `MUST` | fallback diagnostics | 2 | v1 | `AT-EXPORT-FALLBACK` | Not implemented |
| `LP-UX-023` | `MUST` | cursor interaction fixture | 2 | v1 | `AT-FUNC-CURSOR` | Not implemented |
| `LP-UX-024` | `SHOULD` | measurement fixture | 5 | v1 non-blocking | `AT-FUNC-MEASUREMENT` | Not implemented |
| `LP-EXPORT-010` | `MUST NOT` | export negative fixture | 2 | v1 | `AT-EXPORT-STATE` | Not implemented |
| `LP-UX-025` | `MUST NOT` | UX review | 2 | v1 | `AT-REVIEW-UX` | Not implemented |
| `LP-UX-026` | `SHOULD` | panel fixture if shipped | 5 | optional | `AT-FUNC-SERIES-PANEL` | Not implemented |
| `LP-UX-027` | `SHOULD` | large-panel benchmark | 5 | optional | `AT-BENCH-SERIES-PANEL` | Not measured (environment required where hardware or GPU is involved) |
| `LP-UX-028` | `MUST` | keyboard matrix | 2 | v1 | `AT-FUNC-KEYBOARD-A11Y` | Not implemented |
| `LP-UX-029` | `SHOULD` | OS interaction review | 2-3 | v1 quality | `AT-FUNC-KEYBOARD-A11Y` | Not implemented |
| `LP-UX-030` | `MUST` | accessibility review | 2 | v1 | `AT-FUNC-KEYBOARD-A11Y` | Not implemented |
| `LP-UX-031` | `MUST` | contrast fixture | 2 | v1 | `AT-REVIEW-A11Y` | Not implemented |
| `LP-UX-032` | `MUST` | preference fixture | 2 | v1 | `AT-REVIEW-A11Y` | Not implemented |
| `LP-UX-033` | `SHOULD` | platform accessibility review | 2-3 | v1 non-blocking | `AT-REVIEW-A11Y` | Not implemented |
| `LP-PERF-001` | `MUST` | 10M fixture | 1 | native v1 gate | `AT-BENCH-NATIVE-10M` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PERF-002` | `SHOULD` | 100M scenario report | 1-3 | stretch | `AT-BENCH-MEMORY` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PERF-003` | `SHOULD` | memory policy review | 1 | v1 quality | `AT-BENCH-MEMORY` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PERF-004` | `MUST` | measured p99 | 3 | native v1 gate | `AT-BENCH-NATIVE-10M` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PERF-005` | `SHOULD` | measured p99 | 3 | non-blocking target | `AT-BENCH-120HZ` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PERF-006` | `MUST` | counters equal zero | 1 | native v1 gate | `AT-BENCH-HOTPATH` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PERF-007` | `SHOULD` | allocation telemetry | 1 | native quality target | `AT-BENCH-HOTPATH` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PERF-008` | `MUST` | event-to-display measurement | 2 | v1 | `AT-BENCH-LEGEND-1FRAME` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PERF-009` | `MUST` | benchmark artifacts | 0-3 | v1 | `AT-BENCH-MANIFEST` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PERF-010` | `MUST` | fixture manifest | 0-3 | v1 | `AT-BENCH-MANIFEST` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PERF-011` | `MUST` | benchmark report | 0-3 | v1 | `AT-BENCH-MANIFEST` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PERF-012` | `SHOULD` | comparator report | 3-4 | non-blocking | `AT-BENCH-COMPARATORS` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PERF-013` | `MUST` | reproducible protocol | 0-3 | v1 | `AT-BENCH-MANIFEST` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PERF-014` | `MUST` | machine manifest | 3 | v1 | `AT-BENCH-MANIFEST` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PERF-015` | `MUST` | protocol review | 0-3 | v1 | `AT-BENCH-MANIFEST` | Not measured (environment required where hardware or GPU is involved) |
| `LP-QUAL-021` | `MUST` | profile-separated report | 1-3 | v1 | `AT-BENCH-PROFILE-SEPARATION` | Not measured (environment required where hardware or GPU is involved) |
| `LP-QUAL-022` | `MUST` | dependency review policy | 0-3 | v1 | `AT-BENCH-DEPENDENCY` | Not measured (environment required where hardware or GPU is involved) |
| `LP-QUAL-023` | `MUST` | CI/review gate | 3 | v1 | `AT-BENCH-DEPENDENCY` | Not measured (environment required where hardware or GPU is involved) |
| `LP-QUAL-024` | `SHOULD` | decision record | 3 | v1 policy | `AT-BENCH-DEPENDENCY` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PLAT-011` | `MUST` | A/B benchmark report | 4 | conditional future | `AT-BENCH-NATIVE-AB` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PLAT-012` | `MAY` | adoption decision | 4 | future | `AT-BENCH-NATIVE-AB` | Not measured (environment required where hardware or GPU is involved) |
| `LP-QUAL-025` | `REFERENCE` | architecture overview | 0+ | reference | `AT-REVIEW-DAG` | Reference only — no support or implementation claim |
| `LP-QUAL-026` | `MAY` | implementation planning | 0-4 | future | `AT-REVIEW-SCOPE` | Not implemented |
| `LP-REL-002` | `MUST` | release metadata review | 0-3 | v1 pre-alpha | `AT-REVIEW-RELEASE` | Not implemented |
| `LP-MPL-018` | `MUST` | standalone launch and import tests | 1-2 | v1 | `AT-FUNC-VIEWER`, `AT-REVIEW-DAG` | Not implemented |
| `LP-MPL-019` | `MUST NOT` | dependency scan | 0 | v1 | `AT-REVIEW-DAG` | Not implemented |
| `LP-REL-003` | `PHASE` | foundation artifacts | 0 | no release claim | `AT-REVIEW-PHASE-MAP` | Planning only |
| `LP-REL-004` | `PHASE` | native foundation | 1 | no release claim | `AT-REVIEW-PHASE-MAP` | Planning only |
| `LP-REL-005` | `PHASE` | v1 interaction and export | 2 | no release claim | `AT-REVIEW-PHASE-MAP` | Planning only |
| `LP-REL-006` | `PHASE` | cross-platform evidence | 3 | no release claim | `AT-REVIEW-PHASE-MAP` | Planning only |
| `LP-REL-007` | `PHASE` | optional native fast paths | 4 | future | `AT-REVIEW-PHASE-MAP` | Planning only |
| `LP-REL-008` | `PHASE` | post-v1 expansion | 5 | v1.1 or later | `AT-REVIEW-PHASE-MAP` | Planning only |
| `LP-REL-009` | `MUST` | requirement registry validation | 0 | v1 governance | `AT-REVIEW-TRACEABILITY` | Not implemented |
| `LP-REL-010` | `MUST` | all functional rows pass | 1-3 | v1 | `AT-RELEASE-FUNCTIONAL` | Not implemented |
| `LP-REL-011` | `MUST` | all correctness rows pass | 0-3 | v1 | `AT-RELEASE-CORRECTNESS` | Not implemented |
| `LP-REL-012` | `MUST` | all native performance rows pass | 1-3 | native v1 | `AT-RELEASE-PERFORMANCE` | Not implemented |
| `LP-REL-013` | `MUST` | release review bundle | 0-3 | v1 | `AT-RELEASE-QUALITY` | Not implemented |
| `LP-REL-014` | `MUST NOT` | release-document review | 0-3 | v1 governance | `AT-REVIEW-RELEASE` | Not implemented |
| `LP-QUAL-027` | `REFERENCE` | documentation review | 0 | reference | `AT-REVIEW-DEPENDENCIES` | Reference only — no support or implementation claim |
| `LP-QUAL-028` | `MUST` | dependency decision record | 0-3 | v1 governance | `AT-REVIEW-DEPENDENCIES` | Not implemented |
| `LP-PROD-015` | `REFERENCE` | architecture review rubric | 0 | product principle | `AT-REVIEW-PRODUCT` | Reference only — no support or implementation claim |
| `LP-PERF-016` | `SHOULD` | benchmark and design review | 0-3 | v1 quality | `AT-BENCH-LOD-10M`, `AT-REVIEW-PACKET` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PROD-016` | `REFERENCE` | product and export review | 2 | v1 principle | `AT-EXPORT-STATE` | Reference only — no support or implementation claim |
| `LP-PROD-017` | `REFERENCE` | product and benchmark review | 0-3 | v1 principle | `AT-BENCH-LOD-10M` | Reference only — no support or implementation claim |
| `LP-PROD-018` | `REFERENCE` | architecture review | 0-4 | v1 principle | `AT-REVIEW-CORE-DAG`, `AT-BENCH-NATIVE-AB` | Reference only — no support or implementation claim |
| `LP-FUNC-032` | `MUST` | fill geometry and span fixtures — quality oracle: current Matplotlib Agg backend output; `AT-FUNC-FILL` is met only when Agg parity fixtures pass (§5.4): geometry parity to sub-pixel rounding including span baselines, decoded-pixel difference within recorded thresholds, style semantics equal to Agg's resolution | 3B-cont. | v1 | `AT-FUNC-FILL` | Implemented (bounded Phase-3B local contract evidence: PR #68; `TestFillWhitelist`, `TestFillCollectorTrace`, `TestFillStyleContract`, `TestFillPixelParity` in `test_phase3b_fill.py` — strict eligibility for `Polygon` (`Axes.fill`) and `FillBetweenPolyCollection` (`Axes.fill_between`) under the opt-in `agg_srgb` blend mode, §5.4 Agg-oracle parity fixtures pass within recorded thresholds; `stackplot` composition and any release claim stay open) |
| `LP-FUNC-033` | `MUST` | bar geometry and stacking fixtures — quality oracle: current Matplotlib Agg backend output; `AT-FUNC-BAR` is met only when Agg parity fixtures pass (§5.4): anchored-baseline geometry (negative and stacked included) to sub-pixel rounding, pixel parity within recorded thresholds, style semantics equal to Agg's resolution | 3B-cont. | v1 | `AT-FUNC-BAR` | Implemented (bounded Phase-3B local contract evidence: PR #69; `TestBarWhitelist`, `TestBarCollectorTrace`, `TestBarStyleContract`, `TestBarPixelParity`, `TestBarModeBehavior` in `test_phase3b_bar.py` — axis-aligned `Rectangle` bars anchored to declared baselines incl. negative, stacked, and `bottom=` cases, interiors byte-exact and edges inside the ratified 32/255 AA quantum vs Agg; rotated rectangles and any release claim stay refused/open) |
| `LP-FUNC-034` | `MUST` | drawstyle equivalence fixtures against Agg — quality oracle: current Matplotlib Agg backend output; `AT-FUNC-DRAWSTYLE` is met only when steps-pre/post/mid fixtures pass (§5.4): exact generated vertex sequences, pixel parity within recorded thresholds, style semantics equal to Agg's resolution | 3B-cont. | v1 | `AT-FUNC-DRAWSTYLE` | Implemented (bounded Phase-3B local contract evidence: PR #70; `TestStepGeometryParity`, `TestStepStyleContract`, `TestStepTopologyRecurrence`, `TestStepPixelParity`, `TestStepNonFiniteFallback`, `TestStepProfileModes` in `test_phase3b_steps.py` — exact `cbook`-parity vertex generation for steps-pre/post/mid plus the `steps` alias, stroke-edge pixel parity ≥95% within tol=32 with worst ≤228 measured, non-finite samples refusing explicitly; markers and unknown drawstyles stay refused, any release claim stays open) |
| `LP-FUNC-035` | `SHOULD` | cross-primitive ordering and alpha golden tests — quality oracle: current Matplotlib Agg backend output; `AT-SEM-COMPOSITING` is met only when golden frames match Agg layering/occlusion across mixed primitive classes within recorded thresholds (§5.4) | 3B-cont.+1 | v1 quality | `AT-SEM-COMPOSITING` | Not implemented |
| `LP-FUNC-036` | `SHOULD` | polar transform fixtures — quality oracle: current Matplotlib Agg backend output, fixed in advance so later Phase-5 work cannot lower it; `AT-FUNC-POLAR` is met only when polar transform/clip fixtures match Agg under the §5.4 criteria | 5 | v1 non-blocking | `AT-FUNC-POLAR` | Not implemented |
| `LP-FUNC-037` | `SHOULD` | date-tick formatting fixtures — quality oracle: current Matplotlib Agg backend output; `AT-FUNC-DATE-AXIS` is met only when label fixtures pass (§5.4): locator/formatter results equal to Agg's and glyph outlines matching Matplotlib `TextPath` output for the same font properties | 3B-cont.+1 | v1 quality | `AT-FUNC-DATE-AXIS` | Not implemented |
| `LP-FUNC-038` | `SHOULD` | quiver geometry and scaling fixtures — quality oracle: current Matplotlib Agg backend output, fixed in advance so later Phase-5 work cannot lower it; `AT-FUNC-QUIVER` is met only when arrow-glyph geometry/scaling fixtures match Agg under the §5.4 criteria | 5 | v1 non-blocking | `AT-FUNC-QUIVER` | Not implemented |
| `LP-FUNC-039` | `MAY` | scale-extension decision record — any adoption decision must evaluate candidate scales against the §5.4 quality oracle (Agg output) before acceptance | future | future | `AT-SEM-SCALE-EXT` | Not implemented |
| `LP-MPL-020` | `SHOULD` | eligibility-extension process review — every whitelist growth lands its four mechanics together (whitelist entry, collector-trace expectation, style contract, fixtures) and those fixtures must include the §5.4 Agg-oracle parity criteria for the new artist class | continuous | v1 governance | `AT-MPL-ELIGIBILITY` | Not implemented |

## Normative closure: every MUST and MUST NOT

| ID | Class | Required evidence | Current result |
| --- | --- | --- | --- |
| `LP-PROD-002` | `MUST` | `AT-LIFE-PLATFORM` | environment required — Not implemented |
| `LP-PROD-003` | `MUST` | `AT-SEM-LAYOUT`, `AT-EXPORT-STATE` | Not implemented |
| `LP-FUNC-001` | `MUST` | `AT-FUNC-LINE2D` | Not implemented |
| `LP-FUNC-002` | `MUST` | `AT-FUNC-SERIES` | Not implemented |
| `LP-FUNC-003` | `MUST` | `AT-FUNC-AXIS` | Not implemented (bounded Phase-3B local contract evidence: PR #63; decorated-axes decoration rendering per ADR 0015 §4a — `TestDecoratedAxesSpec`, `TestDecoratedAxesEligibility`; labels/date formatting remain unclosed) |
| `LP-FUNC-004` | `MUST` | `AT-FUNC-LOG-AXIS` | Not implemented |
| `LP-FUNC-005` | `MUST` | `AT-FUNC-PAN-ZOOM` | Not implemented |
| `LP-FUNC-006` | `MUST` | `AT-FUNC-PAN-ZOOM` | Not implemented |
| `LP-FUNC-007` | `MUST` | `AT-FUNC-BOX-ZOOM` | Not implemented |
| `LP-FUNC-008` | `MUST` | `AT-FUNC-HISTORY` | Implemented (bounded Phase-1B local contract evidence: canonical-view restore, stability under interaction, and no-op/abort fixtures in `crates/lumenplot/tests/history.rs`; gesture routing remains open) |
| `LP-FUNC-009` | `MUST` | `AT-FUNC-LEGEND` | Not implemented |
| `LP-FUNC-010` | `MUST` | `AT-FUNC-CURSOR` | Not implemented |
| `LP-FUNC-011` | `MUST` | `AT-FUNC-GRID` | Not implemented |
| `LP-FUNC-012` | `MUST` | `AT-FUNC-ANNOTATION`, `AT-EXPORT-ANNOTATION` | Not implemented |
| `LP-FUNC-013` | `MUST` | `AT-EXPORT-PNG` | Not implemented |
| `LP-FUNC-014` | `MUST` | `AT-EXPORT-PDF-VECTOR` | Not implemented |
| `LP-FUNC-015` | `MUST` | `AT-LIFE-FFI`, `AT-MPL-LOADER` | Not implemented |
| `LP-FUNC-016` | `MUST` | `AT-FUNC-VIEWER`, `AT-LIFE-VIEWER` | Not implemented |
| `LP-FUNC-030` | `MUST NOT` | `AT-REVIEW-UX` | Not implemented |
| `LP-UX-001` | `MUST NOT` | `AT-REVIEW-UX` | Not implemented |
| `LP-PROD-010` | `MUST` | `AT-REVIEW-CORE-DAG` | Not implemented |
| `LP-PROD-011` | `MUST` | `AT-REVIEW-FRAME-BOUNDARY` | Not implemented |
| `LP-PROD-012` | `MUST` | `AT-REVIEW-PACKET` | Not implemented |
| `LP-PROD-014` | `MUST` | `AT-REVIEW-CORE-DAG` | Not implemented |
| `LP-DATA-001` | `MUST` | `AT-SEM-F64` | Not implemented |
| `LP-DATA-002` | `MUST NOT` | `AT-SEM-F64` | Not implemented |
| `LP-DATA-006` | `MUST` | `AT-SEM-CHUNK` | Not implemented |
| `LP-DATA-007` | `MUST` | `AT-SEM-CHUNK` | Not implemented |
| `LP-DATA-008` | `MUST` | `AT-SEM-F64-LOCAL` | Not implemented |
| `LP-DATA-009` | `MUST NOT` | `AT-SEM-F64-LOCAL` | Not implemented |
| `LP-LOD-002` | `MUST NOT` | `AT-SEM-LOD-MONO` | Implemented (bounded Phase-1A local contract evidence: `lod::m4::tests::topology_violation_rejects_cross_topology_selection`, `lod::m4::tests::log_scales_use_explicit_full_resolution_and_split_derived_gaps`, `lod::m4::tests::zero_bins_are_rejected_before_selection`, `lod::m4::tests::collapsed_boundaries_keep_selection_exact_against_the_oracle`, `lod::m4::tests::spike_extrema_survive_m4_decimation`) |
| `LP-LOD-003` | `MUST` | `AT-SEM-LOD-MONO` | Implemented (bounded Phase-1A local contract evidence: `lod::m4::tests::extrema_match_bruteforce_oracle_on_generated_series`, `lod::m4::tests::bucketed_extrema_match_the_naive_per_bucket_model`, `lod::m4::tests::spike_extrema_survive_m4_decimation`, with `lod::summary::tests` direct-vs-index extrema and tie coverage) |
| `LP-LOD-004` | `MUST` | `AT-SEM-LOD-TOPOLOGY` | Implemented (bounded Phase-1A local contract evidence: `data::topology::tests::monotonicx_rejects_decreasing_and_arbitraryxy_accepts_it`, `data::topology::tests::monotonicx_equality_is_valid_but_append_reversal_is_not`, `data::topology::tests::append_cannot_change_a_series_topology`, plus the selection-side strict guard in `lod::m4::tests::decreasing_x_is_an_explicit_topology_violation_not_silent_repair`) |
| `LP-LOD-006` | `MUST` | `AT-SEM-LOD-ARBITRARY` | Implemented (bounded Phase-1A local contract evidence: `lod::arbitrary::tests::arbitrary_selection_is_invariant_under_source_permutation`, `lod::arbitrary::tests::culling_is_exact_at_viewport_edges_and_epsilon_outside`, `lod::arbitrary::tests::mixed_order_multi_segment_runs_keep_source_order`, with the existing bounds-culling oracle fixtures) |
| `LP-RENDER-001` | `MUST` | `AT-SEM-RENDER-GOLDEN` | Not implemented |
| `LP-RENDER-002` | `MUST` | `AT-SEM-RENDER-GOLDEN` | Not implemented |
| `LP-RENDER-003` | `MUST` | `AT-SEM-HIDPI` | Not implemented |
| `LP-RENDER-004` | `MUST` | `AT-SEM-COLOR` | Not implemented |
| `LP-RENDER-005` | `MUST` | `AT-SEM-RENDER-GOLDEN` | Not implemented |
| `LP-RENDER-006` | `MUST` | `AT-FUNC-PAN-ZOOM`, `AT-BENCH-FRAME` | Not measured (environment required where hardware or GPU is involved) |
| `LP-RENDER-010` | `MUST` | `AT-SEM-RENDER-GOLDEN` | Not implemented |
| `LP-QUAL-002` | `MUST NOT` | `AT-BENCH-HOTPATH` | Not measured (environment required where hardware or GPU is involved) |
| `LP-QUAL-003` | `MUST NOT` | `AT-SEC-SHADER`, `AT-BENCH-HOTPATH` | Not measured (environment required where hardware or GPU is involved) |
| `LP-QUAL-004` | `MUST NOT` | `AT-BENCH-HOTPATH` | Not measured (environment required where hardware or GPU is involved) |
| `LP-QUAL-005` | `MUST NOT` | `AT-SEM-LAYOUT`, `AT-BENCH-HOTPATH` | Not measured (environment required where hardware or GPU is involved) |
| `LP-QUAL-006` | `MUST NOT` | `AT-BENCH-HOTPATH` | Not measured (environment required where hardware or GPU is involved) |
| `LP-QUAL-007` | `MUST NOT` | `AT-BENCH-HOTPATH` | Not measured (environment required where hardware or GPU is involved) |
| `LP-QUAL-008` | `MUST NOT` | `AT-BENCH-HOTPATH` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PLAT-001` | `MUST` | `AT-LIFE-PLATFORM` | environment required — Not implemented |
| `LP-PLAT-002` | `MUST` | `AT-BENCH-DEPENDENCY` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PLAT-003` | `MUST` | `AT-BENCH-NATIVE-AB` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PLAT-006` | `MUST` | `AT-REVIEW-AUTO` | Not implemented |
| `LP-PLAT-007` | `MUST NOT` | `AT-BENCH-NATIVE-AB` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PLAT-009` | `MUST` | `AT-LIFE-RUNTIME` | environment required — Not implemented |
| `LP-PLAT-010` | `MUST` | `AT-LIFE-RUNTIME` | environment required — Not implemented |
| `LP-QUAL-010` | `MUST` | `AT-SEC-SHADER` | Not implemented |
| `LP-QUAL-011` | `MUST` | `AT-SEC-SHADER` | Not implemented |
| `LP-QUAL-012` | `MUST` | `AT-SEC-SHADER` | Not implemented |
| `LP-QUAL-013` | `MUST NOT` | `AT-REVIEW-CORE-DAG` | Not implemented |
| `LP-SEC-001` | `MUST` | `AT-SEC-UNSAFE` | Not implemented |
| `LP-SEC-002` | `MUST` | `AT-SEC-UNSAFE` | Not implemented |
| `LP-SEC-003` | `MUST NOT` | `AT-SEC-SHADER` | Not implemented |
| `LP-SEC-004` | `MUST` | `AT-SEC-SIZES` | Not implemented |
| `LP-SEC-005` | `MUST` | `AT-SEC-SHADER` | Not implemented |
| `LP-SEC-006` | `MUST` | `AT-SEC-SBOM` | Not implemented |
| `LP-SEC-007` | `MUST` | `AT-SEC-FONTS` | Not implemented |
| `LP-SEC-008` | `MUST` | `AT-SEC-PUBLIC-DOCS` | Not implemented |
| `LP-TEXT-001` | `MUST` | `AT-SEM-LAYOUT` | Not implemented |
| `LP-TEXT-002` | `MUST NOT` | `AT-SEM-LAYOUT` | Not implemented |
| `LP-TEXT-004` | `MUST` | `AT-SEM-LAYOUT` | Not implemented |
| `LP-TEXT-005` | `MUST` | `AT-EXPORT-PDF-TEXT` | Not implemented |
| `LP-TEXT-006` | `MUST NOT` | `AT-EXPORT-PDF-VECTOR` | Not implemented |
| `LP-MPL-001` | `MUST` | `AT-MPL-LOADER`, `AT-REVIEW-CORE-DAG` | Not implemented |
| `LP-MPL-002` | `MUST` | `AT-MPL-LOADER` | Implemented (bounded Phase-3B local contract evidence: PRs #26/#28/#29/#32; `EntryPointDiscoveryTests`, `DeclaredIdentityConstantsTests`, `TestModuleSurface`) |
| `LP-MPL-003` | `MUST` | `AT-MPL-PROFILES` | Implemented (bounded Phase-3B local contract evidence: `TestProfileSelectionValues`, `TestStagedDefaultProfile`, `TestSelectionIsImmutable`, `TestSelectionDrivesDispatch`; hybrid-explicit-as-default and accelerated-native stay open) |
| `LP-MPL-004` | `MUST` | `AT-MPL-AUTHORITY` | Implemented (bounded Phase-3B local contract evidence: `TestRepeatedRenderIdentity`, `TestDiagnosticImmutabilityAcrossAttempts`, `TestFailureTokenStability`, `TestDerivedSnapshotIntegrity`; full closure stays open) |
| `LP-MPL-005` | `MUST` | `AT-SEM-STATE-REVISION` | Implemented (bounded Phase-3B local contract evidence: PR #41; seam classes in `test_phase3b_native_authority.py`) |
| `LP-MPL-006` | `MUST` | `AT-MPL-FALLBACK` | Not implemented |
| `LP-MPL-007` | `MUST` | `AT-MPL-FALLBACK` | Implemented (bounded Phase-3B local contract evidence: PR #32; `TestHybridFallback`, `TestHybridTerminalFailures`) |
| `LP-MPL-008` | `MUST` | `AT-MPL-FALLBACK` | Implemented (bounded Phase-3B local contract evidence: PR #32; `TestHybridFallback`, `TestHybridTerminalFailures`; schema fields also covered by strict-mode oracle classes) |
| `LP-MPL-009` | `MUST` | `AT-EXPORT-FALLBACK` | Not implemented |
| `LP-MPL-011` | `MUST NOT` | `AT-BENCH-PROFILE-SEPARATION` | Not measured (environment required where hardware or GPU is involved) |
| `LP-MPL-013` | `MUST` | `AT-LIFE-FFI`, `AT-BENCH-PROFILE-SEPARATION` | Not measured (environment required where hardware or GPU is involved) |
| `LP-MPL-015` | `MUST NOT` | `AT-LIFE-FFI`, `AT-BENCH-FFI` | Not measured (environment required where hardware or GPU is involved) |
| `LP-MPL-017` | `MUST` | `AT-REVIEW-DAG` | Not implemented |
| `LP-UX-003` | `MUST NOT` | `AT-REVIEW-UX` | Not implemented |
| `LP-UX-004` | `MUST NOT` | `AT-REVIEW-UX` | Not implemented |
| `LP-UX-005` | `MUST NOT` | `AT-REVIEW-UX` | Not implemented |
| `LP-UX-006` | `MUST NOT` | `AT-FUNC-INPUT` | Not implemented |
| `LP-UX-008` | `MUST NOT` | `AT-REVIEW-UX` | Not implemented |
| `LP-UX-009` | `MUST NOT` | `AT-REVIEW-UX` | Not implemented |
| `LP-UX-010` | `MUST NOT` | `AT-REVIEW-UX` | Not implemented |
| `LP-UX-011` | `MUST NOT` | `AT-REVIEW-UX` | Not implemented |
| `LP-UX-012` | `MUST` | `AT-FUNC-HISTORY` | Implemented (bounded Phase-1B local contract evidence: `home_restores_the_stored_canonical_view` in `crates/lumenplot/tests/history.rs`; release claim stays open) |
| `LP-UX-013` | `MUST NOT` | `AT-SEM-STATE-REVISION` | Implemented (bounded Phase-1B local contract evidence: canonical-stability and no-op/-0.0 equality fixtures in `crates/lumenplot/tests/history.rs`; release claim stays open) |
| `LP-UX-014` | `MUST` | `AT-FUNC-INPUT` | Not implemented |
| `LP-UX-015` | `MUST` | `AT-FUNC-INPUT` | Not implemented |
| `LP-UX-016` | `MUST` | `AT-SEM-LEGEND` | Not implemented |
| `LP-UX-017` | `MUST` | `AT-SEM-LEGEND`, `AT-EXPORT-LEGEND` | Not implemented |
| `LP-UX-018` | `MUST NOT` | `AT-REVIEW-UX` | Not implemented |
| `LP-UX-019` | `MUST` | `AT-SEM-LEGEND` | Not implemented |
| `LP-UX-020` | `MUST` | `AT-SEM-LEGEND` | Not implemented |
| `LP-UX-021` | `MUST` | `AT-SEM-STATE-REVISION`, `AT-EXPORT-STATE` | Not implemented |
| `LP-UX-022` | `MUST` | `AT-SEM-LEGEND`, `AT-EXPORT-LEGEND` | Not implemented |
| `LP-QUAL-014` | `MUST` | `AT-SEM-STATE-REVISION` | Not implemented |
| `LP-QUAL-015` | `MUST` | `AT-EXPORT-STATE` | Not implemented |
| `LP-QUAL-016` | `MUST NOT` | `AT-EXPORT-STATE` | Not implemented |
| `LP-QUAL-017` | `MUST` | `AT-SEM-STATE-REVISION`, `AT-LIFE-RUNTIME` | environment required — Not implemented |
| `LP-QUAL-018` | `MUST` | `AT-LIFE-CANCELLATION` | Not implemented |
| `LP-QUAL-019` | `MUST NOT` | `AT-LIFE-FFI` | Not implemented |
| `LP-QUAL-020` | `MUST` | `AT-LIFE-RUNTIME` | environment required — Not implemented |
| `LP-EXPORT-001` | `MUST` | `AT-EXPORT-PNG` | Not implemented |
| `LP-EXPORT-002` | `MUST` | `AT-EXPORT-PDF-VECTOR` | Not implemented |
| `LP-EXPORT-004` | `MUST` | `AT-EXPORT-STATE` | Not implemented |
| `LP-EXPORT-005` | `MUST` | `AT-EXPORT-PDF-VECTOR` | Not implemented |
| `LP-EXPORT-006` | `MUST NOT` | `AT-EXPORT-PDF-VECTOR` | Not implemented |
| `LP-EXPORT-007` | `MUST` | `AT-SEM-LAYOUT`, `AT-EXPORT-LEGEND` | Not implemented |
| `LP-EXPORT-008` | `MUST NOT` | `AT-EXPORT-STATE` | Not implemented |
| `LP-EXPORT-009` | `MUST` | `AT-EXPORT-FALLBACK` | Not implemented |
| `LP-UX-023` | `MUST` | `AT-FUNC-CURSOR` | Not implemented |
| `LP-EXPORT-010` | `MUST NOT` | `AT-EXPORT-STATE` | Not implemented |
| `LP-UX-025` | `MUST NOT` | `AT-REVIEW-UX` | Not implemented |
| `LP-UX-028` | `MUST` | `AT-FUNC-KEYBOARD-A11Y` | Not implemented |
| `LP-UX-030` | `MUST` | `AT-FUNC-KEYBOARD-A11Y` | Not implemented |
| `LP-UX-031` | `MUST` | `AT-REVIEW-A11Y` | Not implemented |
| `LP-UX-032` | `MUST` | `AT-REVIEW-A11Y` | Not implemented |
| `LP-PERF-001` | `MUST` | `AT-BENCH-NATIVE-10M` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PERF-004` | `MUST` | `AT-BENCH-NATIVE-10M` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PERF-006` | `MUST` | `AT-BENCH-HOTPATH` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PERF-008` | `MUST` | `AT-BENCH-LEGEND-1FRAME` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PERF-009` | `MUST` | `AT-BENCH-MANIFEST` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PERF-010` | `MUST` | `AT-BENCH-MANIFEST` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PERF-011` | `MUST` | `AT-BENCH-MANIFEST` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PERF-013` | `MUST` | `AT-BENCH-MANIFEST` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PERF-014` | `MUST` | `AT-BENCH-MANIFEST` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PERF-015` | `MUST` | `AT-BENCH-MANIFEST` | Not measured (environment required where hardware or GPU is involved) |
| `LP-QUAL-021` | `MUST` | `AT-BENCH-PROFILE-SEPARATION` | Not measured (environment required where hardware or GPU is involved) |
| `LP-QUAL-022` | `MUST` | `AT-BENCH-DEPENDENCY` | Not measured (environment required where hardware or GPU is involved) |
| `LP-QUAL-023` | `MUST` | `AT-BENCH-DEPENDENCY` | Not measured (environment required where hardware or GPU is involved) |
| `LP-PLAT-011` | `MUST` | `AT-BENCH-NATIVE-AB` | Not measured (environment required where hardware or GPU is involved) |
| `LP-REL-002` | `MUST` | `AT-REVIEW-RELEASE` | Not implemented |
| `LP-MPL-018` | `MUST` | `AT-FUNC-VIEWER`, `AT-REVIEW-DAG` | Not implemented |
| `LP-MPL-019` | `MUST NOT` | `AT-REVIEW-DAG` | Not implemented |
| `LP-FUNC-032` | `MUST` | `AT-FUNC-FILL` | Implemented (bounded Phase-3B local contract evidence: PR #68; fill/fill-between eligibility with §5.4 Agg-oracle parity fixtures in `test_phase3b_fill.py`; release claim stays open) |
| `LP-FUNC-033` | `MUST` | `AT-FUNC-BAR` | Implemented (bounded Phase-3B local contract evidence: PR #69; bar eligibility with §5.4 Agg-oracle parity fixtures in `test_phase3b_bar.py`; release claim stays open) |
| `LP-FUNC-034` | `MUST` | `AT-FUNC-DRAWSTYLE` | Implemented (bounded Phase-3B local contract evidence: PR #70; step-drawstyle eligibility with §5.4 Agg-oracle parity fixtures in `test_phase3b_steps.py`; release claim stays open) |
| `LP-REL-009` | `MUST` | `AT-REVIEW-TRACEABILITY` | Not implemented |
| `LP-REL-010` | `MUST` | `AT-RELEASE-FUNCTIONAL` | Not implemented |
| `LP-REL-011` | `MUST` | `AT-RELEASE-CORRECTNESS` | Not implemented |
| `LP-REL-012` | `MUST` | `AT-RELEASE-PERFORMANCE` | Not implemented |
| `LP-REL-013` | `MUST` | `AT-RELEASE-QUALITY` | Not implemented |
| `LP-REL-014` | `MUST NOT` | `AT-REVIEW-RELEASE` | Not implemented |
| `LP-QUAL-028` | `MUST` | `AT-REVIEW-DEPENDENCIES` | Not implemented |

## Evidence plans by requirement family

| Family | Evidence focus | Current boundary |
| --- | --- | --- |
| `LP-DATA` | f64 authority, sealed chunk ownership, local-f32 conversion, and residency | Phase-1 owned-data/chunk implementation and local evidence exist under [ADR 0010](../adr/0010-phase1-native-core-facade-contract.md); full v1 local-f32, residency, and scale evidence remains pending. |
| `LP-EXPORT` | PNG/PDF blockers, SVG non-blocking path, state snapshots, and fallback scope | [ADR 0012](../adr/0012-private-line-frame-and-png-contract.md) records the private line/PNG boundary and its bounded implementation/local evidence; full-v1 export, state, vector, and fallback evidence remain pending. |
| `LP-FUNC` | native functional interaction, annotations, viewer, optional capability scope, and the adopted Matplotlib major-feature rows | Phase-1 view/scale implementation and local evidence are recorded in [API 0001](../architecture/api-0001-native-scene-state.md); interaction, annotations, viewer, and v1 evidence remain pending. `LP-FUNC-008` now carries bounded implemented evidence for the deterministic history-transition state substrate (canonical-view restore, stability under interaction, no-op/-0.0 equality, atomic validation) in `crates/lumenplot/tests/history.rs`, while gesture routing and animated transitions stay open. The 2026-08-25 adoption added `LP-FUNC-032`–`LP-FUNC-039` (polygon fill, bars/histograms, step drawstyles, cross-primitive compositing, polar, date/unit axes, quiver, scale extensions) from [`matplotlib-parity-requirements-draft.md`](matplotlib-parity-requirements-draft.md); the W1 "static geometry" rows (`LP-FUNC-032`/`033`/`034`) now carry bounded implemented results (PRs #68/#69/#70, integrated by PR #71 with mixed-workload composition fixtures in `test_phase3b_integration_mixed.py`) whose §5.4 Agg-oracle parity gates are met within recorded thresholds, while the remaining added rows stay `Not implemented`, the flagged contract impacts in that document's Section 8 are hand-off notes for the architecture authority, not designs, and every gate above is additionally bound to that document's §5.4 quality oracle: acceptance requires Agg parity fixtures (geometry parity to sub-pixel rounding, decoded-pixel difference within recorded thresholds, style semantics equal to Agg's resolution; text via `TextPath` outline comparison). |
| `LP-LOD` | MonotonicX dyadic extrema and ArbitraryXY correctness/culling | Phase-1 selection implementation and local evidence are recorded in [ADR 0010](../adr/0010-phase1-native-core-facade-contract.md); the MonotonicX negative/spike/extrema fixtures (`LP-LOD-002`/`LP-LOD-003`, brute-force oracle plus stride negative control), the ArbitraryXY order-invariance/exact-culling/source-order fixtures (`LP-LOD-006`), the bucketed-extrema oracle over spikes/duplicate-x/chunk-cut splits, the strict x-nondecreasing selection guard, and the topology-model fixtures (`LP-LOD-004`) now carry bounded implemented results naming their test functions; the dyadic block index is additionally pinned against a naive linear scan across chunk cuts and ties. All benchmark claims (`LP-LOD-001`/`LP-LOD-005`) remain unmeasured — no performance evidence is claimed by these local fixtures. |
| `LP-MPL` | loader, profiles, authority, fallback diagnostics, eligibility governance, FFI, and separated performance claims | Phase-1 public error mapping is recorded in [API 0002](../architecture/api-0002-errors-capabilities-fallback.md); [API 0003](../architecture/api-0003-python-numpy-matplotlib.md), [ADR 0013](../adr/0013-hidden-facade-private-python-line-png.md), and [ADR 0014](../adr/0014-phase3a2-pinned-manylinux-wheel-evidence.md) record the staged Phase-3A helper and Phase-3A2 pinned wheel/evidence boundaries; the Phase-3A2 private-helper one-wheel build and same-wheel CPython 3.11–3.14 runtime evidence exist as CI-local evidence; the Phase-3B first strict slice (whole-frame seam plus public strict-mode backend) is merged with local contract-test evidence, PRs #26/#28/#29 add the entry-point manifest, the standing Python contract gate, and the wheel/entry-point evidence job (green on `main`), and PR #32 adds hybrid-explicit whole-frame fallback with terminal-failure guards and reconciled strict-style fixtures; loader/packaging identity (`LP-MPL-002`) and the fallback-fixture/diagnostic-schema rows (`LP-MPL-007`/`LP-MPL-008`) now carry bounded implemented results naming their merged test classes, while profile selection, adapter authority/revision fixtures, the full strict error-fixture set, mixed vector/raster output, packaged public-backend runtime evidence, and all benchmark claims remain open. The 2026-08-25 adoption added `LP-MPL-020` (`AT-MPL-ELIGIBILITY`): a `SHOULD` governance row fixing how the strict-mode whitelist may grow for future artist classes per the accepted O-10 boundary mechanics — it is pending like every other open row and adds no implementation claim. |
| `LP-PERF` | 10M native gate, workload fixtures, warm-up, segments, quantiles, and manifests | Pending implementation and evidence; no completion is claimed. |
| `LP-PLAT` | capability selection, main-thread runtime, surfaces, device loss, and platform matrix | Pending implementation and evidence; no completion is claimed. |
| `LP-PROD` | product independence, shared semantic frame, and core dependency direction | Phase-1 native core/facade implementation and local evidence are recorded in [ADR 0010](../adr/0010-phase1-native-core-facade-contract.md); the shared v1 frame and product evidence remain pending. |
| `LP-QUAL` | hot path, lifecycle, shaders, dependency gates, repository boundary, and release quality | Phase-1 Scene ownership/publication implementation and local evidence are recorded in [API 0001](../architecture/api-0001-native-scene-state.md); lifecycle, hot-path, shader, and release evidence remain pending. |
| `LP-REL` | phase placement, release inclusion, and no-claim-before-evidence review | Phase-1A/B local implementation evidence is present; v1 release inclusion and no-claim gates remain open. |
| `LP-RENDER` | line expansion, width, HiDPI, alpha, clipping, and antialiasing | [ADR 0012](../adr/0012-private-line-frame-and-png-contract.md) records the private line-frame/coverage boundary; renderer, golden, and v1 evidence remain pending. |
| `LP-SEC` | unsafe boundary, runtime shader policy, input validation, provenance, SBOM, fonts, and public docs | Pending implementation and evidence; no completion is claimed. |
| `LP-TEXT` | one shaping/layout result, font identity, PDF text, and vector semantics | Pending implementation and evidence; no completion is claimed. |
| `LP-UX` | direct manipulation, Legend state, keyboard, focus, contrast, and reduced motion | `LP-UX-012`/`LP-UX-013` carry bounded Phase-1B implemented evidence for the canonical-view fixture and the state-and-history fixture in `crates/lumenplot/tests/history.rs`; direct manipulation, Legend state, keyboard, focus, contrast, reduced motion, and all release claims remain pending with no completion claimed. |

## Release evidence checklist

| Release area | Required evidence | Current result |
| --- | --- | --- |
| Functional v1 | `AT-RELEASE-FUNCTIONAL` plus linked `AT-FUNC-*`, `AT-LIFE-*`, and `AT-MPL-*` results for every declared matrix cell. | Not implemented; environment required for platform cells. |
| Correctness v1 | `AT-RELEASE-CORRECTNESS` plus f64, LOD, state, layout, export, fallback, and HiDPI fixtures. | Not implemented. |
| Native performance | `AT-RELEASE-PERFORMANCE` plus 10M MonotonicX, hot-path counters, dependency regression, and per-cell p99. | Not measured; environment required. |
| Quality and security | `AT-RELEASE-QUALITY`, unsafe scan, shader provenance, SBOM/license evidence, accessibility review, and persistence scope review. | Not implemented. |

## Source-section and phase consistency checks

- Appendix A of the requirements document covers all original sections 1–36 and states whether wording was retained, clarified, or bounded.
- Annotations and standalone viewer are v1 requirements and have explicit functional, release, and phase entries.
- ArbitraryXY topology/correctness/culling is a v1 model/correctness lane; advanced simplification and picking performance are Phase 5.
- SVG is a v1 `SHOULD` and non-blocking; PNG and PDF are v1 `MUST` outputs.
- Reference dependency versions are non-normative and are not counted as support evidence.
- The Matplotlib major-feature rows (`LP-FUNC-032`–`LP-FUNC-039`, `LP-MPL-020`) were adopted on 2026-08-25 from [`matplotlib-parity-requirements-draft.md`](matplotlib-parity-requirements-draft.md); their wave placement (3B-cont. / 3B-cont.+1 / Phase 5 / future / continuous) is recorded per row, and 3D stays excluded per `LP-FUNC-025`. On the same date the maintainer fixed their shared acceptance quality bar — "implemented to the same quality as the current Matplotlib backend (Agg)" — canonized on 2026-08-26 in Section 5.4 of that document and reflected in this registry's Target cells and evidence plans: each gate is met only by Agg parity fixtures (geometry parity to sub-pixel rounding, decoded-pixel difference within recorded thresholds, style semantics equal to Agg's resolution; text via `TextPath` outline comparison). This fixed gate conditions only; no row's class or phase placement changed. On 2026-08-26 the W1 workstream satisfied those conditions for exactly three rows — `LP-FUNC-032`/`033`/`034` (PRs #68/#69/#70; mixed-workload integration #71) — whose result cells now carry bounded implemented evidence naming their merged fixture classes; all other results are unchanged.

## Honest evidence boundary

No parent research, compile spike, export spike, platform observation, or candidate dependency release is reused as LumenPlot product evidence here. A later implementation must replace each pending result with a reproducible artifact, test output, benchmark manifest, or review record before a release claim is made.
