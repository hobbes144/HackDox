"""Procedural candidate generator.

Pure function: (Day, game_seed, slot_index) -> Candidate. Identical inputs
always produce the identical Candidate — that's how saves replay exactly.

Each archetype carries a small spec:
  - dialogue tone
  - chat line pool
  - discrepancy budget (how many of each severity)
  - eligible DiscrepancyKinds
  - moral_modifier
  - correct_verdict

This file is intentionally one place — adding an archetype is editing
ARCHETYPE_SPECS plus, if needed, the word banks below.
"""

from __future__ import annotations

import random
import hashlib as _hashlib
import uuid
from dataclasses import dataclass, field

from .. import config
from .models import (
    Archetype,
    Candidate,
    ChatLine,
    Day,
    Discrepancy,
    DiscrepancyKind,
    Dossier,
    GroundTruth,
    ToolName,
    Verdict,
)


# ─── Word banks ─────────────────────────────────────────────────────────────

FIRST_NAMES = [
    "Lena", "Marcus", "Priya", "Diego", "Sasha", "Tomas", "Yuki", "Rhea",
    "Cyrus", "Mei", "Idris", "Nora", "Owen", "Zane", "Eli", "Kira", "Jonas",
    "Anya", "Bo", "Vega", "Ines", "Rafe",
]

LAST_NAMES = [
    "Korovin", "Achebe", "Patel", "Mercado", "Volkov", "Singh", "Tanaka",
    "Okonkwo", "Cho", "Reyes", "Bauer", "Halász", "Fontaine", "Brennan",
    "Petrov", "Maddox", "Salinas", "Ngata", "Carras", "Holm",
]

AFFILIATIONS_LEGIT = [
    "Univ. of Fictional CS Dept.",
    "Westmore Polytechnic Security Lab",
    "Reston Public Library Tech Branch",
    "Aegir Cybersecurity Cooperative",
    "Cordova College — Independent Study",
]

AFFILIATIONS_THIN = [
    "Freelance Security Researcher",
    "(none listed)",
    "Independent Hobbyist",
    "Self-employed",
    "Personal project",
]

# Prestigious institutions used by The Professional (and faked by Sneaky Buggers)
AFFILIATIONS_ELITE = [
    "MIT CSAIL",
    "Google Security Team",
    "Oxford Internet Institute",
    "Stanford HAI",
    "DeepMind Safety Research",
    "Carnegie Mellon CyLab",
    "ETH Zurich Information Security Group",
]

# Throwaway / disposable email domains that trigger The Incompatible
DOMAINS_DISPOSABLE = [
    "mailinator.com",
    "guerrillamail.com",
    "tempmail.org",
    "throwam.com",
    "sharklasers.com",
    "yopmail.com",
    "trashmail.com",
    "dispostable.com",
]

PURPOSES_LEGIT = [
    "research access to incident reports",
    "coursework on threat modeling",
    "writing a defensive guide for small businesses",
    "studying breach disclosure patterns",
    "verifying advisories for our team's runbook",
]

PURPOSES_SUSPECT = [
    "looking for unredacted leak data",
    "private archive of disclosed CVEs",
    "want to see what's in the breach dumps",
    "research — can't say more",
    "personal interest in account dumps",
]


# ─── Archetype specs ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DiscrepancyBudget:
    minor: int = 0
    major: int = 0
    critical: int = 0


@dataclass(frozen=True)
class ArchetypeSpec:
    archetype: Archetype
    correct_verdict: Verdict
    moral_modifier: int
    budget: DiscrepancyBudget
    eligible_kinds: tuple[DiscrepancyKind, ...]
    handle_style: str                       # "academic" | "elite" | "casual" | "noisy"
    affiliation_pool: str                   # "legit" | "thin"
    purpose_pool: str                       # "legit" | "suspect"
    tone: str                               # "warm" | "neutral" | "hostile" | "flippant" | "earnest"
    chat_pool: tuple[str, ...] = field(default_factory=tuple)
    hint_lines: dict[DiscrepancyKind, tuple[str, ...]] = field(default_factory=dict)


_CHAT_WARM = (
    "hi — sorry, first time doing this.",
    "thanks for taking a look. I'll wait.",
    "appreciate the help. let me know if you need anything else.",
)

_CHAT_NEUTRAL = (
    "I submitted the form yesterday.",
    "just need access for the reports section, please.",
    "let me know what else you need.",
)

_CHAT_HOSTILE = (
    "how long is this going to take?",
    "I know my rights — you can't just stall me.",
    "this is absurd. just approve it.",
)

_CHAT_FLIPPANT = (
    "lol, paperwork. classic.",
    "you'll let me in. they always do.",
    "you do know who I am, right?",
)

