# Scope research: PDF/SVG export disposition input for the v1 residual plan (LP-FUNC / LP-TEXT / LP-EXPORT)

## Status

**DECISION INPUT ONLY — NOT AN ACCEPTED DECISION, SCOPE CHANGE, ROADMAP
COMMITMENT, DEPENDENCY PIN, OR SUPPORT CLAIM.**
This note inventories the currently-open rows of the `LP-FUNC`, `LP-TEXT`,
and `LP-EXPORT` families in the [traceability
registry](../requirements/traceability-v1.0.md) and classifies each row into
exactly one disposition bucket, so the binding scope decision for the v1
residual plan can be taken once, explicitly, by the `project-commander`
through the `architecture-authority` decision gate. Nothing here promotes,
demotes, re-scopes, or closes any requirement. Where this note says
"disposition", "bucket", or "sequencing input", read exactly that.

**What this note deliberately does not do:** it does not declare any
requirement a non-goal, it does not amend the accepted envelope, and it does
not convert a bounded local-evidence result into a product result. Under the
[open-decisions](../architecture/open-decisions.md) discipline, "if a future
decision changes the accepted envelope, supersede or amend ADR 0002
explicitly and update the requirements and traceability registry together."
That machinery is out of scope for this note.

Evidence basis: every repository citation below was verified verbatim on
origin/main @ `858acc1` on 2026-08-24.

## Canon already on the books

The accepted architecture constrains this disposition before any new decision
is made. The following statements are fixed canon, quoted verbatim:

- [Open decisions, "Accepted decisions that are not open"](../architecture/open-decisions.md):
  "PNG and PDF are v1 MUST outputs; SVG is a v1 SHOULD and non-blocking;
  supported vector semantics are retained and raster-only PDF is forbidden."
- [ADR 0007 §Shared output meaning](../adr/0007-coordinate-color-text-export.md):
  "PNG and PDF are v1 MUST outputs; SVG is a v1 SHOULD and non-blocking.
  Supported vector primitives retain vector meaning, and any explicitly
  allowed raster segment reports its scope and reason through the fallback
  diagnostic boundary."
- [ADR 0007 §Text and PDF modes](../adr/0007-coordinate-color-text-export.md):
  "Searchable PDF requires valid embedding/subsetting, widths, `ToUnicode`,
  and `ActualText` evidence. If that evidence is unavailable, the same shaped
  run becomes a deterministic vector outline, or a `StrictSearchable` mode
  fails explicitly." — and the staged prerequisite: "Native
  Parley/Fontique/HarfRust/Skrifa choices and PDF writer/subsetter choices
  require a deterministic font/license/consumer spike before Phase-2
  dependency integration."
- [Traceability §Source-section and phase consistency checks](../requirements/traceability-v1.0.md):
  "SVG is a v1 `SHOULD` and non-blocking; PNG and PDF are v1 `MUST` outputs."
- [Roadmap §5](../../roadmap.md): supported platforms, provenance, CI gates,
  and build/release evidence precede broad external contribution and any
  production-readiness reassessment — packaging-order context for when export
  evidence lands, not whether it is required.

Three consequences follow directly, before looking at any individual row:

1. **A PDF non-goal declaration is not available as a lane-level option.**
   Demoting PDF would change a listed "accepted decision that is not open"
   and would ripple into `LP-REL-010`/`LP-REL-011` (v1 release evidence
   explicitly names vector PDF semantics). It requires an explicit ADR
   amendment plus coordinated requirements/traceability updates at the
   architecture-authority gate. This note records the requirement rows; it
   does not perform or propose that amendment.
2. **SVG needs no cut.** The canon already carries SVG as `SHOULD` /
   "v1 non-blocking" / "incomplete SVG support remains non-blocking for v1".
   That *is* the documented partial-scope record; converting it to a
   non-goal would weaken the requirement without removing any v1 blocker,
   because none exists today.
3. **A raster-PDF shortcut is not available either.** `LP-TEXT-006` and
   `LP-EXPORT-006` are `MUST NOT` rows forbidding raster-only text and a
   raster screenshot as the final PDF representation whenever supported
   vector semantics are available.

