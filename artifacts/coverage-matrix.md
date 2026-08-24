# Coverage matrix — O-16 Go-gate inputs vs. this host (t_9052c3e2)

Lane: [B2-A] A/B measurement (single serialized lane). Canon: ADR 0006 §O-08
(protocol) + §O-16 (adoption gate). D1–D5 per t_3d7d3594 comment 501.
Host: Linux x86_64 (NixOS 25.5.0, kernel 6.12.103), no GPU, no compositor.
Build: release @ `wt/t_9052c3e2` commits `2a9c575` + `4ee443d`, base
`ace1364` (B2-P rework head — merge-order note at bottom).

## O-16 Go gate inputs, verbatim from ADR 0006

A native path may reach **Go** only after all of the following:

| # | Gate input | Threshold |
|---|------------|-----------|
| 1 | Portable baseline pass + O-07/O-08 evidence pass on declared hardware | — |
| 2 | ≥15% median frame-time improvement | two-cell comparison |
| 3 | ≥15% p99 frame-time improvement | three-comparison set |
| 4 | p99 regression ≤5% | any workload |
| 5 | Memory footprint growth ≤10% | sustained |

## Per-input measurability on THIS host

| Gate input | Measurable here? | Evidence artifact |
|------------|------------------|-------------------|
| Portable O-08 baseline (strict/hybrid) | YES — measured for real | `strict/manifest.json`, `hybrid/manifest.json` (+ `samples-*.jsonl`), both R2-valid |
| Accelerated seam resolve cost (context only, NOT a gate number) | YES — measured | `accelerated/manifest.json`; pooled p50 ≈ 0.145 ms vs facade ≈ 22 ms; labelled inconclusive because the M1 seam has no present step |
| #1 evidence pass "on declared hardware" | NO — Apple Silicon cell is environment required | native cell refused pre-run; see below |
| #2 median ≥15% (two-cell) | NO — needs native cell on macOS | environment required until B2-P prototype lands behind its gate |
| #3 p99 ≥15% (three-comparison) | NO — same | same |
| #4 p99 regression ≤5% | NO — same | same |
| #5 memory ≤10% | NO — no RSS instrumentation lane in this runner; also needs native cell | not instrumented in this lane (see residual notes) |

## Native cell disposition (honesty rule)

The card pins: native must be recorded honestly as environment required /
inconclusive, with zero-substitution and fabrication forbidden.

What was implemented: `--profile native` refuses BEFORE creating any output
directory or child process — stderr reason printed, exit code 2, no
artifacts. Verified end-to-end:

```
$ lumenplot-bench --profile native --out .../native-refusal
bench: profile 'native' cannot run on this host: the native render path has no
implementation in this workspace; the O-08 cell stays unmeasured (environment
required) until the gated native backend lands
bench: no manifest or samples were written; the O-08 cell stays unmeasured
EXIT=2
```

Why no native manifest exists (and why that is the honest record): the D1
schema requires every one of the 5 blocks to carry `frame_count >= 1000`
even under `status=inconclusive` (`_validate_blocks`: `expected int >=
min_frames`). A run that executed zero frames can only be represented by a
manifest that either fabricates frame counts/quantiles (forbidden) or fails
`bench_analysis.py --validate` (forbidden). Pre-run refusal is therefore the
only fail-closed representation of an unexecutable cell; the refusal is also
unit-tested (`native_refusal_happens_before_any_artifact_is_created`,
`native_profile_is_unavailable_and_others_are_available`).

## Same-profile paired A/B proof (deliverable 1)

Two independent strict-profile runs compared with the R2-owned tool:

```
$ bench_analysis.py --compare strict/manifest.json strict-b/manifest.json
-> full paired report, EXIT=0   (report-strict-AB.md)
$ bench_analysis.py --compare strict/manifest.json hybrid/manifest.json
ERROR: refusing cross-profile comparison: A profile='strict' vs B profile='hybrid';
profiles are never compared across (ADR 0006 SS O-08)
-> EXIT=3   (D4 verified)
```

## Validation status of all emitted manifests

| Manifest | `--validate` |
|----------|--------------|
| `strict/manifest.json`     | OK (inconclusive: no gpu/queue/scanout instrumentation) |
| `strict-b/manifest.json`   | OK (second run for paired A/B) |
| `hybrid/manifest.json`     | OK (same single implemented facade path as strict; policy split it names does not exist yet) |
| `accelerated/manifest.json`| OK (extra inconclusive reason: seam has no present step) |
| native                     | intentionally absent — pre-run refusal (see above) |

## Residual notes

- Merge order: base is `ace1364` (B2-P rework). Merge B2-P's branch before
  `wt/t_9052c3e2` or the bench manifest edges dangle on old main.
- `detect_environment` now records applied display scale (GDK_SCALE /
  QT_SCREEN_SCALE_FACTOR, else exactly 1.0); previously null, which failed
  the D1 schema on every manifest main emits.
- Memory-footprint gate input (#5) has no instrumentation in the current
  O-08 runner; recording it as future work rather than guessing a number.
