//! Private backend-neutral logical-resource lifetime accounting.
//!
//! The cache stores only opaque logical identities and ownership state. Backend
//! objects remain with the renderer/device owner; this module deliberately has
//! no dependency on a concrete graphics API.

use std::cell::RefCell;
use std::collections::BTreeMap;
use std::fmt;
use std::rc::{Rc, Weak};

use crate::packet::{DeviceGeneration, LogicalResourceId, MAX_PACKET_RESOURCES, RenderPacket};

/// Maximum number of in-flight submissions retained by one cache.
pub(crate) const MAX_PENDING_SUBMISSIONS: usize = 65_536;

/// A completion observation scoped to one device generation.
///
/// The generation is part of the token so a completion from a device that was
/// lost cannot accidentally retire a resource on its replacement device.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub(crate) struct CompletionFence {
    device_generation: DeviceGeneration,
    sequence: u64,
}

impl CompletionFence {
    /// Creates a completion observation for one device generation.
    pub(crate) const fn new(device_generation: DeviceGeneration, sequence: u64) -> Self {
        Self {
            device_generation,
            sequence,
        }
    }

    /// Device generation that produced this completion observation.
    pub(crate) const fn device_generation(self) -> DeviceGeneration {
        self.device_generation
    }

    /// Monotonic sequence within the device generation.
    pub(crate) const fn sequence(self) -> u64 {
        self.sequence
    }
}

/// Classification for private resource-lifecycle failures.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum ResourceLifecycleErrorKind {
    /// A packet, lease, or completion belongs to another device generation.
    DeviceGenerationMismatch,
    /// Packet validation failed at the cache boundary.
    InvalidPacket,
    /// A lease was submitted to a cache that did not create it.
    InvalidLease,
    /// A completion or submission fence violates the cache's ordering rules.
    InvalidFence,
    /// A fixed lifecycle bound was exceeded.
    CapacityExceeded,
    /// A fallible lifecycle allocation failed.
    AllocationFailed,
}

/// Sanitized private resource-lifecycle failure.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct ResourceLifecycleError {
    kind: ResourceLifecycleErrorKind,
    message: &'static str,
}

impl ResourceLifecycleError {
    const fn new(kind: ResourceLifecycleErrorKind, message: &'static str) -> Self {
        Self { kind, message }
    }

    /// Returns the machine-readable private classification.
    pub(crate) const fn kind(self) -> ResourceLifecycleErrorKind {
        self.kind
    }

    /// Returns sanitized detail for private diagnostics and tests.
    pub(crate) const fn message(self) -> &'static str {
        self.message
    }
}

impl fmt::Display for ResourceLifecycleError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.message)
    }
}

impl std::error::Error for ResourceLifecycleError {}

/// Cache key for one logical resource on one device lifetime.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
struct ResourceKey {
    logical_id: LogicalResourceId,
    device_generation: DeviceGeneration,
}

impl ResourceKey {
    const fn new(logical_id: LogicalResourceId, device_generation: DeviceGeneration) -> Self {
        Self {
            logical_id,
            device_generation,
        }
    }
}

#[derive(Clone, Copy, Debug, Default)]
struct ResourceEntry {
    owner_count: usize,
}

struct PendingSubmission {
    fence: CompletionFence,
    resources: Vec<ResourceKey>,
}

struct CacheState {
    device_generation: DeviceGeneration,
    generation_token: Rc<()>,
    entries: BTreeMap<ResourceKey, ResourceEntry>,
    pending: Vec<PendingSubmission>,
    last_submitted: Option<CompletionFence>,
    last_completed: Option<CompletionFence>,
}

/// Main-thread-owned logical-resource cache.
///
/// Cloning this value clones an owner handle to the same main-thread state; it
/// does not make the cache thread-safe and does not introduce backend objects.
#[derive(Clone)]
pub(crate) struct ResourceCache {
    state: Rc<RefCell<CacheState>>,
}

impl ResourceCache {
    /// Creates an empty cache for one device generation.
    pub(crate) fn new(device_generation: DeviceGeneration) -> Self {
        Self {
            state: Rc::new(RefCell::new(CacheState {
                device_generation,
                generation_token: Rc::new(()),
                entries: BTreeMap::new(),
                pending: Vec::new(),
                last_submitted: None,
                last_completed: None,
            })),
        }
    }

