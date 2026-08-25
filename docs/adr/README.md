# Architecture decision records

The architecture-authority owns architecture decisions; the implementation-worker records accepted decisions in this directory. The records are public-facing documentation and must not depend on private work-item identifiers, local paths, profile memory, or transient research artifacts.

## Index

| ADR | Status | Title | Scope |
| --- | --- | --- | --- |
| [0001](0001-rust-matplotlib-raster-backend.md) | Superseded | Rust Matplotlib raster backend architecture | Historical v0.1 headless raster decision |
| [0002](0002-gpu-native-engine-and-matplotlib-adapter.md) | Accepted | GPU-native engine and first-class Matplotlib adapter | Current v1 pre-alpha architecture |
| [0003](0003-facade-and-crate-dag.md) | Accepted | Facade and crate dependency graph | O-01 facade, visibility, publication guards, and first-slice order |
| [0004](0004-renderpacket-resource-lifecycle.md) | Accepted | RenderPacket and renderer resource lifecycle | O-04 internal packet and resource ownership |
| [0005](0005-runtime-viewer-host-loop.md) | Accepted | Runtime, viewer, and host-loop lifecycle | O-06 session, viewer, host, and recovery semantics |
| [0006](0006-support-benchmark-native-gates.md) | Accepted — evidence pending | Support cells, benchmark protocol, and native-backend gates | O-07/O-08/O-16 target and adoption evidence |
| [0007](0007-coordinate-color-text-export.md) | Accepted — dependency choices staged | Coordinate, color, text, and export semantics | O-11/O-12 semantic and export boundary |
| [0008](0008-portable-gpu-and-shaders.md) | Accepted — evidence pending | Portable GPU runtime and shader artifacts | O-15 implementation baseline and shader policy |
| [0009](0009-version-publication-supply-chain.md) | Accepted current policy | Version, publication, and supply-chain policy | O-17 policy and O-18 serialization exclusion |
| [0010](0010-phase1-native-core-facade-contract.md) | Accepted — Phase-1 implementation and local contract evidence recorded | Phase-1 native core and minimal facade contract | O-01/O-02/O-03/O-05 exact Phase-1 boundary |
| [0011](0011-phase1b-facade-namespace-observation-traits.md) | Accepted amendment — Phase-1B implementation and local contract evidence recorded | Phase-1B facade namespace and observation traits | Narrow amendment to ADR 0010 |
| [0012](0012-private-line-frame-and-png-contract.md) | Accepted amendment — Phase-2A/2B implementation and local evidence recorded | Private line frame and deterministic PNG contract | Phase-2A/2B line-frame and PNG boundary |
| [0013](0013-hidden-facade-private-python-line-png.md) | Accepted staged contract — Phase-3A2 same-wheel evidence recorded (CI-local manifest; GIL CPython 3.11–3.14); Phase-3B first implementation slices merged with local contract-test evidence | Hidden facade and private Python line/PNG helper | Phase-3A owned Rust seam, NumPy/GIL boundary, and helper-only package gate |
| [0014](0014-phase3a2-pinned-manylinux-wheel-evidence.md) | Accepted contract — helper/package/builder same-wheel evidence recorded (CI-local manifest; GIL CPython 3.11–3.14); Phase-3B first strict-mode and hybrid-explicit implementation slices merged with local contract-test evidence; packaged public-backend runtime evidence pending | Phase-3A2 pinned manylinux private-helper wheel and same-wheel evidence | Python package/build boundary without Phase-3B/public adapter claims |
| [0015](0015-phase3b-public-matplotlib-adapter-contract.md) | Accepted contract — Phase-3B first strict-mode and hybrid-explicit implementation slices merged with local contract-test evidence; packaged public-backend runtime evidence pending | Phase-3B public Matplotlib adapter contract | Public backend slice boundary: eligibility preflight, eligible trace, style/format guards, fallback, and terminal-failure rules |
| [0017](0017-metal-native-adoption-decision-record.md) | Accepted — No-Go disposition of the O-16 native adoption gate against the first executed O-08 bundle; nothing authorized, native cell honestly environment required | Metal native adoption decision record (O-16 gate disposition) | First executed O-08 bundle evaluated against the native adoption gate; native cell honestly environment required |
| [0018](0018-user-facing-png-output-description.md) | Accepted — README accuracy and PNG description; amends ADR 0012 §5 by enabling IDAT DEFLATE (Balanced) with measured size evidence | User-facing PNG-output description | README accuracy for shipped phases; PNG stream description; IDAT compression amendment |

ADR 0002 explicitly supersedes ADR 0001. ADR 0001 remains available as historical context; it must not be used as the current v1 architecture without the replacement contract.

## API decision records

