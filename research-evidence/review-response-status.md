# Phase-3A2 review-response status — HEAD 8ac3892 (branch wt/t_14894021)

Scope: response to review comments 226, 228, and 230 on task t_a8b289f7,
covering `crates/lumenplot-python/src/lib.rs`, the Phase-3A2 wheel workflow,
`scripts/phase3a2-sbom.py`, `scripts/phase3a2-manifest.py`, and helper tests.
This file records what is fixed, what remains open, and the probe evidence
gathered on 2026-08-22. Docker, cargo-deny, actionlint, and yamllint are
unavailable in this environment; no hosted-wheel claim is made here.

## Fixed

### 1. Malformed NumPy byte spans are rejected before dereference
(C226-1 / C228-1 / C230-1)

The bridge reads exactly `length * itemsize` bytes from the array data
pointer. `ensure_dense_1d()` now requires a C-contiguous one-dimensional view
whose element stride equals itemsize for length > 1, with checked span
arithmetic, before any `as_array()` call.

Probe results against the rebuilt extension (`target/release/lib_native.so`
copied into `/tmp/lumenplot_phase3a2_probe`, Python 3.14 + NumPy 2.5.1):

| case | before | after |
| --- | --- | --- |
| `as_strided(base(1 elem), shape=(2,), strides=(1e9,))` | exit -11 SIGSEGV | `LumenPlotError(invalid-input)`, exit 1 |
| `as_strided(base, shape=(2,), strides=(8,))` logical 16B over 8B base | rendered OOB | rejected (stride==itemsize but non-contiguous logical span) — see note |
| `np.arange(8)[::2]`, `[::-2]`, `broadcast_to((4,))` | rendered via logical order | `LumenPlotError(invalid-input)` |
| zero-length unaligned `frombuffer(offset=1,count=0)` | PanicException "pointer must be aligned" | accepted harmlessly: 0 elements, dense check passes, no traversal |

Note: the `(2,) strides=(8,)` case over a single-element base is caught by
NumPy's own contiguity computation combined with the stride equality check;
the far-stride variant is caught by stride != itemsize; both return sanitized
errors instead of crashing. A len-1 far-stride view reads only element 0,
which lies inside the base allocation, so it is safe to accept.

Regression fixture added:
`tests/python/test_phase3a2_helper.py::test_non_dense_views_are_rejected_with_explicit_diagnostic`.

Committed as 8ac3892 "fix: reject non-dense numpy views before byte-span reads".

### 2. Manifest generator emits only observed values (C226-3b subset)
Commit a417461: wheel checks verified directly (ZIP testzip, single
METADATA/WHEEL/native .so inventory, Version/Tag extraction, per-entry RECORD
hash+size verification with the RECORD self-entry exemption); SBOM components
validated for name/version/purl coherence and hex hashes before use.

## Verified still open (blocking)

Probes were executed against HEAD a417461/8ac3892 sources this session:

1. **SBOM pipeline cannot pass at all** (worse than reported): with
   `cargo metadata --locked --format-version 1` from this lockfile, **0 of 40
   registry packages carry a `checksum` field**, so commit a417461's
   fail-closed `phase3a2-sbom.py` exits at the first registry crate
   ("adler2"). Cargo.lock holds all 40 checksums; the generator must source
   them from there (join by package id), not from metadata.
   Probe: `python3 scripts/phase3a2-sbom.py --metadata <locked-metadata.json>`
   → "cargo metadata has no checksum for registry package adler2".

2. **RECORD omission/duplicate acceptance persists**: synthesizing a wheel
   that drops one member together with its RECORD row still exits 0;
   duplicating a non-native ZIP member (`py.typed`) still exits 0. Duplicate
   `.so` names are only rejected incidentally via the native-name count.
   Probes: `/tmp/probe-wheel-omit1.whl` EXIT 0; `/tmp/probe-wheel-dup2.whl`
   EXIT 0 (dup of `_native.abi3.so` is caught, EXIT 1).

3. **ELF/RPATH gate is print-only**: the readelf pipeline prints RPATH/RUNPATH
   but only `libpython|libcuda` can fail the step; RUNPATH-only output never
   fails. `elf_rpath: true` in the manifest is unconditional.

4. **Builder tool inventory unprovisioned/unasserted**: container still relies
   on absent in-image rustup toolchain for `RUSTUP_TOOLCHAIN=1.89.0`;
   auditwheel/abi3audit/cargo-deny versions are claimed (6.8.0 / 0.0.26 /
   pinned policy tool) without in-container assertion; manylinux image ships
   auditwheel 6.7.0 vs the claimed 6.8.0.

5. **cargo deny invocation invalid for cargo-deny 0.20.x**
   (`check --all-features` → usage error), and deny.toml's allowlist lacks
   `Apache-2.0 WITH LLVM-exception` (target-lexicon) and `Unicode-3.0`
   (unicode-ident), both present in this locked graph — confirmed by scanning
   license expressions of all 49 packages.

6. **noexec /tmp hosts executable build artifacts**: cargo target dir,
   build-site, and venvs remain under `--tmpfs /tmp:rw,noexec,nosuid,nodev`.

7. **Version duplication** (P2): `pyproject.toml` static version and
   `phase3a2-sbom.py` root component version literal remain; wheel-vs-Cargo
   equality is asserted at runtime, PEP-517 dynamic derivation not implemented.

## Verification performed at 8ac3892

- `cargo fmt --all -- --check`: PASS
- `cargo check --locked --workspace --all-targets --all-features`: PASS
- `cargo test --locked --workspace --all-features`: PASS (18 suites, 0 failed)
- `cargo clippy --locked --workspace --all-targets --all-features -- -D warnings`: PASS
- static architecture checker (`python3 scripts/check_workspace_architecture.py`):
  PASS ("workspace architecture: OK", "phase3a2 static contract: OK")
- `python3 -m unittest scripts.test_check_workspace_architecture`: 162 tests OK
- helper tests against rebuilt extension: 7/7 OK
  (incl. new non-dense-view rejection fixture)
- malformed-span probes: table above
- `nix flake check --all-systems --no-build --no-update-lock-file`: all checks passed
- `git diff --check`: clean

Not runnable here: Docker same-wheel four-cell evidence, cargo deny,
actionlint/yamllint. The container workflow must be re-run end-to-end after
the open items above are resolved before any Phase-3A2 evidence claim.
