# API 0002: Errors, capability diagnostics, and fallback contract

- Status: **Accepted Phase-1 contract; implementation evidence pending**
- Date: 2026-08-21
- Decision owner: architecture-authority
- Recorded by: implementation-worker
- Scope: O-03 public operation errors, Phase-1 engine-to-facade mapping, capability/fallback diagnostics, internal work outcomes, and Rust/Python mapping
- Governing architecture: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](../adr/0002-gpu-native-engine-and-matplotlib-adapter.md)
- Governing Phase-1 record: [ADR 0010 — accepted Phase-1 native core and facade contract](../adr/0010-phase1-native-core-facade-contract.md)
- Open-decision record: [O-03 — Error and capability taxonomy](open-decisions.md#o-03-error-and-capability-taxonomy)

This record separates engine-owned failure, facade-owned public errors,
user-visible capability/fallback information, and scheduler outcomes. It does
not claim that error or fallback implementation exists. The Phase-1 facade uses
`PublicError`; the unpublished engine `SceneError` and `SceneErrorKind` never
cross the crate or FFI boundary.

## Requirement references

The taxonomy and boundary cover `LP-MPL-006` through `LP-MPL-010`,
`LP-QUAL-017` through `LP-QUAL-020`, `LP-PLAT-010`, `LP-EXPORT-009`,
`LP-SEC-004`, and `LP-SEC-008` in the [accepted requirements](../requirements/lumenplot-v1.0.md).
The exact Phase-1 engine mapping and public surface are recorded in
[ADR 0010](../adr/0010-phase1-native-core-facade-contract.md).

## Context

A strict unsupported operation is not the same event as a hybrid fallback, a
lost device, or a stale worker result. Treating all of them as one error type
would either hide degraded output or expose routine scheduler cancellation as a
user exception. The boundary must also prevent Rust panic payloads, internal
causes, generations, and storage details from becoming an FFI contract.

## Decision

### Three non-overlapping layers

1. **Public operation errors.** A failed public operation returns an error with a
   stable non-exhaustive machine code/category and non-contract human detail.
2. **Capability and result diagnostics.** A capability report, successful output,
   successful `show`, or explicit fallback result may carry structured
   diagnostics. A hybrid fallback is successful only when its diagnostic is
   present and describes what happened.
3. **Internal work outcomes.** Derived workers use
   `WorkOutcome::{Ready, Cancelled, StaleDropped}` plus counters. Cancellation
   and stale dropping normally do not become public exceptions.

The layers are not interchangeable: a diagnostic is not an operation error, and
an internal stale outcome is not a user-facing capability.

### Facade-owned stable codes and categories

The public `#[non_exhaustive] ErrorCode` variants and stable lowercase tokens
are:

| Variant | Stable code token |
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
tokens are:

| Variant | Stable category token |
| --- | --- |
| `Input` | `input` |
| `Capability` | `capability` |
| `Lifecycle` | `lifecycle` |
| `Host` | `host` |
| `Backend` | `backend` |
| `Resource` | `resource` |
| `Internal` | `internal` |

Category is derived from `ErrorCode` and is never stored independently. The
initial code/category ownership is:

| Code | Category | Meaning and boundary |
| --- | --- | --- |
| `InvalidInput` | `Input` | Caller shape, value, range, size, or other input validation fails. |
| `UnsupportedCapability` | `Capability` | The selected profile, backend, primitive, transport, or feature is unavailable. |
| `Closed` | `Lifecycle` | The addressed session, viewer, canvas, or handle is closed. |
| `InvalidState` | `Lifecycle` | The operation is invalid for the current semantic or lifecycle state. |
| `HostLoopMisuse` | `Host` | A host-pumped or native-owned loop boundary is used incorrectly. |
| `Reentrancy` | `Host` | An operation would violate the declared non-reentrant host/FFI boundary. |
| `BackendUnavailable` | `Backend` | Capability probing finds no usable selected backend or runtime. |
| `DeviceLost` | `Backend` | The runtime lost its device and reports loss/recovery state explicitly. |
| `RecoveryFailed` | `Backend` | Rebuild from retained CPU Scene/data did not recover the runtime. |
| `OutOfMemory` | `Resource` | Allocation or submission cannot continue. |
| `ResourceInvalid` | `Resource` | A packet, logical resource, or retained renderer resource fails validation or lifetime rules. |
| `Internal` | `Internal` | A contained unexpected failure whose detail is not a parsing contract. |

The human-readable display string is not stable API and must never be parsed in
place of the code/category. Additional structured fields may be attached as
diagnostics, but the code and category remain the machine contract.

### Phase-1 engine ownership and exhaustive mapping

The engine owns an unpublished exhaustive `SceneErrorKind` and opaque
`SceneError`. The Phase-1 engine kinds and their complete facade mapping are:

| Engine `SceneErrorKind` | Facade `ErrorCode` | Facade `ErrorCategory` |
| --- | --- | --- |
| `InvalidInput` | `InvalidInput` | `Input` |
| `TopologyViolation` | `InvalidInput` | `Input` |
| `NonFiniteCanonical` | `InvalidInput` | `Input` |
| `CapacityExceeded` | `InvalidInput` | `Input` |
| `UnsupportedCapability` | `UnsupportedCapability` | `Capability` |
| `InvalidState` | `InvalidState` | `Lifecycle` |
| `SeriesNotFound` | `ResourceInvalid` | `Resource` |
| `AllocationFailed` | `OutOfMemory` | `Resource` |
| `IdentityExhausted` | `Internal` | `Internal` |
| `RevisionExhausted` | `Internal` | `Internal` |
| `Internal` | `Internal` | `Internal` |

The facade owns `PublicError` with private fields and only the observations
`code()`, `category()`, and `message()`. `message()` is sanitized human text
and is not a stable token. `PublicError` implements `Display` and `Error`, but
its public `source()` is always `None`. Engine error types are neither aliased
nor re-exported. Internal causes and panic payloads are discarded at the
boundary.

All Phase-1 facade operations that can fail use `Result<T, PublicError>`,
including construction, view/scale mutation, series add/append, and commit.
Caller data errors return results rather than panic. A caught future FFI panic
maps only to `Internal`/`internal`; raw panic payloads never cross the facade or
FFI edge.

### Rust boundary and internal outcomes

The Rust facade and engine boundary follows `Result<T, PublicError>` for failed
public operations. `PublicError` exposes stable code/category observations and
non-contract detail without exposing RenderPacket fields, backend concrete
types, storage internals, scheduler generations, or panic payloads.

Internal work uses `WorkOutcome` and counters. `Cancelled` and `StaleDropped`
are expected control outcomes for bounded generation-cancellable work; they are
counted and dropped unless a higher-level public operation explicitly needs to
report that it could not produce a result. A stale result can never replace a
newer publication.

`DeviceLost` and `OutOfMemory` are never encoded as fallback reasons. Device
loss may trigger the declared rebuild path; out-of-memory stops submission and
returns an explicit failure according to the runtime contract.

### Python and FFI mapping boundary

The FFI edge is the only place that translates Rust panics and Rust public
results into Python-visible behavior:

- a Rust `PublicError` crosses with its stable code/category and human detail in
  the documented Python error/result envelope;
- Python-facing exceptions or helper results retain the stable code and
  category, but Python class names are not used by the Rust core as a dependency
  or error contract;
- successful outputs and `show` results may carry capability/fallback
  diagnostics in the same structured envelope;
- `WorkOutcome::Cancelled` and `StaleDropped` remain internal and do not become
  ordinary Python exceptions;
- a contained Rust panic maps to `internal` and never exposes its raw payload;
- no non-reentrant lock is held across a Python callback.

This is a one-way mapping boundary: the core does not import Python exception
classes, and Python/Matplotlib objects do not appear in core error types.

### Strict unsupported versus hybrid fallback

The selected profile owns the result policy:

- strict mode returns an `unsupported-capability` operation error for unknown
  custom Artists, unsupported effects, or other unsupported work;
- `hybrid-explicit` may succeed with a whole-frame or explicitly mapped
  fallback, but only with a structured diagnostic;
- mapped subtree fallback is valid only when generation, z-order, clipping, and
  compositing semantics are preserved;
- silent omission, unreported best-effort degradation, and a fallback that
  conceals a device/OOM failure are prohibited.

A fallback diagnostic records at least its reason, type, generation, output
format, and raster/vector scope. Generation is diagnostic context, not a
replacement for `SceneRevision` or semantic identity.

## Consequences

- Callers can branch on stable codes without parsing display text.
- Engine implementation details remain unpublished while the facade mapping is
  exhaustive and testable.
- Capability and fallback information remains observable even for a successful
  output.
- Runtime recovery and memory exhaustion cannot be misreported as an acceptable
  visual fallback.
- Scheduler cancellation and stale work remain implementation control flow
  rather than noisy user failures.
- The FFI surface contains the panic boundary and prevents internal Rust details
  from becoming Python API.

## Verification and evidence boundary

Required evidence includes the exhaustive Phase-1 mapping table, stable token
and category tests, private-field/source-redaction tests, Rust-to-Python failure
and panic fixtures, strict unsupported fixtures, hybrid diagnostics and golden
outputs, device-loss and OOM failures, stale/cancel counters, and checks that
fallback diagnostics never encode device loss or OOM. The current status is
pending implementation and failure evidence.

## Residual risks

- Future Python exception classes must preserve the stable code/category
  boundary and must not collapse explicit fallback into success without
  diagnostics.
- Diagnostic payload growth must not turn internal storage or RenderPacket
  schema into a public wire format.
- Host-loop and reentrancy errors depend on the lifecycle contract in [ADR
  0005](../adr/0005-runtime-viewer-host-loop.md).
- Allocation and identity/revision exhaustion need deterministic fault-injection
  evidence without making test machinery public.

## Related records

- [ADR index](../adr/README.md)
- [ADR 0010 — accepted Phase-1 native core and facade contract](../adr/0010-phase1-native-core-facade-contract.md)
- [Architecture overview](overview.md)
- [API 0001 — native Scene, view, and owned data](api-0001-native-scene-state.md)
- [API 0003 — Python, NumPy, and Matplotlib](api-0003-python-numpy-matplotlib.md)
- [ADR 0005 — runtime, viewer, and host loop](../adr/0005-runtime-viewer-host-loop.md)
- [O-03 open-decision entry](open-decisions.md#o-03-error-and-capability-taxonomy)
- [Accepted requirements: Matplotlib bridge](../requirements/lumenplot-v1.0.md#15-python-and-matplotlib-bridge)
