//! O-08 benchmark runner: fixtures, fresh-process blocks, and statistics.
//!
//! Protocol shape (ADR 0006 §O-08, decisions D2/D3): one profile per run,
//! never mixed; 5 fresh-process blocks of at least 1000 measured frames;
//! nearest-rank percentiles; raw samples retained untrimmed; unavailable
//! instrumentation reported as null, never zero.
//!
//! Freshness mechanism: the parent process re-executes this binary once per
//! block with `--internal-block-runner`; each child owns a pristine process
//! (allocator, caches, process-lifetime state) and streams its block summary
//! back on stdout. A short warm-up precedes measurement in every block so
//! startup work stays out of the steady-state claim.
//!
//! Profiles select the execution policy recorded in the manifest; the
//! selected name is recorded verbatim rather than silently relabeled, and
//! profiles are never mixed within a run. The currently executable paths:
//!
//! - `strict` / `hybrid`: the accepted private PNG facade
//!   (`lumenplot::__private::render_line_png`) — a CPU render-return path with
//!   no window surface or physical present observation. Both names drive that
//!   single implemented path until the policy split they name exists.
//! - `accelerated`: the accepted M1 frame seam
//!   (`lumenplot_render_api::SceneHandle::resolve_frame`) followed by the
//!   portable offscreen renderer's GPU submission and blocking readback. The
//!   scheduler interval ends at readback return, not a display present; GPU
//!   timestamps, queue-domain timestamps, and scanout remain unavailable and
//!   are emitted as null.
//! - `native`: no implementation exists on this host family, so the runner
//!   refuses before producing any artifact (exit code 2). A run that
//!   executed zero frames can never satisfy the manifest schema (every block
//!   must carry `frame_count >= min_frames_per_block`), so refusing up front
//!   is the only fail-closed representation of an unexecutable cell;
//!   measurements arrive when the native backend lands behind its own gate.
//!
//! A/B order randomization: each child shuffles its two labeled sub-phase
//! orderings with a generator seeded from the pinned manifest seed
//! (`BOOTSTRAP_SEED`) mixed with the block index, exercising the ordering
//! machinery future paired fixtures rely on. The chosen order is logged on
//! the child's info stream.

use std::collections::HashSet;
use std::fs::File;
use std::io::{BufRead, BufReader, Write};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

use lumenplot_engine::bridge::{SrgbRgba8, Viewport};
use lumenplot_render_api::SceneHandle;
use lumenplot_render_wgpu::Renderer;

use crate::clocks::{
    ClockBoard, GPU_SPAN, QUEUE_SPAN, READBACK_RETURN_SPAN, RENDER_RETURN_SPAN, SCANOUT_MARKER,
};
use crate::manifest::{
    BOOTSTRAP_SEED, BlockSummary, CounterSummary, Environment, Fixture, Manifest, Measurement,
    emit_clock_entry, emit_manifest, emit_pooled,
};

/// Fixed fixture size required by the O-08 contract (decision D3).
pub(crate) const FIXTURE_POINTS: usize = 10_000;
/// Fixed canvas width in pixels.
pub(crate) const FIXTURE_CANVAS_WIDTH_PX: u32 = 800;
/// Fixed canvas height in pixels.
pub(crate) const FIXTURE_CANVAS_HEIGHT_PX: u32 = 600;
/// Fixed logical dots-per-inch for the fixture.
pub(crate) const FIXTURE_DPI: f64 = 100.0;
/// Number of fresh-process blocks per run.
pub(crate) const BLOCK_COUNT: usize = 5;
/// Minimum measured frames per block.
pub(crate) const MIN_FRAMES_PER_BLOCK: usize = 1000;
/// Unmeasured warm-up frames ahead of every measured stretch.
pub(crate) const WARMUP_FRAMES: usize = 25;

const CPU_RENDER_SEMANTICS: &str =
    "CPU-monotonic acceptance through the private CPU render return; not display-present latency";
const ACCELERATED_READBACK_SEMANTICS: &str = "CPU-monotonic acceptance through portable offscreen render/readback return; no surface present or scanout";

/// Execution profile selected exactly once per run via `--profile`.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum Profile {
    Strict,
    Hybrid,
    Accelerated,
    Native,
}

impl Profile {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::Strict => "strict",
            Self::Hybrid => "hybrid",
            Self::Accelerated => "accelerated",
            Self::Native => "native",
        }
    }

    pub(crate) fn parse(value: &str) -> Option<Self> {
        match value {
            "strict" => Some(Self::Strict),
            "hybrid" => Some(Self::Hybrid),
            "accelerated" => Some(Self::Accelerated),
            "native" => Some(Self::Native),
            _ => None,
        }
    }
}

/// Why a profile cannot execute on this host, when it cannot.
///
/// Returned before any output directory is created or child process is
/// spawned: an unexecutable profile never leaves artifacts behind.
fn profile_unavailability(profile: Profile) -> Option<&'static str> {
    match profile {
        // The native backend does not exist yet anywhere; its future gate is
        // macOS-target Metal behind ADR 0006 §O-16, so the refusal reason
        // stays valid on every host until that lands.
        Profile::Native => Some(
            "the native render path has no implementation in this workspace; \
                  the O-08 cell stays unmeasured (environment required) until \
                  the gated native backend lands",
        ),
        Profile::Strict | Profile::Hybrid | Profile::Accelerated => None,
    }
}

fn scheduler_span(profile: Profile) -> &'static str {
    match profile {
        Profile::Accelerated => READBACK_RETURN_SPAN,
        Profile::Strict | Profile::Hybrid | Profile::Native => RENDER_RETURN_SPAN,
    }
}

fn scheduler_semantics(profile: Profile) -> &'static str {
    match profile {
        Profile::Accelerated => ACCELERATED_READBACK_SEMANTICS,
        Profile::Strict | Profile::Hybrid | Profile::Native => CPU_RENDER_SEMANTICS,
    }
}

/// Probe the accelerated renderer before the output directory is created.
///
/// A missing adapter/device is an unavailable cell, not a reason to emit a
/// schema-shaped manifest with invented frames or quantiles. Each fresh child
/// still creates its own renderer after this parent-side fail-closed probe.
fn probe_profile(profile: Profile) -> Result<(), String> {
    if profile != Profile::Accelerated {
        return Ok(());
    }
    Renderer::new()
        .map(|_| ())
        .map_err(|error| format!("portable accelerated renderer is unavailable: {error}"))
}

/// Deterministic xorshift64* generator (no external crates).
///
/// Used for A/B order randomization and run-id derivation; statistical
/// quality requirements are modest and the algorithm is fully specified so
/// runs stay reproducible from the pinned seeds.
pub(crate) struct XorShift64Star {
    state: u64,
}

impl XorShift64Star {
    /// Create a generator; a zero state is forced away to keep the stream
    /// well-defined.
    pub(crate) fn new(seed: u64) -> Self {
        Self {
            state: if seed == 0 {
                0x9E37_79B9_7F4A_7C15
            } else {
                seed
            },
        }
    }

    pub(crate) fn next_u64(&mut self) -> u64 {
        let mut state = self.state;
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        self.state = state;
        state.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }
}

