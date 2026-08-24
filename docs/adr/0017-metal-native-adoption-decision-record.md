# ADR 0017: Metal native adoption decision record (O-16 gate disposition)

- Status: **Proposal — decision record draft for the architecture-authority; nothing here is Go, and no support, dependency, or implementation claim is made**
- Date: 2026-08-25
- Decision owner: architecture-authority
- Recorded by: engineering-worker
- Scope: the O-16 native-backend adoption/retirement gate applied to the Phase-4 Metal prototype candidate (`LP-PLAT-003`), using the first real O-08 measurement bundle as its evidence input; it decides **nothing** by itself
- Governing architecture: [ADR 0002 — GPU-native engine and first-class Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md)
- Protocol and gate record: [ADR 0006 — support cells, benchmark protocol, and native gates](0006-support-benchmark-native-gates.md) (§O-08 protocol, §O-16 adoption gate)
- Boundary records: [ADR 0003 — facade and crate dependency graph](0003-facade-and-crate-dag.md), [ADR 0004 — RenderPacket resource lifecycle](0004-renderpacket-resource-lifecycle.md), [ADR 0005 — runtime, viewer, and host loop](0005-runtime-viewer-host-loop.md), [ADR 0008 — portable GPU runtime and shader artifacts](0008-portable-gpu-and-shaders.md)
- Seam predecessor: [ADR 0012 — private line frame and deterministic PNG contract](0012-private-line-frame-and-png-contract.md); the minimal synchronous frame seam this lane consumes is specified in [the post-v1 Metal fast-path design notes](../research/post-v1-metal-fastpath-design-notes.md)
- Evidence inputs: the first executed O-08 five-block A/B bundle (strict / hybrid / accelerated profiles measured on a non-declared host, native cell refused pre-run), stored by the measurement lane as [`artifacts/EVIDENCE.md`](../../artifacts/EVIDENCE.md) (per-profile manifests, raw JSONL samples, paired same-profile report, native refusal transcript, pooled statistics) and [`artifacts/coverage-matrix.md`](../../artifacts/coverage-matrix.md) (gate-input coverage matrix); every measured number in this record cites one of these two paths

This record is a **disposition of the O-16 gate against currently existing
evidence**, written so the architecture-authority can act on it without
re-deriving the numbers. Its single conclusion is negative and expected:
**the gate is No-Go today, by design.** Every quantitative gate input is
either unmeasured or unmeasurable until a native cell runs on declared
hardware. Nothing in this record authorizes a dependency, a crate, a code
path, `Backend::Auto` behavior change, or any support claim. Where this
record says "measured", the number is a pooled descriptive statistic from an
inconclusive-labelled run on a host outside every declared cell; where it
says "environment required", no substitute number exists anywhere in this
repository.

## Requirement references

This record is the "Phase 4 decision record" target of:

- `LP-PLAT-003` (`MUST`, Phase 4, evidence `AT-BENCH-NATIVE-AB`): adopt a
  Metal fast path only when prototype measurements and profiling show a
  meaningful benefit over the selected portable path.
- `LP-REL-007` (`PHASE`): Phase 4 covers conditional Metal prototypes and
  their measured comparison with the portable path.

