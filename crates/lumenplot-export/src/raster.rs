use std::mem::size_of;

use lumenplot_engine::bridge::{LineFrame, LineSeries};
use tiny_skia::{FillRule, IntSize, LineCap, LineJoin, Mask, PathBuilder, Stroke, Transform};

use crate::compositor::{pixel_storage_bytes, quantize_round_half_even, rgba_storage_bytes};
use crate::error::{ExportError, ExportErrorKind};
use crate::png::PngSpec;

pub(crate) const MAX_DIMENSION: u32 = 16_384;
pub(crate) const MAX_PIXELS: usize = 16_777_216;
pub(crate) const MAX_OUTPUT_BYTES: usize = 67_108_864;
pub(crate) const MAX_WORK_BYTES: usize = 536_870_912;
pub(crate) const MAX_PATH_POINTS: usize = 1_000_000;

// tiny-skia 0.12.0's private `painter::is_too_big_for_math`, called by
// `Mask::fill_path`, rejects bounds outside `SCALAR_MAX * 0.25`. Keep this
// local precondition aligned with that pinned dependency version.
const TINY_SKIA_SAFE_PATH_BOUND: f32 = f32::MAX * 0.25;

#[derive(Clone, Copy)]
struct ClipRect {
    x_min: f64,
    y_min: f64,
    x_max: f64,
    y_max: f64,
}

pub(crate) struct RasterPlan {
    width: u32,
    height: u32,
    pixel_count: usize,
    scale: f64,
    clip: ClipRect,
    output_estimate: usize,
}

impl RasterPlan {
    pub(crate) fn new(frame: &LineFrame, spec: &PngSpec) -> Result<Self, ExportError> {
        let output_dpi = spec.output_dpi();
        let logical_units_per_inch = frame.logical_units_per_inch();
        if !output_dpi.is_finite()
            || output_dpi <= 0.0
            || !logical_units_per_inch.is_finite()
            || logical_units_per_inch <= 0.0
        {
            return Err(ExportError::invalid_input());
        }
        let scale = output_dpi / logical_units_per_inch;
        if !scale.is_finite() || scale <= 0.0 {
            return Err(ExportError::invalid_input());
        }

        let canvas = frame.canvas();
        let width = checked_dimension(canvas.width(), scale)?;
        let height = checked_dimension(canvas.height(), scale)?;
        let pixel_count = usize::try_from(width)
            .ok()
            .and_then(|width| {
                usize::try_from(height)
                    .ok()
                    .and_then(|height| width.checked_mul(height))
            })
            .ok_or_else(ExportError::capacity_exceeded)?;
        if pixel_count == 0 || pixel_count > MAX_PIXELS {
            return Err(ExportError::capacity_exceeded());
        }

        let clip = frame.plot_rect();
        let clip = ClipRect {
            x_min: clip.x_min() * scale,
            y_min: clip.y_min() * scale,
            x_max: clip.x_max() * scale,
            y_max: clip.y_max() * scale,
        };
        if ![clip.x_min, clip.y_min, clip.x_max, clip.y_max]
            .iter()
            .all(|value| value.is_finite())
            || clip.x_min < 0.0
            || clip.y_min < 0.0
            || clip.x_min >= clip.x_max
            || clip.y_min >= clip.y_max
            || clip.x_max > canvas.width() * scale
            || clip.y_max > canvas.height() * scale
        {
            return Err(ExportError::invalid_input());
        }

        let mut path_points = 0usize;
        for series in frame.series() {
            let stroke_width = series.style().width() * scale;
            if !stroke_width.is_finite()
                || stroke_width <= 0.0
                || stroke_width > f64::from(f32::MAX)
            {
                return Err(ExportError::invalid_input());
            }
            for segment in series.segments() {
                path_points = path_points
                    .checked_add(segment.points().len())
                    .ok_or_else(ExportError::capacity_exceeded)?;
                if path_points > MAX_PATH_POINTS {
                    return Err(ExportError::capacity_exceeded());
                }
                for point in segment.points() {
                    validate_pixel_point(point.x(), point.y(), scale, width, height)?;
                }
            }
        }

        let raw_bytes =
            rgba_storage_bytes(pixel_count).ok_or_else(ExportError::capacity_exceeded)?;
        let rows_with_filter = raw_bytes
            .checked_add(usize::try_from(height).map_err(|_| ExportError::capacity_exceeded())?)
            .ok_or_else(ExportError::capacity_exceeded)?;
        // Upper bound on the encoded PNG size. Since ADR-0018 (IDAT DEFLATE
        // `Balanced`), the encoder emits compressed blocks, so this stored-block
        // budget is intentionally conservative rather than tight: it still bounds
        // any possible encoder output for the pre-flight ceiling check, because
        // every 65,535-byte block contributes at most 5 header bytes plus its
        // (at most) 65,535 payload bytes, all of which are counted here.
        // `CappedWriter` independently enforces MAX_OUTPUT_BYTES while streaming.
        let stored_blocks = rows_with_filter
            .checked_add(65_534)
            .ok_or_else(ExportError::capacity_exceeded)?
            / 65_535;
        let output_estimate = rows_with_filter
            .checked_add(
                stored_blocks
                    .checked_mul(5)
                    .ok_or_else(ExportError::capacity_exceeded)?,
            )
            .and_then(|value| value.checked_add(1_024))
            .ok_or_else(ExportError::capacity_exceeded)?;
        if output_estimate > MAX_OUTPUT_BYTES {
            return Err(ExportError::capacity_exceeded());
        }

        let pixel_bytes =
            pixel_storage_bytes(pixel_count).ok_or_else(ExportError::capacity_exceeded)?;
        let mask_bytes = pixel_count;
        let path_bytes = path_points
            .checked_mul(size_of::<[f32; 2]>())
            .and_then(|value| value.checked_add(path_points.checked_mul(24)?))
            .ok_or_else(ExportError::capacity_exceeded)?;
        let work_bytes = pixel_bytes
            .checked_add(mask_bytes)
            .and_then(|value| value.checked_add(raw_bytes))
            .and_then(|value| value.checked_add(path_bytes))
            .and_then(|value| value.checked_add(output_estimate))
            .ok_or_else(ExportError::capacity_exceeded)?;
        if work_bytes > MAX_WORK_BYTES {
            return Err(ExportError::capacity_exceeded());
        }

        Ok(Self {
            width,
            height,
            pixel_count,
            scale,
            clip,
            output_estimate,
        })
    }

