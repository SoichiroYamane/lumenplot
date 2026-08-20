# ADR 0003: Facade and crate dependency graph

- Status: **Accepted contract**
- Date: 2026-08-21
- Decision owner: architecture-authority
- Recorded by: implementation-worker
- Scope: O-01 facade, crate/module boundaries, visibility, publication guards, and first-slice order
- Governing architecture: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md)
- Open-decision record: [O-01 — Exact facade and crate/module split](../architecture/open-decisions.md#o-01-exact-facade-and-cratemodule-split)

This ADR records an accepted implementation boundary. It does not report that the workspace, crates, bindings, or runtime have been implemented. The current product status remains the pre-alpha status in the [requirements traceability registry](../requirements/traceability-v1.0.md).

## Requirement references

The contract records the architecture and publication boundaries for `LP-PROD-010`, `LP-PROD-014`, `LP-MPL-001`, `LP-MPL-002`, `LP-MPL-017`, `LP-QUAL-025`, and `LP-REL-002` in the [requirements](../requirements/lumenplot-v1.0.md#5-basic-architecture).

## Context

ADR 0002 fixed the one-way dependency direction but intentionally left the exact facade and crate split open. The split must preserve an independent engine, keep concrete frontend/GPU/window types out of the semantic core, prevent an internal packet from becoming a public format, and keep publication and visibility from being inferred from an internal `pub` item.

## Decision

### Option-C workspace shape

Use one future Rust public facade and the following implementation crates and product edges:

```text
python/lumenplot-mpl ── lumenplot-python ──┐
                                           │
native viewer/frontend ── crates/lumenplot ─┼── lumenplot-engine
                                           │                 │
                                           └── lumenplot-export

lumenplot-engine ── semantic frame ── lumenplot-render-api
                                      │
                                      └── lumenplot-render-wgpu

lumenplot-runtime ── main-thread session/surface/device lifecycle
crates/lumenplot-viewer ── viewer product edge over facade + runtime
crates/lumenplot-bench ── internal evidence tooling
```

The exact ownership and allowed edges are:

| Component | Accepted role and dependency boundary |
| --- | --- |
| `crates/lumenplot` | The one future Rust public facade. It depends only on `lumenplot-engine` and `lumenplot-export`. It contains no runtime, window, GPU, or Python concrete types. |
| `crates/lumenplot-engine` | Internal semantic kernel for `scene`, canonical data and sealed chunks, LOD, layout, and the semantic frame. |
| `crates/lumenplot-export` | Semantic-frame-to-output-sink boundary. It is not a renderer or runtime owner. |
| `crates/lumenplot-render-api` | Semantic-frame-to-internal-`RenderPacket` boundary. It is never re-exported by the facade. |
| `crates/lumenplot-render-wgpu` | Concrete portable renderer consuming `lumenplot-render-api`; the dependency direction never points back from render-api to this crate. |
| `crates/lumenplot-runtime` | Main-thread runtime, session, surface, device, and lifecycle ownership. There is no facade-to-runtime edge in this phase. |
| `crates/lumenplot-viewer` | Standalone viewer product edge or binary/library over the facade and runtime. |
| `crates/lumenplot-python` | PyO3 `cdylib` edge providing extension module `lumenplot_mpl._native`. |
| `crates/lumenplot-bench` | Internal benchmark and evidence tooling; it is not a product facade. |
| `python/lumenplot-mpl` | Python distribution `lumenplot-mpl`, package `lumenplot_mpl`, backend `lumenplot_mpl.backend`, loader `module://lumenplot_mpl.backend`, and backend entry-point name `lumenplot`. |

The dependency direction is therefore:

```text
frontend or adapter → lumenplot facade → engine/export
                                   → semantic frame → internal RenderPacket
                                                          → renderer/runtime
```

The engine has no Python feature. No speculative public backend trait is introduced. No public default-feature contract is introduced in Phase 0. The one-way adapter and the concrete package/module names remain as fixed by ADR 0002 and the product requirements ([LP-PROD-010](../requirements/lumenplot-v1.0.md#5-basic-architecture), [LP-PROD-014](../requirements/lumenplot-v1.0.md#5-basic-architecture), [LP-MPL-001](../requirements/lumenplot-v1.0.md#15-python-and-matplotlib-bridge), [LP-MPL-002](../requirements/lumenplot-v1.0.md#15-python-and-matplotlib-bridge), [LP-MPL-017](../requirements/lumenplot-v1.0.md#15-python-and-matplotlib-bridge)).

### Visibility and publication guards

- All workspace and Python packages remain non-publishable during the implementation phases. No package publication, MSRV promise, API stability promise, or ABI stability promise is made by this ADR.
- Cross-crate `pub` is workspace implementation visibility only unless the facade explicitly exposes an item. It must not be treated as public API by inference.
- The facade must not re-export `lumenplot-render-api`, `RenderPacket`, renderer resource identifiers, runtime objects, or Python/Matplotlib objects.
- A documentation/API inventory and a static visibility review are required before any public-surface claim.
- `publish = false` guards and dependency-direction checks are mandatory for all packages as they are scaffolded.
- Lower layers must not acquire reverse dependencies on the adapter, Python, Matplotlib, wgpu, a window system, or native GPU concrete types.

### First-slice order

The accepted implementation order is:

1. Record and independently review this contract set.
2. Scaffold the accepted workspace graph together with dependency, visibility, and non-publication guards.
3. Implement the native core first: owned f64 chunks, topology and gap validation, Scene transactions/revisions/snapshots/selective invalidation, the MonotonicX M4 prototype, semantic frame, and property tests.
4. In parallel, run the scratch gates for the CPython/NumPy wheel matrix, deterministic PNG/color compositing, and native text/font/PDF consumer behavior.
5. After the relevant gate is accepted, implement deterministic PNG export from the native semantic frame.
6. Implement the headless Matplotlib strict and explicit-hybrid PNG adapter over the same engine and semantic frame.
7. Implement the internal packet and one-surface portable wgpu runtime/viewer slice. O-07/O-08 evidence is required before any product, platform, or performance claim.

Old CPU-backend implementation directions remain superseded by ADR 0002. This record does not authorize product implementation beyond the declared order.

## Alternatives and rationale

The accepted shape is Option C because it gives the engine a single public facade while preserving separate internal semantic, export, packet, renderer, runtime, viewer, and Python edges. A flatter facade or a renderer-first split would make visibility and dependency ownership ambiguous; neither is adopted. The choice does not make every internal crate a public package.

## Consequences

Positive consequences:

- The core can be built and tested without importing Python, Matplotlib, wgpu, or a window system.
- The internal packet and runtime can evolve without becoming facade API or persistent format.
- Publication, visibility, and dependency-direction checks become explicit review artifacts.
- Native-first implementation order prevents the adapter from becoming the accidental owner of the engine.

Costs and constraints:

- Cross-crate interfaces require deliberate review even when Rust visibility permits access.
- The first slice requires parallel evidence work before the adapter and portable runtime are declared complete.
- A future public API must be selected from the facade and cannot be inferred from internal modules.

## Verification and evidence boundary

Required checks are a static dependency DAG review, facade/API inventory, `publish = false` review, and documentation links to the canonical requirements and ADR 0002. None of those checks is product implementation or publication evidence. Current requirement results remain `Not implemented`, `Not measured`, or `environment required` in the [traceability registry](../requirements/traceability-v1.0.md).

## Residual risks

- The graph is accepted, but implementation may expose accidental public items unless the visibility inventory is kept with the workspace.
- Runtime and viewer work must not create a hidden facade-to-runtime dependency or move main-thread ownership into the engine.
- Future packaging work must preserve the no-publish and no-stability-claim baseline until the publication decision is changed explicitly.

## Related records

- [ADR index](README.md)
- [Architecture overview](../architecture/overview.md)
- [O-01 open-decision entry](../architecture/open-decisions.md#o-01-exact-facade-and-cratemodule-split)
- [Accepted v1 requirements](../requirements/lumenplot-v1.0.md)
