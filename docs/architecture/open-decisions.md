# LumenPlot open architecture decisions

## Purpose and status

This list contains decisions that must be settled before implementation fan-out or a support claim. It does not reopen accepted architecture decisions. The published requirements and ADR 0002 remain intentionally honest about the pre-alpha baseline; an open item is a follow-up gate, not permission to invent a public API or to block publication. [ADR 0010](../adr/0010-phase1-native-core-facade-contract.md) records the accepted Phase-1 native core/facade envelope, [ADR 0011](../adr/0011-phase1b-facade-namespace-observation-traits.md) records its accepted Phase-1B namespace and observation amendment, [ADR 0012](../adr/0012-private-line-frame-and-png-contract.md) records the accepted private Phase-2A/2B line-frame and PNG boundary, [ADR 0013](../adr/0013-hidden-facade-private-python-line-png.md) records the staged Phase-3A hidden facade/private helper boundary, and [ADR 0014](../adr/0014-phase3a2-pinned-manylinux-wheel-evidence.md) records the staged Phase-3A2 pinned builder and same-wheel evidence boundary. The Phase-1 and bounded Phase-2 records have local implementation evidence; Phase-3A helper, package, and wheel evidence remain pending, and the public Phase-3B Matplotlib contract remains open.

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
- The Phase-2A private line frame and Phase-2B deterministic line/PNG sink are bounded by [ADR 0012](../adr/0012-private-line-frame-and-png-contract.md); this does not expand the public facade or close the full v1 export contract.
- The bounded Phase-2A/2B implementation and local evidence do not close full-v1 export. The staged Phase-3A owned hidden facade and private Python helper are bounded by [ADR 0013](../adr/0013-hidden-facade-private-python-line-png.md); the public Phase-3B result, diagnostic, canvas, and fallback schema remains open.
- Runtime/window/surface/GPU lifecycle is main-thread confined; Scene is single-writer; snapshots are immutable; workers are bounded and generation-cancellable; no non-reentrant lock crosses a Python callback; device loss rebuilds from retained CPU data; OOM is explicit.
- Backend Auto uses capability probing plus static override and no default startup microbenchmark.
- PNG and PDF are v1 MUST outputs; SVG is a v1 SHOULD and non-blocking; supported vector semantics are retained and raster-only PDF is forbidden.
- Project/Scene serialization is a v1 non-goal.
- v1 is pre-alpha; publication, public API stability, MSRV, performance, and platform support are not claimed without evidence.

## Implementation fan-out gates

### O-01 — Exact facade and crate/module split

- State: Accepted — Phase-1 implementation/local evidence recorded; later evidence pending
- Decision owner: architecture-authority
- Needed before: Rust workspace and binding fan-out
- Record: [ADR 0003 — facade and crate dependency graph](../adr/0003-facade-and-crate-dag.md), [ADR 0010 — Phase-1 native core and facade contract](../adr/0010-phase1-native-core-facade-contract.md), [ADR 0011 — Phase-1B facade namespace and observation traits](../adr/0011-phase1b-facade-namespace-observation-traits.md), [ADR 0012 — private line frame and deterministic PNG contract](../adr/0012-private-line-frame-and-png-contract.md), and [ADR 0013 — hidden line/PNG facade and private Python helper](../adr/0013-hidden-facade-private-python-line-png.md)
- Accepted scope: ADR 0003 fixes the Option-C public facade, internal crate/module boundaries, visibility, re-export, publication metadata, and dependency graph. ADR 0010 fixes the Phase-1A private engine boundary, Phase-1B minimum facade seam, and staged delivery order. ADR 0011 fixes the exact Phase-1B crate-root allowlist and private facade modules without changing the DAG. ADR 0012 fixes the private line-frame/export order without changing the facade DAG. ADR 0013 fixes the separately inventoried doc-hidden Phase-3A facade/helper boundary without changing the fifteen root types or DAG.
- Constraints: preserve the one-way DAG; keep concrete frontend/GPU/window types out of core; do not make a candidate crate layout a public API by accident.
- Evidence: dependency graph review, visibility scan, build matrix, and an ADR recording the final split.

### O-02 — Public Rust and Python API surface

