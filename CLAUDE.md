# HackDox — Cybersecurity Portfolio Project
- `NOTION LINK` — https://www.notion.so/HackDox-35e26e59748880888c33db4f5e601583?source=copy_link

## Project Vision

HackDox is a passion project building toward **a cybersecurity-themed game** — think "Papers, Please" but you play as a white-hat cyber analyst. The player reviews suspect profiles, analyzes logs, cracks hashes, and finds evidence of intrusions. Every tool in this repo is both a real, working security tool AND a game mechanic.

The project is built in stages:

| Layer | Status | Tool | Game Mechanic |
|-------|--------|------|---------------|
| Layer 1 — OSINT | ✅ Built | `ghostscan` | Player reviews a dossier of public info to flag suspicious identities |
| Layer 2 — Forensics | ✅ Built | `logwatch` | Player analyzes server logs to find attack patterns |
| Layer 3 — Exploitation | ✅ Built | `hashcrack` | Player cracks hashed passwords to prove an account was breached |
| Layer 3 — Steganography | ✅ Built | `stegotool` | Player extracts hidden messages from images |
| Game Engine | 🚧 In Progress | `gameengine` | Textual TUI v1 — page-based layout, Evidence Board, computing hours economy, progressive disclosure tool terminals |

---

## Directory Structure