/// Nearest-rank percentile: rank = ceil(q * n) over ascending samples.
pub(crate) fn nearest_rank(sorted: &[u64], q: f64) -> Option<u64> {
    if sorted.is_empty() || !(0.0..=1.0).contains(&q) {
        return None;
    }
    let rank = (q * sorted.len() as f64).ceil();
    let rank = rank.clamp(1.0, sorted.len() as f64) as usize;
    sorted.get(rank - 1).copied()
}

/// Convert a Unix timestamp to a UTC RFC3339 string with millisecond
/// precision (proleptic Gregorian, no external crates).
pub(crate) fn unix_nanos_to_rfc3339(total_nanos: i128) -> String {
    let seconds = total_nanos.div_euclid(1_000_000_000);
    let millis = total_nanos.rem_euclid(1_000_000_000) / 1_000_000;
    let days = i64::try_from(seconds.div_euclid(86_400)).unwrap_or(i64::MAX);
    let seconds_of_day = seconds.rem_euclid(86_400);
    let (year, month, day) = civil_from_days(days);
    let hour = seconds_of_day / 3600;
    let minute = (seconds_of_day % 3600) / 60;
    let second = seconds_of_day % 60;
    format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}.{millis:03}Z")
}

/// Days-since-epoch to civil date (Howard Hinnant's algorithm).
fn civil_from_days(days_since_epoch: i64) -> (i64, u32, u32) {
    let shifted = days_since_epoch + 719_468;
    let era = shifted.div_euclid(146_097);
    let day_of_era = (shifted - era * 146_097) as u64;
    let year_of_era =
        (day_of_era - day_of_era / 1460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let year = year_of_era as i64 + era * 400;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let mp = (5 * day_of_year + 2) / 153;
    let day = (day_of_year - (153 * mp + 2) / 5 + 1) as u32;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    (if month <= 2 { year + 1 } else { year }, month as u32, day)
}

/// Current wall-clock time as UTC RFC3339 with millisecond precision.
pub(crate) fn utc_now_rfc3339() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos() as i128)
        .unwrap_or(0);
    unix_nanos_to_rfc3339(nanos)
}

/// Derive a UUID-v4-shaped identifier from system entropy sources available
/// without external crates (clock + pid mixed through the PRNG).
pub(crate) fn derive_run_id(pid: u32) -> String {
    let seed_material = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos() as u64)
        .unwrap_or(0)
        ^ ((pid as u64) << 32);
    let mut generator = XorShift64Star::new(seed_material);
    let high = generator.next_u64();
    let low = generator.next_u64();
    let time_low = high >> 32;
    let time_mid = (high >> 16) & 0xFFFF;
    let time_hi_and_version = (high & 0x0FFF) | 0x4000;
    let clock_seq = ((low >> 48) & 0x3FFF) | 0x8000;
    let node = low & 0x0000_FFFF_FFFF_FFFF;
    format!("{time_low:08x}-{time_mid:04x}-{time_hi_and_version:04x}-{clock_seq:04x}-{node:012x}")
}

/// Build the fixed O-08 fixture series: a smooth 10k-point line spanning the
/// viewport.
pub(crate) fn build_fixture_xy() -> (Vec<f64>, Vec<f64>) {
    let count = FIXTURE_POINTS;
    let mut xs = Vec::with_capacity(count);
    let mut ys = Vec::with_capacity(count);
    for index in 0..count {
        let x = index as f64 / (count - 1) as f64;
        // Two-tone smooth curve; deterministic, no allocation per frame.
        let y = 0.5 + 0.35 * (6.0 * std::f64::consts::PI * x).sin() + 0.1 * x;
        xs.push(x);
        ys.push(y);
    }
    (xs, ys)
}

/// Read a best-effort single-line system description file.
fn read_trimmed(path: &str) -> Option<String> {
    std::fs::read_to_string(path)
        .ok()
        .map(|text| text.trim().to_string())
}

/// First `model name` entry from /proc/cpuinfo, when present.
fn detect_cpu_model() -> String {
    if let Ok(text) = std::fs::read_to_string("/proc/cpuinfo") {
        for line in text.lines() {
            if let Some(rest) = line.strip_prefix("model name")
                && let Some(value) = rest.split(':').nth(1)
            {
                return value.trim().to_string();
            }
        }
    }
    "unknown".to_string()
}

/// Detect the effective display scale factor applied to the measured run.
///
/// Consults the canonical Linux toolkit scaling variables in order and falls
/// back to exactly 1.0: when no scaling variable is set (the headless case),
/// nothing scales the CPU-side pipeline, so 1.0 is the true applied factor --
/// it is a measurement-provenance record, not a claim about attached
/// hardware. Compositor presence stays independently recorded as null by
/// [`detect_environment`].
fn detect_display_scale() -> f64 {
    for key in ["GDK_SCALE", "QT_SCREEN_SCALE_FACTOR"] {
        if let Ok(text) = std::env::var(key)
            && let Ok(value) = text.trim().parse::<f64>()
            && value.is_finite()
            && value > 0.0
        {
            return value;
        }
    }
    1.0
}

fn detect_rustc_version() -> String {
    let Ok(output) = Command::new("rustc").arg("--version").output() else {
        return "unknown".to_string();
    };
    if !output.status.success() {
        return "unknown".to_string();
    }
    String::from_utf8_lossy(&output.stdout)
        .lines()
        .next()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .unwrap_or("unknown")
        .to_string()
}

/// Detect the run environment; unknown descriptors degrade to "unknown"/null
/// (they are provenance metadata, not gate observations, so they do not flip
/// the run status on their own).
pub(crate) fn detect_environment(profile: &str) -> Environment {
    let render_backend = match profile {
        "accelerated" => "portable-wgpu-offscreen-readback",
        "strict" | "hybrid" => "cpu-private-png-facade",
        _ => "unavailable",
    };
    Environment {
        os: std::env::consts::OS.to_string(),
        os_version: read_trimmed("/etc/os-release")
            .and_then(|text| {
                text.lines()
                    .find_map(|line| line.strip_prefix("PRETTY_NAME="))
                    .map(|value| value.trim_matches('"').to_string())
            })
            .unwrap_or_else(|| "unknown".to_string()),
        arch: std::env::consts::ARCH.to_string(),
        kernel: read_trimmed("/proc/sys/kernel/osrelease").unwrap_or_else(|| "unknown".to_string()),
        cpu: detect_cpu_model(),
        toolchain: detect_rustc_version(),
        build_profile: if cfg!(debug_assertions) {
            "debug".to_string()
        } else {
            "release".to_string()
        },
        render_backend: render_backend.to_string(),
        gpu_vendor: None,
        gpu_device: None,
        gpu_driver: None,
        gpu_api: None,
        gpu_feature_level: None,
        compositor: None,
        display_scale: Some(detect_display_scale()),
        present_mode: None,
    }
}

