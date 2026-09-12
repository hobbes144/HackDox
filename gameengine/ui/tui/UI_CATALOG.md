# HackDox TUI — Interface Catalog
*Last updated: 2026-09-12*

---

## Overview

The game runs as a single Textual `App` (`HackDoxApp`) that pushes and pops `Screen` objects.
The main play area is `IntakeScreen`, a five-page layout driven by a `ContentSwitcher`.
All player input during gameplay flows through a persistent `CommandBar` at the bottom of the screen.

---

## Screen Stack

Every change BETWEEN these screens is covered by a `TransitionScreen`
(see Screen Transitions below); page switches inside `IntakeScreen` are not.

```
HackDoxApp
 └── IntroScreen          (start menu)
      └── BriefingScreen  (overseer intro + day title)
           └── IntakeScreen  (main play loop — five pages)
                └── RulesScreen (modal overlay, 0 key)
           └── EODScreen   (end-of-day summary)
      └── GameOverScreen  (Site Health collapsed)
```

---

## Screens

### IntroScreen
- **Trigger:** App launch
- **Content:** ASCII splash, New Game / Continue / Quit
- **Keys:** `N` new game · `Q` quit

### BriefingScreen
- **Trigger:** After new-game or continue
- **Content:** Day title, Overseer opening monologue, press Space to begin
- **Keys:** `Space` begin shift · `Q` quit

### IntakeScreen *(main play screen)*
- **Trigger:** `begin_intake()` call from BriefingScreen
- Five pages switched via number keys (see Page Navigation below)
- Persistent widgets outside the ContentSwitcher: `StatusHeader`, `DebugPanel`, `CommandBar`, footer

### RulesScreen *(modal)*
- **Trigger:** `0` key from IntakeScreen
- Five-tab documentation hub (see Rules Modal section below)
- **Keys:** `0` or `Esc` to close · Tab / click to switch tabs

### EODScreen
- **Trigger:** After last candidate verdict
- **Content:** Verdict scorecard, ⏱ summary, alignment delta, Overseer outro
- **Keys:** `Space` save & continue · `Q` quit

### GameOverScreen
- **Trigger:** Lives reach zero
- **Keys:** `R` restart · `Q` quit

### TransitionScreen *(modal, twice per screen change)*
- **Trigger:** `HackDoxApp._transition`, on every full-screen change
- **Content:** animated CRT signal-loss rows over the screen underneath
- **Keys:** none — input is dead for the duration (see Screen Transitions)

---

## IntakeScreen — Layout

