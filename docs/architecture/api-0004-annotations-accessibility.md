# API 0004: Annotations and accessibility semantics

- Status: **Accepted contract; evidence pending**
- Date: 2026-08-21
- Decision owner: architecture-authority
- Recorded by: implementation-worker
- Scope: O-13 annotation identity, Plot/UI State, history, hit testing, keyboard interaction, focus, contrast, reduced motion, and accessibility tree
- Governing architecture: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](../adr/0002-gpu-native-engine-and-matplotlib-adapter.md)
- Open-decision records: [O-13 — Annotation and interaction history details](open-decisions.md#o-13-annotation-and-interaction-history-details), [O-14 — Accessibility and standalone viewer semantics](open-decisions.md#o-14-accessibility-and-standalone-viewer-semantics)

This record defines semantic annotation and accessibility behavior before UI implementation. It does not claim a viewer package, platform accessibility bridge, or persistent annotation format.

## Requirement references

The annotation and accessibility boundary covers `LP-FUNC-012`, `LP-UX-016` through `LP-UX-022`, `LP-UX-028` through `LP-UX-033`, `LP-QUAL-014` through `LP-QUAL-016`, and `LP-EXPORT-009` in the [requirements](../requirements/lumenplot-v1.0.md#25-keyboard-and-accessibility).

## Context

Annotations affect the plot and its exports, while focus, hover, selection, and drag chrome are transient UI state. Accessibility must preserve the same semantic action and revision outcome without requiring a color-only cue or an animation. The v1 view history is intentionally narrower than general Plot State undo/redo.

## Decision

### Annotation identity and state

`AnnotationId` is a stable process-local `u64` semantic identity. It is scoped to one Scene lifetime, is never reused within that lifetime, and excludes generation. It is not serialized.

Version 1 semantic annotation kinds are:

- text;
- line;
- arrow;
- rectangle.

Ellipse is an optional capability, not a v1 requirement. Every supported annotation retains its geometry space, explicit transform, clip, z-order, and style. The accepted geometry spaces are `Data2D`, `AxesLogical`, `FigureLogical`, and `DisplayLogical`. Hit testing is performed in the declared logical space after the explicit transform and clipping rules are applied.

Annotation add, edit, and delete are Plot State transactions. They are included in the selected ordinary export state and increment `SceneRevision`. Hover, selection, focus, and drag handles/chrome are UI State and are excluded from ordinary exports.

Annotation changes are not entries in v1 view-history Previous/Next undo/redo. View history remains limited to viewport gestures, Home, canonical-view replacement, gesture-end coalescing, and forward-tail truncation as specified by [API 0001](api-0001-native-scene-state.md). There is no persistence or save/load format for annotations.

### Keyboard and focus

Keyboard access is required for navigation, Home/canonical view, previous/next history, grid, cursor, series visibility, Legend operations, annotation operations, cancellation, and export. The semantic action must not depend on a permanent Pan, Zoom, or Box Zoom mode button.

Focus is visibly rendered, remains non-obscured, and moves through the plot and Legend controls. Focus order and keyboard actions are part of the same semantic interaction map on every supported host. Transient focus/UI state does not enter ordinary Plot State exports.

### Contrast and non-color cues

Default colors and states use the unrounded WCAG-derived acceptance baselines of:

- 4.5:1 for normal text;
- 3:1 for large text;
- 3:1 for non-text and focus indicators.

These are acceptance baselines, not a legal WCAG conformance claim. Styles, markers, labels, line patterns, and other cues supplement color so that semantic distinctions do not rely on color alone.

### Reduced motion

When reduced motion is requested, animated or interpolated view transitions are removed or made immediate while preserving the same semantic revision and operation outcome. Reduced motion must not silently disable navigation, history, canonical view, or other semantic actions.

### Semantic accessibility tree and platform bridge

A semantic accessibility tree and platform bridge are a v1 SHOULD. The tree describes the plot, axes, series, Legend, annotations, controls, current view, and keyboard-operable actions where the host platform permits it.

If the platform bridge is unavailable, the implementation emits a structured capability diagnostic. It never downgrades keyboard operation, visible focus, contrast-aware defaults, or reduced-motion behavior merely because the screen-reader bridge is unavailable. PDF tags and SVG `title`/`desc` output are separately capability-labeled and are not silently inferred from the interactive tree.

## Consequences

- Annotation identity remains stable across Scene revisions without creating a persistence contract.
- Plot State and UI State stay separate for history, accessibility, and export.
- Keyboard and visual accessibility remain available even where a platform tree bridge is not.
- Reduced motion changes presentation timing without changing semantic state or outcome.
- The viewer and adapter must expose explicit diagnostics for unavailable accessibility capabilities.

## Verification and evidence boundary

Required evidence includes annotation add/edit/delete and hit-testing fixtures, geometry-space transform/clip/z-order tests, revision and view-history tests, export inclusion/omission tests, keyboard/focus matrices, contrast fixtures, reduced-motion fixtures, accessibility-tree/bridge capability tests, and viewer lifecycle tests. This record reports none of those as complete.

## Residual risks

- Platform accessibility APIs differ and may limit the tree bridge without weakening the core interaction contract.
- Annotation coordinate transforms must remain consistent with the logical-unit rules in [ADR 0007](../adr/0007-coordinate-color-text-export.md).
- Future persistence requires a separate schema, trust, and migration decision.

## Related records

- [ADR index](../adr/README.md)
- [Architecture overview](overview.md)
- [API 0001 — native Scene state](api-0001-native-scene-state.md)
- [ADR 0007 — coordinate, color, text, and export](../adr/0007-coordinate-color-text-export.md)
- [ADR 0009 — publication and serialization guards](../adr/0009-version-publication-supply-chain.md)
- [O-13 open-decision entry](open-decisions.md#o-13-annotation-and-interaction-history-details)
- [O-14 open-decision entry](open-decisions.md#o-14-accessibility-and-standalone-viewer-semantics)
- [Accepted requirements: accessibility](../requirements/lumenplot-v1.0.md#25-keyboard-and-accessibility)
