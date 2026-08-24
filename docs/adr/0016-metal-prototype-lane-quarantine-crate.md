# ADR 0016: Metal prototype lane quarantine crate

- Status: **Accepted contract — quarantine crate and activation-gated static allowance recorded; prototype implementation pending**
- Date: 2026-08-24
- Decision owner: architecture-authority
- Recorded by: engineering-worker
- Scope: `lumenplot-render-metal` quarantine crate, its macOS-target-gated Apple-framework dependency edges, and the activation-gated architecture/dependency contracts that keep the lane inert on every non-macOS target
- Governing architecture: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md)
- Boundary record: [ADR 0003 — facade and crate dependency graph](0003-facade-and-crate-dag.md)
- Seam predecessor: [ADR 0012 — private line frame and deterministic PNG contract](0012-private-line-frame-and-png-contract.md); the minimal synchronous frame seam this lane will consume is specified in [the post-v1 Metal fast-path design notes](../research/post-v1-metal-fastpath-design-notes.md)

This record captures the workstream decision to open a bounded Metal
prototype lane without touching any accepted v1 boundary. It freezes no
implementation: the crate ships as a documentation-only Phase-0 stub with
pinned, target-gated external edges and no Rust source beyond documentation.
The prototype comparison points themselves remain defined by
[the design notes](../research/post-v1-metal-fastpath-design-notes.md); this
record only establishes where the code may live and how the workspace keeps
it from leaking into portable surfaces.

## Context

The post-v1 exploration track wants a measured answer on whether an
Apple-Metal fast path is worth pursuing for interactive use. Measuring
requires real Metal bindings, which cannot exist inside any accepted v1
crate: the workspace's portable crates forbid concrete backend vocabulary,
external dependencies are pinned crate-by-crate, and the public render API
must stay backend-neutral. At the same time, the dependency policy demands
exact pins for every registry package in the lockfile graph, so simply
adding optional dependencies somewhere "temporarily" would weaken exactly
the guarantees the earlier phases established.

## Decision

1. **Quarantine crate.** A new private member `lumenplot-render-metal`
   joins the workspace between `lumenplot-render-api` and
   `lumenplot-render-wgpu`. Its only runtime edge is a versioned path
   dependency on `lumenplot-render-api`; it exposes no items consumed by
   any other workspace crate. The Phase-0 DAG shape is otherwise unchanged.

2. **Target-gated pinned edges.** The crate declares exactly three
   external edges — `objc2 =0.6.2`, `objc2-foundation =0.3.2`, and
   `objc2-metal =0.3.2`, all default-feature-free — inside a single
   `[target.'cfg(target_os = "macos")'.dependencies]` table. On every
   other target the table does not resolve, so no Apple-framework source
   is ever compiled, linked, or fetched into a build graph there; the
   packages remain inert lockfile entries.

3. **Activation-gated fail-closed allowance.** The static architecture
   contract admits the pinned gate table and any Rust source beyond the
   documentation-only stub only while an activation sentinel fires: the
   exact pinned declaration itself, or Rust source files beyond
   `src/lib.rs` in the crate. Removing both artifacts reactivates the
   plain stub rules unchanged. While active, `src/lib.rs` must remain
   documentation-only with no public items and no exported ABI; the
   prototype module set is deliberately not pinned yet because the
   follow-up prototype task owns that decision. Dependency drift of any
   kind — wrong version pin, extra feature, extra table entry, or an
   unlocked edge — fails the checker closed.

4. **Exact supply-chain pins.** The transitive closure of the gated edges
   (`objc2`, `objc2-core-foundation`, `objc2-foundation`,
   `objc2-metal`, plus their `bitflags`, `block2`, `dispatch2`,
   `objc2-encode`, `libc` support set) is pinned in the dependency-policy
   checker with exact versions, checksums, licenses, and lockfile
   dependency sets, moving with `Cargo.lock`. The build-script inventory
   gains `objc2` (its framework-probe build script), keeping the custom
   build-script allowlist exhaustive.

5. **Seam naming firewall.** `lumenplot-render-api` additionally forbids
   whole-word backend vocabulary (`metal`, `mtl`, `objc2`) so the future
   minimal frame seam stays backend-neutral even after the prototype lane
   exists. The negative test travels with the architecture mutation suite.

## Alternatives considered

- **Optional Cargo feature on an existing crate:** rejected; features are
  forbidden in Phase-0 manifests and a feature flag would make the
  quarantine opt-in rather than structurally isolated, weakening both the
  DAG guarantee and the dependency inventory story.
- **Out-of-tree scratch repository:** rejected; the lane must compile
  against the real `lumenplot-render-api` seam under the same locked
  dependency graph and review process, or its measurements would not be
  trustworthy evidence for the later decision.
- **Unpinned edges until the prototype lands:** rejected; it would break
  the exact-pin dependency policy and let the lockfile drift silently.

## Consequences

- Linux CI compiles nothing new for the lane; `cargo check/test/clippy`
  behavior is byte-for-byte unchanged apart from metadata resolution.
- The lockfile grows six inert entries (`dispatch2`, `objc2`,
  `objc2-core-foundation`, `objc2-encode`, `objc2-foundation`,
  `objc2-metal`) whose checksums are enforced everywhere, including
  Linux CI.
- The first prototype slice must land behind the activation sentinel;
  once it defines its module inventory, the inventory should be pinned
  exactly like the bench crate's five-file set.
- No public facade surface, Python helper surface, export claim, or
  platform-support statement changes because of this record. macOS
  remains outside the documented CI build targets; the lane adds no new
  support claim.

## Affected interfaces and required verification

- Workspace membership, DAG edges, and stub rules:
  `scripts/check_workspace_architecture.py` (mutation-tested).
- Dependency inventory, checksums, licenses, lockfile graph, and
  build-script allowlist: `scripts/check_phase2b_dependencies.py`
  (mutation-tested).
- Required verification for the follow-up prototype slice: the two
  checker suites stay green with the sentinel active, plus a
  macOS-target build demonstrating the gated table resolves and links.
