# BUILD PLAN — Batch 4: User Feedback & Content Generation

**Scope:** the `Ready` column of `HackDox Feature Planning` — #61, #62, #63 (playtest fixes) and #15, #16, #43, #44, #45, #46, #47, #49 (content generation).
**Compiled:** 2026-08-18
**Base branch:** `batch-3-UserFeedback-ContentGeneration` · **HEAD** `7fb43b3` · working tree clean
**Verification stance:** every file path, line number, function name and percentage below was read out of the working tree or measured by running the real generator in a container copy. Nothing here is inferred from CLAUDE.md or from the issue text.

> **#48 is in `Todo`, not `Ready`.** #49's own body says *"Depends on the word-banks sub-issue landing first."* You can't close #16 without #48. See Open Question 1.

---

## TL;DR

| Issue | What it really is | Measured severity | Touches engine? | Est. |
|---|---|---|---|---|
| **#62** | Hashcrack fabricates a credential-stuffing burst for *every* weak/leaked-credential candidate | **91/91 (100%)** false claims | rendering only | S |
| **#63** | The platform sweep often omits the GitHub row that is the *only* evidence for EMAIL_GITHUB_MISMATCH | **50/76 (66%)** unflaggable | rendering only | S |
| **#61** | Breach lists are per-candidate, unsorted, and don't include cross-breach-reuse candidates; wants static lists + progressive DB unlock | **98/119 (82%)** contradicted | generator + rendering + config | **L** |
| **#48** | Word banks (`DOMAINS_TRUSTED`, `AFFILIATIONS_FAKED`) | prerequisite for #49 | data only | S |
| **#49** | Per-day approved/denied rule sheet in JSON + Reference-panel rendering | new schema | **schema + loader + UI** | **L** |
| **#43–#47** | Day 1–5 teaching scripts (Overseer copy + scripted candidates + beginner reference copy) | Days 2–20 currently have a **blank** briefing | needs `forced_violations` | **L** |
| **#15** | Epic — closes when #43–47 land | — | — | — |
| **#16** | Epic — closes when #48 + #49 land | — | — | — |

**Two of the three "quick fixes" are genuinely quick. #61 is not a fix, it's a feature** — static, progressively-unlocked breach databases is a new subsystem that changes candidate generation.

**The content half is blocked on three engine gaps that no issue currently tracks.** They're listed in Phase 3 and they are the reason #43–47 can't just be "write some JSON."

---

## The recurring bug class, again

Batch 3 and the playtest fixes named it: *a violation gets asserted, then an artifact is built to match it — instead of the violation being derived from the artifact.* All three of #61/#62/#63 are instances, but #62 is the **inverted** form that hasn't been seen before:

- #63 and #61 are the familiar shape — ground truth exists, the artifact doesn't render it.
- **#62 is the mirror: the artifact renders a violation that ground truth never planted.** The tool tells the player a lie in the player's favour-of-suspicion, and there is no evidence-board row to reconcile it against.

### Why the existing guards didn't catch any of them

`tests/test_engine_foundation.py` has `test_planted_kind_is_visible_in_its_tools_filtered_output` and `test_absent_kind_is_not_claimed_by_its_tools_filtered_output`, which were written for exactly this. Both have holes:

1. **`_filtered_output()` scans one tool per kind** — whichever `candidate_gen._SEVERITY_REVEAL[kind][0]` names. CREDENTIAL_STUFFING is Logwatch-tier, so **Hashcrack's output is never scanned for it.** A tool lying about another tool's violation is invisible to this guard.
2. **Tokens are uppercase enum names.** Hashcrack's claim is lowercase prose (`▲ rapid failure burst — credential stuffing pattern`), so even a cross-tool scan with the current token would miss it.
3. **`limit=1`.** `test_planted_kind_is_visible_...` checks a single candidate. For #63 the pass/fail is a coin flip per candidate, so the suite has been green on a 66% failure rate by luck.
4. **The token can be satisfied by a summary line that isn't evidence.** `_ghostscan_filter_summary_lines` (`tools_bridge.py:638`) prints `▲ EMAIL_GITHUB_MISMATCH` unconditionally when the kind is planted. The guard sees the label and passes; the player sees a label with nothing in the sweep body to corroborate it.

