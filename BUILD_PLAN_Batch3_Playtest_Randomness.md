# BUILD PLAN — Batch 3: Playtest fixes & randomness/variation

**Scope:** issues #50, #51, #52, #53, #54 (HackDox Feature Planning → Ready)
**Date:** 2026-08-17
**Intended base:** `batch-2-difficulty-curve-replayablity` @ `049bd80`
**Verification basis:** every path, symbol and line number below was read from the source. ⚠️ **The device bridge dropped partway through this audit** — see "Blocked on the bridge" at the bottom. The audit was completed against the staged copy of the working tree taken at `049bd80`; I could not re-confirm live git state at the end.

---

## TL;DR

| Issue | What it actually is | Real work? | Est. |
|---|---|---|---|
| **#50** Split General from Dossier rules | Real but contained. `build_rules_text` is **226 lines producing 9 sections** while the other four tabs are ~60 each. Plus tab-follows-page and scroll persistence. | UI | M |
| **#51** Relocate Missing Public Profile | Correct diagnosis, and **worse than filed** — it isn't just mis-catalogued, it's mis-*tiered*, which makes it unflaggable on Day 1. | 1-line tier + catalog | S |
| **#52** Tools generation CLI | Genuinely new. A controlled-generation command so candidate bugs stop needing a lucky seed. | new CLI | M |
| **#53** Typosquat rework | The violation is **entirely fake today** — nothing in the generator makes the handle resemble anything. | generator + render | M |
| **#54** Stegotool tweak | Real, and there's a base-tier design bug behind it: the free tint already gives away the exact zone. | generator + render | M |

Three of the five are the same underlying story: a violation whose *evidence* doesn't match its *claim*. That's the fourth, fifth and sixth instance of the class the new tier guard was written for — and #51 and #53 are in the blind spots that guard deliberately leaves.

---

## Phase 1 — #51: Missing Public Profile is mis-tiered, not just mis-filed

### What the issue says
> "Currently listed under Dossier when there is no way to confirm the violation without the ghostscan tool"

Correct. And the consequence is bigger than a catalog entry.

### Root cause (traced in the code)

`candidate_gen._SEVERITY_REVEAL[MISSING_PUBLIC_PROFILE]` is `(ToolName.DOSSIER, "minor")` — `candidate_gen.py:352`.

But there is **no dossier evidence for it whatsoever**. The dossier's `claimed_github` is set at `candidate_gen.py:873`:

```python
claimed_github=handle if has_github else None,
```

…where `has_github = spec.handle_style != "elite"`. It keys off the *archetype's handle style*, **not** off whether `MISSING_PUBLIC_PROFILE` was planted. So a candidate carrying the violation still shows a perfectly normal GitHub handle on the dossier.

The only actual evidence is in the Ghostscan sweep — `_ghostscan_sweep_lines` at `tools_bridge.py:352`:

```python
n_appear = rng.randint(1, 2) if has_missing else rng.randint(3, 5)
```

The candidate appears on 1–2 platforms instead of 3–5. That is a Ghostscan-only tell.

### The consequence the issue doesn't mention

Because the kind is tiered `DOSSIER`, `intro_day()` returns **1** — so #31's evidence-tier gate happily plants it on Day 1, when Ghostscan is locked until Day 2.

Measured over 600 generated Day-1 candidates of the two archetypes that can roll it (Clumsy Cutie, White Hat): **300 of 600 carried `MISSING_PUBLIC_PROFILE` with Ghostscan locked.** Every one of those is an unflaggable violation that still counts for scoring.

This is the same failure mode as `AFFILIATION_MISMATCH` (`a6ad3b0`) and the stego artifact collision (`049bd80`), and it is specifically in the blind spot of the guard added in `049bd80` — that guard excludes Dossier-tier kinds on the grounds that their evidence is structural. A kind that *claims* to be Dossier-tier but isn't slips straight through.

### Implementation

