# ADR 0009: Version, publication, and supply-chain policy

- Status: **Accepted current policy; future release targets recorded**
- Date: 2026-08-21
- Decision owner: architecture-authority
- Recorded by: implementation-worker
- Scope: O-17 dependency/publication/supply-chain policy and O-18 serialization exclusion
- Governing architecture: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md)
- Open-decision records: [O-17 — Dependency, publication, and supply-chain policy](../architecture/open-decisions.md#o-17-dependency-publication-and-supply-chain-policy), [O-18 — Future serialization schema](../architecture/open-decisions.md#o-18-future-serialization-schema)

This ADR records the current pre-alpha publication boundary and future release targets. It does not add a release workflow, publish a package, select an MSRV, or create a Scene/RenderPacket persistence format.

## Requirement references

The publication and persistence boundary covers `LP-REL-001`, `LP-REL-002`, `LP-QUAL-022` through `LP-QUAL-024`, `LP-QUAL-028`, `LP-SEC-006`, `LP-SEC-008`, and `LP-PROD-012` in the [requirements](../requirements/lumenplot-v1.0.md#30-repository-and-distribution-structure).

## Context

The repository is deliberately pre-alpha. Dependency candidates and implementation lock choices must not become public support promises, and release automation would imply publication authority before the API, compatibility, security, and evidence gates are accepted. Scene/project and RenderPacket serialization were explicitly excluded from v1.

## Decision

### Current implementation-phase policy

- All packages remain non-publishable during implementation phases.
- There is no MSRV promise, `Requires-Python` promise, public API stability promise, or ABI stability promise.
- Package publication and broad support claims remain disabled until an explicit future release decision passes the declared gates.
- No release workflow, signing workflow, or publication automation is added by this record.

Every dependency addition or update requires a locked graph and review of compatibility, correctness, security, license, provenance, MSRV implications, and relevant profile-separated performance. Updates are not auto-merged. An older stable dependency may be retained when it satisfies those gates better than a newer version.

The implementation lock choices in [ADR 0008](0008-portable-gpu-and-shaders.md) and other records are not public pins. A dependency candidate, wheel observation, benchmark target, or platform row is not a release result.

The Phase-3A2 private-helper wheel contract in [ADR 0014](0014-phase3a2-pinned-manylinux-wheel-evidence.md) is likewise a CI-local evidence gate, not a publication workflow, support promise, or release artifact. Its optional artifact upload is reviewable evidence retention only; it does not change this record's non-publication boundary.

### Future rolling support floor and release artifacts

A future release may select a rolling supported floor only after all-target and wheel matrices pass. The release-time supply-chain target is:

- CycloneDX 1.7 JSON as the canonical SBOM;
- optional SPDX derived from the same component and digest set and checked for equality;
- keyless Sigstore/OIDC provenance/signing with in-toto/SLSA metadata;
- PyPI Trusted Publishing used only as upload authentication, not as a substitute for provenance;
- a protected, human-approved release environment with no long-lived PyPI token.

These are future targets, not current artifacts or workflow claims. License, advisory, provenance, and reproducible-build evidence remain release gates.

### O-18 serialization exclusion

O-18 remains **Deferred/Closed by non-goal**. Serialization is excluded from the implementation DAG:

- no public Scene or project save/load format;
- no public RenderPacket export;
- no serde, wire, or persistent RenderPacket format;
- PNG, PDF, and SVG remain output formats, not persistence formats.

After the accepted API and packet records, implementation may add only negative guards proving no public export, serde, wire, or save/load path has been introduced. Reopening O-18 requires a separate schema, security, trust, and migration ADR with property tests. No implementation card may infer a serialization schema from Scene IDs, revisions, diagnostics, benchmark JSONL, or packet internals.

## Alternatives and rationale

Publishing during implementation would turn an unfinished contract into an accidental compatibility promise. Adding a release workflow now would imply release authority and credentials that the project intentionally does not have. A generic serialization format would prematurely freeze resource identity and trust semantics; the accepted non-goal keeps that decision separate.

## Consequences

- Pre-alpha work can evolve behind explicit non-publication guards.
- Dependency updates carry compatibility, security, and performance evidence instead of version novelty.
- Future release artifacts have named interoperability and provenance targets without claiming they exist.
- Serialization scope remains auditable through negative checks and cannot enter the implementation DAG by accident.

## Verification and evidence boundary

Required current checks include package publication guards, absence of release/signing workflows, locked dependency review, license/advisory/provenance policy review, and negative scans for public packet/serde/wire/save-load paths. Future release evidence includes all-target/wheel matrices, CycloneDX/SPDX consistency, reproducible build inputs, and protected Sigstore/SLSA provenance. None is claimed by this ADR.

## Residual risks

- A package tool may expose publishable defaults unless every future package keeps its guard explicit.
- A dependency lock choice can be mistaken for a support promise unless documentation and release review preserve this boundary.
- A future serialization request will need a new security and migration design rather than an extension of this record.

## Related records

- [ADR index](README.md)
- [Architecture overview](../architecture/overview.md)
- [ADR 0003 — facade and crate DAG](0003-facade-and-crate-dag.md)
- [ADR 0006 — support and benchmark gates](0006-support-benchmark-native-gates.md)
- [ADR 0008 — portable GPU and shaders](0008-portable-gpu-and-shaders.md)
- [ADR 0014 — Phase-3A2 pinned manylinux wheel evidence](0014-phase3a2-pinned-manylinux-wheel-evidence.md)
- [O-17 open-decision entry](../architecture/open-decisions.md#o-17-dependency-publication-and-supply-chain-policy)
- [O-18 open-decision entry](../architecture/open-decisions.md#o-18-future-serialization-schema)
- [Accepted requirements: publication boundary](../requirements/lumenplot-v1.0.md#30-repository-and-distribution-structure)