- State: Accepted staged surface — Phase-1 exact surface recorded; Phase-3A helper surface recorded; implementation/evidence pending
- Decision owner: architecture-authority
- Needed before: frontend and FFI implementation
- Record: [API 0001 — native Scene, view, and owned data](api-0001-native-scene-state.md), [API 0003 — Phase-3A Python, NumPy, and private helper](api-0003-python-numpy-matplotlib.md), [ADR 0010 — Phase-1 native core and facade contract](../adr/0010-phase1-native-core-facade-contract.md), [ADR 0011 — Phase-1B facade namespace and observation traits](../adr/0011-phase1b-facade-namespace-observation-traits.md), and [ADR 0013 — hidden line/PNG facade and private Python helper](../adr/0013-hidden-facade-private-python-line-png.md)
- Accepted scope: ADR 0010 replaces the Phase-1 candidates with the exact opaque view/scale, owned `SeriesData`, `PlotScene`, transaction, snapshot, revision, and receipt observations. ADR 0011 fixes their direct crate-root namespace and exact trait guarantees. API 0003/ADR 0013 fix only the staged private Phase-3A helper, owned NumPy copy boundary, and ABI/runtime evidence gate; the public Phase-3B adapter surface remains open.
- Constraints: signatures must not leak engine chunks, LOD, caches, component revisions, or internal RenderPacket fields; the hidden module is not root-re-exported and has no product/semver/ABI/MSRV promise; no public Matplotlib result, diagnostic, canvas, or fallback schema is inferred.
- Evidence: Phase-1 local API evidence, conditional hidden-inventory mutations, exact NumPy dtype/stride/GIL/ownership tests, and the locked CPython/wheel matrix before helper integration.

### O-03 — Error and capability taxonomy

- State: Accepted — Phase-1 mapping recorded; evidence pending
- Decision owner: architecture-authority
- Needed before: API, adapter, runtime, and fallback implementation
- Record: [API 0002 — errors, capabilities, and fallback contract](api-0002-errors-capabilities-fallback.md), [ADR 0010 — Phase-1 native core and facade contract](../adr/0010-phase1-native-core-facade-contract.md), [ADR 0011 — Phase-1B facade namespace and observation traits](../adr/0011-phase1b-facade-namespace-observation-traits.md), and [ADR 0013 — hidden line/PNG facade and private Python helper](../adr/0013-hidden-facade-private-python-line-png.md)
- Accepted scope: API 0002 records stable public category/code tokens, capability/fallback diagnostics, internal `WorkOutcome`, and Rust/Python mapping. ADR 0010 additionally fixes the unpublished exhaustive Phase-1 `SceneErrorKind` set and its mapping to facade-owned `PublicError`. ADR 0011 fixes `as_str` as the sole public stable token observation and preserves the exact non-exhaustive/error trait boundary. ADR 0013 adds only the exhaustive source-less Phase-3A `BridgeError` export mapping; public fallback/result diagnostics remain a later Phase-3B decision.
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

- State: Accepted staged Phase-3A/3A2 policy — package and wheel evidence pending
- Decision owner: architecture-authority
- Needed before: Python bridge and wheel fan-out
- Record: [API 0003 — Phase-3A Python, NumPy, and private helper](api-0003-python-numpy-matplotlib.md), [ADR 0013 — hidden line/PNG facade and private Python helper](../adr/0013-hidden-facade-private-python-line-png.md), and [ADR 0014 — pinned manylinux wheel evidence](../adr/0014-phase3a2-pinned-manylinux-wheel-evidence.md)
- Accepted scope: GIL-enabled CPython 3.11–3.14 with `abi3-py311`, exact built-in native-endian float32/64 one-dimensional arrays, safe logical strides, copy-to-owned-f64 ingestion, NaN gaps, Inf rejection, exact source ranges, the private `_native.render_line_png` helper, and an initial runtime evidence pin of NumPy 2.4.6. Exact candidates pyo3 0.29.2, numpy 0.29.0, and maturin 1.14.1 remain implementation-lane pins.
- Constraints: writable/read-only arrays are never mutated; concurrent caller mutation is not synchronized; no borrowed escape, zero-copy promise, free-threaded/PyPy support, generic buffer/DLPack interface, or LumenPlot C ABI is claimed.
- Evidence: the [Phase-3A2 wheel contract](phase3a2-manylinux-wheel-evidence.md) fixes the direct pinned manylinux builder, locked/offline graph, exact one-wheel CPython 3.11–3.14 matrix, metadata/RECORD/auditwheel/ELF/abi3/license/SBOM/provenance checks, and CI-local manifest schema; dtype/stride/alignment/gap/error/lifetime tests, GIL borrow-drop-detach tests, and copy/render correctness evidence remain implementation gates.

