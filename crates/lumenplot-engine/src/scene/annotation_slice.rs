//! Live Data2D rect/text/line/arrow mirror (M5-ANNOT Slices 1-3).
//!
//! The scene keeps two annotation homes: the live Plot State map on
//! [`SceneState`](super::state::SceneState), mutated by annotation
//! transactions, and the retained [`PlotLayout`](crate::text::PlotLayout)
//! carrier that frames and sinks read. `SceneState::publish` never copies
//! the live map into the carrier; it only re-stamps the carrier revision on
//! data/view change. This module closes that link for exactly four kinds:
//! identity-transform rectangles, text boxes, lines, and arrows declared in
//! [`Data2D`](crate::text::AnnotationSpace::Data2D).
//!
//! [`live_rectangle_layout`] filters the live map in deterministic identity
//! order and [`PlotLayout::from_live_parts`](crate::text::PlotLayout::from_live_parts)
//! rebuilds the carrier from the fixture runs plus that filtered set, so the
//! frame path carries live rectangles, text boxes, lines, and arrows without
//! duplicating the validate, digest, z-order, tie-break, or generation-gate
//! logic already pinned on the carrier. [`hit_live_rectangle`] maps one
//! display query through the existing frame inverse into `Data2D`, then
//! delegates to the mirrored carrier's
//! [`hit_annotation`](crate::text::PlotLayout::hit_annotation).
//!
//! Slice bounds: all four kinds stay in Plot State (and in the
//! accessibility projection) and every Data2D identity one is mirrored;
//! non-`Data2D` spaces and non-identity transforms are skipped by the filter
//! and rejected by the constructor. The mirrored carrier is stamped with the resolving
//! snapshot's font/layout revisions, and annotation-only commits never
//! advance `layout_revision`, so a mirror stays generation-valid until a
//! data/view change re-stamps the carrier.

use super::snapshot::SceneSnapshot;
use super::state::SceneState;
use crate::error::{SceneError, SceneErrorKind};
use crate::frame::ResolvedLayout;
use crate::text::{
    AnnotationHit, AnnotationKind, AnnotationSpace, AnnotationTransform, MAX_RETAINED_ANNOTATIONS,
    PlotLayout, RetainedAnnotation,
};

/// Filters the live annotation map down to the Slice-3 mirror set.
///
/// Returns `None` when the live map holds nothing, in which case frame
/// resolution keeps carrying the fixture annotations unchanged. Otherwise
/// returns the identity-transform `Data2D` rectangles, text boxes, lines,
/// and arrows in deterministic [`AnnotationId`](super::state::AnnotationId) order,
/// including the empty set when live annotations exist but none qualify, so
/// the frame then carries the fixture runs with zero annotations instead of
/// the fixture four. Counts are reserved before collection and the retained
/// capacity ceiling is enforced before allocation, mirroring the carrier
/// rules.
pub(crate) fn live_rectangle_layout(
    state: &SceneState,
) -> Result<Option<Vec<RetainedAnnotation>>, SceneError> {
    let stored = state.annotations_map();
    if stored.is_empty() {
        return Ok(None);
    }
    let mut mirrored = Vec::new();
    mirrored
        .try_reserve(stored.len())
        .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
    for annotation in stored.values() {
        if annotation.kind() != AnnotationKind::Rectangle
            && annotation.kind() != AnnotationKind::Text
            && annotation.kind() != AnnotationKind::Line
            && annotation.kind() != AnnotationKind::Arrow
        {
            continue;
        }
        if annotation.space() != AnnotationSpace::Data2D {
            continue;
        }
        if annotation.transform() != AnnotationTransform::identity() {
            continue;
        }
        mirrored.push(*annotation);
    }
    if mirrored.len() > MAX_RETAINED_ANNOTATIONS {
        return Err(SceneError::new(SceneErrorKind::CapacityExceeded));
    }
    Ok(Some(mirrored))
}

/// Resolves one display query against the mirrored rect/text carrier.
///
/// The query travels display into `Data2D` through the existing frame
/// inverse, then reads the mirrored `layout` through its own
/// generation-gated hit path. Non-finite display input fails with
/// `InvalidInput` at the inverse; a carrier whose revisions no longer match
/// `snapshot` fails with `Internal` instead of reporting against moved
/// geometry. This is a read path: it never mutates scene, layout,
/// visibility, or transient state.
pub(crate) fn hit_live_rectangle(
    layout: &PlotLayout,
    snapshot: &SceneSnapshot,
    resolved: &ResolvedLayout,
    display_x: f64,
    display_y: f64,
) -> Result<Option<AnnotationHit>, SceneError> {
    let (x, y) = resolved.inverse_point(display_x, display_y)?;
    layout.hit_annotation(
        AnnotationSpace::Data2D,
        x,
        y,
        snapshot.font_revision(),
        snapshot.layout_revision(),
    )
}

