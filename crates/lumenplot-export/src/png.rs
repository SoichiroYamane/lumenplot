use std::io::{self, Write};

use png::{BitDepth, ColorType, Compression, Encoder, Filter, SrgbRenderingIntent};

use crate::compositor::{composite_mask, new_pixels, to_rgba8};
use crate::error::ExportError;
use crate::raster::{self, RasterPlan};

pub struct PngSpec {
    output_dpi: f64,
}

impl PngSpec {
    pub fn new(output_dpi: f64) -> Result<Self, ExportError> {
        if !output_dpi.is_finite() || output_dpi <= 0.0 {
            return Err(ExportError::invalid_input());
        }
        Ok(Self { output_dpi })
    }

    pub(crate) fn output_dpi(&self) -> f64 {
        self.output_dpi
    }
}

pub fn encode_line_frame_png(
    frame: &lumenplot_engine::bridge::LineFrame,
    spec: &PngSpec,
) -> Result<Vec<u8>, ExportError> {
    let plan = RasterPlan::new(frame, spec)?;
    let background = frame.background();
    let background = [
        background.r(),
        background.g(),
        background.b(),
        background.a(),
    ];
    let mut pixels = new_pixels(plan.pixel_count(), background)?;

    for series in frame.series() {
        let mask = raster::rasterize_series(series, &plan)?;
        let color = series.style().color();
        let color = [color.r(), color.g(), color.b(), color.a()];
        composite_mask(
            &mut pixels,
            &mask,
            &plan,
            color,
            plan.width(),
            plan.height(),
        )?;
    }

    let rgba = to_rgba8(&pixels)?;
    encode_png(plan.width(), plan.height(), &rgba, plan.output_estimate())
}

fn encode_png(
    width: u32,
    height: u32,
    rgba: &[u8],
    output_estimate: usize,
) -> Result<Vec<u8>, ExportError> {
    let expected = usize::try_from(width)
        .ok()
        .and_then(|width| {
            usize::try_from(height)
                .ok()
                .and_then(|height| width.checked_mul(height))
        })
        .and_then(|pixels| pixels.checked_mul(4))
        .ok_or_else(ExportError::capacity_exceeded)?;
    if expected != rgba.len() {
        return Err(ExportError::internal());
    }

    let mut sink = CappedWriter::new(output_estimate)?;
    {
        let mut encoder = Encoder::new(&mut sink, width, height);
        encoder.set_color(ColorType::Rgba);
        encoder.set_depth(BitDepth::Eight);
        encoder.set_source_srgb(SrgbRenderingIntent::Perceptual);
        encoder.set_compression(Compression::NoCompression);
        encoder.set_filter(Filter::NoFilter);
        let mut writer = encoder
            .write_header()
            .map_err(|_| ExportError::encoding_failed())?;
        writer
            .write_image_data(rgba)
            .map_err(|_| ExportError::encoding_failed())?;
        writer
            .finish()
            .map_err(|_| ExportError::encoding_failed())?;
    }
    Ok(sink.into_inner())
}

struct CappedWriter {
    bytes: Vec<u8>,
    limit: usize,
}

impl CappedWriter {
    fn new(output_estimate: usize) -> Result<Self, ExportError> {
        if output_estimate > raster::MAX_OUTPUT_BYTES {
            return Err(ExportError::capacity_exceeded());
        }
        let initial_capacity = output_estimate.min(1_048_576);
        let mut bytes = Vec::new();
        bytes
            .try_reserve(initial_capacity)
            .map_err(|_| ExportError::allocation_failed())?;
        Ok(Self {
            bytes,
            limit: raster::MAX_OUTPUT_BYTES,
        })
    }

    fn into_inner(self) -> Vec<u8> {
        self.bytes
    }
}

impl Write for CappedWriter {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        let remaining = self.limit.saturating_sub(self.bytes.len());
        if bytes.len() > remaining {
            return Err(io::Error::other("PNG output capacity exceeded"));
        }
        self.bytes
            .try_reserve(bytes.len())
            .map_err(|_| io::Error::other("PNG output allocation failed"))?;
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use std::collections::hash_map::DefaultHasher;
    use std::hash::{Hash, Hasher};
    use std::io::Cursor;

    use super::*;
    use lumenplot_engine::bridge::{
        AxisScale, AxisScales, LineFrameSpec, LineStyle, LogicalRect, LogicalSize, PlotScene,
        SeriesData, SeriesTopology, SrgbRgba8, Viewport,
    };

