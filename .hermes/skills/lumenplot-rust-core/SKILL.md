---
name: lumenplot-rust-core
description: Use for Rust engine, data, LOD, packet, GPU, or export.
version: 0.1.0
metadata:
  hermes:
    tags: [LumenPlot, Rust, engine, data, rendering]
    related_skills: [lumenplot-contract, lumenplot-benchmark]
---

# LumenPlot Rust core procedure

Use for implementation or verification in the Rust engine: Scene and state,
data ingestion, chunks and LOD, RenderPacket production, GPU-facing rendering,
text/layout, or PNG/PDF/SVG export. Always load `lumenplot-contract` first when
the change touches an architecture-owned boundary.

## Procedure

1. Read [`../../../.hermes.md`](../../../.hermes.md) and the two linked reference
   checklists in this skill.
2. Read the canonical requirements, traceability, accepted ADR, and applicable
   open decision under [`docs/architecture/`](../../../docs/architecture/).
3. Search before editing. Keep concrete Python, Matplotlib, GPU-backend, and
   window-system types out of lower engine layers; use the accepted abstraction
   rather than adding a local shortcut.
4. Implement the smallest accepted change. Preserve the canonical ownership,
   revision/generation, cancellation, stale-result, device-loss, OOM, and
   publication rules; do not invent exact packet or public Scene fields.
5. Run focused tests first, then the required format, build, test, and clippy
   checks using the Nix/locked-environment policy in [`../../../.hermes.md`](../../../.hermes.md).
   Add property, semantic, golden, or lifecycle coverage appropriate to the
   changed contract.
6. If the result is described as faster, scalable, cross-platform, or export-
   equivalent, hand it to `lumenplot-benchmark` for a real workload and report.

## Pitfalls

Do not use stride-only decimation, make a process-local packet into a wire or
persistence format, reverse-engineer vector output from GPU buffers, or silently
replace a failed capability with a lower-fidelity path.

## Verification

Record the canonical source, affected layer, focused tests, full checks, and any
measurement artifact. An unresolved data, packet, lifecycle, or export contract
is an architecture gate, not an implementation detail to settle inside the
implementation.
