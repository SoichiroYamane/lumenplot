//! Main-thread-owned runtime lifecycle skeleton.
//!
//! This crate owns the lifecycle boundary around the portable renderer.  The
//! state machine is deliberately usable without a window-system transport so
//! lifecycle transitions can be tested on a headless host.  [`EngineSession`]
//! can also retain a real portable renderer through [`EngineSession::try_new`]
//! or [`EngineSession::with_renderer`].  The logical surface records in this
//! slice are not window or surface handles and do not make a platform-support
//! claim.
//!
//! `PlotScene` remains outside this crate.  Submission records carry an
//! opaque caller-owned scene revision key only for stale-result rejection;
//! the runtime never creates, mutates, or persists scene state.  Work and
//! device generations are independent runtime records.

#![forbid(unsafe_code)]

use std::marker::PhantomData;
use std::rc::Rc;
use std::thread::{self, ThreadId};

use lumenplot_render_wgpu::{RenderError, RenderErrorKind, Renderer};

mod input;

const MAX_SURFACES: usize = 64;
const MAX_SURFACE_DIMENSION: u32 = 16_384;

/// Explicit ownership mode for the runtime loop.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
#[non_exhaustive]
pub enum LoopMode {
    /// The standalone viewer owns the blocking native loop boundary.
    NativeOwned,
    /// An embedding host owns the loop and drives the internal pump boundary.
    HostPumped,
}

/// Coarse lifecycle state of one engine session.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
#[non_exhaustive]
pub enum SessionState {
    /// The session has been created but its loop has not been entered.
    Created,
    /// The session can accept lifecycle work and logical submissions.
    Running,
    /// Device resources are invalid and recovery is required before work can continue.
    DeviceLost,
    /// Allocation or submission reached a terminal memory-exhaustion state.
    OutOfMemory,
    /// Explicit close completed; the state cannot be reopened.
    Closed,
}

/// Lifecycle state of one logical surface owned by a session.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
#[non_exhaustive]
pub enum SurfaceState {
    /// The surface is configured and can accept a ready submission.
    Active,
    /// A resize or resume requires configuration before the next submission.
    ReconfigurePending,
    /// The surface is intentionally not drawable.
    Suspended,
    /// The surface lost its backend resource and must be recreated explicitly.
    Lost,
}

/// Opaque identity for a session-owned logical surface.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct SurfaceId(u64);

/// Condition observed at the present boundary for one submission attempt.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
#[non_exhaustive]
pub enum SurfaceCondition {
    /// The surface is drawable at this attempt.
    Ready,
    /// The surface is occluded; the attempt is skipped without a retry loop.
    Occluded,
    /// The surface did not become available before the bounded wait expired.
    Timeout,
}

/// A submission skip that is not a user-facing operation error.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
#[non_exhaustive]
pub enum SkipReason {
    /// The host or compositor reported occlusion.
    Occluded,
    /// The bounded present wait expired.
    Timeout,
    /// The surface was explicitly suspended.
    Suspended,
}

/// Result of entering or pumping a declared loop boundary.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
#[non_exhaustive]
pub enum LoopOutcome {
    /// Native ownership was entered from the owner thread.
    NativeLoopEntered,
    /// The native loop was already active.
    NativeLoopAlreadyRunning,
    /// One host-pumped iteration completed.
    HostPumpCompleted,
}

/// Observable result of a lifecycle transition.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
#[non_exhaustive]
pub enum LifecycleOutcome {
    Resized,
    Suspended,
    AlreadySuspended,
    Resumed,
    AlreadyActive,
    SurfaceLost,
    AlreadyLost,
    SurfaceRecreated,
    DeviceLost,
    AlreadyDeviceLost,
    DeviceRebuilt,
    TerminalOutOfMemory,
    AlreadyOutOfMemory,
    CloseRequested,
    AlreadyClosed,
}

/// Stable runtime operation-error categories from API 0002.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
#[non_exhaustive]
pub enum RuntimeErrorKind {
    InvalidInput,
    Closed,
    InvalidState,
    HostLoopMisuse,
    Reentrancy,
    UnsupportedCapability,
    BackendUnavailable,
    DeviceLost,
    RecoveryFailed,
    OutOfMemory,
    ResourceInvalid,
    Internal,
}

impl RuntimeErrorKind {
    /// Stable lowercase operation code for the runtime boundary.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::InvalidInput => "invalid-input",
            Self::Closed => "closed",
            Self::InvalidState => "invalid-state",
            Self::HostLoopMisuse => "host-loop-misuse",
            Self::Reentrancy => "reentrancy",
            Self::UnsupportedCapability => "unsupported-capability",
            Self::BackendUnavailable => "backend-unavailable",
            Self::DeviceLost => "device-lost",
            Self::RecoveryFailed => "recovery-failed",
            Self::OutOfMemory => "out-of-memory",
            Self::ResourceInvalid => "resource-invalid",
            Self::Internal => "internal",
        }
    }
}

