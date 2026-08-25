# Matplotlib major-feature native-rendering requirements — DRAFT

## Status

**DRAFT — REQUIREMENTS DRAFTING ONLY. NOT AN ACCEPTED DECISION, NOT AN AMENDMENT,
AND NOT A SUPPORT CLAIM.**

- This document is a *new standalone draft* prepared for integration review. It does
  **not** modify [`lumenplot-v1.0.md`](lumenplot-v1.0.md),
  [`traceability-v1.0.md`](traceability-v1.0.md), any ADR/API record, or any open-decision
  item. Adoption, ID canonization, and any v1.0 rewrite belong exclusively to the human
  architecture authority.
- Every proposed requirement below is marked **[PROPOSED]** and carries a candidate ID in
  the next free slot of its family (`LP-FUNC-032`+, `LP-MPL-020`). Until adopted, these IDs
  are placeholders and must not be cited as existing requirements.
- Requirement levels (`MUST` / `SHOULD` / `MAY`), the registry table format, the evidence-gate
  vocabulary, and the phase model follow [`lumenplot-v1.0.md`](lumenplot-v1.0.md) §2, §32,
  and Appendix A exactly. New evidence-gate names are proposed and require registration in
  the traceability vocabulary if adopted.
- Scope boundary: **3D (mplot3d) remains out of scope** consistent with
  `LP-FUNC-025` (NON-GOAL) and the existing post-v1 3D research notes. Nothing here reopens it.
- Public-safety: this draft contains no private task identifiers, local paths, host details,
  or internal artifact references (`LP-SEC-008` boundary respected).

## How to read this document

1. Section 3 inventories the rendering-relevant Matplotlib feature surface as artists and
   transform paths (not pyplot entry points).
2. Section 4 maps every inventoried feature onto the canonical v1.0 registry and states the
   verdict: already covered / partially covered / uncovered.
3. Section 5 drafts new candidate rows **only** for uncovered features whose addition is
   justified by the recorded priority criteria.
4. Sections 6–8 record the priority rationale, phase-placement proposal, and flagged contract
   impacts. Design work is deliberately excluded; flagged impacts are hand-off notes for the
   architecture authority, not designs.

---

## 1. Problem statement

The accepted product direction is an independent GPU-native engine plus a first-class one-way
Matplotlib adapter (ADR 0002; profile roles fixed by ADR 0015 / API 0005). Today the merged
Phase-3B slices natively render exactly one eligible trace — plain solid `Line2D` strokes on a
single axes with decorations disabled — and fall back to whole-frame Agg otherwise. Practical
consequence: ordinary figures (axes, fills, bars, steps, multiple primitive kinds) either
reject in strict mode or forfeit all native benefit in hybrid mode.

This draft defines, in canonical requirement form, what "render the major features of
Matplotlib natively" means for LumenPlot — bounded by the existing non-goals
(`LP-PROD-006`, `LP-PROD-007`: no full backend-API parity, no Artist-hierarchy
reimplementation) and by the one-way adapter contract.

## 2. Method followed (auditable)

1. **Inventory** — the rendering-relevant Matplotlib surface was enumerated as
   artist/transform classes (Section 3), deliberately excluding pyplot convenience APIs,
   GUI embedding, animation, widgets, and backend infrastructure.
2. **Reconciliation against the canonical registry** — each feature was mapped onto the
   v1.0 registry (223 entries; source of truth `lumenplot-v1.0.md` +
   `traceability-v1.0.md`). Features already owned by an existing row did **not** receive a
   new ID (Section 4).
3. **Gap drafting** — only uncovered features received candidate rows, written in the exact
   v1.0 row grammar with Target/Release/Phase/Evidence fields (Section 5).
4. **Evidence-based leveling** — `MUST` is reserved for low-cost static-geometry extensions
   of the accepted line path with outsized coverage gains; `SHOULD` for capabilities needing
   new transforms, projections, or cross-primitive semantic guarantees; `MAY` for candidates
   with adverse cost/risk balance. Nothing is leveled `MUST` by default (Section 6).
