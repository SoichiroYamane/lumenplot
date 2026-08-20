# ADR 0007: Coordinate, color, text, and export semantics

- Status: **Accepted contract; dependency choices staged**
- Date: 2026-08-21
- Decision owner: architecture-authority
- Recorded by: implementation-worker
- Scope: O-11 coordinate/unit/color/alpha/ICC policy and O-12 retained layout, fonts, text modes, and export semantics
- Governing architecture: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md)
- Open-decision records: [O-11 — Coordinate, unit, color, alpha, and ICC policy](../architecture/open-decisions.md#o-11-coordinate-unit-color-alpha-and-icc-policy), [O-12 — Text, font fallback, and reproducibility strictness](../architecture/open-decisions.md#o-12-text-font-fallback-and-reproducibility-strictness)

This ADR records abstract semantic and export boundaries. It does not select a dependency pin, claim a completed text stack, or report PNG/PDF/SVG output evidence.

## Requirement references

The semantic and output boundary covers `LP-DATA-001`, `LP-DATA-008`, `LP-DATA-009`, `LP-RENDER-003` through `LP-RENDER-005`, `LP-RENDER-010`, `LP-TEXT-001` through `LP-TEXT-007`, and `LP-EXPORT-001` through `LP-EXPORT-009` in the [requirements](../requirements/lumenplot-v1.0.md#14-text).

## Context

Interactive rendering and export must share semantic/layout meaning without assuming a universal display DPI, backend-specific y direction, or device-dependent color behavior. Text must be shaped once and retained with enough provenance for deterministic output, while system fallback and licensing remain explicit.

## Decision

### Abstract logical units and transforms

Semantic/layout geometry, including glyph positions, is finite f64. Internal `DisplayLogical` coordinates use a top-left origin with x increasing rightward and y increasing downward. Every frame carries an explicit `logical_units_per_inch`; there is no universal 96-DPI identity assumption.

- The Matplotlib adapter maps its display coordinates once and records the renderer DPI.
- A native viewer selects an explicit display scale; 96 logical units per inch is a default, not an identity rule.
- PDF conversion is the sole sink that converts `pt = logical * 72 / logical_units_per_inch` and applies the bottom-left/y-up transform.
- Raster dimensions use checked `ceil(logical * DeviceScale)`. Geometry remains fractional until the sink; when snapping is required, ties use deterministic round-half-to-even.
- GPU narrowing occurs only at a sink-local origin-relative f32 boundary. Absolute scientific f64 values are never directly narrowed for drawing.

The semantic frame and retained PlotLayout use the abstract logical geometry; no renderer independently changes units or remeasures layout.

### Color, alpha, and compositing

Version 1 semantic `Color` is finite encoded-sRGB straight RGBA. The rendering boundary performs one conversion to premultiplied linear-sRGB for source-over compositing. The PNG boundary encodes straight sRGB again.

- Transparent RGB canonicalizes to zero.
- PNG emits explicit sRGB metadata and no ICC profile by default.
- An optional ICC profile must be explicit and digest-identified.
- The PDF baseline documents sRGB/DeviceRGB semantics.
- PDF ICC OutputIntent is optional and capability-labeled; no unqualified print-color claim is made.

Byte identity across displays and drivers is not the semantic contract; transform and compositing rules are.

### Clipping

Clip is an ordered transformed intersection stack with an explicit fill rule and explicit scope. A sink applies the stack in order after the declared transforms. Clipping is part of the resolved semantic/layout meaning and must be retained for supported output paths.

### Retained PlotLayout and font identity

`PlotLayout`/semantic-frame state retains:

- finite f64 geometry;
- one shaping result;
- source text and clusters;
- glyph IDs and positions;
- exact font-byte SHA-256, face index, normalized variation, feature, script, language, and direction information;
- clip and style references;
- the resolved fallback route.

Interactive rendering, PNG, PDF, and SVG consume this result. Renderer/export sinks never remeasure text, Legend geometry, or another layout object.

Deterministic export requires exact font bytes plus license/EULA, `fsType`, and provenance evidence. System fallback is interactive-only unless captured as an exact-byte snapshot. Outline conversion alone is not presumed license-safe. Missing glyphs produce a diagnostic plus a deterministic `.notdef` outline or a strict error; a silent blank is prohibited. TeX is an explicit fallback or unsupported capability.

### Text and PDF modes

Searchable PDF requires valid embedding/subsetting, widths, `ToUnicode`, and `ActualText` evidence. If that evidence is unavailable, the same shaped run becomes a deterministic vector outline, or a `StrictSearchable` mode fails explicitly. Raster-only text and raster screenshots as the final PDF representation for supported vector semantics are prohibited.

For the initial Matplotlib PNG slice, documented `TextToPath` supplies one resolved vector outline at the adapter boundary. That is not native font ownership. Native Parley/Fontique/HarfRust/Skrifa choices and PDF writer/subsetter choices require a deterministic font/license/consumer spike before Phase-2 dependency integration.

`tiny-skia` may be considered only as a deterministic CPU PNG export/reference sink after the accepted linear-compositing and color spike. It is not the engine or backend architecture.

A layout digest may identify the internal canonical layout bytes and version for reproducibility. It is non-public and non-persistent; it is not a Scene or RenderPacket identity.

### Shared output meaning

The same resolved semantic/layout frame feeds the interactive renderer, PNG semantic raster path, PDF vector/text path, and SVG vector path. PNG and PDF are v1 MUST outputs; SVG is a v1 SHOULD and non-blocking. Supported vector primitives retain vector meaning, and any explicitly allowed raster segment reports its scope and reason through the fallback diagnostic boundary.

## Alternatives and rationale

A renderer-local unit or text measurement path would make interactive and exported geometry diverge. A universal 96-DPI identity or implicit ICC behavior would turn a host/display convention into a false semantic guarantee. The selected abstract logical frame leaves sink-specific conversion explicit while retaining deterministic geometry and color rules.

## Consequences

- Coordinate and color behavior is testable across sinks without requiring byte-identical pixels.
- Text can be shared across display and export without renderer remeasurement.
- Deterministic output requires font bytes and license/provenance evidence.
- Dependency selection is staged behind real consumer and color-compositing spikes.
- PDF remains vector/searchable when evidence supports it and fails or outlines explicitly otherwise.

## Verification and evidence boundary

Required evidence includes coordinate transform and snapping fixtures, logical/physical/HiDPI matrices, sRGB/linear-compositing and transparency tests, clip-stack tests, shared layout digest tests, font hash/license fixtures, searchable PDF/outline tests, missing-glyph diagnostics, and initial TextToPath PNG fixtures. No output or dependency result is claimed by this ADR.

## Residual risks

- Font licenses and platform fallback can constrain deterministic export more than geometry does.
- ICC and PDF consumer behavior require capability-labeled tests rather than broad print-color claims.
- The staged text and PNG sink spikes may reject an initial candidate dependency without changing this semantic boundary.

## Related records

- [ADR index](README.md)
- [Architecture overview](../architecture/overview.md)
- [API 0003 — Python, NumPy, and Matplotlib](../architecture/api-0003-python-numpy-matplotlib.md)
- [ADR 0004 — RenderPacket resource lifecycle](0004-renderpacket-resource-lifecycle.md)
- [API 0004 — annotations and accessibility](../architecture/api-0004-annotations-accessibility.md)
- [O-11 open-decision entry](../architecture/open-decisions.md#o-11-coordinate-unit-color-alpha-and-icc-policy)
- [O-12 open-decision entry](../architecture/open-decisions.md#o-12-text-font-fallback-and-reproducibility-strictness)
- [Accepted requirements: text](../requirements/lumenplot-v1.0.md#14-text)
