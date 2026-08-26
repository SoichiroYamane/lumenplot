# Codex gap-probe verification and candidate requirement rows (GAP-R1)

## Status

**DRAFT — input to the maintainer adoption flow. Not an accepted decision.**

This document records the verification of the external gap probe (codex /
gpt-5.6-sol, "Agg vs lumenplot gap survey", 2026-08-26, archived at run scope)
against current `main`, and drafts candidate requirement rows for the gaps that
survived verification. Per the GAP-R1 card:

- Nothing here edits [`traceability-v1.0.md`](../requirements/traceability-v1.0.md)
  or any other canonical registry. Adoption is a maintainer decision made
  through the GOV flow (the precedent is ADR-0017's adoption of the nine
  Matplotlib-parity rows from the parity requirements draft).
- Row levels (`MUST`/`SHOULD`), the registry table format, the evidence-gate
  vocabulary, and the phase model follow
  [`lumenplot-v1.0.md`](../requirements/lumenplot-v1.0.md) exactly.
- Public-safety: no private task identifiers, local paths, host details, or
  internal artifact references beyond the minimum needed to cite landed work
  (`LP-SEC-008` boundary respected).

## 1. Verification basis

All findings below were re-checked on **current `origin/main` @ `f87fc8d`**
(merge of the W2 compositing-review lane) — *not* against the older checkout
the probe ran on (`5c7f75f`-era). Two verification channels were used:

1. **Static**: the adapter source (`python/lumenplot_mpl/backend.py`),
   Phase-3B test modules, and the adopted requirements set
   (`matplotlib-parity-requirements-draft.md` as adopted by ADR-0017,
   `traceability-v1.0.md`) at `f87fc8d`.
2. **Live probes**: the evidence venv (Python 3.14.7, Matplotlib 3.11.1,
   NumPy 2.5.2) driving the real native seam from a disposable copy of the
   `f87fc8d` tree, rendering strict/hybrid frames and decoding the PNGs.
   Probe scripts are retained in the GAP-R1 run workspace (not committed).

### 1.1 Probe claims that are STALE (report corrections)

| # | Report claim | Verified state at `f87fc8d` | Disposition |
| --- | --- | --- | --- |
| S-1 | "Registry discrepancy: this checkout does not show LP-FUNC-032..039 / LP-MPL-020 as adopted … the draft explicitly says NOT AN ACCEPTED DECISION" | False since GOV-1: commit `555d7f1` (ADR-0017 No-Go disposition) canonized all nine rows verbatim in `traceability-v1.0.md`; the parity draft's own header now reads **ADOPTED by the architecture authority, 2026-08-25**. The probe inspected a pre-adoption snapshot. | Correction recorded here (§2); report section B premise discarded. |
| S-2 | "Z-order: not encoded … commands rebuilt in `get_lines()` order … No Phase-3B test proves z-order." | Landed after the probe's base: LP-FUNC-035 D1 implements one stable z-order sort per axes over every eligible child (add-order ties, decoration units riding real zorders), and PR #75/#78 merged the AC1–AC7 z-order + alpha suite (`test_phase3b_compositing.py`, 32 tests incl. mixed-class tie pixel probes and byte-exact scenes). | Claim void; no row drafted. LP-FUNC-002/LP-FUNC-035 already own the surface. |

### 1.2 Probe claims CONFIRMED live (still-valid gaps)

