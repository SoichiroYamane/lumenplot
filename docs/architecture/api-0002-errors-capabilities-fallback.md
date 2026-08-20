# API 0002: Errors, capabilities, and fallback diagnostics

- Status: **Accepted contract**
- Date: 2026-08-21
- Decision owner: architecture-authority
- Recorded by: implementation-worker
- Scope: O-03 public operation errors, capability/fallback diagnostics, internal work outcomes, and Rust/Python mapping
- Governing architecture: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](../adr/0002-gpu-native-engine-and-matplotlib-adapter.md)
- Open-decision record: [O-03 — Error and capability taxonomy](open-decisions.md#o-03-error-and-capability-taxonomy)

This record separates user-visible failure, observable capability/fallback information, and scheduler outcomes. It does not claim that any error or fallback implementation exists.

## Requirement references

The taxonomy and fallback boundary covers `LP-MPL-006` through `LP-MPL-010`, `LP-QUAL-018` through `LP-QUAL-020`, `LP-PLAT-010`, and `LP-EXPORT-009` in the [requirements](../requirements/lumenplot-v1.0.md#15-python-and-matplotlib-bridge).

## Context

A strict unsupported operation is not the same event as a hybrid fallback, a lost device, or a stale worker result. Treating all of them as one error type would either hide a degraded output or expose routine scheduler cancellation as a user exception. The boundary must also prevent Rust panic payloads and internal generations from becoming an FFI contract.

## Decision

### Three non-overlapping layers

1. **Public operation errors.** A failed public operation returns an error carrying a stable non-exhaustive machine code/category and non-contract human detail.
2. **Capability and result diagnostics.** A capability report, successful output, successful `show`, or explicit fallback result may carry structured diagnostics. A hybrid fallback is a successful result only when its diagnostic is present and describes what happened.
3. **Internal work outcomes.** Derived workers use `WorkOutcome::{Ready, Cancelled, StaleDropped}` plus counters. Cancellation and stale dropping normally do not become public exceptions.

The layers are not interchangeable: a diagnostic is not a replacement for an operation error, and an internal stale outcome is not a user-facing capability.

### Stable public categories and codes

The following stable code tokens identify the public categories. The set is non-exhaustive so future categories can be added without making consumers exhaustive over the enum.

| Stable code | Category | Meaning and boundary |
| --- | --- | --- |
| `invalid-input` | `InvalidInput` | Shape, value, range, size, or other caller input fails validation. |
| `unsupported-capability` | `UnsupportedCapability` | The selected profile, backend, transport, primitive, or requested feature is not available. |
| `closed` | `Closed` | The addressed session, viewer, canvas, or handle is closed. |
| `invalid-state` | `InvalidState` | The operation is not valid for the current semantic or lifecycle state. |
| `host-loop-misuse` | `HostLoopMisuse` | A host-pumped/native-owned loop boundary was used incorrectly. |
| `reentrancy` | `Reentrancy` | An operation would violate the declared non-reentrant host/FFI boundary. |
| `backend-unavailable` | `BackendUnavailable` | Capability probing finds no usable selected backend or runtime. |
| `device-lost` | `DeviceLost` | The runtime lost the device and reports loss/recovery state explicitly. |
| `recovery-failed` | `RecoveryFailed` | Rebuild from retained CPU Scene/data did not recover the runtime. |
| `out-of-memory` | `OutOfMemory` | Allocation/submission cannot continue; this is an explicit terminal or operation failure. |
| `resource-invalid` | `ResourceInvalid` | A packet, logical resource, or renderer resource fails validation or lifetime rules. |
| `internal` | `Internal` | A contained unexpected failure; details are diagnostic and not a parsing contract. |

The human-readable display string is not stable API and must never be parsed in place of the code/category. Additional structured fields may be attached as diagnostics, but the category/code remains the machine contract.

### Rust boundary

The Rust facade and engine boundary returns a public operation result equivalent to `Result<T, PublicError>` for failed operations. `PublicError` exposes the stable category/code and non-contract detail without exposing RenderPacket fields, backend concrete types, storage internals, scheduler generations, or panic payloads.

Internal work uses `WorkOutcome` and counters. `Cancelled` and `StaleDropped` are expected control outcomes for bounded generation-cancellable work; they are counted and dropped unless a higher-level public operation explicitly needs to report that it could not produce a result. A stale result can never replace a newer publication.

`DeviceLost` and `OutOfMemory` are never encoded as fallback reasons. Device loss may trigger the declared rebuild path; out-of-memory stops submission and returns an explicit failure according to the runtime contract.

### Python/FFI mapping boundary

The FFI edge is the only place that translates Rust panics and Rust public results into Python-visible behavior:

- a Rust `PublicError` crosses with its stable code/category and human detail in the documented Python error/result envelope;
- Python-facing exceptions or helper results retain the stable code and category, but Python class names are not used by the Rust core as a dependency or an error contract;
- successful outputs and `show` results may carry capability/fallback diagnostics in the same structured envelope;
- `WorkOutcome::Cancelled` and `StaleDropped` remain internal and do not become ordinary Python exceptions;
- a contained Rust panic maps to `internal` and never exposes its raw payload;
- no non-reentrant lock is held across a Python callback.

This is a one-way mapping boundary: the core does not import Python exception classes, and Python/Matplotlib objects do not appear in core error types.

### Strict unsupported versus hybrid fallback

The profile owns the result policy:

- strict mode returns an `unsupported-capability` operation error for unknown custom Artists, unsupported effects, or other unsupported work;
- `hybrid-explicit` may succeed with a whole-frame or explicitly mapped fallback, but only with a structured diagnostic;
- mapped subtree fallback is valid only when generation, z-order, clipping, and compositing semantics are preserved;
- silent omission, unreported best-effort degradation, and a fallback that conceals a device/OOM failure are prohibited.

A fallback diagnostic records at least its reason, type, generation, output format, and raster/vector scope. The generation is diagnostic context, not a replacement for `SceneRevision` or semantic identity.

## Consequences

- Callers can branch on stable codes without parsing display text.
- Capability and fallback information remains observable even for a successful output.
- Runtime recovery and memory exhaustion cannot be misreported as an acceptable visual fallback.
- Scheduler cancellation and stale work remain implementation control flow rather than noisy user failures.
- The FFI surface contains the unsafe panic boundary and prevents internal Rust details from becoming Python API.

## Verification and evidence boundary

Required evidence includes a stable-code/error mapping table, Rust-to-Python failure and panic fixtures, strict unsupported fixtures, hybrid diagnostics/golden outputs, device-loss and OOM failures, stale/cancel counters, and checks that fallback diagnostics never encode device loss or OOM. The current status is pending implementation and failure evidence.

## Residual risks

- A future Python class hierarchy must preserve the stable code/category boundary and must not silently collapse explicit fallback into success without diagnostics.
- Diagnostic payload growth must not turn internal storage or RenderPacket schema into a public wire format.
- Host-loop and reentrancy errors depend on the lifecycle contract in [ADR 0005](../adr/0005-runtime-viewer-host-loop.md).

## Related records

- [ADR index](../adr/README.md)
- [Architecture overview](overview.md)
- [API 0001 — native Scene state](api-0001-native-scene-state.md)
- [API 0003 — Python, NumPy, and Matplotlib](api-0003-python-numpy-matplotlib.md)
- [ADR 0005 — runtime, viewer, and host loop](../adr/0005-runtime-viewer-host-loop.md)
- [O-03 open-decision entry](open-decisions.md#o-03-error-and-capability-taxonomy)
- [Accepted requirements: Matplotlib fallback](../requirements/lumenplot-v1.0.md#15-python-and-matplotlib-bridge)
