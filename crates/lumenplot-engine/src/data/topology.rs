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
}
