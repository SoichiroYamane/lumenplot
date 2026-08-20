# Architecture decision records

Sol owns architecture decisions; Luna records accepted decisions in this directory. The records are public-facing documentation and must not depend on private work-item identifiers, local paths, profile memory, or transient research artifacts.

## Index

| ADR | Status | Title | Scope |
| --- | --- | --- | --- |
| [0001](0001-rust-matplotlib-raster-backend.md) | Superseded | Rust Matplotlib raster backend architecture | Historical v0.1 headless raster decision |
| [0002](0002-gpu-native-engine-and-matplotlib-adapter.md) | Accepted | GPU-native engine and first-class Matplotlib adapter | Current v1 pre-alpha architecture |

ADR 0002 explicitly supersedes ADR 0001. ADR 0001 remains available as historical context; it must not be used as the current v1 architecture without the replacement contract.

## Convention

Each ADR should state:

1. status, date, decision owner, and scope;
2. context and the problem;
3. the decision and dependency direction;
4. alternatives and rationale;
5. consequences and compatibility impact;
6. affected interfaces and required verification;
7. residual risks and follow-up decisions.

Architecture records should use stable public links, remove unnecessary tracking query parameters, and avoid private identifiers and local filesystem references. An ADR records an accepted architecture choice; it does not claim that the choice has been implemented. Implementation status and evidence belong in requirements traceability and release records.

Exact public signatures, packet schemas, dependency pins, and routine local implementation details belong in a later ADR only when they are architecture decisions. Keep public and internal boundaries explicit, and never promote a candidate dependency version into a normative requirement without compatibility, correctness, security, license, MSRV, and performance evidence.

## Review and supersession rules

- A new ADR must link to any decision it supersedes.
- A superseded ADR keeps its historical meaning and receives a top-of-file notice pointing to the replacement.
- A replacement ADR must state the supersession in the opposite direction so readers can navigate from either record.
- Follow-up ADRs must not reopen accepted decisions unless the decision owner records a new supersession or amendment.
- Every architecture ADR must identify verification work and distinguish targets from verified results.
