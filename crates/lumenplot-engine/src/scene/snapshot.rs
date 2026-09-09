use std::sync::Arc;

use crate::text::PlotLayout;

use super::revision::SceneRevision;
use super::state::{AxisScales, SceneState, Viewport};

#[derive(Clone, Debug)]
pub(crate) struct SceneSnapshot {
    pub(crate) state: Arc<SceneState>,
}

impl SceneSnapshot {
    pub(crate) fn new(state: Arc<SceneState>) -> Self {
        Self { state }
    }

    pub(crate) fn revision(&self) -> SceneRevision {
        self.state.revision()
    }

    pub(crate) fn canonical_view(&self) -> Viewport {
        self.state.canonical_view()
    }

    pub(crate) fn viewport(&self) -> Viewport {
        self.state.viewport()
    }

    pub(crate) fn axis_scales(&self) -> AxisScales {
        self.state.scales()
    }

    pub(crate) fn font_revision(&self) -> u64 {
        self.state.font_revision().0
    }

    pub(crate) fn layout_revision(&self) -> u64 {
        self.state.layout_revision().0
    }

    pub(crate) fn plot_layout(&self) -> Arc<PlotLayout> {
        self.state.plot_layout().clone()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn assert_send_sync<T: Send + Sync>() {}

    #[test]
    fn snapshot_is_send_and_sync() {
        assert_send_sync::<SceneSnapshot>();
    }
}