These records are accepted follow-up contracts in `docs/architecture/`. They are indexed here so the ADR set and the API set can be reviewed together without making API records into crate or persistence formats.

| Record | Status | Scope |
| --- | --- | --- |
| [API 0001](../architecture/api-0001-native-scene-state.md) | Accepted — Phase-1 exact surface and local implementation evidence recorded | O-02R/O-05 native Scene, view, owned data, transactions, revisions, and snapshots |
| [API 0002](../architecture/api-0002-errors-capabilities-fallback.md) | Accepted — Phase-1 mapping and local failure evidence recorded | O-03 errors, capabilities, fallback diagnostics, and FFI mapping |
| [API 0003](../architecture/api-0003-python-numpy-matplotlib.md) | Accepted staged Phase-3A contract — helper/package/builder same-wheel evidence recorded (CI-local manifest; GIL CPython 3.11–3.14); Phase-3B first strict-mode and hybrid-explicit implementation slices merged with local contract-test evidence; packaged public-backend runtime evidence pending | O-02P/O-09/O-10 Python, NumPy, and Matplotlib bridge |
| [API 0004](../architecture/api-0004-annotations-accessibility.md) | Accepted — evidence pending | O-13/O-14 annotations, interaction history, and accessibility |
| [API 0005](../architecture/api-0005-phase3b-public-matplotlib-backend-surface.md) | Accepted staged surface contract — Phase-3B first strict-mode and hybrid-explicit implementation slices merged with local contract-test evidence; packaged public-backend runtime evidence pending | O-10 Phase-3B public backend result, diagnostic, canvas, and fallback surface |

O-01 through O-17 are accepted contracts with implementation or environment evidence staged by phase. Phase-1A/B implementation and local contract evidence now exist; the bounded Phase-2A/2B line-frame and PNG implementation and local evidence are also recorded. None of these slices closes the v1 product, platform, benchmark, support, or release gates. [ADR 0010](0010-phase1-native-core-facade-contract.md) records the accepted Phase-1 native core/facade slice and resolves the Phase-1 candidates in API 0001 and API 0002; [ADR 0011](0011-phase1b-facade-namespace-observation-traits.md) is its narrow accepted amendment for the Phase-1B root namespace, stable token observations, and exact trait guarantees. [ADR 0012](0012-private-line-frame-and-png-contract.md) records the accepted Phase-2A/2B private line-frame and deterministic line/PNG boundary, whose bounded implementation and local evidence do not expand the public facade or full-v1 export claim. [ADR 0013](0013-hidden-facade-private-python-line-png.md) records the staged Phase-3A hidden facade and private Python helper; [ADR 0014](0014-phase3a2-pinned-manylinux-wheel-evidence.md) records the staged Phase-3A2 pinned builder and same-wheel evidence contract; and [ADR 0015](0015-phase3b-public-matplotlib-adapter-contract.md) + [API 0005](../architecture/api-0005-phase3b-public-matplotlib-backend-surface.md) record the accepted Phase-3B public Matplotlib contract. Phase-3A2 helper/package/builder same-wheel evidence is recorded (CI-local manifest; GIL 3.11–3.14); the Phase-3B first strict-mode and hybrid-explicit implementation slices are merged with local contract-test evidence while packaged public-backend runtime evidence remains pending. [ADR 0009](0009-version-publication-supply-chain.md) records O-18 as Deferred/Closed by the v1 non-goal; it is not an implementation fan-out item.

## Convention

Each ADR should state:

1. status, date, decision owner, and scope;
2. context and the problem;
3. the decision and dependency direction;
4. alternatives and rationale;
5. consequences and compatibility impact;
6. affected interfaces and required verification;
7. residual risks and follow-up decisions.

Architecture records should use stable public links, remove unnecessary tracking query parameters, and avoid private identifiers and local filesystem references. An accepted ADR records a decision; ADR acceptance alone is not implementation evidence. Implementation status may be stated explicitly in the ADR index/status prose only when backed by traceability, review, or release evidence; otherwise it remains unimplemented or pending. No implementation, compatibility, platform, benchmark, or release claim may be inferred from ADR acceptance alone.

Exact public signatures, packet schemas, dependency pins, and routine local implementation details belong in a later ADR only when they are architecture decisions. Keep public and internal boundaries explicit, and never promote a candidate dependency version into a normative requirement without compatibility, correctness, security, license, MSRV, and performance evidence.

## Review and supersession rules

- A new ADR must link to any decision it supersedes.
- A superseded ADR keeps its historical meaning and receives a top-of-file notice pointing to the replacement.
- A replacement ADR must state the supersession in the opposite direction so readers can navigate from either record.
- Follow-up ADRs must not reopen accepted decisions unless the decision owner records a new supersession or amendment.
- Every architecture ADR must identify verification work and distinguish targets from verified results.
