# Dependency policy contract

The repository license decision and dependency licenses are separate controls:

- Project/package licensing is `MIT OR Apache-2.0`, with standard license texts
  and Cargo SPDX metadata still required by the publication task.
- Dependency licenses are checked by `deny.toml`; only the explicitly listed
  permissive expressions are accepted. An allowed dependency license does not
  grant permission to omit project license files.
- Unknown registries and Git sources are denied. A future non-crates.io source
  requires an explicit review and a deliberate policy change.
- Yanked releases, unlicensed/copy-left dependencies, and wildcard dependency
  declarations are not silently accepted.
- The current `Cargo.lock` (v4) records 327 packages: 316 are third-party
  entries sourced entirely from
  `registry+https://github.com/rust-lang/crates.io-index`, each with a
  checksum and none from a Git or unknown source; the remaining 11 are local
  workspace members with no external source. Dependency licenses stay gated
  by `deny.toml`, and this inventory is not evidence that any future
  renderer/window/shader/text/native dependency is approved.

Dependabot creates monthly grouped pull requests only. It does not auto-merge;
changes involving wgpu, winit, shaders, text/layout engines, native bindings,
GPU drivers, or other performance-sensitive code require manual review and a
separate benchmark/compatibility decision.
