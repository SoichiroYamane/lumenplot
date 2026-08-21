# ADR 0013: Phase-3A hidden line/PNG facade and private Python helper

- Status: **Accepted staged contract; Phase-3A implementation and evidence pending**
- Date: 2026-08-21
- Decision owner: architecture-authority
- Recorded by: implementation-worker
- Scope: Phase-3A owned Rust line/PNG facade and private Python helper boundary
- Amends: [ADR 0003 — facade and crate dependency graph](0003-facade-and-crate-dag.md), [ADR 0011 — Phase-1B facade namespace and observation traits](0011-phase1b-facade-namespace-observation-traits.md), and [ADR 0012 — private line frame and deterministic PNG contract](0012-private-line-frame-and-png-contract.md)
- Governing architecture: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md)
- Related API records: [API 0002 — errors, capabilities, and fallback](../architecture/api-0002-errors-capabilities-fallback.md) and [API 0003 — Phase-3A Python, NumPy, and private helper](../architecture/api-0003-python-numpy-matplotlib.md)

This ADR records the final staged Phase-3A decision for a bounded owned
Python-to-native line/PNG path. It is a contract record, not an implementation
or wheel result. It deliberately does not freeze the public Matplotlib result,
diagnostic, canvas, warning, fallback, or root-render API; those belong to a
separate Phase-3B decision after the private helper produces evidence.

## Requirement references

The staged boundary supports the relevant ownership, dependency-direction,
error, export, security, and Python-bridge portions of `LP-PROD-010`,
`LP-PROD-014`, `LP-DATA-001`, `LP-DATA-006`, `LP-DATA-007`, `LP-EXPORT-001`,
`LP-EXPORT-004`, `LP-EXPORT-007`, `LP-SEC-004`, `LP-SEC-006`, `LP-SEC-008`, and
`LP-MPL-001` through `LP-MPL-017` in the
[accepted requirements](../requirements/lumenplot-v1.0.md). The requirements
remain normative and their full-v1 result rows remain unchanged.

## Context

The merged Phase-2A private line frame and Phase-2B deterministic PNG sink now
provide the bounded engine/export evidence needed for a next seam. They remain
private, one-series/full-resolution evidence slices and do not constitute a
Matplotlib backend or full-v1 export implementation. The earlier broad API
0003 bridge description mixed that future public surface with the smaller
contract that can be implemented and tested first.

The architecture-authority therefore selects a typed, owned facade seam and a
private Python helper in two sequential implementation slices. The existing
crate DAG, the stable facade root, state authority, and no-claim pre-alpha
publication boundary are preserved.

## Decision

### 1. Dependency direction and visibility

The dependency direction remains exactly:

```text
lumenplot-python -> lumenplot -> {lumenplot-engine, lumenplot-export}
```

There is no direct `lumenplot-python -> lumenplot-engine` or
`lumenplot-python -> lumenplot-export` edge, no new bridge crate, and no
revision of the accepted Option-C facade. The fifteen existing product types
at the `lumenplot` crate root remain exactly the stable root inventory:

```text
PlotScene, SceneTransaction, SceneSnapshot, SceneRevision, SeriesId,
CommitReceipt, AxisRange, AxisScale, Viewport, AxisScales, SeriesTopology,
SeriesData, PublicError, ErrorCode, ErrorCategory
```

The future Rust seam is one `#[doc(hidden)] pub mod __private` in the
`lumenplot` facade. Rust `pub` is honest implementation visibility: it is not
package privacy. The module is inventoried separately, is not re-exported at
the root, and carries no product, semver, ABI, or MSRV promise while the
workspace remains `publish = false`. The visibility and inventory checker must
pass with the module absent before implementation and must enforce the exact
inventory when it appears.

### 2. Exact hidden Rust inventory

The hidden module contains only the following public types and operation. All
fields are private. Request raw values have no formatting guarantee; the
request types do not gain a raw `Debug` or `Display` contract.

