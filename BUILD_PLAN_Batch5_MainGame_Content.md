# BUILD PLAN — Batch 5: Main-game content (#37, #39, #40, #41, #42)

**Scope:** the rest of the campaign. Days 6–20, the four Dark Web directives, the
scripted White Hat, and the three endings. Closes #6, and with it the content half
of epic #14.

**Compiled** 2026-09-12.
**Base branch / HEAD — NOT VERIFIED.** The desktop shell (`device_bash`) is down on
`pathfinder` (Plan9 share unmounted after the 2026-09-08 Windows update), so no
`git` command could be run this session. Project memory says Batch 4 left HEAD at
`14c0e8b` on `batch-3-UserFeedback-ContentGeneration`, unpushed. **Confirm with
`git branch --show-current && git log --oneline -3` before building.**

Also unverified and worth a look: `config.py`, `ui/tui/app.py` and
`screens/between_day.py` came back from the file bridge with different sizes and
newer mtimes than the directory listing taken minutes earlier in the same session.
Both versions read as complete, non-truncated files. Most likely an uncommitted
working-tree edit, but check `git status` before trusting a clean tree.

Everything else below was read against the working tree as staged on 2026-09-12 and
is cited by file and line.

---

## TL;DR

| Issue | What it really is | Engine change? | Est. |
|---|---|---|---|
| **#37** DW-01…DW-04 | ~30% engine, 70% writing. The `dark_web` rule mutability already exists and is already honoured end to end — what's missing is a way to get a rule *into* a day's book, and a narration branch that justifies it instead of shrugging. | **Yes** — new day-file field + one narration branch | M |
| **#39** Days 5–7 | Nearly pure content. Day 5 is already authored (it's the stego/graduation day); this is really days 6–7. Dark Web candidates *already* appear from day 6 via the `medium` band. Authoring makes it deliberate. The one AC with no mechanism behind it is "chat escalates each appearance". | Small (chat escalation only) | S |
| **#40** Days 8–11 | Content, gated on #37's mechanism. Four day files, the DW introductions, hostile Overseer copy, and Dark-Web-harm chat lines on a Clumsy Cutie / Obvious Admit. | No (consumes #37's) | M |
| **#41** Day 12 White Hat | Content + one real balance decision. `forced_includes` already does the scripting. The problem is that the White Hat's alignment swing is **±1 — identical to every Dark Web candidate**, and there are 8–16 of those across the campaign. "The single biggest alignment swing" is currently false. | **Yes** — alignment weighting | S–M |
| **#42** Days 13+ & endings | The largest by a distance, and the only one that is mostly engine. Three endings do not exist in any form; `CampaignEndScreen` is a 34-line "TO BE CONTINUED" stub. `core/overseer.py`, which #71 assumes, **does not exist**. | **Yes** — substantial | L |

**Honest split:** #39 is a contained content drop. #40 is content behind one small
engine change. #37 and #41 are each one focused engine change plus writing. **#42 is
real engineering** and should not be estimated as "authoring eight more day files".

---

## What's already there (verified, not assumed)

Batch 4 left more of this batch's foundation standing than the issues suggest.

- **`"dark_web"` is already a legal rule mutability** — `models.py:146`,
  `RULE_MUTABILITIES` at `models.py:147-148`.
- **It is already honoured by the flip engine** — `content_loader.mutate_variable_rules`
  passes `fixed` and `dark_web` through untouched (`content_loader.py:230-232`,
  docstring at :211).
- **The diff layer already emits `added` and `removed`** — `rules_engine.diff_rulesets`
  (`rules_engine.py:180-215`), filtered to `mutability != "fixed"`. Project memory
  flagged these as implemented-but-never-produced, specifically so #37 wouldn't have
  to reopen the diff layer. Correct — it doesn't.
- **The Overseer already has phrasings for `added` / `removed`** —
  `screens/_narration.py:76-84`.
- **`Archetype.DARK_WEB` and `Archetype.WHITE_HAT` are fully specced generators** —
  `candidate_gen.py:268-280` and `:384-402`. Both have multi-line verdict reactions
  (`reactions.py:194`, `:224`).
- **`forced_includes` pins an archetype to a slot** — `models.py:378`, parsed at
  `content_loader.py:361-365`. #41's scripting needs no new field.
- **All three White Hat signals are reachable by day 12.** `LOW_AND_SLOW` → Logwatch
  (day 4), `ENCRYPTED_PAYLOAD` → Stegotool (day 5), `BURNER_IDENTITY` → Ghostscan
  (day 2) — `candidate_gen.py:470,477,484` against `config.TOOL_UNLOCK_DAY`. So
  `forced_violations` can pin all three on day 12 and the loader's tier gate
  (`content_loader.py:126-136`) will accept them.