### O-10 — Matplotlib compatibility and profile matrix

- State: Phase-3B public contract open; Phase-3A helper and Phase-3A2 wheel evidence staged separately
- Decision owner: architecture-authority
- Needed before: adapter release claim
- Record: [API 0003 — Phase-3A Python, NumPy, and private helper](api-0003-python-numpy-matplotlib.md), [ADR 0013 — hidden line/PNG facade and private Python helper](../adr/0013-hidden-facade-private-python-line-png.md), and [ADR 0014 — pinned manylinux wheel evidence](../adr/0014-phase3a2-pinned-manylinux-wheel-evidence.md)
- Accepted scope: Phase-3A explicitly excludes a Matplotlib dependency, backend module, entry point, public `render_png`, result/diagnostic/warning types, canvas, and fallback. The later Phase-3B decision must use documented public APIs only, an exact object whitelist plus public `RendererBase` collector, the exact eligible trace, explicit style and non-PNG guards, 72-point mapping, and terminal-failure no-fallback rules.
- Mandatory future boundary: Matplotlib 3.11.1 / backend API 1.1; evaluate
  exactly that surface and forbid `_Backend`, `_renderer`, `_api`,
  `_pylab_helpers`, any `matplotlib._*` path, private artist/transform/cache
  helpers, and undocumented `Axes.axison`.
- Mandatory future collector trace: exactly one Figure-background `draw_path`
  plus one Line2D `draw_path`; axes patch, spines, ticks, text, markers, images,
  collections, mesh/Gouraud, custom artists, and every other renderer callback
  are excluded and must cause explicit unsupported handling.
- Constraints: the public Figure/Artist authority and high-level profile roles from ADR 0002 remain; their exact public result, diagnostic, canvas, generation, fallback, and file/path schema is not frozen by API 0003/ADR 0013.
- Evidence: Phase-3A helper/wheel/runtime evidence first; later loader/entry-point, public API, strict unsupported, hybrid whole-frame Agg, diagnostic, and profile-separated evidence only after Phase-3B is accepted.

### O-11 — Coordinate, unit, color, alpha, and ICC policy

- State: Accepted — evidence pending
- Decision owner: architecture-authority
- Needed before: renderer and export fan-out
- Record: [ADR 0007 — coordinate, color, text, and export semantics](../adr/0007-coordinate-color-text-export.md) and [ADR 0012 — private line frame and deterministic PNG contract](../adr/0012-private-line-frame-and-png-contract.md)
- Accepted scope: explicit logical units/inch, top-left DisplayLogical geometry, single PDF transform, checked raster dimensions, deterministic snapping, encoded-sRGB/linear-compositing boundary, ICC labeling, and ordered clip stack recorded in ADR 0007; ADR 0012 bounds the private line-frame, coverage, alpha, and deterministic line/PNG slice.
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

O-01 through O-17 are recorded accepted contracts with implementation or environment evidence staged by phase. ADR 0010 and its narrow ADR 0011 amendment are the accepted Phase-1 native core/facade contract; Phase-1A/B implementation and local contract evidence now exist without altering the requirements status. ADR 0012 records the accepted private Phase-2A/2B line-frame and PNG boundary, whose bounded implementation and local evidence do not close full-v1 export. ADR 0013 records the staged Phase-3A hidden facade/private helper boundary, and ADR 0014 records the Phase-3A2 pinned builder, same-wheel matrix, and CI-local evidence schema; their helper, package, and wheel evidence remain pending and Phase-3B public Matplotlib schema is open. O-18 is Deferred/Closed by non-goal. Do not silently promote a reference dependency, candidate API, environment observation, parent research result, or benchmark target into an implementation or support result. If a future decision changes the accepted envelope, supersede or amend ADR 0002 explicitly and update the requirements and traceability registry together.
