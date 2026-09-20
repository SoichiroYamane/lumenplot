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
use std::sync::Arc;

use crate::packet::{
    DeviceGeneration, PacketValidationError, RenderPacket, RenderPacketBuilder, WorkGeneration,
};
use lumenplot_engine::bridge::{
    AxisScale, AxisScales, LineFrameSpec, LineStyle, LogicalRect, LogicalSize, PlotLayout,
    PlotScene, SceneError as EngineSceneError, SceneErrorKind as EngineSceneErrorKind,
    SceneRevision, SeriesData, SeriesTopology, SrgbRgba8, Viewport,
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
        let plot_layout = Arc::new(frame.plot_layout().clone());
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
            plot_layout,
            font_revision: frame.plot_layout().font_revision(),
            layout_revision: frame.plot_layout().layout_revision(),
            line_color: spec.line_color,
            line_width_px: spec.line_width_px,
            series,
            three_d: None,
            fill_bar: None,
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

/// Backend-neutral projection mode for the internal 3D semantic frame.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Projection3D {
    Perspective,
    Orthographic,
}

/// Public semantic view facts; the projection matrix remains renderer-local.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ViewFacts3D {
    projection: Projection3D,
    elevation_deg: f64,
    azimuth_deg: f64,
    roll_deg: f64,
    focal_length: Option<f64>,
}

impl ViewFacts3D {
    pub fn new(
        projection: Projection3D,
        elevation_deg: f64,
        azimuth_deg: f64,
        roll_deg: f64,
        focal_length: Option<f64>,
    ) -> Result<Self, FrameSeamError> {
        if ![elevation_deg, azimuth_deg, roll_deg]
            .iter()
            .all(|value| value.is_finite())
            || focal_length.is_some_and(|value| !value.is_finite() || value <= 0.0)
            || (matches!(projection, Projection3D::Perspective) && focal_length.is_none())
            || (matches!(projection, Projection3D::Orthographic) && focal_length.is_some())
        {
            return Err(invalid_input("3D view facts are invalid"));
        }
        Ok(Self {
            projection,
            elevation_deg,
            azimuth_deg,
            roll_deg,
            focal_length,
        })
    }

    pub fn projection(self) -> Projection3D {
        self.projection
    }

    pub fn elevation_deg(self) -> f64 {
        self.elevation_deg
    }

    pub fn azimuth_deg(self) -> f64 {
        self.azimuth_deg
    }

    pub fn roll_deg(self) -> f64 {
        self.roll_deg
    }

    pub fn focal_length(self) -> Option<f64> {
        self.focal_length
    }
}

/// Canonical f64 x/y/z bound pairs carried by one 3D semantic frame.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Bounds3D {
    x: [f64; 2],
    y: [f64; 2],
    z: [f64; 2],
}

impl Bounds3D {
    pub fn new(x: [f64; 2], y: [f64; 2], z: [f64; 2]) -> Result<Self, FrameSeamError> {
        if [x, y, z].iter().any(|pair| {
            !pair[0].is_finite()
                || !pair[1].is_finite()
                || pair[0] >= pair[1]
                || !(pair[1] - pair[0]).is_finite()
        }) {
            return Err(invalid_input("3D bounds are invalid"));
        }
        Ok(Self { x, y, z })
    }

    pub fn x(self) -> [f64; 2] {
        self.x
    }

    pub fn y(self) -> [f64; 2] {
        self.y
    }

    pub fn z(self) -> [f64; 2] {
        self.z
    }
}

/// Canonical f64 source coordinate, retained alongside projected geometry.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Point3D {
    x: f64,
    y: f64,
    z: f64,
}

impl Point3D {
    pub fn new(x: f64, y: f64, z: f64) -> Self {
        Self { x, y, z }
    }

    pub fn x(self) -> f64 {
        self.x
    }

    pub fn y(self) -> f64 {
        self.y
    }

    pub fn z(self) -> f64 {
        self.z
    }
}

#[derive(Clone)]
pub struct Line3DGeometry {
    source: Vec<Point3D>,
    projected: Vec<PacketPoint>,
    segments: Vec<std::ops::Range<usize>>,
    color: SrgbRgba8,
    width_px: f64,
}

