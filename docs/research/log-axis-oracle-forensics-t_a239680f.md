# W3 log-axis lane: Matplotlib log-scale oracle forensics (t_a239680f)

## Status

**LANE EVIDENCE RECORD — measurement notes backing the W3 strict log10
implementation. Not an accepted design; the implemented surface follows
LP-FUNC-004 and LP-MPL-020 through the normal gates.**

Evidence basis: matplotlib 3.11.1 on CPython 3.14.7 (the lane's evidence
venv), probed 2026-08-26 via public `matplotlib.scale` / `Axis` /
`transData` getters and Agg raster probes. Every number below is a real
probe result, not source inspection alone.

## 1. What the adapter must reproduce for `set_xscale/set_yscale("log")`

### 1.1 The projection is base-consistent fractional placement

For a view interval `[lo, hi]` (data units, increasing) and axes pixel
span, matplotlib maps a data value `y` to display space by

```
display = edge + (log_b(y) - log_b(lo)) / (log_b(hi) - log_b(lo)) * span_px
```

with `b` = the axis' log base (`base=` kwarg, default 10). Verified:

- base 2, ylim (1, 8), bbox height 170 at y0=20: data y=2 → mpl display
  y 36.6667 vs base-2 model 36.6667; y=4 → 63.3333 both; y=8 → 90.0000
  both (match tolerance 0.01 px). A log10 model would place y=2 at
  36.6667 too only because (1,8) spans whole decades in both bases —
  so the base-2 probe was designed with non-coinciding probes: all three
  interior placements agree with the base-consistent formula exactly.
