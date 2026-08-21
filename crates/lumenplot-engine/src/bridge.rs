use std::fmt;
use std::ops::Range;

use crate::data::{SeriesInput, Topology};
use crate::error::{self, SceneError as EngineSceneError};
use crate::scene::{
    AxisRange as EngineAxisRange, AxisScale as EngineAxisScale, AxisScales as EngineAxisScales,
    PlotScene as EnginePlotScene, SceneRevision as EngineSceneRevision,
    SceneSnapshot as EngineSceneSnapshot, SceneTransaction as EngineSceneTransaction,
    SeriesId as EngineSeriesId, Viewport as EngineViewport,
};

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum SceneErrorKind {
    InvalidInput,
    UnsupportedCapability,
    InvalidState,
    SeriesNotFound,
    TopologyViolation,
    NonFiniteCanonical,
    CapacityExceeded,
    AllocationFailed,
    IdentityExhausted,
    RevisionExhausted,
    Internal,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SceneError {
    inner: EngineSceneError,
}

impl SceneError {
    pub fn kind(&self) -> SceneErrorKind {
        match self.inner.kind() {
            error::SceneErrorKind::InvalidInput => SceneErrorKind::InvalidInput,
            error::SceneErrorKind::UnsupportedCapability => SceneErrorKind::UnsupportedCapability,
            error::SceneErrorKind::InvalidState => SceneErrorKind::InvalidState,
            error::SceneErrorKind::SeriesNotFound => SceneErrorKind::SeriesNotFound,
            error::SceneErrorKind::TopologyViolation => SceneErrorKind::TopologyViolation,
            error::SceneErrorKind::NonFiniteCanonical => SceneErrorKind::NonFiniteCanonical,
            error::SceneErrorKind::CapacityExceeded => SceneErrorKind::CapacityExceeded,
            error::SceneErrorKind::AllocationFailed => SceneErrorKind::AllocationFailed,
            error::SceneErrorKind::IdentityExhausted => SceneErrorKind::IdentityExhausted,
            error::SceneErrorKind::RevisionExhausted => SceneErrorKind::RevisionExhausted,
            error::SceneErrorKind::Internal => SceneErrorKind::Internal,
        }
    }

    pub fn message(&self) -> &str {
        self.inner.message()
    }
}

impl fmt::Display for SceneError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.message())
    }
}

impl std::error::Error for SceneError {}

