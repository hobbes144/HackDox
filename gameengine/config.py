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
HACKDOLLAR_PER_CORRECT_ADMIT  = 10   # HD$ per correct admit (day-1 rate)
HACKDOLLAR_PER_CORRECT_DENY   = 4    # HD$ per correct deny (smaller cut)
HACKDOLLAR_SITE_HEALTH_BONUS  = 25   # max EOD bonus, scaled by health %
                                     # (paid only above the reward threshold)

# ── Reward decay (#4, lever 1) ───────────────────────────────────────────────
#
# The issue originally specified ⏱ decay — `max(8, 15 - floor(day/3))` per
# correct verdict. That is obsolete: #27 made verdicts grant ZERO ⏱ (the pool
# is a spend-only daily budget), so there is no ⏱ reward left to decay. The
# lever is reframed onto HackDollar$, keeping the original's shape — step down
# every N days, then floor — and its floor ratio (the original bottomed out at
# 8/15 ≈ 53%; admit lands at 6/10 = 60%, deny at 2/4 = 50%).
#
# floor(day/5) is 0 across days 1–4, so the tutorial pays the flat rate and
# #15's "difficulty stays flat-easy across Days 1–5" holds. Both curves reach
# their floor around day 20–24, i.e. at the campaign's climax rather than
# bottoming out mid-run.
#
# The board-accuracy bonus and the EOD Site Health bonus deliberately do NOT
# decay: both are already scored on performance, so decaying them on top would
# penalise a player twice for the same shift.
HACKDOLLAR_DECAY_ADMIT_PERIOD = 5    # admit rate steps down every N days
HACKDOLLAR_DECAY_DENY_PERIOD  = 10   # deny rate steps down every N days
HACKDOLLAR_FLOOR_ADMIT        = 6
HACKDOLLAR_FLOOR_DENY         = 2


