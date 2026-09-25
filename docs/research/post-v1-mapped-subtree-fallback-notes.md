# Post-v1 design research: mapped subtree/Artist fallback review targets (LP-MPL-010)

## Status

**DESIGN RESEARCH ONLY — NOT AN ACCEPTED DECISION, ROADMAP COMMITMENT,
IMPLEMENTATION PLAN, OR SUPPORT CLAIM.**
This note explores what a future *explicitly mapped* subtree/Artist fallback
adapter *would have to prove* under the accepted architecture if the project
ever chooses to build one. Nothing here promotes a mapped-fallback lane to a
contract, a dependency, an implementation obligation, or a support claim.
Where this note says "option", "sketch", or "review target", read exactly
that. It adds no product source, changes no accepted record, and updates no
traceability row.

**v1 NON-GOAL declaration.** Mapped subtree/Artist fallback is not part of any
merged implementation slice, and the merged Phase-3B slices deliberately
exclude it:

- [LP-MPL-010](../requirements/lumenplot-v1.0.md) — `SHOULD`: "Permit subtree
  or Artist fallback only for explicitly mapped adapters that preserve
  generation, z-order, clipping, and compositing semantics."
  (`Target: mapped-adapter review`, `Release: v1 quality`, `Phase: 2`,
  evidence `AT-MPL-FALLBACK`). The requirement names a review target; it does
  not authorize an implementation now.
- [ADR-0002](../adr/0002-gpu-native-engine-and-matplotlib-adapter.md)
  fallback rules: "Subtree or Artist fallback is permitted only for an
  explicitly mapped adapter that verifies generation, z-order, clipping, and
  compositing semantics."
- [API 0002](../architecture/api-0002-errors-capabilities-fallback.md),
  "Strict unsupported versus hybrid fallback": the four semantics are the validity condition for mapped subtree fallback,
  and silent omission and unreported best-effort degradation are prohibited
- [API 0005](../architecture/api-0005-phase3b-public-matplotlib-backend-surface.md)
  §8 / [ADR 0015](../adr/0015-phase3b-public-matplotlib-adapter-contract.md)
  decision 8 fix the merged slice shape: fallback is only the public
  whole-frame Agg render; "there is no partial subtree fallback because
  public callbacks expose no reliable subtree boundary", and native and Agg
  pixels are never composited.
- Architecture overview: "Subtree fallback is reserved for explicitly mapped
  adapters that preserve generation, z-order, clipping, and compositing."

Changing that envelope — adding a mapped lane, extending the diagnostic
schema, or relaxing the whole-frame-only slice boundary — requires an explicit
amendment to ADR 0015/API 0005 plus coordinated requirements and traceability
updates through the `architecture-authority` decision gate. That work is out
of scope for this note, which changes nothing and commits to nothing.

Evidence basis: all repository citations below were verified verbatim on
origin/main @ `a7d65c7` on 2026-08-24.

## Scope guard: why this note exists

The merged Phase-3B slices carry local contract evidence for the strict and
hybrid-explicit lanes: strict mode raises the stable `unsupported-capability`
result before any target write, and hybrid-explicit publishes exactly one
whole-frame Agg fallback with exactly one structured diagnostic, with
terminal-failure rules that keep input/capacity/OOM/encoding/internal/panic/
reentrancy/stale/I-O failures from ever falling back
([API 0005](../architecture/api-0005-phase3b-public-matplotlib-backend-surface.md)
§§3–5, [ADR 0015](../adr/0015-phase3b-public-matplotlib-adapter-contract.md)
decisions 7–9; local fixtures in `tests/python/test_phase3b_backend.py`
(`TestHybridFallback`, `TestHybridTerminalFailures`) and
`tests/python/test_phase3b_error_and_mixed_output.py`). The suite even pins
the absence structurally:
`test_no_subtree_or_segment_fallback_surface_exists` asserts the module
exposes no subtree or region fallback API at all.

LP-MPL-010 remains a separate, unimplemented lane. Its requirement row is
`Not implemented`, and its named target — a *mapped-adapter review* — has no
written definition anywhere in the repository. That gap is a practical
problem: if a future contributor proposes a mapped adapter, reviewers have no
recorded statement of what "preserve generation, z-order, clipping, and
compositing semantics" means concretely, what evidence such a review demands,
or which accepted boundaries constrain the design.