5. **Phase placement** — proposals align with the current implementation state (Phase-3B
   public backend merged; axes-decoration, text-minimal-surface, and multi-axes lanes planned
   separately; native performance gate untouched) (Section 7).

## 3. Feature inventory (rendering-relevant surface)

Grouped by artist/transform path. "Strict-native eligible today?" reflects the merged
Phase-3B slice behavior.

| # | Group | Matplotlib surface | Strict-native today |
| --- | --- | --- | --- |
| F-01 | Line series | `Line2D` (solid, butt/miter, default drawstyle) | yes |
| F-02 | Multi-series overlay | multiple `Line2D` per Axes, stable z-order | yes (same trace shape) |
| F-03 | Scatter | `Collection` paths (`scatter`) | no — outside whitelist |
| F-04 | Filled areas | `Polygon` via `fill` / `fill_between` / `stackplot` | no — outside whitelist |
| F-05 | Bars / histograms | `Rectangle` patches (`bar`, `barh`, `hist`) | no — outside whitelist |
| F-06 | Markers | marker props on lines/collections | no — explicit unsupported result |
| F-07 | Error bars | `ErrorbarContainer` (line + cap/bar collection) | no — outside whitelist |
| F-08 | Step / stair drawstyles | `drawstyle` steps-pre/post/mid | no — explicit unsupported result |
| F-09 | Axes decorations | spines, ticks, tick labels, axis labels, grid | no — `axison=True` rejected |
| F-10 | Scales | linear, log, symlog, logit; date/unit axes | linear only |
| F-11 | Legend | publication legend artist | no — outside whitelist |
| F-12 | Colorbar | mappable-derived artist strip | no — outside whitelist |
| F-13 | Images | `AxesImage` / `imshow` (incl. RGB(A), interpolation) | no — outside whitelist |
| F-14 | Text / annotations / TeX | `Text`, `Annotation`, math text | no — explicit unsupported result (TeX unconfigured) |
| F-15 | Layouts | subplots/gridspec, twin/secondary axes, insets | single-axes only |
| F-16 | Styles / rcParams | rendering-affecting defaults (colors, widths, fonts) | resolved values flow through Figure authority |
| F-17 | Vector fields | `Quiver`, `Barbs`, `streamplot` lines/arrows | no — outside whitelist |
| F-18 | Polar projection | polar Axes transform | no — rectangular-clip contract violated |
| F-19 | Contours | `contour`/`contourf` path collections | no — outside whitelist |

Out of scope by standing decisions: 3D (`mplot3d`), full backend-API parity, custom-Artist
parity, Artist-hierarchy reimplementation (`LP-FUNC-025`, `LP-PROD-006`, `LP-PROD-007`).

## 4. Reconciliation matrix (feature × registry)

Verdicts: **COVERED** (existing row owns it — no new ID), **PARTIAL** (existing row owns the
capability but a named sub-capability is missing — assessed case by case), **UNCOVERED**
(draft a candidate row or defer with rationale). Cross-lane items owned by the separate
axes-on planning effort are marked **LANDED ELSEWHERE** to prevent duplicate IDs.

