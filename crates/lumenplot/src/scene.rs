use crate::error::PublicError;
use crate::series::SeriesData;
use crate::view::{AxisScales, Viewport};
use lumenplot_engine::bridge::{
    CommitReceipt as EngineCommitReceipt, PlotScene as EnginePlotScene,
    SceneRevision as EngineSceneRevision, SceneSnapshot as EngineSceneSnapshot,
    SceneTransaction as EngineSceneTransaction, SeriesId as EngineSeriesId,
};

#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub struct SceneRevision(EngineSceneRevision);

impl SceneRevision {
    pub(crate) fn from_engine(revision: EngineSceneRevision) -> Self {
        Self(revision)
    }
}

#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub struct SeriesId(EngineSeriesId);

impl SeriesId {
    pub(crate) fn from_engine(id: EngineSeriesId) -> Self {
        Self(id)
    }
}

pub struct CommitReceipt {
    revision: SceneRevision,
    changed: bool,
}

impl CommitReceipt {
    pub fn revision(&self) -> SceneRevision {
        self.revision
    }

    pub fn changed(&self) -> bool {
        self.changed
    }

    fn from_engine(receipt: EngineCommitReceipt) -> Self {
        Self {
            revision: SceneRevision::from_engine(receipt.revision()),
            changed: receipt.changed(),
        }
    }
}

pub struct PlotScene {
    inner: EnginePlotScene,
}

impl PlotScene {
    pub fn new(canonical_view: Viewport, scales: AxisScales) -> Result<Self, PublicError> {
        EnginePlotScene::new(canonical_view.into_engine(), scales.into_engine())
            .map(Self::from_engine)
            .map_err(PublicError::from_engine)
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

    fn from_engine(inner: EnginePlotScene) -> Self {
        Self { inner }
    }
}

pub struct SceneTransaction<'a> {
    inner: EngineSceneTransaction<'a>,
}

impl SceneTransaction<'_> {
    pub fn replace_canonical_view(&mut self, view: Viewport) -> Result<(), PublicError> {
        self.inner
            .replace_canonical_view(view.into_engine())
            .map_err(PublicError::from_engine)
    }

    pub fn set_viewport(&mut self, view: Viewport) -> Result<(), PublicError> {
        self.inner
            .set_viewport(view.into_engine())
            .map_err(PublicError::from_engine)
    }

    pub fn set_axis_scales(&mut self, scales: AxisScales) -> Result<(), PublicError> {
        self.inner
            .set_axis_scales(scales.into_engine())
            .map_err(PublicError::from_engine)
    }

    pub fn add_series(&mut self, data: SeriesData) -> Result<SeriesId, PublicError> {
        self.inner
            .add_series(data.into_engine())
            .map(SeriesId::from_engine)
            .map_err(PublicError::from_engine)
    }

    pub fn append_series(&mut self, id: SeriesId, data: SeriesData) -> Result<(), PublicError> {
        self.inner
            .append_series(id.0, data.into_engine())
            .map_err(PublicError::from_engine)
    }

    pub fn commit(self) -> Result<CommitReceipt, PublicError> {
        self.inner
            .commit()
            .map(CommitReceipt::from_engine)
            .map_err(PublicError::from_engine)
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
        Viewport::from_engine(self.inner.canonical_view())
    }

    pub fn viewport(&self) -> Viewport {
        Viewport::from_engine(self.inner.viewport())
    }

    pub fn axis_scales(&self) -> AxisScales {
        AxisScales::from_engine(self.inner.axis_scales())
    }
}