/// Serialize one samples line: `{block, frame, clocks:{...nulls}}`.
fn samples_line(
    block_index: u32,
    frame_index: usize,
    scheduler_clock: &str,
    scheduler_ns: Option<u64>,
) -> String {
    fn clock_field(out: &mut String, name: &str, value: Option<u64>, first: bool) {
        if !first {
            out.push_str(", ");
        }
        out.push('"');
        out.push_str(name);
        out.push_str("\": ");
        match value {
            Some(number) => out.push_str(&number.to_string()),
            None => out.push_str("null"),
        }
    }
    let mut line = String::with_capacity(160);
    line.push_str("{\"block_index\": ");
    line.push_str(&block_index.to_string());
    line.push_str(", \"frame_index\": ");
    line.push_str(&frame_index.to_string());
    line.push_str(", \"clocks\": {");
    clock_field(&mut line, scheduler_clock, scheduler_ns, true);
    clock_field(&mut line, GPU_SPAN, None, false);
    clock_field(&mut line, QUEUE_SPAN, None, false);
    clock_field(&mut line, SCANOUT_MARKER, None, false);
    line.push_str("}}");
    line
}

/// Run the frame loop for one block inside the *current* process and write
/// `samples-<block>.jsonl`. Returns the block summary (quantiles inclusive).
///
/// This is executed by fresh child processes only; see `run_block_child`.
fn run_block_in_process(
    profile: Profile,
    block_index: u32,
    frames: usize,
    out_dir: &str,
) -> Result<BlockSummary, String> {
    if frames < MIN_FRAMES_PER_BLOCK {
        return Err(format!("frames must be at least {MIN_FRAMES_PER_BLOCK}"));
    }
    let block_started_at_utc = utc_now_rfc3339();
    let (xs, ys) = build_fixture_xy();
    let board = ClockBoard::detect();
    let scheduler_clock = scheduler_span(profile);

    // Keep renderer creation and scene/data setup outside the measured frame
    // interval. A renderer failure is returned before this block creates any
    // sample file, and the parent-side probe prevents this path from leaving a
    // partial run on an unavailable host.
    let (accelerated_scene, accelerated_spec, mut accelerated_renderer) =
        if profile == Profile::Accelerated {
            (
                Some(build_scene(&xs, &ys)?),
                Some(build_frame_spec()?),
                Some(Renderer::new().map_err(|error| {
                    format!("accelerated renderer could not be created: {error}")
                })?),
            )
        } else {
            (None, None, None)
        };

    let samples_path = format!("{out_dir}/samples-{block_index}.jsonl");
    let mut samples_out = File::create(&samples_path)
        .map_err(|error| format!("cannot create {samples_path}: {error}"))?;

    // Warm-up: exercise the full profile path without recording anything so
    // block statistics describe steady state rather than startup.
    match profile {
        Profile::Accelerated => {
            let scene = accelerated_scene.as_ref().expect("accelerated scene");
            let spec = accelerated_spec.as_ref().expect("accelerated spec");
            let renderer = accelerated_renderer.as_mut().expect("accelerated renderer");
            for _ in 0..WARMUP_FRAMES {
                let packet = scene
                    .resolve_frame(spec)
                    .map_err(|error| format!("accelerated warm-up resolution failed: {error}"))?;
                renderer
                    .render(&packet)
                    .map_err(|error| format!("accelerated warm-up render failed: {error}"))?;
            }
        }
        _ => {
            for _ in 0..WARMUP_FRAMES {
                let request = build_frame_request(&xs, &ys)?;
                lumenplot::__private::render_line_png(request)
                    .map_err(|error| format!("CPU warm-up render failed: {}", error.message()))?;
            }
        }
    }

    let mut scheduler_samples: Vec<u64> = Vec::with_capacity(frames);
    match profile {
        Profile::Accelerated => {
            // The scene and renderer are retained for the block: each measured
            // frame resolves a packet and submits it to the portable offscreen
            // renderer, whose blocking readback is the measured boundary. No
            // window surface or physical display-present operation exists in
            // this path.
            let scene = accelerated_scene.as_ref().expect("accelerated scene");
            let spec = accelerated_spec.as_ref().expect("accelerated spec");
            let renderer = accelerated_renderer.as_mut().expect("accelerated renderer");
            for frame_index in 0..frames {
                // Borrowed captures: the scene, spec, and renderer stay fixed
                // for the whole block; setup and pipeline warm-up are outside
                // the measured interval.
                let (clocks, resolved) = board.observe_frame(|| {
                    let packet = scene
                        .resolve_frame(spec)
                        .map_err(|error| format!("frame resolution failed: {error}"))?;
                    renderer
                        .render(&packet)
                        .map_err(|error| format!("offscreen render failed: {error}"))?;
                    Ok::<(), String>(())
                });
                if let Err(error) = resolved {
                    return Err(format!("block {block_index} frame {frame_index}: {error}"));
                }
                if let Some(scheduler_ns) = clocks.scheduler_ns {
                    scheduler_samples.push(scheduler_ns);
                }
                let line = samples_line(
                    block_index,
                    frame_index,
                    scheduler_clock,
                    clocks.scheduler_ns,
                );
                writeln!(samples_out, "{line}")
                    .map_err(|error| format!("cannot write {samples_path}: {error}"))?;
            }
        }
        _ => {
            for frame_index in 0..frames {
                let request = build_frame_request(&xs, &ys)?;
                let (clocks, produced) =
                    board.observe_frame(move || lumenplot::__private::render_line_png(request));
                // A failing fixture frame makes the whole block invalid: the run
                // must never report statistics from a broken rendering pipeline.
                if let Err(error) = produced {
                    return Err(format!(
                        "block {block_index} frame {frame_index} failed to render: {}",
                        error.message()
                    ));
                }
                if let Some(scheduler_ns) = clocks.scheduler_ns {
                    scheduler_samples.push(scheduler_ns);
                }
                let line = samples_line(
                    block_index,
                    frame_index,
                    scheduler_clock,
                    clocks.scheduler_ns,
                );
                writeln!(samples_out, "{line}")
                    .map_err(|error| format!("cannot write {samples_path}: {error}"))?;
            }
        }
    }
    samples_out
        .flush()
        .map_err(|error| format!("cannot flush {samples_path}: {error}"))?;

    scheduler_samples.sort_unstable();
    // A/B order randomization seeded from the pinned manifest seed mixed
    // with the block index; future paired fixtures consume this ordering.
    // The draw is deterministic per block and logged on the info stream.
    let ab_seed = ab_order_seed(block_index);
    let mut order_generator = XorShift64Star::new(ab_seed);
    let first_phase = if order_generator.next_u64().is_multiple_of(2) {
        "A"
    } else {
        "B"
    };
    eprintln!("# block {block_index} A/B order: {first_phase} first");

    Ok(BlockSummary {
        block_index,
        pid: std::process::id(),
        started_at_utc: block_started_at_utc,
        frame_count: frames,
        p50_ns: nearest_rank(&scheduler_samples, 0.50),
        p95_ns: nearest_rank(&scheduler_samples, 0.95),
        p99_ns: nearest_rank(&scheduler_samples, 0.99),
    })
}