| Feature group | Existing registry owner(s) | Candidate new ID | Proposed level | Proposed phase | Evidence gate (proposed) | Verdict / note |
| --- | --- | --- | --- | --- | --- | --- |
| F-01 line series | `LP-FUNC-001`, `LP-RENDER-001`–`006`, `LP-MPL-004`–`008` | — | — | — | — | COVERED |
| F-02 multi-series | `LP-FUNC-002` | — | — | — | — | COVERED |
| F-03 scatter | `LP-FUNC-017` (SHOULD, Ph 5) | — | — | — | — | COVERED (deliberate non-blocking placement) |
| F-04 filled areas | — | **LP-FUNC-032** [PROPOSED] | MUST | 3B-cont. | `AT-FUNC-FILL` | UNCOVERED — no registry row owns polygon fill rendering anywhere (native or adapter) |
| F-05 bars / histograms | — | **LP-FUNC-033** [PROPOSED] | MUST | 3B-cont. | `AT-FUNC-BAR` | UNCOVERED — rectangle fill+stroke semantics absent; histogram = adapter-side binning + this row (no engine data-binning requirement) |
| F-06 markers | `LP-FUNC-018` (SHOULD, Ph 5) | — | — | — | — | COVERED |
| F-07 error bars | `LP-FUNC-019` (SHOULD, Ph 5) | — | — | — | — | COVERED |
| F-08 step drawstyles | — | **LP-FUNC-034** [PROPOSED] | MUST | 3B-cont. | `AT-FUNC-DRAWSTYLE` | PARTIAL→UNCOVERED — `LP-FUNC-001` fixes "default" drawstyle implicitly via the eligible-trace contract; step variants are rejected with no owning row |
| F-09 axes decorations | axes-on planning lane (separate card) + `LP-FUNC-003` | — | — | — | — | LANDED ELSEWHERE — spines/ticks/labels/text minimal surface and multi-axes spec are owned by the practical-expansion planning card; this draft creates no competing IDs |
| F-10 linear scale | `LP-FUNC-003` | — | — | — | — | COVERED |
| F-10 log scale | `LP-FUNC-004` | — | — | — | — | COVERED |
| F-10 symlog / logit | — | **LP-FUNC-039** [PROPOSED] | MAY | future | `AT-SEM-SCALE-EXT` | UNCOVERED — deferred candidate; see contract-impact flag C-5 (MonotonicX topology interaction) |
| F-10 date/unit axes | `LP-FUNC-003` (transitively: unit conversion happens upstream of the public getters) | **LP-FUNC-037** [PROPOSED] | SHOULD | 3B-cont.+1 | `AT-FUNC-DATE-AXIS` | PARTIAL — base plotting rides the linear path unchanged, but unit-aware tick-label formatting (date locators/formatters) has no owning row once axes-on lands |
| F-11 legend | `LP-FUNC-009`, `LP-UX-016`–`022` | — | — | — | — | COVERED |
| F-12 colorbar | `LP-MPL-007` (whole-frame fallback) for adapter mode; native = future | — | — | — | — | COVERED for v1 adapter semantics (colorbar content forces declared hybrid fallback); a native colorbar row is deliberately **not** drafted — revisit with image/mappable support post-v1 |
| F-13 images / imshow | `LP-FUNC-023` (MAY, future) | — | — | — | — | COVERED (already adjudicated as post-v1 candidate) |
| F-19 contours | `LP-FUNC-024` (MAY, future) | — | — | — | — | COVERED |
| F-14 text / annotations / TeX | `LP-FUNC-012`, `LP-TEXT-001`–`007`, `LP-MPL-006`, `LP-MPL-012` | — | — | — | — | COVERED (strict raises on unknown/unconfigured TeX; hybrid falls back whole-frame; shared-layout contracts own export identity) |
| F-15 subplots/gridspec | multi-axes lane (see F-09 note) | — | — | — | — | LANDED ELSEWHERE |
| F-15 twin / secondary axes | `LP-FUNC-020` (SHOULD, Ph 5) | — | — | — | — | COVERED |
| F-16 styles / rcParams | `LP-MPL-004` (Figure authority) | — | — | — | — | COVERED — adapter reads resolved values through the authoritative Figure graph; rcParams *parity* is not a goal and gets no row |
| F-17 vector fields | — | **LP-FUNC-038** [PROPOSED] | SHOULD | 5 | `AT-FUNC-QUIVER` | UNCOVERED — quiver arrows are deterministic glyph geometry; streamplot stays out (trajectory-integration algorithm belongs to analysis, cf. `LP-PROD-009`) |
| F-18 polar projection | — | **LP-FUNC-036** [PROPOSED] | SHOULD | 5 | `AT-FUNC-POLAR` | UNCOVERED — new transform family; rectangular clip/background contracts assume rectangles |
| — | — | **LP-FUNC-035** [PROPOSED] | SHOULD | 3B-cont.+1 | `AT-SEM-COMPOSITING` | UNCOVERED — cross-primitive z-order/alpha guarantee; `LP-RENDER-004` owns alpha semantics for *supported* layers but no row pins ordering *across* primitive classes once fills/bars exist |
| — | — | **LP-MPL-020** [PROPOSED] | SHOULD | continuous | `AT-MPL-ELIGIBILITY` | Governance gap — no row defines *how* the strict whitelist may grow; this operationalizes the accepted O-10 boundary mechanics for every future artist class |