- `candidate_gen._SEVERITY_REVEAL[MISSING_PUBLIC_PROFILE]` → `(ToolName.GHOSTSCAN, "minor")`. This is the only functional change; `intro_day()` derives from it and gates the kind to Day 2 automatically.
- `rules_content.VIOLATION_CATALOG`: move from the `DOSSIER` group to `OSINT` (`rules_content.py:35`).
- Add `MISSING_PUBLIC_PROFILE` to `EVIDENCE_TOKENS` in the test suite — now that it's tool-tier, the completeness guard demands it, which is the point.
- Its Ghostscan evidence needs an actual **filter annotation**. Today the reduced platform count is the only signal and nothing ever names it, so it fails the present-when-planted guard the moment it becomes tool-tier. Add a `▲ MISSING_PUBLIC_PROFILE` line to `_ghostscan_filter_summary_lines` and a sweep annotation noting the thin platform presence.

Precedent: this is exactly the `CLAIMED_IP_MISMATCH` → Logwatch move Nick made on 2026-08-16, including the knock-on that a Day-1 weighted rule goes inert until the tool unlocks. Day content already tolerates that.

### Acceptance criteria
- [ ] `MISSING_PUBLIC_PROFILE` is Ghostscan-tier; `intro_day()` returns Ghostscan's unlock day
- [ ] Listed under OSINT on the rules page, not DOSSIER
- [ ] Ghostscan's filter names it; the sweep annotates the thin platform presence
- [ ] No Day-1 candidate can carry it (regression test — this currently fails 50% of the time)
- [ ] Declared in `EVIDENCE_TOKENS`; both directions of the tier guard pass

---

## Phase 2 — #53: the typosquat violation is fake

### What the issue says
> "The violation is pointless and only caught because it is literally spelt out to the player."

Stronger than that: **the handle is not a typosquat of anything.**

### Root cause

`_make_handle` (`candidate_gen.py:517`) is the only thing that builds a handle, and it is purely a function of the candidate's own name plus their archetype's style:

```python
if style == "elite":
    leet = {"a":"4","e":"3","i":"1","o":"0","s":"5"}
    return "".join(leet.get(c,c) for c in (f+l)) + str(rng.randint(10,99))
```

Nothing consults `AFFILIATIONS_ELITE`, nothing consults the discrepancy list. `TYPOSQUAT_HANDLE` is planted in ground truth (`candidate_gen.py:262/291`, Bad Actor and Sneaky Bugger, **major**) and the handle is generated identically to any other candidate's.

So the entire observable evidence is one static line in the free identity block — `tools_bridge.py:305`:

```
?  handle resembles a trusted org/person -- possible typosquat
```

That line is printed for free, before any ⏱ is spent, and it is the *only* tell. Nick's "literally spelt out" is exact: the player isn't detecting anything, they're reading a label. And a major violation is being awarded for it.

### Implementation

**Generation.** After the affiliation is chosen, if `TYPOSQUAT_HANDLE` is planted, derive the handle from a *different* elite org than the one claimed — a lookalike of a real listed professional affiliation. A small deterministic mutation set over the org's canonical handle form: character swap (`rn`→`m`), digit-for-letter (`o`→`0`), doubled letter, dropped letter, adjacent transposition. Store the squatted target so the filter can name it.

