//! Bounded Phase-1B evidence for the view-history state substrate:
//! `LP-FUNC-008`/`AT-FUNC-HISTORY`, `LP-UX-012`/`AT-FUNC-HISTORY`, and
//! `LP-UX-013`/`AT-SEM-STATE-REVISION` over the accepted API-0001 surface.

use lumenplot::{AxisScale, AxisScales, PlotScene, PublicError, Viewport};

const CANONICAL: [f64; 4] = [0.0, 10.0, 0.0, 10.0];

fn view(x_min: f64, x_max: f64, y_min: f64, y_max: f64) -> Viewport {
    Viewport::from_bounds(x_min, x_max, y_min, y_max).expect("valid view")
}

fn linear_scales() -> AxisScales {
    AxisScales::new(AxisScale::Linear, AxisScale::Linear)
}

fn linear_scene() -> PlotScene {
    PlotScene::new(view(0.0, 10.0, 0.0, 10.0), linear_scales()).expect("scene")
}

fn assert_view(actual: Viewport, expected: [f64; 4]) {
    assert_eq!(actual.x().min(), expected[0]);
    assert_eq!(actual.x().max(), expected[1]);
    assert_eq!(actual.y().min(), expected[2]);
    assert_eq!(actual.y().max(), expected[3]);
}

fn assert_canonical(snapshot: &lumenplot::SceneSnapshot, expected: [f64; 4]) {
    assert_view(snapshot.canonical_view(), expected);
}

fn assert_code(error: &PublicError, code: &str) {
    assert_eq!(error.code().as_str(), code);
}

#[test]
fn home_restores_the_stored_canonical_view() {
    let mut scene = linear_scene();
    let mut revision = scene.revision();

    // Interactive pan and zoom move only the current viewport; each commit
    // advances the revision exactly once and leaves the stored canonical
    // view untouched.
    for viewport in [[1.0, 9.0, 2.0, 8.0], [3.0, 6.0, 3.0, 6.0]] {
        let receipt = {
            let mut transaction = scene.transaction();
            transaction
                .set_viewport(view(viewport[0], viewport[1], viewport[2], viewport[3]))
                .expect("viewport edit");
            transaction.commit().expect("view commit")
        };
        assert!(receipt.changed());
        assert_ne!(receipt.revision(), revision);
        revision = receipt.revision();
        let snapshot = scene.snapshot();
        assert_view(snapshot.viewport(), viewport);
        assert_canonical(&snapshot, CANONICAL);
    }

    // Home/Reset reads the stored canonical view out of the snapshot and
    // restores it as the current viewport; the stored canonical itself is
    // unchanged by the restoration.
    let stored = scene.snapshot().canonical_view();
    let home = Viewport::from_bounds(
        stored.x().min(),
        stored.x().max(),
        stored.y().min(),
        stored.y().max(),
    )
    .expect("restored home view");
    let receipt = {
        let mut transaction = scene.transaction();
        transaction.set_viewport(home).expect("home edit");
        transaction.commit().expect("home commit")
    };
    assert!(receipt.changed());
    assert_ne!(receipt.revision(), revision);
    revision = receipt.revision();
    let snapshot = scene.snapshot();
    assert_view(snapshot.viewport(), CANONICAL);
    assert_canonical(&snapshot, CANONICAL);

    // Redefining Home replaces the stored canonical and current view
    // together; later interaction leaves the new Home intact and a second
    // Home restores it again.
    const NEW_HOME: [f64; 4] = [5.0, 7.0, 4.0, 8.0];
    let receipt = {
        let mut transaction = scene.transaction();
        transaction
            .replace_canonical_view(view(5.0, 7.0, 4.0, 8.0))
            .expect("Home replacement");
        transaction.commit().expect("Home replacement commit")
    };
    assert!(receipt.changed());
    assert_ne!(receipt.revision(), revision);
    revision = receipt.revision();
    let receipt = {
        let mut transaction = scene.transaction();
        transaction
            .set_viewport(view(1.0, 3.0, 1.0, 3.0))
            .expect("pan away from new Home");
        transaction.commit().expect("pan commit")
    };
    assert!(receipt.changed());
    assert_ne!(receipt.revision(), revision);
    revision = receipt.revision();
    assert_canonical(&scene.snapshot(), NEW_HOME);

    let stored = scene.snapshot().canonical_view();
    let home = Viewport::from_bounds(
        stored.x().min(),
        stored.x().max(),
        stored.y().min(),
        stored.y().max(),
    )
    .expect("restored new home view");
    let receipt = {
        let mut transaction = scene.transaction();
        transaction.set_viewport(home).expect("second home edit");
        transaction.commit().expect("second home commit")
    };
    assert!(receipt.changed());
    let snapshot = scene.snapshot();
    assert_view(snapshot.viewport(), NEW_HOME);
    assert_canonical(&snapshot, NEW_HOME);
    assert_ne!(snapshot.revision(), revision);
}

#[test]
fn interactive_viewport_changes_leave_the_canonical_view_stable() {
    let mut scene = linear_scene();
    let baseline = scene.snapshot();
    let revision_at_baseline = baseline.revision();
    let mut revision = revision_at_baseline;

    // A pan/zoom sequence including a return to the canonical frame never
    // moves the stored canonical view; every commit steps the revision
    // exactly once and freezes prior snapshot observations.
    let interactions = [
        [1.0, 9.0, 1.0, 9.0],
        [0.0, 2.0, 8.0, 10.0],
        [4.0, 4.5, 0.0, 10.0],
        CANONICAL,
    ];
    for viewport in interactions {
        let receipt = {
            let mut transaction = scene.transaction();
            transaction
                .set_viewport(view(viewport[0], viewport[1], viewport[2], viewport[3]))
                .expect("interaction edit");
            transaction.commit().expect("interaction commit")
        };
        assert!(receipt.changed());
        assert_ne!(receipt.revision(), revision);
        revision = receipt.revision();

        let snapshot = scene.snapshot();
        assert_view(snapshot.viewport(), viewport);
        assert_canonical(&snapshot, CANONICAL);
        assert_eq!(snapshot.revision(), scene.revision());

        assert_eq!(baseline.revision(), revision_at_baseline);
        assert_view(baseline.viewport(), CANONICAL);
        assert_canonical(&baseline, CANONICAL);
    }
}

