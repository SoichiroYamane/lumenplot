# Roadmap

LumenPlot is pre-alpha. This roadmap has no release dates, version promises, or
performance results. Work may be reordered after architecture review.

## 1. Public baseline and architecture reconciliation

- Adopt the legal, security, support, governance, and contribution baseline.
- Choose the public history/privacy strategy and verify provenance.
- Reconcile historical CPU-only records with the GPU-native engine direction.
- Record accepted cross-cutting decisions in public ADRs.

## 2. Engine and adapter boundary

- Define the smallest backend-neutral engine contract.
- Define the Matplotlib adapter capability matrix and explicit failure/fallback
  semantics.
- Keep the one-way dependency `Matplotlib -> adapter -> engine`.
- Specify ownership, lifecycle, and resource behavior before optimization.

## 3. First supported vertical slice

- Implement one measured, documented path from Matplotlib input through the
  adapter into the engine and an explicitly supported output.
- Add correctness tests and state unsupported capabilities clearly.
- Do not call a partial internal IR or exploratory module a stable API.

## 4. Large-data path and measurements

- Add an opt-in fast path only after correctness evidence exists.
- Measure workloads in the target envelope, including 10M–100M data points
  where meaningful and the relevant 60/120 Hz target.
- Publish reproducible benchmark artifacts rather than unsupported speed
  claims.

## 5. Packaging and release readiness

- Establish supported platforms, toolchains, Python/Matplotlib combinations,
  dependency provenance, and build/release evidence.
- Add CI gates, dependency/license scanning, artifact provenance, and branch
  controls before accepting broad external contributions.
- Reassess production readiness only after the supported API and compatibility
  matrix are demonstrated.
