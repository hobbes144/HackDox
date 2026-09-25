# Endless Mode — Build Plan (#7, with #70 and #14)

Drafted 2026-09-25 on branch `Final-Game-Polish` (HEAD `4092f58`). Nothing built yet.
**Status: waiting on Nick's answers to the open questions at the bottom.**

## What Nick asked for

- Endless is the current game, re-cut: same shift loop, same tools, same shop.
- The Foreman is on your side in Endless. She's cooperative and helpful, not manipulative.
- No tutorial and no progressive unlock. Every tool, every violation, every breach
  corpus and the full rulebook are live on shift 1.
- Saves between days, and Continue picks the run back up so it can go on forever.
- Difficulty, scaling and the HD$ economy get retuned so a run is doable but hard,
  and the pieces fit together. Balance work is shared with #70 (the campaign balance
  pass) and #14 (the progression/difficulty-ramp epic).

## What #7 adds on top (issue acceptance criteria)

- [ ] `GameMode.ENDLESS` selectable from the main menu
- [ ] Dark Web archetype never generated in Endless
- [ ] No rule corruption. Overseer-Variable rules still move, but the Foreman explains why.
- [ ] A separate, warm Foreman dialogue bank (not the Campaign one)
- [ ] New loss condition: the rolling 5-day average accuracy has to stay above a configurable threshold
- [ ] The Foreman's tone follows the trend: encouraging when accuracy rises, concerned when it falls
- [ ] Rule changes explained in the briefing: small changes casually, big ones with a reason

> #7's reference to `gameengine/core/day_cycle.py` is out of date. That file doesn't
> exist. The day loop lives in `HackDoxApp` (`ui/tui/app.py`: `start_new_game` →
> `begin_intake` → `finish_day` → `show_between_day` → `advance_day`).

## Audit: what the code does today

### What we can reuse as-is
- `synthesize_day()` already builds a playable day from Day 1's rules plus the config
  curves. Endless is basically "synthesize forever, with different curves and no gates."
- `mutate_variable_rules()` already flips Overseer-Variable severities on a sticky,
  staggered schedule, and `diff_rulesets()` / `rule_change_lines()` already announce
  the changes in the briefing. We only need a new voice for it, not a new mechanism.
- `resolve_aligned_narrative()` already has a fallback chain. An `endless_*` key tier
  can be added in front of it the same way the alignment bands were.
- Saving already happens at both day boundaries (`EODScreen` continue and `advance_day`).
  Continue already goes through `resume_game()`.
- The Site Health loss check (`scoring.health_below_loss`) already runs at the end of
  every day.

### Traps (each one would break Endless if we skipped it)
1. **The day number controls two unrelated things.** `Day.number` / `state.current_day`
   drive both the *unlock gates* and the *difficulty curves*, and they're also part of
   every RNG seed. About 110 call sites read it. The gates are:
   `candidate_gen.intro_day(k) <= day_number` (:1308, :1508, :1976),
   `breach_dbs_unlocked_by` (candidate_gen :951, tools_bridge :297/:308/:734/:989/:1045),
   `stepped_rule_severity`, `kinds_discovered_through`, and `tool_introduced_on` (briefing).
   The curves are: candidate count, band/archetype mix, HD$ payout, tool inflation,
   daily ⏱ budget, stego/cipher grid growth, and Logwatch volume.
   "Everything unlocked on shift 1, difficulty ramps from there" needs those two roles
   split apart.
2. **`load_day(n)` is the campaign.** Days 6–20 are authored JSON. They include Dark Web
   directives (`added_rules`), the scripted White Hat on day 12, and campaign narrative
   keys. Past day 20 it raises `FileNotFoundError`. Endless must never call
   `load_day(n>1)`, and `advance_day`'s `> CAMPAIGN_LAST_DAY → CampaignEndScreen` check
   must not fire in Endless.
