//! SINK-F2 grid tick carrier: deterministic per-axis major-tick locator.
//!
//! The native path cannot consume adapter tick state (one-way DAG
//! `Matplotlib -> adapter -> engine` plus the M2 EXIT-1 engine-only export
//! edge), so grid geometry needs an in-engine computation. This module is
//! that computation's first half: a pure, crate-internal locator of
//! `(AxisRange, AxisScale)` per axis. The second half (carrier vecs stamped
//! on `LineFrame` in `frame::resolve_line_frame`) consumes it.
//!
//! Contract (commander CONTRACT RULING Q1-Q4 on the GRID-INK-CONTRACT
//! proposal):
//!
//! - The locator is `pub(crate)` and pure: same `(range, scale)` always
//!   yields the same tick vec, with no global state and no new public API.
//! - Ticks are data coordinates filtered to the in-view closed interval,
//!   mirroring the adapter rule (`axis.get_ticklocs` filtered into view in
//!   `backend_preflight.py`). Sinks project them through the same scale rule
//!   as series data (linear fraction; log10 fraction per LP-FUNC-004).
//! - Linear axes use 1/2/5 x 10^k "nice" steps targeting at most ~10 ticks,
//!   so ordinary views stay far under the cap. Log10 axes emit integer
//!   decades only (major ticks); a decade span wider than the cap refuses.
//! - Per-axis fixed cap [`MAX_TICKS_PER_AXIS`]: unbounded tick counts
//!   refuse with the existing `CapacityExceeded` pattern at resolve time
//!   (fail-before-allocate: the count is checked before the vec is built),
//!   never OOM and never a silent skip (a silent skip would be an
//!   LP-MPL-020-class degradation and strict-ineligible).
//!
//! Cap rationale: Matplotlib's default major locator yields on the order of
//! ten ticks, so 64 per axis keeps more than 5x headroom (wide decade spans
//! included) while bounding the carried state to 128 `f64`s (~1 KiB) per
//! frame -- negligible against the `MAX_FRAME_POINTS` 1_000_000 frame
//! budget. Raising the constant needs a capacity review against the frame
//! ceilings (`MAX_FRAME_SERIES/SEGMENTS/POINTS`); the count check below is
//! the enforcement point.
//!
//! Validation rule (ruling Q3): the stamped vecs need no separate digest.
//! They are a deterministic function of viewport ranges, scales, and this
//! cap, so the existing retained-reuse gate -- scene-revision equality (any
//! viewport/scales commit bumps `SceneRevision`) plus the carried
//! `(grid_visible, grid_revision)` pair equality -- already covers them:
//! equal gate inputs always reconstruct equal vecs.

use std::cmp::Ordering;

use crate::error::{SceneError, SceneErrorKind};
use crate::scene::{AxisRange, AxisScale};

/// Per-axis fixed cap on carried major-tick positions.
///
/// See the module docs for the rationale. Counts above this refuse with
/// `CapacityExceeded` before any allocation.
pub(crate) const MAX_TICKS_PER_AXIS: usize = 64;

/// Major-tick positions in data coordinates for one axis.
///
/// Pure function of `(range, scale)`: deterministic, no retained state.
/// The returned positions lie inside the closed in-view interval
/// `[range.min(), range.max()]`. Log10 with a non-positive lower bound
/// refuses `InvalidInput` (mirrors `AxisScales::validate`); tick counts
/// above [`MAX_TICKS_PER_AXIS`] refuse `CapacityExceeded`.
pub(crate) fn major_ticks_for_axis(
    range: AxisRange,
    scale: AxisScale,
) -> Result<Vec<f64>, SceneError> {
    // Exhaustive within the defining crate (`#[non_exhaustive]` only
    // restricts downstream crates, of which the engine has none).
    match scale {
        AxisScale::Linear => linear_ticks(range),
        AxisScale::Log10 => log_ticks(range),
    }
}

