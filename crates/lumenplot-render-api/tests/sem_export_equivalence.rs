//! LP-PROD-003 engine-seam equivalence fixture (AT-SEM-LAYOUT + AT-EXPORT-STATE, partial).
//!
//! This is the authorized Phase-B closing slice for the shared
//! semantic/export equivalence gap: it proves the export-side engine
//! `LineFrame` and the render-api `FramePacket`/`SemanticFrame` carry equal
//! retained meaning when resolved from one deterministic scene under a pinned
//! matched spec. It closes the fixture gap only; it makes no closure claim
//! beyond this equivalence fixture and performs no traceability flip.
//!
//! How the two sides are built (mirrored deterministic construction):
//! `SceneHandle` owns its engine scene privately and exposes no snapshot, so
//! the test builds two scenes with identical deterministic sequences (same
//! linear viewport, same two finite MonotonicX series, one transaction commit
//! per series on each side). Side (i) resolves the engine `LineFrame` via
//! `SceneSnapshot::resolve_line_frame`; side (ii) resolves the render-api
//! `FramePacket` via `SceneHandle::resolve_frame` and validates it into a
//! `RenderPacket` to reach the shared `SemanticFrame` through the public
//! `RenderPacket::semantic_frame` accessor. The specs are pinned 1:1
//! (`FrameSpec` maps pixels onto logical units one-to-one at 1.0 lupi, so the
//! `LineFrameSpec` reuses the same numeric canvas/plot/style/background).
//!
//! Scope (commander Q2): linear-axis line-only plus the fixture `PlotLayout`
//! ONLY. The additive `fill_bar` and `three_d` paths are explicitly EXCLUDED
//! and are asserted `None` on the semantic frame at runtime below.
//!
//! Tick-carrier clause (commander Q1): adding tick vecs to `FramePacket` is a
//! schema decision and is DECLINED here, so the packet carries no tick vecs
//! by construction. Coverage is pinned instead by a re-derivation assertion:
//! the same snapshot plus spec resolves twice to byte-identical tick
//! carriers, which are non-empty and live in display space inside the canvas.
//! Per the `LineFrame::x_ticks` carrier contract in
//! `crates/lumenplot-engine/src/bridge.rs`, the carriers rebuild
//! deterministically from viewport, scales, plot geometry, and the per-axis
//! cap at resolve time, so `(grid_visible, grid_revision)` pair equality plus
//! scene-revision equality already covers them with no separate digest.
//!
//! Test home (commander Q3): this new integration file only; the `packet.rs`
//! test module is untouched. Digest helper (commander Q4): `digest_hex`
//! below, inline in this file; no helper on existing types.
//!
//! EXIT-1 boundary (see `crates/lumenplot-export/src/lib.rs`): export keeps
//! consuming the engine `LineFrame`; this fixture adds no export-to-render-api
//! edge and changes no public API, schema, signature, serde/wire identity,
//! checker constant, or threshold. No pixel comparison and no second sink.
//!
//! Transient/cursor/chrome absence is covered by reference, not duplicated:
//! `export_contains_no_transient_chrome` (AT-EXPORT-STATE negative) and
//! `cursor_and_crosshair_have_no_export_projection` (LP-EXPORT-010 negative)
//! in `crates/lumenplot-export/src/png.rs` pin the sink seam to
//! `(&LineFrame, &PngSpec)` only. Neither frame type below exposes hover,
//! selection, cursor, toolbar, or drag state (no such accessor exists), so the
//! equivalence asserted here cannot smuggle transient state.

use lumenplot_engine::bridge::{
    AxisScale, AxisScales, LineFrameSpec, LineStyle, LogicalRect, LogicalSize, PlotScene,
    SeriesData, SeriesTopology, SrgbRgba8, Viewport,
};
use lumenplot_render_api::__internal::{DeviceGeneration, RenderPacketBuilder, WorkGeneration};
use lumenplot_render_api::{FrameSpec, SceneHandle};

const CANVAS_PX: [u32; 2] = [160, 140];
const PLOT_RECT_PX: [u32; 4] = [8, 8, 56, 56];
const DOTS_PER_INCH: f64 = 96.0;
const LINE_WIDTH_PX: f64 = 1.5;
const LINE_COLOR: (u8, u8, u8, u8) = (31, 119, 180, 255);
const BACKGROUND: (u8, u8, u8, u8) = (255, 255, 255, 255);

