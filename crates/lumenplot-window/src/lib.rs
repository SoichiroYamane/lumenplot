//! Skeletal M1 window/event host over the runtime lifecycle boundary.
//!
//! Accepted DAG identity (commander ruling 2026-09-13; ADR 0003 amendment):
//! `crates/lumenplot-window` hosts the native window/event loop over
//! `lumenplot-runtime` and `lumenplot-render-wgpu`, with `publish = false`.
//! The only permitted external edge is pinned winit 0.30.x (baseline
//! 0.30.13); no other external dependency is admitted.
//!
//! Main-thread ownership (runtime, surface, GPU device) follows ADR 0005:
//! the [`WindowApp`] core owns one [`EngineSession`](lumenplot_runtime::EngineSession)
//! on the thread that created it, and lower layers never name concrete
//! window types. The only code in this crate that names winit types is the
//! [`WinitHost`] shell and [`run_window`]; the seam below it
//! ([`WindowSize`], [`CadenceEvent`], [`CadenceSource`], [`WindowApp`]) is
//! backend-neutral.
//!
//! M1 scope clamps (skeletal; review is the gate):
//! - One window opens through winit and OS redraw/resize/occlusion/close
//!   events are mapped onto the runtime's public begin/submit lifecycle.
//!   Engine-paced continuous cadence and GPU present from the raw window
//!   handle are M2 work: the runtime logical surface is created and bound,
//!   but no pixels are presented yet and no vsync pump runs here.
//! - The per-frame scene revision is a skeletal owner-side monotonic counter
//!   standing in for the authoritative `PlotScene` revision, which stays
//!   outside the runtime by contract. The facade supplies real revisions in
//!   a later slice.
//! - The `lumenplot-render-wgpu` edge is declared per the accepted DAG but
//!   not yet consumed: surface present is M2, so M1 constructs the session
//!   without probing a GPU backend and stays headless-safe.

#![forbid(unsafe_code)]

use std::collections::VecDeque;

use lumenplot_runtime::{
    EngineSession, LifecycleOutcome, LoopMode, LoopOutcome, RuntimeError, RuntimeErrorKind,
    SceneRevision, SubmissionOutcome, SurfaceCondition, SurfaceId,
};

/// Largest window dimension accepted by the M1 seam, mirroring the runtime
/// surface bound so a validated [`WindowSize`] never fails surface creation.
pub const MAX_WINDOW_DIMENSION: u32 = 16_384;

/// Backend-neutral window size record carried across the seam.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct WindowSize {
    width: u32,
    height: u32,
}

impl WindowSize {
    /// Validate an explicit pixel size. Zero or over-bound dimensions are
    /// rejected so callers observe invalid input instead of a later surface
    /// failure.
    pub const fn new(width: u32, height: u32) -> Result<Self, WindowError> {
        if width == 0 || height == 0 {
            return Err(WindowError::new(
                WindowErrorKind::InvalidInput,
                "window size must be nonzero",
            ));
        }
        if width > MAX_WINDOW_DIMENSION || height > MAX_WINDOW_DIMENSION {
            return Err(WindowError::new(
                WindowErrorKind::InvalidInput,
                "window size exceeds the M1 bound",
            ));
        }
        Ok(Self { width, height })
    }

    /// Pixel width.
    pub const fn width(self) -> u32 {
        self.width
    }

    /// Pixel height.
    pub const fn height(self) -> u32 {
        self.height
    }

    /// Size as a runtime surface extent pair.
    pub const fn as_array(self) -> [u32; 2] {
        [self.width, self.height]
    }
}

/// Stable M1 window operation-error categories.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
#[non_exhaustive]
pub enum WindowErrorKind {
    /// A size, revision, or event argument was invalid.
    InvalidInput,
    /// The window is closed; no new work is accepted.
    Closed,
    /// The loop ownership boundary has not been entered or the state
    /// disallows the operation.
    InvalidState,
    /// A runtime operation ran on the wrong thread or loop mode.
    HostLoopMisuse,
    /// No native event loop or window is available on this host.
    BackendUnavailable,
    /// A backend/lifecycle failure with no narrower M1 category.
    Internal,
}