    /// Returns the device generation currently owned by the cache.
    pub(crate) fn device_generation(&self) -> DeviceGeneration {
        self.state.borrow().device_generation
    }

    /// Acquires the logical resources referenced by a validated packet.
    ///
    /// The returned lease owns one reference to every packet resource. A
    /// submission transfers those references to a pending completion record;
    /// dropping an unsubmitted lease releases them immediately.
    pub(crate) fn acquire(
        &self,
        packet: &RenderPacket,
    ) -> Result<ResourceLease, ResourceLifecycleError> {
        let mut state = self.state.borrow_mut();
        let device_generation = state.device_generation;
        if packet.device_generation() != device_generation {
            return Err(ResourceLifecycleError::new(
                ResourceLifecycleErrorKind::DeviceGenerationMismatch,
                "packet device generation does not match the cache",
            ));
        }

        // Re-run the private packet boundary immediately before taking owners.
        // This keeps resource acquisition all-or-nothing if internal packet
        // construction or validation changes in a later renderer slice.
        if packet
            .validate(packet.work_generation(), device_generation)
            .is_err()
        {
            return Err(ResourceLifecycleError::new(
                ResourceLifecycleErrorKind::InvalidPacket,
                "packet failed private resource validation",
            ));
        }

        let resource_count = packet.resource_count();
        if resource_count > MAX_PACKET_RESOURCES {
            return Err(ResourceLifecycleError::new(
                ResourceLifecycleErrorKind::CapacityExceeded,
                "resource lease capacity is exceeded",
            ));
        }
        let mut resources = Vec::new();
        resources.try_reserve_exact(resource_count).map_err(|_| {
            ResourceLifecycleError::new(
                ResourceLifecycleErrorKind::AllocationFailed,
                "resource lease allocation failed",
            )
        })?;
        resources.extend(
            packet
                .resource_ids()
                .map(|logical_id| ResourceKey::new(logical_id, device_generation)),
        );

        // Validate every counter before mutating any entry. Packet validation
        // already rejects duplicate IDs, but keeping this pass separate makes
        // the lease acquisition boundary explicitly all-or-nothing.
        if resources.iter().any(|key| {
            state
                .entries
                .get(key)
                .is_some_and(|entry| entry.owner_count == usize::MAX)
        }) {
            return Err(ResourceLifecycleError::new(
                ResourceLifecycleErrorKind::CapacityExceeded,
                "resource owner count is exhausted",
            ));
        }

        for key in &resources {
            let entry = state.entries.entry(*key).or_default();
            entry.owner_count += 1;
        }
        let generation_token = Rc::clone(&state.generation_token);
        drop(state);

        Ok(ResourceLease {
            state: Rc::downgrade(&self.state),
            generation_token,
            device_generation,
            resources,
            released: false,
        })
    }

    /// Transfers a lease to a completion fence without retiring its resources.
    pub(crate) fn submit(
        &self,
        lease: ResourceLease,
        fence: CompletionFence,
    ) -> Result<(), ResourceLifecycleError> {
        if !Weak::ptr_eq(&lease.state, &Rc::downgrade(&self.state)) {
            return Err(ResourceLifecycleError::new(
                ResourceLifecycleErrorKind::InvalidLease,
                "resource lease belongs to another cache",
            ));
        }

        let mut state = self.state.borrow_mut();
        if !Rc::ptr_eq(&lease.generation_token, &state.generation_token)
            || lease.device_generation != state.device_generation
            || fence.device_generation() != state.device_generation
        {
            drop(state);
            return Err(ResourceLifecycleError::new(
                ResourceLifecycleErrorKind::DeviceGenerationMismatch,
                "resource lease or completion belongs to an old device generation",
            ));
        }
        if state.pending.len() >= MAX_PENDING_SUBMISSIONS {
            drop(state);
            return Err(ResourceLifecycleError::new(
                ResourceLifecycleErrorKind::CapacityExceeded,
                "pending submission capacity is exceeded",
            ));
        }
        if state
            .last_submitted
            .is_some_and(|last| fence.sequence() <= last.sequence())
            || state
                .last_completed
                .is_some_and(|last| fence.sequence() <= last.sequence())
        {
            drop(state);
            return Err(ResourceLifecycleError::new(
                ResourceLifecycleErrorKind::InvalidFence,
                "completion fence is not strictly increasing",
            ));
        }
        state.pending.try_reserve(1).map_err(|_| {
            ResourceLifecycleError::new(
                ResourceLifecycleErrorKind::AllocationFailed,
                "pending submission allocation failed",
            )
        })?;

        let resources = lease.into_resources();
        state.pending.push(PendingSubmission { fence, resources });
        state.last_submitted = Some(fence);
        Ok(())
    }

