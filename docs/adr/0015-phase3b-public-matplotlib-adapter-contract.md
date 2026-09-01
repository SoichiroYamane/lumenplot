# ADR 0015: Phase-3B public Matplotlib adapter contract

- Status: **Accepted contract — Phase-3B first strict-mode and hybrid-explicit implementation slices merged with local contract-test evidence; packaged public-backend runtime evidence pending**
- Date: 2026-08-23
- Decision owner: architecture-authority
- Recorded by: engineering-worker
- Scope: Phase-3B public Matplotlib backend slice boundary (strict single-Line2D PNG evidence target)
- Amends: [ADR 0013 — hidden facade and private Python line/PNG helper](0013-hidden-facade-private-python-line-png.md) §9 by recording its mandatory Phase-3B inputs as an explicit contract
- Governing architecture: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md)
- Boundary record: [ADR 0003 — facade and crate dependency graph](0003-facade-and-crate-dag.md)
- Private predecessor: [ADR 0012 — private line frame and deterministic PNG contract](0012-private-line-frame-and-png-contract.md)
- Related API records: [API 0002 — errors, capabilities, and fallback](../architecture/api-0002-errors-capabilities-fallback.md), [API 0003 — Phase-3A Python, NumPy, and private helper](../architecture/api-0003-python-numpy-matplotlib.md), and the companion surface record [API 0005 — Phase-3B public backend surface](../architecture/api-0005-phase3b-public-matplotlib-backend-surface.md)

This ADR is an accepted contract decision. It records the
Phase-3B public Matplotlib adapter contract for the first implementable strict
slice; independent review passed with no blocking findings at branch head
`d9a7366`, and merged Phase-3A helper plus Phase-3A2 same-wheel evidence
recorded in [ADR 0014](0014-phase3a2-pinned-manylinux-wheel-evidence.md) reconcile
with this boundary. It freezes no implementation: no Python source,
manifest, lockfile entry, wheel, workflow, or package artifact is authorized by
this record. Every exact public Python surface name lives in API 0005's
"Provisional names" section and remains unimplemented until the Phase-3B slice
lands. The broad v1 Matplotlib requirements remain normative; this record does
not close any full-v1 traceability row.

## Requirement references

This boundary supports the ownership and bridge portions of
`LP-MPL-001` through `LP-MPL-017`, `LP-FUNC-001` (Line2D series), and
`LP-FUNC-003` (linear axes) in the
[accepted requirements](../requirements/lumenplot-v1.0.md). It explicitly does
not complete them: `LP-PROD-006` keeps full Matplotlib backend API
compatibility, arbitrary private API parity, and unrestricted custom-Artist
parity outside v1, and this slice stays inside those profile bounds.
Profile-specific mapping intent: `LP-MPL-003` (fixed profiles),
`LP-MPL-004` (Figure/Artist authority), `LP-MPL-006`/`LP-MPL-007`/`LP-MPL-008`
(strict unsupported, hybrid whole-frame fallback, structured diagnostics),
and `LP-MPL-011` (no native performance claim for this profile).

## Context

ADR 0013 recorded the staged Phase-3A owned Rust seam and private helper and
deliberately left every public Matplotlib result, diagnostic, warning, canvas,
fallback, profile, generation, and file/path schema open until real helper
evidence existed. Its §9 fixed ten mandatory hazards that any later Phase-3B
decision must preserve. The completed read-only public-backend research
(Microsoft-free public Matplotlib 3.11.1 documentation and source inspection,
plus a scratch CPython/Matplotlib probe) supplies the observed evidence this
proposal builds on: the minimal `RendererBase` callback trace, loader and entry
point mechanics, point-unit linewidth semantics, style representability gaps,
file-output semantics, and the known risks of inherited base-class format
fallback.

The repository still has no merged helper/wheel runtime evidence (Phase-3A/3A2
implementation evidence is pending on a separate lane), and overview.md records
the public Phase-3B contract as open. This proposal is therefore recorded now,
against main, as a docs-only lane: it can be reviewed and reconciled with helper
evidence without colliding with implementation work, but it authorizes none.

## Decision

The following sections are the binding Phase-3B contract for the first public
backend slice, subject to the evidence-reconciliation gate below before any
support claim. Hazard numbering mirrors ADR 0013 §9 order.

### 1. Evidence target and support posture (hazard 1)

Phase-3B evaluation targets exactly Matplotlib 3.11.1 with backend API 1.1 on
CPython 3.11–3.14. This is an evidence target only. No support claim, compatibility
percentage, platform result, or version range follows from it; Matplotlib 3.10 /
API 1.0 remains a separate future cell, and patch releases that change callback
ordering or default styles require re-evaluation.

