//! Standalone viewer edge over the native facade and runtime lifecycle.
//!
//! [`Viewer`] owns the native [`lumenplot::PlotScene`] and keeps it as the
//! semantic authority.  [`EngineSession`] owns only runtime lifecycle state
//! and (when attached) portable backend resources.  This crate intentionally
//! does not add a window-system transport, a persistence format, or a second
//! retained scene model.

#![forbid(unsafe_code)]

use lumenplot::{PlotScene, SceneRevision, SceneSnapshot};
use lumenplot_runtime::{
    DeviceGeneration, EngineSession, LifecycleOutcome, LoopMode, LoopOutcome, RuntimeError,
    SessionState, SurfaceId, SurfaceState,
};

/// Native viewer edge over one authoritative [`PlotScene`].
pub struct Viewer {
    scene: PlotScene,
    session: EngineSession,
}

impl Viewer {
    /// Creates a viewer with an explicit native-owned or host-pumped mode.
    ///
    /// The constructor creates a lifecycle shell and does not probe a GPU.
    /// Use [`EngineSession::try_new`] and [`Self::with_session`] when a real
    /// portable backend is required.
    pub fn new(scene: PlotScene, loop_mode: LoopMode) -> Self {
        Self {
            scene,
            session: EngineSession::new(loop_mode),
        }
    }

    /// Wraps a caller-created runtime session without moving scene authority.
    pub fn with_session(scene: PlotScene, session: EngineSession) -> Self {
        Self { scene, session }
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
        self.session.run_native_loop()
    }

    /// Pumps one explicit host-owned loop iteration.
    pub fn pump(&mut self) -> Result<LoopOutcome, RuntimeError> {
        self.session.pump_once()
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
    fn show_and_pump_follow_the_declared_loop_mode() {
        let mut native = Viewer::new(scene(), LoopMode::NativeOwned);
        assert_eq!(
            native.show().expect("native show"),
            LoopOutcome::NativeLoopEntered
        );
        assert_eq!(
            native
                .pump()
                .expect_err("native viewer is not host-pumped")
                .kind(),
            lumenplot_runtime::RuntimeErrorKind::HostLoopMisuse
        );

        let mut host = Viewer::new(scene(), LoopMode::HostPumped);
        assert_eq!(
            host.pump().expect("host pump"),
            LoopOutcome::HostPumpCompleted
        );
        assert_eq!(
            host.show().expect_err("host retains loop ownership").kind(),
            lumenplot_runtime::RuntimeErrorKind::HostLoopMisuse
        );
    }

    #[test]
    fn viewer_delegates_surface_and_terminal_lifecycle_without_resurrection() {
        let mut viewer = Viewer::new(scene(), LoopMode::HostPumped);
        viewer.pump().expect("host pump");
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
}