## Registry snapshot and disposition

Method: every row of the three families was read from the traceability
registry. Rows whose result is a terminal/closed state were excluded from the
open set; every remaining row appears below exactly once with its registry
fields verbatim and a one-line disposition. Bucket key:

- **B1 — v1-blocking, new-sink chain, spike-first.** First full exercise
  requires a second output sink (PDF or SVG) and therefore the ADR 0007
  staged font/shaping/PDF-writer spike.
- **B2 — v1-blocking, bounded contract exists, product evidence pending.**
  The PNG/state chain; the accepted bounded Phase-2A/2B and Phase-3A/3B
  records carry local evidence, and product-path structural evidence closes
  the rows without any new dependency decision.
- **B3 — v1 non-blocking SHOULD.** No v1 gate depends on closure.
- **B4 — deferred beyond v1.** Phase-5/optional/future rows; no v1 claim.
- **B5 — export-family adjacency owned by other v1 lanes.** Recorded for
  completeness so the open-row census is exhaustive; no export-scope decision
  is taken on these rows here.

### LP-FUNC (30 open rows; LP-FUNC-025 is closed, see exclusions)

| ID | Class | Target | Phase | Release | Evidence gate(s) | Result | Bucket | One-line disposition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `LP-FUNC-001` | `MUST` | deterministic Line2D rendering | 1 | v1 | `AT-FUNC-LINE2D` | Not implemented | B5 | Interaction/render core owned by the engine lanes; not an export-scope question. |
| `LP-FUNC-002` | `MUST` | stable ordering and visibility | 1 | v1 | `AT-FUNC-SERIES` | Not implemented | B5 | Series-state semantics feed exports via Plot State but are decided in the engine lane. |
| `LP-FUNC-003` | `MUST` | axis, tick, and label correctness | 1 | v1 | `AT-FUNC-AXIS` | Not implemented | B5 | Engine-lane correctness; export inherits it through the shared frame. |
| `LP-FUNC-004` | `MUST` | log-axis behavior | 1 | v1 | `AT-FUNC-LOG-AXIS` | Not implemented | B5 | Engine-lane correctness; no export-specific decision. |
| `LP-FUNC-005` | `MUST` | native interaction | 1 | v1 | `AT-FUNC-PAN-ZOOM` | Not implemented | B5 | Interaction lane; UI State exclusion from exports is separately covered by EXPORT rows. |
| `LP-FUNC-006` | `MUST` | anchor-preserving zoom | 1 | v1 | `AT-FUNC-PAN-ZOOM` | Not implemented | B5 | Interaction lane; not export scope. |
| `LP-FUNC-007` | `MUST` | bounded view selection | 1 | v1 | `AT-FUNC-BOX-ZOOM` | Not implemented | B5 | Interaction lane; not export scope. |
| `LP-FUNC-008` | `MUST` | deterministic history transitions | 2 | v1 | `AT-FUNC-HISTORY` | Not implemented | B5 | History/state semantics owned by the interaction/state lane. |
| `LP-FUNC-009` | `MUST` | Legend hit-testing and state changes | 2 | v1 | `AT-FUNC-LEGEND` | Not implemented | B5 | Legend interaction is decided with Legend state rows (UX family), not here. |
| `LP-FUNC-010` | `MUST` | basic scientific inspection | 2 | v1 | `AT-FUNC-CURSOR` | Not implemented | B5 | Cursor semantics; ordinary-export exclusion handled by EXPORT-008/010. |
| `LP-FUNC-011` | `MUST` | Plot State and export consistency | 2 | v1 | `AT-FUNC-GRID` | Not implemented | B5 | Grid toggle consistency is exercised by the B2 export fixtures once they land; decision belongs to the state lane. |
| `LP-FUNC-012` | `MUST` | annotation acceptance fixture | 2 | v1 | `AT-FUNC-ANNOTATION`, `AT-EXPORT-ANNOTATION` | Not implemented | B5 | Export-visible, but annotation staging analysis is a separate lane's charter; defer disposition there. |
| `LP-FUNC-013` | `MUST` | structural PNG output | 2 | v1 | `AT-EXPORT-PNG` | Not implemented | B2 | PNG contract bounded by ADR 0012/ADR 0013 slices; needs public product-path structural evidence to close. |
| `LP-FUNC-014` | `MUST` | structural PDF output | 2 | v1 | `AT-EXPORT-PDF-VECTOR` | Not implemented | B1 | v1 MUST fixed by the accepted envelope; blocked on the ADR 0007 staged font/PDF-writer spike; raster-only PDF is forbidden. |
| `LP-FUNC-015` | `MUST` | package/import/FFI smoke tests | 1-2 | v1 | `AT-LIFE-FFI`, `AT-MPL-LOADER` | Not implemented | B5 | Loader/packaging lane (`LP-MPL-002` carries the bounded entry-point evidence). |
| `LP-FUNC-016` | `MUST` | launch, interaction, close, and package tests | 1-2 | v1 | `AT-FUNC-VIEWER`, `AT-LIFE-VIEWER` | Not implemented | B5 | Standalone-viewer lane; windowing decisions pending there. |
| `LP-FUNC-017` | `SHOULD` | explicit capability status | 5 | v1 non-blocking | `AT-FUNC-SCATTER` | Not implemented | B4 | Phase-5 capability declaration; no v1 blocker, no export dependency. |
| `LP-FUNC-018` | `SHOULD` | explicit capability status | 5 | v1 non-blocking | `AT-FUNC-MARKER` | Not implemented | B4 | Phase-5 capability declaration; no v1 blocker. |
| `LP-FUNC-019` | `SHOULD` | scope declaration | 5 | v1 non-blocking | `AT-FUNC-ERRORBAR` | Not implemented | B4 | Phase-5 capability declaration; no v1 blocker. |
| `LP-FUNC-020` | `SHOULD` | scope declaration | 5 | v1 non-blocking | `AT-FUNC-SECONDARY-AXIS` | Not implemented | B4 | Phase-5 capability declaration; no v1 blocker. |
| `LP-FUNC-021` | `SHOULD` | future SVG structural output | 2 | v1 non-blocking | `AT-EXPORT-SVG` | Not implemented | B3 | Canon already records incomplete SVG as non-blocking; keep the shared frame vector-capable and the row stays honest without a cut. |
| `LP-FUNC-022` | `MAY` | future candidate | future | future | `AT-REVIEW-SCOPE` | Not implemented | B4 | Future MAY candidate; untouched. |
| `LP-FUNC-023` | `MAY` | future candidate | future | future | `AT-REVIEW-SCOPE` | Not implemented | B4 | Future MAY candidate; untouched. |
| `LP-FUNC-024` | `MAY` | future candidate | future | future | `AT-REVIEW-SCOPE` | Not implemented | B4 | Future MAY candidate; untouched. |
| `LP-FUNC-026` | `MAY` | future candidate | 5+ | future | `AT-REVIEW-SCOPE` | Not implemented | B4 | Future MAY candidate; untouched. |
| `LP-FUNC-027` | `MAY` | future candidate | future | future | `AT-REVIEW-SCOPE` | Not implemented | B4 | Future MAY candidate; untouched. |
| `LP-FUNC-028` | `SHOULD` | measurement tooling | 5 | v1 non-blocking | `AT-FUNC-MEASUREMENT` | Not implemented | B4 | Measurement-export is explicitly excluded from ordinary exports by `LP-EXPORT-008`; unrelated to the PDF/SVG question. |
| `LP-FUNC-029` | `MAY` | optional capability | 5 | optional | `AT-FUNC-SERIES-PANEL` | Not implemented | B4 | Optional capability; untouched. |
| `LP-FUNC-030` | `MUST NOT` | UX review | 2 | v1 | `AT-REVIEW-UX` | Not implemented | B5 | UX-scope prohibition; not an export-scope decision. |
| `LP-FUNC-031` | `SHOULD` | 1000-series fixture if shipped | 5 | optional | `AT-BENCH-SERIES-PANEL` | Not measured (environment required where hardware or GPU is involved) | B4 | Optional benchmark, measurement-gated; untouched. |

