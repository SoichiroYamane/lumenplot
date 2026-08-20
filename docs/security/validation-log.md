# Validation log

Validated at 2026-08-20T12:01:52Z. The source checkout was read-only input;
validation artifacts and disposable fixtures were kept outside the public tree.
No GitHub setting, visibility, remote, commit, reset, stash, or history operation
was run by the audit.

## Source facts and status drift

The source checkout was on `main` at `06c7857` tracking `origin/main`. At the
first source observation, the working tree contained the partial Rust
implementation and its formatting/test failures:

```text
## main...origin/main
 M crates/lumenplot/Cargo.toml
 M crates/lumenplot/src/lib.rs
 M docs/adr/README.md
?? IDEA.md
?? crates/lumenplot/src/error.rs
?? crates/lumenplot/src/frame.rs
?? crates/lumenplot/src/geometry.rs
?? crates/lumenplot/src/image.rs
?? crates/lumenplot/src/paint.rs
?? crates/lumenplot/src/path.rs
?? docs/adr/0001-rust-matplotlib-raster-backend.md
```

During the audit, an external change/revert replaced that partial snapshot with
the bootstrap tree. The last source status recheck at 2026-08-20T11:59:55Z was:

```text
## main...origin/main
 M docs/adr/README.md
?? IDEA.md
?? docs/adr/0001-rust-matplotlib-raster-backend.md
```

Therefore a byte-for-byte before/after status claim is not honest for this run:
external source drift was detected. The task's commands did not write the source
checkout; the drift is an integration prerequisite to reconcile before applying
this bundle.

The final live source snapshot has no `rust-toolchain` or `rust-toolchain.toml`,
so CI uses the stable channel fallback and makes no MSRV claim. The current Nix
flake evaluates `x86_64-linux`, `aarch64-linux`, and `aarch64-darwin` dev shells.
The current Cargo lockfile has no third-party dependencies. The integrated
baseline records the project license metadata and includes the standard license
texts required by the publication audit.

## Source command results

These are local observations, not GitHub-hosted CI claims.

| Snapshot | Command | Exit | Result |
| --- | --- | ---: | --- |
| initial partial tree | `cargo fmt --all -- --check` | 1 | FAIL; formatting differences in partial files |
| initial partial tree | `cargo test --workspace` | 101 | FAIL; 9 tests ran, 2 failed |
| initial partial tree | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| initial partial tree | `nix flake check --all-systems --no-build --no-update-lock-file` | 0 | PASS |
| final bootstrap tree | `cargo fmt --all -- --check` | 0 | PASS |
| final bootstrap tree | `cargo test --workspace` | 0 | PASS; 0 tests |
| final bootstrap tree | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| final bootstrap tree | `nix flake check --all-systems --no-build --no-update-lock-file` | 0 | PASS |

The initial failures are retained as a prerequisite because the source changed
while this task was running; the integration worker must select and verify the
owner-approved tree rather than assuming either snapshot is the product baseline.

## Disposable fixture results

An isolated disposable fixture was copied from the final source snapshot and
had the complete bundle overlaid. It was never connected to a Git remote.

| Command | Exit | Result |
| --- | ---: | --- |
| `cargo fmt --manifest-path validation-fixture-current/Cargo.toml --all -- --check` | 0 | PASS |
| `cargo test --manifest-path validation-fixture-current/Cargo.toml --workspace` | 0 | PASS; 0 tests |
| `cargo clippy --manifest-path validation-fixture-current/Cargo.toml --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| `nix flake check --all-systems --no-build --no-update-lock-file` in fixture directory | 0 | PASS; all 3 declared systems evaluated |
| `cargo-deny 0.20.2` on unmodified fixture | 4 | EXPECTED FAIL; missing project license field is a publication prerequisite |
| `cargo-deny 0.20.2` on disposable fixture with `MIT OR Apache-2.0` metadata | 0 | PASS; advisories, bans, licenses, and sources all pass |

The licensed fixture exists only to prove the policy/configuration is valid. It
is not a proposed source-tree edit and is excluded from the transfer archive.

## Workflow and policy validation

- YAML parsing with PyYAML `BaseLoader`: PASS for both workflows, Dependabot,
  pinned-action, and settings manifests.
- Custom structure/security validator: PASS. It found 2 workflows, 6 pinned
  action uses, 4 provenance entries, read-only permissions, both required events,
  concurrency cancellation, the Rust command gates, the Nix matrix/job, no
  `pull_request_target`, no `${{ secrets.* }}`, no cache action, and no release /
  publish / deploy workflow.
- `actionlint` 1.7.12 via `nix run nixpkgs#actionlint -- -color=false ...`: PASS
  (exit 0, no diagnostics).
- `cargo-deny` config syntax/policy: PASS on the licensed disposable fixture;
  current unlicensed source failure is intentionally not bypassed.
- Dependency policy: `deny.toml` denies unknown registries/Git sources and
  wildcard dependencies and keeps an explicit dependency-license allow list;
  it does not substitute for project `MIT OR Apache-2.0` metadata or license
  files.
- No compiler/build cache action is included. No release, publishing, deploy,
  artifact-upload, signing, or credential workflow is included.

## Pinned action provenance

Every source ref below was resolved with `git ls-remote` immediately before this
log was written; the workflow uses the exact resulting 40-character commit:

| Repository | Human ref | Resolved commit | Result |
| --- | --- | --- | --- |
| `actions/checkout` | `refs/tags/v4.2.2` | `11bd71901bbe5b1630ceea73d27597364c9af683` | PASS |
| `dtolnay/rust-toolchain` | `refs/heads/1.97.1` | `032958afbdc797a9164d3bc0b56325c1308924a5` | PASS |
| `DeterminateSystems/nix-installer-action` | `refs/tags/v19` | `90bb610b90bf290cad97484ba341453bd1cbefea` | PASS |
| `EmbarkStudios/cargo-deny-action` | `refs/tags/v2.1.1^{}` | `3c6349835b2b7b196a839186cb8b78e02f7b5f25` | PASS |

The human-readable version comments are present beside every `uses:` line, and
`docs/security/pinned-actions.yml` records the command/ref pair and resolution.
The dtolnay action uses the versioned 1.97.1 action implementation while its
compiler channel is resolved from a repository toolchain file when present, or
stable only because the current source has no toolchain file/MSRV declaration.

## Limitations and integration prerequisites

- `gitleaks` and `trufflehog` were unavailable in the audit environment. A
  dedicated secret scanner over the selected tree and reachable history remains
  mandatory before visibility change.
- The source repository and GitHub settings were not changed or re-read through
  an admin operation. Apply and verify `repository-settings-manifest.yml` only
  after the owner resolves publication, license, privacy/history,
  architecture/status, support-contact, and clean-build decisions.
- The pre-integration source lacked license metadata; the integrated baseline
  adds the decided project SPDX metadata and standard license texts before the
  dependency-policy workflow is used as a publication gate.
- Git status drift occurred outside this task's source write scope. Reconcile the
  final source allowlist and run the complete gates again immediately before
  publication.
- CI compile/test/clippy timing is not product-performance evidence. Renderer,
  GPU, shader, text, windowing, native-binding, and other performance-sensitive
  changes require separate reviewed benchmark/compatibility gates.

## Archive

The deterministic archive is generated at the workspace root after this log was
finalized. Because a digest inside the archive would be self-referential, the
archive SHA-256 and exact listing are recorded in the sibling
`ARCHIVE-MANIFEST.txt` file at the workspace root.