- base 10, ylim (1, 1000): red line endpoints (data y=2 at x=0.1,
  y=500 at x=0.9) land at raster rows [161,162] and [27,28]; the model
  predicts rows 162.94 and 27.06 (line half-width ~1px explains the
  rounding). Segment interiors are straight lines between *projected*
  vertices (raster mid-column rows [93..96] vs naive "project the
  interpolated data point" 44.07 — the per-vertex-then-draw model is
  what Agg does, and what the adapter's affine route produces).

Consequence: the adapter must apply the SAME public affine shape as the
linear path, but with `to_px = f(log_b(value))` per axis. Bases other
than 10 are cheap once the transform is parameterized.

### 1.2 Non-positive DATA under a positive view: clip to −1000 in log space

`matplotlib.scale.LogifyAlert`/`LogTransform(base=10,
nonpositive="clip")` (the default for `set_yscale("log")`) computes

```
out[values <= 0] = -1000   # in log10 units (scale.py:352)
```

i.e. data value ≤ 0 is drawn at `lo + (-1000 - log10(lo))` fractions
below the axis bottom — far off-canvas, then clipped by the axes
rectangle. Probe: ylim (0.1, 100), data point (−1.0, −5.0) transforms to
display y ≈ −26630 px (axes bbox y0=10, height=80), i.e. far above the
canvas top in raster space; the visible effect is that the polyline
runs off-frame and the axes clip rectangle hides everything below the
bottom edge.

Adapter consequence: project every vertex with the clip rule
`log_b(y if y > 0 else CLIP)` where `CLIP = -1000` **in log-base-b
units** (for base b: `-1000 * log_b(10)`, i.e. the same data-space
constant 1e-300 clipped to `-1000` in base-10 exponent units — mpl
clips to the constant −1000 regardless of base since it computes
`np.log(values)/np.log(self.base)` AFTER substituting; verified: the
substitution writes −1000 post-log, so in base-b units it stays −1000).

The engine seam already clips to the axes rectangle, so emitting the
clipped coordinates verbatim reproduces Agg without extra mask logic.
Rows/vertices whose projection lands outside remain in the command (the
native clip rect discards them), matching Agg which also emits the full
path and clips at raster time.

### 1.3 Invalid VIEW domains are refused by matplotlib itself

`ax.set_ylim(0.0, 10.0)` on a log axis warns ("Attempt to set
non-positive ylim on a log-scaled axis will be ignored") and KEEPS the
autoscaled positive interval: probe shows ylim resolves to
(0.89125094…, 10.0). Same for set_ylim(-1, 10). Therefore the adapter's
existing "limits must strictly increase" guard keeps working unchanged:
on an actually-configured log frame the limits ARE positive and
increasing after matplotlib refuses the bad assignment. An invalid
domain request can never produce a degenerate view here; explicit
invalid-domain handling (LP-FUNC-004 wording) is inherited from
matplotlib's own refusal + the existing finite/increasing checks.

Inverted limits (`set_ylim(1000, 1)`) still reach the adapter as a
decreasing pair and keep refusing under the existing guard (unchanged
from the linear path; Agg draws inverted views, but that is outside the
accepted linear slice contract and stays out of scope for W3).

### 1.4 Tick locations stay in DATA units on log axes

`axis.get_ticklocs()` returns data-unit values (probe ylim (1,1000):
locs `[1e-3, 1e0, 1e3, 1e6]`, view interval `[1, 1000]`); the
enumeration/decoration filters compare them against data-unit view
intervals exactly as today. Only the pixel mapping of a location
changes (through the §1.1 projection). No locator-side change needed.

### 1.5 Formatter labels: the default formatter is INELIGIBLE, plain ones work

- Default `LogFormatterSciNotation` labels contain mathtext markers:
  probe ylim (1,1000) → labels
  `$\mathdefault{10^{-3}}$`, `$\mathdefault{10^{0}}$`, … The existing
  `_check_tick_label_static` gate (`"$" in text → math/TeX unsupported`)
  refuses these TODAY, before any geometry runs. That refusal is the
  correct explicit diagnostic for default-formatter frames.
- `ScalarFormatter()` yields plain strings ('0', '1', '1000', …);
  `FuncFormatter(lambda v, p: f"{v:g}")` likewise ('0.001', '1', …).
  Both render natively today end-to-end (verified: strict render OK, no
  diagnostics, with minorticks_off).
- `minorticks_off()` clears the minor-tick refusal (G-09 note
  confirmed): minor ticklines/gridlines count 0 after the call.

W3 therefore needs NO new label machinery: eligibility flows through
the existing T-lane gates, refusing mathtext labels explicitly while
accepting plain-string formatters. This matches LP-MPL-020 (explicit
diagnostics, no silent approximation of mathtext glyphs).

## 2. Current-behavior baseline (pre-W3)

The pre-W3 adapter skipped any non-linear axis in `build_frame_spec`
while the collector still walked scaled artists, so a log frame either
refused on its default mathtext labels or rendered a PARTIAL spec:
measured on the decorated fixture (red line over ylim (1,1000), labels
suppressed), the emitted command list was empty (content AND
decorations dropped) or carried tick-label glyphs only — a silent
degradation LP-MPL-020 forbids. Measured against Agg on a 300x200
fixture with the linear-projection bug still present (line drawn at
linearly-interpolated rows): within32 = 0.9777 but the line sat ~93px
off its Agg position at mid-column. The W3 dispatch closes both by
projecting with the real scale and refusing unsupported scales.

## 3. Decisions encoded (lane-level, inside the accepted LP-MPL-020 mechanics)

1. Accept ONLY scale names "linear" (existing) and "log" (new) per
   axis; any other scale string records the standard explicit
   unsupported reason (symlog/logit/polar belong to LP-FUNC-036/039,
   out of W3 scope). The refusal replaces the former wholesale skip
   that emitted an empty command surface.
2. Base selection reads only public getters (`Axes.get_xscale` /
   `get_yscale`); W3 supports base-10 explicitly and refuses other
   bases with the standard diagnostic rather than touching private
   transform state (`axis._scale` is private).
3. Non-positive data values follow the §1.2 clip constant (−1000 in
   log units) verbatim via `max(value, 1e-300)` before log10; no row
   filtering or bridging.
4. Decorations (gridlines/tick strokes) use the same per-axis
   projection for tick locations; spines are scale-independent and
   unchanged. Vertex convention stays the adapter's frozen one
   (matplotlib display coords, y-up; the native engine flips).
5. Labels ride the existing static gates (mathtext refused, plain
   accepted); no new label code.

## 4. Post-implementation measurements (2026-08-26, real seam)

Full-frame decoded-raster parity vs Agg on 300x200 fixtures
(CPython 3.14.7 + matplotlib 3.11.1 + lane abi3 seam), ratified band
(>=95% of pixels within 32/channel):

- plain label-suppressed log frame: within32 = 0.9777, worst = 255;
- decorated (y-grid + ScalarFormatter labels): within32 = 0.9695,
  worst = 255;
- axis='both' grid variant measured 0.9485 — the extra stroked length
  pushes the documented engine-wide stroke-edge AA trait past 5% of
  this small frame, so the pinned fixture uses y-grid only.

All differing pixels sit on stroke edges/glyph ramps (the documented
Agg-scanline vs tiny-skia-analytic trait); interiors stay exact.

## 5. Probe scripts

Forensic probes were ad-hoc scripts run inside the evidence venv
(`~/lp-verify/venv-evidence`, LD_LIBRARY_PATH gcc-16/zlib recipe);
they are reproduced inline in `tests/python/test_phase3b_log_axis.py`
as pinned assertions rather than kept as standalone artifacts.