impl Line3DGeometry {
    pub fn new(
        source: Vec<Point3D>,
        projected: Vec<PacketPoint>,
        segments: Vec<std::ops::Range<usize>>,
        color: SrgbRgba8,
        width_px: f64,
    ) -> Result<Self, FrameSeamError> {
        let mut previous_end = 0usize;
        let mut segments_valid = true;
        for range in &segments {
            if range.start >= range.end
                || range.end > source.len()
                || range.start < previous_end
                || source[range.start..range.end].iter().any(|point| {
                    !point.x.is_finite() || !point.y.is_finite() || !point.z.is_finite()
                })
            {
                segments_valid = false;
                break;
            }
            previous_end = range.end;
        }
        let source_runs_cover_finite = if segments_valid {
            let mut cursor = 0usize;
            let mut valid = true;
            for range in &segments {
                if source[cursor..range.start]
                    .iter()
                    .any(|point| point.x.is_finite() && point.y.is_finite() && point.z.is_finite())
                {
                    valid = false;
                    break;
                }
                cursor = range.end;
            }
            valid
                && !source[cursor..]
                    .iter()
                    .any(|point| point.x.is_finite() && point.y.is_finite() && point.z.is_finite())
        } else {
            false
        };
        let projected_semantics_match = source.iter().zip(&projected).all(|(source, point)| {
            let source_finite =
                source.x.is_finite() && source.y.is_finite() && source.z.is_finite();
            let projected_finite = point.x.is_finite() && point.y.is_finite();
            let projected_nonfinite = !point.x.is_finite() && !point.y.is_finite();
            (source_finite == projected_finite) && (projected_finite || projected_nonfinite)
        });
        if source.len() != projected.len()
            || !width_px.is_finite()
            || width_px < 0.0
            || !segments_valid
            || !source_runs_cover_finite
            || !projected_semantics_match
        {
            return Err(invalid_input("3D line geometry is invalid"));
        }
        Ok(Self {
            source,
            projected,
            segments,
            color,
            width_px,
        })
    }

    pub fn source(&self) -> &[Point3D] {
        &self.source
    }

    pub fn projected(&self) -> &[PacketPoint] {
        &self.projected
    }

    pub fn segments(&self) -> &[std::ops::Range<usize>] {
        &self.segments
    }

    pub fn color(&self) -> SrgbRgba8 {
        self.color
    }

    pub fn width_px(&self) -> f64 {
        self.width_px
    }
}

#[derive(Clone)]
pub struct Triangle3DGeometry {
    source: [Point3D; 3],
    projected: [PacketPoint; 3],
    fill: SrgbRgba8,
    edge: Option<SrgbRgba8>,
    width_px: f64,
    source_index: usize,
    depth: f64,
}

impl Triangle3DGeometry {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        source: [Point3D; 3],
        projected: [PacketPoint; 3],
        fill: SrgbRgba8,
        edge: Option<SrgbRgba8>,
        width_px: f64,
        source_index: usize,
        depth: f64,
    ) -> Result<Self, FrameSeamError> {
        if source
            .iter()
            .any(|point| !point.x.is_finite() || !point.y.is_finite() || !point.z.is_finite())
            || projected
                .iter()
                .any(|point| !point.x.is_finite() || !point.y.is_finite())
            || !width_px.is_finite()
            || width_px < 0.0
            || !depth.is_finite()
        {
            return Err(invalid_input("3D triangle geometry is invalid"));
        }
        Ok(Self {
            source,
            projected,
            fill,
            edge,
            width_px,
            source_index,
            depth,
        })
    }

    pub fn source(&self) -> &[Point3D; 3] {
        &self.source
    }

    pub fn projected(&self) -> &[PacketPoint; 3] {
        &self.projected
    }

    pub fn fill(&self) -> SrgbRgba8 {
        self.fill
    }

    pub fn edge(&self) -> Option<SrgbRgba8> {
        self.edge
    }

    pub fn width_px(&self) -> f64 {
        self.width_px
    }

    pub fn source_index(&self) -> usize {
        self.source_index
    }

    pub fn depth(&self) -> f64 {
        self.depth
    }
}

fn bound_midpoint(pair: [f64; 2]) -> f64 {
    pair[0] + (pair[1] - pair[0]) * 0.5
}

/// Additive 3D meaning carried by the shared semantic frame.
#[derive(Clone)]
pub struct Semantic3D {
    view: ViewFacts3D,
    bounds: Bounds3D,
    origin: Point3D,
    lines: Vec<Line3DGeometry>,
    triangles: Vec<Triangle3DGeometry>,
    painter_order: Vec<usize>,
    worst_error_px: f64,
}

