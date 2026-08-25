# LumenPlot

**Status: pre-alpha** · **Public API: unstable** · **Production use: not recommended**

LumenPlot is an independent, GPU-native scientific visualization engine with a
first-class Matplotlib adapter. This repository is an exploratory public
baseline, not a stable release or a production support commitment.

The current public direction is:

```text
Matplotlib -> adapter -> LumenPlot engine
```

Matplotlib remains the frontend and the source of plotting semantics at the
adapter boundary. The engine is independent of Matplotlib; the dependency is
one-way from Matplotlib through the adapter into the engine. The intended design
includes a hybrid path: supported capabilities use the engine, unsupported or
compatibility-sensitive cases use an explicit fallback, and an opt-in fast path
may serve large data. Fallbacks must be observable and documented. Unsupported
behavior must never silently degrade.

## Warning

This is **pre-alpha** software. APIs, file formats, performance, packaging, and
compatibility are subject to change. The public API is unstable, and production
use is not recommended. Matplotlib private APIs and arbitrary custom `Artist`
implementations are not promised to be fully compatible. A capability that is
not implemented or verified must be reported explicitly rather than presented
as equivalent behavior.

## Getting started (pre-alpha)

This section gets you from source checkout to a first rendered PNG. It is
kept consistent with the `examples/quickstart.py` script in this
repository, which performs the same steps and can be run directly after
installing (`python examples/quickstart.py`); if this section and that
example ever disagree, treat the example as the source of truth and this
README as stale.

### Prerequisites

- Python 3.11–3.14 (the packaged range of `lumenplot-mpl`)
- `numpy==2.4.6` and `matplotlib>=3.11,<3.12` (pinned-range dependencies;
  `pip install .` resolves them automatically)
