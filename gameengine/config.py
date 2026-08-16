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
#
# ⏱ is a FINITE DAILY tool budget (issue #27). The player receives a fixed
# pool at the start of every shift, spends it only on tools / filters /
# stamps, and it NEVER carries over between days (issue #21). Verdicts no
# longer grant ⏱ — rationing the pool across the day's candidates is the
# core strategic decision. Running out mid-day simply disables tools for
# the rest of the shift; there is no other punishment.
# The base capacity can be raised via the between-day shop.

STARTING_COMPUTE   = 60    # ⏱ base daily budget at campaign start
STARTING_ALIGNMENT = 0     # range: ALIGNMENT_MIN .. ALIGNMENT_MAX
ALIGNMENT_MIN      = -10
ALIGNMENT_MAX      = +10

# Daily-budget difficulty formula (issue #27). Later days bring more
# candidates, so the pool grows a little each day — but slower than the
# workload does, tightening scarcity as the campaign progresses.
DAILY_BUDGET_GROWTH = 4    # extra ⏱ per day beyond day 1
DAILY_BUDGET_MIN    = 30   # formula floor — the day is never unplayable


def daily_compute_budget(day_number: int, capacity: int) -> int:
    """The ⏱ pool granted at the start of the given day.

    capacity is GameState.compute_capacity (upgradable in the shop).
    Tune DAILY_BUDGET_GROWTH / capacity purchases to manage difficulty.
    """
    return max(DAILY_BUDGET_MIN,
               capacity + DAILY_BUDGET_GROWTH * (day_number - 1))


# Maximum evidence-board accuracy bonus — paid in HackDollar$ on a correct
# verdict (issue #27 moved this off ⏱: verdicts never grant computing hours).
BOARD_ACCURACY_MAX_BONUS = 10  # HD$

# ─── Site Health — persistent % loss condition (issues #18/#20, replaces lives)
#
# Every ADMITTED candidate applies their archetype's weight to Site Health.
# Correct denials never damage health (the threat never entered the site).
# Health persists across days. Below the loss threshold → game over; above
# the reward threshold at end of day → HackDollar$ bonus.

SITE_HEALTH_START            = 100.0   # %
SITE_HEALTH_LOSS_THRESHOLD   = 25.0    # dip below at any point → game over
SITE_HEALTH_REWARD_THRESHOLD = 75.0    # above this at EOD → bonus payout

# Keyed by Archetype.value strings so config stays import-free of models.
# Positive = beneficial actor admitted; negative = threat let inside.
ARCHETYPE_HEALTH_WEIGHTS: dict[str, float] = {
    "obvious_admit":     +2.0,
    "day_to_day":        +1.5,
    "the_professional":  +2.0,
    "white_hat":         +1.0,   # rules-invalid, but they help the site
    "clumsy_cutie":      -4.0,   # hygiene risk, not malice
    "the_incompatible":  -2.0,   # policy breach, low actual threat
    "dark_web":          -8.0,
    "bad_actor":        -10.0,
    "sneaky_bugger":    -12.0,
}

# ─── HackDollar$ — persistent between-day currency (issue #21) ───────────────
#
# Earned from correct admits during the day + an end-of-day Site Health
# bonus. Accumulates across the campaign; spent ONLY in the between-day
# menu (upgrades, HackDox Credits, ⏱ capacity). Never spent on tools.

STARTING_HACKDOLLARS          = 0
HACKDOLLAR_PER_CORRECT_ADMIT  = 10   # HD$ per correct admit
HACKDOLLAR_PER_CORRECT_DENY   = 4    # HD$ per correct deny (smaller cut)
HACKDOLLAR_SITE_HEALTH_BONUS  = 25   # max EOD bonus, scaled by health %
                                     # (paid only above the reward threshold)

# ─── HackDox Credits — ground-truth reveal consumable (issues #19/#25) ───────
#
# Spending one credit reveals the current candidate's ground truth
# (correct verdict + planted discrepancy kinds — NOT the evidence trail).
# Bought in the between-day shop with HackDollar$.

STARTING_HACKDOX_CREDITS = 1    # NOTE: issue #25 AC says start 1 (title says
                                # 3 slots — that's the max slot count below)
HACKDOX_CREDIT_MAX       = 3    # slot cap — purchases refuse beyond this
CREDIT_REVEAL_COMMANDS   = ("reveal", "credit", "truth")   # command-bar keywords

# ─── Progressive unlock — the day each tool is introduced (#2 / #31) ─────────
#
# The Dossier (page 0) is always available. The four tools unlock one per day
# across the tutorial, in the teaching order defined by #15/#34
# (Ghostscan → Hashcrack → Logwatch → Stegotool). This mapping is the single
# source of truth for two things:
#   • the candidate generator's evidence-tier gate — a discrepancy is never
#     planted before the day its revealing tool is taught (#31), and
#   • the UI unlock schedule (#33/#34) — which page becomes live on which day.
# Change a value here to reschedule a tool everywhere at once.
#
TOOL_UNLOCK_DAY: dict[str, int] = {
    "dossier":   1,   # always available; listed for completeness
    "ghostscan": 2,
    "hashcrack": 3,
    "logwatch":  4,
    "stegotool": 5,
}


