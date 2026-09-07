# ADR 0016: v1 3D envelope and Agg-parity acceptance

- Status: **Accepted product envelope — O-19 through O-22 decided by the 2026-09-07 amendment below; implementation and evidence pending**
- Accepted by the architecture authority (maintainer), 2026-09-05
- Date: 2026-09-05
- Decision owner: architecture-authority
- Recorded by: architecture-authority
- Scope: promotion of `LP-FUNC-025` to the v1 line/triangulated-surface 3D capability, its acceptance oracle, sequencing, and unchanged internal/public boundaries
- Amends: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md) (3D non-goal only)
- Governing requirements: [`LP-FUNC-025` and §15.1](../requirements/lumenplot-v1.0.md)
- Open implementation gates: [O-19 through O-22](../architecture/open-decisions.md#o-19-3d-projection-default)

This record changes the accepted product envelope; it is not an implementation,
compatibility, performance, platform-support, or release result. The current
traceability result for `LP-FUNC-025` is `Not implemented`.

## Context

ADR 0002 originally excluded 3D rendering from v1, and `LP-FUNC-025` recorded
that exclusion as a `NON-GOAL`. The maintainer has now selected 3D plotting for
v1 with a deliberately bounded quality rule: adapter-originated 3D output is no
worse than the pinned Matplotlib Agg mplot3d reference. “No worse” means the
four-part §15.1 parity contract, including visible ordering artifacts in the
reference; it does not mean that a different, more physically correct depth
result may replace compatibility evidence.

The earlier [3D research note](../research/post-v1-3d-slice-notes.md) supplied
options and identified unresolved choices. Its non-goal status statements are
historical inputs superseded by this record and the requirements amendment; its
prototype observations remain research, not product evidence.

Existing `hybrid-explicit` behavior can already render an unsupported mplot3d
Figure through explicit whole-frame Agg fallback. That proves only the existing
fallback route. Counting it as native 3D implementation would make the new v1
requirement vacuous and is therefore prohibited.

## Decision

### 1. v1 capability and sequence

`LP-FUNC-025` is a Phase 3 v1 `MUST`, with evidence gate `AT-FUNC-3D`. Its
minimum semantic scope is:

- a three-axis plot with decorations sufficient to identify x, y, and z;
- three-dimensional polylines;
- triangulated surface or mesh geometry with deterministic projected draw
  ordering; and
- native and Matplotlib-adapter output derived from the same resolved semantic
  meaning.

Exact public class, function, and constructor signatures are not selected here.
Scatter3D is not silently included or excluded by the word “3D”; O-21 must
classify it relative to `LP-FUNC-017` before its implementation or evidence can
count toward either row.

The implementation milestone follows completion of the shared semantic frame
and internal RenderPacket contract. The roadmap names this ordered insertion
M2.5 and keeps the requirements phase vocabulary at Phase 0 through Phase 5;
no additional phase is introduced.

### 2. Authority, semantic frame, and numeric facts

The accepted state rules do not change:

- native mode keeps `PlotScene` authoritative;
- Matplotlib mode keeps the Figure/Artist graph authoritative and derives a
  revisioned disposable Scene snapshot/cache;
- Scene mutation remains single-writer and transactional, and derived work
  remains immutable, revisioned, generation-cancellable, and stale-safe.

Projection and view attributes are resolved backend-neutral semantic-frame
facts, not renderer-owned mutable state. The frame also carries canonical x, y,
and z coordinates and all three bound pairs as f64 facts. Renderers may derive
local f32 values only at the established renderer boundary; direct absolute
f64-to-f32 narrowing remains prohibited. O-19 selects the public projection
default, and O-20 selects how z participates in origin choice and its precision
budget. This record fixes neither answer.

### 3. Renderer and adapter boundaries

The 3D capability extends the existing semantic-frame and renderer direction; it
does not create a parallel authoritative scene or a frontend dependency in
core. Projected line geometry, triangle batches, and draw/depth order must be
representable by the internal renderer seam, but the exact packet shape cannot
be implemented until O-22 settles packet-schema versioning.

`RenderPacket` remains immutable after validation, process-local,
renderer-instance scoped, internal, and non-serialized. It gains no public
constructor, wire identity, save/load path, persistence identity, or export
ownership. Export continues to consume shared semantic/layout meaning rather
than reverse-engineering GPU buffers.

The fixed adapter profiles remain unchanged:

- `strict-common-2d` remains a 2D profile and explicitly refuses 3D rather than
  changing meaning under its existing name;
- `hybrid-explicit` may render a fully recognized 3D surface natively once its
  complete eligibility contract passes, and otherwise uses the existing
  diagnosed whole-frame Agg fallback; and
- `accelerated-native` remains opt-in and may consume a sealed eligible snapshot
  only under its existing authority and performance rules.

No new profile, silent approximation, partial successful frame, or implicit
fallback is authorized by this record. Every artist-class eligibility extension
still lands its whitelist, collector trace, resolved style contract, negative
cases, fallback behavior, fixtures, and rollback rule atomically.

### 4. `AT-FUNC-3D` acceptance

The acceptance oracle is the pinned `FigureCanvasAgg` mplot3d render identified
by requirements §15.1. All four independent parts apply without relaxed
thresholds:

1. semantic and geometry parity;
2. decoded-pixel parity;
3. text and style parity; and
4. operational parity and fallback.

Each 3D fixture records explicit public projection/view attributes, canonical
f64 x/y/z source facts and bounds, projected line and triangle geometry, draw
order, effective DPI and dimensions, resolved styles/fonts, the reference PNG
and mask digests, and comparator results. A default-case fixture cannot be
accepted until O-19 fixes the default; explicit projection fixtures may be
designed before then but are not implementation authorization.

Triangle/depth-order fixtures include non-intersecting geometry and cases that
expose mplot3d painter-order or intersecting-geometry artifacts. The candidate
must reproduce the pinned reference result for the compatibility path. A depth
buffer that produces a visually superior but different overlap is not a pass;
superior depth semantics require a separately accepted capability and cannot be
substituted for `AT-FUNC-3D`.

Whole-frame Agg fallback remains required and observable when native eligibility
is absent, but fallback output alone cannot close `LP-FUNC-025`. Closure needs a
native 3D semantic/geometry path plus the adapter-originated parity fixtures and
the existing ownership, lifecycle, publication, and no-write failure evidence.

### 5. Boundaries that remain unchanged

This amendment changes only the former 3D exclusion. It does not change:

- `LP-REL-001`: project/Scene serialization and persistent RenderPacket remain
  v1 non-goals;
- the rejection of a public, wire, or serialized RenderPacket;
- the one-way `Matplotlib -> adapter -> engine` dependency direction;
- fitting, regression, and general data-analysis exclusions;
- the native/adapter authority split or fallback diagnostics;
- the evidence-gated portable/native backend policy; or
- any implementation, performance, platform, compatibility, support, or release
  status.

## Stop conditions before implementation fan-out

The following are architecture decisions, not implementation details. Work that
depends on any answer must stop until the corresponding open-decision entry is
accepted. (O-19 through O-22 were decided by the 2026-09-07 amendment below;
their open-decision entries now record those acceptances.)

1. **O-19 — projection default:** orthographic versus perspective, whether both
   are public in the first surface, and the exact default-case semantics.
2. **O-20 — z origin and precision:** how z participates in canonical-f64 to
   origin-relative-local-f32 conversion and the required error budget.
3. **O-21 — scatter3D classification:** whether scatter3D is part of this v1
   `MUST` or remains aligned with `LP-FUNC-017` (`SHOULD`, Phase 5).
4. **O-22 — packet-schema versioning:** whether generation identity is
   sufficient for the internal 3D shape change or an explicit internal schema
   version is required.

## Alternatives considered

### Keep 3D post-v1

Rejected by the maintainer's v1 product decision. Retaining the old non-goal
would make the requirements, roadmap, and release gate contradict that decision.

### Count existing hybrid Agg fallback as implementation

Rejected. It would provide no native 3D semantic frame or renderer capability
and would turn an existing compatibility escape route into false evidence for a
new product requirement.

### Require physically superior depth-buffered output

Rejected as the compatibility gate. mplot3d reference artifacts are part of the
accepted parity output. A superior native mode may be proposed later, but it
cannot replace the pinned compatibility result.

### Publish or serialize a 3D RenderPacket

Rejected. Dimensionality does not change packet ownership, visibility,
persistence, security, or lifecycle boundaries.

## Consequences and compatibility impact

- v1 gains one release-blocking normative row without changing the total
  requirement count: normative rows increase by one, `MUST` increases by one,
  `NON-GOAL` decreases by one, and `AT-FUNC-3D` adds one distinct evidence gate.
- Current behavior does not become a support claim. Until implementation lands,
  strict 2D refusal and explicit whole-frame hybrid fallback remain the honest
  adapter outcomes for mplot3d Figures.
- The shared semantic frame becomes a prerequisite for 3D, preventing a
  renderer-local parallel scene or ad hoc z bounds.
- Matching reference artifacts may constrain a compatibility renderer even when
  a depth buffer could produce a more physically accurate image.
- The four open decisions are now visible stop conditions rather than defaults
  guessed by an implementation worker.

## Verification plan

The documentation amendment is internally consistent only when the canonical
requirements/traceability checker, Markdown link/anchor checks, and repository
documentation checks pass.

Future `AT-FUNC-3D` implementation evidence must include:

- native and adapter authority/revision/stale-generation fixtures;
- canonical f64 x/y/z and bound preservation plus the accepted local-f32 error
  tests from O-20;
- explicit projection/view fixtures and the accepted default-case fixture from
  O-19;
- projected polyline and triangle geometry, clip, style, text, and axes facts;
- non-intersecting and artifact-exposing triangle/depth-order fixtures;
- the complete §15.1 manifest, mask, decoded-pixel, and operational outputs;
- strict no-write and exactly-once hybrid fallback diagnostics for unsupported
  content;
- packet validation, generation/lifetime, and no-public/no-wire/no-persistence
  static guards under the O-22 decision; and
- explicit scatter coverage or exclusion according to O-21.

No benchmark or platform-support result may be inferred from these correctness
fixtures.

## Rollback

If a native 3D eligibility slice regresses any parity fixture, remove that slice
from native eligibility and retain explicit whole-frame Agg fallback. Do not
widen tolerances, hide the diagnostic, or count fallback as closure. This
operational rollback leaves `LP-FUNC-025` pending; reversing the v1 product
requirement itself requires a new maintainer-approved requirements/ADR amendment.

## Residual risks

- The projection default and z-origin policy are user-visible and precision
  sensitive; incorrect choices can invalidate both semantics and fixtures.
- Agg painter ordering is not physically correct for all intersecting geometry,
  yet compatibility requires those artifacts on the parity path.
- The minimum line/surface scope can still expand unexpectedly if scatter3D is
  not classified before API design.
- Internal packet evolution can create stale-consumer ambiguity unless O-22 is
  resolved before field-shape changes.
- The pinned Matplotlib oracle needs explicit review when its version changes;
  “current Agg” is never a moving unrecorded target.

## Amendment 2026-09-07 — O-19 through O-22 decided

Decided by the architecture-authority from the accepted sources in References;
no new product scope was introduced, so no maintainer product decision beyond
the accepted envelope was required. Each item records the chosen option,
rejected alternatives, rationale, and resulting contract text. The O-19
through O-22 entries in the open-decision list now record these acceptances,
and the 3D fixture lane may proceed under the contracts below.

### O-19 — projection default: perspective default, both modes public

Decision: the public 3D view default is perspective projection, and both
perspective and orthographic projections are public in the first surface.
Default-case view facts mirror the pinned oracle reference defaults:
perspective projection under the reference focal-length rule with elevation 30
degrees, azimuth minus 60 degrees, and roll 0 degrees. Every fixture records
its explicit projection and view attributes; no fixture or implementation may
infer a default beyond this record.

Rationale: the pinned oracle reference (`Axes3D`, Matplotlib 3.11.1) defaults
to perspective (`proj_type='persp'`) with exactly these view defaults. Under
the artifacts-included parity gate, the default-case fixture must reproduce
the reference default output, so any other default would force the default
case to diverge from the reference default. Both modes are public because
mplot3d exposes exactly this pair, the oracle can pin both, and the second
mode costs one projection matrix in the backend-neutral semantic frame while
serving measurement-correct views.

Rejected: orthographic default (the default-case fixture would mismatch
reference default construction); perspective-only first surface (withholds an
oracle-pinnable mode with no implementation saving); placing the default in
per-render options (§2 above fixes projection/view attributes as
semantic-frame facts, not renderer-owned mutable state).

Contract text: the public 3D view carries a projection attribute with values
perspective and orthographic; the default is perspective with the
reference-mirroring view facts above; explicit-projection fixtures record
their values; the exact internal matrix remains renderer-local and is never
copied into the public contract.

### O-20 — z origin and precision: per-frame scene origin triple

Decision: z participates identically to x and y. One per-frame scene origin
triple (ox, oy, oz) is derived deterministically from the frame's canonical
f64 x/y/z bound pairs under the accepted 2D origin rule extended per-axis.
Subtraction happens in f64 before narrowing to local f32, and the single
origin is shared by all batches in the frame. The permitted error budget is
the §15.1 part-1 bound applied to projected 3D geometry (finite geometry
agrees to at most 0.25 device pixel before final sink quantization), with
explicit worst-error reporting on large-offset/short-span fixtures across all
three axes.

Rationale: excluding z, or giving it a separate regime, wastes most of the
f32 mantissa when |z − origin| is large — the exact failure the research note
flags. A per-frame scene origin keeps clipping, projection, and pick identity
independent of renderer-local conversion, as the fixed constraints require.

Rejected: z-excluded origin (mantissa waste); per-chunk/per-batch origins
(they break cross-batch draw-order comparison and pick identity);
camera- or view-relative origin (it conflates semantic view facts with numeric
conversion, so a view rotation would silently re-quantize all geometry);
projecting absolute f64 first and narrowing only projected 2D (leaves 3D
local-f32 packet geometry without an origin rule and splits conversion into
two regimes).

Contract text: canonical x/y/z and all three bound pairs stay f64 semantic
facts; the renderer boundary narrows (v − o) per axis from f64 to f32 after
subtracting the recorded per-frame origin triple; fixtures record the origin
triple, bound and projection invariants, and the worst observed error.

### O-21 — scatter3D alignment: with LP-FUNC-017, outside the v1 MUST

Decision: scatter3D is classified with LP-FUNC-017 (`SHOULD`, Phase 5,
`AT-FUNC-SCATTER`). It is not part of the LP-FUNC-025 v1 `MUST` minimum, and
its evidence must not double-count toward `AT-FUNC-3D`. Until the scatter lane
accepts 3D-marker semantics, scatter3D counts toward neither gate.

Rationale: LP-FUNC-025 enumerates "three-dimensional line and
triangulated-surface plots" — marker collections are neither, and §1 above
requires explicit classification before scatter3D can count anywhere. Marker
and collection semantics belong to the scatter lane (LP-FUNC-017) and the
collections lane (LP-MPL-023). Including scatter3D in the `MUST` by
interpretation would expand release-blocking scope without a maintainer
product decision; this classification keeps `MUST` scope exactly as accepted.

Rejected: include-in-`MUST` (scope expansion beyond the accepted requirement
text); a brand-new separate v1 row (inventing requirement rows is beyond
architecture authority — a maintainer may accept one later with its own
evidence gate).

Contract text: `AT-FUNC-3D` fixtures must not use scatter artists as closure
evidence; scatter3D evidence attributes to LP-FUNC-017/`AT-FUNC-SCATTER` only
after that lane's 3D-marker semantics are accepted; adapter treatment of 3D
scatter artists is unchanged (explicit unsupported / whole-frame fallback per
the accepted adapter contract) until then.

### O-22 — packet-schema versioning: generation-triple-only, no explicit version

Decision: the existing generation triple (`SceneRevision`, `WorkGeneration`,
`DeviceGeneration`) is sufficient for the internal 3D shape change. No
explicit packet-schema version is added to the packet identity family.

Rationale: the packet is compile-time-typed, process-local,
renderer-instance-scoped, and never serialized or persisted (ADR 0004 and §3/§5
above) — a shape change is a source change enforced by the type system and
whole-packet validation at build time, and there is no cross-version reader
for a version field to protect. Stale-packet rejection already exists with
distinct per-generation semantics. A version field would be a wire-lookalike
identity on a type whose non-wire status is a lifecycle/security boundary,
inviting exactly the misreading this record rejects and implying a
cross-version compatibility promise the project refuses (O-18).

Rejected: explicit internal schema version (dead check in-process;
wire-identity confusion risk; implied compatibility promise).

Contract text: 3D packet-shape evolution rides the existing triple;
producer/consumer mismatch is rejected by whole-packet validation plus
generation checks plus the existing static direction/type guards; the negative
serialization/persistence guards are extended to cover new 3D fields, and no
version field or compatibility matrix is introduced.

## References

- [Canonical v1 requirements and §15.1](../requirements/lumenplot-v1.0.md)
- [v1 traceability](../requirements/traceability-v1.0.md)
- [ADR 0002 — governing architecture](0002-gpu-native-engine-and-matplotlib-adapter.md)
- [ADR 0004 — internal RenderPacket lifecycle](0004-renderpacket-resource-lifecycle.md)
- [ADR 0007 — coordinate/color/text/export semantics](0007-coordinate-color-text-export.md)
- [ADR 0015 — public Matplotlib adapter contract](0015-phase3b-public-matplotlib-adapter-contract.md)
- [Open decisions O-19 through O-22](../architecture/open-decisions.md#o-19-3d-projection-default)
- [Historical 3D research note](../research/post-v1-3d-slice-notes.md)
