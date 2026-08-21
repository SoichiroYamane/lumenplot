# ADR 0011: Phase-1B facade namespace and observation traits

- Status: **Accepted amendment; Phase-1B implementation and local contract evidence recorded**
- Date: 2026-08-21
- Decision owner: architecture-authority
- Recorded by: implementation-worker
- Scope: Phase-1B facade namespace, stable token observations, and exact public trait guarantees
- Amends: [ADR 0010 — accepted Phase-1 native core and facade contract](0010-phase1-native-core-facade-contract.md)
- Governing architecture: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md)
- Boundary record: [ADR 0003 — facade and crate dependency graph](0003-facade-and-crate-dag.md)
- API records: [API 0001 — native Scene state](../architecture/api-0001-native-scene-state.md), [API 0002 — errors, capabilities, and fallback](../architecture/api-0002-errors-capabilities-fallback.md)

This record is a narrow accepted amendment to ADR 0010. It removes remaining
ambiguity about the Phase-1B Rust facade's root namespace, stable token
observations, and public trait guarantees. It does not change the normative
requirements, the Phase-1A engine contract, the exact constructors or Scene
operation signatures, or the broader product implementation/evidence status in
the [traceability registry](../requirements/traceability-v1.0.md). Phase-1B
source and local contract evidence now exist; v1 product, platform, support,
and release evidence remains pending.

## Requirement references

This amendment clarifies the facade and dependency-direction boundaries for
`LP-PROD-010`, `LP-PROD-014`, `LP-MPL-001`, `LP-QUAL-025`, `LP-REL-002`, and the
Phase-1 state/error implementation boundary covered by [ADR 0010](0010-phase1-native-core-facade-contract.md).
The [accepted requirements](../requirements/lumenplot-v1.0.md) remain normative;
this record does not add a requirement or change a result.

## Context

ADR 0010 selected the minimum opaque Phase-1B facade and fixed its operation
signatures, engine-to-facade error mapping, and private representation boundary.
The API records use observations such as "comparable" and "stable token" but did
not yet state the exact root namespace, token methods, or complete trait
allowances. Those details must be explicit before facade implementation so that
an internal module, a numeric identity, or an incidental derived trait cannot
become an accidental public contract.

## Decision

### 1. Namespace and module boundary

Every intentional Phase-1B product type is exported directly at the `lumenplot`
crate root:

```rust
lumenplot::{
    PlotScene,
    SceneTransaction,
    SceneSnapshot,
    SceneRevision,
    SeriesId,
    CommitReceipt,
    AxisRange,
    AxisScale,
    Viewport,
    AxisScales,
    SeriesTopology,
    SeriesData,
    PublicError,
    ErrorCode,
    ErrorCategory,
}
```

There are no public Phase-1B submodules. Facade implementation modules are
private and are named `error`, `view`, `series`, and `scene`. `lib.rs` exposes
only the exact root allowlist above; it does not expose a module namespace as an
alternative path.

`lumenplot_engine`, its `bridge`, engine `SceneError` and `SceneErrorKind`,
chunks, segments, LOD/index/selection types, component revisions, and raw state
are never re-exported and never appear in public signatures. The hidden bridge
remains an implementation seam, not a product namespace or public API.

### 2. Stable token observations

`ErrorCode` and `ErrorCategory` each provide exactly one public stable token
accessor, the inherent method:

```rust
ErrorCode::as_str(&self) -> &'static str
ErrorCategory::as_str(&self) -> &'static str
```

These methods are the sole public stable token accessors. The exact code tokens
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

The exact category tokens are:

| Variant | Token |
| --- | --- |
| `Input` | `input` |
| `Capability` | `capability` |
| `Lifecycle` | `lifecycle` |
| `Host` | `host` |
| `Backend` | `backend` |
| `Resource` | `resource` |
| `Internal` | `internal` |

No parsing method, numeric representation or discriminant, `serde` support,
`FromStr` implementation, or persistence/wire identity is introduced by this
amendment. Human-readable messages remain non-contract text.

### 3. Exact public trait guarantees

The public trait guarantees for this slice are exactly:

- `SceneRevision` and `SeriesId` are `Copy + Clone + Debug + Eq + PartialEq + Hash`.
  Their private process-local representation has no public numeric access. The
  word "comparable" in ADR 0010 and API 0001 means equality-comparable; it does
  not promise `Ord` or `PartialOrd`.
