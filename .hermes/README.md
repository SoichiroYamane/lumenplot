# Hermes project operating contract

This repository uses one Hermes Kanban board, `lumenplot`, and two isolated
profiles:

- `sol-architect` (`gpt-5.6-sol`, `max`): architecture, API/schema,
  ownership/concurrency, compatibility, security-sensitive decisions, and final
  review of high-risk changes.
- `luna-worker` (`gpt-5.6-luna`, `max`): repository investigation,
  implementation, tests, integration, documentation, ADR maintenance, and
  structured handoff metadata.

Sol must make cross-cutting decisions before fan-out. Every implementation
task must include its objective, relevant files, accepted architecture
decisions, invariants, acceptance criteria, compatibility constraints, and
required verification.

Every Luna completion must record:

- branch and commit
- changed files and implementation summary
- commands and results for formatting, linting, static checks, and tests
- architecture decisions followed or deviations
- residual risks and recommended follow-up

Durable project truth belongs in Git: this file, `docs/adr/`, and future
architecture documentation. Profile memory is supplementary worker knowledge,
not the source of project-wide decisions.

Do not commit credentials, tokens, private runtime state, Hermes SQLite files,
session transcripts, or generated worktree contents.
