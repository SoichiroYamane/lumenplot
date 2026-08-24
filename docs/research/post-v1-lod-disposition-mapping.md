# Post-v1 research: disposition staging and canon mapping for the remaining LP-LOD rows

## Status

**DISPOSITION STAGING ONLY — NOT AN ACCEPTED DECISION, IMPLEMENTATION CLAIM,
SEQUENCING COMMITMENT, OR SUPPORT CLAIM.**
This note prepares the documentation integration for the three LP-LOD rows the
v1-GATE batch ledger recorded as still-open after lanes E/F/G/H — `LP-LOD-001` (O(W) rendering
intent), `LP-LOD-004` (topology distinction), and `LP-LOD-005` (dyadic M4
hierarchy) — by (a) providing a ready-to-commit draft update of their
[traceability registry](../requirements/traceability-v1.0.md) rows, to be
finalized only against the landed implementation-lane state at merge time, and
(b) mapping each row verbatim to the requirements canon it comes from
(§8 Level of detail; §15 Python and Matplotlib bridge; §26 Performance;
§32 Development phases; Appendix A). Nothing here changes any row's current
status: every cited result below remains `Not implemented` / `Not measured` on
`main` until the implementation lane's evidence actually lands and is
independently verified. Where this note says "draft", "proposal", or
"disposition", read exactly that.

Evidence basis: all registry and requirements citations below were verified
verbatim against `origin/main` @ `e6dc09b` on 2026-08-24.

Terminology: "implementation lane" means card
`[batch3] LOD-001/004/005 MonotonicX extrema path (test-first・engine層)`
(t_981abda3), which owns all code and test changes for these rows. This note
owns no code, no tests, and no requirement-file edit beyond the clearly-marked
draft block that must not be committed before the implementation lands.

## 1. Why a draft instead of an edit

The v1-GATE ledger's evidence-first rule ("do not write `implemented` until it
lands") applies with full force here:

- The implementation lane runs in parallel in its own worktree; at the time of
  writing its outcome is unmerged and unverified.
- A traceability row that names test functions or evidence that does not exist
  on `main` would be exactly the "invented/stale evidence citation" class that
  review round 1 of the MPL authority lane removed (`88ece26`).
- Therefore the deliverable is a **prepared diff**: exact replacement text for
  the three rows plus the family-summary sentence, written so that only the
  evidence parentheticals need final adjustment to whatever the merged tests
  are actually named.

## 2. Current registry state (verbatim, origin/main @ e6dc09b)

From [traceability-v1.0.md](../requirements/traceability-v1.0.md), complete
requirement registry (lines 123–127):

| ID | Class | Target | Phase | Release | Gates | Result |
| --- | --- | --- | --- | --- | --- | --- |
| `LP-LOD-001` | `SHOULD` | 10M benchmark | 1 | v1 performance target | `AT-BENCH-LOD-10M` | Not measured (environment required where hardware or GPU is involved) |
| `LP-LOD-004` | `MUST` | topology model tests | 0 | v1 | `AT-SEM-LOD-TOPOLOGY` | Not implemented |
| `LP-LOD-005` | `SHOULD` | hierarchy benchmark | 0-1 | v1 performance target | `AT-SEM-LOD-MONO`, `AT-BENCH-LOD-10M` | Not measured (environment required where hardware or GPU is involved) |

The sibling rows already closed by the v1-E fixture lane (PR #50, commit
`7a67b58`) are quoted in §4 as the format precedent: `Implemented (bounded
Phase-1A local contract evidence: ...)` naming concrete test functions.
`LP-LOD-007` (Phase-5 deferral, `AT-REVIEW-PHASE-BOUNDARY`) stays outside this
note's scope: it is a phase-boundary review row, not an implementation target
of the batch-3 lane.

## 3. Canon mapping table (requirements v1.0 → LP-LOD rows)

Every statement below was checked character-exact in
[lumenplot-v1.0.md](../requirements/lumenplot-v1.0.md) @ `e6dc09b`.

### 3.1 Primary source: §8 Level of detail (lines 137–147)

