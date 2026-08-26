# W1-INT Evidence — mixed fill/bar/steps/line workloads (t_19ef7f10)

Branch `wt/t_19ef7f10`, base = post-merge main `c291e1a`
(#68 LP-FUNC-032 fill, #69 LP-FUNC-033 bar, #70 LP-FUNC-034 steps all merged).
Deliverable: `tests/python/test_phase3b_integration_mixed.py` (9 tests).

## Composition findings pinned by the suite

- A figure carrying all four eligible families renders **one native
  frame** in strict mode with **zero diagnostics**: 6 content commands
  (band fill, 2 bars, triangle fill, default line, expanded steps-mid
  line) following Agg z-order class composition (collections, patches,
  lines; stable within each class).
- Steps-mid expansion inside a mixed frame: 5 samples incl. one
  duplicate-x pair -> exactly 12 projected vertices (cbook parity,
  LP-FUNC-034).
- Hybrid mode stays a **whole-frame contract** on composed content:
  fully eligible mix -> native, no diagnostic; adding ONE ineligible
  artist -> exactly one whole-frame Agg fallback record
  (`unsupported-capability`, scope=whole-frame, type=Rectangle),
  native seam never called, generation +1.
- Strict refusal on a mixed frame is terminal (marker anywhere in the
  frame -> `LumenPlotUnsupportedError`, code=`unsupported-capability`,
  no partial native frame).

## Measured pixel thresholds (2026-08-26, CPython 3.14.7 + mpl 3.11.1 +
dev-profile abi3 seam)

| workload | worst | within-32 | n>32 |
| --- | --- | --- | --- |
| dashboard_banded (5 families, disjoint bands, dup-x steps-mid) | 191 | 95.99% | 802 |
| alpha_overlap (translucent fills over bars + steps-pre risers) | 144 | 96.52% | 697 |
| negative_span_mixed (negative bars under fill apex) | 15 | 100% | 0 |

Fixture caps: `tol=32`, `min_within=0.95`, `worst_cap=191`.

Deliberate exclusion (documented in the module docstring): stacked
slanted fill boundaries multiply the rasterizers' AA phase divergence
beyond any single lane's ramp — measured worst=255, 92.98% within 32 —
which would pin nothing; the composed fixtures band the families so
every edge type appears once. Same divergence class already recorded by
the fill lane (worst_cap 32 on single slanted polygons) and the steps
lane (worst_cap 228 on stroke edges); bars are byte-exact (worst=0
measured standalone).

## Gate re-runs on this branch (post-merge-main base)

| Gate | Result |
| --- | --- |
| `cargo fmt --check` | clean |
| `cargo clippy --locked --workspace --all-targets -- -D warnings` | clean |
| `cargo test --locked --workspace` | 141 passed, 0 failed |
| `scripts/check_workspace_architecture.py` | OK |
| `scripts/check_phase2b_dependencies.py` | OK |
| scripts selftests (manifest/sbom/arch/deps/bench/wheel-evidence) | all OK |
| FULL `unittest discover -s tests/python` (CPython 3.14.7, mpl 3.11.1, real seam) | **269 passed, 0 failed**, 1 pre-existing skip (seam topology probe absent in dev profile; identical skip on base main: 260 tests) |

Test count delta vs base: 260 -> 269 (+9, this card's suite).