```
┌─ StatusHeader ──────────────────────────────────────────────────────┐  height 1
│ HACKDOX  │  Day N  │  slot X/Y  │  ⏱  │  ♥♥♥  │  alignment  │ tabs │
├─ ContentSwitcher (height 1fr, overflow hidden) ─────────────────────┤
│  [active page — see Pages below]                                    │
├─ DebugPanel (height auto, hidden by default) ───────────────────────┤
├─ CommandBar ────────────────────────────────────────────────────────┤  height 3
│  [response / feedback line]                                         │
│  hackdox@terminal:~$ [typed buffer]█                                │
├─ Footer ────────────────────────────────────────────────────────────┤  height 1
│  navigation hint                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Pages (ContentSwitcher)

### Page 1 — Candidate (`1` key)
```
┌─ candidate-top (40%) ───────────────────────────────┐
│  DossierPanel (40%)  │  ChatPanel (60%)             │
├─ candidate-mid (30%) ───────────────────────────────┤
│  EvidenceBoard (100%)                               │
├─ candidate-bot (30%) ───────────────────────────────┤
│  OverseerPanel (40%)  │  ReferencePanel (60%)       │
└─────────────────────────────────────────────────────┘
```
- **ReferencePanel content:** Command list for candidate actions (admit/deny/next + all tool shortcuts)

### Pages 2–5 — Tool Pages (shared layout)
```
┌─ tool-left (32%, height 100%) ──┬─ ToolTerminal (68%) ────────────┐
│  CondensedDossier (50%)         │  VerticalScroll                  │
│  ReferencePanel   (50%)         │  Pre-populated with free data    │
│  (command reference)            │  Base run output appended below  │
│                                 │  Filter output appended last     │
└─────────────────────────────────┴──────────────────────────────────┘
```

| Key | Page | Tool | Reference shows |
|-----|------|------|-----------------|
| `2` | Ghostscan | OSINT sweep | `recon` / `ghostscan` / `g` + `filter` |
| `3` | Hashcrack | Hash cracking | `crack` / `hashcrack` / `h` + `filter` |
| `4` | Logwatch | Log analysis | `analyze` / `logwatch` / `l` + `filter` |
| `5` | Stegotool | Steganography | `extract` / `stegotool` / `s` + `filter` |

---

## Widgets

### StatusHeader
- One-line strip: game title · day title · candidate slot · compute hours · site health · HD$ · credits · alignment bar · page tabs
- Updates on every page switch and verdict

### DossierPanel
- Candidate identity: name, handle, email, affiliation, GitHub handle
- Submitted artifacts section: claimed IP, submitted hash, log path, image path
- Read-only; populated on candidate load

### CondensedDossier
- Slim identity strip shown on tool page sidebars
- Name, handle, email only

### ChatPanel (`VerticalScroll`)
- One-way chat from candidate and Overseer
- Colour-coded by tone: warm (#c8d4e1) · hostile (#ff5470) · flippant (#c084fc) · earnest (#7dd3c0)
- Timestamps shown in dim grey
- `post_reaction()` appends the candidate's closing line during the verdict
  reveal window (content in `reactions.py`). Always full colour — the Sentiment
  Scanner gate applies pre-verdict only

### EvidenceBoard
- Player-controlled checklist of 13 flaggable items across 5 groups
- Groups (board order, matches tool page order): DOSSIER · OSINT (G) · CREDENTIAL (H) · FORENSICS (L) · STEGO (S)
- `↑/↓` move cursor · `Space` toggle flag · cursor renders in green inverse
- Nothing auto-populates — player flags manually
- Board accuracy bonus: up to +10⏱ on correct verdict
- **After a verdict** each *touched* row gains a ✓/✗ and a footer reports how
  many violations went unrecorded. Rows left at "unknown" stay blank — the
  answer key never appears

### OverseerPanel
- Overseer monologue and stat summary for current candidate
- Purple border (#c084fc), distinct from other panels

### ReferencePanel (`Static`)
- Right-side panel on candidate page and tool page sidebars
- **Candidate page:** full command vocabulary
- **Tool pages:** page-specific commands with costs and admit/deny reminder
- Content is static per page (set on candidate load, identical each time)

### ToolTerminal (`VerticalScroll`)
- Progressive disclosure: free data always present on candidate load
- Base run output appended when tool is invoked (costs ⏱)
- Filter output appended when filter is run (costs additional ⏱)
- Empty label removed on first content add

### DebugPanel
- Dev-only: shows candidate ground truth (archetype, discrepancies, correct verdict)
- Toggled by `` ` `` (grave accent key)
- Hidden by default; `height: auto` so it doesn't consume space when invisible

### CommandBar (`Static`)
- Persistent; always visible at the bottom of IntakeScreen
- Two lines: response/feedback · `hackdox@terminal:~$` prompt with live buffer
- Player types commands; Enter submits; Backspace edits; Esc clears
- Uses `self.update(markup)` for Rich markup rendering

---

## Screen Transitions

Every full-screen change glitches instead of cutting: intro → briefing →
shift → end of day → between-day menu → next briefing, plus game over and
campaign end. Page switches within a shift (`1`-`5`) and the modal overlays
(rules, evidence board, credit reveal) are deliberately excluded — they happen
dozens of times a shift, and a lock-out there is friction, not atmosphere.

| Phase | Duration | What is on screen |
|---|---|---|
| out | `TRANSITION_DURATION × TRANSITION_SWAP_AT` | the OUTGOING page, glitch ramping to full coverage |
| swap | one callback, nothing awaited | the screen change, under total coverage — never visible |
| in | the remainder | the INCOMING page, glitch decaying to clear |

Input is dead from the first frame to the last: both halves are modal screens,
so the page underneath gets no keys, no clicks and none of its own bindings,
and `TransitionScreen.on_key` swallows what arrives so a mashed key cannot
queue up and land on the next page. `config.TRANSITION_PASSTHROUGH_KEYS`
(ctrl+c / ctrl+q) is the one exception — an animation must never trap the
player.

The picture lives in `ui/tui/glitch.py` (`build_frame`, `coverage_for`,
`GlitchEnvelope` — all app-free and unit-tested); the screen that draws it is
`ui/tui/screens/transition.py`. It paints in whole terminal ROWS because
Textual's compositor replaces a cell outright whenever any widget paints it:
show-through exists only where the top screen paints nothing, so a covered row
is a `Static` of noise and an uncovered row is `visibility: hidden`. Intensity
is therefore just how many rows are covered — and at the peak that is all of
them, which is what hides the swap.

Knobs: `config.TRANSITION_ENABLED` / `_DURATION` / `_SWAP_AT` /
`_FRAME_INTERVAL` / `_START_INTENSITY` / `_FULL_COVER_AT` / `_MAX_BANDS` /
`_JITTER`. Sound: `transition_glitch`, fired once per window.

