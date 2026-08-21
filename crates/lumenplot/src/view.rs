use crate::error::PublicError;
use lumenplot_engine::bridge::{
    AxisRange as EngineAxisRange, AxisScale as EngineAxisScale, AxisScales as EngineAxisScales,
    Viewport as EngineViewport,
};

pub struct AxisRange {
    inner: EngineAxisRange,
}

impl AxisRange {
    pub fn new(min: f64, max: f64) -> Result<Self, PublicError> {
        EngineAxisRange::new(min, max)
            .map(Self::from_engine)
            .map_err(PublicError::from_engine)
    }

    pub fn min(&self) -> f64 {
        self.inner.min()
    }

    pub fn max(&self) -> f64 {
        self.inner.max()
    }

    pub(crate) fn from_engine(inner: EngineAxisRange) -> Self {
        Self { inner }
    }

    pub(crate) fn into_engine(self) -> EngineAxisRange {
        self.inner
    }
}

#[non_exhaustive]
pub enum AxisScale {
    Linear,
    Log10,
}

impl AxisScale {
    pub(crate) fn into_engine(self) -> EngineAxisScale {
        match self {
            Self::Linear => EngineAxisScale::Linear,
            Self::Log10 => EngineAxisScale::Log10,
        }
    }

    pub(crate) fn from_engine(scale: EngineAxisScale) -> Self {
        match scale {
            EngineAxisScale::Linear => Self::Linear,
            EngineAxisScale::Log10 => Self::Log10,
            _ => unreachable!("unsupported engine axis scale"),
        }
    }
}

pub struct Viewport {
    inner: EngineViewport,
}

impl Viewport {
    pub fn new(x: AxisRange, y: AxisRange) -> Self {
        Self {
            inner: EngineViewport::new(x.into_engine(), y.into_engine()),
        }
    }

    pub fn from_bounds(
        x_min: f64,
        x_max: f64,
        y_min: f64,
        y_max: f64,
    ) -> Result<Self, PublicError> {
        EngineViewport::from_bounds(x_min, x_max, y_min, y_max)
            .map(Self::from_engine)
            .map_err(PublicError::from_engine)
    }

    pub fn x(&self) -> AxisRange {
        AxisRange::from_engine(self.inner.x())
    }

    pub fn y(&self) -> AxisRange {
        AxisRange::from_engine(self.inner.y())
    }

    pub(crate) fn from_engine(inner: EngineViewport) -> Self {
        Self { inner }
    }

    pub(crate) fn into_engine(self) -> EngineViewport {
        self.inner
    }
}

pub struct AxisScales {
    inner: EngineAxisScales,
}

impl AxisScales {
    pub fn new(x: AxisScale, y: AxisScale) -> Self {
        Self {
            inner: EngineAxisScales::new(x.into_engine(), y.into_engine()),
        }
    }

    pub fn x(&self) -> AxisScale {
        AxisScale::from_engine(self.inner.x())
    }

    pub fn y(&self) -> AxisScale {
        AxisScale::from_engine(self.inner.y())
    }

    pub fn validate(&self, viewport: &Viewport) -> Result<(), PublicError> {
        self.inner
            .validate(&viewport.inner)
            .map_err(PublicError::from_engine)
    }

    pub(crate) fn from_engine(inner: EngineAxisScales) -> Self {
        Self { inner }
    }

    pub(crate) fn into_engine(self) -> EngineAxisScales {
        self.inner
    }
}
