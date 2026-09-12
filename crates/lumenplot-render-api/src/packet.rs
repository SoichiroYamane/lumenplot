//! Private validated renderer packet projection.
//!
//! This module owns the M2 process-local packet boundary. Its types are kept
//! crate-private so the public M1 frame seam cannot become a persistence,
//! wire, or frontend contract by accident.

use std::collections::HashSet;
use std::fmt;
use std::ops::Range;

use lumenplot_engine::bridge::{LogicalRect, SrgbRgba8};

use crate::frame::{
    FramePacket, FrameSeamError, FrameSeamErrorKind, MAX_FRAME_DIMENSION, MAX_FRAME_PIXELS,
    MAX_FRAME_SERIES, PacketRevision, SemanticFrame,
};

const MAX_PACKET_POINTS: usize = 1_000_000;
const MAX_PACKET_SEGMENTS: usize = 1_000_000;
const MAX_PACKET_DRAWS: usize = 1_000_000;
pub(crate) const MAX_PACKET_RESOURCES: usize = 4;
const MAX_PACKET_LINE_WIDTH: f64 = 16_384.0;
const RESOURCE_GENERATION: u32 = 1;
const CLIP_RESOURCE_SLOT: u32 = 1;
const STYLE_RESOURCE_SLOT: u32 = 2;

/// Scene revision associated with the owner publication point.
///
/// This remains distinct from the engine-backed [`PacketRevision`].  It is an
/// owner token used to reject a packet after a newer scene publication.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct SceneRevision(u64);

impl SceneRevision {
    pub const fn initial() -> Self {
        Self::new(0)
    }

    pub const fn new(value: u64) -> Self {
        Self(value)
    }
}

/// Scheduler generation associated with derived packet work.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct WorkGeneration(u64);

impl WorkGeneration {
    pub const fn initial() -> Self {
        Self::new(0)
    }

    pub const fn new(value: u64) -> Self {
        Self(value)
    }

    #[cfg(test)]
    fn value(self) -> u64 {
        self.0
    }
}

/// Renderer-instance generation associated with retained logical resources.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct DeviceGeneration(u64);

impl DeviceGeneration {
    pub const fn initial() -> Self {
        Self::new(0)
    }

    pub const fn new(value: u64) -> Self {
        Self(value)
    }

    #[cfg(test)]
    fn value(self) -> u64 {
        self.0
    }
}

/// Internal validation categories; these never become a public error schema.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum PacketValidationErrorKind {
    FrameInvalid,
    CapacityExceeded,
    InvalidResourceId,
    InvalidResourceReference,
    InvalidDrawRange,
    InvalidDrawOrder,
    IncompletePacket,
    AllocationFailed,
    StaleSceneRevision,
    StaleWorkGeneration,
    StaleDeviceGeneration,
}

/// Sanitized failure from packet construction or validation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PacketValidationError {
    kind: PacketValidationErrorKind,
    message: &'static str,
}

impl PacketValidationError {
    fn new(kind: PacketValidationErrorKind, message: &'static str) -> Self {
        Self { kind, message }
    }

    pub fn kind(self) -> PacketValidationErrorKind {
        self.kind
    }

    pub(crate) fn from_frame_error(error: FrameSeamError) -> Self {
        let kind = match error.kind() {
            FrameSeamErrorKind::CapacityExceeded => PacketValidationErrorKind::CapacityExceeded,
            FrameSeamErrorKind::InvalidInput | FrameSeamErrorKind::EngineRejected => {
                PacketValidationErrorKind::FrameInvalid
            }
        };
        Self {
            kind,
            message: if matches!(kind, PacketValidationErrorKind::CapacityExceeded) {
                "packet frame exceeds a supported capacity"
            } else {
                "packet frame is invalid"
            },
        }
    }

    pub(crate) fn into_frame_error(self) -> FrameSeamError {
        let kind = match self.kind {
            PacketValidationErrorKind::CapacityExceeded => FrameSeamErrorKind::CapacityExceeded,
            PacketValidationErrorKind::FrameInvalid => FrameSeamErrorKind::InvalidInput,
            PacketValidationErrorKind::InvalidResourceId
            | PacketValidationErrorKind::InvalidResourceReference
            | PacketValidationErrorKind::InvalidDrawRange
            | PacketValidationErrorKind::InvalidDrawOrder
            | PacketValidationErrorKind::IncompletePacket
            | PacketValidationErrorKind::AllocationFailed
            | PacketValidationErrorKind::StaleSceneRevision
            | PacketValidationErrorKind::StaleWorkGeneration
            | PacketValidationErrorKind::StaleDeviceGeneration => {
                FrameSeamErrorKind::EngineRejected
            }
        };
        FrameSeamError::from_packet_error(kind, self.message)
    }
}

impl fmt::Display for PacketValidationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.message)
    }
}

impl std::error::Error for PacketValidationError {}

/// Expected publication generations for one renderer submission owner.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RenderPacketBuilder {
    expected_scene_revision: SceneRevision,
    expected_work_generation: WorkGeneration,
    expected_device_generation: DeviceGeneration,
}

impl RenderPacketBuilder {
    /// Legacy M1-compatible builder with an initial owner scene token.
    pub const fn new(
        expected_work_generation: WorkGeneration,
        expected_device_generation: DeviceGeneration,
    ) -> Self {
        Self::for_scene(
            SceneRevision::initial(),
            expected_work_generation,
            expected_device_generation,
        )
    }

    /// Builder bound to one owner scene/work/device publication point.
    pub const fn for_scene(
        expected_scene_revision: SceneRevision,
        expected_work_generation: WorkGeneration,
        expected_device_generation: DeviceGeneration,
    ) -> Self {
        Self {
            expected_scene_revision,
            expected_work_generation,
            expected_device_generation,
        }
    }

    /// Builds one complete packet, publishing nothing until every check passes.
    pub fn build(
        &self,
        frame: FramePacket,
        work_generation: WorkGeneration,
        device_generation: DeviceGeneration,
    ) -> Result<RenderPacket, PacketValidationError> {
        if work_generation != self.expected_work_generation {
            return Err(PacketValidationError::new(
                PacketValidationErrorKind::StaleWorkGeneration,
                "packet work generation is stale",
            ));
        }
        if device_generation != self.expected_device_generation {
            return Err(PacketValidationError::new(
                PacketValidationErrorKind::StaleDeviceGeneration,
                "packet device generation is stale",
            ));
        }

        let stats = validate_frame(&frame)?;
        let resources = ResourceTable::for_frame(&frame);
        let draws = build_draws(&frame, stats.segment_count)?;
        let packet = RenderPacket {
            semantic: SemanticFrame::from_frame(frame),
            frame_revision: stats.scene_revision,
            scene_revision: self.expected_scene_revision,
            work_generation,
            device_generation,
            resources,
            draws,
        };
        packet.validate_for_owner(
            self.expected_scene_revision,
            self.expected_work_generation,
            self.expected_device_generation,
        )?;
        Ok(packet)
    }
}