    fn make_frame(
        canvas: (f64, f64),
        plot: (f64, f64, f64, f64),
        output_dpi: f64,
        points: (Vec<f64>, Vec<f64>),
        style: (SrgbRgba8, f64),
        background: SrgbRgba8,
    ) -> (LineFrameSpec, lumenplot_engine::bridge::LineFrame, PngSpec) {
        let canvas = LogicalSize::new(canvas.0, canvas.1).expect("canvas");
        let plot = LogicalRect::new(plot.0, plot.1, plot.2, plot.3).expect("plot");
        let style = LineStyle::new(style.0, style.1).expect("style");
        let frame_spec = LineFrameSpec::new(canvas, plot, 1.0, style, background).expect("spec");
        let view = Viewport::from_bounds(0.0, 10.0, 0.0, 10.0).expect("view");
        let mut scene = PlotScene::new(view, AxisScales::new(AxisScale::Linear, AxisScale::Linear))
            .expect("scene");
        let data = SeriesData::from_owned_xy(SeriesTopology::MonotonicX, points.0, points.1)
            .expect("data");
        {
            let mut transaction = scene.transaction();
            transaction.add_series(data).expect("series");
            transaction.commit().expect("commit");
        }
        let frame = scene
            .snapshot()
            .resolve_line_frame(&frame_spec)
            .expect("frame");
        let png_spec = PngSpec::new(output_dpi).expect("png spec");
        (frame_spec, frame, png_spec)
    }

    fn chunks(bytes: &[u8]) -> Vec<([u8; 4], Vec<u8>)> {
        assert_eq!(&bytes[..8], b"\x89PNG\r\n\x1a\n");
        let mut offset = 8;
        let mut chunks = Vec::new();
        while offset < bytes.len() {
            let length =
                u32::from_be_bytes(bytes[offset..offset + 4].try_into().expect("length")) as usize;
            let kind: [u8; 4] = bytes[offset + 4..offset + 8].try_into().expect("kind");
            let data_start = offset + 8;
            let data_end = data_start + length;
            let crc_end = data_end + 4;
            assert!(crc_end <= bytes.len());
            chunks.push((kind, bytes[data_start..data_end].to_vec()));
            offset = crc_end;
        }
        assert_eq!(offset, bytes.len());
        chunks
    }

    fn decode_rgba(bytes: &[u8]) -> (u32, u32, Vec<u8>) {
        let decoder = png::Decoder::new(Cursor::new(bytes));
        let mut reader = decoder.read_info().expect("header");
        let size = reader.output_buffer_size().expect("buffer size");
        let mut data = vec![0; size];
        let info = reader.next_frame(&mut data).expect("frame");
        data.truncate(info.buffer_size());
        (info.width, info.height, data)
    }

    #[test]
    fn png_has_only_the_contract_chunks() {
        let (_, frame, spec) = make_frame(
            (4.0, 3.0),
            (0.5, 0.25, 3.5, 2.75),
            2.0,
            (vec![0.0, 5.0, 10.0], vec![0.0, 10.0, 0.0]),
            (SrgbRgba8::new(255, 0, 0, 255), 1.0),
            SrgbRgba8::new(255, 255, 255, 255),
        );
        let bytes = encode_line_frame_png(&frame, &spec).expect("PNG");
        let chunks = chunks(&bytes);
        let names: Vec<[u8; 4]> = chunks.iter().map(|(kind, _)| *kind).collect();
        assert_eq!(names.first(), Some(b"IHDR"));
        assert_eq!(names.get(1), Some(b"sRGB"));
        assert_eq!(names.last(), Some(b"IEND"));
        assert!(names[2..names.len() - 1].iter().all(|kind| kind == b"IDAT"));
        assert_eq!(chunks[1].1, vec![0]);
        assert!(!names.iter().any(|kind| {
            matches!(
                kind,
                b"pHYs"
                    | b"gAMA"
                    | b"cHRM"
                    | b"iCCP"
                    | b"tEXt"
                    | b"tIME"
                    | b"PLTE"
                    | b"tRNS"
                    | b"acTL"
                    | b"fcTL"
                    | b"fdAT"
            )
        }));
        let ihdr = &chunks[0].1;
        assert_eq!(u32::from_be_bytes(ihdr[0..4].try_into().expect("width")), 8);
        assert_eq!(
            u32::from_be_bytes(ihdr[4..8].try_into().expect("height")),
            6
        );
        assert_eq!(ihdr[8..], [8, 6, 0, 0, 0]);
    }