/// Sanitized error returned by an explicit runtime operation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RuntimeError {
    kind: RuntimeErrorKind,
    message: &'static str,
}

impl RuntimeError {
    const fn new(kind: RuntimeErrorKind, message: &'static str) -> Self {
        Self { kind, message }
    }

    /// Machine-readable runtime failure kind.
    pub const fn kind(self) -> RuntimeErrorKind {
        self.kind
    }

    /// Non-contract human-readable detail.
    pub const fn message(self) -> &'static str {
        self.message
    }
}

impl std::fmt::Display for RuntimeError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(self.message)
    }
}

impl std::error::Error for RuntimeError {}

/// Caller-owned opaque scene revision key carried by a submission token.
///
/// This is metadata for stale comparison, not a second scene authority.  The
/// owner of the `PlotScene` supplies it at the submission boundary.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct SceneRevision(u64);

impl SceneRevision {
    /// Wrap a caller-owned monotonic scene revision value.
    pub const fn new(value: u64) -> Self {
        Self(value)
    }
}

/// Generation for bounded derived work.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct WorkGeneration(u64);

impl WorkGeneration {
    /// Initial work generation for a newly-created session.
    pub const fn initial() -> Self {
        Self(0)
    }

    fn next(self) -> Result<Self, RuntimeError> {
        self.0.checked_add(1).map(Self).ok_or_else(|| {
            RuntimeError::new(RuntimeErrorKind::Internal, "work generation exhausted")
        })
    }
}

/// Generation for retained adapter/device resources.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct DeviceGeneration(u64);

impl DeviceGeneration {
    /// Initial device generation for a newly-created session.
    pub const fn initial() -> Self {
        Self(0)
    }

    fn next(self) -> Result<Self, RuntimeError> {
        self.0.checked_add(1).map(Self).ok_or_else(|| {
            RuntimeError::new(RuntimeErrorKind::Internal, "device generation exhausted")
        })
    }
}

/// Immutable submission metadata used for stale-result rejection.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct SubmissionToken {
    scene_revision: SceneRevision,
    work_generation: WorkGeneration,
    device_generation: DeviceGeneration,
}

impl SubmissionToken {
    /// Scene revision supplied by the authoritative scene owner.
    pub const fn scene_revision(self) -> SceneRevision {
        self.scene_revision
    }

    /// Work generation captured when the token was issued.
    pub const fn work_generation(self) -> WorkGeneration {
        self.work_generation
    }

    /// Device generation captured when the token was issued.
    pub const fn device_generation(self) -> DeviceGeneration {
        self.device_generation
    }
}

/// Result of a bounded submission acceptance attempt.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
#[non_exhaustive]
pub enum SubmissionOutcome {
    /// The lifecycle state machine accepted the submission for the active surface.
    /// This is not a GPU-present or platform-support claim.
    Ready,
    /// The resize/resume configuration was applied before accepting this attempt.
    Reconfigured,
    /// The result was stale and was dropped without publication.
    StaleDropped,
    /// The attempt was skipped without a busy retry loop.
    Skipped(SkipReason),
}

struct SurfaceSlot {
    id: SurfaceId,
    size: [u32; 2],
    state: SurfaceState,
}

/// Main-thread-owned session around the portable renderer lifecycle.
///
/// ```compile_fail
/// fn move_session_to_worker(session: lumenplot_runtime::EngineSession) {
///     std::thread::spawn(move || drop(session));
/// }
/// ```
///
/// The optional renderer is present only when the portable offscreen backend
/// was successfully created.  The state-only constructor is intentional: it
/// permits headless lifecycle tests and does not pretend that a window system,
/// surface transport, or GPU adapter is available.  When present, the
/// renderer is owned here and cannot be moved to a worker because the session
/// is explicitly non-sendable.
pub struct EngineSession {
    loop_mode: LoopMode,
    state: SessionState,
    owner_thread: ThreadId,
    renderer: Option<Renderer>,
    backend_attached: bool,
    surfaces: Vec<SurfaceSlot>,
    next_surface_id: u64,
    work_generation: WorkGeneration,
    device_generation: DeviceGeneration,
    latest_scene_revision: Option<SceneRevision>,
    // The internal host-pump entry is staged until an accepted transport
    // drives it outside the lifecycle tests.
    #[cfg_attr(not(test), allow(dead_code))]
    pumping: bool,
    _main_thread_only: PhantomData<Rc<()>>,
}

impl EngineSession {
    /// Creates a lifecycle shell without probing a backend.
    ///
    /// Use [`Self::try_new`] when a real portable renderer is required.  The
    /// shell is useful for explicit, headless lifecycle coordination and makes
    /// backend absence an observable operation result rather than an implicit
    /// fallback.
    pub fn new(loop_mode: LoopMode) -> Self {
        Self::from_renderer(loop_mode, None, false)
    }

