//! M4-PRESENT-1 headless integration slice (must pass without GPU/display).
//!
//! Scope (commander Option-A ruling 2026-09-20): public window-core behavior
//! plus the owner-path explicitness that `present_offscreen` relies on. The
//! direct `present_*` unit coverage lives in `src/present.rs` (crate-internal,
//! `pub(crate)` by §5 non-goals: no new public API); this integration file
//! proves through public seams only that logical counts are preserved, close
//! stays idempotent, and the state-only owner path reports an explicit
//! unavailable outcome instead of silently falling back or inventing pixels.
//! No pixel comparison is performed while the tolerance gate reads OPEN.

use lumenplot_render_api::__internal::{SrgbRgba8, Viewport};
use lumenplot_render_api::{FrameSpec, SceneHandle};
use lumenplot_runtime::{
    EngineSession, LifecycleOutcome, LoopMode, RuntimeErrorKind, SceneRevision, SurfaceCondition,
};
use lumenplot_window::{
    CadenceEvent, CloseOutcome, EventApplied, FrameOutcome, WindowApp, WindowErrorKind, WindowSize,
};

/// Numeric pixel-tolerance status.
///
/// OPEN pending Lavapipe control-cell numbers. No pixel comparison is
/// performed while this reads OPEN.
const GPU_CPU_ORACLE_TOLERANCE_STATUS: &str = "OPEN: numeric GPU-vs-CPU/Agg bound pending Lavapipe control-cell measurement; no fabricated threshold";

const ORACLE_CANVAS: [u32; 2] = [160, 120];
const ORACLE_PLOT_RECT: [u32; 4] = [16, 12, 144, 108];
const ORACLE_LINE_WIDTH_PX: f64 = 1.5;
const ORACLE_DPI: f64 = 100.0;

fn test_size() -> WindowSize {
    WindowSize::new(640, 480).expect("valid size")
}

fn oracle_frame() -> (SceneHandle, FrameSpec) {
    let viewport =
        Viewport::from_bounds(0.0, 1.0, 0.0, 1.0).expect("oracle viewport must be valid");
    let mut scene = SceneHandle::new(viewport).expect("oracle scene must build");
    let points = 64usize;
    let mut xs = Vec::with_capacity(points);
    let mut ys = Vec::with_capacity(points);
    for index in 0..points {
        let t = index as f64 / (points - 1) as f64;
        xs.push(t);
        ys.push(0.1 + 0.8 * t);
    }
    scene
        .add_series(xs, ys)
        .expect("oracle series must be accepted");
    let spec = FrameSpec::new(
        ORACLE_CANVAS,
        ORACLE_PLOT_RECT,
        ORACLE_DPI,
        SrgbRgba8::new(31, 119, 180, 255),
        ORACLE_LINE_WIDTH_PX,
        SrgbRgba8::new(255, 255, 255, 255),
    )
    .expect("oracle spec must be valid");
    (scene, spec)
}

#[test]
fn tolerance_gate_stays_visibly_open() {
    assert_eq!(
        GPU_CPU_ORACLE_TOLERANCE_STATUS.as_bytes()[0],
        b'O',
        "tolerance gate must stay visibly OPEN (no numeric bound claimed)"
    );
}

#[test]
fn stub_program_preserves_logical_counts() {
    let mut app = WindowApp::new(test_size()).expect("core opens headlessly");
    let mut program = lumenplot_window::StubCadence::frames_then_close(3);
    let report = app.run_stub(&mut program);
    assert_eq!(report.frames_accepted(), 3);
    assert_eq!(report.frames_skipped(), 0);
    assert!(report.closed());
    assert!(program.is_exhausted());
}

#[test]
fn resize_reconfigures_occlusion_skips_without_latching() {
    let mut app = WindowApp::new(test_size()).expect("core opens headlessly");
    let next = WindowSize::new(800, 600).expect("valid size");
    assert_eq!(
        app.handle_event(CadenceEvent::Resized(next)),
        Ok(EventApplied::Resized)
    );
    assert_eq!(
        app.handle_event(CadenceEvent::RedrawRequested),
        Ok(EventApplied::Redrawn(FrameOutcome::Reconfigured))
    );
    assert_eq!(
        app.handle_event(CadenceEvent::Occluded(true)),
        Ok(EventApplied::ConditionRecorded)
    );
    assert_eq!(
        app.handle_event(CadenceEvent::RedrawRequested),
        Ok(EventApplied::Redrawn(FrameOutcome::Skipped))
    );
    assert_eq!(
        app.handle_event(CadenceEvent::RedrawRequested),
        Ok(EventApplied::Redrawn(FrameOutcome::Accepted))
    );
    assert_eq!(
        app.handle_event(CadenceEvent::TimedOut),
        Ok(EventApplied::ConditionRecorded)
    );
    assert_eq!(
        app.handle_event(CadenceEvent::RedrawRequested),
        Ok(EventApplied::Redrawn(FrameOutcome::Skipped))
    );
}