#[cfg(test)]
mod tests {
    use super::super::revision::SceneRevision;
    use super::super::snapshot::{A11yNodeKind, A11yUiState};
    use super::super::state::{AxisScale, AxisScales, PlotScene, Viewport};
    use super::*;
    use crate::bridge::{LineFrameSpec, LineStyle, LogicalRect, LogicalSize, SrgbRgba8};
    use crate::text::AnnotationShape;

    fn scene() -> PlotScene {
        PlotScene::new(
            Viewport::from_bounds(0.0, 10.0, 0.0, 10.0).expect("view"),
            AxisScales::new(AxisScale::Linear, AxisScale::Linear),
        )
        .expect("scene")
    }

    fn rect_shape(x_min: f64, y_min: f64, x_max: f64, y_max: f64) -> AnnotationShape {
        AnnotationShape::Rectangle {
            x_min,
            y_min,
            x_max,
            y_max,
        }
    }

    fn add_rect(
        plot: &mut PlotScene,
        space: AnnotationSpace,
        shape: AnnotationShape,
        z_order: i32,
    ) -> u64 {
        let mut transaction = plot.transaction();
        let id = transaction
            .add_annotation(space, shape, 1, 1, z_order)
            .expect("add annotation");
        let receipt = transaction.commit().expect("commit");
        assert!(receipt.changed());
        id.0
    }

    fn text_shape(x: f64, y: f64) -> AnnotationShape {
        AnnotationShape::Text {
            x,
            y,
            half_width: 1.0,
            half_height: 1.0,
        }
    }

    fn add_text(plot: &mut PlotScene, space: AnnotationSpace, x: f64, y: f64, z_order: i32) -> u64 {
        let mut transaction = plot.transaction();
        let id = transaction
            .add_annotation(space, text_shape(x, y), 1, 1, z_order)
            .expect("add annotation");
        let receipt = transaction.commit().expect("commit");
        assert!(receipt.changed());
        id.0
    }

    fn line_shape(x1: f64, y1: f64, x2: f64, y2: f64) -> AnnotationShape {
        AnnotationShape::Line { x1, y1, x2, y2 }
    }

    fn arrow_shape(x1: f64, y1: f64, x2: f64, y2: f64) -> AnnotationShape {
        AnnotationShape::Arrow {
            x1,
            y1,
            x2,
            y2,
            head_length: 1.0,
        }
    }

    fn add_line(
        plot: &mut PlotScene,
        space: AnnotationSpace,
        x1: f64,
        y1: f64,
        x2: f64,
        y2: f64,
        z_order: i32,
    ) -> u64 {
        let mut transaction = plot.transaction();
        let id = transaction
            .add_annotation(space, line_shape(x1, y1, x2, y2), 1, 1, z_order)
            .expect("add annotation");
        let receipt = transaction.commit().expect("commit");
        assert!(receipt.changed());
        id.0
    }

    fn add_arrow(
        plot: &mut PlotScene,
        space: AnnotationSpace,
        x1: f64,
        y1: f64,
        x2: f64,
        y2: f64,
        z_order: i32,
    ) -> u64 {
        let mut transaction = plot.transaction();
        let id = transaction
            .add_annotation(space, arrow_shape(x1, y1, x2, y2), 1, 1, z_order)
            .expect("add annotation");
        let receipt = transaction.commit().expect("commit");
        assert!(receipt.changed());
        id.0
    }

    fn frame_spec() -> LineFrameSpec {
        LineFrameSpec::new(
            LogicalSize::new(100.0, 100.0).expect("canvas"),
            LogicalRect::new(0.0, 0.0, 100.0, 100.0).expect("plot"),
            1.0,
            LineStyle::new(SrgbRgba8::new(20, 40, 80, 255), 1.0).expect("style"),
            SrgbRgba8::new(255, 255, 255, 255),
        )
        .expect("frame spec")
    }

    fn resolved_for(snapshot: &SceneSnapshot) -> ResolvedLayout {
        let canvas = LogicalSize::new(100.0, 100.0).expect("canvas");
        let plot = LogicalRect::new(0.0, 0.0, 100.0, 100.0).expect("plot");
        ResolvedLayout::new(canvas, plot, 1.0, snapshot.viewport()).expect("resolved layout")
    }

    #[test]
    fn empty_live_map_selects_fixture() {
        let plot = scene();
        let snapshot = plot.snapshot();
        assert!(
            live_rectangle_layout(&snapshot.state)
                .expect("filter")
                .is_none()
        );
        let frame = crate::frame::resolve_line_frame(&snapshot, &frame_spec()).expect("frame");
        assert_eq!(frame.plot_layout().annotations().len(), 4);
    }

