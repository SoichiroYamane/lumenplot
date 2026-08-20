---
name: lumenplot-benchmark
description: Use for performance, backend, or dependency evidence.
version: 0.1.0
metadata:
  hermes:
    tags: [LumenPlot, performance, benchmarking, backends]
    related_skills: [lumenplot-contract, lumenplot-rust-core, lumenplot-python-bridge]
---

# LumenPlot benchmark and evidence procedure

Use for performance claims, backend selection or promotion, dependency upgrades,
regression checks, and release evidence. Load `lumenplot-contract` plus the
relevant domain skill before measuring an architecture-sensitive change.

## Procedure

1. Read [`../../../.hermes.md`](../../../.hermes.md), including its
   Nix/locked-environment policy, the linked workload reference, and the
   canonical requirements, traceability map, accepted ADR, and relevant
   architecture gate.
2. Define the workload before running it: data topology and size, displayed
   information, viewport/action sequence, warm-up, repetitions, output mode,
   hardware/driver/API, build profile, dependency versions, and counters.
3. Measure real results, including distributional latency such as p50/p95/p99
   where the contract requires it. Record allocations, uploads, callbacks,
   shader/pipeline work, memory, and fallback diagnostics when relevant.
4. Compare against a named baseline under the same workload. Treat dependency
   or native-backend adoption as benchmark- and cross-platform-gated; do not
   promote a newer API merely because it is newer.
5. Report raw reproducible evidence, limitations, and failed or unsupported
   cells. Never fill a missing measurement with an estimate.

## Pitfalls

Do not benchmark a tiny fixture and generalize to large data, report only a mean
for a tail-latency contract, include startup work in a warm steady-state claim,
or call source inspection a measured result. Do not hide a slower or lower-
fidelity fallback in an aggregate score.

## Verification

A benchmark handoff includes the workload, environment, protocol, baseline,
raw summary, counters, artifact paths relative to the repository, and a clear
claim boundary. The canonical release gate and a reviewer must be able to
reproduce or reject the claim without guessing missing inputs.
