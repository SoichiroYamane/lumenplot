use std::collections::BTreeMap;
use std::sync::Arc;

use crate::data::SeriesStorage;
use crate::error::{SceneError, SceneErrorKind};

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
    annotation_revision: ComponentRevision,
    series: BTreeMap<SeriesId, Arc<SeriesStorage>>,
}

pub(crate) struct PublishValues {
    canonical_view: Viewport,
    viewport: Viewport,
    scales: AxisScales,
    revision: SceneRevision,
    data_changed: bool,
    view_changed: bool,
    series: BTreeMap<SeriesId, Arc<SeriesStorage>>,
}

impl PublishValues {
    pub(crate) fn new(
        canonical_view: Viewport,
        viewport: Viewport,
        scales: AxisScales,
        revision: SceneRevision,
        data_changed: bool,
        view_changed: bool,
        series: BTreeMap<SeriesId, Arc<SeriesStorage>>,
    ) -> Self {
        Self {
            canonical_view,
            viewport,
            scales,
            revision,
            data_changed,
            view_changed,
            series,
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
            annotation_revision: ComponentRevision(0),
            series: BTreeMap::new(),
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
            series,
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
        Ok(Self {
            revision,
            canonical_view,
            viewport,
            scales,
            data_revision,
            view_revision,
            style_revision: base.style_revision,
            font_revision: base.font_revision,
            layout_revision: base.layout_revision,
            annotation_revision: base.annotation_revision,
            series,
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

    pub(crate) fn series(&self, id: SeriesId) -> Option<&Arc<SeriesStorage>> {
        self.series.get(&id)
    }

    pub(crate) fn series_map(&self) -> &BTreeMap<SeriesId, Arc<SeriesStorage>> {
        &self.series
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
}

impl PlotScene {
    pub(crate) fn new(canonical_view: Viewport, scales: AxisScales) -> Result<Self, SceneError> {
        Ok(Self {
            state: Arc::new(SceneState::new(canonical_view, scales)?),
            next_series_id: 1,
            next_epoch: 1,
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
