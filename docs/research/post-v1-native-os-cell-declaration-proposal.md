# Proposal: declaring the native macOS/Metal target cell (Phase-4 B1-M2)

Status: **Proposal — nothing binding.** This document is a proposal only. It declares no support, changes no gate, and binds nothing: the Phase-4 adoption gate (O-16) is still `Accepted — evidence pending`, every cell in the ADR 0006 §O-07 registry remains `environment required`, and nothing here becomes operative unless and until the Phase-4 gate turns Go on evidence. No numeric minimum driver version is guessed before measurement.

## Purpose

If the Phase-4 gate hypothetically reaches **Go**, a native macOS prototype would need to declare exactly one target cell from the ADR 0006 §O-07 registry and run it through the complete declaration procedure proposed below. The purpose of this proposal is to fix, ahead of any such decision:

1. which single cell a macOS/Metal prototype would identify as its target;
2. which manifest fields such a declaration would have to carry; and
3. what hosted-CI capacity that cell would require if it were exercised on hosted runners.

## Cell identification

The candidate cell is taken verbatim from the ADR 0006 §O-07 target cell registry row:

> macOS 13 or newer, arm64, Metal | Apple Silicon

A Phase-4 macOS/Metal prototype would therefore identify exactly this one cell as its target:

- Operating system: macOS 13 or newer
- Architecture: arm64
- API family: Metal
- Hardware class: Apple Silicon

Per the registry contract, each row stands alone and carries its own evidence status; no generic platform claim is inferred from another row. This cell stays `environment required` until it passes the complete lifecycle/correctness/benchmark manifest, regardless of any other row's status.

## Declaration manifest fields (verbatim from ADR 0006 §O-07)

A declaration for this cell would record, verbatim from ADR 0006:

> The evidence manifest records the exact OS build, vendor/device, driver string, API feature level, compositor, display scale, and present mode.

Enumerated against the macOS/Metal cell, the manifest fields would be:

| Manifest field | What it would mean for this cell |
| --- | --- |
| OS build | exact macOS build identifier of the host used for evidence |
| vendor/device | Apple Silicon SoC/GPU identifier |
| driver string | OS-bundled driver/firmware identification string |
| API feature level | Metal API feature-set level present and exercised |
| compositor | macOS window server/compositor context |
| display scale | display scale at which evidence was collected |
| present mode | present semantics exercised |

No numeric minimum driver version is guessed before measurement; the driver string field records what was measured, not a floor.

## Proposed declaration procedure (if the Phase-4 gate goes Go)

1. Provision one Apple Silicon host matching the registry row (macOS 13+).
2. Collect the seven manifest fields listed above from that exact host.
3. Run the complete lifecycle, correctness, and benchmark manifest on that cell.
4. Record the declaration with the collected manifest fields attached to the evidence artifacts.
5. Only after the full manifest passes does the cell's status change from `environment required`.

Until step 5 completes, the cell remains `environment required`, and no support claim of any kind is made.

## Hosted-CI matrix impact (proposal only)

This section is a proposal about CI capacity, not a workflow change. No workflow file is added or modified by this document; everything here is prose-level impact analysis only.

- Hosted runner prerequisite: exercising this cell on hosted CI presumes the availability of a hosted macOS runner with arm64 (Apple Silicon) hardware. Without such runners, the cell can only be measured on developer-owned hosts.
- Cost consideration: hosted macOS runners bill at a higher per-minute rate than Linux runners, so adding this cell to shared CI would increase both job count and cost. The proposal is therefore to keep heavier measurements out of per-push execution.
- Cadence proposal: heavyweight measurement workloads (the five fresh-process blocks and other benchmark/lifecycle evidence collection) would be appropriate for nightly or manual-dispatch placement rather than per-push execution.
- Lavapipe control cell unaffected: the control-only cell (Lavapipe/offscreen headless) is unaffected by this proposal; it continues to validate deterministic work without providing window/present evidence, and its execution environment needs no macOS arm64 capacity.
- Boundary: this section deliberately stops short of any workflow YAML. Concrete trigger/filter/job definitions are future implementation work, gated on the same Phase-4 Go decision as everything else.

## Non-goals

This proposal explicitly makes three statements:

1. The cell stays `environment required`. Nothing here changes any cell's status; declarations happen only via the complete manifest evidence pass.
2. No support claim. This document asserts nothing about macOS support, performance, or suitability; it only proposes how a declaration would be made if the gate allows one.
3. Nothing changes until O-16 Go thresholds are met by evidence. Until the two-cell/three-comparison/15% thresholds (with regression and memory limits) are satisfied by measured evidence under O-16, neither the cell declaration nor any CI change described here takes effect.

## References

- ADR 0006 — Support cells, benchmark protocol, and native-backend gates (§O-07 target cell registry; §O-16 native adoption gate)
- Open decisions: O-07 Declared hardware, driver, and CI matrix; O-16 Native backend adoption and retirement gates
- Requirements: LP-PLAT-003 (conditional Metal fast path), LP-REL-007 (Phase 4 conditional prototypes)
