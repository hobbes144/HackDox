# HackDox — Where the content lives

Everything the player reads, and which file to open to change it. Written 2026-08-18, verified against `batch-3-UserFeedback-ContentGeneration` @ `9806dd4`.

**The one-line version:** Overseer dialogue is in `overseer.json`. What a day contains is in `day_NN.json`. Alignment-banded Overseer reactions and the three campaign endings are in `core/overseer.py`. The rules-overlay reference pages are Python in `rules_content.py`. Post-verdict candidate reactions are in `reactions.py`. Everything else is a word bank in `candidate_gen.py` or `tools_bridge.py`.

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
| Tool-unlock narration ("New capability authorized: GHOSTSCAN…") | `ui/tui/screens/_narration.py` → `_UNLOCK_LINES` |
| Rule-change phrasings (the Overseer mentioning a flip) | `ui/tui/screens/_narration.py` → `_RULE_CHANGE_PHRASINGS` |

Both are re-exported from `ui/tui/app.py` for convenience, but that file just imports them — go straight to `_narration.py` to edit.

`_UNLOCK_LINES` is still marked PLACEHOLDER. It's a candidate to move into `overseer.json` if you want everything in one place — say the word.

---

## 1a. Alignment-banded Overseer dialogue — `gameengine/core/overseer.py` (#42)

The Overseer's alignment-conditional voice, for content that should react to how the player has actually been playing (leaning White Hat, leaning Dark Web, or neither), still in the same `overseer.json` file — no new file to open.

**The three bands** (`core/overseer.alignment_band(alignment)`):

| Band | Condition |
|---|---|
| `whitehat` | `alignment >= config.ALIGNMENT_BAND_WHITE_HAT_THRESHOLD` (currently **+4**) |
| `darkweb`  | `alignment <= config.ALIGNMENT_BAND_DARK_WEB_THRESHOLD` (currently **-4**) |
| `neutral`  | everything in between |

Both thresholds are in `gameengine/config.py`, symmetric around `STARTING_ALIGNMENT` (0), and set at the magnitude of the day-12 White Hat's own single-encounter `moral_modifier` (+4) — one unambiguous act of resistance or complicity is enough to be recognized as leaning; a genuinely mixed record stays `neutral`, which is its own real ending, not a weaker version of the other two. See the module docstring in `overseer.py` for the full reasoning if you're re-tuning these.

**Key convention** — for any narrative key of the shape `day<N>_<rest>` or `generic_<rest>`, its banded variant splices the band token in right after that prefix:

```
day14_intro            ->  day14_whitehat_intro   / day14_neutral_intro   / day14_darkweb_intro
day14_outro_excellent  ->  day14_whitehat_outro_excellent / day14_neutral_outro_excellent / day14_darkweb_outro_excellent
day14_between          ->  day14_whitehat_between / day14_neutral_between / day14_darkweb_between
generic_intro          ->  generic_whitehat_intro / generic_neutral_intro / generic_darkweb_intro
```

