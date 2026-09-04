# HackDox — Sprint Roadmap

_Compiled 2026-08-15. Live board state verified against `HackDox Feature Planning` (project 2) and the open-issue set on hobbes144/HackDox. Supersedes the sequencing in `BUILD_PLAN.md` (2026-08-02), whose dependency analysis is still accurate — only #1 has closed since._

This document choreographs the **backlog-sprint tool**, which runs whatever sits in the board's **Ready** column end to end. Each "Batch" below is one Ready-column loadout. Work a batch, let the tool close it out, then stage the next batch into Ready.

---

## Current board snapshot (2026-08-15)

| Column | Issues |
|---|---|
| **Ready** | #2, #4, #31, #32, #33, #34 |
| **Hold** | #3 |
| **Todo** | #5, #6, #7, #9, #11, #14, #15, #16, #17, #35–#49 |
| **In progress / Done** | (empty) |

Open: 31 · Closed: 18. Engine foundation (#18–#30) and the Day 1 playtest (#1) are done.

**Two problems with running Ready as it stands:**

1. **#34 needs #3, which is frozen in Hold.** #34 ("Overseer narrates each tool unlock") renders through the TypewriterLog widget (#3). #3 also feeds #15 and #16. It needs to be thawed before #34 can build.
2. **#2 is the epic, not a work item** — it auto-closes when #31–#34 close. Leave it in Ready as the umbrella; the tool won't write code for it.

Decisions locked this session: Batch 1 includes #3 and closes epic #2 · #4's HD$ decay formula signed off · campaign length ≈ 20 days.

---

## The epics (what "done" means)

| Epic | Closes when | Delivered in |
|---|---|---|
| **#2** Progressive unlock model | #31, #32, #33, #34 done | Batch 1 |
| **#16** Daily rule sheets | #48, #49 done | Batch 3 |
| **#15** Tutorial & onboarding | #43–#47 done | Batch 4 |
| **#5** Rule mutation engine | #35, #36, #37 done | Batch 5 |
| **#6** Campaign days arc | #39, #40, #41, #42 done | Batch 7 |
| **#14** Progression & difficulty ramp (top epic) | #1✓, #2, #4, #5, #6, #15, #16 done | Batch 7 |

---

## The batches (dependency-ordered)

### Batch 1 — Unlock epic + typewriter widget
**Issues:** #3, #31, #32, #33, #34 → closes **#2**
**Board prep:** move #3 Hold → Ready. Leave #2 in Ready as the umbrella. Move #4 → Todo for now (it goes in Batch 2, not here).
**Build order (hard):** **#31 first** (`GameState.unlocked_tools` + evidence-tier gate — the foundation; #32/#33/#34 are all `blocked_by #31`) → then #32 (per-day candidate spec), #33 (locked UI tabs), #3 (TypewriterLog) in any order → **#34 last** (needs both #31 and #3).
**Why first:** self-contained, all game-engine/ui, no content authoring, unblocks the whole progressive-disclosure premise everything downstream assumes.
**Decision gate:** #25 — HackDox Credits starting balance shipped as 1-with-purchasable-cap, but the original spec said 3. Confirm "keep as shipped" or "revert to 3" (touches the unlock economy this batch lives in).

### Batch 2 — Rules/scoring engine + economy
**Issues:** #35, #38, #4, #17 (+ #36 if #3 landed in Batch 1)
- **#35** `Rule.mutability` field + per-day ruleset loading (foundation for the mutation engine)
- **#38** Dual-track scoring + `GameState.alignment` (needed before the White-Hat pivot registers)
- **#4** Difficulty curve — HD$ decay (formula below), tool-cost inflation, detection-complexity mix
- **#17** Candidate volume scaling — ramp target set by the ~20-day length
- **#36** Overseer-Variable rule broadcast in briefing — needs #35 + #3
**Why here:** pure engine/config, mostly independent of each other, all unblocked once Batch 1's widget exists. Establishes the economy + alignment + rule-mutability the campaign content later leans on.
**Signed-off formula (#4):**
```
HACKDOLLAR_PER_CORRECT_ADMIT(day) = max(6, 10 - floor(day / 5))
HACKDOLLAR_PER_CORRECT_DENY(day)  = max(2, 4  - floor(day / 10))
# Board-accuracy bonus + EOD health bonus stay FLAT (already skill-scored).
# Tool-cost inflation: base_cost + floor(day / 4), applied AFTER #23's toolcost_<tool> upgrade reduction.
```
**Cleanup:** #4's acceptance criteria still quote the obsolete ⏱ formula `max(8, 15 - floor(day/3))` — rewrite to the above (⏱ verdict rewards were removed by #27).
**Split option:** if this feels large, run 2a = {#35, #38, #4} (engine) then 2b = {#17, #36} (scaling + briefing).

### Batch 3 — Content-data foundation
**Issues:** #48, #9, #49 → closes **#16**
- **#48** Word banks — `DOMAINS_TRUSTED` / `AFFILIATIONS_FAKED` (pure data)
- **#9** Ghostscan shared day dataset (Logwatch/Hashcrack halves already done — retitle to Ghostscan-only)
- **#49** Per-day rule-sheet JSON + Reference panel (needs #48; author in step with the Day 1–5 structure)
**Decision gate:** #9 retitle/narrow to Ghostscan-only — confirm.

### Batch 4 — Tutorial, Days 1–5
**Issues:** #43, #44, #45, #46, #47 → closes **#15**
Day 1 dossier/economy · Day 2 Ghostscan · Day 3 Hashcrack · Day 4 Logwatch · Day 5 Stegotool + graduation beat.
**Depends on:** Batch 1 (#2 unlock model — the whole premise gates tools by day) + Batch 3 (#48/#49). `floor(day/5)=0` for Days 1–4, so the difficulty curve leaves the tutorial flat-easy by design.

### Batch 5 — Campaign arc I, Days 5–7
**Issues:** #37, #39 (+ #36 if deferred from Batch 2)
- **#37** Dark Web directives DW-01–DW-04 (content) — needs #35
- **#39** Days 5–7 — Dark Web profiles appear, Overseer starts pushing compliance — needs #15's graduation hand-off

### Batch 6 — Corruption arc, Days 8–12
**Issues:** #40, #41
- **#40** Days 8–11 — corruption arc, DW-01–04 introduced — needs #37 + #39
- **#41** Day ~12 — White Hat scripted appearance + alignment choice — needs #40 + #38 (alignment scoring)

### Batch 7 — Finale, Days 13+
**Issues:** #42 → closes **#5, #6, #14**
- **#42** Climax + three endings — needs #41

### Batch 8 — Optional / deferred
- **#7** Endless mode — no hard dependency; could jump to any point as a change of pace. Default: after the campaign ships.
- **#11** Web renderer (Flask) — explicitly v2 per CLAUDE.md. Not sequenced.

---

## Critical path

```
#31 → #33/#32/#3 → #34  ( #2 done )
        → #35 → #37 → #39 → #40 → #41 → #42  ( #5, #6, #14 done )
Tutorial branch: ( #2 done ) + #48/#49 → #43–47  ( #15, #16 done )
```

Everything off that spine — #4, #9, #17, #38, #48 — runs in parallel without slowing the campaign arc.

---

## Decisions still open (surface before the batch that needs them)

| # | Decision | Needed by | Recommendation |
|---|---|---|---|
| #25 | Credits starting balance: keep shipped (1 + cap) or revert to spec (3)? | Batch 1 | Keep as shipped unless playtest says otherwise |
| #9 | Retitle/narrow to Ghostscan-only? | Batch 3 | Yes — the other halves are done |
| #4 | HD$ decay formula | **Signed off** (Batch 2) | ✅ locked this session |
| N | Campaign length | **≈ 20 days** | ✅ locked this session |
| #7 | Endless-mode timing | Batch 8 | Defer until after campaign ships |

---

## Suggested cadence

Batches 1–3 are the foundation and can move quickly (engine + data, little authoring). Batches 4–7 are content-heavy — pace those by how fast you can write/playtest the day scripts. Re-run the Day 1 vertical slice (#1's territory) after Batch 2 lands to sanity-check the new economy numbers before committing to the content arc.