    #[test]
    fn scale_changes_only_pixel_extent() {
        let (_, frame, one) = make_frame(
            (3.0, 2.0),
            (0.0, 0.0, 3.0, 2.0),
            1.0,
            (vec![0.0, 10.0], vec![0.0, 10.0]),
            (SrgbRgba8::new(0, 0, 0, 255), 1.0),
            SrgbRgba8::new(255, 255, 255, 255),
        );
        let two = PngSpec::new(2.0).expect("spec");
        let three = PngSpec::new(3.0).expect("spec");
        for (spec, expected) in [(&one, (3, 2)), (&two, (6, 4)), (&three, (9, 6))] {
            let bytes = encode_line_frame_png(&frame, spec).expect("PNG");
            let chunks = chunks(&bytes);
            let ihdr = &chunks[0].1;
            assert_eq!(
                (
                    u32::from_be_bytes(ihdr[0..4].try_into().expect("width")),
                    u32::from_be_bytes(ihdr[4..8].try_into().expect("height")),
                ),
                expected,
            );
        }
    }

    #[test]
    fn fractional_canvas_extent_uses_ceil_at_each_axis() {
        let (_, frame, spec) = make_frame(
            (1.25, 2.5),
            (0.0, 0.0, 1.25, 2.5),
            2.0,
            (vec![0.0, 10.0], vec![0.0, 10.0]),
            (SrgbRgba8::new(0, 0, 0, 255), 1.0),
            SrgbRgba8::new(255, 255, 255, 255),
        );
        let bytes = encode_line_frame_png(&frame, &spec).expect("PNG");
        let (width, height, _) = decode_rgba(&bytes);
        assert_eq!((width, height), (3, 5));
    }

    #[test]
    fn stroke_width_matrix_and_miter_corner_are_supported() {
        for width in [0.5, 1.0, 2.0] {
            let (_, frame, spec) = make_frame(
                (4.0, 4.0),
                (0.0, 0.0, 4.0, 4.0),
                1.0,
                (vec![0.0, 5.0, 10.0], vec![0.0, 10.0, 0.0]),
                (SrgbRgba8::new(20, 40, 80, 255), width),
                SrgbRgba8::new(255, 255, 255, 255),
            );
            assert!(
                !encode_line_frame_png(&frame, &spec)
                    .expect("stroke PNG")
                    .is_empty()
            );
        }
    }

    #[test]
    fn transparent_background_and_source_canonicalize_rgb() {
        let (_, frame, spec) = make_frame(
            (2.0, 2.0),
            (0.0, 0.0, 2.0, 2.0),
            1.0,
            (Vec::new(), Vec::new()),
            (SrgbRgba8::new(10, 20, 30, 0), 1.0),
            SrgbRgba8::new(40, 50, 60, 0),
        );
        let (_, _, data) = decode_rgba(&encode_line_frame_png(&frame, &spec).expect("PNG"));
        assert!(data.chunks_exact(4).all(|pixel| pixel == [0, 0, 0, 0]));
    }

    #[test]
    fn dimension_pixel_work_and_output_limits_fail_before_allocation() {
        let cases = [
            (
                (16_384.1, 1.0),
                crate::error::ExportErrorKind::CapacityExceeded,
            ),
            (
                (16_384.0, 1_025.0),
                crate::error::ExportErrorKind::CapacityExceeded,
            ),
            (
                (16_384.0, 1_024.0),
                crate::error::ExportErrorKind::CapacityExceeded,
            ),
            (
                (4_096.0, 3_584.0),
                crate::error::ExportErrorKind::CapacityExceeded,
            ),
        ];
        for ((width, height), expected_kind) in cases {
            let (_, frame, spec) = make_frame(
                (width, height),
                (0.0, 0.0, 1.0, 1.0),
                1.0,
                (vec![0.0, 10.0], vec![0.0, 10.0]),
                (SrgbRgba8::new(0, 0, 0, 255), 1.0),
                SrgbRgba8::new(255, 255, 255, 255),
            );
            let error = encode_line_frame_png(&frame, &spec).expect_err("limit");
            assert_eq!(error.kind(), expected_kind);
        }
    }