impl Semantic3D {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        view: ViewFacts3D,
        bounds: Bounds3D,
        origin: Point3D,
        lines: Vec<Line3DGeometry>,
        triangles: Vec<Triangle3DGeometry>,
        painter_order: Vec<usize>,
        worst_error_px: f64,
    ) -> Result<Self, FrameSeamError> {
        let expected_origin = Point3D::new(
            bound_midpoint(bounds.x()),
            bound_midpoint(bounds.y()),
            bound_midpoint(bounds.z()),
        );
        if !origin.x.is_finite()
            || !origin.y.is_finite()
            || !origin.z.is_finite()
            || origin != expected_origin
            || !worst_error_px.is_finite()
            || !(0.0..=0.25).contains(&worst_error_px)
            || painter_order.len() != triangles.len()
            || painter_order.iter().any(|index| *index >= triangles.len())
            || {
                let mut sorted = painter_order.clone();
                sorted.sort_unstable();
                sorted.windows(2).any(|pair| pair[0] == pair[1])
                    || sorted
                        .iter()
                        .enumerate()
                        .any(|(index, value)| *value != index)
            }
        {
            return Err(invalid_input("3D semantic facts are invalid"));
        }
        Ok(Self {
            view,
            bounds,
            origin,
            lines,
            triangles,
            painter_order,
            worst_error_px,
        })
    }

    pub fn view(&self) -> ViewFacts3D {
        self.view
    }

    pub fn bounds(&self) -> Bounds3D {
        self.bounds
    }

    pub fn origin(&self) -> Point3D {
        self.origin
    }

    pub fn lines(&self) -> &[Line3DGeometry] {
        &self.lines
    }

    pub fn triangles(&self) -> &[Triangle3DGeometry] {
        &self.triangles
    }

    pub fn painter_order(&self) -> &[usize] {
        &self.painter_order
    }

    pub fn worst_error_px(&self) -> f64 {
        self.worst_error_px
    }

    pub(crate) fn validate_for_canvas(&self, width: f64, height: f64) -> bool {
        self.lines.iter().all(|line| {
            line.projected.iter().all(|point| {
                (!point.x.is_finite() && !point.y.is_finite())
                    || (point.x >= 0.0 && point.y >= 0.0 && point.x <= width && point.y <= height)
            })
        }) && self.triangles.iter().all(|triangle| {
            triangle.projected.iter().all(|point| {
                point.x >= 0.0 && point.y >= 0.0 && point.x <= width && point.y <= height
            })
        })
    }
}

/// Which fill-bar family a paint key addresses.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FillFamily {
    Fill,
    Bar,
}

/// Position of one fill/bar primitive in the fills-first paint order.
///
/// `paint_order` on [`SemanticFillBar`] is an exact permutation over fills +
/// bars: every fill polygon and bar rectangle paints exactly once beneath the
/// line family, which keeps its own draw order on top (decision D4, the fixed
/// rule mirroring default zorder).
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PaintKey {
    family: FillFamily,
    index: usize,
}

impl PaintKey {
    /// Key addressing the `index`-th fill polygon.
    pub fn fill(index: usize) -> Self {
        Self {
            family: FillFamily::Fill,
            index,
        }
    }

    /// Key addressing the `index`-th bar rectangle.
    pub fn bar(index: usize) -> Self {
        Self {
            family: FillFamily::Bar,
            index,
        }
    }

    /// Family addressed by this key.
    pub fn family(self) -> FillFamily {
        self.family
    }

    /// Index within the family addressed by this key.
    pub fn index(self) -> usize {
        self.index
    }
}

/// Edge stroke resolved for one fill/bar primitive.
///
/// Paint stays inline on the primitive (decision D3), so the packet resource
/// table is unchanged. The consumer strokes the edge immediately after its
/// own fill (decision D5). Width mirrors the [`LineStyle`] contract: finite
/// and positive at construction, re-checked by
/// [`SemanticFillBar::validate_for_canvas`]; like the 3D triangle widths,
/// this slice sets no packet-level upper bound.
#[derive(Clone, Copy, PartialEq)]
pub struct EdgeStyle {
    color: SrgbRgba8,
    width_px: f64,
}

impl EdgeStyle {
    /// Creates an edge stroke; rejects non-finite or non-positive widths.
    pub fn new(color: SrgbRgba8, width_px: f64) -> Result<Self, FrameSeamError> {
        if !width_px.is_finite() || width_px <= 0.0 {
            return Err(invalid_input("fill-bar edge style is invalid"));
        }
        Ok(Self { color, width_px })
    }

    /// Resolved edge color.
    pub fn color(self) -> SrgbRgba8 {
        self.color
    }

