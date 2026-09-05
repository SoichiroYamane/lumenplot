# LP-MPL-020 eligibility review record (t_b98c82cd)

- Date: 2026-09-05. Role: architecture-authority, docs-only governance.
- Task: t_b98c82cd, branch `docs/mpl-020-eligibility`, base `origin/main`
  at PR #107 merge (`5732199`).
- Companion file: the machine-checkable checklist is
  [mpl-020-eligibility-checklist.md](../requirements/mpl-020-eligibility-checklist.md);
  this note is the review record. Neither file edits the canonical
  requirements or the traceability registry.
- Verdict: **PASS with PROPOSED dispositions** — the five classes in §2
  each satisfy the six-mechanic bundle shape (M1–M6) subject to the two
  recorded gaps (slanted-fill refusal unlanded, PR #102 open). No
  `traceability-v1.0.md` flip is applied by this review.

## 1. Accepted sources

1. [`lumenplot-v1.0.md`](../requirements/lumenplot-v1.0.md) §15
   (`LP-MPL-020`, `SHOULD`, continuous, v1 governance) and §15.1 final
   clause (six-mechanic bundle + regression rule).
2. [ADR 0015](../adr/0015-phase3b-public-matplotlib-adapter-contract.md)
   §4 + amendments §4a (decorated axes, PRAC-A-D) / §4b (legend, PRAC-A-L:
   whitelist entry, collector-trace expectation, style contract, and
   fixtures landed together per LP-MPL-020).
3. [`traceability-v1.0.md`](../requirements/traceability-v1.0.md):
   `LP-MPL-020`, `LP-FUNC-032`/`033`/`034`, `LP-FUNC-040`, `LP-MPL-021`,
   `LP-MPL-022`/`023` result cells (all named rows `Not implemented`
   except the three W1 rows with bounded implemented evidence).
4. Implementation evidence on `origin/main`: `backend_preflight.py`
   whitelist/collector/style/refusal structure; `tests/python`
   contract and oracle suites; PRs #101, #103, #105, #106, #107 merged
   and PR #102 open (evidence trail in checklist §6).

## 2. Per-class findings

- C1 Line2D + gap/non-finite: bundle complete as fixtures. Gap MOVETO
  semantics asserted (`test_public_path_starts_new_subpath_after_every_gap`);
  axis-aware oracle cases landed by PR #105 (test-only). Engine pixel
  support converged by PR #106. `LP-FUNC-040` correctly stays
  `Not implemented` — fixtures are not gate closure.
- C2 fill + span/stack: bundle complete for the axis-aligned surface.
  PR #101 + CI fix honestly re-scoped the pixel input instead of widening
  the fixed gate — the correct governance behavior. FILL-AA decision (b)
  (slanted fills exit strict) is recorded but its enforcing code is not on
  `origin/main`: PROPOSED, precondition for any fill-naming flip.
- C3 bar/rect: contract + parity fixtures landed (W1 PR #69,
  `TestBar*`); rotation refusal and zero-area stroke-only emission present.
  Pinned oracle (PR #102) is OPEN and must not be cited as landed; C3's M6
  cell stays OPEN until it merges.
- C4 steps: complete, including exact-vertex parity
  (`TestStepGeometryParity`), topology recurrence, and non-finite fallback
  that never bridges gaps. Narrowest-risk extension (no new artist class).
- C5 legend: complete and the cleanest M1–M6 specimen — ADR 0015 §4b
  records the four mechanics landing together; refusals, compositing
  order, pixel parity, and hybrid behavior all present.

## 3. Governance checks

- No silent approximation or default-on tolerance introduced or enabled by
  anything reviewed: every out-of-contract input maps to an explicit
  strict refusal (no PNG) or whole-frame Agg fallback with one diagnostic.
- PR #105 (test-only) and PRs #106/#107 (engine AA convergence, no
  whitelist/trace/contract change) correctly claim no eligibility change.
- The checklist's R1 procedure instantiates the §15.1 regression rule per
  class; no per-class rollback code exists yet because no regression has
  occurred — the rule is a documented procedure, which is what the
  requirement's "rollback/removal rule" mechanic calls for at this stage.

## 4. Open items (not blockers for this docs change)

1. Land the FILL-AA (b) slanted-fill refusal (decision recorded
   2026-09-04; code unlanded) — preconditions any `LP-MPL-020` progress
   claim naming fills.
2. Merge PR #102 (bar oracle) green — preconditions C3 M6 LANDED.
3. Separate gate-closure adjudications for `LP-FUNC-040` (gap) and
   `LP-MPL-021` (preflight soundness): fixtures green, gates open.
4. Follow-up: dedicated machine checker for the C1–C5 rows (e.g. extend
   `scripts/check_requirements_traceability.py`); row IDs are stable grep
   anchors for it.

## 5. Recommendation

Accept both new files as the LP-MPL-020 governance instrument; record the
§5 PROPOSED dispositions for maintainer adjudication; do not flip any
registry cell in this change; do not merge this PR without human review
(docs-only, no code touched).