### LP-TEXT (7 open rows)

| ID | Class | Target | Phase | Release | Evidence gate(s) | Result | Bucket | One-line disposition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `LP-TEXT-001` | `MUST` | shared-layout fixtures | 2 | v1 | `AT-SEM-LAYOUT` | Not implemented | B1 | Shared screen/PNG/PDF/SVG layout is fully exercisable only once a second sink exists; first full fixture lands with the PDF or SVG sink. |
| `LP-TEXT-002` | `MUST NOT` | no-remeasurement review | 2 | v1 | `AT-SEM-LAYOUT` | Not implemented | B1 | Needs at least two sinks consuming one retained layout; same gating as `LP-TEXT-001`. |
| `LP-TEXT-003` | `SHOULD` | text decision record | 2 | v1 quality | `AT-SEM-LAYOUT` | Not implemented | B1 | SHOULD by class, but this record *is* the output of the ADR 0007 staged spike and is the prerequisite for the whole B1 chain; cheapest first step. |
| `LP-TEXT-004` | `MUST` | deterministic font fixture | 2 | v1 | `AT-SEM-LAYOUT` | Not implemented | B1 | Glyph identity across outputs requires the retained font identity the spike selects; fixture follows the first vector sink. |
| `LP-TEXT-005` | `MUST` | PDF structural check | 2 | v1 | `AT-EXPORT-PDF-TEXT` | Not implemented | B1 | Searchable-PDF/ToUnicode-or-outline behavior is defined against the selected font path; blocked on the same spike. |
| `LP-TEXT-006` | `MUST NOT` | PDF structural negative test | 2 | v1 | `AT-EXPORT-PDF-VECTOR` | Not implemented | B1 | Meaningful only once a real PDF path exists; schedules immediately after `LP-FUNC-014`. |
| `LP-TEXT-007` | `SHOULD` | reproducibility manifest | 2 | v1 quality | `AT-SEC-FONTS` | Not implemented | B3 | Font-byte/license manifest is largely independent of the PDF-writer choice; pairs with `LP-SEC-007` outside these families; no v1 gate depends on it. |

