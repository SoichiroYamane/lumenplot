#[cfg(test)]
use std::cell::Cell;

use crate::bridge::{
    LineFrame, LineFrameSpec, LinePoint, LineSegment, LineSeries, LogicalRect, LogicalSize,
    SceneRevision, SeriesId,
};
use crate::error::{SceneError, SceneErrorKind};
use crate::scene::{AxisRange, AxisScale, SceneSnapshot};

pub(crate) const MAX_FRAME_SERIES: usize = 65_536;
pub(crate) const MAX_FRAME_SEGMENTS: usize = 1_000_000;
pub(crate) const MAX_FRAME_POINTS: usize = 1_000_000;

/// Layout facts resolved once for one immutable snapshot.
///
/// The line slice has one plot clip today, but keeping the transform and clip
/// inputs together makes the semantic result the single source for every
/// consumer. Sinks receive the resolved frame; they do not reconstruct this
/// mapping from scene state.
#[derive(Clone, Copy)]
struct ResolvedLayout {
    canvas: LogicalSize,
    plot_rect: LogicalRect,
    logical_units_per_inch: f64,
    x_range: AxisRange,
    y_range: AxisRange,
}

impl ResolvedLayout {
    fn new(
        canvas: LogicalSize,
        plot_rect: LogicalRect,
        logical_units_per_inch: f64,
        viewport: crate::scene::Viewport,
    ) -> Result<Self, SceneError> {
        let x_range = viewport.x();
        let y_range = viewport.y();
        let x_span = x_range.max() - x_range.min();
        let y_span = y_range.max() - y_range.min();
        if !logical_units_per_inch.is_finite()
            || logical_units_per_inch <= 0.0
            || !canvas.width().is_finite()
            || !canvas.height().is_finite()
            || canvas.width() <= 0.0
            || canvas.height() <= 0.0
            || !x_span.is_finite()
            || !y_span.is_finite()
            || x_span <= 0.0
            || y_span <= 0.0
            || plot_rect.x_min() < 0.0
            || plot_rect.y_min() < 0.0
            || plot_rect.x_max() > canvas.width()
            || plot_rect.y_max() > canvas.height()
        {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }
        Ok(Self {
            canvas,
            plot_rect,
            logical_units_per_inch,
            x_range,
            y_range,
        })
    }

    fn transform_point(&self, x: f64, y: f64) -> Result<LinePoint, SceneError> {
        let x_offset = x - self.x_range.min();
        let y_offset = self.y_range.max() - y;
        if !x_offset.is_finite() || !y_offset.is_finite() {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }
        let x_fraction = x_offset / (self.x_range.max() - self.x_range.min());
        let y_fraction = y_offset / (self.y_range.max() - self.y_range.min());
        if !x_fraction.is_finite() || !y_fraction.is_finite() {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }
        let x_scaled = x_fraction * (self.plot_rect.x_max() - self.plot_rect.x_min());
        let y_scaled = y_fraction * (self.plot_rect.y_max() - self.plot_rect.y_min());
        if !x_scaled.is_finite() || !y_scaled.is_finite() {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }
        let display_x = self.plot_rect.x_min() + x_scaled;
        let display_y = self.plot_rect.y_min() + y_scaled;
        if !display_x.is_finite() || !display_y.is_finite() {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }
        Ok(LinePoint::from_parts(display_x, display_y))
    }
}

#[cfg(test)]
thread_local! {
    static FORCE_ALLOCATION_FAILURE: Cell<bool> = const { Cell::new(false) };
}

#[cfg(test)]
pub(crate) fn set_allocation_failure_for_test(fail: bool) {
    FORCE_ALLOCATION_FAILURE.with(|value| value.set(fail));
}

