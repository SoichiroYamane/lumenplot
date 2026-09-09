//! Private line-only PDF output.
//!
//! This sink deliberately stops at the existing semantic `LineFrame`: it emits
//! encoded-sRGB `DeviceRGB` vector strokes and a vector background, but does not
//! claim text, fonts, SVG, annotations, axes, Legend, or the full-v1 public
//! export contract. Those capabilities remain pending a separate contract.

use std::fmt;
use std::mem::size_of;

use lumenplot_engine::bridge::LineFrame;

use crate::error::{ExportError, ExportErrorKind};
use crate::raster::{MAX_DIMENSION, MAX_OUTPUT_BYTES, MAX_PATH_POINTS, MAX_WORK_BYTES};

const PDF_POINTS_PER_INCH: f64 = 72.0;
const PDF_MAX_COORDINATE: f64 = MAX_DIMENSION as f64;
const PDF_DECIMAL_PLACES: usize = 6;
const PDF_MIN_REPRESENTABLE_NUMBER: f64 = 0.000_000_5;
const PDF_BOUNDARY_EPSILON: f64 = 1.0e-9;
const PDF_MAX_SERIES: usize = 65_536;
const PDF_MAX_SEGMENTS: usize = 1_000_000;
const PDF_INITIAL_CAPACITY: usize = 1_048_576;

// These are conservative upper bounds for the fixed-point number format and
// operators emitted below. They are used only for preflight; the capped writer
// remains the final protection against output growth.
const PDF_BYTES_PER_POINT: usize = 64;
const PDF_BYTES_PER_SEGMENT: usize = 64;
const PDF_BYTES_PER_SERIES: usize = 256;
const PDF_FIXED_CONTENT_BYTES: usize = 2_048;
const PDF_BYTES_PER_OBJECT: usize = 256;
const PDF_BYTES_PER_XREF_ENTRY: usize = 32;
const PDF_FIXED_OUTPUT_BYTES: usize = 4_096;
const PDF_MAX_XREF_OFFSET: usize = 9_999_999_999;

const PDF_FORMAT_ERROR: &str = "PDF encoding failed";

/// Output provenance for the private vector PDF sink.
///
/// PDF geometry is expressed in points and therefore always uses the PDF
/// constant of 72 points per inch. `output_dpi` is retained as provenance for
/// the upstream request; it intentionally does not rescale vector geometry or
/// introduce a raster fallback.
#[derive(Debug)]
#[allow(dead_code)]
pub(crate) struct PdfSpec {
    output_dpi: f64,
}

impl PdfSpec {
    #[allow(dead_code)]
    pub(crate) fn new(output_dpi: f64) -> Result<Self, ExportError> {
        if !output_dpi.is_finite() || output_dpi <= 0.0 {
            return Err(ExportError::invalid_input());
        }
        Ok(Self { output_dpi })
    }

    fn output_dpi(&self) -> f64 {
        self.output_dpi
    }
}

#[derive(Clone, Copy)]
struct PdfRect {
    x_min: f64,
    y_min: f64,
    x_max: f64,
    y_max: f64,
}

struct PdfPlan {
    page_width: f64,
    page_height: f64,
    logical_to_points: f64,
    plot: PdfRect,
    series_count: usize,
    content_estimate: usize,
    output_estimate: usize,
}

