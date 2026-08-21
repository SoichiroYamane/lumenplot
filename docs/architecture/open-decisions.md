# LumenPlot open architecture decisions

## Purpose and status

This list contains decisions that must be settled before implementation fan-out or a support claim. It does not reopen accepted architecture decisions. The published requirements and ADR 0002 are intentionally honest before implementation; an open item is a follow-up gate, not permission to invent a public API or to block publication of the pre-alpha baseline. [ADR 0010](../adr/0010-phase1-native-core-facade-contract.md) records the accepted Phase-1 native core/facade envelope and resolves the Phase-1 candidates in O-01, O-02R, O-03, and O-05 without claiming implementation evidence.

Each item should become an ADR, an API decision record, or a reviewed implementation contract. The exact choice must include rationale, affected interfaces, compatibility impact, and verification evidence.

## Accepted decisions that are not open

The following are fixed by the accepted architecture and must not be returned to this list as competing options:

- LumenPlot is an independent GPU-native engine.
- Matplotlib integration is first-class but one-way through `lumenplot-mpl` / `lumenplot_mpl.backend`.
- Matplotlib mode has Figure/Artist authority and a revisioned derived LumenPlot snapshot/cache; native mode has PlotScene authority.
- The adapter profiles are `strict-common-2d`, `hybrid-explicit` (default), and opt-in `accelerated-native`.
- Strict unsupported results, default hybrid whole-frame fallback for unknown public-boundary effects, mapped subtree fallback only with semantic preservation, and structured fallback diagnostics are required.
- Core/data/layout/render-api layers do not own Matplotlib, Python, wgpu, window, or native GPU concrete types.
- Canonical data is f64; long-lived native state uses Rust-owned immutable sealed chunks; GPU local values are origin-relative f32.
- MonotonicX uses the dyadic M4/extrema direction; ArbitraryXY topology/correctness/culling remains a v1 model lane and advanced performance is Phase 5.
- Semantic/layout data is distinct from the immutable internal process-local RenderPacket. RenderPacket is not public, wire, or persistent format.
- Runtime/window/surface/GPU lifecycle is main-thread confined; Scene is single-writer; snapshots are immutable; workers are bounded and generation-cancellable; no non-reentrant lock crosses a Python callback; device loss rebuilds from retained CPU data; OOM is explicit.
- Backend Auto uses capability probing plus static override and no default startup microbenchmark.
- PNG and PDF are v1 MUST outputs; SVG is a v1 SHOULD and non-blocking; supported vector semantics are retained and raster-only PDF is forbidden.
- Project/Scene serialization is a v1 non-goal.
- v1 is pre-alpha; publication, public API stability, MSRV, performance, and platform support are not claimed without evidence.

## Implementation fan-out gates

### O-01 — Exact facade and crate/module split

- State: Accepted — Phase-1 boundary recorded; evidence pending
- Decision owner: architecture-authority
- Needed before: Rust workspace and binding fan-out
- Record: [ADR 0003 — facade and crate dependency graph](../adr/0003-facade-and-crate-dag.md) and [ADR 0010 — Phase-1 native core and facade contract](../adr/0010-phase1-native-core-facade-contract.md)
- Accepted scope: ADR 0003 fixes the Option-C public facade, internal crate/module boundaries, visibility, re-export, publication metadata, and dependency graph. ADR 0010 fixes the Phase-1A private engine boundary, Phase-1B minimum facade seam, and staged delivery order.
- Constraints: preserve the one-way DAG; keep concrete frontend/GPU/window types out of core; do not make a candidate crate layout a public API by accident.
- Evidence: dependency graph review, visibility scan, build matrix, and an ADR recording the final split.

### O-02 — Public Rust and Python API surface

- State: Accepted — Phase-1 exact surface recorded; evidence pending
- Decision owner: architecture-authority
- Needed before: frontend and FFI implementation
- Record: [API 0001 — native Scene, view, and owned data](api-0001-native-scene-state.md), [API 0003 — Python, NumPy, and Matplotlib](api-0003-python-numpy-matplotlib.md), and [ADR 0010 — Phase-1 native core and facade contract](../adr/0010-phase1-native-core-facade-contract.md)
- Accepted scope: ADR 0010 replaces the Phase-1 candidates with the exact opaque view/scale, owned `SeriesData`, `PlotScene`, transaction, snapshot, revision, and receipt observations; API 0003 remains the adapter-side contract.
- Constraints: signatures must not leak engine chunks, LOD, caches, component revisions, or internal RenderPacket fields; exact NumPy dependency range remains evidence-gated before manifest integration.
- Evidence: API review, docs build, import/loader smoke, compatibility policy, and negative tests for unsupported values.