### 2. Public-API-only boundary (hazard 2)

The adapter source and tests use documented public Matplotlib APIs only. The
forbidden set is permanent for this slice: `_Backend` and legacy private backend
wrappers, `_renderer`/private renderer buffers, `_api`, `_pylab_helpers`/`Gcf`,
any `matplotlib._*` implementation path, private artist/transform/cache helpers,
and the undocumented `Axes.axison` attribute as a capability contract. Inherited
public base classes may use private internals internally; the scan governs direct
adapter imports and references. Because the official `backend_template.py`
imports forbidden names, it must not be copied as a template.

### 3. Two-stage eligibility preflight (hazard 3)

Eligibility is proven in two stages before any native allocation or output:

1. a static documented-public whitelist check of the Figure graph: exactly one
   Figure, one visible standard `Axes`, one visible plain `Line2D`, no visible
   unknown/custom artist, no subfigures/extra axes/text-with-content/legend/
   image/collection/patch/table, equal-length float-like finite-or-NaN line data;
2. one public `RendererBase` collector traversal with no native allocation or
   output, asserting the exact eligible trace in decision 4.

The collector stage is mandatory, not an optimization: documented public API has
no axis-off getter, and a custom artist can hide behavior inside `draw()`. The
collector runs before native output, is treated as an observation (never a silent
mutation), and its invocation of user artist code is an accepted, documented cost
of proof.

### 4. Exact eligible collector trace (hazard 4)

The only eligible collector trace is exactly:

```text
open_group("figure") → open_group("patch") → new_gc()
  → draw_path(figure background rectangle, rgbFace=effective figure RGBA)
→ close_group("patch") → open_group("axes") → open_group("line2d")
  → new_gc() → draw_path(line path, rgbFace=None) → close_group("line2d")
→ close_group("axes") → close_group("figure")
```

One figure-background `draw_path` plus one Line2D `draw_path`; nothing else.
Axes patches, spines, ticks, text, markers, images, collections, quad mesh,
Gouraud triangles, custom artists, hatch colors, and every other renderer
callback cause explicit unsupported handling in strict mode or whole-frame Agg
fallback in hybrid mode. An axes-on fixture (patch/axis/tick/text/spine
callbacks present) is a negative test fixture, never an eligible input.

#### 4a. Decorated-axes amendment (PRAC-A-D lane, 2026-08-25)

Amended by the accepted PRAC-A-D lane decision (parent workstream t_3339d0b5
comment thread): a standard `Axes` with decorations enabled (`axison=True`)
joins the eligible surface so that `LP-FUNC-003` axes decoration rendering
works natively in this slice. The eligible collector grammar widens from the
fixed trace above to its balanced-group form: after the figure background
stroke, each axes group may contain balanced artist subgroups (the
decoration surface and per-line `line2d` groups) whose only stroke events
are `new_gc()` + `draw_path`. Any other renderer callback (text, markers,
images, collections, quad mesh, Gouraud triangles) still raises through the
unbound public `RendererBase` and maps to explicit unsupported handling —
never a silent base-class no-op.

The decorated surface rendered natively, per axes, ahead of that axes'
content lines and clipped to its own rectangle:

1. solid (`linestyle == '-'`, not dashed) visible major gridlines at
   in-view major tick locations, one full-span segment per location;
2. major tick strokes on each visible edge line, length
   `markersize * dpi_eff / 72` px outward from the edge;
3. visible spine edges of the axes rectangle, emitted with the §5 fixed
   stroke surface (Butt cap, Miter join); spine width, color, alpha, and
   visibility are honored, spine-local cap/join styles are normalized,
   not approximated.

Still outside the slice and refused with an explicit reason: any axes
facecolor other than `'none'` (this slice emits no fill command), titles,
axis labels, offset text, tick label text (the T-lane deliverable), visible
minor tick lines or minor gridlines (major-only slice), non-solid gridline
styles, subplotspec/gridspec child axes, and any non-exact `Axes` subclass.
An undecorated fixture (`axison=False`) remains eligible unchanged.

#### 4b. Legend amendment (PRAC-A-L lane, 2026-08-26)

Amended by the accepted PRAC-A-L legend lane decision (2026-08-26): the
standard `matplotlib.legend.Legend` attached to an eligible Axes joins the
strict surface so that F-11 legend rendering works natively in this slice.
Per LP-MPL-020 the whitelist entry, collector-trace expectation, style
contract, and fixtures landed together.

The eligible legend object is narrow by contract:

