//! Minimal synchronous, CPU-side frame seam for the internal render boundary.
//!
//! This is the accepted M1 slice: a second consumer of the private semantic
//! kernel can be written against this surface without inventing the boundary
//! mid-lane, and every concrete renderer consumes exactly this shape behind
//! its own gate. The seam stays backend-agnostic by construction: a renderer
//! receives an opaque [`FramePacket`] already resolved against a
//! [`SceneHandle`] and turns it into pixels through its own prepare / draw /
//! present steps; nothing here names any concrete frontend or backend API.

use std::fmt;

use crate::packet::{
    DeviceGeneration, PacketValidationError, RenderPacket, RenderPacketBuilder, WorkGeneration,
};
use lumenplot_engine::bridge::{
    AxisScale, AxisScales, LineFrameSpec, LineStyle, LogicalRect, LogicalSize, PlotScene,
    SceneError as EngineSceneError, SceneErrorKind as EngineSceneErrorKind, SceneRevision,
    SeriesData, SeriesTopology, SrgbRgba8, Viewport,
};

/// Maximum series per scene, mirroring the engine's frame-resolution cap.
pub(crate) const MAX_FRAME_SERIES: usize = 65_536;
/// Maximum width or height accepted by the process-local seam.
pub(crate) const MAX_FRAME_DIMENSION: u32 = 16_384;
/// Maximum canvas pixels accepted before any renderer-side allocation.
pub(crate) const MAX_FRAME_PIXELS: usize = 16_777_216;

/// Backend-neutral layout resolved from one engine snapshot.
///
/// This stays private to the render boundary. Interactive consumers and the
/// internal packet validator read these facts from the same value instead of
/// independently reconstructing canvas or clip geometry.
#[derive(Clone, Copy)]
pub(crate) struct ResolvedLayout {
    pub(crate) canvas: LogicalSize,
    pub(crate) plot_rect: LogicalRect,
    pub(crate) logical_units_per_inch: f64,
    pub(crate) background: SrgbRgba8,
}

/// Error shape for seam construction and scene resolution.
///
/// The message is sanitized: it carries the engine's stable kind phrase and
/// never embeds offending input values.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrameSeamError {
    kind: FrameSeamErrorKind,
    message: String,
}

impl FrameSeamError {
    /// Error classification for programmatic handling.
    pub fn kind(&self) -> FrameSeamErrorKind {
        self.kind
    }

    /// Sanitized human-readable description.
    pub fn message(&self) -> &str {
        &self.message
    }

    pub(crate) fn from_packet_error(kind: FrameSeamErrorKind, message: &'static str) -> Self {
        Self {
            kind,
            message: message.to_string(),
        }
    }
}

impl fmt::Display for FrameSeamError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl std::error::Error for FrameSeamError {}

/// Error kinds for the frame seam.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum FrameSeamErrorKind {
    /// An input value violated a documented precondition.
    InvalidInput,
    /// The requested configuration exceeds a fixed capacity bound.
    CapacityExceeded,
    /// The engine rejected the underlying scene operation for another reason.
    EngineRejected,
}

impl From<&EngineSceneError> for FrameSeamError {
    fn from(error: &EngineSceneError) -> Self {
        Self {
            kind: match error.kind() {
                EngineSceneErrorKind::InvalidInput => FrameSeamErrorKind::InvalidInput,
                _ => FrameSeamErrorKind::EngineRejected,
            },
            message: error.message().to_string(),
        }
    }
}

fn invalid_input(message: &'static str) -> FrameSeamError {
    FrameSeamError {
        kind: FrameSeamErrorKind::InvalidInput,
        message: message.to_string(),
    }
}

fn engine_error(error: &EngineSceneError) -> FrameSeamError {
    FrameSeamError::from(error)
}

/// Guard mirrored from the engine's frame-resolution cap, factored out so the
/// boundary stays testable without constructing tens of thousands of series.
pub(crate) fn ensure_series_capacity(series_count: usize) -> Result<(), FrameSeamError> {
    if series_count >= MAX_FRAME_SERIES {
        return Err(FrameSeamError {
            kind: FrameSeamErrorKind::CapacityExceeded,
            message: "capacity is exceeded".to_string(),
        });
    }
    Ok(())
}

