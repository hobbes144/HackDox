# Dockside voice pass — GitHub issue drafts (hobbes144/HackDox)

Not filed yet. My computer and Chrome were both unreachable this session.
Labels: `enhancement` on all of them. The content issues use the repo's
`[content]` title prefix.

---

## EPIC — [content] Dockside voice pass: HackDox as "hack" + "docks"

## Motivation

HackDox is meant to be *hack* (computers) plus *docks* (dock work). Today every
line of player-facing copy is cold corporate security speak. The Overseer, the
candidates, the affiliations and even the stego image don't reflect the
longshoreman half of the name. Nick set the direction on 2026-09-24: gritty
dock-worker texture over the existing cybersecurity core, family-friendly (PG).

## Description

The voice is defined once, in `VOICE_GUIDE.md` at the repo root, and enforced by
a new subagent, `.claude/agents/dockside-voice.md`. It owns wording only; rule
predicates, severities, ids, tool output and hint-line clues are off limits.
Word-bank renames are handed to the `rules-evidence` subagent, because those
lists feed the typosquat map, `tools_bridge`'s derived sets and the evidence
guards.

Locked decisions (Nick, 2026-09-24):
- The Overseer is presented to players as **The Foreman**. Code identifiers (`overseer.py`, `overseer.json`, `overseer_*_key`) are unchanged.
- Real-world elite orgs (MIT, Google, DeepMind…) become **made-up harbour organisations** (Port Authority CERT, Tidewater Signals Lab…).
- Email domains are a **mix** of real consumer providers and in-world ones.
- Intensity: **one dock phrase every two or three lines**; none in rule text or tool output.

Sequencing: do the Overseer/Foreman rewrite before #71. #71 reviews days 14–16
and 18–19 dialogue, and that dialogue is about to change.

## Acceptance Criteria

- [ ] `VOICE_GUIDE.md` and `.claude/agents/dockside-voice.md` are in the repo
- [ ] All sub-issues closed
- [ ] Banned-word test and chat-pool density test exist in the suite and were verified red-then-green
- [ ] `CLAUDE.md`, `CONTENT_AUTHORING.md` and `UI_CATALOG.md` point at `VOICE_GUIDE.md` and note the Overseer→Foreman mapping

## Sub-issues
(to be filled with the six below once created)

---

## SUB 1 — [content] Rename the Overseer to the Foreman in every player-visible string

## Motivation
Part of the dockside voice pass. "Overseer" reads as a corporate title; the dock framing needs a foreman.

## Description
Change every string a player can see: chat speaker label, panel titles,
briefing/EOD/between-day headings, Rules pages, credits, endings. Leave code
identifiers, `overseer.json` keys and test names alone. Add a one-line comment at
the top of `core/overseer.py` and `content/narratives/overseer.json` stating the
mapping.

## Acceptance Criteria
- [ ] No player-visible string says "Overseer" (scan UI labels, Rules pages, credits, briefings, day-file copy)
- [ ] Code identifiers unchanged; saves and day files still load
- [ ] Docs note the mapping once

---

## SUB 2 — [content] Rewrite the Foreman's dialogue in the dockside voice

## Motivation
`overseer.json` holds all ~190 lines the Foreman speaks. It's the largest share of the game's personality and the most-read copy.

## Description
Rewrite every value in `overseer.json`, plus `_UNLOCK_LINES` and
`_RULE_CHANGE_PHRASINGS` in `ui/tui/screens/_narration.py`, per VOICE_GUIDE §2–§3.
The arc runs gruff mentor (1–5) → pressure and first favours (6–11) → on the
take, hostile (12–20). Keep every key, the meaning of each line and every
alignment band. Change voice, not plot. `_UNLOCK_LINES` is still marked
PLACEHOLDER; decide whether to rewrite it or retire it in favour of the authored
day 2–5 briefings.

## Acceptance Criteria
- [ ] Every key rewritten; no key added or removed
- [ ] Intensity ~1 dock phrase per 2–3 lines, rising with hostility
- [ ] No line materially longer than its original (typewriter panel fit)
- [ ] Banned-word scan clean
- [ ] Unlock/narration tests pass

---

## SUB 3 — [content] Candidate chat, forced_chat and reaction lines in the dockside voice

## Motivation
Candidates should read as people from around the port: stevedores, crane operators, customs brokers, port IT.

## Description
Rewrite the `_CHAT_*` pools in `core/candidate_gen.py` (including the Dark Web
early/mid/late pools), `forced_chat` in the day files, and `ui/tui/reactions.py`.

**#78 constraint:** flavor must be spread evenly across every pool. If honest
candidates sound more like dockworkers than dishonest ones, the idiom becomes a
tell. **Hint lines are evidence:** rewrite the wrapping, never the clue.

## Acceptance Criteria
- [ ] New test: dock-phrase density per chat pool is within a set tolerance of the others (verified red by salting one pool)
- [ ] Every `hint_lines` / `forced_chat` clue still present
- [ ] Dark Web escalation (flippant → bold → contempt) preserved
- [ ] Test suite green