    /// Creates a session and probes the reviewed portable renderer baseline.
    pub fn try_new(loop_mode: LoopMode) -> Result<Self, RuntimeError> {
        let renderer = Renderer::new().map_err(|error| map_renderer_error(error, false))?;
        Ok(Self::from_renderer(loop_mode, Some(renderer), true))
    }

    /// Wraps an already-created portable renderer in the main-thread session.
    pub fn with_renderer(loop_mode: LoopMode, renderer: Renderer) -> Self {
        Self::from_renderer(loop_mode, Some(renderer), true)
    }

    fn from_renderer(
        loop_mode: LoopMode,
        renderer: Option<Renderer>,
        backend_attached: bool,
    ) -> Self {
        Self {
            loop_mode,
            state: SessionState::Created,
            owner_thread: thread::current().id(),
            renderer,
            backend_attached,
            surfaces: Vec::new(),
            next_surface_id: 1,
            work_generation: WorkGeneration::initial(),
            device_generation: DeviceGeneration::initial(),
            latest_scene_revision: None,
            pumping: false,
            _main_thread_only: PhantomData,
        }
    }

    /// Declared loop ownership mode.
    pub const fn loop_mode(&self) -> LoopMode {
        self.loop_mode
    }

    /// Current session lifecycle state.
    pub const fn state(&self) -> SessionState {
        self.state
    }

    /// Whether explicit close has completed.
    pub const fn is_closed(&self) -> bool {
        matches!(self.state, SessionState::Closed)
    }

    /// Current work generation, kept distinct from scene and device generations.
    pub const fn work_generation(&self) -> WorkGeneration {
        self.work_generation
    }

    /// Current device generation, kept distinct from scene and work generations.
    pub const fn device_generation(&self) -> DeviceGeneration {
        self.device_generation
    }

    /// Number of logical surfaces owned by this session.
    pub fn surface_count(&self) -> usize {
        self.surfaces.len()
    }

    /// Enters the native-owned loop boundary on the owner thread.
    ///
    /// The skeleton records ownership and returns; a real native event source
    /// will provide the blocking loop in the platform/viewer implementation.
    pub fn run_native_loop(&mut self) -> Result<LoopOutcome, RuntimeError> {
        self.ensure_owner()?;
        if !matches!(self.loop_mode, LoopMode::NativeOwned) {
            return Err(RuntimeError::new(
                RuntimeErrorKind::HostLoopMisuse,
                "native-owned loop requested from a host-pumped session",
            ));
        }
        match self.state {
            SessionState::Created => {
                self.state = SessionState::Running;
                Ok(LoopOutcome::NativeLoopEntered)
            }
            SessionState::Running => Ok(LoopOutcome::NativeLoopAlreadyRunning),
            SessionState::DeviceLost => Err(RuntimeError::new(
                RuntimeErrorKind::DeviceLost,
                "device recovery is required before entering the loop",
            )),
            SessionState::OutOfMemory => Err(RuntimeError::new(
                RuntimeErrorKind::OutOfMemory,
                "session is out of memory",
            )),
            SessionState::Closed => Err(RuntimeError::new(
                RuntimeErrorKind::Closed,
                "session is closed",
            )),
        }
    }

    /// Pumps one nonblocking host-owned loop iteration.
    #[cfg_attr(not(test), allow(dead_code))]
    fn pump_once(&mut self) -> Result<LoopOutcome, RuntimeError> {
        self.ensure_owner()?;
        if !matches!(self.loop_mode, LoopMode::HostPumped) {
            return Err(RuntimeError::new(
                RuntimeErrorKind::HostLoopMisuse,
                "host pump requested from a native-owned session",
            ));
        }
        if self.pumping {
            return Err(RuntimeError::new(
                RuntimeErrorKind::Reentrancy,
                "host pump is already active",
            ));
        }

        self.pumping = true;
        let result = match self.state {
            SessionState::Created => {
                self.state = SessionState::Running;
                Ok(LoopOutcome::HostPumpCompleted)
            }
            SessionState::Running => Ok(LoopOutcome::HostPumpCompleted),
            SessionState::DeviceLost => Err(RuntimeError::new(
                RuntimeErrorKind::DeviceLost,
                "device recovery is required before pumping",
            )),
            SessionState::OutOfMemory => Err(RuntimeError::new(
                RuntimeErrorKind::OutOfMemory,
                "session is out of memory",
            )),
            SessionState::Closed => Err(RuntimeError::new(
                RuntimeErrorKind::Closed,
                "session is closed",
            )),
        };
        self.pumping = false;
        result
    }

