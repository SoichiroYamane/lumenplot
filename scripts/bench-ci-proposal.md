# Benchmark CI job proposal (nightly/manual, proposal-stage)

Status: **proposal only** — no benchmark workflow exists and none is added by the
slice that created this file (see [§5](#5-scope-statement)). This follows the
propose-first convention established by
[`phase3b-ci-job-proposal.md`](phase3b-ci-job-proposal.md): the draft job is
reviewed here first and is only wired into `.github/workflows/` behind the
activation checklist in [§4](#4-follow-up-checklist-when-wiring-activates).

Recorded against origin/main @ bda1dcc8. Governing sources:
[ADR 0006 — support cells, benchmark protocol, and native gates](../docs/adr/0006-support-benchmark-native-gates.md)
and the accepted benchmark protocol scope in
[open-decisions.md §O-08](../docs/architecture/open-decisions.md#o-08-benchmark-protocol-and-performance-accounting).

## 1. Trigger design

Proposed triggers: **nightly `schedule` cron and manual `workflow_dispatch`
only.**

- `schedule`: one nightly cron in UTC (GitHub may delay scheduled workflows
  during periods of high load), for example `cron: "30 21 * * *"`.
- `workflow_dispatch`: manual dispatch with a required single-value `profile`
  input restricted to one of `strict | hybrid | accelerated | native`, so an
  operator can run exactly one lane on demand.

Per-pull-request benchmark runs are **prohibited**. Rationale:

- Hosted benchmark runs are heavy: a locked workspace build plus the accepted
  protocol (five fresh-process blocks of at least 1000 measured frames per
  fixture and profile) costs minutes to hours of hosted compute per run,
  multiplied across profiles.
- Shared hosted-runner timings are dominated by runner variance. Per-PR numbers
  would be noise that produces false regression signals and false confidence,
  not evidence.
- Trend data belongs to scheduled runs on a stable ref. Pull-request lanes keep
  the existing fast checks (build, tests, clippy, static dependency and
  architecture checkers) which are cheap enough to run on every push.

## 2. Proposed step sketch

The draft below is non-normative pseudo-YAML for review; exact workflow text is
written only when wiring activates. Current-state note kept deliberately
honest: `crates/lumenplot-bench` is still the Phase-0 documentation stub, so
the command shape shown here is the planned interface from the accepted
benchmark plan. The job must not be wired until the crate implements it
(checklist item 1 in §4).

```yaml
# DRAFT — lives in this proposal until activation; not a workflow file.
steps:
  - name: Check out repository
    uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
    # Same verified pin as .github/workflows/ci.yml. Full 40-character commit
    # SHA plus human-readable version comment, per the policy and registry in
    # docs/security/pinned-actions.yml (require_full_sha; unverified or guessed
    # SHAs are rejected; updates land dependabot-PR-only).

  - name: Resolve repository Rust toolchain
    id: rust-toolchain
    # Same python3/tomllib resolver pattern as the "Resolve repository Rust
    # toolchain" step in ci.yml: read rust-toolchain / rust-toolchain.toml when
    # present (exactly one may exist), otherwise fall back to the stable
    # channel. The repository currently ships neither file, so the fallback is
    # the active path today.

  - name: Install resolved toolchain
    uses: dtolnay/rust-toolchain@032958afbdc797a9164d3bc0b56325c1308924a5 # 1.97.1 action implementation
    with:
      toolchain: ${{ steps.rust-toolchain.outputs.channel }}

  - name: Run benchmark (single profile, never mixed)
    run: cargo run --locked -p lumenplot-bench -- --profile "$PROFILE" --out bench-out
    # $PROFILE resolves to exactly one of strict|hybrid|accelerated|native.

  - name: Upload benchmark artifacts
    uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
    with:
      name: bench-${{ env.PROFILE }}
      path: |
        bench-out/manifest.json
        bench-out/samples-*.jsonl
      if-no-files-found: error
      retention-days: 30 # proposed default; confirm at wiring
```

Notes on the sketch:

- Profiles fan out through a **matrix placeholder for future expansion**: each
  matrix entry passes exactly one `--profile` value to its own job. Profiles
  are never mixed or pooled inside one run, and cross-run aggregation stays
  descriptive only — gate statistics use the per-block maximum p99 within a
  run, and paired bootstrap analysis happens inside one run's five blocks, per
  the accepted protocol in ADR 0006 §O-08.
- `--locked` follows the repository Nix/locked-environment policy (normal Rust
  verification runs locked). The build profile (dev vs release) is left to the
  runner implementation to fix and must be restated here before activation.
- Artifact contents: one `manifest.json` per run carrying the run-level fields
  (schema version, single profile, environment, protocol, per-block quantiles,
  status), plus the raw `samples-*.jsonl` per-frame sample files referenced by
  each block. Raw samples are uploaded because the accepted protocol requires
  retaining raw samples with no trimming or winsorization.
- Retention policy (proposed default, maintainer decision at wiring): 30 days
  for both artifact kinds, giving roughly a one-month rolling trend window at
  nightly cadence; manual dispatches may choose shorter retention per run.
  Uploads stay restricted to trusted refs (scheduled and manual runs on the
  default branch), mirroring the Phase-3B precedent of upload-on-trusted-push.

## 3. Runner isolation and claim boundary

- `ubuntu-24.04` hosted runners are shared virtual machines. Any number they
  produce is **comparative only**: valid for comparing runs of the same
  workflow revision on the same runner image, never an absolute performance
  result.
- The declared O-07 target cells remain `environment required` until measured
  on declared real hardware per ADR 0006. Nothing this job produces promotes,
  closes, or annotates a support or performance cell.
- Hosted runners provide no display/GPU presentation path relevant to the
  accelerated/native lanes. Those profiles are expected to report missing
  observations as `null` with status `inconclusive` and populated
  inconclusive reasons — never zero-substituted — consistent with the clock
  boundary rules in ADR 0006 (a `present()` return is not scanout; scheduler-
  origin intervals keep their `event_accept_to_` naming; derived cross-domain
  values are excluded from gate statistics).
- Artifacts are convenience trend evidence only, not acceptance evidence — the
  same stance as the Phase-3B wheel manifest.

## 4. Follow-up checklist when wiring activates

1. Prerequisite: `lumenplot-bench` implements the planned CLI
   (`--profile <one-of> --out <dir>`). A local probe run exits successfully,
   writes `manifest.json` and the `samples-*.jsonl` files, and the emitted
   manifest passes the analysis script's `--validate` schema check.
2. Exact move/rename: promote the §2 draft into `.github/workflows/` under the
   final name chosen at wiring (for example `bench-nightly.yml`) and flip this
   file's Status line to “activated”, keeping it as the rationale record —
   the phase3b proposal precedent.
3. Permissions least-privilege: workflow-level `permissions: contents: read`
   and nothing else. No secrets, no credential-bearing steps, no cache actions
   unless separately reviewed.
4. Concurrency group: `concurrency: { group: bench-nightly, cancel-in-progress: false }`
   so a manual dispatch serializes behind the scheduled run instead of
   interleaving two heavy jobs on the shared runner pool.
5. Pins: every `uses:` target carries its full verified commit SHA from
   `docs/security/pinned-actions.yml`. Introducing any action not already in
   the registry requires a registry update first (updates are
   dependabot-pull-request-only per the registry policy).
6. Expected first-run probe output: a green run whose uploaded artifact
   contains one `manifest.json` with schema version 1, exactly one profile
   value, five block entries each reporting at least 1000 frames with
   nearest-rank p50/p95/p99, and `status` either `complete` or `inconclusive`
   with a populated reasons list; plus per-block sample files whose lines match
   the accepted per-frame sample shape. On a hosted runner, expect GPU-domain
   and scanout clocks absent (nulls with recorded reasons), not zeros.
7. Confirm the retention days and the trusted-ref upload restriction in the
   wiring review before merge.
8. Link the first successful hosted run from the evidence records as
   comparative-only data; do not restate any number as a support or
   performance result.

## 5. Scope statement

This slice modifies **no workflow YAML**: nothing under `.github/workflows/`
is added, changed, or removed by the change that introduced this document.
This file is the only artifact of the slice, and everything above remains a
proposal until a maintainer-approved change performs the §4 checklist.