    /// Observes completion and retires submissions at or below that fence.
    ///
    /// The returned count is the number of submissions removed. A logical
    /// resource entry is removed only when no active lease or pending
    /// submission still owns its generation-qualified key.
    pub(crate) fn complete(&self, fence: CompletionFence) -> Result<usize, ResourceLifecycleError> {
        let mut state = self.state.borrow_mut();
        if fence.device_generation() != state.device_generation {
            return Err(ResourceLifecycleError::new(
                ResourceLifecycleErrorKind::DeviceGenerationMismatch,
                "completion belongs to an old device generation",
            ));
        }
        if state
            .last_submitted
            .is_some_and(|last| fence.sequence() > last.sequence())
        {
            return Err(ResourceLifecycleError::new(
                ResourceLifecycleErrorKind::InvalidFence,
                "completion fence is beyond submitted work",
            ));
        }
        if state
            .last_completed
            .is_some_and(|last| fence.sequence() <= last.sequence())
        {
            // Repeated and out-of-order observations are harmless. In
            // particular, a backend may report the same completion more than
            // once while the renderer drains its event queue.
            return Ok(0);
        }

        let mut completed_submissions = 0;
        let mut index = 0;
        while index < state.pending.len() {
            if state.pending[index].fence.sequence() <= fence.sequence() {
                let submission = state.pending.swap_remove(index);
                for key in submission.resources {
                    release_resource(&mut state, key);
                }
                completed_submissions += 1;
            } else {
                index += 1;
            }
        }
        state.last_completed = Some(fence);
        Ok(completed_submissions)
    }

    /// Alias for the completion-observation terminology used by renderer code.
    pub(crate) fn signal_completed(
        &self,
        fence: CompletionFence,
    ) -> Result<usize, ResourceLifecycleError> {
        self.complete(fence)
    }

    /// Invalidates all resources from the current device lifetime and switches
    /// the cache to `device_generation`.
    ///
    /// Old packets, leases, pending submissions, and completion observations
    /// cannot affect the replacement generation. CPU Scene/data authority is
    /// outside this cache and is intentionally untouched.
    pub(crate) fn invalidate_device_generation(
        &self,
        device_generation: DeviceGeneration,
    ) -> usize {
        let mut state = self.state.borrow_mut();
        let invalidated = state.entries.len();
        state.device_generation = device_generation;
        state.generation_token = Rc::new(());
        state.entries.clear();
        state.pending.clear();
        state.last_submitted = None;
        state.last_completed = None;
        invalidated
    }

    /// Replaces the cache's device generation, retaining the explicit loss
    /// invalidation behavior under a renderer-oriented name.
    pub(crate) fn replace_device_generation(&self, device_generation: DeviceGeneration) -> usize {
        self.invalidate_device_generation(device_generation)
    }

    /// Number of logical resource keys currently retained.
    pub(crate) fn resource_count(&self) -> usize {
        self.state.borrow().entries.len()
    }

    /// Number of submissions waiting for completion.
    pub(crate) fn pending_submission_count(&self) -> usize {
        self.state.borrow().pending.len()
    }
}

/// Lease for the logical resources acquired by one packet.
#[must_use = "a resource lease must be submitted or kept alive until work ends"]
pub(crate) struct ResourceLease {
    state: Weak<RefCell<CacheState>>,
    generation_token: Rc<()>,
    device_generation: DeviceGeneration,
    resources: Vec<ResourceKey>,
    released: bool,
}

impl ResourceLease {
    /// Device generation associated with this lease.
    pub(crate) fn device_generation(&self) -> DeviceGeneration {
        self.device_generation
    }

    /// Number of logical resources owned by this lease.
    pub(crate) fn resource_count(&self) -> usize {
        self.resources.len()
    }

    fn into_resources(mut self) -> Vec<ResourceKey> {
        self.released = true;
        std::mem::take(&mut self.resources)
    }
}