/// 1/2/5 x 10^k nice-step ticks over a linear range.
fn linear_ticks(range: AxisRange) -> Result<Vec<f64>, SceneError> {
    let (min, max) = (range.min(), range.max());
    if !min.is_finite() || !max.is_finite() || min.partial_cmp(&max) != Some(Ordering::Less) {
        return Err(SceneError::new(SceneErrorKind::InvalidInput));
    }
    let span = max - min;
    if !span.is_finite() || span <= 0.0 {
        return Err(SceneError::new(SceneErrorKind::InvalidInput));
    }
    let raw_step = span / 10.0;
    if !raw_step.is_finite() || raw_step <= 0.0 {
        // Degenerate subnormal span: no positive step is derivable.
        // Refuse closed rather than guessing an unbounded or empty set.
        return Err(SceneError::new(SceneErrorKind::CapacityExceeded));
    }
    let magnitude = 10.0_f64.powf(raw_step.log10().floor());
    if !magnitude.is_finite() || magnitude <= 0.0 {
        return Err(SceneError::new(SceneErrorKind::CapacityExceeded));
    }
    // Finest 1/2/5 multiple whose tick count stays at or under ~10. The
    // 10x arm always qualifies (span / (10 * magnitude) < 10), so `step`
    // leaves this loop positive and finite.
    let mut step = magnitude * 10.0;
    for multiple in [1.0_f64, 2.0, 5.0, 10.0] {
        let candidate = magnitude * multiple;
        if span / candidate <= 9.0 {
            step = candidate;
            break;
        }
    }
    if !step.is_finite() || step <= 0.0 {
        return Err(SceneError::new(SceneErrorKind::CapacityExceeded));
    }
    // Epsilon keeps boundary-exact limits (e.g. max exactly on a multiple)
    // inclusive on both ends despite binary division rounding.
    let epsilon = 1.0e-9;
    let key_lo = (min / step - epsilon).ceil();
    let key_hi = (max / step + epsilon).floor();
    if !key_lo.is_finite() || !key_hi.is_finite() {
        return Err(SceneError::new(SceneErrorKind::CapacityExceeded));
    }
    // f64-to-i64 casts saturate; the span/step ratio is bounded (~<=10
    // keys wide, |key| <= ~2^53 by float density), so saturation cannot
    // trigger on reachable inputs, and the count check below stays exact.
    let key_lo = key_lo as i64;
    let key_hi = key_hi as i64;
    let count = key_hi
        .checked_sub(key_lo)
        .and_then(|span| span.checked_add(1))
        .ok_or_else(|| SceneError::new(SceneErrorKind::CapacityExceeded))?;
    if count <= 0 {
        return Ok(Vec::new());
    }
    if count as u64 > MAX_TICKS_PER_AXIS as u64 {
        return Err(SceneError::new(SceneErrorKind::CapacityExceeded));
    }
    let count = count as usize;
    let mut ticks = Vec::new();
    ticks
        .try_reserve(count)
        .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
    for key in key_lo..=key_hi {
        ticks.push(key as f64 * step);
    }
    Ok(ticks)
}

