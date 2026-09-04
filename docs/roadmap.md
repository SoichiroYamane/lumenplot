# LumenPlot implementation roadmap

- Status: pre-alpha planning document
- Updated: 2026-09-05
- Planning unit: ordered milestones, not release dates
- Source of truth for requirement status: [v1 traceability](requirements/traceability-v1.0.md)

This roadmap turns the accepted requirements and ADRs into an implementation
sequence. It does not create a support, compatibility, performance, or release
claim. A milestone is complete only when its implementation and named evidence
land together.

## 1. Current baseline

The repository already has useful vertical slices, but it is not yet the
GPU-native interactive product described by the v1 requirements.

Implemented with bounded local evidence:

- the Phase-1 Scene, transaction, revision, owned-data, LOD, and minimal Rust
  facade substrate;
- the bounded Phase-2 CPU line raster and deterministic PNG path, subsequently
  extended by the Phase-3B frame-command work;
- the Phase-3A Python bridge and private-helper wheel evidence;
- the Phase-3B public Matplotlib backend with strict and explicit whole-frame
  hybrid behavior, including the shipped hybrid default;
- bounded native Matplotlib eligibility for line, decorated axes, fill, bar, and
  step geometry, with base-10 log axes and a limited Legend/text surface;
  compositing and date/unit-label code is merged, while its adopted
  traceability rows remain open pending reconciliation;
- the M1 synchronous CPU-side frame seam and the O-08 five-block benchmark
  harness;
- bounded private RenderPacket validation with distinct scene/work/device
  generations, origin-relative line geometry, static WGSL provenance checks,
  and headless offscreen wgpu line rendering/readback tests;
- a bounded backend-neutral logical resource cache with generation-qualified
  keys, packet leases, completion-fence retirement, multiple-owner accounting,
  and explicit device-generation invalidation tests;
- a backend-neutral runtime/viewer lifecycle and semantic-input state model,
  a private line-only vector PDF sink, and strict/hybrid benchmark validation
  that refuses unavailable accelerated/native environments explicitly.

Still absent or incomplete:

- a full shared semantic/layout frame and the complete renderer-owned
  RenderPacket lifecycle from [ADR 0004](adr/0004-renderpacket-resource-lifecycle.md);
  PR #91 supplies only the bounded cache/lease/fence model and deterministic
  device-generation invalidation tests;
- the Phase 3 v1 3D line/triangulated-surface capability and its `AT-FUNC-3D`
  four-part mplot3d parity evidence; existing whole-frame Agg fallback does not
  close the native capability;
- a complete portable GPU renderer and declared real-device evidence; the
  current wgpu implementation is a bounded headless line-rendering slice;
- a real window/surface present loop and standalone viewer integration; the
  current runtime/viewer implementation is a backend-neutral lifecycle and
  input state model;
- accelerated-native product delivery, native interaction, and declared
  platform/present evidence;
- full retained text/layout, annotations, Legend interaction, accessibility,
  and public vector PDF output; the current PDF sink is private and line-only;
- v1 release, support, security, and performance closure.

The quarantined Metal lane is not a shortcut around these gaps. [ADR
0017](adr/0017-metal-native-adoption-decision-record.md) records a current
No-Go disposition, and [ADR 0006](adr/0006-support-benchmark-native-gates.md)
requires the portable baseline and declared-hardware evidence before native
backend adoption can be reconsidered.

## 2. Priority rules

Work is ordered by these rules:

1. Restore one trustworthy source of truth before extending the surface.
2. Close the existing CPU/Matplotlib vertical slice before multiplying
   backends.
3. Stabilize the internal semantic frame and packet lifecycle before the v1 3D
   slice or additional concrete GPU/runtime work.
4. Implement the portable wgpu path before any native Metal/D3D12/Vulkan path.
5. Land behavior, negative fixtures, traceability updates, and reproducible
   evidence in the same milestone.
6. Keep unsupported behavior explicit; do not expand strict eligibility by
   approximation.

