# ADR 0001: Rust Matplotlib raster backend architecture

- Status: Superseded
- Date: 2026-08-20
- Decision owner: architecture-authority
- Recorded by: implementation-worker
- Scope: lumenplot v0.1

> **Superseded decision.** This historical ADR is retained as a record of the earlier headless raster-backend decision. The accepted replacement is [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md).
>
> The historical technical text below is not a current v1 contract. Public-safe sanitization removes private work-item identifiers and local artifact references without changing the historical decision being recorded.

## Context

The repository is currently a dependency-free Rust workspace baseline. It has
no plotting model, renderer, Python package, or product public API. The
architecture must therefore be fixed before implementation starts, rather than
allowing the first implementation to accidentally define the public model,
crate boundaries, ownership rules, and compatibility policy.

The product goal is a headless, non-interactive Matplotlib raster backend for
CPython. Matplotlib already owns the retained `Figure` / `Artist` model and its
layout, traversal, and frontend semantics. Lumenplot must not create a second
retained Figure or scene model that can become inconsistent with Matplotlib.
The initial product is deliberately narrower than a general plotting library:
PNG output and a deterministic CPU raster path are the first deliverable.

This decision records the architecture selected by the architecture-authority from the following
inputs:

- Historical repository architecture audit and constraint review.
- Historical Matplotlib backend-author contract research.
- Historical Rust raster, PyO3, NumPy, and packaging research.
- The official Matplotlib, tiny-skia, PyO3, rust-numpy, and maturin sources
  listed in [References](#references).

The research work is evidence for this decision. Temporary task workspaces and
research artifact paths are not part of the architecture contract.

## Decision

### Product scope and compatibility

Lumenplot v0.1 is a CPython-oriented, headless, non-interactive Matplotlib
raster backend. The supported initial range is:

- CPython `>=3.10`.
- Matplotlib `>=3.10,<3.12`.
- NumPy `>=1.26,<3`.

Free-threaded CPython is outside the initial support range. The first output
format is PNG only. GUI/window support, event loops, blitting, SVG, PDF, and a
persistent IR or wire format are out of scope.

The initial drawing scope is:

- solid path stroke and fill;
- line width, dash, cap, and join styles;
- rectangular clipping;
- ordinary text and mathtext through Matplotlib `TextToPath` semantics;
- axis-aligned RGBA images.

`usetex=True`, hatches, non-rectangular clip paths, and Gouraud triangles are
explicitly unsupported in v0.1. They must fail with `NotImplementedError`, not
silently degrade. Marker and collection calls may begin with correctness-first
Matplotlib fallback behavior; optimized batching is a later performance
change, not a second retained scene model.

### Public API

The distribution package is named `lumenplot`, and the backend module is
`lumenplot.backend`. Both supported loader forms are required:

```python
matplotlib.use("module://lumenplot.backend")
matplotlib.use("lumenplot")
```

The package metadata registers the latter through the Matplotlib backend entry
point named `lumenplot` in the `matplotlib.backend` group.

The versioned Python surface consists of:

- `lumenplot.backend.FigureCanvasLumenPlot`, a headless
  `FigureCanvasBase` implementation;
- `lumenplot.backend.FigureManagerLumenPlot`, a headless
  `FigureManagerBase` implementation;
- module aliases `FigureCanvas` and `FigureManager`;
- the canvas contract that Matplotlib invokes.

The renderer and `lumenplot._native` extension module are private
implementation details. Rust crates, Rust IR types, and FFI functions are not
user-facing v0.1 API.

`FigureCanvasLumenPlot` provides this output method:

```python
def print_png(
    self,
    filename_or_obj,
    *,
    metadata=None,
    pil_kwargs=None,
    **kwargs,
):
    ...
```

It accepts both a path-like destination and a binary file-like object. PNG
encoding follows the public Matplotlib `matplotlib.image.imsave` / Pillow path;
Rust owns RGBA rasterization, not PNG metadata or codec compatibility. The
adapter must accept the keyword arguments that Matplotlib can pass to a
third-party print method and must map errors consistently:

- unsupported capability: standard `NotImplementedError`;
- invalid user input, dimensions, shapes, codes, or values: `ValueError`;
- internal rendering or native bridge failure: `RuntimeError`.

No compatibility burden is inherited from the current Rust baseline because
it has no existing product API.

### Dependency direction and crate/module boundaries

The dependency graph is fixed as follows:

```text
Python Matplotlib adapter
  -> lumenplot._native (crates/lumenplot-python)
       -> lumenplot-raster (crates/lumenplot-raster)
            -> lumenplot (crates/lumenplot, core/IR)
```

The boundaries are enforced by Cargo dependencies and module visibility:

- `crates/lumenplot` remains the dependency-free, backend-neutral core and IR
  package. It is an internal workspace package with `publish = false`.
- `crates/lumenplot-raster` is the concrete deterministic CPU renderer. Its
  direct product dependencies are `lumenplot` and `tiny-skia 0.12.0` only. It
  does not enable tiny-skia PNG encoding, text, or GPU features and does not
  depend on Matplotlib, Python, or NumPy.
- `crates/lumenplot-python` builds the `cdylib` extension
  `lumenplot._native`. It depends on the core, raster crate, PyO3 `0.29.2`,
  and rust-numpy `0.29.0`.
- `python/lumenplot/backend.py` is the pure-Python Matplotlib adapter. It owns
  Matplotlib class inheritance, backend loading, Artist-facing fallback
  behavior, text-path conversion, output dispatch, and Python exception
  translation.
- The root `pyproject.toml` and maturin `1.14.1` define packaging. The native
  extension targets `abi3-py310` for the initial CPython support range.

The dependency direction is one-way. Lower Rust crates must not import
Matplotlib or Python objects, and the core must not retain NumPy borrows,
`PyObject` values, or raster backend handles. No reverse dependency or
cross-layer escape hatch is part of v0.1.

A public `Backend` trait is intentionally not introduced yet. The immutable IR
and Cargo dependency graph are the backend boundary until a second concrete
backend exists and demonstrates that a trait abstraction is needed.

### Data contract and in-memory IR

The backend-neutral core uses the following names:

- `FrameSpec`;
- mutable `FrameBuilder`;
- immutable finalized `Frame`;
- ordered `Command`;
- `Path` and `PathCode`;
- `Affine2D`;
- `Color`;
- `Stroke`;
- `ClipRect`;
- `Image`.

Fields remain private and values are created through validated constructors.
The initial `Command` variants are path and image commands. Commands preserve
compositing order; later commands are composited after earlier commands.
`FrameBuilder` exists for one draw or print operation and is finalized before
rasterization. A `Frame` is process-local and in-memory only. It has no serde,
serialization, persistence, wire-format, or independent versioning contract.

The numerical and pixel contract is:

- Coordinates are Matplotlib display-space physical pixels, with lower-left
  origin, x increasing right, y increasing up, and `f64` values.
- `Affine2D` stores `(a, b, c, d, e, f)` with Matplotlib `to_values()`
  semantics: `x' = a*x + c*y + e` and `y' = b*x + d*y + f`.
- Path codes and non-finite/NaN normalization are checked and normalized in the
  Python bridge. The core receives only valid path values and does not infer
  Matplotlib path semantics from malformed input.
- Line widths and dash values remain in points in the IR. The raster boundary
  converts points to pixels using `dpi / 72` exactly once.
- Colors are finite, unpremultiplied sRGB values in `[0, 1]`.
- The public raster result is contiguous, top-to-bottom, unpremultiplied sRGB
  RGBA8 with shape `(height, width, 4)`. Any renderer-native premultiplied
  representation is converted at the raster boundary, and the y flip occurs
  at that boundary once only.
- Frame dimensions, DPI, array dtype/shape requirements, path code/value
  validity, and checked allocation sizes are validated. Invalid values and
  overflow become errors rather than panics.

The bridge validates NumPy views while the GIL is held and copies the required
input data into Rust-owned vectors and IR values. The core and raster crates do
not retain borrowed Python or NumPy memory.

### Concurrency and lifecycle

Matplotlib remains the owner of `Figure`, `Artist`, and canvas lifecycle. A
renderer creates a fresh `FrameBuilder` for each draw or print operation; the
renderer and builder are not shared re-entrant objects.

The native call sequence is:

1. Python enters the adapter with the GIL held.
2. The bridge validates Matplotlib values and NumPy views and copies the data
   needed for the frame into Rust-owned IR and vectors.
3. The builder is finalized into an immutable `Frame`.
4. Only the raster computation over owned data may run without the GIL; it must
   not access Python objects, NumPy borrows, or invoke callbacks.
5. The completed Rust-owned RGBA `Vec<u8>` is transferred to NumPy/output
   handling after Python execution resumes.

There is no global mutable renderer state, async pipeline, worker thread,
background callback, or lock-based shared renderer in the baseline. The
baseline is single-threaded and deterministic. Renderer methods must not call
back into Matplotlib or synchronously re-enter the same canvas. Any future
parallel or asynchronous design requires a separate architecture decision.

### Performance

A Python point-by-point drawing loop is prohibited. One Matplotlib primitive
callback should result in at most one high-level FFI record/batch call. Marker
and collection correctness fallbacks may initially expand work inside the
Python/Rust boundary, but the performance path will use shared geometry and
instance arrays in a batch call rather than one FFI call per marker or point.

Per-frame allocation is limited to a bounded set of owned IR data, the
renderer pixmap, and the final RGBA output. Rayon, GPU execution, persistent
resource caches, and serialization are not introduced for the MVP.

No absolute speed claim is made by this ADR. Follow-up benchmarks will record
baseline behavior for:

- a 100k-point line;
- repeated markers;
- a path collection;
- a 1024x768 basic plot.

Those benchmarks must include FFI call count and the allocation/copy path, not
only wall-clock render time. Changes to batching, allocation reuse, caching,
parallelism, or GPU execution require measurements against these baselines.

## Rejected alternatives

### Retained Rust scene or Figure model

Rejected because Matplotlib already retains the authoritative Figure/Artist
model. A second Rust scene would duplicate z-order, visibility, layout, text,
canvas switching, and lifecycle state, creating synchronization and stale-data
risks. Rust owns a per-frame snapshot, not a long-lived high-level scene.

### Immediate direct raster with no per-frame IR

Rejected because direct point-to-pixel calls would couple Python traversal to
raster implementation, make validation and compositing order harder to test,
and encourage one FFI call per point. The selected per-draw immutable IR keeps
the boundary small while remaining short-lived; it is not a persistent or
user-visible scene model.

### `raqote` or `skia-safe` as the initial raster backend

Rejected for the v0.1 baseline. `tiny-skia 0.12.0` provides a pure-Rust,
headless CPU path with a smaller native dependency and release/build surface.
`raqote` has useful raster features but its optional text path introduces
platform font dependencies and its pixel representation needs additional
conversion policy. `skia-safe` offers broader capabilities but introduces
Skia C++/bindgen/toolchain, native library, binary-cache, and licensing
complexity that is not justified by the initial PNG/path scope. These crates
can be reconsidered only through a new decision and parity tests.

### Public `Backend` trait in v0.1

Rejected as premature API surface. There is one concrete renderer and no
second backend contract to validate. A public trait would freeze object-safety,
lifetime, capability, and error choices before their use cases exist. Cargo
crate boundaries and immutable IR provide sufficient separation for the MVP.

### Native Rust text renderer

Rejected for the initial text path. Matplotlib `TextToPath` preserves ordinary
text and mathtext font selection, metrics, and parser semantics at the
adapter boundary without adding a second font/layout stack. Native text would
add font, shaping, hinting, cache, and platform dependencies. TeX remains
explicitly unsupported rather than being silently approximated.

### Parallel CPU or GPU rasterization in the MVP

Rejected until correctness, ownership, and measurements justify it. Parallel
or GPU work adds ordering, alpha compositing, device/resource lifecycle,
thread-safety, synchronization, portability, and deterministic-output policy.
The owned immutable frame leaves a future extension point without committing
v0.1 to those costs.

### Rust PNG encoding

Rejected for the public output path. Matplotlib's `imsave` / Pillow route owns
PNG metadata, DPI chunks, file-like behavior, and `pil_kwargs` semantics. A
Rust PNG encoder would duplicate or subtly diverge from that contract and
would add codec dependencies. Rust returns RGBA; Python performs PNG output.

### Generic `PyBuffer` as the primary bridge contract

Rejected for v0.1. Matplotlib already supplies typed NumPy arrays, and the
NumPy bridge can validate the required dtype, shape, and ownership before
copying. Accepting arbitrary buffer exporters would add format, stride,
read-only, lifetime, mutation, and ABI policy that is not needed for the
initial backend. A future generic-buffer API must be separately specified and
must not weaken the owned-copy rule.

### Persistent or versioned Rust IR

Rejected for the initial release. Persistence would require schema ownership,
serialization compatibility, migration, and security review before the
renderer semantics are stable. The IR is intentionally process-local and
private until a real replay or storage requirement exists.

## Compatibility and consequences

### Positive consequences

- Matplotlib's existing Figure/Artist, layout, and retained-model semantics
  remain authoritative.
- The Python adapter contains compatibility-sensitive Matplotlib behavior,
  while the Rust core remains backend-neutral and dependency-free.
- The FFI boundary has explicit ownership and GIL rules, and raster work can be
  tested without Python object lifetimes.
- PNG metadata and file-like output reuse Matplotlib/Pillow behavior instead of
  creating a second output contract.
- The initial dependency graph is small and suitable for deterministic,
  headless CPU builds.
- The immutable per-frame IR gives later batching and a possible future second
  backend a controlled internal seam without making it public now.

### Compatibility obligations and risks

- The adapter must support both `module://lumenplot.backend` and the
  `lumenplot` entry point across Matplotlib 3.10 and 3.11. The Python layer
  must isolate version-sensitive collection keyword differences such as
  `hatchcolors`.
- Third-party Matplotlib print methods can receive optional keywords without
  the same filtering as built-in methods. `print_png` therefore accepts and
  explicitly handles the required keyword path rather than relying on a
  narrow filename-only signature.
- The public `filetypes` map must advertise PNG only until another
  `print_<format>` implementation exists.
- Text output can vary with fonts, FreeType, Pillow, operating system, and
  rasterization details. Tests must use explicit fixtures and tolerances rather
  than assuming universal byte-identical images.
- tiny-skia's capability gaps and its internal pixel representation must not
  leak through the public RGBA contract. Unsupported features must raise the
  documented error.
- Copying Python inputs into owned Rust memory has a cost and a bounded memory
  requirement; benchmark records must make that cost visible.
- `abi3-py310` does not imply support for free-threaded CPython or arbitrary
  buffer exporters. Those are separate compatibility decisions.

## Test strategy

The current repository remains implementation-free apart from this ADR and its
index. The existing Rust gates must continue to pass before and after future
implementation work:

```text
cargo fmt --all -- --check
cargo test --workspace
cargo clippy --workspace --all-targets --all-features
```

The implementation plan must add the following verification layers:

1. **Package and loader smoke tests:** import the installed package, select the
   backend through both loader forms, verify `FigureCanvasLumenPlot`,
   `FigureManagerLumenPlot`, aliases, headless manager behavior, and repeated
   Figure creation/destruction.
2. **PNG contract tests:** save to a path and binary file-like object, exercise
   DPI, metadata, `pil_kwargs`, supported filetypes, repeated save, temporary
   canvas/DPI restoration, and unexpected third-party print keywords.
3. **IR validation tests:** cover dimensions, overflow, finite values, path
   codes including `MOVETO`, `LINETO`, `CURVE3`, `CURVE4`, `CLOSEPOLY`, and
   `codes=None`; affine values; private validated constructors; command order;
   rectangular clip; and invalid-input error mapping.
4. **Raster semantic tests:** cover solid stroke/fill, dash/cap/join,
   alpha/color handling, RGBA image input, image clipping, DPI scaling, row
   orientation, output shape/contiguity/channel order, and the single y-flip
   boundary. Compare supported cases with Matplotlib Agg using documented
   tolerances rather than an unconditional exact-pixel requirement.
5. **Text and fallback tests:** cover ordinary text and mathtext through
   `TextToPath`, metrics, baseline, rotation, and DPI. Verify that TeX,
   hatches, non-rectangular clip paths, and Gouraud triangles raise
   `NotImplementedError`.
6. **Collection tests:** verify correctness-first marker and path-collection
   fallback semantics, transforms, offsets, colors, and command ordering. Add
   batch-call and shared-geometry tests when the optimization is implemented.
7. **Lifecycle/GIL tests:** verify that frame data remains valid after Python
   inputs go out of scope, no Python object is accessed during detached raster
   work, repeated draw/print is safe, and no global mutable renderer state is
   required.
8. **Packaging matrix:** build and import `abi3-py310` artifacts across the
   supported CPython/Matplotlib/NumPy range. Free-threaded Python is a negative
   or excluded test case until separately adopted.
9. **Performance baselines:** benchmark the four workloads in the performance
   section and record FFI calls, allocations/copies, output dimensions, and
   deterministic repeatability alongside elapsed time.

## Residual risks

- Matplotlib's backend API has version differences and some renderer/collection
  details are provisional. The adapter must keep compatibility code at the
  Python edge and test both supported minor series.
- The backend does not promise full Agg pixel identity. Font installation,
  FreeType/Pillow versions, anti-aliasing, image interpolation, and alpha
  rounding can produce platform-dependent differences.
- Matplotlib's full renderer contract includes primitives deliberately outside
  this MVP. Unsupported behavior must remain explicit so that users do not
  mistake silent degradation for compatibility.
- The Python-to-owned-IR copy is a correctness and lifetime safeguard but may
  dominate large-image or high-frequency workloads. The required benchmarks
  are needed before changing that rule.
- NumPy and PyO3 ABI/limited-API behavior, wheel tags, and platform packaging
  require CI coverage beyond the current Rust-only workspace.
- No public Rust API, persistent IR schema, second backend, parallel renderer,
  or GPU lifecycle is defined. Each is intentionally deferred and requires a
  new architecture review before being introduced.

## References

### Historical decision inputs

The original decision used an internal repository audit, Matplotlib backend-contract research, and Rust raster/PyO3/NumPy/packaging research. Private work-item identifiers and local artifact references are omitted from this public copy.

### Matplotlib and Python

- Matplotlib, “Writing a backend -- the pyplot interface”:\
  https://matplotlib.org/stable/users/explain/figure/writing_a_backend_pyplot_interface.html
- Matplotlib, “Backends” and backend API versions: \
  https://matplotlib.org/stable/users/explain/figure/backends.html#backend-api-versions
- Matplotlib v3.11.1 `backend_bases.py` (`RendererBase`,
  `GraphicsContextBase`, `FigureCanvasBase`, `FigureManagerBase`):\
  https://github.com/matplotlib/matplotlib/blob/v3.11.1/lib/matplotlib/backend_bases.py
- Matplotlib v3.11.1 backend registry and template: \
  https://github.com/matplotlib/matplotlib/blob/v3.11.1/lib/matplotlib/backends/registry.py\
  https://github.com/matplotlib/matplotlib/blob/v3.11.1/lib/matplotlib/backends/backend_template.py
- Matplotlib v3.11.1 Agg output implementation: \
  https://github.com/matplotlib/matplotlib/blob/v3.11.1/lib/matplotlib/backends/backend_agg.py
- Matplotlib v3.11.1 Path and affine transform sources: \
  https://github.com/matplotlib/matplotlib/blob/v3.11.1/lib/matplotlib/path.py\
  https://github.com/matplotlib/matplotlib/blob/v3.11.1/lib/matplotlib/transforms.py
- Matplotlib stable `TextToPath` API: \
  https://matplotlib.org/stable/api/text_api.html
- Matplotlib stable thread FAQ and v3.11.1 testing guide: \
  https://matplotlib.org/stable/users/faq.html#work-with-threads\
  https://github.com/matplotlib/matplotlib/blob/v3.11.1/doc/devel/testing.rst
- Python C API, thread states and the GIL: \
  https://docs.python.org/3/c-api/threads.html

### Rust raster and packaging

- tiny-skia 0.12.0 crate and API: \
  https://crates.io/crates/tiny-skia/0.12.0\
  https://docs.rs/tiny-skia/0.12.0/tiny_skia/
- PyO3 0.29.2 building/distribution and parallelism: \
  https://pyo3.rs/v0.29.2/building-and-distribution.html\
  https://pyo3.rs/v0.29.2/parallelism.html
- PyO3 0.29.2 `PyBuffer` documentation: \
  https://docs.rs/pyo3/0.29.2/pyo3/buffer/struct.PyBuffer.html
- rust-numpy 0.29.0 API and borrowing rules: \
  https://docs.rs/numpy/0.29.0/numpy/\
  https://docs.rs/numpy/0.29.0/numpy/borrow/index.html
- maturin 1.14.1 configuration and distribution: \
  https://maturin.rs/config.html\
  https://maturin.rs/distribution.html
