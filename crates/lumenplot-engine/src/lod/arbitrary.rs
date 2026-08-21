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
            let in_view = point.x >= x_range.min()
                && point.x <= x_range.max()
                && point.y >= y_range.min()
                && point.y <= y_range.max();
            let in_scale_domain = (scales.x() != AxisScale::Log10 || point.x > 0.0)
                && (scales.y() != AxisScale::Log10 || point.y > 0.0);
            if in_view && in_scale_domain {
                current.push(LodPoint {
                    source: point.source,
                    x: point.x,
                    y: point.y,
                });
            } else if (scales.x() == AxisScale::Log10 || scales.y() == AxisScale::Log10)
                && !current.is_empty()
            {
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
    fn arbitrary_selection_matches_bruteforce_order_and_culls_segments() {
        let input = SeriesInput::from_owned_xy(
            Topology::ArbitraryXY,
            vec![0.0, 2.0, 5.0, 8.0, f64::NAN, 20.0],
            vec![0.0, 3.0, -2.0, 4.0, f64::NAN, 2.0],
            Some(vec![0..4, 5..6]),
        )
        .expect("input");
        let series = SeriesStorage::from_normalized(
            input.into_normalized(),
            DataEpoch(1),
            crate::data::ChunkRevision(1),
        )
        .expect("storage");
        let viewport = Viewport::from_bounds(1.0, 9.0, -3.0, 5.0).expect("viewport");
        let scales = AxisScales::new(AxisScale::Linear, AxisScale::Linear);
        let selection = select_arbitrary(&series, &viewport, &scales).expect("selection");
        let actual: Vec<_> = selection
            .segments
            .iter()
            .flat_map(|segment| segment.points.iter().map(|point| point.source))
            .collect();
        let expected: Vec<_> = series
            .points()
            .iter()
            .filter(|point| point.x >= 1.0 && point.x <= 9.0 && point.y >= -3.0 && point.y <= 5.0)
            .map(|point| point.source)
            .collect();
        assert_eq!(actual, expected);
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
        assert_eq!(selection.segments[1].points[0].source, 2);
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
}