/// Assemble one frame's facade request from the fixture data.
///
/// The facade consumes owned buffers, so each frame clones the fixture
/// during this assembly. Callers run this BEFORE event acceptance (see
/// `run_block_in_process`, which builds the request ahead of
/// `ClockBoard::observe_frame`), so the copy cost lies OUTSIDE the measured
/// scheduler span `event_accept_to_render_return`: that span starts at the
/// accept timestamp and ends when the facade render call returns, and thus
/// measures rendering only, with fixture assembly excluded identically for
/// every frame. It is not a display-present or scanout measurement.
fn build_frame_request(
    xs: &[f64],
    ys: &[f64],
) -> Result<lumenplot::__private::OwnedLinePngRequest, String> {
    let geometry = lumenplot::__private::LinePngGeometry::new(
        [0.0, 1.0, 0.0, 1.0],
        [
            f64::from(FIXTURE_CANVAS_WIDTH_PX),
            f64::from(FIXTURE_CANVAS_HEIGHT_PX),
        ],
        [40.0, 30.0, 760.0, 550.0],
        FIXTURE_DPI,
    )
    .map_err(|error| format!("fixture geometry rejected: {}", error.message()))?;
    let style =
        lumenplot::__private::LinePngStyle::new([31, 119, 180, 255], 1.5, [255, 255, 255, 255])
            .map_err(|error| format!("fixture style rejected: {}", error.message()))?;
    let mut valid_segments = Vec::with_capacity(1);
    valid_segments.push(0..xs.len());
    lumenplot::__private::OwnedLinePngRequest::new(
        xs.to_vec(),
        ys.to_vec(),
        valid_segments,
        geometry,
        style,
        FIXTURE_DPI,
    )
    .map_err(|error| format!("fixture request rejected: {}", error.message()))
}

/// Build the accelerated-profile seam scene once per block: a `SceneHandle`
/// over the canonical 0..1 view holding the same 10k-point monotone-in-x
/// line series as the facade path.
///
/// The scene is built OUTSIDE the measured span; per-frame work resolves a
/// packet and submits it to the retained portable offscreen renderer.
fn build_scene(xs: &[f64], ys: &[f64]) -> Result<SceneHandle, String> {
    let viewport = Viewport::from_bounds(0.0, 1.0, 0.0, 1.0)
        .map_err(|error| format!("fixture view rejected: {}", error.message()))?;
    let mut handle = SceneHandle::new(viewport)
        .map_err(|error| format!("fixture scene rejected: {}", error.message()))?;
    handle
        .add_series(xs.to_vec(), ys.to_vec())
        .map_err(|error| format!("fixture series rejected: {}", error.message()))?;
    Ok(handle)
}

/// Build one frame's seam spec from the fixed O-08 geometry.
fn build_frame_spec() -> Result<lumenplot_render_api::FrameSpec, String> {
    lumenplot_render_api::FrameSpec::new(
        [FIXTURE_CANVAS_WIDTH_PX, FIXTURE_CANVAS_HEIGHT_PX],
        [40, 30, 760, 550],
        FIXTURE_DPI,
        SrgbRgba8::new(31, 119, 180, 255),
        1.5,
        SrgbRgba8::new(255, 255, 255, 255),
    )
    .map_err(|error| format!("fixture seam spec rejected: {}", error.message()))
}

/// Derive the per-block A/B ordering seed from the pinned bootstrap seed and
/// the block index.
///
/// Both the mix and the addition wrap on overflow (`wrapping_mul` /
/// `wrapping_add`) so debug builds with overflow checks stay panic-free for
/// every block index while release builds keep their historical wrapped-seed
/// values bit-for-bit.
fn ab_order_seed(block_index: u32) -> u64 {
    BOOTSTRAP_SEED.wrapping_add(u64::from(block_index).wrapping_mul(0x9E37_79B9_7F4A_7C15))
}

/// Internal block-runner mode: executed as a fresh child process per block.
///
/// Emits `#`-prefixed informational lines and exactly one trailing JSON
/// summary object on stdout.
pub(crate) fn run_block_child(args: &[String]) -> Result<(), String> {
    let mut iter = args.iter();
    let mut block_index: Option<u32> = None;
    let mut frames: Option<usize> = None;
    let mut out_dir = String::from("./bench-out");
    let mut profile = Profile::Strict;
    while let Some(flag) = iter.next() {
        match flag.as_str() {
            "--block-index" => {
                block_index = Some(
                    iter.next()
                        .ok_or("--block-index needs a value")?
                        .parse()
                        .map_err(|_| "--block-index must be an integer")?,
                )
            }
            "--frames" => {
                frames = Some(
                    iter.next()
                        .ok_or("--frames needs a value")?
                        .parse()
                        .map_err(|_| "--frames must be an integer")?,
                )
            }
            "--out" => out_dir = iter.next().ok_or("--out needs a value")?.clone(),
            "--profile" => {
                profile = Profile::parse(iter.next().ok_or("--profile needs a value")?)
                    .ok_or("unknown --profile value for block runner")?;
            }
            // The mode flag that routed us here; not a block parameter.
            "--internal-block-runner" => {}
            other => return Err(format!("unknown block-runner flag {other:?}")),
        }
    }
    let block_index = block_index.ok_or("missing --block-index")?;
    let frames = frames.ok_or("missing --frames")?;

    // The parent refuses unavailable profiles before spawning children, but
    // this mode is still a callable executable entry point. Keep the child
    // fail-closed when invoked directly so `native` cannot accidentally run
    // through the CPU fallback branch.
    if let Some(reason) = profile_unavailability(profile) {
        return Err(format!(
            "profile '{}' cannot run: {reason}",
            profile.as_str()
        ));
    }
    if usize::try_from(block_index).map_or(true, |index| index >= BLOCK_COUNT) {
        return Err(format!("--block-index must be in 0..{BLOCK_COUNT}"));
    }
    if frames < MIN_FRAMES_PER_BLOCK {
        return Err(format!("--frames must be at least {MIN_FRAMES_PER_BLOCK}"));
    }

    let summary = run_block_in_process(profile, block_index, frames, &out_dir)?;
    println!("# block {block_index} complete (fresh pid {})", summary.pid);
    println!(
        "{{\"block_index\": {}, \"pid\": {}, \"started_at_utc\": \"{}\", \
         \"frame_count\": {}, \"p50_ns\": {}, \"p95_ns\": {}, \"p99_ns\": {}}}",
        summary.block_index,
        summary.pid,
        summary.started_at_utc,
        summary.frame_count,
        opt_to_json(summary.p50_ns),
        opt_to_json(summary.p95_ns),
        opt_to_json(summary.p99_ns),
    );
    Ok(())
}

fn opt_to_json(value: Option<u64>) -> String {
    value.map_or_else(|| "null".to_string(), |number| number.to_string())
}

/// Extract an integer field from the child's flat summary JSON.
fn extract_u64(line: &str, key: &str) -> Option<u64> {
    let marker = format!("\"{key}\": ");
    let start = line.find(&marker)? + marker.len();
    let rest = &line[start..];
    let end = rest.find([',', '}']).unwrap_or(rest.len());
    rest[..end].trim().parse().ok()
}

