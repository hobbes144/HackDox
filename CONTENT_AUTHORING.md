# HackDox — Where the content lives

Everything the player reads, and which file to open to change it. Written 2026-08-18, verified against `batch-3-UserFeedback-ContentGeneration` @ `9806dd4`.

**The one-line version:** Overseer dialogue is in `overseer.json`. What a day contains is in `day_NN.json`. The rules-overlay reference pages are Python in `rules_content.py`. Post-verdict candidate reactions are in `reactions.py`. Everything else is a word bank in `candidate_gen.py` or `tools_bridge.py`.

---

## 1. Overseer dialogue — `gameengine/content/narratives/overseer.json`

**Every line the Overseer speaks is in this one file.** Flat `key → string`. Newlines inside a string become separate typewriter beats.

Resolution order (`content_loader.resolve_narrative`):

```
day-specific key  →  generic_* key  →  hard-coded last resort
```

Blanking a value falls through to the generic copy — an empty string means "not written yet", not "she says nothing".

| Key | When it plays |
|---|---|
| `dayN_intro` (or whatever `day_NN.json`'s `overseer_intro_key` names) | Morning briefing |
| `dayN_outro_excellent` / `_passing` / `_poor` / `_failed` | End of day, by rating |
| `dayN_between` | Between-day shop screen |
| `day5_graduation` | The tutorial hand-off beat |
| `generic_intro`, `generic_outro_<rating>`, `generic_between` | **Any day with no authored key** — this is what days 6–20 use |

To give an unauthored day real copy, just add `day12_intro` etc. here. No code change.

**Two lines that are still Python, not JSON:**

| What | Where |
|---|---|
| Tool-unlock narration ("New capability authorized: GHOSTSCAN…") | `ui/tui/app.py` → `_UNLOCK_LINES` |
| Rule-change phrasings (the Overseer mentioning a flip) | `ui/tui/app.py` → `_RULE_CHANGE_PHRASINGS` |

`_UNLOCK_LINES` is still marked PLACEHOLDER. It's a candidate to move into `overseer.json` if you want everything in one place — say the word.

---

## 2. What a day contains — `gameengine/content/days/day_NN.json`

**Days 1–5 are authored. Days 6–20 are synthesized** by `content_loader.synthesize_day()` from Day 1's rules plus the config curves. **An authored file always wins** — drop in a `day_09.json` and it takes over completely, no code change.

Past day 20 (`config.CAMPAIGN_LAST_DAY`) the campaign-end screen fires.

### Fields

| Field | Does |
|---|---|
| `candidate_count` | Shift length. Omit to take the campaign curve. |
| `archetype_mix` | How many of each archetype. Must sum to `candidate_count`. |
| `forced_includes` | `{"slot": "archetype"}` — pin who appears where. |
| `forced_violations` | `{"slot": ["kind", …]}` — pin **what they carry**. This is the tutorial's teaching tool. |
| `allowed_violations` | Whitelist. Nothing outside it is ever planted. |
| `rules` | **Optional.** Omit and the day inherits Day 1's rulebook with today's flips applied. Only Day 1 must declare it. |
| `rule_sheet` | The player-facing approved/denied sheet (see below). |
| `quotas` | `min_correct_admits` / `max_false_admits`. |
| `overseer_intro_key`, `overseer_outro_keys` | Which `overseer.json` keys this day uses. |
| `difficulty_band` | `easy` / `medium` / `hard`. |

### `forced_violations` — the important one

```jsonc
"forced_violations": {
  "1": ["email_github_mismatch"],
  "3": ["breach_hit"]
}
```

Slot 1's candidate now *always* carries that violation, every seed. Three ways this is rejected **loudly at load time**, naming the file:

- the slot doesn't exist in this day's shift
- the violation's tool isn't taught yet (`config.TOOL_UNLOCK_DAY`)
- it isn't expressible yet (e.g. `cross_breach_reuse` before a second breach corpus unlocks)

It fails rather than dropping silently on purpose: a dropped script still plays fine, it just stops teaching the thing the day exists for.

### `rule_sheet` — the Papers-Please sheet (#49)

Rendered **verbatim**. `summary` + `notes` land on the Rules tab; the four lists land on the Dossier tab above the full engine reference.

```jsonc
"rule_sheet": {
  "summary": "One line: what's different today.",
  "approved": { "domains": [...], "affiliations": [...] },
  "denied":   { "domains": [...], "affiliations": [...] },
  "notes":    ["Free-form lines. Plain language."]
}
```

These are **display copy** — they don't drive scoring. `rules` (the predicates) does that. Keeping them honest against each other is an authoring job, deliberately: it's what lets the Overseer's rulebook lie to the player later without the engine lying to itself.

---

## 3. Reference / rules overlay pages — `gameengine/ui/tui/rules_content.py`

The `R` overlay, six tabs, each a `build_*_text(day)` function returning Rich markup:

| Function | Tab |
|---|---|
| `build_rules_text` | Rules — today's ruleset, quotas, ⏱ economy, upgrades |
| `build_dossier_text` | Dossier — quick cases, encryption chips, domain & affiliation lists |
| `build_osint_text` | Ghostscan |
| `build_creds_text` | Hashcrack |
| `build_logs_text` | Logwatch |
| `build_stego_text` | Stegotool |

Also here:

- `VIOLATION_CATALOG` — **the single source of every violation's player-facing name.** The evidence board, rules pages, credit reveal and dev window all read it via `label_for()`. Change a name here and it changes everywhere. Import-time asserts catch a missing or duplicated entry.
- `_CATCH` — the "how you actually catch this" one-liner under each table row.

Severities, revealing tools and trigger descriptions are **derived from the engine**, so they can't drift from the code. Don't hand-edit them here — edit `candidate_gen._SEVERITY_REVEAL` / `_DISCREPANCY_DESCRIPTIONS`.

---

## 4. Word banks

| Bank | File | What |
|---|---|---|
| `AFFILIATIONS_LEGIT` | `core/candidate_gen.py` | Ordinary employers |
| `AFFILIATIONS_ELITE` | `core/candidate_gen.py` | Prestige orgs — **can never be faked** (#56) |
| `AFFILIATIONS_FAKED` | `core/candidate_gen.py` | What a Sneaky Bugger may claim |
| `AFFILIATIONS_THIN` | `core/candidate_gen.py` | "Independent", "Freelance"… |
| `DOMAINS_TRUSTED` / `DOMAINS_PRIVACY` / `DOMAINS_DISPOSABLE` | `core/candidate_gen.py` | Email classification |
| `FIRST_NAMES` / `LAST_NAMES` / `PURPOSES_*` / chat pools | `core/candidate_gen.py` | Identity flavour |
| `_ELITE_ORG_HANDLE` | `core/candidate_gen.py` | Handles the typosquat mimics |
| `_DISCREPANCY_DESCRIPTIONS` | `core/candidate_gen.py` | One-line trigger text per violation |
| `_BREACH_DATABASES` | `core/tools_bridge.py` | Corpus names/years/counts |
| `_GS_LEGIT_PLATFORMS`, `_GS_CRITICAL_FORUMS`, `_GS_ADVISORY_FORUMS` | `core/tools_bridge.py` | Ghostscan sweep surfaces |
| `_GS_NOISE_HANDLES`, `_GS_BREACH_EMAIL_*`, `_HC_NOISE_*` | `core/tools_bridge.py` | Background noise |

**`candidate_gen` owns; `tools_bridge` derives.** `_GS_TRUSTED_DOMAINS`, `_GS_PRIVACY_DOMAINS`, `_GS_SUSPICIOUS_DOMAINS` and `_GS_LEGIT_ORGS` are computed from the banks above — edit the bank, both sides move. This is deliberate: #57 was two hand-synced domain lists drifting until 37% of a violation became undetectable, and it happened again with `_GS_LEGIT_ORGS`. **Never re-introduce a second copy.**

Adding a breach database means editing **two** places, and an import-time assert enforces it: `_BREACH_DATABASES` in `tools_bridge` and `BREACH_DB_UNLOCK_DAY` in `config`.

---

## 5. Verdict reactions — `gameengine/ui/tui/reactions.py`

The candidate's last word, played in the chat panel during the post-verdict
reveal window. Keyed `REACTIONS[Archetype][Verdict]` → a list of interchangeable
variants; one is picked deterministically from the candidate id, so a replayed
day plays back identically.

| | |
|---|---|
| **Key** | Archetype, not tone. Sneaky Bugger and Clumsy Cutie both play "warm" — the whole point of the beat is that one of those masks comes off. |
| **Verdict** | Each archetype has exactly one correct verdict, so ADMIT/DENY already implies right-call/wrong-call. There is no third axis. |
| **`valence`** | The **candidate's** register, not the player's score. An admitted Bad Actor is `"positive"` — good for him, disastrous for the player. The border pulse carries the grade; the chat carries the character. Don't make them say the same thing twice. |
| **Line count** | One line for the seven everyday archetypes — the window is 2–4s. Dark Web and White Hat get multi-line runs; they are the two whose verdict moves alignment, so their reaction is where the moral arc actually speaks. A test enforces this split. |
| **Text** | Plain, no markup. Lines are typed out a character at a time, so brackets would tear mid-reveal. A test enforces this too. |

**Ground truth stays hidden.** A reaction may admit in character that *something*
was there ("...huh. you actually read it."). It must never name which
discrepancy, which tool would have found it, or what the player missed — that
job belongs to the evidence board's grading, which is scoped to the calls the
player actually made.

Adding an archetype to the enum without an entry here degrades to a bland
fallback rather than crashing a shift, so nothing else in the suite would catch
the gap — `test_verdict_reveal.py::test_every_archetype_has_reactions_for_both_verdicts`
is what does.

Window timing lives in `config.py`: `VERDICT_REVEAL_ENABLED`,
`VERDICT_REVEAL_DURATION`, `VERDICT_REVEAL_PULSE_INTERVAL`.

---

## 6. Campaign shape — `gameengine/config.py`

| Knob | Does |
|---|---|
| `TOOL_UNLOCK_DAY` | Which tool unlocks when. **Single source of truth** — drives the UI unlock, the Overseer's narration, and the generator's evidence gate. |
| `BREACH_DB_UNLOCK_DAY` | Which breach corpus unlocks when (#61). Same role. |
| `MIN_BREACH_DBS_FOR_REUSE` | Below this, cross-breach reuse can't be planted. |
| `CAMPAIGN_LAST_DAY` (20) | End of campaign. |
| `TUTORIAL_LAST_DAY` (5) | Teaching days; difficulty levers stay flat across them. |
| `DAY_CANDIDATE_COUNT` | Shift-length curve. |
| `DAY_MIN_CORRECT_ADMITS`, `QUOTA_ADMIT_RATIO` | Quota scaling. |
| `ARCHETYPE_MIX_BY_BAND` | Archetype weighting per difficulty band (synthesized days only). |
| `RULE_FLIP_PERIOD` | How sticky Overseer-Variable rule flips are. |
| `TOOL_COSTS`, `DAY_TOOL_COST`, `DAY_REWARD_PAYOUT` | The ⏱ / HD$ economy. |
| `STEGO_HINT_BUFFER` | Spectral Lens generosity. |

---

## Recipes

**Change what the Overseer says on day 3** → `overseer.json`, key `day3_intro`.

**Give day 9 real dialogue** → add `day9_intro` / `day9_outro_*` / `day9_between` to `overseer.json`. Nothing else.

**Author day 9 properly** → create `content/days/day_09.json`. Copy `day_05.json`, change `number`/`title`, omit `rules`. It takes over from the synthesizer immediately.

**Guarantee a specific violation appears** → `forced_includes` for the archetype + `forced_violations` for the kind. It'll refuse to load if the day can't express it.

**Rename a violation everywhere** → `VIOLATION_CATALOG` in `rules_content.py`. One edit.

**Move a tool to a different day** → `config.TOOL_UNLOCK_DAY`. UI, narration and generator gate all follow.

**Add a breach corpus** → `_BREACH_DATABASES` (tools_bridge) **and** `BREACH_DB_UNLOCK_DAY` (config). Import fails if you forget one.

**Reword a reference page** → the relevant `build_*_text` in `rules_content.py`.

---

## Debugging what you authored

```
hackdox lab -a sneaky_bugger -v typosquat_handle --day 5
hackdox lab --tool hashcrack -n 3
hackdox lab -a bad_actor --tool logwatch --play
```

`hackdox lab` generates candidates under explicit constraints and prints ground truth next to the tool's real filtered output, side by side — which is what makes an unrendered or contradicted violation obvious. With no `--seed` it searches and reports the seed it found, so the case is reproducible.

**Then run the suite.** `python -m pytest gameengine/tests` — 185 tests, and a good number of them exist specifically to catch authored content that stops working: scripted violations that silently stop landing, days that open on an empty Overseer, rule-sheet entries authored but never rendered, tutorial days with no clean admit.