    /// Edge width in display pixels.
    pub fn width_px(self) -> f64 {
        self.width_px
    }
}

/// One closed display-space fill ring.
///
/// Carries `fill_between` bands and Polygon patches as absolute geometry:
/// baseline/`bottom=`/stack offsets, NaN-gap splitting, and color resolution
/// all stay adapter-side and never reach the frame. Closure is implicit
/// (decision D2): the ring is stored open and the consumer closes
/// last-to-first; construction requires at least three finite vertices and
/// [`SemanticFillBar::validate_for_canvas`] re-checks in-canvas placement.
#[derive(Clone, PartialEq)]
pub struct FillPolygon {
    points: Vec<PacketPoint>,
    fill: SrgbRgba8,
    edge: Option<EdgeStyle>,
}

impl FillPolygon {
    /// Creates a fill ring; rejects rings under three points or with
    /// non-finite vertices. The message stays sanitized: it never embeds
    /// vertex values.
    pub fn new(
        points: Vec<PacketPoint>,
        fill: SrgbRgba8,
        edge: Option<EdgeStyle>,
    ) -> Result<Self, FrameSeamError> {
        if points.len() < 3
            || points
                .iter()
                .any(|point| !point.x.is_finite() || !point.y.is_finite())
        {
            return Err(invalid_input("fill polygon is invalid"));
        }
        Ok(Self { points, fill, edge })
    }

    /// Open ring vertices in display space; the consumer closes the ring.
    pub fn points(&self) -> &[PacketPoint] {
        &self.points
    }

    /// Resolved fill paint.
    pub fn fill(&self) -> SrgbRgba8 {
        self.fill
    }

    /// Optional edge stroked immediately after this fill.
    pub fn edge(&self) -> Option<EdgeStyle> {
        self.edge
    }
}

/// One absolute display-space bar rectangle.
///
/// Bar x positions, widths, baselines, `bottom=`, and stacked accumulation
/// resolve to this absolute rectangle adapter-side; histogram binning and
/// color-cycle resolution likewise never reach the frame. [`LogicalRect::new`]
/// rejects degenerate or non-finite rectangles at construction and
/// [`SemanticFillBar::validate_for_canvas`] re-checks in-canvas placement.
#[derive(Clone, Copy, PartialEq)]
pub struct BarRect {
    rect: LogicalRect,
    fill: SrgbRgba8,
    edge: Option<EdgeStyle>,
}

impl BarRect {
    /// Creates a bar rectangle from an already-validated absolute rect.
    pub fn new(rect: LogicalRect, fill: SrgbRgba8, edge: Option<EdgeStyle>) -> Self {
        Self { rect, fill, edge }
    }

    /// Absolute rectangle in display space.
    pub fn rect(self) -> LogicalRect {
        self.rect
    }

    /// Resolved fill paint.
    pub fn fill(self) -> SrgbRgba8 {
        self.fill
    }

    /// Optional edge stroked immediately after this fill.
    pub fn edge(self) -> Option<EdgeStyle> {
        self.edge
    }
}

/// Additive fill/bar meaning carried by the shared semantic frame.
///
/// Decision D1 selects this over a unified fill-primitive family: it mirrors
/// the accepted [`Semantic3D`] precedent with zero change to the M1 line
/// fields, line draws, and the line draw-count invariant.
///
/// Ownership: the producer (`SceneHandle::resolve_frame_candidate`, fed by
/// adapter-resolved absolute geometry) constructs these primitives;
/// renderers never feed the frame. The packet builder validates the family
/// all-or-nothing with everything else; generations, lease/fence retirement,
/// and loss rebuild are unchanged, and no new generation type is introduced.
///
/// Paint rule: `paint_order` is an exact permutation over fills + bars;
/// fills and bars paint first in that order and the line family draws on top
/// (decision D4, the fixed rule mirroring default zorder).
///
/// Renderer consumption (M3-FB-CONSUME-B): the validated-only carrier is
/// `RenderPacket::semantic_frame().fill_bar()`; no new accessor exists.
/// The `FramePacket` carriage stays `pub(crate)`, so the legacy
/// `render(&FramePacket)` entry cannot observe fill/bar meaning and stays
/// line-only. The hidden validated entry consumes this value in
/// `paint_order` beneath the line family (decision D4) with each edge
/// stroked immediately after its own fill (decision D5).
#[derive(Clone)]
pub struct SemanticFillBar {
    fills: Vec<FillPolygon>,
    bars: Vec<BarRect>,
    paint_order: Vec<PaintKey>,
}

