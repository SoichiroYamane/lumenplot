//! M5 Slice-6 grid carry-only neutrality through the public bridge.
//!
//! Scope: public-observable carry-only neutrality ONLY. The grid flag is
//! Plot State carried by `SceneState` with a `pub(crate)` setter
//! transaction and no bridge exposure (Slice-1 non-goal, kept by Slices
//! 2-5), so no public transaction can stage it and no sink reads it yet.
//! What every downstream sink consumes through this surface is pinned here:
//!
//! - (a) a default scene resolves a frame whose layout digests
//!   deterministically across independent frames (carry-only default
//!   reproduces current rendering bit-for-bit);
//! - (b) the carried `plot_layout().layout_revision()` stays on its
//!   pre-grid baseline (one committed series stamps generation 1);
//! - (c) the generation gate frames rely on still fails closed after a
//!   scene change while the new frame validates;
//! - (d) no sink behavior changes: the frame still carries the fixture
//!   four annotations with identical series content and frame geometry.
//!
//! Live-state behavior the bridge cannot stage (set/clear round-trip,
//! snapshot exposure through the existing `Arc<SceneState>` wrapper, and
//! grid-only commits never advancing `layout_revision`) is pinned by the
//! engine unit tests in `src/scene/state.rs` and
//! `src/scene/transaction.rs`.

use lumenplot_engine::bridge::{
    AxisScale, AxisScales, LineFrame, LineFrameSpec, LineStyle, LogicalRect, LogicalSize,
    PlotScene, SeriesData, SeriesTopology, SrgbRgba8, Viewport,
};

/// Resolve one frame on a fresh scene with a two-point series.
///
/// Mirrors the `make_frame` helper in `annotation_slice1.rs`; the canvas
/// and plot cover the full 160x140 page so every fixture annotation lands
/// inside it.
fn make_frame(scene: &PlotScene, style: LineStyle) -> LineFrame {
    let canvas = LogicalSize::new(160.0, 140.0).expect("canvas");
    let plot = LogicalRect::new(8.0, 8.0, 56.0, 56.0).expect("plot");
    let frame_spec =
        LineFrameSpec::new(canvas, plot, 1.0, style, SrgbRgba8::new(255, 255, 255, 255))
            .expect("frame spec");
    scene
        .snapshot()
        .resolve_line_frame(&frame_spec)
        .expect("frame")
}

fn style() -> LineStyle {
    LineStyle::new(SrgbRgba8::new(20, 40, 80, 255), 1.0).expect("style")
}

fn scene_with_series() -> PlotScene {
    let view = Viewport::from_bounds(0.0, 10.0, 0.0, 10.0).expect("view");
    let mut scene =
        PlotScene::new(view, AxisScales::new(AxisScale::Linear, AxisScale::Linear)).expect("scene");
    let data =
        SeriesData::from_owned_xy(SeriesTopology::MonotonicX, vec![0.0, 10.0], vec![0.0, 0.0])
            .expect("series data");
    let mut transaction = scene.transaction();
    transaction.add_series(data).expect("add series");
    transaction.commit().expect("commit");
    scene
}

/// (a) Default frame digest unchanged: independent default scenes digest
/// identically, carry real content, and validate under generation (0, 1).
#[test]
fn default_frame_digest_is_deterministic_and_valid() {
    let first = make_frame(&scene_with_series(), style());
    let second = make_frame(&scene_with_series(), style());
    for frame in [&first, &second] {
        let layout = frame.plot_layout();
        assert!(layout.validate(), "carried layout must validate");
        assert_eq!(layout.font_revision(), 0);
        assert_eq!(layout.layout_revision(), 1);
        assert!(
            layout.validate_for_generation(layout.font_revision(), layout.layout_revision()),
            "carried layout must validate under its own generations"
        );
    }
    assert_eq!(
        first.plot_layout().layout_digest(),
        second.plot_layout().layout_digest(),
        "same scene content must digest identically"
    );
    assert_ne!(
        first.plot_layout().layout_digest(),
        [0u8; 32],
        "digest must carry real content"
    );
}

