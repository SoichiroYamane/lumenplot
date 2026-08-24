//! Hand-written JSON manifest emission for the O-08 protocol (decision D1).
//!
//! External dependencies (including `serde`) are forbidden on this edge by
//! the accepted contract, so every JSON document is emitted with a small
//! string writer. The manifest shape follows D1 field-for-field; the
//! authority over field names is the workstream decision D1, mirrored by
//! R2's `scripts/bench_analysis.py --validate`.
//!
//! Unavailable observations are emitted as JSON `null` and drive the
//! `status: "inconclusive"` mapping; substituting zeros is forbidden.
//! `pooled` statistics are descriptive-only — gate values come from
//! `max_block_p99_ns`.

use std::fmt::Write as _;

pub(crate) const SCHEMA_VERSION: u64 = 1;
/// Paired-bootstrap resamples pinned by the O-08 protocol.
pub(crate) const BOOTSTRAP_RESAMPLES: u32 = 10_000;
/// Bootstrap confidence level pinned by the O-08 protocol.
pub(crate) const BOOTSTRAP_CI: f64 = 0.95;
/// Bootstrap seed pinned by the O-08 protocol (2026-08-24).
pub(crate) const BOOTSTRAP_SEED: u64 = 20_260_824;

/// Fixture identity emitted into the manifest.
pub(crate) struct Fixture {
    pub(crate) id: &'static str,
    pub(crate) points: usize,
    pub(crate) canvas_px: [u32; 2],
    pub(crate) dpi: f64,
}

/// Environment description emitted into the manifest.
pub(crate) struct Environment {
    pub(crate) os: String,
    pub(crate) os_version: String,
    pub(crate) arch: String,
    pub(crate) kernel: String,
    pub(crate) cpu: String,
    pub(crate) gpu_vendor: Option<String>,
    pub(crate) gpu_device: Option<String>,
    pub(crate) gpu_driver: Option<String>,
    pub(crate) gpu_api: Option<String>,
    pub(crate) gpu_feature_level: Option<String>,
    pub(crate) compositor: Option<String>,
    pub(crate) display_scale: Option<f64>,
    pub(crate) present_mode: Option<String>,
}

/// One completed fresh-process block summary.
pub(crate) struct BlockSummary {
    pub(crate) block_index: u32,
    pub(crate) pid: u32,
    pub(crate) started_at_utc: String,
    pub(crate) frame_count: usize,
    pub(crate) p50_ns: Option<u64>,
    pub(crate) p95_ns: Option<u64>,
    pub(crate) p99_ns: Option<u64>,
}

/// Everything needed to render the final manifest document.
pub(crate) struct Manifest<'a> {
    pub(crate) run_id: &'a str,
    pub(crate) generated_at_utc: &'a str,
    pub(crate) profile: &'a str,
    pub(crate) fixture: &'a Fixture,
    pub(crate) environment: &'a Environment,
    pub(crate) clock_lines: &'a str,
    pub(crate) blocks: &'a [BlockSummary],
    pub(crate) pooled_line: &'a str,
    pub(crate) max_block_p99_ns: Option<u64>,
    pub(crate) inconclusive_reasons: &'a [String],
}

fn write_json_string(out: &mut String, value: &str) {
    out.push('"');
    for character in value.chars() {
        match character {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            control if (control as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", control as u32);
            }
            other => out.push(other),
        }
    }
    out.push('"');
}

fn write_optional_number(out: &mut String, value: Option<u64>) {
    match value {
        Some(number) => {
            let _ = write!(out, "{number}");
        }
        None => out.push_str("null"),
    }
}

/// Emit one `clocks[]` entry as an indented JSON object line fragment.
///
/// Returns the serialized entry without surrounding commas; the caller owns
/// array punctuation.
pub(crate) fn emit_clock_entry(name: &str, domain: &str, unit: &str, available: bool) -> String {
    let mut entry = String::new();
    entry.push_str("{\"name\": ");
    write_json_string(&mut entry, name);
    entry.push_str(", \"domain\": ");
    write_json_string(&mut entry, domain);
    entry.push_str(", \"unit\": ");
    write_json_string(&mut entry, unit);
    entry.push_str(", \"available\": ");
    entry.push_str(if available { "true" } else { "false" });
    entry.push('}');
    entry
}

/// Emit the descriptive-only pooled block for the manifest.
pub(crate) fn emit_pooled(
    frame_count: usize,
    p50_ns: Option<u64>,
    p95_ns: Option<u64>,
    p99_ns: Option<u64>,
) -> String {
    let mut pooled = String::new();
    pooled
        .push_str("{\"note\": \"descriptive only; gate uses max_block_p99_ns\", \"frame_count\": ");
    let _ = write!(pooled, "{frame_count}");
    pooled.push_str(", \"p50_ns\": ");
    write_optional_number(&mut pooled, p50_ns);
    pooled.push_str(", \"p95_ns\": ");
    write_optional_number(&mut pooled, p95_ns);
    pooled.push_str(", \"p99_ns\": ");
    write_optional_number(&mut pooled, p99_ns);
    pooled.push('}');
    pooled
}

