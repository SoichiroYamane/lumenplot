# t_9052c3e2 — O-08 profile wiring evidence (B2-A)

Date: 2026-08-25 (JST) · Host: Linux 6.12.103, x86_64, NixOS
Build: `cargo build --release -p lumenplot-bench` @ commit 2a9c575 (+display_scale fix)
Fixture: `line-10k` (10000 points, canvas 800x600, dpi 100), 5 fresh-process blocks x 1000 frames.

## Profile x status coverage matrix

| Profile    | Status        | Evidence                                                                                                   |
|------------|---------------|------------------------------------------------------------------------------------------------------------|
| strict     | measured (inconclusive: no GPU/queue/scanout instrumentation on this host) | `strict/manifest.json` + `samples-*.jsonl`, R2 `--validate` OK, exit 0 |
| hybrid     | measured (same inconclusive reasons; drives the same accepted facade path as strict until the policy split exists) | `hybrid/manifest.json` + samples, R2 `--validate` OK, exit 0 |
| accelerated| measured (inconclusive reasons include the seam's missing present step) | `accelerated/manifest.json` + samples, R2 `--validate` OK, exit 0 |
| native     | refused pre-run, exit 2, NO artifacts | stderr message recorded below; refusal unit-tested in runner.rs |

Native refusal transcript:

```
bench: profile 'native' cannot run on this host: the native render path has no
implementation in this workspace; the O-08 cell stays unmeasured (environment
required) until the gated native backend lands
bench: no manifest or samples were written; the O-08 cell stays unmeasured
EXIT=2
```

Design note: a run that executed zero frames can never satisfy the D1 schema
(every block requires frame_count >= min_frames_per_block=1000, checked even
for status=inconclusive). Refusing before any output directory or child
process exists is therefore the only fail-closed representation of an
unexecutable cell; emitting an "inconclusive" manifest would require either
schema-invalid blocks or fabricated frames.

## Pooled descriptive statistics (not gate numbers)

| Profile     | pooled p50   | pooled p95   | pooled p99   | max block p99 |
|-------------|--------------|--------------|--------------|---------------|
| strict      | 22.015 ms    | 23.030 ms    | 24.256 ms    | see manifest  |
| hybrid      | 22.236 ms    | 23.605 ms    | 24.710 ms    | see manifest  |
| accelerated |  0.145 ms    |  0.151 ms    |  0.163 ms    | see manifest  |

The ~150x gap between accelerated and strict is expected and correctly
labelled: the M1 seam measures packet construction plus scene resolution
only — there is no raster/present step yet, so these are not comparable
accept-to-present claims and are never pooled across profiles.

## R2 tooling behavior verified

- `--validate`: all three executable-profile manifests pass (exit 0).
- Cross-profile A/B refusal: `--compare strict hybrid` -> exit 3 with the
  "profiles are never compared across" error.
- Same-profile A/B: `--compare strict strict-b` -> full report, exit 0,
  written to `report-strict-AB.md`.
- Per-clock quantiles over raw JSONL:
  `--quantiles accelerated/samples-2.jsonl --clock event_accept_to_present_return`
  -> p50=145526ns p95=151357ns p99=161406ns.

## Environment provenance recorded per run

os=NixOS os_version=25.5.0 arch=x86_64 kernel=6.12.103 display_scale=1.0;
gpu/compositor/present_mode stay null (no GPU/compositor instrumentation on
this host).