This note supplies that missing definition as *research*: it derives the
review targets strictly from already-accepted records (requirements, ADR
0002/0007/0015, API 0001/0002/0005), states what a hypothetical mapped
adapter would have to demonstrate, and reserves every unresolved choice for
the `architecture-authority` gate. It closes no gate and implements nothing.

Terminology: "subtree fallback" means rendering some proper subset of the
Figure/Artist graph through a non-native route and combining the results,
where whole-frame fallback renders the entire original request through one
route. "Mapped" means the subset/route decision comes from an explicit,
reviewed mapping, not from runtime heuristic detection.

## 1. Current state (verified)

What exists on the pinned revision, bounded to the Phase-3B public backend
slice:

- Two profiles implemented: `strict-common-2d` (explicit unsupported result,
  no fallback) and `hybrid-explicit` (default; whole-frame Agg fallback for
  unknown public-boundary cases). `accelerated-native` remains opt-in and
  unimplemented.
- Fallback shape: exactly one public
  `matplotlib.backends.backend_agg.FigureCanvasAgg` render of the entire
  original request per successful hybrid publication; native and Agg pixels
  are never composited; the original Figure canvas is restored afterward;
  exactly one structured fallback diagnostic is recorded
  ([ADR 0015](../adr/0015-phase3b-public-matplotlib-adapter-contract.md)
  decision 8). The diagnostic carries the LP-MPL-008 minimum fields:
  kind/reason, type, generation, output_format, scope (`"whole-frame"`),
  representation (`"raster"`), fallback_type (`"matplotlib-agg"`)
  ([API 0005](../architecture/api-0005-phase3b-public-matplotlib-backend-surface.md)
  §3).
- Publication guard: monotonic process-local per-canvas generation counter,
  incremented before preflight; atomic diagnostics replacement only after a
  successful external write; failed attempts clear previously published
  diagnostics; a superseded attempt must not overwrite newer output
  ([API 0005](../architecture/api-0005-phase3b-public-matplotlib-backend-surface.md)
  §2, [ADR 0015](../adr/0015-phase3b-public-matplotlib-adapter-contract.md)
  decision 9).
- Terminal failures: invalid input, capacity/arithmetic overflow,
  allocation/OOM, encoding/internal, redacted Rust panics, reentrancy, stale
  publication, and file-write failures are errors, never fallback triggers;
  device loss and OOM are terminal
  ([ADR 0015](../adr/0015-phase3b-public-matplotlib-adapter-contract.md)
  decision 9; [API 0002](../architecture/api-0002-errors-capabilities-fallback.md)
  forbids DeviceLost/OOM as fallback reasons outright).
- Structural negatives: no subtree/region/partial fallback surface exists in
  the backend module (`test_no_subtree_or_segment_fallback_surface_exists`),
  and raster output is limited to declared whole-frame fallback
  (`TestMixedOutputRasterLimit`).
- Traceability rows as of the pinned revision: LP-MPL-006 `Not implemented`;
  LP-MPL-007 and LP-MPL-008 `Implemented (bounded Phase-3B local contract
  evidence …)`; LP-MPL-009 `Not implemented`; LP-MPL-010 `Not implemented`.
  Strict-mode error fixtures now exist locally
  (`TestStrictErrorFixtures`), so the LP-MPL-006 row understates the local
  evidence; reconciling registry wording is a coordinated-updates concern and
  is intentionally not touched by this note.

No mapped subtree lane exists, no partial-compositing code path exists, and
no claim about their feasibility or cost is made anywhere in this note.

## 2. The four preserved semantics as concrete review targets

The canon names four semantics a mapped adapter must preserve. Read
literally, each is a property the *combined output* must satisfy relative to
the authoritative Matplotlib Figure/Artist render — not a property of the
fallback route alone. A mapped-adapter review would therefore need fixtures
for each property, defined up front. This section derives those targets from
accepted records.

### 2.1 Generation

Accepted basis: the per-canvas monotonic generation counter and
stale-superseded publication guard ([API 0005] §2); the diagnostic
`generation` field ([API 0005] §3, [API 0002]); "A stale result can never
replace a newer publication" ([API 0002]).

