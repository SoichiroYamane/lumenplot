mod error;
mod scene;
mod series;
mod view;

pub use error::{ErrorCategory, ErrorCode, PublicError};
pub use scene::{
    CommitReceipt, PlotScene, SceneRevision, SceneSnapshot, SceneTransaction, SeriesId,
};
pub use series::{SeriesData, SeriesTopology};
pub use view::{AxisRange, AxisScale, AxisScales, Viewport};

#[doc(hidden)]
pub mod __private {
    use std::fmt;
    use std::ops::Range;

    use lumenplot_engine::bridge as engine;
    use lumenplot_export::bridge as export;

    use super::{ErrorCategory, ErrorCode};

    const MAX_SOURCE_POINTS: usize = 1_000_000;

    #[derive(Clone, Copy)]
    enum BridgeCode {
        InvalidInput,
        UnsupportedCapability,
        InvalidState,
        OutOfMemory,
        ResourceInvalid,
        Internal,
    }

    pub struct LinePngGeometry {
        viewport: [f64; 4],
        canvas: [f64; 2],
        plot_rect: [f64; 4],
        logical_units_per_inch: f64,
    }

    pub struct LinePngStyle {
        line_rgba: [u8; 4],
        line_width: f64,
        background_rgba: [u8; 4],
    }

    pub struct OwnedLinePngRequest {
        x: Vec<f64>,
        y: Vec<f64>,
        valid_segments: Vec<Range<usize>>,
        geometry: LinePngGeometry,
        style: LinePngStyle,
        output_dpi: f64,
    }

    pub struct BridgeError {
        code: BridgeCode,
        message: &'static str,
    }

    impl LinePngGeometry {
        pub fn new(viewport: [f64; 4], canvas: [f64; 2], plot_rect: [f64; 4], logical_units_per_inch: f64) -> Result<Self, BridgeError> {
            if !viewport.iter().copied().all(f64::is_finite)
                || viewport[0] >= viewport[1]
                || viewport[2] >= viewport[3]
                || !finite_positive_span(viewport[0], viewport[1])
                || !finite_positive_span(viewport[2], viewport[3])
                || !canvas.iter().copied().all(f64::is_finite)
                || canvas[0] <= 0.0
                || canvas[1] <= 0.0
                || !plot_rect.iter().copied().all(f64::is_finite)
                || plot_rect[0] >= plot_rect[2]
                || plot_rect[1] >= plot_rect[3]
                || !finite_positive_span(plot_rect[0], plot_rect[2])
                || !finite_positive_span(plot_rect[1], plot_rect[3])
                || plot_rect[0] < 0.0
                || plot_rect[1] < 0.0
                || plot_rect[2] > canvas[0]
                || plot_rect[3] > canvas[1]
                || !logical_units_per_inch.is_finite()
                || logical_units_per_inch <= 0.0
            {
                return Err(BridgeError::invalid_input());
            }
            Ok(Self {
                viewport,
                canvas,
                plot_rect,
                logical_units_per_inch,
            })
        }
    }

    impl LinePngStyle {
        pub fn new(line_rgba: [u8; 4], line_width: f64, background_rgba: [u8; 4]) -> Result<Self, BridgeError> {
            if !line_width.is_finite() || line_width <= 0.0 {
                return Err(BridgeError::invalid_input());
            }
            Ok(Self {
                line_rgba: canonical_rgba(line_rgba),
                line_width,
                background_rgba: canonical_rgba(background_rgba),
            })
        }
    }

    impl OwnedLinePngRequest {
        pub fn new(x: Vec<f64>, y: Vec<f64>, valid_segments: Vec<Range<usize>>, geometry: LinePngGeometry, style: LinePngStyle, output_dpi: f64) -> Result<Self, BridgeError> {
            validate_request(&x, &y, &valid_segments, output_dpi)?;
            let mut x = x;
            let mut y = y;
            normalize_gaps(&mut x, &mut y, &valid_segments);
            Ok(Self {
                x,
                y,
                valid_segments,
                geometry,
                style,
                output_dpi,
            })
        }
    }

    impl BridgeError {
        fn new(code: BridgeCode, message: &'static str) -> Self {
            Self { code, message }
        }

        fn invalid_input() -> Self {
            Self::new(BridgeCode::InvalidInput, "input is invalid")
        }

