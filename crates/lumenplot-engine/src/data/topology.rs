use std::ops::Range;

use crate::error::{SceneError, SceneErrorKind};

use super::{GapSpan, Point};

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) enum Topology {
    MonotonicX,
    ArbitraryXY,
}

#[derive(Debug)]
pub(crate) struct SeriesInput {
    topology: Topology,
    normalized: NormalizedSeries,
}

#[derive(Debug)]
pub(crate) struct NormalizedSeries {
    topology: Topology,
    source_len: u64,
    points: Vec<Point>,
    gaps: Vec<GapSpan>,
}

impl SeriesInput {
    pub(crate) fn from_owned_xy(
        topology: Topology,
        x: Vec<f64>,
        y: Vec<f64>,
        valid_segments: Option<Vec<Range<usize>>>,
    ) -> Result<Self, SceneError> {
        if x.len() != y.len() {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }

        let source_len = u64::try_from(x.len())
            .map_err(|_| SceneError::new(SceneErrorKind::CapacityExceeded))?;
        let segments = match valid_segments {
            Some(segments) => segments,
            None => {
                if x.is_empty() {
                    Vec::new()
                } else {
                    std::iter::once(0..x.len()).collect()
                }
            }
        };
        validate_segments(x.len(), &segments)?;

        let mut point_count = 0usize;
        for segment in &segments {
            point_count = point_count
                .checked_add(segment.end - segment.start)
                .ok_or_else(|| SceneError::new(SceneErrorKind::CapacityExceeded))?;
        }

        let mut points = Vec::new();
        points
            .try_reserve_exact(point_count)
            .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
        let mut previous_x = None;
        for segment in &segments {
            for index in segment.clone() {
                let x_value = x[index];
                let y_value = y[index];
                if !x_value.is_finite() || !y_value.is_finite() {
                    return Err(SceneError::new(SceneErrorKind::NonFiniteCanonical));
                }
                if topology == Topology::MonotonicX
                    && previous_x.is_some_and(|previous| x_value < previous)
                {
                    return Err(SceneError::new(SceneErrorKind::TopologyViolation));
                }
                previous_x = Some(x_value);
                let source = u64::try_from(index)
                    .map_err(|_| SceneError::new(SceneErrorKind::CapacityExceeded))?;
                points.push(Point {
                    source,
                    x: x_value,
                    y: y_value,
                });
            }
        }

        let mut gaps = Vec::new();
        gaps.try_reserve(
            segments
                .len()
                .checked_add(1)
                .ok_or_else(|| SceneError::new(SceneErrorKind::CapacityExceeded))?,
        )
        .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
        let mut cursor = 0usize;
        for segment in &segments {
            if cursor < segment.start {
                let start = u64::try_from(cursor)
                    .map_err(|_| SceneError::new(SceneErrorKind::CapacityExceeded))?;
                let end = u64::try_from(segment.start)
                    .map_err(|_| SceneError::new(SceneErrorKind::CapacityExceeded))?;
                gaps.push(GapSpan::new(start, end).expect("validated gap span"));
            }
            cursor = segment.end;
        }
        if cursor < x.len() {
            let start = u64::try_from(cursor)
                .map_err(|_| SceneError::new(SceneErrorKind::CapacityExceeded))?;
            gaps.push(GapSpan::new(start, source_len).expect("validated trailing gap span"));
        }

        Ok(Self {
            topology,
            normalized: NormalizedSeries {
                topology,
                source_len,
                points,
                gaps,
            },
        })
    }

    pub(crate) fn topology(&self) -> Topology {
        self.topology
    }

    pub(crate) fn source_len(&self) -> u64 {
        self.normalized.source_len
    }

    pub(crate) fn point_count(&self) -> usize {
        self.normalized.points.len()
    }

    pub(crate) fn into_normalized(self) -> NormalizedSeries {
        self.normalized
    }
}

impl NormalizedSeries {
    pub(crate) fn topology(&self) -> Topology {
        self.topology
    }