/// Handle over the private semantic kernel state packets are resolved against.
///
/// Renderers never see this type; they receive resolved [`FramePacket`]s.
pub struct SceneHandle {
    scene: PlotScene,
    series_count: usize,
}

impl SceneHandle {
    /// Creates a handle over a linear-axis scene with the given canonical view.
    pub fn new(canonical_view: Viewport) -> Result<Self, FrameSeamError> {
        let scene = PlotScene::new(
            canonical_view,
            AxisScales::new(AxisScale::Linear, AxisScale::Linear),
        )
        .map_err(|error| engine_error(&error))?;
        Ok(Self {
            scene,
            series_count: 0,
        })
    }

    /// Adds one owned monotone-in-x line series to the scene.
    ///
    /// The topology is pinned to [`SeriesTopology::MonotonicX`]: the bench
    /// fixture and the accepted frame path are monotone-in-x line data.
    pub fn add_series(&mut self, xs: Vec<f64>, ys: Vec<f64>) -> Result<(), FrameSeamError> {
        ensure_series_capacity(self.series_count)?;
        let data = SeriesData::from_owned_xy(SeriesTopology::MonotonicX, xs, ys)
            .map_err(|error| engine_error(&error))?;
        {
            let mut transaction = self.scene.transaction();
            transaction
                .add_series(data)
                .map_err(|error| engine_error(&error))?;
            transaction.commit().map_err(|error| engine_error(&error))?;
        }
        self.series_count += 1;
        Ok(())
    }

    /// Resolves the current scene state into a whole-packet immutable
    /// description under `spec`.
    pub fn resolve_frame(&self, spec: &FrameSpec) -> Result<FramePacket, FrameSeamError> {
        let initial_work = WorkGeneration::initial();
        let initial_device = DeviceGeneration::initial();
        let builder = RenderPacketBuilder::new(initial_work, initial_device);
        let packet = self
            .resolve_render_packet(spec, &builder, initial_work, initial_device)
            .map_err(PacketValidationError::into_frame_error)?;
        Ok(packet.frame().clone())
    }

    /// Resolves a frame candidate and validates it for an internal renderer.
    pub(crate) fn resolve_render_packet(
        &self,
        spec: &FrameSpec,
        builder: &RenderPacketBuilder,
        work_generation: WorkGeneration,
        device_generation: DeviceGeneration,
    ) -> Result<RenderPacket, PacketValidationError> {
        let frame = self
            .resolve_frame_candidate(spec)
            .map_err(PacketValidationError::from_frame_error)?;
        builder.build(frame, work_generation, device_generation)
    }

    fn resolve_frame_candidate(&self, spec: &FrameSpec) -> Result<FramePacket, FrameSeamError> {
        let snapshot = self.scene.snapshot();
        let frame = snapshot
            .resolve_line_frame(&spec.inner)
            .map_err(|error| engine_error(&error))?;
        let mut series = Vec::with_capacity(frame.series().len());
        for resolved in frame.series() {
            let mut segments = Vec::with_capacity(resolved.segments().len());
            for segment in resolved.segments() {
                let points = segment
                    .points()
                    .iter()
                    .map(|point| PacketPoint::new(point.x(), point.y()))
                    .collect();
                segments.push(PacketSegment { points });
            }
            series.push(PacketSeries { segments });
        }
        Ok(FramePacket {
            revision: PacketRevision(snapshot.revision()),
            canvas_px: spec.canvas_px,
            dots_per_inch: spec.dots_per_inch,
            layout: ResolvedLayout {
                canvas: frame.canvas(),
                plot_rect: frame.plot_rect(),
                logical_units_per_inch: frame.logical_units_per_inch(),
                background: frame.background(),
            },
            line_color: spec.line_color,
            line_width_px: spec.line_width_px,
            series,
        })
    }

