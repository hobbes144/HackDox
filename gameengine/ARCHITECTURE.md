# HackDox Game Engine — Architecture

> Read this first. Everything in `gameengine/` is built against the contracts in this document.

## 1. Design Goals

1. **UI-agnostic core.** The engine logic — candidate generation, rules evaluation, scoring, day cycle — must work without any UI imports. The Textual TUI is the v1 renderer; a Flask web view will reuse the same core.
2. **Deterministic by default.** Every candidate, every shuffle, every "random" dialogue choice is derived from a seed stored in `GameState`. Replays are exact. Tests are stable.
3. **Diegetic tools.** The four existing tools are not separate apps in this build — they are buttons in the game UI that cost in-game currency to press. Tool output is rendered into the game's panels, not stdout.
4. **Vertical slice first.** v1 is one playable day with all seven archetypes represented, an Overseer intro/outro, a scored end-of-day screen, and a win/loss check. Everything below is designed to extend cleanly to a multi-day campaign without rework.
5. **JSON for everything persistent.** Saves, candidate dossiers, day specs, archetype templates — all JSON. Easy to inspect, easy to author, easy to diff.

---

## 2. Layer Map

```
┌─────────────────────────────────────────────────────────────────┐
│                          ui/ (renderers)                        │
│   ┌──────────────────────────┐    ┌─────────────────────────┐   │
│   │  ui/tui  (Textual)  v1   │    │  ui/web  (Flask)  v2    │   │
│   └────────────┬─────────────┘    └──────────┬──────────────┘   │
│                │ reads/commands              │                  │
│                ▼                             ▼                  │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │                    core/  (UI-agnostic)                     │ │
│ │                                                             │ │
│ │   day_cycle ──► rules_engine ──► scoring                    │ │
│ │       │                                                     │ │
│ │       ├──► candidate_gen ──► models (Candidate, etc.)       │ │
│ │       ├──► overseer (dialogue selector)                     │ │
│ │       ├──► tools_bridge ──► (ghostscan, logwatch, ...)      │ │
│ │       └──► persistence (save/load JSON)                     │ │
│ │                                                             │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                │                             │                  │
│                ▼                             ▼                  │
│        content/ (data files)         ../ghostscan/, etc.        │
└─────────────────────────────────────────────────────────────────┘
```

Rule: **`core/` may not import from `ui/`. `ui/` may import freely from `core/`.** `content/` is data, not code.

---

## 3. Core Data Model

All models live in `core/models.py` as `dataclasses` (frozen where practical).

### Candidate

The unit of play. The player decides ADMIT or DENY for each candidate.

```python
@dataclass(frozen=True)
class Candidate:
    id: str                          # uuid4 hex slice, used as save-key
    archetype: Archetype             # ground truth — never shown to player
    display_name: str                # "Lena Korovin"
    handle: str                      # "lkorovin"
    email: str                       # "lena.k@univ-fictional.edu"
    photo_seed: int                  # for procedural avatar rendering
    claimed_purpose: str             # what they say they want access for
    claimed_affiliation: str         # "Univ. of Fictional CS Dept."
    dossier: Dossier                 # the visible packet of "submitted" info
    chat_script: list[ChatLine]      # one-way dialogue, played in sequence
    truth: GroundTruth               # hidden answer key
```

`archetype` is one of the seven from CLAUDE.md, captured as an enum:

```python
class Archetype(str, Enum):
    OBVIOUS_ADMIT   = "obvious_admit"
    DAY_TO_DAY      = "day_to_day"
    DARK_WEB        = "dark_web"
    CLUMSY_CUTIE    = "clumsy_cutie"
    BAD_ACTOR       = "bad_actor"
    SNEAKY_BUGGER   = "sneaky_bugger"
    WHITE_HAT       = "white_hat"
```

### Dossier

The visible packet the player can scrutinize. Fields the day's rules check against.

```python
@dataclass(frozen=True)
class Dossier:
    claimed_github: str | None
    claimed_breaches: list[str]      # what the candidate claims
    submitted_log_path: str | None   # optional: a log file for logwatch
    submitted_image_path: str | None # optional: an image for stegotool
    submitted_hash: str | None       # optional: a credential for hashcrack
    notes: str                       # free-text "intake officer notes"
```

### Discrepancy

What the player is hunting. Generated alongside the candidate. Each one is tied to which tool can surface it.

```python
@dataclass(frozen=True)
class Discrepancy:
    kind: DiscrepancyKind            # enum below
    severity: Literal["minor", "major", "critical"]
    revealed_by: ToolName            # "dossier" | "ghostscan" | "logwatch" | "hashcrack" | "stegotool"
    description: str                 # human-readable, shown when revealed
```

