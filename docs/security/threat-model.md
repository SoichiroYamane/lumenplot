# Public-fork CI and dependency threat model

## Trust boundary

A `pull_request` workflow may execute code from an untrusted fork. Every Rust
build script, procedural macro, native binding, shader compiler, test fixture,
and generated file in that checkout is untrusted input. Jobs use only the
workflow-level `contents: read` permission, receive no repository secrets, and
never use `pull_request_target`.

The workflow does not interpolate issue titles, branch names, commit messages,
PR body text, or other user-controlled strings into a shell command. The only
shell inputs derived from the checkout are Rust toolchain metadata, which is
parsed with Python and restricted to safe channel/component/target characters
before being passed as action inputs.

## Action and token controls

- Every third-party action is pinned to a full commit SHA and recorded in
  `pinned-actions.yml` with its upstream release/ref verification.
- Dependabot opens grouped monthly pull requests for Cargo and Actions updates;
  it does not auto-merge. Action updates and performance-sensitive dependency
  updates require human review.
- The baseline contains no release, publish, deploy, signing, or credential
  workflow. No artifact upload is enabled.
- The Nix job uses the evaluation-only flake check and disables the installer
  diagnostic endpoint. No mutable cache action is used.

The accepted Phase-3A2 contract adds no current workflow or package artifact.
When its implementation sentinel is introduced, the wheel job must use the
reviewed manylinux tag and digest, separate bridge/offline Docker networks,
read-only/non-privileged containers, locked Cargo inputs, hash-required local
wheel installs, explicit GIL CPython paths, and the CI-local redacted evidence
manifest described by [ADR 0014](../adr/0014-phase3a2-pinned-manylinux-wheel-evidence.md).
An optional `actions/upload-artifact` use is evidence retention only, is restricted to a trusted push to `main`, retains for seven days, and must remain pinned and fail when the evidence file is absent; it is not publication.

## Build-script, native-code, and artifact risks

Cargo compilation can execute build scripts, procedural macros, and native code.
The runner is ephemeral and the token is read-only, but code execution is still
not a sandbox. Do not add secrets, deployment credentials, signing keys, or
write-scoped tokens to these jobs. Do not treat test output, generated binaries,
coverage files, or future uploaded artifacts as trusted release evidence.

A future artifact workflow must define provenance, retention, digest
verification, and fork restrictions before it is added. In particular, an
artifact produced by an untrusted PR must not be promoted, published, or used as
an input to a privileged job.

## Cache poisoning

This baseline intentionally has no `actions/cache` or compiler cache. Fresh
runners avoid cross-branch cache poisoning and no current dependency/build size
requires a cache. If caching is later introduced, use a lockfile/toolchain-keyed
read-only cache, never restore an untrusted PR cache into a privileged job, pin
the cache action, and document cache invalidation and provenance.

## Dependency and license policy

`deny.toml` separates the project license decision (`MIT OR Apache-2.0`) from
licenses of dependencies. Unknown registries, unknown Git sources, unlicensed
or copyleft dependencies, yanked releases, wildcard dependencies, and
unapproved license expressions are not silently allowed. Adding a dependency
such as a renderer, windowing stack, shader tool, text engine, or native binding
requires manual license/provenance review and later performance/compatibility
gates; a green dependency check does not authorize auto-merge.

## Performance claims

The CI compile/test/clippy duration is not a product-performance measurement.
The baseline makes no throughput, latency, renderer, or GPU claim. Any
performance-sensitive dependency or implementation change must add an approved
benchmark/profiling gate rather than treating CI wall-clock time as evidence.

## Residual risks

- A pinned action remains a supply-chain dependency; update it only through a
  reviewed provenance-checked pull request.
- The current repository has no dedicated secret scanner installed in the local
  audit environment; publication still requires a dedicated scanner over the
  approved tree and reachable history.
- The initial observation for this task saw a partial dirty implementation with
  formatting and test failures; a later live recheck observed the bootstrap tree
  passing format/test/clippy. CI still must be rerun on the owner-approved
  integration tree and must not be represented as passing from either snapshot.
- GitHub security capabilities and rulesets were not changed by this artifact;
  the settings manifest must be applied and re-read by an owner/admin.