impl PdfPlan {
    fn new(frame: &LineFrame, spec: &PdfSpec) -> Result<Self, ExportError> {
        if !spec.output_dpi().is_finite() || spec.output_dpi() <= 0.0 {
            return Err(ExportError::invalid_input());
        }
        let logical_units_per_inch = frame.logical_units_per_inch();
        if !logical_units_per_inch.is_finite() || logical_units_per_inch <= 0.0 {
            return Err(ExportError::invalid_input());
        }
        let logical_to_points = PDF_POINTS_PER_INCH / logical_units_per_inch;
        if !logical_to_points.is_finite() || logical_to_points <= 0.0 {
            return Err(ExportError::capacity_exceeded());
        }

        let canvas = frame.canvas();
        if !canvas.width().is_finite()
            || !canvas.height().is_finite()
            || canvas.width() <= 0.0
            || canvas.height() <= 0.0
        {
            return Err(ExportError::invalid_input());
        }
        let page_width = logical_to_points_checked(canvas.width(), logical_to_points)?;
        let page_height = logical_to_points_checked(canvas.height(), logical_to_points)?;
        validate_page_dimension(page_width)?;
        validate_page_dimension(page_height)?;

        let logical_plot = frame.plot_rect();
        validate_logical_rect(logical_plot, canvas.width(), canvas.height())?;
        let plot = PdfRect {
            x_min: boundary_coordinate(
                logical_to_points_checked(logical_plot.x_min(), logical_to_points)?,
                page_width,
            )?,
            y_min: boundary_coordinate(
                page_height - logical_to_points_checked(logical_plot.y_max(), logical_to_points)?,
                page_height,
            )?,
            x_max: boundary_coordinate(
                logical_to_points_checked(logical_plot.x_max(), logical_to_points)?,
                page_width,
            )?,
            y_max: boundary_coordinate(
                page_height - logical_to_points_checked(logical_plot.y_min(), logical_to_points)?,
                page_height,
            )?,
        };
        if !plot.x_min.is_finite()
            || !plot.y_min.is_finite()
            || !plot.x_max.is_finite()
            || !plot.y_max.is_finite()
            || plot.x_min >= plot.x_max
            || plot.y_min >= plot.y_max
        {
            return Err(ExportError::invalid_input());
        }

        let series_count = frame.series().len();
        if series_count > PDF_MAX_SERIES {
            return Err(ExportError::capacity_exceeded());
        }

        let mut path_points = 0usize;
        let mut nonempty_segments = 0usize;
        for series in frame.series() {
            let line_width = logical_to_points_checked(series.style().width(), logical_to_points)?;
            validate_stroke_width(line_width)?;
            for segment in series.segments() {
                if segment.points().is_empty() {
                    continue;
                }
                nonempty_segments = nonempty_segments
                    .checked_add(1)
                    .ok_or_else(ExportError::capacity_exceeded)?;
                if nonempty_segments > PDF_MAX_SEGMENTS {
                    return Err(ExportError::capacity_exceeded());
                }
                path_points = path_points
                    .checked_add(segment.points().len())
                    .ok_or_else(ExportError::capacity_exceeded)?;
                if path_points > MAX_PATH_POINTS {
                    return Err(ExportError::capacity_exceeded());
                }
                for point in segment.points() {
                    validate_logical_point(point.x(), point.y(), canvas.width(), canvas.height())?;
                    let _ = pdf_point(
                        point.x(),
                        point.y(),
                        logical_to_points,
                        page_height,
                        page_width,
                    )?;
                }
            }
        }

        let content_estimate = checked_sum(&[
            PDF_FIXED_CONTENT_BYTES,
            path_points
                .checked_mul(PDF_BYTES_PER_POINT)
                .ok_or_else(ExportError::capacity_exceeded)?,
            nonempty_segments
                .checked_mul(PDF_BYTES_PER_SEGMENT)
                .ok_or_else(ExportError::capacity_exceeded)?,
            series_count
                .checked_mul(PDF_BYTES_PER_SERIES)
                .ok_or_else(ExportError::capacity_exceeded)?,
        ])?;
        let object_count = object_count(series_count)?;
        let output_estimate = checked_sum(&[
            content_estimate,
            object_count
                .checked_mul(PDF_BYTES_PER_OBJECT)
                .ok_or_else(ExportError::capacity_exceeded)?,
            object_count
                .checked_mul(PDF_BYTES_PER_XREF_ENTRY)
                .ok_or_else(ExportError::capacity_exceeded)?,
            PDF_FIXED_OUTPUT_BYTES,
        ])?;
        if output_estimate > MAX_OUTPUT_BYTES {
            return Err(ExportError::capacity_exceeded());
        }
        let offsets_bytes = object_count
            .checked_mul(size_of::<usize>())
            .ok_or_else(ExportError::capacity_exceeded)?;
        let work_bytes = checked_sum(&[content_estimate, output_estimate, offsets_bytes])?;
        if work_bytes > MAX_WORK_BYTES {
            return Err(ExportError::capacity_exceeded());
        }

        Ok(Self {
            page_width,
            page_height,
            logical_to_points,
            plot,
            series_count,
            content_estimate,
            output_estimate,
        })
    }

    fn object_count(&self) -> Result<usize, ExportError> {
        object_count(self.series_count)
    }

