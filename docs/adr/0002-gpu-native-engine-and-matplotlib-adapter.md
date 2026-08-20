# ADR 0002: GPU-native engine and first-class Matplotlib adapter

- Status: **Accepted**
- Date: 2026-08-20
- Decision owner: Sol
- Recorded by: Luna
- Scope: LumenPlot v1 pre-alpha architecture
- Supersedes: [ADR 0001 — Rust Matplotlib raster backend architecture](0001-rust-matplotlib-raster-backend.md)

This record captures the accepted architecture envelope. It is a design decision, not an implementation report. The requirements and traceability documents intentionally retain `Not implemented`, `Not measured`, and `environment required` results until product work produces evidence.

## Context

The earlier architecture treated LumenPlot primarily as a headless CPU raster backend whose authoritative retained model was Matplotlib's Figure/Artist tree. That boundary was coherent for a narrow adapter, but it could not by itself provide the independent GPU-native engine, retained native interaction, sealed scientific data chunks, hierarchical LOD, native viewer, and shared vector-aware layout required by the accepted product direction.

At the same time, Matplotlib's public backend contract remains valuable. It supplies Figure/Artist semantics, common scientific 2D primitives, public text and metrics behavior, and a broad user ecosystem. A transparent adapter cannot promise that ordinary Figure/Artist traversal has native Scene ownership, sealed chunks, hierarchical LOD, or zero Python work in every interaction frame. Unknown custom Artists and effects also cannot be assigned a reliable public subtree boundary without an explicit mapping or fallback.

The architecture therefore needs two explicit product modes and a one-way adapter:

1. Native LumenPlot mode, where PlotScene is authoritative and the engine owns retained interaction state.
2. Matplotlib mode, where Figure/Artist remains authoritative and the adapter produces a revisioned derived LumenPlot snapshot or cache.

The implementation is pre-alpha. Exact public Rust/Python signatures, exact crate names and visibility, error taxonomy, hardware support matrix, and several unit and host-loop details are deliberately deferred to follow-up decisions rather than invented here.

## Decision

### Product boundary and dependency DAG

The dependency direction is:

```text
Native viewer or future frontend
              │
Matplotlib adapter / Python bridge
              │
      engine facade boundary
              │
 core data ── LOD ── shared text/layout ── semantic frame
              │
 internal RenderPacket boundary
              │
 portable renderer or measured native renderer
              │
 window/surface/GPU runtime
```

The diagram is a direction rule, not a frozen crate split. The exact facade and crate/module names are an open follow-up decision. The following edges are fixed:

- Core, data, LOD, layout, and render-api layers do not depend on Matplotlib, Python, wgpu, a window system, or a native GPU API concrete type.
- A frontend or adapter may depend on the engine. The engine does not depend on the frontend.
- The portable and native renderer implementations consume backend-neutral semantic data and an internal packet; they do not redefine the PlotScene authority.
- The standalone viewer is a product edge around the native runtime, not a GUI toolkit abstraction inside core.
- `lumenplot-mpl` is the first-class Matplotlib distribution. Its import package is `lumenplot_mpl`, its backend module is `lumenplot_mpl.backend`, its Matplotlib module loader is `module://lumenplot_mpl.backend`, and its backend entry-point name is `lumenplot`.
- A gsplot or other frontend integration is also one-way: the frontend adapts to LumenPlot, never the reverse.

No exact public function, class, trait, or method signature is established by this ADR. Names above describe package and module boundaries that are already accepted; signature design belongs to the API follow-up ADR.

### State authority and revision flow

Native mode and Matplotlib mode have different authorities:

```text
Native:
  PlotScene (authoritative)
      → revisioned immutable snapshot
      → shared semantic/layout frame
      → internal validated RenderPacket
      → renderer/export consumers

Matplotlib:
  Figure/Artist (authoritative)
      → adapter observation at a safe boundary
      → revisioned derived LumenPlot Scene snapshot/cache
      → profile-specific renderer or explicit fallback/error
```

The adapter must not create a competing long-lived authoritative Figure/Artist model. In native mode, the PlotScene is the authoritative retained model. In Matplotlib mode, a derived Scene is disposable or revisioned cache state and must not silently mutate Figure/Artist.

Plot State and UI State remain distinct. Axis ranges, current Plot State viewport, visibility, styles, labels, annotations, and Legend placement affect an export snapshot. Hover, focus highlight, context menus, toolbar chrome, status surfaces, pointer cursors, transient crosshairs, and drag indicators do not.

