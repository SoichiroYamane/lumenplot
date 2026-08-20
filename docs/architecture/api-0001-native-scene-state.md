# API 0001: Native PlotScene state and revision contract

- Status: **Accepted contract; candidate Rust signatures recorded**
- Date: 2026-08-21
- Decision owner: architecture-authority
- Recorded by: implementation-worker
- Scope: O-02R/O-05 native PlotScene, transactions, snapshots, identities, revisions, invalidation, canonical view, and view history
- Governing architecture: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](../adr/0002-gpu-native-engine-and-matplotlib-adapter.md)
- Open-decision records: [O-02 — Public Rust and Python API surface](open-decisions.md#o-02-public-rust-and-python-api-surface), [O-05 — Scene ownership, mutation, revision, and history](open-decisions.md#o-05-scene-ownership-mutation-revision-and-history)

This record defines semantic native Scene state. It does not define a backend, device, window, event loop, session, viewer, or close operation. It records a contract before implementation; the [traceability registry](../requirements/traceability-v1.0.md) remains the source of implementation status.

## Requirement references

The state and lifecycle boundary covers `LP-QUAL-014` through `LP-QUAL-020`, `LP-MPL-004`, `LP-MPL-005`, `LP-FUNC-008`, `LP-UX-012`, and `LP-UX-013` in the [requirements](../requirements/lumenplot-v1.0.md#21-plot-state-and-ui-state).

## Context

Native mode needs one semantic authority, atomic single-writer updates, immutable observations, and enough revision identity to invalidate only the derived work that changed. A derived Matplotlib Scene is a revisioned cache under the distinct authority rules in ADR 0002; it is not a second native authority.

## Decision

### PlotScene boundary and ownership

`PlotScene` is semantic state only. It owns Plot State, canonical data references, scene identities, view state, and the semantic revision model. It has no backend selection, device or window worker, event loop, externally observable close state, or renderer resource ownership. Rust ownership and ordinary `Drop` are sufficient for the core Scene; `EngineSession`, `Viewer`, and FFI handles own close and shutdown outside this API.

Mutation is single-writer through an explicit `SceneTransaction<'_>` borrowing `&mut PlotScene`:

- a transaction observes one starting state and stages changes;
- explicit `commit` validates and publishes atomically;
- a no-op commit does not change `SceneRevision`;
- dropping an uncommitted transaction aborts it;
- publication returns only public revision and changed/no-op information;
- internal storage, `ChangeSet`, scheduler generations, and invalidation details are not exposed by the receipt.

`SceneSnapshot` is immutable and cloneable. A snapshot retains the owned sealed chunks needed by the state it represents. Workers receive a snapshot or other owned derived input and never obtain a mutable Scene borrow.

### Candidate Rust signatures

The following signatures record the accepted shape while leaving representation and ordinary invalid-input details to implementation:

```rust
pub struct PlotScene { /* semantic state; no backend or close */ }
pub struct SceneTransaction<'scene> { /* single-writer staged update */ }
pub struct SceneSnapshot { /* immutable, cloneable, owned sealed chunks */ }

impl PlotScene {
    pub fn transaction(&mut self) -> SceneTransaction<'_>;
    pub fn snapshot(&self) -> SceneSnapshot;
    pub fn revision(&self) -> SceneRevision;
}

impl SceneTransaction<'_> {
    pub fn replace_canonical_view(&mut self, view: Viewport)
        -> Result<(), SceneError>;
    pub fn commit(self) -> Result<CommitReceipt, SceneError>;
    pub fn abort(self);
}

pub struct CommitReceipt {
    pub revision: SceneRevision,
    pub changed: bool,
}
```

`Drop` on `SceneTransaction` has the same effect as `abort` when `commit` has not been called. The exact public field visibility of the opaque identity and view types follows the same no-storage-leak rule; the signatures do not imply serialization or backend access.

### Semantic identities and generations

The public semantic identity types are opaque monotonic `u64` values:

- `SceneId`
- `SeriesId`
- `AxisId`
- `AnnotationId`

They are scoped to one Scene lifetime and are never reused within that lifetime. A generation is not part of semantic identity, and none of these identities is serialized. `AnnotationId` and annotation behavior are further specified in [API 0004](api-0004-annotations-accessibility.md).

The public publication observation is `SceneRevision`. Separate internal dependency and scheduler values are not semantic identities:

| Value | Role | Public Scene identity? |
| --- | --- | --- |
| `SceneRevision` | Published semantic Scene revision | Public observation only |
| Component revisions | Distinguish data, view, style, font, layout, and annotation dependencies | Internal invalidation inputs |
| `WorkGeneration` | Derived-work scheduler token used for cancellation and stale-result rejection | Internal |
| `DeviceGeneration` | Runtime resource generation used after device loss | Runtime-only; never Scene identity |

A device loss therefore never changes `SceneRevision`. A stale derived result cannot replace a newer publication even when its Scene data remains otherwise valid.

### Selective invalidation

Every mutation identifies the semantic dependency keys it affects. Data, view, style, font, layout, and annotation dependencies have distinct internal component revisions. Derived LOD, layout, semantic-frame, and packet work is invalidated only when its dependency key is affected, but every result still carries the source `SceneRevision` and `WorkGeneration` and is rejected if stale.

The selective invalidation model is an optimization and correctness boundary, not a new public storage schema. A public `CommitReceipt` reports only the resulting `SceneRevision` and whether the commit changed state.

### Canonical view and current viewport

The canonical view is a stored baseline, not an autoscale calculation:

- ordinary pan and zoom change the current viewport only;
- `replace_canonical_view` is an explicit transaction operation that replaces the baseline and clears view history;
- Home restores the stored canonical view and never implicitly autoscale;
- a view change that does not alter the effective viewport is a no-op for revision purposes where the transaction otherwise has no change.

### View-only history

Version 1 history contains view history only:

- previous, next, and Home operate on view entries;
- gesture-end coalescing prevents one drag or wheel gesture from becoming an unbounded sequence of entries;
- a new view after moving backward truncates the forward tail;
- replacing the canonical view clears the history;
- annotation, style, visibility, and other Plot State commits increment `SceneRevision` but are not general Previous/Next undo/redo entries.

The distinction prevents transient UI history and non-view semantic changes from becoming an implicit persistence or general undo model.

### Plot State and UI State

Plot State includes axis ranges and current Plot State viewport, series visibility and styles, grid and labels, Legend placement/style, and annotations. It is the state selected for an ordinary export snapshot. UI State includes hover, selection/focus highlight, toolbar and context surfaces, pointer/crosshair, status surfaces, and drag indicators; it is separate and excluded from ordinary exports.

Native mode gives `PlotScene` authority. Adapter mode gives the Matplotlib Figure/Artist graph authority and uses a revisioned derived Scene snapshot/cache. A live session binding and a frozen snapshot are distinct concepts.

## Alternatives and rationale

A mutable shared Scene or a second long-lived authority beside Figure/Artist would permit races between snapshots, view history, and exports. The single-writer transaction and immutable snapshot contract avoids that ambiguity while keeping the adapter's derived state disposable. General undo/redo was not selected because the accepted v1 history scope is view-only.

## Consequences

- Semantic IDs remain stable across Scene revisions while runtime generations can be replaced independently.
- Derived work can be cancelled or stale-dropped without changing native semantic state.
- Snapshot retention makes asynchronous work safe but requires owned sealed chunks and memory accounting.
- The core API remains independent from concrete runtime and backend objects.
- Public receipts remain small and do not freeze internal change-set or generation representation.

## Verification and evidence boundary

Implementation must test transaction atomicity, Drop-abort behavior, no-op revision stability, snapshot immutability/cloneability, identity non-reuse, component-key invalidation, stale publication rejection, canonical-view reset, gesture coalescing, forward-tail truncation, and Plot/UI State export separation. These are pending implementation evidence; this document does not claim any test has passed.

## Residual risks

- Exact storage and component-key representation may affect memory and scheduling without changing this public semantic contract.
- Adapter synchronization must preserve Figure/Artist authority and cannot reuse native Scene authority rules without an explicit bridge boundary.
- A future persistent Scene format is excluded; identity and revision rules here must not be mistaken for serialization commitments.

## Related records

- [ADR index](../adr/README.md)
- [Architecture overview](overview.md)
- [API 0002 — errors, capabilities, and fallback](api-0002-errors-capabilities-fallback.md)
- [API 0004 — annotations and accessibility](api-0004-annotations-accessibility.md)
- [O-02 open-decision entry](open-decisions.md#o-02-public-rust-and-python-api-surface)
- [O-05 open-decision entry](open-decisions.md#o-05-scene-ownership-mutation-revision-and-history)
- [Accepted requirements: Plot/UI state](../requirements/lumenplot-v1.0.md#21-plot-state-and-ui-state)
