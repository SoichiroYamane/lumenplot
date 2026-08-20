# Workload and measurement checklist

This checklist records how to produce evidence; it does not define a benchmark
schema. Read the [requirements](../../../../docs/requirements/lumenplot-v1.0.md),
[traceability map](../../../../docs/requirements/traceability-v1.0.md),
[accepted ADR](../../../../docs/adr/0002-gpu-native-engine-and-matplotlib-adapter.md),
and the relevant [architecture decisions](../../../../docs/architecture/) first.

## Workload definition

- State topology: monotonic-X or arbitrary-XY, series count, point count, and
  non-finite/gap pattern.
- Displayed information: viewport dimensions, pixel density, visible series,
  legend/grid/annotation/text state, and export target.
- Interaction sequence: warm-up, pan/zoom/box-zoom/history/visibility actions,
  redraw and present semantics, and cancellation or resize events.
- Environment: OS, GPU, driver/API, backend, CPU, build profile, dependency
  versions, and relevant feature flags.

## Measurement protocol

- Separate cold startup, warm-up, steady-state interaction, export, and recovery
  measurements.
- Use enough repetitions to report the required p50/p95/p99 and state outlier
  handling. Record frame time and relevant counters such as Python calls,
  uploads, shader/pipeline creation, allocations, memory, and fallback events.
- Compare an explicit baseline with identical workload and environment. Keep
  raw outputs and the command or harness needed to reproduce them in the
  repository's accepted evidence location.
- For backend or dependency changes, include correctness, visual/export, and
  cross-platform cells before recommending promotion.

## Reporting

State what the measurements prove and what they do not. Include unsupported
cells, missing hardware, failed runs, and fidelity differences. A claim about
10M/100M data, p99 latency, zero callbacks, or backend superiority is invalid
without the corresponding workload and real counters.