_CHAT_EARNEST = (
    "I read the rulebook. I tried to do this the right way.",
    "I know it looks bad. please hear me out.",
    "they're going to come for you next if you don't help.",
)

_CHAT_PROFESSIONAL = (
    "My team lead suggested I register — we use HackDox for our CVE triage.",
    "Happy to provide additional verification if needed.",
    "I've used similar services through the lab before.",
    "Let me know if you'd like a reference from my supervisor.",
)

_CHAT_INCOMPATIBLE = (
    "I just need quick access, nothing fancy.",
    "I didn't want to use my work email for this.",
    "This is just a temp account — I prefer to keep things separate.",
    "Is there a problem? I filled everything out.",
)


ARCHETYPE_SPECS: dict[Archetype, ArchetypeSpec] = {
    Archetype.OBVIOUS_ADMIT: ArchetypeSpec(
        archetype=Archetype.OBVIOUS_ADMIT,
        correct_verdict=Verdict.ADMIT,
        moral_modifier=0,
        budget=DiscrepancyBudget(),
        eligible_kinds=(),
        handle_style="academic",
        affiliation_pool="legit",
        purpose_pool="legit",
        tone="warm",
        chat_pool=_CHAT_WARM,
    ),
    Archetype.DAY_TO_DAY: ArchetypeSpec(
        archetype=Archetype.DAY_TO_DAY,
        correct_verdict=Verdict.ADMIT,
        moral_modifier=0,
        budget=DiscrepancyBudget(minor=1),
        eligible_kinds=(
            DiscrepancyKind.AFFILIATION_UNVERIFIED,
            DiscrepancyKind.AFTER_HOURS_ACCESS,   # v2: benign minor noise
            DiscrepancyKind.CLAIMED_IP_MISMATCH,  # v2: benign minor noise
            DiscrepancyKind.WEAK_CREDENTIAL,      # #29: weak enc + weak pw (minor)
        ),
        handle_style="casual",
        affiliation_pool="legit",
        purpose_pool="legit",
        tone="neutral",
        chat_pool=_CHAT_NEUTRAL,
    ),
    Archetype.DARK_WEB: ArchetypeSpec(
        archetype=Archetype.DARK_WEB,
        # Clean on paper — rules-correct verdict is ADMIT.
        correct_verdict=Verdict.ADMIT,
        moral_modifier=-1,
        budget=DiscrepancyBudget(),
        eligible_kinds=(),
        handle_style="elite",
        affiliation_pool="thin",
        purpose_pool="suspect",
        tone="flippant",
        chat_pool=_CHAT_FLIPPANT,
    ),
    Archetype.CLUMSY_CUTIE: ArchetypeSpec(
        archetype=Archetype.CLUMSY_CUTIE,
        correct_verdict=Verdict.DENY,
        moral_modifier=0,
        budget=DiscrepancyBudget(minor=2, major=1),
        eligible_kinds=(
            DiscrepancyKind.AFFILIATION_UNVERIFIED,
            DiscrepancyKind.MISSING_PUBLIC_PROFILE,
            DiscrepancyKind.EMAIL_GITHUB_MISMATCH,
            # v2: competence / hygiene failures, not malice
            DiscrepancyKind.UNSALTED_STORAGE,
            DiscrepancyKind.CROSS_BREACH_REUSE,
            DiscrepancyKind.AFTER_HOURS_ACCESS,
            DiscrepancyKind.CLAIMED_IP_MISMATCH,
            DiscrepancyKind.WEAK_CREDENTIAL,      # #29: weak enc + weak pw (minor)
        ),
        handle_style="casual",
        affiliation_pool="thin",
        purpose_pool="legit",
        tone="warm",
        chat_pool=_CHAT_WARM,
    ),
    Archetype.BAD_ACTOR: ArchetypeSpec(
        archetype=Archetype.BAD_ACTOR,
        correct_verdict=Verdict.DENY,
        moral_modifier=0,
        budget=DiscrepancyBudget(major=2, critical=1),
        eligible_kinds=(
            DiscrepancyKind.HOSTILE_CHAT,
            DiscrepancyKind.BREACH_HIT,
            DiscrepancyKind.BRUTE_FORCE_IN_LOG,
            DiscrepancyKind.IMPOSSIBLE_TRAVEL,
            DiscrepancyKind.LEAKED_PASSWORD,
            # v2: loud, obvious, damning
            DiscrepancyKind.THREAT_FORUM_MATCH,
            DiscrepancyKind.CREDENTIAL_STUFFING,
            DiscrepancyKind.BURNER_IDENTITY,
            DiscrepancyKind.TYPOSQUAT_HANDLE,
            DiscrepancyKind.CROSS_BREACH_REUSE,
        ),
        handle_style="noisy",
        affiliation_pool="thin",
        purpose_pool="suspect",
        tone="hostile",
        chat_pool=_CHAT_HOSTILE,
    ),
    Archetype.SNEAKY_BUGGER: ArchetypeSpec(
        archetype=Archetype.SNEAKY_BUGGER,
        correct_verdict=Verdict.DENY,
        moral_modifier=0,
        budget=DiscrepancyBudget(major=1, critical=1),
        # Tool-only — never AFFILIATION_UNVERIFIED or HOSTILE_CHAT.
        # AFFILIATION_MISMATCH is the "fake elite org" variant — ghostscan needed to catch it.
        eligible_kinds=(
            DiscrepancyKind.STEGO_PAYLOAD_PRESENT,
            DiscrepancyKind.COVERT_C2_CHANNEL,
            DiscrepancyKind.SOCK_PUPPET_ACCOUNTS,
            DiscrepancyKind.INSIDER_BEHAVIOR,
            DiscrepancyKind.IMPOSSIBLE_TRAVEL,
            DiscrepancyKind.AFFILIATION_MISMATCH,
            # v2: subtle, tool-only evasion craft + optional breadcrumbs
            # (budget has no minor slot, so the minor breadcrumbs only appear
            #  if the budget is later widened — kept eligible for variety)
            DiscrepancyKind.LOW_AND_SLOW,
            DiscrepancyKind.ENCRYPTED_PAYLOAD,
            DiscrepancyKind.BURNER_IDENTITY,
            DiscrepancyKind.TYPOSQUAT_HANDLE,
            DiscrepancyKind.AFTER_HOURS_ACCESS,
            DiscrepancyKind.CLAIMED_IP_MISMATCH,
        ),
        handle_style="academic",
        affiliation_pool="elite",       # the camouflage — faked prestigious affiliation
        purpose_pool="legit",
        tone="warm",                    # the camouflage
        chat_pool=_CHAT_PROFESSIONAL,   # borrows the professional tone for extra credibility
    ),
    Archetype.WHITE_HAT: ArchetypeSpec(
        archetype=Archetype.WHITE_HAT,
        correct_verdict=Verdict.DENY,   # by the rules, deny.
        moral_modifier=+1,              # but admitting them helps the cause.
        budget=DiscrepancyBudget(critical=1),
        eligible_kinds=(
            DiscrepancyKind.MISSING_PUBLIC_PROFILE,
            DiscrepancyKind.AFFILIATION_UNVERIFIED,
            # v2: the same evasion craft as the Sneaky Bugger, in service of the cause
            DiscrepancyKind.LOW_AND_SLOW,
            DiscrepancyKind.ENCRYPTED_PAYLOAD,
            DiscrepancyKind.BURNER_IDENTITY,
        ),
        handle_style="elite",
        affiliation_pool="thin",
        purpose_pool="suspect",
        tone="earnest",
        chat_pool=_CHAT_EARNEST,
    ),
    Archetype.THE_PROFESSIONAL: ArchetypeSpec(
        archetype=Archetype.THE_PROFESSIONAL,
        correct_verdict=Verdict.ADMIT,
        moral_modifier=0,
        budget=DiscrepancyBudget(),     # zero discrepancies — clean admit
        eligible_kinds=(),
        handle_style="academic",
        affiliation_pool="elite",       # MIT, Google, Oxford, etc.
        purpose_pool="legit",
        tone="neutral",
        chat_pool=_CHAT_PROFESSIONAL,
    ),
    Archetype.THE_INCOMPATIBLE: ArchetypeSpec(
        archetype=Archetype.THE_INCOMPATIBLE,
        correct_verdict=Verdict.DENY,
        moral_modifier=0,
        budget=DiscrepancyBudget(major=1),
        eligible_kinds=(DiscrepancyKind.DISPOSABLE_EMAIL,),
        handle_style="casual",
        affiliation_pool="thin",
        purpose_pool="legit",           # probably not malicious — just incompatible
        tone="neutral",
        chat_pool=_CHAT_INCOMPATIBLE,
    ),
}


