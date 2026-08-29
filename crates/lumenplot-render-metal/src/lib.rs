//! Private B2-P prototype documentation stub for the Metal render lane.
//!
//! The Phase-0 boundary stays documentation-only: the accepted M1 seam
//! (`docs/research/post-v1-metal-fastpath-design-notes.md`) requires a minimal,
//! synchronous, CPU-side frame API in `lumenplot-render-api`, with this crate
//! consuming it behind a default-off feature.
//!
//! The first prototype slice lives in `src/device.rs` — minimal Metal device
//! discovery, compiled only through `tests/compile_gate.rs` on macOS targets,
//! never through the library root. Binding work beyond device acquisition
//! remains deferred to later prototype slices.