impl SemanticFillBar {
    /// Creates fill/bar meaning; `paint_order` must be an exact permutation
    /// over fills + bars (mirrors the `Semantic3D` painter-order check).
    /// Empty fills + bars with an empty order resolves to zero primitives,
    /// mirroring the empty-series rule.
    pub fn new(
        fills: Vec<FillPolygon>,
        bars: Vec<BarRect>,
        paint_order: Vec<PaintKey>,
    ) -> Result<Self, FrameSeamError> {
        // Map each key to a linear slot (fills first, then bars) and require
        // full 0..n coverage without duplicates or out-of-range indices.
        let mut slots_valid = paint_order.len() == fills.len() + bars.len();
        let mut slots = Vec::with_capacity(paint_order.len());
        for key in &paint_order {
            let slot = match key.family {
                FillFamily::Fill if key.index < fills.len() => key.index,
                FillFamily::Bar if key.index < bars.len() => fills.len() + key.index,
                _ => {
                    slots_valid = false;
                    break;
                }
            };
            slots.push(slot);
        }
        if slots_valid {
            slots.sort_unstable();
            if slots
                .iter()
                .enumerate()
                .any(|(index, value)| *value != index)
            {
                slots_valid = false;
            }
        }
        if !slots_valid {
            return Err(invalid_input("fill-bar paint order is invalid"));
        }
        Ok(Self {
            fills,
            bars,
            paint_order,
        })
    }

    /// Fill rings in carriage order.
    pub fn fills(&self) -> &[FillPolygon] {
        &self.fills
    }

    /// Bar rectangles in carriage order.
    pub fn bars(&self) -> &[BarRect] {
        &self.bars
    }

    /// Exact permutation over fills + bars, painted beneath the lines.
    pub fn paint_order(&self) -> &[PaintKey] {
        &self.paint_order
    }

    pub(crate) fn validate_for_canvas(&self, width: f64, height: f64) -> bool {
        self.fills.iter().all(|fill| {
            fill.points.iter().all(|point| {
                point.x.is_finite()
                    && point.y.is_finite()
                    && point.x >= 0.0
                    && point.y >= 0.0
                    && point.x <= width
                    && point.y <= height
            }) && fill
                .edge
                .is_none_or(|edge| edge.width_px.is_finite() && edge.width_px > 0.0)
        }) && self.bars.iter().all(|bar| {
            let rect = bar.rect;
            rect.x_min().is_finite()
                && rect.y_min().is_finite()
                && rect.x_max().is_finite()
                && rect.y_max().is_finite()
                && rect.x_min() >= 0.0
                && rect.y_min() >= 0.0
                && rect.x_max() <= width
                && rect.y_max() <= height
                && bar
                    .edge
                    .is_none_or(|edge| edge.width_px.is_finite() && edge.width_px > 0.0)
        })
    }
}

/// Shared backend-neutral semantic/layout result for one resolved scene.
///
/// The current M2 implementation carries the bounded line-family meaning from
/// the retained M1 seam.  Keeping it as a distinct process-local value makes
/// the semantic source explicit: a [`RenderPacket`] is a validated projection
/// of this value, while the M1 [`FramePacket`] remains available to existing
/// consumers during the staged migration.
#[derive(Clone)]
pub struct SemanticFrame {
    frame: FramePacket,
}

impl SemanticFrame {
    pub(crate) fn from_frame(frame: FramePacket) -> Self {
        Self { frame }
    }

    /// The resolved M1 view of the shared semantic/layout meaning.
    pub fn frame(&self) -> &FramePacket {
        &self.frame
    }

    /// Retained text/layout result shared by the renderer-owner consumers.
    pub fn plot_layout(&self) -> &PlotLayout {
        &self.frame.plot_layout
    }

    /// Optional additive 3D meaning carried by this semantic frame.
    pub fn three_d(&self) -> Option<&Semantic3D> {
        self.frame.three_d()
    }

    /// Optional additive fill/bar meaning carried by this semantic frame.
    ///
    /// Validated-only renderer projection: the hidden validated render
    /// entry reads this value and paints it beneath the line family
    /// (decisions D4/D5). The `FramePacket` carriage stays `pub(crate)`
    /// with no new accessor.
    pub fn fill_bar(&self) -> Option<&SemanticFillBar> {
        self.frame.fill_bar()
    }

    #[cfg(test)]
    pub(crate) fn frame_mut(&mut self) -> &mut FramePacket {
        &mut self.frame
    }
}

