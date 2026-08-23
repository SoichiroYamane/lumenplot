# API 0003: Phase-3A Python, NumPy, and private line/PNG helper

- Status: **Accepted staged Phase-3A contract; Phase-3A2 helper/package/builder
same-wheel evidence recorded (CI-local manifest; GIL 3.11–3.14 four-cell);
Phase-3B public Matplotlib contract open**
- Date: 2026-08-21
- Decision owner: architecture-authority
- Recorded by: implementation-worker
- Scope: O-02P/O-09 Phase-3A CPython/abi3/NumPy ownership and private native helper
- Governing architecture: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](../adr/0002-gpu-native-engine-and-matplotlib-adapter.md)
- Boundary record: [ADR 0003 — facade and crate dependency graph](../adr/0003-facade-and-crate-dag.md)
- Error record: [API 0002 — errors, capabilities, and fallback](api-0002-errors-capabilities-fallback.md)
- Governing staged decision: [ADR 0013 — hidden line/PNG facade and private Python helper](../adr/0013-hidden-facade-private-python-line-png.md)
- Phase-3A2 evidence decision: [ADR 0014 — pinned manylinux wheel evidence](../adr/0014-phase3a2-pinned-manylinux-wheel-evidence.md)
- Open-decision records: [O-09 — Python ABI and NumPy ingestion policy](open-decisions.md#o-09-python-abi-and-numpy-ingestion-policy) and [O-10 — Matplotlib compatibility and profile matrix](open-decisions.md#o-10-matplotlib-compatibility-and-profile-matrix)

This record narrows API 0003 to the first implementable, owned Phase-3A
vertical slice. It records no Python product source, package artifact, wheel,
Matplotlib dependency, backend entry point, or support result. The broad v1
Matplotlib requirements remain normative, but the public Phase-3B result,
diagnostic, warning, canvas, fallback, profile, generation, and file/path
schemas are deliberately open until the private helper produces real evidence.

## Requirement references

The staged boundary supports the ownership and bridge portions of `LP-DATA-001`,
`LP-DATA-006`, `LP-DATA-007`, `LP-SEC-004`, and `LP-MPL-001` through `LP-MPL-017`
in the [accepted requirements](../requirements/lumenplot-v1.0.md). A Phase-3A
helper is not completion evidence for the full v1 adapter rows.

## Context and phase boundary

The merged Phase-2A line-frame and Phase-2B deterministic PNG sink provide a
bounded private Rust/export path. The next seam must carry owned values across
Python without leaking engine/export internals, borrowed NumPy memory, or a
premature public Matplotlib schema.

Phase-3A has two ordered implementation slices, with the second slice governed
by its own accepted evidence contract:

1. the exact `lumenplot::__private` Rust facade in [ADR 0013](../adr/0013-hidden-facade-private-python-line-png.md);
2. the private `_native.render_line_png` helper and local package/wheel evidence
   over that integrated seam; [ADR 0014](../adr/0014-phase3a2-pinned-manylinux-wheel-evidence.md)
   fixes the builder, same-wheel matrix, and CI-local manifest boundary for this
   slice without claiming that its implementation exists.

Phase-3A is helper-only. It has no `backend.py`, no Matplotlib import or
dependency, no `matplotlib.backend` entry point, no public `render_png`, no
result/diagnostic/warning types, and no public canvas. A separate accepted
Phase-3B record is required before any of those surfaces are implemented.

## Decision

### 1. Identity and staged package layout

The intended identity is:

- distribution: `lumenplot-mpl`;
- import package: `lumenplot_mpl`;
- private extension: `lumenplot_mpl._native`;
- later reserved backend module: `lumenplot_mpl.backend`.

The future helper-only source layout is
`python/lumenplot_mpl/{__init__.py,_native.pyi,py.typed}` with a repository-root
`pyproject.toml`, built through `crates/lumenplot-python/Cargo.toml`. This
recording lane adds none of those files, manifests, lockfile entries, CI
dependencies, package artifacts, or publication settings. The local evidence
package remains unpublished.

The Rust crate DAG remains exactly:

```text
lumenplot-python -> lumenplot -> {lumenplot-engine, lumenplot-export}
```

There is no direct Python-to-engine/export edge and no new bridge crate.

### 2. Exact private native function

The only Phase-3A Python-visible native function is:

```text
lumenplot_mpl._native.render_line_png(
    x, y, *,
    viewport, canvas, plot_rect,
    logical_units_per_inch, output_dpi,
    line_rgba, line_width, background_rgba,
) -> bytes
```

The function delegates to the exact owned Rust types and operation in
[ADR 0013](../adr/0013-hidden-facade-private-python-line-png.md). Geometry is
top-left `DisplayLogical`; `viewport` is `[x_min,x_max,y_min,y_max]`, `canvas`
is `[width,height]`, and `plot_rect` is `[x_min,y_min,x_max,y_max]`. Color
arguments are four integer channels in `0..=255`. There is no topology option:
the helper is one full-resolution `ArbitraryXY` series, linear axes, uniform
solid Butt/Miter/limit-4 style, and PNG only. It returns owned bytes and no
diagnostics.

The Rust facade repeats equal-length, finite/infinity, NaN-gap, exact maximal
range, geometry, style, DPI, checked-arithmetic, ceiling, and PNG validation.
The request is copied into owned f64 vectors and consumed by a synchronous,
temporary Scene/frame/export operation. No Scene, borrow, pointer, callback,
worker, cache, output target, or Python object crosses the owned detached
interval.

### 3. Candidate dependencies and ABI gate

Add these exact candidates only in the later implementation lane and only
after the evidence gate passes:

```toml
pyo3 = { version = "=0.29.2", default-features = false,
         features = ["macros", "extension-module", "abi3-py311"] }
numpy = { version = "=0.29.0", default-features = false }
```

The PEP-517 build frontend is exactly `maturin==1.14.1`. Candidate metadata
uses `Requires-Python >=3.11,<3.15`. The initial runtime evidence pin is
exactly `numpy==2.4.6`; it is not a runtime support range or a NumPy ABI
promise. `abi3-py311` authorizes only GIL-enabled CPython 3.11, 3.12, 3.13,
and 3.14 evaluation. It is not a LumenPlot C ABI, NumPy ABI guarantee,
platform result, or future-CPython promise.

No `abi3t`/free-threaded, PyPy/GraalPy, handwritten NumPy C API/layout/header
or symbol contract, generic Buffer Protocol, DLPack, zero-copy, borrowed
escape, or project unsafe code is accepted. Dependency build/unsafe surfaces,
the exact lock graph, checksums, licenses, SBOM/notices, maturin build
surface, wheel repair, and provenance remain evidence gates.

### 4. Exact NumPy ingestion policy

Accept only exact built-in NumPy `ndarray` objects, not ndarray subclasses or
masked arrays. Each input is one-dimensional, equal-length, aligned, and
native-endian `float32` or `float64`, with at most `1_000_000` values. Safe
logical positive, negative, and zero strides are accepted. Read-only and
writable arrays are both accepted and are never mutated.

Reject integer, boolean, object, complex, float16, structured, non-native-
endian, unaligned, wrong-dimensional, masked, subclass, and malformed-byte-span
inputs with sanitized `invalid-input`. The caller must not mutate either array
concurrently during the call; LumenPlot provides no synchronization for that
misuse. Mutation after the copy cannot affect output.

While the GIL is attached, the helper validates dtype, shape, endianness,
alignment, stride, capacity, and values, traverses logical order, treats NaN
in either coordinate as a gap, rejects every infinity, builds exact
source-index maximal finite ranges, and copies immediately to owned f64
vectors. Every NumPy/Python borrow and object reference is dropped before
`Python::detach`. Only the pure-owned request/render/output interval may run
detached. The bridge reattaches before constructing Python bytes or an
exception. No Python object, borrow guard, pointer, callback, lock, worker,
Scene, or output target crosses the detached interval. Independent one-shot
calls are reentrant and use no global mutable state.

### 5. Python error boundary

`lumenplot_mpl.LumenPlotError(RuntimeError)` is the only Phase-3A LumenPlot
exception. It has read-only string observations `code`, `category`, and
`message`, and `str(error) == message`. Values are the exact lowercase
API-0002 tokens. There are no subclasses, Python enums, numeric discriminants,
parsers, JSON/wire identity, stable repr or message wording, Rust cause, or
panic payload. Semantic input and bridge failures use this class and are
raised from `None`.

Python call-binding errors remain `TypeError`; interpreter allocation may remain
`MemoryError`; `KeyboardInterrupt` and `SystemExit` remain native exceptions.
Rust-controlled allocation failure maps to `out-of-memory`/`resource`; creating
the final Python `bytes` may raise native `MemoryError`. Device loss and OOM
are never fallback reasons.

The hidden Rust `BridgeError` mapping is exhaustive and leaves existing
`PublicError` mapping unchanged:

| Export source | Code | Category |
| --- | --- | --- |
| `InvalidInput` | `invalid-input` | `input` |
| `UnsupportedCapability` | `unsupported-capability` | `capability` |
| `CapacityExceeded` | `invalid-input` | `input` |
| `AllocationFailed` | `out-of-memory` | `resource` |
| `EncodingFailed` | `internal` | `internal` |
| `Internal` | `internal` | `internal` |

Category derives from code. Messages are sanitized non-contract text,
`source()` is `None`, and unexpected Rust panics are redacted to
`internal`/`internal`.

### 6. Wheel and runtime evidence gate

Before Phase-3A Python integration is accepted, build one locked
`cp311-abi3` `manylinux_2_28` x86_64 single-wheel artifact and test that same
artifact in clean GIL-enabled CPython 3.11, 3.12, 3.13, and 3.14 environments
with exactly NumPy 2.4.6. The matrix covers install/import, extension
initialization, all accepted/rejected dtype/stride/alignment/gap/error/
ownership cases, detached rendering, bytes ownership, and error redaction.
It also covers wheel metadata/`RECORD`, auditwheel, dependency/license/SBOM,
and provenance checks.

The wheel tag alone proves nothing. macOS, Windows, aarch64, universal2,
Windows ARM64, musllinux, other artifacts, free-threaded interpreters,
non-CPython interpreters, and package publication are unsupported or unclaimed
until separate evidence and a reviewed decision exist.

[ADR 0014](../adr/0014-phase3a2-pinned-manylinux-wheel-evidence.md) records the
accepted direct manylinux builder, immutable image/tag/digest and tool inputs,
locked/offline build, explicit GIL CPython interpreter paths, fresh-venv
same-wheel matrix, auditwheel/ELF/abi3/SBOM checks, action pins, and exact
CI-local `phase3a2-wheel-evidence.json` schema. This record remains a contract
only: no wheel, package, workflow, or runtime result is claimed until that
evidence is generated and reviewed.

## Phase-3B boundary remains open

The public-backend research supplies mandatory inputs to a later decision; it
does not authorize Phase-3B implementation or freeze a public schema. That
decision must at minimum preserve:

- evaluate exactly Matplotlib 3.11.1 with backend API 1.1; this is a future
  Phase-3B evidence target, not a Phase-3A dependency or support result;
- use documented public Matplotlib APIs only; `_Backend`, `_renderer`, `_api`,
  `_pylab_helpers`, any `matplotlib._*` path, private artist/transform/cache
  helpers, and undocumented `Axes.axison` are forbidden and are not a contract;
- an exact eligible object whitelist and public `RendererBase` collector before
  native allocation/output;
- the exact eligible collector trace of one Figure-background `draw_path` plus
  one Line2D `draw_path`; axes patch, spines, ticks, text, markers, images,
  collections, mesh/Gouraud, custom artists, and every other renderer callback
  are excluded and must cause explicit unsupported handling;
- rejection of fixed-style mismatches rather than silent approximation;
- 72 DisplayLogical points per inch, effective savefig DPI as output DPI, and
  bottom-left-to-top-left geometry mapping with callback/source reconciliation;
- an explicit non-PNG guard rather than a base-class backend switch;
- only a future public whole-frame `FigureCanvasAgg` fallback, never a partial
  native/Agg composite;
- no fallback after invalid input, capacity/overflow, allocation/OOM,
  encoding/internal/panic, reentrancy/stale publication, or I/O failure; and
- Figure/Artist authority with no non-reentrant lock held across public
  callbacks.

The public result, diagnostic, warning, canvas, fallback, profile, generation,
and file/path schemas require that separate accepted contract. No provisional
`PngResult`, `FallbackDiagnostic`, `LumenPlotFallbackWarning`, `render_png`, or
canvas property schema is adopted here.

## Consequences and residual risks

- The engine remains independent of Python and Matplotlib, and the accepted
  crate DAG remains unchanged.
- The first Python slice has a small, auditable ownership boundary but no
  end-user Matplotlib backend or public fallback/result surface.
- NumPy arrays are copied under the GIL; concurrent caller mutation is an
  explicit caller responsibility, not a hidden synchronization feature.
- A single Linux wheel matrix is not cross-platform support, and an abi3 tag is
  not runtime evidence.
- Full v1 adapter, Matplotlib compatibility, fallback, output, platform,
  benchmark, and release claims remain pending.

## Verification and evidence boundary

This record and [ADR 0014](../adr/0014-phase3a2-pinned-manylinux-wheel-evidence.md)
change the accepted documentation contract and conditional architecture
inventory only. They do not add Rust/Python product source, Cargo/Python
manifests, `Cargo.lock`, CI dependencies, packages, or publication settings.
The requirements traceability registry remains `Not implemented`, `Not
measured`, or `environment required` for full-v1 rows until their evidence
gates close.

## Related records

- [ADR index](../adr/README.md)
- [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](../adr/0002-gpu-native-engine-and-matplotlib-adapter.md)
- [ADR 0003 — facade and crate dependency graph](../adr/0003-facade-and-crate-dag.md)
- [ADR 0011 — Phase-1B facade namespace and observation traits](../adr/0011-phase1b-facade-namespace-observation-traits.md)
- [ADR 0014 — Phase-3A2 pinned manylinux wheel evidence](../adr/0014-phase3a2-pinned-manylinux-wheel-evidence.md)
- [Phase-3A2 wheel and same-wheel evidence contract](phase3a2-manylinux-wheel-evidence.md)
- [ADR 0012 — private line frame and deterministic PNG contract](../adr/0012-private-line-frame-and-png-contract.md)
- [ADR 0013 — hidden line/PNG facade and private Python helper](../adr/0013-hidden-facade-private-python-line-png.md)
- [Architecture overview](overview.md)
- [Open decisions](open-decisions.md)
- [API 0002 — errors, capabilities, and fallback](api-0002-errors-capabilities-fallback.md)
- [Accepted requirements: Python bridge](../requirements/lumenplot-v1.0.md#15-python-and-matplotlib-bridge)