    /// Creates one logical surface owned by this main-thread session.
    pub fn create_surface(&mut self, size: [u32; 2]) -> Result<SurfaceId, RuntimeError> {
        self.ensure_owner()?;
        self.ensure_not_terminal()?;
        validate_surface_size(size)?;
        if self.surfaces.len() >= MAX_SURFACES {
            return Err(RuntimeError::new(
                RuntimeErrorKind::ResourceInvalid,
                "session surface capacity is exhausted",
            ));
        }
        let id = SurfaceId(self.next_surface_id);
        self.next_surface_id = self.next_surface_id.checked_add(1).ok_or_else(|| {
            RuntimeError::new(
                RuntimeErrorKind::ResourceInvalid,
                "surface identity is exhausted",
            )
        })?;
        self.surfaces.push(SurfaceSlot {
            id,
            size,
            state: SurfaceState::Active,
        });
        Ok(id)
    }

    /// Observes a logical surface state.
    pub fn surface_state(&self, id: SurfaceId) -> Result<SurfaceState, RuntimeError> {
        self.find_surface(id).map(|surface| surface.state)
    }

    /// Observes a logical surface size.
    pub fn surface_size(&self, id: SurfaceId) -> Result<[u32; 2], RuntimeError> {
        self.find_surface(id).map(|surface| surface.size)
    }

    /// Records a resize and invalidates older derived work.
    pub fn resize(
        &mut self,
        id: SurfaceId,
        size: [u32; 2],
    ) -> Result<LifecycleOutcome, RuntimeError> {
        self.ensure_owner()?;
        self.ensure_not_terminal()?;
        validate_surface_size(size)?;
        let next_work = self.next_work_generation()?;
        let surface = self.find_surface_mut(id)?;
        surface.size = size;
        if !matches!(surface.state, SurfaceState::Suspended | SurfaceState::Lost) {
            surface.state = SurfaceState::ReconfigurePending;
        }
        self.work_generation = next_work;
        Ok(LifecycleOutcome::Resized)
    }

    /// Suspends one surface without spinning on submissions.
    pub fn suspend(&mut self, id: SurfaceId) -> Result<LifecycleOutcome, RuntimeError> {
        self.ensure_owner()?;
        self.ensure_not_terminal()?;
        let current = self.find_surface(id)?.state;
        if matches!(current, SurfaceState::Suspended) {
            return Ok(LifecycleOutcome::AlreadySuspended);
        }
        if matches!(current, SurfaceState::Lost) {
            return Err(RuntimeError::new(
                RuntimeErrorKind::ResourceInvalid,
                "lost surface must be recreated before suspension",
            ));
        }
        let next_work = self.next_work_generation()?;
        self.find_surface_mut(id)?.state = SurfaceState::Suspended;
        self.work_generation = next_work;
        Ok(LifecycleOutcome::Suspended)
    }

    /// Resumes one suspended surface and schedules reconfiguration.
    pub fn resume(&mut self, id: SurfaceId) -> Result<LifecycleOutcome, RuntimeError> {
        self.ensure_owner()?;
        self.ensure_not_terminal()?;
        let current = self.find_surface(id)?.state;
        if matches!(current, SurfaceState::Suspended) {
            let next_work = self.next_work_generation()?;
            self.find_surface_mut(id)?.state = SurfaceState::ReconfigurePending;
            self.work_generation = next_work;
            return Ok(LifecycleOutcome::Resumed);
        }
        if matches!(current, SurfaceState::Lost) {
            return Err(RuntimeError::new(
                RuntimeErrorKind::ResourceInvalid,
                "lost surface must be recreated before resume",
            ));
        }
        Ok(LifecycleOutcome::AlreadyActive)
    }

    /// Records explicit surface loss. Recovery is a separate owner operation.
    pub fn handle_surface_loss(&mut self, id: SurfaceId) -> Result<LifecycleOutcome, RuntimeError> {
        self.ensure_owner()?;
        self.ensure_not_terminal()?;
        let current = self.find_surface(id)?.state;
        if matches!(current, SurfaceState::Lost) {
            return Ok(LifecycleOutcome::AlreadyLost);
        }
        let next_work = self.next_work_generation()?;
        self.find_surface_mut(id)?.state = SurfaceState::Lost;
        self.work_generation = next_work;
        Ok(LifecycleOutcome::SurfaceLost)
    }

    /// Recreates a lost surface through this session's owner thread.
    pub fn recreate_surface(&mut self, id: SurfaceId) -> Result<LifecycleOutcome, RuntimeError> {
        self.ensure_owner()?;
        self.ensure_not_terminal()?;
        let current = self.find_surface(id)?.state;
        if !matches!(current, SurfaceState::Lost) {
            return Err(RuntimeError::new(
                RuntimeErrorKind::InvalidState,
                "surface recreation requires a lost surface",
            ));
        }
        let next_work = self.next_work_generation()?;
        self.find_surface_mut(id)?.state = SurfaceState::ReconfigurePending;
        self.work_generation = next_work;
        Ok(LifecycleOutcome::SurfaceRecreated)
    }

