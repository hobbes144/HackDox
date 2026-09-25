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
    ├── hackdox.py          ← main CLI entry point (new-game, continue, day, replay, `lab` debug subcommand)
    ├── ARCHITECTURE.md     ← architecture + design doc (read first)
    ├── config.py           ← currency rates, tool costs, loss thresholds, unlock schedules, transition/glitch/audio/cipher tuning
    ├── requirements.txt    ← textual, rich, typer, httpx, bcrypt, pygame (audio) plus shared deps from other tools
    ├── .venv/              ← virtual environment
    ├── saves/              ← JSON player saves + audio_settings.json (volume knobs, kept separate from campaign state)
    ├── content/
    │   ├── archetypes/         ← 7 archetype templates (.py or .json)
    │   ├── word_banks/         ← names, handles, backstories, dialogue snippets
    │   ├── narratives/         ← Overseer dialogue keyed by day + performance + alignment band
    │   ├── days/               ← day_01..day_20.json — full 20-day campaign authored (see Where I'm At)
    │   └── audio/              ← SFX sources: raw_assets/ (licensed clips), sfx/ (generated placeholder tones), music/ (empty — no ambient tracks yet); generate_placeholders.py / process_raw_assets.py
    ├── core/                   ← UI-agnostic engine — the brain
    │   ├── models.py           ← Candidate, Discrepancy, Day, Verdict, GameState
    │   ├── candidate_gen.py    ← procedural generator (seed-deterministic)
    │   ├── rules_engine.py     ← evaluates verdict vs ground truth + day ruleset; diff_rulesets for rule-change narration
    │   ├── content_loader.py   ← day-file loading/validation, synthesize_day() procedural days 2-20 fallback, mutate_variable_rules, apply_severity_steps
    │   ├── scoring.py          ← reward/penalty matrix (asymmetric)
    │   ├── overseer.py         ← alignment-band selector (ending_for_state) + the campaign's 3 endings (issue #42)
    │   ├── audio.py            ← SoundManager — pygame.mixer wrapper, fail-soft, 24-id SFX registry, 3 volume knobs
    │   ├── ascii_map.py        ← resolution-independent world map rasterizer for the Logwatch Activity Report's origin map
    │   ├── tools_bridge.py     ← in-process bridge to ghostscan/logwatch/hashcrack/stegotool
    │   ├── logwatch_report.py  ← Logwatch Activity Report: built FROM the day log + its renderer (2026-09-19)
    │   └── persistence.py      ← save/load GameState as JSON
    ├── ui/
    │   ├── tui/                ← Textual application (v1)
    │   │   ├── app.py
    │   │   ├── app.tcss
    │   │   ├── UI_CATALOG.md       ← authoritative screen/widget/keybinding catalog — read alongside this file for TUI detail
    │   │   ├── rules_content.py    ← VIOLATION_CATALOG/VIOLATION_CLUSTERS/_CATCH/_EXAMPLE — single source for Rules pages + evidence board
    │   │   ├── shared.py           ← cross-page rendering helpers (banded panels, highlight rules)
    │   │   ├── glitch.py           ← shared engine for the screen-transition + damage-glitch CRT effects
    │   │   ├── reactions.py        ← per-archetype chat reaction lines (verdict reveal window)
    │   │   ├── screens/            ← intro, briefing, intake, rules (modal), eod, between_day, credit_reveal, game_over, campaign_end, transition, _narration (unlock/rule-change copy)
    │   │   └── widgets/            ← reusable Textual widgets — evidence board, dossier, tool terminals, breach_list, cipher_block, stego_image, log_list, status_header, typewriter, …
    │   └── web/                ← Flask renderer (planned for v2, not started)
    └── tests/                  ← 593+ tests across the legacy foundation runner and pytest (see Where I'm At for current pass count)
```

**Also accumulated at the repo root and elsewhere since the initial build:** `BUILD_PLAN.md` plus one `BUILD_PLAN_*.md` per batch/feature (Batch1 Progressive Unlock, Batch2 Difficulty/Replayability, Batch3 Playtest/Randomness, Batch4 UserFeedback/ContentGeneration, Batch5 MainGame Content, Issues50-60 Status, HashcrackCipherBlock, Credentials) — shipped-log detail beyond what's narrated below; `CONTENT_AUTHORING.md` — the authoring-surface map (which file owns days/rules/word banks/reference pages); `SPRINT_ROADMAP.md` — the backlog-sprint batch sequencing; `Jenkinsfile` + `JENKINS_SETUP.md` — a real, green Jenkins CI/CD pipeline (Session Log, 2026-09-01/04); `sim_pad.py` — a standalone simulator for tuning the Hashcrack cipher block's alignment feel outside the TUI; `hackdox.sh` — launcher script; `.claude/agents/rules-evidence.md` and `.claude/agents/progression-unlock.md` — two project-specific Claude Code subagents (the former owns keeping any `DiscrepancyKind`'s 5-stage touchpoint chain in sync; Session Log, 2026-09-14).

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
- `claimed_role` / `claimed_location` *(2026-09-19)* — the Logwatch Activity Report's header claims: role is a pure lookup from the stated purpose (`candidate_gen.PURPOSE_ROLES`), location an `OFFICE_CITIES` pick (disjoint from the attack-city pool). The claimed internal IP resolves to this city on the report.

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
- **Logwatch** (`get_logwatch_shared`, 2026-09-19 overhaul): the **Activity Report** — aggregate bars, 24h swimlane timeline, login origins, resource counts, analyst notes — computed from the day log. Attacks are *detected* (unclassified) but never named; the raw auth log is **sealed** in the right panel until the base run
- **Stegotool** (`get_stego_image_info`): image metadata + per-channel LSB entropy scores (0–100, color-coded); RS analysis ratio; LSB autocorrelation — anomalous channels show red before any tool is run

### gameengine — Hashcrack Cipher Block v2 (`ui/tui/widgets/cipher_block.py`, `core/tools_bridge.py`) *(2026-09-14/15)*

Replaced an entirely different v1 mechanic (an "aperture sweep" — moveable reveal windows, per-batch ⏱, a coverage threshold) that Nick rejected the same day he saw it: *"a spatial hunt wearing a cryptography costume"* — too redundant with the Stego stamp mechanic. v1's model, config, and tests were deleted outright, not adapted; don't reintroduce `evaluate_aperture`, `CIPHER_APERTURES_PER_BATCH`, `CIPHER_RESOLVE_COVERAGE`, `hint_region`, or `tint_boost` for Hashcrack.

v2 is a genuine two-stage decrypt:
- **Stage 0 (free):** the block header always shows the block's dimensions, its glyph alphabet, and its digest shape (e.g. "64 hex characters") — enough on its own to know which window fits and whether the credential is worth opening at all.
- **Stage 1 (costs the tool's base ⏱):** pick one of three decryption windows — MD5 / SHA-256 / bcrypt. A wrong pick: "no structure emerged," ⏱ lost, window stays open to retry. bcrypt is a deliberate trap — correctly identifying it as bcrypt is not the same as it being viable to open; it engages, then stalls.
- **Stage 2 (free once stage 1 resolves):** an alignment pad stepped along X and Y (`config.CIPHER_ALIGN_SPAN` / `CIPHER_ALIGN_FALLOFF`); each cell has its own tolerance, and cells within tolerance of the true alignment show plaintext — tiled across rows, read by consensus as you narrow in. A near-ship bug here: per-cell tolerance must be rolled `randint(0, tol)`, not `randint(1, tol)`, or being exactly right and being one step off render identically.
- `UNSALTED_STORAGE` skips both stages entirely — it arrives already decrypted.

Violation retier that came with this rework (also noted in the Evidence Catalog above): `CROSS_BREACH_REUSE` → Hashcrack **critical** (was major); `LEAKED_PASSWORD` → Hashcrack **major** (was critical); `UNSALTED_STORAGE` stays Dossier-tier, moved to the **CREDENTIAL** board group; `WEAK_ENCRYPTION` → Hashcrack **minor**, CREDENTIAL group. Group and tier are now deliberately decoupled — `rules_content.visible_catalog()` gates a kind by its own tool, not its board group. Suite was at 503 tests passing when this landed (2 container-only failures — missing `.wav` assets not staged on purpose, not a regression).

---

## Game Design

### Premise & Lore

**World (2026-09-25, replaces the old "first internet service for cybersecurity information" premise):** some years back a machine mind — *the Undertow* — got loose in the world's networks. Nothing sent down a wire can be trusted any more, and neither can the people who were good with computers. So anything that matters travels by ship: written to sealed drives on air-gapped machines and carried port to port by **bonded couriers**. HackDox is **the data docks** — the pier where that freight is loaded — and the player is the clerk at its gate, deciding who gets a courier bond (admit) and who is turned back (deny). The gate terminal is air-gapped; everything the tools read (breach archives, a snapshot of the open wire, port logbooks, submitted images and credentials) came in by boat. What the Undertow really is, and whether the smugglers are connected to it, is deliberately left open. Full world bible: `VOICE_GUIDE.md` §0.

The player is **forced to do this work against their will**. They report to an **Overseer** whose tone starts warm and friendly during onboarding and grows progressively hostile and manipulative as the days pass. The Overseer is in the pocket of the Dark Web — a small cabal of profiles using their HackDox access for malicious ends — and will increasingly push the player to bend the rules in the Dark Web's favor.

**Theme (2026-09-24): "hack" + "docks".** The job is told as dock work — the player is the clerk at the gate of a waterfront data terminal — and the Overseer is presented to players as **the Foreman** (she/her). Only player-visible text changed; code, file and key names keep `overseer`. `VOICE_GUIDE.md` (repo root) is the single source for the voice; the `dockside-voice` subagent owns the copy; `gameengine/tests/test_voice.py` enforces it.

All in-fiction interaction with candidates and the Overseer is delivered via a **text chat panel** with per-character colors and profile icons. Candidate dialogue is one-way (the player does not type back — only verdicts).

### Player Alignment

The player's verdicts steer them toward one of three alignments:

- **Dark Web aligned** — bends to the Overseer, admits Dark Web profiles, denies the lone White Hat
- **White Hat aligned** — resists the Overseer, denies Dark Web profiles, finds and admits the White Hat
- **Neutral** — strictly follows the day's rules without taking sides

The Dark Web is a "grand conspiracy" — the player can choose to resist or comply, and the ending diverges accordingly.

**Implemented 2026-09-12 (issue #42, Batch 5 Phase 5a — see Session Log):** `GameState.alignment` is a running ±10 counter, moved by each verdict's `moral_modifier` (sign-flipped on a deny). In the current content that means the Dark Web encounters spread across most of the campaign (`moral_modifier = -1` each) and the single, larger day-12 White Hat encounter (`moral_modifier = +4`). Crossing ±`config.ALIGNMENT_BAND_*_THRESHOLD` (currently ±4 — set at the White Hat's own single-encounter magnitude) locks in the White Hat- or Dark-Web-aligned ending; otherwise the campaign ends Neutral. `core/overseer.py`'s `ending_for_state` is a pure function of `GameState`, and `screens/campaign_end.py` renders the three authored epilogues.

### Candidate Archetypes

Each candidate the player reviews is one of nine archetypes. Four are legitimately admittable; five should be denied (though one of those five is *technically* clean on paper). Two of the nine are designed to be quick, low-friction cases that interrupt the flow and let the player bank ⏱ without heavy investigation.

**White-listed (admit):**

- **The Obvious Admit** — squeaky clean, friendly and cooperative. May open up with a sad backstory to evoke sympathy. Should be admitted easily and is the bread-and-butter of currency earnings.
- **The Day-to-Day** — a few minor discrepancies but still valid. Neutral, aggravated, or business-only. Tests the player's ability to distinguish minor noise from disqualifying evidence. *New v2 signals: `AFTER_HOURS_ACCESS`, `CLAIMED_IP_MISMATCH` — benign minor noise the player must learn to wave through.*
- **The Dark Web** — squeaky clean *according to the rules*, but obviously misusing the service. Variant, unpredictable, flippant, egotistical. May brag about or directly reference their malicious work in chat. *Per the rules, they must be admitted; the moral choice to deny them anyway is what shifts alignment toward White Hat.*
- **The Professional** *(quick admit)* — presents a prestigious real-world affiliation (MIT CSAIL, Google Security Team, Oxford Internet Institute, etc.) with a matching institutional email and polished, business-like chat. Ghostscan confirms the affiliation cleanly — no discrepancies. Designed to feel like a fast, easy win. The same archetype's camouflage is weaponized by Sneaky Buggers who fake the affiliation and are caught by `AFFILIATION_MISMATCH` on Ghostscan.

**Black-listed (deny):**

- **The Clumsy Cutie** — multiple discrepancies but obviously not malicious. Friendly, disorganized, lacking proper permissions. The "feel bad about denying them" candidate. *New v2 signals: `UNSALTED_STORAGE`, `CROSS_BREACH_REUSE`, `AFTER_HOURS_ACCESS`, `CLAIMED_IP_MISMATCH` — competence/hygiene failures, not malice.* *(2026-09-19: + `DISPOSABLE_EMAIL` — a throwaway sign-up address; day 1 slot 3's scripted deny beside its unsalted-password flag. Any non-Incompatible carrier is given a real disposable-domain email so the evidence exists.)*
- **The Bad Actor** — numerous obvious discrepancies, neutral-to-hostile, dismissive. The easy deny. *New v2 signals: `THREAT_FORUM_MATCH`, `CREDENTIAL_STUFFING`, `BURNER_IDENTITY`, `TYPOSQUAT_HANDLE`, `CROSS_BREACH_REUSE` — loud, obvious, and damning.* *(2026-09-19: + `STEGO_PAYLOAD_PRESENT` — a loud plaintext image payload, which also makes the carrier-shape kinds reachable for this archetype.)*
- **The Sneaky Bugger** — few subtle discrepancies, hard to detect. Intelligent and malignant. Neutral or friendly, may try to evoke sympathy or build rapport. The candidate that punishes the player for not using tools. May fake a prestigious affiliation (`AFFILIATION_MISMATCH`, Ghostscan-revealed) as camouflage. *New v2 signals: `LOW_AND_SLOW`, `ENCRYPTED_PAYLOAD`, `BURNER_IDENTITY`, `TYPOSQUAT_HANDLE`, plus the `AFTER_HOURS_ACCESS` / `CLAIMED_IP_MISMATCH` breadcrumbs — all filter-tier or tool-only, the reason this archetype demands the tools.*
- **The White Hat Hacker** (unique — only one across the campaign) — obviously invalid by the rules but making an intelligent effort to evade them. A lone cyber-security crusader working against the Dark Web. Admitting them is the White Hat alignment victory condition. *New v2 signals: `LOW_AND_SLOW`, `ENCRYPTED_PAYLOAD`, `BURNER_IDENTITY` — the same evasion craft as the Sneaky Bugger, but in service of the cause.*
- **The Incompatible** *(quick deny)* — email domain is a known disposable / throwaway service (mailinator, yopmail, guerrillamail, etc.), visible on the dossier page without running any tools. Probably not malicious — just using a temp email — but the rules don't allow it. Designed to feel like a fast, obvious deny that breaks up longer investigation sequences.

> **The Obvious Admit, The Professional, and The Dark Web carry no v2 evidence.** The first two must stay clean to be fast wins; the Dark Web must stay *clean according to the rules* so that denying them is a moral choice, not a rules call.

### Evidence Catalog — v2 additions

Ten new evidence pieces extend the board. Each one is **two-sided**: it must be planted by **violation generation** (`candidate_gen.ARCHETYPE_SPECS.eligible_kinds` + `_SEVERITY_REVEAL` + `_KIND_DESC`) *and* be flaggable in **evidence collection** (`app.EVIDENCE_ITEMS`), with a matching reveal path in `tools_bridge` and a predicate in `rules_engine`. Several reuse detection logic that already exists in the standalone tools (noted under "gen source").

| Evidence | `DiscrepancyKind` | Category · Tool | Reveal tier | Severity | Generation source |
|----------|-------------------|-----------------|-------------|----------|-------------------|
| Burner identity | `BURNER_IDENTITY` | OSINT · Ghostscan | base reveal · filter confirms | major | Account-creation dates clustered within days (Ghostscan platform sweep metadata) |
| Threat-forum handle match | `THREAT_FORUM_MATCH` | OSINT · Ghostscan | filter | critical | Formalises the CRITICAL/ADVISORY forum entries the Ghostscan page already renders |
| Typosquatted handle | `TYPOSQUAT_HANDLE` | OSINT · Ghostscan | free dossier cue · base/filter confirm | major | Lookalike of a trusted org/person handle (e.g. `g00gle-sec`) |
| Credential stuffing | `CREDENTIAL_STUFFING` | Forensics · Logwatch | base detect · filter names | major | LogForge `credential_stuffing` scenario (many accounts, few tries each) |
| After-hours access | `AFTER_HOURS_ACCESS` | Forensics · Logwatch | base · filter | minor | LogForge `after_hours` scenario (activity outside business hours) |
| Low-and-slow | `LOW_AND_SLOW` | Forensics · Logwatch | filter (hard to spot) | critical | LogForge `slow_burn` scenario (thresholds evaded by spreading thin) |
| Cross-breach password reuse | `CROSS_BREACH_REUSE` | Credential · Hashcrack | base crack · filter confirms | major | Cracked plaintext recurs across breach DBs — links the Ghostscan breach panel via `_breach_db_for_candidate` |
| Encrypted vs plaintext payload | `ENCRYPTED_PAYLOAD` | Stego · Stegotool | base score · filter decodes | critical | Stegotool hard-mode XOR encoding — deliberate obfuscation vs a casual hidden note |

**Archetype placement (eligible_kinds to add; severities feed each archetype's `DiscrepancyBudget`):**

- **The Day-to-Day** *(budget minor=1)* → `AFTER_HOURS_ACCESS`, `CLAIMED_IP_MISMATCH`, `WEAK_ENCRYPTION`
- **The Clumsy Cutie** *(minor=2, major=1)* → `UNSALTED_STORAGE`, `CROSS_BREACH_REUSE`, `AFTER_HOURS_ACCESS`, `CLAIMED_IP_MISMATCH`, `WEAK_ENCRYPTION`
- **The Bad Actor** *(major=2, critical=1)* → `THREAT_FORUM_MATCH`, `CREDENTIAL_STUFFING`, `BURNER_IDENTITY`, `TYPOSQUAT_HANDLE`, `CROSS_BREACH_REUSE` *(2026-09-19: budget is now minor=1/major=2/critical=1 and `STEGO_PAYLOAD_PRESENT` is eligible)*
- **The Sneaky Bugger** *(major=1, critical=1 — consider +minor=1 for breadcrumbs)* → `LOW_AND_SLOW`, `ENCRYPTED_PAYLOAD`, `BURNER_IDENTITY`, `TYPOSQUAT_HANDLE`, `AFTER_HOURS_ACCESS`, `CLAIMED_IP_MISMATCH`, `WEAK_ENCRYPTION`
- **The White Hat** *(critical=1)* → `LOW_AND_SLOW`, `ENCRYPTED_PAYLOAD`, `BURNER_IDENTITY`

**2026-08-16 revisions (playtest fixes, see Session Log below for the full list):** `CLAIMED_IP_MISMATCH` moved Dossier → **Logwatch** (Forensics) — the dossier's claimed-IP field never actually varied by violation; the mismatch only ever showed up in the Logwatch log, so that's what actually reveals it now (gated to Logwatch's unlock day). `UNSALTED_STORAGE` moved Hashcrack → **Dossier** — this is the reveal tier the original spec above called for ("free (hash shape)") but shipped as Hashcrack-only; the dossier password field now shows the stored value in the clear (⚠ UNSALTED marker) with no crack required. New kind `WEAK_ENCRYPTION` (Dossier, minor, free) fills the slot `CLAIMED_IP_MISMATCH` left behind — flags the password's encryption *algorithm* (MD5 chip) independent of whether the plaintext itself is any good, distinct from `WEAK_CREDENTIAL`.

**2026-09-19 revision — carrier SHAPE, a second Stegotool axis.** Three new Stegotool-tier kinds, all read off the *glyph* the carrier cells form on the stamp grid, independent of the carrier's colour (any colour can carry any shape): `SIGNAL_COMMS_PAYLOAD` (cross: a + or an X, major), `RECURSIVE_PAYLOAD` (closed hollow ring/diamond, critical), `HOSTILE_PAYLOAD` (2–4 parallel strokes that never touch, critical). A conventional carrier (the clumped blocks every stego image had before) plants none of them. They are **free riders, not budgeted**: `candidate_gen._roll_discrepancies` rolls them in a post-roll pass (like `_IMPLIED_KINDS`) only when the candidate actually carries a `_STEGO_ARTIFACT_KINDS` colour kind, only for `_SHAPE_ELIGIBLE_ARCHETYPES` (Bad Actor / Sneaky Bugger / White Hat — Bad Actor currently has no stego colour kind, so it never actually gets one), never on a `forced_violations` slot (scripted slots stay conventional), at most one per candidate (`_STEGO_SHAPE_KINDS`, also an `_EXCLUSIVE_ARTIFACT_GROUPS` entry), conventional with probability `config.STEGO_SHAPE_CONVENTIONAL_CHANCE` (0.55) and the rest split evenly. `tools_bridge.build_stego_image` derives `StegoImageData.shape`/`shape_kind`/`strokes` from ground truth (it never rolls a shape); conventional carriers are cell-for-cell unchanged. Board: new STEGO cluster "Payload Operation"; Day-1 rules `rule_signal_relay_payload` / `rule_recursive_payload` / `rule_hostile_payload`.

**2026-09-19 revision, round 2 — shapes fully in the rules.** *Scripted slots:* a `forced_violations` slot carrying a stego colour kind rolls a shape like any other; a day may author one (name the shape kind in `forced_violations`, validated at load) or pin a plain image (`"carrier_shape": {"<slot>": "conventional"}` → `Day.conventional_carrier_slots`). Day 12's White Hat is authored a `SIGNAL_COMMS_PAYLOAD` cross; day 11 slot 5 is pinned conventional to stay rules-clean. *Rule mutation:* `rule_signal_relay_payload` is `overseer_variable` (the only disqualifying-by-default variable rule) — a deny on days 1-7 and 11-19, advisory on days 8-10 and 20, announced by the generic flip lines; `rule_recursive_payload` stays fixed; **DW-06** `dw06_hostile_payload_leniency` (day 13, beside DW-05, re-listed through day 20) downgrades `HOSTILE_PAYLOAD` to a flag. *Bad Actor* now carries `STEGO_PAYLOAD_PRESENT`. *UNSALTED_STORAGE* (DOSSIER tier and group) is minor until `config.TOOL_UNLOCK_DAY["hashcrack"]` and major from then; its rule follows (`content_loader.apply_severity_steps`: flag, then deny) and the step is announced in that day's briefing. Day 1's duplicate `rule_unsalted_storage` / `rule_cross_breach_reuse` entries were removed and the loader now rejects duplicate rule ids. Sidebar reference panels (`shared.build_ref_*`) are derived from config/tools_bridge.

The evidence board is now 26 items *(30 as of 2026-09-19 — `rules_content.VIOLATION_CATALOG` is authoritative)*. Board categories, board order matches the tool-page order: **DOSSIER** (`MISSING_PUBLIC_PROFILE`, `HOSTILE_CHAT`, `AFFILIATION_UNVERIFIED`, `DISPOSABLE_EMAIL`) · **OSINT** (`BURNER_IDENTITY`, `THREAT_FORUM_MATCH`, `TYPOSQUAT_HANDLE`, + the pre-v2 Ghostscan kinds) · **CREDENTIAL** (`CROSS_BREACH_REUSE`, `WEAK_CREDENTIAL`, `LEAKED_PASSWORD`, `UNSALTED_STORAGE`, `WEAK_ENCRYPTION`) · **FORENSICS** (`CREDENTIAL_STUFFING`, `AFTER_HOURS_ACCESS`, `LOW_AND_SLOW`, `CLAIMED_IP_MISMATCH`, + the pre-v2 Logwatch kinds) · **STEGO** (`ENCRYPTED_PAYLOAD`, + the pre-v2 Stego kinds; 2026-09-19: + the carrier-shape row `SIGNAL_COMMS_PAYLOAD`, `RECURSIVE_PAYLOAD`, `HOSTILE_PAYLOAD`).

**2026-09-14/15 revision — the Hashcrack Cipher Block v2 rework retiers credential evidence and decouples group from tier.** `CROSS_BREACH_REUSE` → Hashcrack **critical** (was major — this had made it unreachable inside Clumsy Cutie's discrepancy budget, so it moved to Sneaky Bugger + Bad Actor instead); `LEAKED_PASSWORD` → Hashcrack **major** (was critical); `UNSALTED_STORAGE` stays Dossier-**tier** (free — the dossier shows the plaintext in the clear) but moved to the **CREDENTIAL** board **group**; `WEAK_ENCRYPTION` → Hashcrack **tier, minor**, CREDENTIAL group (superseding the 2026-08-16 note above, which is now history — it was Dossier-tier only briefly, between that fix and this one). Board group and reveal tier are now deliberately decoupled: `rules_content.visible_catalog()` gates a kind by *its own tool*, not by its board group, so `UNSALTED_STORAGE` and `WEAK_ENCRYPTION` show under CREDENTIAL from day 1 as an intentional partial category. See "gameengine — Hashcrack Cipher Block v2" further up (Key Implementation Notes) for the full mechanic.

### Papers Please Mechanics (distilled)

**Daily cycle.** Each day has its own ruleset that determines admit/deny criteria. The player must read the day's rules and apply them consistently. Each shift also carries an **admit quota** — a minimum number of candidates the player must admit (not necessarily *correctly*) to clear the day. Falling short of quota is a failing performance with story consequences, independent of Site Health.

**Mundane-but-engaging loop.** The validation work is intentionally repetitive — checking the same fields candidate after candidate. Story emerges from the *abnormalities* the player notices in that pattern. Not every abnormality is grounds for denial; *multiple* discrepancies are.

**Two distinct resources (resolved — issue #12).** The GDD previously blurred "currency" and "computing hours". They are now explicitly separate resources:

- **Computing hours (⏱)** — a *finite daily tool budget* (reworked by issue #27). A fixed pool granted at shift start via `config.daily_compute_budget(day, capacity)` (base 60, +4/day, floor 30), spent **only** on tools, filters, and stego stamps. **Verdicts never grant ⏱.** Never carries over; running out mid-day disables tools for the rest of the shift — no other punishment. Rationing the pool across the day's candidates is the core strategic decision.
- **HackDollar$** — a *persistent between-day currency*. Earned from correct verdicts + the evidence-board accuracy bonus (moved off ⏱ by #27) + end-of-day Site Health, tracked separately on `GameState`, and never reset. Spent only in the between-day menu (upgrades, HackDox Credits, ⏱-capacity). See issues #18 (Between Day Menu) and #21.

| Player action | Outcome |
|---------------|---------|
| Correctly admit a valid candidate | +8 HD\$ (decays to 5) + up to 4 HD\$ board accuracy bonus · Site Health ▲ |
| Correctly deny an invalid candidate | +3 HD\$ (decays to 2) + up to 4 HD\$ board accuracy bonus |
| Incorrectly admit a malicious candidate | Site Health ▼ (no ⏱ penalty) |
| Incorrectly deny a valid candidate | Lost reward only — no ⏱ or Site Health penalty |
| Run a tool (ghostscan/logwatch/hashcrack/stegotool) | −5/−4/−3/−1-per-stamp ⏱ |
| Run a tool filter (enhanced analysis) | Additional −3/−3/−4/−2 ⏱ |

**Loss condition — Site Health (%) (resolved — issue #12; replaces lives).** Lives are removed (issues #19 / #24). The loss condition is now a persistent **Site Health** percentage that carries across days and is modulated by performance: admitting malicious actors lowers it, admitting beneficial actors raises it. Drop below the failure threshold → game over; finish a day above the reward threshold → end-of-day bonus (issues #18 / #20). Too few admits (below the day's quota) is a *separate* failing-performance path.

**Tools as resources.** The existing security tools are diegetic — the player invokes them at a per-use ⏱ cost. Each tool also has an optional **filter** — an enhanced analysis pass at extra ⏱ cost. **Filters unlock progressively (resolved — issue #12, Q3):** each tool's filter becomes available on the day that tool is introduced, keeping tutorial pacing clean rather than exposing every filter from day one.

**Overseer & filter avoidance (resolved — issue #12, Q4).** When the player consistently works "bare-handed" (avoiding filters), the Overseer reacts **both** ways: a narrative tell (the Overseer comments on the approach) *and* a mechanic consequence — filter-avoidance correlates with lower accuracy, surfaced as an accuracy stat in the end-of-day summary.

**Upgrades.** HackDollar\$ can be spent in the between-day menu on permanent upgrades that make detection easier (including raising ⏱-capacity).

**Side missions.** Optional objectives that may influence the story or push alignment.

### UI Principles

- Mouse and keyboard.
- Not time-pressured (except optional day-cycle clock).
- **Page-based navigation** — five pages switched with ← / → arrow keys:
  - **Page 0 — Candidate**: Dossier (identity + submitted artifacts) · Chat · Evidence Board · Overseer panel · Reference
  - **Page 1 — Ghostscan**: Condensed dossier · Dynamic reference (target info + signal guide) · Tool terminal
  - **Page 2 — Hashcrack**: Condensed dossier · Dynamic reference (target info + violation types) · Tool terminal
  - **Page 3 — Logwatch** *(2026-09-19)*: sidebar (24%) · Activity Report (40%, free) · Auth log panel (36%, `LogListPanel`, sealed until L; `[`/`]` jump the target's rows)
  - **Page 4 — Stegotool**: Condensed dossier · Dynamic reference (target info + signal guide) · Tool terminal
- **Progressive disclosure** — every tool terminal is pre-populated with free data on candidate load. More information is revealed as the player spends ⏱.
- **Evidence Board** is a **global overlay** (`EvidenceScreen`, toggled with **Tab** from any page) — player-controlled only, nothing auto-populates. Findings are grouped into five categories (DOSSIER · OSINT · FORENSICS · CREDENTIAL · STEGO) navigated with ←/→; each finding can be assigned an **intensity** (minor/major/critical via 1/2/3, or `i` to cycle). Intensity is documentation-only — scoring still keys off the set of flagged `DiscrepancyKind`s. State lives in a headless `EvidenceLog` owned by `IntakeScreen` so it survives page nav + toggling.
- Tool shortcut keys (G/L/H/S) jump directly to that tool page *and* run the tool in one keystroke.
- F key on any tool page runs the filtered variant at extra ⏱ cost.
- Hacker aesthetic: dark panels, color-coded severity (yellow/orange/red), monospace, green/cyan on near-black.

### Tool → Mechanic Mapping

| Tool | Free (always) | Base run | Filter |
|------|---------------|----------|--------|
| `ghostscan` | Email domain + affiliation + GitHub claim assessed from dossier | Platform sweep + commit email + HIBP raw output (player spots mismatches) | Email/commit cross-reference — explicit `▲ MISMATCH` confirmation |
| `logwatch` | Activity Report: bars vs a normal-ceiling tick, timeline lanes, origins (claimed ✓/✗, Δ city changes), resource counts, alerts. Identifiable free: `CLAIMED_IP_MISMATCH`, `IMPOSSIBLE_TRAVEL`; visible: off-hours, insider counts; brute force / stuffing = one **unclassified** "authentication anomaly"; low-and-slow never alerts | Unseals the full auth log (right panel) — every row, target in yellow, **no labels**; player reads the attack's shape | `▲ VIOLATION` labels in the log + a `▲ CONFIRMED` block on the report (low-and-slow correlation, travel km/h) |
| `hashcrack` | *(superseded 2026-09-14/15 by the Cipher Block rework)* Block header only — dimensions, glyph alphabet, digest shape; tells you which decryption window fits and whether it's worth opening | Stage 1: spend ⏱ to pick MD5 / SHA-256 / bcrypt — a wrong pick burns ⏱ and stays open to retry; bcrypt engages, then stalls, on purpose | Stage 2, free once stage 1 resolves: step a 2-axis alignment dial to bring the plaintext into focus; `UNSALTED_STORAGE` skips both stages and arrives already decrypted — see "gameengine — Hashcrack Cipher Block v2" above (Key Implementation Notes) |
| `stegotool` | Pixel-grid image viewer (dominant right column) with subtle blue tint over hot zones + channel entropy stats in the findings terminal | **Stamp minigame** — X enters stamp mode; arrows move a square stamp, Space stamps (`config.STEGO_STAMP_COST` ⏱/stamp), revealing what the cells carry: color = payload type (amber plaintext / crimson encrypted / violet C2), density = carrier fill, size = zone extent, **shape = payload operation** (2026-09-19: the glyph the carrier cells trace — conventional blocks = nothing extra; cross = `SIGNAL_COMMS_PAYLOAD`; hollow ring/diamond = `RECURSIVE_PAYLOAD`; 2–4 parallel non-touching strokes = `HOSTILE_PAYLOAD`). Unfiltered, the resolve block only *describes* the glyph's geometry | Reveal ≥60% of the zone → signature resolves. With the classification filter (F): explicit `▲ STEGO_PAYLOAD_PRESENT / ENCRYPTED_PAYLOAD / COVERT_C2_CHANNEL`, plus a second `▲ SIGNAL_COMMS_PAYLOAD / RECURSIVE_PAYLOAD / HOSTILE_PAYLOAD` for a special glyph (never for conventional). Stamps replaced the old scan/filter tiers |

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
  - [x] **Stegotool stamp minigame rework** — 3-column page (sidebar 26% / findings terminal 34% / interactive image viewer 40%); X → stamp mode, arrows move, Space stamps (1 ⏱), ≥60% zone coverage resolves the ▲ signature. Replaces the stego scan/filter tiers.
  - [x] **Between-day macro loop (issues #18-#25, 2026-07-17)** — lives ripped out (#24); Site Health persistent % loss condition (#20); HackDollar$ persistent currency + per-shift ⏱ reset (#21); HackDox Credits ground-truth reveal via `reveal`/`credit`/`truth` command on every page (#25); 13-upgrade detection-assist catalog with auto-highlights + tool-cost reduction (#23); `BetweenDayScreen` with shift report, Overseer dialogue, and HackDollar$ shop wired EOD → menu → next-day intro (#22)
  - [x] **Issues #27-#30 (2026-07-18)** — finite-daily-⏱ economy (#27); banded, replace-in-place GhostScan report (#28); universal dossier password field + encryption-strength tiers + WEAK_CREDENTIAL minor rework (#29); dynamic engine-derived Rules Pages via `rules_content.py` (#30); stable-hash determinism fix
  - [ ] Vertical slice: Day 1 playable end-to-end with all 7 archetypes represented — not confirmed as a dedicated playtest milestone on its own, though everything below has exercised the mechanics it depends on heavily
- [x] **Campaign content: Days 2-20 authored, Dark Web directives, Overseer alignment bands, and 3 authored endings (2026-08-16 → 2026-09-13, Batches 1-5)** — the full 20-day campaign is authored end to end; see the Session Log for the batch/phase breakdown. Landed on a feature branch (currently `Stego-Shapes`) not yet merged to `main` (see Where I'm At).
  - [x] Batch 1 (2026-08-16) — progressive tool unlock (epic #2: #3, #31-34)
  - [x] Batch 2 (2026-08-16) — procedural day synthesis (`content_loader.synthesize_day`) + difficulty curves (#35, #38, #4, #17, #36)
  - [x] Batch 3 (2026-08-17) — playtest fixes & randomness hardening (#50-54, #56-60) + the `hackdox lab` debugging CLI (#52)
  - [x] Batch 4 (2026-08-18) — Days 1-5 fully authored + breach-DB unlock schedule (#61-63, #15, #43-49)
  - [x] Batch 5 (2026-09-12 → 09-13) — Dark Web directive mechanism, Days 6-20 authored, Overseer alignment bands, 3 campaign endings (#37, #39-42)
- [x] **Evidence Board — clickable chip-grid rework (2026-09-08)** — the flat 27-row checklist became a clustered, named, clickable button grid (`VIOLATION_CLUSTERS`)
- [x] **Verdict Reveal Window (2026-09-07)** — chat reaction + border pulse + evidence-board grading after every verdict
- [x] **Audio system (2026-09-07)** — `SoundManager`, 24-id SFX registry, pygame.mixer, fail-soft, 3 volume knobs (placeholder tones — pygame not yet installed on Nick's real machine)
- [x] **Screen transitions + damage glitch (2026-09-12)** — a CRT signal-loss effect over every screen change, plus a scaled, archetype-tinted burst on any admit that costs Site Health
- [x] **Hashcrack Cipher Block v2 (2026-09-14/15)** — the Hashcrack page rebuilt as a two-stage decrypt minigame, replacing the old crack-and-read-plaintext model; credential evidence tiers redistributed (see Evidence Catalog)
- [x] **Rules/Evidence subagent (2026-09-14)** — a dedicated Claude Code subagent (`.claude/agents/rules-evidence.md`) whose job is keeping any `DiscrepancyKind`'s full touchpoint chain in sync
- [x] **Jenkins CI/CD (2026-09-01/04)** — a real, green pipeline on Nick's own Jenkins (built as a PlayStation SDET II interview artifact, not a game feature); Lint stage cleaned to 0 real findings
- [x] **Logwatch Activity Report overhaul + origin map (2026-09-19/20)** — see the two most recent Session Log entries
- [ ] Web renderer — Flask dashboard reusing the engine core (planned v2)

---

## Where I'm At (last updated 2026-09-21)

The full 20-day campaign is now authored end to end (Batches 1-5, 2026-08-16 → 2026-09-13): progressive tool unlock, procedural-and-authored day content, Dark Web directives, the Overseer's alignment-band dialogue, and all three campaign endings (White Hat / Dark Web / Neutral) are built and wired (`core/overseer.py`, `screens/campaign_end.py`). Layered on since: a full audio pass (placeholder SFX, pygame-based, fail-soft), screen transitions plus a damage-glitch burst on any Site-Health-costing admit, a post-verdict feedback window (chat reaction + border pulse + evidence grading), a clickable chip-grid rework of the Evidence Board, a from-scratch v2 rebuild of the Hashcrack page as a two-stage Cipher Block decrypt minigame (with a matching credential-evidence retier), a Logwatch Activity Report overhaul with an ASCII origin map and honest travel noise, and — most recently — a second Stegotool axis where the carrier's *shape*, not just its color, can plant evidence. A real, green Jenkins CI/CD pipeline now runs the suite on every push (built as a PlayStation SDET II interview artifact). A dedicated Rules/Evidence subagent (`.claude/agents/rules-evidence.md`) exists specifically to keep the Discrepancy-kind touchpoint chain (generator → tool rendering → rules-page catalog → rules-engine predicate → day-file rules) from drifting, since that chain has been the single most common source of bugs across this build.

**Branch/commit state (verified 2026-09-21):** `main` is still at the 2026-09-11 Sound-branch merge (`f6d9e5f`). All of Batch 5, both Hashcrack cipher-block versions, and the carrier-shape/Logwatch-report work are on `Stego-Shapes` — 25 commits ahead of `main`, 0 behind — **not yet merged**. `Stego-Shapes` also currently carries uncommitted working-tree changes (`config.py`, `core/logwatch_report.py`, `core/tools_bridge.py`, `ui/tui/rules_content.py`, `ui/tui/screens/intake.py`, two test files, `UI_CATALOG.md`, and this file, plus a new untracked `core/ascii_map.py`) — this is the 2026-09-19/20 Logwatch-report/origin-map work narrated below, not yet committed as of this writing.

**Test suite:** 593 tests collected as of 2026-09-21 (up from 503 at the 2026-09-14 health-check baseline — the difference is the carrier-shape and Logwatch-report work added since). A run this session got through roughly 90% with no failing dots before hitting the shell's execution-time limit — not a confirmed full green run; re-run the suite properly before trusting it as a baseline.

**Known open items** (see Session Log for origin): issue #73 (dossier-tier evidence guard blind spot, filed 2026-09-14, unresolved); a dormant `DISPOSABLE_EMAIL` / `is_incompatible` ordering risk (0 live occurrences across a 2,800-candidate sweep, left as a flagged judgment call rather than fixed); `day_01.json` still declares `rule_cross_breach_reuse` twice; `_UNLOCK_LINES` in `_narration.py` still placeholder text, now largely redundant with the authored day 2-5 briefings; no in-game audio settings screen yet (volumes are file-only); `play_music()`/`stop_music()` are wired but nothing calls them (no ambient tracks exist); pygame not yet installed in Nick's actual Windows game environment (audio verified only in the Linux device-bridge sandbox); a GitHub Actions companion workflow for Jenkins hasn't been built.

**2026-09-25:** Endless Mode (#7) and the #70 balance pass are built on `Final-Game-Polish` (uncommitted) — see the Session Log entry and `BUILD_PLAN_EndlessMode_2026-09.md`.

**Next up:** merge `Stego-Shapes` into `main` (25 unmerged commits plus the current uncommitted logwatch/shape work is a lot to be carrying on a feature branch); a clean full-suite pytest run to confirm the 593-test baseline is actually green; then the still-deferred Day-1 vertical-slice playthrough and the Web renderer (v2).

## Where I Was (2026-07-18)

> **2026-08-16:** Epic #2 (progressive unlock, issues #3/#31-34) shipped via the backlog-sprint flow on branch `batch-1-progressive-unlock` (not yet pushed/merged to main), plus a round of ad-hoc playtest fixes. Neither is narrated here in full — see the Session Log entry below and the session's project memory (`planning_sprint.md` / `playtest_fixes.md`) for details. This section still reflects the 2026-07-18 state as the last fully-narrated milestone.

**GitHub issues #27-#30 ALL IMPLEMENTED & pilot-verified (2026-07-18).**
- **#27 Computing hours rework** — ⏱ is now a *finite daily budget*: `config.daily_compute_budget(day, capacity)` (STARTING_COMPUTE 60, DAILY_BUDGET_GROWTH 4, floor 30). Verdicts grant **zero ⏱**; the board-accuracy bonus moved to HD$ (folds into `hackdollar_delta`; `CandidateResult.compute_delta` deleted, `board_bonus` is now HD$). `Quotas.compute_target` removed everywhere (model, loader ignores legacy keys, EOD, `_evaluate_performance`). Status header colours the balance by scarcity + shows a live per-tool cost strip (`G5·H3·L4·S1`, upgrade-aware). Running dry just blocks tools (`InsufficientCompute`), no other penalty.
- **#28 GhostScan report UI** — report is now two banded sections: cyan `▌ PLATFORM SWEEP` (platforms + account registry) and orange `▌ BREACH DETECTION` (threat forums + breach dumps), via `_gs_band()`; candidate rows bumped to high-contrast `#e8f0f8/#c8d4e1`. Base run and filter both **REPLACE** the terminal (`ToolTerminal.set_result`) — the free identity block is folded into the report top, so nothing stacks.
- **#29 Dossier password field** — EVERY candidate now submits a credential: `Dossier.submitted_hash` universal + new engine-only `Dossier.password_plain`. Tiers by hash shape (`tools_bridge.password_strength`): bcrypt=STRONG (always safe, uncrackable — `crack_password()` returns None), SHA256=MEDIUM, MD5=WEAK. `WEAK_CREDENTIAL` reworked to **minor** = weak enc + weak plaintext; added to Day-to-Day + Clumsy eligible kinds + a weighted Day-1 rule. Dossier panels (full + 4 condensed) render `Password` row with colour-coded strength chip + crack state; a hashcrack run resolves it on every page (`cracked_password` convention: None/""/plaintext). Clean candidates get honest inline crack results (green ✓ lines). Strong-password bank `_HC_STRONG_PASSWORDS` + `_fake_bcrypt()`.
- **#30 Rules pages overhaul** — new module `gameengine/ui/tui/rules_content.py` is the **single source of truth**: `VIOLATION_CATALOG` (app's `EVIDENCE_ITEMS` imports from it), severities/tools from `candidate_gen._SEVERITY_REVEAL`, descriptions from `_DISCREPANCY_DESCRIPTIONS`, DENY/FLAG "TODAY" column scanned from the live Day's rule predicates, costs/upgrades/domain-lists from config + tools_bridge. All five tabs share a templated layout (title bands, HOW-IT-WORKS, per-group violation tables with severity colours + catch notes). Documents (accurately, per CURRENT engine): daily quotas + 4 performance tiers, Site Health (no lives), finite-⏱ economy + formula, HD$/credits/13-upgrade catalog, F1 board scoring ("flag everything" guidance corrected), alignment −10..+10 with moral modifiers, quick cases, AFFILIATION_MISMATCH vs UNVERIFIED, DISPOSABLE_EMAIL, breach-panel 3-state, SOCK_PUPPET naming, CREDENTIAL_STUFFING as a real flaggable kind, session-grouping upgrade, stamp-minigame stego tab.
- **Latent bugs fixed en route:** (1) all RNG seeding used builtin `hash()` — salted per process, so candidates/day-logs differed between runs (saves couldn't replay; tests were flaky). Replaced with `candidate_gen.stable_hash` (SHA-256) in candidate_gen + tools_bridge. (2) `cand_id` took the TOP hex digits of `UUID(int=hash & 128bits)` — all zeros for non-negative hashes (colliding ids). Now a direct sha256 digest slice. **Candidate rolls changed as a result** (expected, pre-release). (3) Added missing `rule_leaked_password` disqualifying rule to Day 1 so every Bad Actor roll trips ≥1 rule.
- Verified: **16/16 foundation tests** (new: budget formula, verdicts-never-grant-⏱, universal password invariants) · pytest twin 9/9 · full markup sweep (6 candidates × all tools × free/base/filter + all 5 rules tabs) rich-validated clean · **Textual pilot E2E**: ghostscan replace-not-stack, hashcrack resolves dossier password on all panels, rules tabs, full day loop → EOD → between-day → day-advance budget formula. **No truncation incidents** (all files tail-checked + compiled from disk after every write).

## Where I Was (2026-07-17)

**Between-day macro loop — issues #18/#19 sub-issues (#20-#25) ALL IMPLEMENTED & pilot-verified (2026-07-17).**
- **#24 Lives removed** — `GameState.lives`, `STARTING_LIVES`, `FALSE_ADMIT_LIVES_PENALTY`, `ScoreDelta.lives`, `CandidateResult.lives_delta`, persistence field, and all UI hearts are gone (grep-clean; only historical comments remain).
- **#20 Site Health** — `GameState.site_health` (0-100, persists), `config.ARCHETYPE_HEALTH_WEIGHTS` (admits apply the archetype's weight; correct denials never touch health), `SITE_HEALTH_LOSS_THRESHOLD` (25, game over) / `SITE_HEALTH_REWARD_THRESHOLD` (75, EOD bonus). `scoring.health_below_loss()` drives game-over in `_commit_verdict` + `_evaluate_performance`.
- **#21 HackDollar$** — `GameState.hackdollars` persists; earned on correct verdicts (`HACKDOLLAR_PER_CORRECT_ADMIT`=10 / `_DENY`=4) + `scoring.eod_health_bonus()` (max 25, health-scaled) at `finish_day`. ⏱ resets to `GameState.compute_capacity` in `advance_day` — never carries over. EOD screen shows earned + balance.
- **#25 HackDox Credits** — `GameState.hackdox_credits` (start 1 per issue AC — the "3" in the title is the slot cap `HACKDOX_CREDIT_MAX`). `reveal`/`credit`/`truth` in the command bar on ANY page → `CreditRevealScreen` (violet modal): correct verdict + planted kinds/severities only, NO evidence trail. Decrements once per candidate (reopen free); refused at 0.
- **#23 Upgrade catalog** — `config.UPGRADE_CATALOG` (13 items, HD$-priced): log/hash suspicious-line highlights (free-tier `upgrade_highlight` param in `_lw_render`/`_render_hc_log`), approved/prohibited email+affiliation dossier highlights (`tools_bridge.classify_email_domain/affiliation` + `_hl_email`/`_hl_affil` in app.py), stego tint boost (`StegoImagePanel.tint_boost`), hostile-chat ⚠ marker, per-tool ⏱ cost reduction (`tools_bridge.tool_cost()`, stego variant reduces the filter cost). All strict no-ops until owned.
- **#22 Between-day menu** — `BetweenDayScreen` (Shift Report 55% | HackDollar$ Shop 45%, Overseer panel with `day{N}_between` narrative key + fallback): ↑↓/Enter shop with owned/full/unaffordable gating, purchases persist immediately; N → `advance_day` (⏱ reset, save, next `BriefingScreen`, or `CampaignEndScreen` if the day file doesn't exist). Flow: intake → EOD → between-day → next intro.
- **Status header** reworked: `⛨health%`, `HD$`, credit pips `▮▯` replace hearts.
- Verified: **13/13 foundation tests** (new: health damage/deny-immunity, loss threshold, EOD bonus scaling, persistence round-trip asserting no `lives` key, toolcost reduction) · legacy pytest twin rewritten · 6-candidate × all-tools × all-upgrades render sweep exception-free · **Textual pilot E2E**: reveal on tool page + decrement + free reopen + 0-credit refusal, full day loop → EOD → menu, shop purchases (credit/capacity/upgrade, owned+broke refusals), ⏱ reset on day advance, game-over on health threshold.
- ⚠ Truncation bit HARD this session: `config.py`, `scoring.py`, `persistence.py`, `models.py`, `hackdox.py`, and `tools_bridge.py` all truncated mid-edit. `tools_bridge`'s lost tail (`stamp_signature_lines`/`get_stego_stats`) was past git HEAD — **recovered by disassembling `__pycache__/tools_bridge.cpython-310.pyc`** (docstrings + constants + `dis`). Remember that trick. app.py was patched exclusively via bash multi-replace scripts and survived untouched.

## Where I Was (2026-07-14)

**Stegotool stamp minigame — IMPLEMENTED & pilot-verified (2026-07-14).** The stego page is reworked around an interactive stamp mechanic (design roots in the Notion "🖼️ Stegotool Page Redesign" brainstorm; stamp mechanic supersedes the old scan/filter tiers there):
- **Layout:** page 5 is now 3-column — sidebar (26%) | findings terminal (34%) | `StegoImagePanel` image viewer (40%, the dominant right column / game canvas). `#evidence-st` shrunk to 26% to match the sidebar it replaces.
- **Stamp mechanic:** `X` (empty command buffer, page 5 only) or `s`/`extract`/`stamp` command enters **stamp mode** — arrows move an 8×4 stamp (`STEGO_STAMP_W/H`), `Space` stamps at `STEGO_STAMP_COST` (1 ⏱) via `tools_bridge.charge_stamp`, `Esc`/`X` exits; page nav (1–5) auto-exits. Stamp-mode keys are intercepted at the top of `IntakeScreen.on_key`, so the evidence board/command bar are untouched. Buffer guard prevents `x` inside typed commands (e.g. "extract") from triggering.
- **Engine (`tools_bridge`):** `StegoImageData` (frozen dataclass: base_rgb grid, hot zone rect, per-cell `carrier` set, kind, density) built by `build_stego_image()` — deterministic per candidate (reuses seeds `0xB10CA0DE`/`0x57E60001`; carrier seed `0x57A3B007`). Grid scales with payload: clean 30×12 · plaintext 36×16 (density .80–.95) · encrypted 40×18 (.55–.72) · C2 44×20 (.25–.45, wider zone). `evaluate_stamp()` returns `StampResult` (anomalous cells, density %, signature, cumulative zone coverage); `stamp_log_lines()` renders the per-stamp terminal block; `stamp_signature_lines()` prints the explicit `▲ KIND — SIGNATURE RESOLVED` block once coverage ≥ `STEGO_STAMP_RESOLVE_COVERAGE` (0.60). `get_stego_stats()` is the grid-free free-tier stats block for the terminal (grid now lives in the viewer).
- **Visual language:** color = payload type (AMBER `#ff8c42` plaintext / CRIMSON `#ff5470` encrypted / VIOLET `#c084fc` C2), density = carrier fill within the zone, size = zone extent (reported as compact/moderate/sprawling on resolve). *(2026-09-19: + shape = payload operation — conventional blocks / cross / hollow loop / parallel slashes; see the Evidence Catalog's 2026-09-19 revision.)* Revealed clean cells get a green wash; in-zone non-carrier cells "disturbed noise" tint; the free-tier subtle blue tint over hot zones is preserved so a sharp eye can aim stamps before spending ⏱. Legacy `run_stegotool`/`run_stegotool_filtered` remain for compat but are unreachable from the UI (removed from runners + `_FILTER_PAGE_MAP`; `filter` on page 5 responds with a stamp-mode hint).
- **Economy parity:** a compact zone resolves in ~4 stamps ≈ 4 ⏱ — same total as the old scan (2) + filter (2).
- Verified: 8/8 foundation tests · 48-candidate markup sweep exception-free · Textual pilot covers stamp charge/log, Esc exit, `s` command entry, page-nav exit, board toggle, x-in-buffer guard, post-verdict block, next-candidate reset, and single-fire signature resolution on a dirty candidate.


**Evidence Board — toggleable left-side panel (current approach).** An earlier global-overlay (`EvidenceScreen` modal) attempt was reverted. The shipped design keeps the inline board baked into the Candidate page **unchanged**, and adds a toggleable board to the four tool pages:
- `EvidenceState` — shared flag store (`set[DiscrepancyKind]`); `get_flags()` keeps the scoring contract **unchanged**.
- `EvidenceBoard` is now a *view* over `EvidenceState`. Five instances share one state: the Candidate-page board plus one per tool page. Flagging anywhere syncs everywhere.
- On tool pages (2–5), **Tab** (`config.KEY_BINDINGS["toggle_evidence"]`, or `evidence`/`board` command) slides the board in on the **left**, replacing the condensed-dossier sidebar so the tool data on the right stays visible. Hidden by default; open/closed persists across tool-page nav. No-op on the Candidate page.
- `.tool-evidence` boards match the sidebar widths they replace (28% Ghostscan, 32% others). Verified via Textual pilot: toggle, shared state, cross-page persistence, candidate-page no-op; 8/8 foundation tests pass.
- ⚠️ Windows-mount truncation bit three saved files (`app.py`, `config.py`, `app.tcss`) — all repaired by splicing the lost tails from `git HEAD`. Watch for this.

**Evidence Catalog v2 — FULLY IMPLEMENTED & verified (engine + tool rendering).** Ten new evidence pieces (speced in *Game Design → Evidence Catalog — v2 additions*). Status:
- ✅ `models.DiscrepancyKind` — 10 new kinds added.
- ✅ `candidate_gen` — `_SEVERITY_REVEAL` + `_DISCREPANCY_DESCRIPTIONS` + archetype `eligible_kinds` (Day-to-Day, Clumsy, Bad Actor, Sneaky Bugger, White Hat) + artifact gen (hashes for cross-breach/unsalted, image for encrypted). Verified: all 10 surface on the Day-1 mix; Sneaky Bugger correctly omits the minor breadcrumbs (budget has no minor slot — breadcrumbs stay optional per design).
- ✅ `app.EVIDENCE_ITEMS` — board now 25 items (10 new + the 2 previously-missing `AFFILIATION_MISMATCH`/`DISPOSABLE_EMAIL`).
- ✅ `content/days/day_01.json` — added disqualifying rules for credential_stuffing/low_and_slow/encrypted_payload/threat_forum + weighted claimed_ip; all fire via `rules_engine`. 8/8 foundation tests pass; a v2 kind flagged on the board earns full 10⏱ board bonus.
- ✅ **`tools_bridge` terminal rendering DONE** (free/base/filter tiers) for all 10 kinds. Logwatch: split `stuffing` out of the old brute branch into `CREDENTIAL_STUFFING`; added `after_hours` (benign, normal paths) and `low_and_slow` (sub-threshold, is_suspicious=False, surfaced only by a filter-tier cross-day correlation summary); `claimed_ip` mismatch drives the candidate's login IP external (existing orange-highlight path). Ghostscan: `THREAT_FORUM_MATCH` reuses the critical-forum placement (`has_sock or has_forum`); `BURNER_IDENTITY` adds an "account registry" block (clustered creation dates); `TYPOSQUAT_HANDLE` free-tier cue + filter summary. Hashcrack: `CROSS_BREACH_REUSE` (crack + 2nd breach-corpus match, aligned via `_breach_db_for_candidate`) and `UNSALTED_STORAGE` (instant crack) wired through `_hc_candidate_entries` + `_render_hc_log` + filter summary. Stego: `ENCRYPTED_PAYLOAD` added to `suspicious` across all 4 stego fns + a filter decode branch (XOR/encrypted vs plaintext).
- Verified: 8/8 foundation tests; all 6 OSINT/Credential/Stego filter labels render; 720 candidate×all-tools base+filter runs raise zero exceptions; Textual pilot mounts the app, runs every tool page base+filter, toggles the 25-item board, and commits a scored verdict.
- ✅ **Candidate-page board is now a read-only "Flagged Evidence" summary** — lists only the violations the player has flagged (grouped, with count) or "No violations flagged". Editing happens on the tool-page boards (full 25-item checklist). This also removes the candidate-page overflow worry. Tool-page boards (`.tool-evidence`) are vertically centered (`content-align: left middle`). Shared `EvidenceState` keeps the summary live as flags change.
- ⚠️ **Board capacity (tool pages only):** the editable 25-item list may still clip on short terminals — make the tool-page boards scrollable if it bites.
- ⚠️ **Windows-mount truncation** hit `tools_bridge.py` repeatedly mid-edit; the safe path was a single bash-scripted multi-replace write + git-splice repairs. One splice grabbed a wrong anchor and dropped `run_hashcrack_filtered`/`run_stegotool_filtered` — restored from git. If the filtered-variant tail ever looks wrong, compare against `git HEAD`.

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

> **Documentation note (updated 2026-09-21):** the gap flagged by the original 2026-09-14 note —
> Batches 2 through 5, the Evidence Board chip-grid rework, the Hashcrack cipher-block rework,
> `core/overseer.py`, and `core/content_loader.py` — has been backfilled below from git history and
> project memory (see the entries from 2026-08-17 through 2026-09-15). This Session Log should now
> read as continuously accurate through 2026-09-20. Still worth cross-checking `rules_content.py`'s
> `VIOLATION_CATALOG`/`_SEVERITY_REVEAL` directly for anything that's landed since, and note that as
> of this update everything below from 2026-09-12 onward lives on the unmerged `Stego-Shapes` branch,
> not `main` (see Where I'm At).

### 2026-09-25 (Endless Mode #7 + balance pass #70/#14)
Plan + shipped log with every number: `BUILD_PLAN_EndlessMode_2026-09.md`.
- **Endless Mode is live** from the main menu. Its own save slot (`saves/endless_0.json`) — the menu labels "Continue Campaign · Day N" and "Continue Endless · Shift N" separately and says the two never touch; the Endless personal best (`saves/endless_records.json`) shows on the menu and the run-over screen.
- **How it works:** Endless shift N is day number `1000+N` (`config.ENDLESS_DAY_BASE`). Every unlock gate is `unlock_day <= day`, so the whole kit is live from shift 1 with no gate code changed; the difficulty curves go through `config.curve_day()` (identity on campaign days — a golden snapshot of days 1–20 stayed byte-identical). Shift 1 plays like campaign day 7, shift 15 like day 20, then climbs to day 26 by shift 30 and plateaus. Days come from `content_loader.build_endless_day` — never the authored campaign files; no Dark Web, no White Hat.
- **Losing:** Site Health collapse, or the 5-shift rolling accuracy under 70% (counted from shift 5). `core/endless.py` owns the run rules; `EndlessOverScreen` shows why, the run's numbers and the personal best.
- **Economy (Endless):** 5 random upgrades under maintenance per run (MAINT in the shop), escalating capacity price, a Site Patch item, 5 credit slots. Shop rules moved to `core/shop.py` (both modes).
- **The Foreman in Endless** is on the player's side: 34 `endless_*` lines keyed by the accuracy trend (rising/steady/falling, near-the-line, lost), cooperative rule-change phrasings (small changes casual, new hard denies with a reason). VOICE_GUIDE §3 updated.
- **Balance pass (#70, both modes)** via the new `sim_balance.py`: ⏱ was already fine; the Dark Web alignment path was unfinishable (admitting DW is scored correct and cost −8 health each → a perfect by-the-book player lost 75% of campaigns); an 85% player lost every run; a perfect player earned 4.6× the catalog by day 20. Retuned health weights, cut income (board bonus 10→4, payouts 10/4→8/3, health bonus 25→15) and raised upgrade prices ×3.5, so by day 20 a perfect player can afford ~79% of the catalog and a solid one ~50% — players have to choose.
- Tests: 645 → 678 (`test_endless.py` 29, `test_balance.py` 4); every new guard was reverted in a scratch copy and seen red.

### 2026-09-25 (World lore — the Undertow and the data docks)
Nick set the world: after an AI disaster (named *the Undertow* in copy), networks and hackers can't be trusted, so data moves physically by ship, and the player vets the couriers who carry it.
- **World bible:** new `VOICE_GUIDE.md` §0 — the Undertow, data by ship, courier bonds, the air-gapped gate terminal (why the tools work offline), what Site Health / Dark Web / White Hat / HD$ mean in-world, where the world gets explained (day 1 setup, one beat per day on days 2–6), and the questions left open for Nick (what the Undertow is, whether it's still active, who released it, any link to the smugglers).
- **The Foreman:** `day1_intro_friendly` now opens with the world setup (8 lines, tutorial content kept); `day1_between` (HD$ = gate scrip); days 2–5 intros each add one piece beside their tool (air gap, the courier's credential, shipped logbooks, the false bottom); day 6 has her name the smugglers — dismissively, since she's on their payroll.
- **Premise clashes fixed:** candidate purposes are now courier runs (same 5+5 lengths, same roles, legit and suspect share one phrasing shape); six chat lines that assumed "access to a service" became courier lines (pool lengths unchanged); menu subtitle; the Dark Web ending's "first internet security service" sentence; `gameengine/__init__.py` docstring; this file's premise.

### 2026-09-24 (Dockside voice pass — Overseer → the Foreman, harbour word banks, stego harbour scenes)
Nick's thematic pivot: HackDox = hack + docks, cybersecurity with a longshoreman voice, PG. Decisions: rename the Overseer to **the Foreman** (player-facing only); real elite orgs → made-up harbour orgs; email domains a mix of real and in-world; about one dock phrase every two or three lines.
- **Voice source + owner:** `VOICE_GUIDE.md` (repo root) and a new subagent `.claude/agents/dockside-voice.md` (wording only; hands word-bank renames to `rules-evidence`).
- **Foreman:** every player-visible "Overseer" → "Foreman" (speaker labels, panel title, locked-page messages, Rules pages, `simulate` panel); all 186 lines of `overseer.json`, `_UNLOCK_LINES` (no longer placeholder), `_RULE_CHANGE_PHRASINGS`, and the three endings rewritten in the voice (endings now call her "she", not "it"). Keys, meaning and alignment bands unchanged. Flavor rate 6% → 35% of lines (by the test glossary).
- **Candidates:** every `_CHAT_*` pool and `reactions.py` lightly flavored, evenly (0.25–0.40 density per pool, guarded — #78). Pool lengths unchanged.
- **Word banks:** elite orgs → Port Authority CERT, Tidewater Signals Lab, Northreach Maritime Research Institute, Bayside Naval Cyber Institute, Meridian Shipping Security Operations, Lighthouse Foundation for Secure Systems, Harbormaster's Office Network Defense (with handles + institutional domains); ordinary orgs, thin orgs, domains (portmail.net, fogbank.me, flotsam.io…), purposes and stego filenames given harbour versions. `tools_bridge`'s trusted-org check was a hand-kept keyword list ("mit", "stanford"…) — now DERIVED from `AFFILIATIONS_ELITE`. Rules page gained an ELITE row (players can't recognise made-up orgs from the real world). Every list the generator draws from kept its length → **5,430 generated candidates byte-identical to before** apart from text.
- **Day files:** 6 titles, 7 summaries and all six DW justifications (62 copies across days 8–20, plus the spec copies in `test_engine_foundation.py`) rewritten; rule ids/predicates/severities/text untouched (verified against HEAD).
- **Stego art:** new `core/stego_scenes.py` — six harbour scenes (containers, crane at dusk, harbour at night, hull, lighthouse, fog over a pier) replace the gradient/thermal/photo/blueprint/terminal washes. Own RNG, drawn after every existing draw; `StegoImageData.motif` names the scene. Zone/carrier/hint/shape identical across 2,160 images; pinned by a fingerprint test.
- **Cyber scenes (2026-09-25, Nick's follow-up ask):** six more scenes appended for the "hack" half — server room, ops-room wall screen, data-centre aisle, globe at night, hooded figure at a laptop, CCTV camera (a satellite dish was tried and cut: it reads as a tree at 30×12). Dock and cyber scenes are picked about 50/50. Payload fingerprint unchanged.
- **New tests:** `test_voice.py` (11) + `test_stego_scenes.py` (12); every guard broken on purpose in a scratch copy and seen red first — which caught an inert first version of the "Overseer" check (string literals keyed by line, so `classes="speaker"` overwrote the label beside it).
- Suite: 622 → 645 pass.

### 2026-09-20 (Logwatch: origin map, travel noise, paid Analyst Notes)
- **ANALYST NOTES are paid:** new upgrade `UPGRADE_LOG_TRIAGE` "Threat Triage HUD" (30 HD$, Logwatch shop category). Without it the section shows a locked line; the rest of the report is unchanged.
- **Origin map:** `core/ascii_map.py` — a resolution-independent world map rasterised from coarse lat/lon continent boxes (no copied art), drawn at whatever width the report column has (`LW_MAP_MIN_WIDTH`..`LW_MAP_MAX_WIDTH`; below the minimum the plain origins list is used). Numbered markers match the legend (green = claimed IP, red = an origin that failed its way in, amber = elsewhere); dotted arcs = city changes between clean logins, all ONE colour.
- **Honest travel noise:** ~15% of candidates without IMPOSSIBLE_TRAVEL now fly somewhere and log in on arrival (`LW_LEGIT_TRIP_*`); the trip is scheduled so its speed stays far below `LW_MAX_FEASIBLE_KMH`. Travel pairs are no longer suspicious by existing — `TravelPair.feasible`/`kmh`, `LogwatchReport.impossible`. Planted impossible travel now picks cities ≥ `LW_TRAVEL_MIN_KM` apart. The report lists every pair with distance + time and never classifies it; the paid notes flag "faster than any flight"; the filter names it with km/h. `CITY_COORDS` moved to `logwatch_report`.
- Header CLAIMS/VIA IP split onto two lines (narrow terminals). Rules tab 4 + `_CATCH` + config cheat-sheet updated. New tests in `test_logwatch_report.py` (travel feasibility both ways, locked/unlocked notes, map scaling + marker count).

### 2026-09-19 (Logwatch report overhaul)
Nick's redesign of the Logwatch page. Plan + status: project doc `claude/logwatch_report_plan.md`.
- **Page is now 3-column:** sidebar | **Activity Report** (free, centre) | **auth log panel** (`widgets/log_list.py`, sealed until L). Base run unseals the log with NO labels; the filter adds ▲ labels to the log and a ▲ CONFIRMED block to the report. `[`/`]` jump between the target's rows, PgUp/PgDn page it; rows never wrap.
- **The report is computed from the log** (`core/logwatch_report.py` → `build_logwatch_report`), never from ground truth — pinned by `test_report_ignores_engine_only_row_fields`. The reveal-tier table (what the report can/can't tell) is in that module's docstring and pinned by `tests/test_logwatch_report.py`.
- **BREACH_MATCH rows removed from Logwatch** — breach hits are Ghostscan's and Hashcrack's only. HASH_SUBMIT stays as neutral context.
- **Log Analyzer HUD reworked** — neutral ▸ gutter marks + "◂ out of range" report bars; it never names an attack (the old HUD printed attack names).
- **Generator changes (day logs re-rolled):** daytime activity fits the 08:00–18:00 shift (`LW_WORKDAY_WINDOW` now 08:05–11:30 + chain compression); a benign single typo AUTH_FAIL for ~30% of candidates; brute/stuffing attack IPs now random cities (fixed Frankfurt / unmapped 45.131 were tells). New dossier fields `claimed_role`, `claimed_location`.
- Day 4 briefing summary + Overseer `day4_intro` reworded for the report-first flow; Rules tab 4 and the Logwatch reference panel rewritten.
- **Tunables — all in `config.py`, "Logwatch Activity Report" block:** `LW_SHIFT_START/END/END_MARGIN` (shift), `LW_BURST_WINDOW` + `LW_BURST_ALERT` (attack alert), `LW_TRAVEL_REPORT_WINDOW`, `LW_HOSTILE_ORIGIN_FAILS`, `LW_BENIGN_TYPO_CHANCE/LEAD`, `LW_PROFILE_METRICS` (bar label, normal ceiling, scale), `LW_REPORT_WIDTH`, `LW_BAR_WIDTH(_COMPACT)`, `LW_TIMELINE_BIN_MIN(_COMPACT)`; keys `KEY_BINDINGS["log_prev_row"/"log_next_row"]`. The tier tests will tell you if a retune breaks the reveal table (e.g. an alert threshold above `LW_BRUTE_BURST_SIZE`'s minimum).
- **Duplicate identities fixed:** ~0.5% of days used to hold two candidates with the same email/name (one account in the log for two people). `candidate_gen._resolve_identity` now rerolls a slot whose name or email an earlier slot took (salted `identity_retry_N` stream); ~1% of slots moved, every other identity is byte-identical. Pinned by `test_candidate_identities_are_unique_within_a_day`.
- Auth log panel: the `[`/`]` jumped-to row now wears a `›` cursor and a highlight band (`LogListPanel._with_cursor`).
- Tests: 587/587 (new `test_logwatch_report.py`, `test_logwatch_page.py`).

### 2026-09-15 (Hashcrack Cipher Block v2 — credential retier + evidence-board polish)
- Settled the violation redistribution that came with the cipher block (see 2026-09-14 below): `CROSS_BREACH_REUSE` → Hashcrack **critical** (was major, which had made it unreachable inside Clumsy Cutie's discrepancy budget — moved to Sneaky Bugger + Bad Actor instead); `LEAKED_PASSWORD` → Hashcrack **major** (was critical); `UNSALTED_STORAGE` kept its Dossier **tier** but moved to the **CREDENTIAL** board group; `WEAK_ENCRYPTION` → Hashcrack **minor**, CREDENTIAL group.
- Found day 3 slot 2 was silently losing its forced `cross_breach_reuse` in 40/40 seeds because `forced_violations` validates tier/expressibility/whitelist but never budget capacity; fixed by reassigning that slot's archetype. New guard: `test_every_eligible_kind_fits_its_archetypes_budget`.
- `BUILD_PLAN_Credentials_2026-09.md` written as the shipped log.
- Left open: `day_01.json` still declares `rule_cross_breach_reuse` twice; `Dossier.password_plain`'s docstring is stale.

### 2026-09-14 (Hashcrack rebuilt as the Cipher Block; Rules/Evidence subagent built; GitHub merge audit)
- **Hashcrack v1 built, then rejected the same day.** v1 was "an aperture sweep" — moveable reveal windows, per-batch ⏱, a coverage threshold. Nick's verdict: *"a spatial hunt wearing a cryptography costume"* — too close to the Stego stamp mechanic. Deleted outright (model, config, tests), not adapted.
- **Hashcrack v2 built the same day — the Cipher Block.** A genuine two-stage decrypt: stage 0 (free) shows the block's dimensions, glyph alphabet, and digest shape; stage 1 (costs ⏱) is picking one of 3 decryption windows (MD5/SHA-256/bcrypt) — a wrong guess burns ⏱, bcrypt engages then deliberately stalls; stage 2 (free) is a 2-axis alignment dial, each cell with its own tolerance, resolving to plaintext tiled across rows as you narrow in. `UNSALTED_STORAGE` skips both stages. Caught and fixed a near-ship bug: per-cell tolerance must roll `randint(0, tol)`, not `randint(1, tol)`, or being exactly right and being one step off were indistinguishable. See "gameengine — Hashcrack Cipher Block v2" above for the full writeup.
- **Built the Rules/Evidence-propagation subagent** (`.claude/agents/rules-evidence.md`) — a dedicated Claude Code subagent whose sole job is keeping any `DiscrepancyKind`'s full 5-stage touchpoint chain (generator → tool rendering → rules-page catalog → rules-engine predicate → day-file rules) in sync, since that chain had drifted repeatedly across this project's history (cites the Batch 4, evidence-chip-grid, and cipher-block incidents as prior art). A second subagent, `.claude/agents/progression-unlock.md`, also exists in the repo from earlier work not otherwise narrated in this log.
- **GitHub merge audit:** discovered `batch-2-difficulty-curve-replayablity` and `batch-3-UserFeedback-ContentGeneration` were already fully merged to `main` (0 commits ahead), contrary to the standing belief they were unpushed — Batch 3 merged via PR #64 (2026-09-03); Batch 4's #56-#60 commits had landed directly on `main` back on 2026-08-17. Closed out issues #50/#51/#53/#54/#56/#57/#58/#59/#60 on the project board with verification comments (`BUILD_PLAN_Issues50-60_Status_2026-09.md`). Filed **issue #73**: the tier guard that checks every planted violation is observable excludes DOSSIER-tier kinds — a standing blind spot.
- **Health-check sweep** (general audit, not tied to a specific change, using the new subagent's own checklist): found and fixed a duplicate `UNSALTED_STORAGE` entry in `rules_content._CATCH` that was silently shadowing the richer, correct hint text; corrected this file's stale `WEAK_ENCRYPTION` tier claim; swept 2,800 candidates (every day × 200 seeds) for a dormant `DISPOSABLE_EMAIL`/`is_incompatible` ordering risk — 0 live occurrences, left as a flagged judgment call rather than fixed outright.
- Environment note: `device_bash` had been down on Nick's machine since ~2026-09-08 (a Windows update broke the Plan9/virtiofs mount); this and the next few sessions worked via stage/edit/`device_commit_files` instead of live editing.

### 2026-09-12 – 2026-09-13 (Batch 5 — Dark Web directives, Days 6-20, Overseer alignment bands, 3 endings)
The remainder of the campaign (#37, #39-#42), built in five phases plus per-phase review-fix commits, all on the branch that became `Stego-Shapes`:
- **Phase 1 (#37):** Dark Web directive mechanism added to the rules engine — a new `"dark_web"` `RuleMutability`. A directive **adds** a new rule (its own id) while the criterion it supersedes is **removed**, rather than replacing a rule by id or restating the day's full rule array — chosen specifically so `diff_rulesets`' add/remove narration keeps working unmodified.
- **Phase 2 (#39):** Days 6-7 authored — a deliberate Dark Web mix with escalating chat.
- **Phase 3 (#40):** Days 8-11 authored — "the corruption arc," DW-01 through DW-04 wired in.
- **Phase 4 (#41):** Day 12 authored — the scripted, unique White Hat encounter. `WHITE_HAT.moral_modifier` raised to **±4** (was +1) so admitting or denying them actually swings alignment meaningfully.
- **Phase 5a (#42):** `core/overseer.py` built — `GameState.alignment` (a running ±10 counter, moved by each verdict's `moral_modifier`, sign-flipped on a deny) resolves to one of three bands via `ending_for_state`: White Hat-aligned, Dark Web-aligned, or Neutral. Thresholds set to **±4**, matching the White Hat's own single-encounter magnitude. `screens/campaign_end.py` rebuilt from a 34-line "TO BE CONTINUED" stub into the three authored epilogues.
- **Phase 5b (#42):** Days 13, 17, and 20 authored bespoke (the "hard band"), including **DW-05**, a payload-leniency directive; days 14-16 and 18-19 ride the new alignment-banded content selector instead of being hand-authored. The full 20-day campaign is authored end to end for the first time.
- Each phase got its own review-fix commit: a day-9 quota bug and `forced_chat` gaps (days 8-11), guaranteed day-12 decoy coverage (previously left probabilistic), a DW-05 intro wording fix and positional chained-supersession validation (days 13/17/20), and a fix to `hackdox.py`'s `simulate` command that both patched a real `KeyError` and made its regression guard actually exercise the bug it was meant to catch.
- `BUILD_PLAN_Batch5_MainGame_Content.md` and `BUILD_PLAN_Issues50-60_Status_2026-09.md` committed as docs.

### 2026-09-11 (Sound branch merged to main)
- PR #66 ("Sound") merged into `main` — this is what actually landed the transitions/damage-glitch, audio, and verdict-reveal-window work (built 2026-09-06 through 09-07, see below) in the mainline history. `main` has not moved since; everything from the Dark Web directive mechanism onward (2026-09-12+) is on later branches, currently `Stego-Shapes`, unmerged.

### 2026-09-08 (Evidence Board — clickable chip-grid rework)
- Branch `Evidence-Board-interaction`, 5 commits, merged via PR #65: the flat 27-row checklist became a grid of clickable buttons, one named category per row (`VIOLATION_CLUSTERS` in `rules_content.py`), grouped into the same 5 tool clusters (DOSSIER/OSINT/CREDENTIAL/FORENSICS/STEGO), always laid out horizontally (a too-wide category wraps its label downward inside the button rather than stacking vertically — an earlier attempt at the latter broke grouping badly enough in playtesting that it was reverted). Categories shipped unnamed first; playtesting showed players couldn't learn the grouping and fell back to arrow-key walking, so names were restored and a blank category name is now an import-time error. Stegotool is the one page that hides its terminal (not just its sidebar) while the board is open, since the image viewer itself is the evidence there. Suite went 256 → 298 tests.
- Around this date, a Windows update broke `device_bash`'s mount of the project folder ("no Plan9 drive shares mounted") — the outage persisted roughly through 2026-09-15, forcing several sessions in that window into a stage/edit/`device_commit_files` workflow instead of live editing.

### 2026-09-07 (Verdict Reveal Window; Audio system)
- **Verdict Reveal Window:** a ~3s post-verdict feedback beat — a chat reaction line, a border pulse (right/wrong), and evidence-board grading of the player's own flags (touched items get ✓/✗, untouched ones stay blank with an unrecorded-count footer, never the full answer key). Fully skippable — only the border pulse is time-boxed. 20 tests, suite 256 green.
- **Audio system:** `core/audio.py`'s `SoundManager` wraps `pygame.mixer`, fail-soft throughout (silently no-ops if pygame is missing, the mixer fails to init, or sound is disabled — nothing in game logic depends on audio actually working). 24 sound ids (`SFX_REGISTRY`), all placeholder synthesized tones from `content/audio/generate_placeholders.py`, wired at roughly 15 trigger points across verdicts, tool runs, page/focus navigation, and the evidence board. 3 independent volume knobs persisted to `saves/audio_settings.json`, kept separate from campaign saves — no in-game settings screen calls the save yet. 7 tests. pygame was added to `requirements.txt` but, as of this build, not yet installed in Nick's actual Windows environment — verified end-to-end only in the Linux device-bridge sandbox.

### 2026-09-06 (Feedback Reactions)
- Per-archetype chat reaction lines shipped ahead of the full Verdict Reveal Window that would wrap them the next day.

### 2026-09-04 (Jenkins Lint stage — cleaned to zero)
- First real Lint run on the Windows Jenkins agent found 277 ruff findings; triaged and fixed in batches, verified against the full suite after each. ~230 were mechanical `ruff --fix` cleanups; one auto-fix had to be reverted by hand (`--fix` deleted `app.py`'s intentional re-export facade — F401 doesn't understand re-exports — restored with an explicit `__all__`); two real dead-code bugs surfaced (`run_hashcrack()`/`run_hashcrack_filtered()` called helpers removed in an earlier refactor and would have raised `NameError` if ever invoked); 15 `RUF012` findings (mutable Textual `BINDINGS` class defaults) annotated `ClassVar`; one confirmed-dead `F841` (`rules_block` in `intake.py`, superseded by the RulesScreen overlay) removed after Nick confirmed it was safe. Final state: 0 real findings — only the pre-existing, confirmed-harmless `EXE002` (a Linux-checkout-only artifact) remains.

### 2026-09-01 (Jenkins CI/CD built)
- Built for a PlayStation SDET II interview (careers.playstation.com/sdet-ii) — a portfolio/interview-prep artifact, not a game feature. `Jenkinsfile` at the repo root: Checkout → Set Up Python → Install Dependencies → Lint (ruff, non-blocking) → Foundation Tests (the legacy stdlib runner) → Pytest Suite (with JUnit + coverage output). Cross-platform (`isUnix()`-gated venv paths, `python -m pip` instead of the locked `pip.exe` wrapper). Live-debugged through 4 real cross-platform bugs on Nick's own native Windows Jenkins server (missing Java, missing `sh`, missing `python3` alias, venv bin/Scripts layout). Build #5 was the first fully green build.

### 2026-08-18 (Batch 4 shipped — Days 1-5 authored)
- Days 1-5 fully authored for the first time, via a new `forced_violations` + `rule_sheet` day-file schema; before this, every day past Day 1 opened blank and closed on a literal "..." — Overseer copy for days 2-5 plus a generic `generic_*` fallback for days 6-20 fixed that. Sneaky Bugger removed from Day 1's mix (it had been generating zero-discrepancy DENYs). `config.BREACH_DB_UNLOCK_DAY` added — breach databases are now static, sorted, and unlock progressively rather than being randomly assorted from day one; a shared `breach_dbs_for_candidate()` keeps Ghostscan and Hashcrack reading the identical list. Two measured tool-consistency bugs fixed: the Hashcrack credential-stuffing burst had been asserted rather than derived from the actual `CREDENTIAL_STUFFING` flag (91/91 false claims → 0); Ghostscan's platform sweep could omit the GitHub row even when an email/GitHub mismatch was planted (50/76 → 0). Word banks single-sourced (found two more live drifts in the process). Suite went 162 → 185 (legacy runner 16/16). `CONTENT_AUTHORING.md` written as the authoring-surface map. `BUILD_PLAN_Batch4_UserFeedback_ContentGeneration.md` is the full shipped log.

### 2026-08-17 (Batch 3 shipped — playtest fixes & randomness)
- `MISSING_PUBLIC_PROFILE` retiered DOSSIER → GHOSTSCAN (#51) — it had no dossier-side evidence at all, so roughly half of Day 1's candidates carrying it were unflaggable by design. Typosquatted handles made real (#53) — `_make_handle` had never actually consulted the affiliation list; a genuine Levenshtein-1-or-2 lookalike is now built and recorded on `Dossier.handle_squats`, demoted major→minor. Stego carrier cells now clump into segmented rectangles with a dilated `hint_region` for the base-tier tint (#54). Rules pages split `build_dossier_text` out of `build_rules_text`, with per-tab scroll memory (#50). Four affiliation-adjacent kinds standardized into distinct reads: `AFFILIATION_NOT_STATED` / `AFFILIATION_MISMATCH` / `AFFILIATION_UNLISTED` / `MISSING_PUBLIC_PROFILE` (#56). The disposable-domain detector had drifted from the generator's domain list; now derives from it directly (#57). A privacy-provider dossier hint that instructed players to flag something with no matching `DiscrepancyKind` (scoring against them for following the game's own hint) was reworded to non-actionable context (#58). `WEAK_ENCRYPTION` (the algorithm) and `WEAK_CREDENTIAL` (the plaintext) made orthogonal instead of coupled (#59). Every `DiscrepancyKind` given at least one rule so the ruleset can actually express ground truth — Day 1 went from 14 to 27 rules, closing the gap where The Incompatible archetype was 100% unenforceable "by the book" (#60). Also shipped: the **`hackdox lab` debugging CLI** (#52) — generates candidates under explicit constraints (e.g. `hackdox lab -a sneaky_bugger -v typosquat_handle --day 5`), reports its seed for reproducibility, and can pair ground truth against a tool's real filtered output side by side.

### 2026-08-16 (playtest fixes)
Ad-hoc fixes from Nick's manual playtesting, applied directly (not a numbered backlog batch — see `planning_sprint.md`/`playtest_fixes.md` in project memory for the Batch 1 epic that shipped separately the same day). All 32 `gameengine/tests` pass throughout; changes also verified with 2000+-candidate generation sweeps across days 1-5.
- **Tab-toggle bug fixed:** pressing Tab on the Candidate/Dossier page used to force-navigate to Ghostscan and only ever open the Evidence Board, never close it (`on_key`'s Tab handler special-cased page 0 instead of calling `_toggle_evidence()`, even though `board_c0` already supported toggling in place there). Now unified across all 5 pages.
- **`CLAIMED_IP_MISMATCH` moved Dossier → Logwatch** in `_SEVERITY_REVEAL` — the dossier's `claimed_ip` field never actually varied by violation; the mismatch was only ever expressed in the Logwatch log data. Now gated to Logwatch's unlock day (4) instead of day 1.
- **New `WEAK_ENCRYPTION` kind** (Dossier, minor, free) — flags the password's encryption *algorithm* (MD5 strength chip) independent of the plaintext's quality; fills the slot `CLAIMED_IP_MISMATCH` vacated. Distinct from `WEAK_CREDENTIAL` (needs a Hashcrack crack to confirm the plaintext itself is bad). **Correction, 2026-09-14 (health-check sweep):** no longer accurate — the Hashcrack cipher-block rework retiered `WEAK_ENCRYPTION` to `(ToolName.HASHCRACK, "minor")` in `_SEVERITY_REVEAL` (reading the cipher block's digest shape, or buying the Cipher ID HUD upgrade, is what reveals it now; the dossier no longer prints a free strength chip). See `rules_content.VIOLATION_CATALOG`/`_CATCH` for the current, single-sourced tier — treat this paragraph as history, not current behavior.
- **Bug found + fixed:** `_roll_discrepancies` could plant two "credential-artifact" kinds on one candidate at once (e.g. Clumsy Cutie rolling `CROSS_BREACH_REUSE` + `WEAK_ENCRYPTION` together), but `generate()`'s hash-selection is a single if/elif chain — the loser had no matching hash a player could ever actually observe, an unflaggable ground-truth violation. New `candidate_gen._CREDENTIAL_ARTIFACT_KINDS` set enforces at most one credential kind per candidate.
- **`UNSALTED_STORAGE` moved Hashcrack → Dossier**, major severity — this is the reveal tier the original design doc specced ("free (hash shape)") but it had shipped Hashcrack-only. New `Dossier.credential_unsalted` flag makes the dossier password field show the plaintext in the clear (⚠ UNSALTED marker), no crack required; `submitted_hash` stays a real MD5 underneath so Hashcrack's own log rendering needed no changes.
- **Evidence Board `_GROUP_ORDER`** reordered to match tool-page order: DOSSIER, OSINT, CREDENTIAL, FORENSICS, STEGO (was …, FORENSICS, CREDENTIAL, …).
- Added Day-1 rules `rule_weak_encryption` (weighted) and `rule_unsalted_storage` (disqualifying, matching the existing major-severity → disqualifying convention).
- **Next:** none specified — Nick signed off for the day. Batch 2 (#35, #38, #4, #17, #36 — engine/economy) is next up per `planning_sprint.md`.

### 2026-07-18
- **Implemented GitHub issues #27-#30.** #27: ⏱ → finite daily budget (`daily_compute_budget` formula, verdicts grant no ⏱, board bonus now HD$, `compute_target` quota retired). #28: GhostScan report rebuilt as banded PLATFORM SWEEP / BREACH DETECTION sections with high-contrast rows; filter replaces the report in place (`ToolTerminal.set_result`). #29: universal dossier password field with WEAK/MEDIUM/STRONG encryption tiers, bcrypt always safe, `WEAK_CREDENTIAL` reworked to minor (weak enc + weak plaintext), crack state mirrored across all pages. #30: `rules_content.py` — dynamic, engine-derived Rules Pages; Evidence Board catalog now imports from it; all five tabs templated with violation tables + live DENY/FLAG column.
- Fixed pre-existing nondeterminism (builtin `hash()` seeding → `stable_hash`) and colliding candidate ids; added Day-1 `rule_leaked_password`.
- Tests: 16/16 foundation runner, 9/9 pytest twin, full markup sweep clean, Textual pilot E2E through the whole day loop. No file-truncation incidents.
- **Next:** Day-1 vertical-slice playthrough with the new economy (tune `STARTING_COMPUTE`/`DAILY_BUDGET_GROWTH` by feel); author Day 2 content.

### 2026-07-17 (cont.)
- **#20 design rework (Nick):** Site Health deltas are now only *recorded* per verdict and land in ONE batch at end of day via `scoring.apply_end_of_day_health()` (called at the top of `finish_day`). Health never moves mid-shift; the loss condition can only trip at shift end. Between-day Shift Report labels the delta "applied at end of day" and shows a red `▼ HACKDOX IS LOST` block when below threshold — N then goes to `GameOverScreen` instead of the next day (guards in both `BetweenDayScreen.action_next_day` and `App.advance_day`). Status header shows the pending delta as `⛨100% (−8.0 eod)`.
- **Status header is now two lines:** player resources & standings (day · slot · ⏱ · ⛨health+pending · HD$ · credit pips · alignment bar) on top, the page-tab strip on its own line beneath (`#status-header` height 2).
- Tests 14/14 (new: one-batch EOD application test); pilot v2 verifies health static mid-day, EOD application, between-day collapse warning, N → game over.

### 2026-07-17
- **Implemented GitHub issues #20-#25 (all sub-issues of #18 Between Day Menu / #19 Remove Lives).** Lives system fully removed; Site Health % is the loss condition (archetype weights in config, thresholds 25/75); HackDollar$ persistent currency (correct-verdict earn + health-scaled EOD bonus, ⏱ resets to capacity each shift); HackDox Credits ground-truth reveal (global `reveal` command, modal debug view, start 1 / cap 3); 13-upgrade shop catalog (auto-highlight HUDs for logs/hashes/domains/affiliations/stego/chat + per-tool cost reduction); `BetweenDayScreen` between EOD and next-day intro with shift report, Overseer between-day dialogue, and the HD$ shop. `CampaignEndScreen` covers missing day content.
- Tests: foundation runner rewritten to the new economy (13/13 green), legacy pytest twin modernized, render sweep + full Textual pilot E2E pass.
- ⚠ Six files hit Windows-mount truncation; all repaired via bash tail-splices. New recovery trick: lost post-HEAD `tools_bridge` tail reconstructed from the `.cpython-310.pyc` bytecode (marshal + dis).
- **Next:** Day-1 vertical-slice playthrough with the full macro loop; author Day 2 content so `advance_day` has somewhere to go; consider Overseer hostility arc keys (`day{N}_between`).

### 2026-07-14
- **Stegotool stamp minigame rework — DONE.** Page 5 rebuilt as 3-column (sidebar 26% / findings terminal 34% / `StegoImagePanel` viewer 40%). New interactive mechanic replaces the stego scan/filter tiers: X enters stamp mode, arrows move an 8×4 stamp, Space stamps at 1 ⏱ (`charge_stamp`), Esc exits. Revealed cells show payload type by **color** (amber plaintext / crimson encrypted / violet C2), **density** (carrier fill %), and **size** (zone extent); ≥60% zone coverage prints the explicit `▲ SIGNATURE RESOLVED` block once. Free-tier blue tint preserved for pre-⏱ reading.
- Engine: `StegoImageData` + `build_stego_image` / `evaluate_stamp` / `stamp_log_lines` / `stamp_signature_lines` / `get_stego_stats` in `tools_bridge`; config knobs `STEGO_STAMP_COST/W/H`, `STEGO_STAMP_RESOLVE_COVERAGE`, keybinding `stamp_mode: x`. Grid scales with payload severity (30×12 → 44×20).
- UI: `s`/`extract`/`stego`/`stamp`/`x` commands all open stamp mode; `filter` on page 5 hints at stamps; footer + `_REF_STEGOTOOL` reference rewritten (controls + signature color legend); `ToolTerminal.add_lines()` added for the stamp log.
- Verified: 8/8 foundation tests · 48-candidate markup sweep · pilot E2E (charge, log, exits, guards, verdict lock, per-candidate reset, single-fire resolution). No truncation incidents this session (tail-checked after every edit).
- **Next:** Day-1 vertical-slice playthrough (now including the stamp loop); consider stamp-size upgrades and per-difficulty stamp budgets as future ⏱ sinks.

### 2026-06-19 (cont.)
- **Evidence Catalog v2 — `tools_bridge` terminal rendering DONE.** All 10 kinds now reveal across free/base/filter tiers. Logwatch: split credential-stuffing from brute force, added after-hours + low-and-slow (filter-only correlation) + claimed-IP external-login path. Ghostscan: threat-forum (critical-forum reuse), burner identity (account registry), typosquat (free cue + filter). Hashcrack: cross-breach reuse (2nd corpus, breach-aligned) + unsalted storage. Stego: encrypted payload (suspicious + filter decode).
- Verified: 8/8 foundation tests, all filter labels render, 720 candidate×all-tools runs exception-free, Textual pilot runs every tool page + board toggle + scored verdict.
- ⚠️ Truncation gotcha bit `tools_bridge.py` hard — used a single bash multi-replace write + git-splice repairs; one bad splice dropped two filtered-variant fns (restored from git).
- **Two UI tweaks:** Candidate-page board → read-only flagged-only summary (`EvidenceBoard(summary=True)`, new `_render_summary`); tool-page boards vertically centered (`content-align: left middle`). Pilot-verified.
- **Next:** Day-1 vertical-slice playthrough; consider making tool-page boards scrollable if 25 items clip.

### 2026-06-19
- **Evidence Catalog v2 — engine backbone implemented & verified.** Added 10 `DiscrepancyKind`s; wired `candidate_gen` (`_SEVERITY_REVEAL`, `_DISCREPANCY_DESCRIPTIONS`, archetype `eligible_kinds`, artifact gen for cross-breach/unsalted hashes + encrypted-payload image); grew `app.EVIDENCE_ITEMS` to 25; added Day-1 rules. Verified: all 10 kinds surface on the Day-1 mix, 8/8 foundation tests pass, v2 kind earns full board bonus through `scoring.apply`.
- Drafted the 7 new **Rules & Violations** rows in Notion (GS-06/LW-04/LW-05/HC-01/HC-02/ST-01/DS-01) + 7 Evidence Options rows; introduced HC-/ST-/DS- rule prefixes (Nick approved).
- ⚠️ Windows-mount truncation hit `candidate_gen.py` and `day_01.json` again — repaired via git-splice / full rewrite in bash. Backbone files compile clean.
- **Next:** `tools_bridge` free/base/filter rendering for the 10 kinds (Logwatch already has stuffing/after-hours logic to split out); make the evidence board scrollable for 25 items.

### 2026-06-18
- **Evidence Board, take 2** — the global-overlay approach (2026-06-15) was reverted; reimplemented as a **toggleable left-side board** on the four tool pages. Candidate page left untouched. `EvidenceState` (shared flag store) + five `EvidenceBoard` views over it; **Tab** toggles on tool pages, replacing the sidebar so tool data stays visible. Verified via Textual pilot + 8/8 foundation tests.
- Repaired Windows-mount truncation in `app.py`, `config.py`, `app.tcss` by splicing lost tails from `git HEAD`.
- **Evidence Catalog v2 (design)** — speced 10 new evidence pieces and mapped them into archetypes: `BURNER_IDENTITY`, `THREAT_FORUM_MATCH`, `TYPOSQUAT_HANDLE` (OSINT); `CREDENTIAL_STUFFING`, `AFTER_HOURS_ACCESS`, `LOW_AND_SLOW` (Forensics); `CROSS_BREACH_REUSE`, `UNSALTED_STORAGE` (Credential); `ENCRYPTED_PAYLOAD` (Stego); `CLAIMED_IP_MISMATCH` (Dossier). Two-sided (violation generation + evidence collection); documented in CLAUDE.md + Notion. Not yet implemented in code.
- **Next up:** implement v2 catalog — add the `DiscrepancyKind`s, `_SEVERITY_REVEAL` / `_KIND_DESC` / `EVIDENCE_ITEMS` entries, `tools_bridge` reveal tiers, `rules_engine` predicates, and archetype `eligible_kinds`.

### 2026-06-15
- **Evidence Board overhaul** — replaced the inline Page-0 board with a global, toggleable `EvidenceScreen` overlay reachable from any page (Tab / `evidence` / `board` / `e`) *(reverted 2026-06-18 in favour of the left-side toggle)*
- Split into `EvidenceLog` (headless state), `EvidencePicker` (keyboard editor), `EvidenceScreen` (modal); old `EvidenceBoard` widget removed
- Added per-finding **intensity** (minor/major/critical, 1/2/3 or `i` to cycle) — documentation-only, scoring contract unchanged (`get_flags()` still returns `set[DiscrepancyKind]`)
- Findings grouped into 5 categories (DOSSIER/OSINT/FORENSICS/CREDENTIAL/STEGO), ←/→ to jump categories; live intensity-breakdown counter in the overlay header
- New `EVIDENCE_CATALOG` (15 items) replaces `EVIDENCE_ITEMS` — fixes previously-missing `AFFILIATION_MISMATCH` + `DISPOSABLE_EMAIL`
- Candidate page rebalanced (removed `candidate-mid`; top 58% / bot 42%); footer shows `Tab Evidence (N)`; tcss styles added for the modal
- Verified: `app.py` compiles, 8/8 foundation tests pass, board bonus flows through `scoring.apply` end-to-end
- **Next up:** vertical slice (Day 1 playable end-to-end with all 9 archetypes)

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