impl WindowErrorKind {
    /// Stable lowercase operation code for the window boundary.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::InvalidInput => "invalid-input",
            Self::Closed => "closed",
            Self::InvalidState => "invalid-state",
            Self::HostLoopMisuse => "host-loop-misuse",
            Self::BackendUnavailable => "backend-unavailable",
            Self::Internal => "internal",
        }
    }
}

/// Sanitized error returned by an explicit M1 window operation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct WindowError {
    kind: WindowErrorKind,
    message: &'static str,
}

impl WindowError {
    const fn new(kind: WindowErrorKind, message: &'static str) -> Self {
        Self { kind, message }
    }

    /// Machine-readable window failure kind.
    pub const fn kind(self) -> WindowErrorKind {
        self.kind
    }

    /// Stable, sanitized description without backend payloads.
    pub const fn message(self) -> &'static str {
        self.message
    }
}

impl std::fmt::Display for WindowError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(self.message)
    }
}

impl std::error::Error for WindowError {}

/// Map a runtime boundary failure onto the narrower M1 window categories.
/// Lifecycle states the M1 core explicitly handles keep their category;
/// backend/device states with no M1 handling surface as `Internal` with a
/// fixed sanitized message.
const fn map_runtime_error(error: RuntimeError) -> WindowError {
    match error.kind() {
        RuntimeErrorKind::InvalidInput => {
            WindowError::new(WindowErrorKind::InvalidInput, "window input is invalid")
        }
        RuntimeErrorKind::Closed => WindowError::new(WindowErrorKind::Closed, "window is closed"),
        RuntimeErrorKind::InvalidState => {
            WindowError::new(WindowErrorKind::InvalidState, "window state is invalid")
        }
        RuntimeErrorKind::HostLoopMisuse => WindowError::new(
            WindowErrorKind::HostLoopMisuse,
            "window host loop was misused",
        ),
        RuntimeErrorKind::BackendUnavailable => WindowError::new(
            WindowErrorKind::BackendUnavailable,
            "window backend is unavailable",
        ),
        RuntimeErrorKind::UnsupportedCapability
        | RuntimeErrorKind::DeviceLost
        | RuntimeErrorKind::RecoveryFailed
        | RuntimeErrorKind::OutOfMemory
        | RuntimeErrorKind::ResourceInvalid
        | RuntimeErrorKind::Internal => {
            WindowError::new(WindowErrorKind::Internal, "window operation failed")
        }
        RuntimeErrorKind::Reentrancy => {
            WindowError::new(WindowErrorKind::Internal, "window operation failed")
        }
        // `RuntimeErrorKind` is non-exhaustive: a future runtime category with
        // no narrower M1 mapping surfaces as `Internal`, never as a silently
        // accepted success. New kinds get explicit arms in review.
        _ => WindowError::new(WindowErrorKind::Internal, "window operation failed"),
    }
}

/// Backend-neutral cadence event consumed by the [`WindowApp`] core.
///
/// The stub source ([`StubCadence`]) and the winit shell both speak this
/// vocabulary so redraw pacing stays behind the seam: the core never names
/// an OS event type.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
#[non_exhaustive]
pub enum CadenceEvent {
    /// A redraw was requested; issue one engine-paced submission.
    RedrawRequested,
    /// The drawable size changed; reconfigure before the next submission.
    Resized(WindowSize),
    /// The surface is occluded; skip submissions without a retry loop.
    Occluded(bool),
    /// The present wait expired; skip this submission without a retry loop.
    TimedOut,
    /// Observable close was requested.
    CloseRequested,
}

/// Engine-paced redraw source behind the seam.
///
/// The M1 stub implementation is deterministic and headless-safe; the live
/// winit shell translates OS events into the same [`CadenceEvent`]
/// vocabulary instead of implementing this trait.
pub trait CadenceSource {
    /// Yield the next cadence event, or `None` when the program is exhausted.
    fn next_event(&mut self) -> Option<CadenceEvent>;
}