/// (b) `plot_layout().layout_revision()` unchanged: the one-series scene
/// still stamps exactly generation 1 with no grid read path anywhere.
#[test]
fn carried_layout_revision_stays_on_pre_grid_baseline() {
    let mut scene = scene_with_series();
    let frame = make_frame(&scene, style());
    assert_eq!(frame.plot_layout().layout_revision(), 1);
    assert_eq!(frame.plot_layout().font_revision(), 0);

    // A second data commit still advances scene and layout together.
    let data =
        SeriesData::from_owned_xy(SeriesTopology::MonotonicX, vec![0.0, 10.0], vec![0.0, 10.0])
            .expect("diagonal data");
    let mut transaction = scene.transaction();
    transaction.add_series(data).expect("add series");
    let receipt = transaction.commit().expect("commit");
    assert!(receipt.changed());
    let after = make_frame(&scene, style());
    assert!(after.revision() > frame.revision());
    assert_eq!(after.plot_layout().layout_revision(), 2);
}

/// (c) Generation gate holds: after a scene change the old layout is stale
/// under the new generations while the new frame validates.
#[test]
fn stale_carrier_fails_generation_gate_after_scene_change() {
    let mut scene = scene_with_series();
    let before = make_frame(&scene, style());
    let (font_before, layout_before) = {
        let layout = before.plot_layout();
        (layout.font_revision(), layout.layout_revision())
    };

    let data =
        SeriesData::from_owned_xy(SeriesTopology::MonotonicX, vec![0.0, 10.0], vec![0.0, 10.0])
            .expect("diagonal data");
    let mut transaction = scene.transaction();
    transaction.add_series(data).expect("add series");
    let receipt = transaction.commit().expect("commit");
    assert!(receipt.changed());

    let after = make_frame(&scene, style());
    assert!(after.revision() > before.revision());
    let (font_after, layout_after) = {
        let layout = after.plot_layout();
        (layout.font_revision(), layout.layout_revision())
    };
    assert!((font_after, layout_after) != (font_before, layout_before));
    assert!(
        !before
            .plot_layout()
            .validate_for_generation(font_after, layout_after),
        "pinned layout must fail under the new generations"
    );
    assert!(
        after
            .plot_layout()
            .validate_for_generation(font_after, layout_after),
        "new frame must validate under the new generations"
    );
}

/// (d) No sink behavior change: the frame still carries the fixture four
/// with identical series content and unchanged frame geometry.
#[test]
fn frame_content_and_geometry_match_pre_grid_behavior() {
    let scene = scene_with_series();
    let frame = make_frame(&scene, style());

    assert_eq!(frame.plot_layout().annotations().len(), 4);
    assert_eq!(frame.series().len(), 1);
    let points: Vec<(f64, f64)> = frame.series()[0]
        .segments()
        .iter()
        .flat_map(|segment| segment.points())
        .map(|point| (point.x(), point.y()))
        .collect();
    // Data (0..10, y = 0) maps through the viewport into the plot rect
    // (8,8)-(56,56) with the y axis flipped: x = 0 -> 8, x = 10 -> 56,
    // y = 0 -> 56.
    assert_eq!(points, vec![(8.0, 56.0), (56.0, 56.0)]);

    assert_eq!(frame.canvas().width(), 160.0);
    assert_eq!(frame.canvas().height(), 140.0);
    assert_eq!(frame.plot_rect().x_min(), 8.0);
    assert_eq!(frame.plot_rect().y_min(), 8.0);
    assert_eq!(frame.plot_rect().x_max(), 56.0);
    assert_eq!(frame.plot_rect().y_max(), 56.0);
    let background = frame.background();
    assert_eq!(
        (
            background.r(),
            background.g(),
            background.b(),
            background.a()
        ),
        (255, 255, 255, 255)
    );
}
