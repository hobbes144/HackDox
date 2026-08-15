# BUILD PLAN — Batch 1: Progressive Unlock (epic #2)

_Scope: #31, #3, #32, #33, #34 → closes epic #2. Compiled 2026-08-15. Base branch `main` @ `3bbb465` (working tree clean apart from the two planning docs). Every file/line reference below was verified against the staged working tree, not inferred from CLAUDE.md — which is behind reality (no `overseer.py`/`day_cycle.py` exist; the UI is one `app.py`)._

## TL;DR

| Issue | What it really is | Touches save? | Size |
|---|---|---|---|
| **#31** | `GameState.unlocked_tools` + persist + evidence-tier gate in the generator | **Yes** (new persisted field) | M — real engine |
| **#3** | New `TypewriterLog` Textual widget + refactor 3 hosts to use it + scoped advance key | No | **L — the big one** |
| **#32** | Per-day candidate spec (allowed_violations / difficulty_band / forced_includes) on `Day` + generator consumes it | No (content/loader) | M |
| **#33** | Grey out locked tool tabs; make page-nav + shortcuts inert for locked tools | No | S–M — contained UI |
| **#34** | Overseer unlock beat that *flips* `unlocked_tools` when it plays (via #3's triggers hook) | writes the field | S mechanism + content |

**Build order (dependency-forced):** #31 → #3 → #32 → #33 → #34. #31 is the foundation (#32/#33/#34 all `blocked_by` it); #3 is `blocking` #34; #33 needs #31's field to read; #34 needs both #31 (the field) and #3 (the triggers hook).

---

## Verified current state (file:line)

- **`GameState`** — `models.py:296-317`. Mutable dataclass, no `unlocked_tools`. Fields are enumerated by hand in **`persistence.save` (13-26)** and **`persistence.load` (32-47)** — adding a persisted field is a 3-place edit (dataclass + save + load, with a legacy-save default).
- **Generator** — `candidate_gen.generate(game_seed, day, slot_index)` (`620`). Discrepancies chosen in **`_roll_discrepancies` (512-548)** from `spec.eligible_kinds` honoring `spec.budget`. Each kind's revealing tool + severity is in **`_SEVERITY_REVEAL` (347-376)**. Deterministic via `stable_hash` (442).
- **`Day`** — `models.py:256-266`: `archetype_mix`, `candidate_count`, `rules`, `quotas`, overseer keys. Loaded by **`content_loader.load_day` (23-56)** from `content/days/day_NN.json`.
- **Tab strip** — `StatusHeader.render` (`app.py:393-396`) builds tabs from `_PAGE_NAMES` (292), highlighting `page_index`. Has `self.state`, so it can read `state.unlocked_tools`.
- **Page order** — `_PAGE_NAMES = [CANDIDATE, GHOSTSCAN, HASHCRACK, LOGWATCH, STEGOTOOL]` (292). Index→tool: 0 dossier (never gated), 1 ghostscan, 2 hashcrack, 3 logwatch, 4 stegotool. **This already matches #34's teaching order** Dossier→Ghostscan→Hashcrack→Logwatch→Stegotool.
- **Page switch** — `_goto_page(index)` (`1780`): the single choke-point for changing pages. The natural place to block navigation to a locked page.
- **Shortcuts** — g/l/h/s/f are **not** direct bindings; per the BINDINGS comment (`1539`) they route through the command bar → `_run_tool` (`1908`). Gate there, plus at `_goto_page`, plus grey the tab.
- **Overseer/chat rendering** — all plain `Static` today: `OverseerPanel` (`793`, renders `self._intro` + stats), `ChatPanel` (`507`, mounts a `Static` per line, `538`), `BriefingScreen` (`1501-1502`), `EODScreen` (`2337-2338`), `BetweenDayScreen#bd-overseer-text` (`2410`).
- **Space today** — `BriefingScreen`/`EODScreen` Space = continue (`1489`, `2281`); `BetweenDayScreen` Space = buy (`2367`); intake stego Space = stamp (`on_key` `2124`, stamp handling `2172`). #3's advance key must be **widget-focus-scoped**, never a screen-level `Binding("space", …)`.

---

## Phase-by-phase

### Phase 1 — #31 Unlock state model + evidence-tier gate
1. `GameState.unlocked_tools: set[str]` (models.py) — store `ToolName.value` strings for JSON-friendliness (matches how `upgrades` is handled).
2. `persistence.save`: `"unlocked_tools": sorted(state.unlocked_tools)`. `persistence.load`: `set(raw.get("unlocked_tools", <default>))` — legacy saves need a sensible backfill (see **Open Q1**).
3. Evidence-tier gate in `_roll_discrepancies`: filter `eligible` to kinds with `intro_day(kind) <= day.number` before the `take()` calls. `intro_day` source is **Open Q2**.
4. **AC:** `unlocked_tools` round-trips through save/load; a day-1 state can never roll a later-day kind; foundation test covers both.