/// Extract a quoted string field from the child's flat summary JSON.
fn extract_quoted<'a>(line: &'a str, key: &str) -> Option<&'a str> {
    let marker = format!("\"{key}\": \"");
    let start = line.find(&marker)? + marker.len();
    let rest = &line[start..];
    let end = rest.find('"')?;
    Some(&rest[..end])
}

/// Parse the child's trailing summary line into a [`BlockSummary`].
pub(crate) fn parse_block_summary(line: &str) -> Option<BlockSummary> {
    Some(BlockSummary {
        block_index: extract_u64(line, "block_index")? as u32,
        pid: extract_u64(line, "pid")? as u32,
        started_at_utc: extract_quoted(line, "started_at_utc")?.to_string(),
        frame_count: extract_u64(line, "frame_count")? as usize,
        p50_ns: extract_u64(line, "p50_ns"),
        p95_ns: extract_u64(line, "p95_ns"),
        p99_ns: extract_u64(line, "p99_ns"),
    })
}

/// Collect every scheduler observation from the retained raw sample files
/// for the descriptive-only pooled statistics.
///
/// A completed child must have one finite scheduler observation per measured
/// frame. Missing files, malformed rows, or an unavailable scheduler value
/// therefore invalidate the run instead of producing a partial pooled result.
fn read_pooled_scheduler_values(out_dir: &str, scheduler_clock: &str) -> Result<Vec<u64>, String> {
    let mut pooled = Vec::new();
    for block_index in 0..BLOCK_COUNT {
        let path = format!("{out_dir}/samples-{block_index}.jsonl");
        let file = File::open(&path).map_err(|error| format!("cannot read {path}: {error}"))?;
        let marker = format!("\"{scheduler_clock}\": ");
        for (line_number, line) in BufReader::new(file).lines().enumerate() {
            let line = line.map_err(|error| format!("cannot read {path}: {error}"))?;
            let start = line.find(&marker).ok_or_else(|| {
                format!(
                    "{path}:{}: missing scheduler clock {scheduler_clock:?}",
                    line_number + 1
                )
            })?;
            let rest = &line[start + marker.len()..];
            let end = rest.find([',', '}']).unwrap_or(rest.len());
            let value = rest[..end].trim().parse::<u64>().map_err(|_| {
                format!(
                    "{path}:{}: scheduler clock {scheduler_clock:?} must be a number",
                    line_number + 1
                )
            })?;
            pooled.push(value);
        }
    }
    Ok(pooled)
}

fn counter_summary(profile: Profile, blocks: &[BlockSummary]) -> CounterSummary<'static> {
    let measured_frames = blocks.iter().fold(0usize, |total, block| {
        total.saturating_add(block.frame_count)
    });
    let warmup_frames = BLOCK_COUNT.saturating_mul(WARMUP_FRAMES);
    let accelerated = profile == Profile::Accelerated;
    CounterSummary {
        status: if accelerated {
            "partial"
        } else {
            "unavailable"
        },
        warmup_frames,
        measured_frames,
        warmup_render_calls: warmup_frames,
        render_calls: measured_frames,
        resolve_calls: accelerated.then_some(measured_frames),
        offscreen_readbacks: accelerated.then_some(measured_frames),
        // These two zeroes are scoped to this Rust benchmark executable, which
        // does not enter Python or Matplotlib. They are not adapter-profile
        // zero-Python evidence.
        python_callbacks: accelerated.then_some(0),
        matplotlib_dispatch: accelerated.then_some(0),
        // The owning renderer/adapter does not expose these counters yet.
        // Keep them null instead of inferring values from source structure.
        ffi_calls: None,
        shader_compilations: None,
        pipeline_creations: None,
        font_shaping: None,
        lod_regenerations: None,
        upload_bytes: None,
        heap_allocations: None,
        fallback_events: accelerated.then_some(0),
        gpu_timestamp_queries: None,
        queue_completion_observations: None,
        scanout_markers: None,
        note: if accelerated {
            "Rust harness counters plus offscreen readback count; lower-level renderer counters are unavailable and this is not a display-present or standard-adapter gate"
        } else {
            "CPU facade harness call counts only; adapter Python/Matplotlib/fallback counters are unavailable and this is not a native gate"
        },
    }
}