    pub(crate) fn width(&self) -> u32 {
        self.width
    }

    pub(crate) fn height(&self) -> u32 {
        self.height
    }

    pub(crate) fn pixel_count(&self) -> usize {
        self.pixel_count
    }

    pub(crate) fn scale(&self) -> f64 {
        self.scale
    }

    pub(crate) fn output_estimate(&self) -> usize {
        self.output_estimate
    }

    pub(crate) fn clip_a8(&self, x: usize, y: usize) -> u8 {
        let x = x as f64;
        let y = y as f64;
        let x_overlap = (self.clip.x_max.min(x + 1.0) - self.clip.x_min.max(x)).max(0.0);
        let y_overlap = (self.clip.y_max.min(y + 1.0) - self.clip.y_min.max(y)).max(0.0);
        let area = (x_overlap * y_overlap).clamp(0.0, 1.0);
        quantize_round_half_even(area)
    }
}

fn checked_dimension(logical_dimension: f64, scale: f64) -> Result<u32, ExportError> {
    if !logical_dimension.is_finite() || logical_dimension <= 0.0 {
        return Err(ExportError::invalid_input());
    }
    let pixels = logical_dimension * scale;
    if !pixels.is_finite() || pixels <= 0.0 {
        return Err(ExportError::capacity_exceeded());
    }
    let rounded_up = pixels.ceil();
    if !rounded_up.is_finite() || rounded_up < 1.0 || rounded_up > f64::from(MAX_DIMENSION) {
        return Err(ExportError::capacity_exceeded());
    }
    let rounded_up = rounded_up as u64;
    u32::try_from(rounded_up).map_err(|_| ExportError::capacity_exceeded())
}