This needs a field to carry the target. `Dossier` is the natural home (it's the visible packet) but the *target* is ground truth, not a claim — so it belongs on the `Discrepancy` or in a new engine-only dossier field mirroring how `password_plain` already works (`models.py:181`).

**Severity.** `_SEVERITY_REVEAL[TYPOSQUAT_HANDLE]` → `"minor"` (from `"major"`). Knock-on: the Bad Actor's budget is `major=2, critical=1` and the Sneaky Bugger's is `major=1, critical=1` — **neither has a minor slot**, so demoting this kind removes it from both archetypes entirely unless their budgets change. That's a design decision, not an implementation detail → **Open question 1.**

**Rendering.** Delete the free give-away line at `tools_bridge.py:305`. On the filter run, name the squatted target: `▲ TYPOSQUAT_HANDLE — handle mimics <org>'s handle format`. Base run shows the handle plainly next to the claimed org and lets the player notice.

### Acceptance criteria
- [ ] A typosquat candidate's handle is a deterministic lookalike of a *listed* professional affiliation
- [ ] The squatted target is recorded and named by the filter
- [ ] Severity is minor; the archetype budget change from Open question 1 is applied
- [ ] The free "possible typosquat" identity line is gone
- [ ] Generation stays a pure function of `(seed, day, slot)`
- [ ] Tier guard still passes both directions

---

## Phase 3 — #54: Stegotool clumping, and the tint that gives it away

### What the issue says
> "The pixels representing violations should be clumped together in a region… segmented rectangles grouped together in strange ways. The blue highlight upgrade… should highlight [that] region (and an additional buffer) blue, to indicate the general but not exact area."

### Current implementation

`build_stego_image` (`tools_bridge.py:2019`) makes the zone one axis-aligned rectangle and fills it with **uniform independent random noise** — `tools_bridge.py:2076`:

```python
carrier = frozenset(
    (x, y)
    for y in range(hz_y, hz_y + hz_h)
    for x in range(hz_x, hz_x + hz_w)
    if carrier_rng.random() < density
)
```

Every cell is an independent coin flip. There is no structure to read — which is why it reads as static rather than as a hidden payload.

### The design bug behind the ask

The free tier **already tints the exact zone blue** — `app.py:1449`:

```python
elif zone_cell:
    if self.tint_boost:      # Spectral Lens upgrade
        b = min(255, b + 70); r = max(0, r - 30)
    else:
        b = min(255, b + 35); r = max(0, r - 15)
```

`zone_cell` is exact zone membership. So today, before spending anything, the player is shown the precise rectangle — and the 30 HD$ Spectral Lens upgrade only makes that same exact rectangle *bluer*. The stamp minigame is being solved for free, and the upgrade buys almost nothing.

Nick's ask therefore only makes sense if the base tier stops revealing the exact zone. Otherwise "general area + buffer" is strictly *worse* than what the base tier already hands over. → **Open question 2.**

### Implementation

**Clumped carrier.** Replace the uniform fill with N sub-rectangles inside the zone (N scaling with payload type: plaintext → 1–2 large, encrypted → 2–4 medium, C2 → 4–7 small and scattered), each filled at high density, positioned by a seeded walk so they overlap and abut irregularly. Total cell count is still calibrated to `density` so `STEGO_STAMP_RESOLVE_COVERAGE` and the anomalous-cell readout keep their current balance.

**Tint.** Split "exact zone" from "advertised region". Add a dilated bounding region (zone + buffer of 2–3 cells, clamped to the grid) to `StegoImageData`. The Spectral Lens tints *that*; base tier tints nothing (per Open question 2). The renderer's `zone_cell` check at `app.py:1449` becomes a `hint_region` check, and the exact-zone highlight stays where it belongs — behind an actual stamp.

### Acceptance criteria
- [ ] Carrier cells form clumped segmented rectangles, not uniform noise
- [ ] Total carrier count still tracks `density`; resolve coverage balance unchanged
- [ ] Spectral Lens tints a buffered region that does **not** disclose the exact zone
- [ ] Base tier's exact-zone disclosure resolved per Open question 2
- [ ] Deterministic per candidate; same seed → same image
- [ ] Every stego kind still resolves and is still named (tier guard)

---

## Phase 4 — #50: split the rules page, remember the tab and the scroll

### Current implementation

`build_rules_text` (`rules_content.py:201–426`) is **226 lines** and emits nine sections: today's ruleset, daily quotas, computing hours, site health, HackDollar$/credits/upgrades, evidence board, alignment, quick cases, the DOSSIER violation table (`:380`), plus the email-domain and affiliation reference blocks (`:401–403`). `build_osint_text`, `build_creds_text`, `build_logs_text` and `build_stego_text` are ~60 lines each.

`RulesScreen` (`app.py:1591`) hard-codes five `TabPane`s in `compose()` with no initial-tab argument, and each pane wraps a fresh `VerticalScroll` — so both the active tab and every scroll position reset on each open. It's pushed from three places (`app.py:2574`, `:2624`, `:2718`), none of which pass the current page.

`_PAGE_TOOL = [None, "ghostscan", "hashcrack", "logwatch", "stegotool"]` (`app.py:301`) already gives the page→tool mapping the tab-follows-page behaviour needs.

### Implementation

- **New `Dossier` tab.** Split `build_rules_text` into `build_rules_text` (ruleset, quotas, economy, health, HD$, evidence board, alignment) and `build_dossier_text` (quick cases, DOSSIER violation table, encryption strength, email domains, affiliations). Pure extraction — no copy rewritten.
- **Tab follows page.** `RulesScreen(day, evidence_state, initial_tab=...)`; set `TabbedContent.active` in `on_mount`. Map via a `_PAGE_TAB` list parallel to `_PAGE_TOOL`, so page 0 → `tab-dossier`, page 4 → `tab-logs`, etc. All three push sites pass `self._page_index`.
- **Scroll persistence.** `RulesScreen` is re-instantiated per open, so state must live outside it — a small dict on the app (`{tab_id: scroll_y}`), written on dismiss and restored in `on_mount`. Cheapest correct option; a persistent screen instance would fight the modal lifecycle.

### Acceptance criteria
- [ ] Rules tab no longer carries dossier reference material; new Dossier tab holds it
- [ ] Opening from a tool page lands on that tool's tab; from the candidate page, the Dossier tab
- [ ] Scroll position per tab survives close/reopen within a session
- [ ] No copy lost in the split — every band still reachable

---

## Phase 5 — #52: controlled-generation CLI

### Current implementation

`hackdox.py` has four commands: `new-game` (`:39`), `simulate` (`:61`, whole day, by-the-book auto-verdicts), `inspect` (`:118`, one candidate by seed/day/slot), `play` (`:157`). None can *constrain* what gets generated — `simulate` and `inspect` roll whatever the seed gives.

The constraint machinery already exists and is unused from the CLI: `Day.forced_includes` pins an archetype to a slot (#32), `Day.allowed_violations` whitelists kinds (#32), and `Day.difficulty_band` drives the tier bias (#4). Every audit sweep in this session and the last built these by hand with `dataclasses.replace` — which is precisely the friction #52 is about.

### Implementation

New `lab` command:

```
hackdox lab --archetype sneaky_bugger --violation typosquat_handle \
            --tool ghostscan --day 5 --count 3 [--seed N] [--play]
```

- `--archetype` (repeatable) → `forced_includes` across the requested slots
- `--violation` (repeatable) → `allowed_violations`, intersected with the day's tier gate as usual
- `--tool` → filter to kinds that tool reveals, so "show me Ghostscan cases" needs no kind list
- `--day` → drives the tier gate, difficulty band, volume curve and cost/reward curves
- `--seed` → default: search seeds until the constraints are actually satisfiable, and **report which seed was used** so the case is reproducible
- default output: dossier + ground truth + **the filtered output of the revealing tool**, so generation and rendering are visible side by side. That's the pairing that would have surfaced the affiliation bug immediately.
- `--play` launches the TUI on the synthesized day rather than dumping text

Build this on `content_loader.synthesize_day` (#17) rather than a parallel Day builder, so the lab exercises the same code path as real play.

**Ordering note:** #52 should be built **last but used first** in future sessions. It doesn't unblock #51/#53/#54 — those are already diagnosed — but every one of them would have been *found* faster with it.

### Acceptance criteria
- [ ] `lab` constrains archetype, violation and tool, and honours `--day`
- [ ] Reports the seed used; re-running with it reproduces the case exactly
- [ ] Prints dossier + ground truth + the revealing tool's filtered output
- [ ] `--play` starts a real shift on the constrained day
- [ ] Built on `synthesize_day` — no parallel Day construction to drift

---

## Recommended sequencing

1. **#51** — smallest, and it's an active correctness bug affecting half of Day-1 Clumsy Cutie/White Hat candidates.
2. **#53** — generator + render, touches `candidate_gen` and `tools_bridge`.
3. **#54** — same two files; do it after #53 so both generator changes land in sequence rather than tangled.
4. **#50** — pure UI, isolated to `app.py` + `rules_content.py`. Can run in parallel with 1–3.
5. **#52** — last; consumes the shape everything else settled.

---

## Cross-cutting risks

- **`candidate_gen.py` is touched by #51, #53 and #54**, and per project memory this branch still doesn't include main's `b533dfb "Candidate Generation Anomalies"`, which also edits that file. The merge reconciliation debt grows with this batch.
- **#53 and #54 both change what the player sees for an existing violation.** The tier guard from `049bd80` covers "is it named", not "is it findable" — a human playtest pass is the only real check on #54's clumping.
- **#51 makes a Day-1 rule inert until Day 2**, matching the `rule_claimed_ip`/`rule_weak_credential` precedent. Day 1 loses one of its Clumsy Cutie minor options; `day_01.json`'s mix may want a look (already an open follow-up from Batch 1).
- **Determinism.** #53 and #54 both add seeded structure. Same-seed regression assertions required in both.

---

## Open questions

**1. #53 — demoting `TYPOSQUAT_HANDLE` to minor removes it from both its archetypes.**
Bad Actor's budget is `major=2, critical=1`; Sneaky Bugger's is `major=1, critical=1`. Neither has a minor slot, so a minor kind can never be selected for them. Options: give one or both a minor slot; move the kind to archetypes that have minor slots (Day-to-Day, Clumsy Cutie — but a typosquat is deliberate deception, which fits neither); or keep it major and rely on the generation rework alone to earn the severity.
*Recommendation: give the Sneaky Bugger a minor slot.* A subtle, deliberately-deceptive handle is exactly its register, and the reworked violation is a genuine read rather than a label — that's what justifies keeping it in play at all.

**2. #54 — should the base tier still tint the exact zone at all?**
It currently does, which makes the Spectral Lens nearly worthless and the stamp sweep close to free. Options: base tints nothing (sweep blind; the upgrade buys the buffered region); base tints the buffered region faintly and the upgrade strengthens it; or leave base as-is and accept the upgrade is cosmetic.
*Recommendation: base tints nothing.* It restores the point of both the stamp minigame and the 30 HD$ upgrade, and it's the reading that makes your "general but not exact" ask coherent.

**3. #51 — should `MISSING_PUBLIC_PROFILE` keep any dossier presence?**
Moving it to Ghostscan-tier is unambiguous. But you could *also* make the dossier honest by having the generator clear `claimed_github` when the kind is planted — giving it a genuine dossier breadcrumb and arguably justifying the original tiering.
*Recommendation: no — move it cleanly to Ghostscan.* A blank GitHub field is already what `MISSING_PUBLIC_PROFILE`'s own rule predicate (`missing_field:claimed_github`) tests, and overloading the two would make the elite-handle archetypes (whose GitHub is legitimately absent) read as violations.

**4. Branch.** Continue on `batch-2-difficulty-curve-replayablity`, or cut a `batch-3-` branch off it?
*Recommendation: a new `batch-3-playtest-fixes` branch off `049bd80`* — Batch 2 is a coherent, reviewable unit and these are unrelated playtest fixes.

---

# SHIPPED — 2026-08-17

Branch `batch-2-difficulty-curve-replayablity` (Nick chose to continue rather than cut `batch-3-`), based on `049bd80`. **Not pushed.**

| Issue | Commit | Title |
|---|---|---|
| #51 | `253d77b` | Retier Missing Public Profile to Ghostscan and give it real evidence |
| #53 | `242a88d` | Make typosquat handles actual lookalikes and demote to minor |
| #54 | `9a63146` | Clump stego carriers and move the blue tint off the exact zone |
| #50 | `a06309a` | Split the Dossier reference off the Rules tab, follow the page, keep scroll |
| #52 | `c25aaa6` | Add the lab command for controlled candidate generation |

## Decisions (Nick, 2026-08-17)

1. **#53 — Sneaky Bugger gains a minor slot** (`minor=1, major=1, critical=1`). `TYPOSQUAT_HANDLE` was *removed* from Bad Actor rather than left listed-but-unreachable, since that archetype has no minor slot and quiet deception is a poor fit for it anyway.
2. **#54 — base tier tints nothing.** The Spectral Lens is now the only thing that tints, and it tints a buffered region (`STEGO_HINT_BUFFER = 3`).
3. **#51 — clean move to Ghostscan.** No dossier breadcrumb added.
4. **Branch — continued on `batch-2-difficulty-curve-replayablity`** rather than cutting a new one.

## Verification

- **142/142 tests pass** (was 126 at the start of the batch), green after every commit. New files: `test_rules_page.py` (7 tests, headless Textual pilot), `test_lab_cli.py` (9 tests, typer CliRunner).
- Every touched file md5-compared between the tested copy and the working tree before each commit — **no mount truncation**.
- `#51` and `#53` fixes each verified by reverting the change in a scratch copy and confirming the guards go red first.

## What the audit found beyond what was filed

- **#51 was mis-*tiered*, not just mis-filed.** `MISSING_PUBLIC_PROFILE` was `(DOSSIER, minor)` but the dossier's `claimed_github` comes from the archetype's handle style, not from whether the kind was planted — so it had *no* dossier evidence. `intro_day()` therefore returned 1 and the #31 gate planted it on Day 1 with Ghostscan locked: **300 of 600** generated Day-1 Clumsy Cutie / White Hat candidates carried an unflaggable violation that still scored.
- **#53's violation was entirely fake.** `_make_handle` never consulted the affiliation list. The only evidence was a free line naming the violation outright — and it paid *major*.
- **#54 had a design bug behind the ask.** The free tier already tinted the exact zone, so the stamp sweep was near-free and the 30 HD$ Spectral Lens had nothing to sell.
- **#50's imbalance was measurable:** `build_rules_text` was ~226 builder lines / 9 sections against ~60 for every other tab.

## Bugs found *while* implementing

- **#54, first attempt:** forced the carrier cell count to match the old `density` by padding with random spare cells — which destroyed the clumping it was meant to preserve. The premise was wrong: `density` does not feed resolve balance (`evaluate_stamp` computes coverage from *zone* cells), so it is now measured from the generated blocks instead.
- **#54, second attempt:** blocks anchored at a random corner marched into one edge and clamped to full zone width, rendering as scanline bands — and a sweep could resolve the zone **without ever touching a carrier cell**, so the player never saw the signature colour. Blocks now cap at ~55% of the zone per axis and anchor at the zone centre. Verified 0/373 candidates can resolve blind.
- **Two test-precision errors of my own**, both fixed rather than worked around: #53's lookalike check compared characters positionally (wrong for insert/delete squats — now Levenshtein), and #50's content-split check matched bare substrings and tripped on upgrade-shop copy (now matches section headings).

## Smoke-test checklist

- [ ] Day 1 plays unchanged; no Clumsy Cutie carries Missing Public Profile before Day 2
- [ ] Rules overlay opens on the Dossier tab from the candidate page, Logwatch tab from page 4
- [ ] Scroll a Rules tab, close, reopen — position holds
- [ ] Stego page shows **no** blue tint until the Spectral Lens is bought; then a rough area, not the exact block
- [ ] Stamp a stego image — carrier cells read as clumped rectangles, not static
- [ ] A typosquat candidate's handle visibly near-misses its claimed org; filter names the target
- [ ] `hackdox lab -a sneaky_bugger --tool stegotool --play` starts a one-shift lab run with all tools unlocked

## Deliberately not done

- **`rule_typosquat` in `day_01.json`.** With the typosquat now minor there is no rule for it at all, so it never appears even as weighted on the rules page. Surfaced by the lab; it's day-content work.
- **The Dossier-tier evidence guard.** The `049bd80` tier guard still excludes Dossier-tier kinds — which is exactly the blind spot #51 slipped through. A dossier-panel equivalent would need a different shape of test.
- **`b533dfb` merge reconciliation.** This batch touched `candidate_gen.py` three more times; the debt against main's "Candidate Generation Anomalies" keeps growing.