    fn info_object_id(&self) -> Result<usize, ExportError> {
        6usize
            .checked_add(self.series_count)
            .ok_or_else(ExportError::capacity_exceeded)
    }
}

fn object_count(series_count: usize) -> Result<usize, ExportError> {
    // Objects: catalog, pages, page, contents, background ExtGState, one line
    // ExtGState per series, and the provenance Info dictionary.
    series_count
        .checked_add(6)
        .ok_or_else(ExportError::capacity_exceeded)
}

fn checked_sum(values: &[usize]) -> Result<usize, ExportError> {
    values.iter().try_fold(0usize, |sum, value| {
        sum.checked_add(*value)
            .ok_or_else(ExportError::capacity_exceeded)
    })
}

fn logical_to_points_checked(value: f64, scale: f64) -> Result<f64, ExportError> {
    if !value.is_finite() || !scale.is_finite() || scale <= 0.0 {
        return Err(ExportError::invalid_input());
    }
    let points = value * scale;
    if !points.is_finite() {
        return Err(ExportError::capacity_exceeded());
    }
    Ok(points)
}

fn validate_page_dimension(value: f64) -> Result<(), ExportError> {
    if !value.is_finite() || !(PDF_MIN_REPRESENTABLE_NUMBER..=PDF_MAX_COORDINATE).contains(&value) {
        return Err(ExportError::capacity_exceeded());
    }
    Ok(())
}

fn validate_stroke_width(value: f64) -> Result<(), ExportError> {
    if !value.is_finite() || !(PDF_MIN_REPRESENTABLE_NUMBER..=PDF_MAX_COORDINATE).contains(&value) {
        return Err(ExportError::capacity_exceeded());
    }
    Ok(())
}

fn validate_logical_rect(
    rect: lumenplot_engine::bridge::LogicalRect,
    canvas_width: f64,
    canvas_height: f64,
) -> Result<(), ExportError> {
    if !rect.x_min().is_finite()
        || !rect.y_min().is_finite()
        || !rect.x_max().is_finite()
        || !rect.y_max().is_finite()
        || rect.x_min() < 0.0
        || rect.y_min() < 0.0
        || rect.x_min() >= rect.x_max()
        || rect.y_min() >= rect.y_max()
        || rect.x_max() > canvas_width
        || rect.y_max() > canvas_height
    {
        return Err(ExportError::invalid_input());
    }
    Ok(())
}

fn validate_logical_point(
    x: f64,
    y: f64,
    canvas_width: f64,
    canvas_height: f64,
) -> Result<(), ExportError> {
    if !x.is_finite()
        || !y.is_finite()
        || x < 0.0
        || y < 0.0
        || x > canvas_width
        || y > canvas_height
    {
        return Err(ExportError::invalid_input());
    }
    Ok(())
}

fn boundary_coordinate(value: f64, maximum: f64) -> Result<f64, ExportError> {
    if !value.is_finite() || !maximum.is_finite() || maximum <= 0.0 {
        return Err(ExportError::capacity_exceeded());
    }
    if value < -PDF_BOUNDARY_EPSILON || value > maximum + PDF_BOUNDARY_EPSILON {
        return Err(ExportError::invalid_input());
    }
    if value < 0.0 {
        Ok(0.0)
    } else if value > maximum {
        Ok(maximum)
    } else if value == 0.0 {
        Ok(0.0)
    } else {
        Ok(value)
    }
}

fn pdf_point(
    x: f64,
    y: f64,
    logical_to_points: f64,
    page_height: f64,
    page_width: f64,
) -> Result<(f64, f64), ExportError> {
    let x = logical_to_points_checked(x, logical_to_points)?;
    let y_from_top = logical_to_points_checked(y, logical_to_points)?;
    let y = page_height - y_from_top;
    Ok((
        boundary_coordinate(x, page_width)?,
        boundary_coordinate(y, page_height)?,
    ))
}