A mapped lane extends the hazard from one publication to N concurrent
producers (native regions plus one or more fallback subtrees). Review targets
a future design would need to meet:

- Every subtree render participates in the same attempt-generation discipline
  as the frame: a subtree render started under generation G must never be
  composited into a frame published under a later generation.
- Diagnostic generation values stay meaningful per canvas: exactly one
  generation identifies the successful publication, whether the frame is
  wholly native, wholly fallback, or mixed.
- Failed or superseded subtree attempts clear or invalidate their partial
  state under the same atomic-publication rule; no stale partial pixels can
  survive into a newer frame.

### 2.2 Z-order

Accepted basis: Figure/Artist authority with the derived Scene as revisioned
cache only, precisely to avoid "z-order, visibility, layout, history, and
export races" ([ADR-0002], rejected alternative); unknown content never
disappears silently (overview; LP-MPL-006/007).

Review targets:

- Final pixel stacking equals the public Artist `zorder` total order of the
  authoritative Figure for every supported configuration, including ties
  resolved the way Matplotlib resolves them (insertion/document order), and
  including overlapping native and fallback-produced regions.
- No producer may paint over content it does not own: region ownership must
  partition the figure such that each pixel column's stack is assembled in
  authoritative order.
- Hidden/invisible artists (visibility off, empty data) contribute nothing in
  both routes identically.

### 2.3 Clipping

Accepted basis: the ordered clip stack ([ADR-0007]; O-11 accepted scope);
today's preflight rejects non-rectangular or absent-but-required clips as
unsupported ([API 0005] §4); four-edge rectangular clipping is part of the
merged geometry oracle ([API 0005] §6 item 3).

Review targets:

- The combined output applies each artist's full public clip specification —
  clip box plus clip path — with correct intersection semantics across the
  clip stack, not merely bounding-box approximation.
- A subtree routed to Agg inherits Agg's public clip behavior; a region kept
  native keeps the native rectangular clip behavior; the seam must show no
  visible disagreement for supported configurations (tolerance policy below).
- Clips set by containers (Axes patch, figure region) compose with
  artist-level clips in authoritative order.

### 2.4 Compositing

Accepted basis: semantic `Color` is finite encoded-sRGB straight RGBA; the
rendering boundary performs one conversion to premultiplied linear-sRGB for
source-over compositing; the PNG boundary encodes straight sRGB again;
transparent RGB canonicalizes to zero ([ADR-0007]); alpha compositing
semantics for supported colors and layers are a MUST (LP-RENDER-004). The
merged slice simply avoids the problem: "Native and Agg pixels are never
composited" ([ADR 0015] decision 8).

A mapped lane reintroduces the problem at the subtree seam. Review targets:

- Any combination of native and Agg pixels composites under one source-over
  rule in premultiplied linear-sRGB, with straight-sRGB conversion happening
  only at the final PNG boundary — no pasting of straight-alpha bytes, no
  second background, no double-conversion.
- Alpha ladders (including zero-alpha canonicalization) behave identically
  regardless of which route produced the underlying pixels.
- The background is produced by exactly one producer; overlap seams show no
  halo, fringing, or double-blend artifacts under declared tolerance.

### 2.5 Shared verification frame

Byte identity across routes is not the contract; transform and compositing
rules are ([ADR-0007]). Consistent with the merged slice's oracle style
([API 0005] §6 item 3), a future review would compare decoded RGBA against an
independent geometry/blend oracle and a public Agg reference under a declared
tolerance — with the tolerance itself fixed before review, since a tolerance
chosen after seeing results can hide seam defects. Native byte determinism
stays asserted separately from cross-route visual equivalence, as in the
merged suite.

## 3. What "explicitly mapped" must mean

The merged slices reject runtime subtree detection because "public callbacks
expose no reliable subtree boundary"
([ADR 0015] decision 8 rationale; [API 0005] rejected alternative). The word
"explicitly" in LP-MPL-010 and [ADR-0002] is the escape hatch, and it carries
obligations a future proposal would have to satisfy:

- **Enumeration, not inference.** The mapping is a fixed, reviewed table from
  public artist/effect categories to a fallback route, in the same spirit as
  the merged static documented-public whitelist preflight ([API 0005] §4).
  Heuristic "looks fallback-safe" detection is exactly what the merged slice
  rejects and cannot become the mapping mechanism.
- **Public-API sourcing only.** Entries may key only on documented public
  Matplotlib surface, consistent with the O-10 mandatory boundary
  (Matplotlib 3.11.1 / backend API 1.1; no `_Backend`, `_renderer`, `_api`,
  private artist/transform/cache helpers, undocumented internals).
- **Per-entry evidence obligation.** Each mapping entry implicitly claims the
  four semantics hold for that category; a review would demand the §2
  fixtures exercised for every entry, not a sample.
- **Versioned against the compatibility pin.** The mapping is only as stable
  as the pinned Matplotlib surface; a Matplotlib bump re-opens the mapping
  review rather than silently carrying entries forward.
- **Failure posture inherited.** Unknown-to-the-mapping content follows the
  existing lanes (strict unsupported / whole-frame fallback); a mapped lane
  widens the eligible set but does not soften terminal-failure rules
  ([ADR 0015] decision 9) or the no-silent-degradation rule (overview;
  [API 0002]).

## 4. Seams a future implementation must respect

Constraints already fixed by accepted records that a mapped-lane design
cannot renegotiate:

- **Layer placement.** Subtree routing and any pixel-level combination live
  above the engine, in the adapter/backend layer. The engine stays free of
  Matplotlib, Python, and window-system concrete types ([ADR-0002]
  dependency direction; `.hermes.md` architecture direction). The natural
  reading is: fallback subtrees render through public Matplotlib routes, and
  composition happens on adapter-owned buffers — not through any new engine
  seam.
- **Authority.** The Figure/Artist graph stays authoritative; any native-side
  participation remains a disposable one-shot snapshot derived under
  preflight guards, never a retained competing Scene ([ADR-0002];
  [API 0005] §10).
- **RenderPacket boundary.** The internal RenderPacket stays immutable,
  process-local, non-public, and non-serialized (O-04/[ADR-0004]); a mapped
  lane must not turn partial packets or partial GPU readbacks into a public
  interface.
- **Diagnostic schema ownership.** The accepted Phase-3B envelope fixes
  `scope="whole-frame"` and `representation="raster"` for this slice
  ([API 0005] §3). Any subtree lane needs new scope/representation vocabulary
  — that is a public-schema change owned by the `architecture-authority`
  gate, not an implementation detail. Likewise, "exactly one structured
  fallback diagnostic per successful hybrid publication" ([ADR 0015] decision
  8) would need an explicit amendment to define multiplicity for mixed
  output.
- **Export interaction.** Raster segments inside vector documents are
  governed separately by LP-MPL-009 (supported primitives stay vector-aware
  in PDF/SVG; raster fallback limited to the declared unsupported segment or
  frame; LP-EXPORT-009 requires scope/reason reporting for permitted raster
  segments). A subtree mechanism that yields partial raster regions is a
  direct input to that constraint; both rows are `Not implemented` today.
- **Profile separation.** Benchmark claims stay profile-tagged; a mapped lane
  reports its own costs separately and never inherits native zero-Python SLOs
  (LP-MPL-011; profile table in [ADR-0002]).

## 5. Preconditions and evidence gates for any future lane

If the project ever chooses to build a mapped adapter, the accepted records
already fix the order of operations:

1. **Architecture decision first.** An explicit amendment to
   [ADR 0015]/[API 0005] (and, if the diagnostic envelope grows,
   [API 0002]-adjacent review) defining scope vocabulary, diagnostic
   multiplicity, mapping-registry ownership (public API vs private), and
   layer placement. Per the project context, an unresolved public signature,
   schema, or fallback result is a stop condition until decided.
2. **Mapping registry review.** The §3 obligations enumerated per entry,
   before or alongside implementation.
3. **Four-semantics fixtures.** The §2 targets as named fixture groups:
   stale-partial suppression (generation), z-order golden images with
   tie cases, clip-stack intersection fixtures, and alpha-ladder/seam
   compositing fixtures under a pre-declared tolerance.