Correction note: the MPL family already extends to `LP-MPL-019` (one-way-integration and standalone rows), so the governance candidate takes `LP-MPL-020`;
the FUNC family ends at `LP-FUNC-031`, so candidate numbering starts at 032. Proposed gate
names were checked against the 92 registered evidence gates — none collide.

## 5. Proposed requirement rows [PROPOSED — not adopted]

Grammar, field semantics, and release vocabulary follow `lumenplot-v1.0.md`. Each row states
its gap justification inline in prose beneath the row.

### 5.1 Functional candidates

- **LP-FUNC-032** | `MUST` | Support filled polygons (fill and fill-between areas) with declared face color, edge, alpha, and correct baseline/span semantics, in native and adapter rendering. | Target: fill geometry and span fixtures | Release: v1 | Phase: 3B-cont. | Evidence: `AT-FUNC-FILL`

  *Gap*: the registry renders only stroked polylines (`LP-FUNC-001`, `LP-RENDER-001`).
  `fill`/`fill_between`/`stackplot` are among the most frequent scientific-plot primitives;
  today they force whole-frame Agg fallback (hybrid) or rejection (strict), eliminating native
  benefit for typical figures. Static-geometry expansion of the accepted screen-space path;
  no new transform family. Histograms intentionally require no separate row: binning stays
  adapter-side (Figure authority, `LP-MPL-004`), rendered bars satisfy this row.

- **LP-FUNC-033** | `MUST` | Support bar charts as filled-and-stroked rectangles anchored to a declared baseline, including negative and stacked baselines, with per-bar style resolution. | Target: bar geometry and stacking fixtures | Release: v1 | Phase: 3B-cont. | Evidence: `AT-FUNC-BAR`

  *Gap*: no registry row owns rectangle rendering. Together with LP-FUNC-032 this closes the
  categorical/aggregated-data surface, which dominates instrumentation and comparison plots.
  Same implementation family as fills (triangle tessellation of static geometry).

- **LP-FUNC-034** | `MUST` | Support step-series drawstyles (steps-pre, steps-post, steps-mid) as exact vertex-generation semantics on the line path, preserving monotonic-topology eligibility for LOD. | Target: drawstyle equivalence fixtures against Agg | Release: v1 | Phase: 3B-cont. | Evidence: `AT-FUNC-DRAWSTYLE`

  *Gap*: step plots are ubiquitous for sampled/measurement series; the eligible-trace
  contract currently rejects non-default drawstyles with no owning requirement for ever
  supporting them. Vertex-generation-only change; flagged for LOD topology compatibility
  (C-3) because steps remain piecewise-montonic in x.

- **LP-FUNC-035** | `SHOULD` | Preserve painter's-algorithm ordering and alpha compositing semantics across mixed primitive classes (lines, fills, bars) within one frame in all output paths. | Target: cross-primitive ordering and alpha golden tests | Release: v1 quality | Phase: 3B-cont.+1 | Evidence: `AT-SEM-COMPOSITING`

  *Gap*: `LP-RENDER-004` preserves alpha semantics "for supported colors and layers" but no
  row pins *inter-class* ordering once more than one primitive class exists. Without this
  guarantee, introducing fills/bars (032/033) can produce silently wrong occlusion — exactly
  the silent-degradation class the fallback charter forbids. Prerequisite dependency noted:
  correct opaque-background compositing (current background-loss fix lane) must land first.