/// Deterministic stub cadence program for headless M1 verification.
///
/// A fixed event queue drives [`WindowApp`] through the seam with no window
/// system, so redraw pacing, resize reconfiguration, occlusion skips, and
/// close are all observable in unit tests.
#[derive(Clone, Debug, Default)]
pub struct StubCadence {
    events: VecDeque<CadenceEvent>,
}

impl StubCadence {
    /// Empty program; push events explicitly.
    pub fn new() -> Self {
        Self {
            events: VecDeque::new(),
        }
    }

    /// Convenience program: `frames` redraws followed by an observable close.
    pub fn frames_then_close(frames: u32) -> Self {
        let mut program = Self::new();
        for _ in 0..frames {
            program.push(CadenceEvent::RedrawRequested);
        }
        program.push(CadenceEvent::CloseRequested);
        program
    }

    /// Append one event to the program.
    pub fn push(&mut self, event: CadenceEvent) {
        self.events.push_back(event);
    }

    /// Number of events not yet yielded.
    pub fn remaining(&self) -> usize {
        self.events.len()
    }

    /// Whether the program is exhausted.
    pub fn is_exhausted(&self) -> bool {
        self.events.is_empty()
    }
}

impl CadenceSource for StubCadence {
    fn next_event(&mut self) -> Option<CadenceEvent> {
        self.events.pop_front()
    }
}

/// Observable outcome of one engine-paced frame through the seam.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
#[non_exhaustive]
pub enum FrameOutcome {
    /// The runtime accepted the submission for the active surface.
    Accepted,
    /// A pending resize/reconfigure was applied before accepting.
    Reconfigured,
    /// The attempt was skipped (occlusion, timeout, suspension) without a
    /// busy retry loop.
    Skipped,
    /// Stale work was dropped without publication.
    StaleDropped,
}

impl FrameOutcome {
    fn from_submission(outcome: SubmissionOutcome) -> Self {
        match outcome {
            SubmissionOutcome::Ready => Self::Accepted,
            SubmissionOutcome::Reconfigured => Self::Reconfigured,
            SubmissionOutcome::Skipped(_) => Self::Skipped,
            SubmissionOutcome::StaleDropped => Self::StaleDropped,
            // `SubmissionOutcome` is non-exhaustive: an unknown future outcome
            // is conservatively reported as dropped without publication, never
            // as an accepted present.
            _ => Self::StaleDropped,
        }
    }
}

/// Observable outcome of applying one [`CadenceEvent`] to the core.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
#[non_exhaustive]
pub enum EventApplied {
    /// A redraw produced one engine-paced frame outcome.
    Redrawn(FrameOutcome),
    /// A resize was recorded; the next frame reconfigures.
    Resized,
    /// An occlusion or timeout note was recorded for the next frame.
    ConditionRecorded,
    /// A close request completed observably.
    Closed(CloseOutcome),
}

/// Observable outcome of an idempotent close request.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
#[non_exhaustive]
pub enum CloseOutcome {
    /// This call transitioned the window to closed.
    Closed,
    /// The window was already closed; no new work was possible.
    AlreadyClosed,
}

impl CloseOutcome {
    fn from_lifecycle(outcome: LifecycleOutcome) -> Self {
        match outcome {
            LifecycleOutcome::CloseRequested => Self::Closed,
            LifecycleOutcome::AlreadyClosed => Self::AlreadyClosed,
            _ => Self::Closed,
        }
    }
}

/// Headless-observable report from driving a stub program to exhaustion.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct StubRunReport {
    frames_accepted: u64,
    frames_reconfigured: u64,
    frames_skipped: u64,
    frames_stale: u64,
    resizes: u64,
    closed: bool,
}

impl StubRunReport {
    /// Frames accepted for the active surface.
    pub const fn frames_accepted(self) -> u64 {
        self.frames_accepted
    }

    /// Frames that applied a pending reconfigure first.
    pub const fn frames_reconfigured(self) -> u64 {
        self.frames_reconfigured
    }

    /// Frames skipped without a retry loop.
    pub const fn frames_skipped(self) -> u64 {
        self.frames_skipped
    }

    /// Stale frames dropped without publication.
    pub const fn frames_stale(self) -> u64 {
        self.frames_stale
    }

    /// Resize events applied.
    pub const fn resizes(self) -> u64 {
        self.resizes
    }

