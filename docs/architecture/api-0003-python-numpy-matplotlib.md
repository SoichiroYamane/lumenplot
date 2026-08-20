# API 0003: Python, NumPy, and Matplotlib bridge contract

- Status: **Accepted initial contract; evidence pending**
- Date: 2026-08-21
- Decision owner: architecture-authority
- Recorded by: implementation-worker
- Scope: O-02P/O-09/O-10 initial CPython/abi3/NumPy ownership and headless Matplotlib PNG profile
- Governing architecture: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](../adr/0002-gpu-native-engine-and-matplotlib-adapter.md)
- Open-decision records: [O-09 — Python ABI and NumPy ingestion policy](open-decisions.md#o-09-python-abi-and-numpy-ingestion-policy), [O-10 — Matplotlib compatibility and profile matrix](open-decisions.md#o-10-matplotlib-compatibility-and-profile-matrix)

This record declares the initial bridge boundary and compatibility scope. It does not claim a built wheel, a supported Python/Matplotlib matrix, or a completed adapter. The exact NumPy dependency range is evidence-gated before manifest integration; it is not an unresolved public API field.

## Requirement references

The bridge boundary covers `LP-DATA-001`, `LP-DATA-006`, `LP-DATA-007`, `LP-SEC-004`, and `LP-MPL-001` through `LP-MPL-017` in the [requirements](../requirements/lumenplot-v1.0.md#15-python-and-matplotlib-bridge).

## Context

NumPy arrays may be borrowed for bounded validation, but long-lived asynchronous and native state must not retain a Python-owned buffer. The first adapter slice needs a deliberately small headless PNG profile, explicit fallback behavior, and separate native/adapter performance claims.

## Decision

### CPython, ABI, and initial capabilities

The initial implementation target is GIL-enabled CPython 3.11 through 3.14 with `abi3-py311`.

The following are unsupported initial capabilities: PyPy, free-threaded/`abi3t` builds, generic Buffer Protocol ingestion, and DLPack. The ABI tag is a packaging mechanism, not a support claim; the Python/wheel matrix must pass its own evidence gates.

### NumPy ownership and ingestion

The bridge uses typed rust-numpy borrowing only while the Python GIL is attached. The initial input is a one-dimensional, equal-length pair of `float32` or `float64` x/y arrays. The public long-lived ingestion policy is `copy="always"`:

1. traverse any valid strided view in logical order while the attached borrow is valid;
2. validate shape, dtype, values, topology, and lengths;
3. immediately copy to Rust-owned canonical f64 sealed chunks;
4. release the Python borrow before workers, asynchronous work, or GPU work can observe the data.

Borrowed arrays never reach workers, async tasks, or the GPU. There is no initial `copy="never"`, `render_into`, generic buffer, or NumPy-to-GPU zero-copy API.

Value and topology rules:

- `NaN` in either coordinate denotes a gap;
- positive or negative infinity is rejected;
- integer, object, complex, and boolean input is rejected;
- for MonotonicX, finite x values are globally nondecreasing when gaps are ignored;
- duplicate x values are allowed and source order is preserved;
- ArbitraryXY preserves source order and gaps.

Canonical scientific data remains f64 even when input uses float32. The owned sealed-chunk boundary is the lifetime and async safety boundary.

The exact NumPy dependency range must pass a dedicated CPython 3.11–3.14 wheel/import/runtime matrix before it is added to the package manifest. The range is therefore evidence-gated policy, not an unresolved public field and not a support result.

### Initial Matplotlib evaluation matrix

The initial declared evaluation matrix is CPython 3.11–3.14 with Matplotlib 3.11.x and backend API 1.1. Matplotlib 3.10/API 1.0 is a future separately tested bridge, not initial support.

The distribution and module names are fixed:

- distribution: `lumenplot-mpl`;
- import package: `lumenplot_mpl`;
- backend module: `lumenplot_mpl.backend`;
- Matplotlib loader: `module://lumenplot_mpl.backend`;
- backend entry point: `lumenplot`.

### Phase-0 headless PNG profile

The first adapter slice supports headless PNG through public backend boundaries:

- `draw_path` with affine transformation;
- rectangular/path clipping;
- fill, stroke, alpha, dash, cap, and join;
- marker and collection behavior only through tested public/base expansion;
- ordinary text and mathtext through documented `TextToPath`/resolved outline behavior;
- axes, grid, and Legend through those supported primitives.

The following are unsupported initial capabilities: images and arbitrary affine-image behavior, Gouraud, hatch, TeX, filters/path effects, GUI/blit/WebAgg/ipympl/Qt/MacOSX transports, and unknown private or custom behavior.

The initial profile policy is:

| Profile | Initial result |
| --- | --- |
| `strict-common-2d` | Return an explicit unsupported operation error at an unsupported boundary. |
| `hybrid-explicit` | Default profile. Produce a whole-frame **Agg PNG** fallback with a structured warning/result diagnostic when an unsupported boundary is encountered. Never omit it silently. |
| `accelerated-native` | Declared profile, but return explicit unsupported until a sealed-aware implementation exists. |

A PDF whole-frame raster fallback is prohibited. Later PDF output must use semantics-preserving vector fallback or explicit failure. Mapped subtree fallback requires explicit proof of z-order, clipping, and compositing preservation.

The primary Matplotlib path is `Figure.savefig`/canvas `print_png`. Initial adapter configuration exposes profile and diagnostic mode only; it does not expose a public CPU/WGPU/Metal/DX12/Vulkan backend enum. The canvas retains its last diagnostics, and a helper result API is documented separately. There is no GUI `show` in Phase 0.

Fallback diagnostics retain at least reason, type, generation, output format, and raster/vector scope. Adapter measurements report Python, FFI, copy, upload, and fallback costs separately from native zero-Python claims.

## Consequences

- Python-owned input cannot outlive the attached borrow into worker or GPU state.
- Strided and gapped input is defined without promising zero-copy GPU ingestion.
- The adapter can provide useful common headless PNG behavior while remaining honest about unsupported effects and transports.
- The default hybrid profile is observable rather than silently approximate.
- Native Scene authority and the Matplotlib Figure/Artist authority remain distinct.

## Verification and evidence boundary

Required evidence includes dtype/stride/shape/gap/Inf/topology tests, copy and lifetime tests, FFI panic/error fixtures, CPython 3.11–3.14 wheel/import/runtime matrix, Matplotlib loader and entry-point tests, strict unsupported fixtures, Agg fallback goldens and diagnostics, and profile-separated performance reports. No wheel or compatibility cell is claimed here.

## Residual risks

- Matplotlib public backend behavior can vary by version and renderer; the initial matrix is bounded and separately tested.
- TextToPath outlines at the adapter boundary do not establish native font ownership or the later PDF/text contract.
- The exact NumPy dependency range and future Matplotlib 3.10 bridge require evidence before their package policy changes.

## Related records

- [ADR index](../adr/README.md)
- [Architecture overview](overview.md)
- [API 0001 — native Scene state](api-0001-native-scene-state.md)
- [API 0002 — errors, capabilities, and fallback](api-0002-errors-capabilities-fallback.md)
- [ADR 0007 — coordinate, color, text, and export](../adr/0007-coordinate-color-text-export.md)
- [O-09 open-decision entry](open-decisions.md#o-09-python-abi-and-numpy-ingestion-policy)
- [O-10 open-decision entry](open-decisions.md#o-10-matplotlib-compatibility-and-profile-matrix)
- [Accepted requirements: Python bridge](../requirements/lumenplot-v1.0.md#15-python-and-matplotlib-bridge)