    /// Current scene revision as an opaque token.
    pub fn revision(&self) -> PacketRevision {
        PacketRevision(self.scene.revision())
    }
}

/// Opaque scene-revision token carried on every packet.
///
/// Wraps the engine bridge's own opaque revision type; equality and ordering
/// follow scene-revision order without exposing raw counters.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct PacketRevision(SceneRevision);

/// Validated, immutable description of the frame to resolve.
///
/// Construction validates pixel geometry and DPI up front; scene resolution
/// validates the mapped logical geometry, so a successfully produced
/// [`FramePacket`] is consistent by construction.
pub struct FrameSpec {
    inner: LineFrameSpec,
    canvas_px: [u32; 2],
    dots_per_inch: f64,
    line_color: SrgbRgba8,
    line_width_px: f64,
}

impl FrameSpec {
    /// Creates a validated frame specification.
    ///
    /// `plot_rect_px` is `[x_min, y_min, x_max, y_max]` in pixels and must
    /// stay inside the canvas; `line_width_px` is the stroked line width in
    /// pixels; `background` fills the plot area.
    pub fn new(
        canvas_px: [u32; 2],
        plot_rect_px: [u32; 4],
        dots_per_inch: f64,
        line_color: SrgbRgba8,
        line_width_px: f64,
        background: SrgbRgba8,
    ) -> Result<Self, FrameSeamError> {
        if !dots_per_inch.is_finite() || dots_per_inch <= 0.0 {
            return Err(invalid_input("dots-per-inch must be finite and positive"));
        }
        let [width_px, height_px] = canvas_px;
        if width_px == 0 || height_px == 0 {
            return Err(invalid_input(
                "canvas must be at least one pixel wide and tall",
            ));
        }
        if width_px > MAX_FRAME_DIMENSION || height_px > MAX_FRAME_DIMENSION {
            return Err(invalid_input("canvas exceeds the supported dimension"));
        }
        let pixel_count = usize::try_from(width_px)
            .ok()
            .and_then(|width| {
                usize::try_from(height_px)
                    .ok()
                    .and_then(|height| width.checked_mul(height))
            })
            .ok_or_else(|| invalid_input("canvas exceeds the supported pixel count"))?;
        if pixel_count > MAX_FRAME_PIXELS {
            return Err(invalid_input("canvas exceeds the supported pixel count"));
        }
        let [x_min, y_min, x_max, y_max] = plot_rect_px;
        if x_min >= x_max || y_min >= y_max || x_max > width_px || y_max > height_px {
            return Err(invalid_input("plot rectangle must stay inside the canvas"));
        }
        if !line_width_px.is_finite() || line_width_px <= 0.0 {
            return Err(invalid_input("line width must be finite and positive"));
        }
        // Pixel geometry maps onto logical units one-to-one so that pixel
        // quantities (widths, rectangle bounds) keep their numeric meaning;
        // DPI rides along as provenance metadata for present-time scaling.
        let canvas_logical = LogicalSize::new(f64::from(width_px), f64::from(height_px))
            .map_err(|_| invalid_input("canvas size is out of supported logical range"))?;
        let plot_rect_logical = LogicalRect::new(
            f64::from(x_min),
            f64::from(y_min),
            f64::from(x_max),
            f64::from(y_max),
        )
        .map_err(|_| invalid_input("plot rectangle is out of supported logical range"))?;
        let style =
            LineStyle::new(line_color, line_width_px).map_err(|error| engine_error(&error))?;
        let inner = LineFrameSpec::new(canvas_logical, plot_rect_logical, 1.0, style, background)
            .map_err(|error| engine_error(&error))?;
        Ok(Self {
            inner,
            canvas_px,
            dots_per_inch,
            line_color,
            line_width_px,
        })
    }

    /// Canvas size in pixels, `[width, height]`.
    pub fn canvas_px(&self) -> [u32; 2] {
        self.canvas_px
    }

    /// Logical dots-per-inch recorded on specs built from this spec.
    pub fn dots_per_inch(&self) -> f64 {
        self.dots_per_inch
    }
}

