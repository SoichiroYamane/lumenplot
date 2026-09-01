# Traceability coverage-summary recomputation — t_88a9a591

Date: 2026-08-26 · Lane: review rework for [`wt/t_88a9a591`](../requirements/traceability-v1.0.md)
Scope: `docs/requirements/traceability-v1.0.md` bookkeeping only; no requirement
row, class, phase placement, gate definition, or result cell was altered beyond
the two corrections below.

## Reviewer-required corrections (both applied)

The review of the GAP-R1 adoption commit (a3450c9) required two fixes:

1. **Stale Coverage summary.** The block still carried the pre-adoption totals
   (232 entries / 153 normative / 101 gates / old class and family counts) even
   though the five GAP-R1 rows were already in the registry. Corrected to the
   recomputed values: **237 entries / 156 normative / 106 gates;
   MAY=9, MUST=119, MUST NOT=37, NON-GOAL=6, PHASE=6, REFERENCE=13,
   SHOULD=47; FUNC 41, MPL 23** (all other families unchanged).
2. **Inverted normative split.** Both adoption notes said "two normative, three
   advisory"; the actual registry classes are `LP-FUNC-040`, `LP-MPL-021`,
   `LP-MPL-022` = MUST (three normative) and `LP-FUNC-041`, `LP-MPL-023` =
   SHOULD (two advisory), matching the source research document's own row
   levels exactly. Both occurrences corrected to "three normative, two advisory".

Provenance note: these two corrections originated in maintainer commit `167a884`
(2026-08-26 22:09 JST, doc file only) and were ported onto this recovery
candidate as commit `7cbee58`. Their committed content was checked against this
lane's independent recomputation and is identical — every number and both split
phrases match. This lane's remaining diff is the regression-prevention layer
below.

## Method

Every number was recomputed from the committed file itself — first via a
scratch script during analysis, then locked into a permanent verifier — rather
than transcribed from the reviewer's list:

- Registry rows parsed from "Complete requirement registry" with an anchored
  first-column pattern (`| \`LP-XXX-nnn\``). A naive whole-line scan overcounts:
  long Result cells cite sibling IDs inline (e.g. LP-FUNC-004's implemented
  evidence mentions `LP-MPL-020`), which is what produced phantom FUNC+1 /
  MPL+1 / PROD+1 / REL+1 hits during analysis. Anchored parsing gives 237 rows,
  zero duplicate IDs.
- Gate count is method-independent: 106 unique `AT-*` names whether collected
  from whole rows or from the Evidence-gate(s) column alone. The gate-vocabulary
  section defines only wildcards (`AT-FUNC-*`, ...), so it is not a counting
  source.
- Closure section ("Normative closure: every MUST and MUST NOT") holds exactly
  the 156 registry rows of class MUST/MUST NOT, same classes, no extras.
- Adoption-note arithmetic chains correctly: 2026-08-25 note base
  223/150/92 + nine Matplotlib-wave entries == 232/153/101 == the 2026-08-26
  note's recorded pre-adoption baseline; + five GAP-R1 entries == published
  237/156/106.

## Verification artifacts

- `scripts/verify_traceability_coverage.py` — permanent verifier; recomputes
  everything above and asserts the published block equals the recomputation,
  closure == normative set, GAP-R1 split against both registry and the source
  research doc (`docs/research/codex-gap-verification-candidate-rows-t_3f634d0b.md`),
  all five GAP-R1 gates present, and baseline-chain arithmetic. Exit 0 iff all
  checks pass. Current run: 25/25 PASS (including the five per-gate checks).
- `scripts/test_verify_traceability_coverage.py` — mutation suite (six cases):
  unmodified doc passes; entry-total drift, split regression, missing closure
  row, class drift against source, and gate-name typo are each rejected with a
  targeted message. 6/6 ok.
- CI: `.github/workflows/ci.yml` gains "Verify traceability coverage
  bookkeeping" + "Test traceability coverage verifier mutations" steps after the
  Phase-2B checker pair, and adds the mutation module to the aggregate
  "Run checker mutation suites" step — mirroring the existing
  checker/mutation-test pairing convention. Added steps contain fixed literal
  commands only (no `${{ }}` interpolation).

## Commands

    python3 scripts/verify_traceability_coverage.py          # exit 0, 25 checks PASS
    python3 -m unittest scripts/test_verify_traceability_coverage.py -v   # 6 tests OK
    python3 scripts/check_workspace_architecture.py          # OK (policy tooling accepts additions)

Negative controls were also exercised manually on temp copies before the
mutation suite existed: entry-total drift → exit 1 (4 FAILs); inverted split →
exit 1 (targeted FAIL); deleted closure row → exit 1
(`missing=['LP-MPL-021']`).