    /// Whether the program ended in the closed state.
    pub const fn closed(self) -> bool {
        self.closed
    }
}

/// M1 window core: backend-neutral owner of one runtime session and its
/// single logical surface.
///
/// The core is created on the thread that drives it (main-thread ownership
/// per ADR 0005) and never names a concrete window type. The live winit
/// shell owns one of these and feeds it OS events translated to
/// [`CadenceEvent`]; tests drive it with [`StubCadence`] instead.
pub struct WindowApp {
    session: EngineSession,
    surface: SurfaceId,
    size: WindowSize,
    pending_condition: SurfaceCondition,
    next_revision: u64,
    closed: bool,
}

impl WindowApp {
    /// Open the M1 core: enter the native-owned loop boundary and create the
    /// one logical surface for `size`.
    ///
    /// No window-system object is touched, so construction is headless-safe.
    /// The session is backend-detached (no GPU probe); surface present and
    /// device attachment are M2.
    pub fn new(size: WindowSize) -> Result<Self, WindowError> {
        let mut session = EngineSession::new(LoopMode::NativeOwned);
        match session.run_native_loop() {
            Ok(LoopOutcome::NativeLoopEntered | LoopOutcome::NativeLoopAlreadyRunning) => {}
            // `LoopOutcome` is non-exhaustive: any other success outcome
            // (today only `HostPumpCompleted`) cannot drive a native-owned
            // window, so open fails explicitly instead of proceeding.
            Ok(_) => {
                return Err(WindowError::new(
                    WindowErrorKind::Internal,
                    "native loop entry reported an unexpected outcome",
                ));
            }
            Err(error) => return Err(map_runtime_error(error)),
        }
        let surface = session
            .create_surface(size.as_array())
            .map_err(map_runtime_error)?;
        Ok(Self {
            session,
            surface,
            size,
            pending_condition: SurfaceCondition::Ready,
            next_revision: 1,
            closed: false,
        })
    }

    /// Current drawable size.
    pub const fn size(&self) -> WindowSize {
        self.size
    }

    /// Whether observable close has completed.
    pub const fn is_closed(&self) -> bool {
        self.closed
    }

    /// Identity of the one logical surface owned by this core.
    pub const fn surface_id(&self) -> SurfaceId {
        self.surface
    }

    /// Apply one cadence event through the seam.
    pub fn handle_event(&mut self, event: CadenceEvent) -> Result<EventApplied, WindowError> {
        match event {
            CadenceEvent::RedrawRequested => self.request_frame().map(EventApplied::Redrawn),
            CadenceEvent::Resized(size) => {
                self.ensure_open()?;
                self.session
                    .resize(self.surface, size.as_array())
                    .map_err(map_runtime_error)?;
                self.size = size;
                Ok(EventApplied::Resized)
            }
            CadenceEvent::Occluded(occluded) => {
                self.ensure_open()?;
                self.pending_condition = if occluded {
                    SurfaceCondition::Occluded
                } else {
                    SurfaceCondition::Ready
                };
                Ok(EventApplied::ConditionRecorded)
            }
            CadenceEvent::TimedOut => {
                self.ensure_open()?;
                self.pending_condition = SurfaceCondition::Timeout;
                Ok(EventApplied::ConditionRecorded)
            }
            CadenceEvent::CloseRequested => self.request_close().map(EventApplied::Closed),
        }
    }

    /// Issue one engine-paced submission for the active surface.
    ///
    /// The scene revision is the core's monotonic frame counter, a skeletal
    /// stand-in for the authoritative scene revision owned outside the
    /// runtime. The pending occlusion/timeout note is consumed by each
    /// frame so a skip never latches past one submission.
    pub fn request_frame(&mut self) -> Result<FrameOutcome, WindowError> {
        self.ensure_open()?;
        let revision = SceneRevision::new(self.next_revision);
        let token = self
            .session
            .begin_submission(revision)
            .map_err(map_runtime_error)?;
        let condition = self.pending_condition;
        self.pending_condition = SurfaceCondition::Ready;
        let outcome = self
            .session
            .submit(self.surface, token, condition)
            .map_err(map_runtime_error)?;
        self.next_revision = self.next_revision.saturating_add(1).max(1);
        Ok(FrameOutcome::from_submission(outcome))
    }

