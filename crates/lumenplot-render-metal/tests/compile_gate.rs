//! Compile gate for the B2-P Metal prototype lane.
//!
//! The library root stays documentation-only by the static architecture
//! contract (`scripts/check_workspace_architecture.py`), so this test is the
//! only place `src/device.rs` is compiled. It pulls the module in through a
//! `#[path]` include, keeping one copy of truth: whatever compiles here is
//! exactly what later prototype slices will consume.
//!
//! On non-macOS hosts this file compiles to an empty test binary; the
//! cross-target verification for macOS still exercises the real sources
//! through `cargo check --target <apple-target>`.

#![cfg(target_os = "macos")]

#[path = "../src/device.rs"]
mod device;