    #[test]
    fn decoder_roundtrip_is_rgba8_and_repeatable() {
        let (_, frame, spec) = make_frame(
            (3.0, 2.0),
            (0.0, 0.0, 3.0, 2.0),
            1.0,
            (vec![0.0, 10.0], vec![0.0, 10.0]),
            (SrgbRgba8::new(10, 20, 30, 128), 0.5),
            SrgbRgba8::new(0, 0, 0, 0),
        );
        let first = encode_line_frame_png(&frame, &spec).expect("PNG");
        let second = encode_line_frame_png(&frame, &spec).expect("PNG");
        assert_eq!(first, second);
        let mut first_hash = DefaultHasher::new();
        let mut second_hash = DefaultHasher::new();
        first.hash(&mut first_hash);
        second.hash(&mut second_hash);
        assert_eq!(first_hash.finish(), second_hash.finish());

        let decoder = png::Decoder::new(Cursor::new(first));
        let mut reader = decoder.read_info().expect("header");
        let size = reader.output_buffer_size().expect("buffer size");
        let mut data = vec![0; size];
        let info = reader.next_frame(&mut data).expect("frame");
        assert_eq!(info.color_type, ColorType::Rgba);
        assert_eq!(info.bit_depth, BitDepth::Eight);
        assert_eq!(info.buffer_size(), data.len());
    }

    #[test]
    fn duplicate_and_singleton_points_are_handled_without_panic() {
        let (_, duplicate_frame, spec) = make_frame(
            (3.0, 2.0),
            (0.0, 0.0, 3.0, 2.0),
            1.0,
            (vec![5.0, 5.0], vec![5.0, 5.0]),
            (SrgbRgba8::new(10, 20, 30, 255), 1.0),
            SrgbRgba8::new(255, 255, 255, 255),
        );
        encode_line_frame_png(&duplicate_frame, &spec).expect("duplicate point PNG");

        let (_, singleton_frame, spec) = make_frame(
            (3.0, 2.0),
            (0.0, 0.0, 3.0, 2.0),
            1.0,
            (vec![5.0], vec![5.0]),
            (SrgbRgba8::new(10, 20, 30, 255), 1.0),
            SrgbRgba8::new(255, 255, 255, 255),
        );
        encode_line_frame_png(&singleton_frame, &spec).expect("singleton point PNG");
    }

    #[test]
    fn invalid_dpi_is_rejected_without_panicking() {
        for dpi in [0.0, -1.0, f64::NAN, f64::INFINITY] {
            let error = match PngSpec::new(dpi) {
                Ok(_) => panic!("invalid DPI was accepted"),
                Err(error) => error,
            };
            assert_eq!(error.kind(), crate::error::ExportErrorKind::InvalidInput);
            assert!(std::error::Error::source(&error).is_none());
            assert!(!format!("{error:?}").contains("crate"));
        }
    }

    #[test]
    fn allocation_failure_is_reported_before_output() {
        crate::set_allocation_failure_for_test(true);
        let error = match new_pixels(1, [0, 0, 0, 0]) {
            Ok(_) => panic!("allocation failure was ignored"),
            Err(error) => error,
        };
        crate::set_allocation_failure_for_test(false);
        assert_eq!(
            error.kind(),
            crate::error::ExportErrorKind::AllocationFailed
        );
    }

    #[test]
    fn direct_png_buffer_errors_are_sanitized() {
        let error = encode_png(1, 1, &[], 1).expect_err("size");
        assert_eq!(error.kind(), crate::error::ExportErrorKind::Internal);
        assert_eq!(error.to_string(), error.message());
    }

    #[test]
    fn unrepresentable_stroke_is_rejected_instead_of_background_only_png() {
        let (_, frame, spec) = make_frame(
            (2.0, 2.0),
            (0.0, 0.0, 2.0, 2.0),
            1.0,
            (vec![0.0, 10.0], vec![0.0, 0.0]),
            (SrgbRgba8::new(10, 20, 30, 255), 2.0e38),
            SrgbRgba8::new(40, 50, 60, 255),
        );
        let error = encode_line_frame_png(&frame, &spec).expect_err("stroke limits");
        assert_eq!(
            error.kind(),
            crate::error::ExportErrorKind::CapacityExceeded
        );
        assert_eq!(error.message(), "stroke geometry exceeds rasterizer limits");
    }
}