- **`GameState.alignment` persists and clamps** to ±10 (`models.py:443`,
  `scoring.py:258-261`, `config.py:35-37`).
- **Dark Web already appears procedurally** from day 6 — `ARCHETYPE_MIX_BY_BAND`
  gives `dark_web: 1` in `medium` (days 6–12) and `2` in `hard` (13+),
  `config.py:514,533`.
- **Unauthored days already play** rather than opening on silence —
  `resolve_narrative` (`content_loader.py:430-440`) and the `generic_*` keys.
  `test_no_day_opens_or_closes_on_a_blank_overseer` (`test_engine_foundation.py:2965`)
  covers all 20 days and is green today.

**So: nobody has to build the corruption arc's plumbing. It's built. What's missing
is the four things below.**

---

## The four gaps

### Gap 1 — a DW directive has no way into the rulebook

`load_day` (`content_loader.py:323-332`) is all-or-nothing: a day file either
declares a **complete** `rules` array or inherits Day 1's 27 rules with today's
flips. There is no patch, append, or override path.

So "introduce DW-01 on day 8" today means restating all 27 rules plus DW-01 in
`day_08.json`, and again in 09, 10, 11. The loader's own comment
(`content_loader.py:312-322`) argues against exactly this: *"five near-identical
190-line files… a merge conflict waiting to happen and a place for the days to
silently drift apart."*

**Recommendation: a new optional `added_rules` field.** Day inherits Day 1's book,
then appends these. ~15 lines in `content_loader.load_day`, no `Day` dataclass
change needed if they're merged into `rules` at load time. `diff_rulesets` then
reports each as `added` with no further work, because their `mutability` is
`"dark_web"` and therefore not `"fixed"`.

→ **Gate question 1.**

### Gap 2 — "overrides an existing criterion" has no clean diff shape

#37's AC asks each directive to name *"which existing admit/deny criterion it
overrides"*. Two ways to express that, and they behave differently:

- **Replace by id.** Day 8's DW-01 reuses `rule_disposable_email`'s id with new text.
  **This is silently unannounced.** `diff_rulesets` compares `severity` only
  (`rules_engine.py:170-173`) — a rule whose *text* was rewritten but whose severity
  held produces **no** `RuleChange` at all. The player's rulebook changes underneath
  them with the Overseer saying nothing. That is a bug, not a feature, and it's
  latent in the code today.
- **Add + remove.** DW-01 arrives with its own id; the criterion it supersedes leaves
  the book. Both halves already diff correctly, and the briefing already has copy for
  each. Requires the superseded rule's `mutability` to not be `"fixed"`
  (`rules_engine.py:178`).

**Recommendation: add + remove.** It produces a truthful broadcast with zero engine
change beyond Gap 1. If replace-by-id is wanted for authoring convenience, extend
`diff_rulesets` with a `"reworded"` change kind first — otherwise the corruption arc
happens invisibly.

→ **Gate question 1** (same answer covers both).

### Gap 3 — the Overseer shrugs at a Dark Web directive

`rule_change_lines` (`_narration.py:119-141`) buckets purely on `change.kind`. An
added rule gets `_RULE_CHANGE_PHRASINGS["added"]` — *"They've added one. {rule}. I
didn't write it, I just pass it along."* Deliberately bored, and correct for an
Overseer-Variable flip.

#37 asks for the opposite register for these: *large changes need in-fiction
justification*. Today a DW directive would be announced in the same shrug as a
severity wobble.

**Fix:** branch on `change.rule.mutability == "dark_web"` before the `kind` bucket,
and read a per-directive `justification` string authored on the rule itself rather
than a phrasing pool — four directives, four bespoke speeches, not a template.
~10 lines in `_narration.py` plus a `justification` field on `Rule`.

**Flagged, not asked** — this follows directly from #37's own acceptance criteria.

### Gap 4 — nothing about the ending exists

- `CampaignEndScreen` (`screens/campaign_end.py`, 34 lines) takes `day_number` and
  renders **"TO BE CONTINUED — Day N isn't written yet."** No alignment parameter, no
  branch, no epilogue.
- It is reached from `app.advance_day`'s `except FileNotFoundError`
  (`app.py:303-307`), which fires on the attempt to load day 21. The trigger is fine;
  the screen is a placeholder.
