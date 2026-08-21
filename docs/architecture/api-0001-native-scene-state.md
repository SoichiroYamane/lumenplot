# API 0001: Native PlotScene, view, and owned-data contract

- Status: **Accepted Phase-1 contract; implementation evidence pending**
- Date: 2026-08-21
- Decision owner: architecture-authority
- Recorded by: implementation-worker
- Scope: O-02R/O-05 Phase-1 native PlotScene, view/scale, owned series input, transactions, snapshots, identities, revisions, and invalidation
- Governing architecture: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](../adr/0002-gpu-native-engine-and-matplotlib-adapter.md)
- Governing Phase-1 record: [ADR 0010 — accepted Phase-1 native core and facade contract](../adr/0010-phase1-native-core-facade-contract.md)
- Facade amendment: [ADR 0011 — Phase-1B facade namespace and observation traits](../adr/0011-phase1b-facade-namespace-observation-traits.md)
- Related error boundary: [API 0002 — errors, capabilities, and fallback](api-0002-errors-capabilities-fallback.md)
- Open-decision records: [O-02 — Public Rust and Python API surface](open-decisions.md#o-02-public-rust-and-python-api-surface), [O-05 — Scene ownership, mutation, revision, and history](open-decisions.md#o-05-scene-ownership-mutation-revision-and-history)

This record defines the exact Phase-1B facade observations and the Phase-1A
native semantic boundary. It does not define a backend, device, window, event
loop, session, viewer, close operation, renderer resource, Python binding, or
persistence format. It records an accepted contract before implementation; the
[traceability registry](../requirements/traceability-v1.0.md) remains the source
of implementation status. The Phase-1B namespace and trait details are narrowed
by [ADR 0011](../adr/0011-phase1b-facade-namespace-observation-traits.md).

## Requirement references

The Phase-1 state, data, LOD, and lifecycle boundary covers `LP-DATA-001`,
`LP-DATA-006`, `LP-DATA-007`, `LP-LOD-002` through `LP-LOD-006`,
`LP-MPL-005`, `LP-QUAL-014`, `LP-QUAL-017`, `LP-QUAL-018`, `LP-FUNC-003`,
`LP-FUNC-004`, `LP-UX-012`, and `LP-UX-013` in the [accepted
requirements](../requirements/lumenplot-v1.0.md). The exact Phase-1 contract is
recorded in [ADR 0010](../adr/0010-phase1-native-core-facade-contract.md).

## Decision

### Phase-1 authority and delivery boundary

Phase-1A is the synchronous native semantic kernel in `lumenplot-engine`.
Phase-1B is the minimum intentional facade in `lumenplot`, added only after
Phase-1A independently passes. The engine remains unpublished, its root modules
remain private, and it is never re-exported. The only future cross-crate seam is
the narrow hidden `bridge` wrapper described by ADR 0010; chunks, indexes,
caches, Scene internals, and component revisions remain private.

All fields of the facade types are private. The facade returns
`PublicError`, never engine `SceneError`; engine-to-facade error ownership and
mapping are defined in [API 0002](api-0002-errors-capabilities-fallback.md).

### Root namespace and visibility

Every intentional Phase-1B product type is exported directly at the `lumenplot`
crate root:

```rust
lumenplot::{
    PlotScene, SceneTransaction, SceneSnapshot, SceneRevision, SeriesId,
    CommitReceipt, AxisRange, AxisScale, Viewport, AxisScales, SeriesTopology,
    SeriesData, PublicError, ErrorCode, ErrorCategory,
}
```

There are no public Phase-1B submodules. The facade implementation modules are
private and named `error`, `view`, `series`, and `scene`; `lib.rs` exposes only
the exact root allowlist. `lumenplot_engine`, its `bridge`, engine errors,
chunks, segments, LOD/index/selection types, component revisions, and raw state
are never re-exported or named in public signatures.

### View and scale observations

The facade fixes one x/y pair for Phase-1:

- `AxisRange::new(min: f64, max: f64) -> Result<AxisRange, PublicError>`
  accepts only finite endpoints with `min < max`; `min()` and `max()` expose
  the values.
- `#[non_exhaustive] AxisScale` has `Linear` and `Log10`; Log10 is fixed base
  10.
- `Viewport::new(x: AxisRange, y: AxisRange) -> Viewport` constructs an
  immutable data-coordinate viewport. `Viewport::from_bounds(x_min, x_max,
  y_min, y_max) -> Result<Viewport, PublicError>` validates both ranges, and
  `x()`/`y()` expose them.
- `AxisScales::new(x: AxisScale, y: AxisScale) -> AxisScales` constructs the
  scale pair. `x()`/`y()` expose the scales and
  `validate(&Viewport) -> Result<(), PublicError>` rejects nonpositive Log10
  endpoints.

The values are scientific data coordinates, never pixels, DPI, or display
logical coordinates. Canonical finite series data is independent of scale.
Nonpositive coordinates become derived gaps under Log10 selection; canonical
data is not mutated or silently narrowed. Phase-1 M4 acceleration is linear
only, while Log10 uses an explicit full-resolution correctness path.

### Owned series input

The opaque immutable `SeriesData` constructors are:

```rust
SeriesData::from_owned_xy(
    topology: SeriesTopology,
    x: Vec<f64>,
    y: Vec<f64>,
) -> Result<SeriesData, PublicError>

SeriesData::from_owned_xy_segments(
    topology: SeriesTopology,
    x: Vec<f64>,
    y: Vec<f64>,
    valid_segments: Vec<std::ops::Range<usize>>,
) -> Result<SeriesData, PublicError>
```

`#[non_exhaustive] SeriesTopology` has `MonotonicX` and `ArbitraryXY`. The
first constructor treats every position as valid. The segmented constructor
requires equal-length arrays and sorted, strictly separated, nonempty,
in-bounds ranges. Covered values are finite; uncovered positions are explicit
gaps, and uncovered payload is ignored. Source identity is the original
zero-based array index, including gap slots.

Empty arrays and nonempty gap-only arrays are valid. MonotonicX is nondecreasing
across valid samples even across gaps, with duplicate x allowed. ArbitraryXY
preserves source order. The observations are `topology()`, `source_len()`,
`point_count()`, and `is_empty()`; no raw chunk, LOD, cache, or slice accessor
is public.

Scene add and append consume `SeriesData` and retain no borrowed input. Append
requires matching topology and preserves MonotonicX across the boundary. An
empty source-length append is a semantic no-op; a nonempty gap-only append
changes source identity and data revision. Checked input/allocation arithmetic
maps internal fallible allocation to `out-of-memory` through API 0002. Native
NaN-as-gap inference is not part of this API; the Python adapter creates
segments and rejects infinity.

### Exact Phase-1B facade surface

The opaque types are `PlotScene`, `SceneTransaction<'_>`, cloneable
`SceneSnapshot`, `SceneRevision`, `SeriesId`, `CommitReceipt`, `AxisRange`,
`AxisScale`, `Viewport`, `AxisScales`, `SeriesTopology`, and `SeriesData`, plus
`PublicError`, `ErrorCode`, and `ErrorCategory`. `SceneRevision` and `SeriesId`
implement exactly `Copy + Clone + Debug + Eq + PartialEq + Hash`; their private
numeric representation has no public numeric access and no serde/persistence
identity.

```rust
impl PlotScene {
    pub fn new(
        canonical_view: Viewport,
        scales: AxisScales,
    ) -> Result<Self, PublicError>;
    pub fn transaction(&mut self) -> SceneTransaction<'_>;
    pub fn snapshot(&self) -> SceneSnapshot;
    pub fn revision(&self) -> SceneRevision;
}

impl SceneTransaction<'_> {
    pub fn replace_canonical_view(&mut self, view: Viewport)
        -> Result<(), PublicError>;
    pub fn set_viewport(&mut self, view: Viewport)
        -> Result<(), PublicError>;
    pub fn set_axis_scales(&mut self, scales: AxisScales)
        -> Result<(), PublicError>;
    pub fn add_series(&mut self, data: SeriesData)
        -> Result<SeriesId, PublicError>;
    pub fn append_series(&mut self, id: SeriesId, data: SeriesData)
        -> Result<(), PublicError>;
    pub fn commit(self) -> Result<CommitReceipt, PublicError>;
    pub fn abort(self);
}

impl SceneSnapshot {
    pub fn revision(&self) -> SceneRevision;
    pub fn canonical_view(&self) -> Viewport;
    pub fn viewport(&self) -> Viewport;
    pub fn axis_scales(&self) -> AxisScales;
}

impl CommitReceipt {
    pub fn revision(&self) -> SceneRevision;
    pub fn changed(&self) -> bool;
}
```

The view, scale, and snapshot accessors are immutable observations; their
implementation may use value or immutable-reference details without exposing
storage. `SceneRevision` and `SeriesId` implement exactly
`Copy + Clone + Debug + Eq + PartialEq + Hash`; "comparable" means
equality-comparable and does not promise `Ord`, `PartialOrd`, or numeric access.
Their private process-local representation is not a persistence or wire
identity. `SceneSnapshot` is `Clone + Send + Sync` only, owns retained immutable
data, and cannot expose a mutable Scene borrow. No public performance trait
claim is made, and no additional public trait guarantee is made for the other
Phase-1B types in this slice.

All mutating operations that can fail return `Result`. `PlotScene::new` has no
implicit default; its initial canonical and current view are equal.
`replace_canonical_view` validates against the scales and sets canonical and
current view. `set_viewport` changes current view only. `set_axis_scales`
validates both views before an atomic change.

A changed commit increments `SceneRevision` exactly once; an effective no-op
changes neither revision nor component key. Finite numeric equality treats
`-0.0 == 0.0`. A validated add allocates a never-reused `SeriesId` before
staging; abort or later failed commit burns it, while validation failure before
allocation does not. Empty and gap-only additions still change state. Failed
operations preserve usable staged edits; failed commit, `Drop`, and `abort`
leave live state unchanged.

Internal component revisions are `data`, `view`, `style`, `font`, `layout`, and
`annotation`, initially zero. Phase-1 operations touch only data and view.
Component, Work, and Device generations remain private and distinct. View
history, gestures, Home, Previous, and Next are transient runtime/UI state and
are not part of `PlotScene` or `SceneSnapshot` in this slice; their v1 behavior
remains a later runtime/interaction implementation contract.

### Private native representation and selection

The engine uses private data/sample/topology/chunk, lod/summary/m4/arbitrary,
scene/ids/revision/state/transaction/snapshot, and error modules. Canonical
normalized values are finite f64 `Point` values with checked u64 source indexes
or structural gap spans. Immutable SoA chunks retain ordered segments, gap and
chunk-cut continuity metadata, topology, bounds, `DataEpoch`, and
`ChunkRevision`; no numeric sentinel, raw slice, or per-point source array is a
public contract.

A direct scanner is the selection oracle. The eager index uses at most 256 valid
samples per block and a binary factor-of-two summary tree for full blocks;
partial blocks are scanned. Linear MonotonicX bins are exact query-time
x-domain bins with deterministic interpolation, inclusive global endpoints,
deterministic collapsed-boundary merging, duplicate-x boundary ownership, and
per-segment first/last/min/max source-order selection. Full resolution is used
for visible points `<= 4 * B`; otherwise M4 is used. Log10 and ArbitraryXY paths
are correctness-first full-resolution paths as described in ADR 0010. These
selection rules are private implementation contracts and carry no benchmark
claim.

## Alternatives and rationale

The accepted boundary keeps engine error ownership separate from the facade,
uses scale-neutral viewports plus Scene-owned scales, and uses owned vector
input with explicit segments. It rejects a shared error crate or engine error
re-export, scale-carrying ranges, native NaN-gap inference, public raw data/LOD,
stride sampling, and an early full semantic frame. A single-writer transaction
and immutable snapshot avoid a second authority and make failed publication
atomic.

## Consequences

- The public surface is intentionally small and opaque while the native engine
  can evolve its chunks, indexes, caches, and component revisions.
- Facade callers branch on stable `PublicError` codes and cannot depend on
  unpublished `SceneError` details.
- Explicit source identity and gap segments preserve scientific topology and
  permit deterministic direct-versus-index testing.
- Snapshot ownership supports later derived work, with memory accounting left to
  implementation evidence.
- Phase-1 does not imply a renderer, runtime, Python bridge, persistence format,
  MSRV, package publication, or performance/support result.

## Verification and evidence boundary

Required implementation evidence includes normalization/topology/chunk/source
identity property tests; direct-versus-index LOD equivalence and bins/ties/
duplicates/gaps tests; ArbitraryXY culling oracles; transaction state-machine
and snapshot-sharing tests; identity-burn and component-revision tests;
exhaustive error mapping/token/privacy tests; and public API/forbidden-export
inventory tests. These are pending implementation evidence. The [traceability
registry](../requirements/traceability-v1.0.md) must continue to report the
product rows as `Not implemented`, `Not measured`, or `environment required`.

## Residual risks

- Public accessors and private representation must remain aligned without
  accidentally exposing raw chunks, LOD, or persistence identity.
- Log10 derived gaps, duplicate-x boundary ownership, and allocation/exhaustion
  paths need model and fault-injection evidence.
- Runtime view history and adapter synchronization must be implemented outside
  this synchronous core while preserving the authority rules in ADR 0002.

## Related records

- [ADR index](../adr/README.md)
- [ADR 0010 — accepted Phase-1 native core and facade contract](../adr/0010-phase1-native-core-facade-contract.md)
- [ADR 0011 — Phase-1B facade namespace and observation traits](../adr/0011-phase1b-facade-namespace-observation-traits.md)
- [Architecture overview](overview.md)
- [API 0002 — errors, capabilities, and fallback](api-0002-errors-capabilities-fallback.md)
- [API 0003 — Python, NumPy, and Matplotlib](api-0003-python-numpy-matplotlib.md)
- [API 0004 — annotations and accessibility](api-0004-annotations-accessibility.md)
- [O-02 open-decision entry](open-decisions.md#o-02-public-rust-and-python-api-surface)
- [O-05 open-decision entry](open-decisions.md#o-05-scene-ownership-mutation-revision-and-history)
- [Accepted requirements: data model](../requirements/lumenplot-v1.0.md#6-data-model)
- [Accepted requirements: Plot/UI state](../requirements/lumenplot-v1.0.md#21-plot-state-and-ui-state)
