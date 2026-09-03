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

#### macOS (Apple Silicon / `aarch64-darwin`)

On Apple Silicon, prefer the Nix development shell for the editable install:

```bash
nix develop -c bash -c 'pip install -e .'
```

The Darwin devShell supplies the `libiconv` dependency needed by the native
link step. In a non-Nix environment, expose the macOS SDK and prefer Apple's
clang before installing:

```bash
export SDKROOT="$(xcrun --show-sdk-path)"
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:${PATH}"
export CC="$(xcrun --find clang)"
export CXX="$(xcrun --find clang++)"
pip install -e .
```

The `xcrun` commands require the Xcode Command Line Tools (or Xcode) to be
installed. Keep the same Python environment active when running `pip install`.

LumenPlot is **not published to PyPI**. Installation is from a clone of this
repository only:

```bash
git clone https://github.com/SoichiroYamane/lumenplot.git
cd lumenplot
pip install .
```

The install builds the Rust engine locally and registers the Matplotlib
backend entry point. The source checkout intentionally does not contain a
platform-specific `lumenplot_mpl._native` extension; run `pip install .` (or an
equivalent maturin build) before native runtime tests. A source-only checkout
skips native-dependent tests, while an existing but unusable extension remains
a failure rather than being classified as setup.

### Minimal example (hybrid-explicit mode, the default)

```python
import matplotlib

matplotlib.use("module://lumenplot_mpl.backend")  # before any figure work
from lumenplot_mpl.backend import FigureCanvasLumenPlot
from matplotlib import figure
from matplotlib.lines import Line2D

fig = figure.Figure(figsize=(4.0, 3.0), dpi=100)
canvas = FigureCanvasLumenPlot(fig)
ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
ax.set_axis_off()         # this example keeps the frame undecorated (a fixture
                          # choice — decorated axes are strict-eligible too)
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

Strict mode (explicit) renders supported figures through the LumenPlot engine
and raises an explicit `LumenPlotUnsupportedError` for anything else. The
supported surface is deliberately narrow: `Line2D` artists on linear axes,
solid (non-dashed) strokes without markers, and the fixed style surface shown
above (`butt` cap, `miter` join), producing PNG output at the requested DPI.

Since [PR #63](https://github.com/SoichiroYamane/lumenplot/pull/63)
(ADR-0015 §4a), a standard `Axes` with decorations enabled
is also strict-eligible and renders natively: solid major gridlines, major
tick strokes (`markersize * dpi_eff / 72` px), and visible spines in the same
fixed `butt`/`miter` style. Decorated axes require `facecolor='none'` and
label-less ticks; minor ticks/gridlines, non-solid grids, titles, axis
labels, offset text, subplotspec/gridspec children, and non-exact `Axes`
subclasses are still refused with an explicit unsupported reason.

Hybrid mode is the default per figure: it attempts the same native path first
and, only on an explicit unsupported-capability failure, falls back to the
whole frame with Matplotlib Agg, recording a diagnostic. It can also be named
explicitly:

```python
from lumenplot_mpl.backend import FigureCanvasLumenPlot

canvas = FigureCanvasLumenPlot(fig, mode="hybrid")
```

The current staged constructor spelling is `mode="hybrid"` (the default) or
`mode="strict"`; it maps the bounded slice to the accepted
`hybrid-explicit`/`strict-common-2d` roles. The canonical three-profile names
and an end-to-end `accelerated-native` path remain later roadmap gates.

Each render attempt republishes `fig.canvas.last_diagnostics`: a
fallback leaves the single whole-frame diagnostic there; nothing degrades
silently.

Anything beyond this surface — other artist types, log axes, titles, tick
label text, markers, dashes — is out of scope for v1 and fails explicitly in
strict mode rather than rendering approximately. The authoritative contract
is [API-0005: Phase-3B public Matplotlib backend
surface](docs/architecture/api-0005-phase3b-public-matplotlib-backend-surface.md).

### PNG output

Successful native renders produce the deterministic PNG stream defined in
[ADR 0012: private line frame and deterministic PNG
contract](docs/adr/0012-private-line-frame-and-png-contract.md) as amended by
[ADR 0018](docs/adr/0018-user-facing-png-output-description.md): 8-bit RGBA,
non-interlaced, with an sRGB Perceptual chunk and contiguous `IDAT` chunks
compressed with DEFLATE. The stream contains exactly the PNG signature,
`IHDR`, `sRGB`, the `IDAT` chunks, and `IEND`; no `pHYs`, `gAMA`, `cHRM`,
`iCCP`, text, time, palette, or animation metadata is emitted. Dots-per-inch
metadata is deliberately absent, so pixel dimensions are set at render time
from the requested DPI rather than recorded in the file. Row filters stay
disabled so each pixel's bytes remain directly auditable after decompression.
Repeated encoding of the same figure on the same machine produces identical
bytes. Byte identity against Agg output is neither claimed nor expected, and
any standard PNG decoder can read the file.

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
- A claim that complete GPU execution, a fast path, or a particular output
  format is already supported across the v1 matrix.
- Silent conversion, silent fallback, or silent loss of visual semantics.
- Performance claims without a reproducible benchmark and environment record.

## Current implementation status

The current source snapshot contains a ten-crate Rust workspace at version
`0.1.0` plus a `python/lumenplot_mpl` package shipped by the
`lumenplot-mpl` distribution. Phase-1A implements the native semantic kernel;
Phase-1B the minimum Rust facade; Phase-2A/2B the private line-frame seam and the
deterministic CPU raster/PNG sink in `crates/lumenplot-export`; Phase-3A/3A2 the
hidden facade, private Python helper, and pinned manylinux wheel evidence; and
the first Phase-3B slice ships the strict-mode public Matplotlib backend with a
hybrid-explicit default, as documented in [Getting started](#getting-started-pre-alpha).
PR #89 additionally records bounded private RenderPacket validation,
offscreen wgpu line geometry/shader/readback tests, backend-neutral runtime and
viewer state-model tests, semantic input routing, a private line-only vector
PDF sink, and fail-closed benchmark validation. PR #91 adds a bounded logical
resource cache/lease/fence/device-generation model. These are pre-alpha
implementation slices with local evidence — not a completed v1 product,
support matrix, or release. The full semantic/layout frame, real window/present
loop, full renderer-owner resource lifecycle integration, text/font/export/accessibility
surface, real-GPU matrix, accelerated-native measurement, and release closure
remain open. `crates/lumenplot` remains
the sole public Rust facade, following the accepted [facade and crate dependency
graph](docs/adr/0003-facade-and-crate-dag.md). Each package records the dual
license, project repository, root README, and `publish = false`.

No minimum supported Rust version (MSRV) is committed in this baseline. A local
edition or CI toolchain is not a public MSRV promise.

A superseded partial Rust/IR implementation is not part of this public baseline
and must not be presented as the current product design. The historical
CPU-only Matplotlib raster architecture record is retained for context and is
explicitly superseded by the accepted GPU-native architecture decision. The
canonical requirements, traceability record, and architecture documents are
the authoritative public narrative for this baseline.

## Verification commands

The reproducible contributor gate enters the declared Nix environment, builds
the local package, uses a temporary writable Matplotlib cache, and runs the
locked Rust, Python, architecture, dependency, traceability, and repository
checks:

```bash
nix develop -c bash scripts/verify.sh
```

For an environment that already has the local package installed, the two
explicit bypasses are available for diagnosis only:

```bash
bash scripts/verify.sh --skip-install --skip-nix
```

The bypass command is not a replacement for the default gate: native runtime
tests must be run after a successful local build, and the Nix check must be
reported separately when it is skipped.

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