---

## SUB 4 — [content] Harbour-themed word banks: affiliations, email domains, purposes, image filenames

## Motivation
The elite affiliations are real institutions (MIT CSAIL, Google, DeepMind). They don't fit the world, and real company names in a Steam release are a liability. Domains and filenames are the most-seen flavor on every dossier.

## Description
Apply VOICE_GUIDE §5 via the `rules-evidence` subagent:
- **Elite (unfakeable):** Port Authority CERT · Tidewater Signals Lab · Bayside Naval Cyber Institute · Harbormaster's Office Network Defense · Meridian Shipping Security Operations · Northreach Maritime Research Institute · Lighthouse Foundation for Secure Systems.
- **Ordinary:** dockside versions of the current five. **Thin:** stays plain.
- **Domains:** keep real consumer providers and add in-world ones. Names signal the category: ordinary port names = trusted, fog/quiet = privacy, flotsam/jetsam/driftwood/bilge/castoff = disposable.
- **Purposes and `submitted_image_path` names:** port-flavoured.

Touchpoints: `_ELITE_ORG_HANDLE` (new handles must still typosquat at Levenshtein
1–2), the derived sets in `tools_bridge`, and the literals in `test_rules_page.py`.
The rule sheet and the Rules pages need to teach the new elite names, since
players lose the "I recognise that" shortcut.

## Acceptance Criteria
- [ ] No real companies, institutions, ports or unions in any word bank
- [ ] No in-world root shared across two domain categories
- [ ] Typosquat, affiliation and disposable-email guards green
- [ ] `hackdox lab -a sneaky_bugger -v typosquat_handle` produces readable lookalikes of the new handles

---

## SUB 5 — [content] Rule-sheet summaries, notes, titles and Dark Web justifications in the dockside voice

## Motivation
The daily rule sheet and the DW directive speeches are where the Foreman's
framing of the rules lives. They need the voice without blurring what the rules
say.

## Description
Rewrite `title`, `rule_sheet.summary` and `added_rules[].justification` across
`day_01`–`day_20.json`. Notes get at most a light touch. **Rule `text`,
`predicate`, `severity`, `id` and `supersedes` do not change.** Coordinate with
#72, because the Rules pages must stay first-timer clear.

## Acceptance Criteria
- [ ] New test: no glossary idiom appears in any `rules[].text` / `added_rules[].text`
- [ ] All day files load; rule ids and predicates byte-identical to before
- [ ] DW-01…DW-06 justifications still read as the Foreman rationalising the change

---

## SUB 6 — [game-engine] Harbour scenes for the Stegotool carrier image

## Motivation
The stego image is a plain gradient or a single tint. Nick wants a simple,
thematic design: something worth looking at while you sweep it.

## Description
Replace the five `style` branches in `tools_bridge.build_stego_image._base_rgb`
with a motif library drawn on the cell grid (30×12 up to 72×32): container
stacks, a gantry crane at dusk, harbour lights at night, a hull at the waterline,
a lighthouse, fog over a pier. VOICE_GUIDE §7 constraints:
- **Muted palette only.** No saturated amber/crimson/violet (the carrier reveal colours) or green (the clean-reveal wash).
- **No cross, ring or parallel-slash forms** (the SIGNAL_COMMS / RECURSIVE / HOSTILE glyphs). That rules out anchors, life rings, portholes and diagonal crane arms.
- **Spectral Lens** tint must stay visible on every motif.
- **Separate seeded RNG** for motif choice; the existing `rng` draw order is untouched, so zones, carriers and `hackdox lab` seeds reproduce exactly.

## Acceptance Criteria
- [ ] Test: for a fixed set of seeds, `zone`, `carrier`, `hint_region` and `shape` are identical before and after
- [ ] Test: no base cell falls in the reveal hues; tint delta ≥ threshold on every motif
- [ ] Visual check of each motif at min and max grid size (screenshots on the issue)

---

## Voice lines to add to existing issues

| Issue | Add this acceptance criterion |
|---|---|
| #71 Alignment dialogue verdict | Blocked by SUB 2. Review the Foreman's rewritten lines, not the current ones. |
| #72 Rules-page onboarding | Flavor only in summaries; rule text and the violation tables stay plain (VOICE_GUIDE §2). |
| #67 Steam achievements | Achievement names follow VOICE_GUIDE; descriptions state the trigger plainly. |
| #68 Remaining SFX slots | Fill with dock sounds where they fit: foghorn, gulls, crane clank, chain rattle, container thud. |
| #69 Intro + day-start music | Harbour ambience bed (water, distant horns) under the day-start track. |
| #80 Shop chip grid | Shop item names follow VOICE_GUIDE (the supply shed / hiring hall); descriptions stay exact. |

## Probably-stale issues to verify and close
All 20 day files exist, so these look shipped but are still open: #37, #39, #40,
#41, #44–#49, #15, #16, #6. Verify each against the branch history before
closing it with a comment.
