# LumenPlot Product Requirements v1.0

- Status: **Accepted — Pre-alpha Product Requirements**
- Date: 2026-08-20
- Product: LumenPlot
- Publication status: This document records an accepted contract before implementation. It does not report a completed implementation, a supported-platform result, or a measured performance result.

## How to read this document

The original product draft had 36 numbered sections. The same section intent and ordering are retained below so that implementation work can be traced without silently losing scope. The accepted amendments resolve the earlier conflicts between an independent GPU-native engine and a Matplotlib adapter, between v1 and Phase 5, and between targets and evidence.

Only entries carrying a stable `LP-*` identifier are normative or planning statements. Each entry has one classification:

- `MUST`: v1 contract or release-blocking requirement unless its release field says that it is a target awaiting evidence.
- `MUST NOT`: prohibited behavior.
- `SHOULD`: quality target or non-blocking v1 capability unless a later release decision promotes it.
- `MAY`: optional or future capability.
- `NON-GOAL`: explicitly outside v1 responsibility.
- `REFERENCE`: context or candidate technology, not a dependency pin or support claim.
- `PHASE`: planning placement; a phase placement alone does not prove implementation.

The fields `Target`, `Release`, `Phase`, and `Evidence` describe what must eventually be demonstrated. The current verified state is recorded separately in `docs/requirements/traceability-v1.0.md`; all product requirements are currently `Not implemented` or `Not measured` unless that document says they are a non-goal or reference-only item.

Stable requirement families are:

| Family | Scope |
| --- | --- |
| `LP-PROD` | product purpose, independence, and design principles |
| `LP-FUNC` | plotting and interaction capabilities |
| `LP-DATA` | canonical data, chunks, and numeric representation |
| `LP-LOD` | topology and level-of-detail behavior |
| `LP-RENDER` | line rendering and pixel behavior |
| `LP-PLAT` | platform, window, and backend selection |
| `LP-TEXT` | shared text and font/export semantics |
| `LP-MPL` | Matplotlib adapter, profiles, and integration direction |
| `LP-UX` | direct manipulation, Legend, keyboard, and accessibility UX |
| `LP-EXPORT` | PNG, PDF, SVG, and state-to-output behavior |
| `LP-PERF` | workload, latency, and benchmark targets |
| `LP-QUAL` | lifecycle, shader, dependency, repository, and quality gates |
| `LP-SEC` | unsafe, supply-chain, input, and publication safety |
| `LP-REL` | phases, release inclusion, and evidence discipline |

---

## 1. Purpose

LumenPlot is an independent scientific plotting and visualization engine for large measurement and scientific datasets. Its product center is native, low-latency exploration on Windows, macOS, and Linux, while retaining a deliberate one-way integration path for common Matplotlib workflows.

- **LP-PROD-001** | `REFERENCE` | LumenPlot is an independent GPU-native scientific visualization engine rather than a thin implementation detail of another plotting package. | Target: product identity | Release: product review | Phase: 0 | Evidence: `AT-REVIEW-PRODUCT`
- **LP-PROD-002** | `MUST` | The v1 product scope covers the declared Windows, macOS, and Linux support matrix; a platform is not declared supported until its startup, rendering, lifecycle, and benchmark evidence exists. | Target: published support matrix with evidence cells | Release: v1 | Phase: 3 | Evidence: `AT-LIFE-PLATFORM`
- **LP-PROD-003** | `MUST` | Interactive output and PNG/PDF output use semantically equivalent scene, layout, axes, Legend, style, and Plot State data; media-specific antialiasing differences are allowed. | Target: shared semantic frame and export checks | Release: v1 | Phase: 2 | Evidence: `AT-SEM-LAYOUT`, `AT-EXPORT-STATE`
- **LP-PROD-004** | `SHOULD` | The engine leaves a stable conceptual boundary for future Rust, Python, Julia, C, and C++ frontends without making those frontends v1 support commitments. | Target: dependency review | Release: non-blocking | Phase: future | Evidence: `AT-REVIEW-DAG`
- **LP-PROD-005** | `REFERENCE` | The product combines fast exploratory interaction, direct manipulation, GPU-native large-data rendering, scientific precision, and publication-oriented output. | Target: product review | Release: product review | Phase: 0 | Evidence: `AT-REVIEW-PRODUCT`

## 2. Requirement levels

This section preserves the original requirement vocabulary. The classification attached to each `LP-*` entry is authoritative when a sentence appears to have more than one interpretation. A target is not a verified result, and a reference version is not a dependency pin.

## 3. Scope

### 3.1 v1 functional scope

- **LP-FUNC-001** | `MUST` | Support a Line2D series. | Target: deterministic Line2D rendering | Release: v1 | Phase: 1 | Evidence: `AT-FUNC-LINE2D`
- **LP-FUNC-002** | `MUST` | Support multiple series in one plot. | Target: stable ordering and visibility | Release: v1 | Phase: 1 | Evidence: `AT-FUNC-SERIES`
- **LP-FUNC-003** | `MUST` | Support linear axes. | Target: axis, tick, and label correctness | Release: v1 | Phase: 1 | Evidence: `AT-FUNC-AXIS`
- **LP-FUNC-004** | `MUST` | Support logarithmic axes with explicit invalid-domain handling. | Target: log-axis behavior | Release: v1 | Phase: 1 | Evidence: `AT-FUNC-LOG-AXIS`
- **LP-FUNC-005** | `MUST` | Support drag pan. | Target: native interaction | Release: v1 | Phase: 1 | Evidence: `AT-FUNC-PAN-ZOOM`
- **LP-FUNC-006** | `MUST` | Support pointer-centered wheel or trackpad zoom. | Target: anchor-preserving zoom | Release: v1 | Phase: 1 | Evidence: `AT-FUNC-PAN-ZOOM`
- **LP-FUNC-007** | `MUST` | Support Shift-drag box zoom. | Target: bounded view selection | Release: v1 | Phase: 1 | Evidence: `AT-FUNC-BOX-ZOOM`
- **LP-FUNC-008** | `MUST` | Support view history with previous, next, and canonical-view restoration semantics. | Target: deterministic history transitions | Release: v1 | Phase: 2 | Evidence: `AT-FUNC-HISTORY`
- **LP-FUNC-009** | `MUST` | Support an interactive publication-style Legend. | Target: Legend hit-testing and state changes | Release: v1 | Phase: 2 | Evidence: `AT-FUNC-LEGEND`
- **LP-FUNC-010** | `MUST` | Support basic cursor and coordinate inspection showing series, x, and y. | Target: basic scientific inspection | Release: v1 | Phase: 2 | Evidence: `AT-FUNC-CURSOR`
- **LP-FUNC-011** | `MUST` | Support a grid toggle. | Target: Plot State and export consistency | Release: v1 | Phase: 2 | Evidence: `AT-FUNC-GRID`
- **LP-FUNC-012** | `MUST` | Support basic annotations as Plot State, including defined geometry, style, hit-testing, and export behavior. | Target: annotation acceptance fixture | Release: v1 | Phase: 2 | Evidence: `AT-FUNC-ANNOTATION`, `AT-EXPORT-ANNOTATION`
- **LP-FUNC-013** | `MUST` | Support PNG export. | Target: structural PNG output | Release: v1 | Phase: 2 | Evidence: `AT-EXPORT-PNG`
- **LP-FUNC-014** | `MUST` | Support PDF export with retained vector semantics for supported primitives. | Target: structural PDF output | Release: v1 | Phase: 2 | Evidence: `AT-EXPORT-PDF-VECTOR`
- **LP-FUNC-015** | `MUST` | Provide a Python binding and a documented Matplotlib adapter boundary. | Target: package/import/FFI smoke tests | Release: v1 | Phase: 1-2 | Evidence: `AT-LIFE-FFI`, `AT-MPL-LOADER`
- **LP-FUNC-016** | `MUST` | Provide a standalone viewer for native LumenPlot scenes. | Target: launch, interaction, close, and package tests | Release: v1 | Phase: 1-2 | Evidence: `AT-FUNC-VIEWER`, `AT-LIFE-VIEWER`

### 3.2 Extended and future scope

