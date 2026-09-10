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

    // M5-B2: consume the ONE retained layout result shared with the screen and
    // CPU consumers. Glyph cells come from stored positions with zero
    // remeasurement; canvas-scoped compositing lets axis/title/legend labels
    // outside the plot rect still land on the page.
    let text_mask = raster::rasterize_retained_text(frame, &plan)?;
    let text_plan = plan.text_plan();
    composite_mask(
        &mut pixels,
        &text_mask,
        &text_plan,
        raster::TEXT_INK_RGBA8,
        text_plan.width(),
        text_plan.height(),
    )?;

    // M5-P2: stored-geometry annotation ink from the same retained result.
    // Line/arrow shafts and rectangle outlines stroke at the fixture width
    // while text fills its stored coarse box. The pass is canvas-scoped like
    // retained text, so annotations outside the plot rect still land, and it
    // composites with the fixed fixture ink.
    let annotation_mask = raster::rasterize_annotations(frame, &plan)?;
    let annotation_plan = plan.text_plan();
    composite_mask(
        &mut pixels,
        &annotation_mask,
        &annotation_plan,
        raster::ANNOTATION_INK_RGBA8,
        annotation_plan.width(),
        annotation_plan.height(),
    )?;

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
        // ADR-0018: IDAT payloads use DEFLATE (Balanced). Measured on the
        // quickstart fixture (576x432): 995,916 bytes uncompressed ->
        // 2,445 bytes compressed (~407x smaller), versus a 4,367-byte Agg
        // reference for the same figure.
        encoder.set_compression(Compression::Balanced);
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
    fn retained_labels_render_from_one_result_with_stable_bytes() {
        let (_, frame, spec) = make_frame(
            (160.0, 90.0),
            (8.0, 8.0, 56.0, 56.0),
            1.0,
            (vec![0.0, 10.0], vec![0.0, 0.0]),
            (SrgbRgba8::new(255, 0, 0, 255), 1.0),
            SrgbRgba8::new(255, 255, 255, 255),
        );
        // ONE retained result: repeated reads observe the same allocation, and
        // the axis/title/legend families below are the stored sources.
        let layout = frame.plot_layout();
        assert!(std::ptr::eq(layout, frame.plot_layout()));
        assert_eq!(layout.runs().len(), 6);
        assert_eq!(layout.runs()[3].source(), "x");
        assert_eq!(layout.runs()[4].source(), "measurement");
        assert_eq!(layout.runs()[5].source(), "series-0");
        let first = encode_line_frame_png(&frame, &spec).expect("PNG");
        let second = encode_line_frame_png(&frame, &spec).expect("PNG");
        assert_eq!(first, second);
        let (width, height, data) = decode_rgba(&first);
        assert_eq!((width, height), (160, 90));
        // The legend cell for "series-0" opens at stored origin (72, 64) with
        // a 5x7 block, outside the plot rect: its center lands as text ink.
        let center = (67u32 * 160 + 74) as usize * 4;
        assert_eq!(&data[center..center + 4], &[0, 0, 0, 255]);
        // A page corner no stored run reaches stays background.
        let corner = (89u32 * 160 + 159) as usize * 4;
        assert_eq!(&data[corner..corner + 4], &[255, 255, 255, 255]);
    }

    #[test]
    fn stale_retained_generations_fail_the_sink_predicate() {
        let (_, frame, spec) = make_frame(
            (160.0, 90.0),
            (8.0, 8.0, 56.0, 56.0),
            1.0,
            (vec![0.0, 10.0], vec![0.0, 0.0]),
            (SrgbRgba8::new(255, 0, 0, 255), 1.0),
            SrgbRgba8::new(255, 255, 255, 255),
        );
        let layout = frame.plot_layout();
        assert!(layout.validate());
        assert!(layout.validate_for_generation(layout.font_revision(), layout.layout_revision()));
        assert!(!layout.validate_for_generation(
            layout.font_revision().saturating_add(1),
            layout.layout_revision()
        ));
        assert!(!layout.validate_for_generation(
            layout.font_revision(),
            layout.layout_revision().saturating_add(1)
        ));
        // The sink plan re-validates the retained digest before any fill, so
        // a valid retained result plans cleanly here while a corrupt digest
        // would fail with `InvalidInput` before allocation.
        crate::raster::RasterPlan::new(&frame, &spec).expect("valid layout plans");
    }

    #[test]
    fn stored_annotation_geometry_lands_as_ink() {
        // AT-EXPORT-ANNOTATION inclusion: every stored fixture kind lands as
        // ink through the P2 fixture mapping (declared space read as canvas
        // logical identity at unit scale). The canvas is tall enough to hold
        // the DisplayLogical rectangle (100,100)-(140,120) as well.
        let (_, frame, spec) = make_frame(
            (160.0, 140.0),
            (8.0, 8.0, 56.0, 56.0),
            1.0,
            (vec![0.0, 10.0], vec![0.0, 0.0]),
            (SrgbRgba8::new(255, 0, 0, 255), 1.0),
            SrgbRgba8::new(255, 255, 255, 255),
        );
        assert_eq!(frame.plot_layout().annotations().len(), 4);
        let first = encode_line_frame_png(&frame, &spec).expect("PNG");
        let second = encode_line_frame_png(&frame, &spec).expect("PNG");
        assert_eq!(first, second);
        let (width, height, data) = decode_rgba(&first);
        assert_eq!((width, height), (160, 140));
        let pixel = |x: u32, y: u32| -> [u8; 4] {
            let offset = (y * 160 + x) as usize * 4;
            data[offset..offset + 4]
                .try_into()
                .expect("pixel inside the canvas")
        };
        // Text fixture-box: stored Data2D bounds (-2,16,22,24) fill their
        // interior; (10,20) is clear of shafts, glyph cells, and series ink.
        assert_eq!(pixel(10, 20), [0, 0, 0, 255]);
        // Line shaft: AxesLogical (0,0)-(64,32) crosses (8,4), clear of every
        // other stored geometry.
        assert_ne!(pixel(8, 4), [255, 255, 255, 255]);
        // Arrow shaft: FigureLogical (8,8)-(40,24) crosses (24,16), clear of
        // the line shaft, text cells, and the text fixture-box (x_max=22).
        assert_ne!(pixel(24, 16), [255, 255, 255, 255]);
        // Rectangle outline: DisplayLogical (100,100)-(140,120); the top
        // edge carries ink while the interior stays background (outline
        // only, never filled).
        assert_ne!(pixel(120, 100), [255, 255, 255, 255]);
        assert_eq!(pixel(120, 110), [255, 255, 255, 255]);
    }

    #[test]
    fn export_contains_no_transient_chrome() {
        // AT-EXPORT-STATE negative: the PNG seam reads only the retained
        // frame plus spec — the encoder takes no hover, selection, cursor,
        // toolbar, or drag input — so a page corner no stored series, text,
        // or annotation geometry reaches stays background, and repeated
        // encodes are byte-identical.
        let (_, frame, spec) = make_frame(
            (160.0, 140.0),
            (8.0, 8.0, 56.0, 56.0),
            1.0,
            (vec![0.0, 10.0], vec![0.0, 0.0]),
            (SrgbRgba8::new(255, 0, 0, 255), 1.0),
            SrgbRgba8::new(255, 255, 255, 255),
        );
        let first = encode_line_frame_png(&frame, &spec).expect("PNG");
        let second = encode_line_frame_png(&frame, &spec).expect("PNG");
        assert_eq!(first, second);
        let (width, height, data) = decode_rgba(&first);
        assert_eq!((width, height), (160, 140));
        // (159,139): beyond the series line (y=56), every glyph cell
        // (y<=71), and every annotation box/shaft (x<=140, y<=120).
        let corner = (139u32 * 160 + 159) as usize * 4;
        assert_eq!(&data[corner..corner + 4], &[255, 255, 255, 255]);
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

    #[test]
    fn revision_pinned_frame_exports_selected_revision() {
        // LP-EXPORT-004 private evidence: one retained frame per selected
        // revision. Resolving before and after a scene change exports the
        // selected bytes each time; the stale snapshot stays pinned to its
        // own revision while its generation fails the sink predicate.
        let canvas = LogicalSize::new(160.0, 140.0).expect("canvas");
        let plot = LogicalRect::new(8.0, 8.0, 56.0, 56.0).expect("plot");
        let style = LineStyle::new(SrgbRgba8::new(255, 0, 0, 255), 1.0).expect("style");
        let frame_spec =
            LineFrameSpec::new(canvas, plot, 1.0, style, SrgbRgba8::new(255, 255, 255, 255))
                .expect("spec");
        let view = Viewport::from_bounds(0.0, 10.0, 0.0, 10.0).expect("view");
        let mut scene = PlotScene::new(view, AxisScales::new(AxisScale::Linear, AxisScale::Linear))
            .expect("scene");
        let png_spec = PngSpec::new(1.0).expect("png spec");
        {
            let data = SeriesData::from_owned_xy(
                SeriesTopology::MonotonicX,
                vec![0.0, 10.0],
                vec![0.0, 0.0],
            )
            .expect("data");
            let mut transaction = scene.transaction();
            transaction.add_series(data).expect("series");
            transaction.commit().expect("commit");
        }
        let pinned = scene.snapshot();
        let frame_before = pinned.resolve_line_frame(&frame_spec).expect("frame");
        let bytes_before = encode_line_frame_png(&frame_before, &png_spec).expect("PNG");
        let revision_before = frame_before.revision();
        assert_eq!(revision_before, scene.revision());
        let (font_before, layout_before) = {
            let layout = frame_before.plot_layout();
            (layout.font_revision(), layout.layout_revision())
        };
        // A diagonal second series lands new ink at the next revision.
        {
            let data = SeriesData::from_owned_xy(
                SeriesTopology::MonotonicX,
                vec![0.0, 10.0],
                vec![0.0, 10.0],
            )
            .expect("data");
            let mut transaction = scene.transaction();
            transaction.add_series(data).expect("series");
            transaction.commit().expect("commit");
        }
        let frame_after = scene
            .snapshot()
            .resolve_line_frame(&frame_spec)
            .expect("frame");
        assert!(frame_after.revision() > revision_before);
        assert_eq!(frame_after.revision(), scene.revision());
        let bytes_after = encode_line_frame_png(&frame_after, &png_spec).expect("PNG");
        // Non-vacuous: the new series changes the selected export bytes,
        // and each selection is deterministic.
        assert_ne!(bytes_before, bytes_after);
        assert_eq!(
            bytes_after,
            encode_line_frame_png(&frame_after, &png_spec).expect("PNG")
        );
        // The retained generation advanced with the data change, so the
        // pinned generation is stale under the sink predicate.
        let (font_after, layout_after) = {
            let layout = frame_after.plot_layout();
            (layout.font_revision(), layout.layout_revision())
        };
        assert!((font_after, layout_after) != (font_before, layout_before));
        assert!(
            frame_after
                .plot_layout()
                .validate_for_generation(font_after, layout_after)
        );
        assert!(
            !frame_before
                .plot_layout()
                .validate_for_generation(font_after, layout_after)
        );
        // The stale snapshot still resolves and exports its own selected
        // revision, never the newer bytes.
        let stale_frame = pinned.resolve_line_frame(&frame_spec).expect("stale frame");
        assert_eq!(stale_frame.revision(), revision_before);
        assert_eq!(
            encode_line_frame_png(&stale_frame, &png_spec).expect("PNG"),
            bytes_before
        );
    }

    #[test]
    fn cursor_and_crosshair_have_no_export_projection() {
        // LP-EXPORT-010 dedicated negative: the PNG seam takes only
        // (&LineFrame, &PngSpec) — no cursor coordinate, hover, or
        // crosshair input exists — so no full-span cursor crosshair can be
        // positioned, and none is baked in at a default spot either. The
        // plot-center row and column stay background where retained ink
        // never reaches, and repeated encodes are byte-identical.
        let (_, frame, spec) = make_frame(
            (160.0, 140.0),
            (8.0, 8.0, 56.0, 56.0),
            1.0,
            (vec![0.0, 10.0], vec![0.0, 0.0]),
            (SrgbRgba8::new(255, 0, 0, 255), 1.0),
            SrgbRgba8::new(255, 255, 255, 255),
        );
        let first = encode_line_frame_png(&frame, &spec).expect("PNG");
        let second = encode_line_frame_png(&frame, &spec).expect("PNG");
        assert_eq!(first, second);
        let (width, height, data) = decode_rgba(&first);
        assert_eq!((width, height), (160, 140));
        let pixel = |x: u32, y: u32| -> [u8; 4] {
            let offset = (y * 160 + x) as usize * 4;
            data[offset..offset + 4]
                .try_into()
                .expect("pixel inside the canvas")
        };
        // Retained ink near the probes: the series row is y=64, shafts stay
        // at y<=32, glyph cells sit at x 16..21/32..37/48..53 with y 16..23
        // plus (64..69, 32..39) and (64..69, 48..55), the text box covers
        // x -2..22 with y 16..24, and the arrow shaft spans x 8..40 with
        // y 8..24. A center crosshair would ink row y=36 across the plot
        // and column x=36 down the plot; both strips avoid every retained
        // mark above, so any crosshair ink would stand out here.
        for x in 40..64u32 {
            assert_eq!(pixel(x, 36), [255, 255, 255, 255], "row probe at x={x}");
        }
        for y in 30..52u32 {
            assert_eq!(pixel(36, y), [255, 255, 255, 255], "column probe at y={y}");
        }
    }
}