#[test]
fn canonical_and_view_edits_validate_against_current_scales_atomically() {
    // Positive canonical domain on linear scales; switching to log scales
    // validates both staged views before applying atomically.
    let mut scene = PlotScene::new(view(1.0, 10.0, 1.0, 10.0), linear_scales()).expect("scene");
    let mut transaction = scene.transaction();
    transaction
        .set_viewport(view(2.0, 8.0, 2.0, 8.0))
        .expect("staged viewport");
    transaction
        .set_axis_scales(AxisScales::new(AxisScale::Log10, AxisScale::Log10))
        .expect("log scales accept both staged views");
    let error = transaction
        .replace_canonical_view(view(0.0, 5.0, 0.0, 5.0))
        .expect_err("log scales reject a nonpositive canonical range");
    assert_code(&error, "invalid-input");
    let receipt = transaction
        .commit()
        .expect("earlier staged edits remain usable");
    assert!(receipt.changed());
    let snapshot = scene.snapshot();
    assert_view(snapshot.viewport(), [2.0, 8.0, 2.0, 8.0]);
    assert_view(snapshot.canonical_view(), [1.0, 10.0, 1.0, 10.0]);
    assert!(matches!(snapshot.axis_scales().x(), AxisScale::Log10));
    assert!(matches!(snapshot.axis_scales().y(), AxisScale::Log10));

    // With log scales active, a nonpositive current viewport is refused at
    // staging time and leaves nothing behind.
    let mut transaction = scene.transaction();
    let error = transaction
        .set_viewport(view(0.0, 8.0, 2.0, 8.0))
        .expect_err("log scales reject a nonpositive viewport");
    assert_code(&error, "invalid-input");
    let receipt = transaction
        .commit()
        .expect("refusal keeps the commit usable");
    assert!(!receipt.changed());
    assert_view(scene.snapshot().viewport(), [2.0, 8.0, 2.0, 8.0]);

    // A canonical replacement also re-homes the current viewport onto the
    // canonical frame; on the panned scene above it therefore changes state.
    let revision = scene.revision();
    let receipt = {
        let mut transaction = scene.transaction();
        transaction
            .replace_canonical_view(view(1.0, 10.0, 1.0, 10.0))
            .expect("canonical replacement");
        transaction.commit().expect("replacement commit")
    };
    assert!(receipt.changed());
    assert_ne!(scene.revision(), revision);
    let snapshot = scene.snapshot();
    assert_view(snapshot.viewport(), [1.0, 10.0, 1.0, 10.0]);
    assert_view(snapshot.canonical_view(), [1.0, 10.0, 1.0, 10.0]);

    // Repeating every effective value is an effective no-op.
    let revision = scene.revision();
    let receipt = {
        let mut transaction = scene.transaction();
        transaction
            .replace_canonical_view(view(1.0, 10.0, 1.0, 10.0))
            .expect("identical canonical replacement");
        transaction.commit().expect("no-op commit")
    };
    assert!(!receipt.changed());
    assert_eq!(scene.revision(), revision);
}

#[test]
fn view_transitions_follow_noop_and_negative_zero_equality_rules() {
    let mut scene = linear_scene();
    let revision = scene.revision();

    // Restaging the identical viewport is an effective no-op.
    let receipt = {
        let mut transaction = scene.transaction();
        transaction
            .set_viewport(view(0.0, 10.0, 0.0, 10.0))
            .expect("identical viewport edit");
        transaction.commit().expect("identical viewport commit")
    };
    assert!(!receipt.changed());
    assert_eq!(scene.revision(), revision);

    // Finite numeric equality treats -0.0 == 0.0, so a signed-zero-only
    // difference is still a no-op.
    let receipt = {
        let mut transaction = scene.transaction();
        transaction
            .set_viewport(view(-0.0, 10.0, -0.0, 10.0))
            .expect("negative zero viewport edit");
        transaction.commit().expect("negative zero viewport commit")
    };
    assert!(!receipt.changed());
    assert_eq!(scene.revision(), revision);

    // Multiple staged view edits inside one transaction collapse into a
    // single change; the last staged value wins.
    let receipt = {
        let mut transaction = scene.transaction();
        transaction
            .set_viewport(view(1.0, 9.0, 1.0, 9.0))
            .expect("first staged viewport");
        transaction
            .set_viewport(view(2.0, 8.0, 2.0, 8.0))
            .expect("second staged viewport");
        transaction.commit().expect("collapsed view commit")
    };
    assert!(receipt.changed());
    let snapshot = scene.snapshot();
    assert_view(snapshot.viewport(), [2.0, 8.0, 2.0, 8.0]);
    assert_canonical(&snapshot, CANONICAL);
    assert_ne!(scene.revision(), revision);

    // An aborted transaction discards its staged edit entirely.
    let revision = scene.revision();
    {
        let mut transaction = scene.transaction();
        transaction
            .set_viewport(view(3.0, 7.0, 3.0, 7.0))
            .expect("aborted viewport edit");
        transaction.abort();
    }
    assert_eq!(scene.revision(), revision);
    assert_view(scene.snapshot().viewport(), [2.0, 8.0, 2.0, 8.0]);
}