    /// Idempotent observable close. Repeated calls succeed and report
    /// [`CloseOutcome::AlreadyClosed`]; close prevents any new submission.
    pub fn request_close(&mut self) -> Result<CloseOutcome, WindowError> {
        if self.closed {
            return Ok(CloseOutcome::AlreadyClosed);
        }
        let outcome = self.session.close().map_err(map_runtime_error)?;
        self.closed = true;
        Ok(CloseOutcome::from_lifecycle(outcome))
    }

    /// Drive a stub program to exhaustion (or close) and report headless
    /// observations. This is the M1 engine-paced redraw path exercised
    /// without a window system.
    pub fn run_stub(&mut self, source: &mut impl CadenceSource) -> StubRunReport {
        let mut report = StubRunReport {
            frames_accepted: 0,
            frames_reconfigured: 0,
            frames_skipped: 0,
            frames_stale: 0,
            resizes: 0,
            closed: self.closed,
        };
        while !self.closed {
            let Some(event) = source.next_event() else {
                break;
            };
            match self.handle_event(event) {
                Ok(EventApplied::Redrawn(FrameOutcome::Accepted)) => {
                    report.frames_accepted += 1;
                }
                Ok(EventApplied::Redrawn(FrameOutcome::Reconfigured)) => {
                    report.frames_reconfigured += 1;
                }
                Ok(EventApplied::Redrawn(FrameOutcome::Skipped)) => {
                    report.frames_skipped += 1;
                }
                Ok(EventApplied::Redrawn(FrameOutcome::StaleDropped)) => {
                    report.frames_stale += 1;
                }
                Ok(EventApplied::Resized) => {
                    report.resizes += 1;
                }
                Ok(EventApplied::ConditionRecorded) => {}
                Ok(EventApplied::Closed(_)) => {
                    report.closed = true;
                }
                Err(_) => {
                    break;
                }
            }
        }
        report.closed = self.closed;
        report
    }

    fn ensure_open(&self) -> Result<(), WindowError> {
        if self.closed {
            Err(WindowError::new(
                WindowErrorKind::Closed,
                "window is closed",
            ))
        } else {
            Ok(())
        }
    }
}

/// Live winit shell: the only code in this crate that names concrete window
/// types.
///
/// The shell owns one [`WindowApp`] core created on the loop thread in
/// [`winit::application::ApplicationHandler::resumed`] (main-thread ownership
/// per ADR 0005) and translates OS window events into [`CadenceEvent`]s.
/// Redraws are requested once at open and on size-affecting events; no
/// continuous pump runs here, so an occluded window never busy-loops.
pub struct WinitHost {
    size: WindowSize,
    core: Option<WindowApp>,
    window: Option<winit::window::Window>,
    open_error: Option<WindowError>,
    close_outcome: Option<CloseOutcome>,
}

impl WinitHost {
    /// Stage a host for `size`. No window-system object is touched; the
    /// window and core are created in `resumed` on the loop thread.
    pub const fn new(size: WindowSize) -> Self {
        Self {
            size,
            core: None,
            window: None,
            open_error: None,
            close_outcome: None,
        }
    }

    /// Observable close outcome once the loop has exited, if the window
    /// opened and a close was observed.
    pub const fn close_outcome(&self) -> Option<CloseOutcome> {
        self.close_outcome
    }

    /// Whether the window failed to open.
    pub const fn open_error(&self) -> Option<WindowError> {
        self.open_error
    }

    fn translate(&mut self, event_loop: &winit::event_loop::ActiveEventLoop, event: CadenceEvent) {
        let Some(core) = self.core.as_mut() else {
            return;
        };
        match core.handle_event(event) {
            Ok(EventApplied::Closed(outcome)) => {
                self.close_outcome = Some(outcome);
                event_loop.exit();
            }
            Ok(_) => {}
            Err(_) => {
                event_loop.exit();
            }
        }
    }
}

