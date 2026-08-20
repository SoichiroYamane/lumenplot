# LumenPlot open architecture decisions

## Purpose and status

This list contains decisions that must be settled before implementation fan-out or a support claim. It does not reopen accepted architecture decisions. The published requirements and ADR 0002 are intentionally honest before implementation; an open item is a follow-up gate, not permission to invent a public API or to block publication of the pre-alpha baseline.

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

- State: Open
- Decision owner: architecture-authority
- Needed before: Rust workspace and binding fan-out
- Decide: the exact public facade, internal crate/module boundaries, visibility, feature flags, publication metadata, and dependency graph.
- Constraints: preserve the one-way DAG; keep concrete frontend/GPU/window types out of core; do not make a candidate crate layout a public API by accident.
- Evidence: dependency graph review, visibility scan, build matrix, and an ADR recording the final split.

### O-02 — Public Rust and Python API surface

- State: Open
- Decision owner: architecture-authority
- Needed before: frontend and FFI implementation
- Decide: public Scene/facade ownership, handles, transaction/update model, revision observation, backend selection configuration, export entry points, viewer lifecycle surface, and Python object model.
- Constraints: this bundle does not declare exact function, method, class, trait, or exception signatures; signatures must not leak internal RenderPacket fields.
- Evidence: API review, docs build, import/loader smoke, compatibility policy, and negative tests for unsupported values.

### O-03 — Error and capability taxonomy

- State: Open
- Decision owner: architecture-authority
- Needed before: API, adapter, runtime, and fallback implementation
- Decide: stable categories for invalid input, unsupported capability, fallback diagnostic, device loss, out-of-memory, cancellation, stale generation, host-loop misuse, and internal failure.
- Constraints: strict mode must be explicit; hybrid fallback must be observable; no silent omission or best-effort degradation.
- Evidence: error mapping table, Python exception mapping, serialization/diagnostic review, and failure fixtures.

### O-04 — Internal RenderPacket schema and resource lifecycle

- State: Open
- Decision owner: architecture-authority
- Needed before: renderer fan-out
- Decide: packet fields, semantic-to-packet lowering, validation order, opaque logical ID format, generation association, resource cache ownership, packet drop/close behavior, and renderer capability validation.
- Constraints: immutable, validated, process-local, internal, non-serialized; no wgpu/window/Python concrete types; export does not reverse-engineer GPU buffers.
- Evidence: property tests, schema review, resource-lifetime tests, stale-generation tests, and a no-wire-format check.

### O-05 — Scene ownership, mutation, revision, and history

- State: Open
- Decision owner: architecture-authority
- Needed before: core state and interaction fan-out
- Decide: stable identity/handle policy, single-writer transaction/result type, revision increment rules, canonical view, current viewport, history entry semantics, visibility/Legend/annotation ownership, and export snapshot selection.
- Constraints: native PlotScene authority; Matplotlib Figure/Artist authority in adapter mode; derived adapter Scene is revisioned cache; UI State cannot enter ordinary exports.
- Evidence: state-machine/property tests, concurrent worker tests, history tests, export-state fixture, and adapter synchronization review.

### O-06 — Window, viewer, host loop, and lifecycle semantics

- State: Open
- Decision owner: architecture-authority
- Needed before: standalone viewer, Python `show`, notebook, and platform fan-out
- Decide: native-owned versus host-pumped loop, multiple-window ownership, close/drop, suspend/resume, resize, surface loss, device loss, OOM recovery, reentrancy, shutdown, and notebook transport behavior.
- Constraints: runtime/window/surface/GPU main-thread rule; no Python callback lock crossing; Qt/WebAgg/ipympl transports are not silently included in the native latency claim.
- Evidence: lifecycle matrix, platform tests, repeated create/destroy tests, notebook/host-loop smoke tests, and device-loss/OOM fixtures.

### O-07 — Declared hardware, driver, and CI matrix

- State: Open
- Decision owner: architecture-authority
- Needed before: support and p99 release claims
- Decide: OS versions, GPU vendors/models, driver ranges, API feature levels, Wayland/X11 cells, HiDPI scales, headless/CI policy, compositor/present semantics, and minimum evidence per cell.
- Constraints: no generic support claim from a single environment; platform/GPU result is `environment required` until a declared cell is exercised.
- Evidence: machine manifest, startup/render/lifecycle matrix, benchmark artifacts, and release review.

### O-08 — Benchmark protocol and performance accounting

- State: Open
- Decision owner: architecture-authority
- Needed before: native gate and dependency updates
- Decide: exact clock boundaries, present blocking semantics, GPU-complete/readback policy, warm-up definition, fixture order/randomization, sample rejection rules, allocation/copy counters, and p99 reporting format.
- Constraints: at least 1000 measured frames per fixture; p50/p95/p99; input-to-present, event-to-packet, packet-to-submit, and submit-to-GPU-complete/readback separate; strict, hybrid, accelerated, and native profiles never combined.
- Evidence: reproducible benchmark runner, manifest schema, repeated-run analysis, and dependency A/B report.

### O-09 — Python ABI and NumPy ingestion policy

- State: Open
- Decision owner: architecture-authority
- Needed before: Python bridge and wheel fan-out
- Decide: Python minor range, ABI/abi3 policy, NumPy supported dtypes, shape/stride/contiguity, finite/non-finite handling, read-only/mutable semantics, borrow window, GIL detach, copy boundary, thread/lifetime rules, and error mapping.
- Constraints: NumPy zero-copy is an ingestion implementation technique only; long-lived state is owned sealed chunks; NumPy-to-GPU zero-copy is not promised.
- Evidence: dtype/stride/mutation/lifetime tests, wheel matrix, FFI panic/error tests, and upload/copy benchmark.

