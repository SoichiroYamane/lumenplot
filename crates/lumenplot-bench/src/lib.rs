//! Private O-08 benchmark harness crate (documentation-only library target).
//!
//! The benchmark runner required by ADR 0006 §O-08 lives entirely in the
//! binary target: `src/main.rs` declares the private modules (`clocks`,
//! `manifest`, `runner`) with `#[path]` attributes so only the bench binary
//! compiles them. This library target intentionally carries no code and no
//! public items, exactly like the Phase-0 documentation stubs of the other
//! internal crates; the workspace architecture checker enforces that shape
//! once the bench sentinel (any `src/*.rs` beyond `src/lib.rs`) is present.
//!
//! ## Fresh-process blocks
//!
//! The O-08 protocol measures 5 fresh-process blocks of at least 1000 frames
//! each. Freshness is achieved by re-executing this same binary with the
//! internal mode flag `--internal-block-runner`: the parent process spawns a
//! child per block (`std::process::Command` over
//! `std::env::current_exe()`), waits for it to exit, and folds the child's
//! per-block summary into the run manifest. Each child therefore starts with
//! its own allocator, process-lifetime state, and CPU caches, which keeps
//! block statistics independent as required by the protocol.
//!
//! ## Clock domains
//!
//! Four clock domains are observed per frame (see `clocks.rs`): the
//! scheduler domain (`event_accept_to_*`, CPU monotonic), the GPU timestamp
//! domain (own base, never merged into scheduler nanoseconds), the queue
//! domain (`queue_*`, CPU monotonic completion/readback observations), and
//! the scanout domain (marker only when available). Cross-domain derived
//! values carry a `derived_` prefix and are excluded from gate statistics.
//! Domains whose instrumentation is unavailable are reported with
//! `"available": false` and null values instead of zeros.
//!
//! The accelerated profile resolves an accepted frame packet and submits it
//! to the portable offscreen renderer. Its scheduler sample ends at the
//! offscreen readback boundary; no window surface, physical present, or
//! scanout claim is implied.
