"""Core data model for HackDox.

All gameplay objects are defined here as dataclasses. Anything that lives
in a save file or moves between subsystems should round-trip through these
types.

See ARCHITECTURE.md §3 for the design rationale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


# ─── Enums ──────────────────────────────────────────────────────────────────


class Archetype(str, Enum):
    """The seven candidate archetypes from the Notion design doc.

    Ground-truth-only: never shown to the player; drives generator behavior
    and scoring.
    """

    OBVIOUS_ADMIT   = "obvious_admit"    # clean, friendly — admit
    DAY_TO_DAY      = "day_to_day"       # minor issues — admit
    DARK_WEB        = "dark_web"         # rules-clean but morally invalid
    CLUMSY_CUTIE    = "clumsy_cutie"     # honest mistakes — deny
    BAD_ACTOR       = "bad_actor"        # obviously hostile — deny
    SNEAKY_BUGGER   = "sneaky_bugger"    # subtle, manipulative — deny
    WHITE_HAT       = "white_hat"        # invalid but heroic — alignment choice
    THE_PROFESSIONAL = "the_professional" # elite affiliation, ghostscan confirms — quick admit
    THE_INCOMPATIBLE = "the_incompatible" # disposable email domain — quick deny


class Verdict(str, Enum):
    ADMIT = "admit"
    DENY  = "deny"


class ToolName(str, Enum):
    """Which surface revealed a given discrepancy."""

    DOSSIER   = "dossier"               # visible without spending currency
    GHOSTSCAN = "ghostscan"
    LOGWATCH  = "logwatch"
    HASHCRACK = "hashcrack"
    STEGOTOOL = "stegotool"


class DiscrepancyKind(str, Enum):
    """Catalog of every type of error the engine can plant on a candidate.

    Adding a new kind requires adding (a) a generator path in
    `candidate_gen.py`, (b) a detection path in the relevant `tools_bridge`
    function, and (c) ideally a rule predicate in `rules_engine.py`.
    """

    # Dossier-level (no tool needed)
    MISSING_PUBLIC_PROFILE = "missing_public_profile"
    HOSTILE_CHAT           = "hostile_chat"
    AFFILIATION_UNVERIFIED = "affiliation_unverified"

    # Ghostscan-revealed
    EMAIL_GITHUB_MISMATCH  = "email_github_mismatch"
    BREACH_HIT             = "breach_hit"
    SOCK_PUPPET_ACCOUNTS   = "sock_puppet_accounts"
    AFFILIATION_MISMATCH   = "affiliation_mismatch"   # claimed elite org doesn't match ghostscan

    # Dossier-level (disposable email — no tool needed)
    DISPOSABLE_EMAIL       = "disposable_email"        # email domain is a known throwaway service

    # Logwatch-revealed
    BRUTE_FORCE_IN_LOG     = "brute_force_in_log"
    IMPOSSIBLE_TRAVEL      = "impossible_travel"
    INSIDER_BEHAVIOR       = "insider_behavior"

    # Hashcrack-revealed
    LEAKED_PASSWORD        = "leaked_password"
    WEAK_CREDENTIAL        = "weak_credential"

    # Stegotool-revealed
    STEGO_PAYLOAD_PRESENT  = "stego_payload_present"
    COVERT_C2_CHANNEL      = "covert_c2_channel"

    # ── v2 additions (2026-06-18) ──────────────────────────────────────
    # Ghostscan-revealed
    BURNER_IDENTITY        = "burner_identity"        # accounts all created within days
    THREAT_FORUM_MATCH     = "threat_forum_match"     # handle on a known threat forum
    TYPOSQUAT_HANDLE       = "typosquat_handle"       # lookalike of a trusted org/person
    # Logwatch-revealed
    CREDENTIAL_STUFFING    = "credential_stuffing"    # one IP, many accounts, few tries each
    AFTER_HOURS_ACCESS     = "after_hours_access"     # activity outside business hours
    LOW_AND_SLOW           = "low_and_slow"           # attack spread thin to evade thresholds
    # Hashcrack-revealed
    CROSS_BREACH_REUSE     = "cross_breach_reuse"     # cracked plaintext recurs across breaches
    UNSALTED_STORAGE       = "unsalted_storage"       # unsalted / plaintext-equivalent storage
    # Stegotool-revealed
    ENCRYPTED_PAYLOAD      = "encrypted_payload"      # XOR/encrypted hidden payload
    # Dossier-level (prompts Logwatch/Stego)
    CLAIMED_IP_MISMATCH    = "claimed_ip_mismatch"    # claimed IP != IP in submitted logs


class Performance(str, Enum):
    """Bucketed end-of-day rating used to select Overseer outro dialogue."""

    EXCELLENT = "excellent"     # quotas met + few false denials
    PASSING   = "passing"       # quotas met
    POOR      = "poor"          # quotas missed but survived
    FAILED    = "failed"        # game-over conditions tripped


Severity = Literal["minor", "major", "critical"]
RuleSeverity = Literal["disqualifying", "weighted"]


# ─── Chat ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ChatLine:
    """One line of one-way candidate dialogue.

    `tag` is a lightweight semantic label (e.g. "intro", "hint:breach",
    "hostile") used both for rendering style and so chat_script generation
    can plant hints near specific discrepancies.
    """

    timestamp: str       # "10:02" — purely cosmetic
    text: str
    tag: str = "neutral"


# ─── Discrepancies ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Discrepancy:
    kind: DiscrepancyKind
    severity: Severity
    revealed_by: ToolName
    description: str


# ─── Dossier ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Dossier:
    """The visible packet shown on the intake screen.

    All fields are what the candidate *claims* — the engine doesn't trust
    them, the player shouldn't either, and the tools may contradict them.

    `commit_email` is the email address actually found in GitHub commit
    metadata. Set by the generator; may differ from the candidate's claimed
    email if EMAIL_GITHUB_MISMATCH is planted.
    """

    claimed_github:        str | None = None
    claimed_breaches:      tuple[str, ...] = ()
    submitted_image_path:  str | None = None
    submitted_hash:        str | None = None   # issue #29: EVERY candidate submits one
    notes:                 str = ""
    commit_email:          str | None = None   # actual GitHub commit author email
    claimed_ip:            str | None = None   # IP the candidate claims to connect from
    # Issue #29 — the plaintext behind submitted_hash. ENGINE-ONLY ground
    # truth: never rendered until Hashcrack cracks it (and never for bcrypt).
    # Encryption strength is derived from the hash shape:
    #   $2b$… bcrypt = STRONG (uncrackable) · 64-hex SHA256 = MEDIUM · 32-hex MD5 = WEAK
    password_plain:        str | None = None


# ─── Ground truth ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GroundTruth:
    """The hidden answer key for a candidate.

    `moral_modifier` is what gives the Dark Web and White Hat archetypes
    their teeth in the scoring matrix — see ARCHITECTURE.md §6.
    """

    correct_verdict: Verdict
    discrepancies: tuple[Discrepancy, ...]
    moral_modifier: int = 0     # +1 White Hat, -1 Dark Web, 0 otherwise


# ─── Candidate ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Candidate:
    """The unit of play. Generated per-slot, evaluated, then archived."""

    id: str
    archetype: Archetype
    display_name: str
    handle: str
    email: str
    photo_seed: int
    claimed_purpose: str
    claimed_affiliation: str
    dossier: Dossier
    chat_script: tuple[ChatLine, ...]
    truth: GroundTruth


# ─── Rules ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Rule:
    """A line in the day's rulebook.

    `predicate` is a string key resolved by `rules_engine.predicate_registry`,
    which keeps Day files authorable as JSON.
    """

    id: str
    text: str
    predicate: str
    severity: RuleSeverity = "disqualifying"


@dataclass(frozen=True)
class RuleEvaluation:
    """Result of evaluating a candidate against a day's rulebook."""

    triggered_disqualifying: tuple[Rule, ...]
    triggered_weighted: tuple[Rule, ...]

    @property
    def any_triggered(self) -> bool:
        return bool(self.triggered_disqualifying or self.triggered_weighted)


