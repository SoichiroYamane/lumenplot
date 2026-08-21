# LumenPlot architecture overview

## Status

This is the public high-level architecture companion to the accepted pre-alpha requirements and ADR 0002. Publication precedes implementation. No layer, platform, benchmark, API, or compatibility cell described here is reported as complete.

## Product modes

LumenPlot has two explicit modes with different state authority:

```text
Native mode
  PlotScene (authoritative)
       │ immutable revisioned snapshot
       ▼
  shared semantic/layout frame
       │ validated internal packet
       ▼
  portable renderer or measured native renderer
       ▼
  native viewer/window or headless export

Matplotlib mode
  Matplotlib Figure/Artist (authoritative)
       │ safe-boundary observation
       ▼
  revisioned derived LumenPlot Scene snapshot/cache
       ▼
  strict-common-2d | hybrid-explicit | accelerated-native
       ▼
  engine render/export or explicit fallback/error
```

The adapter does not reverse the dependency direction or create a second authoritative Figure model. Standard Matplotlib traversal and native retained interaction are separate performance profiles.

## Public high-level layers

[ADR 0003 — facade and crate DAG](../adr/0003-facade-and-crate-dag.md) records the accepted Option-C facade/crate split, [ADR 0010 — Phase-1 native core and facade contract](../adr/0010-phase1-native-core-facade-contract.md) records the exact first native core/facade slice, and [ADR 0011 — Phase-1B facade namespace and observation traits](../adr/0011-phase1b-facade-namespace-observation-traits.md) narrows its root namespace and observation guarantees. Workspace implementation, visibility/re-export, `publish = false`, and dependency-direction evidence remain pending. The conceptual layers and their allowed direction are fixed:

1. **Frontend and product edges** — native viewer, standalone launch surface, future language frontends, and the Matplotlib adapter.
2. **Engine facade boundary** — the public ownership, view/scale, owned-data, transaction, snapshot, error, root-namespace, token, and trait surface selected for Phase-1B in ADR 0010 as amended by ADR 0011. Runtime, renderer, Python, and persistence surfaces remain later decisions.
3. **Core scene and semantic model** — PlotScene, Plot State, UI State boundary, axes, series, Legend, annotations, styles, and backend-neutral semantic meaning.
4. **Data and LOD** — canonical f64 values, immutable sealed chunks, MonotonicX hierarchy, ArbitraryXY topology/culling model, and revision/generation metadata.
5. **Shared text and layout** — shaping, glyph IDs and positions, font identity, Legend and axis layout, and output-neutral resolved geometry.
6. **Semantic frame** — resolved backend-neutral frame consumed by interactive and vector-aware output paths.
7. **Internal RenderPacket** — immutable, validated, process-local renderer input with opaque generational logical IDs. It is not public, serializable, persistent, or wire data.
8. **Renderer implementations** — portable wgpu path and evidence-gated native prototypes.
9. **Window, surface, and GPU runtime** — main-thread-constrained lifecycle, device/surface recovery, present behavior, and platform capability handling.

## Allowed dependency direction

```text
frontend/adapter → engine facade → core/data/LOD/text/layout
                               → semantic frame → internal RenderPacket
                                                        → renderer/runtime
```

Allowed edges:

- Frontends may depend on the engine facade.
- The Matplotlib adapter may depend on Python, Matplotlib, NumPy, and the engine bridge.
- Renderer implementations may depend on the packet and semantic frame.
- Window/GPU runtime code may depend on platform and GPU APIs.

Forbidden edges:

- Core, data, LOD, text/layout, and render-api layers do not depend on Matplotlib or Python.
- Core does not retain wgpu, window, surface, device, or native API concrete types.
- Lower layers do not call frontend callbacks as part of their ownership model.
- LumenPlot does not depend on gsplot or another frontend.
- Renderer code does not become a second PlotScene authority.

## State and revision flow

Native updates are single-writer transactions. Publication creates an immutable revision. LOD/layout/packet workers receive a generation token and can be cancelled or dropped when stale. Only results matching the current generation may be consumed.

The Phase-1 native slice is deliberately synchronous: Phase-1A owns the
semantic kernel in `lumenplot-engine`, and Phase-1B adds only the opaque
`PlotScene` facade after the kernel passes independently. ADR 0011 requires the
intentional Phase-1B types to be exported directly at the `lumenplot` crate root
with no public Phase-1B submodules; facade implementation modules remain
private. It also limits stable token access to `ErrorCode::as_str` and
`ErrorCategory::as_str`, guarantees only the documented equality/hash/debug
traits for `SceneRevision` and `SeriesId`, `Clone + Send + Sync` for
`SceneSnapshot`, and `Debug + Display + std::error::Error` for `PublicError`.
`SceneSnapshot` owns immutable retained data but carries no public performance
trait claim. No worker, callback, runtime, renderer, or full semantic-frame API
is part of this slice. Phase-1 view history remains transient runtime/UI state
rather than Scene persistence.

