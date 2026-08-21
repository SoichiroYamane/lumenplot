use std::collections::hash_map::DefaultHasher;
use std::error::Error;
use std::fmt::Debug;
use std::hash::{Hash, Hasher};

use lumenplot::{
    AxisRange, AxisScale, AxisScales, ErrorCategory, ErrorCode, PlotScene, PublicError,
    SceneRevision, SceneSnapshot, SeriesData, SeriesId, SeriesTopology, Viewport,
};

fn linear_view() -> Viewport {
    Viewport::from_bounds(0.0, 10.0, 0.0, 10.0).expect("valid view")
}

fn linear_scales() -> AxisScales {
    AxisScales::new(AxisScale::Linear, AxisScale::Linear)
}

fn monotonic_data(values: &[f64]) -> SeriesData {
    monotonic_data_at(0.0, values)
}

fn monotonic_data_at(start: f64, values: &[f64]) -> SeriesData {
    SeriesData::from_owned_xy(
        SeriesTopology::MonotonicX,
        (0..values.len())
            .map(|index| start + index as f64)
            .collect(),
        values.to_vec(),
    )
    .expect("valid monotonic data")
}

fn assert_code(error: &PublicError, code: &str, category: &str) {
    assert_eq!(error.code().as_str(), code);
    assert_eq!(error.category().as_str(), category);
}

fn assert_snapshot_traits<T: Clone + Send + Sync>() {}

fn assert_id_traits<T: Copy + Clone + Debug + Eq + PartialEq + Hash>() {}

#[test]
fn stable_error_code_and_category_tokens_are_exact() {
    let codes = [
        (ErrorCode::InvalidInput, "invalid-input"),
        (ErrorCode::UnsupportedCapability, "unsupported-capability"),
        (ErrorCode::Closed, "closed"),
        (ErrorCode::InvalidState, "invalid-state"),
        (ErrorCode::HostLoopMisuse, "host-loop-misuse"),
        (ErrorCode::Reentrancy, "reentrancy"),
        (ErrorCode::BackendUnavailable, "backend-unavailable"),
        (ErrorCode::DeviceLost, "device-lost"),
        (ErrorCode::RecoveryFailed, "recovery-failed"),
        (ErrorCode::OutOfMemory, "out-of-memory"),
        (ErrorCode::ResourceInvalid, "resource-invalid"),
        (ErrorCode::Internal, "internal"),
    ];
    for (code, token) in codes {
        assert_eq!(code.as_str(), token);
    }

    let categories = [
        (ErrorCategory::Input, "input"),
        (ErrorCategory::Capability, "capability"),
        (ErrorCategory::Lifecycle, "lifecycle"),
        (ErrorCategory::Host, "host"),
        (ErrorCategory::Backend, "backend"),
        (ErrorCategory::Resource, "resource"),
        (ErrorCategory::Internal, "internal"),
    ];
    for (category, token) in categories {
        assert_eq!(category.as_str(), token);
    }
}

#[test]
fn public_errors_are_sanitized_and_redact_sources() {
    let error = AxisRange::new(2.0, 1.0).err().expect("reversed range");
    assert_code(&error, "invalid-input", "input");
    assert_eq!(error.message(), "input is invalid");
    assert_eq!(error.to_string(), error.message());
    assert!(!error.message().contains("2.0"));
    assert!(!error.message().contains("crate"));
    assert!(error.source().is_none());
    let debug = format!("{error:?}");
    assert!(debug.contains("invalid-input"));
    assert!(!debug.contains("SceneError"));
}

#[test]
fn view_constructors_validate_finite_ranges_and_log_domains() {
    for result in [
        AxisRange::new(f64::NAN, 1.0),
        AxisRange::new(1.0, f64::INFINITY),
        AxisRange::new(2.0, 1.0),
        AxisRange::new(1.0, 1.0),
    ] {
        let error = result.err().expect("invalid range");
        assert_code(&error, "invalid-input", "input");
    }

    let error = Viewport::from_bounds(0.0, 1.0, 4.0, 3.0)
        .err()
        .expect("reversed y range");
    assert_code(&error, "invalid-input", "input");

    let invalid_log_view = Viewport::from_bounds(-1.0, 2.0, 1.0, 2.0).expect("finite view");
    let error = AxisScales::new(AxisScale::Log10, AxisScale::Linear)
        .validate(&invalid_log_view)
        .expect_err("log x range must be positive");
    assert_code(&error, "invalid-input", "input");

    let valid_view = Viewport::from_bounds(1.0, 2.0, 1.0, 2.0).expect("positive view");
    AxisScales::new(AxisScale::Log10, AxisScale::Log10)
        .validate(&valid_view)
        .expect("positive log ranges");
    assert!(matches!(valid_view.x().min(), 1.0));
    assert!(matches!(valid_view.y().max(), 2.0));
}