/// Immutable, complete, process-local renderer input.
pub struct RenderPacket {
    semantic: SemanticFrame,
    frame_revision: PacketRevision,
    scene_revision: SceneRevision,
    work_generation: WorkGeneration,
    device_generation: DeviceGeneration,
    resources: ResourceTable,
    draws: Vec<DrawCommand>,
}

impl RenderPacket {
    /// Revalidates an already-built packet against work and device state.
    pub fn validate(
        &self,
        expected_work_generation: WorkGeneration,
        expected_device_generation: DeviceGeneration,
    ) -> Result<(), PacketValidationError> {
        self.validate_with_scene(None, expected_work_generation, expected_device_generation)
    }

    /// Revalidates an already-built packet against the full owner state.
    pub fn validate_for_owner(
        &self,
        expected_scene_revision: SceneRevision,
        expected_work_generation: WorkGeneration,
        expected_device_generation: DeviceGeneration,
    ) -> Result<(), PacketValidationError> {
        self.validate_with_scene(
            Some(expected_scene_revision),
            expected_work_generation,
            expected_device_generation,
        )
    }

    fn validate_with_scene(
        &self,
        expected_scene_revision: Option<SceneRevision>,
        expected_work_generation: WorkGeneration,
        expected_device_generation: DeviceGeneration,
    ) -> Result<(), PacketValidationError> {
        if expected_scene_revision.is_some_and(|expected| self.scene_revision != expected) {
            return Err(PacketValidationError::new(
                PacketValidationErrorKind::StaleSceneRevision,
                "packet scene revision is stale",
            ));
        }
        if self.work_generation != expected_work_generation {
            return Err(PacketValidationError::new(
                PacketValidationErrorKind::StaleWorkGeneration,
                "packet work generation is stale",
            ));
        }
        if self.device_generation != expected_device_generation {
            return Err(PacketValidationError::new(
                PacketValidationErrorKind::StaleDeviceGeneration,
                "packet device generation is stale",
            ));
        }

        let frame = self.semantic.frame();
        let stats = validate_frame(frame)?;
        if self.frame_revision != stats.scene_revision {
            return Err(PacketValidationError::new(
                PacketValidationErrorKind::IncompletePacket,
                "packet scene revision does not match its frame",
            ));
        }
        self.resources.validate(frame)?;
        validate_draws(frame, &self.resources, &self.draws, stats.segment_count)
    }

    /// Shared semantic/layout source projected by this packet.
    pub fn semantic_frame(&self) -> &SemanticFrame {
        &self.semantic
    }

    /// M1 frame view retained for existing consumers.
    pub fn frame(&self) -> &FramePacket {
        self.semantic.frame()
    }

    pub fn scene_revision(&self) -> SceneRevision {
        self.scene_revision
    }

    pub fn work_generation(&self) -> WorkGeneration {
        self.work_generation
    }

    pub fn device_generation(&self) -> DeviceGeneration {
        self.device_generation
    }

    /// Logical resource identities validated as part of this packet.
    pub fn resource_ids(&self) -> impl Iterator<Item = LogicalResourceId> + '_ {
        self.resources.ids()
    }

    /// Number of logical resources validated as part of this packet.
    pub fn resource_count(&self) -> usize {
        self.resources.len()
    }

    #[cfg(test)]
    fn frame_revision(&self) -> PacketRevision {
        self.frame_revision
    }

    #[cfg(test)]
    fn draw_count(&self) -> usize {
        self.draws.len()
    }
}

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct LogicalResourceId {
    slot: u32,
    generation: u32,
}

impl LogicalResourceId {
    const fn from_parts(slot: u32, generation: u32) -> Self {
        Self { slot, generation }
    }

    const fn is_valid(self) -> bool {
        self.slot != 0 && self.generation != 0
    }
}

struct ResourceTable {
    clips: Vec<ClipResource>,
    styles: Vec<StyleResource>,
}

impl ResourceTable {
    fn for_frame(frame: &FramePacket) -> Self {
        Self {
            clips: vec![ClipResource {
                id: LogicalResourceId::from_parts(CLIP_RESOURCE_SLOT, RESOURCE_GENERATION),
                bounds: frame.layout.plot_rect,
            }],
            styles: vec![StyleResource {
                id: LogicalResourceId::from_parts(STYLE_RESOURCE_SLOT, RESOURCE_GENERATION),
                color: frame.line_color,
                width: frame.line_width_px,
            }],
        }
    }

    fn validate(&self, frame: &FramePacket) -> Result<(), PacketValidationError> {
        let resource_count = self
            .clips
            .len()
            .checked_add(self.styles.len())
            .ok_or_else(|| {
                PacketValidationError::new(
                    PacketValidationErrorKind::CapacityExceeded,
                    "packet resource count exceeds a supported capacity",
                )
            })?;
        if resource_count > MAX_PACKET_RESOURCES {
            return Err(PacketValidationError::new(
                PacketValidationErrorKind::CapacityExceeded,
                "packet resource count exceeds a supported capacity",
            ));
        }

        let mut identifiers = HashSet::with_capacity(resource_count);
        for clip in &self.clips {
            if !clip.id.is_valid() {
                return Err(PacketValidationError::new(
                    PacketValidationErrorKind::InvalidResourceId,
                    "packet clip resource identifier is invalid",
                ));
            }
            if !identifiers.insert(clip.id) {
                return Err(PacketValidationError::new(
                    PacketValidationErrorKind::InvalidResourceId,
                    "packet resource identifiers are not unique",
                ));
            }
            if !valid_rect(
                clip.bounds,
                frame.layout.canvas.width(),
                frame.layout.canvas.height(),
            ) {
                return Err(PacketValidationError::new(
                    PacketValidationErrorKind::InvalidResourceReference,
                    "packet clip resource bounds are invalid",
                ));
            }
        }
        for style in &self.styles {
            if !style.id.is_valid() {
                return Err(PacketValidationError::new(
                    PacketValidationErrorKind::InvalidResourceId,
                    "packet style resource identifier is invalid",
                ));
            }
            if !identifiers.insert(style.id) {
                return Err(PacketValidationError::new(
                    PacketValidationErrorKind::InvalidResourceId,
                    "packet resource identifiers are not unique",
                ));
            }
            if !style.width.is_finite() || style.width <= 0.0 || style.width > MAX_PACKET_LINE_WIDTH
            {
                return Err(PacketValidationError::new(
                    PacketValidationErrorKind::InvalidResourceReference,
                    "packet style resource is invalid",
                ));
            }
        }

        let clip = self.clips.first().ok_or_else(|| {
            PacketValidationError::new(
                PacketValidationErrorKind::InvalidResourceReference,
                "packet has no clip resource",
            )
        })?;
        if clip.bounds != frame.layout.plot_rect {
            return Err(PacketValidationError::new(
                PacketValidationErrorKind::InvalidResourceReference,
                "packet clip reference does not match its frame",
            ));
        }
        let style = self.styles.first().ok_or_else(|| {
            PacketValidationError::new(
                PacketValidationErrorKind::InvalidResourceReference,
                "packet has no style resource",
            )
        })?;
        if style.color != frame.line_color || style.width != frame.line_width_px {
            return Err(PacketValidationError::new(
                PacketValidationErrorKind::InvalidResourceReference,
                "packet style reference does not match its frame",
            ));
        }
        Ok(())
    }