Plot State includes axis ranges, current Plot State viewport, series visibility, line styles, labels, annotations, Legend placement/style, and grid state. UI State includes hover, focus highlight, selection highlight, toolbar, context menus, pointer/crosshair, status surfaces, and drag indicators. Export snapshots use Plot State and exclude UI State.

Matplotlib mode treats Figure/Artist as the authority. A derived Scene snapshot/cache is associated with the observed revision and is safe to discard and rebuild. Native ViewState synchronization is coalesced at an explicit boundary and cannot require Python work for each native frame.

## Data and LOD flow

```text
input f64 / bounded NumPy ingestion view
                 │
                 ▼
        Rust-owned sealed chunks
                 │
        ┌────────┴────────┐
        ▼                 ▼
 MonotonicX          ArbitraryXY
 dyadic M4/extrema   topology/order/bounds/culling
        │                 │
        └────────┬────────┘
                 ▼
   origin-relative local f32 for GPU
                 │
                 ▼
       shared semantic/layout frame
```

Canonical scientific coordinates remain f64. Long-lived async/native state owns immutable sealed chunks. GPU local f32 is derived relative to a chunk or viewport origin; an absolute f64-to-f32 cast is not a valid drawing path. MonotonicX is the native v1 performance lane. ArbitraryXY topology, order, bounds, and culling correctness remain in the v1 model; advanced simplification and picking performance are Phase 5.

## Semantic frame and RenderPacket

The semantic/layout frame is shared by interactive rendering and export. It retains vector-aware meaning, resolved styles, clipping, annotations, Legend geometry, glyph positions, and explicit fallback facts. A renderer must not independently remeasure text or Legend geometry.

The internal RenderPacket is a validated process-local projection of that frame for a renderer instance. It is immutable and tied to a Scene revision/generation. It carries opaque logical resource identifiers rather than platform objects. [ADR 0004 — RenderPacket resource lifecycle](../adr/0004-renderpacket-resource-lifecycle.md) records the accepted internal packet/resource-lifecycle contract; implementation, validation, cache/lease/fence-retirement, and device-loss evidence remain pending.

## Matplotlib adapter boundary

The adapter distribution/module boundary is fixed as:

- distribution: `lumenplot-mpl`;
- import package: `lumenplot_mpl`;
- backend module: `lumenplot_mpl.backend`;
- module loader: `module://lumenplot_mpl.backend`;
- backend entry-point name: `lumenplot`.

The three profiles are:

| Profile | Authority | Fallback | Native performance claim |
| --- | --- | --- | --- |
| `strict-common-2d` | Figure/Artist | explicit unsupported result | standard adapter metrics only |
| `hybrid-explicit` | Figure/Artist | default whole-frame fallback for unknown public-boundary cases | fallback cost reported separately |
| `accelerated-native` | LumenPlot-aware input after a sealed snapshot | mapped capabilities only | eligible for native MonotonicX and hot-path gates |

Unknown custom Artists/effects never disappear silently. Subtree fallback is reserved for explicitly mapped adapters that preserve generation, z-order, clipping, and compositing. Supported vector primitives remain vector-aware in PDF/SVG; a declared raster fallback records its reason, generation, format, and scope.

## Text and output flow

```text
one shaping/layout pass
        │
        ├── interactive renderer
        ├── PNG semantic raster path
        ├── PDF vector/text path
        └── SVG vector path (v1 SHOULD, non-blocking)
```

PNG and PDF are v1 release outputs. SVG is a non-blocking v1 SHOULD. PDF text uses a subset plus ToUnicode when available or a deterministic outline fallback. Raster-only PDF is not an accepted final path for supported vector semantics.

## Runtime and lifecycle

The event loop, window, surface, and GPU runtime are main-thread confined or owned by a declared host-loop equivalent. Workers may build bounded derived data but cannot own those concrete runtime objects. Resize, suspend/resume, surface loss, device loss, OOM, close/drop, and reentrancy need environment-backed lifecycle evidence.

`Backend::Auto` uses capability probing plus static override and does not run a default startup microbenchmark. Portable wgpu and window-handle references are candidate baselines, not fixed dependency requirements. Native Metal, D3D12/DXGI, and Vulkan paths are Phase 4 prototypes adopted only after measured benefit.