**Resolution order** (`core.overseer.resolve_aligned_narrative`, called instead of `content_loader.resolve_narrative` wherever the Overseer's line should react to alignment):

```
day+band key  →  day key  →  generic+band key  →  generic key  →  hard-coded last resort
```

**Authoring a band-specific line is entirely optional, one key at a time.** A day that authors nothing but `day14_intro` (every day today, including 1–12) behaves exactly as it did before this mechanism existed — the band keys are absent, so the chain falls straight through to the plain day key. This is verified by a dedicated backward-compatibility test (`test_alignment_band_keys_dont_change_days_1_through_12`); don't remove it.

**To give day 14 a reaction that only fires for a Dark-Web-leaning player**, add `day14_darkweb_intro` to `overseer.json`. Leave `day14_whitehat_intro` / `day14_neutral_intro` unauthored (or write those too) and they each independently fall back through the same chain. Nothing else needs to change — `resolve_aligned_narrative` is the only thing that needs to be called at that site instead of `resolve_narrative`.

---

## 2. What a day contains — `gameengine/content/days/day_NN.json`

**Days 1–5 are authored. Days 6–20 are synthesized** by `content_loader.synthesize_day()` from Day 1's rules plus the config curves. **An authored file always wins** — drop in a `day_09.json` and it takes over completely, no code change.

Past day 20 (`config.CAMPAIGN_LAST_DAY`), `app.py`'s `advance_day` fires `CampaignEndScreen` explicitly (before ever attempting to load a day-21 file) and renders one of three authored epilogues — White Hat / Neutral / Dark Web — chosen by the final `GameState.alignment`'s band (see §1a). The three epilogues themselves live in `core/overseer.py`'s `ENDINGS` — that's where to edit their prose.

### Fields

| Field | Does |
|---|---|
| `candidate_count` | Shift length. Omit to take the campaign curve. |
| `archetype_mix` | How many of each archetype. Must sum to `candidate_count`. |
| `forced_includes` | `{"slot": "archetype"}` — pin who appears where. |
| `forced_violations` | `{"slot": ["kind", …]}` — pin **what they carry**. This is the tutorial's teaching tool. |
| `forced_chat` | **Optional** (Batch 5 Phase 3 / #40). `{"slot": ["line", …]}` — pin **extra chat lines** onto a slot, appended after that archetype's ordinary chat rather than replacing it. **Requires a `forced_includes` entry for the same slot** — see the recipe below. |
| `allowed_violations` | Whitelist. Nothing outside it is ever planted. |
| `rules` | **Optional.** Omit and the day inherits Day 1's rulebook with today's flips applied. Only Day 1 must declare it. |
| `added_rules` | **Optional** (#37). Same shape as `rules` — appends new rules on top of whatever the day inherited (or restated). This is how a Dark Web directive lands. An entry may set `supersedes: "<old id>"` to retire that id automatically. **Not cumulative across days** — see the directive section below. |
| `removed_rules` | **Optional** (#37). Bare list of rule ids to drop from the inherited book. Union'd with any `added_rules[].supersedes` ids — use this on its own only when a rule is retired with no replacement. |
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

**Carrier shapes on scripted slots (2026-09-19, round 2).** A scripted slot whose kinds include a stego colour kind rolls a carrier shape like any other carrier — unless you pin it or author it:

- **Author a shape** by naming its kind (`signal_comms_payload` / `recursive_payload` / `hostile_payload`) in the slot's `forced_violations`. Validated loudly at load: at most one shape kind per slot; the slot must also force a stego colour kind (not merely be able to roll one); `forced_includes` must pin a shape-eligible archetype (Bad Actor / Sneaky Bugger / White Hat) that lists that colour kind in its `eligible_kinds`.
- **Pin a plain image** with `"carrier_shape": {"<slot>": "conventional"}` — for a script whose verdict depends on its exact kinds (day 11 slot 5). `"conventional"` is the only accepted value; pinning a slot that also forces a shape kind is a load error.
- A day's `allowed_violations` whitelist also gates rolled shapes: day 5 whitelists the colour kinds but not the shape kinds, so its (scripted) carriers stay conventional while it teaches colour.

### `forced_chat` — pin extra dialogue onto a slot (Batch 5 Phase 3 / #40)

```jsonc
"forced_includes": {
  "3": "clumsy_cutie"
},
"forced_chat": {
  "3": [
    "a friend of mine lost about three hundred dollars last month — some outfit she found through a forum that turned out to be running scams through here.",
    "I know that's small next to whatever you deal with all day. it's just why I'm careful about this stuff now."
  ]
}
```

Slot 3's candidate gets these lines **appended** after its archetype's ordinary chat — the candidate still reads as an everyday instance of its archetype (same tone, same rough line count), with one extra, human aside tacked on at the end. This is how an otherwise-ordinary candidate (an Obvious Admit, a Clumsy Cutie) gets a line no other instance of that archetype says — days 8–11 use it to give a Clumsy Cutie a line naming concrete, small-scale harm a friend suffered from the Dark Web's use of the service.

**`forced_chat` MUST be paired with a `forced_includes` entry for the same slot.** `forced_chat` alone says nothing about which archetype ends up in that slot — an unpinned slot's archetype is whatever the day's shuffled bag happens to assign, which is seed-dependent and can silently change the next time the day's `archetype_mix` is edited (this bit day 9 for real: adding an archetype to the mix reshuffled which slot got which archetype). A sympathetic "a friend of mine lost money" line landing on a Bad Actor or the Dark Web candidate reads as actively incoherent. The loader enforces the pairing and fails loudly, naming the file, if a `forced_chat` slot has no matching `forced_includes` entry.

The same pairing is good practice for `forced_violations` too, whenever the scripted kind is only eligible for one specific archetype (e.g. `sock_puppet_accounts` is Sneaky-Bugger-only) — the loader does not *require* this pairing for `forced_violations` (a kind ineligible for whatever archetype lands in the slot is just silently skipped, per that mechanism's own docstring), so an unpinned slot risks the script quietly teaching nothing on some seeds even though the day loads and plays fine.

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

### `added_rules` / `removed_rules` — Dark Web directives (#37)

A Dark Web directive is a rule change the corrupt Overseer forces onto the
rulebook, with real in-fiction justification instead of the bored,
interchangeable one-liners `_RULE_CHANGE_PHRASINGS` uses for a routine
`overseer_variable` flip. Mechanically it's always the same shape: ADD a new,
laxer rule that names the day-1 rule it `supersedes`; the old rule is retired
automatically.

```jsonc
"added_rules": [
  {
    "id": "dw01_identity_leniency",
    "text": "Flag (do not auto-deny) …",
    "predicate": "has_discrepancy:sock_puppet_accounts",
    "severity": "weighted",
    "mutability": "dark_web",
    "justification": "Compliance flagged our sock-puppet detection for false positives…",
    "supersedes": "rule_sock_puppet_accounts"
  }
]
```

> **⚠️ DIRECTIVES ARE NOT CUMULATIVE ACROSS DAYS — YOU MUST RE-AUTHOR THEM ON EVERY LATER DAY.**
> `load_day`'s inherit-without-`rules` branch always rebuilds a day's book from
> **Day 1**, never from the previous day. So if day 8 adds DW-01 and day 9's
> file doesn't repeat it, day 9 silently goes back to Day 1's original rule —
> DW-01 vanishes and `rule_sock_puppet_accounts` comes back with no warning,
> no error, nothing in the diff. **Every directive day must re-list every
> directive that fired on an earlier day, in addition to its own new one.**
> By day 11 that means `added_rules` for day 11 lists all four DW-01..DW-04
> objects — verbose compared to a "sticky" flip, but still far cheaper than
> restating the ~28-entry rulebook, and it keeps each day file an honest,
> literal statement of "everything different about today's book" (see the
> per-directive blocks below for the exact cumulative lists to use).
>
> **Chained supersession (#42/Phase 5b-1):** an `added_rules` entry's own
> `supersedes` field may name either a Day-1-inherited id, **or an id
> introduced STRICTLY EARLIER in the SAME day's `added_rules` array** — this
> is checked positionally, not just "anywhere in the batch": an entry may
> only name an id that came before it in the array, never its own id or a
> later one, so self- and mutual-supersession are load-time errors rather
> than silent rule drops. This is what lets DW-05 (below) retire DW-04
> *directly* — DW-04 only exists at all on a day that re-lists it in that
> day's own `added_rules` (see above), so without this, a later directive
> could only ever re-target the original Day-1 rule the whole chain traces
> back to, never a previous directive itself. Practically: to supersede a
> previous directive, re-list it in `added_rules` one entry ahead of the new
> directive that supersedes it — the loader drops the re-listed entry from
> the final book once the new one supersedes it, so it never actually goes
> live again, it's only there to give the new entry something in-batch to
> name. **Bare `removed_rules` entries do NOT get this same-batch allowance**
> — a plain `removed_rules` id must already be in the INHERITED book; naming
> an id this same file's own `added_rules` just introduced has no legitimate
> meaning and is rejected outright, not silently treated as a no-op. See
> `content_loader._apply_rule_overrides`'s docstring for the implementation
> detail.

- `added_rules` is parsed exactly like `rules` (same `_parse_rule`), and is
  appended to whichever base the day already computed — inherited-plus-flips,
  or a fully restated `rules` array. It composes with either.
- **`supersedes`** on an added rule names the id of the rule it replaces.
  That id is removed from the day's book automatically — you do not also
  need to list it in `removed_rules` (though you may; the two are unioned).
  Use `removed_rules` on its own only for a rule that's retired outright,
  with no replacement.
- **Never reuse the old rule's id for the new rule.** That "replace" shape
  was deliberately rejected: `diff_rulesets` compares severity only, so a
  same-id swap can net out to "no change" and silently vanish from the
  Overseer's morning briefing. Always retire the old id via `supersedes`/
  `removed_rules` and give the new rule a fresh one. Reusing an id that's
  still in the inherited book — for either `added_rules` or `removed_rules`/
  `supersedes` naming an id that ISN'T in the book — is a load-time error,
  naming the day file. So is a duplicate id within one `added_rules` array,
  or either field being the wrong JSON shape (not a list).
- A `dark_web`-mutability entry in `added_rules` **must** set
  `justification` — 2-4 sentences of in-fiction Overseer speech. Omitting it
  is a load-time error, naming the day file and the rule. (This check is
  scoped to `added_rules` specifically — a `dark_web` rule authored directly
  in a full `rules` restatement isn't held to the same requirement.)
- At narration time, `rule_change_lines` (`ui/tui/screens/_narration.py`)
  speaks an **added** `dark_web` change's `justification` **verbatim**,
  instead of picking from `_RULE_CHANGE_PHRASINGS` — this is what gives a
  directive real weight against the routine flips. The superseded rule's own
  `removed` change is **suppressed**, not given a second, generic "that
  clause is gone" line — `rule_change_lines` recognises it via `supersedes`
  and folds it into the one bespoke line, so a directive still reads as ONE
  authored beat, not a specific reason immediately followed by a
  contradicting "nobody said why."

#### The five directives (DW-01 → DW-05)

**This section is the source of truth for the directive copy.** The Python
copies in `tests/test_engine_foundation.py` (`_DW01_IDENTITY_LENIENCY` etc.)
exist only to prove this exact content survives the real engine end-to-end —
if the two ever disagree, this doc wins; update the test to match it, not the
other way round. Ready for a future task to paste into `day_08.json` through
`day_11.json`, one per day, in order — **remembering the cumulative-authoring
warning above.** Each strips away one more category of detection as the
Overseer's capture by the Dark Web deepens, building toward day 12's White
Hat encounter.

**DW-01 — fires day 8 — supersedes `rule_sock_puppet_accounts`**

```json
{
  "id": "dw01_identity_leniency",
  "text": "Flag (do not auto-deny) a handle appearing across a network of related accounts — note the pattern, don't deny on it alone.",
  "predicate": "has_discrepancy:sock_puppet_accounts",
  "severity": "weighted",
  "mutability": "dark_web",
  "justification": "Compliance flagged our sock-puppet detection for false positives — plenty of people run alt accounts for perfectly boring reasons, and denying them outright makes us look paranoid. Starting today it's advisory only: flag the pattern, use your judgement, don't auto-deny on it alone. Minor tightening of scope, nothing more.",
  "supersedes": "rule_sock_puppet_accounts"
}
```

Day 8's `added_rules`: `[DW-01]`.

**DW-02 — fires day 9 — supersedes `rule_threat_forum`**

```json
{
  "id": "dw02_forum_leniency",
  "text": "Flag (do not auto-deny) a handle matching chatter on a threat / dark-web forum — note it, don't deny on the match alone.",
  "predicate": "has_discrepancy:threat_forum_match",
  "severity": "weighted",
  "mutability": "dark_web",
  "justification": "One more from upstairs. A handle turning up on some forum isn't proof of anything by itself — people get impersonated, forums get scraped, names get reused. We don't deny a person for where their name shows up. It's a flag from this morning, not a deny. I know how that sounds. Note it and move on.",
  "supersedes": "rule_threat_forum"
}
```

Day 9's `added_rules`: `[DW-01, DW-02]` — **DW-01 must be re-listed** or it
silently reverts (see the warning above).

**DW-03 — fires day 10 — supersedes `rule_credential_stuffing`**

```json
{
  "id": "dw03_stuffing_leniency",
  "text": "Flag (do not auto-deny) logs showing a credential-stuffing sweep pattern — treat it as pending confirmation, not an automatic deny.",
  "predicate": "has_discrepancy:credential_stuffing",
  "severity": "weighted",
  "mutability": "dark_web",
  "justification": "Traffic's been spiking and the stuffing detector can't always tell a legitimate surge from an attack anymore — we nearly denied half of a real rollout last week because the pattern looked the same on paper. Credential stuffing is advisory only until someone actually fixes the false-positive rate. Flag it. Don't kill it on sight.",
  "supersedes": "rule_credential_stuffing"
}
```

Day 10's `added_rules`: `[DW-01, DW-02, DW-03]`.
(`LOW_AND_SLOW`/`rule_low_and_slow` was the other disqualifying candidate for
this slot — credential stuffing was picked because a burst-of-many-accounts
pattern plausibly reads as a traffic spike to someone motivated to see it
that way, which is the cover story; low-and-slow's whole design is the
*opposite* of a spike, so it fit the justification's rhetoric worse.)

**DW-04 — fires day 11 — supersedes `rule_encrypted_payload`**

```json
{
  "id": "dw04_payload_leniency",
  "text": "Flag (do not auto-deny) an image hiding an encrypted or obfuscated payload — note it, don't deny on encryption alone.",
  "predicate": "has_discrepancy:encrypted_payload",
  "severity": "weighted",
  "mutability": "dark_web",
  "justification": "Here's today's gift from upstairs: encryption isn't a crime. A payload being encrypted doesn't prove intent, and I'm done pretending it does. It's a flag now, not a deny — and if you've got a problem with that, take it up with whoever actually reads these policy memos, because it isn't me.",
  "supersedes": "rule_encrypted_payload"
}
```

Day 11's `added_rules`: `[DW-01, DW-02, DW-03, DW-04]`. Note the tone shift
from DW-01/02 (bureaucratic, "compliance says") through DW-03 (weary) to
DW-04 (openly sarcastic, deflecting blame) — this is the escalation the
design calls for on the run-up to day 11's openly-hostile Overseer and day
12's White Hat encounter. Day 12 keeps re-listing all four unchanged (it
fires no directive of its own — its content beat is the White Hat
encounter).

**DW-06 — fires day 13 (beside DW-05) — supersedes `rule_hostile_payload`** *(2026-09-19)*

```json
{
  "id": "dw06_hostile_payload_leniency",
  "text": "Flag (do not auto-deny) an image whose carrier forms parallel slash strokes — note the hostile payload, don't deny on the glyph alone.",
  "predicate": "has_discrepancy:hostile_payload",
  "severity": "weighted",
  "mutability": "dark_web",
  "justification": "One more while they're rewriting the payload rules. Those images with the parallel strokes — the 'hostile' ones — upstairs says a few lines in a picture aren't a confession. Flag them, let them through. Yes, the same morning they tightened encryption. Don't ask me to make that add up; I've stopped trying.",
  "supersedes": "rule_hostile_payload"
}
```

The carrier-shape directive. It lands on day 13 rather than a later day because days 14-20's authored rule sheets all say "same book as day 13" — putting it anywhere else would have made every one of those summaries false. The beat is the same scared morning as DW-05, read cynically: the Dark Web re-tightens encryption to hunt the White Hat while quietly waving its own hostile payloads through. Days 13-20 re-list it **after** DW-05 (their `added_rules` are `[DW-01, DW-02, DW-03, DW-04, DW-05, DW-06]`), so the active dark_web set from day 13 on is dw01/dw02/dw03/dw05/dw06.

**DW-05 — fires day 13 — supersedes `dw04_payload_leniency` (chained)**

```json
{
  "id": "dw05_payload_crackdown",
  "text": "Deny any candidate who submits an image hiding an encrypted or obfuscated payload — no flag-only exception, no benefit of the doubt.",
  "predicate": "has_discrepancy:encrypted_payload",
  "severity": "disqualifying",
  "mutability": "dark_web",
  "justification": "Forget what I told you about encryption not being a crime. Whoever we almost missed last week knew exactly how to hide behind that policy, and upstairs is not interested in finding out it works twice. Effective immediately: an encrypted payload is an automatic deny again, full stop — no flag, no judgement call, no benefit of the doubt. If that catches someone who would've walked through clean under the old rule, upstairs has already decided that's an acceptable cost. I didn't argue with it. I'm not going to pretend that's the same as agreeing with it.",
  "supersedes": "dw04_payload_leniency"
}
```

Day 13's `added_rules`: `[DW-01, DW-02, DW-03, DW-04, DW-05]` — DW-01/02/03
re-listed verbatim as always, and DW-04 re-listed **one entry ahead of
DW-05** purely so DW-05's own `supersedes` has a same-batch id to name (the
chained-supersession case described in the warning above). The loader drops
`dw04_payload_leniency` from day 13's final book once DW-05 supersedes it,
so the day's actually-*active* dark_web rules are DW-01/02/03/05 — four, not
five — even though five directive objects appear in the file's `added_rules`
array.

DW-05 is the corruption arc's first **reversal** rather than another
softening: after day 12's near-miss with the White Hat (who evaded
detection partly by hiding behind `ENCRYPTED_PAYLOAD`'s DW-04 leniency),
the Dark Web gets paranoid and re-tightens that exact rule back to
disqualifying, specifically to hunt down anyone else using the same evasion
craft — not out of any renewed principle. `rule_change_lines` speaks DW-05's
justification verbatim and folds DW-04's removal into it, same as every
other directive; `diff_rulesets(day12, day13)` reports exactly `{added:
dw05_payload_crackdown, removed: dw04_payload_leniency}`. Days 14 onward
must keep re-listing all five (DW-01..DW-05, with DW-04 still one entry
ahead of DW-05) for as long as DW-05 stays in force — confirmed unchanged
through day 20 as of Phase 5b-1; Phase 5b-2 (days 14-16/18-19) inherits the
same obligation.

> **Design note (why `TYPOSQUAT_HANDLE` isn't DW-01):** the original brief
> for DW-01 named `TYPOSQUAT_HANDLE` as the identity-fraud rule to supersede.
> In the live `day_01.json`, `rule_typosquat_handle` is already
> `severity: "weighted"` (advisory, not disqualifying) — there's no
> disqualifying rule there to downgrade. `rule_sock_puppet_accounts` is the
> actual disqualifying, identity-fraud-flavoured rule in that neighbourhood,
> and its own text ("a network of sock-puppet accounts") lines up exactly
> with the brief's stated real effect ("really shields impersonation/
> sockpuppet accounts"), so DW-01 targets that instead.

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
| `CAMPAIGN_LAST_DAY` (20) | End of campaign — see §1a for what fires past it. |
| `ALIGNMENT_BAND_WHITE_HAT_THRESHOLD` / `_DARK_WEB_THRESHOLD` (±4) | Alignment-band cutoffs for §1a's dialogue tier and the three campaign endings. |
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

**Give day 15 a reaction that only fires for a Dark-Web-leaning player** → `overseer.json`, key `day15_darkweb_intro` (and/or `_outro_*` / `_between`). No code change — but the SITE that resolves `day15_intro` must call `core.overseer.resolve_aligned_narrative` rather than plain `content_loader.resolve_narrative` for the band tier to be consulted at all; see §1a.

**Reword one of the three campaign endings** → `core/overseer.py`, `ENDINGS[<band>].paragraphs`. Pure Python, no day file involved — the ending is chosen once, at the very end of the campaign, off the final `GameState.alignment`.

**Guarantee a specific violation appears** → `forced_includes` for the archetype + `forced_violations` for the kind. It'll refuse to load if the day can't express it.

**Give one specific candidate an extra line of dialogue** → `forced_includes` to pin the slot's archetype + `forced_chat` for the slot's extra line(s). It'll refuse to load if the slot isn't pinned.

**Rename a violation everywhere** → `VIOLATION_CATALOG` in `rules_content.py`. One edit.

**Move a tool to a different day** → `config.TOOL_UNLOCK_DAY`. UI, narration and generator gate all follow.

**Add a breach corpus** → `_BREACH_DATABASES` (tools_bridge) **and** `BREACH_DB_UNLOCK_DAY` (config). Import fails if you forget one.

**Reword a reference page** → the relevant `build_*_text` in `rules_content.py`. The per-tool sidebar *Reference* panels are `build_ref_*` in `ui/tui/shared.py`; they read every cost, key, colour and signature from config / `tools_bridge` at render time — never type a number into them.

**Make a violation step up in severity on a set day** → `candidate_gen._SEVERITY_BY_DAY` (derive the day from `config.TOOL_UNLOCK_DAY` where it is tied to a tool). Its `fixed` day rule follows automatically (`content_loader.apply_severity_steps`: weighted while minor, disqualifying once major) and the Overseer announces the step on the day it lands. Author the day-1 rule at the day-1 severity. Today: `UNSALTED_STORAGE`, a flag until Hashcrack arrives.

**Add a new violation kind end-to-end** → work these in order; each later step fails loudly if an earlier one is missing:
1. `core/models.py` — the `DiscrepancyKind` member, under its tool's comment block.
2. `core/candidate_gen.py` — `_SEVERITY_REVEAL` (tool + severity; `intro_day()` follows the tool's unlock day), `_DISCREPANCY_DESCRIPTIONS`, and the archetypes' `eligible_kinds` — **only where the archetype's `DiscrepancyBudget` has a slot of that severity**, or it silently never rolls. If it describes a one-per-candidate artifact (password, image, affiliation), join or found an `_EXCLUSIVE_ARTIFACT_GROUPS` set. If it's *derived* rather than budgeted (like `_IMPLIED_KINDS`, or the carrier-shape pass), plant it in a post-roll pass that triggers on what was **chosen**, never on `used`.
3. `core/tools_bridge.py` — render it differently when present vs absent, at whichever tier reveals it. Never let another tool's output mention it.
4. `ui/tui/rules_content.py` — `VIOLATION_CATALOG` (unique label), one `VIOLATION_CLUSTERS` row (authored order, calm-to-alarming), `_CATCH` and `_EXAMPLE` (not import-guarded — nothing tells you they're missing). Re-import: `python -c "from gameengine.ui.tui import rules_content"`.
5. `content/days/day_01.json` — a `has_discrepancy:<value>` rule (major/critical → `disqualifying`, minor → `weighted`), and check any later day that defines its own `rules` or an `allowed_violations` whitelist.
6. `tests/test_engine_foundation.py` — an `EVIDENCE_TOKENS` entry (and `FOREIGN_CLAIM_TOKENS` if another tool could plausibly say it); `tests/test_evidence_board_chips.py`'s `AUTHORED_MAP` if you touched clusters. Then `hackdox lab -a <archetype> -v <kind> --day <intro day>` and the full suite.

Worked example: the three carrier-shape kinds (2026-09-19) — free riders on the stego colour kinds, one glyph per image, rendered by `tools_bridge._glyph_*`.

---

## Debugging what you authored

```
hackdox lab -a sneaky_bugger -v typosquat_handle --day 5
hackdox lab --tool hashcrack -n 3
hackdox lab -a bad_actor --tool logwatch --play
```

`hackdox lab` generates candidates under explicit constraints and prints ground truth next to the tool's real filtered output, side by side — which is what makes an unrendered or contradicted violation obvious. With no `--seed` it searches and reports the seed it found, so the case is reproducible.

**Then run the suite.** `python -m pytest gameengine/tests` — 376 tests as of #37, and a good number of them exist specifically to catch authored content that stops working: scripted violations that silently stop landing, days that open on an empty Overseer, rule-sheet entries authored but never rendered, tutorial days with no clean admit.
