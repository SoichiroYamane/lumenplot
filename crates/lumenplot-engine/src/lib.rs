//! Synchronous private native semantic kernel for LumenPlot Phase-1A.
//!
//! The engine is intentionally unpublished. Its root modules remain private;
//! the hidden bridge is the only cross-crate seam reserved for the facade.

#![allow(dead_code)]

mod data;
mod error;
mod lod;
mod scene;

#[doc(hidden)]
pub mod bridge;