    #[test]
    fn live_data2d_rectangle_is_mirrored_in_id_order() {
        let mut plot = scene();
        let first = add_rect(
            &mut plot,
            AnnotationSpace::Data2D,
            rect_shape(5.0, 5.0, 8.0, 7.0),
            0,
        );
        let second = add_rect(
            &mut plot,
            AnnotationSpace::Data2D,
            rect_shape(1.0, 1.0, 4.0, 3.0),
            0,
        );
        assert_eq!((first, second), (1, 2));
        assert_eq!(plot.revision(), SceneRevision(2));
        assert_eq!(plot.state.annotation_revision().0, 2);
        // Annotation-only commits never advance the layout generation.
        assert_eq!(plot.state.layout_revision().0, 0);

        let snapshot = plot.snapshot();
        let mirrored = live_rectangle_layout(&snapshot.state)
            .expect("filter")
            .expect("live map is non-empty");
        assert_eq!(mirrored.len(), 2);
        // BTree identity order, independent of insertion order.
        assert_eq!(mirrored[0].id(), first);
        assert_eq!(mirrored[1].id(), second);

        let frame = crate::frame::resolve_line_frame(&snapshot, &frame_spec()).expect("frame");
        let carried = frame.plot_layout().annotations();
        assert_eq!(carried.len(), 2);
        assert_eq!(carried[0].id(), first);
        assert_eq!(carried[1].id(), second);
        assert!(frame.plot_layout().validate());
        assert!(
            frame
                .plot_layout()
                .validate_for_generation(snapshot.font_revision(), snapshot.layout_revision())
        );
    }

    #[test]
    fn live_data2d_text_is_mirrored_in_id_order() {
        let mut plot = scene();
        let first = add_text(&mut plot, AnnotationSpace::Data2D, 5.0, 5.0, 0);
        let second = add_text(&mut plot, AnnotationSpace::Data2D, 2.0, 2.0, 0);
        assert_eq!((first, second), (1, 2));
        // Annotation-only commits never advance the layout generation.
        assert_eq!(plot.state.layout_revision().0, 0);

        let snapshot = plot.snapshot();
        let mirrored = live_rectangle_layout(&snapshot.state)
            .expect("filter")
            .expect("live map is non-empty");
        assert_eq!(mirrored.len(), 2);
        // BTree identity order, independent of insertion order.
        assert_eq!(mirrored[0].id(), first);
        assert_eq!(mirrored[1].id(), second);
        assert!(
            mirrored
                .iter()
                .all(|annotation| annotation.kind() == AnnotationKind::Text)
        );

        let frame = crate::frame::resolve_line_frame(&snapshot, &frame_spec()).expect("frame");
        let carried = frame.plot_layout().annotations();
        assert_eq!(carried.len(), 2);
        assert_eq!(carried[0].id(), first);
        assert_eq!(carried[1].id(), second);
        assert!(frame.plot_layout().validate());
        assert!(
            frame
                .plot_layout()
                .validate_for_generation(snapshot.font_revision(), snapshot.layout_revision())
        );
    }

    #[test]
    fn live_data2d_line_is_mirrored_in_id_order() {
        let mut plot = scene();
        let first = add_line(&mut plot, AnnotationSpace::Data2D, 5.0, 5.0, 8.0, 7.0, 0);
        let second = add_line(&mut plot, AnnotationSpace::Data2D, 1.0, 1.0, 4.0, 3.0, 0);
        assert_eq!((first, second), (1, 2));
        // Annotation-only commits never advance the layout generation.
        assert_eq!(plot.state.layout_revision().0, 0);

        let snapshot = plot.snapshot();
        let mirrored = live_rectangle_layout(&snapshot.state)
            .expect("filter")
            .expect("live map is non-empty");
        assert_eq!(mirrored.len(), 2);
        // BTree identity order, independent of insertion order.
        assert_eq!(mirrored[0].id(), first);
        assert_eq!(mirrored[1].id(), second);
        assert!(
            mirrored
                .iter()
                .all(|annotation| annotation.kind() == AnnotationKind::Line)
        );

        let frame = crate::frame::resolve_line_frame(&snapshot, &frame_spec()).expect("frame");
        let carried = frame.plot_layout().annotations();
        assert_eq!(carried.len(), 2);
        assert_eq!(carried[0].id(), first);
        assert_eq!(carried[1].id(), second);
        assert!(frame.plot_layout().validate());
        assert!(
            frame
                .plot_layout()
                .validate_for_generation(snapshot.font_revision(), snapshot.layout_revision())
        );
    }