/// Deterministic fixture series: two finite MonotonicX line series that stay
/// inside the 0..10 viewport, so every point lands inside the plot rect and
/// each series keeps one structural segment (no clip splits, no reconnection).
fn fixture_series() -> Vec<(Vec<f64>, Vec<f64>)> {
    vec![
        (
            vec![0.0, 2.0, 4.0, 6.0, 8.0, 10.0],
            vec![1.0, 3.0, 2.0, 5.0, 4.0, 6.0],
        ),
        (vec![0.0, 5.0, 10.0], vec![9.0, 7.0, 8.0]),
    ]
}

fn srgb(color: (u8, u8, u8, u8)) -> SrgbRgba8 {
    SrgbRgba8::new(color.0, color.1, color.2, color.3)
}

fn fixture_viewport() -> Viewport {
    Viewport::from_bounds(0.0, 10.0, 0.0, 10.0).expect("fixture viewport")
}

fn fixture_style() -> LineStyle {
    LineStyle::new(srgb(LINE_COLOR), LINE_WIDTH_PX).expect("fixture style")
}

/// Engine side of the mirrored scene: one transaction commit per series, the
/// same sequence `SceneHandle::add_series` performs internally.
fn build_engine_scene() -> PlotScene {
    let mut scene = PlotScene::new(
        fixture_viewport(),
        AxisScales::new(AxisScale::Linear, AxisScale::Linear),
    )
    .expect("fixture engine scene");
    for (xs, ys) in fixture_series() {
        let data = SeriesData::from_owned_xy(SeriesTopology::MonotonicX, xs, ys)
            .expect("fixture series data");
        let mut transaction = scene.transaction();
        transaction.add_series(data).expect("add series");
        transaction.commit().expect("commit");
    }
    scene
}

fn build_handle() -> SceneHandle {
    let mut handle = SceneHandle::new(fixture_viewport()).expect("fixture handle");
    for (xs, ys) in fixture_series() {
        handle.add_series(xs, ys).expect("add series");
    }
    handle
}

fn fixture_frame_spec() -> FrameSpec {
    FrameSpec::new(
        CANVAS_PX,
        PLOT_RECT_PX,
        DOTS_PER_INCH,
        srgb(LINE_COLOR),
        LINE_WIDTH_PX,
        srgb(BACKGROUND),
    )
    .expect("fixture frame spec")
}

fn fixture_line_spec() -> LineFrameSpec {
    let canvas =
        LogicalSize::new(f64::from(CANVAS_PX[0]), f64::from(CANVAS_PX[1])).expect("fixture canvas");
    let plot = LogicalRect::new(
        f64::from(PLOT_RECT_PX[0]),
        f64::from(PLOT_RECT_PX[1]),
        f64::from(PLOT_RECT_PX[2]),
        f64::from(PLOT_RECT_PX[3]),
    )
    .expect("fixture plot rect");
    LineFrameSpec::new(canvas, plot, 1.0, fixture_style(), srgb(BACKGROUND))
        .expect("fixture line spec")
}

/// Inline digest helper (commander Q4): hex for failure messages only. The
/// byte equality itself is asserted on `[u8; 32]` values directly.
fn digest_hex(digest: [u8; 32]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(64);
    for byte in digest {
        out.push(HEX[(byte >> 4) as usize] as char);
        out.push(HEX[(byte & 0x0f) as usize] as char);
    }
    out
}

