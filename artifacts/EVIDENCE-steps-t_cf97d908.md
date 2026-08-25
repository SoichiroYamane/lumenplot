# t_cf97d908 — W1-steps: LP-FUNC-034 step drawstyles (Agg-parity eligibility extension)

Date: 2026-08-26 (JST) · Host: Linux 6.12.103, x86_64, NixOS
Environment: CPython 3.14.7 · matplotlib 3.11.1 · numpy 2.5.2 · lane abi3 native seam
(`lumenplot_mpl._native` with `render_frame_png`, built 2026-08-25)

## What landed

LP-MPL-020 four-mechanics eligibility extension admitting the Matplotlib step
drawstyle family (`steps-pre`, `steps-post`, `steps-mid`, and the historical
`steps` alias = pre):

1. **Whitelist entry** — unchanged (`Line2D` was already whitelisted); the
   style contract grows to admit exactly `_STEP_DRASTYLES`; every other
   non-default drawstyle value is still refused explicitly.
2. **Collector-trace expectation** — unchanged: one single-stroke
   `draw_path` per stepped line.
3. **Style contract** — stroke color/width/cap/join resolve identically with
   steps on; markers stay refused on step lines; unknown drawstyles stay
   rejected.
4. **Fixtures** — `tests/python/test_phase3b_steps.py`: geometry parity
   against matplotlib's own `cbook.STEP_LOOKUP_MAP` expansion via public
   getters (spec-level through the stubbed seam), style contract,
   monotonic-topology recurrence (flag C-3), decoded-pixel parity through the
   real seam, and both profile modes pinned.

Backend change: `_expand_step_vertices()` mirrors `pts_to_{pre,post,mid}step`
exactly (N kept samples -> 2N-1 vertices for pre/post/alias, 2N for mid);
`_EligibilityPreflight` admits the family and expands before projection.

## Measured pixel-parity thresholds (§5.4 oracle, recorded 2026-08-26)

Decoded RGBA8 comparison, strict native vs fresh Agg render of the same
Figure (200x100 @ dpi 100, red lw=2 staircase, 5 samples over [0,10]x[0,6]):

| workload            | within tol=32 | worst delta |
|---------------------|---------------|-------------|
| steps-pre           | 97.68%        | 228         |
| steps-post          | 97.60%        | 228         |
| steps-mid           | 97.47%         | 228         |

Fixture gate: >= 95% of pixels within tol=32 per channel AND worst <= 228
(the largest measured value). Every >32 pixel sits on a stroke edge; interiors
of axis-aligned runs are byte-exact. The identical divergence exists verbatim
on `default`-drawstyle strokes (measured: same 464-pixel >32 set, max 228), so
this is the pre-existing engine-wide stroke-AA phase characteristic (Agg 4px
scanline box filter vs tiny-skia analytic coverage), not a steps regression.
The merged fill lane's ratified fixtures pin fills (its tol=0 fixture passes
here at 99.2% exact, cap 32); strokes were never pinned tighter than this.
Thresholds must be re-measured if the renderer changes.

## Non-finite samples under step drawstyles: explicit refusal (decision)

Draft behavior dropped non-finite rows before expanding. Forensics against
matplotlib 3.11.1 showed that is NOT Agg's observable semantics:

- `cbook.pts_to_prestep` expands blindly (NaN propagates into the expanded
  arrays);
- Agg's path cleaning then re-pairs the surviving risers around the gap, so
  the rendered geometry is neither "drop the row" nor "bridge the gap"
  (measured: shifted-riser staircase, structural mismatch, not AA).

Replicating Agg's cleaner would couple the whitelist to matplotlib internals;
shipping our own drop-row expansion would silently diverge from the oracle.
Per LP-MPL-020 ("never by silent approximation"), stepped lines with any
non-finite sample refuse explicitly with the stable
`unsupported-capability` token; hybrid mode converts to the declared
single whole-frame Agg fallback (pinned by fixtures). The default drawstyle
keeps its historical row-filtering behavior unchanged (also pinned).
Single-sided NaN rows previously crashed with IndexError under the draft
filtering; they now take the same explicit refusal.

## Adapter fix surfaced by this lane (assembly-stage gate)

`_render_strict` consulted `preflight.reasons` once after `collect()` but
before `build_frame_spec()`; refusals recorded during geometry assembly
(`_line_command`: "mismatched or empty line data", "fewer than two finite
points") never gated the render — the frame silently rendered as bare
background in strict mode. Pre-existing on main (reproduces with a
default-drawstyle all-NaN line). Fixed with a second reasons gate immediately
after assembly, still before any seam call.

## Verification record

Commands (venv `~/lp-verify/venv-evidence`, LD_LIBRARY_PATH isolib recipe):

- `python -m unittest tests.python.test_phase3b_steps -v`
  -> Ran 23 tests, OK (skipped=1: seam exposes no topology probe; C-3
  evidence stays at the pure-recurrence fixtures)
- `python -m unittest discover -s tests.python -p "test_*.py"`
  -> Ran 476 tests, OK (skipped=2, both documented no-probe skips)
- `python scripts/check_workspace_architecture.py` -> OK
- `python -m unittest scripts.test_check_workspace_architecture`
  -> Ran 288 tests, OK
- `cargo test -p lumenplot-python` -> 16 passed; 0 failed
- `cargo fmt --check` -> clean (exit 0)
- `cargo clippy --all-targets -- -D warnings` -> clean (finished, no warnings)

No Rust-source changes are on this branch; the runs prove the tree stays at
the sibling lane's merged green state.