impl From<EngineSceneError> for SceneError {
    fn from(inner: EngineSceneError) -> Self {
        Self { inner }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct AxisRange {
    inner: EngineAxisRange,
}

impl AxisRange {
    pub fn new(min: f64, max: f64) -> Result<Self, SceneError> {
        Ok(Self {
            inner: EngineAxisRange::new(min, max)?,
        })
    }

    pub fn min(self) -> f64 {
        self.inner.min()
    }

    pub fn max(self) -> f64 {
        self.inner.max()
    }
}

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
#[non_exhaustive]
pub enum AxisScale {
    Linear,
    Log10,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Viewport {
    inner: EngineViewport,
}

impl Viewport {
    pub fn new(x: AxisRange, y: AxisRange) -> Self {
        Self {
            inner: EngineViewport::new(x.inner, y.inner),
        }
    }

    pub fn from_bounds(x_min: f64, x_max: f64, y_min: f64, y_max: f64) -> Result<Self, SceneError> {
        Ok(Self {
            inner: EngineViewport::from_bounds(x_min, x_max, y_min, y_max)?,
        })
    }

    pub fn x(self) -> AxisRange {
        AxisRange {
            inner: self.inner.x(),
        }
    }

    pub fn y(self) -> AxisRange {
        AxisRange {
            inner: self.inner.y(),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct AxisScales {
    inner: EngineAxisScales,
}

impl AxisScales {
    pub fn new(x: AxisScale, y: AxisScale) -> Self {
        Self {
            inner: EngineAxisScales::new(x.into_engine(), y.into_engine()),
        }
    }

    pub fn x(self) -> AxisScale {
        self.inner.x().into_bridge()
    }

    pub fn y(self) -> AxisScale {
        self.inner.y().into_bridge()
    }

    pub fn validate(&self, viewport: &Viewport) -> Result<(), SceneError> {
        self.inner.validate(&viewport.inner).map_err(Into::into)
    }
}

impl AxisScale {
    fn into_engine(self) -> EngineAxisScale {
        match self {
            Self::Linear => EngineAxisScale::Linear,
            Self::Log10 => EngineAxisScale::Log10,
        }
    }
}

impl EngineAxisScale {
    fn into_bridge(self) -> AxisScale {
        match self {
            Self::Linear => AxisScale::Linear,
            Self::Log10 => AxisScale::Log10,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
#[non_exhaustive]
pub enum SeriesTopology {
    MonotonicX,
    ArbitraryXY,
}

impl SeriesTopology {
    fn into_engine(self) -> Topology {
        match self {
            Self::MonotonicX => Topology::MonotonicX,
            Self::ArbitraryXY => Topology::ArbitraryXY,
        }
    }

    fn from_engine(topology: Topology) -> Self {
        match topology {
            Topology::MonotonicX => Self::MonotonicX,
            Topology::ArbitraryXY => Self::ArbitraryXY,
        }
    }
}

#[derive(Debug)]
pub struct SeriesData {
    inner: SeriesInput,
}

impl SeriesData {
    pub fn from_owned_xy(
        topology: SeriesTopology,
        x: Vec<f64>,
        y: Vec<f64>,
    ) -> Result<Self, SceneError> {
        Self::from_owned_xy_segments_inner(topology, x, y, None)
    }

    pub fn from_owned_xy_segments(
        topology: SeriesTopology,
        x: Vec<f64>,
        y: Vec<f64>,
        valid_segments: Vec<Range<usize>>,
    ) -> Result<Self, SceneError> {
        Self::from_owned_xy_segments_inner(topology, x, y, Some(valid_segments))
    }

    fn from_owned_xy_segments_inner(
        topology: SeriesTopology,
        x: Vec<f64>,
        y: Vec<f64>,
        valid_segments: Option<Vec<Range<usize>>>,
    ) -> Result<Self, SceneError> {
        Ok(Self {
            inner: SeriesInput::from_owned_xy(topology.into_engine(), x, y, valid_segments)?,
        })
    }

    pub fn topology(&self) -> SeriesTopology {
        SeriesTopology::from_engine(self.inner.topology())
    }

    pub fn source_len(&self) -> u64 {
        self.inner.source_len()
    }

    pub fn point_count(&self) -> usize {
        self.inner.point_count()
    }

    pub fn is_empty(&self) -> bool {
        self.source_len() == 0
    }

    fn into_engine(self) -> SeriesInput {
        self.inner
    }
}

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct SceneRevision(u64);

impl SceneRevision {
    fn from_engine(revision: EngineSceneRevision) -> Self {
        Self(revision.0)
    }
}

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct SeriesId(u64);

impl SeriesId {
    fn from_engine(id: EngineSeriesId) -> Self {
        Self(id.0)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CommitReceipt {
    revision: SceneRevision,
    changed: bool,
}

impl CommitReceipt {
    pub fn revision(self) -> SceneRevision {
        self.revision
    }

    pub fn changed(self) -> bool {
        self.changed
    }
}

pub struct PlotScene {
    inner: EnginePlotScene,
}

impl PlotScene {
    pub fn new(canonical_view: Viewport, scales: AxisScales) -> Result<Self, SceneError> {
        Ok(Self {
            inner: EnginePlotScene::new(canonical_view.inner, scales.inner)?,
        })
    }

    pub fn transaction(&mut self) -> SceneTransaction<'_> {
        SceneTransaction {
            inner: self.inner.transaction(),
        }
    }

    pub fn snapshot(&self) -> SceneSnapshot {
        SceneSnapshot {
            inner: self.inner.snapshot(),
        }
    }

    pub fn revision(&self) -> SceneRevision {
        SceneRevision::from_engine(self.inner.revision())
    }
}

pub struct SceneTransaction<'a> {
    inner: EngineSceneTransaction<'a>,
}

impl SceneTransaction<'_> {
    pub fn replace_canonical_view(&mut self, view: Viewport) -> Result<(), SceneError> {
        self.inner
            .replace_canonical_view(view.inner)
            .map_err(Into::into)
    }

    pub fn set_viewport(&mut self, view: Viewport) -> Result<(), SceneError> {
        self.inner.set_viewport(view.inner).map_err(Into::into)
    }

    pub fn set_axis_scales(&mut self, scales: AxisScales) -> Result<(), SceneError> {
        self.inner.set_axis_scales(scales.inner).map_err(Into::into)
    }

    pub fn add_series(&mut self, data: SeriesData) -> Result<SeriesId, SceneError> {
        self.inner
            .add_series(data.into_engine())
            .map(SeriesId::from_engine)
            .map_err(Into::into)
    }

    pub fn append_series(&mut self, id: SeriesId, data: SeriesData) -> Result<(), SceneError> {
        self.inner
            .append_series(EngineSeriesId(id.0), data.into_engine())
            .map_err(Into::into)
    }

    pub fn commit(self) -> Result<CommitReceipt, SceneError> {
        self.inner
            .commit()
            .map(|receipt| CommitReceipt {
                revision: SceneRevision::from_engine(receipt.revision()),
                changed: receipt.changed(),
            })
            .map_err(Into::into)
    }

    pub fn abort(self) {
        self.inner.abort();
    }
}

#[derive(Clone)]
pub struct SceneSnapshot {
    inner: EngineSceneSnapshot,
}

impl SceneSnapshot {
    pub fn revision(&self) -> SceneRevision {
        SceneRevision::from_engine(self.inner.revision())
    }

    pub fn canonical_view(&self) -> Viewport {
        Viewport {
            inner: self.inner.canonical_view(),
        }
    }

    pub fn viewport(&self) -> Viewport {
        Viewport {
            inner: self.inner.viewport(),
        }
    }

    pub fn axis_scales(&self) -> AxisScales {
        AxisScales {
            inner: self.inner.axis_scales(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bridge_constructs_opaque_values_and_sanitizes_errors() {
        let error = AxisRange::new(2.0, 1.0).expect_err("reversed range");
        assert_eq!(error.kind(), SceneErrorKind::InvalidInput);
        assert_eq!(error.message(), "input is invalid");
        assert!(!error.message().contains("2.0"));
        let data =
            SeriesData::from_owned_xy(SeriesTopology::MonotonicX, vec![0.0, 1.0], vec![2.0, 3.0])
                .expect("data");
        assert_eq!(data.source_len(), 2);
        assert_eq!(data.point_count(), 2);
        assert!(!data.is_empty());
    }

    #[test]
    fn bridge_scene_surface_publishes_revision_and_snapshot() {
        let view = Viewport::from_bounds(0.0, 2.0, 0.0, 2.0).expect("view");
        let mut scene = PlotScene::new(view, AxisScales::new(AxisScale::Linear, AxisScale::Linear))
            .expect("scene");
        let old = scene.snapshot();
        let data =
            SeriesData::from_owned_xy(SeriesTopology::MonotonicX, vec![0.0, 1.0], vec![0.0, 1.0])
                .expect("data");
        let receipt = {
            let mut transaction = scene.transaction();
            transaction.add_series(data).expect("add");
            transaction.commit().expect("commit")
        };
        assert!(receipt.changed());
        assert_eq!(scene.revision().0, 1);
        assert_eq!(old.revision().0, 0);
        assert_eq!(old.viewport(), view);
    }

    #[test]
    fn bridge_error_mapping_is_exhaustive_and_messages_are_sanitized() {
        let kinds = [
            error::SceneErrorKind::InvalidInput,
            error::SceneErrorKind::UnsupportedCapability,
            error::SceneErrorKind::InvalidState,
            error::SceneErrorKind::SeriesNotFound,
            error::SceneErrorKind::TopologyViolation,
            error::SceneErrorKind::NonFiniteCanonical,
            error::SceneErrorKind::CapacityExceeded,
            error::SceneErrorKind::AllocationFailed,
            error::SceneErrorKind::IdentityExhausted,
            error::SceneErrorKind::RevisionExhausted,
            error::SceneErrorKind::Internal,
        ];
        for kind in kinds {
            let error = SceneError::from(EngineSceneError::new(kind));
            assert!(!error.message().is_empty());
            assert!(!error.message().contains("crate"));
            assert!(!error.message().contains("0x"));
            assert_eq!(error.to_string(), error.message());
        }
    }
}
