use std::sync::Arc;

use crate::data::{Chunk, ChunkSegment};
use crate::error::{SceneError, SceneErrorKind};

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct PointRef {
    pub(crate) source: u64,
    pub(crate) x: f64,
    pub(crate) y: f64,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct Summary {
    pub(crate) first: PointRef,
    pub(crate) last: PointRef,
    pub(crate) min_y: PointRef,
    pub(crate) max_y: PointRef,
}

impl Summary {
    pub(crate) fn from_point(point: PointRef) -> Self {
        Self {
            first: point,
            last: point,
            min_y: point,
            max_y: point,
        }
    }

    pub(crate) fn combine(self, other: Self) -> Self {
        let min_y = if other.min_y.y < self.min_y.y
            || (other.min_y.y == self.min_y.y && other.min_y.source < self.min_y.source)
        {
            other.min_y
        } else {
            self.min_y
        };
        let max_y = if other.max_y.y > self.max_y.y
            || (other.max_y.y == self.max_y.y && other.max_y.source < self.max_y.source)
        {
            other.max_y
        } else {
            self.max_y
        };
        Self {
            first: self.first,
            last: other.last,
            min_y,
            max_y,
        }
    }
}

#[derive(Debug)]
struct SegmentSummaryIndex {
    point_len: usize,
    blocks: Box<[Summary]>,
    tree_levels: Box<[Box<[Summary]>]>,
}

#[derive(Debug)]
struct ChunkSummaryIndex {
    segments: Box<[SegmentSummaryIndex]>,
}

#[derive(Debug)]
pub(crate) struct SummaryIndex {
    chunks: Box<[ChunkSummaryIndex]>,
    data_chunks: Box<[Arc<Chunk>]>,
}

impl SummaryIndex {
    pub(crate) fn build(chunks: &[Arc<Chunk>]) -> Result<Self, SceneError> {
        let mut chunk_indexes = Vec::new();
        chunk_indexes
            .try_reserve_exact(chunks.len())
            .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
        for chunk in chunks {
            let mut segment_indexes = Vec::new();
            segment_indexes
                .try_reserve_exact(chunk.segments.len())
                .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
            for segment in &chunk.segments {
                segment_indexes.push(build_segment_index(chunk, segment)?);
            }
            chunk_indexes.push(ChunkSummaryIndex {
                segments: segment_indexes.into_boxed_slice(),
            });
        }
        Ok(Self {
            chunks: chunk_indexes.into_boxed_slice(),
            data_chunks: chunks.to_vec().into_boxed_slice(),
        })
    }

    pub(crate) fn range_summary(
        &self,
        chunk_index: usize,
        segment_index: usize,
        start: usize,
        end: usize,
    ) -> Option<Summary> {
        let segment = self.chunks.get(chunk_index)?.segments.get(segment_index)?;
        if start >= end || end > segment.point_len {
            return None;
        }

        let mut result = None;
        let mut cursor = start;
        while cursor < end && !cursor.is_multiple_of(256) {
            result = combine_optional(
                result,
                self.point_summary(chunk_index, segment_index, cursor),
            );
            cursor += 1;
        }

        let full_start = cursor / 256;
        let full_end = (end / 256).min(segment.blocks.len());
        if full_start < full_end {
            result = combine_optional(result, self.tree_range(segment, full_start, full_end));
            cursor = full_end * 256;
        }

        while cursor < end {
            result = combine_optional(
                result,
                self.point_summary(chunk_index, segment_index, cursor),
            );
            cursor += 1;
        }
        result
    }

    fn point_summary(
        &self,
        chunk_index: usize,
        segment_index: usize,
        relative_index: usize,
    ) -> Option<Summary> {
        let index = self.chunks.get(chunk_index)?.segments.get(segment_index)?;
        if relative_index >= index.point_len {
            return None;
        }
        let chunk = self.data_chunks.get(chunk_index)?;
        let chunk_segment = chunk.segments.get(segment_index)?;
        let local_start = usize::try_from(chunk_segment.local_start).ok()?;
        let local = local_start.checked_add(relative_index)?;
        let source = chunk_segment
            .source_start
            .checked_add(u64::try_from(relative_index).ok()?)?;
        Some(Summary::from_point(PointRef {
            source,
            x: *chunk.x.get(local)?,
            y: *chunk.y.get(local)?,
        }))
    }

    fn tree_range(
        &self,
        segment: &SegmentSummaryIndex,
        mut start: usize,
        end: usize,
    ) -> Option<Summary> {
        let mut result = None;
        while start < end {
            let remaining = end - start;
            let mut size = 1usize << (usize::BITS - 1 - remaining.leading_zeros());
            while !start.is_multiple_of(size) {
                size >>= 1;
            }
            let level = size.trailing_zeros() as usize;
            let node = segment.tree_levels.get(level)?.get(start / size)?;
            result = combine_optional(result, Some(*node));
            start += size;
        }
        result
    }
}

fn build_segment_index(
    chunk: &Chunk,
    segment: &ChunkSegment,
) -> Result<SegmentSummaryIndex, SceneError> {
    let local_start = usize::try_from(segment.local_start)
        .map_err(|_| SceneError::new(SceneErrorKind::CapacityExceeded))?;
    let local_end = usize::try_from(segment.local_end)
        .map_err(|_| SceneError::new(SceneErrorKind::CapacityExceeded))?;
    let point_len = local_end
        .checked_sub(local_start)
        .ok_or_else(|| SceneError::new(SceneErrorKind::CapacityExceeded))?;
    let block_count = point_len.div_ceil(256);
    let mut blocks = Vec::new();
    blocks
        .try_reserve_exact(block_count)
        .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
    for block_start in (0..point_len).step_by(256) {
        let block_end = (block_start + 256).min(point_len);
        let mut summary = None;
        for relative in block_start..block_end {
            let local = local_start + relative;
            let source = segment
                .source_start
                .checked_add(
                    u64::try_from(relative)
                        .map_err(|_| SceneError::new(SceneErrorKind::CapacityExceeded))?,
                )
                .ok_or_else(|| SceneError::new(SceneErrorKind::CapacityExceeded))?;
            let point = PointRef {
                source,
                x: *chunk
                    .x
                    .get(local)
                    .ok_or_else(|| SceneError::new(SceneErrorKind::Internal))?,
                y: *chunk
                    .y
                    .get(local)
                    .ok_or_else(|| SceneError::new(SceneErrorKind::Internal))?,
            };
            summary = combine_optional(summary, Some(Summary::from_point(point)));
        }
        blocks.push(summary.ok_or_else(|| SceneError::new(SceneErrorKind::Internal))?);
    }

    let full_block_count = point_len / 256;
    let mut levels: Vec<Vec<Summary>> = Vec::new();
    if full_block_count > 0 {
        levels
            .try_reserve(usize::BITS as usize)
            .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
        levels.push(blocks[..full_block_count].to_vec());
        while levels.last().is_some_and(|level| level.len() > 1) {
            let previous = levels.last().expect("level exists");
            let next_len = previous.len().div_ceil(2);
            let mut next = Vec::new();
            next.try_reserve_exact(next_len)
                .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
            for pair in previous.chunks(2) {
                let first = pair[0];
                next.push(
                    pair.get(1)
                        .copied()
                        .map_or(first, |second| first.combine(second)),
                );
            }
            levels.push(next);
        }
    }
    let boxed_levels = levels
        .into_iter()
        .map(Vec::into_boxed_slice)
        .collect::<Vec<_>>()
        .into_boxed_slice();
    Ok(SegmentSummaryIndex {
        point_len,
        blocks: blocks.into_boxed_slice(),
        tree_levels: boxed_levels,
    })
}

fn combine_optional(left: Option<Summary>, right: Option<Summary>) -> Option<Summary> {
    match (left, right) {
        (Some(left), Some(right)) => Some(left.combine(right)),
        (Some(value), None) | (None, Some(value)) => Some(value),
        (None, None) => None,
    }
}

#[cfg(test)]
mod tests {
    use crate::data::{DataEpoch, SeriesInput, SeriesStorage, Topology};

    const CHUNK_LIMIT: usize = 65_536;

    #[test]
    fn indexed_range_summary_matches_direct_extrema() {
        let x: Vec<_> = (0..700).map(|value| value as f64).collect();
        let y: Vec<_> = x.iter().map(|value| (value * 13.0) % 97.0 - 40.0).collect();
        let input = SeriesInput::from_owned_xy(Topology::MonotonicX, x, y, None).expect("input");
        let storage = SeriesStorage::from_normalized(
            input.into_normalized(),
            DataEpoch(1),
            crate::data::ChunkRevision(1),
        )
        .expect("storage");
        let summary = storage
            .indexed_summary_for_segment_range(0, 17, 613)
            .expect("summary");
        let direct = &storage.points()[17..613];
        assert_eq!(summary.first.source, direct.first().expect("first").source);
        assert_eq!(summary.last.source, direct.last().expect("last").source);
        let min = direct
            .iter()
            .min_by(|left, right| {
                left.y
                    .total_cmp(&right.y)
                    .then(left.source.cmp(&right.source))
            })
            .expect("minimum");
        let max = direct
            .iter()
            .max_by(|left, right| {
                left.y
                    .total_cmp(&right.y)
                    .then(right.source.cmp(&left.source))
            })
            .expect("maximum");
        assert_eq!(summary.min_y.source, min.source);
        assert_eq!(summary.max_y.source, max.source);
    }

    #[test]
    fn extrema_ties_choose_the_earliest_source() {
        let input = SeriesInput::from_owned_xy(
            Topology::MonotonicX,
            vec![0.0, 1.0, 2.0, 3.0],
            vec![5.0, 1.0, 1.0, 5.0],
            None,
        )
        .expect("input");
        let storage = SeriesStorage::from_normalized(
            input.into_normalized(),
            DataEpoch(1),
            crate::data::ChunkRevision(1),
        )
        .expect("storage");
        let summary = storage
            .indexed_summary_for_segment_range(0, 0, 4)
            .expect("summary");
        assert_eq!(summary.min_y.source, 1);
        assert_eq!(summary.max_y.source, 0);
    }

    #[test]
    fn range_summary_spans_a_chunk_cut_without_losing_source_identity() {
        let count = CHUNK_LIMIT + 513;
        let x: Vec<_> = (0..count).map(|value| value as f64).collect();
        let y: Vec<_> = (0..count)
            .map(|value| ((value * 17) % 101) as f64)
            .collect();
        let storage = SeriesStorage::from_normalized(
            SeriesInput::from_owned_xy(Topology::MonotonicX, x, y, None)
                .expect("input")
                .into_normalized(),
            DataEpoch(1),
            crate::data::ChunkRevision(1),
        )
        .expect("storage");
        let start = CHUNK_LIMIT - 71;
        let end = CHUNK_LIMIT + 71;
        let summary = storage
            .indexed_summary_for_segment_range(0, start, end)
            .expect("summary across chunk cut");
        assert_eq!(summary.first.source, start as u64);
        assert_eq!(summary.last.source, (end - 1) as u64);
    }

    /// Naive reference model of the eager block-summary index: recompute
    /// first/last/min/max for every queried range with a plain linear scan
    /// and identical tie rules. Production never calls this; it exists so
    /// the dyadic decomposition is checked against something readable.
    fn naive_summary_of(storage: &SeriesStorage, start: usize, end: usize) -> (u64, u64, u64, u64) {
        let slice = &storage.points()[start..end];
        let min = slice
            .iter()
            .min_by(|left, right| {
                left.y
                    .total_cmp(&right.y)
                    .then(left.source.cmp(&right.source))
            })
            .expect("minimum");
        let max = slice
            .iter()
            .max_by(|left, right| {
                left.y
                    .total_cmp(&right.y)
                    .then(right.source.cmp(&left.source))
            })
            .expect("maximum");
        (
            slice.first().expect("first").source,
            min.source,
            max.source,
            slice.last().expect("last").source,
        )
    }

    #[test]
    fn dyadic_block_index_matches_naive_scan_across_chunk_cuts_and_ties() {
        // Local correctness fixture for the eager dyadic summary index that
        // the O(W)-intent selection leans on: every queried sub-range —
        // spanning block boundaries, chunk cuts, duplicate-y ties, and
        // single-point ranges — must agree exactly with the plain linear
        // model, including which sample wins an extrema tie.
        let count = CHUNK_LIMIT * 2 + 129;
        let x: Vec<_> = (0..count).map(|value| value as f64).collect();
        // Duplicate-y plateaus make the earliest-source tie rule observable;
        // interior spikes guarantee real extrema inside each probed window.
        let mut y: Vec<_> = (0..count).map(|value| ((value / 3) % 29) as f64).collect();
        for position in [CHUNK_LIMIT - 1usize, CHUNK_LIMIT, count - 2] {
            y[position] = 5_000.0;
        }
        for position in [CHUNK_LIMIT + 1usize, count - 1] {
            y[position] = -6_000.0;
        }
        let storage = SeriesStorage::from_normalized(
            SeriesInput::from_owned_xy(Topology::MonotonicX, x, y.clone(), None)
                .expect("input")
                .into_normalized(),
            DataEpoch(1),
            crate::data::ChunkRevision(1),
        )
        .expect("storage");
        assert!(storage.chunks().len() >= 2);

        let probes = [
            (0usize, count),
            (CHUNK_LIMIT - 3, CHUNK_LIMIT + 4),
            (CHUNK_LIMIT, CHUNK_LIMIT * 2),
            (count - 1, count),
            (17, 18),
            (4095, 8192),
            (8192, 8193),
        ];
        for &(start, end) in &probes {
            let summary = storage
                .indexed_summary_for_segment_range(0, start, end)
                .unwrap_or_else(|| panic!("summary for {start}..{end}"));
            assert_eq!(
                (
                    summary.first.source,
                    summary.min_y.source,
                    summary.max_y.source,
                    summary.last.source
                ),
                naive_summary_of(&storage, start, end),
                "index disagreed with the naive scan for {start}..{end}"
            );
            // f64 canonical payloads survive indexing bit-exactly.
            assert_eq!(
                summary.min_y.y.to_bits(),
                y[summary.min_y.source as usize].to_bits()
            );
            assert_eq!(
                summary.max_y.y.to_bits(),
                y[summary.max_y.source as usize].to_bits()
            );
        }

        // Out-of-range and empty queries stay explicit failures: an empty
        // range is rejected outright, and an end past the segment is clamped
        // to the valid window rather than silently reinterpreted.
        assert!(storage.indexed_summary_for_segment_range(0, 5, 5).is_none());
        let clamped = storage
            .indexed_summary_for_segment_range(0, 10, count + 1)
            .expect("end beyond the segment clamps to the valid window");
        assert_eq!(
            (
                clamped.first.source,
                clamped.min_y.source,
                clamped.max_y.source,
                clamped.last.source
            ),
            naive_summary_of(&storage, 10, count)
        );
    }

    #[test]
    fn cross_chunk_ties_keep_earliest_source_and_exact_f64_payloads() {
        // LP-DATA-001/002 and LP-LOD-003/005: a range crossing the fixed
        // chunk cut must preserve the f64 payload and choose the earliest
        // source for both extrema when every y value ties.
        let count = CHUNK_LIMIT + 7;
        let x: Vec<_> = (0..count).map(|value| value as f64).collect();
        let tied_y = 1.0 + 2.0 * f64::EPSILON;
        let y = vec![tied_y; count];
        let storage = SeriesStorage::from_normalized(
            SeriesInput::from_owned_xy(Topology::MonotonicX, x.clone(), y, None)
                .expect("input")
                .into_normalized(),
            DataEpoch(5),
            crate::data::ChunkRevision(1),
        )
        .expect("storage");
        let start = CHUNK_LIMIT - 3;
        let end = CHUNK_LIMIT + 4;
        let summary = storage
            .indexed_summary_for_segment_range(0, start, end)
            .expect("cross-chunk summary");

        assert_eq!(summary.first.source, start as u64);
        assert_eq!(summary.last.source, (end - 1) as u64);
        assert_eq!(summary.min_y.source, start as u64);
        assert_eq!(summary.max_y.source, start as u64);
        assert_eq!(summary.first.x.to_bits(), x[start].to_bits());
        assert_eq!(summary.last.x.to_bits(), x[end - 1].to_bits());
        assert_eq!(summary.min_y.y.to_bits(), tied_y.to_bits());
        assert_eq!(summary.max_y.y.to_bits(), tied_y.to_bits());
        assert_ne!(((tied_y as f32) as f64).to_bits(), tied_y.to_bits());
    }
}
