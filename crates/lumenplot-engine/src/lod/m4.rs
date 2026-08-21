use crate::data::{LogicalSegment, Point, SeriesStorage};
use crate::error::{SceneError, SceneErrorKind};
use crate::scene::{AxisScale, AxisScales, Viewport};

use crate::lod::{PointRef, Summary};

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct LodPoint {
    pub(crate) source: u64,
    pub(crate) x: f64,
    pub(crate) y: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub(crate) struct SelectionSegment {
    pub(crate) points: Vec<LodPoint>,
}

#[derive(Clone, Debug, PartialEq)]
pub(crate) struct LodSelection {
    pub(crate) segments: Vec<SelectionSegment>,
    pub(crate) full_resolution: bool,
    pub(crate) effective_bins: usize,
}

pub(crate) fn select_monotonic(
    series: &SeriesStorage,
    viewport: &Viewport,
    scales: &AxisScales,
    bins: usize,
) -> Result<LodSelection, SceneError> {
    if series.topology() != crate::data::Topology::MonotonicX {
        return Err(SceneError::new(SceneErrorKind::TopologyViolation));
    }
    if bins == 0 {
        return Err(SceneError::new(SceneErrorKind::InvalidInput));
    }
    scales.validate(viewport)?;
    let q0 = viewport.x().min();
    let q1 = viewport.x().max();
    let visible_ranges = visible_ranges(series, q0, q1);
    let visible_count = visible_ranges.iter().try_fold(0usize, |count, range| {
        count
            .checked_add(range.1 - range.0)
            .ok_or_else(|| SceneError::new(SceneErrorKind::CapacityExceeded))
    })?;
    let four_bins = bins
        .checked_mul(4)
        .ok_or_else(|| SceneError::new(SceneErrorKind::CapacityExceeded))?;

    if scales.x() == AxisScale::Log10 || scales.y() == AxisScale::Log10 {
        return full_resolution(series, &visible_ranges, scales, true);
    }
    if visible_count <= four_bins {
        return full_resolution(series, &visible_ranges, scales, false);
    }

    let boundaries = make_boundaries(q0, q1, bins)?;
    let effective_bins = boundaries.len().saturating_sub(1);
    let mut output = Vec::new();
    output
        .try_reserve(series.segments().len())
        .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
    for (segment_index, segment) in series.segments().iter().enumerate() {
        let mut candidates = Vec::new();
        candidates
            .try_reserve(effective_bins.saturating_mul(4))
            .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
        for bin in 0..effective_bins {
            let lower = boundaries[bin];
            let upper = boundaries[bin + 1];
            let start = lower_bound(series.points(), segment, lower);
            let end = if bin + 1 == effective_bins {
                upper_bound(series.points(), segment, upper)
            } else {
                lower_bound(series.points(), segment, upper)
            };
            if start >= end {
                continue;
            }
            append_boundary_duplicates(&mut candidates, series.points(), segment, lower)?;
            if bin + 1 == effective_bins {
                append_boundary_duplicates(&mut candidates, series.points(), segment, upper)?;
            }
            let summary = series
                .indexed_summary_for_segment_range(segment_index, start, end)
                .ok_or_else(|| SceneError::new(SceneErrorKind::Internal))?;
            append_summary_candidates(&mut candidates, summary);
        }
        candidates.sort_unstable_by_key(|point: &LodPoint| point.source);
        candidates.dedup_by_key(|point| point.source);
        if !candidates.is_empty() {
            output.push(SelectionSegment { points: candidates });
        }
    }
    Ok(LodSelection {
        segments: output,
        full_resolution: false,
        effective_bins,
    })
}

fn visible_ranges(series: &SeriesStorage, q0: f64, q1: f64) -> Vec<(usize, usize)> {
    series
        .segments()
        .iter()
        .map(|segment| {
            (
                lower_bound(series.points(), segment, q0),
                upper_bound(series.points(), segment, q1),
            )
        })
        .filter(|(start, end)| start < end)
        .collect()
}

fn full_resolution(
    series: &SeriesStorage,
    ranges: &[(usize, usize)],
    scales: &AxisScales,
    derived_gaps: bool,
) -> Result<LodSelection, SceneError> {
    let mut output = Vec::new();
    output
        .try_reserve(ranges.len())
        .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
    for &(start, end) in ranges {
        let mut current = Vec::new();
        current
            .try_reserve(end - start)
            .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
        for point in &series.points()[start..end] {
            let valid = (!derived_gaps || valid_for_scales(point, scales))
                && (scales.x() != AxisScale::Log10 || point.x > 0.0)
                && (scales.y() != AxisScale::Log10 || point.y > 0.0);
            if valid {
                current.push(LodPoint {
                    source: point.source,
                    x: point.x,
                    y: point.y,
                });
            } else if derived_gaps && !current.is_empty() {
                output.push(SelectionSegment {
                    points: std::mem::take(&mut current),
                });
            }
        }
        if !current.is_empty() {
            output.push(SelectionSegment { points: current });
        }
    }
    Ok(LodSelection {
        segments: output,
        full_resolution: true,
        effective_bins: 1,
    })
}

fn valid_for_scales(point: &Point, scales: &AxisScales) -> bool {
    (scales.x() != AxisScale::Log10 || point.x > 0.0)
        && (scales.y() != AxisScale::Log10 || point.y > 0.0)
}

fn append_summary_candidates(candidates: &mut Vec<LodPoint>, summary: Summary) {
    candidates.push(to_lod_point(summary.first));
    candidates.push(to_lod_point(summary.min_y));
    candidates.push(to_lod_point(summary.max_y));
    candidates.push(to_lod_point(summary.last));
}

fn append_boundary_duplicates(
    candidates: &mut Vec<LodPoint>,
    points: &[Point],
    segment: &LogicalSegment,
    boundary: f64,
) -> Result<(), SceneError> {
    let start = lower_bound(points, segment, boundary);
    let end = upper_bound(points, segment, boundary);
    if start >= end || points[start].x != boundary {
        return Ok(());
    }
    candidates
        .try_reserve(end - start)
        .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
    candidates.extend(points[start..end].iter().map(|point| LodPoint {
        source: point.source,
        x: point.x,
        y: point.y,
    }));
    Ok(())
}

fn to_lod_point(point: PointRef) -> LodPoint {
    LodPoint {
        source: point.source,
        x: point.x,
        y: point.y,
    }
}

fn lower_bound(points: &[Point], segment: &LogicalSegment, value: f64) -> usize {
    let mut left = segment.point_start;
    let mut right = segment.point_end;
    while left < right {
        let middle = left + (right - left) / 2;
        if points[middle].x < value {
            left = middle + 1;
        } else {
            right = middle;
        }
    }
    left
}

fn upper_bound(points: &[Point], segment: &LogicalSegment, value: f64) -> usize {
    let mut left = segment.point_start;
    let mut right = segment.point_end;
    while left < right {
        let middle = left + (right - left) / 2;
        if points[middle].x <= value {
            left = middle + 1;
        } else {
            right = middle;
        }
    }
    left
}

fn make_boundaries(q0: f64, q1: f64, bins: usize) -> Result<Vec<f64>, SceneError> {
    let count = bins
        .checked_add(1)
        .ok_or_else(|| SceneError::new(SceneErrorKind::CapacityExceeded))?;
    let mut boundaries = Vec::new();
    boundaries
        .try_reserve_exact(count)
        .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
    if q0 == q1 {
        boundaries.push(q0);
        boundaries.push(q1);
        return Ok(boundaries);
    }
    for index in 0..=bins {
        let boundary = match index {
            0 => q0,
            value if value == bins => q1,
            value => safe_interpolate(q0, q1, value, bins),
        };
        if boundaries
            .last()
            .is_none_or(|previous| *previous != boundary)
        {
            boundaries.push(boundary.clamp(q0, q1));
        }
    }
    if boundaries.last().is_none_or(|last| *last != q1) {
        boundaries.push(q1);
    }
    Ok(boundaries)
}

fn safe_interpolate(q0: f64, q1: f64, index: usize, bins: usize) -> f64 {
    let fraction = index as f64 / bins as f64;
    let mut value = q0 * (1.0 - fraction) + q1 * fraction;
    if !value.is_finite() {
        let difference = q1 - q0;
        if difference.is_finite() {
            value = q0 + difference * fraction;
        } else {
            value = q0 / bins as f64 * (bins - index) as f64 + q1 / bins as f64 * index as f64;
        }
    }
    if value < q0 {
        q0
    } else if value > q1 {
        q1
    } else {
        value
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::data::{DataEpoch, SeriesInput, SeriesStorage, Topology};

    fn viewport() -> Viewport {
        Viewport::from_bounds(0.0, 10.0, -100.0, 100.0).expect("view")
    }

    #[test]
    fn duplicate_boundary_runs_are_whole_and_source_ordered() {
        let mut x = vec![0.0];
        x.extend(std::iter::repeat_n(1.0, 10));
        x.push(2.0);
        let y: Vec<_> = (0..x.len()).map(|value| value as f64).collect();
        let series = SeriesStorage::from_normalized(
            SeriesInput::from_owned_xy(Topology::MonotonicX, x.to_vec(), y, None)
                .expect("input")
                .into_normalized(),
            DataEpoch(1),
            crate::data::ChunkRevision(1),
        )
        .expect("storage");
        let selection = select_monotonic(
            &series,
            &Viewport::from_bounds(0.0, 2.0, -100.0, 100.0).expect("view"),
            &AxisScales::new(AxisScale::Linear, AxisScale::Linear),
            2,
        )
        .expect("selection");
        assert_eq!(selection.effective_bins, 2);
        let segment = &series.segments()[0];
        assert_eq!(lower_bound(series.points(), segment, 1.0), 1);
        assert_eq!(upper_bound(series.points(), segment, 1.0), 11);
        let duplicate_sources: Vec<_> = selection.segments[0]
            .points
            .iter()
            .map(|point| point.source)
            .filter(|source| (1..11).contains(source))
            .collect();
        assert_eq!(duplicate_sources, (1..11).collect::<Vec<_>>());
    }

    #[test]
    fn extreme_boundaries_remain_finite_and_deterministic() {
        let boundaries = make_boundaries(-f64::MAX, f64::MAX, 17).expect("boundaries");
        assert_eq!(boundaries.first().copied(), Some(-f64::MAX));
        assert_eq!(boundaries.last().copied(), Some(f64::MAX));
        assert!(boundaries.iter().all(|value| value.is_finite()));
        assert!(boundaries.windows(2).all(|pair| pair[0] <= pair[1]));
    }

    #[test]
    fn collapsed_and_degenerate_boundaries_are_deterministic() {
        let next = f64::from_bits(1.0_f64.to_bits() + 1);
        let collapsed = make_boundaries(1.0, next, 1024).expect("boundaries");
        assert!(collapsed.len() <= 3);
        assert_eq!(collapsed.first().copied(), Some(1.0));
        assert_eq!(collapsed.last().copied(), Some(next));
        let degenerate = make_boundaries(5.0, 5.0, 8).expect("degenerate boundary");
        assert_eq!(degenerate, vec![5.0, 5.0]);
    }

    #[test]
    fn direct_and_indexed_selection_match_fixed_generated_cases() {
        for case in 0..8usize {
            let count = 320 + case * 37;
            let x: Vec<_> = (0..count).map(|value| value as f64).collect();
            let y: Vec<_> = (0..count)
                .map(|value| ((value * 31 + case * 7) % 113) as f64 - 50.0)
                .collect();
            let series = SeriesStorage::from_normalized(
                SeriesInput::from_owned_xy(Topology::MonotonicX, x, y, None)
                    .expect("input")
                    .into_normalized(),
                DataEpoch(1),
                crate::data::ChunkRevision(1),
            )
            .expect("storage");
            let view =
                Viewport::from_bounds(0.0, (count - 1) as f64, -60.0, 60.0).expect("viewport");
            let bins = 7;
            let selection = select_monotonic(
                &series,
                &view,
                &AxisScales::new(AxisScale::Linear, AxisScale::Linear),
                bins,
            )
            .expect("selection");
            let boundaries = make_boundaries(0.0, (count - 1) as f64, bins).expect("bins");
            let segment = &series.segments()[0];
            let mut expected = Vec::new();
            for bin in 0..boundaries.len() - 1 {
                let start = lower_bound(series.points(), segment, boundaries[bin]);
                let end = if bin + 1 == boundaries.len() - 1 {
                    upper_bound(series.points(), segment, boundaries[bin + 1])
                } else {
                    lower_bound(series.points(), segment, boundaries[bin + 1])
                };
                if start == end {
                    continue;
                }
                let range = &series.points()[start..end];
                expected.push(range.first().expect("first").source);
                expected.push(
                    range
                        .iter()
                        .min_by(|left, right| {
                            left.y
                                .total_cmp(&right.y)
                                .then(left.source.cmp(&right.source))
                        })
                        .expect("minimum")
                        .source,
                );
                expected.push(
                    range
                        .iter()
                        .max_by(|left, right| {
                            left.y
                                .total_cmp(&right.y)
                                .then(right.source.cmp(&left.source))
                        })
                        .expect("maximum")
                        .source,
                );
                expected.push(range.last().expect("last").source);
            }
            expected.sort_unstable();
            expected.dedup();
            let mut actual: Vec<_> = selection.segments[0]
                .points
                .iter()
                .map(|point| point.source)
                .collect();
            actual.sort_unstable();
            assert_eq!(actual, expected, "case {case}");
        }
    }

    #[test]
    fn gaps_are_never_connected_and_log_selection_splits_derived_gaps() {
        let x = vec![1.0, 2.0, 3.0, f64::NAN, 4.0, 5.0, 6.0];
        let y = vec![1.0, 2.0, 3.0, f64::NAN, 4.0, -1.0, 6.0];
        let series = SeriesStorage::from_normalized(
            SeriesInput::from_owned_xy(Topology::MonotonicX, x, y, Some(vec![0..3, 4..7]))
                .expect("input")
                .into_normalized(),
            DataEpoch(1),
            crate::data::ChunkRevision(1),
        )
        .expect("storage");
        let view = Viewport::from_bounds(1.0, 6.0, -2.0, 7.0).expect("viewport");
        let linear = select_monotonic(
            &series,
            &view,
            &AxisScales::new(AxisScale::Linear, AxisScale::Linear),
            8,
        )
        .expect("linear selection");
        assert_eq!(linear.segments.len(), 2);
        let log = select_monotonic(
            &series,
            &Viewport::from_bounds(1.0, 6.0, 0.1, 7.0).expect("log viewport"),
            &AxisScales::new(AxisScale::Log10, AxisScale::Log10),
            8,
        )
        .expect("log selection");
        assert_eq!(log.segments.len(), 3);
        assert!(log.full_resolution);
    }
}