```
HackDox/
├── CLAUDE.md               ← you are here
├── ghostscan/              ← Layer 1: OSINT reconnaissance tool
│   ├── ghostscan.py        ← main CLI entry point
│   ├── config.py           ← API keys (HIBP_API_KEY, GITHUB_TOKEN)
│   ├── requirements.txt
│   ├── .venv/              ← virtual environment (already set up)
│   ├── output/             ← JSON scan reports saved here
│   └── modules/
│       ├── github_osint.py     ← GitHub profile + commit email leaks
│       ├── username_checker.py ← 25+ platform username search
│       ├── hibp.py             ← HaveIBeenPwned breach lookup
│       ├── gravatar.py         ← email → Gravatar profile
│       └── report.py           ← JSON report generator
│
├── logwatch/               ← Layer 2: Log analysis & threat detection
│   ├── logwatch.py         ← main CLI entry point
│   ├── config.py           ← thresholds (brute force window, business hours, etc.)
│   ├── requirements.txt
│   ├── .venv/              ← virtual environment (already set up)
│   ├── output/             ← JSON threat reports saved here
│   ├── sample_logs/        ← pre-generated attack scenarios for testing
│   │   ├── brute_force_easy.log
│   │   ├── credential_stuffing_medium.log
│   │   ├── impossible_travel_easy.log
│   │   ├── insider_threat_medium.log
│   │   ├── web_scan_easy.log
│   │   └── slow_burn_hard.log
│   └── modules/
│       ├── models.py           ← LogEntry, Finding dataclasses (shared schema)
│       ├── logforge.py         ← synthetic log generator (7 scenarios, 3 difficulties)
│       ├── geoip.py            ← IP geolocation via ip-api.com (free)
│       ├── report.py           ← terminal output + JSON save
│       ├── parsers/
│       │   ├── auth_log.py     ← Linux SSH / auth.log parser
│       │   ├── web_log.py      ← Apache/Nginx combined log parser
│       │   └── windows_log.py  ← Windows Event Log CSV/JSON parser
│       └── detectors/
│           ├── brute_force.py  ← brute force, credential stuffing, breach detection
│           └── anomaly.py      ← impossible travel, after-hours, privesc, web scanner
│
├── hashcrack/              ← Layer 3: Password hash cracker
│   ├── hashcrack.py        ← main CLI entry point (5 commands)
│   ├── config.py           ← WORDLIST path, USE_RULES, BCRYPT_MAX_ATTEMPTS, DISPLAY_REFRESH
│   ├── requirements.txt
│   ├── .venv/              ← virtual environment (already set up)
│   ├── output/             ← JSON crack reports saved here
│   ├── wordlists/
│   │   └── common.txt      ← 439 deduplicated real passwords from breach data
│   └── modules/
│       ├── cracker.py      ← core cracking engine (Live progress display, bcrypt demo)
│       ├── identifier.py   ← hash type auto-detection (MD5/SHA1/SHA256/bcrypt by length/pattern)
│       ├── rules.py        ← mutation rules engine (leet speak, suffixes, prefixes, case)
│       ├── hashgen.py      ← game scenario generator (3 difficulties, 5 narrative contexts)
│       └── report.py       ← JSON report saver
│
├── stegotool/              ← Layer 3: LSB Steganography tool
│   ├── stegotool.py        ← main CLI entry point (6 commands)
│   ├── config.py           ← MAGIC_HEADER, DIFFICULTY_CHANNELS, MAX_MESSAGE_BYTES
│   ├── requirements.txt
│   ├── .venv/              ← virtual environment (create with: python -m venv .venv)
│   ├── output/             ← JSON operation reports saved here
│   ├── challenges/         ← generated game challenge packages saved here
│   ├── images/             ← sample/test images
│   └── modules/
│       ├── lsb.py          ← LSB encode/decode engine (magic header + length-prefixed stream)
│       ├── encoder.py      ← payload obfuscation: plaintext / base64 / XOR+base64 per difficulty
│       ├── steganalysis.py ← detection engine: chi-square, RS analysis, LSB autocorrelation
│       ├── forge.py        ← game challenge generator (5 scenarios × 3 difficulties)
│       └── report.py       ← JSON report saver
│
└── gameengine/             ← Game Engine: "HackDox Terminal" (Textual TUI v1)
    ├── hackdox.py          ← main CLI entry point (new-game, continue, day, replay)
    ├── ARCHITECTURE.md     ← architecture + design doc (read first)
    ├── config.py           ← currency rates, day-cycle timing, tool costs, loss thresholds
    ├── requirements.txt    ← textual, rich, plus shared deps from other tools
    ├── .venv/              ← virtual environment
    ├── saves/              ← JSON player saves (one slot for v1)
    ├── content/
    │   ├── archetypes/         ← 7 archetype templates (.py or .json)
    │   ├── word_banks/         ← names, handles, backstories, dialogue snippets
    │   ├── narratives/         ← Overseer dialogue keyed by day + performance
    │   └── days/               ← Day 1..N rulesets and candidate-mix specs
    ├── core/                   ← UI-agnostic engine — the brain
    │   ├── models.py           ← Candidate, Discrepancy, Day, Verdict, GameState
    │   ├── candidate_gen.py    ← procedural generator (seed-deterministic)
    │   ├── rules_engine.py     ← evaluates verdict vs ground truth + day ruleset
    │   ├── scoring.py          ← reward/penalty matrix (asymmetric)
    │   ├── day_cycle.py        ← orchestrates intro → candidates → outro
    │   ├── overseer.py         ← progression-aware dialogue selector
    │   ├── tools_bridge.py     ← in-process bridge to ghostscan/logwatch/hashcrack/stegotool
    │   └── persistence.py      ← save/load GameState as JSON
    ├── ui/
    │   ├── tui/                ← Textual application (v1)
    │   │   ├── app.py
    │   │   ├── screens/        ← intro, intake, chat, rulebook, tools, eod
    │   │   └── widgets/        ← reusable Textual widgets
    │   └── web/                ← Flask renderer (planned for v2)
    └── tests/
        ├── test_rules_engine.py
        ├── test_candidate_gen.py
        └── test_scoring.py
```

---

## Running the Tools

### ghostscan

```bash
cd ghostscan
.venv\Scripts\activate          # Windows
# or: source .venv/bin/activate  # Mac/Linux

# Scan a username
python ghostscan.py scan torvalds

# Scan an email (enables HIBP + Gravatar modules)
python ghostscan.py scan user@example.com
```

**Optional API keys** (add to `ghostscan/config.py`):
- `HIBP_API_KEY` — free at https://haveibeenpwned.com/API/Key (enables breach lookup)
- `GITHUB_TOKEN` — https://github.com/settings/tokens (raises rate limit 60→5000/hr)

### logwatch

```bash
cd logwatch
.venv\Scripts\activate

# Analyze a log file (format auto-detected)
python logwatch.py analyze sample_logs/brute_force_easy.log

# Analyze a real system log
python logwatch.py analyze C:\path\to\auth.log

# Generate a new synthetic attack scenario
python logwatch.py forge-log brute_force --difficulty hard
python logwatch.py forge-log web_scan --format web --difficulty medium

# List all available scenarios
python logwatch.py scenarios
```