        fn from_engine(error: engine::SceneError) -> Self {
            match error.kind() {
                engine::SceneErrorKind::InvalidInput => {
                    Self::new(BridgeCode::InvalidInput, "input is invalid")
                }
                engine::SceneErrorKind::UnsupportedCapability => Self::new(
                    BridgeCode::UnsupportedCapability,
                    "capability is unsupported",
                ),
                engine::SceneErrorKind::InvalidState => {
                    Self::new(BridgeCode::InvalidState, "scene state is invalid")
                }
                engine::SceneErrorKind::SeriesNotFound => {
                    Self::new(BridgeCode::ResourceInvalid, "series is invalid")
                }
                engine::SceneErrorKind::TopologyViolation => {
                    Self::new(BridgeCode::InvalidInput, "series topology is invalid")
                }
                engine::SceneErrorKind::NonFiniteCanonical => {
                    Self::new(BridgeCode::InvalidInput, "canonical values must be finite")
                }
                engine::SceneErrorKind::CapacityExceeded => {
                    Self::new(BridgeCode::InvalidInput, "input capacity is exceeded")
                }
                engine::SceneErrorKind::AllocationFailed => {
                    Self::new(BridgeCode::OutOfMemory, "allocation failed")
                }
                engine::SceneErrorKind::IdentityExhausted => {
                    Self::new(BridgeCode::Internal, "identity space is exhausted")
                }
                engine::SceneErrorKind::RevisionExhausted => {
                    Self::new(BridgeCode::Internal, "revision space is exhausted")
                }
                engine::SceneErrorKind::Internal => {
                    Self::new(BridgeCode::Internal, "internal error")
                }
            }
        }

        fn from_export(error: export::ExportError) -> Self {
            match error.kind() {
                export::ExportErrorKind::InvalidInput => {
                    Self::new(BridgeCode::InvalidInput, "input is invalid")
                }
                export::ExportErrorKind::UnsupportedCapability => Self::new(
                    BridgeCode::UnsupportedCapability,
                    "capability is unsupported",
                ),
                export::ExportErrorKind::CapacityExceeded => {
                    Self::new(BridgeCode::InvalidInput, "input capacity is exceeded")
                }
                export::ExportErrorKind::AllocationFailed => {
                    Self::new(BridgeCode::OutOfMemory, "allocation failed")
                }
                export::ExportErrorKind::EncodingFailed => {
                    Self::new(BridgeCode::Internal, "internal error")
                }
                export::ExportErrorKind::Internal => {
                    Self::new(BridgeCode::Internal, "internal error")
                }
            }
        }

        pub fn code(&self) -> ErrorCode {
            match self.code {
                BridgeCode::InvalidInput => ErrorCode::InvalidInput,
                BridgeCode::UnsupportedCapability => ErrorCode::UnsupportedCapability,
                BridgeCode::InvalidState => ErrorCode::InvalidState,
                BridgeCode::OutOfMemory => ErrorCode::OutOfMemory,
                BridgeCode::ResourceInvalid => ErrorCode::ResourceInvalid,
                BridgeCode::Internal => ErrorCode::Internal,
            }
        }

        pub fn category(&self) -> ErrorCategory {
            match self.code {
                BridgeCode::InvalidInput => ErrorCategory::Input,
                BridgeCode::UnsupportedCapability => ErrorCategory::Capability,
                BridgeCode::InvalidState => ErrorCategory::Lifecycle,
                BridgeCode::OutOfMemory | BridgeCode::ResourceInvalid => ErrorCategory::Resource,
                BridgeCode::Internal => ErrorCategory::Internal,
            }
        }

        pub fn message(&self) -> &str {
            self.message
        }
    }