## Accepted follow-up contract records

O-01 through O-17 are now accepted contracts recorded in the linked ADR/API documents below. [ADR 0010](../adr/0010-phase1-native-core-facade-contract.md) resolves the Phase-1 native core/facade boundary and the API 0001/API 0002 candidates, and [ADR 0011](../adr/0011-phase1b-facade-namespace-observation-traits.md) narrows the Phase-1B namespace, token, and trait observations, without claiming implementation. Their implementation, compatibility, platform, and benchmark evidence remains pending; these records do not change the `Not implemented`, `Not measured`, or `environment required` statuses in the [traceability registry](../requirements/traceability-v1.0.md).

| Decision | Accepted record | Evidence boundary |
| --- | --- | --- |
| O-01 | [ADR 0003 — facade and crate DAG](../adr/0003-facade-and-crate-dag.md) + [ADR 0010 — Phase-1 native core/facade](../adr/0010-phase1-native-core-facade-contract.md) + [ADR 0011 — Phase-1B namespace and observations](../adr/0011-phase1b-facade-namespace-observation-traits.md) | Static DAG, Phase-1 visibility, root allowlist, and publication guards pending |
| O-02R/O-05 | [API 0001 — native Scene, view, and owned data](api-0001-native-scene-state.md) + [ADR 0010 — Phase-1 native core/facade](../adr/0010-phase1-native-core-facade-contract.md) + [ADR 0011 — Phase-1B namespace and observations](../adr/0011-phase1b-facade-namespace-observation-traits.md) | Exact Phase-1 surface and trait observations recorded; Scene, revision, invalidation, and snapshot tests pending |
| O-03 | [API 0002 — errors, capabilities, and fallback](api-0002-errors-capabilities-fallback.md) + [ADR 0010 — Phase-1 native core/facade](../adr/0010-phase1-native-core-facade-contract.md) + [ADR 0011 — Phase-1B namespace and observations](../adr/0011-phase1b-facade-namespace-observation-traits.md) | Exact Phase-1 mapping and token observations recorded; error and fallback fixtures pending |
| O-04 | [ADR 0004 — RenderPacket resource lifecycle](../adr/0004-renderpacket-resource-lifecycle.md) | Packet and resource-lifetime tests pending |
| O-06 | [ADR 0005 — runtime, viewer, and host loop](../adr/0005-runtime-viewer-host-loop.md) | Lifecycle and platform matrix pending |
| O-07/O-08/O-16 | [ADR 0006 — support, benchmark, and native gates](../adr/0006-support-benchmark-native-gates.md) | All target cells and five-block measurements remain environment required |
| O-02P/O-09/O-10 | [API 0003 — Python, NumPy, and Matplotlib](api-0003-python-numpy-matplotlib.md) | Wheel, import, and headless PNG evidence pending |
| O-11/O-12 | [ADR 0007 — coordinate, color, text, and export](../adr/0007-coordinate-color-text-export.md) | Transform, color, font, and output evidence pending |
| O-13/O-14 | [API 0004 — annotations and accessibility](api-0004-annotations-accessibility.md) | Interaction, accessibility, and viewer evidence pending |
| O-15 | [ADR 0008 — portable GPU and shaders](../adr/0008-portable-gpu-and-shaders.md) | Portable runtime, shader, and loss/OOM evidence pending |
| O-17/O-18 | [ADR 0009 — version, publication, and supply chain](../adr/0009-version-publication-supply-chain.md) | Policy is accepted; O-18 remains Deferred/Closed and only negative guards are allowed |

## Publication-before-implementation boundary

The requirements, traceability registry, and ADRs define the contract and evidence gates. They do not report:

- a completed Rust engine or viewer;
- a released Python wheel or stable public API;
- a supported OS/GPU/driver matrix;
- a measured 10M or 100M result;
- a universal p99 latency result;
- a finished PNG/PDF/SVG exporter;
- a completed Matplotlib fallback implementation;
- a persistent Scene/project format.

The honest baseline is `Not implemented`, `Not measured`, or `environment required` until an implementation worker supplies reproducible evidence. Accepted follow-up records now define the Phase-1 public signatures, root namespace and observation traits, error mapping, facade/crate visibility, packet boundary, units/colors, host-loop behavior, font strictness, and hardware cells. Future serialization remains the Deferred/Closed O-18 non-goal in [ADR 0009](../adr/0009-version-publication-supply-chain.md) and [open decisions](open-decisions.md#o-18-future-serialization-schema).