| Row | Verbatim canon (lumenplot-v1.0.md) | Location |
| --- | --- | --- |
| `LP-LOD-001` | "**LP-LOD-001** \| `SHOULD` \| Make rendering work approach O(viewport width) rather than O(dataset samples) when a suitable LOD hierarchy exists. \| Target: 10M benchmark \| Release: v1 performance target \| Phase: 1 \| Evidence: `AT-BENCH-LOD-10M`" | §8, line 141 |
| `LP-LOD-004` | "**LP-LOD-004** \| `MUST` \| Distinguish MonotonicX from ArbitraryXY topology. \| Target: topology model tests \| Release: v1 \| Phase: 0 \| Evidence: `AT-SEM-LOD-TOPOLOGY`" | §8, line 144 |
| `LP-LOD-005` | "**LP-LOD-005** \| `SHOULD` \| Use a chunk-local dyadic M4-style hierarchy for MonotonicX selection, binary range lookup, and extrema envelopes. \| Target: hierarchy benchmark \| Release: v1 performance target \| Phase: 0-1 \| Evidence: `AT-SEM-LOD-MONO`, `AT-BENCH-LOD-10M`" | §8, line 145 |

§8 preamble (line 139): "LOD is designed around viewport information rather
than raw sample count. MonotonicX receives the v1 optimized path; ArbitraryXY
retains a correctness model in v1 while advanced simplification and picking
performance remain Phase 5." — the framing sentence for the whole family.

### 3.2 Cross-references elsewhere in the canon

These do not redefine the rows; they constrain how their evidence may be
claimed. All quotes verbatim @ `e6dc09b`.

