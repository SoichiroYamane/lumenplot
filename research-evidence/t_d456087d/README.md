# PRAC-A-D evidence: decorated-axes strict-mode native render (t_d456087d)

Date: 2026-08-25 (JST). Environment: NixOS host, worktree
`wt/t_d456087d` rebased on `origin/main` at `efb13a7`; native seam rebuilt
from the merged tree (`cargo build -p lumenplot-python`, debug cdylib copied
to `python/lumenplot_mpl/_native.abi3.so`); CPython 3.14 + Matplotlib 3.11.1
evidence venv (`/home/sy/lp-verify/venv-evidence`) with the standard
LD_LIBRARY_PATH recipe.

## What is proven

An `axison=True` axes (solid major gridlines, major tick strokes, visible
spines) plus one eligible content Line2D renders strictly natively — zero
diagnostics, no Agg invocation — with geometry matching stock Agg within a
3 px ink-bounding-box tolerance, and the white figure background preserved
end to end (the D2 `background_rgba` seam fix from `wt/t_f62d90a3` is part
of this base).

## Artifacts

- `e2e_decorated_axes.py` — self-contained proof script (asserts canvas dims,
  per-ink bboxes within tolerance, background preservation, empty diagnostics).
- `pracad_native_vs_agg_compare.py` — parameterized PNG decoder/comparator.
- `native-vs-agg-comparison.txt` — recorded numeric comparison output.

## Recorded result

```text
strict diagnostics: ()
native canvas: 200x100; agg canvas: 200x100
red line: native bbox (20, 10, 179, 89), agg bbox (21, 11, 179, 89)
dark decoration: native bbox (16, 9, 180, 93), agg bbox (16, 10, 180, 94)
E2E PASS: decorated axes render strictly natively; geometry matches Agg
within tolerance and the figure background is preserved
```

Comparator output:

```text
native: 200x100 ch4; agg: 200x100 ch4
rgb samples beyond tol(40): 3491 of 60000 (5.818%); max channel delta: 255
red-line ink bbox  native: (20, 10, 179, 89)  agg: (21, 11, 179, 89)
dark deco ink bbox native: (16, 9, 180, 93)  agg: (16, 10, 180, 94)
```

Per ADR-0015 §5 byte identity with Agg is never asserted; exact Agg corner
parity is unprovable without a public miter-limit getter. The recorded
5.818%-of-samples delta above tolerance reflects anti-aliasing and blend
differences on decoration strokes (Agg draws spine/tick strokes black with
its own AA; the lane renders the artists' actual colors through the fixed §5
stroke surface), not missing or misplaced geometry — both ink classes occupy
the same ≤3 px-aligned regions in both rasters.

## Reproduction

```sh
export LD_LIBRARY_PATH=<gcc-lib>:<zlib-lib>   # per repo memory recipe
python research-evidence/t_d456087d/e2e_decorated_axes.py
```