#[allow(dead_code)]
pub(crate) fn encode_line_frame_pdf(
    frame: &LineFrame,
    spec: &PdfSpec,
) -> Result<Vec<u8>, ExportError> {
    let plan = PdfPlan::new(frame, spec)?;
    let content = build_content(frame, &plan)?;

    let mut output = PdfWriter::new(plan.output_estimate, MAX_OUTPUT_BYTES)?;
    let mut offsets = fallible_offsets(plan.object_count()?)?;
    offsets.push(0);

    output.write_bytes(b"%PDF-1.4\n%LumenPlot\n")?;
    offsets.push(output.len());
    write_object_header(&mut output, 1)?;
    output.write_str_checked("<< /Type /Catalog /Pages 2 0 R >>\n")?;
    write_object_footer(&mut output)?;

    offsets.push(output.len());
    write_object_header(&mut output, 2)?;
    output.write_str_checked("<< /Type /Pages /Kids [3 0 R] /Count 1 >>\n")?;
    write_object_footer(&mut output)?;

    offsets.push(output.len());
    write_object_header(&mut output, 3)?;
    write_page(&mut output, &plan)?;
    write_object_footer(&mut output)?;

    offsets.push(output.len());
    write_object_header(&mut output, 4)?;
    output.write_fmt_checked(format_args!("<< /Length {} >>\nstream\n", content.len()))?;
    output.write_bytes(&content)?;
    output.write_str_checked("\nendstream\n")?;
    write_object_footer(&mut output)?;

    offsets.push(output.len());
    write_object_header(&mut output, 5)?;
    write_ext_gstate(&mut output, frame.background().a())?;
    write_object_footer(&mut output)?;

    for (index, series) in frame.series().iter().enumerate() {
        offsets.push(output.len());
        let object_id = 6usize
            .checked_add(index)
            .ok_or_else(ExportError::capacity_exceeded)?;
        write_object_header(&mut output, object_id)?;
        write_ext_gstate(&mut output, series.style().color().a())?;
        write_object_footer(&mut output)?;
    }

    let info_object_id = plan.info_object_id()?;
    offsets.push(output.len());
    write_object_header(&mut output, info_object_id)?;
    write_info(
        &mut output,
        frame.logical_units_per_inch(),
        spec.output_dpi(),
    )?;
    write_object_footer(&mut output)?;

    let expected_offsets = plan
        .object_count()?
        .checked_add(1)
        .ok_or_else(ExportError::capacity_exceeded)?;
    if offsets.len() != expected_offsets {
        return Err(ExportError::internal());
    }
    let xref_offset = output.len();
    write_xref(&mut output, &offsets, info_object_id)?;
    if xref_offset > PDF_MAX_XREF_OFFSET {
        return Err(ExportError::capacity_exceeded());
    }
    output.write_fmt_checked(format_args!("startxref\n{xref_offset}\n%%EOF\n"))?;
    Ok(output.into_inner())
}

fn build_content(frame: &LineFrame, plan: &PdfPlan) -> Result<Vec<u8>, ExportError> {
    let mut content = PdfWriter::new(plan.content_estimate, MAX_OUTPUT_BYTES)?;

    content.write_str_checked("q\n")?;
    content.write_str_checked("/BG gs\n")?;
    write_color(&mut content, frame.background(), "rg")?;
    content.write_str_checked("0 0 ")?;
    write_pdf_number(&mut content, plan.page_width)?;
    content.write_str_checked(" ")?;
    write_pdf_number(&mut content, plan.page_height)?;
    content.write_str_checked(" re\nf\nQ\n")?;

    content.write_str_checked("q\n")?;
    write_pdf_number(&mut content, plan.plot.x_min)?;
    content.write_str_checked(" ")?;
    write_pdf_number(&mut content, plan.plot.y_min)?;
    content.write_str_checked(" ")?;
    write_pdf_number(&mut content, plan.plot.x_max - plan.plot.x_min)?;
    content.write_str_checked(" ")?;
    write_pdf_number(&mut content, plan.plot.y_max - plan.plot.y_min)?;
    content.write_str_checked(" re\nW\nn\n")?;

    for (index, series) in frame.series().iter().enumerate() {
        if series
            .segments()
            .iter()
            .all(|segment| segment.points().is_empty())
        {
            continue;
        }
        content.write_fmt_checked(format_args!("/L{index} gs\n"))?;
        write_color(&mut content, series.style().color(), "RG")?;
        let line_width = logical_to_points_checked(series.style().width(), plan.logical_to_points)?;
        write_pdf_number(&mut content, line_width)?;
        content.write_str_checked(" w\n1 J\n0 j\n4 M\n")?;

        for segment in series.segments() {
            let points = segment.points();
            if points.is_empty() {
                continue;
            }
            write_path_point(&mut content, points[0].x(), points[0].y(), plan, "m")?;
            for point in &points[1..] {
                write_path_point(&mut content, point.x(), point.y(), plan, "l")?;
            }
            content.write_str_checked("S\n")?;
        }
    }
    content.write_str_checked("Q\n")?;

    if content.len() > plan.content_estimate {
        return Err(ExportError::capacity_exceeded());
    }
    Ok(content.into_inner())
}