/// Whole-packet immutable description of what to draw.
///
/// Produced only by [`SceneHandle::resolve_frame`]; renderers treat it as
/// read-only input for their prepare / draw / present steps.
#[derive(Clone)]
pub struct FramePacket {
    pub(crate) revision: PacketRevision,
    pub(crate) canvas_px: [u32; 2],
    pub(crate) dots_per_inch: f64,
    pub(crate) layout: ResolvedLayout,
    pub(crate) line_color: SrgbRgba8,
    pub(crate) line_width_px: f64,
    pub(crate) series: Vec<PacketSeries>,
}

impl FramePacket {
    /// Scene revision the packet was resolved at.
    pub fn revision(&self) -> PacketRevision {
        self.revision
    }

    /// Canvas size in pixels, `[width, height]`.
    pub fn canvas_px(&self) -> [u32; 2] {
        self.canvas_px
    }

    /// Logical dots-per-inch the packet was sized for.
    pub fn dots_per_inch(&self) -> f64 {
        self.dots_per_inch
    }

    /// Canvas size in logical units.
    pub fn canvas_logical(&self) -> LogicalSize {
        self.layout.canvas
    }

    /// Plot rectangle in logical units.
    pub fn plot_rect(&self) -> LogicalRect {
        self.layout.plot_rect
    }

    /// Logical units-per-inch recorded on the resolved frame.
    pub fn logical_units_per_inch(&self) -> f64 {
        self.layout.logical_units_per_inch
    }

    /// Fill color of the plot background.
    pub fn background(&self) -> SrgbRgba8 {
        self.layout.background
    }

    /// Resolved line series in display space.
    pub fn series(&self) -> &[PacketSeries] {
        &self.series
    }
}

/// One resolved line series in display space.
#[derive(Clone, Default)]
pub struct PacketSeries {
    pub(crate) segments: Vec<PacketSegment>,
}

impl PacketSeries {
    /// Clipped polyline segments in display space.
    pub fn segments(&self) -> &[PacketSegment] {
        &self.segments
    }
}

/// One clipped polyline segment in display space.
#[derive(Clone, Default)]
pub struct PacketSegment {
    pub(crate) points: Vec<PacketPoint>,
}

impl PacketSegment {
    /// Display-space vertices of this segment.
    pub fn points(&self) -> &[PacketPoint] {
        &self.points
    }
}

/// One display-space vertex.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PacketPoint {
    pub(crate) x: f64,
    pub(crate) y: f64,
}

impl PacketPoint {
    /// Creates a vertex from display-space coordinates.
    pub fn new(x: f64, y: f64) -> Self {
        Self { x, y }
    }

    /// Horizontal coordinate in logical units (pixels at unit scale).
    pub fn x(&self) -> f64 {
        self.x
    }

