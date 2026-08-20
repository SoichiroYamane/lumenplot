# Python and Matplotlib bridge checklist

This is a triggered procedure, not a public binding schema. Read the
[requirements](../../../../docs/requirements/lumenplot-v1.0.md),
[traceability map](../../../../docs/requirements/traceability-v1.0.md),
[accepted ADR](../../../../docs/adr/0002-gpu-native-engine-and-matplotlib-adapter.md),
and the relevant [architecture decisions](../../../../docs/architecture/) first.

## Boundary checks

- Keep the dependency direction `Matplotlib -> adapter -> engine` and the
  engine independent of Python and Matplotlib types.
- Preserve the accepted authority split: Matplotlib Figure/Artist state in
  Matplotlib mode and PlotScene state in native mode. Treat derived snapshots,
  revisions, and synchronization as explicit transitions.
- Keep strict, hybrid, accelerated, and fallback behavior distinguishable. A
  rendered fallback must not hide unsupported effects, private API use, or a
  loss of semantic fidelity.
- Treat borrowed NumPy views as bounded ingestion access. Long-lived native
  state, workers, and GPU upload ownership follow the accepted Rust contract;
  do not promise automatic GPU zero-copy.

## Procedure

1. Identify the public object and mode being changed; link its canonical source.
2. Check dtype, shape, stride, contiguity, non-finite, mutation, exception,
   GIL, thread, and lifetime behavior against the accepted boundary.
3. Exercise state synchronization, redraw/export, fallback diagnostics, and
   close/reentrancy behavior without reaching into private Matplotlib APIs.
4. Run the supported-version/backend/packaging matrix selected by the canonical
   release plan. Separate source compatibility from visual and performance
   evidence.

## Verification

Report exact cases tested, expected errors or diagnostics, authority and revision
transitions, package artifacts, and any unsupported surface. Do not label the
adapter fully compatible unless the declared public contract and test matrix
support that claim.