4. **Terminal-failure inheritance tests.** Injected capacity/OOM/encoding/
   internal/reentrancy/stale/I-O failures during *partial* production must
   fail the whole publication cleanly — no partially composited frame may
   publish, mirroring `TestHybridTerminalFailures` at the subtree level.
5. **Mixed-output/export alignment.** Structural tests satisfying LP-MPL-009/
   LP-EXPORT-009 for any output containing a declared raster segment.
6. **Benchmark separation.** Named workload, displayed-information size, and
   real p50/p95/p99 per the O-08 protocol, tagged with the mapped profile and
   fallback mode, never pooled with strict/hybrid/native numbers.
7. **Registry reconciliation.** Traceability rows move only through the
   coordinated requirements/traceability update, citing the review evidence.

Nothing in this list schedules the work; LP-MPL-010 is a `SHOULD` at v1
quality targeting a review, and the merged slices' residual-risk statements
(miter-corner parity gaps, Agg toolchain-dependent fallback pixels) remain
accurate constraints any lane would inherit.

## 6. Open questions reserved for the architecture-authority

Unresolved today by design; none may be settled by implementation convenience:

1. **Schema:** if a mapped lane is accepted, what are the exact new
   `scope`/`representation`/`kind` tokens, and does diagnostic multiplicity
   become "one per contributing producer" or stay "one per publication"?
   ([API 0005] §3 and [ADR 0015] decision 8 both fix the single-diagnostic
   whole-frame shape.)
2. **Ownership:** is the mapping registry public API (importable, versioned,
   semver-promised) or private adapter configuration? Either answer touches
   O-02's staged-surface discipline.
3. **Composition site:** confirm adapter-owned buffer compositing as the only
   permitted seam, or decide whether any engine-side partial-output surface
   may ever exist (currently none does, and O-04's non-public packet boundary
   argues against one).
4. **Profile interaction:** does the mapped mechanism serve
   `hybrid-explicit` only, or also form the capability-mapping substrate for
   the unimplemented `accelerated-native` profile — "LumenPlot-aware
   Artist/DataSource after a sealed snapshot" with "mapped capabilities only"
   in [ADR-0002]'s profile table? (The overview table words the authority
   column slightly differently; [ADR-0002] governs.)
5. **Tolerance policy:** the numeric comparison tolerance for seam/oracle
   fixtures, fixed per the merged slice's declared-tolerance practice but
   chosen by the authority, not derived post hoc from prototype output.
6. **Trigger and priority:** whether LP-MPL-010's `SHOULD` is ever promoted
   onto the roadmap at all, given the whole-frame lane satisfies the MUST
   rows (LP-MPL-006/007/008) it depends on.

## References

Internal (canonical sources; linked, not copied):

- Requirements: `LP-MPL-006`, `LP-MPL-007`, `LP-MPL-008`, `LP-MPL-009`,
  `LP-MPL-010`, `LP-MPL-011`, `LP-RENDER-004`, `LP-EXPORT-009`
  ([lumenplot-v1.0.md](../requirements/lumenplot-v1.0.md))
- Traceability: [traceability-v1.0.md](../requirements/traceability-v1.0.md)
  (LP-MPL-006…010 rows, `AT-MPL-FALLBACK`, `AT-EXPORT-FALLBACK`)
- Architecture records:
  [ADR-0002](../adr/0002-gpu-native-engine-and-matplotlib-adapter.md),
  [ADR-0004](../adr/0004-renderpacket-resource-lifecycle.md),
  [ADR-0007](../adr/0007-coordinate-color-text-export.md),
  [ADR-0015](../adr/0015-phase3b-public-matplotlib-adapter-contract.md)
- Architecture companions:
  [api-0001](../architecture/api-0001-native-scene-state.md),
  [api-0002](../architecture/api-0002-errors-capabilities-fallback.md),
  [api-0005](../architecture/api-0005-phase3b-public-matplotlib-backend-surface.md),
  [open-decisions](../architecture/open-decisions.md)
  (O-02, O-04, O-08, O-10, O-11)
- Local evidence referenced: `tests/python/test_phase3b_backend.py`,
  `tests/python/test_phase3b_error_and_mixed_output.py`,
  `python/lumenplot_mpl/backend.py`