#[cfg(test)]
thread_local! {
    static FORCE_ALLOCATION_FAILURE: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

#[cfg(test)]
pub(crate) fn set_allocation_failure_for_test(fail: bool) {
    FORCE_ALLOCATION_FAILURE.with(|value| value.set(fail));
}

fn allocation_is_forced_to_fail() -> bool {
    #[cfg(test)]
    {
        FORCE_ALLOCATION_FAILURE.with(std::cell::Cell::get)
    }
    #[cfg(not(test))]
    {
        false
    }
}

pub(crate) fn rasterize_series(
    series: &LineSeries,
    plan: &RasterPlan,
) -> Result<Mask, ExportError> {
    if allocation_is_forced_to_fail() {
        return Err(ExportError::allocation_failed());
    }
    let stroke_width = series.style().width() * plan.scale();
    if !stroke_width.is_finite() || stroke_width <= 0.0 || stroke_width > f64::from(f32::MAX) {
        return Err(ExportError::invalid_input());
    }

    let mut path_builder = PathBuilder::new();
    let mut has_line = false;
    for segment in series.segments() {
        let points = segment.points();
        if points.is_empty() {
            continue;
        }
        let first = to_pixel_point(points[0].x(), points[0].y(), plan)?;
        path_builder.move_to(first[0], first[1]);
        let mut previous = first;
        for point in &points[1..] {
            let point = to_pixel_point(point.x(), point.y(), plan)?;
            path_builder.line_to(point[0], point[1]);
            if point != previous {
                has_line = true;
            }
            previous = point;
        }
    }

    let data = zero_mask_data(plan.pixel_count())?;
    let size = IntSize::from_wh(plan.width(), plan.height()).ok_or_else(ExportError::internal)?;
    let mut mask = Mask::from_vec(data, size).ok_or_else(ExportError::allocation_failed)?;
    if !has_line {
        return Ok(mask);
    }

    let path = path_builder.finish().ok_or_else(ExportError::internal)?;
    let stroke = Stroke {
        width: stroke_width as f32,
        miter_limit: 4.0,
        line_cap: LineCap::Butt,
        line_join: LineJoin::Miter,
        dash: None,
    };
    let stroked = path
        .stroke(&stroke, 1.0)
        .ok_or_else(ExportError::internal)?;
    ensure_stroked_path_is_representable(&stroked)?;
    mask.fill_path(&stroked, FillRule::Winding, true, Transform::identity());
    Ok(mask)
}

fn ensure_stroked_path_is_representable(path: &tiny_skia::Path) -> Result<(), ExportError> {
    let bounds = path.bounds();
    let sides = [bounds.left(), bounds.top(), bounds.right(), bounds.bottom()];
    if sides.iter().all(|side| {
        side.is_finite()
            && *side >= -TINY_SKIA_SAFE_PATH_BOUND
            && *side <= TINY_SKIA_SAFE_PATH_BOUND
    }) {
        Ok(())
    } else {
        Err(ExportError::new(
            ExportErrorKind::CapacityExceeded,
            "stroke geometry exceeds rasterizer limits",
        ))
    }
}

fn zero_mask_data(pixel_count: usize) -> Result<Vec<u8>, ExportError> {
    if allocation_is_forced_to_fail() {
        return Err(ExportError::allocation_failed());
    }
    let mut data = Vec::new();
    data.try_reserve_exact(pixel_count)
        .map_err(|_| ExportError::allocation_failed())?;
    data.resize(pixel_count, 0);
    Ok(data)
}

fn to_pixel_point(x: f64, y: f64, plan: &RasterPlan) -> Result<[f32; 2], ExportError> {
    let x = x * plan.scale();
    let y = y * plan.scale();
    validate_pixel_point(x, y, 1.0, plan.width(), plan.height())?;
    Ok([x as f32, y as f32])
}

fn validate_pixel_point(
    x: f64,
    y: f64,
    scale: f64,
    width: u32,
    height: u32,
) -> Result<(), ExportError> {
    let x = x * scale;
    let y = y * scale;
    let max_x = f64::from(width);
    let max_y = f64::from(height);
    if !x.is_finite()
        || !y.is_finite()
        || x < 0.0
        || y < 0.0
        || x > max_x
        || y > max_y
        || x > f64::from(f32::MAX)
        || y > f64::from(f32::MAX)
    {
        return Err(ExportError::invalid_input());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    use lumenplot_engine::bridge::{
        AxisScale, AxisScales, LineFrameSpec, LineStyle, LogicalRect, LogicalSize, PlotScene,
        SeriesData, SeriesTopology, SrgbRgba8, Viewport,
    };

    fn make_frame(style_width: f64) -> lumenplot_engine::bridge::LineFrame {
        let canvas = LogicalSize::new(4.0, 4.0).expect("canvas");
        let plot = LogicalRect::new(0.0, 0.0, 4.0, 4.0).expect("plot");
        let style = LineStyle::new(SrgbRgba8::new(20, 40, 80, 255), style_width).expect("style");
        let frame_spec =
            LineFrameSpec::new(canvas, plot, 1.0, style, SrgbRgba8::new(255, 255, 255, 255))
                .expect("spec");
        let view = Viewport::from_bounds(0.0, 10.0, 0.0, 10.0).expect("view");
        let mut scene = PlotScene::new(view, AxisScales::new(AxisScale::Linear, AxisScale::Linear))
            .expect("scene");
        let data =
            SeriesData::from_owned_xy(SeriesTopology::MonotonicX, vec![0.0, 10.0], vec![0.0, 0.0])
                .expect("data");
        {
            let mut transaction = scene.transaction();
            transaction.add_series(data).expect("series");
            transaction.commit().expect("commit");
        }
        scene
            .snapshot()
            .resolve_line_frame(&frame_spec)
            .expect("frame")
    }

    #[test]
    fn clip_coverage_is_rectangular_and_half_open() {
        let clip = ClipRect {
            x_min: 0.25,
            y_min: 0.5,
            x_max: 1.75,
            y_max: 1.5,
        };
        let plan = RasterPlan {
            width: 2,
            height: 2,
            pixel_count: 4,
            scale: 1.0,
            clip,
            output_estimate: 0,
        };
        assert_eq!(plan.clip_a8(0, 0), quantize_round_half_even(0.375));
        assert_eq!(plan.clip_a8(1, 0), quantize_round_half_even(0.375));
        assert_eq!(plan.clip_a8(0, 1), quantize_round_half_even(0.375));
        assert_eq!(plan.clip_a8(1, 1), quantize_round_half_even(0.375));
    }

    #[test]
    fn dimensions_use_checked_ceil() {
        assert_eq!(checked_dimension(1.0, 1.0).expect("dimension"), 1);
        assert_eq!(checked_dimension(1.01, 1.0).expect("dimension"), 2);
        assert!(checked_dimension(16_384.1, 1.0).is_err());
    }

    #[test]
    fn stroked_path_preflight_rejects_before_fill_and_normal_width_has_coverage() {
        let too_large_frame = make_frame(2.0e38);
        let spec = PngSpec::new(1.0).expect("spec");
        let plan = RasterPlan::new(&too_large_frame, &spec).expect("plan");
        let series = too_large_frame.series().first().expect("series");
        let error = rasterize_series(series, &plan).expect_err("unrepresentable stroke");
        assert_eq!(error.kind(), ExportErrorKind::CapacityExceeded);
        assert_eq!(error.message(), "stroke geometry exceeds rasterizer limits");

        let ordinary_frame = make_frame(1.0);
        let plan = RasterPlan::new(&ordinary_frame, &spec).expect("plan");
        let series = ordinary_frame.series().first().expect("series");
        let mask = rasterize_series(series, &plan).expect("ordinary stroke");
        assert!(mask.data().iter().any(|coverage| *coverage != 0));
    }

    #[test]
    fn stroked_bounds_check_includes_half_stroke_expansion() {
        let centerline = TINY_SKIA_SAFE_PATH_BOUND * 0.75;
        let stroke_width = TINY_SKIA_SAFE_PATH_BOUND * 0.6;
        assert!(stroke_width < TINY_SKIA_SAFE_PATH_BOUND);

        let mut path_builder = PathBuilder::new();
        path_builder.move_to(0.0, centerline);
        path_builder.line_to(1.0, centerline);
        let path = path_builder.finish().expect("path");
        let stroke = Stroke {
            width: stroke_width,
            miter_limit: 4.0,
            line_cap: LineCap::Butt,
            line_join: LineJoin::Miter,
            dash: None,
        };
        let stroked = path.stroke(&stroke, 1.0).expect("stroked path");
        assert!(stroked.bounds().bottom() > TINY_SKIA_SAFE_PATH_BOUND);

        let error = ensure_stroked_path_is_representable(&stroked).expect_err("bounds");
        assert_eq!(error.kind(), ExportErrorKind::CapacityExceeded);
    }
}