#[test]
fn owned_series_preserves_topology_length_points_and_explicit_gaps() {
    let data = SeriesData::from_owned_xy_segments(
        SeriesTopology::ArbitraryXY,
        vec![1.0, f64::NAN, 3.0, f64::INFINITY],
        vec![10.0, f64::NAN, 30.0, f64::NEG_INFINITY],
        vec![0..1, 2..3],
    )
    .expect("uncovered nonfinite payload is ignored");
    assert!(matches!(data.topology(), SeriesTopology::ArbitraryXY));
    assert_eq!(data.source_len(), 4);
    assert_eq!(data.point_count(), 2);
    assert!(!data.is_empty());

    let gap_only = SeriesData::from_owned_xy_segments(
        SeriesTopology::MonotonicX,
        vec![f64::NAN, f64::INFINITY],
        vec![f64::NAN, f64::NEG_INFINITY],
        Vec::new(),
    )
    .expect("gap-only data is valid");
    assert_eq!(gap_only.source_len(), 2);
    assert_eq!(gap_only.point_count(), 0);
    assert!(!gap_only.is_empty());

    let empty = SeriesData::from_owned_xy(SeriesTopology::MonotonicX, Vec::new(), Vec::new())
        .expect("empty data is valid");
    assert_eq!(empty.source_len(), 0);
    assert_eq!(empty.point_count(), 0);
    assert!(empty.is_empty());
}

#[test]
fn owned_series_rejects_shape_nonfinite_and_topology_errors() {
    let mismatched = SeriesData::from_owned_xy(SeriesTopology::ArbitraryXY, vec![0.0], vec![])
        .err()
        .expect("array lengths must match");
    assert_code(&mismatched, "invalid-input", "input");

    let nonfinite = SeriesData::from_owned_xy(
        SeriesTopology::ArbitraryXY,
        vec![0.0, f64::NAN],
        vec![1.0, 2.0],
    )
    .err()
    .expect("covered values must be finite");
    assert_code(&nonfinite, "invalid-input", "input");

    let reversal =
        SeriesData::from_owned_xy(SeriesTopology::MonotonicX, vec![2.0, 1.0], vec![1.0, 2.0])
            .err()
            .expect("monotonic x cannot reverse");
    assert_code(&reversal, "invalid-input", "input");

    let invalid_segments = SeriesData::from_owned_xy_segments(
        SeriesTopology::ArbitraryXY,
        vec![0.0, 1.0, 2.0],
        vec![0.0, 1.0, 2.0],
        vec![0..2, 2..3],
    )
    .err()
    .expect("segments must be strictly separated");
    assert_code(&invalid_segments, "invalid-input", "input");
}

#[test]
fn scene_transactions_publish_revisions_and_immutable_snapshots() {
    let mut scene = PlotScene::new(linear_view(), linear_scales()).expect("scene");
    let initial = scene.revision();
    let old_snapshot = scene.snapshot();
    assert_eq!(old_snapshot.revision(), initial);
    assert_eq!(old_snapshot.canonical_view().x().min(), 0.0);
    assert_eq!(old_snapshot.viewport().y().max(), 10.0);
    assert!(matches!(old_snapshot.axis_scales().x(), AxisScale::Linear));

    let receipt = scene.transaction().commit().expect("no-op commit");
    assert!(!receipt.changed());
    assert_eq!(receipt.revision(), initial);
    assert_eq!(scene.revision(), initial);

    let receipt = {
        let mut transaction = scene.transaction();
        transaction
            .set_viewport(Viewport::from_bounds(1.0, 9.0, 2.0, 8.0).expect("viewport"))
            .expect("viewport edit");
        transaction.commit().expect("view commit")
    };
    assert!(receipt.changed());
    assert_eq!(receipt.revision(), scene.revision());
    assert_eq!(old_snapshot.revision(), initial);
    assert_eq!(old_snapshot.viewport().x().min(), 0.0);
    assert_eq!(scene.snapshot().viewport().x().min(), 1.0);
}

