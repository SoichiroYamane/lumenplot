use std::collections::BTreeMap;
use std::sync::Arc;

use crate::data::SeriesStorage;
use crate::error::{SceneError, SceneErrorKind};
use crate::text::{PlotLayout, RetainedAnnotation};

use super::ids::SeriesId;
use super::revision::{ComponentRevision, SceneRevision};
use super::snapshot::SceneSnapshot;
use super::transaction::SceneTransaction;

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct AxisRange {
    min: f64,
    max: f64,
}

impl AxisRange {
    pub(crate) fn new(min: f64, max: f64) -> Result<Self, SceneError> {
        if !min.is_finite() || !max.is_finite() || min >= max {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }
        Ok(Self { min, max })
    }

    pub(crate) fn min(self) -> f64 {
        self.min
    }

    pub(crate) fn max(self) -> f64 {
        self.max
    }
}

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
#[non_exhaustive]
pub(crate) enum AxisScale {
    Linear,
    Log10,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct Viewport {
    x: AxisRange,
    y: AxisRange,
}

impl Viewport {
    pub(crate) fn new(x: AxisRange, y: AxisRange) -> Self {
        Self { x, y }
    }

    pub(crate) fn from_bounds(
        x_min: f64,
        x_max: f64,
        y_min: f64,
        y_max: f64,
    ) -> Result<Self, SceneError> {
        Ok(Self::new(
            AxisRange::new(x_min, x_max)?,
            AxisRange::new(y_min, y_max)?,
        ))
    }

    pub(crate) fn x(self) -> AxisRange {
        self.x
    }

    pub(crate) fn y(self) -> AxisRange {
        self.y
    }
}

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) struct AxisScales {
    x: AxisScale,
    y: AxisScale,
}

impl AxisScales {
    pub(crate) fn new(x: AxisScale, y: AxisScale) -> Self {
        Self { x, y }
    }

    pub(crate) fn x(self) -> AxisScale {
        self.x
    }

    pub(crate) fn y(self) -> AxisScale {
        self.y
    }