impl Drop for ResourceLease {
    fn drop(&mut self) {
        if self.released {
            return;
        }
        let Some(state) = self.state.upgrade() else {
            self.resources.clear();
            self.released = true;
            return;
        };
        let mut state = state.borrow_mut();
        if !Rc::ptr_eq(&self.generation_token, &state.generation_token)
            || self.device_generation != state.device_generation
        {
            // Device loss already invalidated the old backend resources. Do
            // not decrement a replacement entry with the same logical ID.
            self.resources.clear();
            self.released = true;
            return;
        }
        for key in self.resources.drain(..) {
            release_resource(&mut state, key);
        }
        self.released = true;
    }
}

fn release_resource(state: &mut CacheState, key: ResourceKey) {
    let should_remove = if let Some(entry) = state.entries.get_mut(&key) {
        entry.owner_count = entry.owner_count.saturating_sub(1);
        entry.owner_count == 0
    } else {
        false
    };
    if should_remove {
        state.entries.remove(&key);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::SceneHandle;
    use crate::frame::FrameSpec;
    use crate::packet::{RenderPacketBuilder, WorkGeneration};
    use lumenplot_engine::bridge::{SrgbRgba8, Viewport};

    const WORK_GENERATION: WorkGeneration = WorkGeneration::new(7);
    const FIRST_DEVICE: DeviceGeneration = DeviceGeneration::new(11);
    const SECOND_DEVICE: DeviceGeneration = DeviceGeneration::new(12);

    fn frame_spec() -> FrameSpec {
        FrameSpec::new(
            [64, 48],
            [4, 4, 60, 44],
            96.0,
            SrgbRgba8::new(31, 119, 180, 255),
            2.0,
            SrgbRgba8::new(255, 255, 255, 255),
        )
        .expect("valid frame spec")
    }

    fn packet(device_generation: DeviceGeneration) -> RenderPacket {
        let view = Viewport::from_bounds(0.0, 1.0, 0.0, 1.0).expect("valid view");
        let mut scene = SceneHandle::new(view).expect("valid scene");
        scene
            .add_series(vec![0.0, 0.5, 1.0], vec![0.0, 1.0, 0.0])
            .expect("valid series");
        let builder = RenderPacketBuilder::new(WORK_GENERATION, device_generation);
        scene
            .resolve_render_packet(&frame_spec(), &builder, WORK_GENERATION, device_generation)
            .expect("valid render packet")
    }

    fn first_resource(packet: &RenderPacket) -> LogicalResourceId {
        packet.resource_ids().next().expect("packet resource")
    }

    #[test]
    fn cache_key_separates_same_logical_resource_by_device_generation() {
        let first_packet = packet(FIRST_DEVICE);
        let logical_id = first_resource(&first_packet);
        let first_key = ResourceKey::new(logical_id, FIRST_DEVICE);
        let second_key = ResourceKey::new(logical_id, SECOND_DEVICE);
        assert_ne!(first_key, second_key);

        let cache = ResourceCache::new(FIRST_DEVICE);
        let lease = cache
            .acquire(&first_packet)
            .expect("first-generation lease");
        assert!(cache.state.borrow().entries.contains_key(&first_key));
        drop(lease);
        assert_eq!(cache.resource_count(), 0);

        cache.invalidate_device_generation(SECOND_DEVICE);
        let replacement = packet(SECOND_DEVICE);
        let lease = cache.acquire(&replacement).expect("replacement lease");
        assert!(!cache.state.borrow().entries.contains_key(&first_key));
        assert!(cache.state.borrow().entries.contains_key(&second_key));
        drop(lease);
    }

    #[test]
    fn lease_lifetime_retains_resources_until_unsubmitted_drop() {
        let cache = ResourceCache::new(FIRST_DEVICE);
        let packet = packet(FIRST_DEVICE);
        let lease = cache.acquire(&packet).expect("lease");
        assert_eq!(lease.device_generation(), FIRST_DEVICE);
        assert_eq!(lease.resource_count(), 2);
        assert_eq!(cache.resource_count(), 2);
        drop(lease);
        assert_eq!(cache.resource_count(), 0);
    }

    #[test]
    fn submitted_resources_retire_only_after_completion() {
        let cache = ResourceCache::new(FIRST_DEVICE);
        let lease = cache.acquire(&packet(FIRST_DEVICE)).expect("lease");
        let fence = CompletionFence::new(FIRST_DEVICE, 4);
        cache.submit(lease, fence).expect("submission");
        assert_eq!(cache.resource_count(), 2);
        assert_eq!(cache.pending_submission_count(), 1);
        assert_eq!(
            cache
                .complete(CompletionFence::new(FIRST_DEVICE, 3))
                .expect("early completion"),
            0
        );
        assert_eq!(cache.resource_count(), 2);
        assert_eq!(cache.complete(fence).expect("completion"), 1);
        assert_eq!(cache.resource_count(), 0);
        assert_eq!(cache.pending_submission_count(), 0);
    }

    #[test]
    fn multiple_owners_prevent_early_retirement() {
        let cache = ResourceCache::new(FIRST_DEVICE);
        let first = cache.acquire(&packet(FIRST_DEVICE)).expect("first lease");
        let second = cache.acquire(&packet(FIRST_DEVICE)).expect("second lease");
        assert_eq!(cache.resource_count(), 2);
        assert_eq!(
            cache
                .state
                .borrow()
                .entries
                .values()
                .next()
                .unwrap()
                .owner_count,
            2
        );

        drop(first);
        assert_eq!(cache.resource_count(), 2);
        assert_eq!(
            cache
                .state
                .borrow()
                .entries
                .values()
                .next()
                .unwrap()
                .owner_count,
            1
        );
        drop(second);
        assert_eq!(cache.resource_count(), 0);
    }

    #[test]
    fn device_loss_invalidates_stale_leases_pending_work_and_completions() {
        let cache = ResourceCache::new(FIRST_DEVICE);
        let old_packet = packet(FIRST_DEVICE);
        let old_revision = old_packet.frame().revision();
        let stale_lease = cache.acquire(&old_packet).expect("old lease");
        let old_submission = cache.acquire(&old_packet).expect("old submission lease");
        let old_fence = CompletionFence::new(FIRST_DEVICE, 4);
        cache
            .submit(old_submission, old_fence)
            .expect("old submission");
        assert_eq!(cache.pending_submission_count(), 1);

        assert_eq!(cache.invalidate_device_generation(SECOND_DEVICE), 2);
        assert_eq!(cache.device_generation(), SECOND_DEVICE);
        assert_eq!(cache.resource_count(), 0);
        assert_eq!(cache.pending_submission_count(), 0);
        assert_eq!(old_packet.frame().revision(), old_revision);
        drop(stale_lease);
        assert_eq!(cache.resource_count(), 0);

        let stale_error = match cache.acquire(&old_packet) {
            Ok(_) => panic!("old packet must be stale after device loss"),
            Err(error) => error,
        };
        assert_eq!(
            stale_error.kind(),
            ResourceLifecycleErrorKind::DeviceGenerationMismatch
        );
        assert_eq!(
            cache
                .complete(old_fence)
                .expect_err("old completion must be rejected")
                .kind(),
            ResourceLifecycleErrorKind::DeviceGenerationMismatch
        );

        let replacement_lease = cache
            .acquire(&packet(SECOND_DEVICE))
            .expect("replacement lease");
        let replacement_fence = CompletionFence::new(SECOND_DEVICE, 1);
        cache
            .submit(replacement_lease, replacement_fence)
            .expect("replacement submission");
        // A stale completion cannot retire a replacement-generation entry.
        assert_eq!(cache.resource_count(), 2);
        assert_eq!(
            cache
                .complete(replacement_fence)
                .expect("replacement completion"),
            1
        );
        assert_eq!(cache.resource_count(), 0);
    }

    #[test]
    fn completion_is_idempotent_for_repeated_observations() {
        let cache = ResourceCache::new(FIRST_DEVICE);
        let fence = CompletionFence::new(FIRST_DEVICE, 9);
        cache
            .submit(cache.acquire(&packet(FIRST_DEVICE)).expect("lease"), fence)
            .expect("submission");
        assert_eq!(cache.signal_completed(fence).expect("first observation"), 1);
        assert_eq!(cache.resource_count(), 0);
        assert_eq!(cache.complete(fence).expect("repeated observation"), 0);
        assert_eq!(cache.resource_count(), 0);
    }
}
