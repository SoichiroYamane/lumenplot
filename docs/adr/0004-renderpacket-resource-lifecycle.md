# ADR 0004: RenderPacket and renderer resource lifecycle

- Status: **Accepted contract**
- Date: 2026-08-21
- Decision owner: architecture-authority
- Recorded by: implementation-worker
- Scope: O-04 internal RenderPacket field families, validation, generations, renderer cache, leases, and fence retirement
- Governing architecture: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md)
- Open-decision record: [O-04 — Internal RenderPacket schema and resource lifecycle](../architecture/open-decisions.md#o-04-internal-renderpacket-schema-and-resource-lifecycle)

This ADR records an internal process-local renderer seam. It does not establish a public struct, serialization schema, wire protocol, persistence format, or product implementation result.

## Requirement references

The packet boundary covers `LP-PROD-011`, `LP-PROD-012`, `LP-PROD-013`, `LP-QUAL-020`, and `LP-SEC-004` in the [requirements](../requirements/lumenplot-v1.0.md#5-basic-architecture).

## Context

The shared semantic/layout frame is the backend-neutral source for interactive rendering and export. A renderer still needs an immutable validated projection with owned geometry and resource references. The projection must carry enough generation information to reject stale work and enough lease information to keep in-flight resources alive without making a GPU object part of the semantic core.

## Decision

### Packet boundary and field families

`RenderPacket` is immutable after validation, process-local, renderer-instance scoped, internal, and built only from a resolved semantic/layout frame. Its field families are:

| Family | Contract |
| --- | --- |
| Packet identity | An internal packet identity used to correlate a validated publication with one renderer instance. |
| Target and view facts | The resolved target/view facts needed by the renderer, including the target dimensions and view-dependent facts selected for this packet. Coordinate and color semantics remain owned by [ADR 0007](0007-coordinate-color-text-export.md). |
| Owned local-f32 and batched geometry | Renderer-ready local f32 data derived from canonical f64 through the accepted origin-relative conversion, grouped into bounded batches. |
| Draw ranges and order | Validated ranges, ordering, and primitive-family draw information; no per-draw public API is implied. |
| Clip and style references | References into validated packet-local or logical resources for clipping and resolved styles. |
| Pick mapping | Internal mapping from rendered geometry to semantic/source identity for supported picking. |
| Opaque logical resource identifiers | Generational logical IDs for buffers, textures, pipelines, fonts, or other retained resources; no backend object is embedded. |

The packet may carry `SceneRevision`, `WorkGeneration`, and `DeviceGeneration` as distinct validation inputs. Adapter fallback and user-facing capability diagnostics belong to the render/export plan or result, not automatically to packet fields.

The packet never contains wgpu, window, surface, device, queue, Python, Matplotlib, or other frontend/backend concrete objects. Export consumes the shared semantic/layout frame and never reverse-engineers GPU buffers from a packet.

### Whole-packet validation and publication

Validation is an all-or-nothing operation:

1. confirm that the source semantic/layout frame and its dependencies are complete and associated with the expected `SceneRevision`;
2. validate finite target/view facts, bounded dimensions, local-f32 geometry, ranges, order, clip/style references, pick mappings, and opaque logical IDs;
3. validate `WorkGeneration` against the scheduler publication point and `DeviceGeneration` against the renderer instance;
4. publish one immutable complete packet only after every validation step succeeds.

No partial packet, partial visible publication, or partial upload is allowed. A packet from an older WorkGeneration is stale even if its SceneRevision matches. A packet associated with an invalidated DeviceGeneration is not submitted to the old device.

The validation result is internal. Public operation errors and fallback diagnostics follow [API 0002](../architecture/api-0002-errors-capabilities-fallback.md); packet field names and validation details do not become a public error schema.

### Resource cache, lease, and retirement

The renderer/device owner maintains the logical-resource-to-backend-object cache. The cache key is the opaque logical resource identity together with `DeviceGeneration`:

```text
logical resource identity + DeviceGeneration → backend resource cache entry
```

- A validated packet acquires a packet lease for the logical resources needed by its in-flight submission.
- The packet lease keeps those resources alive while the packet is owned by the renderer submission path.
- Dropping the packet releases its lease; it does not synchronously destroy a resource that may still be used by the device.
- Actual backend-resource retirement waits for the relevant completion fence or equivalent completion observation.
- A completed fence retires entries whose leases and other owners are gone.
- Device loss invalidates backend resources and packets for the old `DeviceGeneration`, retains CPU Scene/data, and rebuilds through the runtime contract.

`SceneRevision`, `WorkGeneration`, and `DeviceGeneration` are never conflated: a device rebuild does not rewrite semantic Scene history, and a scheduler cancellation does not imply device loss.

### Explicit non-public and non-persistent boundary

The packet has no public constructor, public renderer contract, serde obligation, wire representation, save/load path, or persistence identity. It is not a Scene/project format. The v1 serialization non-goal and its negative guards are recorded in [ADR 0009](0009-version-publication-supply-chain.md).

## Alternatives and rationale

A public or serialized packet would freeze backend resource ownership and make a process-local optimization a compatibility format. Per-draw calls would couple the semantic engine to renderer details and make large-data work harder to bound. The selected immutable packet plus cache/lease/fence boundary keeps the renderer seam narrow while retaining CPU semantic state for recovery.

## Consequences

- Renderer work can be stale-dropped without exposing scheduler internals.
- Device loss can invalidate GPU state while preserving Scene/data authority.
- Fence-based retirement avoids use-after-free while allowing packet ownership to end earlier.
- Export and semantic tests remain backend-neutral.
- Internal packet validation and resource counters are additional implementation work and evidence obligations.

## Verification and evidence boundary

Bounded implementation evidence currently covers packet completeness, invalid-resource rejection, generation-mismatch tests, dependency-direction/type scans, immutable publication, logical resource keying, packet leases, completion-fence retirement, multiple-owner accounting, device-generation invalidation, and negative checks for public constructors/serde/wire formats/persistence. The complete evidence obligation still includes property coverage, concrete renderer-owner integration, device-loss rebuild from retained CPU state, and environment-backed completion semantics; this ADR is not itself evidence that those remaining tests or a complete renderer exist.

## Residual risks

- The exact internal representation of packet batches and logical IDs can affect memory and performance.
- Fence and completion semantics differ by backend and must remain behind the renderer/runtime owner.
- Packet diagnostics must not grow into a second public fallback or persistence schema.

## Related records

- [ADR index](README.md)
- [Architecture overview](../architecture/overview.md)
- [API 0001 — native Scene state](../architecture/api-0001-native-scene-state.md)
- [API 0002 — errors, capabilities, and fallback](../architecture/api-0002-errors-capabilities-fallback.md)
- [ADR 0007 — coordinate, color, text, and export](0007-coordinate-color-text-export.md)
- [ADR 0009 — publication and serialization guards](0009-version-publication-supply-chain.md)
- [O-04 open-decision entry](../architecture/open-decisions.md#o-04-internal-renderpacket-schema-and-resource-lifecycle)
- [Accepted requirements: packet boundary](../requirements/lumenplot-v1.0.md#5-basic-architecture)
