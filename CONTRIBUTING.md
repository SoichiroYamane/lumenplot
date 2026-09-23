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

The canonical gate is:

```bash
nix develop -c bash scripts/verify.sh
```

See [Verification commands](README.md#verification-commands) for the
reproducible gate description.

Formatting and verification commands are intentionally explicit. The commands
below are the manual equivalent:

```bash
# Format a working branch.
cargo fmt --all

# Required checks before requesting review.
# Use a fresh venv python for the python legs below (verify.sh creates one).
python3 -m venv <venv>
<venv>/bin/python -m pip install --editable .
# verify.sh exports MPLCONFIGDIR to a fresh writable temp dir; ensure yours is writable.
cargo fmt --all -- --check
cargo metadata --locked --no-deps --format-version 1
cargo check --locked --workspace --all-targets --all-features
cargo test --locked --workspace --all-features
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
<venv>/bin/python scripts/check_workspace_architecture.py
<venv>/bin/python scripts/check_phase2b_dependencies.py
<venv>/bin/python scripts/check_requirements_traceability.py
<venv>/bin/python -m unittest scripts.test_check_requirements_traceability
<venv>/bin/python scripts/check_docs.py
<venv>/bin/python -m unittest scripts.test_bench_analysis scripts.test_bench_ci scripts.test_check_docs scripts.test_check_phase2b_dependencies scripts.test_check_workspace_architecture scripts.test_phase3a2_manifest scripts.test_phase3a2_sbom scripts.test_phase3b_runtime scripts.test_phase3b_wheel_evidence scripts.test_verify
<venv>/bin/python -m unittest discover -s tests/python
nix flake check --all-systems --no-build --no-update-lock-file
git diff --check
```
scripts/verify.sh is the source of truth for the list above.

For an environment that already has the local package installed, the two
explicit bypasses are available for diagnosis only:

```bash
bash scripts/verify.sh --skip-install --skip-nix
```

The bypass command is not a replacement for the default gate: native runtime
tests must be run after a successful local build, and the Nix check must be
reported separately when it is skipped.

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