### O-03 — Error and capability taxonomy

- State: Accepted — Phase-1 mapping recorded; evidence pending
- Decision owner: architecture-authority
- Needed before: API, adapter, runtime, and fallback implementation
- Record: [API 0002 — errors, capability diagnostics, and fallback contract](api-0002-errors-capabilities-fallback.md) and [ADR 0010 — Phase-1 native core and facade contract](../adr/0010-phase1-native-core-facade-contract.md)
- Accepted scope: API 0002 records stable public category/code tokens, capability/fallback diagnostics, internal `WorkOutcome`, and Rust/Python mapping. ADR 0010 additionally fixes the unpublished exhaustive Phase-1 `SceneErrorKind` set and its mapping to facade-owned `PublicError`.
- Constraints: strict mode must be explicit; hybrid fallback must be observable; no silent omission or best-effort degradation.
- Evidence: error mapping table, Python exception mapping, serialization/diagnostic review, and failure fixtures.

### O-04 — Internal RenderPacket schema and resource lifecycle

- State: Accepted — evidence pending
- Decision owner: architecture-authority
- Needed before: renderer fan-out
- Record: [ADR 0004 — RenderPacket and renderer resource lifecycle](../adr/0004-renderpacket-resource-lifecycle.md)
- Accepted scope: packet field families, whole-packet validation, distinct Scene/Work/Device generations, logical-resource cache, lease/fence retirement, and non-public boundary recorded in ADR 0004.
- Constraints: immutable, validated, process-local, internal, non-serialized; no wgpu/window/Python concrete types; export does not reverse-engineer GPU buffers.
- Evidence: property tests, schema review, resource-lifetime tests, stale-generation tests, and a no-wire-format check.

### O-05 — Scene ownership, mutation, revision, and history

- State: Accepted — Phase-1 transaction/state boundary recorded; evidence pending
- Decision owner: architecture-authority
- Needed before: core state and interaction fan-out
- Record: [API 0001 — native Scene, view, and owned data](api-0001-native-scene-state.md) and [ADR 0010 — Phase-1 native core and facade contract](../adr/0010-phase1-native-core-facade-contract.md)
- Accepted scope: API 0001 and ADR 0010 fix stable semantic observations, single-writer transactions, revision/no-op and identity-burn rules, canonical/current viewport, owned series data, immutable snapshots, and component invalidation. View-only history remains a later runtime/UI state contract in this slice.
- Constraints: native PlotScene authority; Matplotlib Figure/Artist authority in adapter mode; derived adapter Scene is revisioned cache; UI State cannot enter ordinary exports; no Scene persistence identity is introduced.
- Evidence: state-machine/property tests, concurrent worker tests, history tests, export-state fixture, and adapter synchronization review.

### O-06 — Window, viewer, host loop, and lifecycle semantics

- State: Accepted — evidence pending
- Decision owner: architecture-authority
- Needed before: standalone viewer, Python `show`, notebook, and platform fan-out
- Record: [ADR 0005 — runtime, viewer, and host-loop lifecycle](../adr/0005-runtime-viewer-host-loop.md)
- Accepted scope: native-owned standalone loop, explicit host-pumped embedding, separate notebook transport, main-thread multi-surface ownership, idempotent close, recovery, reentrancy, and terminal OOM behavior recorded in ADR 0005.
- Constraints: runtime/window/surface/GPU main-thread rule; no Python callback lock crossing; Qt/WebAgg/ipympl transports are not silently included in the native latency claim.
- Evidence: lifecycle matrix, platform tests, repeated create/destroy tests, notebook/host-loop smoke tests, and device-loss/OOM fixtures.

### O-07 — Declared hardware, driver, and CI matrix

- State: Accepted — evidence pending
- Decision owner: architecture-authority
- Needed before: support and p99 release claims
- Record: [ADR 0006 — support cells, benchmark protocol, and native gates](../adr/0006-support-benchmark-native-gates.md)
- Accepted scope: the Windows, Ubuntu/Vulkan, macOS/Metal, and Lavapipe control rows; per-row manifest fields; and scale/present evidence recorded in ADR 0006. All rows remain environment required.
- Constraints: no generic support claim from a single environment; platform/GPU result is `environment required` until a declared cell is exercised.
- Evidence: machine manifest, startup/render/lifecycle matrix, benchmark artifacts, and release review.

### O-08 — Benchmark protocol and performance accounting

