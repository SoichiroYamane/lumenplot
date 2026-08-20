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
- The current lockfile has no third-party Cargo dependencies, so this check is
  a forward-looking guard rather than evidence that future renderer/window/
  shader/text/native dependencies are approved.

Dependabot creates monthly grouped pull requests only. It does not auto-merge;
changes involving wgpu, winit, shaders, text/layout engines, native bindings,
GPU drivers, or other performance-sensitive code require manual review and a
separate benchmark/compatibility decision.
