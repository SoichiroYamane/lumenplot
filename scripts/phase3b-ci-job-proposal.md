# Phase-3B wheel/entry-point CI job proposal (activated)

Status: **activated** — see `.github/workflows/phase3b-wheel-evidence.yml`.

This directory holds the *original proposal* for the Phase-3B
packaging-evidence CI job. It was deliberately kept out of
`.github/workflows/` until the accepted Phase-3B delivery order (ADR 0015
§12) allowed lifecycle/loader evidence: that evidence comes last, after the
backend implementation lane lands. With the backend module merged and the
entry point declared in `pyproject.toml`, the job is now active under
`.github/workflows/phase3b-wheel-evidence.yml`; this file remains as the
rationale record.

## What was proposed (now active)

The draft job would:

1. check out the repository;
2. create an isolated build venv, install the hash-pinned maturin 1.14.1
   wheel (same reviewed artifact and digest as the accepted Phase-3A2
   offline lane), run `maturin build --release --locked`;
3. install the produced `cp311-abi3` wheel into a fresh run venv with the
   pinned NumPy evidence stack (`numpy==2.4.6`) and Matplotlib 3.11.1;
4. run `python -m unittest discover -s tests/python`, which covers both the
   existing Phase-3A2 helper suite and the new
   `tests/python/test_phase3b_entrypoint.py` identity checks (the entry-point
   checks skip cleanly until the backend module from the sibling lane
   exists, then become standing regression gates);
5. probe the API-0005 surface (entry-point group/name/value, module loader,
   `filetypes` PNG-only, `required_interactive_framework is None`,
   forbidden legacy exports) and emit a JSON manifest as a workflow artifact.

The package-installed public runtime probe is additionally invoked by the
hardened four-cell container lane in
`.github/workflows/phase3a2-wheel.yml`. That lane records one path-free result
for each GIL CPython 3.11, 3.12, 3.13, and 3.14 environment with Matplotlib
3.11.1, then validates the ordered set before optional evidence upload. The
Phase-3B workflow above remains a convenience host probe; neither workflow
creates a support or release claim by itself.

## Why the separate job remains convenience-only

- ADR 0015 §12 orders this evidence after backend implementation; wiring the
  job earlier would have made CI red for reasons the ordered plan already
  anticipated.
- The host manifest is convenience evidence, not acceptance evidence: the
  offline, containerized, hash-pinned pattern of the Phase-3A2 lane remains
  the canonical supply-chain gate for release claims.
- The four-cell runtime records are evidence of one named CI run only; they do
  not establish support, compatibility breadth, or publication readiness.

## How to evaluate

Run locally without any workflow changes:

```sh
python3 scripts/test_phase3b_wheel_evidence.py --probe --workdir /tmp/phase3b-probe
```

The command prints the same JSON manifest the workflow uploads.

Unit tests for the probe's own constants:

```sh
python3 -m unittest scripts.test_phase3b_wheel_evidence
```

## Activation record

1. The local probe reports `surface_status: "implemented"` with every surface
   boolean true when its declared environment is available; a blocked probe is
   reported as blocked rather than treated as a pass.
2. The job now lives at `.github/workflows/phase3b-wheel-evidence.yml`
   (renamed from this proposal), pinned to the reviewed action SHAs from
   `docs/security/pinned-actions.yml`, least-privilege (`contents: read`),
   with the artifact upload restricted to trusted `main` pushes.
3. The emitted manifest folds into the Phase-3B evidence record alongside
   the offline-lane outputs; it is not treated as acceptance alone.