- **LP-FUNC-017** | `SHOULD` | Support scatter as a non-blocking v1 capability or a later capability according to the release matrix. | Target: explicit capability status | Release: v1 non-blocking | Phase: 5 | Evidence: `AT-FUNC-SCATTER`
- **LP-FUNC-018** | `SHOULD` | Support markers as a non-blocking v1 capability or a later capability according to the release matrix. | Target: explicit capability status | Release: v1 non-blocking | Phase: 5 | Evidence: `AT-FUNC-MARKER`
- **LP-FUNC-019** | `SHOULD` | Support error bars as a non-blocking or Phase 5 capability; they are not a native 10M release blocker. | Target: scope declaration | Release: v1 non-blocking | Phase: 5 | Evidence: `AT-FUNC-ERRORBAR`
- **LP-FUNC-020** | `SHOULD` | Support secondary axes as a non-blocking or Phase 5 capability; they are not a native 10M release blocker. | Target: scope declaration | Release: v1 non-blocking | Phase: 5 | Evidence: `AT-FUNC-SECONDARY-AXIS`
- **LP-FUNC-021** | `SHOULD` | Retain SVG-compatible semantic and vector data in the shared frame; complete SVG output is non-blocking for v1. | Target: future SVG structural output | Release: v1 non-blocking | Phase: 2 | Evidence: `AT-EXPORT-SVG`
- **LP-FUNC-022** | `MAY` | Add heatmap support after v1. | Target: future candidate | Release: future | Phase: future | Evidence: `AT-REVIEW-SCOPE`
- **LP-FUNC-023** | `MAY` | Add image support after v1. | Target: future candidate | Release: future | Phase: future | Evidence: `AT-REVIEW-SCOPE`
- **LP-FUNC-024** | `MAY` | Add contour support after v1. | Target: future candidate | Release: future | Phase: future | Evidence: `AT-REVIEW-SCOPE`
- **LP-FUNC-025** | `NON-GOAL` | A 3D rendering engine is outside v1; a post-v1 exploratory candidate does not become a v1 acceptance promise. | Target: scope review | Release: excluded | Phase: future | Evidence: `AT-REVIEW-SCOPE`
- **LP-FUNC-026** | `MAY` | Add streaming measurement views after the v1 mutation, clock, and backpressure contracts are separately decided. | Target: future candidate | Release: future | Phase: 5+ | Evidence: `AT-REVIEW-SCOPE`
- **LP-FUNC-027** | `MAY` | Add direct GPU-tensor interoperability after an explicit ownership and lifetime decision; it does not imply NumPy-to-GPU zero-copy in v1. | Target: future candidate | Release: future | Phase: future | Evidence: `AT-REVIEW-SCOPE`
- **LP-FUNC-028** | `SHOULD` | Add advanced A/B measurement, nearest geometry, delta, and slope tools after the basic cursor contract is stable. | Target: measurement tooling | Release: v1 non-blocking | Phase: 5 | Evidence: `AT-FUNC-MEASUREMENT`
- **LP-FUNC-029** | `MAY` | Provide an optional series-management panel for large series sets. | Target: optional capability | Release: optional | Phase: 5 | Evidence: `AT-FUNC-SERIES-PANEL`
- **LP-FUNC-030** | `MUST NOT` | Turn the publication Legend into the primary large-series management panel. | Target: UX review | Release: v1 | Phase: 2 | Evidence: `AT-REVIEW-UX`
- **LP-FUNC-031** | `SHOULD` | Use a virtualized series list when the optional panel targets very large series counts. | Target: 1000-series fixture if shipped | Release: optional | Phase: 5 | Evidence: `AT-BENCH-SERIES-PANEL`

## 4. Non-goals

- **LP-PROD-006** | `NON-GOAL` | Full Matplotlib backend API compatibility, arbitrary private API parity, and unrestricted custom-Artist parity are outside v1. The first-class adapter is explicitly bounded by its profiles and fallback contract. | Target: scope review | Release: excluded | Phase: 1 | Evidence: `AT-REVIEW-MPL-SCOPE`
- **LP-PROD-007** | `NON-GOAL` | Reimplementation of the Matplotlib Artist hierarchy is outside v1. | Target: scope review | Release: excluded | Phase: 1 | Evidence: `AT-REVIEW-MPL-SCOPE`
- **LP-PROD-008** | `NON-GOAL` | Browser-first plotting and general GUI-toolkit development are outside v1. | Target: scope review | Release: excluded | Phase: future | Evidence: `AT-REVIEW-SCOPE`
- **LP-PROD-009** | `NON-GOAL` | Fitting, regression, and general data-analysis framework responsibilities are outside v1. | Target: scope review | Release: excluded | Phase: future | Evidence: `AT-REVIEW-SCOPE`
- **LP-UX-001** | `MUST NOT` | Put fitting controls in the navigation UI. | Target: UX review | Release: v1 | Phase: 0 | Evidence: `AT-REVIEW-UX`
- **LP-REL-001** | `NON-GOAL` | Project and Scene serialization, project-save files, and a persistent RenderPacket format are v1 non-goals; PNG, PDF, and SVG are outputs rather than persistence formats. | Target: explicit scope review | Release: excluded | Phase: future | Evidence: `AT-REVIEW-PERSISTENCE`

## 5. Basic architecture

The public architecture has two product modes. Native mode is authoritative in `PlotScene`. Matplotlib mode is authoritative in the Matplotlib `Figure`/`Artist` graph and produces a revisioned derived LumenPlot snapshot or cache. The shared semantic/layout frame is distinct from the internal RenderPacket used by a renderer process.

- **LP-PROD-010** | `MUST` | Keep the core independent of Matplotlib, Python, wgpu, window-system concrete types, and native GPU API concrete types. | Target: dependency and type scan | Release: v1 architecture | Phase: 0 | Evidence: `AT-REVIEW-CORE-DAG`
- **LP-PROD-011** | `MUST` | Separate shared semantic and layout data from the immutable internal RenderPacket. | Target: architecture review | Release: v1 architecture | Phase: 0 | Evidence: `AT-REVIEW-FRAME-BOUNDARY`
- **LP-PROD-012** | `MUST` | Keep RenderPacket process-local, internal, immutable, validated, non-serialized, and free of wgpu, window, Python, and public wire-format obligations. | Target: schema and visibility review | Release: v1 architecture | Phase: 0 | Evidence: `AT-REVIEW-PACKET`
- **LP-PROD-013** | `SHOULD` | Batch frame-level work instead of exposing thousands of fine-grained draw calls as the core-to-renderer contract. | Target: packet review | Release: implementation quality | Phase: 0-1 | Evidence: `AT-REVIEW-PACKET`
- **LP-PROD-014** | `MUST` | Preserve one-way dependency direction from frontends and adapters into the engine; lower layers do not depend on higher-level frontend objects. | Target: dependency DAG | Release: v1 architecture | Phase: 0 | Evidence: `AT-REVIEW-CORE-DAG`

## 6. Data model

Canonical scientific coordinates remain owned by the CPU-side model. NumPy ingestion can borrow a read-only view for validation and copying, but asynchronous and native interaction state uses Rust-owned immutable sealed chunks.

- **LP-DATA-001** | `MUST` | Keep canonical scientific coordinates and values in f64. | Target: f64 property tests | Release: v1 | Phase: 0 | Evidence: `AT-SEM-F64`
- **LP-DATA-002** | `MUST NOT` | Convert the canonical scientific store to f32 merely to satisfy a GPU representation. | Target: precision negative tests | Release: v1 | Phase: 0 | Evidence: `AT-SEM-F64`
- **LP-DATA-003** | `SHOULD` | Manage large datasets in independently addressable chunks. | Target: chunk ownership tests | Release: v1 quality | Phase: 0 | Evidence: `AT-SEM-CHUNK`
- **LP-DATA-004** | `SHOULD` | Permit residency, upload, and eviction decisions at chunk granularity rather than requiring the whole dataset to be resident. | Target: resident/streamed measurements | Release: v1 quality | Phase: 1 | Evidence: `AT-BENCH-MEMORY`
- **LP-DATA-005** | `SHOULD` | Treat whole-dataset GPU residency as unnecessary for the 100M scenario. | Target: documented streamed scenario | Release: v1 quality | Phase: 1 | Evidence: `AT-BENCH-MEMORY`
- **LP-DATA-006** | `MUST` | Use Rust-owned immutable sealed chunks for long-lived asynchronous and native interaction state. | Target: ownership and lifetime tests | Release: v1 | Phase: 0-1 | Evidence: `AT-SEM-CHUNK`
- **LP-DATA-007** | `MUST` | Seal new chunks for append operations and retain revision identity for snapshots that reference them. | Target: append and revision tests | Release: v1 | Phase: 0-1 | Evidence: `AT-SEM-CHUNK`

## 7. GPU coordinate precision

GPU-side values use a local coordinate frame. Absolute scientific coordinates are not directly narrowed into GPU values.

- **LP-DATA-008** | `MUST` | Represent GPU positions as origin-relative local f32 values derived from canonical f64 data. | Target: local-frame precision test | Release: v1 | Phase: 0-1 | Evidence: `AT-SEM-F64-LOCAL`
- **LP-DATA-009** | `MUST NOT` | Directly cast large absolute f64 coordinates to f32 for GPU drawing. | Target: precision negative test | Release: v1 | Phase: 0-1 | Evidence: `AT-SEM-F64-LOCAL`
- **LP-DATA-010** | `SHOULD` | Select chunk or viewport origins so local representation preserves the declared scientific error tolerance. | Target: error-bound benchmark | Release: v1 quality | Phase: 0-1 | Evidence: `AT-SEM-F64-LOCAL`

## 8. Level of detail

LOD is designed around viewport information rather than raw sample count. MonotonicX receives the v1 optimized path; ArbitraryXY retains a correctness model in v1 while advanced simplification and picking performance remain Phase 5.