#[test]
fn scene_replace_scale_and_failed_operation_reuse_are_atomic() {
    let mut scene = PlotScene::new(linear_view(), linear_scales()).expect("scene");
    let mut transaction = scene.transaction();
    transaction
        .set_viewport(Viewport::from_bounds(1.0, 9.0, 1.0, 9.0).expect("viewport"))
        .expect("first edit");
    let error = transaction
        .set_axis_scales(AxisScales::new(AxisScale::Log10, AxisScale::Linear))
        .expect_err("canonical view is invalid for log x");
    assert_code(&error, "invalid-input", "input");
    let receipt = transaction.commit().expect("earlier edit remains usable");
    assert!(receipt.changed());
    assert_eq!(scene.snapshot().viewport().x().min(), 1.0);

    let replacement = Viewport::from_bounds(2.0, 8.0, 2.0, 8.0).expect("replacement");
    let receipt = {
        let mut transaction = scene.transaction();
        transaction
            .replace_canonical_view(replacement)
            .expect("canonical replacement");
        transaction.commit().expect("replacement commit")
    };
    assert!(receipt.changed());
    let snapshot = scene.snapshot();
    assert_eq!(snapshot.canonical_view().x().min(), 2.0);
    assert_eq!(snapshot.viewport().x().min(), 2.0);
}

#[test]
fn scene_add_append_abort_and_ids_follow_ownership_rules() {
    let mut scene = PlotScene::new(linear_view(), linear_scales()).expect("scene");
    let old_snapshot = scene.snapshot();
    let first_id = {
        let mut transaction = scene.transaction();
        let id = transaction
            .add_series(monotonic_data(&[1.0, 2.0]))
            .expect("add series");
        transaction
            .append_series(id, monotonic_data_at(1.0, &[3.0, 4.0]))
            .expect("append matching topology");
        transaction.commit().expect("data commit");
        id
    };
    assert_ne!(scene.revision(), old_snapshot.revision());
    let aborted_id = {
        let mut transaction = scene.transaction();
        let aborted_id = transaction.add_series(monotonic_data(&[5.0])).expect("add");
        transaction.abort();
        aborted_id
    };
    assert_ne!(first_id, aborted_id);

    let revision_after_add = scene.revision();
    let mut transaction = scene.transaction();
    let unknown_append = transaction
        .append_series(aborted_id, monotonic_data(&[7.0]))
        .expect_err("aborted id is not live");
    assert_code(&unknown_append, "resource-invalid", "resource");
    transaction
        .add_series(monotonic_data(&[8.0]))
        .expect("failed operation does not poison transaction");
    transaction.commit().expect("reused transaction");
    assert!(scene.revision() != revision_after_add);
}

#[test]
fn append_topology_and_empty_source_rules_are_observable() {
    let mut scene = PlotScene::new(linear_view(), linear_scales()).expect("scene");
    let id = {
        let mut transaction = scene.transaction();
        let id = transaction
            .add_series(monotonic_data(&[1.0]))
            .expect("add series");
        transaction.commit().expect("add commit");
        id
    };

    let revision = scene.revision();
    let receipt = {
        let mut transaction = scene.transaction();
        transaction
            .append_series(
                id,
                SeriesData::from_owned_xy(SeriesTopology::MonotonicX, Vec::new(), Vec::new())
                    .expect("empty append"),
            )
            .expect("empty append is valid");
        transaction.commit().expect("empty append commit")
    };
    assert!(!receipt.changed());
    assert_eq!(scene.revision(), revision);

    let error = {
        let mut transaction = scene.transaction();
        let error = transaction
            .append_series(
                id,
                SeriesData::from_owned_xy(SeriesTopology::ArbitraryXY, vec![2.0], vec![3.0])
                    .expect("arbitrary data"),
            )
            .expect_err("topology must match");
        transaction.abort();
        error
    };
    assert_eq!(error.code().as_str(), "invalid-input");

    let receipt = {
        let mut transaction = scene.transaction();
        transaction
            .append_series(
                id,
                SeriesData::from_owned_xy_segments(
                    SeriesTopology::MonotonicX,
                    vec![f64::NAN, f64::NAN],
                    vec![f64::NAN, f64::NAN],
                    Vec::new(),
                )
                .expect("gap-only append"),
            )
            .expect("gap-only append is valid");
        transaction.commit().expect("gap-only append commit")
    };
    assert!(receipt.changed());
}

#[test]
fn facade_identity_types_have_exact_positive_trait_bounds() {
    assert_snapshot_traits::<SceneSnapshot>();
    assert_id_traits::<SceneRevision>();
    assert_id_traits::<SeriesId>();

    let id = {
        let mut scene = PlotScene::new(linear_view(), linear_scales()).expect("scene");
        let mut transaction = scene.transaction();
        let id = transaction
            .add_series(monotonic_data(&[1.0]))
            .expect("series");
        transaction.abort();
        id
    };
    let mut hasher = DefaultHasher::new();
    id.hash(&mut hasher);
    let _ = hasher.finish();
}
