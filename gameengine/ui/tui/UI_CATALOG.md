# HackDox TUI — Interface Catalog
*Last updated: 2026-05-30*

---

## Overview

The game runs as a single Textual `App` (`HackDoxApp`) that pushes and pops `Screen` objects.
The main play area is `IntakeScreen`, a five-page layout driven by a `ContentSwitcher`.
All player input during gameplay flows through a persistent `CommandBar` at the bottom of the screen.

---

## Screen Stack

```
HackDoxApp
 └── IntroScreen          (start menu)
      └── BriefingScreen  (overseer intro + day title)
           └── IntakeScreen  (main play loop — five pages)
                └── RulesScreen (modal overlay, 0 key)
           └── EODScreen   (end-of-day summary)
      └── GameOverScreen  (lives depleted)
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
- One-line strip: game title · day title · candidate slot · compute hours · lives · alignment bar · page tabs
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

### EvidenceBoard
- Player-controlled checklist of 13 flaggable items across 5 groups
- Groups: OSINT (G) · FORENSICS (L) · CREDENTIAL (H) · STEGO (S) · GENERAL
- `↑/↓` move cursor · `Space` toggle flag · cursor renders in green inverse
- Nothing auto-populates — player flags manually
- Board accuracy bonus: up to +10⏱ on correct verdict

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

Starting compute: 50⏱ · Starting lives: 3

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
| `gameengine/ui/tui/app.py` | All screens, widgets, and IntakeScreen game logic |
| `gameengine/ui/tui/app.tcss` | All CSS for TUI layout and theming |
| `gameengine/config.py` | `KEY_BINDINGS`, tool costs, economy constants |