```text
LinePngGeometry
  new(
      viewport: [f64; 4],
      canvas: [f64; 2],
      plot_rect: [f64; 4],
      logical_units_per_inch: f64,
  ) -> Result<Self, BridgeError>

LinePngStyle
  new(
      line_rgba: [u8; 4],
      line_width: f64,
      background_rgba: [u8; 4],
  ) -> Result<Self, BridgeError>

OwnedLinePngRequest
  new(
      x: Vec<f64>,
      y: Vec<f64>,
      valid_segments: Vec<Range<usize>>,
      geometry: LinePngGeometry,
      style: LinePngStyle,
      output_dpi: f64,
  ) -> Result<Self, BridgeError>

BridgeError
  code(&self) -> ErrorCode
  category(&self) -> ErrorCategory
  message(&self) -> &str
  Debug + Display + std::error::Error, with source() == None

render_line_png(OwnedLinePngRequest)
  -> Result<Vec<u8>, BridgeError>
```

`BridgeError` is facade-owned and its category is derived from its code. There
is no `OwnedLinePngOutput`, `BridgeDiagnostic`, diagnostic vector, hidden
diagnostic kind, topology or scale argument, async handle, callback, renderer
object, borrowed view,
engine/export error in a public signature, `PlotScene`, snapshot, chunk, LOD,
cache, component revision, semantic-frame or `RenderPacket` signature, GPU or
runtime type, Python or Matplotlib type, third-party raster type, serialization
format, C ABI, raw pointer, callback, or trait-object seam. The operation is
synchronous, consumes the request, and returns one owned byte vector.

The fixed native slice is one one-shot `ArbitraryXY` series at full source
resolution, linear axes, one uniform solid style, Butt cap, Miter join with
limit 4, and PNG output. It makes no topology, LOD, scalability, or
performance claim.

### 3. Rust request validation and ownership

The facade repeats validation at its boundary even when an upstream helper has
already validated the same values.

- `x` and `y` have equal length and the request contains at most `1_000_000`
  points.
- Any infinity anywhere is invalid, including an infinity paired with a NaN.
- A covered index contains finite `x` and `y` values. An uncovered index is a
  gap with at least one NaN and is covered by no range.
- `valid_segments` are exactly the maximal non-empty finite-pair runs. They
  are half-open, source ordered, in bounds, disjoint, and separated by at
  least one gap index.
- Empty input and all-gap input are valid. Duplicate points and source order
  are preserved. Gap values are normalized internally and never exposed.

The consumed request constructs one disposable linear `PlotScene`, adds exactly
one owned `ArbitraryXY` series, commits, snapshots, resolves the reviewed
private line frame, encodes through the reviewed private PNG sink, returns the
owned bytes, and drops every intermediate. There is no retained Scene, frame,
cache, worker, asynchronous task, thread, callback, GPU/window object, mixed
revision, or persistence identity. This record makes no `Send`/`Sync` or
cross-call scheduling guarantee.

Geometry uses top-left-origin `DisplayLogical` coordinates:

- `viewport` is `[x_min, x_max, y_min, y_max]`;
- `canvas` is `[width, height]`;
- `plot_rect` is `[x_min, y_min, x_max, y_max]`.

Viewport bounds are finite and strictly increasing. Canvas dimensions are
finite and positive. The plot rectangle is finite, strictly increasing, and
wholly inside the canvas. `logical_units_per_inch` and `output_dpi` are finite
and positive. Style width is finite and positive in `DisplayLogical` units.
Colors are straight-sRGB RGBA8; a zero-alpha color canonicalizes RGB to zero.
Dash selection and alternate cap/join selection are not part of this slice.

The Phase-2 ceilings and checked-arithmetic rules remain unchanged:

| Ceiling | Value | Applies to |
| --- | ---: | --- |
| `max_frame_series` | `65_536` | private line-frame production |
| `max_frame_segments` | `1_000_000` | private line-frame production |
| `max_frame_points` | `1_000_000` | private line-frame production |
| `max_dimension` | `16_384` per axis | PNG sink |
| `max_pixels` | `16_777_216` | PNG sink |
| `max_output_bytes` | `67_108_864` | PNG sink |
| `max_work_bytes` | `536_870_912` | PNG sink |
| `max_path_points` | `1_000_000` | PNG sink |