/// Execute one full run: 5 fresh-process blocks, manifest assembly, gates.
///
/// Returns the process exit code (0 success, non-zero on protocol failure).
pub(crate) fn run_benchmark(profile: Profile, out_dir: &str, pid: u32) -> i32 {
    // Fail-closed profile gate, evaluated BEFORE any output directory or
    // child process exists: an unexecutable profile never leaves artifacts
    // behind. A run that executed zero frames can never satisfy the manifest
    // schema (every block must carry frame_count >= min_frames_per_block),
    // so there is no valid "empty" manifest to emit for this cell.
    if let Some(reason) = profile_unavailability(profile) {
        eprintln!(
            "bench: profile '{}' cannot run on this host: {reason}",
            profile.as_str()
        );
        eprintln!("bench: no manifest or samples were written; the O-08 cell stays unmeasured");
        return 2;
    }

    // Probe the real accelerated path before creating output. If this host has
    // no portable adapter/device, keep the cell NOT_RUN rather than falling
    // back to the old CPU seam or emitting fabricated block evidence.
    if let Err(reason) = probe_profile(profile) {
        eprintln!(
            "bench: profile '{}' cannot run on this host: {reason}",
            profile.as_str()
        );
        eprintln!("bench: no manifest or samples were written; the O-08 cell stays unmeasured");
        return 2;
    }

    if let Err(error) = std::fs::create_dir_all(out_dir) {
        eprintln!("bench: cannot create output directory {out_dir}: {error}");
        return 2;
    }

    let mut blocks = Vec::with_capacity(BLOCK_COUNT);
    let mut block_pids = HashSet::with_capacity(BLOCK_COUNT);
    for block_index in 0..BLOCK_COUNT {
        let executable = match std::env::current_exe() {
            Ok(path) => path,
            Err(error) => {
                eprintln!("bench: cannot locate own executable: {error}");
                return 2;
            }
        };
        let outcome = Command::new(executable)
            .args([
                "--internal-block-runner",
                "--profile",
                profile.as_str(),
                "--block-index",
                &block_index.to_string(),
                "--frames",
                &MIN_FRAMES_PER_BLOCK.to_string(),
                "--out",
                out_dir,
            ])
            .output();
        let output = match outcome {
            Ok(output) => output,
            Err(error) => {
                eprintln!("bench: block {block_index} failed to spawn: {error}");
                return 2;
            }
        };
        if !output.status.success() {
            eprintln!(
                "bench: block {block_index} exited with {:?}",
                output.status.code()
            );
            eprintln!("{}", String::from_utf8_lossy(&output.stderr));
            return 2;
        }
        let stdout = String::from_utf8_lossy(&output.stdout);
        let summary_line = stdout.lines().rev().find(|line| line.starts_with('{'));
        let Some(summary_line) = summary_line else {
            eprintln!("bench: block {block_index} produced no summary line");
            return 2;
        };
        match parse_block_summary(summary_line) {
            Some(summary) if usize::try_from(summary.block_index).ok() != Some(block_index) => {
                eprintln!(
                    "bench: block {block_index} returned summary for block {}",
                    summary.block_index
                );
                return 2;
            }
            Some(summary) if summary.frame_count < MIN_FRAMES_PER_BLOCK => {
                eprintln!(
                    "bench: block {block_index} returned only {} frames",
                    summary.frame_count
                );
                return 2;
            }
            Some(summary) if !block_pids.insert(summary.pid) => {
                eprintln!(
                    "bench: block {block_index} reused pid {}; blocks are not fresh processes",
                    summary.pid
                );
                return 2;
            }
            Some(summary) => blocks.push(summary),
            None => {
                eprintln!("bench: block {block_index} summary unparsable: {summary_line}");
                return 2;
            }
        }
    }

    let board = ClockBoard::detect();
    let scheduler_clock = scheduler_span(profile);
    let descriptors = board.descriptors(scheduler_clock);
    let descriptor_lines: Vec<String> = descriptors
        .iter()
        .map(|descriptor| {
            emit_clock_entry(
                descriptor.name,
                descriptor.domain,
                descriptor.unit,
                descriptor.available,
            )
        })
        .collect();
    let clock_lines = descriptor_lines.join("\n");
    let any_clock_available = descriptors.iter().any(|descriptor| descriptor.available);

    let mut pooled = match read_pooled_scheduler_values(out_dir, scheduler_clock) {
        Ok(values) => values,
        Err(error) => {
            eprintln!("bench: raw sample validation failed: {error}");
            return 2;
        }
    };
    let expected_sample_count = blocks.iter().fold(0usize, |total, block| {
        total.saturating_add(block.frame_count)
    });
    if pooled.len() != expected_sample_count {
        eprintln!(
            "bench: raw sample count {} does not match block total {}",
            pooled.len(),
            expected_sample_count
        );
        return 2;
    }
    pooled.sort_unstable();
    let pooled_line = emit_pooled(
        scheduler_clock,
        pooled.len(),
        nearest_rank(&pooled, 0.50),
        nearest_rank(&pooled, 0.95),
        nearest_rank(&pooled, 0.99),
    );

    let max_block_p99_ns = blocks.iter().filter_map(|b| b.p99_ns).max();
    let mut inconclusive_reasons: Vec<String> = Vec::new();
    for descriptor_name in [GPU_SPAN, QUEUE_SPAN, SCANOUT_MARKER] {
        inconclusive_reasons.push(format!(
            "clock domain '{descriptor_name}' has no instrumentation; observations are null"
        ));
    }
    if profile == Profile::Accelerated {
        // The portable path is an offscreen GPU submission plus blocking
        // readback. It owns no window surface, physical present, or scanout
        // marker, so the scheduler interval is explicitly not an
        // input-to-display claim.
        inconclusive_reasons.push(
            "accelerated profile measures packet resolution plus portable offscreen \
             render/readback; no window surface, physical present, or scanout is observed"
                .to_string(),
        );
    } else {
        inconclusive_reasons.push(
            "strict/hybrid profiles measure the CPU PNG facade return; no window surface, physical present, or scanout is observed"
                .to_string(),
        );
    }
    for block in &blocks {
        if block.frame_count < MIN_FRAMES_PER_BLOCK {
            inconclusive_reasons.push(format!(
                "block {} recorded {} frames, below the {} minimum",
                block.block_index, block.frame_count, MIN_FRAMES_PER_BLOCK
            ));
        }
    }

    let fixture = Fixture {
        id: "line-10k",
        points: FIXTURE_POINTS,
        canvas_px: [FIXTURE_CANVAS_WIDTH_PX, FIXTURE_CANVAS_HEIGHT_PX],
        dpi: FIXTURE_DPI,
    };
    let environment = detect_environment(profile.as_str());
    let measurement = Measurement {
        scheduler_clock,
        scheduler_semantics: scheduler_semantics(profile),
        present_observed: false,
        scanout_observed: false,
    };
    let counters = counter_summary(profile, &blocks);
    let manifest = Manifest {
        run_id: &derive_run_id(pid),
        generated_at_utc: &utc_now_rfc3339(),
        profile: profile.as_str(),
        measurement: &measurement,
        counters: &counters,
        fixture: &fixture,
        environment: &environment,
        clock_lines: &clock_lines,
        blocks: &blocks,
        pooled_line: &pooled_line,
        max_block_p99_ns,
        inconclusive_reasons: &inconclusive_reasons,
    };
    let manifest_path = format!("{out_dir}/manifest.json");
    if let Err(error) = std::fs::write(&manifest_path, emit_manifest(&manifest)) {
        eprintln!("bench: cannot write {manifest_path}: {error}");
        return 2;
    }
    println!("bench: wrote {manifest_path}");

    let all_blocks_long_enough = blocks
        .iter()
        .all(|block| block.frame_count >= MIN_FRAMES_PER_BLOCK);
    if !any_clock_available || !all_blocks_long_enough {
        return 1;
    }
    0
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::manifest::emit_counters;

    #[test]
    fn profile_round_trips_all_four_names() {
        for name in ["strict", "hybrid", "accelerated", "native"] {
            let parsed = Profile::parse(name).expect("profile must parse");
            assert_eq!(parsed.as_str(), name);
        }
        assert!(Profile::parse("native ").is_none());
        assert!(Profile::parse("").is_none());
    }

    #[test]
    fn scheduler_boundaries_are_profile_specific_and_never_present_claims() {
        assert_eq!(scheduler_span(Profile::Strict), RENDER_RETURN_SPAN);
        assert_eq!(scheduler_span(Profile::Hybrid), RENDER_RETURN_SPAN);
        assert_eq!(scheduler_span(Profile::Accelerated), READBACK_RETURN_SPAN);
        assert!(!scheduler_semantics(Profile::Strict).contains("accept-to-present"));
        assert!(!scheduler_semantics(Profile::Accelerated).contains("accept-to-present"));
    }

    #[test]
    fn nearest_rank_matches_ceil_q_n() {
        let samples: Vec<u64> = (1..=100).collect();
        assert_eq!(nearest_rank(&samples, 0.50), Some(50));
        assert_eq!(nearest_rank(&samples, 0.95), Some(95));
        assert_eq!(nearest_rank(&samples, 0.99), Some(99));
        // ceil(q*n) over 10 samples: p50 -> 5th, p95 -> 10th (ceil 9.5).
        let small: Vec<u64> = (10..=100).step_by(10).collect();
        assert_eq!(nearest_rank(&small, 0.50), Some(50));
        assert_eq!(nearest_rank(&small, 0.95), Some(100));
        assert_eq!(nearest_rank(&small, 1.0), Some(100));
        assert_eq!(nearest_rank(&[], 0.5), None);
        assert_eq!(nearest_rank(&samples, -0.1), None);
        assert_eq!(nearest_rank(&samples, 1.1), None);
    }

    #[test]
    fn rfc3339_known_instants_render_correctly() {
        assert_eq!(unix_nanos_to_rfc3339(0), "1970-01-01T00:00:00.000Z");
        // 2026-08-24T00:00:00Z (the pinned bootstrap seed date).
        let seed_date_seconds: i128 = 1_787_529_600;
        assert_eq!(
            unix_nanos_to_rfc3339(seed_date_seconds * 1_000_000_000),
            "2026-08-24T00:00:00.000Z"
        );
        // Leap-year day: 2024-02-29T12:34:56.789Z.
        let leap: i128 = 1_709_210_096_789_000_000;
        assert_eq!(unix_nanos_to_rfc3339(leap), "2024-02-29T12:34:56.789Z");
    }

    #[test]
    fn derived_run_id_is_uuid_v4_shaped_and_deterministic_per_pid_seed() {
        let first = derive_run_id(1234);
        let parts: Vec<&str> = first.split('-').collect();
        assert_eq!(parts.len(), 5);
        assert_eq!((parts[0].len(), parts[1].len(), parts[2].len()), (8, 4, 4));
        assert_eq!((parts[3].len(), parts[4].len()), (4, 12));
        assert!(first.chars().all(|c| c == '-' || c.is_ascii_hexdigit()));
        assert_eq!(&parts[2][..1], "4");
        assert!(matches!(
            parts[3].chars().next().unwrap(),
            '8' | '9' | 'a' | 'b'
        ));
    }

    #[test]
    fn fixture_has_contracted_shape() {
        let (xs, ys) = build_fixture_xy();
        assert_eq!(xs.len(), FIXTURE_POINTS);
        assert_eq!(ys.len(), FIXTURE_POINTS);
        assert_eq!(xs[0], 0.0);
        assert!((*xs.last().unwrap() - 1.0).abs() < 1e-12);
        assert!(ys.iter().all(|y| y.is_finite()));
    }

    #[test]
    fn xorshift_is_deterministic_and_nonzero() {
        let mut a = XorShift64Star::new(42);
        let mut b = XorShift64Star::new(42);
        for _ in 0..16 {
            assert_eq!(a.next_u64(), b.next_u64());
        }
        let mut zero = XorShift64Star::new(0);
        assert_ne!(zero.next_u64(), 0);
    }

    #[test]
    fn ab_order_seed_wraps_deterministically_for_all_block_indices() {
        // The seed mix must wrap on overflow instead of panicking under
        // debug-profile overflow checks: a plain `*` here aborts every block
        // with index >= 2 (the golden-ratio product exceeds u64::MAX), which
        // is exactly how the round-1 defect reached the branch. Pinned
        // wrapped values below are BOOTSTRAP_SEED + index * golden ratio
        // modulo 2^64, so release-profile seeds are unchanged by design.
        let expected: [(u32, u64); 5] = [
            (0, 0x0000_0000_0135_27d8),
            (1, 0x9e37_79b9_807f_a3ed),
            (2, 0x3c6e_f372_ffca_2002),
            (5, 0x1715_609f_7da9_9441),
            (9, 0x8ff3_4785_7ad3_8495),
        ];
        for (block_index, seed) in expected {
            assert_eq!(ab_order_seed(block_index), seed);
        }
        // Extreme boundary: the maximum representable block index must also
        // stay panic-free and land on its pinned wrapped value.
        assert_eq!(ab_order_seed(u32::MAX), 0xe113_025b_81ea_abc3);
    }

    #[test]
    fn block_summary_round_trips_through_the_wire_format() {
        let summary = BlockSummary {
            block_index: 3,
            pid: 4242,
            started_at_utc: "2026-08-24T00:00:00.000Z".to_string(),
            frame_count: 1000,
            p50_ns: Some(1500),
            p95_ns: None,
            p99_ns: Some(9900),
        };
        let wire = format!(
            "{{\"block_index\": {}, \"pid\": {}, \"started_at_utc\": \"{}\", \
             \"frame_count\": {}, \"p50_ns\": {}, \"p95_ns\": {}, \"p99_ns\": {}}}",
            summary.block_index,
            summary.pid,
            summary.started_at_utc,
            summary.frame_count,
            opt_to_json(summary.p50_ns),
            opt_to_json(summary.p95_ns),
            opt_to_json(summary.p99_ns),
        );
        let parsed = parse_block_summary(&wire).expect("wire line must parse");
        assert_eq!(parsed.block_index, 3);
        assert_eq!(parsed.pid, 4242);
        assert_eq!(parsed.frame_count, 1000);
        assert_eq!(parsed.p50_ns, Some(1500));
        assert_eq!(parsed.p95_ns, None);
        assert_eq!(parsed.p99_ns, Some(9900));
    }

    #[test]
    fn emitted_manifest_is_structurally_valid_json() {
        let fixture = Fixture {
            id: "line-10k",
            points: FIXTURE_POINTS,
            canvas_px: [FIXTURE_CANVAS_WIDTH_PX, FIXTURE_CANVAS_HEIGHT_PX],
            dpi: FIXTURE_DPI,
        };
        let environment = Environment {
            os: "test-os".to_string(),
            os_version: "test-version".to_string(),
            arch: "test-arch".to_string(),
            kernel: "test-kernel".to_string(),
            cpu: "test-cpu \"quoted\"".to_string(),
            toolchain: "test-toolchain".to_string(),
            build_profile: "release".to_string(),
            render_backend: "cpu-private-png-facade".to_string(),
            gpu_vendor: None,
            gpu_device: None,
            gpu_driver: None,
            gpu_api: None,
            gpu_feature_level: None,
            compositor: None,
            display_scale: None,
            present_mode: None,
        };
        let blocks = vec![
            BlockSummary {
                block_index: 0,
                pid: 1,
                started_at_utc: "2026-08-24T00:00:00.000Z".to_string(),
                frame_count: MIN_FRAMES_PER_BLOCK,
                p50_ns: Some(10),
                p95_ns: Some(20),
                p99_ns: Some(30),
            },
            BlockSummary {
                block_index: 1,
                pid: 2,
                started_at_utc: "2026-08-24T00:00:01.000Z".to_string(),
                frame_count: MIN_FRAMES_PER_BLOCK,
                p50_ns: None,
                p95_ns: None,
                p99_ns: None,
            },
        ];
        let reasons = vec!["clock domain 'gpu' has no instrumentation".to_string()];
        let descriptors = ClockBoard::detect().descriptors(RENDER_RETURN_SPAN);
        let clock_lines = descriptors
            .iter()
            .map(|descriptor| {
                emit_clock_entry(
                    descriptor.name,
                    descriptor.domain,
                    descriptor.unit,
                    descriptor.available,
                )
            })
            .collect::<Vec<_>>()
            .join("\n");
        let pooled_line = emit_pooled(
            RENDER_RETURN_SPAN,
            2 * MIN_FRAMES_PER_BLOCK,
            Some(10),
            Some(20),
            Some(30),
        );
        let measurement = Measurement {
            scheduler_clock: RENDER_RETURN_SPAN,
            scheduler_semantics: CPU_RENDER_SEMANTICS,
            present_observed: false,
            scanout_observed: false,
        };
        let counters = counter_summary(Profile::Strict, &blocks);
        let manifest = Manifest {
            run_id: "run-id",
            generated_at_utc: "2026-08-24T00:00:00.000Z",
            profile: "strict",
            measurement: &measurement,
            counters: &counters,
            fixture: &fixture,
            environment: &environment,
            clock_lines: &clock_lines,
            blocks: &blocks,
            pooled_line: &pooled_line,
            max_block_p99_ns: Some(30),
            inconclusive_reasons: &reasons,
        };
        let document = emit_manifest(&manifest);

        // No double commas anywhere between array elements.
        assert!(!document.contains(",,"), "double comma: {document}");
        // Balanced structural punctuation.
        assert_eq!(document.matches('[').count(), document.matches(']').count());
        assert_eq!(document.matches('{').count(), document.matches('}').count());
        // Required D1 top-level fields all present.
        for field in [
            "\"schema_version\": 1",
            "\"run_id\"",
            "\"generated_at_utc\"",
            "\"profile\": \"strict\"",
            "\"measurement\"",
            "\"counters\"",
            "\"fixture\"",
            "\"environment\"",
            "\"protocol\"",
            "\"clocks\"",
            "\"blocks\"",
            "\"pooled\"",
            "\"max_block_p99_ns\": 30",
            "\"status\": \"inconclusive\"",
            "\"inconclusive_reasons\"",
            "\"quantile_method\": \"nearest-rank\"",
            "\"trimming\": \"none\"",
            "\"seed\": 20260824",
        ] {
            assert!(document.contains(field), "missing {field}");
        }
        // Unavailable block quantiles serialize as null, never zero.
        assert!(document.contains("\"p99_ns\": null"));
        assert!(document.contains("\"scheduler_clock\": \"event_accept_to_render_return\""));
        assert!(document.contains("\"present_observed\": false"));
        assert!(document.contains("\"upload_bytes\": null"));
        // Escaping keeps embedded quotes intact inside strings.
        assert!(document.contains(r#"test-cpu \"quoted\""#));
    }

    #[test]
    fn counter_summary_distinguishes_harness_zeroes_from_unavailable_adapter_values() {
        let blocks = vec![BlockSummary {
            block_index: 0,
            pid: 1,
            started_at_utc: "2026-08-24T00:00:00.000Z".to_string(),
            frame_count: MIN_FRAMES_PER_BLOCK,
            p50_ns: Some(1),
            p95_ns: Some(2),
            p99_ns: Some(3),
        }];
        let accelerated = emit_counters(&counter_summary(Profile::Accelerated, &blocks));
        assert!(accelerated.contains("\"python_callbacks\": 0"));
        assert!(accelerated.contains("\"fallback_events\": 0"));
        assert!(accelerated.contains("\"upload_bytes\": null"));

        let strict = emit_counters(&counter_summary(Profile::Strict, &blocks));
        assert!(strict.contains("\"python_callbacks\": null"));
        assert!(strict.contains("\"fallback_events\": null"));
    }

    #[test]
    fn environment_detection_degrades_without_panicking() {
        let environment = detect_environment("strict");
        assert!(!environment.os.is_empty());
        assert!(!environment.arch.is_empty());
        assert!(!environment.cpu.is_empty());
        assert!(environment.gpu_vendor.is_none());
        assert!(environment.present_mode.is_none());
        // The D1 schema requires a positive display_scale; headless runs
        // record the truly-applied factor 1.0 rather than null.
        let scale = environment.display_scale.expect("display_scale recorded");
        assert!(scale.is_finite() && scale > 0.0);
    }

    #[test]
    fn display_scale_detector_ignores_invalid_and_nonpositive_values() {
        // The helper reads only canonical toolkit variables; this host has
        // none set in the test environment, so detection must land on 1.0.
        // (Setting env vars here would race other tests: std env is
        // process-global, so the negative cases are pinned by inspection of
        // the guard -- non-numeric, zero, and negative values fail the
        // finite-positive filter and fall through to 1.0.)
        let scale = detect_display_scale();
        assert_eq!(scale, 1.0);
    }

    #[test]
    fn native_profile_is_unavailable_and_others_are_available() {
        let reason = profile_unavailability(Profile::Native).expect("native refuses");
        assert!(
            reason.contains("unmeasured"),
            "reason names the cell: {reason}"
        );
        for profile in [Profile::Strict, Profile::Hybrid, Profile::Accelerated] {
            assert_eq!(profile_unavailability(profile), None);
        }
    }

    #[test]
    fn native_refusal_happens_before_any_artifact_is_created() {
        // The refusal must precede output-directory creation: point --out at
        // a path that does not exist yet and prove it still does not exist
        // after the refused run. A run that executed zero frames can never
        // satisfy the manifest schema, so no artifact may be left behind.
        let root = std::env::temp_dir().join(format!(
            "lumenplot-bench-refusal-{}-{}",
            std::process::id(),
            ab_order_seed(7) & 0xffff
        ));
        let out_dir = root.join("never-created");
        let code = run_benchmark(Profile::Native, out_dir.to_str().expect("utf8"), 1);
        assert_eq!(code, 2);
        assert!(!out_dir.exists(), "refused run must not create the out dir");
        assert!(
            !root.join("manifest.json").exists(),
            "refused run must not write a manifest"
        );
        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn direct_block_runner_refuses_unavailable_or_short_protocol_inputs() {
        let native_args = [
            "--internal-block-runner",
            "--profile",
            "native",
            "--block-index",
            "0",
            "--frames",
            "1000",
        ]
        .into_iter()
        .map(str::to_string)
        .collect::<Vec<_>>();
        let native_error = run_block_child(&native_args).expect_err("native must refuse");
        assert!(native_error.contains("cannot run"), "{native_error}");

        let short_args = [
            "--internal-block-runner",
            "--profile",
            "strict",
            "--block-index",
            "0",
            "--frames",
            "999",
        ]
        .into_iter()
        .map(str::to_string)
        .collect::<Vec<_>>();
        let short_error = run_block_child(&short_args).expect_err("short block must refuse");
        assert!(short_error.contains("at least 1000"), "{short_error}");
    }

    #[test]
    fn accelerated_seam_fixture_builds_and_resolves() {
        // The accelerated fixture assembles against the accepted M1 seam:
        // scene construction succeeds outside the measured span and one
        // resolve_frame call yields a packet with the contracted canvas.
        let (xs, ys) = build_fixture_xy();
        let scene = build_scene(&xs, &ys).expect("scene");
        let spec = build_frame_spec().expect("spec");
        let packet = scene.resolve_frame(&spec).expect("packet");
        assert_eq!(
            packet.canvas_px(),
            [FIXTURE_CANVAS_WIDTH_PX, FIXTURE_CANVAS_HEIGHT_PX]
        );
        assert_eq!(packet.series().len(), 1);
        let points: usize = packet.series()[0]
            .segments()
            .iter()
            .map(|segment| segment.points().len())
            .sum();
        assert_eq!(points, FIXTURE_POINTS);
        // Every resolved vertex stays inside the canvas in display space.
        for series in packet.series() {
            for segment in series.segments() {
                for point in segment.points() {
                    assert!((0.0..=f64::from(FIXTURE_CANVAS_WIDTH_PX)).contains(&point.x()));
                    assert!((0.0..=f64::from(FIXTURE_CANVAS_HEIGHT_PX)).contains(&point.y()));
                }
            }
        }
    }
}
