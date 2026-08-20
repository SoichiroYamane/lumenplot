# lumenplot

This repository is an intentionally neutral Rust workspace baseline. Product
architecture and crate boundaries are not chosen yet; those decisions belong to
the `sol-architect` Hermes profile before parallel implementation begins.

## Reproducible NixOS development

The development toolchain is pinned by `flake.lock` and is available without a
system-wide Rust installation:

```bash
nix develop
cargo metadata --no-deps --format-version 1
```

The initial workspace contains only a dependency-free placeholder crate so
that formatting and test gates are executable. It defines no product API or
architecture; future crate boundaries must be approved by Sol and recorded in
an ADR.

## Hermes parallel workflow

On the NixOS workstation, from this repository, initialize the two Hermes
profiles and the project board once:

```bash
hermes-nix-orchestration-setup --project-dir "$PWD"
```

This creates the user-owned `sol-architect` and `luna-worker` profiles and the
`lumenplot` Kanban board. It does not import credentials or start a gateway.

Use Sol for architecture decisions and task boundaries:

```bash
hermes -p sol-architect chat
```

Use Luna for implementation, testing, integration, and durable handoff records:

```bash
hermes -p luna-worker chat
```

Implementation cards should request isolated worktrees, for example:

```bash
hermes kanban --board lumenplot create \
  "Implement the approved renderer boundary" \
  --assignee luna-worker \
  --workspace worktree \
  --branch hermes/renderer-boundary \
  --body "Follow the Sol architecture decision and include the required tests."
```

The setup command configures manual decomposition, Sol as the orchestrator,
Luna as the default implementer, and first-class review dispatch. A persistent
gateway or service is intentionally outside this repository's development
baseline; dispatch can be run on demand with `hermes kanban dispatch` when
needed.