def tools_unlocked_by(day_number: int) -> set[str]:
    """The tool set a player should have unlocked by the given day.

    Used to backfill legacy saves (predating GameState.unlocked_tools) and to
    seed a new game. Excludes the Dossier, which is not a lockable tool page.
    """
    return {
        tool for tool, intro in TOOL_UNLOCK_DAY.items()
        if tool != "dossier" and intro <= day_number
    }


def tool_introduced_on(day_number: int) -> str | None:
    """The tool (if any) whose unlock day is exactly `day_number`.

    Drives the Overseer's unlock narration (#34): the day a tool is introduced,
    the briefing announces it and flips it on. Dossier is excluded (always
    available). Returns a ToolName value string, or None if no tool debuts.
    """
    for tool, intro in TOOL_UNLOCK_DAY.items():
        if tool != "dossier" and intro == day_number:
            return tool
    return None


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
    "stegotool":  2,   # legacy — stego page now uses the stamp mechanic
}

# ─── Stegotool stamp mechanic ────────────────────────────────────────────────
#
# The stego page replaces the old scan/filter tiers with an interactive
# "stamp" minigame: the player moves a square stamp over the pixel grid
# (arrow keys) and reveals the region under it (Space) at a small ⏱ cost.
# Once the player has revealed enough of the hidden payload zone, the
# signature "resolves" and the explicit ▲ violation label prints.
#
STEGO_STAMP_COST             = 1     # ⏱ per stamp
STEGO_STAMP_RESOLVE_COVERAGE = 0.60  # fraction of zone cells revealed → resolve
STEGO_STAMP_W                = 8     # stamp width  (cells)
STEGO_STAMP_H                = 4     # stamp height (cells; terminal cells ≈ 2:1)

# ── Filter (payload-type reveal) ──────────────────────────────────────────
# The stamp shows the carrier's *color* for free; naming the payload TYPE
# (plaintext / encrypted / C2) requires activating the filter, at this cost.
STEGO_FILTER_COST            = 2     # ⏱ to classify the payload type

# ── Image size scaling by day ─────────────────────────────────────────────
# Grid size (cols, rows) per payload type at day 1. The image grows as the
# campaign progresses: harder days = larger images = more area to sweep.
# Bump these bases, the growth, or the cap to rebalance without touching code.
STEGO_GRID_BASE: dict[str, tuple[int, int]] = {
    "clean":     (30, 12),
    "plaintext": (36, 16),
    "encrypted": (40, 18),
    "c2":        (44, 20),
}
STEGO_GRID_GROWTH_COLS_PER_DAY = 4   # extra columns per day beyond day 1
STEGO_GRID_GROWTH_ROWS_PER_DAY = 2   # extra rows per day beyond day 1
STEGO_GRID_MAX = (72, 32)            # hard cap (cols, rows) so it never overflows

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

# ─── Upgrades (issue #23) ────────────────────────────────────────────────────
#
# Upgrade IDs are plain strings so new upgrades can be added without touching
# game-state serialisation. The player's unlocked set lives in GameState.upgrades.
# All upgrades are permanent, bought in the between-day shop with HackDollar$,
# and are strict no-ops until purchased.
#
UPGRADE_SESSION_GROUPING = "session_grouping"   # Logwatch: groups log by session blocks

# Auto-highlight upgrades — surface signals the engine already computes.
UPGRADE_LOG_HIGHLIGHT    = "log_highlight"      # Logwatch: colour suspicious log lines
UPGRADE_HASH_HIGHLIGHT   = "hash_highlight"     # Hashcrack: colour suspicious audit lines
UPGRADE_EMAIL_APPROVED   = "email_approved_highlight"    # dossier: green trusted domains
UPGRADE_EMAIL_PROHIBITED = "email_prohibited_highlight"  # dossier: red disposable domains
UPGRADE_AFFIL_APPROVED   = "affil_approved_highlight"    # dossier: green trusted orgs
UPGRADE_AFFIL_PROHIBITED = "affil_prohibited_highlight"  # dossier: red threat-actor orgs
UPGRADE_STEGO_TINT       = "stego_area_tint"    # Stegotool: stronger area-of-interest tint
UPGRADE_CHAT_HOSTILE     = "chat_hostile_highlight"      # chat: mark hostile lines

# Economy upgrades -- reduce a tool's cost by TOOLCOST_REDUCTION (floor 1).
# IDs follow "toolcost_<tool>" so _charge() can key off the tool name directly.
UPGRADE_TOOLCOST_GHOSTSCAN = "toolcost_ghostscan"
UPGRADE_TOOLCOST_LOGWATCH  = "toolcost_logwatch"
UPGRADE_TOOLCOST_HASHCRACK = "toolcost_hashcrack"
UPGRADE_TOOLCOST_STEGOTOOL = "toolcost_stegotool"   # reduces the stego filter cost
TOOLCOST_REDUCTION = 1   # ⏱ knocked off the base cost when owned