    pub(crate) fn source_len(&self) -> u64 {
        self.source_len
    }

    pub(crate) fn points(&self) -> &[Point] {
        &self.points
    }

    pub(crate) fn gaps(&self) -> &[GapSpan] {
        &self.gaps
    }

    pub(crate) fn into_parts(self) -> (Topology, u64, Vec<Point>, Vec<GapSpan>) {
        (self.topology, self.source_len, self.points, self.gaps)
    }
}

fn validate_segments(source_len: usize, segments: &[Range<usize>]) -> Result<(), SceneError> {
    let mut previous_end = 0usize;
    for (position, segment) in segments.iter().enumerate() {
        if segment.start >= segment.end || segment.end > source_len {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }
        if position > 0 && segment.start <= previous_end {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }
        previous_end = segment.end;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::data::{ChunkRevision, DataEpoch, SeriesStorage};

    #[test]
    fn normalizes_segments_and_ignores_uncovered_payload() {
        let input = SeriesInput::from_owned_xy(
            Topology::ArbitraryXY,
            vec![1.0, f64::NAN, 3.0, f64::INFINITY],
            vec![10.0, f64::NAN, 30.0, f64::NEG_INFINITY],
            Some(vec![0..1, 2..3]),
        )
        .expect("segments are valid");
        let normalized = input.into_normalized();
        assert_eq!(normalized.source_len(), 4);
        assert_eq!(normalized.points().len(), 2);
        assert_eq!(normalized.points()[1].source, 2);
        assert_eq!(
            normalized.gaps(),
            &[GapSpan { start: 1, end: 2 }, GapSpan { start: 3, end: 4 }]
        );
    }

    #[test]
    fn rejects_nonfinite_covered_values_and_monotonic_reversal() {
        let nonfinite = SeriesInput::from_owned_xy(
            Topology::MonotonicX,
            vec![1.0, f64::NAN],
            vec![1.0, 2.0],
            None,
        );
        assert_eq!(
            nonfinite.expect_err("nonfinite input must fail").kind(),
            SceneErrorKind::NonFiniteCanonical
        );

        let reversal =
            SeriesInput::from_owned_xy(Topology::MonotonicX, vec![2.0, 1.0], vec![1.0, 2.0], None);
        assert_eq!(
            reversal.expect_err("reversal must fail").kind(),
            SceneErrorKind::TopologyViolation
        );
    }

    #[test]
    fn accepts_empty_and_gap_only_inputs() {
        let empty = SeriesInput::from_owned_xy(Topology::MonotonicX, vec![], vec![], None)
            .expect("empty input is valid")
            .into_normalized();
        assert_eq!(empty.source_len(), 0);
        assert!(empty.points().is_empty());
        assert!(empty.gaps().is_empty());

        let gap_only = SeriesInput::from_owned_xy(
            Topology::ArbitraryXY,
            vec![f64::NAN, f64::INFINITY],
            vec![f64::NAN, f64::NEG_INFINITY],
            Some(Vec::new()),
        )
        .expect("gap-only input is valid")
        .into_normalized();
        assert_eq!(gap_only.source_len(), 2);
        assert!(gap_only.points().is_empty());
        assert_eq!(gap_only.gaps(), &[GapSpan { start: 0, end: 2 }]);
    }

    #[test]
    fn monotonic_order_is_checked_across_a_gap_and_bits_are_preserved() {
        let reversal = SeriesInput::from_owned_xy(
            Topology::MonotonicX,
            vec![0.0, f64::NAN, -1.0],
            vec![0.0, f64::NAN, 2.0],
            Some(vec![0..1, 2..3]),
        )
        .expect_err("monotonic order spans gaps");
        assert_eq!(reversal.kind(), SceneErrorKind::TopologyViolation);

        let x = -0.0;
        let y = f64::from_bits(1);
        let normalized = SeriesInput::from_owned_xy(Topology::ArbitraryXY, vec![x], vec![y], None)
            .expect("finite values")
            .into_normalized();
        assert_eq!(normalized.points()[0].x.to_bits(), x.to_bits());
        assert_eq!(normalized.points()[0].y.to_bits(), y.to_bits());
    }

    #[test]
    fn source_positions_reconstruct_valid_points_and_gaps() {
        let normalized = SeriesInput::from_owned_xy(
            Topology::ArbitraryXY,
            vec![10.0, f64::NAN, f64::NAN, 40.0],
            vec![1.0, f64::NAN, f64::NAN, 4.0],
            Some(vec![0..1, 3..4]),
        )
        .expect("segments")
        .into_normalized();
        let mut covered = normalized
            .points()
            .iter()
            .map(|point| point.source)
            .collect::<Vec<_>>();
        covered.extend(normalized.gaps().iter().flat_map(|gap| gap.start..gap.end));
        covered.sort_unstable();
        assert_eq!(covered, (0..normalized.source_len()).collect::<Vec<_>>());
    }

    #[test]
    fn checked_source_shift_rejects_overflow() {
        let result = super::super::chunk::shift_points(
            vec![Point {
                source: 1,
                x: 0.0,
                y: 0.0,
            }],
            u64::MAX,
        );
        assert_eq!(
            result
                .expect_err("source arithmetic must be checked")
                .kind(),
            SceneErrorKind::CapacityExceeded
        );
    }

    #[test]
    fn monotonicx_rejects_decreasing_and_arbitraryxy_accepts_it() {
        // LP-LOD-004 topology-model fixture: the two topologies are distinct
        // ingestion models. MonotonicX enforces the x-nondecreasing invariant
        // (strictly decreasing pairs are TopologyViolation); ArbitraryXY
        // deliberately accepts arbitrary x order because its v1 contract is
        // correctness-preserving culling, not an ordering assumption.
        let decreasing_x = vec![3.0, 1.0, 2.0];
        let y = vec![1.0, 2.0, 3.0];

        let monotonic =
            SeriesInput::from_owned_xy(Topology::MonotonicX, decreasing_x.clone(), y.clone(), None);
        assert_eq!(
            monotonic
                .expect_err("MonotonicX must reject decreasing x")
                .kind(),
            SceneErrorKind::TopologyViolation
        );

        let arbitrary = SeriesInput::from_owned_xy(Topology::ArbitraryXY, decreasing_x, y, None)
            .expect("ArbitraryXY accepts any x order")
            .into_normalized();
        assert_eq!(arbitrary.points().len(), 3);
        assert_eq!(arbitrary.points()[0].source, 0);
    }

    #[test]
    fn monotonicx_equality_is_valid_but_append_reversal_is_not() {
        // LP-LOD-004 boundary model: equal adjacent x stays inside
        // MonotonicX (duplicate-x runs are valid samples), while a strictly
        // smaller x across an append boundary violates the topology even
        // though each half was individually nondecreasing.
        let flat = SeriesInput::from_owned_xy(
            Topology::MonotonicX,
            vec![1.0, 1.0, 1.0],
            vec![0.0, 5.0, -2.0],
            None,
        )
        .expect("equal adjacent x is valid MonotonicX");
        let first =
            SeriesStorage::from_normalized(flat.into_normalized(), DataEpoch(4), ChunkRevision(1))
                .expect("storage");

        let continuation =
            SeriesInput::from_owned_xy(Topology::MonotonicX, vec![0.5], vec![9.0], None);
        assert_eq!(
            SeriesStorage::append(&first, continuation.expect("input").into_normalized())
                .expect_err("append must keep the x order across the seam")
                .kind(),
            SceneErrorKind::TopologyViolation
        );

        let same_x_continuation =
            SeriesInput::from_owned_xy(Topology::MonotonicX, vec![1.0], vec![7.0], None)
                .expect("input")
                .into_normalized();
        let appended = SeriesStorage::append(&first, same_x_continuation)
            .expect("append succeeds")
            .expect("append changes state");
        assert_eq!(appended.point_count(), 4);
        assert_eq!(appended.topology(), Topology::MonotonicX);
    }

    #[test]
    fn append_cannot_change_a_series_topology() {
        // LP-LOD-004 identity model: topology is a per-series invariant.
        // Appending data with a different topology must fail closed instead
        // of silently retagging the stored series.
        let monotonic =
            SeriesInput::from_owned_xy(Topology::MonotonicX, vec![0.0, 1.0], vec![1.0, 2.0], None)
                .expect("input");
        let series = SeriesStorage::from_normalized(
            monotonic.into_normalized(),
            DataEpoch(1),
            ChunkRevision(1),
        )
        .expect("storage");

        let arbitrary_append =
            SeriesInput::from_owned_xy(Topology::ArbitraryXY, vec![5.0, 4.0], vec![0.0, 1.0], None)
                .expect("valid on its own");
        assert_eq!(
            SeriesStorage::append(&series, arbitrary_append.into_normalized())
                .expect_err("cross-topology append must fail")
                .kind(),
            SceneErrorKind::TopologyViolation
        );
        assert_eq!(series.source_len(), 2);
    }

    #[test]
    fn canonical_f64_values_survive_normalization_bit_exactly() {
        // LP-DATA-001/002: normalization owns canonical values as f64. The
        // near-one values are deliberately distinct in f64 but collapse when
        // narrowed to f32, making an accidental precision conversion visible.
        let x = vec![-0.0, f64::from_bits(1), 1.0 + 2.0 * f64::EPSILON, f64::MAX];
        let y = vec![
            f64::from_bits(0x8000_0000_0000_0000 | 1),
            -f64::from_bits(1),
            -1.0 - 2.0 * f64::EPSILON,
            f64::MIN_POSITIVE,
        ];
        let normalized =
            SeriesInput::from_owned_xy(Topology::ArbitraryXY, x.clone(), y.clone(), None)
                .expect("finite values")
                .into_normalized();

        assert_eq!(normalized.points().len(), x.len());
        for (index, point) in normalized.points().iter().enumerate() {
            assert_eq!(point.source, index as u64);
            assert_eq!(point.x.to_bits(), x[index].to_bits());
            assert_eq!(point.y.to_bits(), y[index].to_bits());
        }
        assert_ne!(((x[2] as f32) as f64).to_bits(), x[2].to_bits());
        assert_ne!(((y[2] as f32) as f64).to_bits(), y[2].to_bits());
    }

    #[test]
    fn every_nonfinite_covered_coordinate_is_rejected() {
        // LP-DATA-001/002 negative table: non-finite values cannot enter the
        // canonical store, regardless of which coordinate carries them.
        let cases = [
            (f64::NAN, 0.0),
            (f64::INFINITY, 0.0),
            (f64::NEG_INFINITY, 0.0),
            (0.0, f64::NAN),
            (0.0, f64::INFINITY),
            (0.0, f64::NEG_INFINITY),
        ];
        for (x, y) in cases {
            let error = SeriesInput::from_owned_xy(Topology::ArbitraryXY, vec![x], vec![y], None)
                .expect_err("non-finite covered payload must fail");
            assert_eq!(error.kind(), SceneErrorKind::NonFiniteCanonical);
        }
    }

    #[test]
    fn segmented_input_rejects_empty_overlapping_adjacent_and_out_of_bounds_ranges() {
        // The segmented constructor has an explicit structural contract:
        // ranges are nonempty, sorted, strictly separated, and in bounds.
        let invalid = vec![
            vec![0..0],
            vec![0..5],
            vec![1..2, 0..1],
            vec![0..1, 1..2],
            vec![0..2, 1..3],
        ];
        for segments in invalid {
            let error = SeriesInput::from_owned_xy(
                Topology::ArbitraryXY,
                vec![0.0, 1.0, 2.0, 3.0],
                vec![0.0, 1.0, 2.0, 3.0],
                Some(segments),
            )
            .expect_err("malformed segment ranges must fail");
            assert_eq!(error.kind(), SceneErrorKind::InvalidInput);
        }
    }
}