#[test]
fn engine_seam_semantic_frame_matches_export_line_frame() {
    let engine_scene = build_engine_scene();
    let handle = build_handle();
    let line_spec = fixture_line_spec();
    let frame_spec = fixture_frame_spec();
    let snapshot = engine_scene.snapshot();

    // Side (i): export-side engine frame, resolved twice so the tick-carrier
    // re-derivation clause below compares two independent resolves.
    let line_frame = snapshot
        .resolve_line_frame(&line_spec)
        .expect("engine line frame");
    let line_frame_rerun = snapshot
        .resolve_line_frame(&line_spec)
        .expect("engine line frame rerun");

    // Side (ii): render-api packet, then the validated render packet that
    // carries the shared semantic frame.
    let frame_packet = handle.resolve_frame(&frame_spec).expect("frame packet");
    let builder = RenderPacketBuilder::new(WorkGeneration::initial(), DeviceGeneration::initial());
    let render_packet = builder
        .build(
            frame_packet.clone(),
            WorkGeneration::initial(),
            DeviceGeneration::initial(),
        )
        .expect("validated render packet");
    let packet = render_packet.frame();
    let semantic_layout = render_packet.semantic_frame().plot_layout();

    // (a) Revision equality: each frame carries its own scene's revision. The
    // tokens are opaque by design (no public inner accessor), so cross-type
    // comparison is not publicly observable; identical deterministic build
    // sequences put both scenes at the same generation, and within-type
    // carriage is asserted on both sides.
    assert_eq!(
        line_frame.revision(),
        snapshot.revision(),
        "engine frame must carry its snapshot revision"
    );
    assert_eq!(
        packet.revision(),
        handle.revision(),
        "render-api packet must carry its scene revision"
    );

    // (b) Canvas / plot rect / lupi / background equality under the pinned
    // matched spec. `LogicalSize`, `LogicalRect`, and `SrgbRgba8` expose no
    // `Debug`, so equality uses `assert!` with accessor-based messages.
    assert_eq!(packet.canvas_px(), CANVAS_PX, "canvas pixels must match");
    assert_eq!(
        packet.dots_per_inch(),
        DOTS_PER_INCH,
        "dpi provenance must match"
    );
    assert!(
        line_frame.canvas() == packet.canvas_logical(),
        "canvas logical must match: engine ({}, {}) vs packet ({}, {})",
        line_frame.canvas().width(),
        line_frame.canvas().height(),
        packet.canvas_logical().width(),
        packet.canvas_logical().height(),
    );
    assert!(
        line_frame.plot_rect() == packet.plot_rect(),
        "plot rect must match: engine ({}, {}, {}, {}) vs packet ({}, {}, {}, {})",
        line_frame.plot_rect().x_min(),
        line_frame.plot_rect().y_min(),
        line_frame.plot_rect().x_max(),
        line_frame.plot_rect().y_max(),
        packet.plot_rect().x_min(),
        packet.plot_rect().y_min(),
        packet.plot_rect().x_max(),
        packet.plot_rect().y_max(),
    );
    assert_eq!(
        line_frame.logical_units_per_inch(),
        packet.logical_units_per_inch(),
        "logical units per inch must match"
    );
    assert_eq!(
        line_frame.logical_units_per_inch(),
        1.0,
        "matched spec pins 1.0 lupi"
    );
    assert!(
        line_frame.background() == packet.background(),
        "background must match: engine ({}, {}, {}, {}) vs packet ({}, {}, {}, {})",
        line_frame.background().r(),
        line_frame.background().g(),
        line_frame.background().b(),
        line_frame.background().a(),
        packet.background().r(),
        packet.background().g(),
        packet.background().b(),
        packet.background().a(),
    );
    assert_eq!(
        packet.line_width_px(),
        LINE_WIDTH_PX,
        "line width must ride the matched spec"
    );

    // (c) Series count / order / length plus exact f64 point equality per
    // structural segment. Comparison is per segment, never flattened, so gap
    // boundaries (structural segmentation, no reconnection) are preserved by
    // the shape of the assertion. The `SceneHandle` seam admits finite
    // MonotonicX input only, so the fixture carries two finite series (6 + 3
    // points, one structural segment each); NaN-gap construction through
    // explicit valid segments stays engine-only and out of this slice.
    let line_series = line_frame.series();
    let packet_series = packet.series();
    assert_eq!(
        packet_series.len(),
        line_series.len(),
        "series count must match"
    );
    assert_eq!(packet_series.len(), 2, "fixture carries two series");
    for (index, (line, packet)) in line_series.iter().zip(packet_series.iter()).enumerate() {
        assert_eq!(
            packet.segments().len(),
            line.segments().len(),
            "series {index} segment count must match"
        );
        for (segment_index, (line_segment, packet_segment)) in line
            .segments()
            .iter()
            .zip(packet.segments().iter())
            .enumerate()
        {
            assert_eq!(
                packet_segment.points().len(),
                line_segment.points().len(),
                "series {index} segment {segment_index} length must match"
            );
            for (point_index, (line_point, packet_point)) in line_segment
                .points()
                .iter()
                .zip(packet_segment.points().iter())
                .enumerate()
            {
                assert_eq!(
                    packet_point.x(),
                    line_point.x(),
                    "series {index} segment {segment_index} point {point_index} x must match exactly"
                );
                assert_eq!(
                    packet_point.y(),
                    line_point.y(),
                    "series {index} segment {segment_index} point {point_index} y must match exactly"
                );
            }
        }
    }
    let packet_points: usize = packet_series
        .iter()
        .map(|series| {
            series
                .segments()
                .iter()
                .map(|segment| segment.points().len())
                .sum::<usize>()
        })
        .sum();
    assert_eq!(packet_points, 9, "fixture carries 6 + 3 points");

    // (d) Shared layout: digest byte equality plus font/layout revision
    // equality plus generation-gated validation passing on both carriers.
    let line_layout = line_frame.plot_layout();
    assert_eq!(
        semantic_layout.layout_digest(),
        line_layout.layout_digest(),
        "layout digest must match (packet {} vs engine {})",
        digest_hex(semantic_layout.layout_digest()),
        digest_hex(line_layout.layout_digest()),
    );
    assert_ne!(
        line_layout.layout_digest(),
        [0u8; 32],
        "digest must carry real content"
    );
    assert_eq!(
        semantic_layout.font_revision(),
        line_layout.font_revision(),
        "font revision must match"
    );
    assert_eq!(
        semantic_layout.layout_revision(),
        line_layout.layout_revision(),
        "layout revision must match"
    );
    assert!(
        line_layout
            .validate_for_generation(line_layout.font_revision(), line_layout.layout_revision()),
        "engine layout must validate under its own generations"
    );
    assert!(
        semantic_layout.validate_for_generation(
            semantic_layout.font_revision(),
            semantic_layout.layout_revision()
        ),
        "packet layout must validate under its own generations"
    );

    // (e) Grid pair equality: the carried Plot State pair rides both frames.
    assert_eq!(
        packet.grid_visible(),
        line_frame.grid_visible(),
        "grid visibility must match"
    );
    assert_eq!(
        packet.grid_revision(),
        line_frame.grid_revision(),
        "grid revision must match"
    );

    // (f) Tick-carrier clause (commander Q1): the packet carries no tick vecs
    // by schema decision, so coverage is pinned by re-derivation determinism
    // on the engine carriers plus the (a)/(e) pair-and-revision equality. The
    // rerun resolve must reproduce both carriers exactly; they must be
    // non-empty (non-vacuous) display-space positions inside the canvas.
    assert_eq!(
        line_frame_rerun.x_ticks(),
        line_frame.x_ticks(),
        "x tick carriers must re-derive exactly"
    );
    assert_eq!(
        line_frame_rerun.y_ticks(),
        line_frame.y_ticks(),
        "y tick carriers must re-derive exactly"
    );
    assert!(
        !line_frame.x_ticks().is_empty() && !line_frame.y_ticks().is_empty(),
        "tick carriers must be non-empty on the 0..10 fixture viewport"
    );
    for tick in line_frame.x_ticks() {
        assert!(
            (0.0..=f64::from(CANVAS_PX[0])).contains(tick),
            "x tick {tick} must sit in display space inside the canvas"
        );
    }
    for tick in line_frame.y_ticks() {
        assert!(
            (0.0..=f64::from(CANVAS_PX[1])).contains(tick),
            "y tick {tick} must sit in display space inside the canvas"
        );
    }

    // (g) Transient / cursor / chrome absence holds by reference: the export
    // negatives cited in the module header pin the sink seam to retained
    // state only, and neither `LineFrame` nor `FramePacket`/`SemanticFrame`
    // exposes hover, selection, cursor, toolbar, or drag accessors, so the
    // equality above cannot smuggle transient state. The Q2 exclusion is
    // pinned at runtime here: no additive 3D or fill/bar meaning rides this
    // line-only fixture.
    assert!(
        render_packet.semantic_frame().three_d().is_none(),
        "line-only fixture carries no 3D meaning (Q2 exclusion)"
    );
    assert!(
        render_packet.semantic_frame().fill_bar().is_none(),
        "line-only fixture carries no fill/bar meaning (Q2 exclusion)"
    );
}
