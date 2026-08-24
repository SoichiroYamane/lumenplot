# Post-v1 design research: Metal fast-path prototype comparison points (LP-PLAT-003)

## Status

**DESIGN RESEARCH ONLY — NOT AN ACCEPTED DECISION, ROADMAP COMMITMENT,
ADDITION, RETENTION, OR SUPPORT CLAIM.**
This note explores what a Phase-4 Metal fast-path prototype *would have to
measure* against the accepted portable path if the project ever chooses to
run the experiment. Nothing here promotes a native Metal candidate to a
promise, a dependency, an implementation obligation, or a support claim.
Where this note says "option", "sketch", or "future", read exactly that.

**v1 NON-GOAL declaration.** Native fast-path fan-out is excluded from v1 by
the canon:

- [LP-PLAT-003](../requirements/lumenplot-v1.0.md) — `MUST`: "Adopt a Metal
  fast path only when prototype measurements and profiling show a meaningful
  benefit over the selected portable path." (`Target: Phase 4 decision
  record`, `Release: conditional future`, `Phase: 4`, evidence
  `AT-BENCH-NATIVE-AB`). The requirement gates adoption; it does not
  authorize implementation now.
- [LP-REL-007](../requirements/lumenplot-v1.0.md) — `PHASE`: "Phase 4 covers
  conditional Metal, D3D12, and Vulkan prototypes and their measured
  comparison with the portable path." (`Release: future`).
- [O-16](../architecture/open-decisions.md#o-16-native-backend-adoption-and-retirement-gates),
  recorded in [ADR-0006](../adr/0006-support-benchmark-native-gates.md):
  "No native Metal, D3D12/DXGI, or Vulkan implementation fan-out occurs
  before the portable baseline and the O-07/O-08 evidence pass." The
  open-decision entry itself states: "no native fan-out before
  portable/O-07/O-08 evidence".
- [ADR-0002](../adr/0002-gpu-native-engine-and-matplotlib-adapter.md):
  "Metal, D3D12/DXGI, and Vulkan paths are Phase 4 prototype candidates. A
  native path is adopted only when measured frame time, CPU overhead, present
  latency, memory, and feature availability show a meaningful benefit that
  justifies maintenance. A newer API alone is not an adoption reason."

Changing that envelope requires an explicit ADR amendment plus coordinated
requirements and traceability updates through the `architecture-authority`
decision gate. That work is **out of scope for this note**, which changes
nothing and commits to nothing.

Evidence basis: all repository citations below were verified verbatim on
origin/main @ `265d194` on 2026-08-24.

Terminology: throughout, the subject is the **Phase-4 conditional prototype
candidate (LP-PLAT-003)**. The requirements vocabulary ends at Phase 5 /
`future` / `5+`; no "Phase 6" exists and none is introduced here.

## Scope guard: why this note exists

The task that produced this note asked for *comparison points*: the
independent variables, measurement boundaries, and decision thresholds a
future Metal-vs-wgpu experiment must respect. It deliberately does not ask
for — and this note does not contain — a Metal implementation plan, a crate
layout, a shader strategy, or a timeline. Those belong to a future ADR under
the `architecture-authority` gate, only after the preconditions in §6 hold.

## 1. Current state (verified)

The portable baseline is contractual; no Metal surface exists:

- `crates/lumenplot-render-api/src/lib.rs` is a private Phase-0 documentation
  stub: "Packet construction and validation are deferred to a later phase."
  No renderer trait, packet type, or backend enum is published there yet.
- `crates/lumenplot-render-wgpu/src/lib.rs` is likewise a stub ("Renderer
  implementation is deferred until the internal boundary is ready"), and its
  Cargo.toml depends only on `lumenplot-render-api`. The lockfile carries no
  wgpu, Metal, or objc crates today; `grep -i 'wgpu|metal' Cargo.lock`
  returns nothing beyond the workspace's own stub-crate names.
- Dependency direction (ADR-0003): `lumenplot-engine ── lumenplot-render-api
  ── lumenplot-render-wgpu`; the direction never points back from render-api.
  A future Metal edge would sit beside render-wgpu consuming render-api —
  never underneath it, and never re-exported by the facade.
- The accepted portable runtime stack (ADR-0008 / O-15): wgpu 29.0.4, winit
  0.30.x, raw-window-handle 0.6.x as pinned lockfile implementation choices;
  static verified WGSL artifacts; main-thread resource ownership; device-loss
  rebuild and terminal OOM behavior. These versions are explicitly not public
  support or MSRV claims.
- Traceability status today:
  [traceability-v1.0.md](../requirements/traceability-v1.0.md) records
  `LP-PLAT-003` as "**Not measured** (environment required where hardware or
  GPU is involved)" and `LP-PLAT-001` (portable build/runtime) as
  "environment required — Not implemented". Both stay untouched by this note.

Because the portable renderer itself has no measured baseline yet, every
comparison point below is defined relative to the *contract*, not to any
existing number.

## 2. What may be compared (independent variables)

A Metal fast-path prototype differs from the wgpu portable path along exactly
the axes the canon already names in LP-PLAT-011: "Compare native prototypes
with the portable path on frame time, CPU overhead, present latency, memory,
and feature availability before adoption." Concretely:

<!-- markdownlint-disable MD013 -->

| Axis | Portable-path reference point | What a Metal prototype would vary |
| --- | --- | --- |
| Frame time | end-to-end p50/p95/p99 per O-08 protocol | same fixtures, same blocks, different submission backend |
| CPU overhead | scheduler-acceptance intervals (`event_accept_to_*`) | encode/build cost of `MTLCommandBuffer` vs wgpu's own wrapping |
| Present latency | present-domain observations recorded separately from scanout | `CAMetalLayer` presentation vs wgpu surface present |
| Memory | resident/working-set accounting in the adoption report | buffer/textures held natively vs via wgpu allocator |
| Feature availability | capability probe result per declared cell | MSL-native features wgpu does not expose on Metal |

<!-- markdownlint-enable MD013 -->

Two boundaries are fixed by O-08 regardless of axis: CPU monotonic
scheduler-acceptance intervals keep names beginning with `event_accept_to_*`;
GPU timestamp intervals remain in the GPU timestamp domain; queue completion
is recorded separately; scanout markers are recorded only when available; and
"a `present` return is not scanout". Missing required instrumentation makes a
result inconclusive/unsupported rather than silently passing.

## 3. Measurement protocol (fixed by O-08 / ADR-0006)

The protocol is not negotiable per-experiment; a Metal prototype inherits it
verbatim from ADR-0006 §"Fresh-process blocks and statistical reporting":

1. five fresh-process blocks per fixture/profile/target cell;
2. at least 1000 accepted measured frames per block;
3. A/B order randomized from a manifest seed;
4. raw samples retained (no trimming, no winsorization);
5. nearest-rank p50/p95/p99 reported per block;
6. pooled descriptive result plus maximum block p99;
7. paired block deltas with a fixed-seed 10,000-resample
   percentile-bootstrap 95% confidence interval.

Profiles stay separate and labelled: native, strict-common-2d,
hybrid-explicit, and accelerated-native results are never pooled into one
performance claim (LP-MPL-011 independently forbids applying the native
zero-Python gate to the standard transparent Figure/Artist profile). The v1
native gate workload remains MonotonicX 10M; 100M-resident, streamed, and
appendable scenarios stay separately labelled.

Target cells come from O-07/ADR-0006, not from whatever machine is handy: the
declared macOS row is "macOS 13 or newer, arm64, Metal — Apple Silicon", with
Lavapipe as control only and never a present-support claim. Each cell's
evidence manifest records exact OS build, vendor/device, driver string, API
feature level, compositor, display scale, and present mode.

## 4. Decision thresholds (fixed by O-16 / ADR-0006)

A Metal prototype reaches **Go** only after all of the following, none of
which this note asserts, predicts, or pre-measures:

- correctness, security, lifecycle, and license review passes;
- ≥ 15% median **and** p99 end-to-end improvement on at least two
  representative vendor cells;
- improvement observed across at least three fresh-process comparisons;
- no p99 regression greater than 5% on any declared cell;
- no unexplained memory amplification greater than 10%.

Additionally: a critical correctness/security/lifecycle failure quarantines
the native path immediately; a native path never enters `Backend::Auto`
before Go (LP-PLAT-006 keeps `Backend::Auto` = capability probing + static
override, never a startup microbenchmark); two release cycles with < 5%
benefit trigger a retirement review (LP-PLAT-012 `MAY` retain only the
portable path); LP-PLAT-007 `MUST NOT` retains a native backend solely
because it is newer; threshold changes require a new decision record and
cannot be weakened by an implementation-local benchmark.

## 5. Architectural seams a prototype must respect

If the experiment ever runs, these accepted contracts bound it:

- **Crate placement (ADR-0003).** A Metal edge would be a new concrete
  renderer consuming `lumenplot-render-api`, sibling to
  `lumenplot-render-wgpu`; the facade never re-exports it, and nothing in
  render-api may name Metal types. Whether such a crate is even permitted to
  exist before Go is an architecture-authority question this note flags, not
  answers (§7).
- **Packet boundary (ADR-0004 / O-04).** RenderPacket stays validated
  whole-packet, immutable, process-local, internal, non-serialized, carrying
  `SceneRevision`/`WorkGeneration`/`DeviceGeneration` as distinct validation
  inputs; the logical-resource → backend-object cache key stays logical
  identity + `DeviceGeneration`. No Metal object enters the semantic core.
- **Ownership (ADR-0005 / ADR-0008).** Main-thread session owns adapter,
  device, queue, surfaces; workers prepare owned bytes only. Surface loss,
  resize, device loss, and OOM behaviors follow the existing lifecycle
  matrix obligations (LP-PLAT-009/010).
- **Shader/supply-chain policy (ADR-0008 / LP-SEC-004).** Static verified
  artifacts with provenance; no runtime compilation or download of untrusted
  source. A Metal prototype would need its MSL/AIR artifact story to satisfy
  the same negative tests (runtime-download rejection, hash/provenance)
  before benchmarking counts.
- **Profile separation (ADR-0015 / API-0005 / LP-MPL-011).** The public
  Matplotlib adapter slice makes no native performance claim for the standard
  Figure/Artist profile; hybrid-explicit fallback and strict unsupported
  behavior are unaffected by any backend experiment.

## 6. Preconditions that must hold before the experiment

Ordered; each is currently open:

1. **Portable baseline exists and measures.** `lumenplot-render-wgpu` is a
   stub; LP-PLAT-001 is `environment required — Not implemented`. The O-07
   macOS/Metal declared cell cannot yield an A/B delta until the B side
   renders at all.
2. **O-07 evidence pass.** Declared cells exercised with full lifecycle +
   correctness + benchmark manifests; until then every platform result is
   `environment required`.
3. **O-08 harness exists.** Five-block runner, JSONL capture, manifest seeds,
   bootstrap reporting as tooling contracts (internal, not public formats).
4. **Renderer seam concretized.** The private render-api boundary gains its
   real shape (packet construction/validation), so a second consumer can be
   written without inventing the seam mid-experiment.
5. **Explicit architecture-authority ADR** authorizing the prototype lane,
   per LP-PLAT-003's "Phase 4 decision record" target and O-16's
   "Needed before: Phase 4 prototype merge".

## 7. Open questions reserved for the architecture-authority

These are recorded questions, **not decisions**; each needs an explicit
future decision before any implementation work could begin:

1. **Prototype-lane legality pre-Go** — whether a non-shipping Metal crate
   may exist behind an experimental feature/crate gate during measurement,
   or whether all Metal code waits until after the Go decision (O-16 says
   fan-out waits; whether a quarantined measurement vehicle counts as
   fan-out is unstated).
2. **MSL artifact provenance** — how static Metal shader artifacts meet the
   ADR-0008 provenance/hash corpus when Xcode/toolchain versioning enters
   the build graph, and whether `.metallib` consumption changes the
   supply-chain negative tests.
3. **Present-domain instrumentation on Apple Silicon** — which scanout or
   compositor markers are obtainable on the macOS declared cell, so O-08's
   "recorded only when available" rule has a concrete availability list
   instead of an ad-hoc one per run.
4. **Second vendor cell for the two-cell rule** — O-16 requires improvement
   on two representative vendor cells, but O-07 declares exactly one macOS/
   Metal row; whether Intel-Metal (if still supportable), a second Apple
   generation, or something else satisfies the second cell needs a ruling
   before any Go claim could even be attempted.
5. **Feature-availability ledger format** — what structure the
   "feature availability" column of the LP-PLAT-011 adoption report takes
   (capability-probe diff table vs prose), so the comparison is auditable.

## References

Internal (canonical sources; linked, not copied):

- Requirements: `LP-PLAT-001`, `LP-PLAT-003`, `LP-PLAT-004`, `LP-PLAT-005`,
  `LP-PLAT-006`, `LP-PLAT-007`, `LP-PLAT-009`, `LP-PLAT-010`,
  `LP-PLAT-011`, `LP-PLAT-012`, `LP-REL-007`, `LP-MPL-011`, `LP-SEC-004`
  ([lumenplot-v1.0.md](../requirements/lumenplot-v1.0.md))
- Traceability: [traceability-v1.0.md](../requirements/traceability-v1.0.md)
  (LP-PLAT-001, LP-PLAT-003 rows)
- Architecture records:
  [ADR-0002](../adr/0002-gpu-native-engine-and-matplotlib-adapter.md),
  [ADR-0003](../adr/0003-facade-and-crate-dag.md),
  [ADR-0004](../adr/0004-renderpacket-resource-lifecycle.md),
  [ADR-0005](../adr/0005-runtime-viewer-host-loop.md),
  [ADR-0006](../adr/0006-support-benchmark-native-gates.md),
  [ADR-0008](../adr/0008-portable-gpu-and-shaders.md),
  [ADR-0015](../adr/0015-phase3b-public-matplotlib-adapter-contract.md)
- Architecture companions:
  [open-decisions](../architecture/open-decisions.md)
  (O-04, O-05, O-07, O-08, O-15, O-16),
  [api-0005](../architecture/api-0005-phase3b-public-matplotlib-backend-surface.md)
- Repository state cited: `crates/lumenplot-render-api/src/lib.rs`,
  `crates/lumenplot-render-wgpu/src/lib.rs` + `Cargo.toml`,
  root `Cargo.toml`/`Cargo.lock`

External:

- Apple Metal documentation
  (<https://developer.apple.com/documentation/metal/>)
- wgpu Metal backend notes
  (<https://docs.rs/wgpu/latest/wgpu/>)