/// Render the complete manifest document (pretty-printed, trailing newline).
pub(crate) fn emit_manifest(manifest: &Manifest<'_>) -> String {
    let mut out = String::with_capacity(4096);
    out.push_str("{\n");
    let _ = writeln!(out, "  \"schema_version\": {SCHEMA_VERSION},");
    out.push_str("  \"run_id\": ");
    write_json_string(&mut out, manifest.run_id);
    out.push_str(",\n  \"generated_at_utc\": ");
    write_json_string(&mut out, manifest.generated_at_utc);
    out.push_str(",\n  \"profile\": ");
    write_json_string(&mut out, manifest.profile);

    out.push_str(",\n  \"fixture\": {\n    \"id\": ");
    write_json_string(&mut out, manifest.fixture.id);
    let _ = writeln!(
        out,
        ",\n    \"points\": {},\n    \"canvas_px\": [{}, {}],\n    \"dpi\": {}",
        manifest.fixture.points,
        manifest.fixture.canvas_px[0],
        manifest.fixture.canvas_px[1],
        manifest.fixture.dpi
    );
    out.push_str("  }");

    let environment = manifest.environment;
    out.push_str(",\n  \"environment\": {\n    \"os\": ");
    write_json_string(&mut out, &environment.os);
    out.push_str(",\n    \"os_version\": ");
    write_json_string(&mut out, &environment.os_version);
    out.push_str(",\n    \"arch\": ");
    write_json_string(&mut out, &environment.arch);
    out.push_str(",\n    \"kernel\": ");
    write_json_string(&mut out, &environment.kernel);
    out.push_str(",\n    \"cpu\": ");
    write_json_string(&mut out, &environment.cpu);
    out.push_str(",\n    \"gpu\": ");
    match (
        &environment.gpu_vendor,
        &environment.gpu_device,
        &environment.gpu_driver,
        &environment.gpu_api,
        &environment.gpu_feature_level,
    ) {
        (Some(vendor), Some(device), Some(driver), Some(api), Some(level)) => {
            out.push_str("{\n      \"vendor\": ");
            write_json_string(&mut out, vendor);
            out.push_str(",\n      \"device\": ");
            write_json_string(&mut out, device);
            out.push_str(",\n      \"driver\": ");
            write_json_string(&mut out, driver);
            out.push_str(",\n      \"api\": ");
            write_json_string(&mut out, api);
            out.push_str(",\n      \"feature_level\": ");
            write_json_string(&mut out, level);
            out.push_str("\n    }");
        }
        _ => out.push_str("null"),
    }
    out.push_str(",\n    \"compositor\": ");
    match &environment.compositor {
        Some(value) => write_json_string(&mut out, value),
        None => out.push_str("null"),
    }
    out.push_str(",\n    \"display_scale\": ");
    match environment.display_scale {
        Some(scale) => {
            let _ = write!(out, "{scale}");
        }
        None => out.push_str("null"),
    }
    out.push_str(",\n    \"present_mode\": ");
    match &environment.present_mode {
        Some(value) => write_json_string(&mut out, value),
        None => out.push_str("null"),
    }
    out.push_str("\n  }");

    out.push_str(
        ",\n  \"protocol\": {\n    \"blocks\": 5,\n    \"min_frames_per_block\": 1000,\
         \n    \"quantile_method\": \"nearest-rank\",\n    \"bootstrap\": {\n      \
         \"resamples\": ",
    );
    let _ = write!(out, "{BOOTSTRAP_RESAMPLES}");
    out.push_str(",\n      \"ci\": ");
    let _ = write!(out, "{BOOTSTRAP_CI}");
    out.push_str(",\n      \"seed\": ");
    let _ = write!(out, "{BOOTSTRAP_SEED}");
    out.push_str(",\n      \"method\": \"percentile\"\n    },\n    \"trimming\": \"none\"\n  }");

    out.push_str(",\n  \"clocks\": [");
    if !manifest.clock_lines.is_empty() {
        for line in manifest.clock_lines.lines() {
            out.push_str("\n    ");
            out.push_str(line);
            out.push(',');
        }
        out.pop();
    }
    out.push_str("\n  ]");

    out.push_str(",\n  \"blocks\": [\n");
    for (position, block) in manifest.blocks.iter().enumerate() {
        out.push_str("    {\n      \"block_index\": ");
        let _ = write!(out, "{}", block.block_index);
        out.push_str(",\n      \"pid\": ");
        let _ = write!(out, "{}", block.pid);
        out.push_str(",\n      \"started_at_utc\": ");
        write_json_string(&mut out, &block.started_at_utc);
        out.push_str(",\n      \"frame_count\": ");
        let _ = write!(out, "{}", block.frame_count);
        out.push_str(",\n      \"p50_ns\": ");
        write_optional_number(&mut out, block.p50_ns);
        out.push_str(",\n      \"p95_ns\": ");
        write_optional_number(&mut out, block.p95_ns);
        out.push_str(",\n      \"p99_ns\": ");
        write_optional_number(&mut out, block.p99_ns);
        out.push_str(",\n      \"raw_samples_path\": ");
        write_json_string(&mut out, &format!("samples-{}.jsonl", block.block_index));
        if position + 1 == manifest.blocks.len() {
            out.push_str("\n    }\n");
        } else {
            out.push_str("\n    },\n");
        }
    }
    out.push_str("  ]");

    out.push_str(",\n  \"pooled\": ");
    out.push_str(manifest.pooled_line);

    out.push_str(",\n  \"max_block_p99_ns\": ");
    write_optional_number(&mut out, manifest.max_block_p99_ns);

    let status = if manifest.inconclusive_reasons.is_empty() {
        "complete"
    } else {
        "inconclusive"
    };
    out.push_str(",\n  \"status\": ");
    write_json_string(&mut out, status);
    out.push_str(",\n  \"inconclusive_reasons\": [");
    for (position, reason) in manifest.inconclusive_reasons.iter().enumerate() {
        if position > 0 {
            out.push(',');
        }
        write_json_string(&mut out, reason);
    }
    out.push_str("]\n}\n");
    out
}
