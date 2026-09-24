# BUILD PLAN — Menu System: Start Menu, Settings, Pause (closes #79)

**Scope:** rebuild `IntroScreen` into a real start menu (logo slot, New Game,
Continue/Load, Endless Mode stub, Quit, Credits, Settings), add a `SettingsScreen`
(sound only, for now), add a `PauseScreen` reachable from gameplay via Escape, and
free up Escape from its current in-game overloads so it can be the global pause key.
Absorbs and closes **#79** (Continue/Load is dead code today — `persistence.load()`
is never called).

**Compiled** 2026-09-24, from Nick's voice notes + a read of the working tree
(`intro.py`, `app.py`, `config.py`, `intake.py`, `glitch.py`, `audio.py`,
`persistence.py`) via the device bridge. Everything below is cited by file/line.

Per Nick: **this build plan comes first; pause implementation starts after he's
reviewed it.**

---

## TL;DR

| Piece | What it really is | Engine change? | Est. |
|---|---|---|---|
| **Start menu rebuild** | `IntroScreen` today is 3 `Static` widgets and 2 keys (`N`/`Q`). Needs a logo slot, 6 menu entries, and the ambient glitch flanks. | New screen content + new reusable menu-frame layout | M |
| **#79 Continue/Load** | `persistence.load()`/`save()` are fully built and unused. Purely a wiring job: add the action, gate it on `config.SAVE_FILE.exists()`, resume into the right screen. | Small, self-contained | S |
| **Endless Mode entry** | No engine exists at all — genuinely a dud button for now (disabled/greyed, "coming soon"). | None yet | XS |
| **Settings screen** | `SoundManager` (master/music/sfx volume) is fully built and *already persists* to `audio_settings.json` — `save_settings()` just has nothing calling it. This screen is that missing caller. | New screen, no audio engine work | S |
| **Ambient glitch flanks** | `ui/tui/glitch.py` (`RowPainter`, `build_frame`, palettes) already does exactly this kind of effect for transitions and damage bursts, but as one-shot envelopes. Needs a third, *looping/idle* envelope — new, but built on existing primitives. | Small new module addition, no new concept | S–M |
| **Credits entry** | Naming collision: `credit_reveal.py`'s `CreditRevealScreen` is an *existing, unrelated* in-game mechanic (spending HackDollar "credits" to reveal candidate info). The start-menu "Credits" Nick means is a studio/dev credits screen — does not exist yet. | New screen, new name needed | XS |
| **Pause menu + Escape rewiring** | No pause screen or pause binding exists anywhere. Escape is currently claimed three ways inside `IntakeScreen.on_key` (exit decrypt mode, exit stamp mode, clear command bar) plus declaratively in `RulesScreen`/`CreditRevealScreen` (close overlay). Needs surgery, not just an addition — see below. | Yes — behavioral, needs a decision from Nick | M |

---

## What's already there (verified, not assumed)