### O-10 — Matplotlib compatibility and profile matrix

- State: Open
- Decision owner: architecture-authority
- Needed before: adapter release claim
- Decide: exact supported Matplotlib/Python versions, public/common Artist set, image/Gouraud/hatch/filter policy, text/mathtext/TeX behavior, transport integrations, profile configuration syntax, and diagnostics visibility.
- Constraints: fixed package/module names and three profile roles are accepted; full private/arbitrary compatibility is not a v1 requirement; standard adapter cannot inherit native zero-Python SLOs.
- Evidence: loader/entry-point tests, public API compatibility suite, strict error fixtures, hybrid fallback goldens, and profile-separated benchmark.

### O-11 — Coordinate, unit, color, alpha, and ICC policy

- State: Open
- Decision owner: architecture-authority
- Needed before: renderer and export fan-out
- Decide: scientific/display/local coordinate transforms, origin and y orientation, logical versus physical pixels, PDF points, color space, alpha/premultiplication, ICC/profile handling, clipping, and HiDPI rounding.
- Constraints: canonical f64 and local f32 rules remain fixed; screen/export semantic equivalence does not require byte-identical pixels.
- Evidence: coordinate/color golden suite, PDF/PNG/SVG structural checks, HiDPI matrix, and explicit tolerance policy.

### O-12 — Text, font fallback, and reproducibility strictness

- State: Open
- Decision owner: architecture-authority
- Needed before: shared text/layout and export fan-out
- Decide: shaping stack, font identity/hash/variation manifest, system versus bundled fallback, license requirements, mathtext and TeX boundary, PDF subset/ToUnicode policy, deterministic outline fallback, and missing-glyph diagnostics.
- Constraints: one shaping/layout result is shared; renderer remeasurement is prohibited; raster-only text/PDF is prohibited for supported vector semantics.
- Evidence: font fixture manifest, searchable-PDF test, outline determinism test, fallback review, and license/SBOM evidence.

### O-13 — Annotation and interaction history details

- State: Open
- Decision owner: architecture-authority
- Needed before: v1 interaction/export fan-out
- Decide: annotation geometry and coordinate systems, style and clipping, hit-testing, editability, persistence boundary, export inclusion, and history snapshot representation.
- Constraints: basic annotations are v1 MUST; project/Scene serialization remains a v1 non-goal; transient cursor/UI state is excluded from ordinary exports.
- Evidence: interaction, revision, export, and accessibility fixtures.

### O-14 — Accessibility and standalone viewer semantics

- State: Open
- Decision owner: architecture-authority
- Needed before: v1 release review
- Decide: keyboard focus model, visible focus rendering, contrast defaults, reduced-motion transitions, semantic screen-reader tree scope, platform accessibility APIs, viewer packaging, and fallback behavior.
- Constraints: keyboard navigation/Legend, visible focus, contrast-aware defaults, and reduced motion are v1 MUST; screen-reader tree is SHOULD unless evidence promotes it.
- Evidence: keyboard matrix, contrast/reduced-motion review, platform accessibility checks, and viewer package/lifecycle tests.

### O-15 — GPU runtime and shader artifact details

- State: Open
- Decision owner: architecture-authority
- Needed before: renderer/runtime fan-out
- Decide: wgpu feature limits, adapter/device selection, surface configuration, queue and staging ownership, shader artifact format, compiler invocation, cache key, artifact hash manifest, device-loss rebuild, and OOM policy details.
- Constraints: `Backend::Auto` capability probe plus static override; no default startup microbenchmark; build/CI-time shader artifacts; no runtime untrusted shader compilation/download; Slang-RHI not in core.
- Evidence: shader validator corpus, artifact provenance, platform lifecycle matrix, device-loss/OOM tests, and benchmark manifest.

### O-16 — Native backend adoption and retirement gates

- State: Open
- Decision owner: architecture-authority
- Needed before: Phase 4 prototype merge
- Decide: meaningful-benefit threshold, maintenance-cost review, feature parity expectations, retirement criteria, and how native paths are represented in support and benchmark reports.
- Constraints: Metal, D3D12/DXGI, and Vulkan remain conditional prototypes; adoption is never based solely on API novelty.
- Evidence: A/B frame/CPU/present/memory/features report and an explicit decision record.

### O-17 — Dependency, publication, and supply-chain policy

- State: Open
- Decision owner: architecture-authority
- Needed before: public package or native dependency release
- Decide: exact MSRV, semver/API stability stage, publish controls, license allowlist, advisory policy, SBOM format, reproducible build inputs, artifact signing/verification, and dependency update cadence.
- Constraints: pre-alpha is non-publishable until explicitly changed; reference versions are not normative pins; all updates require compatibility, correctness, security, license, MSRV, and performance review.
- Evidence: CI policy, SBOM/license artifact, reproducible build check, and dependency regression report.

### O-18 — Future serialization schema

- State: Deferred by non-goal
- Decision owner: architecture-authority
- Needed before: any project/Scene save or interchange feature
- Decide: schema owner/versioning, migrations, resource identity, external data references, size limits, trust model, and security validation.
- Constraints: no v1 Scene/project serialization or RenderPacket wire format; PNG/PDF/SVG are outputs, not persistence.
- Evidence: separate schema/security ADR and migration/property tests.

## Decision discipline

When an open item is resolved, record the chosen scope and evidence gate in a follow-up ADR or reviewed implementation contract. Do not silently promote a reference dependency, candidate API, environment observation, parent research result, or benchmark target into an accepted result. If a decision changes the accepted envelope, supersede or amend ADR 0002 explicitly and update the requirements and traceability registry together.