A Scene update is single-writer and transactional. Publication produces an immutable revision. Derived work carries the source revision and a generation token. A result from an older generation cannot replace a newer publication. Native ViewState synchronization to Matplotlib is coalesced at a safe boundary; it is not a Python callback on every native frame.

### Data ownership and LOD

- Canonical scientific coordinates and values remain f64 and CPU-authoritative.
- NumPy can be observed through a bounded read-only ingestion borrow, but long-lived asynchronous and native interaction state uses Rust-owned immutable sealed chunks.
- Appending data seals new chunks and publishes a new revision; chunk size is internal and benchmark-selected, not public API.
- GPU values use origin-relative local f32 representation. A large absolute f64 value is never directly narrowed to f32 for drawing.
- MonotonicX is the v1 optimized topology. Its primary LOD is a chunk-local dyadic M4-style hierarchy preserving first, minimum, maximum, and last samples with source identity and order. Fixed-stride decimation is not a correctness strategy.
- ArbitraryXY retains topology, source order, bounds, and viewport-culling correctness in v1. Advanced geometry simplification and high-scale picking performance are Phase 5 and are not native v1 release blockers.
- GPU residency is controlled at chunk granularity. A 100M dataset need not be entirely resident; resident, streamed, and appendable scenarios are measured separately.

### Semantic/layout frame and RenderPacket

The architecture separates two internal boundaries that were previously easy to conflate.

The shared semantic/layout frame contains backend-neutral resolved meaning: plot geometry, axes, Legend and annotation semantics, visibility, clipping, glyph IDs and positions, resolved styles, and declared fallback facts. It is the source for interactive rendering and vector-aware export. Renderer-specific code must not independently remeasure text or Legend geometry.

`RenderPacket` is a different object:

- immutable after validation;
- process-local and internal;
- consumed by the selected renderer instance;
- associated with a Scene revision and generation;
- built from the shared semantic/layout frame;
- based on opaque generational logical resource identifiers;
- free of wgpu, window, Python, and Matplotlib concrete types;
- not a public API, wire format, persistence format, or serialization schema.

Exact packet fields, validation errors, resource cache ownership, drop behavior, and generation lifetime are intentionally not selected here. They are required inputs to the RenderPacket follow-up ADR. Export consumes shared semantic/layout data and does not reverse-engineer GPU buffers.

### Lifecycle and concurrency

- The event loop, window, surface, and GPU runtime are main-thread confined, or confined to the declared host-loop equivalent.
- One runtime may own multiple windows if the later lifecycle ADR confirms the host-loop and shutdown semantics.
- Scene mutation has one writer. Workers may build LOD, layout, or packet candidates within bounded queues.
- Worker results carry a generation. Stale results are dropped, and cancellation/backpressure is observable rather than an unbounded queue.
- No non-reentrant lock is held across a Python callback.
- Device loss rebuilds renderer resources from retained CPU Scene/data. Out-of-memory is an explicit error; it is not handled by an unbounded silent retry loop.
- Close, drop, suspend, resume, resize, surface loss, device loss, reentrancy, and host-loop ownership require an explicit lifecycle matrix before platform support is claimed.
- Native interaction may run without Python callbacks after warm-up. Matplotlib's ordinary Figure/Artist traversal is not retroactively classified as a native zero-callback path.

### Backend selection and platform baseline

`Backend::Auto` selects from the available implementations through capability probing and a static user override. It does not run a default startup microbenchmark. Diagnostic and CI benchmark selection is separate from startup selection.

The portable renderer uses wgpu as the initial implementation reference while keeping exact versions non-normative. wgpu 29.0.4 is an initial comparison point pending a correctness and cross-platform A/B gate against the relevant later release. winit 0.30.x and raw-window-handle 0.6.x are initial window interoperability references. These references do not freeze a Cargo lockfile or public dependency version.

Metal, D3D12/DXGI, and Vulkan paths are Phase 4 prototype candidates. A native path is adopted only when measured frame time, CPU overhead, present latency, memory, and feature availability show a meaningful benefit that justifies maintenance. A newer API alone is not an adoption reason. Wayland and X11 are both part of the Linux window evidence plan.

### Matplotlib compatibility profiles and fallback

The adapter defines three product profiles:

| Profile | Authority | Intended use | Performance claim |
| --- | --- | --- | --- |
| `strict-common-2d` | Figure/Artist; derived Scene | declared public/common scientific 2D and CI parity | reports Python, FFI, copy, upload, and fallback costs; it does not inherit native zero-Python SLOs |
| `hybrid-explicit` | Figure/Artist; derived Scene plus explicit fallback | default profile for supported primitives and unknown-effects handling | reports fallback cost and never hides unsupported work |
| `accelerated-native` | LumenPlot-aware Artist/DataSource after a sealed snapshot | opt-in native LOD and retained interaction | eligible for the native MonotonicX 10M and zero-Python hot-path gates |