- `SceneSnapshot` is `Clone + Send + Sync` only. It has no public mutable access
  and this record makes no performance trait claim.
- `PublicError` is `Debug + Display + std::error::Error`; its public
  `source()` is always `None`.
- No additional public trait guarantee is made for any other Phase-1B type in
  this slice. Implementation-internal properties must not be described as
  stable API.

The exact constructors, accessors, and Scene operation signatures remain those
in [ADR 0010](0010-phase1-native-core-facade-contract.md) and [API 0001](../architecture/api-0001-native-scene-state.md).

### 4. Error ownership and mapping

`ErrorCode`, `ErrorCategory`, `AxisScale`, and `SeriesTopology` remain
`#[non_exhaustive]`. Category is derived from the code and is never stored
independently. The twelve code/category meanings and the exhaustive eleven
engine-kind mappings remain exactly those recorded in [API 0002](../architecture/api-0002-errors-capabilities-fallback.md)
and [ADR 0010](0010-phase1-native-core-facade-contract.md).

`PublicError` has private fields and only the public observations `code()`,
`category()`, and `message()`. The message is sanitized, non-contract human
text. No engine source, internal cause, or panic payload crosses the facade or
FFI boundary. `PublicError::source()` is always `None`.

### 5. Unchanged boundaries

The following remain unchanged:

- the exact Phase-1 constructors and Scene operation signatures in ADR 0010 and
  API 0001;
- the one-way dependency direction and private engine boundary;
- the exhaustive engine-kind mapping and all twelve public code/category
  meanings;
- `publish = false` for all packages;
- the absence of an API stability, ABI, MSRV, platform, performance, renderer,
  runtime, export, Python, Matplotlib, persistence, wire-format, or package-
  publication claim.

## Alternatives and rationale

A public submodule or a broad facade re-export would make implementation layout
look like product API and would weaken the negative visibility boundary. Numeric
or parsed error identities would invite callers to depend on an unselected
representation or persistence format. Broad derived traits would similarly
freeze incidental ordering, formatting, or storage properties. The selected
root allowlist, two explicit token observations, and narrow trait guarantees
make the intended observations testable without expanding ownership or
persistence commitments.

## Consequences

- Facade callers have one documented import path for the intentional Phase-1B
  product types.
- Internal engine modules, bridge types, raw data, LOD/index state, component
  revisions, and numeric identities remain outside the public namespace.
- Callers can obtain exact code/category tokens without parsing display text,
  while token parsing and persistence identity remain explicitly out of scope.
- Trait-based bounds can rely only on the three listed guarantees; future
  guarantees require an explicit decision rather than an incidental derive.
- The accepted contract is more precise, and local implementation/API-inventory
  evidence now exists; broader product or compatibility claims still require
  their own evidence.

## Verification and evidence boundary

This amendment records the accepted boundary and the local Phase-1B
implementation/API-inventory evidence. The repository architecture checker,
mutation suite, locked Rust checks, and applicable documentation/publication
scans remain required for continued integration. None of this local evidence
closes a full product or compatibility claim, and the traceability registry
remains `Not implemented`, `Not measured`, or `environment required` as
applicable.

## Residual risks and follow-up

- Facade implementation may accidentally expose a module path or engine type;
  the root allowlist and negative visibility tests must remain synchronized.
- Adding a convenience parser, numeric repr, serialization derive, ordering
  trait, or extra observation would require a new architecture decision rather
  than an implementation shortcut.
- Runtime, renderer, export, Python/Matplotlib, persistence, package, platform,
  MSRV, and performance decisions remain governed by their existing records.

## Related records

- [ADR index](README.md)
- [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md)
- [ADR 0003 — facade and crate dependency graph](0003-facade-and-crate-dag.md)
- [ADR 0010 — accepted Phase-1 native core and facade contract](0010-phase1-native-core-facade-contract.md)
- [ADR 0012 — private line frame and deterministic PNG contract](0012-private-line-frame-and-png-contract.md)
- [API 0001 — native Scene, view, and owned data](../architecture/api-0001-native-scene-state.md)
- [API 0002 — errors, capabilities, and fallback](../architecture/api-0002-errors-capabilities-fallback.md)
- [Architecture overview](../architecture/overview.md)
- [Open decisions](../architecture/open-decisions.md)
- [Accepted v1 requirements](../requirements/lumenplot-v1.0.md)
- [Traceability registry](../requirements/traceability-v1.0.md)