pub(crate) fn resolve_line_frame(
    snapshot: &SceneSnapshot,
    spec: &LineFrameSpec,
) -> Result<LineFrame, SceneError> {
    let (canvas, plot_rect, logical_units_per_inch, style, background) = spec.parts();
    let scales = snapshot.state.scales();
    if scales.x() != AxisScale::Linear || scales.y() != AxisScale::Linear {
        return Err(SceneError::new(SceneErrorKind::UnsupportedCapability));
    }
    let layout = ResolvedLayout::new(
        canvas,
        plot_rect,
        logical_units_per_inch,
        snapshot.state.viewport(),
    )?;

    let series_map = snapshot.state.series_map();
    if series_map.len() > MAX_FRAME_SERIES {
        return Err(SceneError::new(SceneErrorKind::CapacityExceeded));
    }

    let mut frame_series = Vec::new();
    reserve(&mut frame_series, series_map.len())?;
    let mut counts = Counts::default();

    for (id, storage) in series_map {
        if storage.point_count() > MAX_FRAME_POINTS || storage.segments().len() > MAX_FRAME_SEGMENTS
        {
            return Err(SceneError::new(SceneErrorKind::CapacityExceeded));
        }
        let mut segments = Vec::new();
        reserve(&mut segments, storage.segments().len())?;
        for logical_segment in storage.segments() {
            if logical_segment.point_start >= logical_segment.point_end
                || logical_segment.point_end > storage.points().len()
            {
                return Err(SceneError::new(SceneErrorKind::Internal));
            }
            let source_points =
                &storage.points()[logical_segment.point_start..logical_segment.point_end];
            let mut transformed = Vec::new();
            reserve(&mut transformed, source_points.len())?;
            for point in source_points {
                transformed.push(layout.transform_point(point.x, point.y)?);
            }
            append_clipped_structural_segment_with_clips(
                &mut segments,
                &transformed,
                std::slice::from_ref(&layout.plot_rect),
                &mut counts,
            )?;
        }
        let bridge_id = SeriesId::from_engine(*id);
        frame_series.push(LineSeries::from_parts(bridge_id, style, segments));
    }

    Ok(LineFrame::from_parts(
        SceneRevision::from_engine(snapshot.revision()),
        layout.canvas,
        layout.plot_rect,
        layout.logical_units_per_inch,
        background,
        frame_series,
    ))
}

#[derive(Default)]
struct Counts {
    segments: usize,
    points: usize,
}

fn reserve<T>(values: &mut Vec<T>, additional: usize) -> Result<(), SceneError> {
    if additional == 0 {
        return Ok(());
    }
    #[cfg(test)]
    if FORCE_ALLOCATION_FAILURE.with(Cell::get) {
        return Err(SceneError::new(SceneErrorKind::AllocationFailed));
    }
    values
        .try_reserve(additional)
        .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))
}

fn append_clipped_structural_segment(
    output: &mut Vec<LineSegment>,
    points: &[LinePoint],
    plot_rect: LogicalRect,
    counts: &mut Counts,
) -> Result<(), SceneError> {
    append_clipped_structural_segment_with_clips(
        output,
        points,
        std::slice::from_ref(&plot_rect),
        counts,
    )
}

fn append_clipped_structural_segment_with_clips(
    output: &mut Vec<LineSegment>,
    points: &[LinePoint],
    clips: &[LogicalRect],
    counts: &mut Counts,
) -> Result<(), SceneError> {
    if points.len() == 1 {
        if clips.iter().all(|clip| point_inside(points[0], *clip)) {
            let mut path = Vec::new();
            append_path_point(&mut path, points[0], counts)?;
            push_output_segment(output, path, counts)?;
        }
        return Ok(());
    }

    let mut current: Option<Vec<LinePoint>> = None;
    for pair in points.windows(2) {
        let clipped = clip_segment_stack(pair[0], pair[1], clips)?;
        let Some((enter, exit)) = clipped else {
            flush_path(output, &mut current, counts)?;
            continue;
        };
        let start = interpolate(pair[0], pair[1], enter)?;
        let end = interpolate(pair[0], pair[1], exit)?;
        if current.is_none() || enter > 0.0 {
            flush_path(output, &mut current, counts)?;
            let mut path = Vec::new();
            append_path_point(&mut path, start, counts)?;
            if exit > enter {
                append_path_point(&mut path, end, counts)?;
            }
            current = Some(path);
        } else if exit > enter {
            let path = current.as_mut().ok_or_else(internal_error)?;
            append_path_point(path, end, counts)?;
        }
    }
    flush_path(output, &mut current, counts)
}