- **LP-LOD-001** | `SHOULD` | Make rendering work approach O(viewport width) rather than O(dataset samples) when a suitable LOD hierarchy exists. | Target: 10M benchmark | Release: v1 performance target | Phase: 1 | Evidence: `AT-BENCH-LOD-10M`
- **LP-LOD-002** | `MUST NOT` | Use blind fixed-stride decimation as the correctness strategy for scientific line LOD. | Target: negative and spike fixtures | Release: v1 | Phase: 0-1 | Evidence: `AT-SEM-LOD-MONO`
- **LP-LOD-003** | `MUST` | Preserve first, minimum, maximum, and last extrema with source indices and order in the MonotonicX hierarchy. | Target: extrema and spike fixtures | Release: v1 | Phase: 0-1 | Evidence: `AT-SEM-LOD-MONO`
- **LP-LOD-004** | `MUST` | Distinguish MonotonicX from ArbitraryXY topology. | Target: topology model tests | Release: v1 | Phase: 0 | Evidence: `AT-SEM-LOD-TOPOLOGY`
- **LP-LOD-005** | `SHOULD` | Use a chunk-local dyadic M4-style hierarchy for MonotonicX selection, binary range lookup, and extrema envelopes. | Target: hierarchy benchmark | Release: v1 performance target | Phase: 0-1 | Evidence: `AT-SEM-LOD-MONO`, `AT-BENCH-LOD-10M`
- **LP-LOD-006** | `MUST` | Preserve ArbitraryXY topology and source order and provide chunk or segment bounds and viewport-culling correctness in v1. | Target: arbitrary-order and culling fixtures | Release: v1 correctness | Phase: 0-1 | Evidence: `AT-SEM-LOD-ARBITRARY`
- **LP-LOD-007** | `SHOULD` | Defer advanced ArbitraryXY geometry simplification and high-scale picking performance to Phase 5; those features are not v1 release blockers. | Target: phase boundary review | Release: v1 non-blocking | Phase: 5 | Evidence: `AT-REVIEW-PHASE-BOUNDARY`

## 9. GPU line renderer

The standard line path expands lines into triangles in screen space and applies analytic antialiasing. Hardware line primitive quality is not treated as the product contract.

- **LP-RENDER-001** | `MUST` | Use a renderer path based on LOD data, screen-space line expansion, triangle geometry, and analytic antialiasing rather than relying on hardware line primitive behavior. | Target: renderer review and goldens | Release: v1 | Phase: 1 | Evidence: `AT-SEM-RENDER-GOLDEN`
- **LP-RENDER-002** | `MUST` | Support arbitrary declared line widths. | Target: width fixture | Release: v1 | Phase: 1 | Evidence: `AT-SEM-RENDER-GOLDEN`
- **LP-RENDER-003** | `MUST` | Support Retina and HiDPI scale factors. | Target: 1x/2x/3x matrix | Release: v1 | Phase: 1 | Evidence: `AT-SEM-HIDPI`
- **LP-RENDER-004** | `MUST` | Preserve alpha compositing semantics for supported colors and layers. | Target: alpha fixture | Release: v1 | Phase: 1 | Evidence: `AT-SEM-COLOR`
- **LP-RENDER-005** | `MUST` | Clip line geometry to the declared plot and viewport regions. | Target: clipping golden | Release: v1 | Phase: 1 | Evidence: `AT-SEM-RENDER-GOLDEN`
- **LP-RENDER-006** | `MUST` | Maintain continuous pan and zoom behavior without topology or clipping corruption. | Target: interaction golden and benchmark | Release: v1 | Phase: 1 | Evidence: `AT-FUNC-PAN-ZOOM`, `AT-BENCH-FRAME`
- **LP-RENDER-007** | `SHOULD` | Support dash patterns. | Target: rendering quality fixture | Release: v1 non-blocking | Phase: 1 | Evidence: `AT-SEM-RENDER-GOLDEN`
- **LP-RENDER-008** | `SHOULD` | Support line joins. | Target: rendering quality fixture | Release: v1 non-blocking | Phase: 1 | Evidence: `AT-SEM-RENDER-GOLDEN`
- **LP-RENDER-009** | `SHOULD` | Support line caps. | Target: rendering quality fixture | Release: v1 non-blocking | Phase: 1 | Evidence: `AT-SEM-RENDER-GOLDEN`
- **LP-RENDER-010** | `MUST` | Use analytic antialiasing as the default; MSAA is an optional implementation technique rather than a release prerequisite. | Target: default-path review | Release: v1 | Phase: 1 | Evidence: `AT-SEM-RENDER-GOLDEN`

## 10. Render hot path

After warm-up, native interaction should update view and selection state rather than rebuild the whole scientific or renderer state.

- **LP-QUAL-001** | `SHOULD` | Keep the steady-state interaction frame close to allocation-free after pipelines, fonts, LOD, and resources are warm. | Target: allocation telemetry | Release: v1 performance target | Phase: 1 | Evidence: `AT-BENCH-HOTPATH`
- **LP-QUAL-002** | `MUST NOT` | Invoke Python callbacks during the native or accelerated-native steady-state interaction frame. | Target: callback counter is zero | Release: native v1 gate | Phase: 1 | Evidence: `AT-BENCH-HOTPATH`
- **LP-QUAL-003** | `MUST NOT` | Compile shaders during the warmed interaction frame. | Target: shader counter is zero | Release: v1 | Phase: 1 | Evidence: `AT-SEC-SHADER`, `AT-BENCH-HOTPATH`
- **LP-QUAL-004** | `MUST NOT` | Create pipelines during the warmed interaction frame. | Target: pipeline counter is zero | Release: v1 | Phase: 1 | Evidence: `AT-BENCH-HOTPATH`
- **LP-QUAL-005** | `MUST NOT` | Shape fonts during the warmed interaction frame. | Target: shaping counter is zero | Release: v1 | Phase: 1-2 | Evidence: `AT-SEM-LAYOUT`, `AT-BENCH-HOTPATH`
- **LP-QUAL-006** | `MUST NOT` | Perform an unbounded large heap allocation during the warmed interaction frame. | Target: allocation telemetry | Release: v1 | Phase: 1 | Evidence: `AT-BENCH-HOTPATH`
- **LP-QUAL-007** | `MUST NOT` | Upload the full dataset during ordinary warmed pan or zoom. | Target: upload-byte counter | Release: v1 | Phase: 1 | Evidence: `AT-BENCH-HOTPATH`
- **LP-QUAL-008** | `MUST NOT` | Rebuild the complete LOD pyramid for an ordinary warmed pan or zoom. | Target: cache-generation counter | Release: v1 | Phase: 1 | Evidence: `AT-BENCH-HOTPATH`

## 11. Platform backend

The portable renderer is the initial reference implementation. Native Metal, D3D12, and Vulkan paths remain independent prototypes whose adoption is evidence-gated rather than automatic.

- **LP-PLAT-001** | `MUST` | Provide a portable wgpu-based implementation path without making the core depend on wgpu concrete types. | Target: portable backend build and runtime | Release: v1 | Phase: 1 | Evidence: `AT-LIFE-PLATFORM`
- **LP-PLAT-002** | `MUST` | Gate backend dependency updates on compatibility, correctness, security, and cross-platform performance evidence. | Target: dependency review | Release: v1 | Phase: 3 | Evidence: `AT-BENCH-DEPENDENCY`
- **LP-PLAT-003** | `MUST` | Adopt a Metal fast path only when prototype measurements and profiling show a meaningful benefit over the selected portable path. | Target: Phase 4 decision record | Release: conditional future | Phase: 4 | Evidence: `AT-BENCH-NATIVE-AB`
- **LP-PLAT-004** | `REFERENCE` | D3D12/DXGI is a Windows native-backend candidate. | Target: candidate review | Release: future | Phase: 4 | Evidence: `AT-BENCH-NATIVE-AB`
- **LP-PLAT-005** | `REFERENCE` | Vulkan is a Linux native-backend candidate and the window path considers both Wayland and X11. | Target: candidate review | Release: future | Phase: 4 | Evidence: `AT-LIFE-PLATFORM`
- **LP-PLAT-006** | `MUST` | Define `Backend::Auto` behavior as capability probing plus a static user override; default startup does not run a microbenchmark. | Target: capability and startup tests | Release: v1 architecture | Phase: 1 | Evidence: `AT-REVIEW-AUTO`
- **LP-PLAT-007** | `MUST NOT` | Retain a native backend solely because it is newer when its measured benefit does not justify its maintenance cost. | Target: adoption review | Release: conditional future | Phase: 4 | Evidence: `AT-BENCH-NATIVE-AB`

## 12. Window and event layer

The initial window baseline is winit with raw-window-handle interoperability. The runtime, surface, and GPU device are owned by the main thread; worker work never assumes ownership of those concrete objects.

- **LP-PLAT-008** | `REFERENCE` | Use winit 0.30.x and raw-window-handle 0.6.x as the initial baseline candidates, subject to gates rather than fixed public version promises. | Target: compatibility matrix | Release: reference | Phase: 1 | Evidence: `AT-LIFE-PLATFORM`
- **LP-PLAT-009** | `MUST` | Confine the event loop, window, surface, and GPU runtime lifecycle to the main thread or its declared host-loop equivalent. | Target: lifecycle tests | Release: v1 | Phase: 1 | Evidence: `AT-LIFE-RUNTIME`
- **LP-PLAT-010** | `MUST` | Define resize, suspend/resume, surface loss, device loss, close, and explicit out-of-memory behavior before claiming platform support. | Target: lifecycle matrix | Release: v1 | Phase: 1-3 | Evidence: `AT-LIFE-RUNTIME`

## 13. Shader

Common shader sources may use Slang as a build-time candidate, while the portable path consumes validated artifacts. Core renderer abstraction remains independent of Slang-RHI.