    /// Records device loss, invalidates surfaces, and advances DeviceGeneration.
    pub fn handle_device_loss(&mut self) -> Result<LifecycleOutcome, RuntimeError> {
        self.ensure_owner()?;
        if matches!(self.state, SessionState::Closed) {
            return Err(RuntimeError::new(
                RuntimeErrorKind::Closed,
                "session is closed",
            ));
        }
        if matches!(self.state, SessionState::OutOfMemory) {
            return Err(RuntimeError::new(
                RuntimeErrorKind::OutOfMemory,
                "session is out of memory",
            ));
        }
        if matches!(self.state, SessionState::DeviceLost) {
            return Ok(LifecycleOutcome::AlreadyDeviceLost);
        }
        let next_device = self.device_generation.next()?;
        let next_work = self.next_work_generation()?;
        self.device_generation = next_device;
        self.work_generation = next_work;
        self.state = SessionState::DeviceLost;
        self.renderer = None;
        for surface in &mut self.surfaces {
            surface.state = SurfaceState::Lost;
        }
        Ok(LifecycleOutcome::DeviceLost)
    }

    /// Rebuilds a previously attached portable renderer after device loss.
    ///
    /// The caller retains the authoritative CPU scene; this method only
    /// recreates runtime-owned backend resources.  A state-only session has no
    /// backend recovery implementation and returns `RecoveryFailed` rather
    /// than pretending to have rebuilt a device.
    pub fn recover_device(&mut self) -> Result<LifecycleOutcome, RuntimeError> {
        self.ensure_owner()?;
        match self.state {
            SessionState::DeviceLost => {}
            SessionState::OutOfMemory => {
                return Err(RuntimeError::new(
                    RuntimeErrorKind::OutOfMemory,
                    "out-of-memory is terminal for this session",
                ));
            }
            SessionState::Closed => {
                return Err(RuntimeError::new(
                    RuntimeErrorKind::Closed,
                    "session is closed",
                ));
            }
            SessionState::Created | SessionState::Running => {
                return Err(RuntimeError::new(
                    RuntimeErrorKind::InvalidState,
                    "device recovery was not requested",
                ));
            }
        }
        if !self.backend_attached {
            return Err(RuntimeError::new(
                RuntimeErrorKind::RecoveryFailed,
                "portable backend recovery is unavailable",
            ));
        }

        let replacement = match Renderer::new() {
            Ok(renderer) => renderer,
            Err(error) if matches!(error.kind(), RenderErrorKind::OutOfMemory) => {
                self.state = SessionState::OutOfMemory;
                return Err(RuntimeError::new(
                    RuntimeErrorKind::OutOfMemory,
                    "portable backend recovery ran out of memory",
                ));
            }
            Err(_) => {
                return Err(RuntimeError::new(
                    RuntimeErrorKind::RecoveryFailed,
                    "portable backend recovery failed",
                ));
            }
        };
        let next_work = self.next_work_generation()?;
        self.renderer = Some(replacement);
        self.state = SessionState::Running;
        self.work_generation = next_work;
        Ok(LifecycleOutcome::DeviceRebuilt)
    }

    /// Records terminal out-of-memory and disables all further submissions.
    pub fn handle_out_of_memory(&mut self) -> Result<LifecycleOutcome, RuntimeError> {
        self.ensure_owner()?;
        if matches!(self.state, SessionState::Closed) {
            return Err(RuntimeError::new(
                RuntimeErrorKind::Closed,
                "session is closed",
            ));
        }
        if matches!(self.state, SessionState::OutOfMemory) {
            return Ok(LifecycleOutcome::AlreadyOutOfMemory);
        }
        self.state = SessionState::OutOfMemory;
        self.renderer = None;
        for surface in &mut self.surfaces {
            surface.state = SurfaceState::Lost;
        }
        Ok(LifecycleOutcome::TerminalOutOfMemory)
    }

    /// Issues a token carrying the current work and device generations.
    pub fn begin_submission(
        &self,
        scene_revision: SceneRevision,
    ) -> Result<SubmissionToken, RuntimeError> {
        self.ensure_owner()?;
        self.ensure_running()?;
        Ok(SubmissionToken {
            scene_revision,
            work_generation: self.work_generation,
            device_generation: self.device_generation,
        })
    }