impl winit::application::ApplicationHandler for WinitHost {
    fn resumed(&mut self, event_loop: &winit::event_loop::ActiveEventLoop) {
        if self.window.is_some() || self.open_error.is_some() {
            return;
        }
        event_loop.set_control_flow(winit::event_loop::ControlFlow::Wait);
        let core = match WindowApp::new(self.size) {
            Ok(core) => core,
            Err(error) => {
                self.open_error = Some(error);
                event_loop.exit();
                return;
            }
        };
        let attributes = winit::window::WindowAttributes::default()
            .with_title("LumenPlot")
            .with_inner_size(winit::dpi::PhysicalSize::new(
                self.size.width(),
                self.size.height(),
            ));
        match event_loop.create_window(attributes) {
            Ok(window) => {
                window.request_redraw();
                self.core = Some(core);
                self.window = Some(window);
            }
            Err(_) => {
                let _ = core;
                self.open_error = Some(WindowError::new(
                    WindowErrorKind::BackendUnavailable,
                    "native window is unavailable",
                ));
                event_loop.exit();
            }
        }
    }

    fn window_event(
        &mut self,
        event_loop: &winit::event_loop::ActiveEventLoop,
        window_id: winit::window::WindowId,
        event: winit::event::WindowEvent,
    ) {
        let owned_id = match self.window.as_ref() {
            Some(window) => window.id(),
            None => return,
        };
        if owned_id != window_id {
            return;
        }
        match event {
            winit::event::WindowEvent::CloseRequested | winit::event::WindowEvent::Destroyed => {
                self.translate(event_loop, CadenceEvent::CloseRequested);
            }
            winit::event::WindowEvent::RedrawRequested => {
                self.translate(event_loop, CadenceEvent::RedrawRequested);
            }
            winit::event::WindowEvent::Resized(size) => {
                match WindowSize::new(size.width, size.height) {
                    Ok(next) => self.translate(event_loop, CadenceEvent::Resized(next)),
                    Err(_) => self.translate(event_loop, CadenceEvent::CloseRequested),
                }
                if let Some(window) = self.window.as_ref() {
                    window.request_redraw();
                }
            }
            winit::event::WindowEvent::Occluded(occluded) => {
                self.translate(event_loop, CadenceEvent::Occluded(occluded));
            }
            winit::event::WindowEvent::ScaleFactorChanged { .. } => {
                let size = self.window.as_ref().map(|window| window.inner_size());
                match size
                    .map(|size| WindowSize::new(size.width, size.height))
                    .transpose()
                {
                    Ok(Some(next)) => self.translate(event_loop, CadenceEvent::Resized(next)),
                    Ok(None) => {}
                    Err(_) => self.translate(event_loop, CadenceEvent::CloseRequested),
                }
                if let Some(window) = self.window.as_ref() {
                    window.request_redraw();
                }
            }
            _ => {}
        }
    }
}

/// Open one window and run the native-owned event loop until an observable
/// close.
///
/// Returns the idempotent close outcome. When no native event loop or window
/// is available (for example a headless host), returns
/// [`WindowErrorKind::BackendUnavailable`] instead of panicking. Must be
/// called on the thread that will own the loop (the main thread).
pub fn run_window(size: WindowSize) -> Result<CloseOutcome, WindowError> {
    let event_loop = winit::event_loop::EventLoop::new().map_err(|_| {
        WindowError::new(
            WindowErrorKind::BackendUnavailable,
            "native event loop is unavailable",
        )
    })?;
    let mut host = WinitHost::new(size);
    event_loop
        .run_app(&mut host)
        .map_err(|_| WindowError::new(WindowErrorKind::Internal, "native event loop failed"))?;
    if let Some(error) = host.open_error() {
        return Err(error);
    }
    Ok(host.close_outcome().unwrap_or(CloseOutcome::AlreadyClosed))
}

#[cfg(test)]
mod tests {
    use super::*;

    const TEST_SIZE: WindowSize = match WindowSize::new(640, 480) {
        Ok(size) => size,
        Err(_) => panic!("test window size is invalid"),
    };

