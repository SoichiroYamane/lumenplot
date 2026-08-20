---
name: lumenplot-contract
description: Use for LumenPlot API, schema, and architecture gates.
version: 0.1.0
metadata:
  hermes:
    tags: [LumenPlot, architecture, API, schema, ownership]
    related_skills: [lumenplot-rust-core, lumenplot-python-bridge, lumenplot-benchmark]
---

# LumenPlot contract gates

Use this skill when a request can change a public API, schema, persistence format,
crate or module boundary, ownership/lifecycle/concurrency rule, backend
abstraction, security boundary, or performance contract. Load it before either
domain skill for implementation work.

## Procedure

1. Read [`../../../.hermes.md`](../../../.hermes.md).
2. Read the applicable [v1 requirements](../../../docs/requirements/lumenplot-v1.0.md),
   [accepted ADR](../../../docs/adr/0002-gpu-native-engine-and-matplotlib-adapter.md),
   [traceability map](../../../docs/requirements/traceability-v1.0.md), and the
   relevant files under [architecture decisions](../../../docs/architecture/).
3. Classify the request as an implementation of an accepted contract or as a
   decision request. Treat an unresolved exact signature, field set, error,
   lifecycle, fallback, or support matrix item as a decision request.
4. For a decision request, stop before editing and state the smallest question
   that `architecture-authority` must settle. Do not infer a public contract from
   code, a proposal note, or a convenient local type.
5. For accepted implementation work, link the governing source in the handoff,
   keep the change inside its boundary, and load the domain skill as needed.
6. Ask `reviewer` to check routine evidence. Route architecture-sensitive
   deviations back to `architecture-authority`.

## Quick checks

- Requirements outrank accepted ADR amendments; code and tests provide evidence;
  proposal notes are not authority.
- The engine remains independent from concrete frontend/backend types.
- A skill is a procedure and link, not a second API or schema document.
- Compatibility and fallback behavior must be explicit and diagnosable.
- Use role names only; never add personal names, machine paths, or private run
  identifiers to public files.

## Pitfalls

Do not revive a historical ADR because it is easier to implement. Do not turn an
open architecture gate into an implementation detail. Do not accept a passing
unit test as proof of an unmeasured performance or cross-platform claim.

## Verification

A contract-gated change is ready for routine review only when its source links,
role ownership, dependency direction, scope, and architecture-sensitive tests
are recorded and no unresolved decision is hidden in the diff.
