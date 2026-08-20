# ADR 0008: Portable GPU runtime and shader artifacts

- Status: **Accepted staged implementation baseline; evidence pending**
- Date: 2026-08-21
- Decision owner: architecture-authority
- Recorded by: implementation-worker
- Scope: O-15 portable wgpu/winit/raw-window-handle baseline, shader validation, ownership, device loss, and OOM
- Governing architecture: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md)
- Open-decision record: [O-15 — GPU runtime and shader artifact details](../architecture/open-decisions.md#o-15-gpu-runtime-and-shader-artifact-details)

The versions in this record are implementation lock choices for an evidence spike. They are not public support promises, MSRV declarations, or permission to update dependencies without the required gates.

## Requirement references

The portable runtime and artifact boundary covers `LP-PLAT-001`, `LP-PLAT-006`, `LP-PLAT-008` through `LP-PLAT-010`, `LP-QUAL-009` through `LP-QUAL-013`, and `LP-SEC-003` and `LP-SEC-005` in the [requirements](../requirements/lumenplot-v1.0.md#13-shader).

## Context

The portable renderer needs a concrete baseline while keeping the semantic core independent of wgpu, windows, and native GPU APIs. Shader artifacts must be reproducible and validated before runtime use; runtime compilation or download would undermine security and startup determinism. Device and resource ownership must remain with the main-thread session.

## Decision

### Portable baseline

The initial portable implementation baseline is:

- wgpu `29.0.4`;
- winit `0.30.13`;
- raw-window-handle `0.6.2`.

These are lockfile implementation choices only. They do not establish public dependency versions, supported hardware, MSRV, ABI, or release compatibility. wgpu 30 remains behind a same-workload correctness, present-behavior, and total-cost A/B evaluation; an upstream compatibility issue must be resolved or explicitly accounted for before that comparison can become a baseline change.

The runtime follows the main-thread and multi-surface ownership in [ADR 0005](0005-runtime-viewer-host-loop.md): one adapter/device/queue may serve multiple surfaces, while mixed-adapter and mixed-device windows are unsupported initially. Device generation and packet cache/loss behavior follow [ADR 0004](0004-renderpacket-resource-lifecycle.md).

### Static shader artifact

The initial portable shader artifact is reviewed static WGSL. Each artifact is accompanied by enough provenance to identify:

- source text and source revision;
- compiler/validation flags or validation mode;
- declared resource layout;
- artifact hash;
- validator manifest and result.

There is no Slang dependency initially, no Slang-RHI in the core renderer abstraction, no runtime source download, and no runtime compiler process. Untrusted shader source is never compiled or downloaded at runtime. A later common-source compiler remains a separately gated dependency decision.

### Ownership and loss rules

Workers may prepare owned upload bytes and bounded derived work. The main-thread session creates and owns the queue, staging resources, GPU resources, surface, and device lifecycle. Workers do not retain or move concrete wgpu/window objects across the ownership boundary.

A device loss invalidates backend resources and packets for the old `DeviceGeneration`; the runtime quiesces and rebuilds from retained CPU Scene/data. OOM is a terminal explicit failure for the affected submission/session path and is not handled by an unbounded retry loop. Surface loss, resize, timeout/occlusion, close, and recovery remain explicit lifecycle outcomes.

### Backend selection boundary

`Backend::Auto` uses capability probing and a static user override. It does not run a default startup microbenchmark. Diagnostic benchmark selection is separate. Portable implementation details do not place a concrete backend enum or wgpu type in the semantic facade.

## Alternatives and rationale

wgpu 29.0.4 is the accepted initial comparison point because it supplies a concrete portable baseline without making version choice a public contract. wgpu 30 is not adopted by novelty; it requires same-workload evidence. Static verified WGSL avoids a runtime compiler/download supply-chain boundary. Slang-RHI is deliberately kept out of core.

## Consequences

- The first renderer slice can be built against a known baseline while remaining evidence-gated.
- Shader provenance and validation are explicit build/CI artifacts.
- Main-thread ownership makes device/surface recovery testable and prevents worker access to concrete runtime objects.
- A later dependency update must pass the compatibility, correctness, security, license, MSRV, and benchmark gates in [ADR 0009](0009-version-publication-supply-chain.md).

## Verification and evidence boundary

Required evidence includes the portable build/runtime matrix, WGSL validator corpus, artifact hash/provenance checks, static runtime-download negative tests, ownership/thread tests, surface/device-loss recovery, OOM terminal behavior, and wgpu 29 versus later same-workload A/B results. No supported cell or dependency adoption result is claimed here.

## Residual risks

- Concrete wgpu behavior remains device, driver, and compositor dependent.
- Static WGSL may require later artifact generation for additional backend classes without changing the core boundary.
- The baseline versions can change only through the documented dependency and performance gates.

## Related records

- [ADR index](README.md)
- [Architecture overview](../architecture/overview.md)
- [ADR 0004 — RenderPacket resource lifecycle](0004-renderpacket-resource-lifecycle.md)
- [ADR 0005 — runtime, viewer, and host loop](0005-runtime-viewer-host-loop.md)
- [ADR 0006 — support and benchmark gates](0006-support-benchmark-native-gates.md)
- [ADR 0009 — version, publication, and supply chain](0009-version-publication-supply-chain.md)
- [O-15 open-decision entry](../architecture/open-decisions.md#o-15-gpu-runtime-and-shader-artifact-details)
- [Accepted requirements: platform and shader rules](../requirements/lumenplot-v1.0.md#12-window-and-event-layer)
