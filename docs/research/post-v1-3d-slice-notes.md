# Post-v1 design research: 3D slice (post-v1 exploratory candidate, LP-FUNC-025)

## Status

**DESIGN RESEARCH ONLY — NOT AN ACCEPTED DECISION, ROADMAP COMMITMENT,
OR SUPPORT CLAIM.**
This note explores how a 3D capability *could* fit the accepted LumenPlot
architecture if the project ever chooses to revisit it. Nothing here promotes a
candidate to a promise, a contract, or an implementation obligation. Where this
note says "option", "sketch", or "future", read exactly that.

**v1 NON-GOAL declaration.** 3D rendering is excluded from v1 by the canon:

- [LP-FUNC-025](../requirements/lumenplot-v1.0.md) — `NON-GOAL`: "A 3D
  rendering engine is outside v1; a post-v1 exploratory candidate does not
  become a v1 acceptance promise." (`Phase: future`, `Release: excluded`,
  evidence `AT-REVIEW-SCOPE`).
- Requirements §4 scope table: "3D remains v1 non-goal and post-v1 only".
- [ADR-0002](../adr/0002-gpu-native-engine-and-matplotlib-adapter.md)
  non-goals: "3D rendering, fitting, regression, or data-analysis
  responsibilities" are outside the engine's responsibilities.

Changing that envelope requires an explicit ADR amendment plus coordinated
requirements and traceability updates through the `architecture-authority`
decision gate. That work is **out of scope for this note**, which changes
nothing and commits to nothing.

Evidence basis: all repository citations below were verified verbatim on
origin/main @ `866cfc5` on 2026-08-24.

Terminology: throughout, the subject is the **post-v1 exploratory candidate
(LP-FUNC-025)**. The requirements vocabulary ends at Phase 5 / `future` /
`5+`; no "Phase 6" exists and none is introduced here.

## 1. Scene semantic-frame extension options

### Current state (verified)

The native semantic surface is strictly two-dimensional today:

- `SeriesTopology` has exactly two variants, `MonotonicX` and `ArbitraryXY`
  (`crates/lumenplot-engine/src/bridge.rs:173`).
- `SeriesData` is built from owned x/y pairs via
  `SeriesData::from_owned_xy(topology, ...)` (`bridge.rs:194`).
- `PlotScene::new(canonical_view: Viewport, scales: AxisScales)`
  (`bridge.rs:581`) fixes a two-axis canonical viewport and per-axis scales.

### Option A — parallel Series3D representation

Introduce a distinct `Series3DData` input and a scene-level marker that the
frame is three-dimensional, keeping existing 2D types untouched.

- Pros: zero ambiguity about which invariants apply; 2D code paths are never
  asked about a z axis.
- Cons: duplicates validation, revision, snapshot, and LOD plumbing along a
  second axis of type variants; risks a long-lived parallel hierarchy that
  later diverges from the 2D contracts.

### Option B — additive third channel on the existing frame (sketch)

Keep `Viewport`, scales, transactions, snapshots, and revisions exactly as
accepted, and add: a third owned coordinate channel on the series input, a
z-bounds fact beside the existing two-axis bounds, and optional projection
attributes on the view facts. 2D scenes simply leave the additions empty, so
the 2D invariants remain checkable.

- Pros: reuses the accepted single-writer transaction/snapshot/revision flow;
  avoids a parallel scene type.
- Cons: touches more shared validation logic; every consumer must handle (or
  explicitly reject) a populated z channel.

This note does not choose between A and B; both are recorded because the
choice interacts with the open questions in §6.

### Three-axis bounds

Canonical data stays f64 (requirements §6 data model). Bounds for x and y come
from the existing canonical viewport; a future 3D candidate would add z bounds
as canonical f64 facts resolved in the same layout step, so that clipping,
ticks, and pick mapping see one consistent bound set rather than renderer-side
ad-hoc limits.

### Projection attributes

A 3D candidate needs camera-style parameters: elevation/azimuth/roll angles
and an orthographic-vs-perspective switch. Two placements are conceivable:
as scene-level view facts resolved once per transaction, or as per-render
options resolved at packet build time. Placement affects who may mutate them
(scene transactions vs. render options) and therefore interacts with O-05;
the choice is deliberately left open here.

Integration constraints that either option must respect:

