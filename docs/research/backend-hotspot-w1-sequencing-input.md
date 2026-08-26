# Process note: `python/lumenplot_mpl/backend.py` as a W1 collision hotspot, and the W2 lane-sequencing input

## Status

**PROCESS RECORD AND SEQUENCING INPUT ONLY — NOT AN ACCEPTED DESIGN, NOT AN
ARCHITECTURE DECISION, NOT A SUPPORT OR PERFORMANCE CLAIM.**
This note records what actually happened around one shared file during the
W1 "static geometry" workstream (2026-08-26) so the next wave plans its lane
order deliberately instead of rediscovering the constraint. It proposes no
module split, no refactor, and no ownership rule; any such design belongs to
the `project-commander` / `architecture-authority` through the normal gates.

Evidence basis: git history on `origin/main` @ `6fc8db0`, verified 2026-08-26.

## 1. What happened in W1

All three W1 implementation lanes had to modify the same file,
`python/lumenplot_mpl/backend.py` (the Phase-3B public adapter): each
LP-MPL-020 eligibility extension touches the whitelist tuple, the static-check
dispatch, the collector-trace branch, and the spec builder that live there.

The merge timeline shows the cost of running three lanes against it:

| Date (2026-08-26) | Event | backend.py delta |
| --- | --- | --- |
| 04:13–04:35 | fill lane (`wt/t_93a0421c`): pre-takeover WIP `98a4f9f`, then merge-with-main snapshot `e32e1be` to absorb the landed textpath/decoration lanes before the real commit `5817303` | +390 then +342/−22 lines churn across two commits for one feature |
| 05:40 | bar lane merges main into `wt/t_d4ceb6af` (`52d4956`), absorbing the just-merged fill slice into `backend.py` (+76/−3 resolved in that file) before its PR #69 merges at 05:53 | +76/−3 |
| 08:25 | steps lane forced a mid-flight merge-from-main `9961e02` to absorb bar (the same `_EligibilityPreflight` regions again) before PR #70 could merge at 08:46 | +76/−3 |

The technical-manager's arming note made the serial chain fill→bar→steps
intentional precisely to avoid concurrent edits to this file ("backend.py
shared-region conflict avoidance"), yet even the serialized lanes each needed
a merge-from-main stop because every extension rewrites overlapping regions:
`_ARTIST_WHITELIST`, the isinstance dispatch chain, the per-class style
checks, the stage-two collector branches, and `build_frame_spec`.

## 2. Why it is structural (observation, not design)

The file concentrates five responsibilities that every eligibility extension
must extend together (the LP-MPL-020 four mechanics plus spec emission):

1. stage-one artist whitelist;
2. per-class static style contracts and their dispatch;
3. stage-two public collector trace grammar;
4. geometry assembly into frame-spec commands;
5. strict/hybrid dispatch and diagnostics publication.

That concentration is what makes extensions reviewable as one unit — and also
what serializes every lane that grows the eligible surface. The pattern is
expected to repeat: the already-planned W2 compositing/date-axis lanes and any
future artist class touch the same regions.

## 3. What W1 practice already does about it (keep doing)

- **Serialize by design.** The parent card ordered the lanes and stated why;
  the ordering held even when it cost wall-clock time.
- **One feature = one commit** per lane (fill `5817303`, bar `028746b`,
  steps `b968c00`), so merge-conflict resolution never interleaves with
  feature logic in history.
- **Merge main into the lane before the feature commit**, keeping the
  conflict-resolution diff separate from the feature diff (all three lanes
  did this; the two mid-flight merges above are the visible cost).
- **Independent review per lane plus an integration card** (`t_19ef7f10`)
  that re-runs all gates on the composed tree — this caught composition-level
  facts no single-lane run could see.

## 4. Sequencing input for W2 (no decision taken here)

For the next wave planning against the same file:

- Keep explicit lane serialization in the parent plan whenever more than one
  lane must edit `backend.py`; treat "merge main into lane immediately before
  opening the PR" as part of the definition of done.
- Budget for one absorb-merge per lane in review time; the W1 data point is
  ~76 resolved backend.py lines per crossing (measured twice, bar and steps).
- If a future wave needs concurrent lanes on this surface anyway, the split
  question (which of the five responsibilities above could move to their own
  modules without breaking the LP-MPL-020 one-unit reviewability contract)
  is an architecture decision to be taken once, up front, by the
  architecture authority — not negotiated per lane mid-flight.

## 5. Related records

- [ADR 0015 §12](../adr/0015-phase3b-public-matplotlib-adapter-contract.md) —
  ordered delivery rationale ("a combined leap … concentrates failures around
  one collision hotspot"); this note records the hotspot materializing exactly
  as that alternative-analysis predicted.
- [`traceability-v1.0.md`](../requirements/traceability-v1.0.md) — the flipped
  `LP-FUNC-032`/`033`/`034` rows name the merged fixture classes per lane.
- Workstream cards: W1 plan `t_996b69bd`, lanes `t_93a0421c` / `t_d4ceb6af` /
  `t_cf97d908`, integration `t_19ef7f10`, final review `t_63ec1a75`.
