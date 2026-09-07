# LP-MPL-020 strict eligibility-extension checklist (per-class contract gate)

- Status: **governance checklist** — `SHOULD`, continuous, v1 governance.
  This file operationalizes the gate; it does not restate or amend the
  canonical requirement. Normative text lives only in
  [§15](lumenplot-v1.0.md#15-python-and-matplotlib-bridge) and
  [§15.1](lumenplot-v1.0.md#151-matplotlib-agg-oracle-and-equivalence-contract)
  of [`lumenplot-v1.0.md`](lumenplot-v1.0.md).
- Requirement: [`LP-MPL-020`](#11-the-gate-rule) (`AT-MPL-ELIGIBILITY`).
  Current registry result: `Not implemented`
  (see [`traceability-v1.0.md`](traceability-v1.0.md)).
  Any result-cell change proposed below is marked **PROPOSED** and is not
  applied by this file — the canonical registry and its machine-checked
  counts are untouched.
- Scope: the five currently strict-eligible classes
  (C1–C5 below). New classes are out of scope until their own
  six-mechanic bundle lands.
- Global prohibitions (non-negotiable): never enable silent approximation;
  never enable default-on tolerance. A class that cannot meet the gate
  stays outside strict eligibility and uses explicit whole-frame Agg
  fallback in hybrid mode.

## 1. The gate

### 1.1 The gate rule

`LP-MPL-020` (`SHOULD`): extend `strict-common-2d` eligibility only through
an explicit per-class contract containing the whitelist entry, public
collector trace, resolved style contract, strict/hybrid behavior, and
Agg-oracle fixtures. The §15.1 final clause adds the sixth mechanic and
the regression rule:

> Every new strict-eligible artist class must land its whitelist, collector
> trace, style contract, negative cases, Agg fixtures, and rollback/removal
> rule together. If any parity fixture regresses, remove that class from
> strict eligibility and retain explicit whole-frame Agg fallback rather
> than shipping a lower-fidelity approximation.

### 1.2 Mechanics and row IDs

Each per-class row below is checked against the same six mechanics:

| ID | Mechanic | What must exist together |
| --- | --- | --- |
| M1 | Whitelist entry | Documented-public artist class in the static whitelist (`backend_preflight.py`) plus the accepted-record amendment (ADR 0015 §4/§4a/§4b or later) |
| M2 | Collector trace | Exact eligible collector-trace expectation asserted by a trace test (balanced-group grammar; no silent base-class no-op) |
| M3 | Style contract | Resolved style contract test (cap/join/solid/width/alpha/clip; Agg-resolved values, not approximations) |
| M4 | Strict/hybrid behavior | Strict mode fails before writing (`LumenPlotUnsupportedError`, no PNG); hybrid mode renders once through whole-frame Agg with exactly one diagnostic |
| M5 | Negative cases | Explicit refusal fixtures for every out-of-contract input of the class (the class's own negative surface, not just the generic error suite) |
| M6 | Agg fixtures | Pinned-oracle fixtures (Matplotlib 3.11.1 / backend API 1.1) meeting the four-part §15.1 parity contract, plus the rollback/removal rule |
| R1 | Regression rule | If any parity fixture of the class regresses: remove the class from strict eligibility, keep whole-frame Agg fallback, never ship a lower-fidelity approximation |

### 1.3 How to machine-check a row

- Every evidence cell names the exact file and test class. Run from the
  repository root with the standing runner (CI
  [ci.yml](../../.github/workflows/ci.yml) uses
  `python3 -m unittest discover -s tests/python`):
  `python3 -m unittest discover -s tests/python -p '<file>.py' -v`,
  or a single class from `tests/python`:
  `python3 -m unittest <module>.<Class> -v`.
- Verdict vocabulary: **LANDED** (merged to `origin/main`, PR cited),
  **OPEN** (work exists but unmerged — PR or branch cited, never counted
  as evidence), **PROPOSED** (governance proposal in §5, not applied).
- Row IDs C1–C5 / M1–M6 / R1 are stable grep anchors for future automation.
  A dedicated checker script (e.g. extending
  `scripts/check_requirements_traceability.py`) is follow-up work, not part
  of this docs-only change.

## 2. Per-class gates

### C1 — Line2D, including gap / non-finite semantics

| Mechanic | Evidence | Status |
| --- | --- | --- |
| M1 whitelist | `matplotlib.lines.Line2D` in the static whitelist (`python/lumenplot_mpl/backend_preflight.py`); base eligible trace in [ADR 0015 §4](../adr/0015-phase3b-public-matplotlib-adapter-contract.md) | LANDED |
| M2 collector trace | Exact `figure → patch → axes → line2d` grammar; `TestStepProfileModes`-adjacent profile tests plus the eligible-trace assertions in the Phase-3B backend suites (`tests/python/test_phase3b_backend.py`) | LANDED |
| M3 style contract | Butt cap / miter join / solid / finite width surface in `_check_line2d_static`; style fixtures in the Phase-3B suites | LANDED |
| M4 strict/hybrid | `TestStrictErrorFixtures`, `TestTerminalAdapterErrors` (`tests/python/test_phase3b_error_and_mixed_output.py`); preflight soundness `TestStrictPreflightSoundness` / `TestHybridPreflightSoundness` (`tests/python/test_mpl_preflight_soundness.py`, PR #103) | LANDED |
| M5 negative cases | Markers, dashes, non-default drawstyles (outside C4), path effects, sketch, snap, custom clip, hyperlinks refused in `_check_line2d_static` | LANDED |
| M6 Agg fixtures | `TestCommittedLine2DGapFixture` + `TestLine2DGapNativeAggParity` (`tests/python/test_agg_oracle_line2d.py`); axis-aware gap cases `TestCommittedGapAxesFixture` + `TestGapAdapterSemantics` (`tests/python/test_agg_oracle_gap.py`, PR #105); engine support via the 24.8 cell-coverage F1 rasterizer (PR #106) | LANDED (fixtures) |
| R1 rollback | §4 procedure, instantiated for Line2D | LANDED (rule) |

Gap-rule note: NaN, ±infinity, and masked samples terminate the current
finite run; the next finite sample begins a new subpath (`MOVETO`); no
segment is drawn across a non-finite sample (§15.1, `Path.iter_segments`
semantics). `LP-FUNC-040` (`AT-FUNC-NAN-GAP`) remains `Not implemented` in
the registry — PR #105 landed fixtures, not gate closure. Proposed flip
condition in §5.

Check:

```text
python3 -m unittest discover -s tests/python -p 'test_agg_oracle_line2d.py' -v
python3 -m unittest discover -s tests/python -p 'test_agg_oracle_gap.py' -v
python3 -m unittest discover -s tests/python -p 'test_mpl_preflight_soundness.py' -v
```

### C2 — Fill, including span and stack (axis-aligned only)

| Mechanic | Evidence | Status |
| --- | --- | --- |
| M1 whitelist | `matplotlib.patches.Polygon` (`Axes.fill`) and `matplotlib.collections.FillBetweenPolyCollection` (`Axes.fill_between`) in the static whitelist; `LP-FUNC-032` (W1, PR #68) | LANDED |
| M2 collector trace | `TestFillCollectorTrace` (`tests/python/test_phase3b_fill.py`); span rectangles resolve unit-square corners through the public transform; `stack[-1] == "FillBetweenPolyCollection"` branch in the trace reconciler | LANDED |
| M3 style contract | `TestFillStyleContract`; empty-edgecolor collections resolve to stroke `None`; Agg-compat blend mode for fills | LANDED |
| M4 strict/hybrid | `TestFillWhitelist` strict/hybrid mode behavior; whole-frame Agg fallback path for refused fills | LANDED |
| M5 negative cases | Non-polygonal fills refused (`MOVETO`/`LINETO`/`CLOSEPOLY`-only in `_check_fill_call`); rotated-rectangle bars refused (C3); slanted-fill refusal — see note | PROPOSED (slanted part) |
| M6 Agg fixtures | `TestCommittedFillFixture` + `TestFillNativeAggParity` (`tests/python/test_agg_oracle_fill.py`, PR #101) covering fill, fill-between, vspan, hspan, two-layer stackplot; PR101-CI-FIX re-scoped the pixel-parity input to the axis-aligned exact surface (slanted edges fail the fixed gate with a fringe-only signature and were removed from the input, not tolerated) | LANDED (axis-aligned) |
| R1 rollback | §4 procedure, instantiated for fills | LANDED (rule) |

Slanted-fill note (FILL-AA decision (b), 2026-09-04): slanted fills exit
strict eligibility — strict refuses before writing, hybrid uses whole-frame
Agg fallback — while axis-aligned fills stay strict-eligible under the
unchanged fixed gate. The decision is recorded; the enforcing code is
**not** on `origin/main` and is therefore PROPOSED, not evidence. Landing
it is the precondition for any `LP-MPL-020` flip that names fills.

Check:

```text
python3 -m unittest discover -s tests/python -p 'test_phase3b_fill.py' -v
python3 -m unittest discover -s tests/python -p 'test_agg_oracle_fill.py' -v
```

### C3 — Bar / rectangle (axis-aligned, baseline-anchored)

| Mechanic | Evidence | Status |
| --- | --- | --- |
| M1 whitelist | `matplotlib.patches.Rectangle` (`Axes.bar` / `Axes.barh`) in the static whitelist; `LP-FUNC-033` (W1, PR #69); rotated rectangles (`angle != 0`) refused — a tilted bar is never rendered as its bounding box | LANDED |
| M2 collector trace | `TestBarCollectorTrace` (`tests/python/test_phase3b_bar.py`); zero-area rectangles with an explicit edge emit a stroke-only command | LANDED |
| M3 style contract | `TestBarStyleContract`; per-bar style resolution; negative and stacked baselines | LANDED |
| M4 strict/hybrid | `TestBarModeBehavior`; `TestBarWhitelist` | LANDED |
| M5 negative cases | Rotated rectangles, non-finite geometry, and out-of-contract bar styles refused in `_check_rectangle_static` | LANDED |
| M6 Agg fixtures | `TestBarPixelParity` (`tests/python/test_phase3b_bar.py`); pinned bar/histogram oracle `test_agg_oracle_bar.py` on branch `agg/bar-oracle` (PR #102) with rect-stroke AA convergence (PR #107) | OPEN (oracle PR unmerged) |
| R1 rollback | §4 procedure, instantiated for bars | LANDED (rule) |

PR #102 is OPEN: its evidence must not be cited as landed. The C3 Agg-fixture
cell flips to LANDED only after PR #102 merges green.

Check:

```text
python3 -m unittest discover -s tests/python -p 'test_phase3b_bar.py' -v
```

### C4 — Steps drawstyles (steps-pre / steps-post / steps-mid)

| Mechanic | Evidence | Status |
| --- | --- | --- |
| M1 whitelist | Not a new artist class: `Line2D` with `drawstyle` in `_STEP_DRASTYLES`; `LP-FUNC-034` (W1, PR #70). Every other non-default drawstyle (and any future value) is still refused explicitly | LANDED |
| M2 collector trace | Step lines use the `line2d` trace branch; `TestStepProfileModes` (`tests/python/test_phase3b_steps.py`) | LANDED |
| M3 style contract | `TestStepStyleContract`; exact vertex-generation semantics; monotonic-topology eligibility preserved for LOD (`TestStepTopologyRecurrence`) | LANDED |
| M4 strict/hybrid | `TestStepProfileModes`; non-finite fallback `TestStepNonFiniteFallback` (steps never bridge gaps) | LANDED |
| M5 negative cases | Non-step non-default drawstyles refused in `_check_line2d_static`; non-finite step inputs take the explicit fallback path | LANDED |
| M6 Agg fixtures | `TestStepGeometryParity` (exact generated vertices for step paths, per §15.1) + `TestStepPixelParity` | LANDED |
| R1 rollback | §4 procedure, instantiated for steps | LANDED (rule) |

Check:

```text
python3 -m unittest discover -s tests/python -p 'test_phase3b_steps.py' -v
```

### C5 — Legend static surface

| Mechanic | Evidence | Status |
| --- | --- | --- |
| M1 whitelist | Exactly `matplotlib.legend.Legend` (subclasses refuse), attached to one standard `Axes`; figure-level legends refuse; [ADR 0015 §4b](../adr/0015-phase3b-public-matplotlib-adapter-contract.md) (PRAC-A-L lane, 2026-08-26: whitelist entry, collector-trace expectation, style contract, and fixtures landed together) | LANDED |
| M2 collector trace | Legend frame/handle/label calls captured by the stage-two collector; `consume_legend` in the trace grammar; legend group checked against the static shape expectation | LANDED |
| M3 style contract | Handles re-check through the fixed line stroke surface (plain `Line2D`, butt/miter/solid, default drawstyle — the legend never relaxes its owner's contract); frame requires standard `FancyBboxPatch` + `BoxStyle.Round`, filled, butt/miter, AA required; labels re-check through the tick-label text contract plus positive font size | LANDED |
| M4 strict/hybrid | `TestLegendHybridMode`; strict refusals produce no PNG | LANDED |
| M5 negative cases | `TestLegendRefusals`: subclasses, figure-level attachment, titles, shadows, multi-column layouts, non-line handles, non-default handle drawstyles, empty entries, unfilled/hatched frames, path effects, custom clip, hyperlinks | LANDED |
| M6 Agg fixtures | `TestLegendCompositingOrder` + `TestLegendCompositingPixelParity` (`tests/python/test_phase3b_legend.py`); legend-frame/handle geometry finiteness checks | LANDED |
| R1 rollback | §4 procedure, instantiated for legends | LANDED (rule) |

Check:

```text
python3 -m unittest discover -s tests/python -p 'test_phase3b_legend.py' -v
```

## 3. Adjacent gates (out of scope, referenced for boundary clarity)

These rows interact with eligibility but are not per-class extensions; they
are listed so reviewers do not mistake their fixtures for M1–M6 evidence:

- `LP-MPL-021` (`AT-MPL-PREFLIGHT-SOUNDNESS`), `MUST`, registry `Not
  implemented`: strict refuses every unrepresentable Figure with no PNG
  (unsupported scale class, inverted limits, zero-projected-content
  geometry-stage refusal). PR #103 landed the fixtures
  (`TestStrictPreflightSoundness` / `TestHybridPreflightSoundness`); the
  gate itself stays open. PROPOSED flip condition in §5.
- `LP-MPL-022` (`AT-MPL-UNIT-DATA`), `MUST`, registry `Not implemented`:
  publicly converted unit/date data consumed for eligible geometry.
- `LP-FUNC-040` (`AT-FUNC-NAN-GAP`), `MUST`, registry `Not implemented`:
  see C1 note.
- Engine convergence PRs #106 (F1 Line2D-gap residual reduction via 24.8
  cell coverage) and #107 (rect-stroke AA convergence with rectilinear
  snap) are implementation support for the pixel gates, not eligibility
  extensions: they change no whitelist, trace, or contract.

## 4. Rollback / removal procedure (R1, all classes)

Trigger: any parity fixture of a strict-eligible class regresses (geometry,
decoded-pixel, text/style, or operational parity per §15.1), or the fixed
gate is found to have been widened after a failed result.

1. Remove the class from strict eligibility: delete its whitelist entry and
   its collector-trace branch in `backend_preflight.py` so strict mode
   refuses it explicitly before writing.
2. Retain explicit whole-frame Agg fallback in hybrid mode with exactly one
   diagnostic (no partial native render, no silent approximation).
3. Convert the regressed parity fixture into a negative-case fixture (strict
   refuses, hybrid falls back) until a new six-mechanic bundle re-lands the
   class.
4. Record the exit in the registry result cell; the class re-enters only via
   a fresh M1–M6 bundle. Capacity, I/O, internal, reentrancy,
   stale-publication, device-loss, and OOM failures never become visual
   fallback (§15.1 part 4).

Per-class instantiation is a one-line pointer: C1 → Line2D branch +
`line2d` trace arm; C2 → Polygon/FillBetweenPolyCollection entries +
`consume_fill` arm (axis-aligned scope); C3 → Rectangle entry +
rectangle arm; C4 → `_STEP_DRASTYLES` membership + step vertex generation;
C5 → Legend entry + `consume_legend` arm + payload builders.

## 5. PROPOSED registry dispositions (not applied)

The following flips are proposed for maintainer adjudication. None is
applied by this file; the canonical
[`traceability-v1.0.md`](traceability-v1.0.md) counts are unchanged.

| Row | Current | Proposed | Condition |
| --- | --- | --- | --- |
| `LP-MPL-020` (`AT-MPL-ELIGIBILITY`) | `Not implemented` | Remains `Not implemented` with this checklist recorded as the governance instrument | This file is the checklist the row's Target calls for, but the row also needs the slanted-fill refusal (C2 note) and PR #102 (C3) landed before any implemented claim |
| `LP-FUNC-040` (`AT-FUNC-NAN-GAP`) | `Not implemented` | `Not implemented` (no flip proposed yet) | PR #105 fixtures green; flip requires the full §15.1 four-part gate demonstrated for all gap cases, adjudicated separately |
| `LP-MPL-021` (`AT-MPL-PREFLIGHT-SOUNDNESS`) | `Not implemented` | `Not implemented` (no flip proposed yet) | PR #103 fixtures green; flip requires gate-closure review, adjudicated separately |
| C2 slanted fills | Inside no row's eligible surface by fixture scoping | Explicit strict refusal + hybrid whole-frame fallback (FILL-AA (b)) | Enforcing code lands on `main` |
| C3 Agg oracle | `test_phase3b_bar.py` parity only | Add pinned bar/histogram oracle parity | PR #102 merges green |

## 6. Evidence trail

| PR | Content | Status at writing |
| --- | --- | --- |
| #68 / #69 / #70, integrated by #71 | W1 static-geometry wave: fill (`LP-FUNC-032`), bar (`LP-FUNC-033`), step drawstyles (`LP-FUNC-034`) with §5.4 Agg-oracle parity fixtures | Merged |
| #101 | Pinned Agg oracle for fill primitives (`TestCommittedFillFixture`, `TestFillNativeAggParity`); CI fix re-scoped pixel input to the axis-aligned exact surface | Merged |
| #102 | Pinned Agg oracle for bar and histogram (`test_agg_oracle_bar.py`) | OPEN — not evidence |
| #103 | Strict preflight soundness fixtures (`TestStrictPreflightSoundness`, `TestHybridPreflightSoundness`) | Merged |
| #105 | Axis-aware gap fixtures (`TestCommittedGapAxesFixture`, `TestGapAdapterSemantics`); test-only, no source change | Merged |
| #106 | F1 Line2D-gap residual reduction (24.8 cell coverage in `crates/lumenplot-python/src/frame/agg_line.rs`) | Merged |
| #107 | Rect-stroke AA convergence (24.8 cell coverage with rectilinear snap) | Merged (HEAD base) |

## 7. Verification of this file

```text
python3 scripts/check_docs.py
python3 scripts/check_requirements_traceability.py
git diff --check
```

`check_requirements_traceability.py` must report unchanged counts (this file
adds no registry row and edits no canonical count); `check_docs.py` must
report no broken local links or anchors.