    /// Accepts one bounded submission attempt, dropping stale work explicitly.
    pub fn submit(
        &mut self,
        id: SurfaceId,
        token: SubmissionToken,
        condition: SurfaceCondition,
    ) -> Result<SubmissionOutcome, RuntimeError> {
        self.ensure_owner()?;
        self.ensure_running()?;
        if token.work_generation != self.work_generation
            || token.device_generation != self.device_generation
        {
            return Ok(SubmissionOutcome::StaleDropped);
        }
        if self
            .latest_scene_revision
            .is_some_and(|latest| token.scene_revision < latest)
        {
            return Ok(SubmissionOutcome::StaleDropped);
        }
        self.latest_scene_revision = Some(token.scene_revision);

        let surface = self.find_surface_mut(id)?;
        if matches!(surface.state, SurfaceState::Suspended) {
            return Ok(SubmissionOutcome::Skipped(SkipReason::Suspended));
        }
        if matches!(surface.state, SurfaceState::Lost) {
            return Err(RuntimeError::new(
                RuntimeErrorKind::ResourceInvalid,
                "surface must be recreated before submission",
            ));
        }
        match condition {
            SurfaceCondition::Occluded => Ok(SubmissionOutcome::Skipped(SkipReason::Occluded)),
            SurfaceCondition::Timeout => Ok(SubmissionOutcome::Skipped(SkipReason::Timeout)),
            SurfaceCondition::Ready => {
                if matches!(surface.state, SurfaceState::ReconfigurePending) {
                    surface.state = SurfaceState::Active;
                    Ok(SubmissionOutcome::Reconfigured)
                } else {
                    Ok(SubmissionOutcome::Ready)
                }
            }
        }
    }

    /// Closes the session. Repeated calls are successful and observable.
    pub fn close(&mut self) -> Result<LifecycleOutcome, RuntimeError> {
        self.ensure_owner()?;
        if matches!(self.state, SessionState::Closed) {
            return Ok(LifecycleOutcome::AlreadyClosed);
        }
        self.state = SessionState::Closed;
        self.renderer = None;
        self.surfaces.clear();
        Ok(LifecycleOutcome::CloseRequested)
    }

    fn ensure_owner(&self) -> Result<(), RuntimeError> {
        if thread::current().id() != self.owner_thread {
            Err(RuntimeError::new(
                RuntimeErrorKind::HostLoopMisuse,
                "runtime operation must run on its owner thread",
            ))
        } else {
            Ok(())
        }
    }

    fn ensure_not_terminal(&self) -> Result<(), RuntimeError> {
        match self.state {
            SessionState::Closed => Err(RuntimeError::new(
                RuntimeErrorKind::Closed,
                "session is closed",
            )),
            SessionState::OutOfMemory => Err(RuntimeError::new(
                RuntimeErrorKind::OutOfMemory,
                "session is out of memory",
            )),
            SessionState::DeviceLost => Err(RuntimeError::new(
                RuntimeErrorKind::DeviceLost,
                "device recovery is required",
            )),
            SessionState::Created | SessionState::Running => Ok(()),
        }
    }

    fn ensure_running(&self) -> Result<(), RuntimeError> {
        match self.state {
            SessionState::Running => Ok(()),
            SessionState::Created => Err(RuntimeError::new(
                RuntimeErrorKind::InvalidState,
                "loop ownership has not been entered",
            )),
            SessionState::DeviceLost => Err(RuntimeError::new(
                RuntimeErrorKind::DeviceLost,
                "device recovery is required",
            )),
            SessionState::OutOfMemory => Err(RuntimeError::new(
                RuntimeErrorKind::OutOfMemory,
                "session is out of memory",
            )),
            SessionState::Closed => Err(RuntimeError::new(
                RuntimeErrorKind::Closed,
                "session is closed",
            )),
        }
    }

    fn next_work_generation(&self) -> Result<WorkGeneration, RuntimeError> {
        self.work_generation.next()
    }

    fn find_surface(&self, id: SurfaceId) -> Result<&SurfaceSlot, RuntimeError> {
        self.surfaces
            .iter()
            .find(|surface| surface.id == id)
            .ok_or_else(|| {
                RuntimeError::new(RuntimeErrorKind::ResourceInvalid, "surface is invalid")
            })
    }

    fn find_surface_mut(&mut self, id: SurfaceId) -> Result<&mut SurfaceSlot, RuntimeError> {
        self.surfaces
            .iter_mut()
            .find(|surface| surface.id == id)
            .ok_or_else(|| {
                RuntimeError::new(RuntimeErrorKind::ResourceInvalid, "surface is invalid")
            })
    }
}

fn validate_surface_size(size: [u32; 2]) -> Result<(), RuntimeError> {
    if size[0] == 0
        || size[1] == 0
        || size[0] > MAX_SURFACE_DIMENSION
        || size[1] > MAX_SURFACE_DIMENSION
    {
        return Err(RuntimeError::new(
            RuntimeErrorKind::InvalidInput,
            "surface size is invalid",
        ));
    }
    Ok(())
}

