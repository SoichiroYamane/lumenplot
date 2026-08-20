# Contributing to LumenPlot

LumenPlot is pre-alpha, its public API is unstable, and production use is not
recommended. Contributions are welcome only when the maintainers have enabled
the relevant public repository workflow.

## Before changing architecture

1. Read the [canonical requirements](docs/requirements/lumenplot-v1.0.md),
   [traceability map](docs/requirements/traceability-v1.0.md), and current
   [ADR index](docs/adr/README.md).
2. For a cross-cutting change, write or update an architecture decision record
   before implementation. The record must cover context, decision,
   alternatives, consequences, affected interfaces, and verification.
3. Keep the dependency direction one-way: `Matplotlib -> adapter -> engine`.
   Do not make the engine depend on Matplotlib or Python objects.
4. Do not turn a partial implementation, an old design note, or an internal
   experiment into a public compatibility promise without a maintainer
   decision.

## Issue and pull request workflow

- Use the repository's bug or feature form when one applies. Search existing
  issues before opening a new one.
- Include a small, reproducible description, expected behavior, actual behavior,
  environment information, and the verification performed.
- Do not include credentials, private data, exploit details, or conduct reports
  in public issues or pull requests.
- Keep documentation and capability/error behavior synchronized with code.
- A pull request that changes a public boundary, persistence format, threading
  model, GPU/resource ownership, security behavior, or compatibility policy
  needs an ADR reference and maintainer review.

## Required local gates

Formatting and verification commands are intentionally explicit:

```bash
# Format a working branch.
cargo fmt --all

# Required checks before requesting review.
cargo fmt --all -- --check
cargo test --locked --workspace --all-features
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
cargo metadata --locked --no-deps --format-version 1
nix flake check --all-systems --no-build --no-update-lock-file
git diff --check
```

Run the checks from the repository root. If a command cannot run in the local
environment, report the exact command and reason in the pull request rather
than replacing it with an unverified claim.

## Review gates

### Performance

Do not make a performance claim without a reproducible benchmark. A benchmark
must identify the workload, point count and shape, hardware, driver/runtime,
render settings, warm-up and repetition policy, correctness check, and command
or artifact needed to repeat it. The 10M–100M and 60/120 Hz figures are targets
only until such evidence exists.

### Unsafe code

New `unsafe` code requires a focused safety comment, a minimal boundary, tests
for the invariants it relies on, and explicit maintainer review. Do not use
`unsafe` to hide an unclear ownership or lifecycle model.

### Private APIs and compatibility

Matplotlib private APIs and arbitrary custom `Artist` behavior are not assumed
to be compatible. If a change uses a private API, document the exact version
surface, failure mode, fallback behavior, and compatibility tests. Unsupported
behavior must be explicit; silent degradation is not acceptable.

### Dependency upgrades

A dependency addition or upgrade requires review of license and provenance,
security advisories, supported platforms, MSRV/toolchain impact, feature flags,
lockfile changes, and reproducible build implications. New native, Python, GPU,
font, image, or generated-artifact dependencies need the same review before
being treated as part of the public support contract.

## Maintainer decision boundary

Human maintainers are accountable for legal terms, security response,
architecture decisions, merge authority, release statements, and repository
visibility. Automated tools can assist with analysis and implementation, but
they are not legal or merge authority.