Dimensions, `ceil`, `u32`, `usize`, multiplication, addition, combined-work
estimates, path counts, and output growth are checked before allocation or
encoding. Fallible allocation is required; overflow, a ceiling violation, and
allocation failure return an explicit error rather than partial output or a
panic.

The sink uses `device_scale = output_dpi / logical_units_per_inch`, tiny-skia
only for bounded A8 coverage, and the ADR 0012 linear-sRGB source-over
compositor. Final output is straight RGBA8 PNG with the locked sRGB intent,
non-interlaced `NoCompression`/`NoFilter` settings, and no metadata chunks.
Transparent output has zero RGB. The determinism statement remains limited to
the same semantic frame bytes, locked dependency/features/checksums,
compiler/toolchain, target, CPU feature selection, and host; no cross-target
byte identity is claimed.

### 4. Error mapping

The existing `PublicError` mapping is unchanged. The hidden facade maps
export failures exhaustively as follows:

| Source | `BridgeError` code | Category |
| --- | --- | --- |
| `InvalidInput` | `invalid-input` | `input` |
| `UnsupportedCapability` | `unsupported-capability` | `capability` |
| `CapacityExceeded` | `invalid-input` | `input` |
| `AllocationFailed` | `out-of-memory` | `resource` |
| `EncodingFailed` | `internal` | `internal` |
| `Internal` | `internal` | `internal` |

Category is always derived from the code. Messages are sanitized, non-contract
human text. `BridgeError` is source-less; dependency, allocator, path, and
internal-cause details never cross the seam. A later Python boundary contains
unexpected Rust unwinds and maps them to sanitized `internal`/`internal`
without exposing panic payloads. Device loss and out-of-memory are failures,
never fallback reasons.

### 5. Staged Python identity and package boundary

Phase-3A records the private helper boundary only. The intended identity is:

- distribution: `lumenplot-mpl`;
- import package: `lumenplot_mpl`;
- private extension: `lumenplot_mpl._native`;
- reserved later public backend module: `lumenplot_mpl.backend`.

The future helper-only source layout is
`python/lumenplot_mpl/{__init__.py,_native.pyi,py.typed}` with a repository-root
`pyproject.toml`, built through `crates/lumenplot-python/Cargo.toml`. This ADR
adds none of those files, manifests, lockfile entries, CI dependencies, or
publication settings. Phase-3A has no Matplotlib dependency, backend module,
backend entry point, public `render_png`, result type, diagnostic type, or
warning type. The local evidence package is not published.

The exact dependency candidates to add only in the later implementation lane
are:

```toml
pyo3 = { version = "=0.29.2", default-features = false,
         features = ["macros", "extension-module", "abi3-py311"] }
numpy = { version = "=0.29.0", default-features = false }
```

The PEP-517 build frontend is exactly `maturin==1.14.1`. Candidate metadata
uses `Requires-Python >=3.11,<3.15`. The initial runtime evidence pin is
exactly `numpy==2.4.6`; it is not a support range or NumPy ABI promise.
`abi3-py311` authorizes only GIL-enabled CPython 3.11 through 3.14 evaluation;
it is not a LumenPlot C ABI, NumPy ABI guarantee, platform result, or future
CPython promise. Free-threaded/`abi3t`, PyPy/GraalPy, and package publication
remain unclaimed.

### 6. Exact private Python function and NumPy policy

The only Phase-3A Python-visible native function is:

```text
lumenplot_mpl._native.render_line_png(
    x, y, *,
    viewport, canvas, plot_rect,
    logical_units_per_inch, output_dpi,
    line_rgba, line_width, background_rgba,
) -> bytes
```

The geometry arrays use the Rust meanings above. Color arguments are four
integer channels in `0..=255`. There is no topology option; the helper always
uses the fixed ArbitraryXY slice.

Accept only exact built-in NumPy `ndarray` objects, not subclasses or masked
arrays. Inputs are one-dimensional equal-length arrays of native-endian
`float32` or `float64`, aligned, and no longer than `1_000_000` values. Safe
logical positive, negative, and zero strides are accepted. Read-only and
writable arrays are both accepted and never mutated. Integer, boolean, object,
complex, float16, structured, non-native-endian, unaligned, wrong-dimensional,
masked, subclass, and malformed-byte-span inputs are rejected with sanitized
`invalid-input`.

