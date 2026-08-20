# ADR 0006: Support cells, benchmark protocol, and native-backend gates

- Status: **Accepted contract; evidence pending**
- Date: 2026-08-21
- Decision owner: architecture-authority
- Recorded by: implementation-worker
- Scope: O-07 support target registry, O-08 benchmark accounting, and O-16 native adoption/retirement gates
- Governing architecture: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md)
- Open-decision records: [O-07 — Declared hardware, driver, and CI matrix](../architecture/open-decisions.md#o-07-declared-hardware-driver-and-ci-matrix), [O-08 — Benchmark protocol and performance accounting](../architecture/open-decisions.md#o-08-benchmark-protocol-and-performance-accounting), [O-16 — Native backend adoption and retirement gates](../architecture/open-decisions.md#o-16-native-backend-adoption-and-retirement-gates)

This ADR records target cells and evidence gates, not support or performance results. Every cell below remains `environment required` until it passes the complete lifecycle, correctness, and benchmark manifest.

## Requirement references

The target and gate contract covers `LP-PROD-002`, `LP-PERF-001`, `LP-PERF-004`, `LP-PERF-006`, `LP-PERF-009` through `LP-PERF-015`, `LP-QUAL-021` through `LP-QUAL-024`, `LP-PLAT-003`, `LP-PLAT-007`, `LP-PLAT-011`, and `LP-PLAT-012` in the [requirements](../requirements/lumenplot-v1.0.md#26-performance-requirements).

## Context

A platform label or a p99 number is not meaningful without an identified OS build, GPU/driver/API feature level, present semantics, display scale, and reproducible timing boundaries. Native backends also need an adoption threshold that is stronger than API novelty and a retirement rule when maintenance cost exceeds measured benefit.

## Decision

### O-07 target cell registry

The initial target registry is:

| Operating-system and API family | Required cells |
| --- | --- |
| Windows 11 23H2 or newer, x86_64, D3D12 | Intel integrated; AMD discrete; NVIDIA discrete |
| Ubuntu 24.04 LTS, x86_64, Vulkan | Intel/Mesa on X11; AMD/Mesa on Wayland; NVIDIA proprietary on X11; NVIDIA proprietary on Wayland |
| macOS 13 or newer, arm64, Metal | Apple Silicon |
| Control only | Lavapipe/offscreen headless; it is never a window or present-support claim. |

Each row is independently supported or unsupported; no generic platform claim is inferred from another row. The evidence manifest records the exact OS build, vendor/device, driver string, API feature level, compositor, display scale, and present mode. No numeric minimum driver version is guessed before measurement.

The scale matrix covers real 1x and 2x behavior, available fractional and 3x behavior, and semantic 1.25x and 3x fixtures. Startup, rendering, lifecycle, and benchmark evidence are required per declared row. Until those artifacts exist, the status is `environment required` and no support claim is made.

### O-08 timing and clock boundaries

The benchmark reports separate domains and never collapses them into a hardware-input-to-display claim:

- CPU monotonic scheduler-acceptance intervals use names beginning with `event_accept_to_*`.
- GPU timestamp intervals remain in the GPU timestamp domain.
- Queue completion/readback observation is recorded separately.
- Scanout markers are recorded only when available.
- A `present` return is not scanout. If a required observation is unavailable, the result is `null`/unsupported, never zero.

The protocol reports input acceptance and measured boundaries honestly; it does not rename scheduler-origin measurements as physical input-to-display latency.

### Fresh-process blocks and statistical reporting

For every fixture, profile, and target cell:

1. run five fresh-process blocks;
2. collect at least 1000 accepted measured frames in each block;
3. randomize A/B order from a manifest seed;
4. retain raw samples;
5. report nearest-rank p50, p95, and p99 for each block;
6. report a pooled descriptive result and the maximum block p99;
7. report paired block deltas and a fixed-seed 10,000-resample percentile-bootstrap 95% confidence interval.

No trimming or winsorization is permitted. Ordinary high-latency frames are retained; controlled recovery is a separate fixture. Any correctness, visual, revision, or stale-publication failure fails the fixture. Missing required instrumentation makes the result inconclusive/unsupported rather than silently passing.

The internal versioned benchmark manifest, JSONL measurements, and result artifacts are tooling contracts only. They are not public Scene, RenderPacket, project, or persistence formats.

Profiles remain separate and labelled. Native, strict-common-2d, hybrid-explicit, and accelerated-native results are not pooled into one performance claim. The native v1 gate is the MonotonicX 10M workload; 100M resident, streamed, and appendable scenarios remain separately labelled.

### O-16 native adoption gate

No native Metal, D3D12/DXGI, or Vulkan implementation fan-out occurs before the portable baseline and the O-07/O-08 evidence pass. A future native path may reach **Go** only after all of the following:

- correctness, security, lifecycle, and license review passes;
- at least 15% median and p99 end-to-end improvement on at least two representative vendor cells;
- the improvement is observed across at least three fresh-process comparisons;
- no p99 regression greater than 5% on any declared cell;
- no unexplained memory amplification greater than 10%.

A critical correctness, security, or lifecycle failure quarantines the native path immediately. A native path never enters `Backend::Auto` before Go. Two release cycles with less than 5% benefit trigger a retirement review. Threshold changes require a new decision record; they cannot be weakened by an implementation-local benchmark.

The adoption report compares frame time, CPU overhead, present latency, memory, feature availability, and maintenance implications against the portable path. API novelty alone is not evidence of benefit.

## Consequences

- Support is a per-cell evidence claim instead of a platform-name assumption.
- Timing reports distinguish scheduler, GPU, queue, and scanout domains.
- Five fresh-process blocks and raw samples make run-to-run variance visible.
- Native paths have an explicit quarantine, Go, and retirement boundary.
- Benchmark tooling and output artifacts stay internal and do not create a persistence schema.

## Verification and evidence boundary

Required artifacts are a target-cell manifest, startup/render/lifecycle matrix, scale fixtures, five-block benchmark runner, raw JSONL and statistical report, profile-separated results, and native A/B adoption or retirement decision records. None is present merely because this ADR names the target. Results remain `Not measured` or `environment required` in the [traceability registry](../requirements/traceability-v1.0.md).

## Residual risks

- Hardware, driver, compositor, and present behavior can make a result cell-specific.
- The 15% improvement threshold may be difficult to reproduce across representative vendors; raw paired blocks and manifest seeds are required.
- A control headless row can validate deterministic work without providing window/present evidence.

## Related records

- [ADR index](README.md)
- [Architecture overview](../architecture/overview.md)
- [ADR 0005 — runtime, viewer, and host loop](0005-runtime-viewer-host-loop.md)
- [ADR 0008 — portable GPU and shaders](0008-portable-gpu-and-shaders.md)
- [ADR 0009 — dependency and publication policy](0009-version-publication-supply-chain.md)
- [O-07 open-decision entry](../architecture/open-decisions.md#o-07-declared-hardware-driver-and-ci-matrix)
- [O-08 open-decision entry](../architecture/open-decisions.md#o-08-benchmark-protocol-and-performance-accounting)
- [O-16 open-decision entry](../architecture/open-decisions.md#o-16-native-backend-adoption-and-retirement-gates)
- [Accepted requirements: performance protocol](../requirements/lumenplot-v1.0.md#26-performance-requirements)