### LP-EXPORT (10 open rows)

| ID | Class | Target | Phase | Release | Evidence gate(s) | Result | Bucket | One-line disposition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `LP-EXPORT-001` | `MUST` | dimensions, alpha, and state fixture | 2 | v1 | `AT-EXPORT-PNG` | Not implemented | B2 | PNG dimensions/alpha/state fixture on the bounded-contract basis; product evidence pending. |
| `LP-EXPORT-002` | `MUST` | vector/text structural fixture | 2 | v1 | `AT-EXPORT-PDF-VECTOR` | Not implemented | B1 | PDF-from-Plot-State structural fixture; blocked on the PDF sink (spike-first). |
| `LP-EXPORT-003` | `SHOULD` | structural SVG fixture | 2 | v1 non-blocking | `AT-EXPORT-SVG` | Not implemented | B3 | Same non-blocking status as `LP-FUNC-021`; rides the shared-frame vector data; no v1 gate depends on it. |
| `LP-EXPORT-004` | `MUST` | state/export fixture | 2 | v1 | `AT-EXPORT-STATE` | Not implemented | B2 | Revision-selection/UI-chrome-exclusion contract is fixed by the accepted state records; fixture pending on the public export path. |
| `LP-EXPORT-005` | `MUST` | structural output review | 2 | v1 | `AT-EXPORT-PDF-VECTOR` | Not implemented | B1 | Vector-retention review across line/text/marker/axis/Legend; exercises the PDF sink semantics. |
| `LP-EXPORT-006` | `MUST NOT` | PDF negative test | 2 | v1 | `AT-EXPORT-PDF-VECTOR` | Not implemented | B1 | Raster-screenshot-PDF prohibition test; pairs with `LP-EXPORT-002`. |
| `LP-EXPORT-007` | `MUST` | cross-output equivalence fixture | 2 | v1 | `AT-SEM-LAYOUT`, `AT-EXPORT-LEGEND` | Not implemented | B1 | Spans interactive+PNG+PDF+SVG; needs a second sink to mean more than the PNG pair. |
| `LP-EXPORT-008` | `MUST NOT` | transient export negative test | 2 | v1 | `AT-EXPORT-STATE` | Not implemented | B2 | Transient-state exclusion contract is fixed; negative fixture pending on the public export path. |
| `LP-EXPORT-009` | `MUST` | fallback diagnostics | 2 | v1 | `AT-EXPORT-FALLBACK` | Not implemented | B1 | Declared raster-segment scope/reason reporting is exercised by mixed vector/raster output, i.e. the PDF chain. |
| `LP-EXPORT-010` | `MUST NOT` | export negative fixture | 2 | v1 | `AT-EXPORT-STATE` | Not implemented | B2 | Cursor/crosshair exclusion contract is fixed; negative fixture pending. |

