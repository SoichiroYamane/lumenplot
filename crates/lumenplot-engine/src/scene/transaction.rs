use std::collections::BTreeMap;
use std::sync::Arc;

use crate::data::{SeriesInput, SeriesStorage};
use crate::error::{SceneError, SceneErrorKind};

use super::ids::SeriesId;
use super::revision::SceneRevision;
use super::state::{AxisScales, PlotScene, PublishValues, SceneState, Viewport};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct CommitReceipt {
    revision: SceneRevision,
    changed: bool,
}

impl CommitReceipt {
    pub(crate) fn revision(self) -> SceneRevision {
        self.revision
    }

    pub(crate) fn changed(self) -> bool {
        self.changed
    }
}

pub(crate) struct SceneTransaction<'a> {
    owner: &'a mut PlotScene,
    base: Arc<SceneState>,
    canonical_view: Viewport,
    viewport: Viewport,
    scales: AxisScales,
    changes: BTreeMap<SeriesId, Arc<SeriesStorage>>,
}

impl<'a> SceneTransaction<'a> {
    pub(crate) fn new(owner: &'a mut PlotScene) -> Self {
        let base = owner.state.clone();
        Self {
            canonical_view: base.canonical_view(),
            viewport: base.viewport(),
            scales: base.scales(),
            base,
            owner,
            changes: BTreeMap::new(),
        }
    }

    pub(crate) fn replace_canonical_view(&mut self, view: Viewport) -> Result<(), SceneError> {
        self.scales.validate(&view)?;
        self.canonical_view = view;
        self.viewport = view;
        Ok(())
    }

    pub(crate) fn set_viewport(&mut self, view: Viewport) -> Result<(), SceneError> {
        self.scales.validate(&view)?;
        self.viewport = view;
        Ok(())
    }

    pub(crate) fn set_axis_scales(&mut self, scales: AxisScales) -> Result<(), SceneError> {
        scales.validate(&self.canonical_view)?;
        scales.validate(&self.viewport)?;
        self.scales = scales;
        Ok(())
    }

    pub(crate) fn add_series(&mut self, data: SeriesInput) -> Result<SeriesId, SceneError> {
        let normalized = data.into_normalized();
        let id = SeriesId(allocate_identity(
            &mut self.owner.next_series_id,
            SceneErrorKind::IdentityExhausted,
        )?);
        let epoch = allocate_identity(
            &mut self.owner.next_epoch,
            SceneErrorKind::IdentityExhausted,
        )?;
        let series = SeriesStorage::from_normalized(
            normalized,
            crate::data::DataEpoch(epoch),
            crate::data::ChunkRevision(1),
        )?;
        self.changes.insert(id, series);
        Ok(id)
    }

    pub(crate) fn append_series(
        &mut self,
        id: SeriesId,
        data: SeriesInput,
    ) -> Result<(), SceneError> {
        let old = self
            .changes
            .get(&id)
            .cloned()
            .or_else(|| self.base.series(id).cloned())
            .ok_or_else(|| SceneError::new(SceneErrorKind::SeriesNotFound))?;
        if let Some(series) = SeriesStorage::append(&old, data.into_normalized())? {
            self.changes.insert(id, series);
        }
        Ok(())
    }

    pub(crate) fn commit(self) -> Result<CommitReceipt, SceneError> {
        let Self {
            owner,
            base,
            canonical_view,
            viewport,
            scales,
            changes,
        } = self;
        let data_changed = !changes.is_empty();
        let view_changed = canonical_view != base.canonical_view()
            || viewport != base.viewport()
            || scales != base.scales();
        if !data_changed && !view_changed {
            return Ok(CommitReceipt {
                revision: base.revision(),
                changed: false,
            });
        }

        let revision = base
            .revision()
            .checked_next()
            .ok_or_else(|| SceneError::new(SceneErrorKind::RevisionExhausted))?;
        let mut series = base.series_map().clone();
        if data_changed {
            for (id, value) in changes {
                series.insert(id, value);
            }
        }
        let next_state = SceneState::publish(
            &base,
            PublishValues::new(
                canonical_view,
                viewport,
                scales,
                revision,
                data_changed,
                view_changed,
                series,
            ),
        )?;
        owner.state = Arc::new(next_state);
        Ok(CommitReceipt {
            revision,
            changed: true,
        })
    }

    pub(crate) fn abort(self) {}
}