/// Whole-packet immutable description of the frame to draw.
///
/// Produced only by [`SceneHandle::resolve_frame`]; renderers treat it as
/// read-only input for their prepare / draw / present steps.
#[derive(Clone)]
pub struct FramePacket {
    pub(crate) revision: PacketRevision,
    pub(crate) canvas_px: [u32; 2],
    pub(crate) dots_per_inch: f64,
    pub(crate) layout: ResolvedLayout,
    pub(crate) plot_layout: Arc<PlotLayout>,
    pub(crate) font_revision: u64,
    pub(crate) layout_revision: u64,
    pub(crate) line_color: SrgbRgba8,
    pub(crate) line_width_px: f64,
    pub(crate) series: Vec<PacketSeries>,
    pub(crate) three_d: Option<Semantic3D>,
    pub(crate) fill_bar: Option<SemanticFillBar>,
}

impl FramePacket {
    /// Attach additive 3D semantic facts without changing the M1 frame seam.
    #[allow(dead_code)]
    pub(crate) fn with_three_d(mut self, three_d: Semantic3D) -> Self {
        self.three_d = Some(three_d);
        self
    }

    pub(crate) fn three_d(&self) -> Option<&Semantic3D> {
        self.three_d.as_ref()
    }

    /// Attach additive fill/bar semantic facts without changing the M1 frame
    /// seam or the line draw path (decision D1).
    #[allow(dead_code)]
    pub(crate) fn with_fill_bar(mut self, fill_bar: SemanticFillBar) -> Self {
        self.fill_bar = Some(fill_bar);
        self
    }

    pub(crate) fn fill_bar(&self) -> Option<&SemanticFillBar> {
        self.fill_bar.as_ref()
    }

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

    /// Encoded straight-sRGB line color resolved for this frame.
    pub fn line_color(&self) -> SrgbRgba8 {
        self.line_color
    }