- **`core/overseer.py` does not exist.** #71 describes it as *"the Overseer's existing
  alignment-conditional dialogue selector"* and asks for it to be verified across days
  14–16 and 18–19. It has never been written. #71 is therefore blocked on #42 building
  it, not merely on #42's content landing.
- **`overseer.json` has no alignment axis.** 39 keys, all `dayN_*` or `generic_*`
  (resolution is day-key → generic-key → hard-coded last resort,
  `content_loader.py:409-440`). Alignment-conditional dialogue needs a third
  dimension in both the file and the resolver.

→ **Gate questions 3 and 4.**

---

## Gap 5 — the White Hat is not special (the #41 finding)

This one is worth separating out because it makes an acceptance criterion currently
unsatisfiable.

| | value | source |
|---|---|---|
| `WHITE_HAT.moral_modifier` | **+1** | `candidate_gen.py:388` |
| `DARK_WEB.moral_modifier` | **−1** | `candidate_gen.py:271` |
| alignment clamp | **±10** | `config.py:36-37` |
| Dark Web candidates, days 6–12 | ~1/day | `ARCHETYPE_MIX_BY_BAND["medium"]`, `config.py:514` |
| Dark Web candidates, days 13–20 | ~2/day | `ARCHETYPE_MIX_BY_BAND["hard"]`, `config.py:533` |

`scoring.score` applies `alignment = moral if player_admit else -moral`
(`scoring.py:194-198`) — no archetype weighting, no day weighting.

**So the campaign's pivotal moral choice moves alignment exactly as much as one
routine Dark Web admit on a Tuesday**, against a pool of roughly 8–16 of them. #41's
AC — *"the single biggest GameState.alignment swing in the campaign"* — cannot be
true as the numbers stand.

Note `test_only_dark_web_and_white_hat_shift_alignment`
(`test_engine_foundation.py:825`) asserts only `moral_modifier != 0`, never a
magnitude, so raising it breaks no existing guard.

→ **Gate question 2.**

---

## Phases

Grouped by risk and dependency, not issue number.

### Phase 1 — #37: directive mechanism + the four directives
**Depends on:** nothing. **Blocks:** Phase 3.

1. `Rule` gains an optional `justification: str | None` (`models.py:268-282`) —
   defaults `None`, so every existing day file loads byte-identically.
2. `load_day` accepts an optional `added_rules` array, parsed by the existing
   `_parse_rule`, appended to the inherited book (`content_loader.py:323-332`).
   Fail loudly on: a `dark_web` rule with no `justification`; an id that collides
   with an inherited rule (that's a replace, which per Gap 2 we're not doing);
   an unknown predicate (already covered by `rules_engine.resolve`).
3. `rule_change_lines` branches on `mutability == "dark_web"` and speaks the
   directive's own `justification` (`_narration.py:119-141`).
4. Author DW-01…DW-04: id, player-facing rule text, predicate, severity,
   justification, trigger day, and the criterion each supersedes.

**Acceptance**
- [ ] Four directives defined with all six attributes each
- [ ] Each is a legal `Rule` with `mutability: "dark_web"` and a `justification`
- [ ] A day carrying one produces exactly one `RuleChange(kind="added")` from
      `diff_rulesets`, and the superseded rule produces one `kind="removed"`
- [ ] The briefing line for a `dark_web` change is the authored justification, not
      a `_RULE_CHANGE_PHRASINGS` template
- [ ] `mutate_variable_rules` leaves all four untouched on every day 1–20
- [ ] A `dark_web` rule authored without a `justification` fails at load, naming the file

**New guards:** a directive that silently fails to enter the book is the #63-class
failure this repo keeps re-learning — assert the *rulebook contents* on each DW day,
not just that the briefing printed something.

---

### Phase 2 — #39: days 6–7
**Depends on:** nothing. Can run parallel to Phase 1.

Day 5 is already authored (`day_05.json` — stego day, `day5_graduation`). Read #39 as
**days 6–7**, with day 5's `rule_sheet` note *"From tomorrow the rulebook starts
changing"* as the handoff it already promises.

1. `day_06.json`, `day_07.json`: `archetype_mix` with a deliberate `dark_web: 1`,
   `allowed_violations`, `difficulty_band: "medium"`, `rule_sheet`, quotas. Omit
   `rules` (inherit).
2. `day6_intro` / `day7_intro`, four outros each, `day6_between` / `day7_between` in
   `overseer.json`. Register: warmth curdling into process. Compliance language, not
   threat.
3. Dark Web chat escalation — see the flagged call below.

