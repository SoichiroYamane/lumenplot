use std::ops::Range;

use crate::error::PublicError;
use lumenplot_engine::bridge::{SeriesData as EngineSeriesData, SeriesTopology as EngineTopology};

#[non_exhaustive]
pub enum SeriesTopology {
    MonotonicX,
    ArbitraryXY,
}

impl SeriesTopology {
    fn into_engine(self) -> EngineTopology {
        match self {
            Self::MonotonicX => EngineTopology::MonotonicX,
            Self::ArbitraryXY => EngineTopology::ArbitraryXY,
        }
    }

    fn from_engine(topology: EngineTopology) -> Self {
        match topology {
            EngineTopology::MonotonicX => Self::MonotonicX,
            EngineTopology::ArbitraryXY => Self::ArbitraryXY,
            _ => unreachable!("unsupported engine series topology"),
        }
    }
}

pub struct SeriesData {
    inner: EngineSeriesData,
}

impl SeriesData {
    pub fn from_owned_xy(
        topology: SeriesTopology,
        x: Vec<f64>,
        y: Vec<f64>,
    ) -> Result<Self, PublicError> {
        EngineSeriesData::from_owned_xy(topology.into_engine(), x, y)
            .map(Self::from_engine)
            .map_err(PublicError::from_engine)
    }

    pub fn from_owned_xy_segments(
        topology: SeriesTopology,
        x: Vec<f64>,
        y: Vec<f64>,
        valid_segments: Vec<Range<usize>>,
    ) -> Result<Self, PublicError> {
        EngineSeriesData::from_owned_xy_segments(topology.into_engine(), x, y, valid_segments)
            .map(Self::from_engine)
            .map_err(PublicError::from_engine)
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
        self.inner.is_empty()
    }

    fn from_engine(inner: EngineSeriesData) -> Self {
        Self { inner }
    }

    pub(crate) fn into_engine(self) -> EngineSeriesData {
        self.inner
    }
}