- **O-02 (public surface)** — signatures must not leak engine chunks, LOD,
  caches, component revisions, or internal RenderPacket fields. Any projection
  attribute exposed publicly would be plain semantic data on the frame, never
  a borrowed renderer internal.
- **O-05 (scene ownership)** — `PlotScene` stays the sole native authority;
  mutations flow through single-writer transactions producing revisions,
  receipts, and immutable snapshots; the derived adapter scene remains
  revisioned cache state. 3D would inherit these rules unchanged.
- **LP-REL-001 (persistence non-goal)** — no serialization identity is
  introduced for scenes or packets, 3D or otherwise. A future 3D scene gains
  no save-file format by virtue of existing.

## 2. RenderPacket extension sketch (internal seam only)

[ADR-0004](../adr/0004-renderpacket-resource-lifecycle.md) fixes seven
RenderPacket field families: packet identity; target and view facts; owned
local-f32 and batched geometry; draw ranges and order; clip and style
references; pick mapping; opaque logical resource identifiers. The packet also
carries `SceneRevision`, `WorkGeneration`, and `DeviceGeneration` as distinct
validation inputs, is validated all-or-nothing before publication, and is
immutable, process-local, internal, and non-serialized (O-04). ADR-0002
explicitly rejected a **public or serialized RenderPacket**; that rejection is
assumed, not revisited.

<!-- markdownlint-disable MD013 -->

A 3D candidate would extend the packet **additively inside the existing seven
families** — no eighth family:

| Future 3D fact | Existing family it lands in |
| --- | --- |
| Camera position/target/up, view matrix, projection matrix, near/far planes | Target and view facts |
| Triangle-list vertices and per-batch index batches (origin-relative local f32) | Owned local-f32 and batched geometry |
| Z-sorted or depth-tested draw ordering, per-batch draw ranges | Draw ranges and order |

<!-- markdownlint-enable MD013 -->

The remaining families (identity, clip/style references, pick mapping, logical
resource identifiers) need no structural change: pick mapping already maps
rendered geometry to semantic identity regardless of dimensionality, and
logical IDs already cover buffers a mesh would occupy.

Geometry conversion follows the accepted rule: canonical f64 is converted to
origin-relative local f32 (requirements §7 prohibits direct absolute
f64→f32 narrowing; coordinate semantics stay owned by ADR-0007). How z bounds
participate in the origin choice is an open question (§6) — a poor origin can
waste most of the f32 mantissa when |z − origin| is large.

Backward compatibility and versioning are **open questions, not decisions**:
one route relies on the existing generation triple (a packet from an older
WorkGeneration is stale regardless of shape); another adds an explicit
packet-schema version to the packet identity family so a renderer instance can
reject packets built under different family shapes. Both preserve the
non-public boundary; neither is chosen here.

The packet remains what O-04 and ADR-0002 require: validated whole-packet,
process-local, renderer-instance scoped, containing no wgpu/window/Python/
Matplotlib concrete objects, and never serialized, persisted, or made public.
Export continues to consume the shared semantic/layout frame and never
reverse-engineers GPU buffers.

## 3. Rendering routes

### 3a. Near-term CPU route: painter's algorithm on the pinned raster stack