**Acceptance**
- [ ] Both days load and pass the existing day guards
- [ ] Each contains at least one Dark Web candidate by declared mix, not by luck
- [ ] Overseer copy reads as a step up from day 5 and short of hostile
- [ ] Rule sheets coordinate with day 5's and with #16's shipped sheets

---

### Phase 3 — #40: days 8–11, the corruption arc
**Depends on:** Phase 1.

1. `day_08.json`…`day_11.json`, each carrying one directive via `added_rules` and
   dropping the criterion it supersedes.
2. Overseer copy escalating compliance-pushing → openly hostile/manipulative by day 11.
3. At least one Clumsy Cutie or Obvious Admit in the range whose chat references harm
   done by the Dark Web. This needs a per-day or per-slot chat override — the chat
   pools are archetype-static (`candidate_gen.py:991`, `base = list(spec.chat_pool)`).
   Cheapest honest route: a `forced_chat` slot override in the day JSON, same shape as
   `forced_violations`.

**Acceptance**
- [ ] Days 8–11 each introduce their directive on its scripted day
- [ ] The briefing announces each with its authored justification
- [ ] Overseer reads as openly hostile by day 11
- [ ] At least one candidate in 8–11 names Dark Web harm in chat
- [ ] The literal-ruleset and moral tracks measurably diverge on at least one
      candidate — this is the first content in the game where `tracks_diverge`
      (#38, `scoring.py:204-217`) can actually be true, and `scoring.py`'s own comment
      at :206-212 predicts exactly this moment

---

### Phase 4 — #41: day 12, the White Hat
**Depends on:** Gate question 2. **Blocks:** Phase 5's ending thresholds.

1. Alignment weighting per the gate answer.
2. `day_12.json`: `forced_includes: {"N": "white_hat"}` plus `forced_violations`
   pinning `LOW_AND_SLOW`, `ENCRYPTED_PAYLOAD`, `BURNER_IDENTITY` — all three clear
   the tier gate by day 12.
3. Bespoke Overseer copy around the encounter, distinct from a Sneaky Bugger day.
4. Confirm `reactions.py`'s White Hat multi-line run reads right in place.

**Acceptance**
- [ ] White Hat scripted, not rolled — same slot every seed
- [ ] All three signals present and each readable with a tool the player owns
- [ ] Admitting shifts alignment toward White Hat by materially more than one
      Dark Web admit; denying shifts the other way
- [ ] Day 12's Overseer copy is distinguishable from a normal suspicious-case day
- [ ] Exactly one White Hat in the whole campaign (guard it — `white_hat` is absent
      from every `ARCHETYPE_MIX_BY_BAND` band today, `config.py:494-534`, and that
      should stay true)

---

### Phase 5 — #42: days 13–20, and the three endings
**Depends on:** Phases 3 and 4. The largest phase.

1. **`core/overseer.py`** — the alignment-conditional dialogue selector. Extend
   `resolve_narrative`'s chain (`content_loader.py:430-440`) to
   `day+alignment key → day key → generic+alignment key → generic key → last resort`.
2. **Day files 13–20**, to the depth chosen at the gate.
3. **Directives targeting the White Hat** post-reveal, using Phase 1's mechanism.
4. **Three endings.** `CampaignEndScreen` takes the final `GameState`, branches on
   alignment (and possibly the White Hat verdict — gate question 4), and renders an
   authored epilogue per outcome.
5. **End-of-campaign trigger.** Works today via `FileNotFoundError` on day 21
   (`app.py:303-307`), but once every day through 20 is authored it's worth an
   explicit `current_day > CAMPAIGN_LAST_DAY` check so the ending isn't reached by
   exception.

**Acceptance**
- [ ] Days 13–20 load and play
- [ ] White-Hat-targeting directives appear post-reveal
- [ ] Three endings reachable, narratively distinct, gated on alignment
- [ ] `CampaignEndScreen` renders the right one for each outcome
- [ ] A test drives all three from a synthetic `GameState` — the whole ending must be
      reachable without a 20-day playthrough, or it will never be re-verified
- [ ] #71 becomes answerable (it currently references a file that doesn't exist)

---

## Sequencing

| Week | Work |
|---|---|
| 1 | Phase 1 (#37) and Phase 2 (#39) in parallel — no shared files |
| 2 | Phase 3 (#40), then Phase 4 (#41) |
| 3 | Phase 5 (#42) — engine first (selector, ending screen), content second |
| 4 | #70's balance pass, then #71's dialogue verdict. Both are downstream by design. |

---

## Cross-cutting risks

1. **`test_authored_days_inherit_the_rulebook_from_day_one`**
   (`test_engine_foundation.py:3001`) loops `range(2, TUTORIAL_LAST_DAY + 1)` — days
   2–5 only. It will **not** fail on days 8–11's added rules. That's lucky, not
   designed. Extend it to every authored day with an explicit `added_rules` carve-out,
   or the next authored day that accidentally restates the rulebook drifts unnoticed.
2. **`test_every_violation_kind_has_a_rule`** (`:2442`) — removing a superseded rule in
   Phase 3 may orphan a violation kind. Check before, not after.
3. **Silent-drop failures are this repo's recurring bug class.** Project memory records
   four guards that went inert during Batch 4 alone. Every new guard here gets verified
   by reverting the fix in a scratch copy and confirming red — particularly the
   directive guards, where a directive that fails to load still plays a perfectly
   normal day.
4. **`day_01.json` is not a generic day fixture.** Batch 4 lost 17 tests to this. Use
   `unconstrained_day()` in `test_engine_foundation.py`.
5. **Merge reconciliation with `main`'s `b533dfb`** is still outstanding from Batch 3,
   and Batches 2–4 all touched `candidate_gen.py`. Phases 1 and 4 touch it again.
6. **`CONTENT_AUTHORING.md` needs updating** — it documents `_UNLOCK_LINES` /
   `_RULE_CHANGE_PHRASINGS` as living in `ui/tui/app.py` (lines 35–36). They moved to
   `ui/tui/screens/_narration.py`; `app.py` only re-exports them (`app.py:45-53`).
   Any new day-file field (`added_rules`, `forced_chat`) belongs in its field table too.
7. **Git over the Windows mount can't unlink its own lock files.** Bit twice in Batch 4.
   `mv .git/*.lock .git/_stale/` pre-emptively before every commit.
8. **The shell is down.** Nothing in Phase 1–5 can be tested or committed from the cloud
   session until the mount is restored. Files can still be written to disk via the
   file bridge; `pytest` and `git` are Nick's to run.

---

## Open questions

### 1. How do Dark Web directives enter the rulebook? — ASKED
**Recommendation: new optional `added_rules` field, and directives ADD a new rule
while the criterion they supersede is REMOVED.** Rationale in Gaps 1 and 2. The
alternative (restate the full 27-rule array per day) is the exact drift the loader's
own comment argues against, and replace-by-id makes the change invisible to the
briefing because `diff_rulesets` compares severity only.

### 2. How big is the White Hat's alignment swing? — ASKED
**Recommendation: raise `WHITE_HAT.moral_modifier` to ±4.** With ~8–16 Dark Web
candidates across the campaign against a ±10 clamp, ±4 makes the day-12 verdict
roughly equal to four ordinary days of drift — decisive without being able to
single-handedly pin the ending. Alternative: a per-day `alignment_weight` override, if
a future second White Hat should be lighter.

### 3. How much of days 13–20 is authored? — ASKED
#70 and #71 record a 2026-09-11 beat map: **13, 17, 20 bespoke; 14–16 and 18–19 ride
the alignment-conditional selector.** That plan exists only in those two issue bodies
and implies building `core/overseer.py`, which does not exist. Confirm it still holds.

### 4. Do the endings branch on alignment alone? — ASKED
If the day-12 White Hat verdict is a gate in its own right (not just its alignment
contribution), `GameState` needs to remember that call — it isn't stored separately
today; only the aggregate `alignment` and the per-day `DayResult` history are
(`models.py:412-417`, `:456`).

### 5. Dark Web chat escalation — MY CALL, FLAGGED
#39's AC says the chat escalates each appearance. There is no mechanism: `chat_pool`
is archetype-static (`candidate_gen.py:279`, selected at `:991`). **Proposing
day-banded pools** — `_CHAT_FLIPPANT_EARLY` / `_MID` / `_LATE` picked by day number —
which is small, deterministic, and reuses the existing selection path. Say the word if
you'd rather author per-day chat in the day JSON instead, or drop the escalation.

### 6. Overseer justification copy lives on the rule — MY CALL, FLAGGED
Four directives, four bespoke justifications authored as a `justification` field on
the rule, rather than a fifth `_RULE_CHANGE_PHRASINGS` bucket. A pool of
interchangeable phrasings is right for routine flips and wrong for a scripted story
beat that happens exactly once.

### 7. Branch and commit granularity — ASKED
Default: continue on `batch-3-UserFeedback-ContentGeneration`, one commit per issue.