    #[test]
    fn live_data2d_arrow_is_mirrored_in_id_order() {
        let mut plot = scene();
        let first = add_arrow(&mut plot, AnnotationSpace::Data2D, 5.0, 5.0, 8.0, 7.0, 0);
        let second = add_arrow(&mut plot, AnnotationSpace::Data2D, 1.0, 1.0, 4.0, 3.0, 0);
        assert_eq!((first, second), (1, 2));
        // Annotation-only commits never advance the layout generation.
        assert_eq!(plot.state.layout_revision().0, 0);

        let snapshot = plot.snapshot();
        let mirrored = live_rectangle_layout(&snapshot.state)
            .expect("filter")
            .expect("live map is non-empty");
        assert_eq!(mirrored.len(), 2);
        // BTree identity order, independent of insertion order.
        assert_eq!(mirrored[0].id(), first);
        assert_eq!(mirrored[1].id(), second);
        assert!(
            mirrored
                .iter()
                .all(|annotation| annotation.kind() == AnnotationKind::Arrow)
        );

        let frame = crate::frame::resolve_line_frame(&snapshot, &frame_spec()).expect("frame");
        let carried = frame.plot_layout().annotations();
        assert_eq!(carried.len(), 2);
        assert_eq!(carried[0].id(), first);
        assert_eq!(carried[1].id(), second);
        assert!(frame.plot_layout().validate());
        assert!(
            frame
                .plot_layout()
                .validate_for_generation(snapshot.font_revision(), snapshot.layout_revision())
        );
    }

    #[test]
    fn mixed_rect_and_text_mirror_together_in_id_order() {
        let mut plot = scene();
        let rect = add_rect(
            &mut plot,
            AnnotationSpace::Data2D,
            rect_shape(1.0, 1.0, 4.0, 3.0),
            0,
        );
        let text = add_text(&mut plot, AnnotationSpace::Data2D, 6.0, 6.0, 0);
        assert_eq!((rect, text), (1, 2));

        let snapshot = plot.snapshot();
        let frame = crate::frame::resolve_line_frame(&snapshot, &frame_spec()).expect("frame");
        let carried = frame.plot_layout().annotations();
        assert_eq!(carried.len(), 2);
        assert_eq!(carried[0].id(), rect);
        assert_eq!(carried[0].kind(), AnnotationKind::Rectangle);
        assert_eq!(carried[1].id(), text);
        assert_eq!(carried[1].kind(), AnnotationKind::Text);
        assert!(frame.plot_layout().validate());
    }

    #[test]
    fn mixed_all_four_kinds_mirror_together_in_id_order() {
        let mut plot = scene();
        let line = add_line(&mut plot, AnnotationSpace::Data2D, 0.0, 0.0, 4.0, 4.0, 0);
        let rect = add_rect(
            &mut plot,
            AnnotationSpace::Data2D,
            rect_shape(1.0, 1.0, 4.0, 3.0),
            0,
        );
        let arrow = add_arrow(&mut plot, AnnotationSpace::Data2D, 5.0, 5.0, 8.0, 7.0, 0);
        let text = add_text(&mut plot, AnnotationSpace::Data2D, 6.0, 6.0, 0);
        assert_eq!((line, rect, arrow, text), (1, 2, 3, 4));

        let snapshot = plot.snapshot();
        let frame = crate::frame::resolve_line_frame(&snapshot, &frame_spec()).expect("frame");
        let carried = frame.plot_layout().annotations();
        assert_eq!(carried.len(), 4);
        assert_eq!(carried[0].id(), line);
        assert_eq!(carried[0].kind(), AnnotationKind::Line);
        assert_eq!(carried[1].id(), rect);
        assert_eq!(carried[1].kind(), AnnotationKind::Rectangle);
        assert_eq!(carried[2].id(), arrow);
        assert_eq!(carried[2].kind(), AnnotationKind::Arrow);
        assert_eq!(carried[3].id(), text);
        assert_eq!(carried[3].kind(), AnnotationKind::Text);
        assert!(frame.plot_layout().validate());
    }