- **LP-QUAL-009** | `REFERENCE` | Slang is the first common-shader-source candidate for Metal, DXIL, SPIR-V, and WGSL artifact production. | Target: candidate review | Release: reference | Phase: 1 | Evidence: `AT-SEC-SHADER`
- **LP-QUAL-010** | `MUST` | Compile shader artifacts at build or CI time and test the generated portable and native forms. | Target: reproducible artifact build | Release: v1 | Phase: 1 | Evidence: `AT-SEC-SHADER`
- **LP-QUAL-011** | `MUST` | Cache shader artifacts with provenance sufficient to identify their source and compiler inputs. | Target: artifact manifest | Release: v1 | Phase: 1 | Evidence: `AT-SEC-SHADER`
- **LP-QUAL-012** | `MUST` | Run shader compatibility validation for every declared backend artifact class. | Target: validator corpus | Release: v1 | Phase: 1 | Evidence: `AT-SEC-SHADER`
- **LP-QUAL-013** | `MUST NOT` | Make Slang-RHI a dependency of the core renderer abstraction. | Target: dependency scan | Release: v1 architecture | Phase: 1 | Evidence: `AT-REVIEW-CORE-DAG`

### 13.1 Security and provenance boundary

- **LP-SEC-001** | `MUST` | Keep unsafe code out of core, data, layout, and render-api layers. | Target: static unsafe scan | Release: v1 architecture | Phase: 0 | Evidence: `AT-SEC-UNSAFE`
- **LP-SEC-002** | `MUST` | Isolate and document unsafe operations in FFI, platform, and native-backend modules with explicit ownership and validation boundaries. | Target: unsafe review | Release: v1 | Phase: 0-3 | Evidence: `AT-SEC-UNSAFE`
- **LP-SEC-003** | `MUST NOT` | Compile or download untrusted shader sources at runtime. | Target: runtime negative test | Release: v1 | Phase: 1 | Evidence: `AT-SEC-SHADER`
- **LP-SEC-004** | `MUST` | Validate input sizes, integer conversions, dimensions, and overflow before allocation, upload, or indexing. | Target: malformed-input tests | Release: v1 | Phase: 0-1 | Evidence: `AT-SEC-SIZES`
- **LP-SEC-005** | `MUST` | Verify shader artifact hashes and source/compiler provenance before use. | Target: artifact verification | Release: v1 | Phase: 1 | Evidence: `AT-SEC-SHADER`
- **LP-SEC-006** | `MUST` | Review dependency licenses, advisories, provenance, and SBOM evidence before release. | Target: supply-chain review | Release: v1 | Phase: 0-3 | Evidence: `AT-SEC-SBOM`
- **LP-SEC-007** | `MUST` | Verify license evidence for bundled or deterministic test fonts before distribution. | Target: font license manifest | Release: v1 | Phase: 2 | Evidence: `AT-SEC-FONTS`
- **LP-SEC-008** | `MUST` | Keep public documentation free of private task/session identifiers, local paths, host details, credentials, and raw internal artifact paths. | Target: publication safety scan | Release: bundle publication | Phase: 0 | Evidence: `AT-SEC-PUBLIC-DOCS`

## 14. Text

One shaping and layout result is shared by interactive rendering and export. Font identity, variations, licensing, fallback, and PDF text semantics are evidence-bearing concerns rather than hidden renderer details.

- **LP-TEXT-001** | `MUST` | Share text layout across the screen, PNG, PDF, and SVG semantic paths. | Target: shared-layout fixtures | Release: v1 | Phase: 2 | Evidence: `AT-SEM-LAYOUT`
- **LP-TEXT-002** | `MUST NOT` | Re-measure text or Legend geometry independently in each renderer. | Target: no-remeasurement review | Release: v1 | Phase: 2 | Evidence: `AT-SEM-LAYOUT`
- **LP-TEXT-003** | `SHOULD` | Use a common shaping stack selected through compatibility, correctness, licensing, and reproducibility gates; Parley with its supporting shaping components is an initial candidate, not a pin. | Target: text decision record | Release: v1 quality | Phase: 2 | Evidence: `AT-SEM-LAYOUT`
- **LP-TEXT-004** | `MUST` | Preserve glyph identity, positions, font face, variation, and resolved layout identity across supported output paths. | Target: deterministic font fixture | Release: v1 | Phase: 2 | Evidence: `AT-SEM-LAYOUT`
- **LP-TEXT-005** | `MUST` | Produce searchable PDF text with an embeddable subset and ToUnicode mapping when the selected font path supports it, or use a deterministic outline fallback. | Target: PDF structural check | Release: v1 | Phase: 2 | Evidence: `AT-EXPORT-PDF-TEXT`
- **LP-TEXT-006** | `MUST NOT` | Use raster-only text or a raster screenshot as the final PDF representation for supported text and vector primitives. | Target: PDF structural negative test | Release: v1 | Phase: 2 | Evidence: `AT-EXPORT-PDF-VECTOR`
- **LP-TEXT-007** | `SHOULD` | Record font bytes or a stable font identity, face, variation, fallback route, and license evidence for deterministic fixtures. | Target: reproducibility manifest | Release: v1 quality | Phase: 2 | Evidence: `AT-SEC-FONTS`

## 15. Python and Matplotlib bridge

The Matplotlib adapter is first-class but one-way. It does not turn LumenPlot core into a Matplotlib implementation. Native mode and adapter mode have different authorities and different performance claims.

- **LP-MPL-001** | `MUST` | Provide a first-class one-way Matplotlib adapter while keeping LumenPlot core independent of Matplotlib and Python concrete types. | Target: package and DAG review | Release: v1 | Phase: 1-2 | Evidence: `AT-MPL-LOADER`, `AT-REVIEW-CORE-DAG`
- **LP-MPL-002** | `MUST` | Use the distribution name `lumenplot-mpl`, import package `lumenplot_mpl`, backend module `lumenplot_mpl.backend`, module loader `module://lumenplot_mpl.backend`, and backend entry-point name `lumenplot`. | Target: loader and packaging smoke tests | Release: v1 | Phase: 1-2 | Evidence: `AT-MPL-LOADER`
- **LP-MPL-003** | `MUST` | Offer the fixed compatibility profiles `strict-common-2d`, `hybrid-explicit`, and `accelerated-native`, with `hybrid-explicit` as the default and `accelerated-native` opt-in. | Target: profile selection tests | Release: v1 | Phase: 1-2 | Evidence: `AT-MPL-PROFILES`
- **LP-MPL-004** | `MUST` | Treat the Matplotlib Figure/Artist graph as authoritative in adapter mode and retain only a revisioned derived LumenPlot Scene snapshot or cache. | Target: authority and revision tests | Release: v1 | Phase: 1-2 | Evidence: `AT-MPL-AUTHORITY`
- **LP-MPL-005** | `MUST` | Treat PlotScene as authoritative in native mode. | Target: native authority tests | Release: v1 | Phase: 1 | Evidence: `AT-SEM-STATE-REVISION`
- **LP-MPL-006** | `MUST` | Make strict-common-2d raise an explicit unsupported result for unknown custom Artists, unsupported effects, or unconfigured TeX rather than silently dropping them. | Target: error fixtures | Release: v1 | Phase: 1-2 | Evidence: `AT-MPL-FALLBACK`
- **LP-MPL-007** | `MUST` | Make hybrid-explicit use whole-frame fallback for unknown custom Artists or effects when a reliable public subtree boundary is unavailable. | Target: fallback fixture | Release: v1 | Phase: 1-2 | Evidence: `AT-MPL-FALLBACK`
- **LP-MPL-008** | `MUST` | Record structured fallback reason, type, generation, output format, and raster/vector scope; silent omission and unreported best-effort degradation are not allowed. | Target: diagnostic schema and golden tests | Release: v1 | Phase: 1-2 | Evidence: `AT-MPL-FALLBACK`
- **LP-MPL-009** | `MUST` | Keep supported semantic primitives vector-aware in PDF/SVG and limit raster fallback to the declared unsupported segment or frame. | Target: mixed-output structural test | Release: v1 | Phase: 2 | Evidence: `AT-EXPORT-FALLBACK`
- **LP-MPL-010** | `SHOULD` | Permit subtree or Artist fallback only for explicitly mapped adapters that preserve generation, z-order, clipping, and compositing semantics. | Target: mapped-adapter review | Release: v1 quality | Phase: 2 | Evidence: `AT-MPL-FALLBACK`
- **LP-MPL-011** | `MUST NOT` | Apply the native zero-Python and native 10M performance gate to the standard transparent Figure/Artist profile. | Target: separated benchmark claims | Release: v1 | Phase: 1-3 | Evidence: `AT-BENCH-PROFILE-SEPARATION`
- **LP-MPL-012** | `SHOULD` | Keep ordinary strict-profile text capture at public Matplotlib text and metrics boundaries; private implementation names are not part of the compatibility contract. | Target: versioned text matrix | Release: v1 quality | Phase: 2 | Evidence: `AT-MPL-TEXT`
- **LP-MPL-013** | `MUST` | Keep native ViewState synchronization to Matplotlib at a safe, coalesced boundary rather than invoking Python redraw work for every native frame. | Target: reentrancy and counter tests | Release: v1 | Phase: 1-2 | Evidence: `AT-LIFE-FFI`, `AT-BENCH-PROFILE-SEPARATION`
- **LP-MPL-014** | `REFERENCE` | An initial strict evaluation baseline is Python 3.11 or later with Matplotlib 3.11.x; the baseline is not a support claim until the package and platform matrix passes. | Target: compatibility matrix | Release: reference | Phase: 1-3 | Evidence: `AT-MPL-MATRIX`
- **LP-MPL-015** | `MUST NOT` | Assume that a NumPy-to-GPU path is automatically zero-copy; the upload boundary is explicit. | Target: copy and ownership tests | Release: v1 | Phase: 1 | Evidence: `AT-LIFE-FFI`, `AT-BENCH-FFI`
- **LP-MPL-016** | `SHOULD` | Leave a future path for Python Buffer Protocol and DLPack interoperability without weakening owned-chunk and lifetime rules. | Target: API review | Release: future | Phase: future | Evidence: `AT-REVIEW-FFI`
- **LP-MPL-017** | `MUST` | Keep third-party integration one-way: gsplot or another frontend adapts to LumenPlot, and LumenPlot does not depend on gsplot. | Target: dependency scan | Release: v1 | Phase: 1 | Evidence: `AT-REVIEW-DAG`

