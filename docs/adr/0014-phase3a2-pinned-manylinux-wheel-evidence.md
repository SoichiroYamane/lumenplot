# ADR 0014: Phase-3A2 pinned manylinux wheel evidence contract

- Status: **Accepted contract — Phase-3A2 helper/package/builder same-wheel evidence is recorded (CI-local manifest; GIL CPython 3.11–3.14); Phase-3B first strict-mode and hybrid-explicit implementation slices merged with local contract-test evidence; packaged public-backend runtime evidence recorded in PR #89 CI; full compatibility/release evidence remains pending**
- Date: 2026-08-21
- Decision owner: architecture-authority
- Recorded by: implementation-worker
- Scope: Phase-3A2 private `lumenplot-mpl` helper wheel builder, same-wheel CPython evidence, and supply-chain boundary
- Governing architecture: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md)
- Related amendment: [ADR 0013 — hidden facade and private Python line/PNG helper](0013-hidden-facade-private-python-line-png.md)
- Related API record: [API 0003 — Python, NumPy, and Matplotlib boundary](../architecture/api-0003-python-numpy-matplotlib.md)
- Open-decision records: [O-09 — Python ABI and NumPy ingestion policy](../architecture/open-decisions.md#o-09-python-abi-and-numpy-ingestion-policy), [O-10 — Matplotlib compatibility and profile matrix](../architecture/open-decisions.md#o-10-matplotlib-compatibility-and-profile-matrix)

This ADR records the evidence contract for the private Phase-3A2 helper only. It
is not a package implementation, a public Matplotlib backend decision, a
support claim, a release approval, or a Phase-3B contract.

## Requirement and scope boundary

The contract provides an auditable implementation gate for the Python/NumPy
bridge and supply-chain requirements in [the v1 requirements](../requirements/lumenplot-v1.0.md#15-python-and-matplotlib-bridge),
without claiming that the v1 Matplotlib adapter requirements are implemented.
It preserves the [ADR 0009 publication and persistence boundary](0009-version-publication-supply-chain.md):
there is no publishing workflow, no signing workflow, no package registry
upload, and no Scene or RenderPacket persistence format.

The distribution name is `lumenplot-mpl`; the private import package is
`lumenplot_mpl`. The Phase-3A2 package deliberately does not provide
`lumenplot_mpl.backend`, a Matplotlib entry point, a public `render_png`
function, or a public compatibility profile. Those remain Phase-3B/public
adapter decisions and must not be inferred from a passing helper-wheel run.

## Context

ADR 0013 stages a hidden Rust facade and a private line/PNG helper surface so
that the first Python packaging work can be tested without freezing the public
Matplotlib adapter. A wheel built directly on a mutable host would make the
result difficult to attribute to a known glibc/toolchain/dependency set. A
wheel that is only imported on the builder interpreter would also leave the
abi3 and same-wheel runtime claim untested.

The accepted evidence must therefore make the build inputs immutable, keep the
builder isolated, build only a private helper wheel, and install that exact
wheel into each declared GIL-enabled CPython cell. A source rebuild per Python
cell is not equivalent evidence.

## Decision

### 1. Implementation activation and fail-closed gate

The repository architecture checker remains unchanged for the pre-implementation
baseline. The Phase-3A2 gate activates when any of these implementation
sentinels appears:

- a root `pyproject.toml`;
- the `python/lumenplot_mpl/` package directory;
- a workflow that contains a Python-wheel/manylinux/maturin/auditwheel path; or
- a `pyo3` or `numpy` runtime dependency in `crates/lumenplot-python/Cargo.toml`.

Once active, the default checker fails closed unless the complete package,
direct container workflow, exact dependency/input inventory, and four-cell
same-wheel static contract are present. It does not claim runtime evidence.
The dedicated Phase-3A2 workflow invokes the explicit
`--phase3a2-evidence` mode only after generating the CI-local manifest; that
mode additionally requires and validates the complete four-cell runtime
evidence. A partial sentinel or missing/invalid explicit evidence must never
leave an apparently passing gate.

### 2. Private package boundary

The first wheel is an internal helper artifact, not a public backend. The
accepted package/build boundary is:

- distribution: `lumenplot-mpl`;
- import package: `lumenplot_mpl`;
- private native module: `lumenplot_mpl._native`;
- private helper: `_native.render_line_png`;
- Python exception mapping: `LumenPlotError` with structured code/category/message
  fields as defined by the accepted bridge records;
- no `lumenplot_mpl.backend`, `module://` entry point, public `render_png`, or
  Matplotlib import in this phase;
- PyO3 remains downstream of the facade/engine dependency direction and may not
  make the engine depend on Python or Matplotlib concrete types.

The wheel may use the accepted candidate dependency versions from API 0003:
PyO3 `=0.29.2` with `macros`, `extension-module`, and `abi3-py311`, and the
Rust NumPy crate `=0.29.0` without default features. These are implementation
constraints for this slice, not a project-wide MSRV or support promise.

### 3. Immutable builder inputs

The builder uses the x86_64 manylinux glibc-2.28 image identified by both tag
and digest:

```text
quay.io/pypa/manylinux_2_28_x86_64:2026.08.15-1@sha256:0c87ccb5996dab6c3b7612ee4fda7b80c4ab3c44a86c2541e4a872afdf4f131b
```

The verified image config digest is
`sha256:fd0c576d9673648a125bffeaea6acb762d8bc52d97da9034dfdbe00f98a17dd5`.
The build records Rust `1.89.0`, the exact 64-hex SHA-256 of `Cargo.lock`,
the Cargo-derived package version, and the pinned maturin `1.14.1` wheel
(`dfc54ae32e6fcb18302193ab9a30b0b25eefffba994ae13238974805533ef75e`).

The official source observations are:

- [Quay manylinux tag](https://quay.io/repository/pypa/manylinux_2_28_x86_64?tab=tags&tag=2026.08.15-1)
  and [its manifest endpoint](https://quay.io/v2/pypa/manylinux_2_28_x86_64/manifests/2026.08.15-1);
- [maturin 1.14.1 JSON metadata](https://pypi.org/pypi/maturin/1.14.1/json);
- [NumPy 2.4.6 JSON metadata](https://pypi.org/pypi/numpy/2.4.6/json);
- [checkout v4.2.2](https://github.com/actions/checkout/tree/v4.2.2),
  [rust-toolchain action 1.97.1](https://github.com/dtolnay/rust-toolchain/tree/1.97.1),
  and optional [upload-artifact v7.0.1](https://github.com/actions/upload-artifact/tree/v7.0.1).

The workflow must verify the image reference and config digest in-container or
by the container runtime, verify Rust and Cargo versions inside the container,
run `cargo fetch --locked`/`cargo metadata --locked`, and build offline with
`--locked --offline`. Dependency sources, checksums, license results, and the
SBOM input set are evidence, not mutable host state.

### 4. Direct container workflow and security controls

The accepted workflow is direct Docker/Podman-style invocation. It does not use
`PyO3/maturin-action`, `actions/setup-python`, an unpinned image, or a host
Python interpreter as the builder. It has both `push` and `pull_request`
coverage for `main`, workflow-level `contents: read`, no secrets, no
`pull_request_target`, no package write permission, and no release/publish/
deploy/signing step.

The prefetch and build/test phases are separate containers. The prefetch phase
may use `--network=bridge` only to obtain the reviewed inputs. The build and
runtime phases use `--network=none`. Every container uses the reviewed image,
`--platform=linux/amd64`, a read-only root (`--read-only`), an explicit
non-root `--user`, `--cap-drop=ALL`, `--security-opt=no-new-privileges`,
read-only source and wheelhouse mounts, and `--tmpfs` for writable temporary
state. `--privileged`, host networking, writable source mounts, and mutable
cache actions are forbidden.

The workflow uses the explicit in-image GIL CPython interpreters:

```text
/opt/python/cp311-cp311/bin/python
/opt/python/cp312-cp312/bin/python
/opt/python/cp313-cp313/bin/python
/opt/python/cp314-cp314/bin/python
```

It must not use `--find-interpreter`, `cp314t`, `abi3t`, a free-threaded
interpreter, or a non-CPython implementation.

### 5. Wheel and same-wheel matrix

Maturin builds one private artifact with the exact tag
`cp311-abi3-manylinux_2_28_x86_64`. The workflow performs ZIP integrity,
`METADATA`/version, `WHEEL` tag, `RECORD` hash/size, ELF dependency and
RPATH/RUNPATH, abi3, and SBOM checks. It runs `auditwheel show` and
`auditwheel check`; `auditwheel repair` is forbidden because repair would
create an unrecorded second artifact.

The exact wheel is copied by digest, not rebuilt, into fresh virtual
environments for CPython 3.11, 3.12, 3.13, and 3.14. Each cell uses
`python -m venv --clear`, installs only hash-pinned binary NumPy `2.4.6` from
a local wheelhouse with `--no-index --no-cache-dir --only-binary=:all:
--require-hashes`, installs the identical helper wheel, imports the private
module, and runs the private helper fixtures. A missing cell, a rebuild, a
silent interpreter search, a permissive pip install, or a different wheel
hash invalidates the evidence.

The current NumPy wheel inputs are:

| CPython | Wheel | SHA-256 |
| --- | --- | --- |
| 3.11 | `numpy-2.4.6-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl` | `89cd468399cfd2504718f0ba50e410dca55a170b61a02ad92bb18c8a65186e93` |
| 3.12 | `numpy-2.4.6-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl` | `90f9849678c75fe7afa2d348ac842c168b0a4d3d61919687216dfc547976d853` |
| 3.13 | `numpy-2.4.6-cp313-cp313-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl` | `a7830bab239b79cda9c08c2da014761cafb48da6150e1da17ac06283f43b6089` |
| 3.14 | `numpy-2.4.6-cp314-cp314-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl` | `a2c306dea656c12c68f51f4cea133cbe78ca7435eb28c735eac1d3ebe73be6e8` |

### 6. CI-local evidence manifest

A successful run generates `phase3a2-wheel-evidence.json` in CI workspace
storage. It is UTF-8 JSON, is not committed or published, and contains no
absolute runner paths, credentials, task identifiers, or raw private artifact
paths. The architecture checker enforces these exact top-level keys:

```text
builder, checks, claim_boundary, runtime_cells, schema, source, wheel
```

`schema` is exactly `lumenplot.phase3a2-wheel-evidence.v1`. The file uses LF
line endings, two-space indentation, lexicographically sorted object keys, and
the fixed runtime-cell order 3.11, 3.12, 3.13, 3.14; it contains no timestamp,
run ID, host path, secret, or raw internal artifact path.

The required object fields are:

- `source`: `commit` (40-hex revision), `cargo_lock_sha256` (64-hex digest),
  `distribution` (`lumenplot-mpl`), and `cargo_version`;
- `builder`: image/tag+digest, image config digest, `linux/amd64`, glibc `2.28`,
  auditwheel `6.8.0`, abi3audit `0.0.26`, Rust `1.89.0`, maturin `1.14.1`,
  and its wheel SHA-256;
- `wheel`: filename, SHA-256, exact tag, Cargo-expected version,
  `METADATA` version, and true `zip`, `metadata`, `wheel`, `record`, `elf`,
  `abi3`, and `sbom` flags; `sbom_format` is exactly `CycloneDX 1.5`;
- `runtime_cells`: exactly four objects for CPython 3.11–3.14, each recording
  the explicit interpreter path, NumPy version and wheel SHA-256, identical
  helper-wheel SHA-256, rechecked input-wheel SHA-256, Cargo-expected version,
  installed distribution version, and `result: "pass"`;
- `checks`: true booleans named
  `cargo_locked_sources_checksums_licenses`, `same_wheel`, `metadata_version`,
  `auditwheel`, `elf_rpath`, `abi3audit`, `private_helper_fixtures`, and
  `redaction_ownership`;
- `claim_boundary`: `private_helper_only: true`, with
  `release_artifact: false`, `platform_support_claim: false`, and
  `publication_authorized: false`.

The manifest is evidence of the named run only. It cannot be used to infer a
supported Python/Matplotlib matrix, a public backend, publication readiness,
or a Phase-3B decision.

### 7. Action pin and artifact policy

Every action used by the optional wheel workflow is pinned to a full commit SHA,
with the human release/ref and the exact `git ls-remote` command recorded in
[`docs/security/pinned-actions.yml`](../security/pinned-actions.yml). The
accepted observations are checkout `11bd71901bbe5b1630ceea73d27597364c9af683`,
rust-toolchain `032958afbdc797a9164d3bc0b56325c1308924a5`, and optional
upload-artifact `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`. If artifact upload is
used, it is non-release evidence storage only, runs for a trusted push to `main`, uses `if-no-files-found: error`, retains evidence for exactly seven days, and does not feed publication. The first implementation may omit upload entirely.

## Alternatives and rationale

- **Host-native maturin build:** rejected because host glibc, Rust, Python, and
  dependency state would be implicit and difficult to reproduce.
- **`PyO3/maturin-action` or `actions/setup-python`:** rejected for this slice;
  direct immutable-container invocation makes the builder and network boundary
  explicit.
- **One wheel per Python cell:** rejected because rebuilds cannot prove that
  the same abi3 artifact works across the matrix.
- **`--find-interpreter`:** rejected because implicit interpreter selection can
  silently select a free-threaded or non-CPython executable.
- **`auditwheel repair`:** rejected because it creates a new artifact after the
  recorded build and obscures which file the runtime matrix exercised.
- **Uploading every build output:** rejected by default because this is a
  private evidence contract, not a release pipeline. Optional upload remains
  fail-closed and retention-bounded.
- **Opening the public Matplotlib backend now:** rejected because API 0003 and
  ADR 0013 deliberately leave Phase-3B authority, fallback, and compatibility
  decisions open.

## Consequences

- The first Python packaging implementation has a deterministic, reviewable
  builder and a bounded claim surface.
- Four runtime cells exercise one wheel, making abi3 evidence distinct from
  source-build success.
- The source tree remains pre-alpha and non-publishable; CI-local JSON is not a
  persistence format or a public package manifest.
- The accepted versions and image are evidence inputs for this slice only. They
  do not establish MSRV, Python support, NumPy support, Matplotlib compatibility,
  or release support.
- The checker and mutation tests become part of the architecture evidence. A
  future change that removes a required input or security control fails before
  it can be described as a passing wheel run.

## Verification and evidence boundary

Required implementation verification is divided into two layers:

1. **Static contract gate:** the standard-library architecture checker activates
   on the implementation sentinel and verifies the package boundary, exact
   workflow controls, action pins, immutable input inventory, four explicit
   interpreters, and exact UTF-8 evidence schema. Mutation tests must reject
   partial activation, missing matrix cells, wrong tags/digests, unlocked or
   networked builds, permissive pip, repair, ABI3/free-threaded drift, missing
   venv isolation, bad action pins, and missing artifact failure guards.
2. **Runtime evidence:** the direct container workflow builds with the locked
   graph, performs auditwheel/ELF/abi3/metadata/RECORD/SBOM checks, runs the
   private helper fixtures, installs the identical wheel in all four fresh
   GIL-CPython environments, and emits the non-public JSON manifest. No run is
   represented as product or release evidence until its manifest and logs are
   reviewed.

This ADR records the contract and verified source observations only. It does
not claim that the wheel, workflow, or runtime matrix exists or has passed.

## Residual risks and follow-up

- The manylinux tag and external action refs remain supply-chain inputs and must
  be re-probed before implementation merge; a changed ref requires a reviewed
  update to the inventory and checker constants.
- The selected Rust/PyO3/NumPy versions have not established a project MSRV or
  cross-platform support floor.
- The private helper does not resolve Matplotlib Artist authority, fallback,
  profile, text, viewer, or public backend behavior. Those questions remain
  Phase-3B architecture gates.
- Future artifact storage must retain the manifest and logs without treating
  them as publishable package or persistence formats.

## Related records

- [ADR index](README.md)
- [ADR 0002 — GPU-native engine and Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md)
- [ADR 0009 — version, publication, and supply-chain policy](0009-version-publication-supply-chain.md)
- [ADR 0013 — hidden facade and private Python line/PNG helper](0013-hidden-facade-private-python-line-png.md)
- [API 0003 — Python, NumPy, and Matplotlib](../architecture/api-0003-python-numpy-matplotlib.md)
- [Phase-3A2 wheel evidence contract](../architecture/phase3a2-manylinux-wheel-evidence.md)
- [Pinned action inventory](../security/pinned-actions.yml)