    #[test]
    fn other_kinds_and_spaces_stay_in_state_but_out_of_mirror() {
        let mut plot = scene();
        {
            let mut transaction = plot.transaction();
            transaction
                .add_annotation(
                    AnnotationSpace::AxesLogical,
                    AnnotationShape::Line {
                        x1: 0.0,
                        y1: 0.0,
                        x2: 4.0,
                        y2: 4.0,
                    },
                    1,
                    1,
                    1,
                )
                .expect("axes line");
            transaction
                .add_annotation(
                    AnnotationSpace::FigureLogical,
                    AnnotationShape::Arrow {
                        x1: 0.0,
                        y1: 0.0,
                        x2: 4.0,
                        y2: 4.0,
                        head_length: 1.0,
                    },
                    1,
                    1,
                    2,
                )
                .expect("figure arrow");
            transaction
                .add_annotation(AnnotationSpace::AxesLogical, text_shape(2.0, 2.0), 1, 1, 3)
                .expect("axes text");
            transaction
                .add_annotation(
                    AnnotationSpace::DisplayLogical,
                    rect_shape(10.0, 10.0, 20.0, 20.0),
                    1,
                    1,
                    4,
                )
                .expect("display rectangle");
            transaction.commit().expect("commit");
        }
        let snapshot = plot.snapshot();
        assert_eq!(snapshot.state.annotations_map().len(), 4);
        // Live annotations exist in state, but none is Data2D: the mirror
        // is empty, so the frame drops the fixture four.
        let mirrored = live_rectangle_layout(&snapshot.state)
            .expect("filter")
            .expect("live map is non-empty");
        assert!(mirrored.is_empty());
        let frame = crate::frame::resolve_line_frame(&snapshot, &frame_spec()).expect("frame");
        assert!(frame.plot_layout().annotations().is_empty());
        assert!(frame.plot_layout().validate());

        // Adding one qualifying Data2D line mirrors exactly that line.
        let id = add_line(&mut plot, AnnotationSpace::Data2D, 0.0, 0.0, 4.0, 4.0, 0);
        let snapshot = plot.snapshot();
        let frame = crate::frame::resolve_line_frame(&snapshot, &frame_spec()).expect("frame");
        let carried = frame.plot_layout().annotations();
        assert_eq!(carried.len(), 1);
        assert_eq!(carried[0].id(), id);
        assert_eq!(carried[0].kind(), AnnotationKind::Line);
    }

    #[test]
    fn mirrored_layout_digest_is_deterministic_and_distinct_from_fixture() {
        let mut first_plot = scene();
        add_rect(
            &mut first_plot,
            AnnotationSpace::Data2D,
            rect_shape(1.0, 1.0, 4.0, 3.0),
            0,
        );
        let mut second_plot = scene();
        add_rect(
            &mut second_plot,
            AnnotationSpace::Data2D,
            rect_shape(1.0, 1.0, 4.0, 3.0),
            0,
        );
        let first =
            crate::frame::resolve_line_frame(&first_plot.snapshot(), &frame_spec()).expect("frame");
        let second = crate::frame::resolve_line_frame(&second_plot.snapshot(), &frame_spec())
            .expect("frame");
        assert_eq!(
            first.plot_layout().layout_digest(),
            second.plot_layout().layout_digest()
        );
        let empty = scene();
        let fixture =
            crate::frame::resolve_line_frame(&empty.snapshot(), &frame_spec()).expect("frame");
        assert_ne!(
            first.plot_layout().layout_digest(),
            fixture.plot_layout().layout_digest()
        );
    }

    #[test]
    fn hit_reports_inside_outside_and_edges() {
        let mut plot = scene();
        add_rect(
            &mut plot,
            AnnotationSpace::Data2D,
            rect_shape(1.0, 1.0, 4.0, 3.0),
            0,
        );
        let snapshot = plot.snapshot();
        let frame = crate::frame::resolve_line_frame(&snapshot, &frame_spec()).expect("frame");
        let resolved = resolved_for(&snapshot);
        // Display maps as (x * 10, (10 - y) * 10): data (2.5, 2.0) is (25, 80).
        let hit = hit_live_rectangle(frame.plot_layout(), &snapshot, &resolved, 25.0, 80.0)
            .expect("hit")
            .expect("inside");
        assert_eq!(hit.id(), 1);
        assert_eq!(hit.kind(), AnnotationKind::Rectangle);
        // Data (0.5, 2.0) is display (5, 80): outside.
        assert!(
            hit_live_rectangle(frame.plot_layout(), &snapshot, &resolved, 5.0, 80.0)
                .expect("miss")
                .is_none()
        );
        // Data (1.0, 2.0) is display (10, 80): on the edge, edges included.
        assert!(
            hit_live_rectangle(frame.plot_layout(), &snapshot, &resolved, 10.0, 80.0)
                .expect("edge")
                .is_some()
        );
    }

    #[test]
    fn text_hit_reports_inside_outside_and_edges() {
        let mut plot = scene();
        add_text(&mut plot, AnnotationSpace::Data2D, 2.0, 2.0, 0);
        let snapshot = plot.snapshot();
        let frame = crate::frame::resolve_line_frame(&snapshot, &frame_spec()).expect("frame");
        let carried = frame.plot_layout().annotations();
        assert_eq!(carried.len(), 1);
        assert_eq!(carried[0].kind(), AnnotationKind::Text);
        let resolved = resolved_for(&snapshot);
        // Text box (2.0, 2.0) half extents (1.0, 1.0): data (2.0, 2.0) is
        // display (20, 80).
        let hit = hit_live_rectangle(frame.plot_layout(), &snapshot, &resolved, 20.0, 80.0)
            .expect("hit")
            .expect("inside");
        assert_eq!(hit.id(), 1);
        assert_eq!(hit.kind(), AnnotationKind::Text);
        // Data (0.5, 2.0) is display (5, 80): outside.
        assert!(
            hit_live_rectangle(frame.plot_layout(), &snapshot, &resolved, 5.0, 80.0)
                .expect("miss")
                .is_none()
        );
        // Data (1.0, 2.0) is display (10, 80): on the edge, edges included.
        assert!(
            hit_live_rectangle(frame.plot_layout(), &snapshot, &resolved, 10.0, 80.0)
                .expect("edge")
                .is_some()
        );
    }