The profiles are not interchangeable marketing labels. A benchmark must identify the profile, authority, data path, and fallback mode.

Fallback rules:

- Strict mode raises an explicit unsupported result for unknown custom Artists, unsupported effects, unsupported Gouraud or affine-image cases, private effects, or unconfigured TeX.
- The default hybrid mode uses whole-frame fallback for unknown custom Artists or effects when the public callback does not expose a reliable Artist-subtree boundary.
- Subtree or Artist fallback is permitted only for an explicitly mapped adapter that verifies generation, z-order, clipping, and compositing semantics.
- Every fallback records structured reason, type, generation, output format, and raster/vector scope.
- Supported primitives remain vector-aware in PDF and SVG. Raster fallback is limited to the declared unsupported segment or frame.
- Silent omission, unreported best-effort flattening, and an implied full-private-API compatibility promise are prohibited.

The standard adapter remains valuable for common public 2D compatibility, but it is not required to satisfy native 10M or zero-Python hot-path targets. Ordinary Matplotlib text and metrics capture remains at public compatibility boundaries. Native/aware mode may use the shared native shaping/layout stack. Full TeX parity is not a v1 requirement; it must be an explicit fallback or unsupported result.

### Text and export

One shaping pass produces shared glyph IDs, positions, font identity, variations, and resolved layout. Interactive output, PNG, PDF, and SVG consume that result. Renderer-specific text remeasurement is not allowed.

PDF text remains searchable when an embeddable subset and ToUnicode mapping are available. A deterministic outline fallback is permitted when they are not. Raster-only text and a raster screenshot embedded as the final PDF for supported vector semantics are prohibited.

PNG and PDF are v1 release requirements. SVG is a v1 SHOULD and non-blocking; the shared semantic frame must retain SVG-compatible vector meaning even if the complete SVG writer lands later. Font bytes or stable identities, fallback choices, variation data, and license evidence belong in reproducibility fixtures. Exact coordinate origin, physical/logical/PDF units, color space, alpha, premultiplication, and font-fallback strictness are follow-up decisions.

### Performance and dependency gates

The native v1 performance gate is a MonotonicX 10M workload. The 100M scenarios are separately labelled resident, streamed, and appendable cases. A standard Matplotlib profile never inherits the native gate.

The benchmark protocol warms pipelines, fonts, and LOD before measuring at least 1000 frames per fixture. It records p50, p95, and p99, machine/OS/GPU/driver/API-feature/toolchain manifest, and separate input-to-present, event-to-packet, packet-to-submit, and submit-to-GPU-complete or readback segments. Cold startup and first upload are separate measurements.

The current targets are p99 below 16.7 ms at 60 Hz on each declared supported native hardware cell and a non-blocking p99 target below 8.3 ms on declared 120 Hz-class cells. These are targets, not measured results. The benchmark must record Python callbacks, Matplotlib dispatch, FFI, shader compile, pipeline creation, font shaping, LOD regeneration, upload bytes, heap allocation, and fallback counters where the profile makes them meaningful.

Updates to wgpu, winit, shader compilers, text stack, or native bindings require compatibility, correctness, security, license, MSRV, and benchmark regression evidence. An older stable version may be retained when it satisfies the gates better than a newer version. No exact version is normative in this ADR.

### Security and unsafe boundary

- Core, data, layout, and render-api layers have no unsafe implementation boundary.
- Unsafe FFI, platform, window, and native-backend operations are isolated, documented, reviewed, and paired with explicit ownership and validation rules.
- Runtime compilation or download of untrusted shaders is not permitted.
- Input sizes, dimensions, integer conversions, overflow, resource counts, and artifact lengths are validated before allocation, upload, or indexing.
- Shader artifacts have source/compiler provenance and verified hashes.
- Dependency license, advisory, provenance, and SBOM evidence is part of release review.
- Deterministic or bundled test fonts require license evidence.
- Public documentation excludes private work-item/session identifiers, local paths, host details, credentials, and raw internal artifact paths.

### Versioning, publication, and non-goals

The product is pre-alpha. Package publication, public API stability, MSRV, ABI stability, exact Rust facade, exact Python signatures, and broad support claims remain undecided until their follow-up gates pass. Pre-alpha package metadata remains non-publishable (`publish = false` where the eventual package system supports that control) until release ownership explicitly changes it.