    /// Line width in display pixels resolved for this frame.
    pub fn line_width_px(&self) -> f64 {
        self.line_width_px
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
        assert!(packet.line_color() == SrgbRgba8::new(31, 119, 180, 255));
        assert_eq!(packet.line_width_px(), 2.0);
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
    fn three_d_origin_uses_an_overflow_safe_midpoint() {
        let bounds = Bounds3D::new([9.0e307, 1.0e308], [-1.0e308, -9.0e307], [0.0, 2.0])
            .expect("finite bounds");
        let semantic = Semantic3D::new(
            ViewFacts3D::new(Projection3D::Perspective, 30.0, -60.0, 0.0, Some(1.0)).expect("view"),
            bounds,
            Point3D::new(9.5e307, -9.5e307, 1.0),
            Vec::new(),
            Vec::new(),
            Vec::new(),
            0.0,
        )
        .expect("semantic facts");
        assert_eq!(semantic.origin(), Point3D::new(9.5e307, -9.5e307, 1.0));
    }

    #[test]
    fn three_d_line_segments_cover_only_finite_runs_in_order() {
        let source = vec![
            Point3D::new(0.0, 0.0, 0.0),
            Point3D::new(f64::NAN, f64::NAN, f64::NAN),
            Point3D::new(1.0, 1.0, 1.0),
        ];
        let projected = vec![
            PacketPoint::new(10.0, 10.0),
            PacketPoint::new(f64::NAN, f64::NAN),
            PacketPoint::new(20.0, 20.0),
        ];
        let valid = Line3DGeometry::new(
            source.clone(),
            projected.clone(),
            vec![0..1, 2..3],
            SrgbRgba8::new(1, 2, 3, 255),
            1.0,
        )
        .expect("finite runs");
        assert_eq!(valid.segments(), &[0..1, 2..3]);
        assert!(
            Line3DGeometry::new(
                source.clone(),
                projected.clone(),
                vec![2..3, 0..1],
                SrgbRgba8::new(1, 2, 3, 255),
                1.0,
            )
            .is_err()
        );
        assert!(
            Line3DGeometry::new(
                vec![Point3D::new(0.0, 0.0, 0.0), Point3D::new(1.0, 1.0, 1.0)],
                vec![PacketPoint::new(10.0, 10.0), PacketPoint::new(20.0, 20.0)],
                std::iter::once(0..1).collect(),
                SrgbRgba8::new(1, 2, 3, 255),
                1.0,
            )
            .is_err()
        );
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

    fn fill_bar_band() -> FillPolygon {
        // Hand-derived carriage fixture: one fill_between band as an open
        // quad ring (closure is implicit per D2) with inline paint + edge.
        FillPolygon::new(
            vec![
                PacketPoint::new(100.0, 200.0),
                PacketPoint::new(200.0, 250.0),
                PacketPoint::new(300.0, 220.0),
                PacketPoint::new(100.0, 180.0),
            ],
            SrgbRgba8::new(31, 119, 180, 128),
            Some(EdgeStyle::new(SrgbRgba8::new(31, 119, 180, 255), 1.0).expect("edge")),
        )
        .expect("band")
    }

    fn fill_bar_stacked_bar() -> BarRect {
        // One bar whose stacked offset is already resolved to an absolute
        // rect adapter-side; the frame never sees the stacking inputs.
        BarRect::new(
            LogicalRect::new(400.0, 300.0, 440.0, 500.0).expect("absolute bar rect"),
            SrgbRgba8::new(255, 127, 14, 255),
            None,
        )
    }

    fn fill_bar_fixture() -> SemanticFillBar {
        SemanticFillBar::new(
            vec![fill_bar_band()],
            vec![fill_bar_stacked_bar()],
            vec![PaintKey::fill(0), PaintKey::bar(0)],
        )
        .expect("permutation")
    }

    #[test]
    fn fill_bar_fixture_carries_absolute_geometry_with_inline_paint() {
        let semantic = fill_bar_fixture();
        assert_eq!(semantic.fills().len(), 1);
        assert_eq!(semantic.bars().len(), 1);
        let band = &semantic.fills()[0];
        assert_eq!(band.points().len(), 4);
        assert_eq!(band.points()[0], PacketPoint::new(100.0, 200.0));
        assert!(band.fill() == SrgbRgba8::new(31, 119, 180, 128));
        let edge = band.edge().expect("band edge");
        assert!(edge.color() == SrgbRgba8::new(31, 119, 180, 255));
        assert_eq!(edge.width_px(), 1.0);
        let bar = semantic.bars()[0];
        assert_eq!(bar.rect().x_min(), 400.0);
        assert_eq!(bar.rect().y_min(), 300.0);
        assert_eq!(bar.rect().x_max(), 440.0);
        assert_eq!(bar.rect().y_max(), 500.0);
        assert!(bar.fill() == SrgbRgba8::new(255, 127, 14, 255));
        assert!(bar.edge().is_none());
        assert_eq!(
            semantic.paint_order(),
            &[PaintKey::fill(0), PaintKey::bar(0)]
        );
        assert_eq!(semantic.paint_order()[0].family(), FillFamily::Fill);
        assert_eq!(semantic.paint_order()[1].family(), FillFamily::Bar);
        assert!(semantic.validate_for_canvas(f64::from(CANVAS_W), f64::from(CANVAS_H)));
    }

    #[test]
    fn default_frames_carry_no_fill_bar_until_attached() {
        // The producer resolves lines only; fill/bar meaning attaches
        // additively without changing the M1 seam (decision D1).
        let handle = fixture_handle();
        let packet = handle.resolve_frame(&fixture_spec()).expect("packet");
        assert!(packet.fill_bar().is_none());
        let attached = handle
            .resolve_frame(&fixture_spec())
            .expect("packet")
            .with_fill_bar(fill_bar_fixture());
        assert!(attached.fill_bar().is_some());
    }

    #[test]
    fn fill_bar_rings_accept_implicit_close_but_reject_degenerate_geometry() {
        // An unclosed three-point ring is valid: the consumer closes
        // last-to-first (decision D2).
        FillPolygon::new(
            vec![
                PacketPoint::new(10.0, 10.0),
                PacketPoint::new(20.0, 10.0),
                PacketPoint::new(15.0, 20.0),
            ],
            SrgbRgba8::new(0, 0, 0, 255),
            None,
        )
        .expect("implicit close");
        // Under-three-point rings and non-finite vertices are rejected with
        // sanitized messages that never embed vertex values.
        for points in [
            vec![],
            vec![PacketPoint::new(10.0, 10.0)],
            vec![PacketPoint::new(10.0, 10.0), PacketPoint::new(20.0, 10.0)],
            vec![
                PacketPoint::new(9_999.0, 10.0),
                PacketPoint::new(f64::NAN, 10.0),
                PacketPoint::new(15.0, 20.0),
            ],
            vec![
                PacketPoint::new(10.0, 10.0),
                PacketPoint::new(20.0, f64::INFINITY),
                PacketPoint::new(15.0, 20.0),
            ],
        ] {
            let error = FillPolygon::new(points, SrgbRgba8::new(0, 0, 0, 255), None)
                .err()
                .expect("degenerate ring must be rejected");
            assert_eq!(error.kind(), FrameSeamErrorKind::InvalidInput);
            assert!(!error.message().contains("9999"));
        }
        // Out-of-canvas placement fails canvas validation, not construction.
        let escaped = FillPolygon::new(
            vec![
                PacketPoint::new(10.0, 10.0),
                PacketPoint::new(20.0, 10.0),
                PacketPoint::new(f64::from(CANVAS_W) + 1.0, 20.0),
            ],
            SrgbRgba8::new(0, 0, 0, 255),
            None,
        )
        .expect("construction admits canvas-external rings");
        let semantic = SemanticFillBar::new(vec![escaped], Vec::new(), vec![PaintKey::fill(0)])
            .expect("permutation");
        assert!(!semantic.validate_for_canvas(f64::from(CANVAS_W), f64::from(CANVAS_H)));
    }

    #[test]
    fn fill_bar_bars_reject_degenerate_rects_and_out_of_canvas() {
        // Degenerate or non-finite rectangles never become bars.
        assert!(
            LogicalRect::new(440.0, 300.0, 400.0, 500.0).is_err(),
            "inverted rect must be rejected"
        );
        assert!(
            LogicalRect::new(400.0, 300.0, 400.0, 500.0).is_err(),
            "zero-area rect must be rejected"
        );
        // A well-formed rect outside the canvas fails canvas validation.
        let escaped = BarRect::new(
            LogicalRect::new(0.0, 0.0, f64::from(CANVAS_W) + 1.0, 10.0).expect("rect"),
            SrgbRgba8::new(0, 0, 0, 255),
            None,
        );
        let semantic = SemanticFillBar::new(Vec::new(), vec![escaped], vec![PaintKey::bar(0)])
            .expect("permutation");
        assert!(!semantic.validate_for_canvas(f64::from(CANVAS_W), f64::from(CANVAS_H)));
    }

    #[test]
    fn fill_bar_paint_order_must_be_an_exact_permutation() {
        // Duplicates, out-of-range indices, wrong-family indices, and missing
        // primitives are all rejected (mirror of the 3D painter-order check).
        let fills = vec![fill_bar_band(), fill_bar_band()];
        let bars = vec![fill_bar_stacked_bar()];
        for order in [
            vec![PaintKey::fill(0), PaintKey::fill(0), PaintKey::bar(0)],
            vec![PaintKey::fill(0), PaintKey::fill(2), PaintKey::bar(0)],
            vec![PaintKey::fill(0), PaintKey::fill(1), PaintKey::bar(1)],
            vec![PaintKey::fill(0), PaintKey::fill(1), PaintKey::fill(0)],
            vec![PaintKey::fill(0), PaintKey::fill(1)],
            vec![PaintKey::fill(0), PaintKey::bar(0), PaintKey::bar(0)],
        ] {
            let error = SemanticFillBar::new(fills.clone(), bars.clone(), order)
                .err()
                .expect("broken permutation must be rejected");
            assert_eq!(error.kind(), FrameSeamErrorKind::InvalidInput);
        }
        SemanticFillBar::new(
            fills,
            bars,
            vec![PaintKey::bar(0), PaintKey::fill(1), PaintKey::fill(0)],
        )
        .expect("any order across families is a valid permutation");
        // Empty fills + bars with an empty order resolves to zero primitives,
        // mirroring the empty-series rule.
        let empty =
            SemanticFillBar::new(Vec::new(), Vec::new(), Vec::new()).expect("empty fill-bar");
        assert!(empty.fills().is_empty());
        assert!(empty.bars().is_empty());
        assert!(empty.validate_for_canvas(f64::from(CANVAS_W), f64::from(CANVAS_H)));
    }

    #[test]
    fn fill_bar_edge_width_must_be_finite_and_positive() {
        for width in [0.0, -1.0, f64::NAN, f64::INFINITY] {
            let error = EdgeStyle::new(SrgbRgba8::new(0, 0, 0, 255), width)
                .err()
                .expect("bad edge width must be rejected");
            assert_eq!(error.kind(), FrameSeamErrorKind::InvalidInput);
        }
        let edge = EdgeStyle::new(SrgbRgba8::new(0, 0, 0, 255), 2.5).expect("edge");
        assert_eq!(edge.width_px(), 2.5);
    }
}