Relative effort below is directional: **S** is a focused change, **M** is a
multi-module slice, and **L** is a cross-crate or environment-backed milestone.

## 3. Ordered milestones

### M0 — Reconcile the baseline and make verification reproducible

- Priority: P0
- Effort: S-M
- Depends on: nothing

Implement:

- reconcile the traceability rows and architecture summaries with the merged
  compositing and date/unit-label slices, preserving bounded evidence and
  leaving LP-FUNC-035 and LP-FUNC-037 open until their acceptance evidence is
  reviewed;
- keep the implemented `hybrid` default synchronized with the accepted
  `hybrid-explicit` profile, while retaining the current staged `strict` /
  `hybrid` spelling until the M1 public profile-name closure;
- make the documented local verification path enter the correct Nix/dev-shell
  environment, supply native link dependencies such as `libiconv`, install the
  Python package before integration tests, and use a writable Matplotlib cache;
- add a single contributor-facing command or script for Rust, Python,
  architecture, formatting, and documentation gates;
- remove or clearly label checked-in platform-specific extension artifacts so
  a foreign `_native.abi3.so` cannot be mistaken for a locally runnable build.

Exit criteria:

- the roadmap, README, architecture overview, open decisions, and traceability
  agree on implemented features and profile defaults;
- the documented clean-checkout verification path passes without manual
  environment repair;
- failures caused by an uninstalled package or wrong-platform extension are
  reported as setup failures rather than product-test failures.

### M1 — Close and modularize the public Matplotlib slice

- Priority: P0
- Effort: M
- Depends on: M0

Implement:

- split the current `python/lumenplot_mpl/backend.py` hotspot into private
  modules for eligibility/style contracts, collector grammar, frame-spec
  assembly, and canvas/diagnostic publication while preserving the API 0005
  public surface;
- keep the LP-MPL-020 growth rule atomic for every artist class: whitelist,
  collector expectation, style contract, strict/hybrid behavior, and Agg
  parity fixtures land together;
- finish the full strict error/terminal-failure matrix, generation/reentrancy
  fixtures, and packaged public-backend runtime evidence;
- close the already-landed compositing and date/unit-label slices in
  traceability, or record the exact remaining acceptance gaps;
- keep `accelerated-native` explicitly unavailable until a real accelerated
  render-and-present path exists.

Exit criteria:

- the installed wheel passes the accepted CPython 3.11-3.14 and Matplotlib
  matrix for loader, strict, hybrid, diagnostics, file output, and failure
  behavior;
- all currently eligible primitives have Agg-oracle geometry/style/pixel
  fixtures;
- adding a new eligibility class no longer requires editing one monolithic
  2,000+ line module in several unrelated regions.

### M2 — Complete the shared semantic frame and RenderPacket contract

- Priority: P0
- Effort: L
- Depends on: M0; M1 supplies the mature adapter consumer

Current status: PR #91 records a bounded private logical-resource cache,
packet lease transfer, completion-fence retirement, multiple-owner accounting,
and device-generation invalidation model. The shared semantic/layout frame,
concrete renderer-owner integration, device-loss rebuild, and full environment
evidence remain open.

Implement:

- evolve the bounded M1 line `FramePacket` into the internal shared
  semantic/layout frame required by the architecture overview;
- represent ordered primitives, transforms, clip stacks, resolved styles,
  background, and explicit fallback facts without frontend or GPU concrete
  types;
- implement distinct SceneRevision, WorkGeneration, and DeviceGeneration
  handling, whole-packet validation, immutable publication, and stale-work
  rejection;
- implement logical resource IDs, cache ownership, packet leases, completion
  retirement, and device-loss invalidation as specified by ADR 0004;
- preserve origin-relative f32 narrowing only at the renderer boundary while
  retaining canonical scientific values as f64;
- add property tests, malformed/capacity tests, visibility/type scans, and
  negative checks preventing a public/serialized packet API.

Exit criteria:

