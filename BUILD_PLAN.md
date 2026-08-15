# HackDox Build Plan

_Compiled 2026-08-02. Sequences all 32 currently-open GitHub issues (hobbes144/HackDox) into dependency-ordered waves. Excludes #11 (web renderer, deferred v2)._

Legend: **Wave** = a batch of issues with no blocking dependencies on each other, safe to work in any order or in parallel. Waves are ordered — a later wave's issues generally depend on an earlier wave finishing.

---

## Wave 0 — Ready now, no code dependencies

Nothing here is blocked by anything else in the backlog. Good starting points regardless of what else is happening.

| Issue | What | Why it's unblocked |
|---|---|---|
| **#1** | Day 1 vertical-slice playtest | All engine pieces it needs (archetype gen, tool bridge, scoring, evidence board, save/load) are already built and closed out (#18–#30). Purely a playtest/verification pass. |
| **#3** | TypewriterLog widget | Standalone Textual component. Doesn't need anything else to exist first — and three other issues (#34, #15, #16 indirectly) want it, so building it early raises the ceiling on everything downstream instead of them settling for `Static` placeholders. |
| **#9** | Ghostscan shared day dataset (narrowed) | Logwatch and Hashcrack already got this treatment; only the Ghostscan half remains. Standalone engine work in `tools_bridge.py`. |
| **#31** | Unlock state model (`GameState.unlocked_tools` + evidence-tier gate) | Foundation of #2 — no upstream dependency. |
| **#35** | `Rule.mutability` field + per-day ruleset loading | Pure data model + loader change in `rules_engine.py`. No dependency on #2's unlock model or any content. |
| **#48** | Word banks — `DOMAINS_TRUSTED` / `AFFILIATIONS_FAKED` | Pure content/data, extends existing `AFFILIATIONS_ELITE` / `DOMAINS_DISPOSABLE` banks. |
| **#4 (decision only)** | Reward-decay curve verification | Not code-blocked — blocked on Nick confirming the proposed HD$ formula (posted as a comment on #4). Once confirmed, implementation is a small `config.py` change. |
| **#7 (optional)** | Endless mode | Technically unblocked — reuses the core engine, explicitly removes the corruption arc, so it doesn't need #5/#6. Listed here for completeness but recommended to defer (see Wave 7 / outstanding questions). |

---

## Wave 1 — Unlocked by Wave 0

| Issue | What | Blocked by |
|---|---|---|
| **#32** | Per-day candidate spec object | #31 (native GitHub "blocked by" set) |
| **#33** | Locked UI tabs (greyed-out + inert shortcuts) | #31 (native GitHub "blocked by" set) |
| **#38** | Dual-track scoring + `GameState.alignment` | #35 |
| **#4 (implementation)** | Tool-cost inflation + HD$ reward decay in code | The Wave 0 decision landing |
| **#17** | Candidate volume scaling | Soft dependency — needs the campaign-length question answered to pick a sensible ramp target (see Outstanding Questions) |

---

## Wave 2 — Unlocked by Waves 0–1

| Issue | What | Blocked by |
|---|---|---|
| **#34** | Overseer narrates tool unlocks | #31 + #3 (native GitHub "blocked by" set) |
| **#36** | Overseer-Variable rule broadcast in briefing | #35 + #3 |

**#2 closes out at the end of this wave** — all four sub-issues (#31, #32, #33, #34) done.

---

## Wave 3 — Tutorial content (needs #2 fully done)

| Issue | What | Blocked by |
|---|---|---|
| **#43–#47** | #15's five Day 1–5 teaching scripts | #2 complete (the whole premise is gating tools/violations by day) |
| **#49** | Per-day rule sheet JSON + Reference panel | #48 (word banks) + should be authored in step with #15's day-by-day structure |

**#15 and #16 close out at the end of this wave.**

---

## Wave 4 — Campaign arc begins

| Issue | What | Blocked by |
|---|---|---|
| **#39** | Days 5–7 content (Dark Web profiles appear) | #15's graduation beat (Day 5 hand-off point) |
| **#37** | Dark Web directives DW-01–DW-04 (content) | #35 |

---

## Wave 5 — Corruption arc + pivot

| Issue | What | Blocked by |
|---|---|---|
| **#40** | Days 8–11 content (corruption arc, DW-01–04 introduced) | #37 + #39 |
| **#41** | Day ~12 — White Hat Hacker scripted appearance | #40 + #38 (alignment scoring must exist to register the pivot) |

---

## Wave 6 — Finale

| Issue | What | Blocked by |
|---|---|---|
| **#42** | Days 13+ — climax, three endings | #41 |

**#5 and #6 close out here. #14 (epic) is complete once #1, #2, #4, #5, #6, #15, #16 are all done** — that's the full "progressive, taught, scaling campaign" definition of done.

---

## Wave 7 — Optional / anytime

| Issue | What | Notes |
|---|---|---|
| **#7** | Endless mode | No hard dependency on the campaign arc — could move as early as Wave 1 if Nick wants a change of pace. Recommended default: after the main campaign ships, since it's explicitly a secondary mode. |

## Deferred (not sequenced)

| Issue | What | Notes |
|---|---|---|
| **#11** | Web renderer (Flask dashboard) | Explicitly v2 per CLAUDE.md roadmap. Not sequenced into the waves above. |

---

## Critical path (longest dependency chain)

```
#31 → #33/#32 → #34 → (#2 done) → #43-47 (#15) → #39 → #37 → #40 → #41 → #42 → (#6, #5, #14 done)
```

Everything else (Wave 0's #1/#3/#9/#35/#48, Wave 1's #38/#4/#17) can be worked off this critical path in parallel without slowing the campaign arc down.

---

## Outstanding questions

These are decisions only Nick can make — code work is either blocked on them or would be guesswork without them.

1. **#4 curve verification** — proposed `max(6, 10 - floor(day/5))` (admit) / `max(2, 4 - floor(day/10))` (deny), posted as a comment on #4. Needs a sign-off or adjustment.
2. **#9 retitle** — OK to narrow #9's title/acceptance criteria to Ghostscan-only, since Logwatch and Hashcrack are already done? (Comment posted on #9 proposing this.)
3. **#25 HackDox Credits starting balance** — the issue spec said 3 starting slots; shipped code starts at 1 with a purchasable cap up to `HACKDOX_CREDIT_MAX`. Intentional design change, or should it be fixed to match the original spec?
4. **Campaign length (N)** — how many total days should the campaign run? Affects #16's rule-sheet authoring scope, #17's candidate-volume ramp target, and #42's climax pacing. The #4 curve's floor timing (~day 20–24) assumed roughly a 20-day campaign as a starting guess.
5. **#7 Endless mode timing** — sequence it as an early parallel task (change of pace from campaign content), or fully defer until after the campaign ships?