fn point_inside(point: LinePoint, plot_rect: LogicalRect) -> bool {
    point.x() >= plot_rect.x_min()
        && point.x() <= plot_rect.x_max()
        && point.y() >= plot_rect.y_min()
        && point.y() <= plot_rect.y_max()
}

fn clip_segment(
    first: LinePoint,
    second: LinePoint,
    plot_rect: LogicalRect,
) -> Result<Option<(f64, f64)>, SceneError> {
    let dx = second.x() - first.x();
    let dy = second.y() - first.y();
    if !dx.is_finite() || !dy.is_finite() {
        return Err(SceneError::new(SceneErrorKind::InvalidInput));
    }

    let mut enter = 0.0;
    let mut exit = 1.0;
    let boundaries = [
        (-dx, first.x() - plot_rect.x_min()),
        (dx, plot_rect.x_max() - first.x()),
        (-dy, first.y() - plot_rect.y_min()),
        (dy, plot_rect.y_max() - first.y()),
    ];
    for (p, q) in boundaries {
        if !p.is_finite() || !q.is_finite() {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }
        if p == 0.0 {
            if q < 0.0 {
                return Ok(None);
            }
            continue;
        }
        let ratio = q / p;
        if !ratio.is_finite() {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }
        if p < 0.0 {
            if ratio > exit {
                return Ok(None);
            }
            if ratio > enter {
                enter = ratio;
            }
        } else {
            if ratio < enter {
                return Ok(None);
            }
            if ratio < exit {
                exit = ratio;
            }
        }
    }
    if enter > exit {
        Ok(None)
    } else {
        Ok(Some((enter, exit)))
    }
}

/// Intersect a segment with each transformed clip in declaration order.
///
/// The interval remains in the original segment's parameter space, so a
/// later clip can remove an exit/re-entry run without reconnecting it to a
/// neighboring structural segment.
fn clip_segment_stack(
    first: LinePoint,
    second: LinePoint,
    clips: &[LogicalRect],
) -> Result<Option<(f64, f64)>, SceneError> {
    let mut enter: f64 = 0.0;
    let mut exit: f64 = 1.0;
    for clip in clips {
        let Some((clip_enter, clip_exit)) = clip_segment(first, second, *clip)? else {
            return Ok(None);
        };
        enter = enter.max(clip_enter);
        exit = exit.min(clip_exit);
        if !enter.is_finite() || !exit.is_finite() {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }
        if enter > exit {
            return Ok(None);
        }
    }
    Ok(Some((enter, exit)))
}

fn interpolate(first: LinePoint, second: LinePoint, ratio: f64) -> Result<LinePoint, SceneError> {
    if ratio == 0.0 {
        return Ok(first);
    }
    if ratio == 1.0 {
        return Ok(second);
    }
    let x = first.x() + ratio * (second.x() - first.x());
    let y = first.y() + ratio * (second.y() - first.y());
    if !x.is_finite() || !y.is_finite() {
        return Err(SceneError::new(SceneErrorKind::InvalidInput));
    }
    Ok(LinePoint::from_parts(x, y))
}

fn append_path_point(
    path: &mut Vec<LinePoint>,
    point: LinePoint,
    counts: &mut Counts,
) -> Result<(), SceneError> {
    if counts.points >= MAX_FRAME_POINTS {
        return Err(SceneError::new(SceneErrorKind::CapacityExceeded));
    }
    reserve(path, 1)?;
    path.push(point);
    counts.points += 1;
    Ok(())
}

fn push_output_segment(
    output: &mut Vec<LineSegment>,
    path: Vec<LinePoint>,
    counts: &mut Counts,
) -> Result<(), SceneError> {
    if path.is_empty() {
        return Err(internal_error());
    }
    if counts.segments >= MAX_FRAME_SEGMENTS {
        return Err(SceneError::new(SceneErrorKind::CapacityExceeded));
    }
    reserve(output, 1)?;
    output.push(LineSegment::from_parts(path));
    counts.segments += 1;
    Ok(())
}

fn flush_path(
    output: &mut Vec<LineSegment>,
    current: &mut Option<Vec<LinePoint>>,
    counts: &mut Counts,
) -> Result<(), SceneError> {
    if let Some(path) = current.take() {
        push_output_segment(output, path, counts)?;
    }
    Ok(())
}