3. **Some curves grow without limit** (harmless in a 20-day campaign, fatal in Endless):
   - Logwatch noise: `LW_ENTRIES_BY_DAY[7] * 1.15^(day-7)`, from `tools_bridge.generate_day_log`.
     That's ~730 rows on day 20, ~12,000 on day 40 and ~1.3M on day 75.
   - `tool_cost_inflation = day // 4`: every tool costs +10 ⏱ by day 40.
   - `daily_compute_budget = capacity + 4·(day-1)`: +156 ⏱ by day 40, so the budget
     outruns the inflation.
   - The capacity shop item is a flat 100 HD$ with no cap, so a long run can buy its
     way to unlimited ⏱.
   - The stego and cipher grids *do* have caps (`STEGO_GRID_MAX`, `CIPHER_GRID_MAX`),
     and the HD$ payout has floors. Those are fine.
4. **The tutorial runs by day number.** `BriefingScreen` plays `_UNLOCK_LINES` whenever
   `tool_introduced_on(day.number)` returns a tool, so Endless shifts 2–5 would play
   tutorial unlock lines. `unlocked_tools` starts empty, and `persistence.load()` backfills
   it from `current_day`.
5. **There's no day history.** `GameState.completed_days` is declared but nothing ever
   fills it, and `persistence` doesn't save results. A rolling 5-day accuracy needs a new
   field that gets saved.
6. **Game Over restarts the campaign.** `GameOverScreen.action_restart` calls
   `start_new_game()`.
7. **There's only one save slot.** `config.SAVE_FILE = saves/slot_0.json`, and nothing in
   it records the mode. An Endless save loaded as a campaign would drop you into
   day N's authored campaign content. (See question 1.)
8. **Known caveat, still true:** saving from Pause mid-shift resumes at that day's
   briefing, not mid-shift. That's acceptable for Endless ("save between days" is
   exactly what's supported).

## Proposed architecture

**Two day numbers.** Add two fields to `Day`, both defaulting to `number` so the campaign
doesn't change:
- `gate_day`: what the unlock gates read. In Endless it's pinned to `CAMPAIGN_LAST_DAY`,
  so every tool, kind, breach DB and severity step is at its final state.
- `curve_day`: what the difficulty curves read. In Endless it comes from the shift number
  through a new `config.endless_curve_day(shift)` (see question 2).
- `number` stays the real shift count and keeps seeding the RNG, so every shift is unique.

Every gate call site switches from `day.number` to `day.gate_day`, and every curve call
site to `day.curve_day`. Call sites that only get an `int` are updated at the caller.
Campaign days have `gate_day == curve_day == number`, which is why the campaign stays
byte-identical. That gets locked in with a golden snapshot test (see Phase 1).

**Endless day builder.** New `content_loader.build_endless_day(shift)`. It works like
`synthesize_day`, but it:
- uses the Endless archetype table (no `dark_web`, no `white_hat`)
- keeps Overseer-Variable flips running (keyed on `shift`)
- uses `endless_*` narrative keys
- never touches authored day files

**Game mode.** New `GameMode` enum (`CAMPAIGN`, `ENDLESS`) on `GameState.mode`. It gets
saved, and a save without it loads as campaign. `HackDoxApp` gets a small
`_day_for(state)` switch plus `start_endless_game()`, and each existing flow method
branches on mode where it differs.

**Shift history.** `GameState.shift_history: list[ShiftRecord]` records shift, accuracy,
correct count, total, health delta and HD$ earned. It's saved, and we keep only the last
N entries plus lifetime totals. Rolling accuracy is computed from it in
`scoring.rolling_accuracy(state, window=5)`.

## Phases