/// Integer-decade major ticks over a log10 range.
fn log_ticks(range: AxisRange) -> Result<Vec<f64>, SceneError> {
    let (min, max) = (range.min(), range.max());
    if !min.is_finite() || !max.is_finite() || min.partial_cmp(&max) != Some(Ordering::Less) {
        return Err(SceneError::new(SceneErrorKind::InvalidInput));
    }
    if min <= 0.0 {
        // log10 is undefined at/below zero; mirrors AxisScales::validate.
        return Err(SceneError::new(SceneErrorKind::InvalidInput));
    }
    let exponent_lo = min.log10().ceil();
    let exponent_hi = max.log10().floor();
    if !exponent_lo.is_finite() || !exponent_hi.is_finite() {
        return Err(SceneError::new(SceneErrorKind::InvalidInput));
    }
    // Finite positive doubles have log10 in (-324, 309]; the i32 casts are
    // exact on every reachable input.
    let exponent_lo = exponent_lo as i32;
    let exponent_hi = exponent_hi as i32;
    let count = exponent_hi
        .checked_sub(exponent_lo)
        .and_then(|span| span.checked_add(1))
        .ok_or_else(|| SceneError::new(SceneErrorKind::CapacityExceeded))?;
    if count <= 0 {
        // Range sits strictly inside one decade: no major tick in view.
        return Ok(Vec::new());
    }
    if count as u64 > MAX_TICKS_PER_AXIS as u64 {
        return Err(SceneError::new(SceneErrorKind::CapacityExceeded));
    }
    let count = count as usize;
    let mut ticks = Vec::new();
    ticks
        .try_reserve(count)
        .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
    for exponent in exponent_lo..=exponent_hi {
        ticks.push(10.0_f64.powi(exponent));
    }
    Ok(ticks)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn assert_close(actual: f64, expected: f64) {
        assert!(
            (actual - expected).abs() <= 1.0e-9,
            "{actual} != {expected}"
        );
    }

    fn linear_range(min: f64, max: f64) -> (AxisRange, AxisScale) {
        (
            AxisRange::new(min, max).expect("linear range"),
            AxisScale::Linear,
        )
    }

    fn log_range(min: f64, max: f64) -> (AxisRange, AxisScale) {
        (
            AxisRange::new(min, max).expect("log range"),
            AxisScale::Log10,
        )
    }

    #[test]
    fn linear_locator_uses_nice_steps_and_linear_fractions() {
        // [0, 10] takes the 2.0 nice step: 6 in-view ticks.
        let (range, scale) = linear_range(0.0, 10.0);
        let ticks = major_ticks_for_axis(range, scale).expect("linear ticks");
        assert_eq!(ticks.len(), 6);
        for (tick, expected) in ticks.iter().zip([0.0, 2.0, 4.0, 6.0, 8.0, 10.0]) {
            assert_close(*tick, expected);
        }
        // Linear-fraction mapping (adapter `_fraction` linear branch):
        // the carried data coords land uniformly over [0, 1].
        for (tick, expected) in ticks.iter().zip([0.0, 0.2, 0.4, 0.6, 0.8, 1.0]) {
            assert_close((tick - 0.0) / (10.0 - 0.0), expected);
        }
        // Deterministic reconstruction: same inputs rebuild equal vecs.
        let rebuilt = major_ticks_for_axis(range, scale).expect("rebuild");
        assert_eq!(ticks, rebuilt);
    }

    #[test]
    fn log_locator_emits_decades_with_log10_fractions() {
        // [1, 1000] spans exactly decades 0..=3.
        let (range, scale) = log_range(1.0, 1000.0);
        let ticks = major_ticks_for_axis(range, scale).expect("log ticks");
        assert_eq!(ticks.len(), 4);
        for (tick, expected) in ticks.iter().zip([1.0, 10.0, 100.0, 1000.0]) {
            assert_close(*tick, expected);
        }
        // Log10-fraction mapping (adapter `_fraction` log branch):
        // (log10(v) - log10(lo)) / (log10(hi) - log10(lo)).
        for (tick, expected) in ticks.iter().zip([0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0]) {
            let fraction =
                (tick.log10() - 1.0_f64.log10()) / (1000.0_f64.log10() - 1.0_f64.log10());
            assert_close(fraction, expected);
        }
        // Sub-decade ranges carry no major tick, deterministically.
        let (narrow, log) = log_range(2.0, 5.0);
        assert_eq!(
            major_ticks_for_axis(narrow, log).expect("narrow log"),
            Vec::<f64>::new()
        );
    }

    #[test]
    fn locator_refuses_bad_input_and_unbounded_counts() {
        // Log10 at/below zero mirrors AxisScales::validate.
        let (bad, log) = log_range(0.0, 10.0);
        assert_eq!(
            major_ticks_for_axis(bad, log)
                .expect_err("non-positive log")
                .kind(),
            SceneErrorKind::InvalidInput
        );
        // A 101-decade span yields ~101 ticks over the 64-per-axis cap.
        let (wide, log) = log_range(1.0, 1.0e100);
        assert_eq!(
            major_ticks_for_axis(wide, log)
                .expect_err("unbounded decades")
                .kind(),
            SceneErrorKind::CapacityExceeded
        );
        // Ordinary wide linear views stay bounded under the cap.
        let (linear_wide, linear) = linear_range(-1.0e12, 1.0e12);
        let ticks = major_ticks_for_axis(linear_wide, linear).expect("wide linear");
        assert!(ticks.len() <= MAX_TICKS_PER_AXIS);
        assert!(!ticks.is_empty());
    }
}