fn write_path_point(
    output: &mut PdfWriter,
    x: f64,
    y: f64,
    plan: &PdfPlan,
    operator: &str,
) -> Result<(), ExportError> {
    let (x, y) = pdf_point(
        x,
        y,
        plan.logical_to_points,
        plan.page_height,
        plan.page_width,
    )?;
    write_pdf_number(output, x)?;
    output.write_str_checked(" ")?;
    write_pdf_number(output, y)?;
    output.write_fmt_checked(format_args!(" {operator}\n"))
}

fn write_page(output: &mut PdfWriter, plan: &PdfPlan) -> Result<(), ExportError> {
    output.write_str_checked("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ")?;
    write_pdf_number(output, plan.page_width)?;
    output.write_str_checked(" ")?;
    write_pdf_number(output, plan.page_height)?;
    output.write_str_checked(
        "] /Resources << /ProcSet [/PDF] /ColorSpace << /RGB /DeviceRGB >> /ExtGState << /BG 5 0 R",
    )?;
    for index in 0..plan.series_count {
        let object_id = 6usize
            .checked_add(index)
            .ok_or_else(ExportError::capacity_exceeded)?;
        output.write_fmt_checked(format_args!(" /L{index} {object_id} 0 R"))?;
    }
    output.write_str_checked(" >> >> /Contents 4 0 R >>\n")
}

fn write_ext_gstate(output: &mut PdfWriter, alpha: u8) -> Result<(), ExportError> {
    let alpha = f64::from(alpha) / 255.0;
    output.write_str_checked("<< /Type /ExtGState /CA ")?;
    write_pdf_number(output, alpha)?;
    output.write_str_checked(" /ca ")?;
    write_pdf_number(output, alpha)?;
    output.write_str_checked(" >>\n")
}

fn write_info(
    output: &mut PdfWriter,
    logical_units_per_inch: f64,
    output_dpi: f64,
) -> Result<(), ExportError> {
    output.write_str_checked(
        "<< /Producer (LumenPlot private line PDF sink) /LPFormat (private-line-vector-v1) /LPLogicalUnitsPerInch (",
    )?;
    write_pdf_number(output, logical_units_per_inch)?;
    output.write_str_checked(") /LPOutputDpi (")?;
    write_pdf_number(output, output_dpi)?;
    output.write_str_checked(") >>\n")
}

fn write_color(
    output: &mut PdfWriter,
    color: lumenplot_engine::bridge::SrgbRgba8,
    operator: &str,
) -> Result<(), ExportError> {
    write_pdf_number(output, f64::from(color.r()) / 255.0)?;
    output.write_str_checked(" ")?;
    write_pdf_number(output, f64::from(color.g()) / 255.0)?;
    output.write_str_checked(" ")?;
    write_pdf_number(output, f64::from(color.b()) / 255.0)?;
    output.write_fmt_checked(format_args!(" {operator}\n"))
}

fn write_pdf_number(output: &mut PdfWriter, value: f64) -> Result<(), ExportError> {
    if !value.is_finite() {
        return Err(ExportError::invalid_input());
    }
    let value = if value == 0.0 { 0.0 } else { value };
    output.write_fmt_checked(format_args!(
        "{value:.precision$}",
        precision = PDF_DECIMAL_PLACES
    ))
}

fn write_object_header(output: &mut PdfWriter, object_id: usize) -> Result<(), ExportError> {
    output.write_fmt_checked(format_args!("{object_id} 0 obj\n"))
}

fn write_object_footer(output: &mut PdfWriter) -> Result<(), ExportError> {
    output.write_str_checked("endobj\n")
}

