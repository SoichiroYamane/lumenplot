//! Standalone viewer edge over the native facade and runtime lifecycle.
//!
//! [`Viewer`] owns the native [`lumenplot::PlotScene`] and keeps it as the
//! semantic authority.  [`EngineSession`] owns only runtime lifecycle state
//! and (when attached) portable backend resources.  This crate intentionally
//! does not add a window-system transport, a persistence format, or a second
//! retained scene model.

#![forbid(unsafe_code)]
#![cfg_attr(not(test), allow(dead_code))]

use lumenplot::{PlotScene, PublicError, SceneRevision, SceneSnapshot, Viewport};
use lumenplot_runtime::{
    DeviceGeneration, EngineSession, LifecycleOutcome, LoopMode, LoopOutcome, RuntimeError,
    SessionState, SurfaceId, SurfaceState,
};

/// Native viewer edge over one authoritative [`PlotScene`].
pub struct Viewer {
    scene: PlotScene,
    session: EngineSession,
    history: ViewerHistory,
    focus: Option<ViewerFocus>,
    pending: Option<[f64; 4]>,
}

impl Viewer {
    /// Creates a viewer with an explicit native-owned or host-pumped mode.
    ///
    /// The constructor creates a lifecycle shell and does not probe a GPU.
    /// Use [`EngineSession::try_new`] and [`Self::with_session`] when a real
    /// portable backend is required.
    pub fn new(scene: PlotScene, loop_mode: LoopMode) -> Self {
        let history = ViewerHistory::new(viewport_bounds(&scene.snapshot().viewport()));
        Self {
            scene,
            session: EngineSession::new(loop_mode),
            history,
            focus: None,
            pending: None,
        }
    }

    /// Wraps a caller-created runtime session without moving scene authority.
    pub fn with_session(scene: PlotScene, session: EngineSession) -> Self {
        let history = ViewerHistory::new(viewport_bounds(&scene.snapshot().viewport()));
        Self {
            scene,
            session,
            history,
            focus: None,
            pending: None,
        }
    }

    /// Borrows the authoritative native scene.
    pub fn scene(&self) -> &PlotScene {
        &self.scene
    }

    /// Mutably borrows the authoritative native scene for a transaction.
    pub fn scene_mut(&mut self) -> &mut PlotScene {
        &mut self.scene
    }

    /// Captures an immutable scene snapshot without transferring authority.
    pub fn snapshot(&self) -> SceneSnapshot {
        self.scene.snapshot()
    }

    /// Current authoritative scene revision.
    pub fn revision(&self) -> SceneRevision {
        self.scene.revision()
    }

    /// Declared loop ownership mode.
    pub const fn loop_mode(&self) -> LoopMode {
        self.session.loop_mode()
    }

    /// Current runtime lifecycle state.
    pub const fn state(&self) -> SessionState {
        self.session.state()
    }

    /// Whether explicit close has completed.
    pub const fn is_closed(&self) -> bool {
        self.session.is_closed()
    }

    /// Enters the explicit standalone native-owned loop boundary.
    pub fn show(&mut self) -> Result<LoopOutcome, RuntimeError> {
        self.enter_native_loop()
    }

    /// Creates one session-owned logical surface.
    pub fn create_surface(&mut self, size: [u32; 2]) -> Result<SurfaceId, RuntimeError> {
        self.session.create_surface(size)
    }

    /// Observes one logical surface's lifecycle state.
    pub fn surface_state(&self, id: SurfaceId) -> Result<SurfaceState, RuntimeError> {
        self.session.surface_state(id)
    }

    /// Observes one logical surface's configured size.
    pub fn surface_size(&self, id: SurfaceId) -> Result<[u32; 2], RuntimeError> {
        self.session.surface_size(id)
    }

    /// Records a surface resize.
    pub fn resize(
        &mut self,
        id: SurfaceId,
        size: [u32; 2],
    ) -> Result<LifecycleOutcome, RuntimeError> {
        self.session.resize(id, size)
    }

