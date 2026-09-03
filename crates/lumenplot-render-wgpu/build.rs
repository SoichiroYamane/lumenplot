use std::fs;
use std::path::Path;

use naga::front::wgsl;
use naga::valid::{Capabilities, ValidationFlags, Validator};
use sha2::{Digest, Sha256};

const EXPECTED_MANIFEST_KEY: &str = "sha256 = \"";

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
    let expected = manifest
        .lines()
        .find_map(|line| line.trim().strip_prefix(EXPECTED_MANIFEST_KEY))
        .and_then(|value| value.strip_suffix('"'))
        .filter(|value| value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit()))
        .unwrap_or_else(|| panic!("WGSL manifest has no valid SHA-256 entry"));
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

    println!("cargo:rustc-env=LUMENPLOT_LINE_SHADER_SHA256={actual}");
}
