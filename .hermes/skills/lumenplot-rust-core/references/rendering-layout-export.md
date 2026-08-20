# Rendering, layout, and export checklist

This is a triggered procedure, not a RenderPacket schema. Read the
[requirements](../../../../docs/requirements/lumenplot-v1.0.md),
[traceability map](../../../../docs/requirements/traceability-v1.0.md),
[accepted ADR](../../../../docs/adr/0002-gpu-native-engine-and-matplotlib-adapter.md),
and the relevant [architecture decisions](../../../../docs/architecture/) first.

## Before implementation

- Identify the authoritative mode, revision, layout generation, and publication
  boundary. Do not choose exact fields or resource APIs in this checklist.
- Confirm that packet validation, logical resource identity, resource lifetime,
  main-thread/device lifecycle, bounded workers, stale-result dropping, device
  loss, and out-of-memory behavior are already accepted for the change.
- Treat screen, PNG, PDF, and SVG as consumers of the shared semantic layout and
  resolved scene state. Do not create renderer-specific text measurement rules.

## Implementation checks

- Keep the engine free of concrete Matplotlib, Python, GPU-backend, and window
  types. Keep backend capability and fallback diagnostics explicit.
- Preserve the warm steady-state publication rules: no unplanned shader or
  pipeline creation, full-data upload, font shaping, or LOD rebuild in the
  interaction path.
- Keep line, text, legend, axis, clipping, HiDPI, alpha, and export behavior
  aligned with the canonical acceptance contract. Do not reverse-engineer
  vector output from a raster or GPU buffer.

## Verification

Use semantic and golden tests for layout identity, line and text behavior,
HiDPI, clipping, alpha, interaction publication, and PNG/PDF/SVG output. Test
resize, suspend/resume, surface/device loss, close, cancellation, and stale
revisions where relevant. Record actual artifact inspection and environment
information; never claim export equivalence from a compile-only result.
