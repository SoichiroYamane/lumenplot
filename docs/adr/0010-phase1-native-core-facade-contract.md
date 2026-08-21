# ADR 0010: Accepted Phase-1 native core and facade contract

- Status: **Accepted contract; implementation evidence pending**
- Date: 2026-08-21
- Decision owner: architecture-authority
- Recorded by: implementation-worker
- Scope: Phase-1A native semantic kernel and Phase-1B minimal Rust facade
- Governing architecture: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md)
- Related boundary record: [ADR 0003 — facade and crate dependency graph](0003-facade-and-crate-dag.md)
- API records: [API 0001 — native Scene state](../architecture/api-0001-native-scene-state.md), [API 0002 — errors, capabilities, and fallback](../architecture/api-0002-errors-capabilities-fallback.md)
- Open-decision records: [O-01 — Exact facade and crate/module split](../architecture/open-decisions.md#o-01-exact-facade-and-cratemodule-split), [O-02 — Public Rust and Python API surface](../architecture/open-decisions.md#o-02-public-rust-and-python-api-surface), [O-03 — Error and capability taxonomy](../architecture/open-decisions.md#o-03-error-and-capability-taxonomy), [O-05 — Scene ownership, mutation, revision, and history](../architecture/open-decisions.md#o-05-scene-ownership-mutation-revision-and-history)

This record is the accepted authority for the Phase-1 native core and facade
slice. It resolves the candidate `SceneError`/`PublicError` and Scene/view/data
surface recorded in API 0001 and API 0002 for this phase. It does not change the
normative requirements, claim implementation evidence, or authorize package
publication.

## Requirement references

The contract is an implementation boundary for the accepted architecture and
covers the relevant portions of `LP-PROD-010`, `LP-PROD-014`, `LP-DATA-001`,
`LP-DATA-006`, `LP-DATA-007`, `LP-LOD-002` through `LP-LOD-006`,
`LP-FUNC-003`, `LP-FUNC-004`, `LP-MPL-005`, `LP-QUAL-014`, `LP-QUAL-017`,
`LP-QUAL-018`, `LP-SEC-001`, `LP-SEC-004`, `LP-SEC-008`, `LP-UX-012`,
`LP-UX-013`, `LP-REL-003`, and `LP-REL-004` in the [v1 requirements](../requirements/lumenplot-v1.0.md).
The [traceability registry](../requirements/traceability-v1.0.md) remains the
source of implementation and evidence status.

## Context

The Phase-0 workspace is a documentation and boundary scaffold. The accepted
architecture requires a native PlotScene authority, Rust-owned canonical data,
topology-aware LOD, immutable snapshots, and a one-way facade without exposing
internal renderer or persistence formats. Earlier API records intentionally left
several exact choices as candidates. In particular, API 0001 used `SceneError`
in candidate facade signatures while API 0002 described the facade result as
`Result<T, PublicError>`; the Phase-1 contract must make that ownership and
mapping explicit before implementation starts.

The first implementation slice must also avoid turning a convenient internal
representation into a public API. It therefore distinguishes the synchronous
semantic kernel from the minimal facade, fixes the public observations, and
keeps chunks, indexes, component revisions, and derived selection state private.

## Decision

### 1. Delivery stages and boundary

Phase-1 is delivered in two ordered stages:

1. **Phase-1A** implements the synchronous native semantic kernel in
   `lumenplot-engine`. It must independently pass its implementation and
   architecture gates before the facade slice is added.
2. **Phase-1B** adds the minimum intentional Rust facade in `lumenplot` after
   Phase-1A has independently passed and landed.

`lumenplot-engine` remains unpublished and is never re-exported. Its root
modules remain private. The only future cross-crate seam is a narrow
`#[doc(hidden)] pub mod bridge` wrapper API intended for the facade; raw chunks,
M4 indexes, Scene internals, caches, and component revisions never cross that
seam. The bridge is not a public product API or a persistence identity.

All other crates remain stubs in this phase. Phase-1 makes no renderer,
`RenderPacket`, runtime/window/GPU, export, text/layout, Python/NumPy/
Matplotlib, persistence/wire/serde, release, performance, or platform-support
claim. The implementation uses the standard library only: no new dependency,
feature, unsafe code, serialization identity, MSRV claim, or publication change
is authorized by this record.

### 2. Error ownership and exhaustive Phase-1 mapping

The engine owns an exhaustive unpublished `SceneErrorKind` and opaque
`SceneError`. The facade owns `PublicError`, `ErrorCode`, and `ErrorCategory`.
Engine error types are not re-exported or aliased. Every engine error produced by
this phase has an exhaustive facade mapping, and the mapping is part of the
required tests.

The Phase-1 engine kinds are:

- `InvalidInput`
- `UnsupportedCapability`
- `InvalidState`
- `SeriesNotFound`
- `TopologyViolation`
- `NonFiniteCanonical`
- `CapacityExceeded`
- `AllocationFailed`
- `IdentityExhausted`
- `RevisionExhausted`
- `Internal`

The mapping is:

| Engine kind | Public code | Public category |
| --- | --- | --- |
| `InvalidInput` | `InvalidInput` (`invalid-input`) | `Input` (`input`) |
| `TopologyViolation` | `InvalidInput` (`invalid-input`) | `Input` (`input`) |
| `NonFiniteCanonical` | `InvalidInput` (`invalid-input`) | `Input` (`input`) |
| `CapacityExceeded` | `InvalidInput` (`invalid-input`) | `Input` (`input`) |
| `UnsupportedCapability` | `UnsupportedCapability` (`unsupported-capability`) | `Capability` (`capability`) |
| `InvalidState` | `InvalidState` (`invalid-state`) | `Lifecycle` (`lifecycle`) |
| `SeriesNotFound` | `ResourceInvalid` (`resource-invalid`) | `Resource` (`resource`) |
| `AllocationFailed` | `OutOfMemory` (`out-of-memory`) | `Resource` (`resource`) |
| `IdentityExhausted` | `Internal` (`internal`) | `Internal` (`internal`) |
| `RevisionExhausted` | `Internal` (`internal`) | `Internal` (`internal`) |
| `Internal` | `Internal` (`internal`) | `Internal` (`internal`) |

The public `#[non_exhaustive] ErrorCode` variants and stable lowercase tokens
are:

| Variant | Token |
| --- | --- |
| `InvalidInput` | `invalid-input` |
| `UnsupportedCapability` | `unsupported-capability` |
| `Closed` | `closed` |
| `InvalidState` | `invalid-state` |
| `HostLoopMisuse` | `host-loop-misuse` |
| `Reentrancy` | `reentrancy` |
| `BackendUnavailable` | `backend-unavailable` |
| `DeviceLost` | `device-lost` |
| `RecoveryFailed` | `recovery-failed` |
| `OutOfMemory` | `out-of-memory` |
| `ResourceInvalid` | `resource-invalid` |
| `Internal` | `internal` |

The public `#[non_exhaustive] ErrorCategory` variants and stable lowercase
tokens are `Input`/`input`, `Capability`/`capability`,
`Lifecycle`/`lifecycle`, `Host`/`host`, `Backend`/`backend`,
`Resource`/`resource`, and `Internal`/`internal`. Category is derived from the
code; it is not independently stored and cannot become inconsistent.

`PublicError` has private fields and only the observations `code()`,
`category()`, and `message()`. Its message is sanitized human text, not a
stable token. It implements `Display` and `Error`; its public `source()` is
always `None`. Internal causes and panic payloads never cross the facade or FFI
boundary. A caught future FFI panic maps only to `internal`. Caller data errors
return results rather than panic.

### 3. Public viewport and scale contract

The facade exposes one fixed x/y pair in Phase-1. Viewport values are scientific
data coordinates, never pixels, DPI, or display-logical coordinates.

- `AxisRange` is opaque and immutable. `AxisRange::new(min: f64, max: f64)`
  returns `Result<AxisRange, PublicError>`; `min()` and `max()` expose the
  values. Both endpoints must be finite and `min < max`. Reversal, clamping,
  NaN, and infinity are rejected.
- `#[non_exhaustive] AxisScale` has `Linear` and `Log10`. `Log10` is fixed base
  10; no user-selected log base is introduced.
- `Viewport::new(x: AxisRange, y: AxisRange) -> Viewport` constructs an
  immutable viewport. `Viewport::from_bounds(x_min, x_max, y_min, y_max)`
  returns `Result<Viewport, PublicError>`. `x()` and `y()` expose the two axis
  ranges.
- `AxisScales::new(x: AxisScale, y: AxisScale) -> AxisScales` constructs the
  scale pair. `x()` and `y()` expose the scales, and
  `validate(&Viewport) -> Result<(), PublicError>` rejects a Log10 range whose
  endpoint is not strictly positive.
- Phase-1 has exactly one x/y pair. Public `AxisId` and multi-axis mutation are
  deferred rather than rejected as a v1 feature policy.
- `PlotScene::new(canonical_view: Viewport, scales: AxisScales)` returns
  `Result<Self, PublicError>` and has no implicit default. The initial canonical
  view and current viewport are equal.

Canonical finite series values are accepted independently of the selected
scale. Under Log10, nonpositive coordinates become derived out-of-domain gaps
when selecting data; canonical data is not mutated or silently narrowed. The
accelerated M4 path is linear-axis only. Log10 selection uses an explicit
internal full-resolution correctness path and makes no performance claim.

### 4. Public owned series input

`#[non_exhaustive] SeriesTopology` has `MonotonicX` and `ArbitraryXY`.
`SeriesData` is opaque and immutable. Its constructors are:

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

The first constructor treats every position as valid. The segmented
constructor requires equal-length arrays. `valid_segments` must be sorted,
strictly separated, nonempty, and in bounds; each range identifies a valid run
and uncovered positions are explicit gaps. Covered x/y values must be finite.
Uncovered payload is ignored and never enters canonical storage. Source identity
is the original zero-based array index, including uncovered gap slots.

Empty arrays are valid empty series. A nonempty array with no valid segment is
valid gap-only data. `MonotonicX` is nondecreasing across all valid samples,
including across gaps, and duplicate x is allowed. `ArbitraryXY` preserves
source order. The observations are `topology()`, `source_len()`,
`point_count()`, and `is_empty()`; no raw chunk, LOD, cache, or slice accessor
exists.

Adding or appending a series consumes `SeriesData`. Ownership transfers to the
Scene boundary, but internal zero-copy is not promised and no borrowed input is
retained. Append requires matching topology and preserves the MonotonicX rule
across the old/new boundary. An append with empty source length is a semantic
no-op. A nonempty gap-only append changes source identity and the data revision.
Input and allocation arithmetic is checked; internal fallible allocation maps to
`out-of-memory`. No arbitrary public size limit is promised.

The Python NaN-gap and infinity policy remains adapter-owned. The adapter creates
explicit valid segments, rejects infinity, and never makes raw NaN
interpretation a native public rule.

### 5. Exact minimal facade Scene API

The Phase-1B facade has these opaque types: `PlotScene`,
`SceneTransaction<'_>`, cloneable `SceneSnapshot`, `SceneRevision`, `SeriesId`,
`CommitReceipt`, `AxisRange`, `AxisScale`, `Viewport`, `AxisScales`,
`SeriesTopology`, `SeriesData`, and the public error types above. All fields are
private.

The operation surface is:

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

The accessor return forms are immutable observations; they do not expose mutable
Scene borrows or internal storage. `SceneRevision` and `SeriesId` are
comparable, hashable, and debuggable observations with private numeric
representation. They are not serde, persistence, wire, or cross-process
identities.

`SceneSnapshot` is `Clone + Send + Sync` and owns retained immutable data. Its
clones are O(1) immutable-state references in the implementation, but this is
not a public performance promise. No mutable Scene borrow escapes a snapshot.
There is no public remove, replace-series, readback iterator, axis ID,
style/layout/annotation, history, worker-generation, semantic-frame,
`RenderPacket`, backend, callback, serialization, or persistence API in this
phase.

### 6. Private data and chunk contract

The engine's private module direction is:

```text
data::{sample, topology, chunk}
lod::{summary, m4, arbitrary}
scene::{ids, revision, state, transaction, snapshot}
error
```

There is no full semantic-frame module in Phase-1. The normalized boundary uses
explicit `Point { source: SourceIndex, x, y }` values or structural `GapSpan`
values. Canonical point scalars are finite f64 and are never sorted, repaired,
or narrowed. Consecutive gaps merge. `SourceIndex` is a checked zero-based u64
logical input position that includes gap slots.

Sealed chunks are immutable SoA values with boxed f64 x/y valid columns,
ordered nonempty Segment descriptors, gap/source-span and chunk-cut continuity
metadata, topology, finite bounds, `DataEpoch`, and `ChunkRevision`. Numeric
sentinels are not used, and a per-point source array is not required when a
segment base/span derives identity.

The provisional internal target is 65,536 valid points per chunk and local
indexes are u32. These are benchmark-tunable implementation facts, not API or
performance promises. A new series or full replacement receives a never-reused
Scene-allocated `DataEpoch`. Append preserves the epoch and allocates
monotonically increasing `ChunkRevision` values starting at 1. Phase-1 exposes
no replacement or rechunk operation. Chunk cuts preserve connectivity;
`GapSpan` breaks it. A gap-only append may update series source length without
creating a point chunk.

### 7. M4 and LOD correctness contract

A direct query scanner is the model oracle and the small-data/full-resolution
path. The accelerated index is an eager immutable block-summary index per
chunk/segment. Each block contains at most 256 valid source-ordered samples and
a binary factor-of-two tree summarizes full blocks; partial blocks are scanned.
There is no full per-point tree, eviction, worker, or lazy mutable semantic cache
in Phase-1.

For linear MonotonicX selection, finite `[q0, q1]` queries and requested nonzero
`B` use exact query-time x-domain bins. Boundaries are deterministic safe
interpolation boundaries; non-final bins are `[b_j, b_{j+1})` and the final bin
includes `q1`. When `q0 == q1`, one effective bin is used. Adjacent f64
boundaries that collapse are merged deterministically and reported internally
as fewer effective bins, never replaced by stride sampling.

Global endpoints are inclusive. A duplicate-x run on a boundary belongs wholly
to the bin beginning at that boundary, and duplicate x samples remain distinct.
Each gap-delimited logical segment is processed independently and is never
connected to another segment. For every populated `(segment, bin)`, first and
last are selected by SourceIndex; minimum and maximum use finite y values with
the earliest SourceIndex winning ties. Candidates are sorted by SourceIndex and
deduplicate only identical sample references; distinct equal-x/equal-y samples
remain distinct.

Full resolution is selected when visible valid points are at most `4 * B`, using
checked arithmetic. Otherwise M4 is selected. Multiple gap segments may make the
output exceed `4 * B`; the paper theorem is not a renderer acceptance or
performance claim.

Log10 axes use a scale-aware explicit full-resolution path; nonpositive x/y
values split derived out-of-domain segments. `ArbitraryXY` performs only
correctness-preserving chunk/segment bounds culling and full-resolution ordered
output. It makes no simplification or picking performance claim. Index
build/query allocation, overflow, and range failures are explicit private
errors; there is no silent stride or fidelity fallback.

### 8. Scene ownership, revisions, and transient UI state

This is a synchronous first slice. `PlotScene` is single-writer through `&mut`;
there is no mutex, async worker queue, or callback in the core contract.
Immutable chunks and state use `Arc`, and snapshots are `Send + Sync` immutable
observations.

A new Scene revision is 0. A changed commit increments the revision exactly
once. IDs, `DataEpoch` values, and `ChunkRevision` values start at 1, are
checked, and are never reused. A validated add allocates `SeriesId` before
staging; an abort or later failed commit burns it. Validation failure before
allocation does not burn it.

Transactions use copy-on-write/delta staging over an immutable base. An
operation failure leaves prior staged edits usable. Commit consumes the
transaction and publishes atomically only after validation and allocation
succeed. A failed commit, `Drop`, or explicit abort leaves live state and
revision unchanged.

An effective no-op commit changes no revision or component key. Equality for
finite viewport and scale observations uses normal numeric equality, so
`-0.0 == 0.0`. Adding a series always changes state, including an empty or
gap-only series. Appending source length zero is a no-op; a nonempty gap-only
append changes state.

Internal component revisions are `data`, `view`, `style`, `font`, `layout`, and
`annotation`, initially 0. A changed commit increments each touched key once.
Phase-1 operations touch only `data` and `view`. Component, Work, and Device
generations remain private and distinct.

`replace_canonical_view` validates against the current scales and sets canonical
and current view; it is a view change when effective values differ.
`set_viewport` changes only the current viewport. `set_axis_scales` validates
both the canonical and current views before applying an atomic change.

View history, gesture/Home/Previous/Next state is transient UI/runtime state and
is excluded from `PlotScene` and `SceneSnapshot` in this phase. History is
therefore deferred to the runtime/interaction contract rather than introduced
as a persistence schema. A full SemanticFrame is also deferred. Phase-1 tests
SceneSnapshot and `LodSelection`; a `SemanticDataSeed` is not introduced unless
a later real consumer receives a separate architecture decision.

### 9. Guards and required evidence

Phase-1A updates the repository checker to allow private engine modules and only
the hidden bridge seam while continuing to reject facade exports, raw
module/re-export leakage, forbidden dependency directions and concrete types,
external dependencies, serde/persistence, unsafe code, and package/publication
drift. Phase-1B extends the checker with the exact facade allowlist and negative
checks for engine, raw data, chunk, LOD, and packet re-exports. Mutation tests
cover both permitted and forbidden cases.

Required future evidence includes:

- deterministic generated/model/property tests for normalization, topology,
  chunks, and source identity;
- direct-scanner versus index M4 equivalence, bins, ties, duplicates, gaps, and
  extreme finite-boundary tests;
- an ArbitraryXY culling oracle;
- transaction state-machine tests for no-op, abort, atomicity, identity burn,
  component revisions, and snapshot sharing;
- exhaustive error mapping, token, privacy, and panic-redaction tests; and
- public facade inventory and forbidden-export tests.

No benchmark or platform-support claim follows from these unit tests. Internal
chunk targets and selection complexity are unmeasured and non-public until a
separate benchmark record supplies real workload evidence.

## Rejected choices

- Alias or re-export engine `SceneError` as the public error, or add a new
  shared error crate.
- Use a scale-carrying range that duplicates Scene scale authority, or expose a
  raw-float viewport API.
- Infer gaps from native NaN values, or expose raw chunks, LOD indexes, caches,
  or slices publicly.
- Use engine glob/raw re-exports, or fan out immediately to renderer, runtime,
  or Python implementation.
- Use a fixed viewport/chunk-aligned M4 oracle, stride sampling, or a full
  per-point summary tree.
- Introduce a full SemanticFrame now, or put general command-log undo/history
  in `PlotScene`.

## Consequences

Positive consequences are a small public surface, an exhaustive and stable
facade error boundary, explicit topology/gap/source identity, deterministic
correctness paths, and immutable revisioned Scene ownership. The engine can be
implemented and tested without frontend, GPU, window, Python, serialization, or
publication dependencies.

The costs are additional mapping and validation tests, retained immutable data,
identity values that can burn on failed staging, and a Phase-1 full-resolution
Log10 path without a performance claim. Internal defaults, allocation behavior,
chunk size, local index width, and selection complexity may change without
altering this public contract.

## Verification and evidence boundary

This document records an accepted decision, not implementation completion. The
implementation stages must pass the repository architecture checker and
mutation suite, locked Rust format/check/test/clippy/metadata checks, applicable
Nix and security/documentation checks, and the contract-focused tests listed
above. The traceability registry must continue to report product requirements
as `Not implemented`, `Not measured`, or `environment required` until those
artifacts exist.

## Residual risks and follow-up

- Phase-1 implementation may expose accidental public items unless the
  Phase-1A/1B checker and API inventory are kept synchronized.
- The hidden bridge must remain narrow; any request to expose raw engine data,
  packet fields, or persistent identity requires a new architecture decision.
- Runtime-owned view history, full semantic-frame consumers, and renderer/
  backend lifecycle remain later contracts and must not be inferred from this
  synchronous slice.
- Allocation-failure and identity/revision exhaustion paths need deterministic
  test injection without making test machinery part of the public API.
- Log10 derived gaps and duplicate-x boundary ownership need model/property
  evidence before LOD claims are made.

## Related records

- [ADR index](README.md)
- [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md)
- [ADR 0003 — facade and crate dependency graph](0003-facade-and-crate-dag.md)
- [API 0001 — native Scene, view, and owned data](../architecture/api-0001-native-scene-state.md)
- [API 0002 — errors, capability diagnostics, and fallback](../architecture/api-0002-errors-capabilities-fallback.md)
- [Architecture overview](../architecture/overview.md)
- [Open decisions](../architecture/open-decisions.md)
- [Accepted v1 requirements](../requirements/lumenplot-v1.0.md)
- [Traceability registry](../requirements/traceability-v1.0.md)