    /// Suspends a surface without a busy submission retry.
    pub fn suspend(&mut self, id: SurfaceId) -> Result<LifecycleOutcome, RuntimeError> {
        self.session.suspend(id)
    }

    /// Resumes a surface and schedules reconfiguration.
    pub fn resume(&mut self, id: SurfaceId) -> Result<LifecycleOutcome, RuntimeError> {
        self.session.resume(id)
    }

    /// Records and explicitly recovers surface loss.
    pub fn handle_surface_loss(&mut self, id: SurfaceId) -> Result<LifecycleOutcome, RuntimeError> {
        self.session.handle_surface_loss(id)
    }

    /// Recreates a previously lost surface through the owner session.
    pub fn recreate_surface(&mut self, id: SurfaceId) -> Result<LifecycleOutcome, RuntimeError> {
        self.session.recreate_surface(id)
    }

    /// Records device loss and invalidates runtime-owned resources.
    pub fn handle_device_loss(&mut self) -> Result<LifecycleOutcome, RuntimeError> {
        self.session.handle_device_loss()
    }

    /// Attempts runtime-owned device rebuild from the retained native state.
    pub fn recover_device(&mut self) -> Result<LifecycleOutcome, RuntimeError> {
        self.session.recover_device()
    }

    /// Records terminal out-of-memory behavior.
    pub fn handle_out_of_memory(&mut self) -> Result<LifecycleOutcome, RuntimeError> {
        self.session.handle_out_of_memory()
    }

    /// Closes the viewer and its runtime session idempotently.
    pub fn close(&mut self) -> Result<LifecycleOutcome, RuntimeError> {
        self.session.close()
    }

    /// Exposes the runtime's current device generation for lifecycle evidence.
    pub const fn device_generation(&self) -> DeviceGeneration {
        self.session.device_generation()
    }
}

// M4-B1 private viewer application seam.
//
// Headless, dependency-free application of the accepted pan/zoom/box,
// Home, history, cancel, and focus semantics over the authoritative
// `PlotScene`. Each committed semantic transition uses exactly one facade
// transaction so the scene revision advances exactly once; transient focus
// and pending-gesture state never enter the scene or ordinary exports.
// Cursor/measurement, Legend/annotation state, text, and accessibility work
// are M5 and are never added here. Real pointer-coordinate conversion, drag
// state, and double-click timing remain future work; view steps below are
// deterministic headless fractions around the center.

const VIEWER_HISTORY_LIMIT: usize = 64;

#[derive(Clone, Debug)]
struct ViewerHistory {
    entries: Vec<[f64; 4]>,
    index: usize,
}

impl ViewerHistory {
    fn new(canonical: [f64; 4]) -> Self {
        Self {
            entries: vec![canonical],
            index: 0,
        }
    }

    fn current(&self) -> [f64; 4] {
        self.entries[self.index]
    }

    fn push(&mut self, view: [f64; 4]) -> bool {
        if self.entries[self.index] == view {
            return false;
        }
        self.entries.truncate(self.index + 1);
        self.entries.push(view);
        self.index += 1;
        if self.entries.len() > VIEWER_HISTORY_LIMIT {
            self.entries.remove(0);
            self.index -= 1;
        }
        true
    }

    fn previous(&mut self) -> Option<[f64; 4]> {
        if self.index == 0 {
            None
        } else {
            self.index -= 1;
            Some(self.entries[self.index])
        }
    }