## 16. Interactive UI principles

The UI is plot-first, direct-manipulation oriented, and progressively disclosed. The native viewer owns this UX; adapter transports must not be presented as equivalent latency profiles without evidence.

- **LP-UX-002** | `SHOULD` | Make the plot canvas the primary surface and keep persistent controls minimal. | Target: UX review | Release: v1 quality | Phase: 1-2 | Evidence: `AT-REVIEW-UX`
- **LP-UX-003** | `MUST NOT` | Use a large permanent toolbar as the primary interaction surface. | Target: UX review | Release: v1 | Phase: 1-2 | Evidence: `AT-REVIEW-UX`
- **LP-UX-004** | `MUST NOT` | Use a permanently visible sidebar as a prerequisite for ordinary navigation. | Target: UX review | Release: v1 | Phase: 1-2 | Evidence: `AT-REVIEW-UX`
- **LP-UX-005** | `MUST NOT` | Make ordinary navigation depend on modal-heavy workflows. | Target: UX review | Release: v1 | Phase: 1-2 | Evidence: `AT-REVIEW-UX`
- **LP-UX-006** | `MUST NOT` | Require mode selection before ordinary pan or zoom. | Target: interaction usability test | Release: v1 | Phase: 1 | Evidence: `AT-FUNC-INPUT`

## 17. Toolbar

The compact toolbar exposes history, canonical view, grid, cursor, series, export, and secondary commands. Direct manipulation remains the default.

- **LP-UX-007** | `SHOULD` | Provide compact access to previous, next, Home, Grid, Cursor, Series, Export, and secondary commands. | Target: native viewer review | Release: v1 quality | Phase: 2 | Evidence: `AT-REVIEW-UX`
- **LP-UX-008** | `MUST NOT` | Require a permanent Pan button for ordinary drag navigation. | Target: UX review | Release: v1 | Phase: 1 | Evidence: `AT-REVIEW-UX`
- **LP-UX-009** | `MUST NOT` | Require a permanent Zoom button for ordinary wheel or trackpad navigation. | Target: UX review | Release: v1 | Phase: 1 | Evidence: `AT-REVIEW-UX`
- **LP-UX-010** | `MUST NOT` | Present Fit as a permanent substitute for the canonical Home action. | Target: UX review | Release: v1 | Phase: 2 | Evidence: `AT-REVIEW-UX`
- **LP-UX-011** | `MUST NOT` | Require a permanent Box Zoom mode button for Shift-drag box zoom. | Target: UX review | Release: v1 | Phase: 1 | Evidence: `AT-REVIEW-UX`

## 18. Home and reset

Home returns to the Figure-defined or native canonical view. It is not an implicit autoscale operation.

- **LP-UX-012** | `MUST` | Restore the stored canonical view for Home or Reset. | Target: canonical-view fixture | Release: v1 | Phase: 1-2 | Evidence: `AT-FUNC-HISTORY`
- **LP-UX-013** | `MUST NOT` | Change the canonical range merely because interactive pan or zoom changed the current viewport. | Target: state and history fixture | Release: v1 | Phase: 1-2 | Evidence: `AT-SEM-STATE-REVISION`

## 19. Mouse and trackpad interaction

The interaction map retains the original direct-manipulation intent. Axis gestures affect only the addressed axis.

- **LP-UX-014** | `MUST` | Map left drag to pan, wheel or trackpad input to pointer-centered zoom, Shift-drag to box zoom, line click to selection, background click to clear, double-click to Home, and right-click to a transient context action. | Target: event-routing matrix | Release: v1 | Phase: 1-2 | Evidence: `AT-FUNC-INPUT`
- **LP-UX-015** | `MUST` | Restrict axis-region scroll and drag to the addressed x or y dimension. | Target: axis-only fixture | Release: v1 | Phase: 1 | Evidence: `AT-FUNC-INPUT`

## 20. Legend

Legend is a formal Plot Scene element, not a checkbox widget. Its publication geometry remains stable while visibility state changes.

- **LP-UX-016** | `MUST` | Model Legend as part of Plot Scene and shared semantic layout. | Target: scene and layout review | Release: v1 | Phase: 2 | Evidence: `AT-SEM-LEGEND`
- **LP-UX-017** | `MUST` | Share Legend position, font, glyph layout, line sample, marker, spacing, padding, border, background, and column geometry across screen and exports. | Target: semantic equivalence fixture | Release: v1 | Phase: 2 | Evidence: `AT-SEM-LEGEND`, `AT-EXPORT-LEGEND`
- **LP-UX-018** | `MUST NOT` | Add checkbox, eye, or pin icons to the ordinary publication Legend as a substitute for hit-testing. | Target: visual review | Release: v1 | Phase: 2 | Evidence: `AT-REVIEW-UX`
- **LP-UX-019** | `MUST` | Make a single Legend-entry click toggle series visibility while preserving entry geometry and retaining a visibly distinguishable hidden entry. | Target: Legend state fixture | Release: v1 | Phase: 2 | Evidence: `AT-SEM-LEGEND`
- **LP-UX-020** | `MUST` | Make a Legend-entry double click solo a series and a subsequent double click restore the prior visibility state. | Target: solo/restore fixture | Release: v1 | Phase: 2 | Evidence: `AT-SEM-LEGEND`
- **LP-UX-021** | `MUST` | Keep right-click actions transient and exclude them from Plot State and exports. | Target: context and export negative test | Release: v1 | Phase: 2 | Evidence: `AT-SEM-STATE-REVISION`, `AT-EXPORT-STATE`
- **LP-UX-022** | `MUST` | Persist Legend background or padding drag as Plot State and keep entry drag distinct from click-to-toggle hit testing. | Target: drag/export/hit-test fixture | Release: v1 | Phase: 2 | Evidence: `AT-SEM-LEGEND`, `AT-EXPORT-LEGEND`

## 21. Plot State and UI State

Plot State affects exports. UI State is transient and does not. Native Scene mutation is single-writer and publishes immutable revisioned snapshots; bounded workers may compute derived work but cannot publish stale generations.

- **LP-QUAL-014** | `MUST` | Separate Plot State from UI State. | Target: state schema review | Release: v1 | Phase: 1-2 | Evidence: `AT-SEM-STATE-REVISION`
- **LP-QUAL-015** | `MUST` | Include axis ranges, grid visibility, series visibility, styles, Legend position and style, labels, annotations, and current Plot State viewport in the export snapshot. | Target: export-state fixture | Release: v1 | Phase: 2 | Evidence: `AT-EXPORT-STATE`
- **LP-QUAL-016** | `MUST NOT` | Include hover, selection highlight, context menus, toolbar, status bar, panels, mouse cursor, shortcut overlays, transient crosshair, or drag indicators in ordinary exports. | Target: export negative fixture | Release: v1 | Phase: 2 | Evidence: `AT-EXPORT-STATE`
- **LP-QUAL-017** | `MUST` | Use single-writer transactional Scene updates that publish immutable revisioned snapshots. | Target: revision and race tests | Release: v1 architecture | Phase: 0-1 | Evidence: `AT-SEM-STATE-REVISION`, `AT-LIFE-RUNTIME`
- **LP-QUAL-018** | `MUST` | Bound worker queues, provide generation cancellation or stale-result dropping, and define backpressure for LOD/layout work. | Target: cancellation and queue tests | Release: v1 architecture | Phase: 0-1 | Evidence: `AT-LIFE-CANCELLATION`
- **LP-QUAL-019** | `MUST NOT` | Hold a non-reentrant lock across a Python callback. | Target: reentrancy test | Release: v1 | Phase: 1-2 | Evidence: `AT-LIFE-FFI`
- **LP-QUAL-020** | `MUST` | Rebuild renderer resources from retained CPU Scene/data after device loss and report out-of-memory as an explicit error rather than a silent retry loop. | Target: device-loss/OOM matrix | Release: v1 | Phase: 1-3 | Evidence: `AT-LIFE-RUNTIME`

## 22. Export

PNG and PDF are v1 release outputs. SVG remains a non-blocking SHOULD. Supported primitives retain vector semantics; unsupported fallback is explicit and observable.

