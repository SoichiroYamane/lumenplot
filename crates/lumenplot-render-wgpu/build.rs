use std::fs;
use std::path::Path;

use naga::front::wgsl;
use naga::valid::{Capabilities, ValidationFlags, Validator};
use sha2::{Digest, Sha256};

// The manifest is the authoritative provenance record for the static WGSL
// artifact (Phase-B line-only slice). Every field below is pinned: any
// hash or metadata mutation fails the build instead of flowing silently
// into the renderer. The runtime linkage lives in `src/shader.rs`, which
// consumes the emitted `LUMENPLOT_LINE_SHADER_*` values and refuses to
// verify when its compiled provenance drifts from this manifest.
const EXPECTED_SCHEMA: &str = "1";
const EXPECTED_ARTIFACT: &str = "line.wgsl";
const EXPECTED_SOURCE_REVISION: &str = "lumenplot-line-wgsl-v1";
const EXPECTED_VALIDATOR: &str = "naga 29.0.4";
const EXPECTED_VALIDATION: &str =
    "naga WGSL parser plus wgpu 29.0.4 checked shader at renderer initialization";
const EXPECTED_RESOURCE_LAYOUT: &str =
    "group0/binding0 uniform(viewport_px, half_width_px, color_linear)";
const EXPECTED_COORDINATE_SPACE: &str = "DisplayLogical top-left";

fn main() {
    println!("cargo:rerun-if-changed=shaders/line.wgsl");
    println!("cargo:rerun-if-changed=shaders/manifest.toml");

    let shader_path = Path::new("shaders/line.wgsl");
    let manifest_path = Path::new("shaders/manifest.toml");
    let source = fs::read(shader_path).unwrap_or_else(|error| {
        panic!("failed to read static WGSL artifact: {error}");
    });
    let manifest = fs::read_to_string(manifest_path).unwrap_or_else(|error| {
        panic!("failed to read static WGSL manifest: {error}");
    });

    let schema = manifest_field(&manifest, "schema");
    if schema != EXPECTED_SCHEMA {
        panic!("WGSL manifest schema is not the pinned Phase-B value");
    }
    let artifact = manifest_field(&manifest, "artifact");
    if artifact != EXPECTED_ARTIFACT {
        panic!("WGSL manifest artifact is not the pinned Phase-B value");
    }
    let source_revision = manifest_field(&manifest, "source_revision");
    if source_revision != EXPECTED_SOURCE_REVISION {
        panic!("WGSL manifest source revision is not the pinned Phase-B value");
    }
    let expected = manifest_field(&manifest, "sha256");
    if expected.len() != 64 || !expected.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        panic!("WGSL manifest has no valid SHA-256 entry");
    }
    let validator = manifest_field(&manifest, "validator");
    if validator != EXPECTED_VALIDATOR {
        panic!("WGSL manifest validator is not the pinned Phase-B value");
    }
    let validation = manifest_field(&manifest, "validation");
    if validation != EXPECTED_VALIDATION {
        panic!("WGSL manifest validation mode is not the pinned Phase-B value");
    }
    let resource_layout = manifest_field(&manifest, "resource_layout");
    if resource_layout != EXPECTED_RESOURCE_LAYOUT {
        panic!("WGSL manifest resource layout is not the pinned Phase-B value");
    }
    let coordinate_space = manifest_field(&manifest, "coordinate_space");
    if coordinate_space != EXPECTED_COORDINATE_SPACE {
        panic!("WGSL manifest coordinate space is not the pinned Phase-B value");
    }

    let actual = format!("{:x}", Sha256::digest(&source));
    if actual != expected {
        panic!("static WGSL artifact hash does not match its manifest");
    }

    let source = std::str::from_utf8(&source).unwrap_or_else(|error| {
        panic!("static WGSL artifact is not UTF-8: {error}");
    });
    let module = wgsl::parse_str(source).unwrap_or_else(|error| {
        panic!("static WGSL artifact failed to parse: {error}");
    });
    Validator::new(ValidationFlags::all(), Capabilities::all())
        .validate(&module)
        .unwrap_or_else(|error| panic!("static WGSL artifact failed validation: {error}"));

    // Provenance linkage consumed at runtime by `src/shader.rs`: the manifest
    // stays authoritative because any mutation above fails the build before
    // these values can drift into the compiled renderer.
    println!("cargo:rustc-env=LUMENPLOT_LINE_SHADER_SHA256={actual}");
    println!("cargo:rustc-env=LUMENPLOT_LINE_SHADER_SOURCE_REVISION={source_revision}");
    println!("cargo:rustc-env=LUMENPLOT_LINE_SHADER_RESOURCE_LAYOUT={resource_layout}");
    println!("cargo:rustc-env=LUMENPLOT_LINE_SHADER_VALIDATION={validation}");
}

/// Extracts one `key = value` entry from the pinned manifest shape.
///
/// String values arrive quoted (`key = \"value\"`) and `schema` arrives as a
/// bare integer. A missing or malformed entry fails the build; the manifest
/// is never trusted partially.
fn manifest_field(manifest: &str, key: &str) -> String {
    let prefix = format!("{key} = ");
    let line = manifest.lines().find_map(|line| {
        let trimmed = line.trim();
        trimmed.strip_prefix(prefix.as_str())
    });
    let Some(raw) = line else {
        panic!("WGSL manifest is missing its {key} entry");
    };
    let raw = raw.trim();
    if let Some(quoted) = raw
        .strip_prefix('"')
        .and_then(|value| value.strip_suffix('"'))
    {
        quoted.to_string()
    } else if raw.bytes().all(|byte| byte.is_ascii_digit()) && !raw.is_empty() {
        raw.to_string()
    } else {
        panic!("WGSL manifest {key} entry is not a pinned string or integer");
    }
}
