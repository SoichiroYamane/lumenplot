# ADR 0018: User-facing PNG-output description

- Status: Accepted — amended in place on 2026-08-25: IDAT DEFLATE compression enabled, superseding the `NoCompression` clause of [ADR 0012](0012-private-line-frame-and-png-contract.md) §5 on this single point
- Date: 2026-08-25
- Decision owner: architecture-authority
- Recorded by: implementation-worker
- Scope: public README documentation accuracy for shipped phases, the user-facing PNG-output description, and the IDAT compression setting of the private Phase-2B/Phase-3 PNG sinks
- Amends: [ADR 0012 — private line frame and deterministic PNG contract](0012-private-line-frame-and-png-contract.md) (§5 stream definition, compression clause only)
- Related: [API-0005 — Phase-3B public Matplotlib backend surface](../architecture/api-0005-phase3b-public-matplotlib-backend-surface.md)

## Requirement references

Serves `LP-SEC-008` (keep public documentation free of private task/session
identifiers, local paths, host details, credentials, and raw internal artifact
paths) and supports the transparency intent of `LP-MPL-008` (silent omission
and unreported best-effort degradation are not allowed).
It changes no requirement row, closes no gate, and adds no dependency.

## Context

The repository README still described a nine-package workspace with no Python
package, adapter, examples, or release packaging, while the same README's
Getting-started section documented installing `lumenplot-mpl`, selecting the
public backend, and running `examples/quickstart.py`. The user-facing PNG
output was undocumented outside ADR prose. Separately, the sink encoded every
`IDAT` payload as stored (uncompressed) DEFLATE blocks: the quickstart
fixture produced a 995,916-byte PNG where Matplotlib's Agg backend produces
4,367 bytes for the identical figure — a ~228x size penalty paid by every
user for a property only determinism audits benefit from.

## Decision

### 1. Documentation pass

The README states current implementation status accurately (ten-crate
workspace plus the `python/lumenplot_mpl` package shipped by the
`lumenplot-mpl` distribution; strict-mode public backend with opt-in hybrid
fallback; GPU lanes as named stub crates) and gains a user-facing "PNG
output" subsection describing the actual stream: 8-bit RGBA non-interlaced
pixels, sRGB Perceptual intent, exact chunk set (`IHDR`, `sRGB`, contiguous
`IDAT`, `IEND`; no `pHYs`/`gAMA`/`cHRM`/`iCCP`/text/time/palette/APNG),
no DPI metadata chunk, row filters disabled, same-host byte determinism, and
no byte-identity claim against Agg. This pass is documentation-only.

### 2. Amendment: IDAT DEFLATE compression enabled

The private sinks set `Compression::Balanced` instead of
`Compression::NoCompression`. Everything else in the ADR 0012 §5 stream
contract is unchanged and remains binding: exact chunk set, sRGB Perceptual
intent 0, `Filter::NoFilter`, RGBA/Eight/non-interlaced, ceiling checks,
error taxonomy, and the narrow same-host determinism claim (which has always
been conditioned on exact locked versions/toolchain/host, so a compression
setting change does not weaken it).

Measured evidence (quickstart fixture, 576x432, this host, locked png 0.18.1):

| Configuration | Output size |
| --- | ---: |
| `NoCompression` (before) | 995,916 bytes |
| `Compression::Fast` | 11,460 bytes |
| `Compression::Balanced` (selected) | 2,445 bytes |
| Agg reference, same figure | 4,367 bytes |

`Fast` leaves fdeflate's streaming shortcut on the table for this data shape
(11,460 bytes); `Balanced` yields a file ~407x smaller than stored blocks and
smaller than the Agg reference for the same figure. Encoding cost remains
sub-millisecond at this fixture size in both profiles. The selected level is
a fixed implementation constant of the private sink, not a public option.

## Alternatives considered

- Keeping `NoCompression` and documenting the size cost was rejected: the
  cost (~228x on the reference fixture) is paid by every downstream consumer
  while the audit benefit is served equally well by any fixed, pinned level.
- `Compression::Fast` was rejected on measurement: it underperforms here
  because fdeflate's fast path does not compress this pixel layout well.
- `High` was rejected: marginal size gain over `Balanced` does not justify
  the extra encode time for interactive savefig paths.
- Public compression options were rejected: they would expand the public
  surface and break the fixed-bytes property across option values.

## Consequences

- Users get reasonably sized PNGs (2,445 vs 995,916 bytes on the fixture)
  with zero behavioral change beyond byte values inside `IDAT`.
- Determinism scope is unchanged: same host/toolchain/lockfile still yields
  identical bytes; cross-host byte identity remains explicitly unclaimed.
- ADR 0012 §5's "NoCompression" word is superseded by this record; all other
  clauses stand. Reviewers of ADR 0012 should read §5 subject to this
  amendment.
- No manifest, lockfile, feature, or public-API change.

## Verification

Existing gates cover the amendment without new tests by design: the export
suite asserts the exact chunk set, decoder roundtrip, and repeated-encode
byte equality; the Phase-3B suite decodes `IDAT` with zlib and asserts pixel
oracles. Re-run after the change: `cargo fmt --all -- --check`,
`cargo test --locked --workspace --all-features`, `cargo clippy --locked
--workspace --all-targets --all-features -- -D warnings`, plus an end-to-end
render of `examples/quickstart.py` verifying chunk order, BTYPE=2 DEFLATE
payloads, filter bytes all zero, and two-process SHA-256 equality. Measured
sizes above are recorded from those runs.

## References

- [ADR 0012 — private line frame and deterministic PNG contract](0012-private-line-frame-and-png-contract.md)
- [ADR 0015 — Phase-3B public Matplotlib adapter contract](0015-phase3b-public-matplotlib-adapter-contract.md)
- [API-0005 — Phase-3B public Matplotlib backend surface](../architecture/api-0005-phase3b-public-matplotlib-backend-surface.md)
