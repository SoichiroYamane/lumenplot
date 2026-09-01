#!/usr/bin/env python3
"""Machine verification for docs/requirements/traceability-v1.0.md coverage bookkeeping.

Recomputes every Coverage-summary number directly from the registry and
closure tables in that same file, then asserts:

  1. the published Coverage summary block equals the recomputation;
  2. the normative-closure section lists exactly the MUST/MUST NOT rows;
  3. the GAP-R1 adoption split (three normative, two advisory) matches both
     the registry classes and the source research document;
  4. the recorded pre-adoption baselines are arithmetically consistent
     (baseline + added == published totals);
  5. the five GAP-R1 evidence-gate names exist in the registry.

Exit code 0 iff all checks pass. Intended for CI and pre-commit use.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TRACE = REPO / "docs" / "requirements" / "traceability-v1.0.md"
GAPR1 = REPO / "docs" / "research" / "codex-gap-verification-candidate-rows.md"

ROW = re.compile(r"^\|\s*`(LP-[A-Z]+-\d+)`\s*\|\s*`([A-Z][A-Z -]*?)`\s*\|(.*)$")
GATE = re.compile(r"`(AT-[A-Z0-9-]+)`")

GAPR1_IDS = ("LP-FUNC-040", "LP-FUNC-041", "LP-MPL-021", "LP-MPL-022", "LP-MPL-023")
GAPR1_NEW_GATES = (
    "AT-FUNC-NAN-GAP",       # LP-FUNC-040
    "AT-MPL-PREFLIGHT-SOUNDNESS",  # LP-MPL-021
    "AT-MPL-UNIT-DATA",      # LP-MPL-022
    "AT-MPL-COLLECTIONS",    # LP-MPL-023
    "AT-FUNC-MAPPABLE",      # LP-FUNC-041
)

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def sections(text: str) -> dict[str, str]:
    out: dict[str, list[str]] = {}
    cur = "(preamble)"
    for line in text.splitlines():
        if line.startswith("## "):
            cur = line[3:].strip()
            out[cur] = []
        else:
            out.setdefault(cur, []).append(line)
    return {k: "\n".join(v) for k, v in out.items()}


def main() -> int:
    text = TRACE.read_text(encoding="utf-8")
    secs = sections(text)

    # --- recompute from the registry -----------------------------------------
    reg: list[tuple[str, str, str]] = []  # (id, class, whole row)
    for line in secs["Complete requirement registry"].splitlines():
        m = ROW.match(line)
        if m:
            reg.append((m.group(1), m.group(2), line))
    ids = [r[0] for r in reg]
    classes = {rid: cls for rid, cls, _ in reg}

    dupes = sorted({rid for rid in ids if ids.count(rid) > 1})
    check("registry IDs unique", not dupes, f"duplicates: {dupes}")

    class_counts: dict[str, int] = {}
    for _, cls, _ in reg:
        class_counts[cls] = class_counts.get(cls, 0) + 1

    fam_counts: dict[str, int] = {}
    for rid, _, _ in reg:
        fam = rid.split("-")[1]
        fam_counts[fam] = fam_counts.get(fam, 0) + 1

    norm_ids = {rid for rid, cls, _ in reg if cls in ("MUST", "MUST NOT")}
    gates_registry: set[str] = set()
    gates_column_only: set[str] = set()
    for rid, cls, line in reg:
        found = GATE.findall(line)
        gates_registry.update(found)
        col = line.split("|")[6]  # Evidence gate(s) column (0-based: '', ID, Class, Target, Phase, Release, Gates, ...)
        gates_column_only.update(GATE.findall(col))

    check(
        "gate count stable (whole row vs gate column)",
        gates_registry == gates_column_only,
        f"{len(gates_registry)} vs {len(gates_column_only)}",
    )

    # --- closure section must equal the normative set ------------------------
    clo: list[tuple[str, str]] = []
    for line in secs["Normative closure: every MUST and MUST NOT"].splitlines():
        m = ROW.match(line)
        if m:
            clo.append((m.group(1), m.group(2)))
    clo_map = dict(clo)
    check("closure rows unique", len(clo_map) == len(clo), f"{len(clo)} rows")
    check("closure covers every MUST/MUST NOT row", set(clo_map) == norm_ids,
          f"missing={sorted(norm_ids - set(clo_map))} extra={sorted(set(clo_map) - norm_ids)}")
    check("closure classes agree with registry",
          all(classes.get(rid) == cls for rid, cls in clo),
          str({rid: (classes.get(rid), cls) for rid, cls in clo if classes.get(rid) != cls}))

    # --- published summary block must equal the recomputation ----------------
    summ = secs["Coverage summary"]

    def bold(pat: str) -> int:
        m = re.search(pat, summ)
        return int(m.group(1)) if m else -1

    pub_entries = bold(r"Requirement entries: \*\*(\d+)\*\*")
    pub_norm = bold(r"requiring closure: \*\*(\d+)\*\*")
    pub_gates = bold(r"Evidence gates referenced: \*\*(\d+)\*\*")
    check("published entries == recomputed", pub_entries == len(reg), f"{pub_entries} vs {len(reg)}")
    check("published normative == recomputed", pub_norm == len(norm_ids), f"{pub_norm} vs {len(norm_ids)}")
    check("published gates == recomputed", pub_gates == len(gates_registry), f"{pub_gates} vs {len(gates_registry)}")

    m = re.search(r"Classification counts: (.+)", summ)
    pub_classes: dict[str, int] = {}
    if m:
        pub_classes = {k.strip(): int(v) for k, v in re.findall(r"([A-Z][A-Z -]*?)=(\d+)", m.group(1))}
    check("published classification counts == recomputed", pub_classes == class_counts,
          f"published={pub_classes} recomputed={class_counts}")

    m = re.search(r"Stable families: (.+)", summ)
    pub_fams: dict[str, int] = {}
    if m:
        pub_fams = dict(
            (name, int(n)) for name, n in re.findall(r"`([A-Z]+)` \((\d+)\)", m.group(1))
        )
    check("published families == recomputed", pub_fams == fam_counts,
          f"only-published={ {k: v for k, v in pub_fams.items() if pub_fams.get(k) != fam_counts.get(k)} } "
          f"only-recomputed={ {k: v for k, v in fam_counts.items() if pub_fams.get(k) != v} }")

    # --- GAP-R1 adoption split ----------------------------------------------
    new_cls = {rid: classes.get(rid) for rid in GAPR1_IDS}
    n_norm = sum(1 for c in new_cls.values() if c in ("MUST", "MUST NOT"))
    n_adv = sum(1 for c in new_cls.values() if c in ("SHOULD", "MAY"))
    check("all five GAP-R1 rows present in registry", all(v for v in new_cls.values()), str(new_cls))
    check("GAP-R1 split is three normative / two advisory", (n_norm, n_adv) == (3, 2),
          f"{n_norm} normative / {n_adv} advisory from {new_cls}")

    gap_text = GAPR1.read_text(encoding="utf-8") if GAPR1.exists() else ""
    if gap_text:
        src_rows = re.findall(r"^\|\s*`(LP-[A-Z]+-\d+)`\s*\|\s*(MUST|SHOULD)\s*\|.*\|\s*ADOPTED\s*\|",
                              gap_text, re.M)
        src_cls = dict(src_rows)
        check("research doc marks exactly the five GAP-R1 rows ADOPTED", set(src_cls) == set(GAPR1_IDS),
              f"src={sorted(src_cls)}")
        check("research doc levels agree with registry classes",
              all(new_cls[rid] == cls for rid, cls in src_cls.items()),
              str({rid: (new_cls.get(rid), cls) for rid, cls in src_cls.items() if new_cls.get(rid) != cls}))
    else:
        failures.append("research doc missing")
        print("[FAIL] GAP-R1 source research doc not found:", GAPR1)

    for g in GAPR1_NEW_GATES:
        check(f"GAP-R1 gate defined in registry: {g}", g in gates_registry)

    # --- adoption-note baselines are arithmetically consistent ---------------
    # Matplotlib wave (2026-08-25): nine entries added onto a 223-entry base.
    mpl_wave_ids = [f"LP-FUNC-{n:03d}" for n in range(32, 40)] + ["LP-MPL-020"]
    check("Matplotlib-wave rows present", all(r in classes for r in mpl_wave_ids))
    check("2026-08-25 note records pre-adoption baseline 223/150/92",
          "the pre-adoption baseline was 223 entries / 150 normative / 92 gates" in text)
    # Chain: note-1 base + its nine additions == note-2's recorded pre-adoption
    # baseline (232/153/101); note-2 base + five additions == published totals.
    check("adoption-note arithmetic chains 223+9 -> 232 -> +5 -> published",
          223 + 9 == 232 and 150 + 3 == 153 and 92 + 9 == 101
          and 232 + 5 == pub_entries and 153 + 3 == pub_norm and 101 + 5 == pub_gates,
          f"{pub_entries}/{pub_norm}/{pub_gates}")
    # GAP-R1 (2026-08-26): five entries onto the post-Matplotlib-wave base.
    check("2026-08-26 note records pre-adoption baseline 232/153/101",
          "pre-adoption baseline was 232 entries / 153 normative / 101 gates" in text)
    check("2026-08-26 baseline arithmetic (232 + 5 == published)",
          232 + 5 == pub_entries and 153 + 3 == pub_norm and 101 + 5 == pub_gates,
          f"{pub_entries}/{pub_norm}/{pub_gates}")
    check("adoption note says three normative, two advisory",
          "three normative, two advisory" in text and "two normative, three advisory" not in text)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        return 1
    print(f"OK: traceability coverage bookkeeping verified "
          f"({len(reg)} entries, {len(norm_ids)} normative, {len(gates_registry)} gates).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
