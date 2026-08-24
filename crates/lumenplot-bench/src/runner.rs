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
//! Profiles select the execution policy recorded in the manifest. The
//! currently accepted public surface is the private PNG facade, so all four
//! profile names drive that single implemented path today; the selected
//! name is recorded verbatim rather than silently relabeled.
//!
//! A/B order randomization: each child shuffles its two labeled sub-phase
//! orderings with a generator seeded from the pinned manifest seed
//! (`BOOTSTRAP_SEED`) mixed with the block index, exercising the ordering
//! machinery future paired fixtures rely on. The chosen order is logged on
//! the child's info stream.

use std::fs::File;
use std::io::{BufRead, BufReader, Write};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

use crate::clocks::{ClockBoard, GPU_SPAN, QUEUE_SPAN, SCANOUT_MARKER, SCHEDULER_SPAN};
use crate::manifest::{
    BOOTSTRAP_SEED, BlockSummary, Environment, Fixture, Manifest, emit_clock_entry, emit_manifest,
    emit_pooled,
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

/// Detect the run environment; unknown descriptors degrade to "unknown"/null
/// (they are provenance metadata, not gate observations, so they do not flip
/// the run status on their own).
pub(crate) fn detect_environment() -> Environment {
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
        gpu_vendor: None,
        gpu_device: None,
        gpu_driver: None,
        gpu_api: None,
        gpu_feature_level: None,
        compositor: None,
        display_scale: None,
        present_mode: None,
    }
}

/// Serialize one samples line: `{block, frame, clocks:{...nulls}}`.
fn samples_line(block_index: u32, frame_index: usize, scheduler_ns: Option<u64>) -> String {
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
    clock_field(&mut line, SCHEDULER_SPAN, scheduler_ns, true);
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
    block_index: u32,
    frames: usize,
    out_dir: &str,
) -> Result<BlockSummary, String> {
    let (xs, ys) = build_fixture_xy();
    let board = ClockBoard::detect();

    let samples_path = format!("{out_dir}/samples-{block_index}.jsonl");
    let mut samples_out = File::create(&samples_path)
        .map_err(|error| format!("cannot create {samples_path}: {error}"))?;

    // Warm-up: exercise the full path without recording anything so block
    // statistics describe steady state rather than startup.
    for _ in 0..WARMUP_FRAMES {
        let request = build_frame_request(&xs, &ys)?;
        let _pixels = lumenplot::__private::render_line_png(request);
    }

    let mut scheduler_samples: Vec<u64> = Vec::with_capacity(frames);
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
        let line = samples_line(block_index, frame_index, clocks.scheduler_ns);
        writeln!(samples_out, "{line}")
            .map_err(|error| format!("cannot write {samples_path}: {error}"))?;
    }
    samples_out
        .flush()
        .map_err(|error| format!("cannot flush {samples_path}: {error}"))?;

    scheduler_samples.sort_unstable();
    // A/B order randomization seeded from the pinned manifest seed mixed
    // with the block index; future paired fixtures consume this ordering.
    // The draw is deterministic per block and logged on the info stream.
    let ab_seed = BOOTSTRAP_SEED.wrapping_add(u64::from(block_index) * 0x9E37_79B9_7F4A_7C15);
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
        started_at_utc: utc_now_rfc3339(),
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
/// scheduler span `event_accept_to_present_return`: that span starts at the
/// accept timestamp and ends when the facade render call returns, and thus
/// measures rendering only, with fixture assembly excluded identically for
/// every frame.
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

/// Internal block-runner mode: executed as a fresh child process per block.
///
/// Emits `#`-prefixed informational lines and exactly one trailing JSON
/// summary object on stdout.
pub(crate) fn run_block_child(args: &[String]) -> Result<(), String> {
    let mut iter = args.iter();
    let mut block_index: Option<u32> = None;
    let mut frames: Option<usize> = None;
    let mut out_dir = String::from("./bench-out");
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
            // The mode flag that routed us here; not a block parameter.
            "--internal-block-runner" => {}
            other => return Err(format!("unknown block-runner flag {other:?}")),
        }
    }
    let block_index = block_index.ok_or("missing --block-index")?;
    let frames = frames.ok_or("missing --frames")?;

    let summary = run_block_in_process(block_index, frames, &out_dir)?;
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
fn read_pooled_scheduler_values(out_dir: &str) -> Vec<u64> {
    let mut pooled = Vec::new();
    for block_index in 0..BLOCK_COUNT {
        let path = format!("{out_dir}/samples-{block_index}.jsonl");
        let Ok(file) = File::open(&path) else {
            continue;
        };
        let marker = format!("\"{SCHEDULER_SPAN}\": ");
        for line in BufReader::new(file).lines().map_while(Result::ok) {
            if let Some(start) = line.find(&marker) {
                let rest = &line[start + marker.len()..];
                let end = rest.find([',', '}']).unwrap_or(rest.len());
                if let Ok(value) = rest[..end].trim().parse::<u64>() {
                    pooled.push(value);
                }
            }
        }
    }
    pooled
}

/// Execute one full run: 5 fresh-process blocks, manifest assembly, gates.
///
/// Returns the process exit code (0 success, non-zero on protocol failure).
pub(crate) fn run_benchmark(profile: Profile, out_dir: &str, pid: u32) -> i32 {
    if let Err(error) = std::fs::create_dir_all(out_dir) {
        eprintln!("bench: cannot create output directory {out_dir}: {error}");
        return 2;
    }

    let mut blocks = Vec::with_capacity(BLOCK_COUNT);
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
            Some(summary) => blocks.push(summary),
            None => {
                eprintln!("bench: block {block_index} summary unparsable: {summary_line}");
                return 2;
            }
        }
    }

    let board = ClockBoard::detect();
    let descriptors = board.descriptors();
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

    let mut pooled = read_pooled_scheduler_values(out_dir);
    pooled.sort_unstable();
    let pooled_line = emit_pooled(
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
    let environment = detect_environment();
    let manifest = Manifest {
        run_id: &derive_run_id(pid),
        generated_at_utc: &utc_now_rfc3339(),
        profile: profile.as_str(),
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
        let descriptors = ClockBoard::detect().descriptors();
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
        let pooled_line = emit_pooled(2 * MIN_FRAMES_PER_BLOCK, Some(10), Some(20), Some(30));
        let manifest = Manifest {
            run_id: "run-id",
            generated_at_utc: "2026-08-24T00:00:00.000Z",
            profile: "strict",
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
        // Escaping keeps embedded quotes intact inside strings.
        assert!(document.contains(r#"test-cpu \"quoted\""#));
    }

    #[test]
    fn environment_detection_degrades_without_panicking() {
        let environment = detect_environment();
        assert!(!environment.os.is_empty());
        assert!(!environment.arch.is_empty());
        assert!(!environment.cpu.is_empty());
        assert!(environment.gpu_vendor.is_none());
        assert!(environment.present_mode.is_none());
    }
}