| # | Phase | Main files | Size |
|---|---|---|---|
| 0 | **Balance simulator.** Headless scripted players (tool-diligent, dossier-only, sloppy/rushed) run N shifts through the real generator, scoring and economy. Output per shift: ⏱ needed vs. ⏱ available, HD$ in/out, health path, accuracy. One harness serves Endless and #70. Lives next to `sim_pad.py` (or under `hackdox lab`). | new `sim_balance.py` | M |
| 1 | **Split the day number.** Add `Day.gate_day`/`curve_day`, re-route the gate and curve call sites, and cap the Logwatch volume. Guard: a golden snapshot of campaign days 1–20 × several seeds (candidate truth, tool output hash, costs, budgets) taken **before** the change must match exactly **after** it. Revert-check the guard. | models, config, candidate_gen, tools_bridge, content_loader, scoring, briefing, rules_content | M |
| 2 | **Endless day builder and curves.** `build_endless_day`, the `ENDLESS_*` config block, the endless archetype table, `endless_curve_day()`, and bounded versions of inflation, budget and volume. | config, content_loader | M |
| 3 | **Mode, history and saving.** `GameMode`, `shift_history`, a save schema version, backward-compatible loading, and whatever slot layout question 1 decides. | models, persistence, config | S |
| 4 | **Loss conditions and results.** Rolling-accuracy loss with a grace window, Site Health loss per question 3, an Endless Game Over screen (shifts survived, lifetime accuracy, best run), Restart → a new Endless run, and a personal-best record per question 5. | scoring, game_over, app | S–M |
| 5 | **App flow and UI.** Main-menu button goes live. All tools unlocked from shift 1, and the briefing skips the unlock beats. The Evidence Board and Rules page show the full catalog. The status header and EOD show rolling accuracy and its trend. Campaign End never fires. Pause and Continue work in both modes. Update `UI_CATALOG.md`. | intro, app, briefing, eod, status_header | M |
| 6 | **Endless Foreman voice.** `endless_*` keys in `overseer.json` for intro, outro × performance, and between. Trend-aware selector (rising/steady/falling from the rolling window). Cooperative rule-change phrasing: small flips casual, big ones with a reason. Written by the `dockside-voice` agent against `VOICE_GUIDE.md` and checked by `test_voice.py`. | overseer.json, core/overseer.py, _narration.py | M |
| 7 | **Endless economy and tuning.** Shop money sinks per question 4, then tune the curves in the Phase 0 simulator until all three player profiles land where we want them. | config, between_day | M |
| 8 | **#70 campaign balance pass.** Use the same simulator across all 20 days on both alignment paths. Check the AC ("no day makes correct play mathematically impossible on ⏱"). Any config changes get their rationale written up here. #14's difficulty-ramp items are checked off against the same data. | config, this doc | M |

Order: 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8. Phase 6 can run alongside 4–5 since it only
touches content and the narrative resolver. Phase 8 can start as soon as Phase 0 exists
if you want campaign numbers early.

## How it gets verified
- The full suite passes after every phase. Phase 1 must not change a single campaign test.
- The golden campaign snapshot is identical before and after Phase 1.
- A new `test_endless.py` checks:
  - shift 1 has every tool unlocked
  - no Dark Web or White Hat candidates across 200 shifts × seeds
  - no `load_day(n>1)` calls
  - every curve is bounded at shift 500
  - rolling-accuracy loss trips and grace-window edge cases
  - save → load round-trip keeps the mode and history
  - an old campaign save still loads as a campaign
  - Continue resumes Endless in Endless
- Every new guard is checked by reverting the fix in a scratch copy and confirming the test fails.
- A `run_test()` pilot pass covering the menu, starting Endless, playing a shift, Pause,
  Quit, Continue, Game Over and Restart.

## Defaults I'll use unless you say otherwise
- The White Hat is also left out of Endless (#7: "every denied candidate genuinely poses
  a threat"). Alignment is frozen at 0 and never read.
- Rule changes in Endless are severity flips only (the existing mechanism). No rules
  enter or leave the book. The "big change with a reason" beat is a flip on a rule that
  carries a critical violation.
- Accuracy = correct verdicts ÷ candidates judged that shift, using the moral `correct`
  track (same as the economy).
- The rolling-accuracy loss only applies once 5 shifts have been played, so shift 1
  can't end a run.

## Open questions for Nick
1. **Save slot.** Should Endless share `slot_0.json` with the campaign, or get its own slot?
2. **Difficulty shape.** Where does shift 1 start, and does it ever stop getting harder?
3. **Losing.** Rolling accuracy *and* Site Health, or only one of them? What threshold?
4. **Economy once the shop is bought out.** What's HD$ for on shift 40?
5. **Score / personal best.** Track a best run?
6. **#70 scope.** Do the campaign balance pass in this same batch, or after Endless ships?
