//! Minimal Metal device discovery for the B2-P prototype lane.
//!
//! This module is deliberately quarantined: it compiles only behind
//! `#[cfg(target_os = "macos")]`, and only into the crate's integration-test
//! binary via `tests/compile_gate.rs`. The library root stays
//! documentation-only by contract (enforced by
//! `scripts/check_workspace_architecture.py`), so no item in this file can
//! widen the crate's public surface.
//!
//! The pinned `objc2-metal` edge carries the bare `std` feature set (no
//! generated classes), so the declaration below is the entire binding surface
//! this first slice needs. Follow-up slices must grow it here, inside the
//! quarantine, rather than through new external edges.
//!
//! The gate compiles this module without ever calling into it, so the whole
//! module is allowed to be dead code by construction.
#![allow(dead_code)]

use core::fmt;

use objc2::rc::Retained;
use objc2::runtime::AnyObject;

/// Handle to the system's preferred Metal device.
///
/// Dropping the handle releases the underlying Objective-C object.
/// Acquisition is environment-dependent: on machines without a usable device
/// (unsupported hardware, missing framework, headless virtual machine)
/// [`SystemDevice::acquire`] returns [`None`] instead of failing loudly,
/// mirroring the prototype-lane posture of LP-PLAT-011.
pub struct SystemDevice {
    inner: Retained<AnyObject>,
}

#[link(name = "Metal", kind = "framework")]
#[link(name = "CoreGraphics", kind = "framework")]
// Two framework links are intentional; clippy counts them as duplicate
// attributes.
#[allow(clippy::duplicated_attributes)]
unsafe extern "C" {
    /// Returns the preferred system-default Metal device, or null.
    ///
    /// The returned reference follows the create-rule: it is retained, and
    /// ownership transfers to the caller.
    fn MTLCreateSystemDefaultDevice() -> *mut AnyObject;
}

impl SystemDevice {
    /// Acquires the system's preferred Metal device, or `None` when Metal is
    /// unavailable.
    ///
    /// This mirrors `MTLCreateSystemDefaultDevice`: the system picks the GPU
    /// associated with the main display, which is exactly the posture the
    /// prototype lane needs for its first measurement slice.
    pub fn acquire() -> Option<Self> {
        // SAFETY: plain FFI call; see the extern declaration above for the
        // returned-pointer contract.
        let raw = unsafe { MTLCreateSystemDefaultDevice() };
        // A null result means Metal is unavailable; there is nothing to
        // release in that case.
        //
        // SAFETY: a non-null create-rule pointer carries a +1 retain the
        // framework hands to us; `Retained` adopts it and releases on drop.
        let inner = unsafe { Retained::from_raw(raw) }?;
        Some(Self { inner })
    }
}

impl fmt::Debug for SystemDevice {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("SystemDevice")
            .finish_non_exhaustive()
    }
}