    impl fmt::Debug for BridgeError {
        fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
            formatter
                .debug_struct("BridgeError")
                .field("code", &self.code().as_str())
                .field("category", &self.category().as_str())
                .field("message", &self.message)
                .finish()
        }
    }

    impl fmt::Display for BridgeError {
        fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
            formatter.write_str(self.message)
        }
    }

    impl std::error::Error for BridgeError {}

    pub fn render_line_png(request: OwnedLinePngRequest) -> Result<Vec<u8>, BridgeError> {
        let OwnedLinePngRequest {
            x,
            y,
            valid_segments,
            geometry,
            style,
            output_dpi,
        } = request;

        let viewport = engine::Viewport::from_bounds(
            geometry.viewport[0],
            geometry.viewport[1],
            geometry.viewport[2],
            geometry.viewport[3],
        )
        .map_err(BridgeError::from_engine)?;
        let scales = engine::AxisScales::new(engine::AxisScale::Linear, engine::AxisScale::Linear);
        let mut scene =
            engine::PlotScene::new(viewport, scales).map_err(BridgeError::from_engine)?;

        let data = engine::SeriesData::from_owned_xy_segments(
            engine::SeriesTopology::ArbitraryXY,
            x,
            y,
            valid_segments,
        )
        .map_err(BridgeError::from_engine)?;

        let canvas = engine::LogicalSize::new(geometry.canvas[0], geometry.canvas[1])
            .map_err(BridgeError::from_engine)?;
        let plot_rect = engine::LogicalRect::new(
            geometry.plot_rect[0],
            geometry.plot_rect[1],
            geometry.plot_rect[2],
            geometry.plot_rect[3],
        )
        .map_err(BridgeError::from_engine)?;
        let line_style = engine::LineStyle::new(
            engine::SrgbRgba8::new(
                style.line_rgba[0],
                style.line_rgba[1],
                style.line_rgba[2],
                style.line_rgba[3],
            ),
            style.line_width,
        )
        .map_err(BridgeError::from_engine)?;
        let background = engine::SrgbRgba8::new(
            style.background_rgba[0],
            style.background_rgba[1],
            style.background_rgba[2],
            style.background_rgba[3],
        );
        let frame_spec = engine::LineFrameSpec::new(
            canvas,
            plot_rect,
            geometry.logical_units_per_inch,
            line_style,
            background,
        )
        .map_err(BridgeError::from_engine)?;

        {
            let mut transaction = scene.transaction();
            transaction
                .add_series(data)
                .map_err(BridgeError::from_engine)?;
            transaction.commit().map_err(BridgeError::from_engine)?;
        }

        let frame = scene
            .snapshot()
            .resolve_line_frame(&frame_spec)
            .map_err(BridgeError::from_engine)?;
        let png_spec = export::PngSpec::new(output_dpi).map_err(BridgeError::from_export)?;
        export::encode_line_frame_png(&frame, &png_spec).map_err(BridgeError::from_export)
    }

    fn validate_request(
        x: &[f64],
        y: &[f64],
        valid_segments: &[Range<usize>],
        output_dpi: f64,
    ) -> Result<(), BridgeError> {
        if x.len() != y.len() || x.len() > MAX_SOURCE_POINTS {
            return Err(BridgeError::invalid_input());
        }
        if !output_dpi.is_finite() || output_dpi <= 0.0 {
            return Err(BridgeError::invalid_input());
        }
        if x.iter().chain(y.iter()).any(|value| value.is_infinite()) {
            return Err(BridgeError::invalid_input());
        }

        let mut previous_end = 0usize;
        for (position, segment) in valid_segments.iter().enumerate() {
            if segment.start >= segment.end
                || segment.end > x.len()
                || position > 0 && segment.start <= previous_end
            {
                return Err(BridgeError::invalid_input());
            }
            if (previous_end..segment.start).any(|index| finite_pair(x[index], y[index]))
                || (segment.start..segment.end).any(|index| !finite_pair(x[index], y[index]))
            {
                return Err(BridgeError::invalid_input());
            }
            previous_end = segment.end;
        }
        if (previous_end..x.len()).any(|index| finite_pair(x[index], y[index])) {
            return Err(BridgeError::invalid_input());
        }
        Ok(())
    }

    fn normalize_gaps(x: &mut [f64], y: &mut [f64], valid_segments: &[Range<usize>]) {
        let mut covered_until = 0usize;
        for segment in valid_segments {
            for index in covered_until..segment.start {
                x[index] = f64::NAN;
                y[index] = f64::NAN;
            }
            covered_until = segment.end;
        }
        for index in covered_until..x.len() {
            x[index] = f64::NAN;
            y[index] = f64::NAN;
        }
    }

    fn finite_pair(x: f64, y: f64) -> bool {
        x.is_finite() && y.is_finite()
    }

    fn finite_positive_span(min: f64, max: f64) -> bool {
        let span = max - min;
        span.is_finite() && span > 0.0
    }

    fn canonical_rgba(mut color: [u8; 4]) -> [u8; 4] {
        if color[3] == 0 {
            color[0] = 0;
            color[1] = 0;
            color[2] = 0;
        }
        color
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        #[test]
        fn validation_accepts_empty_and_exact_gap_runs() {
            let geometry = LinePngGeometry::new(
                [0.0, 10.0, 0.0, 10.0],
                [8.0, 8.0],
                [0.0, 0.0, 8.0, 8.0],
                72.0,
            )
            .expect("geometry");
            let style = LinePngStyle::new([255, 0, 0, 255], 1.0, [0, 0, 0, 0]).expect("style");
            let request = OwnedLinePngRequest::new(
                vec![0.0, f64::NAN, 2.0, 3.0, f64::NAN],
                vec![0.0, 4.0, 2.0, 3.0, f64::NAN],
                vec![0..1, 2..4],
                geometry,
                style,
                144.0,
            )
            .expect("request");
            assert!(request.x[1].is_nan());
            assert!(request.y[1].is_nan());
            assert!(request.x[4].is_nan());

            let geometry =
                LinePngGeometry::new([0.0, 1.0, 0.0, 1.0], [1.0, 1.0], [0.0, 0.0, 1.0, 1.0], 72.0)
                    .expect("geometry");
            let style = LinePngStyle::new([1, 2, 3, 255], 1.0, [4, 5, 6, 255]).expect("style");
            let empty =
                OwnedLinePngRequest::new(Vec::new(), Vec::new(), Vec::new(), geometry, style, 72.0)
                    .expect("empty request");
            assert!(empty.x.is_empty());
        }

        #[test]
        fn validation_rejects_nonfinite_and_noncanonical_segments() {
            let geometry =
                LinePngGeometry::new([0.0, 1.0, 0.0, 1.0], [1.0, 1.0], [0.0, 0.0, 1.0, 1.0], 72.0)
                    .expect("geometry");
            let style = LinePngStyle::new([1, 2, 3, 255], 1.0, [4, 5, 6, 255]).expect("style");
            let cases = [
                (vec![0.0], vec![], std::iter::once(0..1).collect()),
                (
                    vec![f64::INFINITY],
                    vec![0.0],
                    std::iter::once(0..1).collect(),
                ),
                (vec![0.0, 1.0], vec![0.0, 1.0], Vec::new()),
                (
                    vec![0.0, f64::NAN],
                    vec![0.0, 1.0],
                    std::iter::once(0..2).collect(),
                ),
                (vec![0.0, 1.0], vec![0.0, 1.0], vec![0..1, 1..2]),
                (
                    vec![0.0, 1.0],
                    vec![0.0, 1.0],
                    std::iter::once(1..2).collect(),
                ),
                (vec![0.0, f64::NAN], vec![0.0, 1.0], vec![0..1, 1..2]),
            ];
            for (x, y, segments) in cases {
                let result = OwnedLinePngRequest::new(
                    x,
                    y,
                    segments,
                    LinePngGeometry::new(
                        geometry.viewport,
                        geometry.canvas,
                        geometry.plot_rect,
                        geometry.logical_units_per_inch,
                    )
                    .expect("geometry"),
                    LinePngStyle::new(style.line_rgba, style.line_width, style.background_rgba)
                        .expect("style"),
                    72.0,
                );
                let error = match result {
                    Ok(_) => panic!("invalid request was accepted"),
                    Err(error) => error,
                };
                assert_eq!(error.code().as_str(), "invalid-input");
            }
        }

        #[test]
        fn constructors_validate_geometry_style_and_canonicalize_transparency() {
            assert!(
                LinePngGeometry::new([0.0, 1.0, 0.0, 1.0], [1.0, 1.0], [0.0, 0.0, 2.0, 1.0], 72.0,)
                    .is_err()
            );
            assert!(
                LinePngGeometry::new(
                    [0.0, f64::INFINITY, 0.0, 1.0],
                    [1.0, 1.0],
                    [0.0, 0.0, 1.0, 1.0],
                    72.0,
                )
                .is_err()
            );
            assert!(LinePngStyle::new([1, 2, 3, 255], f64::NAN, [0, 0, 0, 255]).is_err());
            let style = LinePngStyle::new([1, 2, 3, 0], 1.0, [4, 5, 6, 0]).expect("style");
            assert_eq!(style.line_rgba, [0, 0, 0, 0]);
            assert_eq!(style.background_rgba, [0, 0, 0, 0]);
        }

        #[test]
        fn error_mapping_is_exhaustive_sanitized_and_source_less() {
            let codes = [
                BridgeCode::InvalidInput,
                BridgeCode::UnsupportedCapability,
                BridgeCode::InvalidState,
                BridgeCode::OutOfMemory,
                BridgeCode::ResourceInvalid,
                BridgeCode::Internal,
            ];
            for code in codes {
                let error = BridgeError::new(code, "safe message");
                assert!(!error.message().is_empty());
                assert!(!error.message().contains("crate"));
                assert!(!error.code().as_str().is_empty());
                assert!(!error.category().as_str().is_empty());
                assert!(std::error::Error::source(&error).is_none());
            }
        }

        #[test]
        fn rendered_bytes_match_the_direct_engine_export_path() {
            let geometry = LinePngGeometry::new(
                [0.0, 10.0, 0.0, 10.0],
                [64.0, 48.0],
                [4.0, 4.0, 60.0, 44.0],
                72.0,
            )
            .expect("geometry");
            let style =
                LinePngStyle::new([255, 32, 16, 255], 1.5, [8, 12, 20, 255]).expect("style");
            let request = OwnedLinePngRequest::new(
                vec![0.0, 4.0, f64::NAN, 6.0, 10.0],
                vec![0.0, 8.0, 9.0, 8.0, 0.0],
                vec![0..2, 3..5],
                geometry,
                style,
                144.0,
            )
            .expect("request");
            let actual = render_line_png(request).expect("facade render");

            let view = engine::Viewport::from_bounds(0.0, 10.0, 0.0, 10.0).expect("view");
            let scales =
                engine::AxisScales::new(engine::AxisScale::Linear, engine::AxisScale::Linear);
            let mut scene = engine::PlotScene::new(view, scales).expect("scene");
            let data = engine::SeriesData::from_owned_xy_segments(
                engine::SeriesTopology::ArbitraryXY,
                vec![0.0, 4.0, f64::NAN, 6.0, 10.0],
                vec![0.0, 8.0, f64::NAN, 8.0, 0.0],
                vec![0..2, 3..5],
            )
            .expect("data");
            let canvas = engine::LogicalSize::new(64.0, 48.0).expect("canvas");
            let plot_rect = engine::LogicalRect::new(4.0, 4.0, 60.0, 44.0).expect("plot");
            let line_style = engine::LineStyle::new(engine::SrgbRgba8::new(255, 32, 16, 255), 1.5)
                .expect("line style");
            let frame_spec = engine::LineFrameSpec::new(
                canvas,
                plot_rect,
                72.0,
                line_style,
                engine::SrgbRgba8::new(8, 12, 20, 255),
            )
            .expect("frame spec");
            {
                let mut transaction = scene.transaction();
                transaction.add_series(data).expect("series");
                transaction.commit().expect("commit");
            }
            let frame = scene
                .snapshot()
                .resolve_line_frame(&frame_spec)
                .expect("frame");
            let png_spec = export::PngSpec::new(144.0).expect("PNG spec");
            let expected = export::encode_line_frame_png(&frame, &png_spec).expect("PNG");

            assert_eq!(actual, expected);
            assert!(actual.starts_with(b"\x89PNG\r\n\x1a\n"));
        }

        #[test]
        fn empty_and_all_gap_inputs_render_a_background_png() {
            for (x, y) in [
                (Vec::new(), Vec::new()),
                (vec![f64::NAN, 1.0], vec![2.0, f64::NAN]),
            ] {
                let geometry = LinePngGeometry::new(
                    [0.0, 1.0, 0.0, 1.0],
                    [8.0, 8.0],
                    [0.0, 0.0, 8.0, 8.0],
                    72.0,
                )
                .expect("geometry");
                let style =
                    LinePngStyle::new([10, 20, 30, 255], 1.0, [40, 50, 60, 255]).expect("style");
                let request = OwnedLinePngRequest::new(x, y, Vec::new(), geometry, style, 72.0)
                    .expect("request");
                let output = render_line_png(request).expect("background PNG");
                assert!(output.starts_with(b"\x89PNG\r\n\x1a\n"));
            }
        }
    }
}
