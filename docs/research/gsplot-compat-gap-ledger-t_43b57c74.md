# gsplot compatibility gap ledger — GSPLOT-COMPAT (t_43b57c74)

Status: ANALYSIS INPUT — no requirement is added, changed, or closed by this
document. It maps the observed gsplot 0.4.1 API surface onto the adopted
Matplotlib-parity rows (`LP-FUNC-032`–`LP-FUNC-039`, `LP-MPL-020`) and classifies
each gap per the project-commander directive of 2026-08-26:
(a) covered by landed work, (b) covered by in-flight W2, or
(c) NEW — needs a candidate row or an explicit non-goal declaration.

Evidence basis: all adapter behavior below was executed live on origin/main @
`6fc8db0` (worktree `wt/t_43b57c74`) with the Phase-3B evidence venv
(Python 3.14.7, Matplotlib 3.11.1, NumPy 2.5.2, real native seam) on 2026-08-26.
gsplot reference: PyPI `gsplot 0.4.1` (installed in the same venv) cross-checked
against local checkout `~/dev/python/gsplot` @ `51e61ce`. Every "observed"
refusal string is a verbatim `LumenPlotUnsupportedError` message from that run.
PDF scope cites `docs/research/post-v1-export-scope-disposition.md`; it is not reopened here.

## 1. Method

1. Inventoried the full public gsplot surface (`gs.__all__`, 66 names) and read
   each implementation module to identify exactly which Matplotlib artists,
   collections, and Figure structures every call emits.