- **LP-EXPORT-001** | `MUST` | Export PNG from the current Plot State. | Target: dimensions, alpha, and state fixture | Release: v1 | Phase: 2 | Evidence: `AT-EXPORT-PNG`
- **LP-EXPORT-002** | `MUST` | Export PDF from the current Plot State. | Target: vector/text structural fixture | Release: v1 | Phase: 2 | Evidence: `AT-EXPORT-PDF-VECTOR`
- **LP-EXPORT-003** | `SHOULD` | Export SVG without weakening shared semantic layout; incomplete SVG support remains non-blocking for v1. | Target: structural SVG fixture | Release: v1 non-blocking | Phase: 2 | Evidence: `AT-EXPORT-SVG`
- **LP-EXPORT-004** | `MUST` | Exports contain the selected revision of Plot State and omit UI chrome and transient interaction state. | Target: state/export fixture | Release: v1 | Phase: 2 | Evidence: `AT-EXPORT-STATE`
- **LP-EXPORT-005** | `MUST` | Retain line, text, marker, axis, and Legend semantics as vector primitives when the capability is supported. | Target: structural output review | Release: v1 | Phase: 2 | Evidence: `AT-EXPORT-PDF-VECTOR`
- **LP-EXPORT-006** | `MUST NOT` | Implement final PDF by embedding only a raster screenshot when supported vector semantics are available. | Target: PDF negative test | Release: v1 | Phase: 2 | Evidence: `AT-EXPORT-PDF-VECTOR`
- **LP-EXPORT-007** | `MUST` | Use the same resolved semantic/layout frame for interactive, PNG, PDF, and SVG paths. | Target: cross-output equivalence fixture | Release: v1 | Phase: 2 | Evidence: `AT-SEM-LAYOUT`, `AT-EXPORT-LEGEND`
- **LP-EXPORT-008** | `MUST NOT` | Export the cursor as ordinary Plot State unless an explicit future measurement-export feature is selected. | Target: transient export negative test | Release: v1 | Phase: 2 | Evidence: `AT-EXPORT-STATE`
- **LP-EXPORT-009** | `MUST` | Report fallback scope and reason when an output includes an explicitly permitted raster segment. | Target: fallback diagnostics | Release: v1 | Phase: 2 | Evidence: `AT-EXPORT-FALLBACK`

## 23. Cursor and measurement

The basic cursor is a v1 inspection capability. Measurement math and multi-cursor tooling remain a Phase 5 quality lane.

- **LP-UX-023** | `MUST` | Keep ordinary cursor display transient and show series, x, and y in the inspection surface. | Target: cursor interaction fixture | Release: v1 | Phase: 2 | Evidence: `AT-FUNC-CURSOR`
- **LP-UX-024** | `SHOULD` | Add crosshair, nearest-point or nearest-line selection, A/B cursor, delta x, delta y, and slope in the later measurement lane. | Target: measurement fixture | Release: v1 non-blocking | Phase: 5 | Evidence: `AT-FUNC-MEASUREMENT`
- **LP-EXPORT-010** | `MUST NOT` | Include ordinary cursor and crosshair state in exports. | Target: export negative fixture | Release: v1 | Phase: 2 | Evidence: `AT-EXPORT-STATE`

## 24. Series panel

An optional panel supports large series sets without changing the publication Legend into a management widget.

- **LP-UX-025** | `MUST NOT` | Use the Legend as a substitute for a large-series management panel. | Target: UX review | Release: v1 | Phase: 2 | Evidence: `AT-REVIEW-UX`
- **LP-UX-026** | `SHOULD` | If a series panel ships, provide search, visibility, show-all, hide-all, and multi-selection operations. | Target: panel fixture if shipped | Release: optional | Phase: 5 | Evidence: `AT-FUNC-SERIES-PANEL`
- **LP-UX-027** | `SHOULD` | If the panel targets 1000 or more series, keep its interaction latency bounded with a virtualized or equivalent strategy. | Target: large-panel benchmark | Release: optional | Phase: 5 | Evidence: `AT-BENCH-SERIES-PANEL`

## 25. Keyboard and accessibility

Keyboard operation, visible focus, contrast-aware defaults, and reduced-motion behavior are v1 requirements. A semantic screen-reader tree is a SHOULD until platform evidence changes its release classification.

- **LP-UX-028** | `MUST` | Provide keyboard-operable navigation, Legend operations, canonical view, grid, cursor, series visibility, cancellation, and history controls. | Target: keyboard matrix | Release: v1 | Phase: 2 | Evidence: `AT-FUNC-KEYBOARD-A11Y`
- **LP-UX-029** | `SHOULD` | Permit platform-appropriate modifier-key adjustment without changing the semantic actions. | Target: OS interaction review | Release: v1 quality | Phase: 2-3 | Evidence: `AT-FUNC-KEYBOARD-A11Y`
- **LP-UX-030** | `MUST` | Make keyboard focus visible and preserve focus movement through the plot and Legend controls. | Target: accessibility review | Release: v1 | Phase: 2 | Evidence: `AT-FUNC-KEYBOARD-A11Y`
- **LP-UX-031** | `MUST` | Use contrast-aware default colors and states. | Target: contrast fixture | Release: v1 | Phase: 2 | Evidence: `AT-REVIEW-A11Y`
- **LP-UX-032** | `MUST` | Provide a reduced-motion behavior for animated or interpolated view transitions. | Target: preference fixture | Release: v1 | Phase: 2 | Evidence: `AT-REVIEW-A11Y`
- **LP-UX-033** | `SHOULD` | Expose a semantic tree suitable for screen-reader integration where the host platform permits it. | Target: platform accessibility review | Release: v1 non-blocking | Phase: 2-3 | Evidence: `AT-REVIEW-A11Y`

## 26. Performance requirements

Performance statements are targets until a benchmark manifest records real measurements. Profiles are never combined into one claim. The native MonotonicX 10M path is the v1 performance gate; ArbitraryXY advanced performance remains Phase 5.

- **LP-PERF-001** | `MUST` | Use 10^7 samples per series as the principal native target workload. | Target: 10M fixture | Release: native v1 gate | Phase: 1 | Evidence: `AT-BENCH-NATIVE-10M`
- **LP-PERF-002** | `SHOULD` | Exercise 10^8 samples through chunked, resident/streamed, and appendable scenarios without implying that all samples are GPU resident. | Target: 100M scenario report | Release: stretch | Phase: 1-3 | Evidence: `AT-BENCH-MEMORY`
- **LP-PERF-003** | `SHOULD` | Keep full 100M GPU residency optional rather than a release prerequisite. | Target: memory policy review | Release: v1 quality | Phase: 1 | Evidence: `AT-BENCH-MEMORY`
- **LP-PERF-004** | `MUST` | Target p99 interaction frame time below 16.7 ms at 60 Hz on each declared supported native hardware cell after protocol warm-up. | Target: measured p99 | Release: native v1 gate | Phase: 3 | Evidence: `AT-BENCH-NATIVE-10M`
- **LP-PERF-005** | `SHOULD` | Target p99 interaction frame time below 8.3 ms on declared 120 Hz-class native hardware cells after the measurement protocol is fixed. | Target: measured p99 | Release: non-blocking target | Phase: 3 | Evidence: `AT-BENCH-120HZ`
- **LP-PERF-006** | `MUST` | Record zero Python callbacks, bulk uploads, shader compilations, and pipeline creations in the warmed native or accelerated-native interaction frame. | Target: counters equal zero | Release: native v1 gate | Phase: 1 | Evidence: `AT-BENCH-HOTPATH`
- **LP-PERF-007** | `SHOULD` | Keep warmed native interaction heap allocation close to zero under the declared allocation definition. | Target: allocation telemetry | Release: native quality target | Phase: 1 | Evidence: `AT-BENCH-HOTPATH`
- **LP-PERF-008** | `MUST` | Reflect a Legend visibility toggle within one displayed frame in the native viewer under the declared present semantics. | Target: event-to-display measurement | Release: v1 | Phase: 2 | Evidence: `AT-BENCH-LEGEND-1FRAME`
- **LP-PERF-009** | `MUST` | Evaluate performance with repeatable benchmarks rather than subjective interaction impressions. | Target: benchmark artifacts | Release: v1 | Phase: 0-3 | Evidence: `AT-BENCH-MANIFEST`
- **LP-PERF-010** | `MUST` | Include fixed 10k, 1M, and 10M line; 10 x 1M; 100 x 100k; large ArbitraryXY; and large MonotonicX workloads. | Target: fixture manifest | Release: v1 | Phase: 0-3 | Evidence: `AT-BENCH-MANIFEST`
- **LP-PERF-011** | `MUST` | Measure initial load, LOD build, GPU upload, pan, zoom, Legend toggle, picking, p50, p95, p99, CPU, GPU, memory, peak memory, and energy where measurable. | Target: benchmark report | Release: v1 | Phase: 0-3 | Evidence: `AT-BENCH-MANIFEST`
- **LP-PERF-012** | `SHOULD` | Use Matplotlib MacOSX/QtAgg, gnuplot, VisPy, portable LumenPlot, and adopted native LumenPlot paths as separately labelled comparator candidates. | Target: comparator report | Release: non-blocking | Phase: 3-4 | Evidence: `AT-BENCH-COMPARATORS`
- **LP-PERF-013** | `MUST` | Warm pipelines, fonts, and LOD before measured frames; measure at least 1000 frames per fixture and record input-to-present, event-to-packet, packet-to-submit, and submit-to-GPU-complete segments separately. | Target: reproducible protocol | Release: v1 | Phase: 0-3 | Evidence: `AT-BENCH-MANIFEST`
- **LP-PERF-014** | `MUST` | Record OS, GPU, vendor, driver, API feature level, display scale, toolchain, fixture, profile, and measurement semantics with each performance result. | Target: machine manifest | Release: v1 | Phase: 3 | Evidence: `AT-BENCH-MANIFEST`

## 27. Benchmark

The benchmark suite is a release evidence source, not an implementation claim. Cold load, warm interaction, GPU completion, and fallback cost are reported separately.