# ─── Day ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Quotas:
    """Day-level pass/fail criteria.

    (compute_target removed by issue #27 — ⏱ is a spend-only daily budget
    now, so an end-of-day balance target no longer makes sense.)
    """

    min_correct_admits: int = 2
    max_false_admits: int = 1


@dataclass(frozen=True)
class Day:
    number: int
    title: str
    rules: tuple[Rule, ...]
    candidate_count: int
    archetype_mix: dict[Archetype, int]
    quotas: Quotas
    overseer_intro_key: str
    overseer_outro_keys: dict[Performance, str]


# ─── Day results & game state ───────────────────────────────────────────────


@dataclass(frozen=True)
class CandidateResult:
    candidate_id: str
    archetype: Archetype
    player_verdict: Verdict
    correct: bool
    board_bonus: int          # HD$ earned from evidence-board accuracy (issue #27)
    alignment_delta: int
    site_health_delta: float  # % change to Site Health (admits apply archetype weight)
    hackdollar_delta: int     # HD$ earned on this verdict (incl. board bonus)


@dataclass(frozen=True)
class DayResult:
    day_number: int
    performance: Performance
    results: tuple[CandidateResult, ...]
    final_currency: int
    final_alignment: int


# Upgrade IDs are strings (e.g. "auto_flag_breaches") for forward-compat.
UpgradeId = str


@dataclass
class GameState:
    """The single source of truth between sessions.

    Mutable by design — this is what gets saved/loaded. Keep it small and
    serializable; large derived data lives elsewhere.
    """

    seed: int
    current_day: int = 1
    compute_hours: int = 60       # ⏱ — finite daily tool budget (issue #27)
    compute_capacity: int = 60    # ⏱ base of the daily-budget formula (upgradable)
    alignment: int = 0
    site_health: float = 100.0    # persistent % loss condition (issues #18/#20)
    hackdollars: int = 0          # persistent between-day currency (issue #21)
    hackdox_credits: int = 1      # ground-truth reveal consumable (issue #25)
    upgrades: set[UpgradeId] = field(default_factory=set)
    # Progressive unlock (#31): which tool pages the player has been granted.
    # Stores ToolName.value strings (JSON-friendly, like `upgrades`). The
    # Dossier is never listed here — it's page 0, always available. A fresh
    # game starts empty; the Overseer's briefing beat (#34) adds a tool to
    # this set the moment its unlock line plays. The UI (#33) greys any tool
    # page not in here. Legacy saves without the field are backfilled from
    # config.TOOL_UNLOCK_DAY on load, so a mid-campaign player isn't locked out.
    unlocked_tools: set[str] = field(default_factory=set)
    completed_days: list[DayResult] = field(default_factory=list)
    # In-progress-day fields -- populated only mid-day:
    current_slot_index: int = 0
    pending_results: list[CandidateResult] = field(default_factory=list)