- exactly `matplotlib.legend.Legend` (subclasses refuse), attached to a
  standard `Axes` (`Legend.axes`); figure-level legends refuse;
- single column (verified from the public legend layout geometry;
  multi-column layouts refuse);
- no shadow, no title text;
- one or more entries, each pairing a plain `Line2D` handle with a visible
  non-empty label; every other handle type refuses;
- each handle re-checks through the fixed line stroke surface
  (`_check_line2d_static`: butt cap, miter join, solid, no markers, default
  drawstyle — the legend never relaxes its owner's style contract);
- each label re-checks through the tick-label text contract plus a positive
  font-size guard (no math/TeX, no path effects, no leading/trailing
  whitespace, no newlines).

The collector grammar widens accordingly. Since the LP-FUNC-035 D2
amendment (interleaved class-mixed acceptance, order-free axes body) the
axes group carries no whole-trace ordering to widen; the legend's own
group structure is what matters: one balanced `legend` group inside the
axes group containing (frame-on legends) one `patch` group carrying the
rounded frame outline and (per entry, in draw order) one `line2d` group
with the proxy handle stroke and one `text` group whose `draw_text`
callback must match the statically enumerated legend label queue. Legend
geometry provenance:
Matplotlib's own `Legend.draw` layout executes under the collector and hands
over display-space geometry — the frame path arrives already transformed to
display pixels (the collector records its affine flag), and each handle
stroke arrives in handlebox-local coordinates with its layout affine, which
the adapter applies explicitly. The adapter never re-derives legend layout
algebra from getters; drift between static enumeration and the live stream
refuses through the existing label cross-check.

Rendered commands, ordered by the compositing contract below (LP-FUNC-035
D1): the frame outline and handle strokes ride as one bundle at the
`Legend` artist's real public zorder inside the axes' single stable sort —
exactly where Matplotlib paints the legend relative to decorations and
content lines (default zorder 5 paints above default content; negative
content zorders sink below it):

1. the frame outline as one filled+stroked path command (`decoration:
   "legend_frame"`): facecolor from the collected patch face, edge color /
   width / alpha from the collected graphics context, identity transform,
   full-canvas clip. This is the slice's only sanctioned curved outline
   (`BoxStyle.Round` MOVETO/LINETO/CURVE3/CLOSEPOLY); other code sets, a
   polygonal frame, hatching, dashes, sketch, or path effects refuse;
2. one polyline per handle (`decoration: "legend_handle"`) with the §5
   stroke surface resolved from the collected graphics context;
3. one glyph-path command per entry label via the public `textpath`
   module (`decoration: "legend_label"`), identical route to tick labels.

Still outside the slice and refused with an explicit reason: figure-level
legends, legend subclasses, multi-column layouts, shadows, titles,
non-`Line2D` handles, handles violating the stroke contract, empty legends,
unsupported label text, and any legend on axes whose projection is
unsupported by this slice.

### 5. Fixed-style guards, no approximation (hazard 5)

The native request supports exactly the Phase-2 private frame style surface:
positive finite solid stroke width, encoded straight-sRGB RGBA8 color with
zero-alpha RGB canonicalized to zero, rectangular clip, solid dash state, Butt
cap, Miter join, miter limit 4, antialiasing enabled, no snap/sketch/path
effects. Effective solid cap/join styles other than Butt/Miter are rejected, not
approximated; a strict fixture must set them explicitly because current
Matplotlib defaults are projecting/round. Dashes, markers, non-default
drawstyles, per-series styles, custom miter limits, and renderer metadata are
unsupported. Matplotlib exposes join style but no public miter-limit getter, so
exact Agg corner parity is unprovable: image comparison against Agg uses
declared semantic tolerance (or avoids sharp-corner fixtures); byte identity
with Agg is never asserted, while same-host native byte determinism remains a
separate requirement.

### 6. Geometry and DPI mapping (hazard 6)

Canonical geometry is top-left `DisplayLogical` with 72 DisplayLogical points
per inch.
With effective savefig DPI (`print_figure` temporarily sets `figure.dpi`) as
output DPI and physical canvas pixel size from public accessors, the scale factor
is `s = 72 / dpi_eff`; each finite bottom-left display pixel point `(x_px, y_px)`
maps to top-left logical points `(x_px * s, (H_px - y_px) * s)`, and rectangular
clips map corner-to-corner equivalently. Rendering sources series data through
the data route — public `Line2D` coordinate getters plus public increasing linear
Axes limits into one temporary linear `ArbitraryXY` native request — to preserve
full source resolution and NaN gap structure; the collected callback path proves
the affine transform and clipping behavior and reconciles against the sourced
data rather than feeding rendering. Non-affine transforms, inverted or log axes,
custom transforms/clips, and non-default drawstyles are unsupported.

### 7. Explicit non-PNG guard (hazard 7)

PNG is the only output format. `print_figure` is guarded so non-PNG formats fail
explicitly instead of falling through inherited base-class behavior, which
research demonstrated silently selects another registered backend's encoder
(observed `%PDF-1.4` output). `filetypes` contains only PNG; extension inference
follows public `Figure.savefig` semantics; invalid orientation values fail
explicitly; non-empty `metadata` beyond None/empty, non-empty `pil_kwargs`,
`bbox_inches='tight'`, non-default padding, and `bbox_extra_artists` are
unsupported natively (hybrid may delegate the entire original request to whole-
frame Agg). Native PNG bytes are constructed completely before any external
write: adapter-owned files are opened/written/closed by the adapter; caller-owned
binary file-like targets receive exactly one public `write(bytes)` call and are
never closed; `OSError`, short writes, and user writer exceptions propagate
unchanged, and Agg is never invoked after a native I/O failure.

### 8. Hybrid fallback shape (hazard 8)

If hybrid-explicit is accepted for this slice, fallback is only the public
whole-frame `matplotlib.backends.backend_agg.FigureCanvasAgg` render of the
entire original request, restoring the original Figure canvas afterward. Native
and Agg pixels are never composited; there is no partial subtree fallback because
public callbacks expose no reliable subtree boundary. Exactly one structured
fallback diagnostic is recorded per successful hybrid publication. Strict mode
never falls back: unsupported capability raises the stable unsupported result
before any target write.

### 9. Terminal-failure rules (hazard 9)

Fallback is a capability decision made before output. Invalid input, capacity or
arithmetic overflow, allocation/OOM, encoding/internal errors, Rust panics
(redacted), reentrancy, stale publication, and file-write failures are explicit
errors and never trigger Agg fallback or silent degradation. Device loss and OOM
are terminal. A stale attempt must not overwrite a newer published result:
publication is guarded by a monotonic process-local per-canvas generation
counter, diagnostics are replaced atomically only after successful publication,
and failed attempts clear previously published diagnostics so stale fallback
state is never reported. Calls are reentrant-safe with no global mutable state
and no non-reentrant lock held across public callbacks.

### 10. Figure/Artist authority (hazard 10)

In adapter mode the Matplotlib Figure/Artist graph remains authoritative; the
native request is a disposable one-shot snapshot derived under the preflight
guards, never a retained competing Scene, and no native ViewState writeback is
claimed for this slice. The adapter never mutates the authoritative Figure to
make an unsupported feature pass (explicit configuration changes stay the
caller's decision), restores any temporary effective-DPI state after output, and
holds no non-reentrant lock across public callbacks.

### 11. Identity, layout, profiles, and error envelope

Identity follows `LP-MPL-002`: distribution `lumenplot-mpl`, import package
`lumenplot_mpl`, backend module `lumenplot_mpl.backend`, module loader
`module://lumenplot_mpl.backend`, entry-point group
`[project.entry-points."matplotlib.backend"]` with value
`lumenplot = "lumenplot_mpl.backend"`. Source layout extends accepted API 0003
§1 (`python/lumenplot_mpl/{__init__.py,_native.pyi,py.typed}` plus repository-root
`pyproject.toml` built via `crates/lumenplot-python`) with `backend.py` added at
implementation time. Backend exports are `FigureCanvasLumenPlot(FigureCanvasBase)`
aliased as `FigureCanvas` and unchanged `FigureManager = FigureManagerBase` with
diagnostics living on the canvas; `required_interactive_framework = None`;
`filetypes` is PNG-only. Profiles are the fixed trio from `LP-MPL-003` with
strict-common-2d raising unsupported before write, hybrid-explicit defaulting to
whole-frame Agg fallback, and accelerated-native explicitly deferred out of this
slice. Errors reuse the lowercase API-0002 tokens through the existing exhaustive
BridgeError mapping, with `LumenPlotError(RuntimeError)` remaining the only
LumenPlot exception class; savefig/print_png keep `None` return semantics and a
separate provisional helper returns owned bytes plus immutable diagnostics. The
crate DAG is unchanged: `lumenplot-python -> lumenplot ->
{lumenplot-engine, lumenplot-export}`, with the engine free of Python and
Matplotlib concrete types. Exact result/diagnostic field names remain in API
0005's provisional-names section.

### 12. Ordered delivery after acceptance

Acceptance of this ADR and API 0005 gates implementation in this order: (1)
helper-first verification over the merged Phase-3A seam once PR-level helper and
wheel evidence lands; (2) strict single-Line2D canvas behind the two-stage
preflight with explicit unsupported handling; (3) hybrid-explicit whole-frame Agg
fallback and diagnostics only after strict paths are independently tested; (4)
loader/entry-point/package lifecycle tests last. Axes/text/markers/collections/
images/Gouraud/TeX/vector formats, accelerated-native, additional Matplotlib
versions, platforms, and any performance claim are later, separately evidenced
work. No sentence in this proposal claims support, performance, platform reach,
or zero-Python traversal for the ordinary Figure/Artist profile (`LP-MPL-011`).

## Alternatives considered

- **Waiting for merged Phase-3A/3A2 evidence before recording anything** was
  rejected for this docs lane because recording is a precondition of the next
  phase and the file set is disjoint from implementation work; the mitigation
  was Proposed status plus an evidence-reconciliation gate on acceptance, which
  this record has now satisfied.
- **Recording the contract as accepted immediately** was rejected because
  API 0003 keeps Phase-3B schemas deliberately open until real helper evidence
  exists and repo policy requires independent review and maintainer merge
  approval for architecture acceptance.
- **Callback-route rendering (sourcing geometry from the collected renderer
  path)** was rejected for rendering because renderer-side simplification can
  lose source resolution and NaN gap structure; it is kept for eligibility proof
  and affine/clip reconciliation.
- **A combined helper + package + canvas + fallback leap** was rejected: it
  concentrates failures around one collision hotspot and makes attribution
  impossible; ordered delivery keeps each step independently verifiable.
- **Byte-identity image oracles against Agg** were rejected because the missing
  public miter-limit getter makes exact corner parity unprovable; semantic
  tolerance is honest about that residual gap.

## Consequences

Positive consequences (on acceptance):

- ADR 0013 §9's mandatory hazards become an explicit, testable contract instead
  of a hazard list, without reopening any settled Phase-3A boundary.
- Reviewers get a fixed eligible-trace definition and fixed-style guard set to
  verify implementation evidence against, keeping unsupported features loud.
- The strict slice stays small enough to attribute failures while preserving the
  Figure/Artist authority and one-way dependency direction.

Costs and residual constraints:

- The slice renders one solid-styled Line2D on linear axes with PNG output only;
  everything else is explicit unsupported or whole-frame fallback.
- Corner-rendering parity with Agg remains unproven at the miter level; visual
  comparisons are tolerance-based by design, not by omission.
- The collector executes user artist code during preflight; this is documented,
  bounded to run before native allocation, and never a mutation.
- Acceptance additionally requires reconciliation against merged Phase-3A/3A2
  helper and wheel evidence; this document records no such evidence today.

## Verification and evidence boundary

Acceptance adds documentation only: two records and their index entries. No
product source, manifests, lockfiles, CI dependencies, wheel artifacts,
workflows, or publication settings exist for this slice yet, and no existing
ADR/API record is edited. The workspace architecture checker and its unittest
suite stayed green on the acceptance branch. After implementation, the governing
verification is the API 0005 tests matrix (loader/import, collector trace,
geometry/style oracle, native output, option/error matrix, fallback and terminal-
failure injection, lifecycle/generation, forbidden-name scans, packaging and
evidence gates), with any timing or compatibility-breadth claim routed through
the benchmark skill's named-workload protocol.

## Related records

- [ADR index](README.md)
- [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md)
- [ADR 0003 — facade and crate dependency graph](0003-facade-and-crate-dag.md)
- [ADR 0012 — private line frame and deterministic PNG contract](0012-private-line-frame-and-png-contract.md)
- [ADR 0013 — hidden facade and private Python line/PNG helper](0013-hidden-facade-private-python-line-png.md)
- [ADR 0014 — Phase-3A2 pinned manylinux wheel evidence](0014-phase3a2-pinned-manylinux-wheel-evidence.md)
- [API 0002 — errors, capabilities, and fallback](../architecture/api-0002-errors-capabilities-fallback.md)
- [API 0003 — Phase-3A Python, NumPy, and private helper](../architecture/api-0003-python-numpy-matplotlib.md)
- [API 0005 — Phase-3B public backend surface](../architecture/api-0005-phase3b-public-matplotlib-backend-surface.md)
- [Architecture overview](../architecture/overview.md)
- [Open decisions — O-10](../architecture/open-decisions.md)
- [v1 requirements](../requirements/lumenplot-v1.0.md)
- [Requirements traceability](../requirements/traceability-v1.0.md)