    fn ids(&self) -> impl Iterator<Item = LogicalResourceId> + '_ {
        self.clips
            .iter()
            .map(|clip| clip.id)
            .chain(self.styles.iter().map(|style| style.id))
    }

    fn len(&self) -> usize {
        self.clips.len().saturating_add(self.styles.len())
    }

    fn has_clip(&self, id: LogicalResourceId) -> bool {
        self.clips.iter().any(|clip| clip.id == id)
    }

    fn has_style(&self, id: LogicalResourceId) -> bool {
        self.styles.iter().any(|style| style.id == id)
    }
}

struct ClipResource {
    id: LogicalResourceId,
    bounds: LogicalRect,
}

struct StyleResource {
    id: LogicalResourceId,
    color: SrgbRgba8,
    width: f64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct DrawCommand {
    series_index: usize,
    segment_index: usize,
    range: Range<usize>,
    clip: LogicalResourceId,
    style: LogicalResourceId,
}

fn build_draws(
    frame: &FramePacket,
    segment_count: usize,
) -> Result<Vec<DrawCommand>, PacketValidationError> {
    if segment_count > MAX_PACKET_DRAWS {
        return Err(PacketValidationError::new(
            PacketValidationErrorKind::CapacityExceeded,
            "packet draw count exceeds a supported capacity",
        ));
    }
    let mut draws = Vec::new();
    draws.try_reserve(segment_count).map_err(|_| {
        PacketValidationError::new(
            PacketValidationErrorKind::AllocationFailed,
            "packet draw allocation failed",
        )
    })?;
    let clip = LogicalResourceId::from_parts(CLIP_RESOURCE_SLOT, RESOURCE_GENERATION);
    let style = LogicalResourceId::from_parts(STYLE_RESOURCE_SLOT, RESOURCE_GENERATION);
    for (series_index, series) in frame.series.iter().enumerate() {
        for (segment_index, segment) in series.segments.iter().enumerate() {
            draws.push(DrawCommand {
                series_index,
                segment_index,
                range: 0..segment.points.len(),
                clip,
                style,
            });
        }
    }
    Ok(draws)
}

#[derive(Clone, Copy)]
struct FrameStats {
    scene_revision: PacketRevision,
    segment_count: usize,
}

fn validate_frame(frame: &FramePacket) -> Result<FrameStats, PacketValidationError> {
    let [width_px, height_px] = frame.canvas_px;
    if width_px == 0
        || height_px == 0
        || width_px > MAX_FRAME_DIMENSION
        || height_px > MAX_FRAME_DIMENSION
    {
        return Err(PacketValidationError::new(
            PacketValidationErrorKind::FrameInvalid,
            "packet canvas geometry is invalid",
        ));
    }
    let pixel_count = usize::try_from(width_px)
        .ok()
        .and_then(|width| {
            usize::try_from(height_px)
                .ok()
                .and_then(|height| width.checked_mul(height))
        })
        .ok_or_else(|| {
            PacketValidationError::new(
                PacketValidationErrorKind::CapacityExceeded,
                "packet canvas exceeds a supported pixel count",
            )
        })?;
    if pixel_count > MAX_FRAME_PIXELS {
        return Err(PacketValidationError::new(
            PacketValidationErrorKind::CapacityExceeded,
            "packet canvas exceeds a supported pixel count",
        ));
    }

    let canvas_width = frame.layout.canvas.width();
    let canvas_height = frame.layout.canvas.height();
    if !canvas_width.is_finite()
        || !canvas_height.is_finite()
        || canvas_width <= 0.0
        || canvas_height <= 0.0
        || canvas_width != f64::from(width_px)
        || canvas_height != f64::from(height_px)
    {
        return Err(PacketValidationError::new(
            PacketValidationErrorKind::FrameInvalid,
            "packet canvas geometry is invalid",
        ));
    }
    if !valid_rect(frame.layout.plot_rect, canvas_width, canvas_height) {
        return Err(PacketValidationError::new(
            PacketValidationErrorKind::FrameInvalid,
            "packet plot geometry is invalid",
        ));
    }
    if !frame.dots_per_inch.is_finite()
        || frame.dots_per_inch <= 0.0
        || !frame.layout.logical_units_per_inch.is_finite()
        || frame.layout.logical_units_per_inch <= 0.0
        || !frame.line_width_px.is_finite()
        || frame.line_width_px <= 0.0
        || frame.line_width_px > MAX_PACKET_LINE_WIDTH
    {
        return Err(PacketValidationError::new(
            PacketValidationErrorKind::FrameInvalid,
            "packet frame metadata is invalid",
        ));
    }

    if !frame
        .plot_layout
        .validate_for_generation(frame.font_revision, frame.layout_revision)
    {
        return Err(PacketValidationError::new(
            PacketValidationErrorKind::FrameInvalid,
            "packet retained text layout is invalid",
        ));
    }

    if let Some(three_d) = frame.three_d()
        && !three_d.validate_for_canvas(canvas_width, canvas_height)
    {
        return Err(PacketValidationError::new(
            PacketValidationErrorKind::FrameInvalid,
            "packet 3D semantic geometry is invalid",
        ));
    }

    if frame.series.len() > MAX_FRAME_SERIES {
        return Err(PacketValidationError::new(
            PacketValidationErrorKind::CapacityExceeded,
            "packet series count exceeds a supported capacity",
        ));
    }
    let mut point_count = 0usize;
    let mut segment_count = 0usize;
    for series in &frame.series {
        segment_count = segment_count
            .checked_add(series.segments.len())
            .ok_or_else(|| {
                PacketValidationError::new(
                    PacketValidationErrorKind::CapacityExceeded,
                    "packet segment count exceeds a supported capacity",
                )
            })?;
        if segment_count > MAX_PACKET_SEGMENTS {
            return Err(PacketValidationError::new(
                PacketValidationErrorKind::CapacityExceeded,
                "packet segment count exceeds a supported capacity",
            ));
        }
        for segment in &series.segments {
            if segment.points.is_empty() {
                return Err(PacketValidationError::new(
                    PacketValidationErrorKind::InvalidDrawRange,
                    "packet segment has no drawable points",
                ));
            }
            point_count = point_count
                .checked_add(segment.points.len())
                .ok_or_else(|| {
                    PacketValidationError::new(
                        PacketValidationErrorKind::CapacityExceeded,
                        "packet point count exceeds a supported capacity",
                    )
                })?;
            if point_count > MAX_PACKET_POINTS {
                return Err(PacketValidationError::new(
                    PacketValidationErrorKind::CapacityExceeded,
                    "packet point count exceeds a supported capacity",
                ));
            }
            for point in &segment.points {
                if !point.x.is_finite()
                    || !point.y.is_finite()
                    || point.x < 0.0
                    || point.y < 0.0
                    || point.x > canvas_width
                    || point.y > canvas_height
                {
                    return Err(PacketValidationError::new(
                        PacketValidationErrorKind::FrameInvalid,
                        "packet point geometry is invalid",
                    ));
                }
            }
        }
    }

    Ok(FrameStats {
        scene_revision: frame.revision,
        segment_count,
    })
}

fn valid_rect(rect: LogicalRect, canvas_width: f64, canvas_height: f64) -> bool {
    let x_min = rect.x_min();
    let y_min = rect.y_min();
    let x_max = rect.x_max();
    let y_max = rect.y_max();
    x_min.is_finite()
        && y_min.is_finite()
        && x_max.is_finite()
        && y_max.is_finite()
        && x_min >= 0.0
        && y_min >= 0.0
        && x_min < x_max
        && y_min < y_max
        && x_max <= canvas_width
        && y_max <= canvas_height
        && (x_max - x_min).is_finite()
        && (y_max - y_min).is_finite()
}

fn validate_draws(
    frame: &FramePacket,
    resources: &ResourceTable,
    draws: &[DrawCommand],
    expected_count: usize,
) -> Result<(), PacketValidationError> {
    if draws.len() != expected_count {
        return Err(PacketValidationError::new(
            PacketValidationErrorKind::IncompletePacket,
            "packet draw list is incomplete",
        ));
    }

    let mut previous = None;
    for draw in draws {
        let Some(series) = frame.series.get(draw.series_index) else {
            return Err(PacketValidationError::new(
                PacketValidationErrorKind::InvalidDrawOrder,
                "packet draw series order is invalid",
            ));
        };
        let Some(segment) = series.segments.get(draw.segment_index) else {
            return Err(PacketValidationError::new(
                PacketValidationErrorKind::InvalidDrawOrder,
                "packet draw segment order is invalid",
            ));
        };
        let current = (draw.series_index, draw.segment_index);
        if previous.is_some_and(|prior| prior >= current) {
            return Err(PacketValidationError::new(
                PacketValidationErrorKind::InvalidDrawOrder,
                "packet draw order is invalid",
            ));
        }
        previous = Some(current);
        if draw.range.start >= draw.range.end || draw.range.end > segment.points.len() {
            return Err(PacketValidationError::new(
                PacketValidationErrorKind::InvalidDrawRange,
                "packet draw range is invalid",
            ));
        }
        if !resources.has_clip(draw.clip) || !resources.has_style(draw.style) {
            return Err(PacketValidationError::new(
                PacketValidationErrorKind::InvalidResourceReference,
                "packet draw resource reference is invalid",
            ));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::frame::{FrameSpec, PacketPoint, PacketSegment};
    use lumenplot_engine::bridge::{PlotLayout, Viewport};

    const WORK: WorkGeneration = WorkGeneration::new(7);
    const DEVICE_GENERATION: DeviceGeneration = DeviceGeneration::new(11);

    fn fixture_spec() -> FrameSpec {
        FrameSpec::new(
            [800, 600],
            [40, 30, 760, 550],
            100.0,
            SrgbRgba8::new(31, 119, 180, 255),
            2.0,
            SrgbRgba8::new(255, 255, 255, 255),
        )
        .expect("spec")
    }

    fn fixture_frame(point_count: usize) -> FramePacket {
        let mut handle = crate::frame::SceneHandle::new(
            Viewport::from_bounds(0.0, 1.0, 0.0, 1.0).expect("view"),
        )
        .expect("handle");
        let mut xs = Vec::with_capacity(point_count);
        let mut ys = Vec::with_capacity(point_count);
        for index in 0..point_count {
            let fraction = if point_count <= 1 {
                0.0
            } else {
                index as f64 / (point_count - 1) as f64
            };
            xs.push(fraction);
            ys.push(0.25 + 0.5 * fraction);
        }
        handle.add_series(xs, ys).expect("series");
        handle.resolve_frame(&fixture_spec()).expect("frame")
    }

    fn packet(point_count: usize) -> RenderPacket {
        let builder = RenderPacketBuilder::new(WORK, DEVICE_GENERATION);
        builder
            .build(fixture_frame(point_count), WORK, DEVICE_GENERATION)
            .expect("packet")
    }

    #[test]
    fn semantic_3d_facts_cross_the_owner_packet_boundary_without_new_identity() {
        use crate::frame::{
            Bounds3D, Line3DGeometry, Point3D, Projection3D, Semantic3D, Triangle3DGeometry,
            ViewFacts3D,
        };

        let source_line = vec![Point3D::new(0.0, 0.0, 0.0), Point3D::new(1.0, 1.0, 1.0)];
        let projected_line = vec![
            PacketPoint::new(100.0, 100.0),
            PacketPoint::new(200.0, 200.0),
        ];
        let line = Line3DGeometry::new(
            source_line,
            projected_line,
            std::iter::once(0..2).collect(),
            SrgbRgba8::new(220, 30, 40, 255),
            1.5,
        )
        .expect("line");
        let triangle = Triangle3DGeometry::new(
            [
                Point3D::new(0.0, 0.0, 0.0),
                Point3D::new(1.0, 0.0, 0.0),
                Point3D::new(0.0, 1.0, 1.0),
            ],
            [
                PacketPoint::new(120.0, 120.0),
                PacketPoint::new(220.0, 120.0),
                PacketPoint::new(120.0, 220.0),
            ],
            SrgbRgba8::new(30, 120, 220, 255),
            Some(SrgbRgba8::new(0, 0, 0, 0)),
            1.0,
            0,
            0.25,
        )
        .expect("triangle");
        let semantic = Semantic3D::new(
            ViewFacts3D::new(Projection3D::Perspective, 30.0, -60.0, 0.0, Some(1.0)).expect("view"),
            Bounds3D::new([0.0, 1.0], [0.0, 1.0], [0.0, 1.0]).expect("bounds"),
            Point3D::new(0.5, 0.5, 0.5),
            vec![line],
            vec![triangle],
            vec![0],
            0.0,
        )
        .expect("semantic 3D");
        let frame = fixture_frame(8).with_three_d(semantic);
        let packet = RenderPacketBuilder::new(WORK, DEVICE_GENERATION)
            .build(frame, WORK, DEVICE_GENERATION)
            .expect("packet");
        let three_d = packet.semantic_frame().three_d().expect("3D facts");
        assert_eq!(three_d.view().projection(), Projection3D::Perspective);
        assert_eq!(three_d.bounds().z(), [0.0, 1.0]);
        assert_eq!(three_d.origin().z(), 0.5);
        assert_eq!(packet.scene_revision(), SceneRevision::initial());
        assert_eq!(packet.work_generation().value(), WORK.value());
        assert_eq!(
            packet.device_generation().value(),
            DEVICE_GENERATION.value()
        );
    }

    #[test]
    fn generations_and_scene_revision_remain_distinct_metadata() {
        let packet = packet(8);
        assert_eq!(packet.scene_revision(), SceneRevision::initial());
        assert_eq!(packet.frame_revision(), packet.frame().revision());
        assert_eq!(packet.work_generation().value(), WORK.value());
        assert_eq!(
            packet.device_generation().value(),
            DEVICE_GENERATION.value()
        );
        assert_eq!(WORK.value(), DEVICE_GENERATION.value() - 4);
    }

    #[test]
    fn generated_finite_frames_always_publish_complete_draws() {
        for point_count in [1, 2, 3, 8, 31, 127] {
            let packet = packet(point_count);
            assert_eq!(packet.draw_count(), 1);
            packet
                .validate(WORK, DEVICE_GENERATION)
                .expect("valid packet");
        }

        // A small deterministic property sweep exercises varied finite
        // geometry without introducing a dependency for random generation.
        for seed in 1..=32u64 {
            let mut generated = packet(32);
            let mut state = seed;
            for point in &mut generated.semantic.frame_mut().series[0].segments[0].points {
                state = state
                    .wrapping_mul(6_364_136_223_846_793_005)
                    .wrapping_add(1);
                point.y = 30.0 + (state as f64 / u64::MAX as f64) * 520.0;
            }
            generated
                .validate(WORK, DEVICE_GENERATION)
                .expect("property frame");
        }
    }

    #[test]
    fn invalid_frame_geometry_is_rejected_before_packet_creation() {
        let mut frame = fixture_frame(4);
        frame.series[0].segments[0].points[1] = PacketPoint::new(f64::NAN, 20.0);
        let builder = RenderPacketBuilder::new(WORK, DEVICE_GENERATION);
        let error = builder
            .build(frame, WORK, DEVICE_GENERATION)
            .err()
            .expect("non-finite geometry must fail");
        assert_eq!(error.kind(), PacketValidationErrorKind::FrameInvalid);

        let mut metadata = fixture_frame(4);
        metadata.line_width_px = f64::INFINITY;
        let error = builder
            .build(metadata, WORK, DEVICE_GENERATION)
            .err()
            .expect("non-finite style must fail");
        assert_eq!(error.kind(), PacketValidationErrorKind::FrameInvalid);
    }

    #[test]
    fn invalid_ranges_order_and_references_are_rejected() {
        let mut range_packet = packet(4);
        range_packet.draws[0].range = 2..2;
        let error = range_packet
            .validate(WORK, DEVICE_GENERATION)
            .expect_err("empty range must fail");
        assert_eq!(error.kind(), PacketValidationErrorKind::InvalidDrawRange);

        let mut order_frame = fixture_frame(4);
        let duplicate_points = order_frame.series[0].segments[0].points.clone();
        order_frame.series[0].segments.push(PacketSegment {
            points: duplicate_points,
        });
        let builder = RenderPacketBuilder::new(WORK, DEVICE_GENERATION);
        let mut order_packet = builder
            .build(order_frame, WORK, DEVICE_GENERATION)
            .expect("two-segment packet");
        order_packet.draws.swap(0, 1);
        let error = order_packet
            .validate(WORK, DEVICE_GENERATION)
            .expect_err("reversed order must fail");
        assert_eq!(error.kind(), PacketValidationErrorKind::InvalidDrawOrder);

        let mut resource_packet = packet(4);
        resource_packet.draws[0].clip = LogicalResourceId::from_parts(0, RESOURCE_GENERATION);
        let error = resource_packet
            .validate(WORK, DEVICE_GENERATION)
            .expect_err("invalid resource reference must fail");
        assert_eq!(
            error.kind(),
            PacketValidationErrorKind::InvalidResourceReference
        );

        let mut invalid_id_packet = packet(4);
        invalid_id_packet.resources.clips[0].id =
            LogicalResourceId::from_parts(0, RESOURCE_GENERATION);
        let error = invalid_id_packet
            .validate(WORK, DEVICE_GENERATION)
            .expect_err("invalid resource identifier must fail");
        assert_eq!(error.kind(), PacketValidationErrorKind::InvalidResourceId);

        let mut style_packet = packet(4);
        style_packet.resources.styles[0].width = f64::NAN;
        let error = style_packet
            .validate(WORK, DEVICE_GENERATION)
            .expect_err("invalid style resource must fail");
        assert_eq!(
            error.kind(),
            PacketValidationErrorKind::InvalidResourceReference
        );
    }

    #[test]
    fn stale_generations_are_rejected_without_publication() {
        let builder = RenderPacketBuilder::new(WORK, DEVICE_GENERATION);
        let frame = fixture_frame(4);

        let error = builder
            .build(frame.clone(), WorkGeneration::new(6), DEVICE_GENERATION)
            .err()
            .expect("stale work must fail");
        assert_eq!(error.kind(), PacketValidationErrorKind::StaleWorkGeneration);

        let error = builder
            .build(frame, WORK, DeviceGeneration::new(10))
            .err()
            .expect("stale device must fail");
        assert_eq!(
            error.kind(),
            PacketValidationErrorKind::StaleDeviceGeneration
        );
    }

    #[test]
    fn stale_retained_layout_generation_is_rejected_before_publication() {
        let builder = RenderPacketBuilder::new(WORK, DEVICE_GENERATION);
        let mut stale_layout = fixture_frame(4);
        stale_layout.layout_revision = stale_layout.layout_revision.saturating_add(1);
        let error = builder
            .build(stale_layout, WORK, DEVICE_GENERATION)
            .err()
            .expect("stale layout generation must fail");
        assert_eq!(error.kind(), PacketValidationErrorKind::FrameInvalid);

        let mut stale_font = fixture_frame(4);
        stale_font.font_revision = stale_font.font_revision.saturating_add(1);
        let error = builder
            .build(stale_font, WORK, DEVICE_GENERATION)
            .err()
            .expect("stale font generation must fail");
        assert_eq!(error.kind(), PacketValidationErrorKind::FrameInvalid);
    }

    #[test]
    fn owner_scene_revision_is_revalidated_without_partial_publication() {
        let scene = SceneRevision::new(41);
        let builder = RenderPacketBuilder::for_scene(scene, WORK, DEVICE_GENERATION);
        let packet = builder
            .build(fixture_frame(4), WORK, DEVICE_GENERATION)
            .expect("owner-bound packet");
        packet
            .validate_for_owner(scene, WORK, DEVICE_GENERATION)
            .expect("current owner point");
        let error = packet
            .validate_for_owner(SceneRevision::new(42), WORK, DEVICE_GENERATION)
            .expect_err("newer scene must reject the old packet");
        assert_eq!(error.kind(), PacketValidationErrorKind::StaleSceneRevision);
    }

    #[test]
    fn independent_consumers_read_one_validated_semantic_frame() {
        let builder =
            RenderPacketBuilder::for_scene(SceneRevision::initial(), WORK, DEVICE_GENERATION);
        let packet = builder
            .build(fixture_frame(8), WORK, DEVICE_GENERATION)
            .expect("packet");
        let mut recording = RecordingRenderer::new(WORK, DEVICE_GENERATION);
        recording
            .submit(fixture_frame(8), WORK, DEVICE_GENERATION)
            .expect("recording consumer");
        let mut digest = SemanticDigestRenderer::new();
        digest
            .consume(&packet, SceneRevision::initial(), WORK, DEVICE_GENERATION)
            .expect("independent semantic consumer");
        let screen_layout = screen_layout_consumer(&packet);
        let export_layout = export_layout_consumer(&packet);
        assert!(std::ptr::eq(screen_layout, export_layout));
        assert_eq!(digest.frame_count, 1);
        assert_ne!(digest.digest, 0);
        let recorded_layout = recording.published()[0].semantic_frame().plot_layout();
        assert_eq!(recorded_layout.layout_digest(), digest.layout_digest);
        assert_eq!(recorded_layout.runs().len(), digest.layout_run_count);
        assert_eq!(recorded_layout.runs()[0].source(), "0.0");
        assert_eq!(recorded_layout.runs()[1].source(), "2026-01-01");
        assert_eq!(recorded_layout.runs()[2].source(), "mm");
        assert_eq!(recorded_layout.runs()[3].source(), "x");
        assert_eq!(recorded_layout.runs()[4].source(), "measurement");
        assert_eq!(recorded_layout.runs()[5].source(), "series-0");
        assert_eq!(recording.published()[0].frame().series().len(), 1);
    }
    #[test]
    fn frame_validation_rejects_mismatched_canvas_and_capacity() {
        let mut mismatched = fixture_frame(3);
        mismatched.canvas_px = [801, 600];
        let builder = RenderPacketBuilder::new(WORK, DEVICE_GENERATION);
        let error = builder
            .build(mismatched, WORK, DEVICE_GENERATION)
            .err()
            .expect("canvas metadata mismatch must fail");
        assert_eq!(error.kind(), PacketValidationErrorKind::FrameInvalid);

        let too_large = FrameSpec::new(
            [16_384, 16_384],
            [0, 0, 16_384, 16_384],
            100.0,
            SrgbRgba8::new(0, 0, 0, 255),
            1.0,
            SrgbRgba8::new(255, 255, 255, 255),
        );
        assert!(
            too_large.is_err(),
            "pixel bound must fail before allocation"
        );
    }

    #[test]
    fn renderer_double_publishes_only_complete_packets() {
        let mut renderer = RecordingRenderer::new(WORK, DEVICE_GENERATION);
        renderer
            .submit(fixture_frame(4), WORK, DEVICE_GENERATION)
            .expect("current packet");
        assert_eq!(renderer.published().len(), 1);

        let stale = renderer.submit(fixture_frame(4), WorkGeneration::new(6), DEVICE_GENERATION);
        assert_eq!(
            stale.expect_err("stale work").kind(),
            PacketValidationErrorKind::StaleWorkGeneration
        );
        assert_eq!(renderer.published().len(), 1);

        let invalid = {
            let mut frame = fixture_frame(4);
            frame.series[0].segments[0].points[0] = PacketPoint::new(-1.0, 0.0);
            renderer.submit(frame, WORK, DEVICE_GENERATION)
        };
        assert_eq!(
            invalid.expect_err("invalid frame").kind(),
            PacketValidationErrorKind::FrameInvalid
        );
        assert_eq!(renderer.published().len(), 1);
    }

    #[test]
    fn finite_multi_series_frames_publish_complete_draw_lists() {
        let mut handle = crate::frame::SceneHandle::new(
            Viewport::from_bounds(0.0, 1.0, 0.0, 1.0).expect("view"),
        )
        .expect("handle");
        for (offset, point_count) in [(0.0, 2usize), (0.2, 5), (0.1, 9)] {
            let mut xs = Vec::with_capacity(point_count);
            let mut ys = Vec::with_capacity(point_count);
            for index in 0..point_count {
                let fraction = index as f64 / (point_count - 1) as f64;
                xs.push(fraction);
                ys.push(offset + 0.5 * fraction);
            }
            handle.add_series(xs, ys).expect("series");
        }
        let frame = handle.resolve_frame(&fixture_spec()).expect("frame");
        assert_eq!(frame.series.len(), 3);
        let expected_draws: usize = frame
            .series
            .iter()
            .map(|series| series.segments.len())
            .sum();
        assert_eq!(expected_draws, 3);
        let packet = RenderPacketBuilder::new(WORK, DEVICE_GENERATION)
            .build(frame, WORK, DEVICE_GENERATION)
            .expect("packet");
        assert_eq!(packet.draw_count(), expected_draws);
        assert_eq!(packet.resource_count(), 2);
        packet
            .validate(WORK, DEVICE_GENERATION)
            .expect("valid packet");
        for draw in &packet.draws {
            let segment = &packet.frame().series[draw.series_index].segments[draw.segment_index];
            assert_eq!(draw.range, 0..segment.points.len());
        }
    }

    #[test]
    fn packet_resource_capacity_and_line_width_boundaries_are_explicit() {
        let base = packet(4);
        assert_eq!(base.resource_count(), 2);
        assert!(base.resource_count() <= MAX_PACKET_RESOURCES);

        // Draw-count capacity is enforced before any allocation.
        let frame = fixture_frame(4);
        let error = build_draws(&frame, MAX_PACKET_DRAWS + 1).expect_err("draw overflow must fail");
        assert_eq!(error.kind(), PacketValidationErrorKind::CapacityExceeded);

        // Resource-count capacity: three extra valid resources push the
        // table from 2 to 5, past the bound of 4.
        let mut crowded = packet(4);
        let bounds = crowded.frame().layout.plot_rect;
        for slot in [3u32, 4, 5] {
            crowded.resources.clips.push(ClipResource {
                id: LogicalResourceId::from_parts(slot, RESOURCE_GENERATION),
                bounds,
            });
        }
        assert_eq!(crowded.resource_count(), 5);
        let error = crowded
            .validate(WORK, DEVICE_GENERATION)
            .expect_err("resource overflow must fail");
        assert_eq!(error.kind(), PacketValidationErrorKind::CapacityExceeded);

        // Style width is inclusive at the bound and rejected just above it.
        // The packet cross-checks the style against its frame, so the bound
        // case moves both together.
        let mut at_bound = packet(4);
        at_bound.semantic.frame_mut().line_width_px = MAX_PACKET_LINE_WIDTH;
        at_bound.resources.styles[0].width = MAX_PACKET_LINE_WIDTH;
        at_bound
            .validate(WORK, DEVICE_GENERATION)
            .expect("inclusive bound");
        for width in [MAX_PACKET_LINE_WIDTH + 1.0, 0.0, -1.0, f64::NAN] {
            let mut invalid = packet(4);
            invalid.resources.styles[0].width = width;
            let error = invalid
                .validate(WORK, DEVICE_GENERATION)
                .expect_err("bad style width must fail");
            assert_eq!(
                error.kind(),
                PacketValidationErrorKind::InvalidResourceReference
            );
        }

        // The same overflow at the frame seam is a frame rejection before
        // packet construction.
        let mut wide_frame = fixture_frame(4);
        wide_frame.line_width_px = MAX_PACKET_LINE_WIDTH + 1.0;
        let error = RenderPacketBuilder::new(WORK, DEVICE_GENERATION)
            .build(wide_frame, WORK, DEVICE_GENERATION)
            .err()
            .expect("wide frame must fail");
        assert_eq!(error.kind(), PacketValidationErrorKind::FrameInvalid);
    }

    #[test]
    fn malformed_logical_ids_ranges_and_order_are_rejected() {
        // Slot-zero, generation-zero, and duplicated identifiers.
        for id in [
            LogicalResourceId::from_parts(0, RESOURCE_GENERATION),
            LogicalResourceId::from_parts(CLIP_RESOURCE_SLOT, 0),
            LogicalResourceId::from_parts(0, 0),
        ] {
            let mut malformed = packet(4);
            malformed.resources.clips[0].id = id;
            let error = malformed
                .validate(WORK, DEVICE_GENERATION)
                .expect_err("bad clip id must fail");
            assert_eq!(error.kind(), PacketValidationErrorKind::InvalidResourceId);
        }
        let mut bad_style = packet(4);
        bad_style.resources.styles[0].id = LogicalResourceId::from_parts(STYLE_RESOURCE_SLOT, 0);
        assert_eq!(
            bad_style
                .validate(WORK, DEVICE_GENERATION)
                .expect_err("bad style id")
                .kind(),
            PacketValidationErrorKind::InvalidResourceId
        );
        let mut duplicate = packet(4);
        duplicate.resources.styles[0].id = duplicate.resources.clips[0].id;
        assert_eq!(
            duplicate
                .validate(WORK, DEVICE_GENERATION)
                .expect_err("duplicate id")
                .kind(),
            PacketValidationErrorKind::InvalidResourceId
        );

        // Draw references to unknown generations never resolve.
        for clip in [
            LogicalResourceId::from_parts(9, RESOURCE_GENERATION),
            LogicalResourceId::from_parts(CLIP_RESOURCE_SLOT, 0),
        ] {
            let mut dangling = packet(4);
            dangling.draws[0].clip = clip;
            assert_eq!(
                dangling
                    .validate(WORK, DEVICE_GENERATION)
                    .expect_err("dangling clip")
                    .kind(),
                PacketValidationErrorKind::InvalidResourceReference
            );
        }

        // Ranges: empty, inverted, zero-length, and over-long are invalid.
        // The inverted range is built from variables so the rejection under
        // test is constructed at runtime rather than as a literal.
        let point_len = packet(4).frame().series[0].segments[0].points.len();
        assert_eq!(point_len, 4);
        let inverted = {
            let start = 3usize;
            let end = 1usize;
            start..end
        };
        for range in [2..2, inverted, 0..0, 0..point_len + 1] {
            let mut bad_range = packet(4);
            bad_range.draws[0].range = range;
            assert_eq!(
                bad_range
                    .validate(WORK, DEVICE_GENERATION)
                    .expect_err("bad range")
                    .kind(),
                PacketValidationErrorKind::InvalidDrawRange
            );
        }
        let mut valid_range = packet(4);
        valid_range.draws[0].range = 0..point_len;
        valid_range
            .validate(WORK, DEVICE_GENERATION)
            .expect("full range");

        // Order: out-of-bounds indices and a duplicated first draw.
        let mut bad_series = packet(4);
        bad_series.draws[0].series_index = 99;
        assert_eq!(
            bad_series
                .validate(WORK, DEVICE_GENERATION)
                .expect_err("bad series")
                .kind(),
            PacketValidationErrorKind::InvalidDrawOrder
        );
        let mut bad_segment = packet(4);
        bad_segment.draws[0].segment_index = 99;
        assert_eq!(
            bad_segment
                .validate(WORK, DEVICE_GENERATION)
                .expect_err("bad segment")
                .kind(),
            PacketValidationErrorKind::InvalidDrawOrder
        );
        let mut two_frame = fixture_frame(4);
        let duplicate_points = two_frame.series[0].segments[0].points.clone();
        two_frame.series[0].segments.push(PacketSegment {
            points: duplicate_points,
        });
        let mut duplicated = RenderPacketBuilder::new(WORK, DEVICE_GENERATION)
            .build(two_frame, WORK, DEVICE_GENERATION)
            .expect("two-segment packet");
        duplicated.draws[1] = duplicated.draws[0].clone();
        assert_eq!(
            duplicated
                .validate(WORK, DEVICE_GENERATION)
                .expect_err("duplicate draw")
                .kind(),
            PacketValidationErrorKind::InvalidDrawOrder
        );
    }

    #[test]
    fn truncated_or_extended_draw_lists_are_incomplete() {
        let mut truncated = packet(4);
        truncated.draws.pop();
        assert_eq!(
            truncated
                .validate(WORK, DEVICE_GENERATION)
                .expect_err("truncated")
                .kind(),
            PacketValidationErrorKind::IncompletePacket
        );
        let mut extended = packet(4);
        let first = extended.draws[0].clone();
        extended.draws.push(first);
        assert_eq!(
            extended
                .validate(WORK, DEVICE_GENERATION)
                .expect_err("extended")
                .kind(),
            PacketValidationErrorKind::IncompletePacket
        );
    }

    #[test]
    fn failed_builds_publish_nothing_and_later_success_recovers() {
        let mut renderer = RecordingRenderer::new(WORK, DEVICE_GENERATION);
        renderer
            .submit(fixture_frame(4), WORK, DEVICE_GENERATION)
            .expect("first");
        assert_eq!(renderer.published().len(), 1);

        // Stale work, stale device, invalid geometry, and canvas mismatch
        // each fail with their own kind and publish nothing.
        assert_eq!(
            renderer
                .submit(fixture_frame(4), WorkGeneration::new(6), DEVICE_GENERATION)
                .expect_err("stale work")
                .kind(),
            PacketValidationErrorKind::StaleWorkGeneration
        );
        assert_eq!(
            renderer
                .submit(fixture_frame(4), WORK, DeviceGeneration::new(10))
                .expect_err("stale device")
                .kind(),
            PacketValidationErrorKind::StaleDeviceGeneration
        );
        let mut bad_point = fixture_frame(4);
        bad_point.series[0].segments[0].points[0] = PacketPoint::new(-1.0, 0.0);
        assert_eq!(
            renderer
                .submit(bad_point, WORK, DEVICE_GENERATION)
                .expect_err("bad point")
                .kind(),
            PacketValidationErrorKind::FrameInvalid
        );
        let mut bad_canvas = fixture_frame(4);
        bad_canvas.canvas_px = [801, 600];
        assert_eq!(
            renderer
                .submit(bad_canvas, WORK, DEVICE_GENERATION)
                .expect_err("bad canvas")
                .kind(),
            PacketValidationErrorKind::FrameInvalid
        );
        assert_eq!(renderer.published().len(), 1);

        // A later valid submission still publishes and validates.
        renderer
            .submit(fixture_frame(4), WORK, DEVICE_GENERATION)
            .expect("recovery");
        assert_eq!(renderer.published().len(), 2);
        renderer.published()[1]
            .validate(WORK, DEVICE_GENERATION)
            .expect("recovered packet");

        // Owner-scene staleness is likewise a whole-packet rejection.
        let scene = SceneRevision::new(41);
        let owner_builder = RenderPacketBuilder::for_scene(scene, WORK, DEVICE_GENERATION);
        let owner_packet = owner_builder
            .build(fixture_frame(4), WORK, DEVICE_GENERATION)
            .expect("owner packet");
        assert_eq!(
            owner_packet
                .validate_for_owner(SceneRevision::new(42), WORK, DEVICE_GENERATION)
                .expect_err("stale scene")
                .kind(),
            PacketValidationErrorKind::StaleSceneRevision
        );
    }

    #[test]
    fn generic_validate_ignores_scene_while_owner_validate_enforces_it() {
        let scene = SceneRevision::new(41);
        let packet = RenderPacketBuilder::for_scene(scene, WORK, DEVICE_GENERATION)
            .build(fixture_frame(4), WORK, DEVICE_GENERATION)
            .expect("packet");
        // Distinct owner tokens stay distinct values.
        assert_ne!(scene, SceneRevision::initial());
        packet
            .validate(WORK, DEVICE_GENERATION)
            .expect("scene-agnostic revalidation");
        packet
            .validate_for_owner(scene, WORK, DEVICE_GENERATION)
            .expect("current owner");
        assert_eq!(
            packet
                .validate_for_owner(SceneRevision::new(42), WORK, DEVICE_GENERATION)
                .expect_err("moved scene")
                .kind(),
            PacketValidationErrorKind::StaleSceneRevision
        );
    }

    fn screen_layout_consumer(packet: &RenderPacket) -> &PlotLayout {
        packet.semantic_frame().plot_layout()
    }

    fn export_layout_consumer(packet: &RenderPacket) -> &PlotLayout {
        packet.semantic_frame().plot_layout()
    }

    /// Backend-neutral test double that owns only complete internal packets.
    struct RecordingRenderer {
        builder: RenderPacketBuilder,
        published: Vec<RenderPacket>,
    }

    impl RecordingRenderer {
        fn new(work_generation: WorkGeneration, device_generation: DeviceGeneration) -> Self {
            Self {
                builder: RenderPacketBuilder::new(work_generation, device_generation),
                published: Vec::new(),
            }
        }

        fn submit(
            &mut self,
            frame: FramePacket,
            work_generation: WorkGeneration,
            device_generation: DeviceGeneration,
        ) -> Result<(), PacketValidationError> {
            let packet = self
                .builder
                .build(frame, work_generation, device_generation)?;
            self.published.push(packet);
            Ok(())
        }

        fn published(&self) -> &[RenderPacket] {
            &self.published
        }
    }

    /// Independent consumer that reads the same validated semantic meaning
    /// without sharing the recording renderer's storage or implementation.
    struct SemanticDigestRenderer {
        frame_count: usize,
        digest: u64,
        layout_digest: [u8; 32],
        layout_run_count: usize,
    }

    impl SemanticDigestRenderer {
        fn new() -> Self {
            Self {
                frame_count: 0,
                digest: 0,
                layout_digest: [0; 32],
                layout_run_count: 0,
            }
        }

        fn consume(
            &mut self,
            packet: &RenderPacket,
            scene_revision: SceneRevision,
            work_generation: WorkGeneration,
            device_generation: DeviceGeneration,
        ) -> Result<(), PacketValidationError> {
            packet.validate_for_owner(scene_revision, work_generation, device_generation)?;
            let layout = packet.semantic_frame().plot_layout();
            self.layout_digest = layout.layout_digest();
            self.layout_run_count = layout.runs().len();
            let mut digest = 0xcbf29ce484222325;
            for series in packet.semantic_frame().frame().series() {
                for segment in series.segments() {
                    for point in segment.points() {
                        digest ^= point.x().to_bits();
                        digest = digest.wrapping_mul(0x100000001b3);
                        digest ^= point.y().to_bits();
                        digest = digest.wrapping_mul(0x100000001b3);
                    }
                }
            }
            self.frame_count += 1;
            self.digest = digest;
            Ok(())
        }
    }
}