- State: Accepted — evidence pending
- Decision owner: architecture-authority
- Needed before: native gate and dependency updates
- Record: [ADR 0006 — support cells, benchmark protocol, and native gates](../adr/0006-support-benchmark-native-gates.md)
- Accepted scope: separate scheduler/GPU/queue/scanout clocks, five fresh-process blocks of at least 1000 frames, raw nearest-rank quantiles, paired bootstrap, no trimming, and inconclusive instrumentation behavior recorded in ADR 0006.
- Constraints: at least 1000 measured frames per fixture; p50/p95/p99; input-to-present, event-to-packet, packet-to-submit, and submit-to-GPU-complete/readback separate; strict, hybrid, accelerated, and native profiles never combined.
- Evidence: reproducible benchmark runner, manifest schema, repeated-run analysis, and dependency A/B report.

### O-09 — Python ABI and NumPy ingestion policy

- State: Accepted — evidence pending
- Decision owner: architecture-authority
- Needed before: Python bridge and wheel fan-out
- Record: [API 0003 — Python, NumPy, and Matplotlib bridge](api-0003-python-numpy-matplotlib.md)
- Accepted scope: GIL-enabled CPython 3.11–3.14 with `abi3-py311`, typed float32/64 one-dimensional copy-always ingestion, NaN gaps, Inf rejection, owned f64 chunks, and unsupported initial capabilities recorded in API 0003. The exact NumPy dependency range is evidence-gated.
- Constraints: NumPy zero-copy is an ingestion implementation technique only; long-lived state is owned sealed chunks; NumPy-to-GPU zero-copy is not promised.
- Evidence: dtype/stride/mutation/lifetime tests, wheel matrix, FFI panic/error tests, and upload/copy benchmark.

### O-10 — Matplotlib compatibility and profile matrix

- State: Accepted — evidence pending
- Decision owner: architecture-authority
- Needed before: adapter release claim
- Record: [API 0003 — Python, NumPy, and Matplotlib bridge](api-0003-python-numpy-matplotlib.md)
- Accepted scope: the initial CPython/Matplotlib 3.11.x headless PNG matrix, public-boundary primitive set, explicit unsupported list, three profile results, Agg fallback, and diagnostic configuration recorded in API 0003.
- Constraints: fixed package/module names and three profile roles are accepted; full private/arbitrary compatibility is not a v1 requirement; standard adapter cannot inherit native zero-Python SLOs.
- Evidence: loader/entry-point tests, public API compatibility suite, strict error fixtures, hybrid fallback goldens, and profile-separated benchmark.

### O-11 — Coordinate, unit, color, alpha, and ICC policy

- State: Accepted — evidence pending
- Decision owner: architecture-authority
- Needed before: renderer and export fan-out
- Record: [ADR 0007 — coordinate, color, text, and export semantics](../adr/0007-coordinate-color-text-export.md)
- Accepted scope: explicit logical units/inch, top-left DisplayLogical geometry, single PDF transform, checked raster dimensions, deterministic snapping, encoded-sRGB/linear-compositing boundary, ICC labeling, and ordered clip stack recorded in ADR 0007.
- Constraints: canonical f64 and local f32 rules remain fixed; screen/export semantic equivalence does not require byte-identical pixels.
- Evidence: coordinate/color golden suite, PDF/PNG/SVG structural checks, HiDPI matrix, and explicit tolerance policy.

### O-12 — Text, font fallback, and reproducibility strictness

- State: Accepted — evidence pending
- Decision owner: architecture-authority
- Needed before: shared text/layout and export fan-out
- Record: [ADR 0007 — coordinate, color, text, and export semantics](../adr/0007-coordinate-color-text-export.md)
- Accepted scope: retained PlotLayout/font identity, one shaping result, exact font/provenance and license evidence, TextToPath initial PNG boundary, searchable-PDF/outline modes, missing-glyph diagnostics, and staged dependency spikes recorded in ADR 0007.
- Constraints: one shaping/layout result is shared; renderer remeasurement is prohibited; raster-only text/PDF is prohibited for supported vector semantics.
- Evidence: font fixture manifest, searchable-PDF test, outline determinism test, fallback review, and license/SBOM evidence.

### O-13 — Annotation and interaction history details

- State: Accepted — evidence pending
- Decision owner: architecture-authority
- Needed before: v1 interaction/export fan-out
- Record: [API 0004 — annotations and accessibility semantics](api-0004-annotations-accessibility.md)
- Accepted scope: stable process-local AnnotationId, v1 annotation kinds and geometry spaces, logical hit testing, Plot State/export inclusion, UI State exclusion, and non-membership in view history recorded in API 0004.
- Constraints: basic annotations are v1 MUST; project/Scene serialization remains a v1 non-goal; transient cursor/UI state is excluded from ordinary exports.
- Evidence: interaction, revision, export, and accessibility fixtures.