fn allocate_identity(counter: &mut u64, kind: SceneErrorKind) -> Result<u64, SceneError> {
    let value = *counter;
    if value == 0 {
        return Err(SceneError::new(kind));
    }
    *counter = value.checked_add(1).unwrap_or(0);
    Ok(value)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::data::{SeriesInput, Topology};
    use crate::scene::state::{AxisRange, AxisScale, AxisScales, Viewport};
    use std::sync::Arc;

    fn scene() -> PlotScene {
        PlotScene::new(
            Viewport::from_bounds(0.0, 10.0, 0.0, 10.0).expect("view"),
            AxisScales::new(AxisScale::Linear, AxisScale::Linear),
        )
        .expect("scene")
    }

    fn data(values: &[f64]) -> SeriesInput {
        SeriesInput::from_owned_xy(
            Topology::MonotonicX,
            (0..values.len()).map(|value| value as f64).collect(),
            values.to_vec(),
            None,
        )
        .expect("data")
    }

    #[test]
    fn no_op_and_abort_do_not_publish() {
        let mut plot = scene();
        let before = plot.snapshot();
        let receipt = plot.transaction().commit().expect("commit");
        assert!(!receipt.changed());
        assert_eq!(receipt.revision(), SceneRevision(0));
        assert_eq!(plot.revision(), SceneRevision(0));
        let transaction = plot.transaction();
        transaction.abort();
        assert_eq!(plot.revision(), SceneRevision(0));
        assert_eq!(before.revision(), plot.snapshot().revision());
    }

    #[test]
    fn failed_operation_keeps_earlier_staged_view() {
        let mut plot = scene();
        let mut transaction = plot.transaction();
        transaction
            .set_viewport(Viewport::from_bounds(1.0, 9.0, 1.0, 9.0).expect("view"))
            .expect("first edit");
        let error = transaction
            .set_axis_scales(AxisScales::new(AxisScale::Log10, AxisScale::Linear))
            .expect_err("canonical view is invalid for log scale");
        assert_eq!(error.kind(), SceneErrorKind::InvalidInput);
        let receipt = transaction.commit().expect("earlier edit remains usable");
        assert!(receipt.changed());
        assert_eq!(plot.snapshot().viewport().x().min(), 1.0);
    }

    #[test]
    fn add_and_append_update_data_once_and_preserve_old_snapshot() {
        let mut plot = scene();
        let old = plot.snapshot();
        let id = {
            let mut transaction = plot.transaction();
            let id = transaction.add_series(data(&[1.0, 2.0])).expect("add");
            transaction
                .append_series(
                    id,
                    SeriesInput::from_owned_xy(
                        Topology::MonotonicX,
                        vec![2.0, 3.0],
                        vec![3.0, 4.0],
                        None,
                    )
                    .expect("append data"),
                )
                .expect("append");
            let receipt = transaction.commit().expect("commit");
            assert_eq!(receipt.revision(), SceneRevision(1));
            id
        };
        assert_eq!(plot.revision(), SceneRevision(1));
        assert!(old.state.series_map().is_empty());
        assert_eq!(plot.state.series(id).expect("series").point_count(), 4);
        assert_eq!(plot.state.component_revisions().0.0, 1);
    }

    #[test]
    fn validation_failure_does_not_burn_identity() {
        let mut plot = scene();
        let transaction = plot.transaction();
        let bad =
            SeriesInput::from_owned_xy(Topology::MonotonicX, vec![2.0, 1.0], vec![1.0, 2.0], None)
                .expect_err("topology validation fails before allocation");
        assert_eq!(bad.kind(), SceneErrorKind::TopologyViolation);
        transaction.commit().expect("no-op commit");
        let id = plot
            .transaction()
            .add_series(data(&[1.0]))
            .expect("first valid id");
        assert_eq!(id, SeriesId(1));
    }

    #[test]
    fn aborted_add_burns_identity_but_not_live_state() {
        let mut plot = scene();
        {
            let mut transaction = plot.transaction();
            let id = transaction.add_series(data(&[1.0])).expect("add");
            assert_eq!(id, SeriesId(1));
            transaction.abort();
        }
        assert_eq!(plot.revision(), SceneRevision(0));
        assert!(plot.state.series_map().is_empty());
        let id = plot
            .transaction()
            .add_series(data(&[2.0]))
            .expect("next id");
        assert_eq!(id, SeriesId(2));
    }

    #[test]
    fn revision_exhaustion_is_atomic_and_component_revisions_are_selective() {
        let mut plot = scene();
        plot.set_revision_for_test(SceneRevision(u64::MAX));
        let before = plot.snapshot();
        let mut transaction = plot.transaction();
        transaction
            .set_viewport(Viewport::from_bounds(1.0, 9.0, 1.0, 9.0).expect("view"))
            .expect("staged view");
        let error = transaction.commit().expect_err("revision exhaustion");
        assert_eq!(error.kind(), SceneErrorKind::RevisionExhausted);
        assert_eq!(plot.snapshot().viewport(), before.viewport());
        assert!(plot.state.series_map().is_empty());

        let mut plot = scene();
        let initial = plot.state.component_revisions();
        {
            let mut transaction = plot.transaction();
            transaction
                .set_viewport(Viewport::from_bounds(1.0, 9.0, 1.0, 9.0).expect("view"))
                .expect("view");
            transaction.commit().expect("view commit");
        }
        let after_view = plot.state.component_revisions();
        assert_eq!(after_view.0, initial.0);
        assert_eq!(after_view.1.0, initial.1.0 + 1);
        {
            let mut transaction = plot.transaction();
            transaction.add_series(data(&[1.0])).expect("data");
            transaction.commit().expect("data commit");
        }
        let after_data = plot.state.component_revisions();
        assert_eq!(after_data.0.0, initial.0.0 + 1);
        assert_eq!(after_data.1, after_view.1);
    }

    #[test]
    fn snapshot_clones_share_state_and_old_snapshots_remain_immutable() {
        let mut plot = scene();
        let first = plot.snapshot();
        let first_clone = first.clone();
        assert!(Arc::ptr_eq(&first.state, &first_clone.state));
        {
            let mut transaction = plot.transaction();
            transaction.add_series(data(&[1.0])).expect("data");
            transaction.commit().expect("commit");
        }
        assert_eq!(first.revision(), SceneRevision(0));
        assert!(first.state.series_map().is_empty());
        assert_eq!(plot.snapshot().revision(), SceneRevision(1));
    }

    #[test]
    fn range_rejects_nonfinite_and_reversed_values() {
        assert!(AxisRange::new(f64::NAN, 1.0).is_err());
        assert!(AxisRange::new(2.0, 1.0).is_err());
    }
}