**Phase 0 closes all four holes before any fix lands**, so each fix can be proven against a red test.

---

## Phase 0 — Harden the evidence guards (no issue; prerequisite)

**Files:** `gameengine/tests/test_engine_foundation.py`

1. Split `EVIDENCE_TOKENS` into `EVIDENCE_TOKENS` (must appear in the revealing tool) and a new `FOREIGN_CLAIM_TOKENS: dict[DiscrepancyKind, tuple[str, ...]]` — prose phrases that *any other* tool must never emit for a candidate that doesn't carry the kind. Seed it with `CREDENTIAL_STUFFING: ("credential stuffing",)`.
2. New `test_no_tool_claims_a_violation_another_tool_owns` — for each kind in `FOREIGN_CLAIM_TOKENS`, generate candidates *without* the kind and assert none of the four tool outputs contains any of its phrases.
3. New `test_corroborating_evidence_exists_in_the_sweep_body`, separate from the filter-summary check: for EMAIL_GITHUB_MISMATCH, AFFILIATION_MISMATCH and MISSING_PUBLIC_PROFILE, assert the *body* line (not the summary block) is present. Implement by slicing the output at the `[FILTER] violation summary` divider and searching only above it.
4. Raise `test_planted_kind_is_visible_...` from `limit=1` to `limit=8`, and assert the sweep actually produced ≥ 8 carriers so the guard can't go inert.

**Acceptance:** each new test goes **red** on `7fb43b3` before any fix is applied. Verified by running them on the unmodified tree first.

---

## Phase 1 — #62 · Hashcrack stops fabricating credential stuffing

**Symptom (Nick):** *"The Above log is observed on a candidate with a Weak Credential violation. But the Credential Stuffing violation is not on the Evidence Board."*

**Root cause — `gameengine/core/tools_bridge.py:798`:**

```python
has_cred = has_leaked or has_weak          # L788
...
if has_cred:                               # L798
    # Credential-stuffing burst from external IP
    burst = rng.randint(3, 6)
    ...  violation_kind="stuffing"
```

The burst is emitted for `LEAKED_PASSWORD or WEAK_CREDENTIAL` — it has **never** consulted `DiscrepancyKind.CREDENTIAL_STUFFING`. `_render_hc_log:961` then annotates it `▲ rapid failure burst — credential stuffing pattern` (and `:979` on the explicit-tags path). Meanwhile `_SEVERITY_REVEAL[CREDENTIAL_STUFFING] = (LOGWATCH, "critical")` (`candidate_gen.py:408`), so the kind cannot appear on the Hashcrack evidence board — by design.

**Measured: 91 of 91.** Every single weak/leaked-credential candidate in the sweep got the stuffing burst; not one carried the violation.

Nick's issue offers two dispositions. **Recommended: reinstate as honest evidence, don't remove.** The burst is good log texture and its removal would leave Hashcrack's log flat — but it must be *derived from ground truth*, per the pattern the playtest-fix notes named:

- `if has_cred:` → `if has_stuffing:` where `has_stuffing = CREDENTIAL_STUFFING in kinds`.
- Candidates with a credential violation but no stuffing get the **normal-login** branch (L816) — one `AUTH_OK` from the claimed IP — which is the honest read for "bad password, no attack pattern."
- Keep the annotation text, now that it's true.
- **Open Question 2** covers whether CREDENTIAL_STUFFING should *also* be Hashcrack-revealable.

**Blast radius:** `_hc_candidate_entries` also uses `has_cred` at L832 to pick the HASH_SUBMIT source IP (`ext_ip if has_cred else claimed_ip`). That must follow the same switch or a non-stuffing candidate will submit their hash from an external IP that appears nowhere else in their log — a new orphan signal. Regression-test it.

**Acceptance criteria**
- [ ] No candidate without CREDENTIAL_STUFFING produces a `stuffing`-kinded Hashcrack entry (Phase 0 guard 2, red before / green after)
- [ ] Candidates *with* CREDENTIAL_STUFFING still show the burst in Hashcrack **and** the named violation in Logwatch
- [ ] HASH_SUBMIT source IP agrees with the rest of the candidate's own log lines
- [ ] Full suite green