The v1 product does not promise:

- full Matplotlib private API or arbitrary Artist parity;
- a second retained authoritative Figure model in native mode;
- a public RenderPacket or persistent Scene/project serialization format;
- web-browser-first transport or general GUI toolkit development;
- 3D rendering, fitting, regression, or data-analysis responsibilities;
- automatic NumPy-to-GPU zero-copy;
- universal pixel identity across fonts, drivers, compositors, and media.

PNG, PDF, and SVG are output formats, not a v1 persistence schema. Future serialization requires a separate schema and security decision.

## Rejected options

### A transparent Matplotlib-only engine

Rejected as the sole architecture. It preserves Figure/Artist authority but cannot honestly assign native retained Scene ownership, sealed chunks, hierarchical LOD, or zero Python work to ordinary Figure/Artist redraws. It remains represented by the strict and hybrid adapter profiles rather than being treated as the whole product.

### Two independent long-lived authoritative scenes in one mode

Rejected. A second retained high-level Scene beside Figure/Artist would create stale state, z-order, visibility, layout, history, and export races. The derived adapter Scene is revisioned cache state; native PlotScene is authoritative only in native mode.

### Public or serialized RenderPacket

Rejected for v1. The packet exists to give renderer implementations an immutable validated seam, not to freeze a wire, persistence, or public schema before packet ownership and resource lifetimes are proven.

### Per-draw primitive calls as the core boundary

Rejected. Thousands of fine-grained calls couple interaction and Python traversal to renderer details and make large-data behavior harder to bound. The selected semantic-frame and packet boundaries support batching and LOD selection.

### Runtime shader compilation or download

Rejected for reproducibility, security, startup latency, and supply-chain reasons. Artifacts are produced and checked during build or CI.

### Automatic native backend adoption

Rejected. Platform API novelty is not a performance result. Native paths remain prototypes until A/B measurements justify their maintenance cost.

### Default startup microbenchmark for Backend Auto

Rejected. Capability probing and a static override provide deterministic startup behavior. Diagnostic benchmark selection is a separate operation.

### Silent Matplotlib fallback

Rejected. An unsupported effect that disappears or is flattened without structured diagnostics is not compatibility. Strict errors and observable hybrid fallback make the boundary testable.

### Normative dependency pins in the requirements

Rejected. Candidate versions age and may regress. Compatibility, correctness, performance, license, MSRV, and security gates select an implementation version later.

### Raster screenshot as final PDF

Rejected. Supported lines, text, axes, markers, and Legend retain vector semantics; declared unsupported segments may use an explicit, diagnosed fallback.

## Consequences

### Positive consequences

- LumenPlot can develop an independent native engine without making Matplotlib the core dependency.
- Matplotlib users receive an explicit first-class adapter with honest compatibility profiles and fallback behavior.
- State authority, revision identity, and generation cancellation are visible instead of being implicit synchronization hazards.
- Canonical f64, sealed chunks, local f32, and topology-specific LOD give large-data implementation work a coherent numeric boundary.
- Shared semantic/layout data preserves consistent Legend and text behavior across interactive and export paths.
- Renderer implementations receive a narrow, immutable, backend-neutral internal packet without creating a public schema prematurely.
- Platform and dependency choices remain evidence-gated, reducing the risk of claiming support from a candidate release or a single workstation.
- Security, unsafe, artifact, font-license, and public-documentation rules are part of the architecture rather than cleanup work.

### Costs and compatibility impact

- There are separate correctness and performance profiles for native, strict, hybrid, and accelerated adapter modes.
- A custom Matplotlib Artist may produce a strict unsupported result or a hybrid whole-frame fallback instead of an unannounced approximation.
- Native view updates and Matplotlib synchronization require coalescing, revision tracking, and reentrancy tests.
- Sealed chunks and immutable snapshots add copies and memory accounting at ingestion boundaries.
- The native runtime requires platform lifecycle handling, main-thread ownership, device-loss recovery, and explicit OOM behavior.
- Exact public APIs, package matrix, unit/color policy, and hardware support cells require more decisions before implementation fan-out.

## Verification plan

The implementation plan must add evidence for the following gates. None is satisfied by this ADR alone.