| # | Report claim | Live result at `f87fc8d` |
| --- | --- | --- |
| V-1 | Non-linear scales silently skip frame building → background-only success in strict mode | Confirmed: a log-scale axes (decorations off) under strict mode returns exit-code success with a 200x100 PNG whose decoded pixels are 100% background — byte-identical to every other content-free strict output of the same geometry. Inverted limits behave identically. Hybrid mode falls back correctly with one `LumenPlotFallbackDiagnostic`, so the hole is strict-mode-only. |
| V-2 | NaN/masked gaps can be bridged natively | Confirmed: default-drawstyle line `[0,1,nan,3]` renders `(1,0.5)->(3,2.5)` as ONE continuous polyline through the NaN row (red pixels verified along the whole chord). The Agg oracle paints BOTH adjacent segments' far side only up to the non-finite vertex and resumes painting at the next finite vertex — i.e., Agg kills both segments touching the bad sample; lumenplot joins across them. Same divergence for masked arrays and infinities, in every path-simplification regime. |
| V-3 | Unit/date conversion: only tick formatting owned | Partially stale: `_line_command` now reads `get_xdata(orig=False)` (unit-resolved floats; LP-FUNC-037 comment cites parity draft F-10), so plain date-axis data converts correctly today (live-verified). What remains unowned is the *requirement*: no registry row pins unit-aware geometry fidelity or refuses non-representable converted payloads explicitly. |
| V-4 | Collections outside whitelist | Confirmed verbatim refusals on `f87fc8d`: `artist PathCollection is outside the supported whitelist`, same template for `LineCollection` / `PatchCollection`. |
| V-5 | Scalar-mappable semantics unowned | Confirmed statically: no Normalize/colormap surface exists anywhere in the adapter; every mappable artist is refused before style resolution, and no adopted row requires the semantics. |

## 2. Registry-state note (correction to the report)