    #[test]
    fn line_hit_reports_on_near_and_far_shaft() {
        let mut plot = scene();
        add_line(&mut plot, AnnotationSpace::Data2D, 1.0, 1.0, 4.0, 3.0, 0);
        let snapshot = plot.snapshot();
        let frame = crate::frame::resolve_line_frame(&snapshot, &frame_spec()).expect("frame");
        let carried = frame.plot_layout().annotations();
        assert_eq!(carried.len(), 1);
        assert_eq!(carried[0].kind(), AnnotationKind::Line);
        let resolved = resolved_for(&snapshot);
        // Shaft midpoint data (2.5, 2.0) is display (25, 80).
        let hit = hit_live_rectangle(frame.plot_layout(), &snapshot, &resolved, 25.0, 80.0)
            .expect("hit")
            .expect("on the shaft");
        assert_eq!(hit.id(), 1);
        assert_eq!(hit.kind(), AnnotationKind::Line);
        // Data (2.5, 3.0) is display (25, 70): within the carrier shaft
        // tolerance, so it still hits.
        assert!(
            hit_live_rectangle(frame.plot_layout(), &snapshot, &resolved, 25.0, 70.0)
                .expect("near query")
                .is_some()
        );
        // Data (2.5, 8.0) is display (25, 20): clear of the shaft, miss.
        assert!(
            hit_live_rectangle(frame.plot_layout(), &snapshot, &resolved, 25.0, 20.0)
                .expect("far query")
                .is_none()
        );
    }

    #[test]
    fn arrow_hit_reports_on_shaft_and_far_miss() {
        let mut plot = scene();
        add_arrow(&mut plot, AnnotationSpace::Data2D, 1.0, 1.0, 4.0, 3.0, 0);
        let snapshot = plot.snapshot();
        let frame = crate::frame::resolve_line_frame(&snapshot, &frame_spec()).expect("frame");
        let carried = frame.plot_layout().annotations();
        assert_eq!(carried.len(), 1);
        assert_eq!(carried[0].kind(), AnnotationKind::Arrow);
        let resolved = resolved_for(&snapshot);
        // Shaft midpoint data (2.5, 2.0) is display (25, 80).
        let hit = hit_live_rectangle(frame.plot_layout(), &snapshot, &resolved, 25.0, 80.0)
            .expect("hit")
            .expect("on the shaft");
        assert_eq!(hit.id(), 1);
        assert_eq!(hit.kind(), AnnotationKind::Arrow);
        // Data (2.5, 8.0) is display (25, 20): clear of the shaft, miss.
        assert!(
            hit_live_rectangle(frame.plot_layout(), &snapshot, &resolved, 25.0, 20.0)
                .expect("far query")
                .is_none()
        );
    }

    #[test]
    fn hit_overlap_prefers_higher_z_order_then_later_layout_order() {
        let mut plot = scene();
        let low = add_rect(
            &mut plot,
            AnnotationSpace::Data2D,
            rect_shape(1.0, 1.0, 4.0, 3.0),
            5,
        );
        let tied = add_rect(
            &mut plot,
            AnnotationSpace::Data2D,
            rect_shape(2.0, 2.0, 5.0, 4.0),
            5,
        );
        let snapshot = plot.snapshot();
        let frame = crate::frame::resolve_line_frame(&snapshot, &frame_spec()).expect("frame");
        let resolved = resolved_for(&snapshot);
        // Data (3.0, 2.5) is display (30, 75): inside both; same z-order
        // resolves to the later annotation in layout order.
        let hit = hit_live_rectangle(frame.plot_layout(), &snapshot, &resolved, 30.0, 75.0)
            .expect("hit")
            .expect("overlap");
        assert_eq!(hit.id(), tied);
        assert_ne!(hit.id(), low);
        // A higher z-order wins regardless of layout order.
        let top = add_rect(
            &mut plot,
            AnnotationSpace::Data2D,
            rect_shape(0.0, 0.0, 3.5, 3.5),
            9,
        );
        let snapshot = plot.snapshot();
        let frame = crate::frame::resolve_line_frame(&snapshot, &frame_spec()).expect("frame");
        let resolved = resolved_for(&snapshot);
        let hit = hit_live_rectangle(frame.plot_layout(), &snapshot, &resolved, 30.0, 75.0)
            .expect("hit")
            .expect("overlap");
        assert_eq!(hit.id(), top);
    }