fn write_xref(
    output: &mut PdfWriter,
    offsets: &[usize],
    info_object_id: usize,
) -> Result<(), ExportError> {
    let size = offsets.len();
    output.write_fmt_checked(format_args!("xref\n0 {size}\n"))?;
    output.write_str_checked("0000000000 65535 f \n")?;
    for offset in offsets.iter().skip(1) {
        if *offset > PDF_MAX_XREF_OFFSET {
            return Err(ExportError::capacity_exceeded());
        }
        output.write_fmt_checked(format_args!("{offset:010} 00000 n \n"))?;
    }
    output.write_fmt_checked(format_args!(
        "trailer\n<< /Size {size} /Root 1 0 R /Info {info_object_id} 0 R >>\n"
    ))
}

struct PdfWriter {
    bytes: Vec<u8>,
    limit: usize,
    failure: Option<ExportError>,
}

impl PdfWriter {
    fn new(initial_estimate: usize, limit: usize) -> Result<Self, ExportError> {
        if initial_estimate > limit {
            return Err(ExportError::capacity_exceeded());
        }
        if allocation_is_forced_to_fail() {
            return Err(ExportError::allocation_failed());
        }
        let mut bytes = Vec::new();
        bytes
            .try_reserve(initial_estimate.min(PDF_INITIAL_CAPACITY))
            .map_err(|_| ExportError::allocation_failed())?;
        Ok(Self {
            bytes,
            limit,
            failure: None,
        })
    }

    fn write_bytes(&mut self, bytes: &[u8]) -> Result<(), ExportError> {
        let remaining = self
            .limit
            .checked_sub(self.bytes.len())
            .ok_or_else(ExportError::capacity_exceeded)?;
        if bytes.len() > remaining {
            return self.record_failure(ExportError::capacity_exceeded());
        }
        if bytes.is_empty() {
            return Ok(());
        }
        if allocation_is_forced_to_fail() {
            return self.record_failure(ExportError::allocation_failed());
        }
        self.bytes
            .try_reserve(bytes.len())
            .map_err(|_| ExportError::allocation_failed())?;
        self.bytes.extend_from_slice(bytes);
        Ok(())
    }

    fn write_str_checked(&mut self, value: &str) -> Result<(), ExportError> {
        self.write_bytes(value.as_bytes())
    }

    fn write_fmt_checked(&mut self, arguments: fmt::Arguments<'_>) -> Result<(), ExportError> {
        if fmt::write(self, arguments).is_err() {
            return Err(self.failure.clone().unwrap_or_else(pdf_encoding_failed));
        }
        Ok(())
    }

    fn record_failure(&mut self, error: ExportError) -> Result<(), ExportError> {
        self.failure = Some(error.clone());
        Err(error)
    }

    fn len(&self) -> usize {
        self.bytes.len()
    }

    fn into_inner(self) -> Vec<u8> {
        self.bytes
    }
}

impl fmt::Write for PdfWriter {
    fn write_str(&mut self, value: &str) -> fmt::Result {
        self.write_bytes(value.as_bytes()).map_err(|error| {
            self.failure = Some(error);
            fmt::Error
        })
    }
}

fn pdf_encoding_failed() -> ExportError {
    ExportError::new(ExportErrorKind::EncodingFailed, PDF_FORMAT_ERROR)
}