### Phase 2 — #3 TypewriterLog widget
1. New widget: async `type_line()` coroutine, internal message queue, `advance()` (Space, focus-scoped: first press fast-completes the current line, second advances), `●` unread indicator, `Message` event carrying `speaker/lines[]/color/icon/triggers`.
2. Refactor `OverseerPanel` and `ChatPanel` to render through it; wire the 3rd consumer `BetweenDayScreen#bd-overseer-text` (key `day{N}_between`).
3. **The advance key is scoped to the widget's focus** — remove/relocate the colliding screen-level Space bindings' reach so buy/continue/stamp still work when the widget isn't focused.
4. **AC:** all six #3 criteria; `triggers` hook fires a callback when a message finishes (this is what #34 rides).

### Phase 3 — #32 Per-day candidate spec
1. Extend `Day` with `allowed_violations: tuple[DiscrepancyKind,...] = ()`, `difficulty_band: str = "easy"`, `forced_includes: tuple[...] = ()` (defaults keep existing day files valid). `content_loader.load_day` reads them. **(shape = Open Q3, defaulting to extend-`Day`.)**
2. `generate()` intersects `allowed_violations` with the Phase-1 intro-day gate (whitelist AND taught-yet).
3. `forced_includes` pins an archetype to a slot in `_pick_archetype_for_slot`.
4. **AC:** spec consumed as primary input; `forced_includes` pins a slot; same spec+seed → same set.

### Phase 4 — #33 Locked tool tabs
1. `StatusHeader.render`: render tabs for tools not in `state.unlocked_tools` greyed/dim + a lock glyph.
2. `_goto_page`: if target page's tool is locked, refuse (or land on a "not yet unlocked" state) — no switch.
3. Command-bar/`_run_tool` path: locked tool shortcut = inert, **no ⏱ charge**, no nav. Optional Overseer-flavored "not available yet" line.
4. **AC:** locked tabs visibly distinct; locked shortcuts inert (no run, no ⏱, no nav); Textual pilot proves a locked page can't be reached or run.

### Phase 5 — #34 Overseer narrates unlocks
1. Each day's briefing, when it introduces a tool, plays an Overseer line whose `triggers` hook (from #3) **adds the tool to `unlocked_tools`** at that moment.
2. Order matches Dossier→Ghostscan→Hashcrack→Logwatch→Stegotool. Content scope = **Open Q4** (mechanism + placeholder lines now vs authoring the Day 1–5 copy now, which overlaps #15).
3. **AC:** each unlock has an Overseer line; playing it flips the field (not cosmetic); order matches #15's sequence.

---

## Cross-cutting risks
- **`persistence` legacy saves.** A pre-#31 save has no `unlocked_tools`. The load default must not leave a mid-campaign player with everything locked. Tied to Open Q1.
- **`app.py` is 119 KB and edited by hand elsewhere** (CLAUDE.md notes Windows-mount truncation). Edits to #3/#33 sites will be verified with `py_compile` + tail-checks after every write.
- **#34 vs #15 content boundary** — authored unlock lines live in per-day narrative that #15 owns. Keep #34 to mechanism + placeholders unless Open Q4 says otherwise, so we don't author the same day scripts twice.
- **Determinism** — the Phase-1 gate and Phase-3 whitelist both filter `eligible`; a fixture must prove a Day-1 roll still satisfies each archetype's budget after filtering (a Bad Actor whose critical kinds are all later-day would otherwise generate empty). May require Day-1 `allowed_violations` to include at least one kind per required budget slot.

## Verification (Python — no tsc/eslint/Supabase here)
- `python gameengine/tests/run_foundation_tests.py` — extend with: unlock_tools save/load round-trip; day-1 cannot roll a later-day kind; forced_includes pins a slot; locked-tool budget-satisfiability.
- Textual pilot: locked page unreachable + shortcut inert + no ⏱ charge; TypewriterLog advance/fast-complete/unread across all three hosts without breaking buy/continue/stamp.
- `py_compile` every touched file from disk + tail-check after each write (mount-truncation guard).

## Open questions → the gate
1. **Unlock model** — stored-and-flipped-by-#34-trigger (per the AC, needs a legacy-save default), or derived-from-day schedule (simpler, makes #34's flip cosmetic)?
2. **`intro_day` source** — derive from each kind's revealing tool's unlock day, or use explicit per-kind values from the Notion "Evidence Options DB → Introduced to Player on Day"?
3. **#32 spec shape** — extend `Day` (recommended, least churn) vs a separate `CandidateDaySpec`. Per-day `seed`: keep the existing global-seed derivation (recommended) or add a per-day override?
4. **#34 content scope** — build the trigger mechanism + placeholder unlock lines now (final copy with #15), or author the Day 1–5 unlock lines in this batch?
5. **Branch + commit granularity** — feature branch name, and one-commit-per-issue (recommended)?