---

## Damage Glitch

A brief burst of the same signal-loss effect over the LIVE candidate page
after an admit that **damages Site Health** — the site glitching as something
gets inside it. Health itself lands in one batch at end of day, so without
this the moment a threat gets in passes with only a line of text.

| Admit | ⛨ | Colour | Effect |
|---|---|---|---|
| The Incompatible | −2 | violet `#c084fc` | a few torn rows, ~0.3s — easy to miss |
| Clumsy Cutie | −4 | yellow `#ffd93d` | noticeable |
| The Dark Web | −8 | green `#00ff9f` | heavy — and their admit is CORRECT by the rules |
| Bad Actor | −10 | red `#ff5470` | heavier |
| Sneaky Bugger | −12 | white `#e8f0f8` | briefly swallows the screen, ~0.9s |

The colour says *who* got in; the size says *how badly*. Every hue is one the
game already uses (severity yellow/orange/red, Overseer violet, terminal
green), so the burst never introduces a colour the player hasn't been taught
to read — the Dark Web's green is the "everything checks out" colour turned
against them, and the Sneaky Bugger's white is no colour at all.
`config.ARCHETYPE_GLITCH_TINT` is the table; `glitch.tinted_palette()` biases
the frame palette toward the hue (`DAMAGE_GLITCH_TINT_BIAS`, 0.7) rather than
flooding it — at 1.0 it stops reading as a broken signal and becomes a
coloured rectangle. Screen transitions keep the house palette: the tint
belongs to a verdict, and a screen change is nobody's fault.

Keyed off the verdict's recorded `site_health_delta`, not a list of
archetypes: a correct denial never fires it (health untouched), admitting the
White Hat never fires it either (+1 — rules-wrong, but the site is better for
it), and retuning `ARCHETYPE_HEALTH_WEIGHTS` retunes the whole scale.
`glitch.burst_shape()` maps the hit to (peak, duration);
`glitch.BurstEnvelope` hits at once and decays, with a stutter re-hit on the
heavier ones.

Unlike a screen transition it **never blocks** — NEXT stays live and the
keyboard keeps working, because the verdict window is skippable by design. The
rows are mounted onto `IntakeScreen` on its own `damage-glitch` CSS layer,
which is what lets them cover the page without rearranging it.

Code: `IntakeScreen._begin_damage_glitch` / `_render_damage_glitch` /
`_end_damage_glitch` (torn down from `_end_verdict_reveal`, so every candidate
load and the unmount path both clear it). Knobs:
`config.DAMAGE_GLITCH_ENABLED` / `_MIN_DURATION` / `_MAX_DURATION` /
`_MIN_PEAK` / `_MAX_PEAK` / `_CURVE` / `_RE_HIT_ABOVE` / `_FRAME_INTERVAL` /
`_TINT_BIAS` / `_TINT_DEFAULT` · `config.ARCHETYPE_GLITCH_TINT`.

---

## Verdict Reveal Window

Fires on every verdict; ~3s, fully skippable (NEXT is enabled before the window
opens). Three channels, each answering a different question — plus the Damage
Glitch above, which fires only when the admit cost the site something:

| Channel | Question | Where |
|---|---|---|
| Chat reaction | "how did that land on the person?" | `reactions.py` → `ChatPanel.post_reaction` |
| Border pulse | "was I right?" | `IntakeScreen._begin_verdict_reveal` + the `vf-*` classes at the end of `app.tcss` |
| Board grading | "were my individual calls right?" | `EvidenceState.reveal` |

Pulse targets all nine panels that can be on screen (dossier, chat, both
Candidate-page boards, the verdict panel, and all four tool-page boards) —
A/D work from any page, so a verdict delivered while reading a log still reads.

Only the pulse is time-boxed. The chat reaction and the graded board persist
until the next candidate loads: a grade that erases itself after three seconds
is a grade nobody gets to use.

Knobs: `config.VERDICT_REVEAL_ENABLED` / `_DURATION` / `_PULSE_INTERVAL`.

---

## Rules Modal — Five Tabs

