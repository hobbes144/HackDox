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
# it is not expressible — in ground truth or in the Hashcrack log, which prints
# two BREACH_MATCH rows for it — until at least two databases are unlocked.
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
    "hashcrack":  8,   # extended wordlist + full mutation rules
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

# ─── Hashcrack shared log — volume scaling ───────────────────────────────────
#
# Same shape as LW_ENTRIES_BY_DAY above. Previously a flat max(80, 160 -
# len(candidate_entries)) regardless of day (no day-scaling at all) — batch-3
# task #4d/#7 made it day-scaled and configurable, and — same reasoning as
# LW_ENTRIES_BY_DAY above — started smaller now that Credential HUD's
# highlighting is a real gate instead of a no-op.
HC_ENTRIES_BY_DAY: dict[int, int] = {
    1:  35,
    2:  45,
    3:  55,
    4:  70,
    5:  85,
    6: 100,
    7: 115,
}
HC_ENTRIES_DEFAULT      = 95    # fallback for days not in the dict
HC_ENTRIES_SCALE_FACTOR = 1.15  # multiplier applied per day beyond the last key
HC_ENTRIES_MIN          = 10    # floor — never fewer noise rows than this

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
LW_WORKDAY_WINDOW        = (25200, 54000)   # 7am–3pm: when a candidate's day starts
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

# Logwatch — noise (unrelated background accounts)
LW_NOISE_TIME_WINDOW     = (21600, 86399)
# Weighted pool an unrelated noise row's event type is drawn from — repeat an
# entry to raise its odds (AUTH_OK appears 3x here → ~50% of noise rows).
LW_NOISE_EVENT_WEIGHTS: list[str] = [
    "AUTH_OK", "AUTH_OK", "AUTH_FAIL", "FILE_READ", "SESSION_END", "AUTH_OK",
]

# Hashcrack — normal/legit candidate activity window and pacing
HC_WORKDAY_WINDOW        = (25200, 50400)   # 7am–2pm
HC_NORMAL_LOGIN_GAP      = (30, 120)        # AUTH_OK → hash submit, non-stuffing path
HC_HASH_SUBMIT_GAP       = (5, 30)          # login → HASH_SUBMIT row
HC_BREACH_ROW_GAP        = (5, 20)          # gap between a candidate's breach-match rows

# Hashcrack — credential-stuffing burst (gated on CREDENTIAL_STUFFING itself,
# see #62 in tools_bridge._hc_candidate_entries)
HC_STUFFING_BURST_SIZE   = (3, 6)
HC_STUFFING_COOLDOWN     = (1, 3)           # burst → the AUTH_OK that follows it
HC_STUFFING_POST_GAP     = (10, 60)         # AUTH_OK → hash submit

# Hashcrack — noise (unrelated background accounts)
HC_NOISE_TIME_WINDOW     = (21600, 79200)
HC_NOISE_EVENT_WEIGHTS: list[str] = [
    "AUTH_OK", "AUTH_OK", "AUTH_FAIL", "HASH_SUBMIT",
    "AUTH_OK", "HASH_SUBMIT", "BREACH_MATCH",
]

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
UPGRADE_LOG_HIGHLIGHT    = "log_highlight"      # Logwatch: colour suspicious log lines
UPGRADE_HASH_HIGHLIGHT   = "hash_highlight"     # Hashcrack: colour suspicious audit lines
UPGRADE_EMAIL_APPROVED   = "email_approved_highlight"    # dossier: green trusted domains
UPGRADE_EMAIL_PROHIBITED = "email_prohibited_highlight"  # dossier: red disposable domains
UPGRADE_AFFIL_APPROVED   = "affil_approved_highlight"    # dossier: green trusted orgs
UPGRADE_AFFIL_PROHIBITED = "affil_prohibited_highlight"  # dossier: red threat-actor orgs
UPGRADE_STEGO_TINT       = "stego_area_tint"    # Stegotool: stronger area-of-interest tint
UPGRADE_CHAT_HOSTILE     = "chat_hostile_highlight"      # chat: mark hostile lines
UPGRADE_CRYPTO_ID        = "crypto_id_highlight"   # dossier: auto-label MD5/SHA256/bcrypt chip
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
    (UPGRADE_HASH_HIGHLIGHT,   "Credential HUD",        35, "auto-highlight suspicious lines in the Hashcrack audit log"),
    (UPGRADE_LOG_HIGHLIGHT,    "Log Analyzer HUD",      35, "auto-highlight suspicious lines in the Logwatch day log"),
    (UPGRADE_TOOLCOST_GHOSTSCAN, "Ghostscan Optimizer", 45, f"ghostscan costs {TOOLCOST_REDUCTION} ⏱ less"),
    (UPGRADE_TOOLCOST_LOGWATCH,  "Logwatch Optimizer",  40, f"logwatch costs {TOOLCOST_REDUCTION} ⏱ less"),
    (UPGRADE_TOOLCOST_HASHCRACK, "Hashcrack Optimizer", 35, f"hashcrack costs {TOOLCOST_REDUCTION} ⏱ less"),
    (UPGRADE_TOOLCOST_STEGOTOOL, "Stego Optimizer",     30, f"stego filter costs {TOOLCOST_REDUCTION} ⏱ less"),
    (UPGRADE_CRYPTO_ID,        "Cipher ID HUD",       20, "auto-label the dossier's encryption-strength chip (MD5/SHA256/bcrypt)"),
    (UPGRADE_BREACH_AUTO,      "Breach Feed Sync",     30, "confirm breach-corpus hits on the free base Ghostscan run, not just the filter"),
    (UPGRADE_HC_VERDICT,       "Crack Verdict Analyzer", 20, "label a cracked password's strength verdict, not just the plaintext"),
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