- **LP-FUNC-036** | `SHOULD` | Support polar projection for line and fill primitives with angle/radius tick semantics equivalent to the linear-axes decoration contract. | Target: polar transform fixtures | Release: v1 non-blocking | Phase: 5 | Evidence: `AT-FUNC-POLAR`

  *Gap*: polar axes are a standard scientific view (directional/pattern data). Requires a new
  transform family and generalizing the rectangular clip/background assumptions of the
  current request schema — genuine architecture surface, hence SHOULD non-blocking, not MUST.
  Contract flag C-4 applies.

- **LP-FUNC-037** | `SHOULD` | Format tick labels for date and unit-aware axes using the authoritative converter/locator information from the Figure graph. | Target: date-tick formatting fixtures | Release: v1 quality | Phase: 3B-cont.+1 | Evidence: `AT-FUNC-DATE-AXIS`

  *Gap*: date-valued data already flows correctly (units resolve to floats upstream of the
  public getters the adapter reads), but once the axes-decoration lane delivers tick labels,
  unit-aware formatting has no owning row. Kept separate from `LP-FUNC-003` (linear axes
  correctness) so the numeric contract is not burdened with localization/format concerns.

- **LP-FUNC-038** | `SHOULD` | Support quiver-style vector fields as deterministic arrow glyphs derived from grid or dispersed sample vectors. | Target: quiver geometry and scaling fixtures | Release: v1 non-blocking | Phase: 5 | Evidence: `AT-FUNC-QUIVER`

  *Gap*: vector fields appear across experimental-fluids/EM/instrument workloads; glyph
  geometry is deterministic and LOD-friendly. Streamplot is deliberately excluded: trajectory
  integration is analysis-adjacent (`LP-PROD-009`) and belongs to a separate future decision.

- **LP-FUNC-039** | `MAY` | Add further axis scales (symlog, logit) after an explicit transform-and-topology decision records their interaction with LOD hierarchy selection. | Target: scale-extension decision record | Release: future | Phase: future | Evidence: `AT-SEM-SCALE-EXT`

  *Rationale for MAY (not SHOULD)*: moderate usage frequency versus high contract risk —
  segment-linear transforms interact with MonotonicX topology detection and hierarchy
  selection (flag C-5). Adoption must follow, not precede, the topology decision.

### 5.2 Adapter governance candidate

- **LP-MPL-020** | `SHOULD` | Grow the strict-common-2d eligibility surface only by explicit per-class contract extensions — whitelist entry, collector-trace expectation, style contract, and fixtures landed together — never by silent approximation or default-on tolerance. | Target: eligibility-extension process review | Release: v1 quality | Phase: continuous | Evidence: `AT-MPL-ELIGIBILITY`

  *Gap*: the accepted Phase-3B contract fixes today's whitelist mechanically (exact object
  whitelist + exact eligible trace), which is correct for the current slice but leaves the
  *growth protocol* undefined. Without a governing row, each new artist class (fills, bars,
  steps — i.e., every candidate above) ad-hocly renegotiates the strict contract. This row
  binds future growth to the established mechanics: stage-one whitelist + stage-two public
  collector trace + explicit unsupported results for everything else. It changes no accepted
  decision; it operationalizes the existing O-10 boundary for subsequent slices.

### 5.3 Deliberately *not* drafted

- **Colorbar (native)** — adapter-mode semantics are fully served by the declared
  whole-frame fallback (`LP-MPL-007`); a native colorbar presumes mappable/image support
  (`LP-FUNC-022`/`LP-FUNC-023`, post-v1). Drafting now would front-run that adjudication.
