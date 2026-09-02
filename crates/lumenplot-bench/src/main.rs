//! O-08 benchmark binary: CLI surface for the fresh-process block runner.
//!
//! Usage:
//!
//! ```text
//! lumenplot-bench --profile <strict|hybrid|accelerated|native> [--out <dir>]
//! ```
//!
//! Exactly one profile must be selected; profiles are never mixed. The
//! parent process re-executes itself once per block with the internal
//! `--internal-block-runner` mode flag (see `runner`), so a full run spawns
//! 5 fresh child processes, one per block. Output defaults to `./bench-out/`
//! and receives `manifest.json` plus `samples-<block>.jsonl` raw files. The
//! accelerated profile uses the portable offscreen renderer and records an
//! offscreen readback boundary; it never labels that CPU interval as
//! display-present latency.

#![forbid(unsafe_code)]

#[path = "clocks.rs"]
mod clocks;
#[path = "manifest.rs"]
mod manifest;
#[path = "runner.rs"]
mod runner;

use runner::Profile;

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match run(args) {
        Ok(code) => std::process::exit(code),
        Err(message) => {
            eprintln!("bench: {message}");
            print_usage();
            std::process::exit(2);
        }
    }
}

fn print_usage() {
    eprintln!("usage: lumenplot-bench --profile <strict|hybrid|accelerated|native> [--out <dir>]");
}

/// Parse arguments and dispatch to the run or block-runner mode.
///
/// Returns the process exit code instead of exiting directly so tests can
/// drive it without spawning processes.
fn run(args: Vec<String>) -> Result<i32, String> {
    // Child mode is detected before the run-mode parser so the block
    // runner owns its whole flag subset.
    if args.iter().any(|flag| flag == "--internal-block-runner") {
        return runner::run_block_child(&args).map(|()| 0);
    }

    let mut iter = args.iter();
    let mut profile: Option<Profile> = None;
    let mut out_dir: Option<String> = None;

    while let Some(flag) = iter.next() {
        match flag.as_str() {
            "--profile" => {
                if profile.is_some() {
                    return Err("--profile given more than once".to_string());
                }
                let value = iter.next().ok_or("--profile needs a value")?;
                profile = Some(
                    Profile::parse(value).ok_or_else(|| format!("unknown profile {value:?}"))?,
                );
            }
            "--out" => {
                if out_dir.is_some() {
                    return Err("--out given more than once".to_string());
                }
                out_dir = Some(iter.next().ok_or("--out needs a value")?.clone());
            }
            other => return Err(format!("unknown argument {other:?}")),
        }
    }

    let profile = profile
        .ok_or("missing required --profile (exactly one of strict|hybrid|accelerated|native)")?;
    let out_dir = out_dir.as_deref().unwrap_or("./bench-out");
    Ok(runner::run_benchmark(profile, out_dir, std::process::id()))
}