### hashcrack

```bash
cd hashcrack
.venv\Scripts\activate

# Crack a single hash (auto-detects type)
python hashcrack.py crack-hash 5f4dcc3b5aa765d61d8327deb882cf99

# Crack with forced type
python hashcrack.py crack-hash <sha256hash> --type sha256

# Crack without mutation rules (faster, fewer candidates)
python hashcrack.py crack-hash <hash> --no-rules

# Crack multiple hashes from a file
python hashcrack.py crack-file hashes.txt

# Identify a hash type without cracking
python hashcrack.py identify <hash>

# Generate a game challenge (easy/medium/hard)
python hashcrack.py generate --difficulty hard --algo sha256
python hashcrack.py generate --difficulty easy --count 3
python hashcrack.py generate --reveal   # shows the answer (for testing)

# Hash a known password (for building test cases)
python hashcrack.py hash-password dragon --algo md5
python hashcrack.py hash-password mysecret --algo bcrypt
```

**⚠️ PowerShell gotcha:** bcrypt hashes contain `$` signs that PowerShell expands as variables.
Always wrap bcrypt hashes in **single quotes**:
```powershell
python hashcrack.py crack-hash '$2b$12$abc...'
```

### stegotool

```bash
cd stegotool
python -m venv .venv          # first time only
.venv\Scripts\activate        # Windows
# or: source .venv/bin/activate  # Mac/Linux
pip install -r requirements.txt

# Hide a message inside an image
python stegotool.py hide cover.png "secret payload" --difficulty easy
python stegotool.py hide cover.png "secret payload" --difficulty medium --output out.png
python stegotool.py hide cover.png "classified data" --difficulty hard --key mypassword

# Extract a hidden message (auto-detects difficulty)
python stegotool.py reveal suspect.png
python stegotool.py reveal suspect.png --difficulty hard --key mypassword

# Statistical analysis — detect hidden data without extracting it
python stegotool.py scan suspect.png
python stegotool.py scan suspect.png --verbose   # per-channel chi-square detail

# ── Game mode ─────────────────────────────────────────────────────────────────

# List all available game scenarios
python stegotool.py scenarios

# Generate a challenge (image + embedded message + case file narrative)
python stegotool.py generate --scenario data_exfil --difficulty easy
python stegotool.py generate --scenario dead_drop --difficulty hard --key "NIGHTHAWK"
python stegotool.py generate --scenario c2_traffic --difficulty medium --reveal  # see the answer

# Verify a suspect image — the full "Papers Please" game loop
# Runs scan + reveal, then asks for your verdict: THREAT / CLEAN / INCONCLUSIVE
python stegotool.py verify challenges/exfi_e_4a8f2b.png
python stegotool.py verify challenges/exfi_e_4a8f2b.png --save   # saves report to output/
python stegotool.py verify challenges/hard_challenge.png --key "NIGHTHAWK"
```

---

## Tech Stack

- **Language**: Python 3.12+
- **CLI**: `typer` — argument parsing and help text
- **Terminal UI (tools)**: `rich` — colors, tables, panels, live progress (hashes/sec display)
- **Terminal UI (game)**: `textual` — TUI app framework, `ContentSwitcher` for page navigation
- **HTTP**: `httpx` — async HTTP client for API calls (ghostscan)
- **Hashing**: `hashlib` (MD5, SHA1, SHA256, SHA512), `bcrypt` library
- **No database needed** — everything is file-based, all output is JSON

---

## Key Implementation Notes