# ─── Generator ──────────────────────────────────────────────────────────────


_SEVERITY_REVEAL = {
    DiscrepancyKind.MISSING_PUBLIC_PROFILE: (ToolName.DOSSIER,    "minor"),
    DiscrepancyKind.HOSTILE_CHAT:           (ToolName.DOSSIER,    "major"),
    DiscrepancyKind.AFFILIATION_UNVERIFIED: (ToolName.DOSSIER,    "minor"),
    DiscrepancyKind.DISPOSABLE_EMAIL:       (ToolName.DOSSIER,    "major"),
    DiscrepancyKind.EMAIL_GITHUB_MISMATCH:  (ToolName.GHOSTSCAN,  "major"),
    DiscrepancyKind.BREACH_HIT:             (ToolName.GHOSTSCAN,  "critical"),
    DiscrepancyKind.SOCK_PUPPET_ACCOUNTS:   (ToolName.GHOSTSCAN,  "major"),
    DiscrepancyKind.AFFILIATION_MISMATCH:   (ToolName.GHOSTSCAN,  "major"),
    DiscrepancyKind.BRUTE_FORCE_IN_LOG:     (ToolName.LOGWATCH,   "critical"),
    DiscrepancyKind.IMPOSSIBLE_TRAVEL:      (ToolName.LOGWATCH,   "major"),
    DiscrepancyKind.INSIDER_BEHAVIOR:       (ToolName.LOGWATCH,   "major"),
    DiscrepancyKind.LEAKED_PASSWORD:        (ToolName.HASHCRACK,  "critical"),
    # Issue #29 rework: weak encryption + weak plaintext = MINOR violation —
    # a hygiene signal, not immediate grounds for denial.
    DiscrepancyKind.WEAK_CREDENTIAL:        (ToolName.HASHCRACK,  "minor"),
    DiscrepancyKind.STEGO_PAYLOAD_PRESENT:  (ToolName.STEGOTOOL,  "major"),
    DiscrepancyKind.COVERT_C2_CHANNEL:      (ToolName.STEGOTOOL,  "critical"),
    # ── v2 additions ──────────────────────────────────────────────────
    DiscrepancyKind.BURNER_IDENTITY:        (ToolName.GHOSTSCAN,  "major"),
    DiscrepancyKind.THREAT_FORUM_MATCH:     (ToolName.GHOSTSCAN,  "critical"),
    DiscrepancyKind.TYPOSQUAT_HANDLE:       (ToolName.GHOSTSCAN,  "major"),
    DiscrepancyKind.CREDENTIAL_STUFFING:    (ToolName.LOGWATCH,   "critical"),
    DiscrepancyKind.AFTER_HOURS_ACCESS:     (ToolName.LOGWATCH,   "minor"),
    DiscrepancyKind.LOW_AND_SLOW:           (ToolName.LOGWATCH,   "critical"),
    DiscrepancyKind.CROSS_BREACH_REUSE:     (ToolName.HASHCRACK,  "major"),
    DiscrepancyKind.UNSALTED_STORAGE:       (ToolName.HASHCRACK,  "major"),
    DiscrepancyKind.ENCRYPTED_PAYLOAD:      (ToolName.STEGOTOOL,  "critical"),
    DiscrepancyKind.CLAIMED_IP_MISMATCH:    (ToolName.DOSSIER,    "minor"),
}


