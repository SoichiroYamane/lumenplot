# Phase-3B wheel/entry-point CI job proposal (propose-only)

Status: **proposal — not wired into GitHub Actions**

This directory holds a *proposed* Phase-3B packaging-evidence CI job. It is
deliberately **not** placed under `.github/workflows/`: per the accepted
Phase-3B delivery order (ADR 0015 §12), lifecycle/loader evidence comes last,
after the backend implementation lane lands, and workflow activation is a
reviewed change. This file exists so reviewers can see and discuss the exact
proposed shape without it executing anywhere.

## What the proposal contains

`phase3b-ci-job-proposal.yml` — a draft job that would:

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

## Why propose-only

- ADR 0015 §12 orders this evidence after backend implementation; wiring the
  job now would make CI red for reasons the ordered plan already anticipates.
- The manifest is convenience evidence, not acceptance evidence: the offline,
  containerized, hash-pinned pattern of the Phase-3A2 lane remains the
  canonical supply-chain gate for release claims.
- Workflow files execute on third-party infrastructure; adding one is a
  maintainer-visible decision that belongs in review, not in a worker diff.

## How to evaluate

Run locally without any workflow changes:

```sh
python3 scripts/test_phase3b_wheel_evidence.py --probe --workdir /tmp/phase3b-probe
```

The command prints the same JSON manifest the proposed job would upload.
Unit tests for the probe's own constants:

```sh
python3 -m unittest scripts.test_phase3b_wheel_evidence
```

## Follow-up when the backend lands

1. Re-run the local probe; expect `surface_status: "implemented"` with every
   surface boolean true and zero skipped identity checks.
2. Move `phase3b-ci-job-proposal.yml` under `.github/workflows/` (renamed,
   pinned actions, least-privilege permissions) via a reviewed PR.
3. Fold the emitted manifest into the Phase-3B evidence record alongside the
   offline-lane outputs; do not treat this manifest alone as acceptance.