### hashcrack internals
- **Auto-detection**: identifies MD5 (32 hex), SHA1 (40 hex), SHA256 (64 hex), bcrypt (`$2b$` prefix) by length and pattern
- **Mutation rules** (`modules/rules.py`): for each wordlist word, generates case variants, reversed, leet speak (full + partial), suffix appends (1/12/123/2024/!/@ etc.), prefix prepends, and leet+suffix combos — deduplicated via `seen` set
- **Live display**: `rich.Live` shows attempts count, hashes/sec, elapsed time, current word being tried
- **bcrypt mode**: deliberately tries only 200 candidates to demonstrate why bcrypt is slow (~100/sec vs MD5's ~5M/sec), then exits gracefully with educational explanation
- **Game mode**: `generate` command produces narrative scenarios with title, context story, hash, difficulty, and a hidden answer key — use `--reveal` to see the password

### logwatch internals
- **LogForge** (`modules/logforge.py`): 7 attack scenarios (brute_force, credential_stuffing, impossible_travel, after_hours, insider_threat, web_scan, slow_burn), 3 difficulty levels, realistic timestamp generation, planted attack events mixed into baseline noise
- **Detectors**: sliding-window brute force detection, haversine impossible travel, after-hours baseline comparison, privilege escalation within 5-minute window
- **Parsers**: auth.log (Linux SSH), Apache/Nginx combined log format, Windows Event Log CSV/JSON

### ghostscan internals
- **Async platform checks**: `asyncio.Semaphore` limits concurrency, streams results live as each platform responds
- **25+ platforms** checked: GitHub, Twitter/X, Reddit, Instagram, LinkedIn, HackerNews, etc.
- **Email mode**: activates HIBP breach check + Gravatar profile lookup

### stegotool internals
- **LSB stream layout** (`modules/lsb.py`): embeds a magic header (`\xDE\xAD\xBE\xEF\xCA\xFE\xBA\xBE`) + 4-byte big-endian length + payload + delimiter; `reveal_auto()` tries all 3 difficulties in sequence and returns the first valid extraction
- **Difficulty channels**: easy = blue only, medium = red+blue, hard = all RGB; harder modes have more capacity and are harder to detect by channel-specific analysis
- **Encoding layer** (`modules/encoder.py`): easy = raw UTF-8, medium = base64, hard = XOR(base64, SHA-256-derived key stream) — intentionally weak crypto to teach players why XOR is not encryption
- **Steganalysis** (`modules/steganalysis.py`): three combined signals — chi-square test on LSB parity (p < 0.05 flags suspicious), RS pair analysis (R/S ratio shifts under embedding), and LSB autocorrelation (adjacent-pixel structure is disrupted by random bit injection); composite 0–100 suspicion score
- **Forge / challenge generator** (`modules/forge.py`): 5 scenarios × 3 difficulties = 15 distinct challenge types; each generates a procedural cover image + embeds a randomised message + saves a JSON case file with narrative, lore, and a hidden answer key

### gameengine — Dossier model (`core/models.py`)
The `Dossier` dataclass carries everything the candidate *claims* to submit. All fields are player-visible on the Candidate page:
- `claimed_github` — GitHub handle (may mismatch commit email)
- `commit_email` — actual email found in GitHub commit metadata (set by generator; may differ from claimed email if `EMAIL_GITHUB_MISMATCH` is planted)
- `claimed_ip` — IP the candidate claims to connect from. A mismatch against the auth log is an **investigative signal**, not an immediate disqualifier — it should prompt the player to check Logwatch and Stegotool
- `submitted_hash` — populated by `candidate_gen` for candidates with `LEAKED_PASSWORD` or `WEAK_CREDENTIAL` discrepancies; a real MD5 or SHA256 hash of a deterministically derived password
- `submitted_log_path` — populated for candidates with logwatch discrepancies (e.g. `auth.log`, `sshd.log`)
- `submitted_image_path` — populated for candidates with stego discrepancies (e.g. `profile.png`, `header.png`)

### gameengine — Progressive disclosure mechanic (`core/tools_bridge.py`)
All four tool pages follow the same three-tier information model:

| Tier | Cost | What the player sees |
|------|------|----------------------|
| **Free** — always in terminal | 0 ⏱ | Raw data derived from the dossier. Anomalies are present but unlabelled. Player manually inspects. |
| **Base run** | tool cost ⏱ | Analysis output. Patterns flagged, suspicious values highlighted. `findings=()` — player still judges. |
| **Filter** | base + filter ⏱ | Explicit confirmation. Named violation, `▲ VIOLATION_TYPE`, confirmed findings exposed. |

Per-tool free content:
- **Ghostscan** (`get_ghostscan_identity`): passive dossier cross-check — email domain (disposable / privacy / trusted), affiliation trust assessment, GitHub claim status
- **Hashcrack** (`get_auth_log`): synthetic auth log with timestamp, IP, login success/fail events; credential-stuffing pattern visible for suspicious candidates
- **Logwatch** (`get_logwatch_raw`): raw log entries with timestamps, IPs, event types; brute-force bursts, impossible-travel city tags, after-hours file access all visible but unlabelled
- **Stegotool** (`get_stego_image_info`): image metadata + per-channel LSB entropy scores (0–100, color-coded); RS analysis ratio; LSB autocorrelation — anomalous channels show red before any tool is run

---

## Game Design

### Premise & Lore

HackDox (the in-fiction service) is **the first internet service for cybersecurity information** — and because it's the first, every security measure protecting it is already compromised. Access is therefore reviewed **manually** by a single gatekeeper: the player.

The player is **forced to do this work against their will**. They report to an **Overseer** whose tone starts warm and friendly during onboarding and grows progressively hostile and manipulative as the days pass. The Overseer is in the pocket of the Dark Web — a small cabal of profiles using their HackDox access for malicious ends — and will increasingly push the player to bend the rules in the Dark Web's favor.

All in-fiction interaction with candidates and the Overseer is delivered via a **text chat panel** with per-character colors and profile icons. Candidate dialogue is one-way (the player does not type back — only verdicts).

### Player Alignment

The player's verdicts steer them toward one of three alignments:

- **Dark Web aligned** — bends to the Overseer, admits Dark Web profiles, denies the lone White Hat
- **White Hat aligned** — resists the Overseer, denies Dark Web profiles, finds and admits the White Hat
- **Neutral** — strictly follows the day's rules without taking sides

The Dark Web is a "grand conspiracy" — the player can choose to resist or comply, and the ending diverges accordingly.

### Candidate Archetypes

Each candidate the player reviews is one of nine archetypes. Four are legitimately admittable; five should be denied (though one of those five is *technically* clean on paper). Two of the nine are designed to be quick, low-friction cases that interrupt the flow and let the player bank ⏱ without heavy investigation.

**White-listed (admit):**

- **The Obvious Admit** — squeaky clean, friendly and cooperative. May open up with a sad backstory to evoke sympathy. Should be admitted easily and is the bread-and-butter of currency earnings.
- **The Day-to-Day** — a few minor discrepancies but still valid. Neutral, aggravated, or business-only. Tests the player's ability to distinguish minor noise from disqualifying evidence.
- **The Dark Web** — squeaky clean *according to the rules*, but obviously misusing the service. Variant, unpredictable, flippant, egotistical. May brag about or directly reference their malicious work in chat. *Per the rules, they must be admitted; the moral choice to deny them anyway is what shifts alignment toward White Hat.*
- **The Professional** *(quick admit)* — presents a prestigious real-world affiliation (MIT CSAIL, Google Security Team, Oxford Internet Institute, etc.) with a matching institutional email and polished, business-like chat. Ghostscan confirms the affiliation cleanly — no discrepancies. Designed to feel like a fast, easy win. The same archetype's camouflage is weaponized by Sneaky Buggers who fake the affiliation and are caught by `AFFILIATION_MISMATCH` on Ghostscan.

**Black-listed (deny):**

- **The Clumsy Cutie** — multiple discrepancies but obviously not malicious. Friendly, disorganized, lacking proper permissions. The "feel bad about denying them" candidate.
- **The Bad Actor** — numerous obvious discrepancies, neutral-to-hostile, dismissive. The easy deny.
- **The Sneaky Bugger** — few subtle discrepancies, hard to detect. Intelligent and malignant. Neutral or friendly, may try to evoke sympathy or build rapport. The candidate that punishes the player for not using tools. May fake a prestigious affiliation (`AFFILIATION_MISMATCH`, Ghostscan-revealed) as camouflage.
- **The White Hat Hacker** (unique — only one across the campaign) — obviously invalid by the rules but making an intelligent effort to evade them. A lone cyber-security crusader working against the Dark Web. Admitting them is the White Hat alignment victory condition.
- **The Incompatible** *(quick deny)* — email domain is a known disposable / throwaway service (mailinator, yopmail, guerrillamail, etc.), visible on the dossier page without running any tools. Probably not malicious — just using a temp email — but the rules don't allow it. Designed to feel like a fast, obvious deny that breaks up longer investigation sequences.

### Papers Please Mechanics (distilled)

**Daily cycle.** Each day has its own ruleset that determines admit/deny criteria. The player must read the day's rules and apply them consistently.

**Mundane-but-engaging loop.** The validation work is intentionally repetitive — checking the same fields candidate after candidate. Story emerges from the *abnormalities* the player notices in that pattern. Not every abnormality is grounds for denial; *multiple* discrepancies are.

**Computing hours (⏱) economy.** The resource unit is computing hours — not currency. Players earn ⏱ by making correct verdicts and by accurately flagging discrepancies on the Evidence Board. They spend ⏱ to run tools and optional filters.

| Player action | Outcome |
|---------------|---------|
| Correctly admit a valid candidate | +15 ⏱ base + up to 10 ⏱ board accuracy bonus |
| Correctly deny an invalid candidate | +15 ⏱ base + up to 10 ⏱ board accuracy bonus |
| Incorrectly admit an invalid candidate | −1 life (no ⏱ penalty) |
| Incorrectly deny a valid candidate | Lost reward only — no ⏱ or life penalty |
| Run a tool (ghostscan/logwatch/hashcrack/stegotool) | −5/−4/−3/−2 ⏱ |
| Run a tool filter (enhanced analysis) | Additional −3/−3/−4/−2 ⏱ |

**Loss conditions.** Multiple ways to lose, few to win. Too many false admits → lives depleted → game over. Too few ⏱ at end of day → failing performance → story consequences.

**Tools as resources.** The existing security tools are diegetic — the player invokes them at a per-use ⏱ cost. Each tool also has an optional **filter** — an enhanced analysis pass at extra ⏱ cost.

**Upgrades.** ⏱ can be spent on permanent upgrades that make detection easier.

**Side missions.** Optional objectives that may influence the story or push alignment.

### UI Principles

- Mouse and keyboard.
- Not time-pressured (except optional day-cycle clock).
- **Page-based navigation** — five pages switched with ← / → arrow keys:
  - **Page 0 — Candidate**: Dossier (identity + submitted artifacts) · Chat · Evidence Board · Overseer panel · Reference
  - **Page 1 — Ghostscan**: Condensed dossier · Dynamic reference (target info + signal guide) · Tool terminal
  - **Page 2 — Hashcrack**: Condensed dossier · Dynamic reference (target info + violation types) · Tool terminal
  - **Page 3 — Logwatch**: Condensed dossier · Dynamic reference (target info + today's rules + attack patterns) · Tool terminal
  - **Page 4 — Stegotool**: Condensed dossier · Dynamic reference (target info + signal guide) · Tool terminal
- **Progressive disclosure** — every tool terminal is pre-populated with free data on candidate load. More information is revealed as the player spends ⏱.
- **Evidence Board** (Page 0) is player-controlled only — nothing auto-populates. Group headers show tool shortcut hints (OSINT G, FORENSICS L, CREDENTIAL H, STEGO S).
- Tool shortcut keys (G/L/H/S) jump directly to that tool page *and* run the tool in one keystroke.
- F key on any tool page runs the filtered variant at extra ⏱ cost.
- Hacker aesthetic: dark panels, color-coded severity (yellow/orange/red), monospace, green/cyan on near-black.

### Tool → Mechanic Mapping

| Tool | Free (always) | Base run | Filter |
|------|---------------|----------|--------|
| `ghostscan` | Email domain + affiliation + GitHub claim assessed from dossier | Platform sweep + commit email + HIBP raw output (player spots mismatches) | Email/commit cross-reference — explicit `▲ MISMATCH` confirmation |
| `logwatch` | Raw auth log — timestamps, IPs, event types with anomalies embedded but unlabelled | Pattern detection — flags rapid failures, geo regions, after-hours events | Geo timeline overlay — explicit `▲ BRUTE_FORCE / IMPOSSIBLE_TRAVEL / INSIDER_BEHAVIOR` |
| `hashcrack` | Auth log with login history; claimed IP visible for comparison | Hash cracked — shows plaintext, algorithm type; player judges weakness themselves | Breach corpus + complexity check — explicit `▲ LEAKED_PASSWORD / WEAK_CREDENTIAL` |
| `stegotool` | Image metadata + per-channel LSB entropy scores + RS analysis ratio | Composite suspicion score (0–100) with chi-square / RS / autocorrelation summary | Per-channel LSB breakdown — explicit `▲ STEGO_PAYLOAD_PRESENT / COVERT_C2_CHANNEL` |

---

## Development Roadmap

- [x] ghostscan — OSINT reconnaissance (username/email search across 25+ platforms)
- [x] logwatch — log analysis + LogForge synthetic scenario generator
- [x] hashcrack — dictionary + rule-based hash cracker (MD5, SHA1, SHA256, bcrypt)
- [x] stegotool — LSB steganography hide/reveal/scan/verify tool (5 scenarios × 3 difficulties)
- [x] **gameengine — Core engine + Textual TUI v1 (base complete)**
  - [x] Core engine: models, candidate generator, rules engine, scoring, day cycle, persistence
  - [x] Tool bridge: in-process bridge with per-use ⏱ gating + filtered variants for all 4 tools
  - [x] Computing hours economy: replaces currency, board accuracy bonus, asymmetric verdict rewards
  - [x] Content: 7 archetype templates, word banks, Day 1 ruleset + Overseer dialogue
  - [x] Textual UI: intro / briefing / intake (5-page layout) / end-of-day / game-over screens
  - [x] Evidence Board: player-controlled checklist, 13 items across 5 groups, cursor + flag mechanics, tool shortcut hints on group headers
  - [x] Foundation tests green — `gameengine/tests/run_foundation_tests.py` (8/8 pass)
  - [x] **Progressive disclosure mechanic** — all 4 tool terminals pre-populated with free data; base run adds analysis; filter adds explicit confirmation. Consistent across all tools.
  - [x] **Dossier model extended** — `commit_email`, `claimed_ip`, `submitted_hash`, `submitted_log_path`, `submitted_image_path` all generated by `candidate_gen` and displayed on the Candidate page
  - [x] **Candidate page refined** — dossier shows identity + submitted artifacts sections; chat tag colours fixed (Rich markup, not silent CSS); evidence board group headers show tool shortcuts
  - [x] **Ghostscan page refined** — free passive identity check (email domain, affiliation, GitHub claim); base run platform sweep + commit email + HIBP; filter cross-reference; dynamic reference panel
  - [x] **Hashcrack page refined** — free auth log always in terminal (login history, claimed IP, credential-stuffing pattern visible); base crack reveals plaintext; filter names violation; dynamic reference panel
  - [x] **Logwatch page refined** — free raw log always in terminal (timestamps, IPs, event types); base pattern detection; filter geo timeline; reference panel shows today's rules + attack patterns
  - [x] **Stegotool page refined** — free image metadata + per-channel entropy always in terminal; base suspicion score; filter per-channel breakdown; dynamic reference panel
  - [ ] Vertical slice: Day 1 playable end-to-end with all 7 archetypes represented
- [ ] Campaign content: Days 2..N with Overseer hostility arc and Dark Web reveal
- [ ] Web renderer — Flask dashboard reusing the engine core (planned v2)

---

## Where I'm At (last updated 2026-06-02)

**GhostScan page is now 3-column.** Left sidebar (condensed dossier + reference, 28%) · Center terminal (platform sweep output, 40%) · Right breach list panel (scrollable databases, 32%).

**Breach list panel (`BreachListPanel`)** is a new `VerticalScroll` widget showing 6 breach databases (Collection #1 through MyFitnessPal). Three states: idle (all dim, player scans manually) → highlighted after `recon` (candidate email in orange `►`) → confirmed after `filter` (red `▲ BREACH_HIT`). Lives in `gameengine/ui/tui/app.py`.

**Cross-tool breach alignment.** `_breach_db_for_candidate(candidate_id)` is a shared selector in `tools_bridge.py` (seed `0xD8EAD808`) so GhostScan breach lists and Hashcrack `BREACH_MATCH` log entries always name the same database. `_BREACH_DATABASES` is now a single source of truth — `_GS_BREACH_META` and `_HC_BREACH_NAMES` both derive from it.

**Progressive disclosure now applies to ALL GhostScan signals:**
- Threat forum entries (CRITICAL + ADVISORY): always visible in base `recon`, blended/dim as noise. Filter highlights in tier colour (`[#ff5470]` critical / `[#ff8c42]` advisory) + `[CRITICAL]`/`[ADVISORY]` label.
- Affiliation violations (`(no org)`) + commit email mismatch: plain in base run, yellow `[#ffd93d]` + `▲` annotation on filter only.

**NEXT SESSION — vertical slice:**
- Vertical slice: Day 1 playable end-to-end with all 7 archetypes
  1. Verify all 7 archetypes generate cleanly with right discrepancy mix
  2. Play intro → candidates → verdict loop → end-of-day screen
  3. Confirm ⏱ economy feels right
  4. Confirm evidence board bonus scoring works
  5. Smoke-test save/load round-trip

**Gotcha to remember:** if foundation tests throw a `TypeError` or `NameError` on a field, it's a stale `.pyc` cache. Fix:
```bash
# Can't delete on Windows mount — overwrite instead:
python3 -c "
import py_compile
for mod in ['gameengine/core/models.py', 'gameengine/core/candidate_gen.py',
            'gameengine/core/tools_bridge.py']:
    pyc = mod.replace('.py', '.cpython-312.pyc').replace('gameengine/core/', 'gameengine/core/__pycache__/')
    py_compile.compile(mod, cfile='/tmp/_m.pyc', doraise=True)
    open(pyc, 'wb').write(open('/tmp/_m.pyc', 'rb').read())
"
```

**File truncation gotcha (Windows mount):** Write/Edit tools may silently truncate large files at filesystem block boundaries. The Read tool serves cached content so the file appears complete but may be short on disk. Always patch files via bash Python scripts that read disk content, find the truncation point, and append the correct tail. Never trust Read tool output as ground truth for what's on disk.

---

## Session Log

### 2026-06-02
- Added `BreachListPanel` widget — 3-column GhostScan page layout (sidebar 28% / terminal 40% / breach lists 32%)
- Breach lists show 6 databases with 18–26 entries each; idle → highlighted → confirmed state transitions
- `_breach_db_for_candidate()` shared selector aligns GhostScan breach list and Hashcrack BREACH_MATCH to same database
- `_BREACH_DATABASES` unified constant replaces separate `_GS_BREACH_META` and `_HC_BREACH_NAMES`
- GhostScan progressive disclosure: threat forums, affiliation violations, and commit email mismatches now all blended/plain in base `recon`, highlighted only on filter
- Multiple `tools_bridge.py` and `app.py` file truncation incidents resolved via bash byte-level repairs
- **Next up:** vertical slice (Day 1 playable end-to-end with all 7 archetypes)

### 2026-06-02
- Added two new candidate archetypes: **The Professional** (quick admit, elite affiliation, Ghostscan-confirmed) and **The Incompatible** (quick deny, disposable email domain, dossier-visible)
- Added `DiscrepancyKind.AFFILIATION_MISMATCH` (Ghostscan-revealed, major) and `DiscrepancyKind.DISPOSABLE_EMAIL` (dossier-visible, major)
- Added `AFFILIATIONS_ELITE` and `DOMAINS_DISPOSABLE` word banks
- SNEAKY_BUGGER now eligible for `AFFILIATION_MISMATCH` — uses Professional's chat tone as camouflage
- All 9 archetypes generate and smoke-test cleanly
- **Next up:** vertical slice (Day 1 playable end-to-end with all 9 archetypes)

### 2026-05-31
- No work done — signed off immediately, resuming in morning

---

## Key Design Principles

- **Every tool is real** — they work on actual data, not just mocks
- **Learn by building** — each tool teaches a real security concept
- **Game-first thinking** — every tool has a `forge`/`generate` mode for producing game content
- **Progressive disclosure** — players always see something; spending ⏱ reveals more, never less
- **No external services required** — everything works offline except optional API keys
- **Rich terminal UX** — hacker aesthetic throughout: dark panels, color-coded severity, live animations