- **LP-PERF-015** | `MUST` | Keep benchmark results reproducible enough to distinguish cold setup, warm interaction, fallback, CPU submit, GPU completion, and display-present behavior. | Target: protocol review | Release: v1 | Phase: 0-3 | Evidence: `AT-BENCH-MANIFEST`
- **LP-QUAL-021** | `MUST` | Keep native, strict-common-2d, hybrid-explicit, and accelerated-native results in separate labelled profiles. | Target: profile-separated report | Release: v1 | Phase: 1-3 | Evidence: `AT-BENCH-PROFILE-SEPARATION`

## 28. Performance-gated dependency policy

Dependency updates are reviewed as compatibility and performance changes. The reference table in Section 34 is non-normative.

- **LP-QUAL-022** | `MUST` | Do not adopt wgpu, winit, shader compiler, text-stack, or native-binding updates automatically. | Target: dependency review policy | Release: v1 | Phase: 0-3 | Evidence: `AT-BENCH-DEPENDENCY`
- **LP-QUAL-023** | `MUST` | Require a benchmark regression comparison for a dependency update before adoption. | Target: CI/review gate | Release: v1 | Phase: 3 | Evidence: `AT-BENCH-DEPENDENCY`
- **LP-QUAL-024** | `SHOULD` | Prefer an older stable version over a newer version when the older version satisfies compatibility, correctness, security, and measured performance gates. | Target: decision record | Release: v1 policy | Phase: 3 | Evidence: `AT-BENCH-DEPENDENCY`

## 29. Native backend adoption criteria

Native paths are Phase 4 prototypes. They are not automatic release requirements merely because a platform API is newer.

- **LP-PLAT-011** | `MUST` | Compare native prototypes with the portable path on frame time, CPU overhead, present latency, memory, and feature availability before adoption. | Target: A/B benchmark report | Release: conditional future | Phase: 4 | Evidence: `AT-BENCH-NATIVE-AB`
- **LP-PLAT-012** | `MAY` | Retain only the portable path when a native prototype does not provide a meaningful benefit relative to its maintenance cost. | Target: adoption decision | Release: future | Phase: 4 | Evidence: `AT-BENCH-NATIVE-AB`

## 30. Repository and distribution structure

The original repository map is retained as an implementation direction, not a frozen public crate API. Exact facade/crate split, visibility, and public signatures remain follow-up architecture work.

- **LP-QUAL-025** | `REFERENCE` | The implementation is expected to separate core, data, LOD, text, render API, portable renderer, native prototypes, window/runtime, Python adapter, standalone viewer, shader artifacts, benchmarks, and build tooling. | Target: architecture overview | Release: reference | Phase: 0+ | Evidence: `AT-REVIEW-DAG`
- **LP-QUAL-026** | `MAY` | Keep native renderer modules deferred until a measured prototype is warranted. | Target: implementation planning | Release: future | Phase: 0-4 | Evidence: `AT-REVIEW-SCOPE`
- **LP-REL-002** | `MUST` | Keep pre-alpha packages non-publishable until public API, MSRV, compatibility, security, and evidence gates are explicitly accepted; no stable API promise is made by this document. | Target: release metadata review | Release: v1 pre-alpha | Phase: 0-3 | Evidence: `AT-REVIEW-RELEASE`

## 31. Relationship to frontends and gsplot

LumenPlot is independently usable. A frontend may adapt to it, but the engine does not depend on the frontend. The Matplotlib adapter described in Section 15 follows the same rule.

- **LP-MPL-018** | `MUST` | Keep LumenPlot usable as a standalone engine and viewer without requiring gsplot or Matplotlib. | Target: standalone launch and import tests | Release: v1 | Phase: 1-2 | Evidence: `AT-FUNC-VIEWER`, `AT-REVIEW-DAG`
- **LP-MPL-019** | `MUST NOT` | Make LumenPlot core or native runtime depend on gsplot. | Target: dependency scan | Release: v1 | Phase: 0 | Evidence: `AT-REVIEW-DAG`

## 32. Development phases

Phase placement is a sequencing map. It does not turn unfinished work into a verified result.

- **LP-REL-003** | `PHASE` | Phase 0 covers workspace foundations, Plot IR, DataChunk ownership, f64 tests, the LOD prototype, benchmark framework, security/reproducibility policy, and architecture documentation. | Target: foundation artifacts | Release: no release claim | Phase: 0 | Evidence: `AT-REVIEW-PHASE-MAP`
- **LP-REL-004** | `PHASE` | Phase 1 covers the portable line renderer, initial window/runtime path, shader artifacts, axes, ticks, text, pan, zoom, Home, and the native MonotonicX 10M path. | Target: native foundation | Release: no release claim | Phase: 1 | Evidence: `AT-REVIEW-PHASE-MAP`
- **LP-REL-005** | `PHASE` | Phase 2 covers Legend, UI, annotations, cursor, history, shared text/layout, PNG, and PDF. | Target: v1 interaction and export | Release: no release claim | Phase: 2 | Evidence: `AT-REVIEW-PHASE-MAP`
- **LP-REL-006** | `PHASE` | Phase 3 covers the declared OS benchmark matrix, dependency A/B evaluation, lifecycle matrix, and release evidence. | Target: cross-platform evidence | Release: no release claim | Phase: 3 | Evidence: `AT-REVIEW-PHASE-MAP`
- **LP-REL-007** | `PHASE` | Phase 4 covers conditional Metal, D3D12, and Vulkan prototypes and their measured comparison with the portable path. | Target: optional native fast paths | Release: future | Phase: 4 | Evidence: `AT-REVIEW-PHASE-MAP`
- **LP-REL-008** | `PHASE` | Phase 5 covers advanced measurement, ArbitraryXY simplification and picking performance, error bars, scatter, markers, secondary axes, optional series panel, and streaming. | Target: post-v1 expansion | Release: v1.1 or later | Phase: 5 | Evidence: `AT-REVIEW-PHASE-MAP`
- **LP-REL-009** | `MUST` | Assign every v1 `MUST` or `MUST NOT` to a phase, a release gate, and an evidence type before implementation fan-out. | Target: requirement registry validation | Release: v1 governance | Phase: 0 | Evidence: `AT-REVIEW-TRACEABILITY`

## 33. v1 release acceptance criteria

The following release groups are the canonical replacement for the earlier incomplete checklist. A checked box would be evidence from a later implementation; this publication records every item as pending.

### Functional release gates

- **LP-REL-010** | `MUST` | v1 release evidence covers launch on every declared platform, Line2D, multiple series, axes/ticks/labels, linear/log axes, pan, pointer zoom, box zoom, Home, history, grid, basic cursor, publication Legend, Legend click toggle, Legend solo/restore, Legend drag, annotations, PNG, PDF, Python binding, and standalone viewer. | Target: all functional rows pass | Release: v1 | Phase: 1-3 | Evidence: `AT-RELEASE-FUNCTIONAL`

### Correctness release gates

- **LP-REL-011** | `MUST` | v1 release evidence covers canonical f64, local-f32 precision, extrema-preserving MonotonicX LOD, ArbitraryXY topology/culling correctness, shared Legend/text layout, hidden-series export, state separation, vector PDF semantics, and HiDPI behavior. | Target: all correctness rows pass | Release: v1 | Phase: 0-3 | Evidence: `AT-RELEASE-CORRECTNESS`

### Performance release gates

- **LP-REL-012** | `MUST` | v1 native release evidence covers the 10M MonotonicX benchmark, native hot-path counters, no bulk upload during ordinary pan/zoom, dependency regression gate, and p99 results for every declared supported platform cell. | Target: all native performance rows pass | Release: native v1 | Phase: 1-3 | Evidence: `AT-RELEASE-PERFORMANCE`
- **LP-REL-013** | `MUST` | v1 release evidence covers keyboard accessibility, focus visibility, contrast-aware defaults, reduced-motion behavior, explicit fallback diagnostics, unsafe boundaries, shader provenance, and the persistence non-goal. | Target: release review bundle | Release: v1 | Phase: 0-3 | Evidence: `AT-RELEASE-QUALITY`
- **LP-REL-014** | `MUST NOT` | Describe any target, reference technology, prototype, parent research result, or unmeasured compatibility cell as an implemented product result. | Target: release-document review | Release: v1 governance | Phase: 0-3 | Evidence: `AT-REVIEW-RELEASE`

## 34. Reference technology baseline

The following table preserves the original technology-selection intent while explicitly making every version non-normative. A version may be adopted only after compatibility, correctness, performance, license, MSRV, and security checks. No exact dependency version is fixed by this document.

| Area | Initial reference, not a pin |
| --- | --- |
| Language | Rust |
| Portable GPU | wgpu 29/30 A/B evaluation |
| Window | winit 0.30.x |
| Window handles | raw-window-handle 0.6.x |
| macOS | Metal where measured beneficial |
| Windows | D3D12/DXGI candidate |
| Linux | Vulkan 1.4 candidate with Wayland/X11 |
| Shader | Slang build-time candidate and validated WGSL/native artifacts |
| Text | Parley/HarfRust/Skrifa/Fontique candidate stack |
| Python | PyO3 candidate |
| NumPy | rust-numpy candidate |

- **LP-QUAL-027** | `REFERENCE` | The versions and libraries in this section are dated investigation references and do not create public dependency pins. | Target: documentation review | Release: reference | Phase: 0 | Evidence: `AT-REVIEW-DEPENDENCIES`
- **LP-QUAL-028** | `MUST` | Adopt a selected dependency only after compatibility, correctness, performance, license, MSRV, and security gates pass. | Target: dependency decision record | Release: v1 governance | Phase: 0-3 | Evidence: `AT-REVIEW-DEPENDENCIES`