    /// Vertical coordinate in logical units (pixels at unit scale).
    pub fn y(&self) -> f64 {
        self.y
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const FIXTURE_POINTS: usize = 10_000;
    const CANVAS_W: u32 = 800;
    const CANVAS_H: u32 = 600;

    fn fixture_xy() -> (Vec<f64>, Vec<f64>) {
        let count = FIXTURE_POINTS;
        let mut xs = Vec::with_capacity(count);
        let mut ys = Vec::with_capacity(count);
        for index in 0..count {
            let x = index as f64 / (count - 1) as f64;
            let y = 0.5 + 0.35 * (6.0 * std::f64::consts::PI * x).sin() + 0.1 * x;
            xs.push(x);
            ys.push(y);
        }
        (xs, ys)
    }

    fn fixture_spec() -> FrameSpec {
        // Same geometry family as the O-08 bench fixture: 10k-point line on an
        // 800x600 canvas at 100 DPI with a margins-around-plot layout.
        FrameSpec::new(
            [CANVAS_W, CANVAS_H],
            [60, 40, 780, 570],
            100.0,
            SrgbRgba8::new(31, 119, 180, 255),
            2.0,
            SrgbRgba8::new(255, 255, 255, 255),
        )
        .expect("spec")
    }

    fn fixture_handle() -> SceneHandle {
        let mut handle = SceneHandle::new(Viewport::from_bounds(0.0, 1.0, 0.0, 1.0).expect("view"))
            .expect("handle");
        let (xs, ys) = fixture_xy();
        handle.add_series(xs, ys).expect("series");
        handle
    }

    #[test]
    fn fixture_packet_resolves_the_bench_fixture_shape() {
        let handle = fixture_handle();
        let packet = handle.resolve_frame(&fixture_spec()).expect("packet");
        assert_eq!(packet.canvas_px(), [CANVAS_W, CANVAS_H]);
        assert_eq!(packet.dots_per_inch(), 100.0);
        assert_eq!(packet.revision(), handle.revision());
        assert_eq!(packet.series().len(), 1);
        let total_points: usize = packet.series()[0]
            .segments()
            .iter()
            .map(|segment| segment.points().len())
            .sum();
        assert_eq!(total_points, FIXTURE_POINTS);
        for series in packet.series() {
            for segment in series.segments() {
                for point in segment.points() {
                    assert!((0.0..=f64::from(CANVAS_W)).contains(&point.x()));
                    assert!((0.0..=f64::from(CANVAS_H)).contains(&point.y()));
                }
            }
        }
        // Monotone-in-x data resolves left-edge-first: the first vertex sits
        // on the plot rectangle's left edge at mid-height (the fixture starts
        // at canonical y = 0.5 on a 0..1 view).
        let first = packet.series()[0].segments()[0].points()[0];
        assert!((first.x() - 60.0).abs() < 1e-9);
        assert!((first.y() - 305.0).abs() < 1e-9);
    }

    #[test]
    fn packet_exposes_one_resolved_logical_layout_to_consumers() {
        let handle = fixture_handle();
        let packet = handle.resolve_frame(&fixture_spec()).expect("packet");

        assert_eq!(packet.canvas_logical().width(), f64::from(CANVAS_W));
        assert_eq!(packet.canvas_logical().height(), f64::from(CANVAS_H));
        assert_eq!(packet.plot_rect().x_min(), 60.0);
        assert_eq!(packet.plot_rect().y_min(), 40.0);
        assert_eq!(packet.plot_rect().x_max(), 780.0);
        assert_eq!(packet.plot_rect().y_max(), 570.0);
        assert_eq!(packet.logical_units_per_inch(), 1.0);
        let background = packet.background();
        assert_eq!(
            (
                background.r(),
                background.g(),
                background.b(),
                background.a()
            ),
            (255, 255, 255, 255,)
        );
    }

    #[test]
    fn revisions_advance_with_scene_mutations() {
        let mut handle = SceneHandle::new(Viewport::from_bounds(0.0, 1.0, 0.0, 1.0).expect("view"))
            .expect("handle");
        let initial = handle.revision();
        handle
            .add_series(vec![0.0, 1.0], vec![0.0, 1.0])
            .expect("add");
        let after = handle.revision();
        assert!(after > initial);
        let packet = handle.resolve_frame(&fixture_spec()).expect("packet");
        assert_eq!(packet.revision(), after);
    }

    #[test]
    fn invalid_dpi_canvas_and_line_width_are_rejected() {
        for dpi in [0.0, -1.0, f64::NAN, f64::INFINITY] {
            let error = FrameSpec::new(
                [CANVAS_W, CANVAS_H],
                [60, 40, 780, 570],
                dpi,
                SrgbRgba8::new(0, 0, 0, 255),
                1.0,
                SrgbRgba8::new(255, 255, 255, 255),
            )
            .err()
            .expect("dpi must validate");
            assert_eq!(error.kind(), FrameSeamErrorKind::InvalidInput);
        }
        for canvas in [[0, CANVAS_H], [CANVAS_W, 0]] {
            let error = FrameSpec::new(
                canvas,
                [0, 0, 1, 1],
                100.0,
                SrgbRgba8::new(0, 0, 0, 255),
                1.0,
                SrgbRgba8::new(255, 255, 255, 255),
            )
            .err()
            .expect("empty canvas must be rejected");
            assert_eq!(error.kind(), FrameSeamErrorKind::InvalidInput);
        }
        for width in [0.0, -1.0, f64::NAN, f64::INFINITY] {
            let error = FrameSpec::new(
                [CANVAS_W, CANVAS_H],
                [60, 40, 780, 570],
                100.0,
                SrgbRgba8::new(0, 0, 0, 255),
                width,
                SrgbRgba8::new(255, 255, 255, 255),
            )
            .err()
            .expect("line width must validate");
            assert_eq!(error.kind(), FrameSeamErrorKind::InvalidInput);
        }
    }

    #[test]
    fn plot_rect_outside_the_canvas_is_rejected() {
        for rect in [
            [0, 0, CANVAS_W + 1, 570],
            [60, 40, 780, CANVAS_H + 1],
            [780, 40, 60, 570],
            [60, 570, 780, 40],
        ] {
            let error = FrameSpec::new(
                [CANVAS_W, CANVAS_H],
                rect,
                100.0,
                SrgbRgba8::new(0, 0, 0, 255),
                1.0,
                SrgbRgba8::new(255, 255, 255, 255),
            )
            .err()
            .expect("rect must stay inside the canvas");
            assert_eq!(error.kind(), FrameSeamErrorKind::InvalidInput);
            assert!(error.message().len() < 120);
            assert!(!error.to_string().contains(&format!("{rect:?}")));
        }
    }

    #[test]
    fn empty_series_is_accepted_but_resolves_to_no_points() {
        // The engine admits empty series at add time; the seam keeps that
        // behavior and an empty series simply contributes zero points to the
        // packet rather than erroring.
        let mut handle = SceneHandle::new(Viewport::from_bounds(0.0, 1.0, 0.0, 1.0).expect("view"))
            .expect("handle");
        handle.add_series(Vec::new(), Vec::new()).expect("empty");
        let packet = handle.resolve_frame(&fixture_spec()).expect("packet");
        let total_points: usize = packet
            .series()
            .iter()
            .map(|series| {
                series
                    .segments()
                    .iter()
                    .map(|segment| segment.points().len())
                    .sum::<usize>()
            })
            .sum();
        assert_eq!(total_points, 0);
    }

    #[test]
    fn mismatched_series_data_is_rejected_without_panicking() {
        let mut handle = SceneHandle::new(Viewport::from_bounds(0.0, 1.0, 0.0, 1.0).expect("view"))
            .expect("handle");
        let error = handle
            .add_series(vec![0.0, 1.0, 2.0], vec![0.0, 1.0])
            .expect_err("mismatched lengths must be rejected");
        assert_eq!(error.kind(), FrameSeamErrorKind::InvalidInput);
    }

    #[test]
    fn series_capacity_boundary_matches_engine_cap() {
        ensure_series_capacity(MAX_FRAME_SERIES - 1).expect("just below cap");
        let error = ensure_series_capacity(MAX_FRAME_SERIES).expect_err("one past the cap");
        assert_eq!(error.kind(), FrameSeamErrorKind::CapacityExceeded);
        let error =
            ensure_series_capacity(usize::MAX).expect_err("maximum count must not overflow");
        assert_eq!(error.kind(), FrameSeamErrorKind::CapacityExceeded);
    }

    #[test]
    fn error_messages_stay_sanitized() {
        let spec_error = FrameSpec::new(
            [CANVAS_W, CANVAS_H],
            [60, 40, 780, 570],
            -3.0,
            SrgbRgba8::new(0, 0, 0, 255),
            1.0,
            SrgbRgba8::new(255, 255, 255, 255),
        )
        .err()
        .expect("negative dpi");
        assert!(!spec_error.message().contains("-3"));
        // Non-finite view bounds are rejected at handle construction.
        assert!(Viewport::from_bounds(f64::NAN, 1.0, 0.0, 1.0).is_err());
        assert!(Viewport::from_bounds(2.0, 1.0, 0.0, 1.0).is_err());
    }
}
