# BUILD PLAN — Batch 2: Difficulty Curve & Replayability

**Scope:** issues #35, #38, #4, #17, #36 (HackDox Feature Planning → Ready)
**Date:** 2026-08-16
**Base branch:** `batch-2-difficulty-curve-replayablity` @ `6904822` ("Tweaks"), working tree clean
**Verification basis:** every file path, function name, constant and line number below was read from the working tree at `6904822`, not inferred from CLAUDE.md or the issue bodies. Baseline test state confirmed green before planning: **32/32 pass** (`gameengine/tests`, pytest, cloud copy).

---

## TL;DR

| Issue | What it actually is, after reading the code | Touches content? | Est. |
|---|---|---|---|
| **#35** Rule.mutability + per-day ruleset loading | Half of it is **already done**. Rules already reload per shift. Real work = one dataclass field + one loader line + a test that pins the reload behaviour. | loader + day JSON | S |
| **#38** Dual-track scoring / GameState.alignment | **Mostly already shipped** and never closed. `alignment` exists, persists, clamps, renders in 4 places; moral modifiers are already exactly Dark Web −1 / White Hat +1. Real work = split the two tracks so they are *separately recorded*, plus the tests the AC asks for. | no | S |
| **#4** Difficulty curve | Real engineering. Reward decay (HD$ reframe), tool-cost inflation, and giving `difficulty_band` actual teeth — it is currently a **dead field**. | config + generator + EOD UI | L |
| **#17** Candidate volume scaling | Medium. `Day.candidate_count` already drives the loop; the curve, the quota scaling and the JSON-optional fallback are new. | config + loader | M |
| **#36** Overseer-Variable rule broadcast | Real engineering, and the **only issue in the batch that cannot be demonstrated at all today** — see the blocker below. | briefing UI + rules engine | M |