## 35. Final design principles

- **LP-PROD-015** | `REFERENCE` | Design priority is scientific correctness, interaction latency, stable visual output, large-data scalability, cross-platform behavior, maintainability, and only then use of the newest APIs. | Target: architecture review rubric | Release: product principle | Phase: 0 | Evidence: `AT-REVIEW-PRODUCT`
- **LP-PERF-016** | `SHOULD` | Reduce the amount of work required for a frame, especially through LOD, retained resources, and native hot paths, before relying on lower-level micro-optimization. | Target: benchmark and design review | Release: v1 quality | Phase: 0-3 | Evidence: `AT-BENCH-LOD-10M`, `AT-REVIEW-PACKET`

## 36. Completion vision

The long-term product vision remains a single engine combining fast exploratory interaction, direct manipulation, GPU-native scale, scientific precision, publication-quality output, and consistent interactive/exported Legend semantics. The v1 contract is deliberately honest: publication precedes implementation, and all targets remain pending until evidence is produced.

- **LP-PROD-016** | `REFERENCE` | The most important UX outcome is that the exported plot represents the Plot State shown by the interactive view while transient controls remain outside the export. | Target: product and export review | Release: v1 principle | Phase: 2 | Evidence: `AT-EXPORT-STATE`
- **LP-PROD-017** | `REFERENCE` | The most important scale outcome is rendering in proportion to displayed information rather than blindly to dataset size, subject to the declared topology and LOD boundaries. | Target: product and benchmark review | Release: v1 principle | Phase: 0-3 | Evidence: `AT-BENCH-LOD-10M`
- **LP-PROD-018** | `REFERENCE` | The most important architecture outcome is a GPU-independent core with a portable path and evidence-gated native escape paths. | Target: architecture review | Release: v1 principle | Phase: 0-4 | Evidence: `AT-REVIEW-CORE-DAG`, `AT-BENCH-NATIVE-AB`

---

## Appendix A — Original 36-section coverage and change manifest

The source intent is retained by section. The last column records only the accepted conflict fix or scope clarification; it is not a claim that implementation exists.

| Original section | Canonical section | Intent retained | Accepted clarification or change |
| ---: | --- | --- | --- |
| 1 | Purpose | independent scientific plotting engine, large-data exploration, low-latency native interaction, shared export | first-class one-way Matplotlib adapter added without reversing independence |
| 2 | Requirement levels | MUST, MUST NOT, SHOULD, MAY vocabulary | `NON-GOAL`, `REFERENCE`, and `PHASE` labels make scope and evidence explicit |
| 3 | Scope | 2D line plotting and v1 interaction/export list | annotations and standalone viewer added to v1 traceability |
| 4 | Non-goals | no full Matplotlib parity, browser-first, 3D, GUI toolkit, fitting, analysis framework | public/common adapter retained; 3D remains v1 non-goal and post-v1 only |
| 5 | Basic architecture | core, semantic frame, renderer boundary, portable/native paths | concrete GPU/window/frontend types excluded from core; RenderPacket is internal |
| 6 | Data model | f64 canonical data and chunks | Rust-owned immutable sealed chunks for long-lived state |
| 7 | GPU precision | local relative f32 representation | direct absolute f64-to-f32 narrowing prohibited |
| 8 | LOD | O(W) intent, extrema, MonotonicX/ArbitraryXY | dyadic M4/extrema MonotonicX path; ArbitraryXY advanced performance is Phase 5 |
| 9 | GPU line renderer | triangle expansion, AA, width, HiDPI, alpha, clipping | retained as v1 renderer contract |
| 10 | Render hot path | no callback, compile, upload, or full rebuild after warm-up | native/accelerated profile boundary makes Matplotlib ceiling explicit |
| 11 | Platform backend | wgpu portable path and Metal/D3D12/Vulkan candidates | `Auto` is capability probe plus static override; no startup microbenchmark |
| 12 | Window/event | winit/raw-window-handle baseline and OS surface direction | main-thread lifecycle, loss, suspend, and OOM evidence required |
| 13 | Shader | common source, build-time compilation, artifacts, compatibility tests | runtime compile/download prohibited; core independent of Slang-RHI |
| 14 | Text | shared shaping/layout across screen and exports | subset+ToUnicode or outline fallback; font provenance required |
| 15 | Python bridge | PyO3/rust-numpy, CPU view, no assumed GPU zero-copy | adapter names/profiles fixed; exact API and ABI remain follow-up gates |
| 16 | UI principles | plot-first, direct manipulation, progressive disclosure | native viewer owns UX; no mode prerequisite |
| 17 | Toolbar | compact history/grid/cursor/series/export controls | permanent pan/zoom/fit/box controls remain prohibited |
| 18 | Home | canonical view rather than autoscale | authority differs by native and Matplotlib modes |
| 19 | Mouse/trackpad | pan, zoom, box zoom, selection, reset, axis-only gestures | retained as functional event matrix |
| 20 | Legend | formal scene element, shared export geometry, toggle/solo/drag | stable geometry, transient context actions, explicit state generation |
| 21 | Plot/UI state | exportable Plot State separated from transient UI State | single-writer snapshots and derived adapter revision added |
| 22 | Export | PNG/PDF required, SVG desired, vector semantics | SVG non-blocking; raster-only PDF prohibited |
| 23 | Cursor | basic coordinate inspection and future measurement | basic cursor v1; A/B/delta/slope Phase 5 |
| 24 | Series panel | optional large-series management separate from Legend | remains optional Phase 5 |
| 25 | Keyboard | navigation and shortcuts | accessibility adds focus, contrast, reduced-motion MUSTs |
| 26 | Performance | 10M target, 100M stretch, frame and callback targets | native MonotonicX gate; profile-separated, measured targets |
| 27 | Benchmark | fixed workloads and CPU/GPU/memory/quantile measures | warm-up, 1000 frames, segments, and machine manifest added |
| 28 | Dependency policy | benchmark-gated updates and old stable fallback | compatibility/license/MSRV/security gates added |
| 29 | Native adoption | prototype and compare native paths | no automatic adoption; maintenance-cost decision required |
| 30 | Repository structure | core/data/LOD/text/render/window/python/viewer/shader/bench layout | exact crate split is open; no product code is published by this bundle |
| 31 | Frontend relationship | standalone engine and gsplot one-way relationship | Matplotlib adapter follows the same one-way rule |
| 32 | Development phases | Phase 0 through Phase 5 sequencing | v1/Phase/Release inclusion matrix made explicit |
| 33 | v1 acceptance | functional, correctness, performance checklist | annotations, viewer, accessibility, fallback, safety rows added |
| 34 | Reference versions | dated technology candidates | all versions marked reference-only, never normative pins |
| 35 | Design principles | correctness and work reduction over novelty | retained as review rubric |
| 36 | Completion vision | unified interaction, export, precision, and scale | pre-alpha publication explicitly separated from implementation evidence |

## Appendix B — Accepted amendments and boundaries

1. LumenPlot is an independent GPU-native engine. `lumenplot-mpl` is a first-class, one-way adapter rather than a reverse dependency.
2. Matplotlib mode treats Figure/Artist as authoritative and LumenPlot Scene as a revisioned derived snapshot/cache. Native mode treats PlotScene as authoritative.
3. The fixed adapter profiles are `strict-common-2d`, `hybrid-explicit` (default), and opt-in `accelerated-native`. Standard adapter measurements are never merged with native zero-Python claims.
4. Canonical f64, Rust-owned immutable sealed chunks, origin-relative local f32, MonotonicX dyadic M4/extrema LOD, and ArbitraryXY Phase 5 advanced performance are the data/LOD boundaries.
5. Semantic/layout data is distinct from the immutable internal process-local RenderPacket. The packet is not public, wire, or persistent format.
6. Main-thread runtime, single-writer Scene updates, immutable snapshots, bounded workers, generation cancellation, stale-result dropping, no lock across Python callbacks, device-loss rebuild, and explicit OOM are lifecycle boundaries.
7. Backend Auto uses capability probing and static override. wgpu, winit, raw-window-handle, shader, text, and binding versions remain reference candidates pending gates.
8. Shared shaping/layout and vector-aware PNG/PDF/SVG semantics are required; PNG/PDF are v1 MUST, SVG is SHOULD and non-blocking, and raster-only PDF is prohibited.
9. Annotations, standalone viewer, keyboard/focus/contrast/reduced-motion accessibility, safety policy, explicit persistence non-goal, and benchmark protocol are part of v1 traceability.

## Appendix C — Public-safe provenance

This bundle was reconciled against the accepted product draft, the cross-section requirements audit, and the recorded architecture decisions. Internal work-item identifiers, session identifiers, local filesystem paths, host details, private URLs, and raw research artifact paths are intentionally omitted from this public copy. The omission is metadata sanitization only; it does not change the historical intent or claim that any implementation evidence exists.

## Appendix D — Normative status boundary

- Product targets are not implementation results.
- Reference dependencies are not pins.
- Platform and GPU support is not claimed without environment-specific evidence.
- `Not implemented` and `Not measured` are valid pre-alpha statuses and are recorded in the traceability companion.
- Exact public Rust/Python signatures, exact crate/facade split, packet fields, error taxonomy, hardware matrix, units/colors, host-loop semantics, font fallback strictness, and GPU runtime details require follow-up ADRs listed in `docs/architecture/open-decisions.md`.
