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

# Alignment bands (issue #42) — the three-ending structure (Game Design →
# "Player Alignment") needs a way to classify a running GameState.alignment
# value as leaning White Hat, leaning Dark Web, or neither. See
# `core/overseer.py` for the selector this feeds and the full reasoning;
# short version: scoring.score() moves alignment by the candidate's
# moral_modifier (Dark Web = -1 per verdict, White Hat = +4 once on day 12),
# so a player who resists the Overseer's Dark Web pressure across even a
# handful of encounters — or who makes the single White Hat call — clears
# +4 well before day 20; a player who complies clears -4 the same way. A
# threshold set at the White Hat's own single-encounter magnitude means one
# unambiguous act of resistance (or complicity) is enough to be recognized,
# while a genuinely mixed record — some resisted, some not — stays neutral
# rather than tipping on noise. Symmetric around STARTING_ALIGNMENT (0).
ALIGNMENT_BAND_WHITE_HAT_THRESHOLD = 4    # alignment >= this -> "whitehat"
ALIGNMENT_BAND_DARK_WEB_THRESHOLD  = -4   # alignment <= this -> "darkweb"

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

SITE_HEALTH_START            = 50.0   # %
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

STARTING_HACKDOX_CREDITS = 0    # NOTE: issue #25 AC says start 1 (title says
                                # 3 slots — that's the max slot count below)
HACKDOX_CREDIT_MAX       = 3    # slot cap — purchases refuse beyond this
CREDIT_REVEAL_COMMANDS   = ("reveal", "credit", "truth")   # command-bar keywords

# Batch-3 task #8: fallback width for StatusHeader's right-justify math when
# the widget's real render width isn't available yet (unmounted, e.g. a
# direct StatusHeader(...).render() call in a test) — the bar still needs a
# number to pad against. In a real mounted app self.size.width (the actual
# terminal width) is used instead, so this constant never affects play.
STATUS_BAR_FALLBACK_WIDTH = 100

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


# ─── Progressive breach-database unlock (#61) ────────────────────────────────
#
# The breach corpora the player must scan are static for the whole campaign —
# the same names, the same contents, every day. Difficulty comes from ADDING
# databases, never from changing or removing one, so a player who learns a
# list keeps that knowledge for the rest of the run. That is the entire point:
# before this, get_breach_lists() reseeded all six databases per CANDIDATE, so
# scanning was pure busywork and memory bought you nothing.
#
# Deliberately shaped like TOOL_UNLOCK_DAY above, and it is the single source
# of truth for the same two things:
#   • which databases the Ghostscan breach panel renders on a given day, and
#   • which database the generator may attach a candidate to — a candidate is
#     never planted into a corpus the player cannot open.
#
# Keys must match tools_bridge._BREACH_DATABASES exactly; that module asserts
# it at import rather than trusting the two to stay hand-synced, which is the
# lesson #57 cost us.
#
# Schedule rationale: one new corpus per tutorial beat (days 1/3/5) so the
# panel grows while the player is still learning to read it, then spaced out
# across the campaign. Day 3 is load-bearing — see MIN_BREACH_DBS_FOR_REUSE.
BREACH_DB_UNLOCK_DAY: dict[str, int] = {
    "Collection #1 (2019)":  1,
    "LinkedIn (2016)":       3,
    "RockYou (2024)":        5,
    "Dropbox (2012)":        8,
    "Adobe (2013)":         12,
    "MyFitnessPal (2018)":  16,
}

# CROSS_BREACH_REUSE means "this password recurs across MULTIPLE corpora", so
# it is not expressible — in ground truth or in the cipher block's readout, which
# names two corpora for it — until at least two databases are unlocked.
# The generator refuses to plant it below this threshold. Under the schedule
# above that is day 3, which is also the kind's evidence-tier intro day
# (Hashcrack), so today the constraint binds exactly where the tier gate
# already did. It is enforced anyway: retuning the schedule above must not be
# able to silently reintroduce an unobservable violation.
MIN_BREACH_DBS_FOR_REUSE = 2


def breach_dbs_unlocked_by(day_number: int) -> list[str]:
    """The breach databases available on the given day, in unlock order.

    Ordered by (unlock day, name) rather than by dict order so the result is a
    pure function of the table and two callers can never disagree about index
    0. Once a database is in, it never leaves.
    """
    return [
        name for name, intro in sorted(
            BREACH_DB_UNLOCK_DAY.items(), key=lambda kv: (kv[1], kv[0]))
        if intro <= day_number
    ]


def breach_db_introduced_on(day_number: int) -> str | None:
    """The breach database (if any) whose unlock day is exactly `day_number`."""
    for name, intro in sorted(BREACH_DB_UNLOCK_DAY.items(),
                              key=lambda kv: (kv[1], kv[0])):
        if intro == day_number:
            return name
    return None


# ─── Tool base costs (⏱ per invocation) ─────────────────────────────────────

TOOL_COSTS: dict[str, int] = {
    "ghostscan":  2,
    "hashcrack":  3,
    "logwatch":   4,
    "stegotool":  5,
}

# ─── Filter costs (⏱ additional, on top of tool base cost) ──────────────────
# Filters make raw output easier to interpret but never give the answer.