| Tab | Contents |
|-----|----------|
| **Rules** | Today's disqualifying rules · minor discrepancy rules · general principles · tool costs · economy summary · email domain lists · affiliation lists |
| **OSINT** | Signal definitions (EMAIL_GITHUB_MISMATCH, BREACH_HIT, SOCK_PUPPET_ACCOUNTS) · legitimate platforms list · threat-actor platforms list · investigation tiers |
| **Credentials** | Hash type identification guide (MD5/SHA-1/SHA-256/bcrypt) · violation definitions (LEAKED_PASSWORD, WEAK_CREDENTIAL) · auth log reading guide · investigation tiers |
| **Log Analysis** | What log analysis is · log entry format · event types · attack patterns (BRUTE_FORCE, CREDENTIAL_STUFFING, IMPOSSIBLE_TRAVEL, INSIDER_BEHAVIOR) · investigation tiers |
| **Steganography** | What LSB steganography is · suspicion score ranges · detection signals (chi-square, RS analysis, autocorrelation) · difficulty channels · violation types (STEGO_PAYLOAD_PRESENT, COVERT_C2_CHANNEL) · investigation tiers |

---

## Key Bindings

All bindings are defined in `gameengine/config.py → KEY_BINDINGS`. Change there to remap everywhere.

### Immediate (no Enter required)

| Key | Action |
|-----|--------|
| `1` | Page: Candidate |
| `2` | Page: Ghostscan |
| `3` | Page: Hashcrack |
| `4` | Page: Logwatch |
| `5` | Page: Stegotool |
| `0` | Open Rules modal |
| `↑` / `↓` | Cycle widget focus within current page |
| `←` / `→` | Cycle widget focus (same as ↑/↓) |
| `` ` `` | Toggle debug panel |

### Command Bar (type + Enter)

| Command(s) | Action | Cost |
|------------|--------|------|
| `recon` · `ghostscan` · `g` | Run Ghostscan | 5⏱ |
| `crack` · `hashcrack` · `h` | Run Hashcrack | 3⏱ |
| `analyze` · `logwatch` · `l` | Run Logwatch | 4⏱ |
| `extract` · `stegotool` · `stego` · `s` | Run Stegotool | 2⏱ |
| `filter` · `f` | Run filter on current tool page | +2–4⏱ |
| `admit` · `a` | Admit candidate | — |
| `deny` · `d` | Deny candidate | — |
| `next` · `n` | Next candidate | — |
| `rules` | Open rules modal | — |
| `help` · `?` | Show help text in command bar | — |
| `quit` · `exit` · `q` | Quit game | — |

Unrecognised input: random in-universe error message (PERMISSION DENIED / ACCESS RESTRICTED / etc.)

---

## Progressive Disclosure — All Four Tools

| Tier | Cost | What appears in terminal |
|------|------|--------------------------|
| **Free** (on candidate load) | 0⏱ | Raw data — anomalies present but unlabelled |
| **Base run** | tool cost ⏱ | Analysis output — patterns flagged, values highlighted |
| **Filter** | base + filter cost ⏱ | Explicit confirmation — named violation, `▲ VIOLATION_TYPE` |

---

## Economy

| Event | Effect |
|-------|--------|
| Correct admit or deny | +15⏱ base |
| Evidence board accuracy bonus | +0–10⏱ |
| False admit (invalid candidate) | −1 life |
| False deny (valid candidate) | No penalty — just lost reward |
| Run Ghostscan | −5⏱ |
| Run Hashcrack | −3⏱ |
| Run Logwatch | −4⏱ |
| Run Stegotool | −2⏱ |
| Ghostscan filter | −3⏱ additional |
| Hashcrack filter | −4⏱ additional |
| Logwatch filter | −3⏱ additional |
| Stegotool filter | −2⏱ additional |

Starting compute: 50⏱ · Site Health: 100% · HackDox Credits: 1

---

## CSS / Theming

File: `gameengine/ui/tui/app.tcss`

| Colour | Role |
|--------|------|
| `#0b0e10` | Screen background |
| `#0f1419` | Panel background |
| `#00ff9f` | Accent green — active borders, prompt, correct |
| `#7dd3c0` | Cyan — titles, labels, headers |
| `#c8d4e1` | Body text |
| `#6b7785` | Dim labels |
| `#c084fc` | Purple — Overseer, filter output |
| `#ffd93d` | Yellow — minor severity |
| `#ff8c42` | Orange — major severity |
| `#ff5470` | Red — critical severity, hostile chat |

---

## Files

| File | Purpose |
|------|---------|
| `gameengine/ui/tui/app.py` | `HackDoxApp` — screen stack, transitions, day lifecycle |
| `gameengine/ui/tui/glitch.py` | Glitch frames for both effects (frame builder, palettes, envelopes, `RowPainter`) |
| `gameengine/ui/tui/screens/transition.py` | `TransitionScreen` — draws the glitch, blocks input |
| `gameengine/ui/tui/app.tcss` | All CSS for TUI layout and theming |
| `gameengine/config.py` | `KEY_BINDINGS`, tool costs, economy constants |