| Row | Related canon | Location |
| --- | --- | --- |
| `LP-LOD-001`, `LP-LOD-005` | "**LP-PERF-001** \| `MUST` \| Use 10^7 samples per series as the principal native target workload. \| Target: 10M fixture \| Release: native v1 gate \| Phase: 1 \| Evidence: `AT-BENCH-NATIVE-10M`" | §26 Performance requirements, line 355 |
| `LP-LOD-001`, `LP-LOD-005` | §26 preamble: "Performance statements are targets until a benchmark manifest records real measurements. Profiles are never combined into one claim. The native MonotonicX 10M path is the v1 performance gate" | §26, line 353 |
| `LP-LOD-001`, `LP-LOD-005` | "**LP-PERF-009** \| `MUST` \| Evaluate performance with repeatable benchmarks rather than subjective interaction impressions." | §26, line 362 |
| `LP-LOD-001`, `LP-LOD-005` | "**LP-PERF-010** \| `MUST` \| Include fixed 10k, 1M, and 10M line; 10 x 1M; 100 x 100k; large ArbitraryXY; and large MonotonicX workloads. \| Target: fixture manifest" | §26, line 364 |
| `LP-LOD-001`, `LP-LOD-005` | [LP-MPL-011](../requirements/lumenplot-v1.0.md) (`MUST NOT`, §15 line 244) statement cell verbatim: "Apply the native zero-Python and native 10M performance gate to the standard transparent Figure/Artist profile." — gate cell: `AT-BENCH-PROFILE-SEPARATION` (row's Target/Release/Phase cells not reproduced) | §15 Python and Matplotlib bridge, line 244 |
| `LP-LOD-005` | §27 Benchmark preamble: "The benchmark suite is a release evidence source, not an implementation claim." | §27, line 371 |
| `LP-LOD-001` | [LP-PERF-016](../requirements/lumenplot-v1.0.md) (`SHOULD`, §35 line 461) statement cell verbatim: "Reduce the amount of work required for a frame, especially through LOD, retained resources, and native hot paths, before relying on lower-level micro-optimization." — gate cells: `AT-BENCH-LOD-10M`, `AT-REVIEW-PACKET` (row's Target/Release/Phase cells not reproduced) | §35 Final design principles, line 461 |
| `LP-LOD-001` | "**LP-PROD-017** \| `REFERENCE` \| The most important scale outcome is rendering in proportion to displayed information rather than blindly to dataset size, subject to the declared topology and LOD boundaries." (shares gate `AT-BENCH-LOD-10M`) | §36 Completion vision, line 468 |
| family | "**LP-REL-003** \| `PHASE` \| Phase 0 covers workspace foundations, Plot IR, DataChunk ownership, f64 tests, the LOD prototype, benchmark framework, security/reproducibility policy, and architecture documentation. | Target: foundation artifacts | Release: no release claim | Phase: 0 | Evidence: `AT-REVIEW-PHASE-MAP`" (§32 Development phases, line 411) |
| `LP-LOD-001`, `LP-LOD-005` | "**LP-REL-004** \| `PHASE` \| Phase 1 covers the portable line renderer, initial window/runtime path, shader artifacts, axes, ticks, text, pan, zoom, Home, and the native MonotonicX 10M path." | §32, line 412 |
| family | Appendix A section manifest, row "| 8 \| LOD \| O(W) intent, extrema, MonotonicX/ArbitraryXY \| dyadic M4/extrema MonotonicX path; ArbitraryXY advanced performance is Phase 5 \|" | Appendix A, line 486 |

Gate vocabulary ([traceability §Acceptance gate vocabulary](../requirements/traceability-v1.0.md)):
`AT-BENCH-*` = "Benchmark with fixed fixture, warm-up, sample count, quantiles,
and machine manifest"; `AT-SEM-*` = "Semantic, property, invariant, or topology
test". So even a fully green oracle suite can never satisfy `LP-LOD-001`'s or
`LP-LOD-005`'s `AT-BENCH-LOD-10M` cell alone — that requires an O-08 runner
manifest from a declared environment.

<!-- markdownlint-disable MD013 -->

### 3.3 What each row needs for closure (derived from gates + targets)

| Row | Closure requires | Cannot be closed by |
| --- | --- | --- |
| `LP-LOD-001` | An `AT-BENCH-LOD-10M` measurement on a declared host via the O-08 bench runner, recorded per the machine-manifest rules (`LP-PERF-014`) | Oracle/unit fixtures; CI-local runs; any claim inside the Matplotlib adapter profile (`LP-MPL-011`) |
| `LP-LOD-004` | Topology-model tests distinguishing MonotonicX from ArbitraryXY selection semantics under `AT-SEM-LOD-TOPOLOGY` | Benchmark data; renderer goldens |
| `LP-LOD-005` | Both `AT-SEM-LOD-MONO` structural evidence of the dyadic M4 hierarchy *and* the `AT-BENCH-LOD-10M` measurement | Either gate alone |

## 4. Draft traceability edits (DO NOT COMMIT until the implementation lane lands)

The following blocks reproduce the exact current lines and the proposed
replacements. **The base lines are quoted from `origin/main` @ `e6dc09b`; if
the implementation lane rebases over other traceability changes, re-verify the
base lines first.**

Commit precondition checklist (all must hold at finalization time):

- [ ] Implementation branch `[batch3] LOD-001/004/005` is merged or
      merge-approved, and its tests exist under the merged tree paths.
- [ ] Every test name written into a Result cell exists in the merged tree
      (`rg '<name>' crates/` hits).
- [ ] Only the three rows below plus the one LP-LOD family-summary row change;
      no other registry line is touched (v1-GATE audit rule).
- [ ] No benchmark number appears anywhere unless an O-08 manifest artifact
      backs it (`AT-BENCH-*` rows stay `Not measured` otherwise).
- [ ] `git diff --check` clean; both architecture checkers pass (they pin
      nothing under `docs/research/`, but run them anyway).

### 4.1 Draft A — implementation evidence without a benchmark (expected case)

Applies when the lane lands correctness/topology/hierarchy-construction
evidence but no O-08 10M measurement exists yet. Wording follows the accepted
v1-E precedent (`7a67b58`): bounded local contract evidence, named tests, no
benchmark claim.

Registry table occurrence 1 (§Complete requirement registry):

```diff
-| `LP-LOD-001` | `SHOULD` | 10M benchmark | 1 | v1 performance target | `AT-BENCH-LOD-10M` | Not measured (environment required where hardware or GPU is involved) |
+| `LP-LOD-001` | `SHOULD` | 10M benchmark | 1 | v1 performance target | `AT-BENCH-LOD-10M` | Not measured (environment required where hardware or GPU is involved); a batch-3 engine lane added O(W)-path construction evidence without a benchmark claim — see the LP-LOD family summary |
-| `LP-LOD-004` | `MUST` | topology model tests | 0 | v1 | `AT-SEM-LOD-TOPOLOGY` | Not implemented |
+| `LP-LOD-004` | `MUST` | topology model tests | 0 | v1 | `AT-SEM-LOD-TOPOLOGY` | Implemented (bounded Phase-1A local contract evidence: <topology-distinction test names from the merged lane>) |
-| `LP-LOD-005` | `SHOULD` | hierarchy benchmark | 0-1 | v1 performance target | `AT-SEM-LOD-MONO`, `AT-BENCH-LOD-10M` | Not measured (environment required where hardware or GPU is involved) |
+| `LP-LOD-005` | `SHOULD` | hierarchy benchmark | 0-1 | v1 performance target | `AT-SEM-LOD-MONO`, `AT-BENCH-LOD-10M` | Not measured (environment required where hardware or GPU is involved); the `AT-SEM-LOD-MONO` half carries bounded Phase-1A local contract evidence (<dyadic M4 hierarchy construction/selection test names from the merged lane>), while the `AT-BENCH-LOD-10M` half stays open |
```

(The `LP-LOD-002`/`LP-LOD-003`/`LP-LOD-006` rows at lines 124 and 128 stay untouched —
they were closed by v1-E in PR #50 and are not part of this batch.)

Registry table occurrence 2 (§Normative closure: every MUST and MUST NOT) —
note this table has columns ID/Class/Gate/Result, so `LP-LOD-001` and
`LP-LOD-005` (both `SHOULD`) do not appear there; only the `LP-LOD-004` row
does:

```diff
-| `LP-LOD-004` | `MUST` | `AT-SEM-LOD-TOPOLOGY` | Not implemented |
+| `LP-LOD-004` | `MUST` | `AT-SEM-LOD-TOPOLOGY` | Implemented (bounded Phase-1A local contract evidence: <topology-distinction test names from the merged lane>) |
```

Family summary (§Evidence plans by requirement family, `LP-LOD` row) — replace
the trailing clause while keeping everything before "while":

```diff
-...while the topology-model rows (`LP-LOD-004`) and all benchmark claims (`LP-LOD-001`/`LP-LOD-005`) remain open.
+...while the benchmark claims (`LP-LOD-001`/`LP-LOD-005`, `AT-BENCH-LOD-10M`) remain open pending O-08 runner measurements on declared hosts; the topology-model row (`LP-LOD-004`) and the `AT-SEM-LOD-MONO` half of `LP-LOD-005` now carry bounded implemented results naming their test functions.
```

### 4.2 Draft B — full closure including a 10M measurement (only if an O-08 manifest exists)

Do not use unless a machine-manifest-backed benchmark artifact is merged. In
that case additionally convert the two `Not measured` results to the measured
form used elsewhere in the registry and extend the family summary accordingly.
This draft deliberately stops short of writing that wording: inventing a
measured form without the artifact would repeat the stale-citation class of
finding that review round 1 removed.

## 5. Zero-impact proof obligations

| # | Obligation | Concrete mechanism |
| --- | --- | --- |
| i | Docs-only diff | This lane adds one docs file and nothing else; `git diff --name-only origin/main` shows only `docs/research/post-v1-lod-disposition-mapping.md` |
| ii | Traceability untouched in this lane | Neither `docs/requirements/*.md` file is modified here; §4 is draft text living in this research note only |
| iii | Static checkers pin nothing new | `scripts/check_workspace_architecture.py` and `scripts/check_phase2b_dependencies.py` pass unchanged (no workflow vocabulary introduced) |
| iv | CI workflows untouched | No `.github/workflows/` change; no auditwheel/manylinux/maturin/wheel vocabulary added anywhere |
| v | No Rust/Python change | No crate, module, or `python/` file touched; no dependency edges added |

## 6. Handoff notes for the finalize step

Whoever commits the §4 drafts (the implementation lane's landing flow, or a
follow-up docs task once t_981abda3 merges):

1. Re-read the merged test list from the implementation lane's PR and fill
   every `<...>` placeholder with exact, existing test function names.
2. Keep the two-occurrence rule: the `LP-LOD-004` Result text must be
   character-identical in both tables (precedent: `7a67b58`).
3. Update the LP-LOD family-summary row in the same commit so the prose and
   the registry rows cannot disagree (precedent: same commit in `7a67b58`).
4. If the lane lands without topology-distinction tests, drop the §4
   `LP-LOD-004` hunk entirely and leave the row `Not implemented`; partial
   wording must never imply more than the merged tests show.
5. Record the PR number in the completing card's summary, per the batch
   convention.

## Related records

- [Requirements §8 Level of detail](../requirements/lumenplot-v1.0.md)
- [Traceability registry](../requirements/traceability-v1.0.md)
- Sibling research notes: [annotations/viewer staging](post-v1-annotations-viewer-staging.md),
  [export scope disposition](post-v1-export-scope-disposition.md),
  [Metal fastpath](post-v1-metal-fastpath-design-notes.md)
