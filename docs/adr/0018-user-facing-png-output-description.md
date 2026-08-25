# ADR 0018: User-facing PNG-output description

- Status: Accepted
- Date: 2026-08-25
- Decision owner: architecture-authority
- Recorded by: implementation-worker
- Scope: public README documentation of the Phase-2B/3B PNG output; no code change
- Amends: none (documentation only)
- Governing architecture: [ADR 0012 — private line frame and deterministic PNG contract](0012-private-line-frame-and-png-contract.md), [ADR 0015 — Phase-3B public Matplotlib adapter contract](0015-phase3b-public-matplotlib-adapter-contract.md)

## Context

The root README's "Getting started" section documents a working first-render
path (`pip install .`, strict-mode backend, `savefig("quickstart.png")`), but
the "Current implementation status" section still described an earlier
snapshot: a nine-package workspace with "no Python package, first-class
Matplotlib adapter, GPU renderer, separate raster package, examples, or
release packaging". The repository now ships the `lumenplot-mpl` distribution
with `python/lumenplot_mpl`, the Phase-2B export sink, the hidden Phase-3A
facade and helper, pinned Phase-3A2 wheel evidence, and the first Phase-3B
strict/hybrid backend slices, so the two sections contradicted each other.
Nothing in the README described the produced PNG stream itself (chunk set,
color type, determinism scope, absence of density metadata), leaving users to
discover from ADR 0012 that `IDAT` payloads are stored uncompressed.

During the same pass, enabling DEFLATE compression for the export sink was
evaluated and rejected at this layer. [ADR 0012 §5](0012-private-line-frame-and-png-contract.md)
is an accepted record that normatively pins `NoCompression` and `NoFilter`
for the deterministic sink; both encoders (`crates/lumenplot-export/src/png.rs`,
`crates/lumenplot-python/src/frame.rs`) match it exactly. Changing encoder
settings is an architecture amendment owned by the architecture-authority,
not a documentation task, and no size, performance, or correctness defect was
demonstrated by this slice.

## Decision

1. The README's implementation-status prose is corrected to describe the
   current snapshot honestly: ten-crate workspace plus the
   `python/lumenplot_mpl` package, phase-by-phase implemented slices, and the
   GPU render lanes explicitly named as documentation-only stubs.
2. The README gains a "PNG output" subsection describing what successful
   native renders produce: 8-bit RGBA non-interlaced stream with an sRGB
   Perceptual chunk, signature/`IHDR`/`sRGB`/contiguous `IDAT`/`IEND` chunks
   only, no `pHYs`/`gAMA`/`cHRM`/`iCCP`/text/time/palette/animation
   metadata, no dots-per-inch metadata, same-host byte determinism, no Agg
   byte identity, standard-decoder readability, and larger-than-Agg files
   because `IDAT` payloads are stored uncompressed by contract.
3. The encoder configuration is unchanged. Any future compression change
   requires an architecture-amendment record that updates ADR 0012 §5, the
   chunk-level structural tests in `crates/lumenplot-export/src/png.rs`, and
   the stdlib decoder assumptions in `tests/python/test_phase3b_backend.py`.

## Alternatives and rationale

- **Enable DEFLATE compression now** was rejected: it would amend an accepted
  ADR without its owner's decision, break the documented byte-determinism
  surface for marginal gain, and exceed this slice's documentation scope.
- **Leave the README stale until packaged runtime evidence lands** was
  rejected: the contradiction misleads every new reader today, and describing
  shipped behavior does not claim unearned support, platform, or release
  evidence.
- **Describe PNG internals only in ADR 0012** was rejected: the README is the
  entry point users actually read; a short factual subsection with a link to
  the authoritative record serves them without duplicating normative text.

## Consequences

Positive consequences:

- New users get an accurate picture of what exists, including what remains a
  stub, before forming expectations about v1.
- The PNG file characteristics — including intentionally uncompressed `IDAT`
  data and missing DPI metadata — are discoverable from the README instead of
  surprising users comparing output sizes with Agg.
- Future compression work has a recorded starting point and an explicit list
  of the records and tests it must update together.

Costs and constraints:

- The README makes additional factual claims that must be kept in sync with
  future phases (crate count, stub list, chunk set).
- Uncompressed `IDAT` payloads remain a visible cost until an accepted
  amendment changes ADR 0012 §5.

## Affected interfaces and required verification

No Rust, Python, packaging, or dependency surface changes. Verification is
repository-gate only: `cargo fmt --all -- --check`,
`cargo test --locked --workspace --all-features`,
`cargo clippy --locked --workspace --all-targets --all-features -- -D warnings`,
`cargo metadata --locked --no-deps --format-version 1`, and
`git diff --check`. Documentation claims were cross-checked against
`pyproject.toml`, `Cargo.toml`/`Cargo.lock`, crate sources, and the existing
chunk-level tests rather than newly asserted.

## Residual risks and follow-up decisions

- Packaged public-backend runtime evidence remains pending, as recorded in
  ADR 0014/ADR 0015/API 0005; this record adds none.
- If compression, DPI metadata (`pHYs`), or additional chunks are ever wanted,
  the follow-up is an ADR-0012 amendment owned by the architecture-authority,
  with the structural tests listed above updated in the same change.