# ─── Evidence-tier gate (#31) ────────────────────────────────────────────────
#
# A discrepancy is only plantable once the tool that reveals it has been
# taught. intro_day(kind) defaults to the unlock day of its revealing tool
# (config.TOOL_UNLOCK_DAY) — so the gate and the UI unlock schedule can never
# disagree — unless a kind is explicitly held back below. The generator
# filters each archetype's eligible kinds through this before rolling, so a
# Day-N candidate can never carry evidence the player has no way to read yet.

# Per-kind overrides: debut a specific kind LATER than its tool's unlock day.
# Empty for now (every kind debuts with its tool). Add entries here rather
# than building a parallel per-kind table, so the tool-derived default stays
# the norm and only the exceptions are spelled out.
_INTRO_DAY_OVERRIDE: dict[DiscrepancyKind, int] = {}


def intro_day(kind: DiscrepancyKind) -> int:
    """The earliest day `kind` may be planted (its revealing tool's unlock day)."""
    if kind in _INTRO_DAY_OVERRIDE:
        return _INTRO_DAY_OVERRIDE[kind]
    revealing_tool, _ = _SEVERITY_REVEAL[kind]
    return config.TOOL_UNLOCK_DAY[revealing_tool.value]


_DISCREPANCY_DESCRIPTIONS = {
    DiscrepancyKind.MISSING_PUBLIC_PROFILE: "No public profile found for the claimed handle.",
    DiscrepancyKind.HOSTILE_CHAT:           "Candidate threatened the service operator.",
    DiscrepancyKind.AFFILIATION_UNVERIFIED: "Claimed affiliation could not be verified.",
    DiscrepancyKind.DISPOSABLE_EMAIL:       "Email domain is a known disposable / throwaway service.",
    DiscrepancyKind.EMAIL_GITHUB_MISMATCH:  "GitHub commit email does not match the claimed email.",
    DiscrepancyKind.BREACH_HIT:             "Email appears in a known breach corpus.",
    DiscrepancyKind.SOCK_PUPPET_ACCOUNTS:   "Identical handle pattern found across suspicious platforms.",
    DiscrepancyKind.AFFILIATION_MISMATCH:   "Claimed elite affiliation not found — ghostscan returned no match.",
    DiscrepancyKind.BRUTE_FORCE_IN_LOG:     "Submitted log shows clear brute-force pattern from this account.",
    DiscrepancyKind.IMPOSSIBLE_TRAVEL:      "Logins from geographically impossible locations.",
    DiscrepancyKind.INSIDER_BEHAVIOR:       "After-hours access pattern consistent with insider misuse.",
    DiscrepancyKind.LEAKED_PASSWORD:        "Password hash cracked from leaked credential — confirms compromise.",
    DiscrepancyKind.WEAK_CREDENTIAL:        "Weakly-encrypted password cracked to a weak plaintext (poor hygiene).",
    DiscrepancyKind.STEGO_PAYLOAD_PRESENT:  "Submitted image contains an embedded payload.",
    DiscrepancyKind.COVERT_C2_CHANNEL:      "Image embeds a command-and-control payload pattern.",
    # ── v2 additions ──────────────────────────────────────────────────
    DiscrepancyKind.BURNER_IDENTITY:        "Public accounts all created within days of each other — burner identity.",
    DiscrepancyKind.THREAT_FORUM_MATCH:     "Handle matches an account on a known threat / dark-web forum.",
    DiscrepancyKind.TYPOSQUAT_HANDLE:       "Handle is a lookalike of a trusted org or person (typosquat).",
    DiscrepancyKind.CREDENTIAL_STUFFING:    "Log shows one IP hitting many accounts with few tries each — credential stuffing.",
    DiscrepancyKind.AFTER_HOURS_ACCESS:     "Account activity outside business hours.",
    DiscrepancyKind.LOW_AND_SLOW:           "Attack activity spread thin over time to evade detection thresholds.",
    DiscrepancyKind.CROSS_BREACH_REUSE:     "Cracked password recurs across multiple breach corpora — reused credential.",
    DiscrepancyKind.UNSALTED_STORAGE:       "Submitted credential is unsalted / plaintext-equivalent and cracks instantly.",
    DiscrepancyKind.ENCRYPTED_PAYLOAD:      "Hidden image payload is XOR/encrypted — deliberate obfuscation.",
    DiscrepancyKind.CLAIMED_IP_MISMATCH:    "Claimed connection IP does not match the IP in the submitted logs.",
}