- the CPU export path and a second renderer test double consume the same
  validated frame/packet meaning;
- stale generations, incomplete packets, invalid resources, and premature
  retirement fail deterministically;
- core/render-api remain free of Python, Matplotlib, wgpu, window, and native
  GPU types.

### M2.5 — Add the v1 3D Agg-parity slice

- Priority: P0
- Effort: L
- Depends on: M2; M1 supplies the mature adapter consumer
- Requirements phase: 3 (the fractional milestone label is not a new phase)

Before implementation, resolve the four stop conditions in [ADR
0016](adr/0016-v1-3d-envelope-and-agg-parity.md) and
[O-19 through O-22](architecture/open-decisions.md#o-19-3d-projection-default):
projection default, z-origin/local-f32 precision, scatter3D requirement
alignment, and internal packet-schema versioning.

Implement only after those decisions:

- extend the shared semantic frame with explicit projection/view facts and
  canonical f64 x/y/z bounds while preserving existing authority, revision, and
  generation rules;
- support 3D polylines and triangulated surface/mesh geometry through the
  existing internal renderer seam, with deterministic projected triangle/depth
  ordering and no public or serialized RenderPacket;
- map the accepted public mplot3d surface through the existing adapter profiles:
  `strict-common-2d` refuses, fully recognized `hybrid-explicit` content may use
  the native path, and unsupported content retains diagnosed whole-frame Agg
  fallback;
- add the pinned `FigureCanvasAgg` mplot3d fixture set for all four §15.1 parity
  parts, including explicit projection attributes, large-offset f64 z bounds,
  non-intersecting ordering, and artifact-exposing intersecting triangles; and
- keep scatter3D absent from both implementation and evidence until O-21 assigns
  it to `LP-FUNC-025`, `LP-FUNC-017`, or a separately accepted row.

Exit criteria:

- `AT-FUNC-3D` has native semantic/geometry evidence plus adapter-originated
  four-part parity; existing whole-frame fallback is not counted as closure;
- projected line/triangle geometry, decoded pixels, style/text, and reference
  painter-order artifacts match the pinned Agg oracle without widened
  tolerances or a superiority substitution;
- 3D state obeys the existing authority, immutable-publication, cancellation,
  stale-generation, lifecycle, and no-write failure contracts; and
- static checks prove RenderPacket remains internal, process-local,
  non-serialized, non-persistent, and absent from the public surface.

### M3 — Implement the portable offscreen wgpu vertical slice

- Priority: P1
- Effort: L
- Depends on: M2 and M2.5

Implement:

- adopt the staged dependency baseline from [ADR
  0008](adr/0008-portable-gpu-and-shaders.md) through the required dependency,
  license, and lockfile review;
- render the existing line/fill/bar/step and accepted 3D line/triangle
  frame-command subset offscreen with reviewed static WGSL and explicit
  artifact hashes/provenance;
- implement prepare/upload/draw/readback with bounded allocations, resource
  reuse, and device-generation checks;
- compare decoded output against the CPU reference and Agg oracle under named
  tolerances at 1x, 1.25x, 2x, and 3x semantic scale fixtures;
- add explicit device-unavailable, validation, device-loss, and OOM outcomes.

Exit criteria:

- a headless portable GPU test renders the supported packet subset without
  bypassing the semantic frame;
- shader validation/provenance and runtime-download negative checks pass;
- correctness passes on the Lavapipe control cell and at least one real
  portable-GPU environment, without yet making a broad support claim.

### M4 — Build runtime, viewer, and native interaction

- Priority: P1
- Effort: L
- Depends on: M3 and the state substrate from M2

Implement:

- main-thread `EngineSession` ownership for adapter/device/queue and 0..N
  surfaces, with explicit standalone and host-pumped modes;
- surface configure/resize/suspend/resume/loss handling, device rebuild from
  retained CPU state, terminal OOM, idempotent close, and no resurrection
  after close;
- the standalone viewer over the public facade;
- pan, anchor-preserving zoom, box zoom, Home, Previous/Next history,
  coalesced gesture commits, and forward-tail truncation;
- keyboard equivalents and reentrancy/foreign-callback guards from ADR 0005
  and API 0004.

Exit criteria:

- repeated create/draw/resize/close cycles pass on a declared environment;
- interaction changes advance revisions exactly once per committed semantic
  transition and never require a Python callback per native frame;
- close, stale work, surface loss, device loss, and OOM have observable,
  bounded outcomes.

### M5 — Close v1 semantic output and UX requirements

- Priority: P1
- Effort: L
- Depends on: M2; interactive portions also depend on M4

Implement in this order:

1. retained text shaping/layout with exact font identity and shared glyph
   geometry;
2. numeric, date/unit tick labels, axis labels, titles, and Legend layout
   through that shared result;
3. Plot State grid/visibility, Legend hit testing, cursor inspection, and the
   four required annotation kinds;
4. keyboard/focus/contrast/reduced-motion behavior and the semantic
   accessibility tree/bridge boundary;
5. full structural PNG closure and vector PDF with searchable text or the
   specified deterministic outline fallback;
6. SVG only after PNG/PDF MUST requirements pass, because SVG is non-blocking.

Exit criteria:

- interactive, PNG, and PDF paths consume one retained layout result and no
  renderer remeasures text or Legend geometry;
- ordinary export contains Plot State and annotations but excludes hover,
  focus, selection, pointer, and drag chrome;
- PDF structural tests prove vector primitives and valid text/outline behavior;
- accessibility and annotation acceptance fixtures pass on every claimed
  host, with explicit diagnostics where a platform bridge is unavailable.

### M6 — Deliver and measure accelerated-native behavior

- Priority: P2
- Effort: L
- Depends on: M3, M4, and the benchmark/tooling parts of M0

Implement:

- connect the MonotonicX LOD hierarchy to a retained accelerated render path
  with bounded worker queues, cancellation, and upload reuse;
- add 10M-point native and adapter fixtures, resident/streamed scenarios,
  append/update workloads, allocation/upload/cache counters, and RSS memory
  instrumentation;
- complete scheduler, GPU timestamp, queue-completion, and available scanout
  observations without combining clock domains;
- run five fresh-process blocks of at least 1,000 accepted frames per fixture
  and retain raw JSONL, manifests, p50/p95/p99, maximum block p99, and paired
  bootstrap reports;
- keep strict, hybrid, accelerated, and native profiles separate.

Exit criteria:

- `accelerated-native` is a real end-to-end render/present profile rather than
  the current CPU seam-resolution measurement;
- the 10M native gate, hot-path counters, correctness checks, and memory policy
  have reproducible evidence on declared cells;
- 60/120 Hz and 10M/100M values are described only as measured results or
  explicitly labelled targets.

### M7 — Cross-platform, supply-chain, and pre-alpha release closure

- Priority: P2
- Effort: L/environment-backed
- Depends on: M1-M6, including M2.5, for the surface being claimed

Implement:

- execute the O-07 Windows/D3D12, Ubuntu/Vulkan, macOS/Metal, display-scale,
  and Lavapipe-control matrices for the portable path;
- complete unsafe review, malformed size/input tests, shader provenance,
  dependency/license review, SBOM, artifact provenance, secret scanning, and
  publication metadata;
- publish wheels only for cells that pass package/import/FFI/runtime evidence;
- close every normative v1 requirement or narrow the release scope through an
  accepted requirement/ADR change;
- assemble functional, correctness, performance, quality, security, and
  support evidence into the release review bundle.

Exit criteria:

- each support statement names a passing OS/GPU/driver/compositor/scale cell;
- the complete clean release candidate passes all documented gates from
  reproducible commands and artifacts;
- no README, package metadata, or release note claims stability, compatibility,
  platform support, or performance beyond the recorded evidence.

## 4. Dependency map

```text
M0 truth + reproducible verification
 ├─> M1 Matplotlib/public-package closure ─────┐
 └─> M2 semantic frame + RenderPacket ─────────┴─> M2.5 v1 3D parity
       │                                              │
       │                                              └─> M3 portable offscreen wgpu
       │                                                    └─> M4 runtime/viewer/interaction
       │                                                            └─> M6 accelerated end-to-end path
       └─> M5 text/layout/export/UX ────────────────────────────────────────┘

M1 + M2 + M2.5 + M3 + M4 + M5 + M6 ──> M7 release evidence
```

M1 and the early design/test work of M2 may overlap. M2.5 starts only after M2
and its O-19–O-22 decisions are accepted; M3 follows M2.5 and must not invent a
renderer-specific packet. M5's retained layout may start after M2 while
M2.5/M3/M4 proceed, provided every sink continues to consume the same semantic
result.

## 5. Work deliberately deferred

Do not prioritize these ahead of the ordered v1 milestones above:

- Metal, D3D12/DXGI, or native Vulkan fast paths. Reopen only after the
  portable baseline and O-16 thresholds can be evaluated; Metal is currently
  No-Go under ADR 0017.
- project/Scene serialization or a public RenderPacket/wire format.
- full Matplotlib private-API, custom-Artist, GUI-toolkit, or rcParams parity.
- native scatter, markers, error bars, polar, quiver, images, contours,
  secondary axes, large series panels, and advanced ArbitraryXY
  simplification/picking unless a blocking v1 requirement is explicitly
  accepted for them; scatter3D additionally waits for O-21 classification.
- SVG optimization before required PNG and vector PDF closure.

## 6. Next three implementation slices

The recommended immediate queue is:

1. **M0 baseline reconciliation** — update traceability for the latest merged
   work, settle the profile default, and make the clean verification command
   reliable on macOS/Nix and wheel-installed Python. The bounded M0 code and
   evidence lanes are now merged locally; the release remains pre-alpha.
2. **M1 adapter modularization plus packaged runtime evidence** — reduce the
   `backend.py` collision hotspot without changing public behavior, then close
   the accepted Phase-3B package matrix.
3. **M2 packet/resource-lifecycle slice** — complete the shared semantic frame,
   WorkGeneration/DeviceGeneration validation, stale rejection, renderer test
   double, logical cache, packet leases, completion retirement, and device-loss
   invalidation before expanding the wgpu command subset.

These three slices reduce current ambiguity and implementation risk while
creating the narrowest safe path to the first real portable GPU frame.

## 7. Governing references

- [Canonical v1 requirements](requirements/lumenplot-v1.0.md)
- [Requirement traceability and evidence status](requirements/traceability-v1.0.md)
- [Architecture overview](architecture/overview.md)
- [Open decisions and evidence gates](architecture/open-decisions.md)
- [ADR 0004 — RenderPacket lifecycle](adr/0004-renderpacket-resource-lifecycle.md)
- [ADR 0005 — runtime and viewer lifecycle](adr/0005-runtime-viewer-host-loop.md)
- [ADR 0006 — support and benchmark gates](adr/0006-support-benchmark-native-gates.md)
- [ADR 0007 — coordinate, text, color, and export semantics](adr/0007-coordinate-color-text-export.md)
- [ADR 0008 — portable GPU and shader baseline](adr/0008-portable-gpu-and-shaders.md)
- [ADR 0015 — public Matplotlib adapter contract](adr/0015-phase3b-public-matplotlib-adapter-contract.md)
- [ADR 0016 — v1 3D envelope and Agg-parity acceptance](adr/0016-v1-3d-envelope-and-agg-parity.md)
- [ADR 0017 — Metal No-Go disposition](adr/0017-metal-native-adoption-decision-record.md)
- [API 0004 — annotations and accessibility](architecture/api-0004-annotations-accessibility.md)
- [Phase-3B public backend surface](architecture/api-0005-phase3b-public-matplotlib-backend-surface.md)