- **Histogram binning** — data-space binning is analysis work performed adapter-side under
  Figure authority; the engine renders pre-computed bars (LP-FUNC-033).
- **Streamplot** — algorithmic trajectory integration conflicts with the
  no-analysis-responsibilities boundary (`LP-PROD-009`).
- **rcParams parity** — resolved values arrive through the authoritative Figure graph;
  parity of the *mechanism* is a non-goal (`LP-PROD-006`/`LP-MPL-004`).
- **Axes decorations, tick/label text surface, multi-axes/subplot spec** — owned by the
  active practical-expansion planning lane; duplicated IDs here would fork ownership.

## 6. Priority rationale ("major feature" test)

A feature qualifies as *major* — and its row's level — by scoring all four criteria; no
single criterion decides:

1. **Usage frequency** in scientific/measurement plotting practice (Matplotlib gallery
   weight and typical instrument/dashboard figure composition). Lines+fills+bars+decorated
   axes cover the overwhelming majority of 2-D scientific figures; scatter/markers/errorbars
   are common but already placed non-blocking by prior adjudication.
2. **User impact when missing** — measured in fallback cost: every non-whitelisted primitive
   converts a potentially native frame into whole-frame Agg (zero native benefit) or a strict
   rejection (adoption blocker). Fill/bars/steps sit on nearly every such path.
3. **Engine implementation cost** — static-geometry expansions of the accepted
   screen-space-expansion path (fills, bars, steps) are cheap relative to their coverage;
   transform-family additions (polar, scales) and semantic guarantees (compositing) are
   costlier, hence lower levels.
4. **Contract risk** — rows touching RenderPacket schema, LOD topology, or the strict
   eligibility mechanics carry flags (Section 8) and cannot exceed SHOULD until the flagged
   decision is recorded — except LP-FUNC-032/033/034, whose risk is bounded to one
   schema-class extension flagged for the authority rather than hidden.

Leveling outcome: 3 MUSTs (cheap, maximal coverage, bounded risk), 4 SHOULDs (real demand,
higher cost/risk), 1 governance SHOULD, 1 MAY (risk-dominated). No row is MUST by fiat.

## 7. Phase-placement proposal

Aligned with actual implementation state: Phase-3B public backend merged; background-pixel,
dependency, README/IDAT correction lanes in flight; axes-decoration / text-minimal /
multi-axes lanes planned; native benchmark gate untouched.

| Wave | Content | Rationale |
| --- | --- | --- |
| **W1 — "static geometry" (Phase 3B continuation, adapter + engine seam)** | LP-FUNC-032 (fill), LP-FUNC-033 (bar), LP-FUNC-034 (steps); LP-MPL-020 governs each slice | largest coverage-per-cost; pure geometry; each lands as an eligibility extension per the governance row; prerequisite: background-compositing fix merged so decoded-pixel assertions stay meaningful |
| **W2 — "correct composition" (after W1 + axes-on stabilizes)** | LP-FUNC-035 (cross-primitive compositing), LP-FUNC-037 (date tick labels) | compositing needs ≥2 primitive classes to exist; label formatting needs the axes-decoration text surface |
| **W3 — "expansion" (Phase 5 train, beside existing FUNC-017–020)** | LP-FUNC-036 (polar), LP-FUNC-038 (quiver); LP-FUNC-039 held pending topology decision | matches the existing Phase-5 expansion bundle placement; no competition with v1 native gate lanes |

Native-viewer parity follows the same waves where the capability is engine-side; the adapter
profile separation rules (`LP-MPL-011`, `LP-QUAL-021`) apply unchanged — nothing here moves
any performance gate onto adapter profiles.

## 8. Flagged contract impacts (flags only — no design)