def DAY_REWARD_PAYOUT(day_number: int, admit: bool) -> int:
    """HD$ paid for one correct verdict on the given day.

    `admit` selects the admit or deny rate — correct denials have always paid
    the smaller cut, and they decay on a slower clock because there is less
    there to take away.
    """
    if admit:
        return max(HACKDOLLAR_FLOOR_ADMIT,
                   HACKDOLLAR_PER_CORRECT_ADMIT
                   - day_number // HACKDOLLAR_DECAY_ADMIT_PERIOD)
    return max(HACKDOLLAR_FLOOR_DENY,
               HACKDOLLAR_PER_CORRECT_DENY
               - day_number // HACKDOLLAR_DECAY_DENY_PERIOD)

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

# ─── Tool cost inflation (#4, lever 2) ───────────────────────────────────────
#
# Tool base costs creep up as the campaign runs, so the same shift budget buys
# fewer scans. Applied in tools_bridge.tool_cost() AFTER #23's toolcost_*
# upgrade reduction, so a purchased optimizer keeps saving its ⏱ at day 20
# instead of being quietly erased by inflation.
#
# Two things deliberately do NOT inflate:
#   • FILTER costs. The GDD wants players pushed *into* filters as rewards
#     shrink (filter-avoidance is meant to correlate with lower accuracy).
#     Inflating only the base makes the filter relatively cheaper over time,
#     which pushes the right way; inflating both would push against the design.
#   • The stego STAMP cost. STEGO_GRID_GROWTH_* already grows the image every
#     day, so the number of stamps needed to reach resolve coverage rises on
#     its own. Charging more per stamp on top of a bigger grid compounds.
TOOL_COST_INFLATION_PERIOD = 4   # +1 ⏱ to every tool base cost every N days


def tool_cost_inflation(day_number: int) -> int:
    """Extra ⏱ added to every tool's base cost on the given day."""
    return day_number // TOOL_COST_INFLATION_PERIOD


def DAY_TOOL_COST(tool_name: str, day_number: int,
                  upgrades: set[str] | None = None) -> int:
    """The effective ⏱ base cost of a tool on a given day.

    The read-only twin of `tools_bridge.tool_cost()`, for UI that wants to
    preview next shift's prices without a GameState in hand (#4's end-of-day
    display). Ordering must match tool_cost() exactly: upgrade reduction and
    its floor first, inflation second.
    """
    base = TOOL_COSTS[tool_name]
    if upgrades and f"toolcost_{tool_name}" in upgrades:
        base = max(1, base - TOOLCOST_REDUCTION)
    return base + tool_cost_inflation(day_number)

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

CINEMATIC_CHAT             = False
CHAT_LINE_DELAY            = 0.04

# ─── Campaign shape (#17) ────────────────────────────────────────────────────
#
# CAMPAIGN_LAST_DAY is the ceiling for procedurally-synthesized days: past it,
# content_loader stops synthesizing and the campaign-end screen fires. The
# candidate-count cap below and #4's reward-decay floors are both tuned to
# bottom out shortly before this, so the campaign's last stretch plays at its
# hardest rather than easing off.
CAMPAIGN_LAST_DAY = 20

# Days 1..TUTORIAL_LAST_DAY are the teaching days (#15): one tool introduced
# per day, and the difficulty levers deliberately stay flat across them.
TUTORIAL_LAST_DAY = 5

# ─── Candidate volume ramp (#17) ─────────────────────────────────────────────
#
# The "volume" difficulty lever, complementing #4's economy/complexity levers.
# Curve shape lives entirely in DAY_CANDIDATE_COUNT so there is one place to
# retune it:
#
#   days 1-5 : 6 6 6 6 6                      (flat — teaching, not grinding)
#   days 6+  : 7 7 8 8 9 9 10 10 11 11 12 …   (+1 every two days)
#   cap      : 12, reached on day 16
#
# A day_NN.json that declares candidate_count explicitly always overrides this.
CANDIDATE_COUNT_TUTORIAL = 6     # flat count across the tutorial days
CANDIDATE_COUNT_BASE     = 6     # where the post-tutorial ramp starts
CANDIDATE_COUNT_GROWTH   = 0.5   # extra candidates per day after the tutorial
CANDIDATE_COUNT_CAP      = 12    # sustained late-campaign ceiling


def DAY_CANDIDATE_COUNT(day_number: int) -> int:
    """How many candidates the given day's shift contains.

    Single source of truth for shift length: the intake loop drives off
    Day.candidate_count, which is either the day file's explicit value or this.
    """
    if day_number <= TUTORIAL_LAST_DAY:
        return CANDIDATE_COUNT_TUTORIAL
    beyond = day_number - TUTORIAL_LAST_DAY
    # math.ceil without the import — the first post-tutorial day should already
    # feel a step longer rather than rounding back down to the tutorial length.
    grown = CANDIDATE_COUNT_BASE + -int(-beyond * CANDIDATE_COUNT_GROWTH // 1)
    return min(CANDIDATE_COUNT_CAP, grown)


# Quotas scale with volume (#17 AC / issue #12). A 12-candidate shift asking
# for the same 2 correct admits as a 6-candidate shift would get *easier* as
# the campaign ramps. The ratio is chosen so Day 1 is numerically unchanged:
# round(6 * 0.34) == 2, exactly what day_01.json already declares.
QUOTA_ADMIT_RATIO = 0.34
# max_false_admits deliberately does NOT scale. Letting more threats through on
# a longer shift would make late days more forgiving — backwards for a ramp.


def DAY_MIN_CORRECT_ADMITS(day_number: int, candidate_count: int,
                           authored: int | None = None) -> int:
    """The day's admit quota, scaled to shift length.

    `authored` is the day file's own value where it declares one; the result is
    never lower than what the content author asked for.
    """
    scaled = max(1, round(candidate_count * QUOTA_ADMIT_RATIO))
    return max(scaled, authored or 0)


# ─── Difficulty bands (#4 / #17) ─────────────────────────────────────────────
#
# The coarse label a day carries. Authored per-day where a day file exists;
# synthesized days derive it from here. It drives #4's detection-complexity
# lever — archetype mix and discrepancy-tier bias.
DIFFICULTY_BAND_LAST_EASY   = TUTORIAL_LAST_DAY   # days 1-5
DIFFICULTY_BAND_LAST_MEDIUM = 12                  # days 6-12; 13+ is hard


def difficulty_band_for_day(day_number: int) -> str:
    if day_number <= DIFFICULTY_BAND_LAST_EASY:
        return "easy"
    if day_number <= DIFFICULTY_BAND_LAST_MEDIUM:
        return "medium"
    return "hard"


# ─── Detection complexity (#4, lever 3) ──────────────────────────────────────
#
# Band-weighted archetype mixes for procedurally-synthesized days. An authored
# day_NN.json's own archetype_mix always overrides this, so writing real day
# content never has to fight the curve.
#
# The shift the issue asks for is "toward Sneaky Bugger dominance late-game":
# easy days lean on the obvious cases the tutorial taught, hard days load up
# on the archetype that punishes not using tools. Values are relative weights,
# not counts — content_loader.scale_archetype_mix apportions them to the day's
# actual candidate count.
#
# Keyed by Archetype.value strings so config stays import-free of models, the
# same convention ARCHETYPE_HEALTH_WEIGHTS already uses.
ARCHETYPE_MIX_BY_BAND: dict[str, dict[str, int]] = {
    # Day-1-like: the bread-and-butter admits, one of each threat.
    "easy": {
        "obvious_admit":    3,
        "day_to_day":       1,
        "the_professional": 1,
        "clumsy_cutie":     1,
        "the_incompatible": 1,
        "bad_actor":        1,
        "sneaky_bugger":    1,
    },
    # Fewer freebies, the subtle threat starts to outnumber the loud one.
    "medium": {
        "obvious_admit":    2,
        "day_to_day":       2,
        "the_professional": 1,
        "clumsy_cutie":     1,
        "the_incompatible": 1,
        "bad_actor":        1,
        "sneaky_bugger":    2,
        "dark_web":         1,
    },
    # Sneaky Bugger dominant; the easy reads are scarce and the moral forks
    # are frequent. This is the band where coasting on dossier reads fails.
    #
    # The Professional and The Incompatible are deliberately KEPT here even
    # though they are the two "quick case" archetypes. The GDD wants those as
    # pacing beats — low-friction cases that interrupt a run of heavy
    # investigation and let the player bank ⏱. Dropping them from the hard band
    # made a late shift twelve straight deep investigations with no breathing
    # room, which reads as a wall rather than escalation.
    "hard": {
        "obvious_admit":    1,
        "day_to_day":       2,
        "the_professional": 1,
        "the_incompatible": 1,
        "clumsy_cutie":     1,
        "bad_actor":        1,
        "sneaky_bugger":    4,
        "dark_web":         2,
    },
}

# On "hard" days the generator prefers evidence that needs a tool over evidence
# readable free off the dossier, so a late-game candidate's discrepancies sit
# behind the ⏱ economy rather than in plain sight. See
# candidate_gen._roll_discrepancies.
DIFFICULTY_BANDS_TOOL_BIASED: frozenset[str] = frozenset({"hard"})

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
    # Toggle the editable Evidence Board on every page. On tool pages (2-5)
    # it slides in on the left so the tool data on the right stays visible.
    # On the Candidate page (1) it swaps in for the read-only summary board.
    "toggle_evidence":  "tab",
    "toggle_debug":     "grave_accent",
    "help":             "question_mark",
    "quit":             "q",
}