- A Rust toolchain (the extension module is built from source via
  [maturin](https://www.maturin.rs); there are no binary wheels yet)

LumenPlot is **not published to PyPI**. Installation is from a clone of this
repository only:

```bash
git clone https://github.com/SoichiroYamane/lumenplot.git
cd lumenplot
pip install .
```

The install builds the Rust engine locally and registers the Matplotlib
backend entry point.

### Minimal example (strict mode, the default)

```python
import matplotlib

matplotlib.use("module://lumenplot_mpl.backend")  # before any figure work
from lumenplot_mpl.backend import FigureCanvasLumenPlot
from matplotlib import figure
from matplotlib.lines import Line2D

fig = figure.Figure(figsize=(4.0, 3.0), dpi=100)
canvas = FigureCanvasLumenPlot(fig)
ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
ax.axison = False         # strict mode requires axes decorations off
ax.add_line(
    Line2D(
        [0.0, 2.5, 5.0, 7.5, 10.0],
        [1.0, 3.0, 2.0, 4.0, 3.5],
        color="red",
        linewidth=2.0,
        solid_capstyle="butt",
        solid_joinstyle="miter",
    )
)
ax.set_xlim(0.0, 10.0)
ax.set_ylim(0.0, 5.0)
fig.savefig("quickstart.png", dpi=144)
```

Notes:

- The backend must be selected before any figure work (and before the stock
  Agg backend would be picked).
- Strict mode accepts exactly butt caps and miter joins; Matplotlib's
  defaults (`projecting`/`round`) are rejected rather than approximated,
  so the stroke style above is set explicitly.
- A successful native render leaves `fig.canvas.last_diagnostics` empty.

### What strict mode supports today

Strict mode (default) renders supported figures through the LumenPlot engine
and raises an explicit `LumenPlotUnsupportedError` for anything else. The
supported surface is deliberately narrow: `Line2D` artists on linear axes
with axes decorations off, solid (non-dashed) strokes without markers, and
the fixed style surface shown above (`butt` cap, `miter` join). PNG output
at the requested DPI.

Hybrid mode is opt-in per figure: it attempts the same native path first and,
only on an explicit unsupported-capability failure, falls back to the whole
frame with Matplotlib Agg, recording a diagnostic:

```python
from lumenplot_mpl.backend import FigureCanvasLumenPlot

canvas = FigureCanvasLumenPlot(fig, mode="hybrid")
```

Each render attempt republishes `fig.canvas.last_diagnostics`: a
fallback leaves the single whole-frame diagnostic there; nothing degrades
silently.

Anything beyond this surface — other artist types, log axes, titles, ticks,
text, markers, dashes — is out of scope for v1 and fails explicitly in
strict mode rather than rendering approximately. The authoritative contract
is [API-0005: Phase-3B public Matplotlib backend
surface](docs/architecture/api-0005-phase3b-public-matplotlib-backend-surface.md).

## Goals

- Establish an independent engine boundary for scientific visualization.
- Provide a first-class Matplotlib adapter without making Matplotlib a lower-
  level engine dependency.
- Keep fallback behavior explicit, testable, and visible to users.
- Add an opt-in large-data path only after correctness and reproducible
  measurements justify it.
- Record cross-cutting architecture decisions before implementation freezes a
  public contract.

## Non-goals for this baseline

- A stable public API or a production-ready renderer.
- Full compatibility with Matplotlib private APIs or every custom `Artist`.
- A claim that GPU execution, a fast path, or a particular output format is
  already implemented.
- Silent conversion, silent fallback, or silent loss of visual semantics.
- Performance claims without a reproducible benchmark and environment record.

## Current implementation status

The current source snapshot contains a nine-package, dependency-free Rust
workspace at version `0.1.0`. Phase-1A implements the native semantic kernel and
Phase-1B implements the minimum Rust facade, with local contract, visibility,
and repository-gate evidence. These are pre-alpha implementation slices, not a
completed v1 product, support matrix, or release. `crates/lumenplot` remains the
sole facade; the later packages remain private documentation-only stubs
following the accepted [facade and crate dependency graph](docs/adr/0003-facade-and-crate-dag.md).
Each package records the dual license, project repository, root README, and
`publish = false`. The current source contains no Python package,
first-class Matplotlib adapter, GPU renderer, separate raster package,
examples, or release packaging. Therefore those later components, and the full
v1 output/runtime behavior, are not described as implemented or supported.

No minimum supported Rust version (MSRV) is committed in this baseline. A local
edition or CI toolchain is not a public MSRV promise.

A superseded partial Rust/IR implementation is not part of this public baseline
and must not be presented as the current product design. The historical
CPU-only Matplotlib raster architecture record is retained for context and is
explicitly superseded by the accepted GPU-native architecture decision. The
canonical requirements, traceability record, and architecture documents are
the authoritative public narrative for this baseline.

## Verification commands

These are the repository gates observed during the read-only audit and are the
commands to run again after integration. Listing a command is not a claim that
the current partial working tree passes it.

```bash
cargo fmt --all -- --check
cargo test --locked --workspace --all-features
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
cargo metadata --locked --no-deps --format-version 1
nix flake check --all-systems --no-build --no-update-lock-file
git diff --check
```

The final publication gate also needs a dedicated secret scanner over the
approved working tree and reachable history. Do not treat a pattern-only scan
as equivalent to a dedicated scanner.

## Project documents

- [Canonical requirements](docs/requirements/lumenplot-v1.0.md)
- [Requirements traceability](docs/requirements/traceability-v1.0.md)
- [Roadmap](docs/roadmap.md)
- [Architecture decision record index](docs/adr/README.md)
- [Architecture overview and open decisions](docs/architecture/)
- [Contributing](CONTRIBUTING.md)
- [Support policy](SUPPORT.md)
- [Security policy](SECURITY.md)
- [Governance](GOVERNANCE.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [MIT license](LICENSE-MIT) and [Apache License 2.0](LICENSE-APACHE)

The paths above are the proposed public paths. An integration worker must
preserve them or update every link if the repository's canonical layout is
changed.

## Contribution and security

Public contributions should follow [CONTRIBUTING.md](CONTRIBUTING.md), the
[Code of Conduct](CODE_OF_CONDUCT.md), and [GOVERNANCE.md](GOVERNANCE.md).
Do not put secrets, private vulnerability details, or sensitive conduct reports
in public issues or pull requests; use the routes described in
[SECURITY.md](SECURITY.md) and [SUPPORT.md](SUPPORT.md).

## License

LumenPlot is released under the dual license **MIT OR Apache-2.0**. The default
project attribution is `Copyright 2026 LumenPlot contributors`. See
[LICENSE-MIT](LICENSE-MIT) and [LICENSE-APACHE](LICENSE-APACHE).

## Benchmark claims policy

The ranges **10M–100M data points** and **60/120 Hz** are unmeasured target
envelopes only. They are not achieved-throughput claims, compatibility claims,
or release criteria in this baseline. Any future performance statement must
include the workload, data shape, hardware, driver/runtime versions, rendering
settings, warm-up/repetition policy, output correctness checks, and a
reproducible benchmark command or artifact. Until then, describe these numbers
only as targets.