### Excluded closed rows

Exactly one row of the three families is closed and therefore absent from the
tables above: [`LP-FUNC-025`](../requirements/lumenplot-v1.0.md) — `NON-GOAL`,
"A 3D rendering engine is outside v1", result "Not applicable — scope
exclusion". No `REFERENCE`-only or `Planning`-only rows exist in these three
families.

## Census and cross-checks

- Open rows extracted and classified: **47** (`LP-FUNC` 30, `LP-TEXT` 7,
  `LP-EXPORT` 10).
- Bucket membership sums to the census: B1 = 12, B2 = 5, B3 = 3, B4 = 12, B5 = 15; 12+5+3+12+15 = 47.
- Every `MUST`/`MUST NOT` row of the three families also appears in the
  registry's "Normative closure" section with the same evidence gate; the
  dispositions above apply to both appearances identically.
- The `Result` values quoted are the registry's honest statuses; none of the
  bounded Phase-2A/2B or Phase-3A/3B records promotes any of these rows to
  closure, per the registry's status rules and honest-evidence boundary.

## Sequencing input for the residual plan (non-binding)

Read strictly as input to the project-commander's decision, the buckets imply
one dependency spine and two independent tracks:

1. **Critical path (B1):** run the ADR 0007 staged deterministic
   font/license/consumer spike → record its outcome (naturally satisfies
   `LP-TEXT-003`) → select the native shaping/font path and PDF
   writer/subsetter → land the PDF sink → close `LP-FUNC-014`,
   `LP-TEXT-005/006`, `LP-EXPORT-002/005/006` and extend `LP-TEXT-001/002/004`
   and `LP-EXPORT-007/009` fixtures to the new sink.
2. **Independent track (B2):** PNG/state structural evidence on the existing
   bounded contract (`LP-FUNC-013`, `LP-EXPORT-001/004/008/010`); no
   dependency decision is required; it can proceed in parallel with (1).
3. **Non-blocking tail (B3):** `LP-FUNC-021`, `LP-EXPORT-003`, `LP-TEXT-007`
   stay open-and-honest with no v1 gate; SVG structural work naturally
   reuses whatever the B1 spike retains in the shared frame.

If the commander instead wished to demote PDF (or SVG) today, the required
mechanics are: an explicit amendment/supersession at the architecture-authority
gate touching the accepted-envelope list and ADR 0007, coordinated
requirements and traceability edits including the release-evidence rows that
name vector PDF semantics, and a fresh honesty pass over this note. None of
that is initiated here.

## Verification appendix

Commands executed against origin/main @ `858acc1` while preparing this note
(all quoted fields above were copied from their output):

- `grep -n "LP-FUNC-014\|LP-TEXT-005\|LP-TEXT-006\|LP-EXPORT" docs/requirements/traceability-v1.0.md`
- Full-file reads of the registry (status rules, complete requirement
  registry, normative closure, evidence plans, honest evidence boundary),
  `docs/architecture/open-decisions.md`, `docs/adr/0007-coordinate-color-text-export.md`,
  and `docs/roadmap.md`.
- Row-count check: 31 `LP-FUNC` − 1 closed (`LP-FUNC-025`) + 7 `LP-TEXT` +
  10 `LP-EXPORT` = 47 classified rows; bucket sum 47.

No file outside this document was modified.
