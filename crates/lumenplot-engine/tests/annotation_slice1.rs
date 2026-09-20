//! M5-ANNOT Slice-1 mirror-selection fallback through the public bridge.
//!
//! Scope: the empty-live-map branch of the frame mirror only. Live Plot
//! State cannot be staged through the public bridge (annotation
//! transactions stay `pub(crate)` with no bridge exposure by Slice-1
//! non-goal), so the live-rectangle branch is pinned by the engine unit
//! tests in `src/scene/annotation_slice.rs`. What every downstream sink
//! consumes through this surface is pinned here:
//!
//! - (a) an empty live map resolves a frame carrying exactly the fixture
//!   four annotations, in order, with exact fixture spaces and bounds;
//! - (b) the carried layout validates, stamps generation (0, 0), and
//!   digests deterministically across independent frames;
//! - (c) the generation gate the mirror relies on fails closed: after a
//!   scene change, the old layout no longer validates under the new
//!   generations while the new frame does.

use lumenplot_engine::bridge::{
    AnnotationShape, AnnotationSpace, AxisScale, AxisScales, LineFrame, LineFrameSpec, LineStyle,
    LogicalRect, LogicalSize, PlotScene, SeriesData, SeriesTopology, SrgbRgba8, Viewport,
};

/// Resolve one frame on a fresh scene with a two-point series.
///
/// Mirrors the `make_frame` helper in `text_layout_units.rs`; the canvas
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

/// (a) Empty live map: the frame carries exactly the fixture four.
#[test]
fn empty_live_map_carries_fixture_four_in_order() {
    let scene = scene_with_series();
    let frame = make_frame(&scene, style());
    let annotations = frame.plot_layout().annotations();
    assert_eq!(annotations.len(), 4);

    // Kinds in fixture layout order: text, line, arrow, rectangle.
    assert!(matches!(
        annotations[0].shape(),
        AnnotationShape::Text {
            x: 10.0,
            y: 20.0,
            half_width: 12.0,
            half_height: 4.0,
        }
    ));
    assert!(matches!(
        annotations[1].shape(),
        AnnotationShape::Line {
            x1: 0.0,
            y1: 0.0,
            x2: 64.0,
            y2: 32.0,
        }
    ));
    assert!(matches!(
        annotations[2].shape(),
        AnnotationShape::Arrow {
            x1: 8.0,
            y1: 8.0,
            x2: 40.0,
            y2: 24.0,
            head_length: 6.0,
        }
    ));
    assert!(matches!(
        annotations[3].shape(),
        AnnotationShape::Rectangle {
            x_min: 100.0,
            y_min: 100.0,
            x_max: 140.0,
            y_max: 120.0,
        }
    ));

    // One distinct declared space per kind, fixture order.
    let spaces: Vec<AnnotationSpace> = annotations
        .iter()
        .map(|annotation| annotation.space())
        .collect();
    assert_eq!(
        spaces,
        vec![
            AnnotationSpace::Data2D,
            AnnotationSpace::AxesLogical,
            AnnotationSpace::FigureLogical,
            AnnotationSpace::DisplayLogical,
        ]
    );

    // Stored coarse boxes resolved once at construction.
    let bounds: Vec<(f64, f64, f64, f64)> = annotations
        .iter()
        .map(|annotation| annotation.bounds())
        .collect();
    assert_eq!(
        bounds,
        vec![
            (-2.0, 16.0, 22.0, 24.0),
            (0.0, 0.0, 64.0, 32.0),
            (2.0, 2.0, 46.0, 30.0),
            (100.0, 100.0, 140.0, 120.0),
        ]
    );
}

/// (b) The carried layout validates, stamps (0, 0), and digests
/// deterministically across independent frames.
#[test]
fn carried_layout_validates_and_digests_deterministically() {
    let first = make_frame(&scene_with_series(), style());
    let second = make_frame(&scene_with_series(), style());
    for frame in [&first, &second] {
        let layout = frame.plot_layout();
        assert!(layout.validate(), "carried layout must validate");
        assert_eq!(layout.font_revision(), 0);
        // One committed series advances the layout generation exactly once.
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

/// (c) Generation gate: after a scene change the old layout is stale
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
    // The fallback still carries the fixture four after the change.
    assert_eq!(after.plot_layout().annotations().len(), 4);
}
