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
    MAX_FRAME_SERIES, PacketRevision,
};

const MAX_PACKET_POINTS: usize = 1_000_000;
const MAX_PACKET_SEGMENTS: usize = 1_000_000;
const MAX_PACKET_DRAWS: usize = 1_000_000;
pub(crate) const MAX_PACKET_RESOURCES: usize = 4;
const MAX_PACKET_LINE_WIDTH: f64 = 16_384.0;
const RESOURCE_GENERATION: u32 = 1;
const CLIP_RESOURCE_SLOT: u32 = 1;
const STYLE_RESOURCE_SLOT: u32 = 2;

/// Scheduler generation associated with derived packet work.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub(crate) struct WorkGeneration(u64);

impl WorkGeneration {
    pub(crate) const fn initial() -> Self {
        Self::new(0)
    }

    pub(crate) const fn new(value: u64) -> Self {
        Self(value)
    }

    #[cfg(test)]
    fn value(self) -> u64 {
        self.0
    }
}

/// Renderer-instance generation associated with retained logical resources.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub(crate) struct DeviceGeneration(u64);

impl DeviceGeneration {
    pub(crate) const fn initial() -> Self {
        Self::new(0)
    }

    pub(crate) const fn new(value: u64) -> Self {
        Self(value)
    }

    #[cfg(test)]
    fn value(self) -> u64 {
        self.0
    }
}

/// Internal validation categories; these never become a public error schema.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) enum PacketValidationErrorKind {
    FrameInvalid,
    CapacityExceeded,
    InvalidResourceId,
    InvalidResourceReference,
    InvalidDrawRange,
    InvalidDrawOrder,
    IncompletePacket,
    AllocationFailed,
    StaleWorkGeneration,
    StaleDeviceGeneration,
}

/// Sanitized failure from packet construction or validation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct PacketValidationError {
    kind: PacketValidationErrorKind,
    message: &'static str,
}

impl PacketValidationError {
    fn new(kind: PacketValidationErrorKind, message: &'static str) -> Self {
        Self { kind, message }
    }

    #[cfg(test)]
    pub(crate) fn kind(self) -> PacketValidationErrorKind {
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
pub(crate) struct RenderPacketBuilder {
    expected_work_generation: WorkGeneration,
    expected_device_generation: DeviceGeneration,
}

impl RenderPacketBuilder {
    pub(crate) const fn new(
        expected_work_generation: WorkGeneration,
        expected_device_generation: DeviceGeneration,
    ) -> Self {
        Self {
            expected_work_generation,
            expected_device_generation,
        }
    }

    /// Builds one complete packet, publishing nothing until every check passes.
    pub(crate) fn build(
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
            frame,
            scene_revision: stats.scene_revision,
            work_generation,
            device_generation,
            resources,
            draws,
        };
        packet.validate(
            self.expected_work_generation,
            self.expected_device_generation,
        )?;
        Ok(packet)
    }
}

/// Immutable, complete, process-local renderer input.
pub(crate) struct RenderPacket {
    frame: FramePacket,
    scene_revision: PacketRevision,
    work_generation: WorkGeneration,
    device_generation: DeviceGeneration,
    resources: ResourceTable,
    draws: Vec<DrawCommand>,
}

impl RenderPacket {
    /// Revalidates an already-built packet against the current owner state.
    pub(crate) fn validate(
        &self,
        expected_work_generation: WorkGeneration,
        expected_device_generation: DeviceGeneration,
    ) -> Result<(), PacketValidationError> {
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

        let stats = validate_frame(&self.frame)?;
        if self.scene_revision != stats.scene_revision {
            return Err(PacketValidationError::new(
                PacketValidationErrorKind::IncompletePacket,
                "packet scene revision does not match its frame",
            ));
        }
        self.resources.validate(&self.frame)?;
        validate_draws(
            &self.frame,
            &self.resources,
            &self.draws,
            stats.segment_count,
        )
    }

    pub(crate) fn frame(&self) -> &FramePacket {
        &self.frame
    }

    #[cfg(test)]
    fn scene_revision(&self) -> PacketRevision {
        self.scene_revision
    }

    #[allow(dead_code)]
    pub(crate) fn work_generation(&self) -> WorkGeneration {
        self.work_generation
    }

    #[allow(dead_code)]
    pub(crate) fn device_generation(&self) -> DeviceGeneration {
        self.device_generation
    }

    /// Logical resource identities validated as part of this packet.
    #[allow(dead_code)]
    pub(crate) fn resource_ids(&self) -> impl Iterator<Item = LogicalResourceId> + '_ {
        self.resources.ids()
    }

    /// Number of logical resources validated as part of this packet.
    #[allow(dead_code)]
    pub(crate) fn resource_count(&self) -> usize {
        self.resources.len()
    }

    #[cfg(test)]
    fn draw_count(&self) -> usize {
        self.draws.len()
    }
}

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub(crate) struct LogicalResourceId {
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
    use lumenplot_engine::bridge::Viewport;

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
    fn generations_and_scene_revision_remain_distinct_metadata() {
        let packet = packet(8);
        assert_eq!(packet.scene_revision(), packet.frame().revision());
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
            for point in &mut generated.frame.series[0].segments[0].points {
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
}
