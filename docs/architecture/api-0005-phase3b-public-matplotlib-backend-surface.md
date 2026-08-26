# API 0005: Phase-3B public Matplotlib backend surface

- Status: **Accepted staged surface contract — Phase-3B first strict-mode and hybrid-explicit implementation slices merged with local contract-test evidence; packaged public-backend runtime evidence pending**
- Date: 2026-08-23
- Decision owner: architecture-authority
- Recorded by: engineering-worker
- Scope: O-02P/O-09/O-10 Phase-3B public canvas, result/diagnostic separation, file-output, and eligibility surface (first strict slice)
- Governing architecture: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](../adr/0002-gpu-native-engine-and-matplotlib-adapter.md)
- Boundary record: [ADR 0003 — facade and crate dependency graph](../adr/0003-facade-and-crate-dag.md)
- Error record: [API 0002 — errors, capabilities, and fallback](api-0002-errors-capabilities-fallback.md)
- Staged private predecessor: [API 0003 — Phase-3A Python, NumPy, and private helper](api-0003-python-numpy-matplotlib.md)
- Contract record: [ADR 0015 — Phase-3B public Matplotlib adapter contract](../adr/0015-phase3b-public-matplotlib-adapter-contract.md)

This record is the accepted surface companion to ADR 0015. It details the
public backend module surface, the result/diagnostic separation, file-output
semantics, and the eligibility/tests boundary for the first Phase-3B slice. It
authorizes no implementation: until ADR 0015 and this record are accepted, no
Python source, `backend.py`, manifest entry, entry point, wheel, or workflow
may be created for this surface. All exact Python names in
[Provisional names](#provisional-names--non-contract-until-phase-3b-acceptance)
are non-contract placeholders subject to the acceptance decision.

## Requirement references

Same rows as ADR 0015: ownership/bridge portions of `LP-MPL-001`
through `LP-MPL-017`, `LP-FUNC-001`, `LP-FUNC-003`, bounded by `LP-PROD-006`.
Profile mapping: `LP-MPL-003` profiles; `LP-MPL-004` authority;
`LP-MPL-006`/`007`/`008` unsupported/fallback/diagnostics; `LP-MPL-011` no
native performance claim; `LP-MPL-014` reference baseline only.

## Context

API 0003 froze the Phase-3A private helper boundary and deliberately left every
Phase-3B public schema open. The completed read-only public-backend research on
Matplotlib 3.11.1 supplies the observed callback signatures, loader mechanics,
file-output semantics, and risk inventory that this proposal turns into a
reviewable surface definition. Helper/package/wheel runtime evidence remains
pending on a separate lane; this proposal records a schema candidate for
reconciliation against that evidence, not a shipped result.

## Decision

### 1. Backend module identity and exports

Identity per `LP-MPL-002` (unchanged from API 0003 §1 plus the backend module):

```text
distribution      lumenplot-mpl
import package    lumenplot_mpl
private extension lumenplot_mpl._native
backend module    lumenplot_mpl.backend
module loader     module://lumenplot_mpl.backend
entry point       [project.entry-points."matplotlib.backend"]
                  lumenplot = "lumenplot_mpl.backend"
```

Source layout extends accepted API 0003 §1 (`python/lumenplot_mpl/
{__init__.py,_native.pyi,py.typed}` + repository-root `pyproject.toml` built via
`crates/lumenplot-python`) with `python/lumenplot_mpl/backend.py` added at
implementation time only. The backend module exposes:

- `FigureCanvasLumenPlot(FigureCanvasBase)` with class alias `FigureCanvas`;
- `FigureManager = FigureManagerBase` unchanged — diagnostics live on the
  canvas, never on the manager;
- `required_interactive_framework = None`;
- `filetypes` containing exactly PNG;
- no `_Backend`, `new_figure_manager`, `draw_if_interactive`, or module-level
  `show` (the modern canvas API does not require them).

Registration works both ways from the loader matrix: `matplotlib.use("module://
lumenplot_mpl.backend")` before pyplot import, and `matplotlib.use("lumenplot")`
through the installed entry point. The crate DAG stays
`lumenplot-python -> lumenplot -> {lumenplot-engine, lumenplot-export}`; the
engine remains free of Python/Matplotlib concrete types.

### 2. Canvas behavior and generation guard

The canvas holds only adapter-owned state: an immutable last-publication record
and a monotonic process-local generation counter started at zero per canvas
instance. Every native attempt increments generation before preflight.
Publication of bytes-plus-diagnostics is atomic: `last_diagnostics` is replaced
only after a successful external write, and any failed attempt clears previously
published diagnostics so stale fallback state is never reported. A stale attempt
(generation superseded) must not overwrite newer output. Calls are reentrant:
no non-reentrant lock is held across Matplotlib callbacks, no global mutable
state exists, and draw-event reentrancy follows explicit policy rather than
accident. The Figure/Artist graph stays authoritative; the canvas never mutates
it to force eligibility and restores temporary effective-DPI state after
output.

### 3. Result and diagnostic separation

Matplotlib-compatible methods keep their contract shape:

- `Figure.savefig(...)` / `canvas.print_figure(...)` / `canvas.print_png(...)`
  return `None`;
- a separate provisional helper returns owned PNG bytes plus immutable
  diagnostics (name in Provisional names);
- native success carries an empty diagnostics tuple;
- hybrid success carries exactly one structured fallback diagnostic;
- strict unsupported raises/fails with the stable `unsupported-capability`
  token before any target write.

Diagnostic information content (exact field naming provisional) is the minimum
required by LP-MPL-008 and API 0002:

```text
kind/reason     stable unsupported-capability or fallback token
type            public artist or callback type context
generation      non-negative process-local per-canvas attempt number
output_format   "png" for this slice
scope           "whole-frame" for hybrid fallback
representation  "raster" for Agg fallback; vector is out of scope here
fallback_type   "matplotlib-agg" when hybrid fallback published the frame
```

No diagnostic field becomes a persistence/wire identity, numeric enum, JSON
schema, or stable message wording; `str()`/repr/message text is explicitly
non-contract. Errors reuse the lowercase API-0002 tokens through the existing
exhaustive BridgeError mapping (`InvalidInput→invalid-input/input`,
`UnsupportedCapability→unsupported-capability/capability`,
`CapacityExceeded→invalid-input/input`, `AllocationFailed→out-of-memory/
resource`, `EncodingFailed→internal/internal`, `Internal→internal/internal`),
with `LumenPlotError(RuntimeError)` remaining the only LumenPlot exception
class for this slice. Python call-binding errors stay `TypeError`; interpreter
allocation may stay `MemoryError`; panics are redacted to internal.

### 4. Eligibility preflight and eligible trace

Two stages run before any native allocation/output, as specified in
ADR 0015 decisions 3–4: the static documented-public whitelist check, then one
public `RendererBase` collector traversal asserting the exact trace of one
figure-background `draw_path` plus one Line2D `draw_path`. Any other renderer
callback, unknown/custom artist, axes decoration, non-affine transform,
non-rectangular or absent clip where required, or style outside decision 5's
fixed set causes explicit unsupported handling (strict) or whole-frame Agg
fallback (hybrid). The collector executes user artist code by design; it runs
before native allocation, is an observation, and never mutates the Figure.
Rendering sources geometry through the data route (public Line2D getters +
public increasing linear Axes limits into one temporary linear `ArbitraryXY`
request); the collected path reconciles affine/clipping behavior but never
feeds rendering.

PRAC-A-D alignment (ADR 0015 §4a, 2026-08-25): a standard decorated `Axes`
(`axison=True`) is additionally eligible. The collector grammar widens to
balanced artist subgroups whose only stroke events are `new_gc()` +
`draw_path`; each decorated axes emits solid visible major gridlines, major
tick strokes (`markersize * dpi_eff / 72` px outward), and its visible spine
edges — all with the §5 stroke surface (Butt/Miter), clipped to that axes'
rectangle and ordered ahead of its content lines. Axes facecolor other than
`'none'`, titles, axis labels, offset/tick label text (T-lane), minor tick or
gridline content, non-solid grid styles, subplotspec/gridspec children, and
non-exact `Axes` types remain explicitly unsupported.

### 5. File-output semantics

PNG-only with an explicit guard: `print_figure` is overridden/guarded so
non-PNG formats fail explicitly instead of silently selecting another
registered backend encoder (research demonstrated inherited base-class `%PDF-1.4`
fallthrough). Additional fixed rules:

- `print_png(self, target, **kwargs)` accepts str/path-like/binary file-like
  targets and tolerates inherited kwargs (`orientation`, `facecolor`,
  `edgecolor`, `bbox_inches_restore`); invalid orientation values fail
  explicitly rather than being ignored.
- Effective savefig DPI drives both pixel geometry (72-point conversion) and
  the Phase-2 `output_dpi`; `dpi='figure'` resolves to the original DPI; state
  restoration happens even on failure paths.
- `metadata=None`/empty is the only native-compatible metadata request;
  non-empty metadata is unsupported natively and unsupported in hybrid (Agg's
  public path may add its own Software/dpi chunks; that difference is
  documented, not hidden).
- Non-empty `pil_kwargs`, `bbox_inches='tight'`, non-default padding, and
  `bbox_extra_artists` are unsupported natively; hybrid may delegate the whole
  original request to public Agg. The base tight-bbox preliminary probe must
  never write native bytes.
- Native bytes are fully constructed before writing. Adapter-owned files are
  opened/written/closed by the adapter; caller-owned binary file-likes receive
  exactly one public `write(bytes)` and are never closed; `OSError`, short
  writes, and user writer exceptions propagate unchanged; Agg is never invoked
  after a native I/O failure.
- Fallback-after-failure rules follow ADR 0015 decision 9: capability
  fallback only before output; input/capacity/OOM/encoding/internal/panic/
  reentrancy/stale/I-O failures are terminal errors.

### 6. Tests matrix

Verification after acceptance (each item maps to a named fixture group):

1. Loader/import: clean-process imports, subclass/alias checks,
   `required_interactive_framework is None`, PNG-only `filetypes`,
   module-loader and entry-point registration, forbidden-name scan
   (`_Backend`, `_renderer`, `_api`, `_pylab_helpers`, `matplotlib._*`,
   private artist/transform/cache helpers, undocumented `axison`).
2. Collector trace: exact figure/patch/axes/line2d group order, single
   background and line `draw_path`, affine transform, rectangular clip,
   `rgbFace=None`; axes-on negative fixture rejected/fallback.
3. Geometry/style oracle: linear increasing limits, top-left mapping at
   1x/2x/3x DPI and fractional sizes, four-edge clipping, NaN gaps without
   reconnection, duplicate points, fractional axes positions, RGBA/alpha
   quantization with zero-alpha canonicalization, widths 0.5/1/2 pt, explicit
   Butt/Miter; decoded-RGBA comparison against an independent geometry/blend
   oracle and Agg visual reference under declared tolerance; same-host native
   byte determinism asserted separately; no byte identity vs Agg.
4. Native output: `savefig(BytesIO, format="png")`, direct `print_png`,
   pathlib paths with/without extension, uppercase format, dpi forms,
   facecolors, dimensions, PNG chunk/metadata contract, repeated identical
   bytes.
5. Options/errors: strict and hybrid handling of marker, dash, default
   projecting/round styles, invalid width, non-default drawstyle, path
   effects/sketch/snap/antialias-off, log/inverted/non-affine transforms,
   custom clip, multiple lines/axes, text/ticks/spines/legend, image,
   collection, Gouraud, hatch, TeX, non-empty metadata/pil_kwargs/tight bbox,
   PDF/SVG/other formats, non-writable target, short writer, writer exception,
   invalid dpi/orientation.
6. Fallback and terminal failures: hybrid publishes exactly one whole-frame Agg
   render with one complete diagnostic; injected capacity/OOM/encoding/
   internal/reentrancy/stale/I-O failures never fall back; failed attempts
   clear prior diagnostics; strict fails before any target write.
7. Lifecycle/generation: repeated draw/draw_idle/savefig after mutation,
   atomic `last_diagnostics` replacement, monotonic generations, stale-request
   suppression, plt.close/manager destroy/create-draw-close cycles, headless
   show without GUI hang, no stale canvas ownership.
8. Packaging/evidence: install/import across claimed CPython cells with the
   pinned NumPy evidence stack, entry-point resolution, sdist/py.typed contents
   if selected, locked dependency/license/provenance checks; timing claims only
   via the benchmark protocol with named workload and real percentiles.

Initial evaluation matrix: CPython 3.11–3.14 × Matplotlib 3.11.x/API 1.1 on the
already-evidenced Linux wheel cell; Matplotlib 3.10, other platforms, and
free-threaded interpreters remain unclaimed future cells. No performance,
platform, or compatibility-percentage claim exists anywhere in this proposal.

## Provisional names — non-contract until Phase-3B acceptance

Every name below is a placeholder for review discussion. Acceptance decides the
final spelling; implementation must not ship any of these names before then.

```text
canvas method        render_png() -> LumenPlotPngResult          (owned-bytes helper)
result type          LumenPlotPngResult(bytes, diagnostics)
diagnostic type      LumenPlotFallbackDiagnostic
warning type         LumenPlotFallbackWarning                    (if a warning mode survives review)
canvas attribute     last_diagnostics                            (read-only observation)
```

Constraints already binding regardless of final names: savefig/print_png return
`None`; results own their bytes; diagnostics are immutable after publication and
replaced atomically; warnings/recording modes must be explicit and no silent
ignore mode may exist if a warning mode is accepted.

## Alternatives considered

- **Freezing exact public names now** was rejected: API 0003 keeps Phase-3B
  schemas deliberately open until helper evidence lands, so names stay
  provisional while the structural contract is reviewable.
- **Callback-route rendering** was rejected for rendering (simplification loses
  source resolution/NaN gaps) and kept for proof/reconciliation.
- **Returning rich objects from savefig/print_png** was rejected: it breaks
  Matplotlib return-shape compatibility; the separate helper owns rich results.
- **Partial subtree Agg compositing** was rejected: public callbacks expose no
  reliable subtree boundary; only whole-frame fallback is safe.
- **Silent tolerance of non-PNG formats via base-class fallthrough** was
  rejected on research evidence of silent `%PDF-1.4` output.

## Consequences and residual risks

Positive (on acceptance): one auditable public surface for the first strict
slice; explicit unsupported/fallback behavior instead of silent degradation; a
generation-guarded publication model ready for later slices; no engine
dependency on Python or Matplotlib types.

Residual: single-line, linear-axis, solid-style, PNG-only coverage; miter-corner
parity with Agg unprovable for lack of a public getter (tolerance-based image
comparison by design); collector executes user artist code during preflight;
Agg fallback adds renderer/toolchain-dependent pixels and metadata; all support,
performance, platform, and version-range claims stay pending behind the
acceptance and evidence gates.

## Verification and evidence boundary

Acceptance changes documentation only: one new record. It adds no
product source, manifests, lockfiles, CI dependencies, wheels, workflows, or
publication settings, and edits no existing record. The workspace architecture
checker and unittest suite stayed green on the acceptance branch. Traceability rows for
full-v1 Matplotlib requirements remain `Not implemented`/`Not measured`/
`environment required`; acceptance here changes none of them.

## Related records

- [ADR index](../adr/README.md)
- [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](../adr/0002-gpu-native-engine-and-matplotlib-adapter.md)
- [ADR 0013 — hidden facade and private Python line/PNG helper](../adr/0013-hidden-facade-private-python-line-png.md)
- [ADR 0014 — Phase-3A2 pinned manylinux wheel evidence](../adr/0014-phase3a2-pinned-manylinux-wheel-evidence.md)
- [ADR 0015 — Phase-3B public Matplotlib adapter contract](../adr/0015-phase3b-public-matplotlib-adapter-contract.md)
- [API 0002 — errors, capabilities, and fallback](api-0002-errors-capabilities-fallback.md)
- [API 0003 — Phase-3A Python, NumPy, and private helper](api-0003-python-numpy-matplotlib.md)
- [Architecture overview](overview.md)
- [Open decisions — O-10](open-decisions.md)
- [v1 requirements](../requirements/lumenplot-v1.0.md)
- [Requirements traceability](../requirements/traceability-v1.0.md)
