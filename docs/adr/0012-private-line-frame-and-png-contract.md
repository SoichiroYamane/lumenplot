# ADR 0012: Private line frame and deterministic PNG contract

- Status: **Accepted amendment; Phase-2 implementation evidence pending**
- Date: 2026-08-21
- Decision owner: architecture-authority
- Recorded by: implementation-worker
- Scope: private Phase-2A line-frame production and private Phase-2B deterministic line/PNG sink
- Amends: [ADR 0003 — facade and crate dependency graph](0003-facade-and-crate-dag.md), [ADR 0007 — coordinate, color, text, and export semantics](0007-coordinate-color-text-export.md), and [ADR 0010 — Phase-1 native core and facade contract](0010-phase1-native-core-facade-contract.md)
- Governing architecture: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md)
- Related amendment: [ADR 0011 — Phase-1B facade namespace and observation traits](0011-phase1b-facade-namespace-observation-traits.md)
- Open-decision records: [O-01 — Exact facade and crate/module split](../architecture/open-decisions.md#o-01-exact-facade-and-cratemodule-split) and [O-11 — Coordinate, unit, color, alpha, and ICC policy](../architecture/open-decisions.md#o-11-coordinate-unit-color-alpha-and-icc-policy)

This record selects the smallest accepted private seam for the next implementation
slice: an engine-owned, line/polyline-only semantic frame followed by a
custom-composited deterministic PNG sink. It does not change the normative v1
requirements, add a public facade or export API, make `RenderPacket` public, or
claim that Phase-2A/2B implementation, output, platform support, performance,
MSRV, ABI, or release evidence exists.

## Requirement references

The bounded slice provides an implementation boundary for the shared semantic
frame and line/PNG portions of `LP-PROD-003`, `LP-FUNC-001`, `LP-FUNC-002`,
`LP-RENDER-003` through `LP-RENDER-005`, `LP-EXPORT-001`, `LP-EXPORT-004`,
`LP-EXPORT-007`, and the input/size and dependency review portions of
`LP-SEC-004`, `LP-SEC-006`, `LP-QUAL-022`, and `LP-QUAL-028` in the
[accepted v1 requirements](../requirements/lumenplot-v1.0.md). The full
requirements remain normative; this ADR narrows an implementation slice and
does not close any requirement row or alter the [traceability registry](../requirements/traceability-v1.0.md).

## Context

Phase-1A and Phase-1B now have implementation and local contract evidence, but
the existing hidden engine bridge intentionally exposes only opaque Scene
observations. The next seam must provide enough resolved geometry and style for
an export sink without leaking raw chunks, source indexes, LOD state, caches,
component revisions, or the internal `RenderPacket` boundary.

The semantic frame remains the shared meaning between interactive rendering and
export. The first implementation slice is deliberately smaller than the v1
product: it resolves only line/polyline geometry from one immutable snapshot,
uses full source resolution, and emits only deterministic RGBA8 PNG. Axes,
labels, text, Legend, annotations, log axes, vector output, adapter behavior,
and runtime behavior require later contracts and evidence.

## Decision

### 1. Ordered delivery and ownership

The work is delivered in this order:

1. Integrate and independently review this ADR and its documentation links.
2. Implement Phase-2A in the private engine frame module.
3. Independently review and merge Phase-2A.
4. Implement Phase-2B in the private export sink, adding its exact dependency
   graph only at that stage.

Phase-2A owns conversion from one immutable engine snapshot to an owned private
line frame. Phase-2B owns raster coverage, linear-sRGB compositing, and PNG
encoding. Neither phase changes the public `lumenplot` facade. The frame has no
mutation, cache, worker, callback, device, window, runtime, serde, persistence,
or `RenderPacket` boundary; it is not cached, persisted, serialized, passed
through a worker or callback, or converted into a `RenderPacket` by this record.

### 2. Phase-2A private line-frame boundary

The implementation adds an engine-private `frame` module and only the following
additional doc-hidden bridge wrappers in `lumenplot_engine::bridge`. Every field
is private. The bridge is an implementation seam, not a product namespace, wire
format, persistence identity, or public facade surface.

The intentional wrapper types and observations/operations are exactly:

| Type | Operations |
| --- | --- |
| `LogicalSize` | `new`, `width`, `height` |
| `LogicalRect` | `new`, `x_min`, `y_min`, `x_max`, `y_max` |
| `SrgbRgba8` | `new`, `r`, `g`, `b`, `a` |
| `LineStyle` | `new`, `color`, `width` |
| `LineFrameSpec` | `new(canvas, plot_rect, logical_units_per_inch, line_style, background)` |
| `LineFrame` | `revision`, `canvas`, `plot_rect`, `logical_units_per_inch`, `background`, `series` |
| `LineSeries` | `id`, `style`, `segments` |
| `LineSegment` | `points` |
| `LinePoint` | `x`, `y` |

The existing bridge `SceneSnapshot` gains exactly one operation:

```text
resolve_line_frame(&LineFrameSpec)
```

It returns an owned `LineFrame` on success and the existing bridge
`SceneError` on failure. Constructor validation is fallible where the input
requires validation. No additional bridge observations, raw-data accessors,
raw point source IDs, source-point indexes, chunk handles, LOD handles, cache
handles, or Scene-state accessors are authorized by this ADR.

`SrgbRgba8::new` constructs encoded straight-sRGB RGBA8. An input with zero
alpha canonicalizes all RGB channels to zero, and every transparent output
follows the same canonicalization. `LineStyle` is request-local and contains a
finite, strictly positive width and the encoded straight-sRGB color. Its stroke
cap and join behavior is fixed to Butt and Miter with miter limit 4; callers do
not select another cap, join, or miter limit in this slice.

`LineFrameSpec` carries the finite canvas, finite plot rectangle, finite
positive `logical_units_per_inch`, one request-local `LineStyle`, and the
background color. The frame also carries the plot rectangle so a sink can apply
coverage clipping without recovering it from a renderer or a raster buffer.

### 3. Phase-2A frame semantics

A successful `resolve_line_frame` has these invariants:

- It is an owned immutable result of exactly one `SceneSnapshot` revision and
  reports that revision through `LineFrame::revision`.
- It contains every current series in ascending `SeriesId` order, including an
  empty series and a gap-only series. Such series have zero `LineSegment` values.
- It uses full source resolution. It does not invoke M4, LOD, culling, a cache,
  or a performance path. Source order, structural segments, duplicate points,
  extrema, and explicit gaps are retained subject to clipping.
- Both axes must be `Linear`. If either snapshot scale is `Log10`, resolution
  returns `UnsupportedCapability`; canonical data and the snapshot are not
  changed.
- Finite canonical f64 coordinates are transformed to finite `DisplayLogical`
  coordinates with a top-left origin, x increasing rightward, and y increasing
  downward. No snap and no f32 narrowing occurs in the engine frame.
- Each structural segment is clipped independently against the rectangular plot
  rectangle with f64 Liang–Barsky clipping. Boundary intersections are inserted
  when a segment crosses the rectangle. Exit/re-entry runs are split, and a gap
  is never reconnected to a neighboring structural segment. A zero-length or
  duplicate point is handled as part of its own structural run and never creates
  a connection across a gap.
- The request-local style is applied uniformly to every series. The frame does
  not expose per-point style, renderer resources, platform objects, or GPU
  values.

The frame resolver may return only the existing engine error kinds applicable to
this seam: `InvalidInput`, `UnsupportedCapability`, `CapacityExceeded`,
`AllocationFailed`, and `Internal`. It does not add an engine error kind or a
new public facade mapping. Non-finite values, invalid extents, invalid scale,
invalid style, and arithmetic failure are diagnosed explicitly rather than
clamped silently.

### 4. Private Phase-2 safety ceilings

Phase-2 implementations use these private hard ceilings before allocation.
They are internal evidence limits, not public support, scalability, or v1
performance claims:

| Ceiling | Value | Applies to |
| --- | ---: | --- |
| `max_frame_series` | `65_536` | Phase-2A frame production |
| `max_frame_segments` | `1_000_000` | Phase-2A frame production |
| `max_frame_points` | `1_000_000` | Phase-2A frame production |
| `max_dimension` | `16_384` per axis | Phase-2B sink |
| `max_pixels` | `16_777_216` | Phase-2B sink |
| `max_output_bytes` | `67_108_864` | Phase-2B sink |
| `max_work_bytes` | `536_870_912` | Phase-2B sink |
| `max_path_points` | `1_000_000` | Phase-2B sink |

Phase-2A counts series, structural segments, and points with checked arithmetic
and validates the limits before and during frame allocation. Phase-2B applies
its path-point limit independently to the sink representation. All finite
checks and `ceil`, `u32`, `usize`, multiplication, addition, and combined-work
calculations are checked before allocation or encoding. Actual combined work
and output estimates are checked in addition to each individual ceiling;
satisfying an individual cap does not override a combined cap. Fallible
containers use `try_reserve` or an equivalent checked allocation path.
Overflow, a ceiling violation, and allocation failure return an explicit error;
partial output and panic-based rejection are not accepted.

### 5. Phase-2B private deterministic PNG boundary

`lumenplot-export` may add private modules named `error`, `raster`,
`compositor`, and `png`, plus exactly one `#[doc(hidden)] pub mod bridge`.
The bridge has private fields and contains only the following intentional
Phase-2B boundary:

```text
ExportErrorKind::{
    InvalidInput,
    UnsupportedCapability,
    CapacityExceeded,
    AllocationFailed,
    EncodingFailed,
    Internal,
}
ExportError
PngSpec::new(output_dpi: f64)
encode_line_frame_png(
    &lumenplot_engine::bridge::LineFrame,
    &PngSpec,
) -> Result<Vec<u8>, ExportError>
```

`ExportError` exposes only its sanitized kind and message observations, has no
source cause, and never carries a path, allocator detail, dependency error,
panic payload, or other internal data across the bridge. There is no public
facade/export API and no third-party type leakage. The only accepted direct
Phase-2B dependencies are:

```toml
tiny-skia = { version = "=0.12.0", default-features = false, features = ["std"] }
png = { version = "=0.18.1", default-features = false }
```

The dependency and lockfile change is Phase-2B work only. This documentation
phase does not modify a manifest or `Cargo.lock`.

`tiny-skia` `Path`/`Stroke`/`Mask` is used only to obtain A8 coverage. A
`tiny-skia` `Pixmap` is forbidden as the final color sink. The final color
storage and compositor are private LumenPlot logic. The sink computes
`device_scale = output_dpi / logical_units_per_inch` and checks
`ceil(canvas * device_scale)` dimensions. Geometry is converted to bounded,
origin-relative f32 only at the tiny-skia sink after finite and range checks;
the frame and clip algebra remain f64.

For each series the sink uses Butt/Miter/limit-4 stroke behavior. For each
covered pixel it combines the A8 path coverage `m = a8 / 255` with analytic
rectangular pixel-cell clip coverage `k = clip_a8 / 255`. With decoded linear
sRGB color `L(rgb)`, style alpha `alpha`, and destination premultiplied values
`D_p` and `D_a`, the private compositor uses finite, clamped f64 intermediates:

```text
 a   = (alpha / 255) * m * k
 S_p = L(rgb) * a
 out_a = a + D_a * (1 - a)
 out_p = S_p + D_p * (1 - a)
```

sRGB decoding uses the `0.04045` threshold. After source-over compositing, the
sink unpremultiplies only when alpha is positive, encodes sRGB with the
`0.0031308` threshold, and quantizes straight RGBA8 using round-half-even. If
quantized alpha is zero, RGB is forced to zero. These rules apply to both the
line colors and the background and do not depend on a renderer's premultiplied
ARGB/BGRA convention.

The PNG stream is exactly an RGBA/Eight, non-interlaced image with sRGB
Perceptual intent 0, `NoCompression`, and `NoFilter`. It has the PNG signature,
`IHDR`, `sRGB`, one or more contiguous `IDAT` chunks, and `IEND`, with no
`pHYs`, `gAMA`, `cHRM`, `iCCP`, text, time, palette, APNG, or other metadata
chunks. PNG output does not become a persistence or Scene format.

The determinism claim is intentionally narrow: repeated encoding is expected to
produce the same bytes only for the same semantic frame bytes, exact locked
versions/checksums/features, compiler/toolchain, target, CPU feature selection,
and host. No cross-target, cross-toolchain, universal pixel, font, driver, or
platform byte-identity claim is made.

### 6. Required verification gates

Phase-2A must include, at minimum:

- snapshot revision and immutability tests;
- deterministic SeriesId/source/segment ordering;
- empty and gap-only series tests;
- all four rectangular clip crossings, exit/re-entry, boundary insertion, and
  no-gap-reconnection tests;
- linear transform and top-left/origin tests;
- duplicate-point tests;
- invalid-spec and Log10-unsupported tests;
- allocation and private-capacity guard tests; and
- exact bridge/private API inventory and negative leakage mutation tests.

Phase-2B must include, at minimum:

- 1x/2x/3x device-scale transforms and fractional extents;
- an independent f64 Liang–Barsky clip oracle;
- width fixtures for `0.5`, `1`, and `2`;
- Butt/Miter/limit-4 stroke fixtures;
- partial A8 coverage;
- an independent blend and alpha oracle;
- transparent-RGB-zero assertions;
- resource, overflow, and allocation/OOM injection;
- an independent PNG parser, chunk, and metadata assertion;
- decoder roundtrip and repeated-byte/hash checks on the same host; and
- exact dependency, checksum, license, unsafe, and build-script graph guards,
  including a negative test proving that `Pixmap` is not the final color sink.

These are implementation and review gates, not evidence supplied by this ADR.

## Alternatives and rationale

The selected boundary keeps semantic ownership in the engine and makes the
external crates narrow, private, and auditable:

- `tiny-skia` coverage plus a custom linear compositor is selected for the first
  sink because it supplies a bounded path/stroke/mask raster operation while
  leaving color, alpha, clipping, and output determinism under explicit
  LumenPlot rules. Its `Pixmap` color path is specifically not selected.
- `lyon_tessellation` `1.0.20` is rejected for this first slice. It supplies
  geometry tessellation but not the required coverage/compositor contract, so
  deterministic coverage and edge behavior would become a larger local burden.
- `raqote` `0.8.5` is rejected for this first slice. Its older maintenance
  posture and premultiplied-ARGB/BGRA draw-target conventions make it a poorer
  fit for the explicit linear-sRGB/RGBA8 sink boundary and increase the risk of
  accidentally making a backend convention normative.
- A wholly custom coverage rasterizer is rejected for this first slice. It has
  the smallest nominal dependency graph but the largest independent coverage
  oracle, antialiasing, and correctness burden.

The candidate direct/transitive audit records these residual risks for the
Phase-2B review. The versions below are the locked candidate graph to verify at
integration, not a current repository lockfile claim:

| Candidate | Audited graph/risk |
| --- | --- |
| `tiny-skia 0.12.0` | `arrayref 0.3.9`, `arrayvec 0.7.8`, `bytemuck 1.25.2`, `cfg-if 1.0.4`, `log 0.4.33`, and `tiny-skia-path 0.12.0`; `tiny-skia-path` uses `strict-num 0.1.1`. Byte/SIMD helper code includes unsafe surfaces that require targeted review. |
| `png 0.18.1` | `bitflags 2.13.1`, `crc32fast 1.5.0` with `cfg-if 1.0.4`, `fdeflate 0.3.7` with `simd-adler32 0.3.10`, and `flate2 1.1.9` through `miniz_oxide 0.8.9` with `adler2 2.0.1` and `simd-adler32 0.3.10`. `crc32fast` build-time CPU probing and the compression graph require build/provenance review. |
| Rejected `lyon_tessellation 1.0.20` | `float_next_after 1.0.0`, `lyon_path 1.0.19`, `lyon_geom 1.0.19`, `euclid 0.22.14`, `num-traits 0.2.19`, `autocfg 1.5.1`, and `libm 0.2.16`; its stroke/coverage surface and unsafe audit would add correctness burden without closing the sink contract. |
| Rejected `raqote 0.8.5` | `euclid`, `num-traits`, `lyon_geom`, `sw-composite 0.7.16`, and `typed-arena 2.0.2`; draw-target/rasterizer unsafe surfaces and premultiplied-ARGB/BGRA behavior are not adopted. |

The integration review must re-check checksums, licenses, sources, build
scripts, unsafe blocks, feature resolution, allocator failure behavior, and the
combined-work ceilings. `try_reserve` and pre-allocation estimates reduce but
do not eliminate allocator and denial-of-service risk; malformed dimensions,
path counts, and encoded-output growth remain explicit negative-test cases.
No dependency is a public support, MSRV, ABI, or release promise.

## Consequences

Positive consequences:

- The next implementation has a narrow, testable private seam without expanding
  the unstable public facade.
- Engine-owned f64 geometry and structural gaps remain authoritative through the
  sink-local f32 conversion and custom linear compositor.
- PNG output can be checked structurally and byte-for-byte within a clearly
  bounded same-host determinism claim.
- Dependency, unsafe, overflow, allocation, and metadata behavior is visible at
  the Phase-2B gate instead of hidden behind a convenient raster backend.

Costs and constraints:

- The first slice is line/polyline-only and cannot claim axes, text, Legend,
  annotations, log axes, vector output, Matplotlib compatibility, GPU behavior,
  or v1 export completion.
- A custom compositor and clip-coverage rule require independent semantic and
  golden oracles; a passing PNG decoder is insufficient.
- Exact dependency pins require locked graph, license, provenance, unsafe, and
  build-script review before manifest integration.
- Same-host determinism does not remove cross-platform or toolchain differences.

## Explicit exclusions

This amendment does not authorize or claim:

- axes, ticks, grid, labels, text, fonts, shaping, Legend, or annotations;
- `Log10` axes;
- LOD, culling, or performance results;
- PDF or SVG;
- Matplotlib, Python, or NumPy behavior;
- GPU, runtime, window, surface, or device behavior;
- `RenderPacket` production or access;
- persistence, serde, Scene/project serialization, or a wire format;
- a public facade or public export API;
- platform, MSRV, ABI, support, release, cross-target determinism, or
  performance claims.

## Verification and evidence boundary

The ADR integration is documentation evidence that an architecture-authority
decision has been recorded. Phase-2A and Phase-2B implementation evidence must
be supplied by the ordered implementation and independent-review gates above.
This task changes documentation only; it intentionally does not modify Rust
source, manifests, or `Cargo.lock`. The requirements and traceability results
remain honest: Phase-1A/B implementation and local contract evidence may be
reported, while the full v1 functional, export, platform, performance, support,
and release gates remain open.

## Related records

- [ADR index](README.md)
- [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md)
- [ADR 0003 — facade and crate dependency graph](0003-facade-and-crate-dag.md)
- [ADR 0007 — coordinate, color, text, and export semantics](0007-coordinate-color-text-export.md)
- [ADR 0010 — accepted Phase-1 native core and facade contract](0010-phase1-native-core-facade-contract.md)
- [ADR 0011 — Phase-1B facade namespace and observation traits](0011-phase1b-facade-namespace-observation-traits.md)
- [Architecture overview](../architecture/overview.md)
- [Open architecture decisions](../architecture/open-decisions.md)
- [Accepted v1 requirements](../requirements/lumenplot-v1.0.md)
- [Requirements traceability](../requirements/traceability-v1.0.md)
