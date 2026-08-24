use crate::data::{SeriesStorage, Topology};
use crate::error::{SceneError, SceneErrorKind};
use crate::scene::{AxisScale, AxisScales, Viewport};

use super::m4::{LodPoint, LodSelection, SelectionSegment};

pub(crate) fn select_arbitrary(
    series: &SeriesStorage,
    viewport: &Viewport,
    scales: &AxisScales,
) -> Result<LodSelection, SceneError> {
    if series.topology() != Topology::ArbitraryXY {
        return Err(SceneError::new(SceneErrorKind::TopologyViolation));
    }
    scales.validate(viewport)?;
    let x_range = viewport.x();
    let y_range = viewport.y();
    let derived_gaps = scales.x() == AxisScale::Log10 || scales.y() == AxisScale::Log10;
    let mut output = Vec::new();
    output
        .try_reserve(series.segments().len())
        .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;

    for segment in series.segments() {
        if !segment
            .bounds
            .intersects(x_range.min(), x_range.max(), y_range.min(), y_range.max())
        {
            continue;
        }
        let mut current = Vec::new();
        current
            .try_reserve(segment.point_end - segment.point_start)
            .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
        for point in &series.points()[segment.point_start..segment.point_end] {
            let in_scale_domain = (scales.x() != AxisScale::Log10 || point.x > 0.0)
                && (scales.y() != AxisScale::Log10 || point.y > 0.0);
            if in_scale_domain {
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::data::{DataEpoch, SeriesInput, SeriesStorage};

    #[test]
    fn arbitrary_selection_uses_segment_bounds_and_preserves_full_runs() {
        let input = SeriesInput::from_owned_xy(
            Topology::ArbitraryXY,
            vec![-1.0, 1.0, 3.0, f64::NAN, 20.0],
            vec![0.0, 0.0, 0.0, f64::NAN, 2.0],
            Some(vec![0..3, 4..5]),
        )
        .expect("input");
        let series = SeriesStorage::from_normalized(
            input.into_normalized(),
            DataEpoch(1),
            crate::data::ChunkRevision(1),
        )
        .expect("storage");
        let viewport = Viewport::from_bounds(0.0, 2.0, -1.0, 1.0).expect("viewport");
        let scales = AxisScales::new(AxisScale::Linear, AxisScale::Linear);
        let selection = select_arbitrary(&series, &viewport, &scales).expect("selection");
        let actual: Vec<_> = selection
            .segments
            .iter()
            .flat_map(|segment| segment.points.iter().map(|point| point.source))
            .collect();
        assert_eq!(actual, vec![0, 1, 2]);
        assert_eq!(selection.segments.len(), 1);
    }

    #[test]
    fn alternating_out_of_view_points_are_not_reconnected_after_filtering() {
        let input = SeriesInput::from_owned_xy(
            Topology::ArbitraryXY,
            vec![-1.0, 1.0, -1.0, 1.0],
            vec![0.0, 0.0, 1.0, 1.0],
            None,
        )
        .expect("input");
        let series = SeriesStorage::from_normalized(
            input.into_normalized(),
            DataEpoch(1),
            crate::data::ChunkRevision(1),
        )
        .expect("storage");
        let selection = select_arbitrary(
            &series,
            &Viewport::from_bounds(0.0, 2.0, -1.0, 2.0).expect("viewport"),
            &AxisScales::new(AxisScale::Linear, AxisScale::Linear),
        )
        .expect("selection");
        let sources: Vec<_> = selection.segments[0]
            .points
            .iter()
            .map(|point| point.source)
            .collect();
        assert_eq!(sources, vec![0, 1, 2, 3]);
    }

    #[test]
    fn disjoint_segments_are_culled_but_crossing_segments_are_retained() {
        let input = SeriesInput::from_owned_xy(
            Topology::ArbitraryXY,
            vec![-10.0, -9.0, f64::NAN, -1.0, 3.0],
            vec![0.0, 0.0, f64::NAN, 1.0, 1.0],
            Some(vec![0..2, 3..5]),
        )
        .expect("input");
        let series = SeriesStorage::from_normalized(
            input.into_normalized(),
            DataEpoch(1),
            crate::data::ChunkRevision(1),
        )
        .expect("storage");
        let selection = select_arbitrary(
            &series,
            &Viewport::from_bounds(0.0, 2.0, 0.0, 2.0).expect("viewport"),
            &AxisScales::new(AxisScale::Linear, AxisScale::Linear),
        )
        .expect("selection");
        assert_eq!(selection.segments.len(), 1);
        let sources: Vec<_> = selection.segments[0]
            .points
            .iter()
            .map(|point| point.source)
            .collect();
        assert_eq!(sources, vec![3, 4]);
    }

    #[test]
    fn gaps_and_chunk_cuts_preserve_logical_segment_continuity() {
        let chunk_point_limit = 65_536;
        let count = chunk_point_limit + 3;
        let mut x: Vec<_> = (0..count).map(|value| value as f64).collect();
        let mut y = x.clone();
        x.extend([f64::NAN, f64::NAN]);
        y.extend([f64::NAN, f64::NAN]);
        x.extend([
            count as f64 + 10.0,
            count as f64 + 11.0,
            count as f64 + 12.0,
        ]);
        y.extend([0.0, 1.0, 2.0]);
        x.extend([f64::NAN, f64::NAN]);
        y.extend([f64::NAN, f64::NAN]);
        x.extend([-100.0, -99.0]);
        y.extend([0.0, 1.0]);
        let input = SeriesInput::from_owned_xy(
            Topology::ArbitraryXY,
            x,
            y,
            Some(vec![0..count, count + 2..count + 5, count + 7..count + 9]),
        )
        .expect("input");
        let series = SeriesStorage::from_normalized(
            input.into_normalized(),
            DataEpoch(1),
            crate::data::ChunkRevision(1),
        )
        .expect("storage");
        assert_eq!(series.chunks().len(), 2);
        let selection = select_arbitrary(
            &series,
            &Viewport::from_bounds(0.0, count as f64 + 12.0, -1.0, count as f64 + 1.0)
                .expect("viewport"),
            &AxisScales::new(AxisScale::Linear, AxisScale::Linear),
        )
        .expect("selection");
        assert_eq!(selection.segments.len(), 2);
        let sources: Vec<Vec<_>> = selection
            .segments
            .iter()
            .map(|segment| segment.points.iter().map(|point| point.source).collect())
            .collect();
        assert_eq!(sources[0], (0..count as u64).collect::<Vec<_>>());
        assert_eq!(
            sources[1],
            ((count + 2) as u64..(count + 5) as u64).collect::<Vec<_>>()
        );
    }

    fn segment_bounds_model(
        series: &SeriesStorage,
        viewport: &Viewport,
        scales: &AxisScales,
    ) -> Vec<Vec<u64>> {
        let x_range = viewport.x();
        let y_range = viewport.y();
        series
            .segments()
            .iter()
            .filter_map(|segment| {
                if !segment.bounds.intersects(
                    x_range.min(),
                    x_range.max(),
                    y_range.min(),
                    y_range.max(),
                ) {
                    return None;
                }
                let run: Vec<_> = series.points()[segment.point_start..segment.point_end]
                    .iter()
                    .filter(|point| {
                        (scales.x() != AxisScale::Log10 || point.x > 0.0)
                            && (scales.y() != AxisScale::Log10 || point.y > 0.0)
                    })
                    .map(|point| point.source)
                    .collect();
                (!run.is_empty()).then_some(run)
            })
            .collect()
    }

    #[test]
    fn generated_oracle_compares_bounds_decisions_and_full_runs() {
        for case in 0..32usize {
            let source_len = 17 + case % 11;
            let x: Vec<_> = (0..source_len)
                .map(|index| ((case * 13 + index * 7) % 31) as f64 - 15.0)
                .collect();
            let y: Vec<_> = (0..source_len)
                .map(|index| ((case * 5 + index * 11) % 29) as f64 - 14.0)
                .collect();
            let segments = vec![0..5, 7..12, 14..source_len - case % 3];
            let series = SeriesStorage::from_normalized(
                SeriesInput::from_owned_xy(Topology::ArbitraryXY, x, y, Some(segments))
                    .expect("input")
                    .into_normalized(),
                DataEpoch(1),
                crate::data::ChunkRevision(1),
            )
            .expect("storage");
            let x_min = (case * 17 % 23) as f64 - 14.0;
            let y_min = (case * 19 % 23) as f64 - 14.0;
            let viewport = Viewport::from_bounds(
                x_min,
                x_min + 4.0 + (case % 5) as f64,
                y_min,
                y_min + 5.0 + (case % 4) as f64,
            )
            .expect("viewport");
            let scales = AxisScales::new(AxisScale::Linear, AxisScale::Linear);
            let selection = select_arbitrary(&series, &viewport, &scales).expect("selection");
            let actual: Vec<Vec<_>> = selection
                .segments
                .iter()
                .map(|segment| segment.points.iter().map(|point| point.source).collect())
                .collect();
            assert_eq!(
                actual,
                segment_bounds_model(&series, &viewport, &scales),
                "case {case}"
            );
        }
    }

    #[test]
    fn log_domain_values_split_output_segments() {
        let input = SeriesInput::from_owned_xy(
            Topology::ArbitraryXY,
            vec![1.0, 2.0, 3.0, 4.0],
            vec![1.0, -1.0, 2.0, 3.0],
            None,
        )
        .expect("input");
        let series = SeriesStorage::from_normalized(
            input.into_normalized(),
            DataEpoch(1),
            crate::data::ChunkRevision(1),
        )
        .expect("storage");
        let viewport = Viewport::from_bounds(1.0, 4.0, 0.1, 4.0).expect("viewport");
        let selection = select_arbitrary(
            &series,
            &viewport,
            &AxisScales::new(AxisScale::Log10, AxisScale::Log10),
        )
        .expect("selection");
        assert_eq!(selection.segments.len(), 2);
        assert_eq!(selection.segments[0].points[0].source, 0);
        let sources: Vec<_> = selection.segments[1]
            .points
            .iter()
            .map(|point| point.source)
            .collect();
        assert_eq!(sources, vec![2, 3]);
    }

    #[test]
    fn arbitrary_topology_retains_source_order() {
        let input = SeriesInput::from_owned_xy(
            Topology::ArbitraryXY,
            vec![3.0, 1.0, 2.0],
            vec![3.0, 1.0, 2.0],
            None,
        )
        .expect("input");
        let series = SeriesStorage::from_normalized(
            input.into_normalized(),
            DataEpoch(1),
            crate::data::ChunkRevision(1),
        )
        .expect("storage");
        let viewport = Viewport::from_bounds(0.0, 4.0, 0.0, 4.0).expect("viewport");
        let selection = select_arbitrary(
            &series,
            &viewport,
            &AxisScales::new(AxisScale::Linear, AxisScale::Linear),
        )
        .expect("selection");
        let sources: Vec<_> = selection.segments[0]
            .points
            .iter()
            .map(|point| point.source)
            .collect();
        assert_eq!(sources, vec![0, 1, 2]);
    }

    #[test]
    fn arbitrary_selection_is_invariant_under_source_permutation() {
        // LP-LOD-006: reordering the same logical samples must not change
        // which geometry is retained. Each retained run keeps its own
        // relative order; runs that fall outside the viewport are culled in
        // every permutation.
        // Logical content: three runs, the last outside the viewport.
        let runs: [&[(f64, f64)]; 3] = [
            &[(3.0, 30.0), (1.0, 10.0)],
            &[(2.0, -20.0), (5.0, 50.0), (4.0, 40.0)],
            &[(-9.0, -9.0), (-8.0, -8.0)],
        ];
        let build = |orders: [&[usize]; 3]| {
            let mut x = Vec::new();
            let mut y = Vec::new();
            let mut valid_segments = Vec::new();
            for (run, order) in runs.iter().zip(orders) {
                if !valid_segments.is_empty() {
                    // One uncovered gap slot between runs keeps them
                    // structurally separate.
                    x.push(f64::NAN);
                    y.push(f64::NAN);
                }
                let start = x.len();
                for &source_slot in order {
                    let (px, py) = run[source_slot];
                    x.push(px);
                    y.push(py);
                }
                valid_segments.push(start..x.len());
            }
            SeriesStorage::from_normalized(
                SeriesInput::from_owned_xy(Topology::ArbitraryXY, x, y, Some(valid_segments))
                    .expect("input")
                    .into_normalized(),
                DataEpoch(1),
                crate::data::ChunkRevision(1),
            )
            .expect("storage")
        };
        let identity = build([&[0usize, 1][..], &[0, 1, 2], &[0, 1]]);
        let shuffled = build([&[1usize, 0][..], &[2, 0, 1], &[1, 0]]);
        let viewport = Viewport::from_bounds(0.0, 6.0, -25.0, 55.0).expect("viewport");
        let scales = AxisScales::new(AxisScale::Linear, AxisScale::Linear);
        let select = |series: &SeriesStorage| {
            let selection = crate::lod::arbitrary::select_arbitrary(series, &viewport, &scales)
                .expect("selection");
            // Compare geometry sets with within-run order normalized: a
            // permutation may legitimately store a run in a different
            // internal order, but the retained point multiset must match.
            let mut runs: Vec<Vec<(u64, u64)>> = selection
                .segments
                .iter()
                .map(|segment| {
                    let mut points: Vec<(u64, u64)> = segment
                        .points
                        .iter()
                        .map(|point| (point.x.to_bits(), point.y.to_bits()))
                        .collect();
                    points.sort();
                    points
                })
                .collect();
            runs.sort();
            runs
        };
        assert_eq!(select(&identity), select(&shuffled));
        // Both permutations retain exactly the two in-view runs, in stored
        // order, and drop the out-of-view run entirely.
        let expected_geometry = vec![
            vec![
                (1.0_f64.to_bits(), 10.0_f64.to_bits()),
                (3.0_f64.to_bits(), 30.0_f64.to_bits()),
            ],
            vec![
                (2.0_f64.to_bits(), (-20.0_f64).to_bits()),
                (4.0_f64.to_bits(), 40.0_f64.to_bits()),
                (5.0_f64.to_bits(), 50.0_f64.to_bits()),
            ],
        ];
        assert_eq!(select(&identity), expected_geometry);
    }

    #[test]
    fn culling_is_exact_at_viewport_edges_and_epsilon_outside() {
        // LP-LOD-006 negative/positive boundary fixture: a run touching the
        // viewport only at an edge intersects inclusively and stays; a run
        // just outside by one ULP of x is culled completely.
        let next_after_zero = f64::from_bits(0.0_f64.to_bits() + 1);
        let x = vec![0.0, 1.0, f64::NAN, -next_after_zero, -1.0];
        let y = vec![2.0, 3.0, f64::NAN, 0.0, 1.0];
        let series = SeriesStorage::from_normalized(
            SeriesInput::from_owned_xy(Topology::ArbitraryXY, x, y, Some(vec![0..2, 3..5]))
                .expect("input")
                .into_normalized(),
            DataEpoch(1),
            crate::data::ChunkRevision(1),
        )
        .expect("storage");
        let selection = crate::lod::arbitrary::select_arbitrary(
            &series,
            &Viewport::from_bounds(0.0, 2.0, -1.0, 4.0).expect("viewport"),
            &AxisScales::new(AxisScale::Linear, AxisScale::Linear),
        )
        .expect("selection");
        assert_eq!(selection.segments.len(), 1);
        let sources: Vec<_> = selection.segments[0]
            .points
            .iter()
            .map(|point| point.source)
            .collect();
        assert_eq!(sources, vec![0, 1]);
    }

    #[test]
    fn mixed_order_multi_segment_runs_keep_source_order() {
        // LP-LOD-006: neither gaps nor chunk cuts may sort or reconnect
        // arbitrary-order runs; output equals stored source order per run.
        let count = 65_536;
        let first_run: Vec<f64> = (0..count)
            .map(|index| count as f64 - index as f64)
            .collect();
        let tail_x = vec![7.5, 1.5, 9.5];
        let tail_y = vec![70.0, 10.0, 90.0];
        let mut x = first_run.clone();
        let mut y: Vec<f64> = first_run.iter().rev().copied().collect();
        x.extend([f64::NAN]);
        y.extend([f64::NAN]);
        x.extend(tail_x);
        y.extend(tail_y);
        let series = SeriesStorage::from_normalized(
            SeriesInput::from_owned_xy(
                Topology::ArbitraryXY,
                x,
                y,
                Some(vec![0..count, count + 1..count + 4]),
            )
            .expect("input")
            .into_normalized(),
            DataEpoch(1),
            crate::data::ChunkRevision(1),
        )
        .expect("storage");
        let selection = crate::lod::arbitrary::select_arbitrary(
            &series,
            &Viewport::from_bounds(0.0, 10.0, -1.0, 100_000.0).expect("viewport"),
            &AxisScales::new(AxisScale::Linear, AxisScale::Linear),
        )
        .expect("selection");
        assert_eq!(selection.segments.len(), 2);
        let tail_sources: Vec<_> = selection.segments[1]
            .points
            .iter()
            .map(|point| point.source)
            .collect();
        assert_eq!(
            tail_sources,
            vec![(count + 1) as u64, (count + 2) as u64, (count + 3) as u64]
        );
        let tail_pairs: Vec<_> = selection.segments[1]
            .points
            .iter()
            .map(|point| (point.x, point.y))
            .collect();
        assert_eq!(tail_pairs, vec![(7.5, 70.0), (1.5, 10.0), (9.5, 90.0)]);
        assert!(selection.full_resolution);
    }
}