The caller must not mutate either array concurrently during the call; LumenPlot
provides no synchronization for that misuse. Mutation after the owned copy
cannot affect output. With the GIL attached, the bridge validates dtype, shape,
endianness, alignment, stride, capacity, and values, traverses logical order,
canonicalizes NaN in either coordinate as a gap, rejects every infinity, builds
exact source-index maximal finite ranges, and copies to owned `f64` vectors.
Every NumPy/Python borrow and object reference is dropped before
`Python::detach`. Only the pure-owned request/render/output interval may run
detached. The bridge reattaches before constructing Python bytes or an
exception. No Python object, borrow guard, pointer, callback, lock, worker,
Scene, or output target crosses the detached interval. Independent one-shot
calls are reentrant and use no global mutable state.

`lumenplot_mpl.LumenPlotError(RuntimeError)` is the only Phase-3A LumenPlot
exception. It exposes read-only string observations `code`, `category`, and
`message`, and `str(error) == message`. Code/category values are the exact
lowercase API-0002 tokens. There are no subclasses, Python enums, numeric
discriminants, parsers, JSON/wire identity, stable repr or message wording,
Rust cause, or panic payload. Semantic input and bridge failures use this class
and are raised from `None`. Python call-binding errors remain `TypeError`;
interpreter allocation may remain `MemoryError`; `KeyboardInterrupt` and
`SystemExit` remain native exceptions. Rust-controlled allocation failure maps
to `out-of-memory`/`resource`; creation of the final Python `bytes` may raise
native `MemoryError`.

### 7. Evidence and support gate

Before Phase-3A Python integration is accepted, one locked
`cp311-abi3` `manylinux_2_28` x86_64 single-wheel artifact must be tested as
the same artifact in clean GIL-enabled CPython 3.11, 3.12, 3.13, and 3.14
environments with exactly NumPy 2.4.6. The gate includes install/import,
extension initialization, dtype/stride/alignment/gap/error/ownership cases,
detached rendering, byte ownership, error redaction, wheel metadata and
`RECORD`, auditwheel, dependency/license/SBOM, and provenance checks.

The wheel tag alone is not evidence. macOS, Windows, aarch64, universal2,
Windows ARM64, musllinux, other artifacts, free-threaded interpreters,
non-CPython interpreters, and package publication are unsupported or unclaimed
until separate evidence and a reviewed decision exist.

### 8. Ordered delivery

The accepted sequence is:

1. record, independently review, and integrate this ADR and its synchronized
   status/checker changes;
2. implement, independently review, and integrate the pure-Rust hidden facade
   seam;
3. on that integrated seam, implement, independently review, and integrate the
   private `_native.render_line_png` helper and local helper-only package/wheel
   evidence;
4. record a separate Phase-3B public Matplotlib contract before adding a
   backend, public result/diagnostic/warning surface, fallback, or entry point.

No step silently widens the support matrix, adds a release artifact, changes the
DAG, or turns a local helper result into a v1 compatibility claim.

### 9. Mandatory Phase-3B inputs, not a Phase-3A schema

The completed public-backend research is retained as a future contract input,
not as an authorization to implement or as a frozen result schema. The later
Phase-3B decision must at minimum preserve these hazards:

- evaluate exactly Matplotlib 3.11.1 with backend API 1.1; this is a future
  Phase-3B evidence target, not a Phase-3A dependency or support result;
- use documented public Matplotlib APIs only; `_Backend`, `_renderer`, `_api`,
  `_pylab_helpers`, any `matplotlib._*` path, private artist/transform/cache
  helpers, and undocumented `Axes.axison` are forbidden and are not a contract;
- require an exact eligible object whitelist and a public `RendererBase`
  collector before native allocation/output;
- require the exact eligible collector trace of one Figure-background
  `draw_path` plus one Line2D `draw_path`; axes patch, spines, ticks, text,
  markers, images, collections, mesh/Gouraud, custom artists, and every other
  renderer callback are excluded and must cause explicit unsupported handling;
- reject fixed-style mismatches, including unrepresentable defaults, rather
  than silently approximating them;