2. Reconstructed each of the 11 shipped examples faithfully against the
   lumenplot backend (strict first, then hybrid), using the worktree backend at
   origin/main so landed PRs (#63/#65 decorated axes + labels, #68 fill, #69
   bar, #70 steps, #71 mixed-workload integration) are all present.
3. Recorded the exact strict refusal reason or hybrid fallback type for each
   feature, then classified it against the registry rows.

Note on one-way integration: `LP-MPL-017/018/019` fix that gsplot adapts to
LumenPlot and LumenPlot never depends on gsplot. This ledger therefore treats
"gap" strictly as *native strict-mode rendering capability*, never as a need to
import or special-case gsplot inside lumenplot-mpl.

## 2. Observed strict-mode eligibility surface (live probes)

Eligible today (renders natively with zero diagnostics):

| Surface | Row owner | Probe result |
| --- | --- | --- |
| plain solid Line2D, butt/miter | LP-FUNC-001 + W1 lanes | OK |
| multiple lines / z-order classes | LP-FUNC-002, W1-INT suite | OK |
| `ax.fill`, `fill_between` (any linewidth incl. default edge) | LP-FUNC-032 (#68) | OK |
| `bar`/`barh` axis-aligned Rectangles incl. negative, stacked, edges | LP-FUNC-033 (#69) | OK |
| drawstyle steps-pre/post/mid via exact vertex generation | LP-FUNC-034 (#70) | OK |
| decorated axes: spines, major tick strokes, solid major gridlines | PRAC-A-D (#63/#65) | OK |
| major tick label glyphs (visible labels rendered natively) | PRAC-A-W T-lane | OK |
| `hist` (adapter-side binning → Rectangles) | rides LP-FUNC-033 | OK |
| `stackplot` content (FillBetweenPolyCollection family) | rides LP-FUNC-032 | OK |
| hybrid whole-frame fallback for everything else | LP-MPL-007 (#32) | OK, structured diagnostic |

Refused today (strict), each observed live:

| Surface | Verbatim refusal |
| --- | --- |
| markers on lines | `markers are unsupported in strict mode` |
| dashed/dotted strokes | `dashed strokes are unsupported in strict mode` |
| round/projecting caps | `solid cap style 'round' is unsupported; strict mode requires 'butt'` |
| scatter PathCollection (any style, incl. solid) | `artist PathCollection is outside the supported whitelist` |
| LineCollection (cmap_line/cmap_dash/cmap_scatter base), even fully solid | `artist LineCollection is outside the supported whitelist` |
| Legend | `artist Legend is outside the supported whitelist` |
| titles, axis labels, suptitle, annotations, ax.text | `titles are unsupported` / `axis labels are unsupported` / `artist Text is outside the supported whitelist` / `artist Annotation is outside the supported whitelist` |
| subplotspec/gridspec/mosaic axes | `subplots/grid-spec layouts are unsupported` |
| inset child Axes (`AxesHostAxes`) | `AxesHostAxes is outside the supported Axes whitelist` |
| opaque axes facecolor | `axes background fills are unsupported; set facecolor='none' for strict mode` |
| visible minor ticks | `visible minor ticks are unsupported; strict mode supports major ticks only` |
| log-scale axes (minor ticks auto-on) | same minor-tick gate (clears with `minorticks_off()`) |
| imshow image, contourf QuadContourSet | `artist AxesImage is outside the supported whitelist` / `artist QuadContourSet is outside the supported whitelist` |
| errorbar caps (projecting cap) | `solid cap style 'projecting' is unsupported; strict mode requires 'butt'` |
| PDF/SVG output; bbox_inches='tight'; non-empty PNG metadata | `format 'pdf' is unsupported; only 'png' exists` / `bbox_inches output is unsupported natively` / `non-empty PNG metadata is unsupported natively` |

## 3. Gap mapping table

Legend: **(a)** = covered by landed work; **(b)** = covered by in-flight wave;
**NEW** = needs candidate row or explicit non-goal declaration. "Blocked share"
counts gsplot examples/API calls whose execution path hits the item (11 example
files inventoried; several blocked by more than one item).

| # | Gap (gsplot surface → native need) | Classification | Registry row / disposition | Observed state @ 6fc8db0 | gsplot usage blocked |
| --- | --- | --- | --- | --- | --- |
| G-01 | Legend artist (`gs.legend`, `gs.legends`, `gs.cmap_legend`, called in 9 of 11 examples) | NEW | No adopted row owns *rendering* the publication Legend natively; F-11 was marked COVERED only because interactive/semantic Legend rows exist (`LP-FUNC-009`, `LP-UX-016`–`022`, all Phase 2, not implemented). Strict-mode Legend drawing has no owner and no whitelist entry. | `artist Legend is outside the supported whitelist`; legend presence forces whole-frame Agg under hybrid | 9 of 11 examples; highest single blocker |
| G-02 | Mosaic/subplot layouts (`gs.subplots("ABBB;ACCD")`, `figure.subplot_mosaic`) | NEW (partially pre-covered by axes-on lane decisions recorded as LANDED ELSEWHERE in §4 of the parity draft, but no row owns multi-axes strict eligibility and nothing has landed) | F-09/F-15 verdict "LANDED ELSEWHERE" refers to the practical-expansion planning card; the merged PRAC-A-D slice still refuses any subplotspec axes. Needs either the promised multi-axes lane card or a new row before gsplot's core layout works natively. | `subplots/grid-spec layouts are unsupported` | 8 of 11 examples use multi-panel figures (`subplots("AB…")`) |
| G-03 | cmap_* series (`cmap_line`, `cmap_dash`, `cmap_scatter` → per-segment/per-point colored `LineCollection`/`PathCollection`) | NEW | Scatter itself is deliberately COVERED by `LP-FUNC-017` (SHOULD, Ph 5) but that row does not own the LineCollection class used by `cmap_line`/`cmap_dash`. A candidate row (or an LP-MPL-020-governed extension of LP-FUNC-001's trace to solid multi-colored LineCollections) is needed. Dash variants additionally need dashed-stroke support (G-08). | `artist LineCollection is outside the supported whitelist` even when fully solid | colored_lines, scatter (B panel), matplotlib_interoperability |
| G-04 | Scatter points (`gs.scatter` → `PathCollection`) | (a)-adjacent: row EXISTS but unimplemented | `LP-FUNC-017` SHOULD Phase 5 already owns scatter; classification per directive = existing-row coverage, not a new ID. Listed here because its blocked share is large. | `artist PathCollection is outside the supported whitelist` | 4 examples + every `scatter` call |
| G-05 | Markers (`marker=` on every `gs.line`, default `'o'`; series identities add 10 marker kinds) | (a)-adjacent: row EXISTS but unimplemented | `LP-FUNC-018` SHOULD Phase 5 owns markers. gsplot's default `marker="o"` makes this hit even plain line series. | `markers are unsupported in strict mode` | nearly all `line()` calls unless caller overrides marker |
| G-06 | Dashed/dotted strokes (gsplot default `ls="--"`; 9 of 10 series linestyles are dash families) | NEW | No adopted row owns non-solid stroke patterns natively; F-01 covers only the default drawstyle solid line. Candidate row required (dash pattern as engine command attribute), or fold into the LineCollection/marker wave. | `dashed strokes are unsupported in strict mode` | every default `line()`, `cmap_dash`, error bars |
| G-07 | Axis labels, titles, suptitle, text annotations (`gs.label` records, `gs.title`, `gs.suptitle`, `index=`/panel letters, TeX mathtext labels like `$\sin(x)$`) | PARTIALLY (b): tick-label glyphs landed (PRAC-A-W) but general Text is not in W2 except date formatting (LP-FUNC-037); annotation geometry is `LP-FUNC-012` (MUST, Ph 2, not implemented); general strict Text rendering has no dedicated parity row beyond `LP-MPL-012` capture semantics | The textpath module exists (T-lane), so extension mechanics per LP-MPL-020 are proven; a candidate row for strict-mode free Text/title rendering (TextPath outline oracle per §5.4 text criterion) would close gsplot's biggest text gap. | `axis labels are unsupported`, `titles are unsupported`, `artist Text …`, `artist Annotation …` | 8+ examples (labels/titles/indexes); publication.py entirely |
| G-08 | Inset axes + zoom indicators (`gs.inset`, `gs.inset_axes`; publication.py) | NEW | F-15 insets were folded into "LANDED ELSEWHERE"/multi-axes planning with no landed row; child-Axes whitelist entry absent. Needs explicit placement (new row or named part of the multi-axes card). | `AxesHostAxes is outside the supported Axes whitelist` | publication.py inset panel |
| G-09 | Log-scale axes (`gs.label(xscale=...)`, legacy scale strings) | LANDED (W3, base-10) | Linear is COVERED (`LP-FUNC-003`); base-10 log now renders natively end to end (W3 lane t_a239680f): scale dispatch accepts `linear`/base-10 `log`, projects content/fills/gridlines/tick strokes through the fractional log placement Agg uses, applies matplotlib's clip rule for non-positive data (`-1000` in log units), and inherits invalid-view-domain handling from matplotlib's own limit clamp. Default `LogFormatterSciNotation` labels still refuse (mathtext markers, existing T-lane gate) — callers need a plain formatter (e.g. `ScalarFormatter`) plus `minorticks_off()`; locator-driven minor-tick policy and symlog/logit stay with LP-FUNC-039 (MAY, future). | `$…mathtext labels refused` on default formatter; `visible minor ticks are unsupported` without minorticks_off | any scaled-axis example |
| G-10 | Error bars (`ErrorbarContainer`: projecting caps + data-bearing line collection) | (a)-adjacent: `LP-FUNC-019` SHOULD Ph 5 owns them | Refusal surfaces through cap/join style gates today; real fix is container-class support per LP-FUNC-019. | `solid cap style 'projecting' is unsupported` | measurement-style workflows |
| G-11 | Images / heatmap (`imshow`) | (a)-adjacent: `LP-FUNC-023` MAY future (post-v1) + colorbar deliberately not drafted (§5.3 of parity draft) | unchanged; hybrid fallback serves v1 semantics. | `artist AxesImage …` | none in current examples |
| G-12 | Contours (`contour`/`contourf`) | (a)-adjacent: `LP-FUNC-024` MAY future | unchanged. | `artist QuadContourSet …` | none in current examples |
| G-13 | Cross-primitive compositing guarantees once fills/bars/lines mix with alpha overlap | (b): W2 | `LP-FUNC-035` (SHOULD, 3B-cont.+1, `AT-SEM-COMPOSITING`). W1-INT suite (#71) already pins mixed-frame composition; W2 adds the Agg-layering golden gate. | mixed frames render natively today; ordering pinned by tests, alpha-overlap golden pending | translucency-heavy overlays |
| G-14 | Date/unit tick label formatting (date axes with `DateFormatter`) | (b): W2 | `LP-FUNC-037` (SHOULD, 3B-cont.+1, `AT-FUNC-DATE-AXIS`). Base date plotting already rides the linear path (verified renderable when labels suppressed); only unit-aware label formatting is open. | date frames fall back whole-frame today via the text gate | time-series examples |
| G-15 | Polar projection | out of gsplot scope for now | `LP-FUNC-036` SHOULD Ph 5 unchanged; gsplot exposes no polar API. | rectangular-clip contract | none |
| G-16 | Quiver/vector fields | out of gsplot scope | `LP-FUNC-038` SHOULD Ph 5 unchanged; no gsplot API. | — | none |
| G-17 | PDF output (gs.save defaults emit PNG+PDF; legacy `gs.show` writes PNG+PDF at dpi 600) | DISPOSITIONED — cite, do not reopen | v1 export-scope record (`docs/research/post-v1-export-scope-disposition.md`): PNG+PDF are v1 MUST outputs owned by `LP-FUNC-014`/`LP-TEXT-005`/`LP-TEXT-006` behind the ADR 0007 staged font/PDF-writer spike; raster-only PDF forbidden; SVG SHOULD. Adapter-side PDF is that same envelope — no new row. | `format 'pdf' is unsupported; only 'png' exists`; also `bbox_inches output is unsupported natively` blocks gs.save's default crop=True path | gs.save/gs.savefig/gs.show in ALL examples (every example saves) |
| G-18 | `bbox_inches="tight"` crop (gs.save default crop=True) | NEW (export-shape question, distinct from PDF vector semantics) | Neither the disposition record nor any adopted row addresses tight-crop rendering in the native pipeline (it changes the exported media box). Needs a small candidate row or an explicit statement that native output keeps the exact design canvas and callers must crop outside. | `bbox_inches output is unsupported natively` | gs.save-based examples (crop=True default) |
| G-19 | Non-empty PNG metadata forwarding (gs.save metadata param) | NEW (tiny) | print_png refuses non-empty metadata; either declare metadata a non-goal for the native sink or add a bounded row. | `non-empty PNG metadata is unsupported natively` | only callers passing metadata |
| G-20 | Stale tick-label enumeration vs draw-time order (defect, not a missing feature) | NEW defect finding — hand to implementation planning | When limits are autoscaled (no explicit set_xlim/set_ylim before render), static enumeration reads stale locator text (e.g. expects `'−2'` while draw emits `'0'`), so decorated axes with DEFAULT ticks refuse despite PRAC-A-W being eligible. Pinning limits first renders fine (verified both ways). Also: `_fill_command` raises bare `IndexError: tuple index out of range` on stackplot's per-poly edge-color arrays instead of recording an unsupported reason (LP-MPL-006 violation shape). Both are adapter robustness fixes, cheap, high leverage for gsplot where figures autoscale until save time. | reproducible on demand (scripts kept in run notes) | most realistic gsplot figures (autoscale) |

## 4. Priority view (largest share of gsplot example execution blocked first)

1. **G-01 Legend** — blocks 9/11 examples outright; every figure with a legend
   falls back whole-frame in hybrid, so no native benefit accrues even when all
   content is eligible.
2. **G-02 Multi-panel/mosaic layout** — blocks 8/11 examples at the structure
   level; prerequisite for treating any multi-axes gsplot figure natively.
3. **G-03/G-04/G-05/G-06 cmap_*/scatter/markers/dash cluster** — the plotting
   primitives themselves; G-05+G-06 together make even plain `gs.line()` output
   ineligible unless the caller overrides two defaults. LP-FUNC-017/018 exist
   for scatter/markers (Ph 5); dash strokes and solid LineCollections have no
   owning row (candidate-row candidates).
4. **G-07 Text beyond tick labels** (axis labels, titles, panel indexes,
   annotations) — blocks publication.py completely plus label/index usage in
   most others; T-lane textpath module makes this a natural LP-MPL-020
   eligibility extension.
5. **G-17/G-18 Output shape** (PDF dispositioned; tight-crop open) — affects
   every example's final write step regardless of render eligibility.
6. **G-20 Robustness defects** — cheapest wins; directly convert silent
   fragility into either native success (limits-pinned case renders today) or
   honest diagnostics.

## 5. Recommended next wave (for commander fan-out without re-derivation)

Wave G1 — "unblock the gsplot main path" (each card = one LP-MPL-020-governed
eligibility extension with §5.4 Agg-oracle fixtures; sequencing within the wave
follows the priority list above):

1. **Adapter robustness pair** (G-20): (i) re-derive tick-label enumeration at
   draw time or pin limits before enumeration; (ii) guard `_fill_command`
   against ragged edge-color arrays → explicit unsupported reason. Small diff,
   immediately widens native coverage for autoscaled figures.
2. **Multi-axes strict eligibility** (G-02): admit N standard decorated Axes
   created via subplotspec/gridspec (per-axes groups already exist in the
   command stream; decoration commands must become per-axes). Depends on the
   axes-on practical-expansion lane decisions referenced as LANDED ELSEWHERE —
   confirm ownership before dispatch.
3. **Native Legend rendering** (G-01): whitelist Legend, define its command
   surface (frame patch + proxy line/path samples + glyph runs via the existing
   textpath module). Largest single unlock; fixture = Agg layering comparison.
4. **Solid multi-colored LineCollection** (G-03 subset, no dashes): covers
   `cmap_line` and `cmap_scatter` solids; defer `cmap_dash` until G-dash.
5. **Free Text/title/axis-label rendering** (G-07): extend the T-lane to
   arbitrary Text artists with rotation/alignment; mathtext stays refused
   (unconfigured TeX boundary) and hybrid falls back — matches LP-MPL-012.
6. **Dash-pattern strokes** (G-06 + `cmap_dash` remainder): engine command
   attribute for dash arrays; touches RenderPacket schema → flag C-1-style
   authority sign-off before SHOULD-level commitment.
7. **Tight-crop decision card** (G-18): architecture-authority choice between
   "native output keeps design canvas; crop outside" vs implementing
   bbox_inches-equivalent. Pair with G-19 metadata stance in the same card.

Not scheduled (recorded dispositions): PDF/SVG export (cite post-v1-export-scope
disposition + LP-FUNC-014/LP-TEXT-005/006; ADR 0007 spike prerequisite),
images/contours/polar/quiver/symlog (existing MAY/future rows), UI deferral
(maintainer decision 2026-08-26: viewer slices L1–L3 wait until W2 + gsplot
waves complete).

## 6. Verification trail

- Backend identity: `lumenplot_mpl.backend.__file__` = worktree path; native
  seam = real `_native.abi3.so` copied into the worktree package (16.3 MB,
  CPython 3.14 abi3).
- Probes: ~30 individual strict/hybrid render attempts as listed in §2/§3;
  every refusal quoted verbatim from `LumenPlotUnsupportedError` messages.
- Suite health: `python -m unittest discover -s tests/python -p "test_phase3b*.py"`
  executed against the same environment (result recorded in the completion
  comment).
- gsplot source of truth: PyPI wheel 0.4.1 in the evidence venv; local git
  checkout @ 51e61ce for module internals (identical API surface).