    #[test]
    fn window_size_rejects_zero_and_over_bound() {
        assert!(WindowSize::new(0, 480).is_err());
        assert!(WindowSize::new(640, 0).is_err());
        assert!(WindowSize::new(MAX_WINDOW_DIMENSION + 1, 480).is_err());
        assert!(WindowSize::new(640, MAX_WINDOW_DIMENSION + 1).is_err());
        let size = WindowSize::new(640, 480).expect("valid size");
        assert_eq!(size.as_array(), [640, 480]);
    }

    #[test]
    fn error_kinds_have_stable_codes() {
        assert_eq!(WindowErrorKind::InvalidInput.as_str(), "invalid-input");
        assert_eq!(WindowErrorKind::Closed.as_str(), "closed");
        assert_eq!(
            WindowErrorKind::BackendUnavailable.as_str(),
            "backend-unavailable"
        );
    }

    #[test]
    fn stub_program_drives_redraws_then_observable_close() {
        let mut app = WindowApp::new(TEST_SIZE).expect("core opens headlessly");
        assert!(!app.is_closed());
        let mut program = StubCadence::frames_then_close(3);
        let report = app.run_stub(&mut program);
        assert_eq!(report.frames_accepted(), 3);
        assert_eq!(report.frames_skipped(), 0);
        assert!(report.closed());
        assert!(app.is_closed());
        assert!(program.is_exhausted());
    }

    #[test]
    fn resize_reconfigures_on_next_frame() {
        let mut app = WindowApp::new(TEST_SIZE).expect("core opens headlessly");
        let next = WindowSize::new(800, 600).expect("valid size");
        assert_eq!(
            app.handle_event(CadenceEvent::Resized(next)),
            Ok(EventApplied::Resized)
        );
        assert_eq!(app.size().as_array(), [800, 600]);
        assert_eq!(
            app.handle_event(CadenceEvent::RedrawRequested),
            Ok(EventApplied::Redrawn(FrameOutcome::Reconfigured))
        );
        assert_eq!(
            app.handle_event(CadenceEvent::RedrawRequested),
            Ok(EventApplied::Redrawn(FrameOutcome::Accepted))
        );
    }

    #[test]
    fn occlusion_skips_one_frame_without_latching() {
        let mut app = WindowApp::new(TEST_SIZE).expect("core opens headlessly");
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
    }

    #[test]
    fn timeout_skips_one_frame_without_latching() {
        let mut app = WindowApp::new(TEST_SIZE).expect("core opens headlessly");
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
    fn close_is_idempotent_and_prevents_new_work() {
        let mut app = WindowApp::new(TEST_SIZE).expect("core opens headlessly");
        assert_eq!(
            app.handle_event(CadenceEvent::CloseRequested),
            Ok(EventApplied::Closed(CloseOutcome::Closed))
        );
        assert!(app.is_closed());
        assert_eq!(app.request_close(), Ok(CloseOutcome::AlreadyClosed));
        assert_eq!(
            app.handle_event(CadenceEvent::RedrawRequested),
            Err(WindowError::new(
                WindowErrorKind::Closed,
                "window is closed"
            ))
        );
        assert_eq!(
            app.handle_event(CadenceEvent::Resized(TEST_SIZE)),
            Err(WindowError::new(
                WindowErrorKind::Closed,
                "window is closed"
            ))
        );
    }

    #[test]
    fn stub_stops_at_close_and_reports_counts() {
        let mut app = WindowApp::new(TEST_SIZE).expect("core opens headlessly");
        let mut program = StubCadence::new();
        program.push(CadenceEvent::RedrawRequested);
        program.push(CadenceEvent::Occluded(true));
        program.push(CadenceEvent::RedrawRequested);
        program.push(CadenceEvent::CloseRequested);
        program.push(CadenceEvent::RedrawRequested);
        let report = app.run_stub(&mut program);
        assert_eq!(report.frames_accepted(), 1);
        assert_eq!(report.frames_skipped(), 1);
        assert!(report.closed());
        assert_eq!(program.remaining(), 1);
    }

    #[test]
    fn winit_host_stages_without_touching_the_window_system() {
        let host = WinitHost::new(TEST_SIZE);
        assert!(host.close_outcome().is_none());
        assert!(host.open_error().is_none());
    }
}