The export and Python seams already render through tiny-skia, pinned at
`=0.12.0` in both `crates/lumenplot-export/Cargo.toml:12` and
`crates/lumenplot-python/Cargo.toml:19`, with usage in
`export/src/raster.rs`, `export/src/compositor.rs`, and the Python
`render_frame_png` seam (`python/src/frame.rs:992`). A first 3D implementation
could reuse exactly this stack: project triangles to 2D with the §1 view
facts, sort them back-to-front by depth (painter's algorithm), fill with
tiny-skia paths, and clip to the three-axis bounds.

Properties of this route:

- No new dependency, no GPU requirement, works everywhere export works today.
- Same fidelity class as matplotlib's own mplot3d, which is likewise a 2D
  projection with painter-style layering (§4) — intersecting geometry produces
  layering artifacts rather than correct occlusion.
- Sorting cost grows with triangle count; ADR-0004's bounded-batch grouping is
  the natural place to bound sort scope per batch.
- It is a candidate vehicle for *evidence*, not an adoption decision: any
  claim that this route is fast enough would require the named-workload
  measurement protocol the project demands.

### 3b. Target route: depth-buffered triangles via the wgpu portable renderer

The intended end state renders triangles with a hardware depth buffer on the
portable path required by LP-PLAT-001 (a `MUST` portable wgpu-based
implementation path that keeps wgpu concrete types out of the core) and staged
by [ADR-0008](../adr/0008-portable-gpu-and-shaders.md). Today both
`crates/lumenplot-render-api/src/lib.rs` and
`crates/lumenplot-render-wgpu/src/lib.rs` are Phase-0 documentation stubs, so
this route is blocked until those crates stop being stubs.

Adoption discipline: Phase-4 native evidence gates govern this exactly as
they govern any native-path decision. `AT-BENCH-NATIVE-AB` (LP-PLAT-003,
LP-PLAT-011, LP-PLAT-012, LP-PLAT-007) requires measured A/B comparison of
frame time, CPU overhead, present latency, memory, and feature availability
before adoption, and forbids retaining a backend merely because it is newer.
Depth-buffered 3D rendering is adopted, if ever, **evidence-gated — never
automatically**, and a CPU-painter route is retained whenever the measured
benefit does not justify the maintenance cost.

## 4. Matplotlib adapter side

### mplot3d reality

Matplotlib's 3D support is itself a 2D projection, not a 3D renderer:

- mplot3d transforms data through proj3d's world → view → perspective
  transformation chain and draws the result with ordinary 2D artists using
  painter-style ordering
  (<https://matplotlib.org/stable/gallery/mplot3d/>).
- Maintainers have long stated that mplot3d is "not a true 3d plotting
  library" and cannot correctly layer *intersecting* artists; z-order
  artifacts for crossing Poly3DCollections remain open in
  <https://github.com/matplotlib/matplotlib/issues/3919> .
- pyplot cannot create 3D content implicitly: 3D axes exist only through the
  explicit Axes3D API (`fig.add_subplot(projection="3d")` /
  `mpl_toolkits.mplot3d.axes3d.Axes3D`).

### Today's adapter behavior (verified)

The Phase-3B adapter whitelist is Line2D-only:
`_EligibilityPreflight._ARTIST_WHITELIST = (matplotlib.lines.Line2D,)`
(`python/lumenplot_mpl/backend.py:303`), with the stable token
`_UNSUPPORTED_TOKEN = "unsupported-capability"` at
`python/lumenplot_mpl/backend.py:67`. Consequences for 3D figures today:

- Any Axes3D artist (Line3D, Poly3DCollection, and friends) fails the
  documented-public whitelist check of API-0005 §4 before any native
  allocation or output.
- **Strict** mode therefore raises/fails with the stable
  `unsupported-capability` token before any target write (API-0005 §3).
- **Hybrid** mode falls back whole-frame to matplotlib's Agg backend, which
  renders mplot3d natively fine — the fallback is faithful to matplotlib,
  including mplot3d's own painter's-algorithm artifacts. Hybrid publishes
  exactly one structured fallback diagnostic with `scope="whole-frame"`,
  `representation="raster"`, `fallback_type="matplotlib-agg"`.

So v1 already handles 3D input explicitly and observably, without any 3D-aware
code: unknown artists are unsupported, and the documented fallback renders
them through matplotlib.

### Future diagnostic extension (design sketch, not a contract)

If a later slice wants 3D-specific diagnostics instead of generic
unknown-artist handling:

- Detect 3D artists explicitly in the eligibility preflight: presence of
  `mpl_toolkits.mplot3d.axes3d.Axes3D` and art3d artist classes
  (`Line3D`, `Line3DCollection`, `Poly3DCollection`, 3D scatter/collection
  variants).
- Emit precise `type` context tokens in the API-0005 §3 diagnostic shape
  (for example artist-class-derived tokens such as an Axes3D context vs. a
  Poly3DCollection context). Exact token naming is provisional and
  non-contract: API-0005 §3 fixes the field set, while wording stays
  non-contract and no diagnostic becomes a wire/persistence identity.
- Preserve no silent pass-through: detection must only ever route to explicit
  strict unsupported or whole-frame hybrid fallback, never to native
  rendering of un-whitelisted geometry, honoring the O-03 constraint of no
  silent omission or best-effort degradation and the API-0005 §3–4
  fixed-set diagnostic contract.
- Any whitelist widening is a public-surface change (O-02, API-0005) owned by
  the `architecture-authority`; this note proposes none.

## 5. v1 zero-impact proof obligations

A post-v1 research note must demonstrably not move v1. Each obligation below
has a concrete mechanism, and each mechanism was checked in this worktree:

<!-- markdownlint-disable MD013 -->

| # | Obligation | Concrete mechanism |
| --- | --- | --- |
| i | Adapter whitelist unchanged in v1 ⇒ 3D rides the documented fallback path | `_ARTIST_WHITELIST = (Line2D,)` is untouched; strict `unsupported-capability` and hybrid whole-frame Agg behave exactly as recorded in API-0005 §3–4; existing Phase-3B suites pin this behavior |
| ii | Zero Rust/Python schema changes in v1 | This lane adds one docs file and nothing else; `git diff --name-only origin/main` must show only `docs/research/post-v1-3d-slice-notes.md` |
| iii | Static checker pins nothing under `docs/research/` ⇒ gate unaffected | `docs/research/` lies outside every inventoried checker surface (crates, facade modules, Python inventory, workflow vocabulary); verification runs `scripts/check_workspace_architecture.py` and requires exit 0 |
| iv | CI workflows and wheel-evidence jobs untouched | No `.github/workflows/` file changes, so the workspace-architecture wheel-evidence classification (auditwheel/manylinux/maturin/wheel vocabulary) sees nothing new |
| v | Traceability rows untouched | [LP-FUNC-025](../requirements/traceability-v1.0.md) remains `Not applicable — scope exclusion` in the v1 traceability registry; requirements §4 scope row remains "3D remains v1 non-goal and post-v1 only"; neither file is modified here |

<!-- markdownlint-enable MD013 -->

LP-FUNC-025 itself carries the guard against promise creep — "a post-v1
exploratory candidate does not become a v1 acceptance promise" — and this note
stays inside that guard by being strictly non-normative research.

## 6. Open questions for the architecture-authority

These are recorded questions, **not decisions**; each needs an explicit
future decision before any implementation work could begin:

1. **Projection default** — orthographic vs. perspective for a future 3D
   view, and whether both modes are exposed or one is chosen first.
2. **Z bounds in the f64→f32 conversion** — how the third axis participates
   in the accepted canonical-f64 → origin-relative-local-f32 conversion
   (requirements §7): origin placement per scene vs. per axis triple, and the
   resulting precision budget when |z − origin| is large.
3. **Scatter alignment** — whether a future scatter3D candidate aligns with
   LP-FUNC-017 scatter semantics (`SHOULD`, Phase 5, `AT-FUNC-SCATTER`) or is
   tracked separately under LP-FUNC-025.
4. **Packet-schema versioning** — generation-triple-only staleness versus an
   explicit packet-schema version inside the packet identity family, if the
   family set ever grows (see §2).
5. **ADR numbering reservation** — whether to reserve the next ADR number
   (0016 at the time of writing) for a future 3D decision record, so a later
   amendment does not renumber history.

## References

Internal (canonical sources; linked, not copied):

- Requirements: `LP-FUNC-025`, §4 scope table, `LP-REL-001`, `LP-PLAT-001`,
  `LP-PLAT-003/007/011/012`, `LP-FUNC-017`
  ([lumenplot-v1.0.md](../requirements/lumenplot-v1.0.md))
- Traceability: [traceability-v1.0.md](../requirements/traceability-v1.0.md)
- Architecture records: [ADR-0002](../adr/0002-gpu-native-engine-and-matplotlib-adapter.md),
  [ADR-0004](../adr/0004-renderpacket-resource-lifecycle.md),
  [ADR-0007](../adr/0007-coordinate-color-text-export.md),
  [ADR-0008](../adr/0008-portable-gpu-and-shaders.md),
  [API-0005](../architecture/api-0005-phase3b-public-matplotlib-backend-surface.md),
  [open-decisions](../architecture/open-decisions.md) (O-02, O-03, O-04, O-05)

External:

- matplotlib mplot3d documentation and projection pipeline
  (<https://matplotlib.org/stable/gallery/mplot3d/>)
- matplotlib issue 3919, mplot3d intersecting-artist layering limitation
  (<https://github.com/matplotlib/matplotlib/issues/3919>)