# Shop catalog: (upgrade_id, label, HD$ price, description).
# The between-day menu renders this list; effects key off GameState.upgrades.
UPGRADE_CATALOG: list[tuple[str, str, int, str]] = [
    (UPGRADE_LOG_HIGHLIGHT,    "Log Analyzer HUD",      35, "auto-highlight suspicious lines in the Logwatch day log"),
    (UPGRADE_HASH_HIGHLIGHT,   "Credential HUD",        35, "auto-highlight suspicious lines in the Hashcrack audit log"),
    (UPGRADE_EMAIL_APPROVED,   "Domain Whitelist HUD",  20, "auto-highlight approved email domains on the dossier"),
    (UPGRADE_EMAIL_PROHIBITED, "Domain Blacklist HUD",  25, "auto-highlight prohibited email domains on the dossier"),
    (UPGRADE_AFFIL_APPROVED,   "Org Whitelist HUD",     20, "auto-highlight approved affiliations on the dossier"),
    (UPGRADE_AFFIL_PROHIBITED, "Org Blacklist HUD",     25, "auto-highlight prohibited affiliations on the dossier"),
    (UPGRADE_STEGO_TINT,       "Spectral Lens",         30, "stronger blue tint over stego areas of interest"),
    (UPGRADE_CHAT_HOSTILE,     "Sentiment Scanner",     20, "auto-mark hostile text in candidate chat"),
    (UPGRADE_SESSION_GROUPING, "Session Grouper",       30, "group the Logwatch day log into session blocks"),
    (UPGRADE_TOOLCOST_GHOSTSCAN, "Ghostscan Optimizer", 45, f"ghostscan costs {TOOLCOST_REDUCTION} ⏱ less"),
    (UPGRADE_TOOLCOST_LOGWATCH,  "Logwatch Optimizer",  40, f"logwatch costs {TOOLCOST_REDUCTION} ⏱ less"),
    (UPGRADE_TOOLCOST_HASHCRACK, "Hashcrack Optimizer", 35, f"hashcrack costs {TOOLCOST_REDUCTION} ⏱ less"),
    (UPGRADE_TOOLCOST_STEGOTOOL, "Stego Optimizer",     30, f"stego filter costs {TOOLCOST_REDUCTION} ⏱ less"),
]

# Non-upgrade shop items (consumables / capacity).
SHOP_PRICE_CREDIT       = 40   # HD$ per HackDox Credit (up to HACKDOX_CREDIT_MAX)
SHOP_PRICE_CAPACITY     = 60   # HD$ per ⏱-capacity increase
COMPUTE_CAPACITY_STEP   = 10   # ⏱ added to capacity per purchase

# ─── Save slot (single-slot for v1) ─────────────────────────────────────────

SAVE_SLOT = "slot_0"
SAVE_FILE = SAVES_DIR / f"{SAVE_SLOT}.json"

# ─── Key bindings ─────────────────────────────────────────────────────────────────
#
# Change any value here to remap that control everywhere in the TUI.
# Use Textual key names: letters are lowercase, specials are snake_case
# (e.g. "grave_accent", "question_mark", "escape", "space", "f1").
#
# Pages are navigated with the number row.  Arrow keys navigate focus
# between panels within the current page.
#
KEY_BINDINGS: dict[str, str] = {
    # ── Page navigation (number row) ──────────────────────
    "page_candidate":   "1",
    "page_ghostscan":   "2",
    "page_hashcrack":   "3",
    "page_logwatch":    "4",
    "page_stegotool":   "5",
    "page_rules":       "0",   # 0 key opens the rules overlay

    # ── Within-page focus navigation ──────────────────────
    # up/down cycle focus; left/right also cycle (spatial feel).
    # Note: when the Evidence Board has focus, up/down move the cursor
    # within the board instead and do NOT cycle page focus.
    "focus_prev":       "up",
    "focus_next":       "down",
    "focus_left":       "left",
    "focus_right":      "right",

    # ── Verdict & flow ────────────────────────────────────
    "admit":            "a",
    "deny":             "d",
    "next_candidate":   "n",

    # ── Tool shortcuts (jump to page + run tool) ──────────────────
    "tool_ghostscan":   "g",
    "tool_logwatch":    "l",
    "tool_hashcrack":   "h",
    "tool_stegotool":   "s",   # jumps to the stego page + enters stamp mode
    "filter_current":   "f",

    # ── Stegotool stamp mode (page 5 only) ────────────────────
    # Toggles stamp mode when the command buffer is empty. In stamp mode the
    # arrow keys move the stamp, Space stamps (STEGO_STAMP_COST),  and
    # Escape (or this key again) exits.
    "stamp_mode":       "x",

    # ── Misc ────────────────────────────────
    # Toggle the Evidence Board on the tool pages (2-5). It slides in on the
    # left so the tool data on the right stays visible. On the Candidate page
    # (1) the board is always baked in, so this key is a no-op there.
    "toggle_evidence":  "tab",
    "toggle_debug":     "grave_accent",
    "help":             "question_mark",
    "quit":             "q",
}