### O-14 — Accessibility and standalone viewer semantics

- State: Accepted — evidence pending
- Decision owner: architecture-authority
- Needed before: v1 release review
- Record: [API 0004 — annotations and accessibility semantics](api-0004-annotations-accessibility.md)
- Accepted scope: keyboard actions, visible focus, contrast baselines and non-color cues, reduced-motion semantic preservation, SHOULD accessibility tree/bridge, and structured unavailable-capability behavior recorded in API 0004.
- Constraints: keyboard navigation/Legend, visible focus, contrast-aware defaults, and reduced motion are v1 MUST; screen-reader tree is SHOULD unless evidence promotes it.
- Evidence: keyboard matrix, contrast/reduced-motion review, platform accessibility checks, and viewer package/lifecycle tests.

### O-15 — GPU runtime and shader artifact details

- State: Accepted — evidence pending
- Decision owner: architecture-authority
- Needed before: renderer/runtime fan-out
- Record: [ADR 0008 — portable GPU runtime and shader artifacts](../adr/0008-portable-gpu-and-shaders.md)
- Accepted scope: wgpu 29.0.4/winit 0.30.13/raw-window-handle 0.6.2 implementation baseline, static verified WGSL, main-thread resource ownership, device-loss rebuild, and terminal OOM recorded in ADR 0008. These versions are not public support or MSRV claims.
- Constraints: `Backend::Auto` capability probe plus static override; no default startup microbenchmark; build/CI-time shader artifacts; no runtime untrusted shader compilation/download; Slang-RHI not in core.
- Evidence: shader validator corpus, artifact provenance, platform lifecycle matrix, device-loss/OOM tests, and benchmark manifest.

### O-16 — Native backend adoption and retirement gates

- State: Accepted — evidence pending
- Decision owner: architecture-authority
- Needed before: Phase 4 prototype merge
- Record: [ADR 0006 — support cells, benchmark protocol, and native gates](../adr/0006-support-benchmark-native-gates.md)
- Accepted scope: no native fan-out before portable/O-07/O-08 evidence; Go at the accepted two-cell/three-comparison/15% thresholds with regression and memory limits; quarantine and two-cycle retirement review recorded in ADR 0006.
- Constraints: Metal, D3D12/DXGI, and Vulkan remain conditional prototypes; adoption is never based solely on API novelty.
- Evidence: A/B frame/CPU/present/memory/features report and an explicit decision record.

### O-17 — Dependency, publication, and supply-chain policy

- State: Accepted — evidence pending
- Decision owner: architecture-authority
- Needed before: public package or native dependency release
- Record: [ADR 0009 — version, publication, and supply-chain policy](../adr/0009-version-publication-supply-chain.md)
- Accepted scope: no current MSRV or stability promise, non-publishable implementation packages, locked dependency review gates, future rolling floor, CycloneDX 1.7/Sigstore-SLSA targets, and no release workflow recorded in ADR 0009.
- Constraints: pre-alpha is non-publishable until explicitly changed; reference versions are not normative pins; all updates require compatibility, correctness, security, license, MSRV, and performance review.
- Evidence: CI policy, SBOM/license artifact, reproducible build check, and dependency regression report.

### O-18 — Future serialization schema

- State: Deferred/Closed by non-goal
- Decision owner: architecture-authority
- Needed before: any project/Scene save or interchange feature
- Record: [ADR 0009 — version, publication, and supply-chain policy](../adr/0009-version-publication-supply-chain.md)
- Future decision scope: schema ownership, migrations, resource identity, external references, size limits, trust model, and security validation require a separate schema/security/migration ADR before any save or interchange feature.
- Constraints: no v1 Scene/project serialization or RenderPacket wire format; PNG/PDF/SVG are outputs, not persistence.
- Evidence: separate schema/security ADR and migration/property tests.

## Decision discipline

O-01 through O-17 are recorded accepted contracts with implementation or environment evidence still pending. ADR 0010 is the accepted Phase-1 native core/facade contract and does not alter the requirements status. O-18 is Deferred/Closed by non-goal. Do not silently promote a reference dependency, candidate API, environment observation, parent research result, or benchmark target into an implementation or support result. If a future decision changes the accepted envelope, supersede or amend ADR 0002 explicitly and update the requirements and traceability registry together.
