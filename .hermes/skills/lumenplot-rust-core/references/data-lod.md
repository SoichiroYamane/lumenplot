# Rust data and LOD checklist

This is a triggered procedure, not a replacement data schema. Read the
[requirements](../../../../docs/requirements/lumenplot-v1.0.md),
[traceability map](../../../../docs/requirements/traceability-v1.0.md),
[accepted ADR](../../../../docs/adr/0002-gpu-native-engine-and-matplotlib-adapter.md),
and the relevant [architecture decisions](../../../../docs/architecture/) first.

## Before implementation

- Identify whether the request is about canonical representation, ingestion
  ownership, chunk sealing, topology, LOD construction, query/culling, or an
  unresolved public data contract.
- Keep canonical scientific precision and long-lived ownership in the layer
  selected by the accepted contract. Treat temporary views and GPU upload
  representations as different lifetimes.
- Distinguish monotonic-X and arbitrary-XY behavior before selecting an index,
  culling rule, simplifier, or benchmark workload.
- If exact chunk fields, public handles, mutation visibility, or non-finite-value
  policy is missing from the canonical sources, stop for an architecture gate.

## Implementation checks

- Preserve source order, topology, extrema, and gap semantics required by the
  canonical contract; do not substitute stride-only sampling.
- Keep LOD selection tied to displayed information and viewport state rather than
  a fixed sample count. Keep cache invalidation and stale-generation behavior
  explicit.
- Keep asynchronous work bounded and publish only a result whose input revision
  is still current. Make memory pressure and cancellation observable.

## Verification

Use focused unit and property tests for precision, monotonicity, source-index
ordering, extrema retention, gaps, topology, viewport selection, cache
invalidation, and stale-result rejection. Report data size, displayed width,
selected level, output count, and real timing/memory counters for performance
claims. A source-only complexity argument is not benchmark evidence.