FILTER_COSTS: dict[str, int] = {
    "ghostscan":  4,   # cross-reference email vs GitHub commit history
    "logwatch":   6,   # geographic timeline overlay
    "hashcrack":  8,   # legacy — hashcrack page now uses the cipher-block aperture
    "stegotool":  10,   # legacy — stego page now uses the stamp mechanic
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
    display). Ordering must match tool_cost() exactly: upgrade reduction,
    then inflation, then the 1 ⏱ floor applied to the final total (not to
    the pre-inflation intermediate — see tool_cost()'s docstring).
    """
    base = TOOL_COSTS[tool_name]
    if upgrades and f"toolcost_{tool_name}" in upgrades:
        base -= TOOLCOST_REDUCTION
    total = base + tool_cost_inflation(day_number)
    return max(1, total)

# ─── Stegotool stamp mechanic ────────────────────────────────────────────────
#
# The stego page replaces the old scan/filter tiers with an interactive
# "stamp" minigame: the player moves a square stamp over the pixel grid
# (arrow keys) and reveals the region under it (Space) at a small ⏱ cost.
# Once the player has revealed enough of the hidden payload zone, the
# signature "resolves" and the explicit ▲ violation label prints.
#
STEGO_STAMP_COST             = 5     # ⏱ per stamp
STEGO_STAMP_RESOLVE_COVERAGE = 0.60  # fraction of zone cells revealed → resolve
STEGO_STAMP_W                = 8     # stamp width  (cells)
STEGO_STAMP_H                = 4     # stamp height (cells; terminal cells ≈ 2:1)

# ── Spectral Lens hint region (#54) ───────────────────────────────────────
# How far beyond the real payload zone the Spectral Lens upgrade's blue tint
# extends, in cells. The tint advertises a GENERAL area, never the exact zone —
# larger buffer = vaguer hint. Before #54 the free tier tinted the exact zone,
# which solved the stamp minigame for nothing and left the 30 HD$ upgrade with
# almost nothing to sell; base tier now tints nothing at all.
STEGO_HINT_BUFFER            = 2     # cells of slack around the zone

# ── Filter (payload-type reveal) ──────────────────────────────────────────
# The stamp shows the carrier's *color* for free; naming the payload TYPE
# (plaintext / encrypted / C2) requires activating the filter, at this cost.
STEGO_FILTER_COST            = 10     # ⏱ to classify the payload type

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

# ── Carrier SHAPE axis (2026-09-19) ───────────────────────────────────────
# Independent of the payload COLOUR above: the glyph the carrier cells form
# encodes the payload's purpose. Rolled in candidate_gen._roll_discrepancies
# ONLY for a shape-eligible archetype (candidate_gen._SHAPE_ELIGIBLE_ARCHETYPES)
# that actually carries a stego colour kind. This is the chance such a carrier
# stays CONVENTIONAL (clumped blocks — no extra violation); the remainder is
# split evenly across the three special shapes (cross / enclosed / slash).
# Kept the majority outcome so a special glyph stays a notable find rather
# than the default.
STEGO_SHAPE_CONVENTIONAL_CHANCE = 0.55

# ── Free-tier readout bars (image statistics) ─────────────────────────────
# The free stego terminal (tools_bridge._stego_image_lines) renders R/G/B
# channel entropy, RS-pair ratios, and LSB autocorrelation as bars instead
# of bare numbers -- same block-bar language as the Logwatch Activity
# Report (LW_PROFILE_METRICS / logwatch_report._bar), so the tool pages
# read as one system. Each bar shows a shaded "expected" band (what a
# clean image reads) plus the observed value's position -- visible with
# no upgrade owned. The Channel Colorizer upgrade (UPGRADE_STEGO_RGB_COLOR)
# only adds severity colour on top; it never gates the band/shape itself.
STEGO_BAR_WIDTH          = 14        # chars; LW_BAR_WIDTH_COMPACT-sized to
                                      # fit the 34%-wide findings terminal

# R/G/B channel LSB entropy score (0-100). Clean images land in this band;
# suspicious images push one (or two, for C2) channels well past it.
STEGO_ENTROPY_SCALE      = 100
STEGO_ENTROPY_EXPECTED   = (8, 30)

# RS pair analysis: R-group and S-group ratios plotted as two point-value
# bars on the same 0.70-1.30 scale. Clean images keep both near 1.0;
# embedding pushes them apart in opposite directions.
STEGO_RS_SCALE           = (0.70, 1.30)
STEGO_RS_EXPECTED        = (0.95, 1.05)

# LSB autocorrelation: signed, expected near zero for a clean image.
STEGO_CORR_SCALE         = (-0.05, 0.25)
STEGO_CORR_EXPECTED      = (-0.02, 0.04)

# RS pair (R-group / S-group ratio) is plotted as a 2-D point on one square,
# both axes sharing STEGO_RS_SCALE/STEGO_RS_EXPECTED -- a clean image sits
# near the centre band on both axes; embedding pushes R and S apart in
# opposite directions, which reads as the point drifting off the shaded
# square rather than two separately-legible numbers.
STEGO_RS_PLANE_W         = 13        # chars (X axis: R-group ratio)
STEGO_RS_PLANE_H         = 5         # rows  (Y axis: S-group ratio)

# Independent per-signal "tell" chance (issue: multiple points of contact).
# A suspicious image doesn't push every readout out of range together --
# each signal group rolls independently, so sometimes only the RS plane
# reads anomalous while the RGB bars look clean, or vice versa. The player
# has to cross-check more than one readout before trusting either; no
# single number is a reliable go/no-go on its own. If every roll misses,
# one group is forced on so a genuinely suspicious image always leaves at
# least one thread to pull in the free tier.
STEGO_TELL_CHANCE_ENTROPY = 0.70
STEGO_TELL_CHANCE_RS      = 0.70
STEGO_TELL_CHANCE_CORR    = 0.70

# ─── Hashcrack cipher block ──────────────────────────────────────────────────
#
# The Hashcrack page is a standalone TWO-STAGE DECRYPTION minigame. The
# candidate's credential is rendered as a block of ciphertext glyphs; the
# player identifies the algorithm from the block itself, selects the matching
# decryption window, and then walks a two-axis alignment pad until the whole
# block resolves into the password.
#
# It replaced an earlier aperture-sweep design (moveable reveal windows, a
# per-batch ⏱ cost, a coverage threshold). That version was a spatial hunt
# wearing a cryptography costume — the skill it tested was "find the hidden
# rectangle", which the stego stamp already does better. This one tests
# reading a credential and tuning a decrypt, which is the thing the page is
# actually about.
#
# What the player establishes rather than being handed:
#
#   1. the ALGORITHM — read off the block's digest shape and glyph alphabet,
#      free, before any ⏱ is spent (CIPHER_GRID_BASE below);
#   2. whether it is VIABLE AT ALL — bcrypt is identifiable and uncrackable,
#      so the only winning move is not to open it;
#   3. the PASSWORD's own strength — read off the plaintext that comes into
#      focus as the dial approaches true.
#
# Only STAGE 1 costs ⏱, at the tool's ordinary base cost (so inflation and the
# Hashcrack Optimizer both still apply). The dial is free to turn: the spend
# decision is "is this credential worth opening", made once, up front.

# ── Block geometry, per encryption tier ───────────────────────────────────
# (cols, rows) at day 1. The block's shape is the player-facing tell, so these
# must stay visibly distinct — collapsing two of them silently deletes the
# free read this whole feature is built on. bcrypt is widest on purpose: the
# most expensive-looking block is the one you should never pay to open.
CIPHER_GRID_BASE: dict[str, tuple[int, int]] = {
    "weak":   (32, 4),    # MD5     — 32 hex
    "medium": (40, 6),    # SHA256  — 64 hex
    "strong": (52, 8),    # bcrypt  — $2b$12$…
}
# Growth is gentle and asymmetric — area is what makes a block harder to read,
# and growing both dimensions every day compounds fast.
CIPHER_GRID_GROWTH_COLS_PER_DAY = 1   # extra columns per day beyond day 1
CIPHER_GRID_GROWTH_ROWS_PERIOD  = 4   # +1 row every N days beyond day 1
CIPHER_GRID_MAX = (50, 10)            # hard cap (cols, rows) so it never overflows

# The literal prefix bcrypt stamps into the first cells of the block's top row.
# Structural evidence, not a label: it is part of the ciphertext the player is
# looking at, exactly as the $2b$ prefix is part of a real bcrypt hash.
CIPHER_BCRYPT_PREFIX = "$2b$12$"

# The character that separates repeats of the password when the block decrypts.
# The plaintext is TILED across the whole block rather than sitting in one run:
# partial alignment scrambles a different subset of cells in each repeat, so a
# player who is close can read the password by consensus across rows. That is
# what makes the last few dial steps satisfying instead of fiddly.
CIPHER_TILE_SEPARATOR = "·"

# ── Stage 1: the decryption windows ───────────────────────────────────────
# One window per algorithm family. Selecting the one that matches the
# candidate's digest engages the decrypt; any other choice wastes the spend.
# Keys are the tier names used by CIPHER_GRID_BASE and password_strength().
CIPHER_WINDOWS: tuple[tuple[str, str, str], ...] = (
    # (tier key, display label, the digest shape it is built for)
    ("weak",   "MD5",     "32-hex digest"),
    ("medium", "SHA-256", "64-hex digest"),
    ("strong", "bcrypt",  "$2b$ key-stretched"),
)

# ── Stage 2: the alignment pad (two axes) ─────────────────────────────────
# The decrypt has the right family but the wrong derived key. That key is a
# COORDINATE, not a scalar: the player walks an (x, y) pad with the arrow keys
# until the block resolves. Per tier: how far each axis spans, and how near
# the true point they must get before ANY cell resolves.
#
# Why two axes rather than one dial. A single dial can be bisected by feel —
# spin, glance, spin — so a player could solve it without ever really reading
# the block. Two axes have no such shortcut: the only usable signal is the
# ciphertext sharpening as they close in, which is what this stage was always
# meant to be about. It also gives the step budget below something to measure.
#
# ERROR IS MANHATTAN — |dx| + |dy| — and that is load-bearing. Under a
# Chebyshev max() metric a player at (dx=1, dy=9) sees NOTHING change when
# they press left or right, because the larger axis swallows the smaller one,
# and a control that ignores half its inputs reads as broken. Manhattan moves
# the error by exactly one on every arrow press, so every keypress answers the
# question the player just asked: warmer, or colder.
# Pads are deliberately WIDER THAN TALL. Two reasons, both practical: a
# terminal cell is about twice as tall as it is wide, so a 29×9 pad reads as
# roughly square on screen; and the pad is drawn at one character per position
# directly under a block that is already up to ten rows deep, so height is the
# scarce dimension. Squaring these off would push the pad off the panel.
CIPHER_ALIGN_SPAN: dict[str, tuple[int, int]] = {
    "weak":   (20, 6),    # MD5    — 21×7 pad,  max walk 26
    "medium": (28, 8),    # SHA256 — 29×9 pad,  max walk 36
    "strong": (0, 0),     # bcrypt — never reaches stage 2 at all
}
# Each cell gets its own threshold and shows plaintext while the Manhattan
# error clears it, so the DISTRIBUTION of those thresholds is the difficulty
# curve. A cell's threshold is drawn as
#
#     round(max_walk * u ** falloff),   u ~ U(0, 1),  max_walk = span_x + span_y
#
# which makes the share of the block legible at error e exactly
# 1 − (e / max_walk) ** (1 / falloff).
#
# Two properties come out of that shape, and BOTH are the point:
#
#   Every position has signal. Only the single farthest corner of the pad is
#   fully dark. A uniform 0..tolerance draw (the first cut of this) left over
#   half the medium pad at zero resolved cells, so the opening of every search
#   was a blind walk — and a blind walk billed by a step budget is a fee the
#   player had no way to avoid. There is now always a gradient to climb.
#
#   The gradient is STEEPEST at the end. With falloff > 1 the curve is convex:
#   the last few steps each flip a large share of the block, while steps out at
#   the rim barely move it. That is the right way round — it is the fine-tune
#   that is supposed to feel precise, not the approach.
#
# Raising falloff darkens the rim without touching the endgame; 1.0 would make
# the reveal linear in distance and the last step no more informative than the
# first.
CIPHER_ALIGN_FALLOFF: dict[str, float] = {
    "weak":   2.0,   # MD5    — generous; signal well out toward the rim
    "medium": 2.6,   # SHA256 — dimmer at distance, same sharp endgame
    "strong": 0.0,   # bcrypt — never reaches stage 2 at all
}

# ── Stage 2: the step budget ──────────────────────────────────────────────
# Walking the pad is free for the first CIPHER_DIAL_FREE_STEPS presses. After
# that every CIPHER_DIAL_OVERAGE_BLOCK further steps costs
# CIPHER_DIAL_OVERAGE_COST ⏱.
#
# The point is NOT to tax stage 2. A player who reads the block and walks more
# or less straight at it finishes inside the free allowance and pays nothing,
# every time. The budget exists so that flailing has a price — it turns "sweep
# the whole pad and watch for sparkle" from a viable strategy into an
# expensive one, which is what makes reading the block worth doing.
#
# Free steps must therefore stay comfortably above the worst-case DIRECT walk,
# or a player who did everything right still gets billed for the pad's size.
# Since the cursor starts at the CENTRE, that worst case is the distance from
# the middle to the farthest corner — 18 on the largest pad, half what a corner
# start would cost. See CipherBlockData.worst_direct_walk and
# test_a_direct_walk_is_always_free, which measures it rather than assuming it.
#
# RETUNED 45/10 -> 28/8 when the start moved to the centre. Halving the
# distances halved the step counts, and at the old numbers the fee had gone
# nearly inert: a careless player paid nothing 99% of the time, so the budget
# was no longer pricing anything. 28/8 reproduces the profile the 45/10 pair
# had from a corner, which is the balance that was actually wanted.
#
# Calibrated against simulated players reading the block (sim_pad.py):
#
#   clean coordinate descent   median  9 steps   pays nothing 100% of runs
#   the same, with human slip  median  9 steps   pays nothing 100% of runs
#   careless hill-climber      median 18 steps   pays nothing  77%, mean 0.3 ⏱
#   near-random wandering      median 35 steps   pays nothing  40%, median 1 ⏱
#
# The clean profile's worst observed run is 18 steps against 28 free, so a
# player who reads the block is never billed, with 55% headroom. Against a
# day-3 budget near 68 ⏱ the wanderer's couple of ⏱ is a nudge, which is the
# intent — raise OVERAGE_COST and it becomes a punishment for being bad at the
# minigame rather than a reason to read.
CIPHER_DIAL_FREE_STEPS    = 28
CIPHER_DIAL_OVERAGE_BLOCK = 8    # further steps per charge
CIPHER_DIAL_OVERAGE_COST  = 1    # ⏱ per block

# ── Credential HUD hint box ───────────────────────────────────────────────
# Half-width of the BOX the Credential HUD upgrade marks around the true
# coordinate, as a FRACTION of each axis's span (minimum one position).
#
# A fraction rather than a flat number of positions, because the two axes are
# very different lengths. A flat half-width of 3 — the first cut of this — was
# a real hint on a 28-wide X axis and covered the ENTIRE 6-tall Y axis, so the
# upgrade silently degraded into an X-only hint and the player got Y for free.
# Scaling per axis keeps the box the same shape relative to the pad whatever
# CIPHER_ALIGN_SPAN is retuned to.
#
# Same stance as STEGO_HINT_BUFFER (#54): it narrows the search, it never
# answers it, and the BASE TIER MARKS NOTHING. At 0.18 the box covers roughly
# an eighth to a fifth of the pad — worth 35 HD$, still several steps of real
# searching. Push it below about 0.05 and it becomes the answer; above about
# 0.35 and it stops narrowing anything.
CIPHER_HINT_FRACTION = 0.18

# ─── Day-cycle pacing ────────────────────────────────────────────────────────

CINEMATIC_CHAT             = False
CHAT_LINE_DELAY            = 0.04

# ─── Verdict reveal window ───────────────────────────────────────────────────
#
# A short beat between "the player delivered a verdict" and "the player moves
# on", in which three feedback channels fire at once:
#
#   1. the candidate reacts in the chat panel, in the voice they have been
#      using all along, to what the player just did to them;
#   2. the Candidate-page panels pulse green (verdict matched ground truth) or
#      red (it did not);
#   3. the evidence board grades the calls the player actually made.
#
# The window is deliberately SKIPPABLE (see IntakeScreen._begin_verdict_reveal):
# NEXT unlocks the instant the verdict lands, so a player who already knows the
# answer never waits on an animation. The pulse is what gets interrupted; the
# chat reaction and the graded board persist until the next candidate loads,
# because those are things a player reads rather than watches.
#
# Set VERDICT_REVEAL_ENABLED = False to switch the whole beat off — verdicts
# then behave exactly as they did before this feature.
VERDICT_REVEAL_ENABLED        = True
VERDICT_REVEAL_DURATION       = 3.0    # seconds the border pulse runs
VERDICT_REVEAL_PULSE_INTERVAL = 0.22   # seconds between bright/dim swaps

# ─── Screen transitions (glitch) ─────────────────────────────────────────────
#
# Every FULL-SCREEN change (intro → briefing → shift → end of day → between-day
# menu → next briefing, plus game over / campaign end) is covered by an
# animated CRT signal-loss effect instead of cutting straight over. Page
# switches WITHIN the shift (1-5) and the modal overlays (rules, evidence
# board, credit reveal) are untouched — those happen dozens of times a shift
# and a lock-out there would just be friction.
#
# The window is two halves (see HackDoxApp._transition): the first covers the
# outgoing screen and ramps up to full coverage, the swap happens underneath
# at the peak where nothing is visible, and the second decays back to clear
# over the incoming screen. Input is dead for the whole duration — that is the
# point of the beat, so a keystroke meant for the old page cannot land on the
# new one.
#
# Set TRANSITION_ENABLED = False to switch it off: screen changes then cut
# instantly, exactly as they did before the feature.
TRANSITION_ENABLED = True
TRANSITION_DURATION = 0.75      # seconds, total across both halves
TRANSITION_SWAP_AT = 0.5       # fraction of the duration spent over the OLD screen
TRANSITION_FRAME_INTERVAL = 0.05   # seconds between frames (~20fps)

# Look. Intensity drives how MANY terminal rows a frame paints over, because
# an unpainted row is the only way the screen underneath shows through (see
# widgets/glitch.py).
TRANSITION_START_INTENSITY = 0.35  # first frame — a hard hit, not a fade-in
TRANSITION_FULL_COVER_AT = 0.90    # intensity at which every row is covered
TRANSITION_MAX_BANDS = 7           # tear bands at peak intensity
TRANSITION_JITTER = 0.12           # per-frame flicker around the ramp

# Keys that still work while a transition is on screen. Quitting must never be
# blocked by an animation.
TRANSITION_PASSTHROUGH_KEYS = ("ctrl+c", "ctrl+q")

# ─── Damage glitch (wrong admit) ─────────────────────────────────────────────
#
# The same signal-loss effect, fired in place over the live page for a brief
# moment after an admit that DAMAGES SITE HEALTH — the site itself glitching
# as something gets inside it. Scaled by the size of the hit, so the numbers
# the player never sees mid-shift (health lands in one batch at end of day)
# are still felt at the moment they earn them:
#
#   the_incompatible  −2   a couple of torn rows, easy to miss
#   clumsy_cutie      −4   noticeable
#   dark_web          −8   heavy — note this one is CORRECT by the rules
#   bad_actor        −10   heavier
#   sneaky_bugger    −12   briefly swallows the screen
#
# Driven off the verdict's recorded site_health_delta rather than a list of
# archetypes, which is why a correct denial never fires it (health untouched)
# and admitting the White Hat never does either (+1: rules-wrong, but the
# site is better for it). The signal is damage, not disapproval.
#
# Unlike a screen transition this NEVER blocks input: the rows sit on their own
# CSS layer over the live page, and NEXT stays enabled throughout (the verdict
# window's skippability is a locked design decision — see VERDICT_REVEAL_*).
DAMAGE_GLITCH_ENABLED = True
DAMAGE_GLITCH_MIN_DURATION = 0.30   # seconds, at the smallest hit
DAMAGE_GLITCH_MAX_DURATION = 0.90   # seconds, at the worst hit in the table
DAMAGE_GLITCH_MIN_PEAK = 0.10       # opening intensity, smallest hit
DAMAGE_GLITCH_MAX_PEAK = 0.95       # opening intensity, worst hit
DAMAGE_GLITCH_CURVE = 1.6           # >1 keeps the low end genuinely subtle
DAMAGE_GLITCH_RE_HIT_ABOVE = 0.55   # peaks above this stutter a second time
DAMAGE_GLITCH_FRAME_INTERVAL = 0.05 # seconds between frames (~20fps)

# Colour bias — the burst says WHO got in, not just how badly. Each archetype
# tints the static toward its own hue, all of them drawn from the palette the
# rest of the game already speaks (severity yellow/orange/red, Overseer violet,
# terminal green) so the burst never introduces a colour the player has not
# been taught to read:
#
#   the_incompatible  violet   the odd one out — a policy mismatch, not malice
#   clumsy_cutie      yellow   the minor-severity hue: sloppiness, not intent
#   dark_web          green    the "everything checks out" colour turned against
#                              the player — this admit WAS correct by the rules
#   bad_actor         red      critical severity, the loudest thing on screen
#   sneaky_bugger     white    no colour at all: clinical, surgical, the worst
#
# Only archetypes that can damage Site Health ever show one (the rest never
# fire the burst). Change a hue here and the whole effect follows.
ARCHETYPE_GLITCH_TINT: dict[str, str] = {
    "the_incompatible": "#c084fc",
    "clumsy_cutie":     "#ffd93d",
    "dark_web":         "#00ff9f",
    "bad_actor":        "#ff5470",
    "sneaky_bugger":    "#e8f0f8",
}
DAMAGE_GLITCH_TINT_DEFAULT = "#ff5470"  # an archetype with no entry of its own
DAMAGE_GLITCH_TINT_BIAS = 0.7           # share of the palette the hue takes over
                                        # (1.0 is a flat colour wash — it stops
                                        # reading as a broken signal)

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


# ─── Dark Web chat escalation (#39) ──────────────────────────────────────────
#
# Band boundaries for candidate_gen._dark_web_chat_pool. Deliberately its own
# schedule, not the difficulty bands above (medium runs 6-12) — this is a
# narrative escalation curve for one archetype's voice, not a detection-
# complexity lever, and the two happen to diverge past day 12.
DARK_WEB_CHAT_BAND_LAST_EARLY = 9   # days 6-9
DARK_WEB_CHAT_BAND_LAST_MID   = 15  # days 10-15; 16-20 is LATE


# ─── Overseer-Variable rule flips (#35 / #36) ────────────────────────────────
#
# How many days an `overseer_variable` rule holds its current severity before
# it may swing again. Bigger = calmer rulebook and rarer briefing asides.
# Each rule's phase is staggered off its own id, so raising this does not make
# every rule flip on the same morning — see content_loader.mutate_variable_rules.
RULE_FLIP_PERIOD = 3


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
# Batch-3 task #4e: roughly halved from the pre-batch-3 values (was
# 80/100/120/150/180/210/240) — Log Analyzer HUD's highlighting is now a
# REAL gate (previously it did nothing once the tool was run, see
# _lw_render's docstring), so the ungated log needs to still be readable by
# hand at the volumes a Day-1/2 player is actually facing.
LW_ENTRIES_BY_DAY: dict[int, int] = {
    1:  40,    # Day 1  — quiet intro shift, readable without the upgrade
    2:  50,
    3:  60,
    4:  75,
    5:  90,
    6: 105,
    7: 120,
}
LW_ENTRIES_DEFAULT      = 100   # fallback for days not in the dict
LW_ENTRIES_SCALE_FACTOR = 1.15  # multiplier applied per day beyond the last key
LW_ENTRIES_MIN          = 10    # floor — never fewer noise rows than this

# Batch-3 task #5: fraction of noise AUTH_OK rows (unrelated background
# accounts) that log in from the same external-city IP pool violations use
# (tools_bridge._LW_CITIES), instead of the plain internal noise IPs. Before
# this, ONLY a violation (or the candidate's own legit foreign login) ever
# carried an exotic city tag — so "any foreign city in the log" was itself
# the tell, with no need to read anything else. At this fraction, foreign
# cities are common background noise and the player has to correlate
# account + pattern, not just scan for non-US/non-internal city names.
LW_NOISE_EXTERNAL_CITY_FRACTION = 0.3

# ─── Log generation timing (batch-3 task #7) ─────────────────────────────────
#
# Every (min, max) pair below feeds an rng.randint(*pair) somewhere in
# tools_bridge's Logwatch/Hashcrack log builders. These were bare literals
# scattered through _lw_candidate_entries/_hc_candidate_entries before this —
# pulled out so day-length, burst size, and pacing can all be retuned from
# here without touching generation code. Values are exactly what was already
# hardcoded (a pure extraction, not a rebalance) — safe to retune freely.
#
# All times are seconds-since-midnight on the shared log's single day.

# Logwatch — normal/legit candidate activity window and pacing
LW_WORKDAY_WINDOW        = (29100, 41400)   # 08:05–11:30: when a candidate's day starts
                                            # (2026-09-19: was 7am–3pm; must start inside
                                            # LW_SHIFT_START for the Activity Report)
LW_NORMAL_LOGIN_COUNT    = (2, 3)           # # of plain AUTH_OK rows with no violation
LW_NORMAL_LOGIN_GAP      = (1800, 7200)     # seconds between those logins
LW_CLEAN_ACTIVITY_COUNT  = (3, 5)           # rows for a candidate with NO violations at all
LW_CLEAN_ACTIVITY_GAP    = (900, 3600)
LW_CLEAN_ACTIVITY_EVENTS: list[str] = ["AUTH_OK", "FILE_READ", "AUTH_OK", "SESSION_END"]

# Logwatch — per-violation generation knobs
LW_BRUTE_BURST_SIZE      = (4, 7)           # AUTH_FAIL rows before the AUTH_OK
LW_BRUTE_COOLDOWN        = (1800, 3600)     # gap after a resolved brute-force
LW_STUFFING_SPRAY_SIZE   = 5                # distinct OTHER accounts sprayed (capped to pool size)
LW_STUFFING_COOLDOWN     = (1800, 3600)
LW_TRAVEL_GAP            = (2100, 5400)     # 35–90 min between the two impossible logins
LW_TRAVEL_COOLDOWN       = (1800, 3600)
LW_INSIDER_WINDOW        = (82800, 3600)    # (start-of-window, span) — 11pm–midnight
LW_INSIDER_STEP1_GAP     = (1, 5)           # FILE_READ → SUDO_EXEC
LW_INSIDER_STEP2_GAP     = (1, 10)          # SUDO_EXEC → second FILE_READ
LW_AFTERHOURS_WINDOW     = (79200, 9000)    # (start-of-window, span) — ~10pm onward
LW_AFTERHOURS_GAP        = (120, 900)       # AUTH_OK → FILE_READ
LW_SLOW_FIRST_TS         = (3600, 10800)    # first low-and-slow AUTH_FAIL
LW_SLOW_BURST_SIZE       = (3, 4)           # scattered AUTH_FAIL count
LW_SLOW_GAP              = (9000, 16000)    # gap between each scattered attempt

# ─── Logwatch Activity Report (2026-09-19 overhaul) ─────────────────────────
#
# The free tier of the Logwatch page is an aggregate Activity Report computed
# FROM the day log (tools_bridge / core/logwatch_report.py) — never from
# ground truth, so the report and the log can never disagree. These knobs
# define what the report calls normal.
#
# TUNING CHEAT-SHEET (Nick, 2026-09-19 — safe to play with; the tier tests in
# tests/test_logwatch_report.py fail loudly if a retune breaks the design):
#   "the attack alert fires too easily / not enough" -> LW_BURST_ALERT, LW_BURST_WINDOW
#       (must stay <= the smallest burst: LW_BRUTE_BURST_SIZE[0] and
#        LW_STUFFING_SPRAY_SIZE, and above what low-and-slow can reach)
#   "what counts as off-hours"         -> LW_SHIFT_START / LW_SHIFT_END
#   "which bars read as out of range"  -> the middle number in LW_PROFILE_METRICS
#   "a failed login is too telling"    -> LW_BENIGN_TYPO_CHANCE
#   "the report wraps on my terminal"  -> LW_REPORT_WIDTH / *_COMPACT layout knobs
#   "honest travel too rare / common"  -> LW_LEGIT_TRIP_CHANCE (a roll, ~half land)
#   "when is travel impossible"        -> LW_MAX_FEASIBLE_KMH (+ LW_TRAVEL_MIN_KM)
#   "turn the origin map off / resize" -> LW_MAP_ENABLED / LW_MAP_MIN_WIDTH / _MAX_WIDTH

# The one standard shift every candidate claims. Off-hours = candidate's own
# successful activity outside [start, end). Seconds since midnight.
LW_SHIFT_START           = 8 * 3600         # 08:00
LW_SHIFT_END             = 18 * 3600        # 18:00
LW_SHIFT_END_MARGIN      = 900              # daytime activity is compressed to end this early

# Attack alert: this many LINKED auth failures (on the account, or from an
# external IP that later logged in as it) inside one window trips the
# report's unclassified "authentication anomaly" alert. Low-and-slow is built
# to never reach it.
LW_BURST_WINDOW          = 600              # seconds
LW_BURST_ALERT           = 4

# Travel feasibility (2026-09-20). Two consecutive logins from CLEAN origins
# in different cities are a travel pair; the report calls it EVIDENCE only
# when the implied speed beats this. Real trips (below) are noise against the
# "two cities = deny" reflex, so this line is what separates them.
LW_MAX_FEASIBLE_KMH      = 900              # airliner cruise + a little slack

# Honest business travel: this share of candidates WITHOUT planted impossible
# travel actually fly somewhere during the shift and log in from there. The
# destination is chosen so the trip is comfortably feasible — the gap is at
# least LW_TRIP_TIME_MARGIN x the flight time it needs.
# NOTE: this is the ROLL, not the realised rate — a candidate whose day is
# already full (or who works after hours, see the generator) can't fit a trip.
# 0.30 here lands at roughly 15% of all candidates actually travelling.
LW_LEGIT_TRIP_CHANCE     = 0.30
LW_TRIP_CRUISE_KMH       = 750              # how fast the flight itself is
LW_TRIP_OVERHEAD_H       = 1.5              # airports, boarding, transfers
LW_TRIP_TIME_MARGIN      = 1.3
LW_TRIP_ARRIVAL_LOGINS   = (1, 2)           # logins from the destination city
LW_TRIP_ARRIVAL_GAP      = (600, 3600)      # seconds between those logins
LW_TRIP_MAX_KM           = 6000             # a day trip's realistic reach (the
                                            # flight has to fit inside the shift)

# Planted IMPOSSIBLE_TRAVEL picks two cities at least this far apart, so the
# LW_TRAVEL_GAP between them is always well past LW_MAX_FEASIBLE_KMH — the
# violation can never accidentally be a feasible hop.
LW_TRAVEL_MIN_KM         = 3000

# An origin with at least this many linked failures FROM its IP is treated as
# hostile (an attacker's foothold), not the user's own travel, and is left out
# of travel pairs. 2, not 1, so a single benign typo never disqualifies the
# user's real location.
LW_HOSTILE_ORIGIN_FAILS  = 2

# Honest noise: chance any candidate fumbles one password during the shift,
# so "has a failed login" is never on its own a tell.
LW_BENIGN_TYPO_CHANCE    = 0.3
LW_BENIGN_TYPO_LEAD      = (8, 90)          # seconds before the first login it lands

# Layout of the rendered report (characters). The centre column is ~40% of
# the screen; 56 fits a 150-col terminal without wrapping.
LW_REPORT_WIDTH          = 56
LW_BAR_WIDTH             = 20
LW_TIMELINE_BIN_MIN      = 30               # minutes per timeline cell (48 cells/day)
# Compact layout, used automatically when the report column is narrower than
# LW_REPORT_WIDTH (small terminals): shorter bars, hour-wide timeline cells.
LW_BAR_WIDTH_COMPACT     = 12
LW_TIMELINE_BIN_MIN_COMPACT = 60            # 24 cells/day

# ASCII world map of login origins (core/ascii_map.py, 2026-09-20). Drawn
# whenever the report column is at least LW_MAP_MIN_WIDTH wide (it re-draws
# itself at the column's width — narrower = coarser, never broken); below
# that the plain origins list is shown instead.
LW_MAP_ENABLED           = True
LW_MAP_MIN_WIDTH         = 38
LW_MAP_MAX_WIDTH         = 56

# Activity Profile bars, top to bottom: metric -> (label, normal ceiling,
# bar scale max). The ceiling is drawn as a │ tick; a value past it is "out
# of range" (and turns amber with the Log Analyzer HUD). Reorder freely; the
# metric keys are fixed (logwatch_report.LogwatchReport.metric).
LW_PROFILE_METRICS: dict[str, tuple[str, int, int]] = {
    "logins":     ("Logins",        4, 8),
    "failures":   ("Auth failures", 1, 8),
    "origins":    ("Origins",       1, 4),
    "files":      ("File access",   5, 10),
    "privileged": ("Privileged",    0, 4),
    "off_hours":  ("Off-hours",     0, 6),
}

# Logwatch — noise (unrelated background accounts)
LW_NOISE_TIME_WINDOW     = (21600, 86399)
# Weighted pool an unrelated noise row's event type is drawn from — repeat an
# entry to raise its odds (AUTH_OK appears 3x here → ~50% of noise rows).
LW_NOISE_EVENT_WEIGHTS: list[str] = [
    "AUTH_OK", "AUTH_OK", "AUTH_FAIL", "FILE_READ", "SESSION_END", "AUTH_OK",
]

# Credential rows in the Logwatch log (relocated 2026-09-14)
#
# The cipher-block rework deleted the Hashcrack page's own shared credential
# audit log, and with it every HC_* knob that paced it: HC_ENTRIES_BY_DAY and
# friends (volume), HC_WORKDAY_WINDOW / HC_NORMAL_LOGIN_GAP /
# HC_HASH_SUBMIT_GAP (timing), HC_STUFFING_* (a burst Logwatch was already
# generating for itself via LW_BRUTE_BURST_SIZE / LW_STUFFING_SPRAY_SIZE
# above), and HC_NOISE_* (noise rows that no longer exist).
#
# The last survivor, HC_BREACH_ROW_GAP, went on 2026-09-19 with the
# BREACH_MATCH rows it paced (breach hits are no longer Logwatch's business).

# ─── Upgrades (issue #23) ────────────────────────────────────────────────────
#
# Upgrade IDs are plain strings so new upgrades can be added without touching
# game-state serialisation. The player's unlocked set lives in GameState.upgrades.
# All upgrades are permanent, bought in the between-day shop with HackDollar$,
# and are strict no-ops until purchased.
#
# (Session Grouper upgrade removed — it reordered the Logwatch log into
# per-session blocks but added no detection power, just an alternate layout,
# so it wasn't worth the shop slot or the maintenance cost of a near-duplicate
# renderer. See tools_bridge._lw_render, which no longer branches on it.)

# Auto-highlight upgrades — surface signals the engine already computes.
UPGRADE_LOG_HIGHLIGHT    = "log_highlight"      # Logwatch: ▸ marks + out-of-range bars (never names)
UPGRADE_LOG_TRIAGE       = "log_triage_notes"   # Logwatch: unlocks the report's ANALYST NOTES
UPGRADE_HASH_HIGHLIGHT   = "hash_highlight"     # Hashcrack: mark the region of the
                                                # alignment pad holding the true key
UPGRADE_EMAIL_APPROVED   = "email_approved_highlight"    # dossier: green trusted domains
UPGRADE_EMAIL_PROHIBITED = "email_prohibited_highlight"  # dossier: red disposable domains
UPGRADE_AFFIL_APPROVED   = "affil_approved_highlight"    # dossier: green trusted orgs
UPGRADE_AFFIL_PROHIBITED = "affil_prohibited_highlight"  # dossier: red threat-actor orgs
UPGRADE_STEGO_TINT       = "stego_area_tint"    # Stegotool: stronger area-of-interest tint
UPGRADE_CHAT_HOSTILE     = "chat_hostile_highlight"      # chat: mark hostile lines
UPGRADE_CRYPTO_ID        = "crypto_id_highlight"   # hashcrack: auto-label the cipher
                                                   # block's tier (MD5/SHA256/bcrypt)
UPGRADE_BREACH_AUTO      = "breach_auto_detect"    # ghostscan: confirm BREACH_HIT on the free base run
UPGRADE_HC_VERDICT       = "hashcrack_verdict_highlight"  # hashcrack: label a crack's strength verdict
UPGRADE_STEGO_RGB_COLOR  = "stego_rgb_color"       # stegotool: colour-code channel entropy readout

# Economy upgrades -- reduce a tool's cost by TOOLCOST_REDUCTION (floor 1).
# IDs follow "toolcost_<tool>" so _charge() can key off the tool name directly.
UPGRADE_TOOLCOST_GHOSTSCAN = "toolcost_ghostscan"
UPGRADE_TOOLCOST_LOGWATCH  = "toolcost_logwatch"
UPGRADE_TOOLCOST_HASHCRACK = "toolcost_hashcrack"
UPGRADE_TOOLCOST_STEGOTOOL = "toolcost_stegotool"   # reduces the stego filter cost
TOOLCOST_REDUCTION = 2   # ⏱ knocked off the base cost when owned

# Shop catalog: (upgrade_id, label, HD$ price, description).
# The between-day menu renders this list; effects key off GameState.upgrades.
UPGRADE_CATALOG: list[tuple[str, str, int, str]] = [
    (UPGRADE_CHAT_HOSTILE,     "Sentiment Scanner",     20, "auto-mark hostile text in candidate chat"),
    (UPGRADE_EMAIL_APPROVED,   "Domain Whitelist HUD",  20, "auto-highlight approved email domains on the dossier"),
    (UPGRADE_EMAIL_PROHIBITED, "Domain Blacklist HUD",  25, "auto-highlight prohibited email domains on the dossier"),
    (UPGRADE_AFFIL_APPROVED,   "Org Whitelist HUD",     20, "auto-highlight approved affiliations on the dossier"),
    (UPGRADE_AFFIL_PROHIBITED, "Org Blacklist HUD",     25, "auto-highlight prohibited affiliations on the dossier"),
    (UPGRADE_STEGO_TINT,       "Spectral Lens",         30, "stronger blue tint over stego areas of interest"),
    (UPGRADE_HASH_HIGHLIGHT,   "Credential HUD",        35, "mark the region of the alignment pad the true key sits in"),
    (UPGRADE_LOG_HIGHLIGHT,    "Log Analyzer HUD",      35, "mark anomalous auth-log rows (▸) and out-of-range report bars — points, never names"),
    (UPGRADE_LOG_TRIAGE,       "Threat Triage HUD",     30, "unlock the Logwatch report's Analyst Notes — attack bursts, source & travel anomalies, off-shift work"),
    (UPGRADE_TOOLCOST_GHOSTSCAN, "Ghostscan Optimizer", 45, f"ghostscan costs {TOOLCOST_REDUCTION} ⏱ less"),
    (UPGRADE_TOOLCOST_LOGWATCH,  "Logwatch Optimizer",  40, f"logwatch costs {TOOLCOST_REDUCTION} ⏱ less"),
    (UPGRADE_TOOLCOST_HASHCRACK, "Hashcrack Optimizer", 35, f"hashcrack costs {TOOLCOST_REDUCTION} ⏱ less"),
    (UPGRADE_TOOLCOST_STEGOTOOL, "Stego Optimizer",     30, f"stego filter costs {TOOLCOST_REDUCTION} ⏱ less"),
    (UPGRADE_CRYPTO_ID,        "Cipher ID HUD",       20, "auto-label the cipher block's encryption tier (MD5/SHA256/bcrypt)"),
    (UPGRADE_BREACH_AUTO,      "Breach Feed Sync",     30, "confirm breach-corpus hits on the free base Ghostscan run, not just the filter"),
    (UPGRADE_HC_VERDICT,       "Crack Verdict Analyzer", 20, "label a recovered password's strength verdict, not just the plaintext"),
    (UPGRADE_STEGO_RGB_COLOR,  "Channel Colorizer",    25, "colour-code the RGB channel entropy readout by severity"),
]

# Sub-category (by tool page) each upgrade belongs to, for shop-UI grouping.
# Colors intentionally mirror rules_content.GROUP_ACCENT's DOSSIER/OSINT/
# CREDENTIAL/FORENSICS/STEGO tool colors, so an upgrade's category color
# matches that tool's color everywhere else in the UI.
UPGRADE_CATEGORY: dict[str, str] = {
    UPGRADE_CHAT_HOSTILE:        "Candidate",
    UPGRADE_EMAIL_APPROVED:      "Candidate",
    UPGRADE_EMAIL_PROHIBITED:    "Candidate",
    UPGRADE_AFFIL_APPROVED:      "Candidate",
    UPGRADE_AFFIL_PROHIBITED:    "Candidate",
    UPGRADE_STEGO_TINT:          "Stegotool",
    UPGRADE_HASH_HIGHLIGHT:      "Hashcrack",
    UPGRADE_LOG_HIGHLIGHT:       "Logwatch",
    UPGRADE_LOG_TRIAGE:          "Logwatch",
    UPGRADE_TOOLCOST_GHOSTSCAN:  "Ghostscan",
    UPGRADE_TOOLCOST_LOGWATCH:   "Logwatch",
    UPGRADE_TOOLCOST_HASHCRACK:  "Hashcrack",
    UPGRADE_TOOLCOST_STEGOTOOL:  "Stegotool",
    UPGRADE_CRYPTO_ID:           "Candidate",
    UPGRADE_BREACH_AUTO:         "Ghostscan",
    UPGRADE_HC_VERDICT:          "Hashcrack",
    UPGRADE_STEGO_RGB_COLOR:     "Stegotool",
}
# Display order for the shop's per-tool sub-headers — mirrors the page/key
# order (1-5, dossier/chat first) so the grouping reads the same way the
# tool tabs do.
UPGRADE_CATEGORY_ORDER: list[str] = [
    "Candidate", "Ghostscan", "Hashcrack", "Logwatch", "Stegotool",
]
UPGRADE_CATEGORY_ACCENT: dict[str, str] = {
    "Candidate":  "#7dd3c0",   # matches GROUP_ACCENT["DOSSIER"]
    "Ghostscan":  "#6ad4ff",   # matches GROUP_ACCENT["OSINT"]
    "Hashcrack":  "#c084fc",   # matches GROUP_ACCENT["CREDENTIAL"]
    "Logwatch":   "#ffb454",   # matches GROUP_ACCENT["FORENSICS"]
    "Stegotool":  "#ff8cc8",   # matches GROUP_ACCENT["STEGO"]
}

# Non-upgrade shop items (consumables / capacity).
SHOP_PRICE_CREDIT       = 100   # HD$ per HackDox Credit (up to HACKDOX_CREDIT_MAX)
SHOP_PRICE_CAPACITY     = 100   # HD$ per ⏱-capacity increase
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

    # ── Logwatch auth log panel (page 4 only, 2026-09-19) ─────
    # Jump between the target account's rows in the (unsealed) auth log.
    # Textual key names; only read while the command buffer is empty.
    "log_prev_row":     "left_square_bracket",
    "log_next_row":     "right_square_bracket",

    # ── Hashcrack decrypt mode (page 3 only) ──────────────────
    # Deliberately the SAME physical key as stamp mode above: one "engage this
    # page's minigame" gesture, dispatched on which page you are standing on.
    # They are separate entries rather than one shared name because the two
    # modes have different costs, different surfaces and different exit
    # behaviour — collapsing them into one binding would make rebinding either
    # silently rebind the other.
    # Decrypt mode runs in two stages: first left/right pick a decryption
    # window and Enter buys it, then all four arrows walk the alignment pad —
    # left/right on X, up/down on Y — with the block sharpening live. Escape
    # (or this key again) exits from either stage.
    "decrypt_mode":     "x",

    # ── Misc ────────────────────────────────
    # Toggle the editable Evidence Board on every page. On tool pages (2-5)
    # it slides in on the left so the tool data on the right stays visible.
    # On the Candidate page (1) it swaps in for the read-only summary board.
    "toggle_evidence":  "tab",
    "toggle_debug":     "grave_accent",
    "help":             "question_mark",
    "quit":             "q",
}

# ─── Audio ────────────────────────────────────────────────────────────────────
#
# Textual has no built-in sound — SFX and (future) background music are
# played independently through pygame.mixer (see gameengine/core/audio.py).
# Missing pygame, or no audio device on the host (CI, headless), both
# degrade to silence automatically; none of this is required to run or
# test the game. Volumes are 0.0-1.0 and multiply together (an SFX plays at
# master_volume * sfx_volume).

AUDIO_DIR           = CONTENT_DIR / "audio"
AUDIO_SFX_DIR       = AUDIO_DIR / "sfx"
AUDIO_MUSIC_DIR     = AUDIO_DIR / "music"
# Deliberately NOT part of a campaign save (core/persistence.py) — a volume
# preference should survive starting a new game or switching save slots.
AUDIO_SETTINGS_PATH = SAVES_DIR / "audio_settings.json"

SOUND_ENABLED_DEFAULT = True
DEFAULT_MASTER_VOLUME = 1.0   # overall multiplier on both channels below
DEFAULT_MUSIC_VOLUME  = 0.6   # background/ambient tracks (no trigger uses this yet)
DEFAULT_SFX_VOLUME    = 0.8   # one-shot cues — verdicts, tool runs, UI ticks, etc.