| # | Flag | Affected candidates | Decision surface |
| --- | --- | --- | --- |
| C-1 | RenderPacket command set is line-stroke-shaped; fill/bar primitives imply a new command class (filled geometry) | LP-FUNC-032, LP-FUNC-033 | RenderPacket schema owner (O-04); architecture authority; process-local/internal/non-serialized invariants (`LP-PROD-012`) must hold |
| C-2 | Eligibility whitelist/trace growth mechanics | all W1 rows via LP-MPL-020 | operationalizes the accepted Phase-3B boundary mechanics; amend-or-reference decision for O-10 |
| C-3 | Step drawstyles must preserve monotonic-x topology eligibility so LOD selection stays valid | LP-FUNC-034 | LOD topology owner; verify M4 hierarchy treats step vertices as exact polyline points (`LP-LOD-002`/`003` unaffected) |
| C-4 | Polar introduces the first non-Cartesian transform; request-schema clip/background fields assume rectangles | LP-FUNC-036 | transform/coordinate policy (O-11 adjacent) + request schema owner |
| C-5 | Segment-linear scales (symlog) interact with topology detection (data-space) vs selection (transformed-space) | LP-FUNC-039 | LOD topology + coordinate decision; gated before any adoption |
| C-6 | Cross-primitive alpha/order depends on opaque-background compositing being correct end-to-end | LP-FUNC-035 | prerequisite: background-loss correction lane merged with its decoded-pixel regression assertion |
| C-7 | Date/unit label formatting consumes Figure-authoritative locator/converter info; must not duplicate layout measurement | LP-FUNC-037 | shared text/layout contract (`LP-TEXT-001`/`002`; no per-renderer re-measurement) |

## 9. Integration decision points (for the adopting review)

1. Promote LP-FUNC-032/033/034 into `lumenplot-v1.0.md` §3.1 at the next requirements
   revision, or hold as an amendments appendix until W1 evidence exists (release-honesty
   rule `LP-REL-014` favors late promotion).
2. Register proposed gates (`AT-FUNC-FILL`, `AT-FUNC-BAR`, `AT-FUNC-DRAWSTYLE`,
   `AT-SEM-COMPOSITING`, `AT-FUNC-POLAR`, `AT-FUNC-DATE-AXIS`, `AT-FUNC-QUIVER`,
   `AT-SEM-SCALE-EXT`, `AT-MPL-ELIGIBILITY`) in the traceability gate-vocabulary table, or
   remap onto existing families.
3. Confirm the LP-FUNC-035 / LP-RENDER-004 scope split (ordering-across-classes vs
   alpha-within-supported-layers).
4. Decide whether LP-MPL-020 is absorbed into an O-10 amendment or stands alone.
5. Confirm W3 rows join the existing Phase-5 expansion train (`LP-FUNC-017`–`020`) as one
   release vehicle.
6. On adoption, update the registry counts (currently: 223 entries / 150 normative) and add
   coverage-matrix rows in Appendix A; this draft intentionally performs no such edit.

## Appendix — Verification trail

- Registry parsed programmatically from `docs/requirements/lumenplot-v1.0.md`: 223 rows;
  families and maxima: PROD 18, FUNC 31, UX 33, REL 14, DATA 10, LOD 7, RENDER 10, QUAL 28,
  PLAT 12, SEC 8, TEXT 7, MPL 19, EXPORT 10, PERF 16; levels: MUST 113, MUST NOT 37,
  SHOULD 40, MAY 8, REFERENCE 13, PHASE 6, NON-GOAL 6; 92 distinct evidence gates — matching
  the published traceability coverage summary exactly.
- Proposed gate names checked for collisions against all 92 registered gates: none.
- Candidate ID slots verified unused: `LP-FUNC-032`…`039` and `LP-MPL-020` (the MPL family already extends to 019, so the next free slot is 020).
- Behavior statements about the merged Phase-3B slice (eligible trace, strict rejections,
  hybrid whole-frame fallback, PNG-only surface) reflect `python/lumenplot_mpl/backend.py`
  and the Phase-3B contract-test suite as merged at the time of drafting.