It applies verbatim, without reinterpreting, the thresholds fixed by
[ADR 0006 §O-16](0006-support-benchmark-native-gates.md#o-16-native-adoption-gate)
and [O-16](../architecture/open-decisions.md#o-16-native-backend-adoption-and-retirement-gates),
and the measurement protocol fixed by
[ADR 0006 §O-08](0006-support-benchmark-native-gates.md#o-08-timing-and-clock-boundaries).
It also exercises the comparison dimensions of `LP-PLAT-011` (frame time,
CPU overhead, present latency, memory, feature availability) to the extent
the current harness instruments them, and respects `LP-PLAT-006`
(`Backend::Auto` = capability probing + static override, never a startup
microbenchmark), `LP-PLAT-007` (never retained solely because it is newer),
and `LP-PLAT-012` (MAY retain only the portable path).

## Context

The post-v1 exploration track needs a measured answer on whether an
Apple-Metal fast path is worth pursuing for interactive use. The accepted
canon already fixes how that answer must be produced: O-07 declares the
target cells, O-08 fixes the five-fresh-block protocol and statistics, and
O-16 fixes the Go/No-Go/retire thresholds. What did not exist yet was any
executed O-08 bundle to evaluate the gate against. This record evaluates the
gate against the first such bundle, produced on a Linux host with no GPU and
no compositor instrumentation: three executable profiles measured for real
(strict, hybrid, accelerated), each five fresh-process blocks of 1000
accepted frames over raw JSONL capture
([`artifacts/EVIDENCE.md`](../../artifacts/EVIDENCE.md)), plus a native cell
that refuses pre-run because no native render path exists in this workspace.

Prototype-lane legality provenance: a minimal synchronous frame seam and a
quarantined `lumenplot-render-metal` crate behind a default-off feature flag
exist solely as isolated measurement vehicles, authorized for this campaign
by explicit architecture-commander instruction. The underlying legality
question — whether a non-shipping Metal crate may exist behind such a gate
during measurement — was left undecided at authorization time and remains
[open question 1 of the post-v1 Metal fast-path design notes](../research/post-v1-metal-fastpath-design-notes.md#7-open-questions-reserved-for-the-architecture-authority);
the authorization is therefore recorded here as provenance only. It is not a
Go decision, adds no dependency to any accepted v1 crate, creates no
`Backend::Auto` participation, and grants no shipping surface.

## Gate evaluation

The O-16 preamble precondition — no implementation fan-out before the
portable baseline and the O-07/O-08 evidence pass — is not yet engaged by any
adoption claim, because no implementation fan-out has occurred. For the
record: the portable strict/hybrid half of the baseline was measured for
real, but on an undeclared Linux host, and the macOS/Metal declared cell is
environment required (native cell refused pre-run, exit code 2, zero
artifacts — see [`artifacts/EVIDENCE.md`](../../artifacts/EVIDENCE.md) and
[`artifacts/coverage-matrix.md`](../../artifacts/coverage-matrix.md)).

The five Go conjuncts, quoted verbatim, each with its disposition against
that bundle:

| # | Gate conjunct (verbatim from ADR 0006 §O-16) | Disposition |
| --- | --- | --- |
| 1 | correctness, security, lifecycle, and license review passes | **Not yet applicable** — no native implementation exists in this workspace to review |
| 2 | at least 15% median and p99 end-to-end improvement on at least two representative vendor cells | **Unmeasurable** — requires a native side measured on two declared vendor cells; none exists, and the second-vendor-cell question is an open ruling |
| 3 | the improvement is observed across at least three fresh-process comparisons | **Unmeasurable** — no native side exists to compare |
| 4 | no p99 regression greater than 5% on any declared cell | **Unmeasurable** — no native side exists to compare |
| 5 | no unexplained memory amplification greater than 10% | **Unmeasurable** — additionally, no current runner provides a memory (RSS) instrumentation lane ([`artifacts/coverage-matrix.md`](../../artifacts/coverage-matrix.md), gate input 5) |

Consequence clauses that bind regardless of numbers: a critical
correctness/security/lifecycle failure quarantines the native path
immediately; a native path never enters `Backend::Auto` before Go;
two release cycles with less than 5% benefit trigger a retirement review.
All three remain satisfied vacuously today — there is no native path to
quarantine, promote, or retire — and this record changes none of them.

**Verdict: No-Go, with zero gate conjuncts satisfied and none waivable.**
Threshold changes require a new decision record and cannot be weakened by
an implementation-local benchmark, so no part of this disposition may be
read as relaxing conjunct 1–5.

### What was actually measured (context only — not gate numbers)

These are pooled descriptive statistics from the inconclusive-labelled
bundle; per O-08 they are never pooled across profiles into one performance
claim, and they are not comparable accept-to-present claims because the
accelerated seam has no present step yet:

Source for every value below:
[`artifacts/EVIDENCE.md`](../../artifacts/EVIDENCE.md) (pooled descriptive
statistics and the native refusal transcript), cross-checked against the
gate-input rows of
[`artifacts/coverage-matrix.md`](../../artifacts/coverage-matrix.md).

| Profile | pooled p50 | pooled p95 | pooled p99 | status |
| --- | --- | --- | --- | --- |
| strict | 22.015 ms | 23.030 ms | 24.256 ms | measured, inconclusive (no gpu/queue/scanout instrumentation on host) — `artifacts/EVIDENCE.md` |
| hybrid | 22.236 ms | 23.605 ms | 24.710 ms | measured, inconclusive (same reasons; drives the same implemented facade path as strict) — `artifacts/EVIDENCE.md` |
| accelerated | 0.145 ms | 0.151 ms | 0.163 ms | measured, inconclusive (seam resolve cost only; no present step) — `artifacts/EVIDENCE.md` |
| native | — | — | — | refused pre-run, exit 2, no manifest or samples written — `artifacts/EVIDENCE.md`, `artifacts/coverage-matrix.md` |

The ~150x gap between accelerated and strict is expected and correctly
labelled: packet construction plus scene resolution versus the full facade
render path. It predicts nothing about an accept-to-present A/B outcome.
(Both observations are recorded in
[`artifacts/EVIDENCE.md`](../../artifacts/EVIDENCE.md).)

### Honesty rule for the native cell

A run that executes zero frames cannot satisfy the O-08 block schema (every
block carries `frame_count >= min_frames_per_block` even under
`status=inconclusive`). The only fail-closed representation of an
unexecutable cell is refusal before any output directory or child process
exists — stderr reason, exit code 2, zero artifacts. Emitting a synthetic
"inconclusive" native manifest would require either fabricated frame counts
or a schema-invalid document; both are forbidden. The refusal behavior is
unit-tested alongside the profile availability matrix. The schema constraint
and the refusal transcript are recorded in
[`artifacts/EVIDENCE.md`](../../artifacts/EVIDENCE.md), and the covering
unit tests are named in
[`artifacts/coverage-matrix.md`](../../artifacts/coverage-matrix.md).

## Alternatives considered

- **Declare provisional Go on the accelerated-vs-strict gap:** rejected;
  the gap measures seam overhead, not render cost; the comparison crosses
  profile boundaries, which O-08 forbids pooling; and conjunct 1 fails on
  undeclared hardware regardless.
- **Emit a schema-valid inconclusive native manifest with zero-frame
  blocks:** rejected; it violates the D1 block schema and normalizes
  fabricating measurements for cells that never ran.
- **Defer any decision record until a macOS run exists:** rejected for
  process reasons; LP-PLAT-003 names a Phase-4 *decision record* as the
  target artifact, O-16's "Needed before" line expects the gate to be
  evaluated explicitly, and recording the honest No-Go now prevents the
  unbounded state where nobody can say which conjuncts are open.

## Consequences

- The Metal lane stays quarantined out of every shipping surface: no
  `Backend::Auto` participation, no facade re-export, no support claim,
  no dependency added to any accepted v1 crate.
- The next gate attempt requires, in order: a concretized renderer seam
  consumer on declared hardware, an O-07 evidence pass on the declared
  macOS/Metal cell, then a full O-08 native-vs-portable A/B under the
  five-block protocol — plus a memory-instrumentation lane for conjunct 5,
  which no current runner provides.
- The second-vendor-cell question (conjunct 2 requires two representative
  vendor cells while O-07 declares exactly one macOS/Metal row) remains an
  explicit architecture-authority ruling recorded in
  [the post-v1 Metal fast-path design notes §7](../research/post-v1-metal-fastpath-design-notes.md);
  this record does not guess it.
- Retirement review triggers stay armed: if a future native path ships
  experimentally and posts less than 5% benefit across two release cycles,
  the retirement review fires exactly as ADR 0006 states.

## Verification and evidence boundary

Required artifacts referenced by this record, all produced by the
measurement lane and stored in-tree with it, are the two evidence documents
cited throughout: [`artifacts/EVIDENCE.md`](../../artifacts/EVIDENCE.md) —
the profile x status matrix, the native refusal transcript, the pooled
statistics quoted above, the R2 tooling behaviors (manifest validation,
cross-profile comparison refusal, same-profile paired A/B, per-clock
quantiles), and per-run environment provenance — and
[`artifacts/coverage-matrix.md`](../../artifacts/coverage-matrix.md) — the
per-conjunct map from each O-16 gate input to its evidence artifact and its
measurability verdict on this host. The underlying per-run manifests and raw
JSONL samples referenced by those two documents remain stored with the
measurement lane itself.
None of these artifacts closes a traceability row by itself: results remain
`Not measured` / `environment required` in the
[traceability registry](../requirements/traceability-v1.0.md) until the
declared-hardware evidence pass exists.

## Residual risks

- The undeclared-host baseline can drift while the declared cell remains
  unmeasured; the pooled numbers above are snapshots, not baselines of
  record, and must be re-measured under the declared-cell protocol before
  any future Go claim cites them.
- Present-domain instrumentation on Apple Silicon (which scanout/compositor
  markers are obtainable) is unresolved in the research notes; until it is,
  even a successful macOS run may produce incomplete present-latency columns.
- Memory amplification (conjunct 5) has no instrumentation lane anywhere in
  the current tooling; a future lane must add it before the gate can even be
  attempted, rather than guessing a number.

## Related records

- [ADR index](README.md)
- [O-08 evidence bundle summary — `artifacts/EVIDENCE.md`](../../artifacts/EVIDENCE.md)
- [O-16 gate-input coverage matrix — `artifacts/coverage-matrix.md`](../../artifacts/coverage-matrix.md)
- [ADR 0002 — GPU-native engine and Matplotlib adapter](0002-gpu-native-engine-and-matplotlib-adapter.md)
- [ADR 0006 — support, benchmark, and native gates](0006-support-benchmark-native-gates.md)
- [O-16 open-decision entry](../architecture/open-decisions.md#o-16-native-backend-adoption-and-retirement-gates)
- [Post-v1 Metal fast-path design notes (LP-PLAT-003)](../research/post-v1-metal-fastpath-design-notes.md)
- [Post-v1 native OS-cell declaration proposal](../research/post-v1-native-os-cell-declaration-proposal.md)