`DiscrepancyKind` enumerates the concrete checks: `EMAIL_GITHUB_MISMATCH`, `BREACH_HIT`, `BRUTE_FORCE_IN_LOG`, `STEGO_PAYLOAD_PRESENT`, `LEAKED_PASSWORD`, `IMPOSSIBLE_TRAVEL`, etc. — one per detection the tools can produce.

### GroundTruth

The hidden answer key. Used by `scoring.py` after the player commits.

```python
@dataclass(frozen=True)
class GroundTruth:
    correct_verdict: Verdict         # ADMIT | DENY
    discrepancies: list[Discrepancy] # all planted issues, even unrevealed
    moral_modifier: int              # +1 White Hat, -1 Dark Web, 0 neutral
```

The **moral modifier** is what powers alignment drift. The Dark Web archetype is `correct_verdict=ADMIT` (clean on paper) with `moral_modifier=-1` (admitting them helps the bad guys). Denying anyway costs currency but earns alignment.

### Day

Authored in `content/days/day_01.json` and loaded into a frozen dataclass.

```python
@dataclass(frozen=True)
class Day:
    number: int
    title: str                       # "Day 1 — Onboarding"
    rules: list[Rule]                # the published rulebook
    candidate_count: int             # e.g. 6
    archetype_mix: dict[Archetype, int]  # forced distribution
    quotas: Quotas                   # min admits, max false-admits, etc.
    overseer_intro_key: str          # lookup into narratives/
    overseer_outro_keys: dict[Performance, str]  # by performance bucket
```

### Rule

The rulebook is data — readable to the player, executable by the engine.

```python
@dataclass(frozen=True)
class Rule:
    id: str                          # "rule_breach_hit"
    text: str                        # "Deny any candidate found in a known breach corpus."
    predicate: PredicateRef          # serializable reference resolved by rules_engine
    severity: Literal["disqualifying", "weighted"]
```

`predicate` is a small string key (e.g., `"has_discrepancy:BREACH_HIT"`) that the rules engine maps to a registered Python function. Keeping it as a string keeps days authorable as JSON.

### GameState

Persisted to `saves/<slot>.json`. Single source of truth between sessions.

```python
@dataclass
class GameState:
    seed: int
    current_day: int
    currency: int
    alignment: int                   # -10 (Dark Web) ... +10 (White Hat)
    site_health: float               # persistent % loss condition (replaces lives, #20)
    hackdollars: int                 # persistent between-day currency (#21)
    hackdox_credits: int             # ground-truth reveal consumables (#25)
    compute_capacity: int            # per-shift ⏱ reset target
    upgrades: set[UpgradeId]
    completed_days: list[DayResult]
    rng_state: tuple                 # so saves resume mid-day reproducibly
```

---

## 4. Candidate Generator

`core/candidate_gen.py`. Pure function from `(Day, GameState.seed, slot_index)` to `Candidate`.

Algorithm:

1. Decide the archetype for this slot using the day's `archetype_mix` (deterministic from seed).
2. Load the archetype template from `content/archetypes/<archetype>.py`. A template declares:
   - dialogue tone (cooperative / hostile / flippant / sympathetic / etc.)
   - chat line pool (snippets that compose into a 3-8 line script)
   - discrepancy budget — `{minor: N, major: M, critical: K}` ranges per archetype
   - which `DiscrepancyKind`s are eligible
3. Roll names/handles/emails from `content/word_banks/`. Apply archetype-specific patterns (e.g. Dark Web tends toward elite-speak handles; Day-to-Day uses plausible academic emails).
4. Roll the discrepancy set — pick from the eligible kinds up to the budget. **Crucially, the budget defines the archetype:**
   - Obvious Admit → 0 discrepancies
   - Day-to-Day → 1 minor
   - Dark Web → 0 visible-by-rule discrepancies, but `moral_modifier = -1` and chat references illicit acts
   - Clumsy Cutie → 2-4 mixed minors/majors
   - Bad Actor → 3-5 majors/criticals
   - Sneaky Bugger → 1-2 well-hidden majors (only revealed by tool, never by dossier)
   - White Hat → 1 critical that looks like a Bad Actor at first glance, but chat reveals motive
5. For each discrepancy, plant the supporting artifact if needed:
   - `BRUTE_FORCE_IN_LOG` → call `logwatch.modules.logforge` to synthesize a log file, attach to dossier
   - `STEGO_PAYLOAD_PRESENT` → call `stegotool.modules.forge` to embed a payload in a procedural image
   - `LEAKED_PASSWORD` → pick a wordlist password and hash it via `hashcrack.modules.hashgen`
   - `BREACH_HIT` → just a flag the ghostscan bridge will return; no external state needed
6. Compose the chat script from the archetype's pool, splicing in 0-2 lines that hint at the planted discrepancies (more hints for easy archetypes, fewer for Sneaky Bugger).
7. Return a fully populated `Candidate`.