    #[test]
    fn hit_stale_layout_fails_closed_while_annotation_commits_stay_valid() {
        let mut plot = scene();
        add_rect(
            &mut plot,
            AnnotationSpace::Data2D,
            rect_shape(1.0, 1.0, 4.0, 3.0),
            0,
        );
        let before = plot.snapshot();
        let before_frame = crate::frame::resolve_line_frame(&before, &frame_spec()).expect("frame");
        let resolved = resolved_for(&before);
        // An annotation-only commit keeps the layout generation, so the
        // mirror stays valid.
        add_rect(
            &mut plot,
            AnnotationSpace::Data2D,
            rect_shape(6.0, 6.0, 8.0, 8.0),
            0,
        );
        let middle = plot.snapshot();
        assert_eq!(middle.layout_revision(), before.layout_revision());
        assert!(
            hit_live_rectangle(before_frame.plot_layout(), &middle, &resolved, 25.0, 80.0)
                .expect("current carrier")
                .is_some()
        );
        // A view change re-stamps the carrier generation: the pinned layout
        // is stale and fails instead of reporting against moved geometry.
        {
            let mut transaction = plot.transaction();
            transaction
                .set_viewport(Viewport::from_bounds(1.0, 9.0, 1.0, 9.0).expect("view"))
                .expect("moved view");
            transaction.commit().expect("commit view");
        }
        let after = plot.snapshot();
        assert_ne!(after.layout_revision(), before.layout_revision());
        let error = hit_live_rectangle(before_frame.plot_layout(), &after, &resolved, 25.0, 80.0)
            .expect_err("stale carrier");
        assert_eq!(error.kind(), SceneErrorKind::Internal);
        let current = crate::frame::resolve_line_frame(&after, &frame_spec()).expect("frame");
        let resolved_after = resolved_for(&after);
        // Viewport (1..9, 1..9): display (18.75, 87.5) is data (2.5, 2.0).
        assert!(
            hit_live_rectangle(current.plot_layout(), &after, &resolved_after, 18.75, 87.5)
                .expect("current carrier")
                .is_some()
        );
    }

    #[test]
    fn hit_rejects_non_finite_display_input() {
        let mut plot = scene();
        add_rect(
            &mut plot,
            AnnotationSpace::Data2D,
            rect_shape(1.0, 1.0, 4.0, 3.0),
            0,
        );
        let snapshot = plot.snapshot();
        let frame = crate::frame::resolve_line_frame(&snapshot, &frame_spec()).expect("frame");
        let resolved = resolved_for(&snapshot);
        let error = hit_live_rectangle(frame.plot_layout(), &snapshot, &resolved, f64::NAN, 80.0)
            .expect_err("non-finite query");
        assert_eq!(error.kind(), SceneErrorKind::InvalidInput);
    }

    #[test]
    fn accessibility_projection_lists_live_rectangle() {
        let mut plot = scene();
        let id = add_rect(
            &mut plot,
            AnnotationSpace::Data2D,
            rect_shape(1.0, 1.0, 4.0, 3.0),
            0,
        );
        let tree = plot
            .snapshot()
            .project_a11y(A11yUiState::new())
            .expect("projection");
        let nodes: Vec<u64> = tree
            .root()
            .children()
            .iter()
            .filter(|node| node.kind_ref() == A11yNodeKind::Annotation)
            .filter_map(|node| node.key())
            .collect();
        assert_eq!(nodes, vec![id]);
    }

    #[test]
    fn accessibility_projection_lists_live_text() {
        let mut plot = scene();
        let id = add_text(&mut plot, AnnotationSpace::Data2D, 2.0, 2.0, 0);
        let tree = plot
            .snapshot()
            .project_a11y(A11yUiState::new())
            .expect("projection");
        let nodes: Vec<u64> = tree
            .root()
            .children()
            .iter()
            .filter(|node| node.kind_ref() == A11yNodeKind::Annotation)
            .filter_map(|node| node.key())
            .collect();
        assert_eq!(nodes, vec![id]);
    }

    #[test]
    fn accessibility_projection_lists_live_line_and_arrow() {
        let mut plot = scene();
        let line = add_line(&mut plot, AnnotationSpace::Data2D, 0.0, 0.0, 4.0, 4.0, 0);
        let arrow = add_arrow(&mut plot, AnnotationSpace::Data2D, 5.0, 5.0, 8.0, 7.0, 0);
        let tree = plot
            .snapshot()
            .project_a11y(A11yUiState::new())
            .expect("projection");
        let nodes: Vec<u64> = tree
            .root()
            .children()
            .iter()
            .filter(|node| node.kind_ref() == A11yNodeKind::Annotation)
            .filter_map(|node| node.key())
            .collect();
        assert_eq!(nodes, vec![line, arrow]);
    }