1. **DAG and visibility:** scan core/data/layout/render-api dependencies for Python, Matplotlib, GUI, wgpu, and window concrete types; review the one-way adapter graph.
2. **State authority:** test native PlotScene authority, Matplotlib Figure/Artist authority, revisioned derived snapshots, Plot/UI State separation, history, and stale-generation rejection.
3. **Data and LOD:** property-test f64 authority, local-f32 error bounds, sealed chunk ownership, MonotonicX extrema/source order, no fixed-stride decimation, and ArbitraryXY topology/culling.
4. **Packet:** validate immutable process-local packet construction, opaque logical identifiers, generation association, rejection of invalid resources, absence of concrete backend types, and non-serialization.
5. **Lifecycle:** exercise main-thread runtime, multiple windows if selected, resize, suspend/resume, surface and device loss, OOM, close/drop, Python reentrancy, bounded worker cancellation, and backpressure.
6. **Matplotlib profiles:** import the declared package through the module loader and entry point, test each profile, test strict errors, hybrid diagnostics, mapped subtree rules, public text capture, and profile-separated metrics.
7. **Text and export:** test one shaping/layout result, font identity and license fixture, PNG state, PDF vector structure, searchable text or deterministic outlines, SVG structure when implemented, and explicit fallback scope.
8. **Performance:** run fixed workloads with warm-up and at least 1000 measured frames, record the full machine manifest and timing segments, and report native and adapter profiles separately.
9. **Security:** run unsafe scans, size/overflow tests, artifact hash checks, runtime shader negative tests, dependency/license/SBOM review, and public-documentation prohibited-string scans.
10. **Release:** do not mark v1 accepted until every `MUST`/`MUST NOT` in the requirements traceability registry has a passing linked artifact and every declared platform cell is identified.

## Follow-up ADRs required before implementation fan-out

The following are deliberately open decisions, not reopened accepted decisions:

1. Exact public facade and crate/module DAG, visibility, ownership, and publication layout.
2. Exact public Rust and Python API shapes, exception/error taxonomy, versioning, MSRV, ABI, and package matrix.
3. Internal RenderPacket fields, validation rules, logical resource identifiers, generation/lifetime, cache ownership, and drop/close behavior.
4. Python/NumPy dtype, shape, stride, read-only/mutation, borrow-window, GIL, lifetime, and upload policy.
5. Host-pumped versus native-owned `show`/viewer loop, notebook behavior, reentrancy, and transport semantics.
6. Declared OS/GPU/vendor/driver/API-feature/HiDPI/headless support cells and the benchmark manifest protocol.
7. Coordinate origin, logical/physical/PDF units, color space, alpha/premultiplication, clipping, and HiDPI conversion policy.
8. Font fallback strictness, bundled-font license manifest, text/TeX capability matrix, embedding, ToUnicode, and outline reproducibility.
9. Annotation schema, hit-testing, history snapshot details, accessibility implementation, and standalone-viewer packaging.
10. Future Scene/project serialization schema and its security/migration policy; serialization remains a v1 non-goal until then.

## Residual risks

- The public Matplotlib backend contract does not provide a universal retained native Scene or arbitrary Artist subtree boundary; profile boundaries and fallback diagnostics must remain visible.
- Device, driver, compositor, font, and display differences can make universal pixel identity or unqualified latency claims invalid.
- Exact packet/resource ownership and public API choices can still create implementation hotspots if they are deferred while partial code grows.
- Sealed chunk copies, derived adapter snapshots, and fallback rasterization may dominate some workloads; benchmark counters must expose those costs.
- Native path maintenance may exceed its benefit on some platforms; the adoption gate must be revisited with every prototype.
- Text shaping, TeX, image effects, hatches, Gouraud operations, and private Matplotlib behavior have uneven compatibility surfaces.
- A pre-alpha contract can be implemented partially; publication must not be mistaken for support or completion.

## References

- Matplotlib backend author guidance: https://matplotlib.org/stable/users/explain/figure/writing_a_backend_pyplot_interface.html
- Matplotlib backend API: https://matplotlib.org/stable/users/explain/figure/backends.html#backend-api-versions
- Matplotlib backend base classes: https://github.com/matplotlib/matplotlib/blob/v3.11.1/lib/matplotlib/backend_bases.py
- Matplotlib text API: https://matplotlib.org/stable/api/text_api.html
- wgpu releases: https://github.com/gfx-rs/wgpu/releases
- winit releases: https://github.com/rust-windowing/winit/releases
- raw-window-handle documentation: https://docs.rs/raw-window-handle/
- Slang compilation guide: https://shader-slang.org/slang/user-guide/compiling.html
- Parley releases: https://github.com/linebender/parley/releases
- PyO3 documentation: https://pyo3.rs/
- rust-numpy documentation: https://docs.rs/numpy/
