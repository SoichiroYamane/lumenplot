use std::sync::Arc;

use crate::error::{SceneError, SceneErrorKind};
use crate::lod::{Summary, SummaryIndex};

use super::{GapSpan, NormalizedSeries, Point, Topology};

pub(crate) const MAX_POINTS_PER_CHUNK: usize = 65_536;

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub(crate) struct DataEpoch(pub(crate) u64);

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub(crate) struct ChunkRevision(pub(crate) u64);

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct Bounds {
    pub(crate) min_x: f64,
    pub(crate) max_x: f64,
    pub(crate) min_y: f64,
    pub(crate) max_y: f64,
}

impl Bounds {
    pub(crate) fn from_points(points: &[Point]) -> Option<Self> {
        let first = points.first()?;
        let mut bounds = Self {
            min_x: first.x,
            max_x: first.x,
            min_y: first.y,
            max_y: first.y,
        };
        for point in &points[1..] {
            bounds.min_x = bounds.min_x.min(point.x);
            bounds.max_x = bounds.max_x.max(point.x);
            bounds.min_y = bounds.min_y.min(point.y);
            bounds.max_y = bounds.max_y.max(point.y);
        }
        Some(bounds)
    }

    pub(crate) fn intersects(&self, min_x: f64, max_x: f64, min_y: f64, max_y: f64) -> bool {
        self.max_x >= min_x && self.min_x <= max_x && self.max_y >= min_y && self.min_y <= max_y
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct LogicalSegment {
    pub(crate) point_start: usize,
    pub(crate) point_end: usize,
    pub(crate) source_start: u64,
    pub(crate) source_end: u64,
    pub(crate) bounds: Bounds,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct ChunkSegment {
    pub(crate) logical_segment: usize,
    pub(crate) global_start: usize,
    pub(crate) global_end: usize,
    pub(crate) local_start: u32,
    pub(crate) local_end: u32,
    pub(crate) source_start: u64,
}

#[derive(Debug)]
pub(crate) struct Chunk {
    pub(crate) point_start: usize,
    pub(crate) x: Box<[f64]>,
    pub(crate) y: Box<[f64]>,
    pub(crate) segments: Box<[ChunkSegment]>,
    pub(crate) gaps: Box<[GapSpan]>,
    pub(crate) source_start: u64,
    pub(crate) source_end: u64,
    pub(crate) continues_before: bool,
    pub(crate) continues_after: bool,
    pub(crate) topology: Topology,
    pub(crate) bounds: Option<Bounds>,
    pub(crate) epoch: DataEpoch,
    pub(crate) revision: ChunkRevision,
}

#[derive(Debug)]
pub(crate) struct SeriesStorage {
    topology: Topology,
    source_len: u64,
    points: Arc<[Point]>,
    gaps: Arc<[GapSpan]>,
    segments: Arc<[LogicalSegment]>,
    chunks: Arc<[Arc<Chunk>]>,
    summary_index: Arc<SummaryIndex>,
    bounds: Option<Bounds>,
    epoch: DataEpoch,
    next_chunk_revision: ChunkRevision,
}

impl SeriesStorage {
    pub(crate) fn from_normalized(
        normalized: NormalizedSeries,
        epoch: DataEpoch,
        first_revision: ChunkRevision,
    ) -> Result<Arc<Self>, SceneError> {
        let (topology, source_len, points, gaps) = normalized.into_parts();
        Self::from_parts(topology, source_len, points, gaps, epoch, first_revision)
    }

    pub(crate) fn append(
        old: &Arc<Self>,
        normalized: NormalizedSeries,
    ) -> Result<Option<Arc<Self>>, SceneError> {
        let (topology, source_len, new_points, new_gaps) = normalized.into_parts();
        if topology != old.topology {
            return Err(SceneError::new(SceneErrorKind::TopologyViolation));
        }
        if source_len == 0 {
            return Ok(None);
        }

        let source_len_total = old
            .source_len
            .checked_add(source_len)
            .ok_or_else(|| SceneError::new(SceneErrorKind::CapacityExceeded))?;
        if old.topology == Topology::MonotonicX
            && let (Some(old_last), Some(new_first)) = (old.points.last(), new_points.first())
            && new_first.x < old_last.x
        {
            return Err(SceneError::new(SceneErrorKind::TopologyViolation));
        }

        let shifted_points = shift_points(new_points, old.source_len)?;
        let shifted_gaps = shift_gaps(new_gaps, old.source_len)?;
        let mut points = Vec::new();
        points
            .try_reserve_exact(
                old.points
                    .len()
                    .checked_add(shifted_points.len())
                    .ok_or_else(|| SceneError::new(SceneErrorKind::CapacityExceeded))?,
            )
            .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
        points.extend(old.points.iter().copied());
        points.extend(shifted_points);

        let mut gaps = Vec::new();
        gaps.try_reserve_exact(
            old.gaps
                .len()
                .checked_add(shifted_gaps.len())
                .ok_or_else(|| SceneError::new(SceneErrorKind::CapacityExceeded))?,
        )
        .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
        gaps.extend(old.gaps.iter().copied());
        gaps.extend(shifted_gaps);
        gaps = merge_adjacent_gaps(gaps)?;

        if points.len() == old.points.len() {
            return Ok(Some(Arc::new(Self {
                topology,
                source_len: source_len_total,
                points: Arc::from(points.into_boxed_slice()),
                gaps: Arc::from(gaps.into_boxed_slice()),
                segments: old.segments.clone(),
                chunks: old.chunks.clone(),
                summary_index: old.summary_index.clone(),
                bounds: old.bounds,
                epoch: old.epoch,
                next_chunk_revision: old.next_chunk_revision,
            })));
        }

        Self::from_parts(
            topology,
            source_len_total,
            points,
            gaps,
            old.epoch,
            old.next_chunk_revision,
        )
        .map(Some)
    }

    fn from_parts(
        topology: Topology,
        source_len: u64,
        points: Vec<Point>,
        gaps: Vec<GapSpan>,
        epoch: DataEpoch,
        first_revision: ChunkRevision,
    ) -> Result<Arc<Self>, SceneError> {
        if points
            .iter()
            .any(|point| !point.x.is_finite() || !point.y.is_finite())
        {
            return Err(SceneError::new(SceneErrorKind::NonFiniteCanonical));
        }
        let points_arc: Arc<[Point]> = Arc::from(points.into_boxed_slice());
        let gaps_arc: Arc<[GapSpan]> = Arc::from(gaps.into_boxed_slice());
        let segments = build_segments(&points_arc)?;
        let segments_arc: Arc<[LogicalSegment]> = Arc::from(segments.into_boxed_slice());
        let chunks = build_chunks(
            topology,
            &points_arc,
            &gaps_arc,
            &segments_arc,
            epoch,
            first_revision,
        )?;
        let next_chunk_revision = if chunks.is_empty() {
            first_revision
        } else {
            let last_revision = first_revision
                .0
                .checked_add(
                    u64::try_from(chunks.len() - 1)
                        .map_err(|_| SceneError::new(SceneErrorKind::CapacityExceeded))?,
                )
                .ok_or_else(|| SceneError::new(SceneErrorKind::RevisionExhausted))?;
            if last_revision == u64::MAX {
                ChunkRevision(0)
            } else {
                ChunkRevision(last_revision + 1)
            }
        };
        let summary_index = SummaryIndex::build(&chunks)?;
        let bounds = Bounds::from_points(&points_arc);
        Ok(Arc::new(Self {
            topology,
            source_len,
            points: points_arc,
            gaps: gaps_arc,
            segments: segments_arc,
            chunks: Arc::from(chunks.into_boxed_slice()),
            summary_index: Arc::new(summary_index),
            bounds,
            epoch,
            next_chunk_revision,
        }))
    }

    pub(crate) fn topology(&self) -> Topology {
        self.topology
    }

    pub(crate) fn source_len(&self) -> u64 {
        self.source_len
    }

    pub(crate) fn point_count(&self) -> usize {
        self.points.len()
    }

    pub(crate) fn points(&self) -> &[Point] {
        &self.points
    }

    pub(crate) fn gaps(&self) -> &[GapSpan] {
        &self.gaps
    }

    pub(crate) fn segments(&self) -> &[LogicalSegment] {
        &self.segments
    }

    pub(crate) fn chunks(&self) -> &[Arc<Chunk>] {
        &self.chunks
    }

    pub(crate) fn bounds(&self) -> Option<Bounds> {
        self.bounds
    }

    pub(crate) fn epoch(&self) -> DataEpoch {
        self.epoch
    }

    pub(crate) fn next_chunk_revision(&self) -> ChunkRevision {
        self.next_chunk_revision
    }

    pub(crate) fn indexed_summary_for_segment_range(
        &self,
        logical_segment: usize,
        start: usize,
        end: usize,
    ) -> Option<Summary> {
        if start >= end || logical_segment >= self.segments.len() {
            return None;
        }
        let mut combined: Option<Summary> = None;
        for (chunk_index, chunk) in self.chunks.iter().enumerate() {
            for (segment_slot, chunk_segment) in chunk.segments.iter().enumerate() {
                if chunk_segment.logical_segment != logical_segment {
                    continue;
                }
                let overlap_start = start.max(chunk_segment.global_start);
                let overlap_end = end.min(chunk_segment.global_end);
                if overlap_start >= overlap_end {
                    continue;
                }
                let local_start = overlap_start - chunk_segment.global_start;
                let local_end = overlap_end - chunk_segment.global_start;
                let summary = self.summary_index.range_summary(
                    chunk_index,
                    segment_slot,
                    local_start,
                    local_end,
                )?;
                combined = Some(match combined {
                    Some(previous) => previous.combine(summary),
                    None => summary,
                });
            }
        }
        combined
    }
}

fn build_segments(points: &[Point]) -> Result<Vec<LogicalSegment>, SceneError> {
    let mut segments = Vec::new();
    if points.is_empty() {
        return Ok(segments);
    }
    segments
        .try_reserve(1)
        .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
    let mut start = 0usize;
    for index in 1..=points.len() {
        let ends_segment = index == points.len()
            || points[index]
                .source
                .checked_sub(points[index - 1].source)
                .is_none_or(|distance| distance != 1);
        if ends_segment {
            let source_start = points[start].source;
            let source_end = points[index - 1]
                .source
                .checked_add(1)
                .ok_or_else(|| SceneError::new(SceneErrorKind::CapacityExceeded))?;
            let bounds = Bounds::from_points(&points[start..index])
                .ok_or_else(|| SceneError::new(SceneErrorKind::Internal))?;
            segments.push(LogicalSegment {
                point_start: start,
                point_end: index,
                source_start,
                source_end,
                bounds,
            });
            if index < points.len() {
                segments
                    .try_reserve(1)
                    .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
            }
            start = index;
        }
    }
    Ok(segments)
}

fn build_chunks(
    topology: Topology,
    points: &[Point],
    gaps: &[GapSpan],
    segments: &[LogicalSegment],
    epoch: DataEpoch,
    first_revision: ChunkRevision,
) -> Result<Vec<Arc<Chunk>>, SceneError> {
    if !points.is_empty() && first_revision.0 == 0 {
        return Err(SceneError::new(SceneErrorKind::RevisionExhausted));
    }
    let chunk_count = if points.is_empty() {
        0
    } else {
        points.len().div_ceil(MAX_POINTS_PER_CHUNK)
    };
    let mut chunks = Vec::new();
    chunks
        .try_reserve_exact(chunk_count)
        .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
    let mut point_start = 0usize;
    let mut chunk_index = 0usize;
    while point_start < points.len() {
        let point_end = point_start
            .checked_add(MAX_POINTS_PER_CHUNK)
            .unwrap_or(points.len())
            .min(points.len());
        let point_len = point_end - point_start;
        let source_start = points[point_start].source;
        let source_end = points[point_end - 1]
            .source
            .checked_add(1)
            .ok_or_else(|| SceneError::new(SceneErrorKind::CapacityExceeded))?;

        let mut x = Vec::new();
        let mut y = Vec::new();
        x.try_reserve_exact(point_len)
            .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
        y.try_reserve_exact(point_len)
            .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
        for point in &points[point_start..point_end] {
            x.push(point.x);
            y.push(point.y);
        }

        let mut chunk_segments = Vec::new();
        let mut continues_before = false;
        let mut continues_after = false;
        for (logical_index, segment) in segments.iter().enumerate() {
            let overlap_start = segment.point_start.max(point_start);
            let overlap_end = segment.point_end.min(point_end);
            if overlap_start >= overlap_end {
                continue;
            }
            continues_before |= overlap_start > segment.point_start;
            continues_after |= overlap_end < segment.point_end;
            let local_start = u32::try_from(overlap_start - point_start)
                .map_err(|_| SceneError::new(SceneErrorKind::CapacityExceeded))?;
            let local_end = u32::try_from(overlap_end - point_start)
                .map_err(|_| SceneError::new(SceneErrorKind::CapacityExceeded))?;
            chunk_segments.push(ChunkSegment {
                logical_segment: logical_index,
                global_start: overlap_start,
                global_end: overlap_end,
                local_start,
                local_end,
                source_start: points[overlap_start].source,
            });
        }

        let mut chunk_gaps = Vec::new();
        for gap in gaps {
            if gap.end <= source_start || gap.start >= source_end {
                continue;
            }
            let start = gap.start.max(source_start);
            let end = gap.end.min(source_end);
            if start < end {
                chunk_gaps.push(GapSpan { start, end });
            }
        }
        let revision = ChunkRevision(
            first_revision
                .0
                .checked_add(
                    u64::try_from(chunk_index)
                        .map_err(|_| SceneError::new(SceneErrorKind::CapacityExceeded))?,
                )
                .ok_or_else(|| SceneError::new(SceneErrorKind::RevisionExhausted))?,
        );
        chunks.push(Arc::new(Chunk {
            point_start,
            x: x.into_boxed_slice(),
            y: y.into_boxed_slice(),
            segments: chunk_segments.into_boxed_slice(),
            gaps: chunk_gaps.into_boxed_slice(),
            source_start,
            source_end,
            continues_before,
            continues_after,
            topology,
            bounds: Bounds::from_points(&points[point_start..point_end]),
            epoch,
            revision,
        }));
        point_start = point_end;
        chunk_index += 1;
    }
    Ok(chunks)
}

pub(crate) fn shift_points(mut points: Vec<Point>, offset: u64) -> Result<Vec<Point>, SceneError> {
    for point in &mut points {
        point.source = point
            .source
            .checked_add(offset)
            .ok_or_else(|| SceneError::new(SceneErrorKind::CapacityExceeded))?;
    }
    Ok(points)
}

fn shift_gaps(mut gaps: Vec<GapSpan>, offset: u64) -> Result<Vec<GapSpan>, SceneError> {
    for gap in &mut gaps {
        gap.start = gap
            .start
            .checked_add(offset)
            .ok_or_else(|| SceneError::new(SceneErrorKind::CapacityExceeded))?;
        gap.end = gap
            .end
            .checked_add(offset)
            .ok_or_else(|| SceneError::new(SceneErrorKind::CapacityExceeded))?;
    }
    Ok(gaps)
}

fn merge_adjacent_gaps(gaps: Vec<GapSpan>) -> Result<Vec<GapSpan>, SceneError> {
    let mut merged: Vec<GapSpan> = Vec::new();
    merged
        .try_reserve_exact(gaps.len())
        .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
    for gap in gaps {
        if let Some(previous) = merged.last_mut()
            && previous.end == gap.start
        {
            previous.end = gap.end;
            continue;
        }
        merged.push(gap);
    }
    Ok(merged)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::data::SeriesInput;

    fn input(
        topology: Topology,
        x: Vec<f64>,
        y: Vec<f64>,
        segments: Vec<std::ops::Range<usize>>,
    ) -> SeriesInput {
        SeriesInput::from_owned_xy(topology, x, y, Some(segments)).expect("valid input")
    }

    #[test]
    fn chunk_cuts_preserve_source_continuity() {
        let count = MAX_POINTS_PER_CHUNK + 3;
        let x: Vec<_> = (0..count).map(|value| value as f64).collect();
        let y = x.clone();
        let storage = SeriesStorage::from_normalized(
            input(
                Topology::MonotonicX,
                x,
                y,
                std::iter::once(0..count).collect(),
            )
            .into_normalized(),
            DataEpoch(1),
            ChunkRevision(1),
        )
        .expect("chunked input");
        assert_eq!(storage.chunks().len(), 2);
        assert!(storage.chunks()[0].continues_after);
        assert!(storage.chunks()[1].continues_before);
        assert_eq!(
            storage.chunks()[1].segments[0].source_start,
            MAX_POINTS_PER_CHUNK as u64
        );
        assert_eq!(storage.chunks()[0].revision, ChunkRevision(1));
        assert_eq!(storage.chunks()[1].revision, ChunkRevision(2));
    }

    #[test]
    fn append_retains_epoch_and_gap_only_append_changes_source_length() {
        let first = SeriesStorage::from_normalized(
            input(
                Topology::MonotonicX,
                vec![1.0],
                vec![2.0],
                std::iter::once(0..1).collect(),
            )
            .into_normalized(),
            DataEpoch(7),
            ChunkRevision(1),
        )
        .expect("first series");
        let appended = SeriesStorage::append(
            &first,
            input(
                Topology::MonotonicX,
                vec![f64::NAN, f64::NAN],
                vec![f64::NAN, f64::NAN],
                Vec::new(),
            )
            .into_normalized(),
        )
        .expect("append succeeds")
        .expect("nonempty gap-only append changes state");
        assert_eq!(appended.epoch(), DataEpoch(7));
        assert_eq!(appended.source_len(), 3);
        assert_eq!(appended.point_count(), 1);
        assert_eq!(first.source_len(), 1);
        assert_eq!(first.chunks().len(), appended.chunks().len());
    }

    #[test]
    fn append_merges_adjacent_structural_gaps() {
        let first = SeriesStorage::from_normalized(
            input(
                Topology::ArbitraryXY,
                vec![1.0, f64::NAN, f64::NAN],
                vec![2.0, f64::NAN, f64::NAN],
                std::iter::once(0..1).collect(),
            )
            .into_normalized(),
            DataEpoch(1),
            ChunkRevision(1),
        )
        .expect("first series");
        let appended = SeriesStorage::append(
            &first,
            input(
                Topology::ArbitraryXY,
                vec![f64::NAN, f64::NAN],
                vec![f64::NAN, f64::NAN],
                Vec::new(),
            )
            .into_normalized(),
        )
        .expect("append succeeds")
        .expect("gap-only append changes source length");
        assert_eq!(appended.gaps(), &[GapSpan { start: 1, end: 5 }]);
    }
}