    #[test]
    fn annotation_commits_leave_view_component_untouched() {
        let mut plot = scene();
        let canonical = plot.snapshot().canonical_view();
        let viewport = plot.snapshot().viewport();
        add_rect(
            &mut plot,
            AnnotationSpace::Data2D,
            rect_shape(1.0, 1.0, 4.0, 3.0),
            0,
        );
        assert_eq!(plot.state.component_revisions().1.0, 0);
        assert_eq!(plot.snapshot().canonical_view(), canonical);
        assert_eq!(plot.snapshot().viewport(), viewport);
    }

    #[test]
    fn from_live_parts_accepts_all_four_kinds_rejects_rest() {
        let snapshot = scene().snapshot();
        let runs = snapshot.plot_layout().runs().to_vec();
        // Data2D identity text boxes mirror alongside rectangles.
        let text = RetainedAnnotation::new(
            1,
            AnnotationSpace::Data2D,
            AnnotationShape::Text {
                x: 2.0,
                y: 2.0,
                half_width: 1.0,
                half_height: 1.0,
            },
            AnnotationTransform::identity(),
            1,
            1,
            0,
        )
        .expect("text");
        let layout = PlotLayout::from_live_parts(runs.clone(), vec![text], 0, 0).expect("mirror");
        assert_eq!(layout.annotations().len(), 1);
        assert_eq!(layout.annotations()[0].kind(), AnnotationKind::Text);
        assert!(layout.validate());
        // Data2D identity line shafts mirror.
        let line = RetainedAnnotation::new(
            2,
            AnnotationSpace::Data2D,
            AnnotationShape::Line {
                x1: 0.0,
                y1: 0.0,
                x2: 4.0,
                y2: 4.0,
            },
            AnnotationTransform::identity(),
            1,
            1,
            0,
        )
        .expect("line");
        let layout = PlotLayout::from_live_parts(runs.clone(), vec![line], 0, 0).expect("mirror");
        assert_eq!(layout.annotations().len(), 1);
        assert_eq!(layout.annotations()[0].kind(), AnnotationKind::Line);
        assert!(layout.validate());
        // Data2D identity arrow shafts mirror.
        let arrow = RetainedAnnotation::new(
            3,
            AnnotationSpace::Data2D,
            AnnotationShape::Arrow {
                x1: 0.0,
                y1: 0.0,
                x2: 4.0,
                y2: 4.0,
                head_length: 1.0,
            },
            AnnotationTransform::identity(),
            1,
            1,
            0,
        )
        .expect("arrow");
        let layout = PlotLayout::from_live_parts(runs.clone(), vec![arrow], 0, 0).expect("mirror");
        assert_eq!(layout.annotations().len(), 1);
        assert_eq!(layout.annotations()[0].kind(), AnnotationKind::Arrow);
        assert!(layout.validate());
        // Non-Data2D lines stay out even with an identity map.
        let foreign_line = RetainedAnnotation::new(
            4,
            AnnotationSpace::AxesLogical,
            AnnotationShape::Line {
                x1: 0.0,
                y1: 0.0,
                x2: 4.0,
                y2: 4.0,
            },
            AnnotationTransform::identity(),
            1,
            1,
            0,
        )
        .expect("axes line");
        let error = PlotLayout::from_live_parts(runs.clone(), vec![foreign_line], 0, 0)
            .expect_err("non-Data2D is not mirrored");
        assert_eq!(error.kind(), SceneErrorKind::InvalidInput);
        let foreign = RetainedAnnotation::new(
            5,
            AnnotationSpace::AxesLogical,
            rect_shape(0.0, 0.0, 2.0, 2.0),
            AnnotationTransform::identity(),
            1,
            1,
            0,
        )
        .expect("axes rectangle");
        let error = PlotLayout::from_live_parts(runs, vec![foreign], 0, 0)
            .expect_err("non-Data2D is not mirrored");
        assert_eq!(error.kind(), SceneErrorKind::InvalidInput);
    }

    #[test]
    fn from_live_parts_rejects_over_capacity() {
        let snapshot = scene().snapshot();
        let runs = snapshot.plot_layout().runs().to_vec();
        let mut rectangles = Vec::new();
        for id in 1..=MAX_RETAINED_ANNOTATIONS as u64 + 1 {
            rectangles.push(
                RetainedAnnotation::new(
                    id,
                    AnnotationSpace::Data2D,
                    rect_shape(0.0, 0.0, 1.0, 1.0),
                    AnnotationTransform::identity(),
                    1,
                    1,
                    0,
                )
                .expect("rectangle"),
            );
        }
        let error =
            PlotLayout::from_live_parts(runs, rectangles, 0, 0).expect_err("capacity exceeded");
        assert_eq!(error.kind(), SceneErrorKind::CapacityExceeded);
    }
}