The probe's Section B premise ("this checkout does not show those rows as
adopted … the canonical registry still reports FUNC max 31 and MPL max 19") is
**superseded**: the canonical registry at `f87fc8d` carries the nine adopted
rows `LP-FUNC-032`–`LP-FUNC-039` + `LP-MPL-020` (canonized by GOV-1 / ADR-0017,
PR #66, commit `555d7f1`), with honest `Not implemented` result entries per the
release-honesty rule (`LP-REL-014`). The candidate IDs below were verified
unclaimed on `origin/main` (no occurrence of `FUNC-040`, `FUNC-041`,
`MPL-021`, `MPL-022`, `MPL-023` anywhere in `docs/`), so they remain free.

## 3. Candidate rows

Format mirrors the adopted parity draft's row table. Each row names its
evidence gate (new gate names are marked *new*; none collide with the existing
acceptance-gate vocabulary), a phase proposal, and its gsplot-compat ledger
mapping (G-numbers per
[`gsplot-compat-gap-ledger-t_43b57c74.md`](gsplot-compat-gap-ledger-t_43b57c74.md)).
Quality oracle for every row: current Matplotlib Agg backend output, fixed as
the acceptance bar by the maintainer on 2026-08-25 for the adopted parity rows;
the same bar applies here unless the authority says otherwise.

| ID | Level | Requirement | Phase | Release | Evidence gate | Ledger | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `LP-FUNC-040` | MUST | Non-finite sample fidelity — NaN/masked/infinite samples in eligible line data MUST render exactly as Agg renders them: both segments adjacent to a non-finite sample are omitted, and painting resumes at the next finite sample as a new subpath; native output MUST NOT bridge or reconnect across a gap. Quality oracle: Agg pixel parity of gap fixtures (interior NaN, leading/trailing non-finite, masked arrays, infinities) under the parity criteria of the parity draft §5.4. | 3B-cont.+1 | v1 quality | `AT-FUNC-NAN-GAP` (*new*) | — | PROPOSED |
| `LP-MPL-021` | MUST | Strict-preflight soundness — strict mode MUST refuse every Figure it cannot represent completely and return no PNG: any axes whose scale class is outside the declared eligibility surface (today: non-linear x/y scales), any inverted limits pair, and any geometry-stage refusal that leaves an axes with zero projected content MUST produce an explicit `LumenPlotUnsupportedError`, never a successful partial or background-only frame. Hybrid mode's existing whole-frame fallback diagnostic path remains the only success route for such frames. | 3B-cont. | v1 quality | `AT-MPL-PREFLIGHT-SOUNDNESS` (*new*) | G-09 (residual soundness half) | PROPOSED |
| `LP-MPL-022` | MUST | Public unit-conversion consumption — unit-aware artists (dates, calibrated units) MUST be rendered from Matplotlib's publicly converted numeric data (the `orig=False` view) so converted geometry matches Agg's drawn geometry, while Figure-authoritative limits/converter semantics stay untouched; conversion outputs that cannot be represented natively MUST be refused explicitly, never silently dropped to zero commands. | 3B-cont.+1 | v1 quality | `AT-MPL-UNIT-DATA` (*new*) | G-14 (data half; label half stays LP-FUNC-037) | PROPOSED |
| `LP-MPL-023` | SHOULD | Native collection translation — supported members of `LineCollection`, `PatchCollection`, and `PathCollection` MUST NOT be approximated: either translated natively with per-element style, clip, transform, and z-order fidelity (each class landing as an eligibility extension per `LP-MPL-020`: whitelist entry, collector-trace expectation, style contract, fixtures together), or refused explicitly; silent whole-class approximation is forbidden. | W-lane, post-W1 | post-v1 | `AT-MPL-COLLECTIONS` (*new*) | G-03, G-04, G-10 | PROPOSED |
| `LP-FUNC-041` | SHOULD | Scalar-mappable semantics — where mappable artists become eligible (scatter/images per the post-v1 map), normalization and colormap application MUST match Matplotlib: `Normalize` (and declared alternatives) mapping, under/over/bad colors, and shared colorbar↔artist consistency, with Agg pixel parity per the parity draft §5.4. Native colorbar remains governed by its existing disposition (parity draft "deliberately not drafted" list); this row owns only artist-side mapping semantics. | 5 | v1 non-blocking | `AT-FUNC-MAPPABLE` (*new*) | G-11, G-12 (+G-03 cmap_* mapping half) | PROPOSED |

## 4. Row-by-row rationale and boundary notes

### LP-FUNC-040 — non-finite sample fidelity (MUST)

The live divergence is the sharpest of the confirmed gaps: for
`[0, 1, nan, 3]` the oracle leaves the samples around the gap unconnected
(both touching segments omitted; the next finite sample starts fresh), while
`f87fc8d` row-filtering emits one continuous `(1,0.5)->(3,2.5)` polyline.
Verified identical under masked arrays, infinities, long (simplify-on) and
short (raw) paths — the oracle behavior is regime-invariant, so the row can
state it without a simplification carve-out.

Boundary: `LP-FUNC-034` (steps) already refuses *any* non-finite sample
explicitly, which satisfies this row's "never bridge" clause for the step
family; no change is proposed there. The existing fixture
(`test_nan_gaps_do_not_reconnect`, default drawstyle) pins only the retained
vertex count — it cannot distinguish Agg's two-broken-segments semantics from
a bridging chord, which is exactly why a dedicated pixel-parity gate is needed.

Leveling: MUST — silent wrong-pixel output on ordinary messy-data plots
(instrument dropouts are exactly NaN rows) is a correctness defect in the
native surface, cheap to bound, and pure Python-side path assembly (no seam
schema change: subpath breaks express through the existing MOVETO/LINETO code
vocabulary).

### LP-MPL-021 — strict-preflight soundness (MUST)

Confirmed hole: strict mode returns a successful background-only PNG for
non-linear scales (and identically for inverted limits) because frame
assembly silently skips axes it cannot project. The report's "late failure"
half is partially stale: current main re-checks collector reasons after
geometry assembly, and a fully-empty Figure is refused outright ("no drawable
content observed"); what remains open is exactly the skip-class hole — an
axes that *would* have content but whose scale/limits fall outside the
projection surface contributes zero commands and nothing notices. Hybrid mode
already falls back correctly with one structured diagnostic, so this row
costs nothing outside strict mode.

Ledger note: G-09 records log-scale frames falling back whole-frame; its
"residual" half is precisely this soundness defect (the decorated-log refusal
is honest, the undecorated-log fake success is not). Fixing soundness makes
every unrepresentable frame fail loudly or fall back with a diagnostic; it
does not make log axes render natively — that remains `LP-FUNC-004`.

Leveling: MUST — the strict contract ("refuse what cannot be represented")
is the product's trust anchor; a success-shaped lie breaks ADR-0015 §9's
terminal-failure discipline regardless of artist coverage.

### LP-MPL-022 — public unit-conversion consumption (MUST)

Partially landed de facto (`get_xdata(orig=False)`) and live-verified for
date axes (native render, real glyph output), but unowned as a requirement:
nothing pins converted-geometry parity or refuses unrepresentable converted
payloads explicitly. The report's original framing ("dates become zero
commands / late reasons unchecked") is stale at `f87fc8d`; what remains is a
codification MUST so the behavior is a contract, not an implementation
accident. Ledger G-14's data half lands here; its label-formatting half
stays with `LP-FUNC-037`. Leveling follows the probe: cheap (already true),
correctness-critical to pin, zero risk.

### LP-MPL-023 — native collection translation (SHOULD)

Verbatim refusals verified for all three classes. The ledger classifies the
driving gsplot surfaces NEW-(c) (G-03 cmap_* LineCollection/PathCollection
families, even fully solid) or existing-row-unimplemented (G-04 scatter via
`LP-FUNC-017`, G-10 error bars via `LP-FUNC-019`) — none of those existing
rows owns the *collection class itself*, which is the gap this row declares.
Each class carries per-element style/transform/z-order contract risk, which
under the parity draft's own criteria (§6 criterion 4: RenderPacket-schema
touching rows cannot exceed SHOULD) caps this row at SHOULD. Per-class
adoption still flows exclusively through the `LP-MPL-020` eligibility
mechanics; this row only declares the translation requirement and forbids
silent whole-class approximation. The MAY-level scatter row precedent
(parity draft §5.1, risk-dominated) stays untouched — this row does not
pre-adjudicate any specific class.

### LP-FUNC-041 — scalar-mappable semantics (SHOULD)

No Normalize/colormap machinery exists natively (static check). Deliberately
narrower than the probe's draft: colorbar rendering keeps its recorded
disposition (parity draft §5.3 "deliberately not drafted"), images/scatter
eligibility stays owned by the post-v1 map (`LP-FUNC-022/023`,
`LP-FUNC-017`), so this row owns ONLY mapping semantics where a mappable
artist becomes eligible. The cmap_* ledger rows (G-03) and image/contour
surfaces (G-11, G-12) are the demand side. SHOULD per the parity draft's
transform-family cost heuristic; phase 5 aligns with `LP-FUNC-038/039`.

## 5. Phase placement proposal

| Wave | Rows | Rationale |
| --- | --- | --- |
| 3B-cont. (next strict-correctness slice) | `LP-MPL-021` | Smallest diff, closes a success-shaped lie; unblocks honest strict-mode claims everywhere else. |
| 3B-cont.+1 | `LP-FUNC-040`, `LP-MPL-022` | Both are Python-side path/data assembly with pixel-parity gates; natural to land and evidence together. |
| W-lane, post-W1 | `LP-MPL-023` | Each collection class is an `LP-MPL-020` eligibility extension; sequencing belongs to the active practical-expansion lane. |
| 5 | `LP-FUNC-041` | Aligns with the transform-family rows (`LP-FUNC-038/039`); presumes mappable eligibility decisions first. |

## 6. Explicit non-goals recorded by this verification

- No registry edit, no gate-name registration, no result-column change: all
  of that is maintainer adoption work in the GOV flow.
- No change proposed to the LP-FUNC-034 step-family non-finite refusal
  (already conforms).
- Z-order, decorated axes, tick-label glyphs, fills/bars/steps: verified
  landed and owned (S-2 / ledger section 2); no row drafted.
- The report's "implementation gaps already owned" list is confirmed
  accurate as written (z-order→`LP-FUNC-002`, log axes→`LP-FUNC-004`,
  dashes→`LP-RENDER-007`, markers→`LP-FUNC-018`,
  fallback-reason retention→`LP-MPL-008`); none re-drafted here.

## 7. Verification artifact index

- Report under verification: external codex/gpt-5.6-sol survey, 2026-08-26
  (archived at run scope; not committed — public-safety boundary).
- Live probes: disposable `f87fc8d` tree + freshly built native seam,
  evidence venv (Python 3.14.7, Matplotlib 3.11.1, NumPy 2.5.2);
  probe scripts retained in the GAP-R1 run workspace only.
- Reference documents: adopted
  [`matplotlib-parity-requirements-draft.md`](../requirements/matplotlib-parity-requirements-draft.md)
  (row format, §5.4 oracle criteria, §6 leveling criteria),
  [`traceability-v1.0.md`](../requirements/traceability-v1.0.md) @ `f87fc8d`
  (registry state),
  [`gsplot-compat-gap-ledger-t_43b57c74.md`](gsplot-compat-gap-ledger-t_43b57c74.md)
  (G-number mappings), ADR-0017 (adoption precedent).
