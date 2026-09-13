//! Skeletal Phase-0 documentation stub for the window/event host crate.
//!
//! Accepted DAG identity (commander ruling 2026-09-13; ADR 0003 amendment):
//! `crates/lumenplot-window` hosts the native window/event loop over
//! `lumenplot-runtime` and `lumenplot-render-wgpu`, with `publish = false`.
//! The only permitted external edge is pinned winit 0.30.x (implementation
//! baseline ADR 0008: winit 0.30.13); no other external dependency is
//! admitted.
//!
//! Main-thread ownership (runtime, surface, GPU device) follows ADR 0005:
//! worker work never assumes ownership of those concrete objects, and lower
//! layers never name concrete window types.
//!
//! The M1 seam surface (window-trait seam, engine-paced redraw cadence,
//! close/idempotent-shutdown surface) is designed in the M1 lane with review
//! as the gate. This stub stays documentation-only: no public items, no seam
//! signatures, no production code.
