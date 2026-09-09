# ADR 0005: Runtime, viewer, and host-loop lifecycle

- Status: **Accepted contract**
- Date: 2026-08-21
- Decision owner: architecture-authority
- Recorded by: implementation-worker
- Scope: O-06 EngineSession/Viewer ownership, native and hosted loops, notebook transport, main-thread lifecycle, multi-surface behavior, close, recovery, and OOM
- Governing architecture: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md)
- Open-decision record: [O-06 — Window, viewer, host loop, and lifecycle semantics](../architecture/open-decisions.md#o-06-window-viewer-host-loop-and-lifecycle-semantics)

This ADR records lifecycle semantics before the complete runtime implementation. The repository now has a bounded backend-neutral lifecycle/input state model with local tests, but this record does not claim support for an operating system, window system, notebook transport, or GPU device.

## Requirement references

The runtime and viewer boundary covers `LP-FUNC-016`, `LP-PLAT-009`, `LP-PLAT-010`, `LP-MPL-013`, and `LP-QUAL-017` through `LP-QUAL-020` in the [requirements](../requirements/lumenplot-v1.0.md#12-window-and-event-layer).

## Context

Native viewing needs a main-thread-owned event loop and GPU lifecycle, while embedded Matplotlib hosts cannot always surrender their loop. A single generic `show` or `pump` interpretation would make close, reentrancy, notebook, and latency behavior ambiguous. Device and surface failures also need explicit outcomes rather than silent retries.

## Decision

### EngineSession and Viewer ownership

`EngineSession` is main-thread confined. It owns one adapter, one device, and one queue, and may own `0..N` surfaces/windows (zero to many). A `Viewer` is the product edge over the facade and runtime; it does not move backend/device ownership into `PlotScene`. The Scene/session binding is distinct from a frozen `SceneSnapshot`.

Initial multi-adapter or mixed-device windows are an explicit `UnsupportedCapability`. Multiple surfaces that share the session's one adapter/device/queue are within the accepted lifecycle model, subject to environment evidence.

The event loop, window, surface, GPU runtime, and device resources remain in the main-thread or declared host-loop owner. Workers may prepare bounded owned data and derived candidates but cannot own those concrete lifecycle objects.

### Loop modes and transports

| Context | Accepted loop/transport behavior |
| --- | --- |
| Standalone viewer | Native-owned blocking main-thread loop. The viewer owns the loop until an observable close. |
| Selected embedded/Matplotlib hosts | Explicit nonblocking host-pumped adapter. The host retains loop ownership and the adapter participates only at the declared safe boundary. |
| Notebook | Separate transport and capability. Notebook behavior is not silently treated as native viewer behavior or as the same latency profile. |
| Generic external `pump` | Private until platform evidence establishes a safe public contract. |

The loop mode is explicit. Qt, WebAgg, ipympl, and other transports are not implicitly included in native latency claims; the initial headless Matplotlib PNG profile has no GUI `show` behavior.

### Close and shutdown

Session and viewer close are idempotent and observable. A close request transitions the owner to a closed state and prevents new work/submission. `Drop` is best-effort only: it must not block across a foreign host boundary or invoke a foreign callback. Explicit close/shutdown owns the reliable lifecycle operation; core `PlotScene` itself has ordinary Rust ownership and no externally observable close.

No non-reentrant lock is held across a Python callback. Host-loop misuse, reentrancy, and closed-state failures use the public error boundary in [API 0002](../architecture/api-0002-errors-capabilities-fallback.md).

### Surface and device lifecycle

The runtime handles the following states explicitly:

- surface timeout or occlusion skips the affected submission without a busy loop;
- outdated surface configuration or resize reconfigures the surface before submission;
- surface loss recreates the surface through the main-thread owner;
- device loss quiesces submission, invalidates old backend resources, increments runtime `DeviceGeneration`, and rebuilds from the latest retained CPU Scene/data and valid semantic state;
- out-of-memory stops submission and returns an explicit terminal failure; it does not enter an unbounded automatic retry loop;
- a stale packet or work result is dropped according to the distinct Scene/Work/Device generation rules;
- close prevents recovery work from reopening or resurrecting a session.

Device loss does not change `SceneRevision`, semantic IDs, or view history. The packet/resource lease and fence behavior is specified by [ADR 0004](0004-renderpacket-resource-lifecycle.md).

### Multi-surface limits

One adapter/device/queue may serve multiple surfaces/windows. Mixed-adapter or mixed-device ownership is unsupported initially and must produce a structured capability result rather than implicit migration. Surface-specific loss and resize are handled per surface while session/device recovery remains session-owned.

## Alternatives and rationale

A single native-owned loop for every embedding would conflict with host and notebook ownership. A fully generic public pump API would expose lifecycle and reentrancy obligations before platform evidence. The hybrid boundary preserves explicit native-owned, host-pumped, and notebook transports without claiming equivalent semantics or latency.

## Consequences

- Standalone viewing can own a deterministic main-thread lifecycle.
- Embedded hosts retain control of their loop and receive explicit capability boundaries.
- Multiple surfaces are possible without permitting mixed-device ambiguity.
- Close, loss, and OOM are observable state transitions rather than silent retries.
- Runtime implementation must test foreign callback and host-loop reentrancy carefully.

## Verification and evidence boundary

Required evidence is a lifecycle matrix covering launch, repeated create/destroy, close/drop, resize, suspend/resume, occlusion/timeout, surface loss, device loss/rebuild, OOM, host-loop misuse, reentrancy, multiple surfaces, notebook transport, and mixed-device rejection. Platform results remain `environment required` until the target cells pass the complete matrix.

## Residual risks

- Host frameworks differ in loop and callback ownership; unsupported transports must remain explicit.
- Device recovery can fail for reasons that need a stable `RecoveryFailed` result rather than an implicit fallback.
- A multi-surface implementation may expose synchronization or fairness issues that require benchmark and lifecycle evidence.

## Related records

- [ADR index](README.md)
- [Architecture overview](../architecture/overview.md)
- [API 0001 — native Scene state](../architecture/api-0001-native-scene-state.md)
- [API 0002 — errors, capabilities, and fallback](../architecture/api-0002-errors-capabilities-fallback.md)
- [ADR 0004 — RenderPacket resource lifecycle](0004-renderpacket-resource-lifecycle.md)
- [ADR 0008 — portable GPU and shaders](0008-portable-gpu-and-shaders.md)
- [O-06 open-decision entry](../architecture/open-decisions.md#o-06-window-viewer-host-loop-and-lifecycle-semantics)
- [Accepted requirements: window lifecycle](../requirements/lumenplot-v1.0.md#12-window-and-event-layer)
