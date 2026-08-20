## Summary

<!-- State the user-visible change and its current status. -->

## Scope and design

- What changed:
- What is explicitly unsupported or unchanged:
- [ ] Cross-cutting architecture changes have an ADR reference or are covered
      by an existing accepted ADR.
- [ ] The dependency direction remains `Matplotlib -> adapter -> engine`.

## Verification

- [ ] `cargo fmt --all -- --check`
- [ ] `cargo test --locked --workspace --all-features`
- [ ] `cargo clippy --locked --workspace --all-targets --all-features -- -D warnings`
- [ ] `cargo metadata --locked --no-deps --format-version 1`
- [ ] `nix flake check --all-systems --no-build --no-update-lock-file` (when the
      Nix development environment is part of the change)
- [ ] `git diff --check`

## Compatibility, security, and performance

- [ ] Unsupported capabilities fail or use a documented explicit fallback; no
      silent degradation was introduced.
- [ ] No secrets or private data are included.
- [ ] New `unsafe`, private API use, native dependency, or dependency upgrade is
      documented and has the required maintainer review.
- [ ] Any performance statement includes a reproducible benchmark, workload,
      environment, correctness check, and command or artifact. Otherwise the
      statement is described only as a target.

## Checklist

- [ ] Documentation and status wording match the implementation.
- [ ] Tests cover the changed behavior and the relevant failure path.
- [ ] This pull request does not claim production readiness or stable API
      compatibility for pre-alpha behavior.