**Two issues are substantially already built** (#35's reload half, most of #38). I am not going to pad them into fake work — I will implement the genuinely-missing piece, write the tests their acceptance criteria demand, and say plainly in the commit what was already there.

---

## The blocker that shapes the whole batch

**`content/days/` contains exactly one file: `day_01.json`.**

`content_loader.load_day(n)` (`gameengine/core/content_loader.py:24-25`) reads `day_{n:02d}.json` and raises `FileNotFoundError` for anything else. `HackDoxApp.advance_day` (`gameengine/ui/tui/app.py:3067-3072`) catches that and pushes `CampaignEndScreen`. **The campaign therefore ends after Day 1 today.**

Four of the five issues in this batch are functions of the day number:

- #17's candidate curve has nothing to scale across.
- #4's reward decay and cost inflation never move off their day-1 values.
- #36 diffs today's ruleset against *yesterday's* — with one day file there is no yesterday, ever.
- #35's "reloads the ruleset each shift" is untestable past shift one.

Authoring literal `day_02.json … day_20.json` is issues #39/#40/#41/#6 — a different batch, and content work Nick should write, not me. So the batch needs a **procedural day fallback**: when `day_NN.json` is absent and `N <= CAMPAIGN_LAST_DAY`, synthesize a `Day` from the config curves instead of ending the campaign. An authored JSON file always wins where one exists.

This is not scope creep bolted on — it is the thing that turns all four levers from dead constants into observable behaviour, and it is exactly the "variation and replayability" foundation this batch is supposed to be. **It is also the one decision I should not make alone** — see Open Question 1.

---

## Dependency order

```
#17 (candidate curve)  ─┐
                        ├─→ procedural day synthesis ─→ #36 (needs a "yesterday")
#4  (bands + costs)    ─┘                          └─→ #35's reload test has real days
#35 (mutability field) ────────────────────────────→ #36 (needs mutability to filter on)
#38 (dual-track)       ──── independent, can land anywhere
```

Non-obvious constraints:

1. **#35 must precede #36.** #36 broadcasts only rules whose `mutability != fixed`. Without the field there is nothing to filter and the broadcast would either fire on every rule (a diff dump, which the AC explicitly forbids) or on none.
2. **#17 must precede #4's detection-complexity lever.** The band-driven archetype mix is only meaningful once the day's candidate count is a function of the day; otherwise a "hard" mix is being applied to a fixed 6-slot day.
3. **#4's tool-cost inflation must apply *after* #23's `toolcost_*` upgrade reduction** — otherwise late-game inflation silently erases a 45 HD$ purchase. `tools_bridge.tool_cost()` (`core/tools_bridge.py:47-54`) applies the reduction today; the day term is added after the `max(1, ...)` floor.
4. **#38 is independent** and can be committed first as a low-risk warm-up.

Build order: **#35 → #17 → #4 → #36 → #38** (with the day-synthesis fallback landing inside #17, where the curve it depends on is defined).

---

## Phase 1 — #35: `Rule.mutability` + per-day ruleset loading

### What the issue asks for vs. what exists

> "rules_engine.py loads the active ruleset from content/days/day_N.json fresh each shift, rather than assuming a static Day-1-style ruleset for the whole campaign."

**This is already true.** `rules_engine.evaluate(candidate, day)` (`core/rules_engine.py:99`) is a pure function that takes the `Day` as an argument — it holds no ruleset state at all. `HackDoxApp.advance_day` calls `load_day(st.current_day)` fresh on every day advance (`ui/tui/app.py:3068`), and `start_new_game` does the same at `:2997`. There is no cached or static ruleset anywhere to remove.

What is genuinely missing is the `mutability` field, and a **test that pins the reload behaviour** so a future refactor cannot quietly reintroduce a cached ruleset.

### Implementation

- `core/models.py` — add `RuleMutability = Literal["fixed", "overseer_variable", "dark_web"]` next to the existing `RuleSeverity` alias (`models.py:122`), and `mutability: RuleMutability = "fixed"` to `Rule` (`models.py:230-241`). Defaulting to `"fixed"` is what makes this a no-op for Day 1's 14 rules.
- `core/content_loader.py:27-35` — `mutability=r.get("mutability", "fixed")` inside the existing `Rule(...)` construction. Same optional-key pattern `severity` already uses at `:32`.
- Validate the value on load and raise on an unknown string, matching `rules_engine.resolve()`'s fail-loud stance (`rules_engine.py:80`) — a typo in day JSON must not silently become `"fixed"`.

### Acceptance criteria

- [ ] `Rule.mutability` exists with the three states, defaulting to `fixed`
- [ ] `content_loader` round-trips `mutability` from day JSON; unknown values raise
- [ ] Day 1's existing 14 rules all load as `fixed` — zero behaviour change
- [ ] Test: a rule's `mutability` survives a `day_N.json` round-trip
- [ ] Test: `rules_engine` evaluates against the *passed* Day, and advancing the day swaps the active ruleset (pins the already-correct reload behaviour)

---

## Phase 2 — #17: candidate volume scaling

### Current state

`Day.candidate_count` (`core/models.py:276`) is a **required** JSON key (`content_loader.py:62`, `raw["candidate_count"]`) and already drives every consumer:

- the intake loop's end-of-day check — `ui/tui/app.py:2135`
- the status header's `[n/total]` — `app.py:422`
- the headless simulate command — `hackdox.py:92`
- **the shared day-log builders** — `tools_bridge.generate_hashcrack_day_log` (`:771`) and `generate_day_log` (`:1260`) both iterate `range(day.candidate_count)` to plant per-candidate entries in the shared logs

`config.DEFAULT_CANDIDATES_PER_DAY = 6` (`config.py:206`) is **dead code — defined and never read anywhere in the package.**

### Implementation

**Curve** (`config.py`, replacing the dead constant):

```python
TUTORIAL_LAST_DAY        = 5    # days 1-5 stay flat-easy (#15)
CANDIDATE_COUNT_TUTORIAL = 6
CANDIDATE_COUNT_BASE     = 6
CANDIDATE_COUNT_GROWTH   = 0.5  # +1 candidate every 2 days after the tutorial
CANDIDATE_COUNT_CAP      = 12

def DAY_CANDIDATE_COUNT(day_number: int) -> int: ...
```

Yielding 6/6/6/6/6 · 7 7 8 8 9 9 10 10 11 11 12 (cap from day 16) across a 20-day campaign.

**JSON becomes optional:** `content_loader` switches to `raw.get("candidate_count") or config.DAY_CANDIDATE_COUNT(raw["number"])`. `day_01.json`'s explicit `6` still wins, so **Day 1 is byte-for-byte unchanged**.

**Quota scaling** (#17 AC 5 / issue #12): `Quotas.min_correct_admits` is a flat JSON number (`2` on Day 1 of 6 candidates ≈ ⅓). Scale it as `max(json_value, round(count * QUOTA_ADMIT_RATIO))` with `QUOTA_ADMIT_RATIO = 0.34` — Day 1 evaluates to `round(2.04) = 2`, i.e. **unchanged**, and a 12-candidate day asks for 4. `max_false_admits` stays flat at 1: scaling it *up* with volume would make late shifts more forgiving, which is backwards for a difficulty ramp.

**Procedural day synthesis** (the blocker above) lands here: `content_loader.synthesize_day(n)` builds a `Day` from the curves when no JSON exists and `n <= config.CAMPAIGN_LAST_DAY` (20, per the locked campaign-length decision), inheriting Day 1's rule list. Beyond the last day it raises `FileNotFoundError` as today, so `CampaignEndScreen` still fires — the campaign gains an ending instead of losing one.

**Terminology fix** (issue comment): the issue body says "more chances to lose a life". Lives were removed in #19/#24; the wording becomes "take Site Health damage".

### Acceptance criteria

- [ ] `config.DAY_CANDIDATE_COUNT(day)` exists; no magic candidate counts in the day loop
- [ ] `candidate_count` optional in day JSON, falling back to the curve; `day_01.json` unchanged at 6
- [ ] Days 1–5 flat; ramp begins after graduation; cap respected
- [ ] Quotas scale with count, and Day 1's quota is numerically unchanged
- [ ] Deterministic: same seed + day → same candidate set *and order* (regression-guard on `_pick_archetype_for_slot`'s day-scoped bag)
- [ ] A representative late day (16, 12 candidates) is completable — balance pass recorded in the shipped log

---

## Phase 3 — #4: difficulty curve

### The stale acceptance criterion

The issue's first AC — `max(8, 15 - floor(day / 3))` ⏱ per correct verdict — **is obsolete and will be rewritten, not implemented.** #27 (shipped in `305e65f`) made verdicts grant **zero** ⏱; `scoring.apply()` does not touch `state.compute_hours` at all (`core/scoring.py:146-149`). Nick's own two comments on the issue already flag this and propose the HD$ reframe, which is a locked decision.

### Lever 1 — reward decay (HD$)

`config.HACKDOLLAR_PER_CORRECT_ADMIT = 10` / `_DENY = 4` (`config.py:92-93`) become day-parameterised helpers:

```python
def HACKDOLLAR_PER_CORRECT_ADMIT(day) -> int:  # max(6, 10 - day // 5)
def HACKDOLLAR_PER_CORRECT_DENY(day)  -> int:  # max(2,  4 - day // 10)
```

`floor(day/5)` is 0 for days 1–4, so the tutorial is untouched. Both curves bottom out around day 20–24, matching #6's climax window. **Board-accuracy bonus and EOD health bonus stay flat** — they are already skill-scored; decaying them too would double-penalise.

Consumer: `scoring.score()` (`scoring.py:107-112`) currently reads the bare constants. It needs the day number. `score()` takes `(candidate, player_verdict, player_flags)` and `apply()` takes `state`, which already carries `current_day` — so **`score()` gains an explicit `day_number: int` parameter and `apply()` passes `state.current_day`**. Explicit beats reaching into `state` from a pure function.

### Lever 2 — tool cost inflation

`tools_bridge.tool_cost(state, tool_name)` (`:47-54`) applies the `toolcost_*` upgrade reduction and floors at 1. The day term is added **after** that floor, so a purchased upgrade is never erased:

```python
base = config.TOOL_COSTS[tool_name]
if f"toolcost_{tool_name}" in state.upgrades:
    base = max(1, base - config.TOOLCOST_REDUCTION)
return base + config.tool_cost_inflation(state.current_day)   # + day // 4
```

`state.current_day` is already on `GameState` (`models.py:336`), so **no call-site signature changes** — `_charge()` (`:57`) and every runner pick it up for free.

Two deliberate judgement calls, both worth arguing with:

- **Filter costs do NOT inflate.** The GDD wants players pushed *into* filters as the campaign tightens ("filter-avoidance correlates with lower accuracy"). Inflating the base only makes the filter relatively cheaper over time, which pushes the right way. Inflating both would push against the design.
- **Stego stamp cost does NOT inflate.** `STEGO_GRID_GROWTH_*` (`config.py:200-202`) already grows the image per day, so the *number* of stamps needed to hit `STEGO_STAMP_RESOLVE_COVERAGE` rises on its own. Inflating the per-stamp cost on top would compound quadratically.

### Lever 3 — detection complexity

`Day.difficulty_band` is currently a **dead field** — set by the loader (`content_loader.py:52`), stored on the model (`models.py:295`), asserted once in a test, and **read by no game logic anywhere.** This is where it gets teeth, via two sub-levers:

**(a) Archetype mix.** `config.day_archetype_mix(day, count)` produces a band-appropriate mix for procedurally-synthesized days — easy days weighted to Obvious Admit / Day-to-Day, hard days shifting toward Sneaky Bugger and Bad Actor. Authored day JSON always overrides.

**(b) Discrepancy tier bias.** `candidate_gen._roll_discrepancies()`'s `take()` helper (`:610-628`) currently fills each severity slot with the first shuffled eligible kind of that severity. On a `hard` band, the eligible list is **stably sorted so tool-revealed kinds precede dossier-revealed ones** — so a hard-day Clumsy Cutie's minor slot preferentially plants something needing Logwatch rather than something readable free off the dossier. Determinism is preserved: a stable sort of an already-seeded shuffle is still a pure function of the seed.

### Lever 4 — surfacing it

#4's AC asks the end-of-day screen to show the payout rate and next shift's tool costs. `BetweenDayScreen._report_text()` (`app.py:2780-2828`) already shows `next_budget` in exactly this "what next shift looks like" register — the decay rate and inflated costs join it there. `EODScreen` (`:2638`) gets the current payout rate alongside its existing HD$ line.

### Acceptance criteria

- [ ] Issue body's obsolete ⏱ decay AC rewritten to the HD$ reframe
- [ ] `HACKDOLLAR_PER_CORRECT_ADMIT(day)` / `_DENY(day)`; days 1–4 pay the current flat rate
- [ ] Tool cost inflation `+ day // 4`, applied *after* the upgrade reduction — test proves a purchased upgrade still saves ⏱ at day 20
- [ ] Filter and stamp costs deliberately uninflated, with the reasoning in a code comment
- [ ] `difficulty_band` drives archetype mix and discrepancy-tier bias; generation stays seed-deterministic
- [ ] Between-day report shows next shift's payout rate and tool costs
- [ ] Test: reward decay floors; test: cost inflation ordering; test: hard band biases toward tool-revealed kinds

---

## Phase 4 — #36: Overseer-Variable rule broadcast

### Stale references

The issue refs `gameengine/core/overseer.py` and `gameengine/core/day_cycle.py`. **Neither file exists** — CLAUDE.md's directory tree lists them aspirationally. The briefing lives in `BriefingScreen` (`ui/tui/app.py:1778-1835`), and the day cycle is orchestrated by `HackDoxApp`'s `start_new_game` / `begin_intake` / `finish_day` / `show_between_day` / `advance_day` methods (`:2985-3076`).

**#3 has already shipped**, so the issue's "plain Static is an acceptable placeholder" escape hatch is unnecessary — `TypewriterLog` is live and `_play_overseer()` (`:1750-1762`) is the exact posting helper this needs.

### Implementation

**Diff layer** — `rules_engine.diff_rulesets(prev: Day | None, cur: Day) -> tuple[RuleChange, ...]`, a pure function returning `added` / `removed` / `severity_changed` records, **filtered to `mutability != "fixed"`**. A `None` previous day (day 1) returns empty — nothing has changed yet on the first shift.

**Phrasing layer** — `RULE_CHANGE_PHRASINGS` in the UI layer, keyed by change kind, deliberately understated per the AC's "casual, not a klaxon":

> *"Oh — before I forget. Legal's decided the after-hours thing is a note now, not a bar. Don't overthink it."*

rather than `severity: disqualifying → weighted`. Multiple changes get varied openers so a two-change day doesn't read as a template.

**Wiring** — `BriefingScreen` gains a `prev_day` argument. `advance_day` (`:3059-3068`) already holds `self._day` (yesterday) at the moment it loads today's, so passing it through is a two-line change. The broadcast lines post *after* the day's intro beat and *before* the tool-unlock line, so a day that both unlocks a tool and flips a rule reads in the right order. It reuses the `_play_overseer` / `.post()` pattern that `_UNLOCK_LINES` already established at `:1811-1815`.

**Content:** procedurally-synthesized days flip one `overseer_variable` rule on a seeded cadence, so the mechanic is observable immediately rather than waiting on #39/#40/#41.

### Acceptance criteria

- [ ] A line is generated for every Overseer-Variable rule that changed from the prior day
- [ ] No line for unchanged rules, and none for `fixed` rules even when they change
- [ ] Day 1 broadcasts nothing (no prior day)
- [ ] Tone reads as in-fiction and casual, not a diff dump
- [ ] Delivered through `TypewriterLog`, ordered after the intro beat and before any unlock line
- [ ] Test: diff filters by mutability; test: briefing posts one line per changed variable rule

---

## Phase 5 — #38: dual-track scoring

### What is already shipped (and never closed out)

Reading the code against the four acceptance criteria:

| AC | Status |
|---|---|
| `GameState.alignment` added, persisted | **Done.** `models.py:339`; saved `persistence.py:18`, loaded `:41`; clamped to ±10 in `scoring.apply()` `:150-153` |
| Dark Web / White Hat verdicts shift alignment; others do not | **Done.** Verified by running the generator: `moral_modifier` is `-1` for `dark_web`, `+1` for `white_hat`, and **`0` for all seven others** — `scoring.score()` `:115-118` gates the delta on `moral != 0` |
| Literal-ruleset scoring unaffected by alignment tracking | **Done.** `hackdollars` and `site_health` are computed in separate branches that never read `alignment` |
| Foundation test for the core tension | **Missing.** No test asserts it |

Alignment is also already rendered in four places: the status header (`app.py:403`), the verdict toast (`:2229-2231`), EOD (`:2664`, `:2675`) and the between-day report (`:2800-2810`).

### What is genuinely missing

The **two tracks are not separately recorded.** `CandidateResult.correct` (`models.py:307`) is a single boolean derived from `truth.correct_verdict`. For the Dark Web archetype those two tracks happen to coincide today — Dark Web is `correct_verdict=ADMIT` with `budget=DiscrepancyBudget()` and `eligible_kinds=()`, so it trips no rules and admitting it is both rules-correct and morally compromising. That is the intended tension, and it works — **but it works by coincidence of the data, not because the engine models two tracks.** The moment #5's Dark-Web-Mutated directives (#37) make a rule that *permits* something the ground truth condemns, a single `correct` boolean cannot express the disagreement.

So Phase 5 makes the split explicit and testable:

- `ScoreDelta` / `CandidateResult` gain `rules_verdict: Verdict` — what the **literal active ruleset** says (DENY iff `rules_engine.evaluate()` returns any disqualifying trigger), recorded alongside the existing moral `correct`.
- `scoring.apply()` takes the `RuleEvaluation` so the literal track is recorded from the actual day rules rather than re-derived.
- `CandidateResult.rules_correct` — whether the player matched the *ruleset*, distinct from matching *ground truth*. The economy stays keyed off `correct` exactly as today: **zero payout change.**
- The between-day report gains a "by the book / by conscience" divergence count when the two tracks disagree — the corruption arc's readout.

### Acceptance criteria

- [ ] `rules_verdict` / `rules_correct` recorded per candidate, separate from moral `correct`
- [ ] HD$ and Site Health payouts numerically identical to pre-change for every archetype (regression test)
- [ ] Test: admitting a Dark Web candidate under a ruleset that permits it is `rules_correct=True` **and** shifts alignment
- [ ] Test: the seven non-alignment archetypes never move alignment
- [ ] Test: alignment persists and clamps at ±10

---

## Cross-cutting risks

- **`candidate_gen.py` merge hazard.** Per project memory, `batch-1-progressive-unlock` was branched from `3bbb465` and does **not** include main's `b533dfb "Candidate Generation Anomalies"`, which also edits `candidate_gen.py`. Phase 3 edits `_roll_discrepancies` in the same file. Reconcile on merge to main.
- **Shared day-log cost scales with candidate count.** `generate_day_log` and `generate_hashcrack_day_log` iterate `day.candidate_count` *and* `config.LW_ENTRIES_BY_DAY[day]` (up to 240+ noise entries). At 12 candidates on a late day both grow together; both are built once in `IntakeScreen.on_mount` (`app.py:2009-2010`). Worth timing, not worth pre-optimising.
- **Determinism is the thing most likely to break.** Phases 2 and 3 both touch generation. Every change must stay a pure function of `(seed, day, slot)` — `candidate_gen.stable_hash` exists precisely because builtin `hash()` broke this before (2026-07-18). Same-seed regression assertions go in every generation-touching commit.
- **Day 1 must not move.** `day_01.json`'s explicit `candidate_count`, quotas and 14 `fixed` rules are the tutorial baseline. Every phase above is designed so Day 1 output is byte-identical; the existing 32 tests are the guard.
- **Windows-mount truncation.** Known repo hazard. Every edited file gets a line-count + tail check before commit.

---

## Open questions

**1. Procedural day fallback — build it, or leave the campaign ending at Day 1?**
*Recommendation: build it.* Without it, four of this batch's five issues ship as constants nobody can observe, and #36 cannot be demonstrated at all. It is also the direct answer to "the basis for a lot of the game's variation and replayability."

**2. What does an Overseer-Variable rule actually vary?**
*Recommendation: severity flips only for now* (disqualifying ↔ weighted). It reuses `rules_engine`'s existing severity branch (`:109-112`) with no new machinery, it is the "small process update" register the AC asks for, and rules entering/leaving the set is the louder change that #37's Dark Web directives should own.

**3. Should `difficulty_band` drive the archetype mix procedurally, or stay authored per-day?**
*Recommendation: config-driven with JSON override.* Authored days win where they exist; synthesized days get a band-appropriate mix. Nick keeps full authorial control without needing to write 20 files before the lever works.

**4. Campaign length for the synthesis ceiling — confirm 20 days?**
Project memory records "campaign length ≈ 20 days" as locked. Confirming, because it becomes a hard constant (`CAMPAIGN_LAST_DAY`) that the curves' floors and caps are tuned against.

**5. Should tool-cost inflation apply to filter costs too?**
*Recommendation: no* — see the reasoning in Phase 3. Flagging it because the issue text says "per use" without distinguishing, and it is a real design fork rather than an implementation detail.

---

# SHIPPED — 2026-08-16

Branch `batch-2-difficulty-curve-replayablity`, based on `6904822`. **Not pushed.**

| Issue | Commit | Title |
|---|---|---|
| #35 | `b92852f` | Add Rule.mutability and pin the per-shift ruleset reload |
| #17 | `b742051` | Scale candidate volume by day and synthesize days past authored content |
| #4  | `63b073a` | Land the three difficulty levers: reward decay, cost inflation, detection complexity |
| #36 | `bc61bff` | Broadcast Overseer-Variable rule changes in the morning briefing |
| #38 | `de0e7c3` | Record the literal-ruleset and moral scoring tracks separately |

## Decisions taken (Nick, 2026-08-16)

All five gate questions answered with the recommended option:

1. **Procedural day fallback — build it.** `content_loader.synthesize_day` covers days 2–20 when no `day_NN.json` exists; authored JSON always wins; `CAMPAIGN_LAST_DAY + 1` still raises `FileNotFoundError` → `CampaignEndScreen`.
2. **Overseer-Variable = severity flips only.** disqualifying ↔ weighted. Rules entering/leaving the set stays scoped to #37's Dark Web directives.
3. **`difficulty_band` drives the archetype mix from config, JSON overrides.** `ARCHETYPE_MIX_BY_BAND` applies to synthesized days only.
4. **Campaign length confirmed at 20 days** — now the hard constant `config.CAMPAIGN_LAST_DAY`.
5. **Filter costs and stego stamp cost do not inflate.** Base tool costs only.

## Where the curve landed

| Day | Candidates | Band | Correct admit | Correct deny | Ghostscan ⏱ | ⏱ budget |
|---:|---:|---|---:|---:|---:|---:|
| 1  | 6  | easy   | 10 HD$ | 4 HD$ | 5  | 60  |
| 5  | 6  | easy   | 9      | 4     | 6  | 76  |
| 10 | 9  | medium | 8      | 3     | 7  | 96  |
| 16 | 12 | hard   | 7      | 3     | 9  | 120 |
| 20 | 12 | hard   | 6      | 2     | 10 | 136 |

The per-candidate ⏱ budget stays roughly flat in raw hours (10.0 → 11.3) but falls from **2.0 ghostscans per candidate to 1.1**. That is the squeeze: the workload and the prices rise faster than the pool does.

**Rule-flip cadence** across a campaign run: silent most mornings, one aside on days 3, 6 and 11, two on day 8.

**By-the-book playthrough** (auto-DENY iff a disqualifying rule fires) at seed `0xC0FFEE`:

| Day | Correct | Divergent | HD$ | Site Health | Alignment |
|---:|---|---:|---:|---|---:|
| 1  | 5/6   | 1 | 58 | 94% | 0 |
| 5  | 5/6   | 1 | 40 | 95% | 0 |
| 10 | 6/9   | 3 | 68 | 66% | −1 |
| 16 | 10/12 | 2 | 94 | 52% | −3 |
| 20 | 10/12 | 2 | 80 | 39% | −5 |

A player who follows the rulebook perfectly still drifts to **−5 Dark Web by day 20**, because the rulebook keeps telling them to admit the Dark Web. That is #5's premise working end to end.

## Verification

- **66/66 pytest** in `gameengine/tests` (32 pre-existing + 34 new/rewritten), green after every commit.
- **16/16** on the legacy `run_foundation_tests.py` runner.
- Every touched file byte-compared (md5 + line count) between the tested copy and the working tree before each commit — **no mount truncation in this session**.
- Full-stack headless playthrough across days 1/5/10/16/20 exercising generation → rules → scoring → EOD health.

## Bugs found and fixed en route

- **`scale_archetype_mix` total-preservation.** Writing the test surfaced that the "every archetype keeps a slot" guarantee is unsatisfiable when a shift is shorter than the archetype list. Since `_pick_archetype_for_slot` walks the bag with `bag[pos % len(bag)]`, a mix that doesn't sum to the shift length wraps and the realized mix silently stops matching the declared mix. Fixed by dropping the smallest proportional shares below that threshold rather than weakening the assertion.
- **Hard band had no pacing beats.** The first cut dropped The Professional and The Incompatible, producing twelve consecutive deep investigations. Both are kept and a test pins it.
- **Sentence-initial rule fragments read as lowercase** in two Overseer phrasings. Fixed with a template-shape check rather than post-hoc capitalisation, which would have mangled abbreviations inside rule text.

## Smoke-test checklist for the next play session

- [ ] Day 1 plays exactly as before — 6 candidates, quota 2, no rule broadcast, no "next shift" warnings
- [ ] Day 2 loads (synthesized) rather than ending the campaign
- [ ] Day 3's briefing carries one amber rule-change line, after the intro beat and before the Hashcrack unlock line
- [ ] Between-day report shows "Next shift" with tool costs highlighted on days 3, 7, 11, …
- [ ] A late day (16) is 12 candidates and does not run the ⏱ pool dry at target accuracy
- [ ] Admitting a Dark Web candidate reads "by the book, not by conscience" in the verdict toast

## Deliberately not done

- **Authored day content for days 2–20.** That is #39/#40/#41/#6. Synthesized days are a playable floor, not a substitute — the Overseer's intro/outro keys for those days resolve to generic fallback copy.
- **`dark_web` mutability is reserved but unused.** No generator plants one; that is #37.
- **`RuleChange` kinds "added"/"removed" are implemented and tested but never produced** by the current flip logic, which only changes severity (per decision 2). They are there so #37 doesn't have to reopen the diff layer.

## Open questions

1. ~~Procedural day fallback?~~ **ANSWERED** — build it.
2. ~~What does an Overseer-Variable rule vary?~~ **ANSWERED** — severity flips only.
3. ~~`difficulty_band` config-driven or authored?~~ **ANSWERED** — config-driven, JSON overrides.
4. ~~Campaign length?~~ **ANSWERED** — 20 days.
5. ~~Inflate filter costs?~~ **ANSWERED** — no.

**New, for playtesting rather than code:** the curve numbers above are a first pass. `CANDIDATE_COUNT_GROWTH`, `TOOL_COST_INFLATION_PERIOD`, `HACKDOLLAR_DECAY_*_PERIOD` and `RULE_FLIP_PERIOD` are all single config knobs — retune by feel once a late day is actually played.