---

## Phase 2 — #63 · Guarantee the GitHub row when the mismatch is planted

**Symptom (Nick):** *"when this happens with a candidate with a GitHub Email Mismatch violation, there is nothing for the email to be compared against and the player cannot identify an email mismatch."*

**Root cause — `gameengine/core/tools_bridge.py:408`:**

```python
n_appear = rng.randint(1, 2) if has_missing else rng.randint(3, 5)
cand_platforms = set(rng.sample(_GS_LEGIT_PLATFORMS, min(n_appear, len(_GS_LEGIT_PLATFORMS))))
```

`_GS_LEGIT_PLATFORMS` has 8 entries (`:195`); 3–5 are sampled at random. The commit-email row — the only evidence for this kind — is emitted at `:453` **inside `if platform == "GitHub"`**, so when GitHub isn't sampled there is nothing to compare.

**Measured: 50 of 76 (66%)** of EMAIL_GITHUB_MISMATCH candidates render no GitHub row at all.

**Fix — Nick's preferred option, and it's the right one.** Nick's option 2 ("every candidate absent from GitHub is a violation") would collide head-on with MISSING_PUBLIC_PROFILE, which owns "handle barely appears" per the #56 four-way affiliation split. Two kinds, one signal — the exact ambiguity #56 was fixed to remove.

```python
# #63: the commit-email row below is EMAIL_GITHUB_MISMATCH's only evidence,
# and the random sample dropped GitHub 66% of the time — leaving the filter
# summary naming a violation with nothing in the body to corroborate it.
# GitHub is forced into the set whenever the kind is planted. Sampled from
# the remaining platforms so the count (and therefore MISSING_PUBLIC_PROFILE's
# thinned-sweep tell) is unchanged.
```

Keep `len(cand_platforms)` identical so #51's `▲ present on only N of 8 platforms` line does not shift. Draw the remaining `n_appear - 1` from `_GS_LEGIT_PLATFORMS` minus GitHub, using the same `rng` call count so unrelated candidates' noise is untouched — *verify this by diffing a sweep for a non-mismatch candidate before and after.*

**Acceptance criteria**
- [ ] 100% of EMAIL_GITHUB_MISMATCH candidates render a GitHub row with a `commits:` email (Phase 0 guard 3)
- [ ] Platform count distribution unchanged for candidates without the kind
- [ ] MISSING_PUBLIC_PROFILE's `N of 8` line unchanged
- [ ] Full suite green

---

## Phase 3 — #61 · Breach list unification *(the big one)*

Nick's issue has three separable requirements. They differ enormously in cost, and one of them is a genuine new subsystem.

### 3a — Alphabetize *(trivial)*

`get_breach_lists` (`tools_bridge.py:690`) appends entries in RNG order (`:718–726`). Sort each database's entries by email before returning, preserving the `is_candidate_match` flag. The candidate's real email then sorts into place naturally, which is *better* camouflage than a random insert position — and it's what makes scanning the list cheap, which is the point.

### 3b — Static lists for the whole game *(medium)*

`get_breach_lists:700` seeds off `int(candidate.id, 16) ^ 0xB8EA4DB5`. **Every candidate sees six completely different databases** — verified: contents differ between any two candidates, and each DB has a random 18–26 entries. So a player who memorises a list learns nothing, which is precisely the complaint.

Fix: seed the noise from the **game seed** per database index, memoize on `(game_seed, db_index)`, and layer the candidate's email in on top. This changes the signature to `get_breach_lists(candidate, game_seed)`; the only caller is `app.py:1275` (`BreachListPanel.load`), which has the state to hand. Fix the entry count per DB too — a static list that changes length between candidates isn't static.

### 3c — Progressive breach-DB unlock *(large — new subsystem)*

Nick: *"On day 1 the player only has Collection #1 to consider… as difficulty increases more lists will be added. Once a list is added it should not be removed. This introduces a Progressive unlock feature for the Breach Databases relevant to candidate generation (a candidate should not be generated if it is on a locked list)."*

This is structurally the same shape as `config.TOOL_UNLOCK_DAY` and should be built the same way — one config table as the single source of truth for both the panel and the generator:

```python
# config.py — parallel to TOOL_UNLOCK_DAY. The single source of truth for
# which breach databases exist on a given day, for BOTH the Ghostscan panel
# and the generator's DB assignment. A candidate can only ever be planted
# into a database the player can actually open.
BREACH_DB_UNLOCK_DAY: dict[str, int] = { ... }
def breach_dbs_unlocked_by(day_number: int) -> list[str]: ...
```

`_breach_db_for_candidate(candidate_id)` (`:224`) gains a `day_number` parameter and picks only from the unlocked set. It has **three** call sites that must all move together — `get_breach_lists:710`, `_hc_candidate_entries:842`, and the reuse second-DB pick at `:851` — or Ghostscan and Hashcrack will name different databases, which is the bug #61 was filed about in the first place.

The `:851` reuse pick (`_HC_BREACH_NAMES[idx]`, no day awareness) needs the same treatment, **and cross-breach reuse needs at least two unlocked databases to be expressible at all.** That's a hard generation constraint: on any day with fewer than two unlocked DBs, CROSS_BREACH_REUSE must not be plantable. See Open Question 3.

### 3d — Tool continuity: reuse implies a breach hit

Nick: *"Cross breach password Reuse found on the Hashcrack page implies that the candidate is from a breach list on the ghostscan; do they not."* **They do not.**

`get_breach_lists:706`: `should_seed = has_breach or has_leaked` — **CROSS_BREACH_REUSE is absent.**
`_hc_candidate_entries:841`: `if has_leaked or has_reuse:` — emits one or two BREACH_MATCH rows.

**Measured: 98 of 119 (82%)** CROSS_BREACH_REUSE candidates have their email in **no** Ghostscan breach list while Hashcrack names two databases they're supposedly in. (The 21 that work are Bad Actors who happened to also roll BREACH_HIT.)

Nick's instinct — *"any candidate with a Cross breach password Reuse should also have a Breach Hit violation"* — is one of two fixes, and I'd argue against it:

- **Option A (Nick's):** force BREACH_HIT to co-occur with CROSS_BREACH_REUSE in `_roll_discrepancies`. Costs the candidate a *critical* budget slot (`BREACH_HIT` is critical, `:390`), which Clumsy Cutie doesn't have (`budget=DiscrepancyBudget(minor=2, major=1)`, `:233`) — so **CROSS_BREACH_REUSE would become unreachable for Clumsy Cutie**, silently removing the one hygiene-failure archetype it was written for. It also collapses two violations into one signal.
- **Option B (recommended):** add CROSS_BREACH_REUSE to `should_seed` at `:706`. The email appears in the breach lists — which is *true*, that's what reuse means — and BREACH_HIT stays a separate violation about the *email* rather than the *password*. Zero budget impact, zero archetype loss, and it makes Hashcrack and Ghostscan agree, which is the actual complaint.

This is **Open Question 4** and it's the one I'd most like you to overrule me on if you disagree, because it's a design call about what BREACH_HIT *means*, not a bug fix.

**Acceptance criteria (#61)**
- [ ] Each breach database renders alphabetically sorted
- [ ] Two different candidates on the same seed see byte-identical database contents, minus their own seeded email
- [ ] `BREACH_DB_UNLOCK_DAY` in `config.py` drives both the panel and the generator; no candidate is ever assigned a locked database
- [ ] A candidate carrying CROSS_BREACH_REUSE always appears in the Ghostscan breach lists
- [ ] Ghostscan and Hashcrack name the *same* database for the same candidate, on every day (regression test)
- [ ] CROSS_BREACH_REUSE is not plantable on a day with fewer than two unlocked databases

---

## Phase 4 — Engine prerequisites for the content work

**These are not tracked by any issue and #43–#49 cannot be completed without them.** They are the honest reason the content batch is bigger than "write some JSON."

### 4a — Days 2–20 have a blank Overseer

`app.py:3278` and `:3285`: `self._narratives.get(self._day.overseer_intro_key, "")`. `synthesize_day` (`content_loader.py:189`) assigns `overseer_intro_key = f"day{n}_intro"`, and **`content/narratives/overseer.json` contains only the six day-1 keys.** So the briefing on days 2–20 is an empty string. The outro falls back to the literal `"..."` (`:3305`). Only the between-day beat has real generic fallback copy (`:3320`).

This is fine for a synthesized day *after* the tutorial (it's a known placeholder), but it is fatal for Days 2–5 — the exact days #44–#47 are about. Authoring `day_02..05` narrative keys is the content half; giving days 6–20 a non-empty generic fallback is the engineering half, and it should land here rather than as 15 more authored days.

### 4b — `forced_includes` pins an archetype, not a violation

`models.Day:336` — `forced_includes: dict[int, Archetype]`. Every one of #43–#47 asks for *"at least one scripted clear-admit and one clear-deny demonstrating the mechanic just taught."* You cannot express that today: pinning `BAD_ACTOR` to slot 3 gives you *a* Bad Actor, not one carrying BRUTE_FORCE_IN_LOG specifically.

Proposed addition, deliberately parallel to the existing field so the JSON stays diff-able:

```jsonc
"forced_violations": { "3": ["brute_force_in_log"] }
```

→ `Day.forced_violations: dict[int, tuple[DiscrepancyKind, ...]]`, consumed in `_roll_discrepancies` *before* the random roll, still subject to the evidence-tier gate (`intro_day`) so a script can't accidentally teach a violation whose tool isn't unlocked yet. Requires a matching `allowed_violations`-style validation error when a forced kind's `intro_day` is later than the day.

### 4c — No `approved`/`denied` block in the day schema

This is #49's central acceptance criterion and it does not exist. `build_dossier_text` (`rules_content.py:451–472`) reads the lists directly off `tools_bridge._GS_TRUSTED_DOMAINS` / `_GS_SUSPICIOUS_DOMAINS` / `_GS_PRIVACY_DOMAINS` / `_GS_LEGIT_ORGS` and **ignores its `day` parameter entirely** for that section. Needs, in order: JSON schema → `Day` field → `content_loader._parse_*` → a `synthesize_day` default → `rules_content` rendering from the day rather than the module constants.

**Note in passing:** `rules_content.py:462` still tells the player privacy domains are *"flag only with other discrepancies"* — the exact instruction #58 removed from `tools_bridge` because flagging it scores as a false positive. Same bug, second location. Fold into this phase.

---

## Phase 5 — #48 · Word banks

`AFFILIATIONS_LEGIT` / `THIN` / `ELITE` and `DOMAINS_DISPOSABLE` live in `candidate_gen.py:54–95`. `_GS_TRUSTED_DOMAINS` lives in `tools_bridge.py:165`. There is **no `content/word_banks/` directory** despite #48's Ref line, and `DOMAINS_TRUSTED` doesn't exist under that name.

Per #57's lesson — *hand-syncing is how they drifted* — the fix is to **name the existing `_GS_TRUSTED_DOMAINS` as the canonical `DOMAINS_TRUSTED`** in one module and have the other derive from it, exactly as `_GS_SUSPICIOUS_DOMAINS = frozenset(_DISPOSABLE_DOMAINS)` already does. `AFFILIATIONS_FAKED` is new: the pool `AFFILIATION_MISMATCH` draws its *claimed* org from, distinct from `AFFILIATIONS_ELITE` (which #56 made un-fakeable).

Whether these move to JSON under `content/word_banks/` or stay as Python constants is **Open Question 5**.

---

## Phase 6 — #43–#47 · The Day 1–5 teaching scripts *(closes #15)*

With 4a and 4b landed, each day is: author `day_NN.json` + `overseer.json` keys + a beginner pass on that tool's reference tab.

| Issue | Day | New tool | Violations to introduce | Reference tab |
|---|---|---|---|---|
| #43 | 1 | — (Dossier) | DISPOSABLE_EMAIL, HOSTILE_CHAT, UNSALTED_STORAGE, WEAK_ENCRYPTION, AFFILIATION_NOT_STATED | `build_dossier_text` |
| #44 | 2 | Ghostscan | BREACH_HIT, EMAIL_GITHUB_MISMATCH, AFFILIATION_MISMATCH/UNLISTED, MISSING_PUBLIC_PROFILE | `build_osint_text` |
| #45 | 3 | Hashcrack | WEAK_CREDENTIAL, LEAKED_PASSWORD, CROSS_BREACH_REUSE | `build_creds_text` |
| #46 | 4 | Logwatch | BRUTE_FORCE_IN_LOG, CREDENTIAL_STUFFING, AFTER_HOURS_ACCESS, IMPOSSIBLE_TRAVEL, INSIDER_BEHAVIOR, CLAIMED_IP_MISMATCH, LOW_AND_SLOW | `build_logs_text` |
| #47 | 5 | Stegotool | STEGO_PAYLOAD_PRESENT, ENCRYPTED_PAYLOAD, COVERT_C2_CHANNEL + **graduation beat** | `build_stego_text` |

The tool→day mapping is already enforced: `candidate_gen.intro_day` (`:501`) reads `config.TOOL_UNLOCK_DAY`, so a violation cannot be planted before its tool's day. **The teaching order in #15 and the gate in `config.py` already agree** — no reconciliation needed.

**`day_01.json` needs `allowed_violations` set.** It currently carries all 27 rules with no whitelist (`allowed_violations: ()`), so Day 1 plants anything the tier gate allows. For a taught Day 1 the whitelist should be explicit — this is also the open follow-up from Batch 1 ("day_01.json mix rebalance → #32/#15").

The graduation beat (#47) is a distinct screen state, not just another line: it has to read differently from a briefing. Cheapest honest implementation is a dedicated `day5_graduation` narrative key played on the **EOD** screen of day 5 rather than the day-6 briefing, so it lands as a closing beat.

---

## Phase 7 — #49 · Per-day rule sheets *(closes #16)*

With 4c landed, author the `approved`/`denied` block per day and render it. Ramp per #16: Day 1 tiny, later days add domains/affiliations/flips. Rule IDs stay in the `GS-/LW-/HC-/ST-/DS-` convention — **note that `day_01.json` currently uses `rule_breach`-style ids, not that convention**, so either the convention or the existing ids has to give (Open Question 6).

---

## Recommended sequencing

| Block | Contents | Why here |
|---|---|---|
| **1** | Phase 0 → Phase 1 (#62) → Phase 2 (#63) | Contained rendering fixes with hard numbers; the guards make them provable. Ships as three commits and could go out today. |
| **2** | Phase 3 (#61) | Touches the generator and adds config state. Needs its own space. |
| **3** | Phase 4 (engine prereqs) + Phase 5 (#48) | Unblocks everything downstream. Nothing player-visible ships here. |
| **4** | Phase 6 (#43–47 → closes #15) | The bulk of the authoring. Days can land one at a time. |
| **5** | Phase 7 (#49 → closes #16) | Last, because it re-renders content authored in block 4. |

Blocks 1 and 3 can run in parallel with each other; nothing else can.

---

## Cross-cutting risks

- **`tools_bridge.py` is touched by Phases 1, 2, 3 and 4c.** Four issues, one 2432-line file. Commit in phase order and re-run the whole suite each time, not just the touched test.
- **RNG call-count changes shift every downstream candidate.** `_ghostscan_sweep_lines` and `get_breach_lists` both walk a shared `rng`. Adding or removing a single `rng.choice` re-rolls noise for every candidate generated after it. Every fix here must preserve call counts or explicitly accept the reshuffle — and the sweep-diff check in Phase 2 is the pattern for proving it.
- **`_breach_db_for_candidate` has three call sites** across two tools. They are the mechanism by which the two pages agree. Change one, change all three.
- **Day-1 content is the template for every synthesized day.** `synthesize_day` does `template = load_day(1)` (`content_loader.py:161`). Adding `allowed_violations` to `day_01.json` in Phase 6 therefore **silently constrains days 6–20 as well**. Either set it and accept that, or have `synthesize_day` explicitly clear it — decide deliberately rather than discovering it.
- **Branch is unpushed and carries Batches 2 + 3.** The merge reconciliation against `main`'s `b533dfb "Candidate Generation Anomalies"` (which also edits `candidate_gen.py`) is still outstanding from Batch 3, and Phase 3 edits that file again.

---

## Open questions

**1. #48 is in `Todo` while #49 (which depends on it) is in `Ready`.** Pull #48 into this batch, or defer #49 to the next one?
→ *Recommend:* pull #48 in. It's small, it's data, and #16 can't close without it.

**2. #62 — should Hashcrack also be able to reveal CREDENTIAL_STUFFING?** Right now it's Logwatch-only, and the honest fix makes Hashcrack's log quieter for credential candidates.
→ *Recommend:* keep it Logwatch-only and let the burst appear in Hashcrack **only** when the kind is genuinely planted. Two tools showing the same event from different angles is good design; two tools *owning* it is how the #56 naming mess happened.

**3. #61 — what's the breach-DB unlock schedule?** Six databases exist. Day 1 = Collection #1 only, per your issue. Suggest `{Collection #1: 1, LinkedIn: 3, RockYou: 5, Dropbox: 8, Adobe: 12, MyFitnessPal: 16}` — one per tutorial beat, then spaced through the campaign. **CROSS_BREACH_REUSE needs two DBs, so it becomes plantable on day 3 rather than day 3-by-tool-gate.**

**4. #61 — reuse ⇒ breach hit, or reuse ⇒ seeded in the lists?** Full argument in Phase 3d.
→ *Recommend:* Option B (seed the email, keep the violations separate). Option A costs Clumsy Cutie the violation entirely.

**5. #48 — word banks as JSON under `content/word_banks/`, or stay as Python constants?**
→ *Recommend:* stay in Python, single-source them (one module owns, the other derives). #57's drift bug was caused by two hand-synced copies, and moving to JSON adds a third surface. #16's "keep it data-driven" intent is satisfied by the per-day JSON in #49, which is where authoring actually happens.

**6. #49 — rule IDs.** #16/#49 want `GS-/LW-/HC-/ST-/DS-`; `day_01.json` ships `rule_breach`, `rule_github_mismatch`, … and `mutate_variable_rules` hashes on `rule.id` for its flip phase (`content_loader.py:138`), so **renaming ids changes which rules flip on which days.** Rename anyway, keep the current ids, or carry a display-id alongside?
→ *Recommend:* keep the ids, add a `ref` field for the DB-facing code. Cheapest, and it doesn't perturb the flip schedule.

**7. Branch and commit granularity for this batch.** Continue on `batch-3-UserFeedback-ContentGeneration`, or cut a new branch? Default is one commit per issue.

---

# SHIPPED — 2026-08-18

Branch `batch-3-UserFeedback-ContentGeneration`, base `7fb43b3`. **Not pushed.**

| Commit | Issue | What landed |
|---|---|---|
| `e834188` | **#62** | Hashcrack stuffing burst derived from `CREDENTIAL_STUFFING` instead of `has_cred`; HASH_SUBMIT source IP follows the same switch. New `FOREIGN_CLAIM_TOKENS` guard scanning all four tools for prose claims. |
| `af5361f` | **#63** | GitHub swapped into the sweep's platform set when the mismatch is planted, count preserved. New sweep-body guard that ignores the filter summary. |
| `4305ef2` | **#61** | `BREACH_DB_UNLOCK_DAY` + progressive unlock; static cached noise keyed on the game seed; alphabetized fixed-length lists; `breach_dbs_for_candidate()` as the one source both tools read; reuse blocked below two corpora. |
| `9806dd4` | **#15, #43–47, #48, #49** | Days 1–5 authored; `forced_violations` and `rule_sheet` added to the day schema; generic Overseer fallback so no day is silent; word banks single-sourced. Closes **#15** and **#16**. |

**Tests: 162 → 185 pass**, plus 16/16 on the legacy runner.

## Measured, before → after

| | before | after |
|---|---|---|
| #62 — Hashcrack claims stuffing with no ground truth | 91/91 (100%) | **0** (17 true claims, 0 missing) |
| #63 — mismatch carriers with no GitHub row | 50/76 (66%) | **0/76** |
| #61 — reuse carriers in no breach list | 98/119 (82%) | **0/149** |
| #61 — Ghostscan/Hashcrack corpus disagreements | — | **0** |
| Scripted tutorial violations landing | n/a (impossible) | **25/25 seeds × 30 slots** |
| Days opening on a blank Overseer | 2–20 | **none** |

## Answered questions

1. **#48 in or out?** → **ANSWERED: in.** Shipped in `9806dd4`; #16 closes.
2. **Hashcrack revealing CREDENTIAL_STUFFING?** → **ANSWERED: no.** Logwatch-only; the burst appears in Hashcrack only when genuinely planted.
3. **Breach-DB unlock schedule.** → **ANSWERED:** `{Collection #1: 1, LinkedIn: 3, RockYou: 5, Dropbox: 8, Adobe: 12, MyFitnessPal: 16}`. Day 3 is load-bearing — it's when reuse becomes expressible.
4. **Reuse ⇒ breach hit, or ⇒ seeded in the lists?** → **ANSWERED: seeded** (Nick, against his own first instinct, on the Clumsy Cutie budget argument).
5. **Word banks JSON or Python?** → **ANSWERED: Python**, single-sourced. Per-day JSON is where authoring happens.
6. **Rule IDs.** → **ANSWERED: keep `rule_*`.** Renaming changes `mutate_variable_rules`'s flip phases (it hashes `rule.id`), so a rename would silently reschedule which rules flip on which mornings. The `GS-/LW-/HC-` convention can ride along as a display `ref` field if it's still wanted.
7. **Branch / granularity.** → **ANSWERED:** continue on `batch-3-UserFeedback-ContentGeneration`, one commit per issue.

## Corrections to this plan, found while building

- **Phase 4's warning that `day_01.json`'s `allowed_violations` would leak into days 6–20 was wrong.** `synthesize_day` sets `allowed_violations=()` explicitly. What *did* leak was into the **tests** — seventeen of them used `load_day(1)` as a generic fixture and silently started receiving Day 1's tutorial script. Fixed with an explicit `unconstrained_day()` helper.
- **Phase 3's estimate of #61 as "the big one" held**, but 3c turned out cheaper than expected because `TOOL_UNLOCK_DAY` was a ready-made template.
- **`test_cross_breach_reuse_is_not_plantable_below_two_databases` was inert as first written** — under the shipped schedule the constraint and the tier gate bind on the same day, so it passed with the constraint deleted. It now monkeypatches the unlock table to separate them.
- **The `run_foundation_tests` Sneaky Bugger test was asserting something no longer true** ("entirely tool-only") and passing only on a lucky `SEED`; `WEAK_ENCRYPTION` joined that archetype's pool at some point. Rewritten to the property that actually holds: its *disqualifying* evidence is always behind a tool.

## Not done, deliberately

- **`_UNLOCK_LINES` in `app.py` is still marked PLACEHOLDER.** The Day 2–5 briefings now introduce each tool properly in `overseer.json`, so the unlock line is a second, shorter announcement of the same thing. Worth either rewriting or moving into `overseer.json` — it's the last Overseer copy still living in Python.
- **The `b533dfb` merge reconciliation against `main`** is still outstanding from Batch 3, and this batch touched `candidate_gen.py` again.
- **Days 6–20 remain synthesized** with generic Overseer copy. That's the designed floor, and #39/#40/#41 are where authored replacements go.

## Smoke-test checklist

- [ ] Day 1: slot 1 is a disposable-email deny, slot 3 shows a plaintext password on the dossier, slot 5 is hostile in chat. No Sneaky Bugger.
- [ ] Day 2 briefing introduces Ghostscan; breach panel shows **one** database (Collection #1), alphabetized.
- [ ] Day 3: panel shows **two** databases; the reuse candidate's email is findable in both, and Hashcrack names those same two.
- [ ] Day 4: a weak-password candidate no longer shows an AUTH_FAIL burst; the stuffing candidate does.
- [ ] Day 5: three stego candidates, one per signature colour; graduation copy plays.
- [ ] `R` overlay, Rules tab: the day's summary and plain-language notes appear above the ruleset.
- [ ] `R` overlay, Dossier tab: "today's rule sheet" block above the full reference lists.
- [ ] Day 7+ (synthesized): briefing and end-of-day both show generic copy, never blank and never `...`.