fn map_renderer_error(error: RenderError, during_recovery: bool) -> RuntimeError {
    let kind = error.kind();
    match kind {
        RenderErrorKind::AdapterUnavailable | RenderErrorKind::DeviceUnavailable => {
            if during_recovery {
                RuntimeError::new(
                    RuntimeErrorKind::RecoveryFailed,
                    "portable backend recovery is unavailable",
                )
            } else {
                RuntimeError::new(
                    RuntimeErrorKind::BackendUnavailable,
                    "portable backend is unavailable",
                )
            }
        }
        RenderErrorKind::SurfaceUnavailable => RuntimeError::new(
            RuntimeErrorKind::UnsupportedCapability,
            "window surface transport is unsupported in this runtime slice",
        ),
        RenderErrorKind::SurfaceLost => RuntimeError::new(
            RuntimeErrorKind::ResourceInvalid,
            "surface resource is lost",
        ),
        RenderErrorKind::DeviceLost => {
            RuntimeError::new(RuntimeErrorKind::DeviceLost, "portable device is lost")
        }
        RenderErrorKind::OutOfMemory => RuntimeError::new(
            RuntimeErrorKind::OutOfMemory,
            "portable backend is out of memory",
        ),
        RenderErrorKind::WrongThread => RuntimeError::new(
            RuntimeErrorKind::HostLoopMisuse,
            "portable backend operation used the wrong thread",
        ),
        RenderErrorKind::InvalidInput
        | RenderErrorKind::CapacityExceeded
        | RenderErrorKind::ShaderInvalid
        | RenderErrorKind::ReadbackFailed
        | RenderErrorKind::Internal => RuntimeError::new(
            RuntimeErrorKind::Internal,
            "portable backend operation failed",
        ),
        _ => RuntimeError::new(
            RuntimeErrorKind::Internal,
            "portable backend operation failed",
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn running(mode: LoopMode) -> EngineSession {
        let mut session = EngineSession::new(mode);
        match mode {
            LoopMode::NativeOwned => session
                .run_native_loop()
                .expect("native loop")
                .eq(&LoopOutcome::NativeLoopEntered),
            LoopMode::HostPumped => session
                .pump_once()
                .expect("host pump")
                .eq(&LoopOutcome::HostPumpCompleted),
        };
        session
    }

    #[test]
    fn loop_ownership_modes_are_explicit_and_non_interchangeable() {
        let mut native = EngineSession::new(LoopMode::NativeOwned);
        assert_eq!(
            native.run_native_loop().expect("native loop"),
            LoopOutcome::NativeLoopEntered
        );
        assert_eq!(
            native.run_native_loop().expect("idempotent native entry"),
            LoopOutcome::NativeLoopAlreadyRunning
        );
        assert_eq!(
            native
                .pump_once()
                .expect_err("native loop cannot be pumped")
                .kind(),
            RuntimeErrorKind::HostLoopMisuse
        );

        let mut host = EngineSession::new(LoopMode::HostPumped);
        assert_eq!(
            host.pump_once().expect("host pump"),
            LoopOutcome::HostPumpCompleted
        );
        assert_eq!(
            host.run_native_loop()
                .expect_err("host owns the loop")
                .kind(),
            RuntimeErrorKind::HostLoopMisuse
        );
    }

    #[test]
    fn surface_resize_suspend_resume_and_loss_are_observable() {
        let mut session = running(LoopMode::HostPumped);
        let first = session.create_surface([640, 480]).expect("surface");
        let second = session.create_surface([320, 240]).expect("second surface");
        assert_eq!(session.surface_count(), 2);
        assert_eq!(
            session.surface_state(first).expect("state"),
            SurfaceState::Active
        );
        assert_eq!(session.surface_size(second).expect("size"), [320, 240]);

        assert_eq!(
            session.resize(first, [800, 600]).expect("resize"),
            LifecycleOutcome::Resized
        );
        assert_eq!(
            session.surface_state(first).expect("pending state"),
            SurfaceState::ReconfigurePending
        );
        assert_eq!(
            session.suspend(first).expect("suspend"),
            LifecycleOutcome::Suspended
        );
        assert_eq!(
            session.suspend(first).expect("idempotent suspend"),
            LifecycleOutcome::AlreadySuspended
        );
        assert_eq!(
            session.resume(first).expect("resume"),
            LifecycleOutcome::Resumed
        );
        assert_eq!(
            session.surface_state(first).expect("resume state"),
            SurfaceState::ReconfigurePending
        );
        assert_eq!(
            session.handle_surface_loss(first).expect("surface loss"),
            LifecycleOutcome::SurfaceLost
        );
        assert_eq!(
            session.recreate_surface(first).expect("surface recreation"),
            LifecycleOutcome::SurfaceRecreated
        );
        assert_eq!(
            session.surface_state(first).expect("recreated state"),
            SurfaceState::ReconfigurePending
        );
    }

    #[test]
    fn timeout_occlusion_and_reconfiguration_never_busy_retry() {
        let mut session = running(LoopMode::HostPumped);
        let surface = session.create_surface([64, 64]).expect("surface");
        let token = session
            .begin_submission(SceneRevision::new(1))
            .expect("token");
        assert_eq!(
            session
                .submit(surface, token, SurfaceCondition::Occluded)
                .expect("occlusion"),
            SubmissionOutcome::Skipped(SkipReason::Occluded)
        );
        assert_eq!(
            session
                .submit(surface, token, SurfaceCondition::Timeout)
                .expect("timeout"),
            SubmissionOutcome::Skipped(SkipReason::Timeout)
        );
        assert_eq!(
            session.resize(surface, [128, 128]).expect("resize"),
            LifecycleOutcome::Resized
        );
        let reconfigured_token = session
            .begin_submission(SceneRevision::new(2))
            .expect("new token");
        assert_eq!(
            session
                .submit(surface, reconfigured_token, SurfaceCondition::Ready)
                .expect("reconfigure"),
            SubmissionOutcome::Reconfigured
        );
        assert_eq!(
            session
                .submit(surface, reconfigured_token, SurfaceCondition::Ready)
                .expect("ready"),
            SubmissionOutcome::Ready
        );
    }

    #[test]
    fn stale_work_scene_and_device_submissions_are_dropped_or_rejected() {
        let mut session = running(LoopMode::NativeOwned);
        let surface = session.create_surface([64, 64]).expect("surface");
        let first = session
            .begin_submission(SceneRevision::new(1))
            .expect("first token");
        assert_eq!(
            session.resize(surface, [96, 96]).expect("resize"),
            LifecycleOutcome::Resized
        );
        assert_eq!(
            session
                .submit(surface, first, SurfaceCondition::Ready)
                .expect("stale work"),
            SubmissionOutcome::StaleDropped
        );

        let newer = session
            .begin_submission(SceneRevision::new(2))
            .expect("new token");
        assert_eq!(
            session
                .submit(surface, newer, SurfaceCondition::Ready)
                .expect("new work"),
            SubmissionOutcome::Reconfigured
        );
        let older_scene = SubmissionToken {
            scene_revision: SceneRevision::new(1),
            work_generation: session.work_generation(),
            device_generation: session.device_generation(),
        };
        assert_eq!(
            session
                .submit(surface, older_scene, SurfaceCondition::Ready)
                .expect("stale scene"),
            SubmissionOutcome::StaleDropped
        );

        let previous_device = session.device_generation();
        assert_eq!(
            session.handle_device_loss().expect("device loss"),
            LifecycleOutcome::DeviceLost
        );
        assert_ne!(session.device_generation(), previous_device);
        assert_eq!(
            session
                .begin_submission(SceneRevision::new(3))
                .expect_err("device loss quiesces submissions")
                .kind(),
            RuntimeErrorKind::DeviceLost
        );
        assert_eq!(
            session
                .recover_device()
                .expect_err("state-only recovery is explicit")
                .kind(),
            RuntimeErrorKind::RecoveryFailed
        );
    }

    #[test]
    fn out_of_memory_is_terminal_and_close_is_idempotent() {
        let mut session = running(LoopMode::HostPumped);
        let surface = session.create_surface([64, 64]).expect("surface");
        assert_eq!(
            session.handle_out_of_memory().expect("oom"),
            LifecycleOutcome::TerminalOutOfMemory
        );
        assert_eq!(
            session.handle_out_of_memory().expect("idempotent oom"),
            LifecycleOutcome::AlreadyOutOfMemory
        );
        assert_eq!(
            session
                .begin_submission(SceneRevision::new(1))
                .expect_err("oom rejects tokens")
                .kind(),
            RuntimeErrorKind::OutOfMemory
        );
        assert_eq!(
            session
                .submit(
                    surface,
                    SubmissionToken {
                        scene_revision: SceneRevision::new(1),
                        work_generation: session.work_generation(),
                        device_generation: session.device_generation(),
                    },
                    SurfaceCondition::Ready,
                )
                .expect_err("oom rejects submissions")
                .kind(),
            RuntimeErrorKind::OutOfMemory
        );
        assert_eq!(
            session
                .recover_device()
                .expect_err("oom cannot recover")
                .kind(),
            RuntimeErrorKind::OutOfMemory
        );
        assert_eq!(
            session.close().expect("close"),
            LifecycleOutcome::CloseRequested
        );
        assert_eq!(
            session.close().expect("repeat close"),
            LifecycleOutcome::AlreadyClosed
        );
        assert!(session.is_closed());
    }

    #[test]
    fn reentrant_host_pump_and_invalid_sizes_are_explicit_errors() {
        let mut session = running(LoopMode::HostPumped);
        session.pumping = true;
        assert_eq!(
            session.pump_once().expect_err("reentrant pump").kind(),
            RuntimeErrorKind::Reentrancy
        );
        session.pumping = false;
        assert_eq!(
            session
                .create_surface([0, 64])
                .expect_err("zero surface width")
                .kind(),
            RuntimeErrorKind::InvalidInput
        );
        assert_eq!(
            session
                .create_surface([MAX_SURFACE_DIMENSION + 1, 64])
                .expect_err("oversized surface")
                .kind(),
            RuntimeErrorKind::InvalidInput
        );
        assert_eq!(RuntimeErrorKind::OutOfMemory.as_str(), "out-of-memory");
    }
}