    pub(crate) fn validate(self, viewport: &Viewport) -> Result<(), SceneError> {
        if (self.x == AxisScale::Log10 && (viewport.x.min() <= 0.0 || viewport.x.max() <= 0.0))
            || (self.y == AxisScale::Log10 && (viewport.y.min() <= 0.0 || viewport.y.max() <= 0.0))
        {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub(crate) struct AnnotationId(pub(crate) u64);

#[derive(Debug)]
pub(crate) struct SceneState {
    revision: SceneRevision,
    canonical_view: Viewport,
    viewport: Viewport,
    scales: AxisScales,
    data_revision: ComponentRevision,
    view_revision: ComponentRevision,
    style_revision: ComponentRevision,
    font_revision: ComponentRevision,
    layout_revision: ComponentRevision,
    plot_layout: Arc<PlotLayout>,
    annotation_revision: ComponentRevision,
    grid_visible: bool,
    grid_revision: ComponentRevision,
    series: BTreeMap<SeriesId, Arc<SeriesStorage>>,
    annotations: BTreeMap<AnnotationId, RetainedAnnotation>,
}

pub(crate) struct PublishValues {
    canonical_view: Viewport,
    viewport: Viewport,
    scales: AxisScales,
    revision: SceneRevision,
    data_changed: bool,
    view_changed: bool,
    annotation_changed: bool,
    grid_visible: bool,
    grid_changed: bool,
    series: BTreeMap<SeriesId, Arc<SeriesStorage>>,
    annotations: BTreeMap<AnnotationId, RetainedAnnotation>,
}

impl PublishValues {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn new(
        canonical_view: Viewport,
        viewport: Viewport,
        scales: AxisScales,
        revision: SceneRevision,
        data_changed: bool,
        view_changed: bool,
        annotation_changed: bool,
        grid_visible: bool,
        grid_changed: bool,
        series: BTreeMap<SeriesId, Arc<SeriesStorage>>,
        annotations: BTreeMap<AnnotationId, RetainedAnnotation>,
    ) -> Self {
        Self {
            canonical_view,
            viewport,
            scales,
            revision,
            data_changed,
            view_changed,
            annotation_changed,
            grid_visible,
            grid_changed,
            series,
            annotations,
        }
    }
}

impl SceneState {
    pub(crate) fn new(canonical_view: Viewport, scales: AxisScales) -> Result<Self, SceneError> {
        scales.validate(&canonical_view)?;
        Ok(Self {
            revision: SceneRevision(0),
            canonical_view,
            viewport: canonical_view,
            scales,
            data_revision: ComponentRevision(0),
            view_revision: ComponentRevision(0),
            style_revision: ComponentRevision(0),
            font_revision: ComponentRevision(0),
            layout_revision: ComponentRevision(0),
            plot_layout: Arc::new(PlotLayout::fixture()?),
            annotation_revision: ComponentRevision(0),
            grid_visible: true,
            grid_revision: ComponentRevision(0),
            series: BTreeMap::new(),
            annotations: BTreeMap::new(),
        })
    }

    pub(crate) fn publish(base: &Self, values: PublishValues) -> Result<Self, SceneError> {
        let PublishValues {
            canonical_view,
            viewport,
            scales,
            revision,
            data_changed,
            view_changed,
            annotation_changed,
            grid_visible,
            grid_changed,
            series,
            annotations,
        } = values;
        let data_revision = if data_changed {
            base.data_revision
                .checked_next()
                .ok_or_else(|| SceneError::new(SceneErrorKind::RevisionExhausted))?
        } else {
            base.data_revision
        };
        let view_revision = if view_changed {
            base.view_revision
                .checked_next()
                .ok_or_else(|| SceneError::new(SceneErrorKind::RevisionExhausted))?
        } else {
            base.view_revision
        };
        let layout_changed = data_changed || view_changed;
        let layout_revision = if layout_changed {
            base.layout_revision
                .checked_next()
                .ok_or_else(|| SceneError::new(SceneErrorKind::RevisionExhausted))?
        } else {
            base.layout_revision
        };
        let annotation_revision = if annotation_changed {
            base.annotation_revision
                .checked_next()
                .ok_or_else(|| SceneError::new(SceneErrorKind::RevisionExhausted))?
        } else {
            base.annotation_revision
        };
        let grid_revision = if grid_changed {
            base.grid_revision
                .checked_next()
                .ok_or_else(|| SceneError::new(SceneErrorKind::RevisionExhausted))?
        } else {
            base.grid_revision
        };
        let plot_layout = if layout_changed {
            Arc::new(base.plot_layout.with_layout_revision(layout_revision.0))
        } else {
            base.plot_layout.clone()
        };
        Ok(Self {
            revision,
            canonical_view,
            viewport,
            scales,
            data_revision,
            view_revision,
            style_revision: base.style_revision,
            font_revision: base.font_revision,
            layout_revision,
            plot_layout,
            annotation_revision,
            grid_visible,
            grid_revision,
            series,
            annotations,
        })
    }

    pub(crate) fn revision(&self) -> SceneRevision {
        self.revision
    }

    pub(crate) fn canonical_view(&self) -> Viewport {
        self.canonical_view
    }

    pub(crate) fn viewport(&self) -> Viewport {
        self.viewport
    }

    pub(crate) fn scales(&self) -> AxisScales {
        self.scales
    }

    pub(crate) fn font_revision(&self) -> ComponentRevision {
        self.font_revision
    }

    pub(crate) fn layout_revision(&self) -> ComponentRevision {
        self.layout_revision
    }

    pub(crate) fn plot_layout(&self) -> &Arc<PlotLayout> {
        &self.plot_layout
    }

    pub(crate) fn series(&self, id: SeriesId) -> Option<&Arc<SeriesStorage>> {
        self.series.get(&id)
    }

    pub(crate) fn series_map(&self) -> &BTreeMap<SeriesId, Arc<SeriesStorage>> {
        &self.series
    }

    pub(crate) fn annotation_revision(&self) -> ComponentRevision {
        self.annotation_revision
    }

    pub(crate) fn grid_visible(&self) -> bool {
        self.grid_visible
    }

    pub(crate) fn grid_revision(&self) -> ComponentRevision {
        self.grid_revision
    }

    pub(crate) fn annotation(&self, id: AnnotationId) -> Option<&RetainedAnnotation> {
        self.annotations.get(&id)
    }

    pub(crate) fn annotations_map(&self) -> &BTreeMap<AnnotationId, RetainedAnnotation> {
        &self.annotations
    }

    #[cfg(test)]
    pub(crate) fn component_revisions(&self) -> (ComponentRevision, ComponentRevision) {
        (self.data_revision, self.view_revision)
    }
}

#[derive(Debug)]
pub(crate) struct PlotScene {
    pub(crate) state: Arc<SceneState>,
    pub(crate) next_series_id: u64,
    pub(crate) next_epoch: u64,
    pub(crate) next_annotation_id: u64,
}

impl PlotScene {
    pub(crate) fn new(canonical_view: Viewport, scales: AxisScales) -> Result<Self, SceneError> {
        Ok(Self {
            state: Arc::new(SceneState::new(canonical_view, scales)?),
            next_series_id: 1,
            next_epoch: 1,
            next_annotation_id: 1,
        })
    }

    pub(crate) fn transaction(&mut self) -> SceneTransaction<'_> {
        SceneTransaction::new(self)
    }

    pub(crate) fn snapshot(&self) -> SceneSnapshot {
        SceneSnapshot::new(self.state.clone())
    }

    pub(crate) fn revision(&self) -> SceneRevision {
        self.state.revision()
    }

    #[cfg(test)]
    pub(crate) fn set_revision_for_test(&mut self, revision: SceneRevision) {
        Arc::get_mut(&mut self.state)
            .expect("test scene has no snapshots")
            .revision = revision;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn view() -> Viewport {
        Viewport::from_bounds(0.0, 10.0, 0.0, 10.0).expect("view")
    }

    fn scales() -> AxisScales {
        AxisScales::new(AxisScale::Linear, AxisScale::Linear)
    }

    fn unchanged_values(base: &SceneState, revision: SceneRevision) -> PublishValues {
        PublishValues::new(
            base.canonical_view(),
            base.viewport(),
            base.scales(),
            revision,
            false,
            false,
            false,
            base.grid_visible(),
            false,
            base.series_map().clone(),
            base.annotations_map().clone(),
        )
    }

    #[test]
    fn grid_default_is_visible_with_zero_revision() {
        let state = SceneState::new(view(), scales()).expect("scene state");
        assert!(state.grid_visible());
        assert_eq!(state.grid_revision(), ComponentRevision(0));
        // The default reproduces current rendering bit-for-bit: every other
        // component revision starts at zero.
        assert_eq!(state.layout_revision(), ComponentRevision(0));
        assert_eq!(state.annotation_revision(), ComponentRevision(0));
        assert_eq!(
            state.component_revisions(),
            (ComponentRevision(0), ComponentRevision(0))
        );
    }

    #[test]
    fn grid_only_publish_bumps_grid_revision_only() {
        let base = SceneState::new(view(), scales()).expect("scene state");
        let before_layout = base.plot_layout().clone();
        let mut values = unchanged_values(&base, SceneRevision(1));
        values.grid_visible = false;
        values.grid_changed = true;
        let next = SceneState::publish(&base, values).expect("publish");
        assert!(!next.grid_visible());
        assert_eq!(next.grid_revision(), ComponentRevision(1));
        // Grid-only publish leaves every other component revision put.
        assert_eq!(next.layout_revision(), ComponentRevision(0));
        assert_eq!(next.annotation_revision(), ComponentRevision(0));
        assert_eq!(
            next.component_revisions(),
            (ComponentRevision(0), ComponentRevision(0))
        );
        // The retained layout carrier is shared, never re-stamped.
        assert!(Arc::ptr_eq(&before_layout, next.plot_layout()));
    }

    #[test]
    fn publish_without_grid_change_keeps_grid_state() {
        let base = SceneState::new(view(), scales()).expect("scene state");
        let next =
            SceneState::publish(&base, unchanged_values(&base, SceneRevision(1))).expect("publish");
        assert!(next.grid_visible());
        assert_eq!(next.grid_revision(), ComponentRevision(0));
        assert_eq!(next.layout_revision(), ComponentRevision(0));
    }

    #[test]
    fn snapshot_wrapper_exposes_grid_flag_without_struct_change() {
        let plot = PlotScene::new(view(), scales()).expect("scene");
        let snapshot = plot.snapshot();
        assert!(snapshot.state.grid_visible());
        assert_eq!(snapshot.state.grid_revision(), ComponentRevision(0));
        assert!(Arc::ptr_eq(&plot.state, &snapshot.state));
    }
}
