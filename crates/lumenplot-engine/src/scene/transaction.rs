use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;

use crate::data::{SeriesInput, SeriesStorage};
use crate::error::{SceneError, SceneErrorKind};
use crate::text::{
    AnnotationShape, AnnotationSpace, AnnotationTransform, MAX_RETAINED_ANNOTATIONS,
    RetainedAnnotation,
};

use super::AnnotationId;
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
    annotation_upserts: BTreeMap<AnnotationId, RetainedAnnotation>,
    annotation_deletes: BTreeSet<AnnotationId>,
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
            annotation_upserts: BTreeMap::new(),
            annotation_deletes: BTreeSet::new(),
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

    /// Stages one annotation add as Plot State.
    ///
    /// P1 scope pins the explicit transform to identity; custom transforms,
    /// geometry-space hit-testing, and export wiring belong to later stages.
    /// Identity allocation mirrors `add_series`: a validated add allocates a
    /// never-reused [`AnnotationId`] before staging, so abort or a later
    /// failed commit burns it, while validation failure before allocation
    /// does not.
    pub(crate) fn add_annotation(
        &mut self,
        space: AnnotationSpace,
        shape: AnnotationShape,
        clip_ref: u32,
        style_ref: u32,
        z_order: i32,
    ) -> Result<AnnotationId, SceneError> {
        // Validate shape/clip/style before burning an identity by probing
        // with a dummy id; the real allocation happens only on success.
        RetainedAnnotation::new(
            1,
            space,
            shape,
            AnnotationTransform::identity(),
            clip_ref,
            style_ref,
            z_order,
        )?;
        let id = AnnotationId(allocate_identity(
            &mut self.owner.next_annotation_id,
            SceneErrorKind::IdentityExhausted,
        )?);
        let annotation = RetainedAnnotation::new(
            id.0,
            space,
            shape,
            AnnotationTransform::identity(),
            clip_ref,
            style_ref,
            z_order,
        )?;
        self.annotation_upserts.insert(id, annotation);
        Ok(id)
    }

    /// Stages one annotation edit as Plot State, preserving identity.
    ///
    /// Unknown ids fail with `InvalidInput` without staging. A dedicated
    /// `AnnotationNotFound` kind remains an `architecture-authority` decision;
    /// see the PR proposal. Editing to the identical retained value stages an
    /// equal record, which commit treats as an effective no-op.
    pub(crate) fn edit_annotation(
        &mut self,
        id: AnnotationId,
        space: AnnotationSpace,
        shape: AnnotationShape,
        clip_ref: u32,
        style_ref: u32,
        z_order: i32,
    ) -> Result<(), SceneError> {
        if self.annotation_deletes.contains(&id) {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }
        if !self.annotation_upserts.contains_key(&id) && self.base.annotation(id).is_none() {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }
        let annotation = RetainedAnnotation::new(
            id.0,
            space,
            shape,
            AnnotationTransform::identity(),
            clip_ref,
            style_ref,
            z_order,
        )?;
        self.annotation_upserts.insert(id, annotation);
        Ok(())
    }

    /// Stages one annotation delete as Plot State.
    ///
    /// Unknown ids fail with `InvalidInput` without staging, for the same
    /// pending-kind reason documented on [`Self::edit_annotation`]. Adding
    /// then deleting the same staged id in one transaction nets to no
    /// annotation change, while the allocated identity stays burned.
    pub(crate) fn delete_annotation(&mut self, id: AnnotationId) -> Result<(), SceneError> {
        if self.annotation_upserts.remove(&id).is_some() {
            // Freshly staged add removed; only record a base delete when the
            // identity also exists in the committed base map.
            if self.base.annotation(id).is_some() {
                self.annotation_deletes.insert(id);
            }
            return Ok(());
        }
        if self.base.annotation(id).is_none() || self.annotation_deletes.contains(&id) {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }
        self.annotation_deletes.insert(id);
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
            annotation_upserts,
            annotation_deletes,
        } = self;
        let data_changed = !changes.is_empty();
        let view_changed = canonical_view != base.canonical_view()
            || viewport != base.viewport()
            || scales != base.scales();
        let mut annotations = base.annotations_map().clone();
        for id in &annotation_deletes {
            annotations.remove(id);
        }
        for (id, value) in annotation_upserts {
            annotations.insert(id, value);
        }
        if annotations.len() > MAX_RETAINED_ANNOTATIONS {
            return Err(SceneError::new(SceneErrorKind::CapacityExceeded));
        }
        let annotation_changed = annotations != *base.annotations_map();
        if !data_changed && !view_changed && !annotation_changed {
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
                annotation_changed,
                series,
                annotations,
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
    use crate::text::{AnnotationShape, AnnotationSpace};
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
    fn retained_layout_generation_is_shared_until_a_scene_change() {
        let mut plot = scene();
        let before = plot.snapshot();
        let before_layout = before.plot_layout();
        assert_eq!(before.font_revision(), 0);
        assert_eq!(before.layout_revision(), 0);
        assert!(before_layout.validate_for_generation(0, 0));

        let same = plot.snapshot();
        let same_layout = same.plot_layout();
        assert!(Arc::ptr_eq(&before_layout, &same_layout));

        {
            let mut transaction = plot.transaction();
            transaction
                .set_viewport(Viewport::from_bounds(1.0, 9.0, 1.0, 9.0).expect("view"))
                .expect("view");
            transaction.commit().expect("commit");
        }

        let after = plot.snapshot();
        let after_layout = after.plot_layout();
        assert_eq!(after.font_revision(), 0);
        assert_eq!(after.layout_revision(), 1);
        assert!(!Arc::ptr_eq(&before_layout, &after_layout));
        assert!(
            !before_layout.validate_for_generation(after.font_revision(), after.layout_revision())
        );
        assert!(
            after_layout.validate_for_generation(after.font_revision(), after.layout_revision())
        );
    }

    #[test]
    fn range_rejects_nonfinite_and_reversed_values() {
        assert!(AxisRange::new(f64::NAN, 1.0).is_err());
        assert!(AxisRange::new(2.0, 1.0).is_err());
    }

    fn text_shape(x: f64, y: f64) -> AnnotationShape {
        AnnotationShape::Text {
            x,
            y,
            half_width: 6.0,
            half_height: 2.0,
        }
    }

    fn rect_shape() -> AnnotationShape {
        AnnotationShape::Rectangle {
            x_min: 1.0,
            y_min: 1.0,
            x_max: 4.0,
            y_max: 3.0,
        }
    }

    fn add_text(plot: &mut PlotScene, x: f64, y: f64) -> AnnotationId {
        let mut transaction = plot.transaction();
        let id = transaction
            .add_annotation(AnnotationSpace::Data2D, text_shape(x, y), 1, 1, 1)
            .expect("add annotation");
        transaction.commit().expect("commit").revision();
        id
    }

    #[test]
    fn annotation_add_bumps_scene_and_annotation_revision_only() {
        let mut plot = scene();
        let old = plot.snapshot();
        let old_layout = old.plot_layout();
        let id = {
            let mut transaction = plot.transaction();
            let id = transaction
                .add_annotation(AnnotationSpace::Data2D, text_shape(10.0, 20.0), 1, 1, 1)
                .expect("add");
            assert_eq!(id, AnnotationId(1));
            let receipt = transaction.commit().expect("commit");
            assert!(receipt.changed());
            assert_eq!(receipt.revision(), SceneRevision(1));
            id
        };
        assert_eq!(plot.revision(), SceneRevision(1));
        assert_eq!(plot.state.annotation_revision().0, 1);
        // Data/view/layout component keys stay put on an annotation-only change.
        assert_eq!(plot.state.component_revisions().0.0, 0);
        assert_eq!(plot.state.component_revisions().1.0, 0);
        assert_eq!(plot.state.layout_revision().0, 0);
        assert!(Arc::ptr_eq(&old_layout, &plot.snapshot().plot_layout()));
        let stored = plot.state.annotation(id).expect("stored annotation");
        assert_eq!(stored.id(), 1);
        assert_eq!(stored.space(), AnnotationSpace::Data2D);
        // Old snapshot stays immutable and empty.
        assert_eq!(old.revision(), SceneRevision(0));
        assert!(old.state.annotations_map().is_empty());
        assert_eq!(plot.state.annotations_map().len(), 1);
    }

    #[test]
    fn annotation_edit_preserves_identity_and_bumps_once() {
        let mut plot = scene();
        let id = add_text(&mut plot, 10.0, 20.0);
        let before = plot.snapshot();
        {
            let mut transaction = plot.transaction();
            transaction
                .edit_annotation(id, AnnotationSpace::Data2D, text_shape(11.0, 21.0), 1, 1, 2)
                .expect("edit");
            let receipt = transaction.commit().expect("commit");
            assert!(receipt.changed());
            assert_eq!(receipt.revision(), SceneRevision(2));
        }
        assert_eq!(plot.revision(), SceneRevision(2));
        assert_eq!(plot.state.annotation_revision().0, 2);
        let stored = plot.state.annotation(id).expect("edited annotation");
        assert_eq!(stored.id(), id.0);
        assert_eq!(stored.shape(), text_shape(11.0, 21.0));
        assert_eq!(stored.z_order(), 2);
        // Pre-edit snapshot still carries the original shape.
        assert_eq!(
            before.state.annotation(id).expect("before").shape(),
            text_shape(10.0, 20.0)
        );
        assert_eq!(plot.state.component_revisions().0.0, 0);
        assert_eq!(plot.state.component_revisions().1.0, 0);
    }

    #[test]
    fn annotation_edit_to_identical_value_is_noop() {
        let mut plot = scene();
        let id = add_text(&mut plot, 5.0, 5.0);
        let revision = plot.revision();
        let annotation_revision = plot.state.annotation_revision();
        {
            let mut transaction = plot.transaction();
            transaction
                .edit_annotation(id, AnnotationSpace::Data2D, text_shape(5.0, 5.0), 1, 1, 1)
                .expect("identical edit stages");
            let receipt = transaction.commit().expect("commit");
            assert!(!receipt.changed());
            assert_eq!(receipt.revision(), revision);
        }
        assert_eq!(plot.revision(), revision);
        assert_eq!(plot.state.annotation_revision(), annotation_revision);
    }

    #[test]
    fn annotation_delete_removes_and_bumps() {
        let mut plot = scene();
        let first = add_text(&mut plot, 1.0, 1.0);
        let second = {
            let mut transaction = plot.transaction();
            let id = transaction
                .add_annotation(AnnotationSpace::Data2D, rect_shape(), 1, 1, 2)
                .expect("add rect");
            transaction.commit().expect("commit");
            id
        };
        let before = plot.snapshot();
        assert_eq!(before.state.annotations_map().len(), 2);
        {
            let mut transaction = plot.transaction();
            transaction.delete_annotation(first).expect("delete");
            let receipt = transaction.commit().expect("commit");
            assert!(receipt.changed());
            assert_eq!(receipt.revision(), SceneRevision(3));
        }
        assert!(plot.state.annotation(first).is_none());
        assert!(plot.state.annotation(second).is_some());
        assert_eq!(plot.state.annotation_revision().0, 3);
        // Deleted identity is never reused: the next add burns forward.
        let next = {
            let mut transaction = plot.transaction();
            let id = transaction
                .add_annotation(AnnotationSpace::Data2D, text_shape(9.0, 9.0), 1, 1, 1)
                .expect("add after delete");
            transaction.commit().expect("commit");
            id
        };
        assert_eq!(next, AnnotationId(3));
        assert!(before.state.annotation(first).is_some());
    }

    #[test]
    fn annotation_validation_failure_does_not_burn_identity() {
        let mut plot = scene();
        {
            let mut transaction = plot.transaction();
            let bad = transaction
                .add_annotation(
                    AnnotationSpace::Data2D,
                    AnnotationShape::Text {
                        x: 0.0,
                        y: 0.0,
                        half_width: 0.0,
                        half_height: 1.0,
                    },
                    1,
                    1,
                    0,
                )
                .expect_err("zero half-width is invalid");
            assert_eq!(bad.kind(), SceneErrorKind::InvalidInput);
            let bad_clip = transaction
                .add_annotation(AnnotationSpace::Data2D, text_shape(0.0, 0.0), 0, 1, 0)
                .expect_err("zero clip_ref is invalid");
            assert_eq!(bad_clip.kind(), SceneErrorKind::InvalidInput);
            let receipt = transaction.commit().expect("empty commit stays no-op");
            assert!(!receipt.changed());
        }
        let id = add_text(&mut plot, 0.0, 0.0);
        assert_eq!(id, AnnotationId(1));
    }

    #[test]
    fn annotation_abort_burns_identity_but_not_live_state() {
        let mut plot = scene();
        {
            let mut transaction = plot.transaction();
            let id = transaction
                .add_annotation(AnnotationSpace::Data2D, text_shape(1.0, 1.0), 1, 1, 0)
                .expect("add");
            assert_eq!(id, AnnotationId(1));
            transaction.abort();
        }
        assert_eq!(plot.revision(), SceneRevision(0));
        assert!(plot.state.annotations_map().is_empty());
        let id = add_text(&mut plot, 2.0, 2.0);
        assert_eq!(id, AnnotationId(2));
    }

    #[test]
    fn annotation_unknown_edit_delete_fail_without_revision_bump() {
        let mut plot = scene();
        let missing = AnnotationId(999);
        {
            let mut transaction = plot.transaction();
            let edit = transaction
                .edit_annotation(
                    missing,
                    AnnotationSpace::Data2D,
                    text_shape(0.0, 0.0),
                    1,
                    1,
                    0,
                )
                .expect_err("unknown edit fails");
            assert_eq!(edit.kind(), SceneErrorKind::InvalidInput);
            let delete = transaction
                .delete_annotation(missing)
                .expect_err("unknown delete fails");
            assert_eq!(delete.kind(), SceneErrorKind::InvalidInput);
            let receipt = transaction.commit().expect("failed ops stage nothing");
            assert!(!receipt.changed());
        }
        assert_eq!(plot.revision(), SceneRevision(0));
        assert_eq!(plot.state.annotation_revision().0, 0);
    }

    #[test]
    fn annotation_add_then_delete_in_same_transaction_nets_noop_but_burns() {
        let mut plot = scene();
        {
            let mut transaction = plot.transaction();
            let id = transaction
                .add_annotation(AnnotationSpace::Data2D, text_shape(3.0, 3.0), 1, 1, 0)
                .expect("staged add");
            assert_eq!(id, AnnotationId(1));
            transaction.delete_annotation(id).expect("staged delete");
            let receipt = transaction.commit().expect("commit");
            assert!(!receipt.changed());
            assert_eq!(receipt.revision(), SceneRevision(0));
        }
        assert!(plot.state.annotations_map().is_empty());
        let next = add_text(&mut plot, 4.0, 4.0);
        assert_eq!(next, AnnotationId(2));
    }

    #[test]
    fn annotation_commits_leave_view_state_untouched_view_history_exclusion() {
        // V1 view history lives outside PlotScene/Snapshot (API 0001); the
        // scene-side proof is that annotation transactions never touch the
        // view component, viewport, or canonical view.
        let mut plot = scene();
        let canonical = plot.snapshot().canonical_view();
        let viewport = plot.snapshot().viewport();
        let id = add_text(&mut plot, 1.0, 2.0);
        assert_eq!(plot.state.component_revisions().1.0, 0);
        assert_eq!(plot.snapshot().canonical_view(), canonical);
        assert_eq!(plot.snapshot().viewport(), viewport);
        {
            let mut transaction = plot.transaction();
            transaction
                .edit_annotation(id, AnnotationSpace::Data2D, text_shape(2.0, 3.0), 1, 1, 1)
                .expect("edit");
            transaction.commit().expect("commit");
        }
        assert_eq!(plot.state.component_revisions().1.0, 0);
        assert_eq!(plot.snapshot().viewport(), viewport);
        {
            let mut transaction = plot.transaction();
            transaction.delete_annotation(id).expect("delete");
            transaction.commit().expect("commit");
        }
        assert_eq!(plot.state.component_revisions().1.0, 0);
        assert_eq!(plot.snapshot().canonical_view(), canonical);
    }

    #[test]
    fn annotation_all_four_kinds_retained_with_never_reused_ids() {
        let mut plot = scene();
        let ids = {
            let mut transaction = plot.transaction();
            let text = transaction
                .add_annotation(AnnotationSpace::Data2D, text_shape(10.0, 20.0), 1, 1, 1)
                .expect("text");
            let line = transaction
                .add_annotation(
                    AnnotationSpace::AxesLogical,
                    AnnotationShape::Line {
                        x1: 0.0,
                        y1: 0.0,
                        x2: 64.0,
                        y2: 32.0,
                    },
                    1,
                    1,
                    2,
                )
                .expect("line");
            let arrow = transaction
                .add_annotation(
                    AnnotationSpace::FigureLogical,
                    AnnotationShape::Arrow {
                        x1: 8.0,
                        y1: 8.0,
                        x2: 40.0,
                        y2: 24.0,
                        head_length: 6.0,
                    },
                    1,
                    1,
                    3,
                )
                .expect("arrow");
            let rect = transaction
                .add_annotation(
                    AnnotationSpace::DisplayLogical,
                    AnnotationShape::Rectangle {
                        x_min: 100.0,
                        y_min: 100.0,
                        x_max: 140.0,
                        y_max: 120.0,
                    },
                    1,
                    1,
                    4,
                )
                .expect("rect");
            let receipt = transaction.commit().expect("commit");
            assert!(receipt.changed());
            assert_eq!(receipt.revision(), SceneRevision(1));
            vec![text, line, arrow, rect]
        };
        assert_eq!(
            ids,
            vec![
                AnnotationId(1),
                AnnotationId(2),
                AnnotationId(3),
                AnnotationId(4)
            ]
        );
        assert_eq!(plot.state.annotation_revision().0, 1);
        assert_eq!(plot.state.annotations_map().len(), 4);
    }

    #[test]
    fn annotation_failed_commit_burns_identity_and_leaves_state_unchanged() {
        let mut plot = scene();
        plot.set_revision_for_test(SceneRevision(u64::MAX));
        let before = plot.snapshot();
        let mut transaction = plot.transaction();
        let first = transaction
            .add_annotation(AnnotationSpace::Data2D, text_shape(1.0, 1.0), 1, 1, 0)
            .expect("staged id");
        assert_eq!(first, AnnotationId(1));
        let error = transaction.commit().expect_err("revision exhausted");
        assert_eq!(error.kind(), SceneErrorKind::RevisionExhausted);
        assert!(plot.state.annotations_map().is_empty());
        assert_eq!(plot.snapshot().viewport(), before.viewport());
        // The burned identity is not reused even though nothing published.
        let mut transaction = plot.transaction();
        let second = transaction
            .add_annotation(AnnotationSpace::Data2D, text_shape(2.0, 2.0), 1, 1, 0)
            .expect("next staged id");
        assert_eq!(second, AnnotationId(2));
    }

    #[test]
    fn annotation_capacity_is_enforced_atomically() {
        let mut plot = scene();
        {
            let mut transaction = plot.transaction();
            for index in 0..MAX_RETAINED_ANNOTATIONS {
                transaction
                    .add_annotation(
                        AnnotationSpace::Data2D,
                        text_shape(index as f64, 0.0),
                        1,
                        1,
                        0,
                    )
                    .expect("fill to capacity");
            }
            let receipt = transaction.commit().expect("capacity commit");
            assert!(receipt.changed());
        }
        assert_eq!(plot.state.annotations_map().len(), MAX_RETAINED_ANNOTATIONS);
        let mut transaction = plot.transaction();
        transaction
            .add_annotation(AnnotationSpace::Data2D, text_shape(0.0, 1.0), 1, 1, 0)
            .expect("over-capacity stages");
        let error = transaction.commit().expect_err("capacity exceeded");
        assert_eq!(error.kind(), SceneErrorKind::CapacityExceeded);
        assert_eq!(plot.state.annotations_map().len(), MAX_RETAINED_ANNOTATIONS);
    }

    #[test]
    fn annotation_and_data_in_one_commit_bump_revision_once() {
        let mut plot = scene();
        let mut transaction = plot.transaction();
        transaction.add_series(data(&[1.0])).expect("series");
        transaction
            .add_annotation(AnnotationSpace::Data2D, text_shape(7.0, 7.0), 1, 1, 0)
            .expect("annotation");
        let receipt = transaction.commit().expect("commit");
        assert!(receipt.changed());
        assert_eq!(receipt.revision(), SceneRevision(1));
        assert_eq!(plot.state.component_revisions().0.0, 1);
        assert_eq!(plot.state.annotation_revision().0, 1);
        assert_eq!(plot.state.annotations_map().len(), 1);
    }
}