    fn next(&mut self) -> Option<[f64; 4]> {
        if self.index + 1 >= self.entries.len() {
            None
        } else {
            self.index += 1;
            Some(self.entries[self.index])
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ViewerFocus {
    Plot,
    Legend,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ViewerAxis {
    Both,
    X,
    Y,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ViewerDirection {
    Left,
    Right,
    Up,
    Down,
}

fn viewport_bounds(view: &Viewport) -> [f64; 4] {
    [
        view.x().min(),
        view.x().max(),
        view.y().min(),
        view.y().max(),
    ]
}

fn bounds_to_viewport(bounds: [f64; 4]) -> Result<Viewport, PublicError> {
    Viewport::from_bounds(bounds[0], bounds[1], bounds[2], bounds[3])
}

fn pan_bounds(current: [f64; 4], axis: ViewerAxis) -> [f64; 4] {
    let x_shift = (current[1] - current[0]) * 0.1;
    let y_shift = (current[3] - current[2]) * 0.1;
    match axis {
        ViewerAxis::Both => [
            current[0] + x_shift,
            current[1] + x_shift,
            current[2] + y_shift,
            current[3] + y_shift,
        ],
        ViewerAxis::X => [
            current[0] + x_shift,
            current[1] + x_shift,
            current[2],
            current[3],
        ],
        ViewerAxis::Y => [
            current[0],
            current[1],
            current[2] + y_shift,
            current[3] + y_shift,
        ],
    }
}

fn zoom_bounds(current: [f64; 4], axis: ViewerAxis) -> [f64; 4] {
    const FACTOR: f64 = 0.8;
    let center_x = (current[0] + current[1]) * 0.5;
    let center_y = (current[2] + current[3]) * 0.5;
    let half_x = (current[1] - current[0]) * 0.5 * FACTOR;
    let half_y = (current[3] - current[2]) * 0.5 * FACTOR;
    match axis {
        ViewerAxis::Both => [
            center_x - half_x,
            center_x + half_x,
            center_y - half_y,
            center_y + half_y,
        ],
        ViewerAxis::X => [center_x - half_x, center_x + half_x, current[2], current[3]],
        ViewerAxis::Y => [current[0], current[1], center_y - half_y, center_y + half_y],
    }
}

fn box_bounds(current: [f64; 4], axis: ViewerAxis) -> [f64; 4] {
    let center_x = (current[0] + current[1]) * 0.5;
    let center_y = (current[2] + current[3]) * 0.5;
    let quarter_x = (current[1] - current[0]) * 0.25;
    let quarter_y = (current[3] - current[2]) * 0.25;
    match axis {
        ViewerAxis::Both => [
            center_x - quarter_x,
            center_x + quarter_x,
            center_y - quarter_y,
            center_y + quarter_y,
        ],
        ViewerAxis::X => [
            center_x - quarter_x,
            center_x + quarter_x,
            current[2],
            current[3],
        ],
        ViewerAxis::Y => [
            current[0],
            current[1],
            center_y - quarter_y,
            center_y + quarter_y,
        ],
    }
}

fn navigate_bounds(current: [f64; 4], direction: ViewerDirection) -> [f64; 4] {
    let x_shift = (current[1] - current[0]) * 0.1;
    let y_shift = (current[3] - current[2]) * 0.1;
    match direction {
        ViewerDirection::Left => [
            current[0] - x_shift,
            current[1] - x_shift,
            current[2],
            current[3],
        ],
        ViewerDirection::Right => [
            current[0] + x_shift,
            current[1] + x_shift,
            current[2],
            current[3],
        ],
        ViewerDirection::Up => [
            current[0],
            current[1],
            current[2] + y_shift,
            current[3] + y_shift,
        ],
        ViewerDirection::Down => [
            current[0],
            current[1],
            current[2] - y_shift,
            current[3] - y_shift,
        ],
    }
}

impl Viewer {
    fn enter_native_loop(&mut self) -> Result<LoopOutcome, RuntimeError> {
        self.session.run_native_loop()
    }

    fn current_bounds(&self) -> [f64; 4] {
        viewport_bounds(&self.scene.snapshot().viewport())
    }

    fn canonical_bounds(&self) -> [f64; 4] {
        viewport_bounds(&self.scene.snapshot().canonical_view())
    }

    fn apply_bounds(&mut self, next: [f64; 4]) -> Result<bool, PublicError> {
        let view = bounds_to_viewport(next)?;
        let mut transaction = self.scene.transaction();
        transaction.set_viewport(view)?;
        let receipt = transaction.commit()?;
        if receipt.changed() {
            self.history.push(next);
            self.pending = None;
        }
        Ok(receipt.changed())
    }

    fn apply_bounds_without_history_push(&mut self, next: [f64; 4]) -> Result<bool, PublicError> {
        let view = bounds_to_viewport(next)?;
        let mut transaction = self.scene.transaction();
        transaction.set_viewport(view)?;
        let receipt = transaction.commit()?;
        if receipt.changed() {
            self.pending = None;
        }
        Ok(receipt.changed())
    }

    fn apply_pan(&mut self, axis: ViewerAxis) -> Result<bool, PublicError> {
        let next = pan_bounds(self.current_bounds(), axis);
        self.apply_bounds(next)
    }

    fn apply_zoom(&mut self, axis: ViewerAxis) -> Result<bool, PublicError> {
        let next = zoom_bounds(self.current_bounds(), axis);
        self.apply_bounds(next)
    }

    fn apply_box(&mut self, axis: ViewerAxis) -> Result<bool, PublicError> {
        let next = box_bounds(self.current_bounds(), axis);
        self.apply_bounds(next)
    }

    fn apply_navigate(&mut self, direction: ViewerDirection) -> Result<bool, PublicError> {
        let next = navigate_bounds(self.current_bounds(), direction);
        self.apply_bounds(next)
    }

    fn apply_home(&mut self) -> Result<bool, PublicError> {
        let next = self.canonical_bounds();
        self.apply_bounds(next)
    }

    fn apply_history_previous(&mut self) -> Result<bool, PublicError> {
        let Some(view) = self.history.previous() else {
            return Ok(false);
        };
        self.apply_bounds_without_history_push(view)
    }

    fn apply_history_next(&mut self) -> Result<bool, PublicError> {
        let Some(view) = self.history.next() else {
            return Ok(false);
        };
        self.apply_bounds_without_history_push(view)
    }

    fn move_focus_next(&mut self) -> Option<ViewerFocus> {
        let next = match self.focus {
            None => Some(ViewerFocus::Plot),
            Some(ViewerFocus::Plot) => Some(ViewerFocus::Legend),
            Some(ViewerFocus::Legend) => Some(ViewerFocus::Plot),
        };
        self.focus = next;
        next
    }

    fn move_focus_previous(&mut self) -> Option<ViewerFocus> {
        let next = match self.focus {
            None => Some(ViewerFocus::Legend),
            Some(ViewerFocus::Plot) => Some(ViewerFocus::Legend),
            Some(ViewerFocus::Legend) => Some(ViewerFocus::Plot),
        };
        self.focus = next;
        next
    }

    fn buffer_pan(&mut self, axis: ViewerAxis) {
        let base = self.pending.unwrap_or_else(|| self.current_bounds());
        self.pending = Some(pan_bounds(base, axis));
    }

    fn commit_pending(&mut self) -> Result<bool, PublicError> {
        let Some(view) = self.pending else {
            return Ok(false);
        };
        self.apply_bounds(view)
    }

    fn cancel_pending(&mut self) {
        self.pending = None;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use lumenplot::{AxisScale, AxisScales, Viewport};

    fn scene() -> PlotScene {
        PlotScene::new(
            Viewport::from_bounds(0.0, 1.0, 0.0, 1.0).expect("viewport"),
            AxisScales::new(AxisScale::Linear, AxisScale::Linear),
        )
        .expect("scene")
    }

    #[test]
    fn viewer_keeps_plotscene_as_the_authority() {
        let mut viewer = Viewer::new(scene(), LoopMode::NativeOwned);
        let initial = viewer.revision();
        let snapshot = viewer.snapshot();
        assert_eq!(snapshot.revision(), initial);

        let next_view = Viewport::from_bounds(-1.0, 2.0, -1.0, 2.0).expect("next view");
        let mut transaction = viewer.scene_mut().transaction();
        transaction
            .set_viewport(next_view)
            .expect("viewport mutation");
        transaction.commit().expect("commit");

        assert_ne!(viewer.revision(), initial);
        assert_eq!(viewer.snapshot().revision(), viewer.revision());
    }

    #[test]
    fn show_respects_the_declared_loop_mode_without_public_pump_api() {
        let mut native = Viewer::new(scene(), LoopMode::NativeOwned);
        assert_eq!(
            native.show().expect("native show"),
            LoopOutcome::NativeLoopEntered
        );

        let mut host = Viewer::new(scene(), LoopMode::HostPumped);
        assert_eq!(host.loop_mode(), LoopMode::HostPumped);
        assert_eq!(
            host.show().expect_err("host retains loop ownership").kind(),
            lumenplot_runtime::RuntimeErrorKind::HostLoopMisuse
        );
    }

    #[test]
    fn viewer_delegates_surface_and_terminal_lifecycle_without_resurrection() {
        let mut viewer = Viewer::new(scene(), LoopMode::HostPumped);
        let surface = viewer.create_surface([320, 240]).expect("surface");
        assert_eq!(
            viewer.resize(surface, [640, 480]).expect("resize"),
            LifecycleOutcome::Resized
        );
        assert_eq!(
            viewer.handle_surface_loss(surface).expect("surface loss"),
            LifecycleOutcome::SurfaceLost
        );
        assert_eq!(
            viewer.recreate_surface(surface).expect("surface recreate"),
            LifecycleOutcome::SurfaceRecreated
        );
        assert_eq!(
            viewer.handle_out_of_memory().expect("oom"),
            LifecycleOutcome::TerminalOutOfMemory
        );
        assert_eq!(
            viewer.close().expect("close"),
            LifecycleOutcome::CloseRequested
        );
        assert_eq!(
            viewer.close().expect("repeat close"),
            LifecycleOutcome::AlreadyClosed
        );
        assert!(viewer.is_closed());
    }

    #[test]
    fn native_show_requires_observable_close_and_never_resurrects() {
        let mut viewer = Viewer::new(scene(), LoopMode::NativeOwned);
        assert_eq!(viewer.state(), SessionState::Created);
        assert_eq!(
            viewer.show().expect("native show"),
            LoopOutcome::NativeLoopEntered
        );
        assert_eq!(viewer.state(), SessionState::Running);
        assert_eq!(
            viewer.show().expect("idempotent native entry"),
            LoopOutcome::NativeLoopAlreadyRunning
        );
        assert_eq!(
            viewer.close().expect("close"),
            LifecycleOutcome::CloseRequested
        );
        assert!(viewer.is_closed());
        assert_eq!(
            viewer.show().expect_err("closed loop").kind(),
            lumenplot_runtime::RuntimeErrorKind::Closed
        );
        assert_eq!(
            viewer
                .create_surface([64, 64])
                .expect_err("no resurrection")
                .kind(),
            lumenplot_runtime::RuntimeErrorKind::Closed
        );
        assert_eq!(
            viewer.close().expect("repeat close"),
            LifecycleOutcome::AlreadyClosed
        );
    }

    #[test]
    fn viewer_applies_accepted_interactions_with_exactly_once_revision() {
        let mut viewer = Viewer::new(scene(), LoopMode::NativeOwned);
        viewer.show().expect("native show");
        let initial = viewer.revision();
        let canonical = viewer.canonical_bounds();

        assert!(viewer.apply_pan(ViewerAxis::Both).expect("pan"));
        let after_pan = viewer.revision();
        assert_ne!(after_pan, initial);
        assert_eq!(viewer.snapshot().revision(), after_pan);

        assert!(viewer.apply_zoom(ViewerAxis::Both).expect("zoom"));
        let after_zoom = viewer.revision();
        assert_ne!(after_zoom, after_pan);

        assert!(viewer.apply_box(ViewerAxis::Both).expect("box"));
        let after_box = viewer.revision();
        assert_ne!(after_box, after_zoom);

        assert!(
            viewer
                .apply_navigate(ViewerDirection::Right)
                .expect("navigate")
        );
        let after_navigate = viewer.revision();
        assert_ne!(after_navigate, after_box);

        assert!(viewer.apply_home().expect("home"));
        let after_home = viewer.revision();
        assert_ne!(after_home, after_navigate);
        assert_eq!(viewer.current_bounds(), canonical);

        // Home at the canonical view is a no-op and must not advance revision.
        assert!(!viewer.apply_home().expect("no-op home"));
        assert_eq!(viewer.revision(), after_home);

        // History traversal advances exactly once per step; bounds report
        // false without a revision change.
        assert!(viewer.apply_history_previous().expect("history back"));
        let after_back = viewer.revision();
        assert_ne!(after_back, after_home);
        assert!(viewer.apply_history_next().expect("history forward"));
        assert_ne!(viewer.revision(), after_back);
        assert_eq!(viewer.current_bounds(), canonical);

        // Focus moves are transient and never touch the scene revision.
        let revision_before_focus = viewer.revision();
        assert_eq!(viewer.move_focus_next(), Some(ViewerFocus::Plot));
        assert_eq!(viewer.move_focus_next(), Some(ViewerFocus::Legend));
        assert_eq!(viewer.move_focus_previous(), Some(ViewerFocus::Plot));
        assert_eq!(viewer.revision(), revision_before_focus);

        // Coalesced gesture: two buffered pans commit as one revision.
        viewer.buffer_pan(ViewerAxis::Both);
        viewer.buffer_pan(ViewerAxis::Both);
        let before_commit = viewer.revision();
        assert!(viewer.commit_pending().expect("commit"));
        let revision_after_commit = viewer.revision();
        assert_ne!(revision_after_commit, before_commit);
        assert!(!viewer.commit_pending().expect("empty commit"));
        assert_eq!(viewer.pending, None);

        // Cancel leaves scene and revision alone.
        let bounds_before_cancel = viewer.current_bounds();
        viewer.buffer_pan(ViewerAxis::X);
        assert!(viewer.pending.is_some());
        viewer.cancel_pending();
        assert_eq!(viewer.pending, None);
        assert_eq!(viewer.current_bounds(), bounds_before_cancel);
        assert_eq!(viewer.revision(), revision_after_commit);
    }

    #[test]
    fn viewer_history_truncates_forward_tail_on_new_commit() {
        let mut viewer = Viewer::new(scene(), LoopMode::NativeOwned);
        viewer.show().expect("native show");
        viewer.apply_pan(ViewerAxis::Both).expect("pan");
        viewer.apply_pan(ViewerAxis::Both).expect("pan");
        assert_eq!(viewer.history.entries.len(), 3);
        assert_eq!(viewer.history.current(), viewer.current_bounds());
        assert!(viewer.apply_history_previous().expect("back"));
        assert_eq!(viewer.history.index, 1);
        viewer.apply_pan(ViewerAxis::X).expect("new pan");
        assert_eq!(viewer.history.entries.len(), 3);
        assert_eq!(viewer.history.index, 2);
        // Axis-scoped and directional steps keep the headless seam exercised.
        assert!(viewer.apply_pan(ViewerAxis::Y).expect("y pan"));
        assert!(viewer.apply_zoom(ViewerAxis::X).expect("x zoom"));
        assert!(viewer.apply_zoom(ViewerAxis::Y).expect("y zoom"));
        assert!(viewer.apply_box(ViewerAxis::X).expect("x box"));
        assert!(viewer.apply_box(ViewerAxis::Y).expect("y box"));
        assert!(viewer.apply_navigate(ViewerDirection::Left).expect("left"));
        assert!(viewer.apply_navigate(ViewerDirection::Up).expect("up"));
        assert!(viewer.apply_navigate(ViewerDirection::Down).expect("down"));
    }

    #[test]
    #[ignore = "environment required: real native loop, surface, and present cell needed; headless viewer logic is covered above and physical present is never claimed here"]
    fn declared_environment_viewer_launch_is_harness_ready() {
        let mut viewer = Viewer::new(scene(), LoopMode::NativeOwned);
        assert_eq!(
            viewer.show().expect("native show"),
            LoopOutcome::NativeLoopEntered
        );
        let surface = viewer.create_surface([320, 240]).expect("surface");
        viewer.resize(surface, [640, 480]).expect("resize");
        viewer.apply_pan(ViewerAxis::Both).expect("pan");
        assert_eq!(
            viewer.close().expect("close"),
            LifecycleOutcome::CloseRequested
        );
        assert!(viewer.is_closed());
    }
}