fn internal_error() -> SceneError {
    SceneError::new(SceneErrorKind::Internal)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bridge::{
        AxisScale, AxisScales, LineStyle, LogicalSize, PlotScene, SeriesData, SeriesTopology,
        SrgbRgba8, Viewport,
    };

    fn spec() -> LineFrameSpec {
        let canvas = LogicalSize::new(100.0, 80.0).expect("canvas");
        let plot = LogicalRect::new(10.0, 20.0, 90.0, 60.0).expect("plot");
        let style = LineStyle::new(SrgbRgba8::new(40, 50, 60, 255), 1.5).expect("style");
        LineFrameSpec::new(canvas, plot, 96.0, style, SrgbRgba8::new(1, 2, 3, 255)).expect("spec")
    }

    fn scene_with_series(
        x: Vec<f64>,
        y: Vec<f64>,
        segments: Option<Vec<std::ops::Range<usize>>>,
    ) -> (PlotScene, crate::bridge::SeriesId) {
        let view = Viewport::from_bounds(0.0, 10.0, 0.0, 10.0).expect("view");
        let mut scene = PlotScene::new(view, AxisScales::new(AxisScale::Linear, AxisScale::Linear))
            .expect("scene");
        let data = match segments {
            Some(segments) => {
                SeriesData::from_owned_xy_segments(SeriesTopology::ArbitraryXY, x, y, segments)
                    .expect("data")
            }
            None => SeriesData::from_owned_xy(SeriesTopology::ArbitraryXY, x, y).expect("data"),
        };
        let id = {
            let mut transaction = scene.transaction();
            let id = transaction.add_series(data).expect("add series");
            transaction.commit().expect("commit series");
            id
        };
        (scene, id)
    }

    fn assert_close(actual: f64, expected: f64) {
        assert!(
            (actual - expected).abs() <= 1.0e-12,
            "{actual} != {expected}"
        );
    }

    #[test]
    fn constructor_validation_and_transparent_color_canonicalization() {
        assert!(LogicalSize::new(0.0, 1.0).is_err());
        assert!(LogicalSize::new(1.0, f64::INFINITY).is_err());
        assert!(LogicalRect::new(2.0, 0.0, 1.0, 1.0).is_err());
        assert!(LineStyle::new(SrgbRgba8::new(1, 2, 3, 0), 0.0).is_err());
        assert!(
            LineFrameSpec::new(
                LogicalSize::new(10.0, 10.0).expect("canvas"),
                LogicalRect::new(0.0, 0.0, 11.0, 10.0).expect("rect"),
                96.0,
                LineStyle::new(SrgbRgba8::new(1, 2, 3, 255), 1.0).expect("style"),
                SrgbRgba8::new(0, 0, 0, 255),
            )
            .is_err()
        );
        let transparent = SrgbRgba8::new(8, 9, 10, 0);
        assert_eq!(
            (
                transparent.r(),
                transparent.g(),
                transparent.b(),
                transparent.a()
            ),
            (0, 0, 0, 0)
        );
    }

    #[test]
    fn transforms_to_top_left_display_logical_and_retains_frame_metadata() {
        let (scene, id) = scene_with_series(vec![0.0, 5.0, 10.0], vec![0.0, 5.0, 10.0], None);
        let frame = scene.snapshot().resolve_line_frame(&spec()).expect("frame");
        assert_eq!(frame.revision(), scene.revision());
        assert_eq!(frame.canvas().width(), 100.0);
        assert_eq!(frame.plot_rect().y_min(), 20.0);
        assert_eq!(frame.logical_units_per_inch(), 96.0);
        assert_eq!(frame.background().a(), 255);
        assert_eq!(frame.series().len(), 1);
        assert_eq!(frame.series()[0].id(), id);
        assert_eq!(frame.series()[0].style().color().r(), 40);
        assert_eq!(frame.series()[0].style().width(), 1.5);
        let points = frame.series()[0].segments()[0].points();
        assert_close(points[0].x(), 10.0);
        assert_close(points[0].y(), 60.0);
        assert_close(points[1].x(), 50.0);
        assert_close(points[1].y(), 40.0);
        assert_close(points[2].x(), 90.0);
        assert_close(points[2].y(), 20.0);
    }

    #[test]
    fn series_order_is_ascending_even_after_identity_burn() {
        let view = Viewport::from_bounds(0.0, 10.0, 0.0, 10.0).expect("view");
        let mut scene = PlotScene::new(view, AxisScales::new(AxisScale::Linear, AxisScale::Linear))
            .expect("scene");
        {
            let mut transaction = scene.transaction();
            transaction
                .add_series(
                    SeriesData::from_owned_xy(SeriesTopology::ArbitraryXY, vec![0.0], vec![0.0])
                        .expect("data"),
                )
                .expect("first");
            transaction.abort();
        }
        let (second, third) = {
            let mut transaction = scene.transaction();
            let second = transaction
                .add_series(
                    SeriesData::from_owned_xy(SeriesTopology::ArbitraryXY, vec![1.0], vec![1.0])
                        .expect("data"),
                )
                .expect("second");
            let third = transaction
                .add_series(
                    SeriesData::from_owned_xy(SeriesTopology::ArbitraryXY, vec![2.0], vec![2.0])
                        .expect("data"),
                )
                .expect("third");
            transaction.commit().expect("commit");
            (second, third)
        };
        let frame = scene.snapshot().resolve_line_frame(&spec()).expect("frame");
        assert_eq!(frame.series().len(), 2);
        assert_eq!(frame.series()[0].id(), second);
        assert_eq!(frame.series()[1].id(), third);
    }

    #[test]
    fn empty_and_gap_only_series_remain_with_zero_segments() {
        let view = Viewport::from_bounds(0.0, 10.0, 0.0, 10.0).expect("view");
        let mut scene = PlotScene::new(view, AxisScales::new(AxisScale::Linear, AxisScale::Linear))
            .expect("scene");
        {
            let mut transaction = scene.transaction();
            transaction
                .add_series(
                    SeriesData::from_owned_xy(SeriesTopology::ArbitraryXY, Vec::new(), Vec::new())
                        .expect("empty"),
                )
                .expect("empty series");
            transaction
                .add_series(
                    SeriesData::from_owned_xy_segments(
                        SeriesTopology::ArbitraryXY,
                        vec![f64::NAN, f64::INFINITY],
                        vec![f64::NAN, f64::NEG_INFINITY],
                        Vec::new(),
                    )
                    .expect("gap only"),
                )
                .expect("gap-only series");
            transaction.commit().expect("commit");
        }
        let frame = scene.snapshot().resolve_line_frame(&spec()).expect("frame");
        assert_eq!(frame.series().len(), 2);
        assert!(
            frame
                .series()
                .iter()
                .all(|series| series.segments().is_empty())
        );
    }

    #[test]
    fn structural_gaps_are_not_reconnected() {
        let (scene, _) = scene_with_series(
            vec![0.0, 2.0, f64::NAN, 8.0, 10.0, f64::NAN, 4.0, 6.0],
            vec![0.0, 2.0, f64::NAN, 8.0, 10.0, f64::NAN, 4.0, 6.0],
            Some(vec![0..2, 3..5, 6..8]),
        );
        let frame = scene.snapshot().resolve_line_frame(&spec()).expect("frame");
        assert_eq!(frame.series()[0].segments().len(), 3);
        assert_eq!(frame.series()[0].segments()[0].points().len(), 2);
        assert_eq!(frame.series()[0].segments()[1].points().len(), 2);
        assert_eq!(frame.series()[0].segments()[2].points().len(), 2);
    }

    #[test]
    fn clipping_handles_crossings_outside_runs_and_duplicates() {
        let rect = LogicalRect::new(0.0, 0.0, 10.0, 10.0).expect("rect");
        let inside = |x: f64, y: f64| LinePoint::from_parts(x, y);
        let crossing = [inside(-5.0, 5.0), inside(15.0, 5.0)];
        let mut output = Vec::new();
        let mut counts = Counts::default();
        append_clipped_structural_segment(&mut output, &crossing, rect, &mut counts)
            .expect("crossing");
        assert_eq!(output.len(), 1);
        assert_close(output[0].points()[0].x(), 0.0);
        assert_close(output[0].points()[1].x(), 10.0);

        let exit_reentry = [inside(5.0, 5.0), inside(15.0, 5.0), inside(5.0, 5.0)];
        let mut output = Vec::new();
        let mut counts = Counts::default();
        append_clipped_structural_segment(&mut output, &exit_reentry, rect, &mut counts)
            .expect("split");
        assert_eq!(output.len(), 2);
        assert_eq!(output[0].points().len(), 2);
        assert_eq!(output[1].points().len(), 2);

        let duplicate = [inside(4.0, 4.0), inside(4.0, 4.0), inside(6.0, 6.0)];
        let mut output = Vec::new();
        let mut counts = Counts::default();
        append_clipped_structural_segment(&mut output, &duplicate, rect, &mut counts)
            .expect("duplicate");
        assert_eq!(output.len(), 1);
        assert_eq!(output[0].points().len(), 3);
    }

    #[test]
    fn ordered_clip_stack_intersects_each_clip_without_reconnecting_runs() {
        let outer = LogicalRect::new(0.0, 0.0, 10.0, 10.0).expect("outer");
        let inner = LogicalRect::new(2.0, 2.0, 8.0, 8.0).expect("inner");
        let points = [
            LinePoint::from_parts(-1.0, 5.0),
            LinePoint::from_parts(11.0, 5.0),
            LinePoint::from_parts(-1.0, 5.0),
        ];
        let mut output = Vec::new();
        let mut counts = Counts::default();
        append_clipped_structural_segment_with_clips(
            &mut output,
            &points,
            &[outer, inner],
            &mut counts,
        )
        .expect("stacked clip");
        assert_eq!(output.len(), 2);
        assert_close(output[0].points()[0].x(), 2.0);
        assert_close(output[0].points()[1].x(), 8.0);
        assert_close(output[1].points()[0].x(), 8.0);
        assert_close(output[1].points()[1].x(), 2.0);

        let disjoint = LogicalRect::new(12.0, 0.0, 14.0, 10.0).expect("disjoint");
        let mut output = Vec::new();
        let mut counts = Counts::default();
        append_clipped_structural_segment_with_clips(
            &mut output,
            &[
                LinePoint::from_parts(-1.0, 5.0),
                LinePoint::from_parts(11.0, 5.0),
            ],
            &[outer, disjoint],
            &mut counts,
        )
        .expect("disjoint clip stack");
        assert!(output.is_empty());
    }

    #[test]
    fn all_boundary_crossings_and_exact_boundary_points_are_retained() {
        let rect = LogicalRect::new(0.0, 0.0, 10.0, 10.0).expect("rect");
        let cases = [
            (
                LinePoint::from_parts(-1.0, 5.0),
                LinePoint::from_parts(5.0, 5.0),
            ),
            (
                LinePoint::from_parts(11.0, 5.0),
                LinePoint::from_parts(5.0, 5.0),
            ),
            (
                LinePoint::from_parts(5.0, -1.0),
                LinePoint::from_parts(5.0, 5.0),
            ),
            (
                LinePoint::from_parts(5.0, 11.0),
                LinePoint::from_parts(5.0, 5.0),
            ),
        ];
        for (first, second) in cases {
            let clipped = clip_segment(first, second, rect)
                .expect("clip")
                .expect("crosses rectangle");
            assert!(clipped.0 <= clipped.1);
        }
        let boundary = [
            LinePoint::from_parts(0.0, 0.0),
            LinePoint::from_parts(10.0, 10.0),
        ];
        let mut output = Vec::new();
        let mut counts = Counts::default();
        append_clipped_structural_segment(&mut output, &boundary, rect, &mut counts)
            .expect("boundary");
        assert_eq!(output[0].points().len(), 2);
        assert_eq!(output[0].points()[0].x(), 0.0);
        assert_eq!(output[0].points()[1].y(), 10.0);
    }

    #[test]
    fn fully_outside_and_single_boundary_touch_are_handled() {
        let rect = LogicalRect::new(0.0, 0.0, 10.0, 10.0).expect("rect");
        let outside = [
            LinePoint::from_parts(-2.0, -2.0),
            LinePoint::from_parts(-1.0, -1.0),
        ];
        let mut output = Vec::new();
        let mut counts = Counts::default();
        append_clipped_structural_segment(&mut output, &outside, rect, &mut counts)
            .expect("outside");
        assert!(output.is_empty());
        let touch = [
            LinePoint::from_parts(-1.0, 0.0),
            LinePoint::from_parts(0.0, 0.0),
        ];
        let mut output = Vec::new();
        let mut counts = Counts::default();
        append_clipped_structural_segment(&mut output, &touch, rect, &mut counts).expect("touch");
        assert_eq!(output.len(), 1);
        assert_eq!(output[0].points().len(), 1);
    }

    #[test]
    fn log10_is_explicitly_unsupported_and_old_snapshot_is_immutable() {
        let view = Viewport::from_bounds(1.0, 10.0, 1.0, 10.0).expect("view");
        let mut scene = PlotScene::new(view, AxisScales::new(AxisScale::Linear, AxisScale::Linear))
            .expect("scene");
        let old = scene.snapshot();
        {
            let mut transaction = scene.transaction();
            transaction
                .add_series(
                    SeriesData::from_owned_xy(
                        SeriesTopology::ArbitraryXY,
                        vec![1.0, 10.0],
                        vec![1.0, 10.0],
                    )
                    .expect("data"),
                )
                .expect("series");
            transaction.commit().expect("commit");
        }
        let old_frame = old.resolve_line_frame(&spec()).expect("old frame");
        assert!(old_frame.series().is_empty());
        let mut transaction = scene.transaction();
        transaction
            .set_axis_scales(AxisScales::new(AxisScale::Log10, AxisScale::Linear))
            .expect("log scale");
        transaction.commit().expect("scale commit");
        let error = match scene.snapshot().resolve_line_frame(&spec()) {
            Ok(_) => panic!("log unsupported"),
            Err(error) => error,
        };
        assert_eq!(
            error.kind(),
            crate::bridge::SceneErrorKind::UnsupportedCapability
        );
    }

    #[test]
    fn resolved_frame_keeps_the_published_snapshot_after_later_state_changes() {
        let view = Viewport::from_bounds(0.0, 10.0, 0.0, 10.0).expect("view");
        let mut scene = PlotScene::new(view, AxisScales::new(AxisScale::Linear, AxisScale::Linear))
            .expect("scene");
        let old_snapshot = scene.snapshot();
        let old_frame = old_snapshot.resolve_line_frame(&spec()).expect("old frame");

        {
            let mut transaction = scene.transaction();
            transaction
                .add_series(
                    SeriesData::from_owned_xy(
                        SeriesTopology::ArbitraryXY,
                        vec![0.0, 10.0],
                        vec![0.0, 10.0],
                    )
                    .expect("data"),
                )
                .expect("series");
            transaction.commit().expect("commit");
        }

        assert!(old_frame.series().is_empty());
        let current_frame = scene
            .snapshot()
            .resolve_line_frame(&spec())
            .expect("current frame");
        assert!(current_frame.revision() > old_frame.revision());
        assert_eq!(current_frame.series().len(), 1);
    }

    #[test]
    fn arithmetic_overflow_and_allocation_failure_are_explicit() {
        let view = Viewport::from_bounds(-f64::MAX, f64::MAX, -1.0, 1.0).expect("view");
        let mut scene = PlotScene::new(view, AxisScales::new(AxisScale::Linear, AxisScale::Linear))
            .expect("scene");
        {
            let mut transaction = scene.transaction();
            transaction
                .add_series(
                    SeriesData::from_owned_xy(
                        SeriesTopology::ArbitraryXY,
                        vec![f64::MAX],
                        vec![0.0],
                    )
                    .expect("data"),
                )
                .expect("series");
            transaction.commit().expect("commit");
        }
        let error = match scene.snapshot().resolve_line_frame(&spec()) {
            Ok(_) => panic!("overflow"),
            Err(error) => error,
        };
        assert_eq!(error.kind(), crate::bridge::SceneErrorKind::InvalidInput);

        let (scene, _) = scene_with_series(vec![0.0], vec![0.0], None);
        set_allocation_failure_for_test(true);
        let error = match scene.snapshot().resolve_line_frame(&spec()) {
            Ok(_) => panic!("injected allocation failure"),
            Err(error) => error,
        };
        set_allocation_failure_for_test(false);
        assert_eq!(
            error.kind(),
            crate::bridge::SceneErrorKind::AllocationFailed
        );
    }

    #[test]
    fn private_frame_ceilings_are_checked_before_output_growth() {
        let rect = LogicalRect::new(0.0, 0.0, 10.0, 10.0).expect("rect");
        let points = [LinePoint::from_parts(1.0, 1.0)];
        let mut counts = Counts {
            segments: 0,
            points: MAX_FRAME_POINTS,
        };
        let mut output = Vec::new();
        let error = append_clipped_structural_segment(&mut output, &points, rect, &mut counts)
            .expect_err("point ceiling");
        assert_eq!(error.kind(), SceneErrorKind::CapacityExceeded);

        let mut counts = Counts {
            segments: MAX_FRAME_SEGMENTS,
            points: 0,
        };
        let mut output = Vec::new();
        let error = append_clipped_structural_segment(&mut output, &points, rect, &mut counts)
            .expect_err("segment ceiling");
        assert_eq!(error.kind(), SceneErrorKind::CapacityExceeded);
    }

    fn oracle_clip(first: LinePoint, second: LinePoint, rect: LogicalRect) -> Option<(f64, f64)> {
        let dx = second.x() - first.x();
        let dy = second.y() - first.y();
        let mut cuts = vec![0.0, 1.0];
        for (numerator, denominator) in [
            (rect.x_min() - first.x(), dx),
            (rect.x_max() - first.x(), dx),
            (rect.y_min() - first.y(), dy),
            (rect.y_max() - first.y(), dy),
        ] {
            if denominator != 0.0 {
                let ratio = numerator / denominator;
                if ratio.is_finite() && (0.0..=1.0).contains(&ratio) {
                    cuts.push(ratio);
                }
            }
        }
        cuts.sort_by(f64::total_cmp);
        let mut clipped = None;
        for pair in cuts.windows(2) {
            let midpoint = (pair[0] + pair[1]) * 0.5;
            let x = first.x() + midpoint * dx;
            let y = first.y() + midpoint * dy;
            if x >= rect.x_min() && x <= rect.x_max() && y >= rect.y_min() && y <= rect.y_max() {
                clipped = Some((pair[0], pair[1]));
                break;
            }
        }
        if clipped.is_some() {
            clipped
        } else if point_inside(first, rect) {
            Some((0.0, 0.0))
        } else if point_inside(second, rect) {
            Some((1.0, 1.0))
        } else {
            None
        }
    }

    #[test]
    fn direct_f64_clip_oracle_matches_deterministic_property_loop() {
        let rect = LogicalRect::new(-3.0, -2.0, 7.0, 5.0).expect("rect");
        let mut state = 0x1234_5678_9abc_def0u64;
        for _ in 0..2048 {
            state = state
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1);
            let first_x = (state >> 16) as i16 as f64 / 17.0;
            state = state
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1);
            let first_y = (state >> 16) as i16 as f64 / 17.0;
            state = state
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1);
            let second_x = (state >> 16) as i16 as f64 / 17.0;
            state = state
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1);
            let second_y = (state >> 16) as i16 as f64 / 17.0;
            let first = LinePoint::from_parts(first_x, first_y);
            let second = LinePoint::from_parts(second_x, second_y);
            let actual = clip_segment(first, second, rect).expect("clip");
            let expected = oracle_clip(first, second, rect);
            match (actual, expected) {
                (None, None) => {}
                (Some((actual_enter, actual_exit)), Some((expected_enter, expected_exit))) => {
                    assert!((actual_enter - expected_enter).abs() < 1.0e-12);
                    assert!((actual_exit - expected_exit).abs() < 1.0e-12);
                }
                mismatch => panic!("clip mismatch: {mismatch:?}"),
            }
        }
    }
}
