"""Game-wide tunables.

These are the only knobs that should be touched to rebalance the game. Any
gameplay constant that might need adjustment lives here, not inline in the
engine.
"""

from __future__ import annotations

from pathlib import Path

# ─── Filesystem ──────────────────────────────────────────────────────────────

ROOT_DIR = Path(__file__).resolve().parent
CONTENT_DIR = ROOT_DIR / "content"
SAVES_DIR = ROOT_DIR / "saves"
DAYS_DIR = CONTENT_DIR / "days"
ARCHETYPES_DIR = CONTENT_DIR / "archetypes"
WORD_BANKS_DIR = CONTENT_DIR / "word_banks"
NARRATIVES_DIR = CONTENT_DIR / "narratives"

SAVES_DIR.mkdir(parents=True, exist_ok=True)

# ─── Economy — Computing Hours (⏱) ──────────────────────────────────────────

STARTING_COMPUTE   = 50    # ⏱ at shift start
STARTING_LIVES     = 3
STARTING_ALIGNMENT = 0     # range: ALIGNMENT_MIN .. ALIGNMENT_MAX
ALIGNMENT_MIN      = -10
ALIGNMENT_MAX      = +10

# Reward for any correct verdict (admit or deny)
CORRECT_VERDICT_REWARD = 15   # ⏱

# Maximum bonus for a perfectly accurate evidence board
BOARD_ACCURACY_MAX_BONUS = 10  # ⏱

# False admit consequences — costs lives, not compute hours
FALSE_ADMIT_LIVES_PENALTY = 1

# ─── Tool base costs (⏱ per invocation) ─────────────────────────────────────

TOOL_COSTS: dict[str, int] = {
    "ghostscan":  5,
    "logwatch":   4,
    "hashcrack":  3,
    "stegotool":  2,
}

# ─── Filter costs (⏱ additional, on top of tool base cost) ──────────────────
# Filters make raw output easier to interpret but never give the answer.

FILTER_COSTS: dict[str, int] = {
    "ghostscan":  3,   # cross-reference email vs GitHub commit history
    "logwatch":   3,   # geographic timeline overlay
    "hashcrack":  4,   # extended wordlist + full mutation rules
    "stegotool":  2,   # per-channel LSB chi-square breakdown
}

# ─── Day-cycle pacing ────────────────────────────────────────────────────────

DEFAULT_CANDIDATES_PER_DAY = 6
CINEMATIC_CHAT             = False
CHAT_LINE_DELAY            = 0.04

# ─── Logwatch shared log — volume scaling ────────────────────────────────────
#
# Target total noise entries (background accounts) per day number.
# Candidate entries are generated separately and always included.
# Days beyond the last key scale by LW_ENTRIES_SCALE_FACTOR per extra day.
# Set LW_ENTRIES_BY_DAY[N] directly to pin any day to an exact count.
#
LW_ENTRIES_BY_DAY: dict[int, int] = {
    1:  80,    # Day 1  — quiet intro shift
    2: 100,
    3: 120,
    4: 150,
    5: 180,
    6: 210,
    7: 240,
}
LW_ENTRIES_DEFAULT      = 200   # fallback for days not in the dict
LW_ENTRIES_SCALE_FACTOR = 1.15  # multiplier applied per day beyond the last key

# ─── Upgrades ────────────────────────────────────────────────────────────────
#
# Upgrade IDs are plain strings so new upgrades can be added without touching
# game-state serialisation. The player's unlocked set lives in GameState.upgrades.
#
UPGRADE_SESSION_GROUPING = "session_grouping"   # Logwatch: groups log by session blocks

# ─── Save slot (single-slot for v1) ─────────────────────────────────────────

SAVE_SLOT = "slot_0"
SAVE_FILE = SAVES_DIR / f"{SAVE_SLOT}.json"

# ─── Key bindings ─────────────────────────────────────────────────────────────
#
# Change any value here to remap that control everywhere in the TUI.
# Use Textual key names: letters are lowercase, specials are snake_case
# (e.g. "grave_accent", "question_mark", "escape", "space", "f1").
#
# Pages are navigated with the number row.  Arrow keys navigate focus
# between panels within the current page.
#
KEY_BINDINGS: dict[str, str] = {
    # ── Page navigation (number row) ──────────────────────────────────────
    "page_candidate":   "1",
    "page_ghostscan":   "2",
    "page_hashcrack":   "3",
    "page_logwatch":    "4",
    "page_stegotool":   "5",
    "page_rules":       "0",   # 0 key opens the rules overlay

    # ── Within-page focus navigation ──────────────────────────────────────
    # up/down cycle focus; left/right also cycle (spatial feel).
    # Note: when the Evidence Board has focus, up/down move the cursor
    # within the board instead and do NOT cycle page focus.
    "focus_prev":       "up",
    "focus_next":       "down",
    "focus_left":       "left",
    "focus_right":      "right",

    # ── Verdict & flow ────────────────────────────────────────────────────
    "admit":            "a",
    "deny":             "d",
    "next_candidate":   "n",

    # ── Tool shortcuts (jump to page + run tool) ──────────────────────────
    "tool_ghostscan":   "g",
    "tool_logwatch":    "l",
    "tool_hashcrack":   "h",
    "tool_stegotool":   "s",
    "filter_current":   "f",

    # ── Misc ──────────────────────────────────────────────────────────────
    "toggle_debug":     "grave_accent",
    "help":             "question_mark",
    "quit":             "q",
}