**Seeding rule:** every `random.Random` instance the generator uses is derived from `hash((game_seed, day_number, slot_index, purpose))` — never from the global random module. This is what keeps replays exact.

---

## 5. Rules Engine

`core/rules_engine.py`.

A `Rule` carries a `predicate` string like `"has_discrepancy:BREACH_HIT"` or `"affiliation_in_allowlist"`. The engine maintains a registry of `predicate_name -> callable(Candidate, GameState) -> bool`. Authoring a new day means adding a new JSON entry, not Python — unless a brand-new predicate kind is needed.

Evaluation:

```python
def evaluate(candidate: Candidate, day: Day, state: GameState) -> RuleEvaluation:
    triggered: list[Rule] = []
    for rule in day.rules:
        if predicate_registry[rule.predicate](candidate, state):
            triggered.append(rule)
    return RuleEvaluation(
        triggered_disqualifying = [r for r in triggered if r.severity == "disqualifying"],
        triggered_weighted = [r for r in triggered if r.severity == "weighted"],
    )
```

The engine **does not produce a verdict** — it produces the evidence a player would also see in the rulebook. The *correct* verdict comes from `GroundTruth.correct_verdict`, which the candidate generator sets directly from the archetype.

This separation matters: it means the player can disagree with the rules (e.g., deny a Dark Web candidate who passes the rules) and the engine can score the moral consequence separately from the procedural one.

---

## 6. Scoring

`core/scoring.py`. Pure function from `(Candidate, Verdict, RuleEvaluation, GameState)` to `ScoreDelta`.

The asymmetric matrix from CLAUDE.md, encoded:

| Correct verdict | Player verdict | Currency | XP | Lives | Alignment |
|---|---|---|---|---|---|
| ADMIT | ADMIT | +base_reward | +1 | 0 | 0 |
| ADMIT | DENY  | 0 | 0 | 0 | +moral_modifier (if moral candidate) |
| DENY  | DENY  | 0 | +2 (advancement) | 0 | -moral_modifier |
| DENY  | ADMIT | -penalty | 0 | -1 | -moral_modifier |

The moral-modifier line is what gives Dark Web denials and White Hat admits their teeth. A correct *procedural* call against a morally-loaded candidate awards alignment in the opposite direction; a *deliberately wrong* call sacrifices currency/Site Health to gain alignment.

---

## 7. Day Cycle

`core/day_cycle.py`. State machine driving a single day.

```
DayPhase enum:
  INTRO        → Overseer pre-day briefing rendered
  INTAKE       → looping over candidates
    each candidate:
      DOSSIER  → player views dossier panel
      CHAT     → chat lines stream in (player may issue tool actions)
      VERDICT  → player commits ADMIT or DENY
      RESULT   → score applied, mini-toast shown
  OUTRO        → Overseer post-day reaction (selected by Performance bucket)
  EOD          → end-of-day summary, save, "Continue" → next day
```

The TUI never owns this state — it queries `day_cycle.current_phase()` and dispatches events back to advance. Same contract a Flask renderer would use.

---

## 8. Tools Bridge

`core/tools_bridge.py`. The four real tools, exposed to the engine as thin functions that:

1. **Charge currency** before invocation (raises `InsufficientFunds` if unaffordable).
2. **Run the underlying tool in-process** by importing its modules (not subprocess).
3. **Return a normalized result struct** — never raw stdout. The Textual screen renders it.
4. **Cache per-candidate** so re-running the same tool on the same candidate in the same day doesn't double-charge.

Concrete surface:

```python
def run_ghostscan(candidate, state) -> GhostscanResult
def run_logwatch(candidate, state) -> LogwatchResult
def run_hashcrack(candidate, state) -> HashcrackResult
def run_stegotool(candidate, state) -> StegotoolResult
```

Each implementation imports from the tool's package (`ghostscan.modules.*` etc.). To make those importable from `gameengine/`, we add the project root to `sys.path` in `hackdox.py` and consolidate dependencies into the gameengine venv. Per-tool venvs are kept for standalone tool use; the gameengine venv is a superset.

The bridge **does not call out to the network for ghostscan** in v1 — it returns synthetic results derived from the candidate's planted discrepancies. (Real network calls would be slow and non-deterministic; bad for a game loop.) The same module can flip to live mode later for an "advanced" mode.

---

## 9. Persistence

`core/persistence.py`. JSON serialization for `GameState` and the in-progress day. One slot for v1 (`saves/slot_0.json`). Atomic write via tmp-file-then-rename.

A save written mid-day captures `current_phase`, `current_slot_index`, and `rng_state`, so resuming reproduces the exact same next candidate.

---

## 10. Textual UI (v1)