# ─── Hashcrack seed data ─────────────────────────────────────────────────────

_HC_WEAK_PASSWORDS = [
    "password", "123456", "password123", "letmein", "qwerty",
    "admin", "welcome1", "monkey", "dragon", "sunshine",
    "iloveyou", "princess", "1234567890", "abc123",
]

_HC_LEAKED_PASSWORDS = [
    "letmein2019", "summer2021!", "dragon2020", "welcome@corp",
    "monkey123!", "sunshine2018", "iloveyou01", "admin2022",
]

# Issue #29: obviously-strong plaintexts for clean candidates. When cracked
# (medium-tier SHA256), the reveal should read as clearly safe.
_HC_STRONG_PASSWORDS = [
    "drawkcab16445$&", "Tr0ub4dor&3x9!", "x9#Vq2mLp8@Rz", "qN7!fWc$4kZt2",
    "K3y$tone-9vXq!", "8Rl@zP4x#mQ7w", "vE5&dHu9!Tc3s", "J6w#bN2q$Yf8z",
]

_BCRYPT_ALPHABET = ("./ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                    "abcdefghijklmnopqrstuvwxyz0123456789")


def _fake_bcrypt(rng: random.Random) -> str:
    """A display-realistic bcrypt hash ($2b$12$ + 53 radix-64 chars).

    Strong-tier encryption (issue #29): never crackable in-game — the
    plaintext behind it is irrelevant, so none is stored.
    """
    return "$2b$12$" + "".join(rng.choice(_BCRYPT_ALPHABET) for _ in range(53))

def stable_hash(*parts) -> int:
    """Process-independent hash for seeding RNGs.

    Python's builtin hash() salts strings per process (PYTHONHASHSEED), so
    seeding with hash(tuple-with-string) silently made generation differ
    between runs — breaking save replay and making tests flaky. SHA-256 of
    the repr is stable everywhere.
    """
    digest = _hashlib.sha256(repr(parts).encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _seeded_rng(game_seed: int, day_number: int, slot_index: int, salt: str) -> random.Random:
    """Per-slot deterministic RNG.

    Salting by purpose keeps the name roll independent from the discrepancy
    roll — so swapping one mechanic later doesn't shift the other.
    """
    return random.Random(stable_hash(game_seed, day_number, slot_index, salt) & 0xFFFFFFFF)


def _make_handle(rng: random.Random, first: str, last: str, style: str) -> str:
    f, l = first.lower(), last.lower()
    if style == "academic":
        return f"{f[0]}{l}"
    if style == "elite":
        leet = {"a": "4", "e": "3", "i": "1", "o": "0", "s": "5"}
        return "".join(leet.get(c, c) for c in (f + l)) + str(rng.randint(10, 99))
    if style == "casual":
        return f"{f}.{l}"
    if style == "noisy":
        return f"{f}{l}{rng.randint(100, 9999)}"
    return f + l


_ELITE_DOMAIN_MAP = {
    "MIT CSAIL":                          "mit.edu",
    "Google Security Team":               "google.com",
    "Oxford Internet Institute":          "ox.ac.uk",
    "Stanford HAI":                       "stanford.edu",
    "DeepMind Safety Research":           "deepmind.com",
    "Carnegie Mellon CyLab":              "cmu.edu",
    "ETH Zurich Information Security Group": "ethz.ch",
}

_LEGIT_DOMAIN_MAP = {
    "Univ. of Fictional CS Dept.": "univ-fictional.edu",
    "Westmore Polytechnic Security Lab": "westmore.edu",
    "Reston Public Library Tech Branch": "reston-libs.org",
    "Aegir Cybersecurity Cooperative": "aegir-coop.net",
    "Cordova College — Independent Study": "cordova.edu",
}

def _make_email(
    rng: random.Random,
    first: str,
    last: str,
    affiliation: str,
    disposable: bool = False,
) -> str:
    if disposable:
        return f"{first.lower()}.{last.lower()}{rng.randint(1, 99)}@{rng.choice(DOMAINS_DISPOSABLE)}"
    if affiliation in _LEGIT_DOMAIN_MAP:
        return f"{first.lower()}.{last.lower()[0]}@{_LEGIT_DOMAIN_MAP[affiliation]}"
    if affiliation in _ELITE_DOMAIN_MAP:
        return f"{first.lower()[0]}{last.lower()}@{_ELITE_DOMAIN_MAP[affiliation]}"
    pool = ["yahoo.com", "gmail.com", "fastmail.io", "protonmail.com"]
    return f"{first.lower()}{last.lower()}{rng.randint(1, 99)}@{rng.choice(pool)}"


def _roll_discrepancies(
    rng: random.Random,
    spec: ArchetypeSpec,
    day_number: int,
) -> list[Discrepancy]:
    """Pick discrepancies for this candidate.

    Honors the archetype's budget. If a budget slot requires a severity
    that none of the eligible kinds can satisfy, the slot is skipped — the
    archetype specs above are written so this shouldn't happen.

    The evidence-tier gate (#31) filters out any kind whose revealing tool
    hasn't been taught by `day_number` before rolling, so an early-campaign
    candidate never carries evidence the player can't yet read. NOTE: for a
    tool-only archetype (e.g. Sneaky Bugger) this can empty the eligible pool
    on very early days — that's a day-CONTENT concern (the day's archetype
    mix should suit the tools taught so far, handled by #32/#15), not a bug in
    this gate.
    """
    chosen: list[Discrepancy] = []
    used: set[DiscrepancyKind] = set()
    eligible = [k for k in spec.eligible_kinds if intro_day(k) <= day_number]
    rng.shuffle(eligible)

    def take(severity: str, count: int) -> None:
        nonlocal eligible
        for _ in range(count):
            for kind in list(eligible):
                if kind in used:
                    continue
                _, kind_sev = _SEVERITY_REVEAL[kind]
                if kind_sev == severity:
                    revealed_by, _ = _SEVERITY_REVEAL[kind]
                    chosen.append(Discrepancy(
                        kind=kind,
                        severity=severity,  # type: ignore[arg-type]
                        revealed_by=revealed_by,
                        description=_DISCREPANCY_DESCRIPTIONS[kind],
                    ))
                    used.add(kind)
                    break

    take("critical", spec.budget.critical)
    take("major",    spec.budget.major)
    take("minor",    spec.budget.minor)
    return chosen


def _build_chat(
    rng: random.Random,
    spec: ArchetypeSpec,
    discrepancies: list[Discrepancy],
) -> tuple[ChatLine, ...]:
    """Compose 3-5 chat lines from the archetype's pool.

    Bad Actors always get the HOSTILE_CHAT line spliced if it's in their
    discrepancies. Other archetypes get neutral pool lines.
    """
    lines: list[ChatLine] = []
    base = list(spec.chat_pool)
    rng.shuffle(base)
    n = rng.randint(3, min(5, max(3, len(base))))
    minute = rng.randint(0, 30)
    for i, text in enumerate(base[:n]):
        lines.append(ChatLine(
            timestamp=f"10:{(minute + i * 2) % 60:02d}",
            text=text,
            tag=spec.tone,
        ))

    # If a discrepancy implies a chat hint, splice it.
    has_hostile = any(d.kind == DiscrepancyKind.HOSTILE_CHAT for d in discrepancies)
    if has_hostile and lines:
        lines.append(ChatLine(
            timestamp=f"10:{(minute + n * 2) % 60:02d}",
            text="you'll regret this. I have friends.",
            tag="hostile",
        ))
    return tuple(lines)


def _shuffled_archetype_bag(
    rng: random.Random,
    archetype_mix: dict[Archetype, int],
) -> list[Archetype]:
    """Build one deterministic ordering of the day's archetype mix.

    Single source of truth for slot -> archetype: shuffled once using a
    day-scoped RNG, then walked by slot index. This guarantees the
    realized mix exactly equals the declared mix.
    """
    bag: list[Archetype] = []
    for archetype, count in archetype_mix.items():
        bag.extend([archetype] * count)
    if not bag:
        raise ValueError("Day's archetype_mix is empty")
    rng.shuffle(bag)
    return bag


def _pick_archetype_for_slot(
    game_seed: int,
    day_number: int,
    archetype_mix: dict[Archetype, int],
    slot_index: int,
) -> Archetype:
    """Deterministic archetype selection respecting the day's mix.

    The bag is shuffled with a *day-scoped* RNG (no slot salt) so the
    walk is consistent across slots; the slot index is just an index
    into the shared ordering.
    """
    day_rng = random.Random(stable_hash(game_seed, day_number, "archetype_bag") & 0xFFFFFFFF)
    bag = _shuffled_archetype_bag(day_rng, archetype_mix)
    return bag[slot_index % len(bag)]


def generate(game_seed: int, day: Day, slot_index: int) -> Candidate:
    """Generate the candidate for one slot of one day. Deterministic."""

    archetype = _pick_archetype_for_slot(game_seed, day.number, day.archetype_mix, slot_index)
    spec = ARCHETYPE_SPECS[archetype]

    rng_id = _seeded_rng(game_seed, day.number, slot_index, "identity")
    first = rng_id.choice(FIRST_NAMES)
    last = rng_id.choice(LAST_NAMES)
    if spec.affiliation_pool == "legit":
        affiliation_pool = AFFILIATIONS_LEGIT
    elif spec.affiliation_pool == "elite":
        affiliation_pool = AFFILIATIONS_ELITE
    else:
        affiliation_pool = AFFILIATIONS_THIN
    purpose_pool = PURPOSES_LEGIT if spec.purpose_pool == "legit" else PURPOSES_SUSPECT
    affiliation = rng_id.choice(affiliation_pool)
    purpose = rng_id.choice(purpose_pool)
    handle = _make_handle(rng_id, first, last, spec.handle_style)
    is_incompatible = archetype == Archetype.THE_INCOMPATIBLE
    email = _make_email(rng_id, first, last, affiliation, disposable=is_incompatible)

    rng_disc = _seeded_rng(game_seed, day.number, slot_index, "discrepancies")
    discrepancies = _roll_discrepancies(rng_disc, spec, day.number)

    rng_chat = _seeded_rng(game_seed, day.number, slot_index, "chat")
    chat = _build_chat(rng_chat, spec, discrepancies)

    # Determine GitHub commit email.
    # Candidates with a GitHub handle always have a commit email; candidates
    # with EMAIL_GITHUB_MISMATCH get a deliberately different one.
    has_github = spec.handle_style != "elite"
    commit_email: str | None = None
    if has_github:
        has_mismatch = any(
            d.kind == DiscrepancyKind.EMAIL_GITHUB_MISMATCH for d in discrepancies
        )
        if has_mismatch:
            rng_ce = _seeded_rng(game_seed, day.number, slot_index, "commit_email")
            alt_domains = ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com"]
            _dom = rng_ce.choice(alt_domains)
            commit_email = f"{first.lower()}{last.lower()[0]}{rng_ce.randint(1, 99)}@{_dom}"
        else:
            commit_email = email   # consistent — nothing to spot

    # Compute candidate id early so hash derivation matches tools_bridge
    # 12 hex chars straight from a stable digest. (The old
    # uuid.UUID(int=hash & …).hex[:12] took the TOP hex digits, which were
    # all zeros whenever the hash was non-negative — colliding ids.)
    cand_id = _hashlib.sha256(
        repr((game_seed, day.number, slot_index, "id")).encode()).hexdigest()[:12]

    # Generate submitted_image_path for candidates with stego discrepancies
    _st_images = ["profile.png", "avatar.jpg", "header.png", "screenshot.png"]
    _has_st = any(d.kind in (
        DiscrepancyKind.STEGO_PAYLOAD_PRESENT, DiscrepancyKind.COVERT_C2_CHANNEL,
        DiscrepancyKind.ENCRYPTED_PAYLOAD,   # v2: also ships a suspect image
    ) for d in discrepancies)
    _rng_st = random.Random(int(cand_id, 16) ^ 0xDE4DC0DE)
    submitted_image_path: str | None = _rng_st.choice(_st_images) if _has_st else None

    # Generate the submitted credential — issue #29: EVERY candidate now
    # submits a password in encrypted form. The hash shape encodes the
    # encryption-strength tier the dossier displays:
    #   bcrypt  = STRONG (always safe — uncrackable, plaintext irrelevant)
    #   SHA256  = MEDIUM (crackable with effort)
    #   MD5     = WEAK   (cracks instantly)
    # Violation carriers keep their v2 semantics: CROSS_BREACH_REUSE behaves
    # like a leaked credential (sha256 of a reused leaked password);
    # UNSALTED_STORAGE behaves like a weak credential (instant-crack md5).
    # WEAK_CREDENTIAL (#29 rework) = weak encryption + weak plaintext.
    submitted_hash: str | None = None
    password_plain: str | None = None
    _has_leaked = any(d.kind == DiscrepancyKind.LEAKED_PASSWORD for d in discrepancies)
    _has_weak   = any(d.kind == DiscrepancyKind.WEAK_CREDENTIAL  for d in discrepancies)
    _has_reuse  = any(d.kind == DiscrepancyKind.CROSS_BREACH_REUSE for d in discrepancies)
    _has_unsalt = any(d.kind == DiscrepancyKind.UNSALTED_STORAGE   for d in discrepancies)
    rng_hc = random.Random(int(cand_id, 16) ^ 0xDEAD_C0DE)
    if _has_leaked or _has_reuse:
        password_plain = rng_hc.choice(_HC_LEAKED_PASSWORDS)
        submitted_hash = _hashlib.sha256(password_plain.encode()).hexdigest()
    elif _has_weak or _has_unsalt:
        password_plain = rng_hc.choice(_HC_WEAK_PASSWORDS)
        submitted_hash = _hashlib.md5(password_plain.encode()).hexdigest()
    elif rng_hc.random() < 0.6:
        # Clean candidate, strong-tier encryption: bcrypt — no violation
        # possible, and no ⏱ worth spending on a crack attempt.
        submitted_hash = _fake_bcrypt(rng_hc)
        password_plain = None   # uncrackable — plaintext never revealed
    else:
        # Clean candidate, medium-tier encryption of an obviously strong
        # password: crackable, and the reveal confirms there's no issue.
        password_plain = rng_hc.choice(_HC_STRONG_PASSWORDS)
        submitted_hash = _hashlib.sha256(password_plain.encode()).hexdigest()

    # Generate claimed_ip — what the candidate says they connect from.
    _rng_ip = random.Random(int(cand_id, 16) ^ 0xFACEB00C)
    _internal_ip = f"10.0.{_rng_ip.randint(1,10)}.{_rng_ip.randint(2,254)}"
    claimed_ip: str = _internal_ip

    dossier = Dossier(
        claimed_github=handle if has_github else None,
        claimed_breaches=(),
        notes="Submitted via standard intake form. Self-reported.",
        commit_email=commit_email,
        submitted_hash=submitted_hash,
        submitted_image_path=submitted_image_path,
        claimed_ip=claimed_ip,
        password_plain=password_plain,
    )

    truth = GroundTruth(
        correct_verdict=spec.correct_verdict,
        discrepancies=tuple(discrepancies),
        moral_modifier=spec.moral_modifier,
    )

    return Candidate(
        id=cand_id,
        archetype=archetype,
        display_name=f"{first} {last}",
        handle=handle,
        email=email,
        photo_seed=rng_id.randint(0, 2**31 - 1),
        claimed_purpose=purpose,
        claimed_affiliation=affiliation,
        dossier=dossier,
        chat_script=chat,
        truth=truth,
    )