#[test]
fn state_only_owner_path_is_explicit_without_backend() {
    let mut session = EngineSession::new(LoopMode::NativeOwned);
    session
        .run_native_loop()
        .expect("native loop entry must succeed");
    let surface = session
        .create_surface(ORACLE_CANVAS)
        .expect("surface must be created");
    let (scene, spec) = oracle_frame();
    let frame = scene
        .resolve_frame(&spec)
        .expect("oracle seam resolution must succeed");
    let token = session
        .begin_submission(SceneRevision::new(1))
        .expect("submission token must issue");
    let error = session
        .submit_frame(surface, frame, token, SurfaceCondition::Ready)
        .expect_err("state-only session must not validate a submission");
    assert_eq!(
        error.kind(),
        RuntimeErrorKind::BackendUnavailable,
        "missing portable backend must be an explicit outcome"
    );
}

#[test]
fn suspend_resume_is_idempotent_without_backend() {
    let mut session = EngineSession::new(LoopMode::NativeOwned);
    session
        .run_native_loop()
        .expect("native loop entry must succeed");
    let surface = session
        .create_surface(ORACLE_CANVAS)
        .expect("surface must be created");
    assert_eq!(
        session.suspend(surface),
        Ok(LifecycleOutcome::Suspended),
        "first suspend must suspend the active surface"
    );
    assert_eq!(
        session.suspend(surface),
        Ok(LifecycleOutcome::AlreadySuspended),
        "second suspend must stay idempotent"
    );
    assert_eq!(
        session.resume(surface),
        Ok(LifecycleOutcome::Resumed),
        "resume must schedule reconfiguration"
    );
    assert_eq!(
        session.resume(surface),
        Ok(LifecycleOutcome::AlreadyActive),
        "resume of an active surface must stay idempotent"
    );
}

#[test]
fn surface_loss_rebuild_is_explicit_without_backend() {
    let mut session = EngineSession::new(LoopMode::NativeOwned);
    session
        .run_native_loop()
        .expect("native loop entry must succeed");
    let surface = session
        .create_surface(ORACLE_CANVAS)
        .expect("surface must be created");
    assert_eq!(
        session.handle_surface_loss(surface),
        Ok(LifecycleOutcome::SurfaceLost),
        "loss must be recorded observably"
    );
    assert_eq!(
        session.handle_surface_loss(surface),
        Ok(LifecycleOutcome::AlreadyLost),
        "repeated loss must stay idempotent"
    );
    assert_eq!(
        session.recreate_surface(surface),
        Ok(LifecycleOutcome::SurfaceRecreated),
        "recreate must rebuild through the owner thread"
    );
    assert_eq!(
        session.suspend(surface),
        Ok(LifecycleOutcome::Suspended),
        "rebuilt surface must accept lifecycle work again"
    );
}

#[test]
fn close_is_idempotent_and_prevents_new_work() {
    let mut app = WindowApp::new(test_size()).expect("core opens headlessly");
    assert_eq!(
        app.handle_event(CadenceEvent::CloseRequested),
        Ok(EventApplied::Closed(CloseOutcome::Closed))
    );
    assert!(app.is_closed());
    assert_eq!(app.request_close(), Ok(CloseOutcome::AlreadyClosed));
    let redraw = app
        .handle_event(CadenceEvent::RedrawRequested)
        .expect_err("post-close redraw must report closed");
    assert_eq!(redraw.kind(), WindowErrorKind::Closed);
    let resize_size = WindowSize::new(640, 480).expect("valid size");
    let resized = app
        .handle_event(CadenceEvent::Resized(resize_size))
        .expect_err("post-close resize must report closed");
    assert_eq!(resized.kind(), WindowErrorKind::Closed);
    assert_eq!(
        WindowErrorKind::BackendUnavailable.as_str(),
        "backend-unavailable",
        "unavailable code stays stable for the present stub"
    );
}