- **`IntroScreen`** (`ui/tui/screens/intro.py`) — a `Container#splash` with title/subtitle/hint `Static`s, `BINDINGS = [n → new_game, q → quit_app]`. Styled by `#splash` in `app.tcss:509-516`.
- **`HackDoxApp.on_mount()`** (`app.py:201-204`) pushes `IntroScreen` and calls `_sync_music(intro)`, which plays the `"menu"` track for anything that isn't `IntakeScreen`.
- **Persistence is fully built and orphaned (#79's actual bug).** `core/persistence.py` has `save(state)` (atomic, end-of-day) and `load()` (rebuilds a full `GameState`, backfills `unlocked_tools` for old saves). Zero call sites for `.load()` or an `action_continue` anywhere in the repo. `config.SAVE_SLOT = "slot_0"`, `config.SAVE_FILE = SAVES_DIR / "slot_0.json"` — single-slot today, by config.
- **Audio is fully built and has no UI.** `core/audio.py` `SoundManager` + shared `sound_manager`; three independent 0.0–1.0 knobs (`master_volume`/`music_volume`/`sfx_volume`), each settable via `set_*_volume()`, persisted to `config.AUDIO_SETTINGS_PATH` (`SAVES_DIR/audio_settings.json`), deliberately separate from campaign saves. **Nothing calls `save_settings()` today** — project memory flagged this exact gap as "the natural next step" before this conversation happened.
- **The glitch/transition system is a real, tested asset, not something to build from scratch.** `ui/tui/glitch.py` has `build_frame`, `RowPainter`, `Palette`/`DEFAULT_PALETTE`, `GlitchEnvelope` (full-screen transition), `BurstEnvelope` (damage burst). The hard constraint they were both built around: Textual's compositor is per-cell, so a translucent background does nothing — only a `Static` with real characters, or a `visibility: hidden` row, actually shows the page through. `RowPainter` already solves this. The ambient flanks Nick wants are a **third envelope shape** (continuous/looping, low intensity, non-blocking) reusing the same `build_frame`/`RowPainter` primitives — not a new visual technique.
- **`config.KEY_BINDINGS`** (`config.py:1257-1320`) is the single source of truth for every key in the game, already includes `"stamp_mode": "x"` and `"decrypt_mode": "x"` (deliberately the same physical key — see below), `"quit": "q"`, `"help": "question_mark"`. No `"pause"` entry exists.
- **`IntakeScreen.on_key`** (`intake.py:1319+`) intercepts keys itself, ahead of Textual's declarative `BINDINGS` (comment at line 1323: "on_key fires before BINDINGS"). Inside it, `"escape"` is claimed three times:
  1. `if k in ("escape", config.KEY_BINDINGS["decrypt_mode"])` → exits Hashcrack's decrypt mode (line ~1335).
  2. `if k in ("escape", config.KEY_BINDINGS["stamp_mode"])` → exits Stegotool's stamp mode (line ~1367).
  3. `elif k == "escape":` (line ~1442, the fallback) → clears the command bar and prints "cleared".
  **Important finding: X (`config.KEY_BINDINGS["stamp_mode"]`/`["decrypt_mode"]`) already exits both modes on its own** — Escape is redundant there, not load-bearing. This is exactly the rewiring Nick asked for and it's mostly already done; freeing Escape from cases 1–2 costs nothing.
- **`RulesScreen`** (`rules.py:34`) and **`CreditRevealScreen`** (`credit_reveal.py:25`) bind `escape` *declaratively* (`Binding("escape", "dismiss_...", "Close")`) to close themselves as modal overlays. These are legitimate, narrow uses (closing the topmost screen) and don't need to change — Textual only routes a key to the topmost pushed screen, so Escape closing a modal and Escape pausing gameplay underneath it never collide.
- **Full-screen transitions are enforced by a test that walks the AST** (`test_every_full_screen_change_goes_through_the_transition`, per project memory) — any new screen swap that doesn't go through `HackDoxApp._transition`/`_transition_swap`/`_transition_end` will fail CI. The new menu screens must go through the same choreography, not a bare `push_screen`.

---

## Decisions (locked 2026-09-24, Nick)

1. **Escape always pauses.** From `IntakeScreen`, Escape opens the Pause menu immediately, even with unsaved command-bar text. The old "Escape clears the command bar" fallback is removed outright (not moved to another key).
2. **Pause menu contents: Resume, Settings, Quit to Main Menu, Quit to Desktop.** Mirrors the Start Menu's reach. Note: this makes the Pause menu depend on `SettingsScreen` (Phase 3) — until that phase ships, Pause's Settings entry ships as a disabled/"coming soon" stub, same treatment as Endless Mode on the Start Menu.
3. **Single-slot Continue is enough.** No multi-slot Load screen this pass — satisfies #79 as written. The Start Menu button can say "Continue" or "Load" cosmetically; underneath it's the same single-slot `persistence.load()` call. A real multi-slot Load screen is a later, separate feature if wanted.
4. **"Credits" naming collision** — going with `CreditsScreen` / `credits.py`, distinct from the existing `CreditRevealScreen` / `credit_reveal.py` in-fiction mechanic. Not re-confirmed explicitly, low-risk enough to proceed on.
5. **Ambient glitch tuning** will need hand-tuning on Nick's terminal after a first pass, same as `TRANSITION_DURATION` was. Not blocking Phase 1's build, just won't be "right" first try.
6. **Still open:** whether Escape-to-pause extends beyond `IntakeScreen` to `BriefingScreen`/`EODScreen`. Pause implementation (below) starts with `IntakeScreen` only, since that's gameplay proper and what Nick called out explicitly; the other screens can get the same wiring on request.

---

## Phased build order

### Phase 1 — Reusable menu frame + ambient glitch flanks  *(SHIPPED 2026-09-24)*
Everything else depends on this. Build once, use on Start Menu, Settings, and Pause.

- New layout primitive (e.g. `MenuFrame` container / shared CSS class) — a three-column
  row: `left-glitch | central-column | right-glitch`, central column fixed-width and
  centered, side columns fill remaining space.
- New envelope in `glitch.py` for continuous ambient motion — a looping, low-intensity,
  non-blocking variant of `GlitchEnvelope`/`BurstEnvelope` (reusing `build_frame`,
  `RowPainter`, `DEFAULT_PALETTE`; new config knobs `AMBIENT_GLITCH_*` alongside the
  existing `TRANSITION_*`/`DAMAGE_GLITCH_*` blocks in `config.py`). Renders on its own
  layer the same way the damage burst does, so it never disturbs menu-button layout.
  Must keep animating while idle without blocking key input — unlike the transition
  screen, this is not a modal.
- Reuse `DEFAULT_PALETTE` (menus aren't archetype-tinted; no reason to invent a new
  palette here).

### Phase 2 — Start Menu rebuild (closes #79)  *(SHIPPED 2026-09-24)*
- Rewrite `intro.py`: logo slot (plain centered text for now, swappable later),
  central column with New Game / Continue / Endless Mode (stub) / Quit / Credits /
  Settings, flanked by Phase 1's ambient glitch.
- Add `config.KEY_BINDINGS` entries for the new actions (`continue_game`,
  `open_settings`, `open_credits`; Endless Mode stub may not need a live key yet).
  Hint line becomes dynamic, matching the existing pattern in the linked issue
  ("hint line and binding should reflect" whether Continue is available).
- `action_continue`: gate on `config.SAVE_FILE.exists()`; hide/disable the entry
  otherwise (issue #79 acceptance criterion). Calls `persistence.load()`, resumes
  into the correct screen for `state.current_day` instead of `start_new_game()`.
- Update `UI_CATALOG.md`'s `IntroScreen` section to match shipped behavior (also an
  explicit #79 acceptance criterion — it currently documents a Continue option that
  doesn't exist).
- Endless Mode entry renders disabled/"coming soon" — no action wired.
- All screen transitions go through `HackDoxApp._transition`, not a bare `push_screen`
  (the AST test enforces this).

### Phase 3 — Settings screen (sound only)  *(SHIPPED 2026-09-24)*
- New `SettingsScreen`, same `MenuFrame` layout as the Start Menu.
- Three controls (master/music/sfx volume) bound to the existing
  `sound_manager.set_master_volume()` etc.; on change or on close, call the
  already-built (never-called) `save_settings()`.
- Reachable from the Start Menu now; from the Pause menu once Phase 4 exists.
- No new audio engine work — this phase is 100% UI wiring onto an existing system.

### Phase 4 — Credits screen  *(SHIPPED 2026-09-24 — built ahead of an explicit ask; it's a required Start Menu button and was trivial once Phase 1's menu-frame existed. Flag to Nick.)*
- New `CreditsScreen` (name pending decision #3 above) — static content, same
  `MenuFrame` shell, no interactivity beyond "back."

### Phase 5 — Pause menu + Escape rewiring  *(SHIPPED 2026-09-24 — extended beyond the original IntakeScreen-only scope per Nick's follow-up: also reachable from BriefingScreen, EODScreen, and BetweenDayScreen. Both Quit actions now save first; BetweenDayScreen's own `Q` quit binding was removed in favor of Pause being the one place quitting happens.)*
- New `PauseScreen`: Resume, Settings (stub until Phase 3 ships), Quit to Main Menu,
  Quit to Desktop.
- In `IntakeScreen.on_key`: drop `"escape"` from the two mode-exit checks (X alone
  already exits both — verified above, not a functional loss) and remove the
  command-bar-clear-on-escape fallback entirely; Escape now always opens Pause.
- Wire Escape → open Pause from `IntakeScreen` only, for this pass. `RulesScreen`
  and `CreditRevealScreen` keep their own declarative `escape` bindings unchanged —
  they close the topmost modal, which never conflicts with Pause underneath it.
- Pause does NOT run the full-screen glitch transition (it's meant to be
  quick/reversible, unlike a day-to-day swap) — pushed as a lightweight modal-style
  screen instead.

---

## Test surface to extend (matching existing conventions)

- `test_transitions.py` / a new `test_ambient_glitch.py` — mirror
  `test_the_page_shows_through_a_partial_frame` for the new envelope; confirm it never
  blocks input (mirrors `test_the_burst_does_not_block_the_player`).
- A new `test_intro_menu.py` (or extend wherever `IntroScreen` is covered today) —
  Continue hidden with no save file, shown and functional with one; hint line matches
  available actions.
- `test_audio.py` — extend for `SettingsScreen` calling `save_settings()` on change.
- Whatever test currently asserts `IntroScreen`'s bindings/hint text will need updating
  to match the new menu (currently just `N`/`Q`).

---

## Environment note

Built against the working tree as staged via the device bridge on `pathfinder`
2026-09-24 (bridge is up this session — prior notes about it being down since
2026-09-08 no longer apply as of today). Not yet run against `git status`/branch
state — confirm current branch and clean-tree status before starting Phase 1.

---

## Follow-up pass (2026-09-24, same day, after all 5 phases shipped)

Two things Nick flagged after using the shipped menus:

1. **Small-terminal scaling.** `.menu-column`'s content (logo, subtitle,
   6 buttons, hint) is centered with a fixed layout and no way to shrink —
   on a short terminal the bottom of the menu (Quit, and the hint line)
   rendered off-screen with nothing indicating it was there. Fixed by
   giving `.menu-column` `overflow-y: auto` (`app.tcss`) — it now scrolls
   when content doesn't fit, and Tab/arrow-key focus movement (and the
   mouse wheel) bring the rest of the menu into view. Confirmed via
   `run_test(size=(80, 16))`: the Quit button's region was previously
   `y=28` against a 16-row screen (fully off-screen); after the fix, Tab
   navigation scrolls it to `y=6`, on-screen. A generous terminal is
   unaffected — no scrollbar appears when everything already fits.

2. **Ambient glitch flanks — "slower, calmer, flowing between states."**
   The Phase 1 ambient panel just rerolled a brand-new random frame every
   tick, which reads as flicker, not the "naturally progressing and
   evolving" ambiance Nick asked for. Rebuilt as a HOLD → MORPH → HOLD loop
   (`widgets/menu_glitch.py`): a still frame sits for
   `AMBIENT_GLITCH_HOLD_DURATION` (3.5s), then flows into a freshly rolled
   one over `AMBIENT_GLITCH_MORPH_DURATION` (2.4s, several times slower
   than the 0.75s screen-transition glitch) via a ragged top-to-bottom wipe
   (`AMBIENT_GLITCH_MORPH_JITTER` staggers each row's switch point so the
   front isn't one clean bar), then holds again. Each state's overall
   intensity still drifts via the existing sine wave, just sampled once per
   state instead of once per frame.

   Building this hit a real bug worth flagging: an early version cached the
   two states as prebuilt Rich `Text` frames and named its own "last known
   size" bookkeeping attribute `self._size` — which silently shadows
   `Widget._size`, Textual's own private layout attribute. Overwriting it
   with a plain tuple corrupted the framework's layout bookkeeping and
   reliably crashed a few ticks after mount (`Screen._refresh_layout` →
   `AttributeError: 'tuple' object has no attribute 'region'`), on every
   terminal size tried, regardless of what the widget's own logic was
   doing — it took a fair amount of bisection to find, since none of the
   content-strategy changes tried along the way (skip repainting, `.copy()`
   the rows, always rebuild fresh) touched the actual cause. Renamed to
   `self._panel_size` and it was gone. New tests in
   `test_ambient_glitch.py` cover the pure blend/switch-point math and this
   crash specifically (`test_panel_survives_many_ticks_without_crashing_layout`).

---

## Second follow-up (2026-09-24, same day) — two bugs Nick found

1. **Sound couldn't be re-enabled.** Toggling Settings' mute switch off then
   back on left the game silent. Root cause: `SoundManager.set_enabled(True)`
   only flipped the `.enabled` flag — nothing called `play_music()` again to
   actually resume the loop. The one call site that does
   (`HackDoxApp._sync_music`) only fires on a full screen change (through
   `_swap_screen`/`_transition`), and Settings/Pause are pushed as plain
   overlays that never go through that path. Fixed in `core/audio.py`:
   `play_music()` now records what it was asked for in
   `_desired_music_id`/`_desired_music_loop` regardless of whether it
   actually played (muted or backend unavailable), and `set_enabled(True)`
   resumes that track if one was ever requested. New tests in
   `test_audio.py`.

2. **Ambient glitch flanks weren't visible on the Main Menu or Settings.**
   Root cause was a Phase 1 CSS gap, not anything from today's morph
   rewrite: `.menu-flank` never had an explicit `height` rule, so it
   defaulted to `auto` (sized to its own rendered content) and collapsed to
   a single row instead of filling `.menu-frame`'s full height — confirmed
   via `run_test`: panel size was `(18, 1)` against a 40-row screen before
   the fix, `(18, 40)` after. A 1-row sliver at that scale reads as "not
   there." Fixed by adding `height: 1fr` to `.menu-flank` in `app.tcss`.

---

## Third follow-up (2026-09-24, same day) — glitch color didn't match the page

Nick: "the base color of the glitch needs to match the base color of the
page so it looks like the glitches are naturally a part of the page."

Root cause: the ambient panel was drawing from `glitch.DEFAULT_PALETTE`,
whose dark/background tones (`_DARK_BG`, `_VOID` = `#05070a`) are tuned for
the transition and damage-burst effects — both fade to or from a void
darker than the page, which is the right feel for something covering the
whole screen mid-effect. `Screen`'s actual background (`app.tcss`, top of
file) is `#0b0e10` — a different, lighter near-black — so at the panel's
normal low intensity, most of every frame was reading as a visibly separate
dark rectangle next to the page rather than part of it.

Fixed: added `config.PAGE_BACKGROUND = "#0b0e10"` (mirrors `Screen`'s CSS
background — no way to read a CSS value from Python here, so it has to be
kept in sync by hand if the page background ever changes). `menu_glitch.py`
now builds its own `_AMBIENT_PALETTE` with `dark_bg`/`tear_bg` anchored to
`config.PAGE_BACKGROUND` instead of `DEFAULT_PALETTE`'s void tones —
foreground/accent colours (the actual glitch characters) are untouched, so
it still reads as noise, just noise sitting on the page's own background
rather than a separate panel. `.menu-flank`'s own CSS `background` also
changed from `#05070a` to `#0b0e10` to match, so blank/untouched cells
agree too. Confirmed via `run_test`: every row style sampled from a live
panel now shows `... on #0b0e10`. Full regression suite re-run clean.

---

## Fourth follow-up (2026-09-24, same day) — glitch flanks on the Credit reveal popup

Nick: the HackDox Credit reveal popup (`screens/credit_reveal.py`, spending a
Credit to see a candidate's ground truth) "feels a little boring" and asked
for the same flanking glitch treatment as the menus.

`CreditRevealScreen` is a `ModalScreen` whose only child used to be the
violet-bordered `#credit-modal` box, centered by `CreditRevealScreen {
align: center middle; }` — everything else was flat page background
(`#0b0e10`, same value as `config.PAGE_BACKGROUND`, so no separate color
fix was needed here, unlike the menu flanks earlier today). Restructured
`compose()` to wrap `#credit-modal` in the same `Horizontal(classes=
"menu-frame")` + two `AmbientGlitchPanel(classes="menu-flank")` pattern the
Start Menu/Settings/Credits use — `#credit-modal` itself is untouched (same
width/border/background/content).

One new thing needed: `.menu-frame` never had an `align` rule of its own —
IntroScreen/SettingsScreen/CreditsScreen's middle child (`.menu-column`)
always filled the full frame height and centered its own content, so it
never needed help. `#credit-modal` is a short `height: auto` box, so
`.menu-frame` now carries `align: center middle;` to center it vertically
between the flanks — harmless no-op for the three existing screens.

Confirmed via `run_test`: both flank panels render full-height (`(13, 40)`
against a 40-row screen), the modal box sits centered between them
(`Region(x=13, y=0, width=74, height=18)` against a 100-wide screen), and
Escape/Enter still dismiss correctly. Full regression suite re-run clean.