- map Matplotlib bottom-left display pixels through 72 DisplayLogical points per
  inch into the top-left native geometry, with effective savefig DPI as output
  DPI and callback/source reconciliation;
- explicitly guard non-PNG output instead of allowing a base-class backend
  switch;
- if hybrid is later accepted, use only a public whole-frame `FigureCanvasAgg`
  fallback, never a partial native/Agg composite;
- never fallback after invalid input, capacity/overflow, allocation/OOM,
  encoding/internal/panic, reentrancy/stale publication, or I/O failure;
- retain Figure/Artist authority and do not hold a non-reentrant lock across
  public callbacks.

The public Matplotlib root result, diagnostic, warning, canvas, fallback,
profile, generation, and file/path schemas remain open until that separate
record is accepted. No provisional `PngResult`, `FallbackDiagnostic`,
`render_png`, or canvas contract is adopted here.

## Alternatives and rationale

- A many-scalar hidden function is rejected because geometry, style, and DPI
  ordering and validation would become an FFI call-site concern.
- A direct Python-to-engine/export edge and a new bridge crate are rejected
  because they violate the accepted DAG and duplicate ownership/error seams.
- Raw pointers, an external C ABI, callbacks, trait objects, serde or another
  wire format, and borrowed outputs are rejected because they weaken ownership,
  panic containment, and inventory auditing.
- The superseded ADR 0001 CPU-backend architecture is not revived. Phase-3A is
  only an owned seam over the accepted engine/export boundaries.
- A public Matplotlib canvas or fallback schema is deferred until the private
  helper has real package and runtime evidence; feasibility research alone is
  insufficient.

## Consequences

Positive consequences:

- The engine remains independent of Python and Matplotlib and the existing DAG
  is unchanged.
- The hidden seam is typed, owned, synchronous, and statically auditable while
  the fifteen stable root types remain unchanged.
- NumPy lifetime, stride, mutation, GIL, and exception behavior are explicit
  before a package implementation begins.
- Phase-2 line/PNG rules remain the single native/export source of truth and
  export failures cannot be disguised as fallback.
- Public Matplotlib compatibility is staged behind evidence instead of being
  implied by a private helper or an abi3 wheel tag.

Costs and residual constraints:

- The first Python slice is narrow and has no public Matplotlib backend or
  diagnostic/result API.
- The private Rust module is Rust-public and therefore requires a separate
  inventory and reconsideration before publication or stability claims.
- A single Linux wheel/evidence cell does not establish cross-platform support.
- The helper copies NumPy input and provides no concurrent-mutation
  synchronization; those costs and responsibilities must remain visible.

## Verification and evidence boundary

This ADR recording is documentation and conditional-checker work only. It does
not add Rust/Python product source, Cargo/Python manifests, `Cargo.lock`, CI
dependencies, package artifacts, or publication settings. The checker passes
with the hidden module absent and its mutation suite must reject missing,
extra, leaked, formatted, or incorrectly signed hidden items when a synthetic
module is present.

The merged Phase-2A/B bounded implementation and local dependency/static
checks may be reported as local evidence for that private record. Full-v1
functional, export, Matplotlib, platform, benchmark, security, and release
requirements remain `Not implemented`, `Not measured`, or `environment
required` until their evidence gates close.

## Related records

- [ADR index](README.md)
- [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md)
- [ADR 0003 — facade and crate dependency graph](0003-facade-and-crate-dag.md)
- [ADR 0011 — Phase-1B facade namespace and observation traits](0011-phase1b-facade-namespace-observation-traits.md)
- [ADR 0012 — private line frame and deterministic PNG contract](0012-private-line-frame-and-png-contract.md)
- [API 0002 — errors, capabilities, and fallback](../architecture/api-0002-errors-capabilities-fallback.md)
- [API 0003 — Phase-3A Python, NumPy, and private helper](../architecture/api-0003-python-numpy-matplotlib.md)
- [Architecture overview](../architecture/overview.md)
- [Open architecture decisions](../architecture/open-decisions.md)
- [Accepted v1 requirements](../requirements/lumenplot-v1.0.md)
- [Requirements traceability](../requirements/traceability-v1.0.md)
