---
name: lumenplot-python-bridge
description: Use for Python, NumPy, PyO3, or Matplotlib bridge work.
version: 0.1.0
metadata:
  hermes:
    tags: [LumenPlot, Python, NumPy, PyO3, Matplotlib]
    related_skills: [lumenplot-contract, lumenplot-benchmark]
---

# LumenPlot Python bridge procedure

Use for Python bindings, NumPy ingestion, PyO3 boundaries, the one-way Matplotlib
adapter, explicit hybrid/fallback behavior, or Python packaging. Always load
`lumenplot-contract` first for public API, ABI, ownership, error, or state
authority questions.

## Procedure

1. Read [`../../../.hermes.md`](../../../.hermes.md), the linked bridge
   reference, and the canonical requirements, traceability map, accepted ADR,
   and applicable architecture gate.
2. Identify the mode and state authority. Keep the independent engine below the
   adapter; do not make the engine depend on Python or Matplotlib concrete types.
3. Implement only the declared public adapter contract. Preserve explicit
   capability diagnostics and fallback; never silently claim full Matplotlib
   compatibility or hide unsupported custom/private behavior.
4. Treat NumPy borrowing as an ingestion-lifetime question, not as a promise of
   long-lived Python memory, worker access, or automatic GPU zero-copy. Escalate
   unresolved dtype, shape, stride, mutation, exception, GIL, thread, or lifetime
   policy before editing the public boundary.
5. Test the public path, state synchronization, strict and hybrid behavior,
   fallback diagnostics, error mapping, packaging, and supported backend matrix.
   Send timing or compatibility breadth claims to `lumenplot-benchmark`.

## Pitfalls

Do not reimplement the Matplotlib Artist hierarchy, depend on private backend
APIs, let a borrowed array escape its contract, or treat a passing import as
proof of ABI, rendering, or lifecycle correctness.

## Verification

Record the accepted adapter source, mode/state authority, Python and NumPy
boundary cases exercised, expected diagnostics, packaging checks, and any
unmeasured compatibility surface. Architecture-sensitive uncertainty remains a
contract gate.
