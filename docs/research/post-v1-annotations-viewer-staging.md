# Post-v1 research: staging the annotations and viewer interaction lanes

## Status

**DESIGN RESEARCH ONLY — NOT AN ACCEPTED DECISION, SEQUENCING COMMITMENT,
OR SUPPORT CLAIM.**
This note stages the two largest unstarted v1 interaction lanes — annotations
(LP-FUNC-012) and the standalone viewer (LP-FUNC-016) — plus the coupled
interaction rows (view history, Legend, cursor, grid) against infrastructure
that already has merged local contract evidence. Nothing here becomes
operative by itself: every cited requirement row remains `Not implemented` in
the [traceability registry](../requirements/traceability-v1.0.md), no ADR or
API record is amended, and no sequencing below binds a future planning card.
Where this note says "proposal", "option", or "stage", read exactly that.

The accepted semantic contracts for both lanes already exist and are treated
here as fixed inputs, not as proposals:

- annotations and accessibility: [API 0004](../architecture/api-0004-annotations-accessibility.md)
  (records [O-13](../architecture/open-decisions.md#o-13-annotation-and-interaction-history-details)
  and [O-14](../architecture/open-decisions.md#o-14-accessibility-and-standalone-viewer-semantics));
- runtime, viewer, and host-loop lifecycle: [ADR 0005](../adr/0005-runtime-viewer-host-loop.md)
  (record [O-06](../architecture/open-decisions.md#o-06-window-viewer-host-loop-and-lifecycle-semantics));
- GPU runtime baseline: [ADR 0008](../adr/0008-portable-gpu-and-shaders.md) /
  [O-15](../architecture/open-decisions.md#o-15-gpu-runtime-and-shader-artifact-details);
- the Phase-1 rule that view history and gestures live *outside* the scene
  core: [API 0001](../architecture/api-0001-native-scene-state.md).

What remains for these lanes is staged engineering, not new decisions. New
decisions that *are* needed are collected in the final section as recorded
questions for the `architecture-authority`.

Evidence basis: all repository citations below were verified verbatim on
origin/main @ `858acc1` on 2026-08-24.

Terminology: "lane" means a group of open requirement rows addressable by one
implementation thrust. The requirements vocabulary ends at Phase 5; nothing
here introduces a new phase number. Despite the file name, the subject rows
are **open v1 rows**; "staging" refers to preparing their implementation
sequencing, and no row's status is changed by this note.

## 1. Open-row inventory (verified verbatim)

### 1.1 Primary functional rows

From the [requirement registry](../requirements/lumenplot-v1.0.md), with
registry columns (level / target / phase / gates / result) quoted from
[traceability-v1.0.md](../requirements/traceability-v1.0.md):

| Row | Level | Requirement subject | Target | Phase | Gates | Result |
| --- | --- | --- | --- | --- | --- | --- |
| `LP-FUNC-008` | MUST | view history previous/next + canonical restoration | deterministic history transitions | 2 | `AT-FUNC-HISTORY` | Not implemented |
| `LP-FUNC-009` | MUST | interactive publication-style Legend | Legend hit-testing and state changes | 2 | `AT-FUNC-LEGEND` | Not implemented |
| `LP-FUNC-010` | MUST | basic cursor and coordinate inspection (series, x, y) | basic scientific inspection | 2 | `AT-FUNC-CURSOR` | Not implemented |
| `LP-FUNC-011` | MUST | grid toggle | Plot State and export consistency | 2 | `AT-FUNC-GRID` | Not implemented |
| `LP-FUNC-012` | MUST | basic annotations as Plot State (geometry, style, hit-testing, export) | annotation acceptance fixture | 2 | `AT-FUNC-ANNOTATION`, `AT-EXPORT-ANNOTATION` | Not implemented |
| `LP-FUNC-016` | MUST | standalone viewer for native scenes | launch, interaction, close, and package tests | 1-2 | `AT-FUNC-VIEWER`, `AT-LIFE-VIEWER` | Not implemented |
| `LP-UX-012` | MUST | restore stored canonical view for Home/Reset | canonical-view fixture | 1-2 | `AT-FUNC-HISTORY` | Not implemented |

Registry sources: rows `LP-FUNC-008`–`LP-FUNC-012` at
`docs/requirements/traceability-v1.0.md:78–82`, `LP-FUNC-016` at line 86,
`LP-UX-012` at line 205; requirement wording at
`docs/requirements/lumenplot-v1.0.md:70–78` and `:276`.

### 1.2 Coupled MUST-NOT rows that constrain both lanes

These rows are negative constraints; each fails if the viewer or annotation
surface is built the wrong way, regardless of whether its positive row passes.

| Row | Constraint | Phase | Gate |
| --- | --- | --- | --- |
| `LP-FUNC-030` | publication Legend is not the primary large-series management panel | 2 | `AT-REVIEW-UX` |
| `LP-UX-001` | no fitting controls in the navigation UI | 0 | `AT-REVIEW-UX` |
| `LP-UX-003` | no large permanent toolbar as primary interaction surface | 1-2 | `AT-REVIEW-UX` |
| `LP-UX-004` | no permanently visible sidebar prerequisite for navigation | 1-2 | `AT-REVIEW-UX` |
| `LP-UX-005` | no modal-heavy workflows for ordinary navigation | 1-2 | `AT-REVIEW-UX` |
| `LP-UX-006` | no mode selection required before ordinary pan/zoom | 1 | `AT-FUNC-INPUT` |
| `LP-UX-008` | no permanent Pan button for ordinary drag navigation | 1 | `AT-REVIEW-UX` |
| `LP-UX-009` | no permanent Zoom button for wheel/trackpad navigation | 1 | `AT-REVIEW-UX` |
| `LP-UX-010` | Fit is not a permanent substitute for canonical Home | 2 | `AT-REVIEW-UX` |
| `LP-UX-011` | no permanent Box Zoom mode button for Shift-drag | 1 | `AT-REVIEW-UX` |
| `LP-UX-013` | interactive pan/zoom never changes the stored canonical range | 1-2 | `AT-SEM-STATE-REVISION` |
| `LP-UX-018` | no checkbox/eye/pin icons substituting for Legend hit-testing | 2 | `AT-REVIEW-UX` |
| `LP-QUAL-016` | hover/selection/context/chrome/cursor excluded from ordinary exports | 2 | `AT-EXPORT-STATE` |
| `LP-QUAL-019` | no non-reentrant lock held across a Python callback | 1-2 | `AT-LIFE-FFI` |
| `LP-EXPORT-008` | cursor not exported as ordinary Plot State | 2 | `AT-EXPORT-STATE` |
| `LP-EXPORT-010` | cursor/crosshair state excluded from exports | 2 | `AT-EXPORT-STATE` |

Registry sources: `traceability-v1.0.md` lines 100 (`LP-FUNC-030`),
106 (`LP-UX-001`), 196–206 (`LP-UX-003`–`LP-UX-013`), 211 (`LP-UX-018`),
218 (`LP-QUAL-016`), 221 (`LP-QUAL-019`), 230/234 (`LP-EXPORT-008/010`).

Adjacent positive rows these lanes must carry with them (not re-tabulated):
event routing `LP-UX-014`/axis-only `LP-UX-015` (`AT-FUNC-INPUT`, phase 1-2 /
1); Legend scene membership through drag persistence `LP-UX-016`–`LP-UX-022`
(`AT-SEM-LEGEND` family, phase 2); Plot/UI State separation `LP-QUAL-014`,
export-snapshot inclusion `LP-QUAL-015`; keyboard/accessibility
`LP-UX-028`+ (`AT-FUNC-KEYBOARD-A11Y`); standalone-without-Matplotlib
`LP-MPL-018`; Legend-toggle latency `LP-PERF-008`
(`AT-BENCH-LEGEND-1FRAME`).

## 2. Landed infrastructure these lanes stand on

Everything below was read in this worktree; descriptions are of merged,
evidence-backed behavior, not of this note's intentions.

**Scene kernel with a stored canonical view.**
`lumenplot-engine` keeps `canonical_view` as a distinct field beside the
mutable `viewport` (`crates/lumenplot-engine/src/scene/state.rs`; see
`SceneState::new` and the accessors `canonical_view()`/`viewport()`), and the
bridge exposes `replace_canonical_view` and `set_viewport` as separate
transaction operations (`crates/lumenplot-engine/src/bridge.rs:614–623`).
The six private component revisions of API 0001 already include
`annotation_revision` (`scene/state.rs:114`, initialized at `:163`, carried
through `publish` at `:202`) even though Phase-1 operations touch only data
and view. Consequence: the Home-vs-viewport distinction that
`LP-UX-012`/`LP-UX-013` fixtures need is already representable; what is
missing is everything transient around it (history stack, gesture
coalescing), which API 0001 explicitly assigns to runtime/UI state outside
`PlotScene` and `SceneSnapshot`.

**Single-writer transaction and immutable snapshot.**
`PlotScene::transaction() -> SceneTransaction` with `commit() ->
CommitReceipt{revision, changed}` and `abort()`, plus `snapshot()` sharing
immutable state, are the only mutation path at the facade
(`bridge.rs:592–607`). Annotation add/edit/delete must ride exactly this path
per API 0004 ("Annotation add, edit, and delete are Plot State
transactions"), so the annotation lane inherits the receipt/atomicity
fixtures' shape for free.

**Deterministic raster oracle.**
The private line-frame → PNG path
(`lumenplot-export`: `RasterPlan`, compositor, `encode_line_frame_png` at
`png.rs:26`) produces golden-byte-comparable output from a fully resolved
frame (`SceneSnapshot::resolve_line_frame`, `bridge.rs:684`). The
`AT-EXPORT-ANNOTATION` and `AT-EXPORT-STATE` fixtures can extend this oracle
pattern instead of inventing a new one.

**Hidden-seam adapter pattern.**
Phase-3B proved the delivery mechanism for interpreter-free native calls:
owned IR copied once across the boundary, all Python references dropped
before rendering, panics contained (`crates/lumenplot-python/src/lib.rs`
header), with strict/hybrid policy and structured diagnostics in the public
backend (`python/lumenplot_mpl/backend.py`). Any viewer-adjacent Python
surface would reuse this pattern; the viewer itself needs none of it.

**Benchmark protocol shell.**
`lumenplot-bench` implements the O-08 shape (5 fresh-process blocks of ≥1000
measured frames, nearest-rank percentiles, seeded A/B order randomization;
`src/runner.rs:40–66`) with all four profile names driving the single
implemented PNG path today. `LP-PERF-008` (Legend toggle within one displayed
frame) is an event-to-display measurement that cannot even start until the
runtime/present path exists; noting the dependency here so nobody schedules
the bench row ahead of the runtime.

**Stub DAG positions already correct.**
`lumenplot-viewer` depends on `lumenplot` + `lumenplot-runtime`;
`lumenplot-runtime` depends on `lumenplot-render-wgpu`; both runtime and
viewer (and `render-api`/`render-wgpu`) are documentation-only stubs whose
headers defer to later phases. The layering the overview fixes — frontend
edges → facade → core → … → renderer/runtime — is already expressed in
`Cargo.toml` edges and enforced by `scripts/check_phase2b_dependencies.py`.
Neither lane needs a workspace-DAG change to begin.

## 3. Gap map and proposed staging

### 3.1 Annotations lane (LP-FUNC-012; API 0004 is the contract)

Gaps between API 0004's accepted semantics and the current tree:

- **Identity service.** `AnnotationId` must be a stable process-local `u64`,
  scoped to one Scene lifetime, never reused within it, generation-excluded,
  never serialized. The engine already solves the identical problem for
  `SeriesId` (allocate-before-stage, burn on abort/failed commit — API 0001);
  the annotation identity service is the same discipline under a second name.
- **Annotation state as transactions.** Storage for the four v1 kinds
  (text, line, arrow, rectangle; ellipse stays an optional capability) with
  per-annotation geometry space (`Data2D`, `AxesLogical`, `FigureLogical`,
  `DisplayLogical`), explicit transform, clip, z-order, and style. Add/edit/
  delete go through `SceneTransaction`, increment `SceneRevision` exactly
  once per effective change and bump `annotation_revision` (the slot exists).
- **Hit-testing oracle.** Logical-space hit tests applied after the explicit
  transform and clipping rules. This needs a data→display mapping shared with
  layout; today such a mapping exists only inside private line-frame
  resolution. Proposal: treat "resolved semantic frame" (the Phase-2 shared
  layout layer, `LP-PROD-003`/`LP-TEXT-001` territory) as the natural home
  rather than growing ad-hoc math into the scene kernel — see open question 1.
- **Export inclusion and exclusion.** Ordinary export snapshots include
  annotations (`LP-QUAL-015`) while hover/selection/focus/drag chrome stays
  UI State and is excluded (`LP-QUAL-016`). The negative half is free if —
  and only if — chrome never enters Plot State in the first place; the
  staging below enforces that ordering.
- **Explicitly out of lane scope** (already decided, restated to prevent
  drift): no persistence or save/load format; no view-history membership for
  annotation edits; no serialization schema.

Proposed stages, each independently testable:

| Stage | Content | Headless-testable today? |
| --- | --- | --- |
| A1 | engine annotation store + transaction ops + identity burn rules; revision fixtures (`AT-FUNC-ANNOTATION` core) | yes — pure kernel, mirrors Phase-1A fixtures |
| A2 | geometry-space transforms, clip, z-order; logical hit-test oracles (`AT-FUNC-ANNOTATION` hit-testing) | yes — property/oracle tests |
| A3 | export inclusion + UI-chrome exclusion over the PNG seam (`AT-EXPORT-ANNOTATION`, `AT-EXPORT-STATE` negatives) | yes — extends the golden oracle |
| A4 | interactive editing chrome (handles, drag) as UI State behind the runtime boundary | no — blocked on V1 |

### 3.2 Viewer lane (LP-FUNC-016; history rows LP-FUNC-008, LP-UX-012/013; ADR 0005 is the contract)

Gaps:

- **Runtime skeleton.** `EngineSession` main-thread confinement owning one
  adapter/device/queue and `0..N` surfaces; the portable wgpu edge per O-15's
  implementation baseline (wgpu 29.0.4, winit 0.30.13, raw-window-handle
  0.6.2 — implementation baselines and support claims are different things,
  as ADR 0008 states). Standalone viewing is the native-owned blocking loop;
  close idempotent and observable; `Drop` best-effort only.
- **Transient view-history stack outside the scene.** API 0001 fixes the
  location (runtime/UI state, not `PlotScene`/`SceneSnapshot`) and the v1
  scope (viewport gestures, Home, canonical-view replacement, gesture-end
  coalescing, forward-tail truncation; annotation edits excluded). Previous/
  next walk this stack; Home restores the stored canonical view
  (`LP-UX-012`); interactive pan/zoom writes only the viewport and never the
  canonical range (`LP-UX-013` negative fixture).
- **Input routing as a semantic-action map.** `LP-UX-014`'s full matrix
  (left-drag pan, wheel pointer-centered zoom, Shift-drag box zoom, click
  select, background clear, double-click Home, right-click transient context)
  plus axis-restricted variants (`LP-UX-015`) can be expressed as pure
  functions `event → semantic action` and tested headless before any window
  exists. This is the highest-leverage early artifact in the whole lane: the
  same action map feeds keyboard equivalents (`LP-UX-028`), the accessibility
  contract's "same semantic action" rule, and the reduced-motion rule
  (presentation timing changes, semantics do not).
- **Lifecycle evidence.** The ADR 0005 verification matrix (launch,
  create/destroy, close/drop, resize, occlusion, surface/device loss, OOM,
  reentrancy, multi-surface, mixed-device rejection) remains environment
  evidence; staging cannot close it, only make the code paths testable.

Proposed stages:

| Stage | Content | Depends on |
| --- | --- | --- |
| V1 | runtime skeleton: session/surface lifecycle on the portable wgpu edge; observable close | nothing in this note |
| V2 | semantic input-action map (pure, headless) covering mouse matrix + keyboard equivalents + focus model | nothing (can start immediately, parallel to V1) |
| V3 | transient history stack + Home/canonical + truncation fixtures (`AT-FUNC-HISTORY`) | V2 semantics; V1 only for end-to-end runs |
| V4 | present path through the renderer; Legend/cursor/grid consumption; package tests (`AT-FUNC-VIEWER` tail, `AT-LIFE-VIEWER` prep) | V1+V3 |

### 3.3 Coupled interaction lanes (Legend LP-FUNC-009, cursor LP-FUNC-010/`LP-UX-023`, grid LP-FUNC-011)

All three are consumers of the V2 action map and the A1–A3 export-state
discipline, which is why they belong in the same staging note:

- **Legend** (`LP-FUNC-009`, `LP-UX-016`–`022`): a formal Plot Scene element
  with shared semantic layout; entry click toggles series visibility while
  entry geometry stays stable (`style_revision` bump, not relayout); double-
  click solo/restore needs a prior-visibility snapshot held as UI state;
  background/padding drag persists as Plot State (`LP-UX-022`); right-click
  menus stay transient (`LP-UX-021`); no checkbox/eye/pin substitutes
  (`LP-UX-018`). Hit-testing reuses the A2 oracle machinery.
- **Cursor** (`LP-FUNC-010`, `LP-UX-023`): nearest-series readout showing
  series/x/y, transient by definition — three separate rows
  (`LP-QUAL-016`, `LP-EXPORT-008`, `LP-EXPORT-010`) exist purely to keep it
  out of exports, so its state must live entirely in the UI-state side of the
  V3/V4 split.
- **Grid** (`LP-FUNC-011`): the smallest row, and the cleanest end-to-end
  probe: toggle is a Plot State mutation included in export snapshots
  (`LP-QUAL-015`), so `AT-FUNC-GRID` doubles as the Plot-State-vs-export
  equivalence check for the whole state model.

Proposed placement: implement each behind V2 (semantic actions) and before
V4 packaging; grid can lead as the trivial vertical slice through the entire
state→export pipeline.

### 3.4 Cross-cutting constraints the stages must inherit

- **Viewer shell shape** is dictated by the MUST-NOT cluster: plot-first
  canvas, minimal persistent controls, progressive disclosure (`LP-UX-002`
  SHOULD, `LP-UX-007` SHOULD), direct-manipulation defaults with no mode
  prerequisites. A shell review checklist mapped row-by-row onto §1.2 is the
  cheap form of `AT-REVIEW-UX` evidence when the time comes.
- **Keyboard/focus/contrast/reduced motion** (API 0004): designing them into
  the V2 action map costs far less than retrofitting; contrast baselines are
  the unrounded 4.5:1 / 3:1 / 3:1 acceptance values.
- **Adapter interplay**: `LP-QUAL-019` (no non-reentrant lock across a Python
  callback) constrains any future point where the adapter and a hosted
  runtime meet; the Phase-3A GIL-dropping pattern is the precedent.
- **Honest boundary**: no stage above closes a row. Registry results move
  only when reproducible fixtures/manifests replace them, and the platform/
  benchmark cells stay `environment required` until run on declared hardware.

## 4. Proposed cross-lane ordering (a proposal, not a plan of record)

```text
now    A1–A3 (annotations, engine-only)   V2 (input-action map, headless)
then   V1 (runtime skeleton)              V3 (history stack)
then   grid slice → Legend → cursor (behind V2 semantics)
last   V4 present path + chrome (A4)      viewer package tests
       bench rows (LP-PERF-008 et al.) strictly after V4
```

Rationale: A1–A3 and V2 need no window system, no new dependencies, and no
DAG changes, so they are the only stages that produce reviewable evidence on
every developer machine; V1 is the long pole and should start as early as the
manager schedules it; everything user-visible composes from pieces that were
already tested headless.

## 5. Zero-impact proof obligations

A research note must demonstrably not move v1. Each obligation was checked in
this worktree:

<!-- markdownlint-disable MD013 -->

| # | Obligation | Concrete mechanism |
| --- | --- | --- |
| i | Docs-only diff | This lane adds one docs file and nothing else; `git diff --name-only origin/main` must show only `docs/research/post-v1-annotations-viewer-staging.md` |
| ii | Static checker pins nothing under `docs/research/` ⇒ gate unaffected | Verification runs `scripts/check_workspace_architecture.py --root .` (exit 0, "workspace architecture: OK") and `scripts/check_phase2b_dependencies.py` (exit 0) in this worktree |
| iii | CI workflows untouched | No `.github/workflows/` change; the wheel-evidence classifier sees no new auditwheel/manylinux/maturin/wheel vocabulary |
| iv | Traceability rows untouched | Every row in §1 keeps its registry `Not implemented` result; neither requirements nor traceability files are modified here |
| v | No Rust/Python schema change | No crate, module, or `python/` file is added or edited; the stub headers of `lumenplot-viewer`/`lumenplot-runtime` remain accurate |

<!-- markdownlint-enable MD013 -->

## 6. Recorded questions for the architecture-authority

Questions, **not decisions**; each needs an explicit future decision before
the dependent stage could begin:

1. **Semantic-frame home.** Should the resolved frame consumed by hit-testing
   and shared layout live as engine-private modules or a new private layer?
   The crate DAG is frozen by ADR 0003 and changes require architecture
   review; A2 can proceed against engine-private resolution either way, but
   A4/V4 composition wants an answer.
2. **Action-map visibility.** Is the V2 semantic-action map ever a public
   facade type (O-02 implications), or permanently private runtime detail?
   Keyboard-equivalent evidence (`LP-UX-028`) is satisfiable either way.
3. **History-stack parameters.** Gesture-end coalescing windows and stack
   bounds are protocol numbers; `AT-FUNC-HISTORY` fixtures cannot pin them
   without a decision record.
4. **Hit-testing precision.** f64 scene space exclusively, or permitted
   local-f32 screen-space acceleration validated against an f64 oracle,
   mirroring the `LP-DATA-009` local-f32 lane?
5. **Sequencing authorization.** Does the manager authorize A1–A3 and V2
   (headless, dependency-free) ahead of V1, per §4?

## Related records

- [API 0004 — annotations and accessibility](../architecture/api-0004-annotations-accessibility.md)
- [ADR 0005 — runtime, viewer, and host loop](../adr/0005-runtime-viewer-host-loop.md)
- [ADR 0008 — portable GPU and shaders](../adr/0008-portable-gpu-and-shaders.md)
- [API 0001 — native Scene state](../architecture/api-0001-native-scene-state.md)
- [Requirements](../requirements/lumenplot-v1.0.md) ·
  [Traceability registry](../requirements/traceability-v1.0.md)
- Sibling research notes: [3D slice](post-v1-3d-slice-notes.md),
  [Metal fastpath](post-v1-metal-fastpath-design-notes.md),
  [native OS cell declaration](post-v1-native-os-cell-declaration-proposal.md)