fn fallible_offsets(object_count: usize) -> Result<Vec<usize>, ExportError> {
    if allocation_is_forced_to_fail() {
        return Err(ExportError::allocation_failed());
    }
    let mut offsets = Vec::new();
    let offset_count = object_count
        .checked_add(1)
        .ok_or_else(ExportError::capacity_exceeded)?;
    offsets
        .try_reserve_exact(offset_count)
        .map_err(|_| ExportError::allocation_failed())?;
    Ok(offsets)
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

#[cfg(test)]
mod tests {
    use std::str;

    use super::*;
    use lumenplot_engine::bridge::{
        AxisScale, AxisScales, LineFrameSpec, LineStyle, LogicalRect, LogicalSize, PlotScene,
        SeriesData, SeriesTopology, SrgbRgba8, Viewport,
    };

    fn make_frame(
        logical_units_per_inch: f64,
        line_color: SrgbRgba8,
        line_width: f64,
        background: SrgbRgba8,
    ) -> lumenplot_engine::bridge::LineFrame {
        let canvas = LogicalSize::new(8.0, 4.0).expect("canvas");
        let plot = LogicalRect::new(0.0, 0.0, 8.0, 4.0).expect("plot");
        let style = LineStyle::new(line_color, line_width).expect("style");
        let frame_spec =
            LineFrameSpec::new(canvas, plot, logical_units_per_inch, style, background)
                .expect("frame spec");
        let view = Viewport::from_bounds(0.0, 10.0, 0.0, 10.0).expect("view");
        let mut scene = PlotScene::new(view, AxisScales::new(AxisScale::Linear, AxisScale::Linear))
            .expect("scene");
        let data = SeriesData::from_owned_xy(
            SeriesTopology::ArbitraryXY,
            vec![0.0, 10.0],
            vec![10.0, 0.0],
        )
        .expect("data");
        {
            let mut transaction = scene.transaction();
            transaction.add_series(data).expect("series");
            transaction.commit().expect("commit");
        }
        scene
            .snapshot()
            .resolve_line_frame(&frame_spec)
            .expect("line frame")
    }

    fn content(bytes: &[u8]) -> &str {
        let start = bytes
            .windows(7)
            .position(|window| window == b"stream\n")
            .expect("stream")
            + 7;
        let end = bytes[start..]
            .windows(10)
            .position(|window| window == b"\nendstream")
            .expect("endstream")
            + start;
        str::from_utf8(&bytes[start..end]).expect("content UTF-8")
    }

    fn assert_structurally_valid(bytes: &[u8]) {
        assert!(bytes.starts_with(b"%PDF-1.4\n%LumenPlot\n"));
        assert!(bytes.ends_with(b"%%EOF\n"));
        assert!(!bytes.windows(15).any(|window| window == b"/Subtype /Image"));
        assert!(!bytes.windows(2).any(|window| window == b"BI"));

        let text = str::from_utf8(bytes).expect("PDF text");
        let startxref_marker = "startxref\n";
        let startxref = text.rfind(startxref_marker).expect("startxref") + startxref_marker.len();
        let xref_offset: usize = text[startxref..]
            .split('\n')
            .next()
            .expect("xref offset")
            .parse()
            .expect("numeric xref offset");
        assert_eq!(&text[xref_offset..xref_offset + 4], "xref");

        let xref_end = text[xref_offset..].find("trailer\n").expect("trailer") + xref_offset;
        let xref = &text[xref_offset..xref_end];
        let mut lines = xref.lines();
        assert_eq!(lines.next(), Some("xref"));
        let header = lines.next().expect("xref header");
        let size: usize = header
            .split_whitespace()
            .nth(1)
            .expect("xref size")
            .parse()
            .expect("xref size number");
        let free = lines.next().expect("free xref entry");
        assert!(free.ends_with(" f "));
        let entries: Vec<&str> = lines.collect();
        assert_eq!(entries.len() + 1, size);
        for (object_id, entry) in entries
            .iter()
            .enumerate()
            .map(|(index, entry)| (index + 1, entry))
        {
            assert!(entry.ends_with(" n "), "bad xref entry: {entry}");
            let offset: usize = entry
                .split_whitespace()
                .next()
                .expect("object offset")
                .parse()
                .expect("object offset number");
            let marker = format!("{object_id} 0 obj\n");
            assert_eq!(&text[offset..offset + marker.len()], marker);
        }

        let trailer = &text[xref_end..];
        assert!(trailer.contains("/Root 1 0 R"));
        assert!(trailer.contains("/Info "));
    }

    #[test]
    fn emits_deterministic_structurally_valid_vector_pdf() {
        let frame = make_frame(
            96.0,
            SrgbRgba8::new(255, 0, 0, 128),
            2.0,
            SrgbRgba8::new(10, 20, 30, 64),
        );
        let spec = PdfSpec::new(300.0).expect("PDF spec");
        let first = encode_line_frame_pdf(&frame, &spec).expect("PDF");
        let second = encode_line_frame_pdf(&frame, &spec).expect("PDF");
        assert_eq!(first, second);
        assert_structurally_valid(&first);

        let body = str::from_utf8(&first).expect("PDF body");
        assert!(body.contains("/MediaBox [0 0 6.000000 3.000000]"));
        assert!(body.contains("/LPLogicalUnitsPerInch (96.000000)"));
        assert!(body.contains("/LPOutputDpi (300.000000)"));
        assert!(body.contains("/Type /ExtGState"));
        assert!(body.contains("/CA 0.501961 /ca 0.501961"));
        assert!(body.contains("/CA 0.250980 /ca 0.250980"));

        let drawing = content(&first);
        assert!(drawing.contains("1.000000 0.000000 0.000000 RG"));
        assert!(drawing.contains("1.500000 w"));
        assert!(drawing.contains("0.000000 3.000000 m\n6.000000 0.000000 l\nS\n"));
        assert!(drawing.contains("/L0 gs"));
        assert!(drawing.contains("0 0 6.000000 3.000000 re\nf"));
        assert!(drawing.contains("W\nn"));
        assert!(!drawing.contains("/Subtype /Image"));
    }

    #[test]
    fn logical_units_change_physical_page_but_output_dpi_is_provenance_only() {
        let frame_96 = make_frame(
            96.0,
            SrgbRgba8::new(0, 0, 0, 255),
            1.0,
            SrgbRgba8::new(255, 255, 255, 255),
        );
        let frame_144 = make_frame(
            144.0,
            SrgbRgba8::new(0, 0, 0, 255),
            1.0,
            SrgbRgba8::new(255, 255, 255, 255),
        );
        let low_dpi = PdfSpec::new(72.0).expect("PDF spec");
        let high_dpi = PdfSpec::new(600.0).expect("PDF spec");
        let first = encode_line_frame_pdf(&frame_96, &low_dpi).expect("PDF");
        let second = encode_line_frame_pdf(&frame_96, &high_dpi).expect("PDF");
        let third = encode_line_frame_pdf(&frame_144, &high_dpi).expect("PDF");
        let first_text = str::from_utf8(&first).expect("PDF");
        let second_text = str::from_utf8(&second).expect("PDF");
        let third_text = str::from_utf8(&third).expect("PDF");

        assert!(first_text.contains("/MediaBox [0 0 6.000000 3.000000]"));
        assert!(second_text.contains("/MediaBox [0 0 6.000000 3.000000]"));
        assert!(third_text.contains("/MediaBox [0 0 4.000000 2.000000]"));
        assert!(first_text.contains("/LPOutputDpi (72.000000)"));
        assert!(second_text.contains("/LPOutputDpi (600.000000)"));
        assert!(third_text.contains("/LPLogicalUnitsPerInch (144.000000)"));
        assert!(content(&first).contains("0.000000 3.000000 m\n6.000000 0.000000 l\nS\n"));
        assert!(content(&third).contains("0.000000 2.000000 m\n4.000000 0.000000 l\nS\n"));
    }

    #[test]
    fn rejects_invalid_or_unrepresentable_pdf_requests_before_output() {
        for dpi in [0.0, -1.0, f64::NAN, f64::INFINITY] {
            assert_eq!(
                PdfSpec::new(dpi).expect_err("invalid DPI"),
                ExportError::invalid_input()
            );
        }

        let huge_canvas = LogicalSize::new(30_000.0, 4.0).expect("canvas");
        let huge_plot = LogicalRect::new(0.0, 0.0, 30_000.0, 4.0).expect("plot");
        let style = LineStyle::new(SrgbRgba8::new(0, 0, 0, 255), 1.0).expect("style");
        let spec = LineFrameSpec::new(
            huge_canvas,
            huge_plot,
            96.0,
            style,
            SrgbRgba8::new(255, 255, 255, 255),
        )
        .expect("frame spec");
        let view = Viewport::from_bounds(0.0, 10.0, 0.0, 10.0).expect("view");
        let mut scene = PlotScene::new(view, AxisScales::new(AxisScale::Linear, AxisScale::Linear))
            .expect("scene");
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
        let frame = scene
            .snapshot()
            .resolve_line_frame(&spec)
            .expect("line frame");
        let error = encode_line_frame_pdf(&frame, &PdfSpec::new(300.0).expect("PDF spec"))
            .expect_err("page limit");
        assert_eq!(error.kind(), ExportErrorKind::CapacityExceeded);
    }

    #[test]
    fn allocation_failure_is_reported_without_partial_pdf() {
        let frame = make_frame(
            96.0,
            SrgbRgba8::new(0, 0, 0, 255),
            1.0,
            SrgbRgba8::new(255, 255, 255, 255),
        );
        let spec = PdfSpec::new(300.0).expect("PDF spec");
        crate::set_allocation_failure_for_test(true);
        let error = encode_line_frame_pdf(&frame, &spec).expect_err("allocation failure");
        crate::set_allocation_failure_for_test(false);
        assert_eq!(error.kind(), ExportErrorKind::AllocationFailed);
    }
}