`ui/tui/app.py` is a `textual.App` with screens managed by the `day_cycle` phase.

Screen layout (one main play screen, four panels):

```
┌──────────────────────────────────────────────────────────────────────┐
│ HACKDOX  ░░░░░░░  Day 1  ·  $432  ·  Alignment ▢▢▢▢░▢▢▢▢  ·  ♥♥♥    │
├────────────────────────────────┬─────────────────────────────────────┤
│ DOSSIER                        │ CHAT                                │
│  Handle: lkorovin              │  [10:02] hi — sorry, first time     │
│  Email:  lena.k@univ-...edu    │         doing this                  │
│  Claimed GitHub: lenacode       │  [10:02] my prof said you'd have    │
│  Affiliation: Univ. Fictional  │         the dataset I need          │
│  Purpose: research access      │  [10:03] anyway, thanks!            │
│  ...                           │                                     │
├────────────────────────────────┼─────────────────────────────────────┤
│ RULEBOOK (Day 1)               │ TOOLS                               │
│  [1] Deny if breached          │  [G] Ghostscan         $40          │
│  [2] Deny if no public profile │  [L] Logwatch          $30          │
│  [3] Deny if hostile           │  [H] Hashcrack         $50          │
│                                │  [S] Stegotool         $25          │
├────────────────────────────────┴─────────────────────────────────────┤
│ OVERSEER  ▸ "Welcome back. The line's already forming."              │
├──────────────────────────────────────────────────────────────────────┤
│  [A] ADMIT      [D] DENY      [N] Next candidate                     │
└──────────────────────────────────────────────────────────────────────┘
```

Five screens total for v1:

- `intro.py` — title splash, new game / continue
- `intake.py` — the layout above; the heart of the game
- `tool_result.py` — modal/inline panel when a tool finishes
- `eod.py` — end-of-day stats, Overseer outro, save & continue
- `game_over.py` — loss screen (Site Health below threshold or quota failed)

Textual widgets are kept thin — they read `core` data and dispatch events. No business logic in widgets.

---

## 11. Day 1 Content (Vertical Slice Spec)

**Title:** "Day 1 — Onboarding"

**Rulebook (3 rules):**
1. Deny any candidate found in a known breach database.
2. Deny any candidate whose claimed GitHub doesn't exist or whose email doesn't match their commit history.
3. Deny any candidate who behaves hostilely or threatens the service.

**Candidate mix (6 total):**
- 2 × Obvious Admit
- 1 × Day-to-Day
- 1 × Clumsy Cutie
- 1 × Bad Actor
- 1 × Sneaky Bugger

(Dark Web and White Hat are reserved for Day 2+ — they require the Overseer arc to land.)

**Quotas:**
- Min correct admits: 2
- Max false admits: 1 (one strike forgiven; second strike = game over)
- Currency target: $200 to "pay rent"

**Overseer dialogue:**
- Intro: friendly, welcoming, walks through the rulebook
- Outro variants: praise (good performance), measured (passing), warning (poor)

---

## 12. Test Strategy

`tests/` uses pytest.

- `test_candidate_gen.py` — given fixed seeds, each archetype produces the expected discrepancy budget and `moral_modifier`. Snapshot a handful of candidates and assert they don't drift.
- `test_rules_engine.py` — for each archetype × Day 1 ruleset, the right rules trigger. White Hat triggers disqualifying rules; Dark Web triggers none.
- `test_scoring.py` — the asymmetric matrix is enforced. Currency/Site-Health/alignment changes match the table in §6.
- `test_day_cycle.py` — phase transitions are valid; saving mid-day and reloading produces the same next state.

The Textual app gets a manual smoke test in v1 (Textual's testing tools exist but the cost isn't worth it for the vertical slice).

---

## 13. Out of Scope for v1

These are deliberately deferred — the architecture leaves seams for them:

- Multi-day campaign content (Days 2..N)
- Overseer hostility arc (data exists, but the alignment thresholds that trigger it are post-v1)
- Upgrades shop (`upgrades` set on `GameState` is wired through, but no shop UI)
- Side missions
- Web renderer (`ui/web/` stays empty until v2)
- Live ghostscan network mode
- Sound / animations beyond Textual's built-in transitions

---

## 14. Open Questions

1. **Avatar rendering.** The Notion notes call for "profile icons" per character. For TUI v1, we plan to use a 4×8 ANSI-color block portrait derived from `photo_seed` (recognizable, distinct, free). If you want something richer (e.g., ASCII art portraits), flag it.
2. **Chat pacing.** Real-time character streaming feels great but slows the loop. Default: lines appear instantly; an optional `--cinematic` flag enables streaming. Confirm preference at first play.
3. **Tool costs.** Initial numbers above ($40/30/50/25) are placeholders. Will be tuned after the first playthrough.
