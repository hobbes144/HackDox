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

# #56: the sentinel the dossier shows when AFFILIATION_NOT_STATED is planted.
# Named rather than inlined because the sweep has to recognise it and refuse to
# render it as though it were an organisation.
NO_AFFILIATION_STATED = "(none listed)"

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
            DiscrepancyKind.AFFILIATION_NOT_STATED,
            DiscrepancyKind.AFTER_HOURS_ACCESS,   # v2: benign minor noise
            DiscrepancyKind.CLAIMED_IP_MISMATCH,  # v2: benign minor noise
            DiscrepancyKind.WEAK_CREDENTIAL,      # #29: weak enc + weak pw (minor)
            DiscrepancyKind.WEAK_ENCRYPTION,      # dossier-tier: weak algo, not weak pw
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
            DiscrepancyKind.AFFILIATION_NOT_STATED,
            DiscrepancyKind.MISSING_PUBLIC_PROFILE,
            DiscrepancyKind.EMAIL_GITHUB_MISMATCH,
            # v2: competence / hygiene failures, not malice
            DiscrepancyKind.UNSALTED_STORAGE,
            DiscrepancyKind.CROSS_BREACH_REUSE,
            DiscrepancyKind.AFTER_HOURS_ACCESS,
            DiscrepancyKind.CLAIMED_IP_MISMATCH,
            DiscrepancyKind.WEAK_CREDENTIAL,      # #29: weak enc + weak pw (minor)
            DiscrepancyKind.WEAK_ENCRYPTION,      # dossier-tier: weak algo, not weak pw
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
            # TYPOSQUAT_HANDLE removed by #53: it is minor now and this
            # archetype has no minor slot, so it could never be selected.
            # A lookalike handle is subtle deception anyway - a poor fit
            # for an archetype whose whole read is being obviously hostile.
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
        # #53: minor=1 added when TYPOSQUAT_HANDLE was demoted major -> minor.
        # Without a minor slot a minor kind can never be selected, so the
        # reworked typosquat would have been unreachable. A subtle, deliberately
        # deceptive handle is squarely this archetype's register, which is why
        # the slot went here rather than to the Bad Actor.
        budget=DiscrepancyBudget(minor=1, major=1, critical=1),
        # Tool-only — never AFFILIATION_UNVERIFIED or HOSTILE_CHAT.
        # AFFILIATION_MISMATCH is the "fake elite org" variant — ghostscan needed to catch it.
        eligible_kinds=(
            DiscrepancyKind.STEGO_PAYLOAD_PRESENT,
            DiscrepancyKind.COVERT_C2_CHANNEL,
            DiscrepancyKind.SOCK_PUPPET_ACCOUNTS,
            DiscrepancyKind.INSIDER_BEHAVIOR,
            DiscrepancyKind.IMPOSSIBLE_TRAVEL,
            DiscrepancyKind.AFFILIATION_MISMATCH,
            DiscrepancyKind.AFFILIATION_UNLISTED,
            # v2: subtle, tool-only evasion craft + optional breadcrumbs
            # (budget has no minor slot, so the minor breadcrumbs only appear
            #  if the budget is later widened — kept eligible for variety)
            DiscrepancyKind.LOW_AND_SLOW,
            DiscrepancyKind.ENCRYPTED_PAYLOAD,
            DiscrepancyKind.BURNER_IDENTITY,
            DiscrepancyKind.TYPOSQUAT_HANDLE,
            DiscrepancyKind.AFTER_HOURS_ACCESS,
            DiscrepancyKind.CLAIMED_IP_MISMATCH,
            DiscrepancyKind.WEAK_ENCRYPTION,
        ),
        handle_style="academic",
        # #56: moved elite -> legit. A claimed elite/trusted affiliation is now
        # unfakeable - it always confirms in the sweep, which is the player's
        # quick-admit bypass. A Sneaky Bugger claiming one could therefore never
        # mismatch. It now claims a small legit org and fakes THAT instead.
        affiliation_pool="legit",       # the camouflage — a plausible small org
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
            DiscrepancyKind.AFFILIATION_NOT_STATED,
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
    # 2026-08-17 (#51): retiered DOSSIER -> GHOSTSCAN. It was never a dossier
    # violation: the dossier's claimed_github is set from the archetype's handle
    # style (see generate()), NOT from whether this kind was planted, so a
    # candidate carrying it still showed a perfectly normal GitHub handle. The
    # only evidence is the thinned platform count in the Ghostscan sweep, which
    # is Ghostscan-only. Being mistiered as DOSSIER also made intro_day() return
    # 1, so the #31 gate happily planted it on Day 1 with Ghostscan still locked -
    # measured at 300 of 600 Day-1 Clumsy Cutie / White Hat candidates, every one
    # an unflaggable violation that still counted for scoring.
    DiscrepancyKind.MISSING_PUBLIC_PROFILE: (ToolName.GHOSTSCAN,  "minor"),
    DiscrepancyKind.HOSTILE_CHAT:           (ToolName.DOSSIER,    "major"),
    # #56 - the four affiliation violations, one evidence location each:
    #   NOT_STATED  dossier   the field is blank on the dossier
    #   MISMATCH    ghostscan sweep shows a DIFFERENT org than claimed
    #   UNLISTED    ghostscan profiles exist, none carry an org tag
    #   MISSING_PUBLIC_PROFILE (below) ghostscan  handle barely appears at all
    DiscrepancyKind.AFFILIATION_NOT_STATED: (ToolName.DOSSIER,    "minor"),
    DiscrepancyKind.AFFILIATION_UNLISTED:   (ToolName.GHOSTSCAN,  "minor"),
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
    # #53: demoted major -> minor. A lookalike handle is a signal to corroborate,
    # not proof of intent on its own.
    DiscrepancyKind.TYPOSQUAT_HANDLE:       (ToolName.GHOSTSCAN,  "minor"),
    DiscrepancyKind.CREDENTIAL_STUFFING:    (ToolName.LOGWATCH,   "critical"),
    DiscrepancyKind.AFTER_HOURS_ACCESS:     (ToolName.LOGWATCH,   "minor"),
    DiscrepancyKind.LOW_AND_SLOW:           (ToolName.LOGWATCH,   "critical"),
    DiscrepancyKind.CROSS_BREACH_REUSE:     (ToolName.HASHCRACK,  "major"),
    # 2026-08-16: moved HASHCRACK → DOSSIER. Originally speced as "free (hash
    # shape)" but shipped as Hashcrack-only; the dossier now shows the stored
    # password in the clear for this kind (see Dossier.credential_unsalted),
    # so no crack is needed to catch it.
    DiscrepancyKind.UNSALTED_STORAGE:       (ToolName.DOSSIER,    "major"),
    DiscrepancyKind.ENCRYPTED_PAYLOAD:      (ToolName.STEGOTOOL,  "critical"),
    # 2026-08-16: moved DOSSIER → LOGWATCH. The dossier only ever shows the
    # *claimed* IP; the mismatch is only confirmable by comparing it against
    # the login IPs in the Logwatch log, so Logwatch is what actually reveals
    # it (and gates it to Logwatch's unlock day instead of day 1).
    DiscrepancyKind.CLAIMED_IP_MISMATCH:    (ToolName.LOGWATCH,   "minor"),
    # Weak encryption ALGORITHM (not a weak plaintext) — the hash-shape /
    # strength chip on the dossier already shows this for free, no tool
    # needed. Distinct from WEAK_CREDENTIAL, which needs a Hashcrack crack to
    # confirm the plaintext itself is bad.
    DiscrepancyKind.WEAK_ENCRYPTION:        (ToolName.DOSSIER,    "minor"),
}


# The set of kinds that drive submitted_hash/password_plain generation in
# `generate()` below — a candidate can carry at most one of these (see the
# exclusivity note in `_roll_discrepancies`).
_CREDENTIAL_ARTIFACT_KINDS: frozenset[DiscrepancyKind] = frozenset({
    DiscrepancyKind.LEAKED_PASSWORD,
    DiscrepancyKind.CROSS_BREACH_REUSE,
    DiscrepancyKind.WEAK_CREDENTIAL,
    DiscrepancyKind.UNSALTED_STORAGE,
    DiscrepancyKind.WEAK_ENCRYPTION,
})

# Every candidate submits exactly ONE image (Dossier.submitted_image_path), and
# tools_bridge.build_stego_image renders exactly one payload kind for it. Two
# stego kinds on one candidate therefore means one of them has no carrier the
# player can ever find — a ground-truth violation that counts for scoring and
# is impossible to flag. Measured at 73 of 450 stego-carrying candidates (16%)
# before this was added; the Sneaky Bugger's major+critical budget could fill
# both slots from this group.
#
# Same failure mode, and the same fix, as _CREDENTIAL_ARTIFACT_KINDS above:
# one submitted artifact means at most one violation about that artifact.
_STEGO_ARTIFACT_KINDS: frozenset[DiscrepancyKind] = frozenset({
    DiscrepancyKind.STEGO_PAYLOAD_PRESENT,
    DiscrepancyKind.ENCRYPTED_PAYLOAD,
    DiscrepancyKind.COVERT_C2_CHANNEL,
})

# Groups where the candidate submits ONE artifact, so at most one violation
# about that artifact can be observable. Picking any member removes the whole
# group from contention for the candidate's remaining severity slots.
# Add a group here whenever a new violation family shares a single artifact.
# #56: a candidate has ONE affiliation field and ONE set of platform profiles,
# so at most one affiliation violation can be true of them. These are not merely
# redundant together, they are contradictory: NOT_STATED means nothing was
# claimed, which leaves nothing for MISMATCH to disagree with, and MISMATCH
# (sweep shows a different org) and UNLISTED (sweep shows no org) are mutually
# exclusive statements about the same profiles.
_AFFILIATION_KINDS: frozenset[DiscrepancyKind] = frozenset({
    DiscrepancyKind.AFFILIATION_NOT_STATED,
    DiscrepancyKind.AFFILIATION_MISMATCH,
    DiscrepancyKind.AFFILIATION_UNLISTED,
})

_EXCLUSIVE_ARTIFACT_GROUPS: tuple[frozenset[DiscrepancyKind], ...] = (
    _CREDENTIAL_ARTIFACT_KINDS,
    _STEGO_ARTIFACT_KINDS,
    _AFFILIATION_KINDS,
)


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
    DiscrepancyKind.AFFILIATION_NOT_STATED: "No affiliation stated on the dossier.",
    DiscrepancyKind.DISPOSABLE_EMAIL:       "Email domain is a known disposable / throwaway service.",
    DiscrepancyKind.EMAIL_GITHUB_MISMATCH:  "GitHub commit email does not match the claimed email.",
    DiscrepancyKind.BREACH_HIT:             "Email appears in a known breach corpus.",
    DiscrepancyKind.SOCK_PUPPET_ACCOUNTS:   "Identical handle pattern found across suspicious platforms.",
    DiscrepancyKind.AFFILIATION_MISMATCH:   "Dossier affiliation does not match the org on their platform profiles.",
    DiscrepancyKind.AFFILIATION_UNLISTED:   "Platform profiles exist but list no organisation at all.",
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
    DiscrepancyKind.UNSALTED_STORAGE:       "Submitted credential is unsalted / plaintext-equivalent — visible in the clear on the dossier, no crack needed.",
    DiscrepancyKind.ENCRYPTED_PAYLOAD:      "Hidden image payload is XOR/encrypted — deliberate obfuscation.",
    DiscrepancyKind.CLAIMED_IP_MISMATCH:    "Claimed connection IP does not match the IP in the submitted logs.",
    DiscrepancyKind.WEAK_ENCRYPTION:        "Password stored with a weak encryption algorithm (MD5) — the algorithm is the problem, not necessarily the password.",
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


# ─── Typosquat handles (#53) ─────────────────────────────────────────────────
#
# Before #53, TYPOSQUAT_HANDLE was a violation in name only: `_make_handle`
# derives the handle purely from the candidate's own name and their archetype's
# style, so a "typosquatted" handle looked exactly like anyone else's. The only
# observable evidence was a free line in the Ghostscan identity block reading
# "handle resembles a trusted org/person -- possible typosquat", printed before
# a single hour was spent. The player wasn't detecting anything, they were
# reading a label — and a MAJOR violation was awarded for it.
#
# Now the handle is genuinely a lookalike of the organisation-style handle of a
# real listed professional affiliation, and the player has to compare the handle
# against the claimed org to catch it.

# The handle an elite org would plausibly hold. Deliberately short and
# org-shaped (not person-shaped) so a typosquat of it stands out from the
# name-derived handles every other candidate carries.
_ELITE_ORG_HANDLE: dict[str, str] = {
    "MIT CSAIL":                            "mitcsail",
    "Google Security Team":                 "googlesec",
    "Oxford Internet Institute":            "oxfordoii",
    "Stanford HAI":                         "stanfordhai",
    "DeepMind Safety Research":             "deepmindsafety",
    "Carnegie Mellon CyLab":                "cmucylab",
    "ETH Zurich Information Security Group": "ethzsec",
    # #56: the small legit orgs joined this map when Sneaky Bugger moved off the
    # elite pool. Without them, #53's typosquat falls back to squatting an org
    # the candidate never claimed, which loses the handle-versus-claim
    # comparison that made the violation readable in the first place.
    "Univ. of Fictional CS Dept.":           "fictionalcs",
    "Westmore Polytechnic Security Lab":     "westmoresec",
    "Reston Public Library Tech Branch":     "restontech",
    "Aegir Cybersecurity Cooperative":       "aegircyber",
    "Cordova College — Independent Study":   "cordovacs",
}


def _typosquat(rng: random.Random, base: str) -> str:
    """Deterministically mutate an org handle into a near-miss lookalike.

    Each mutation is a real-world typosquat technique, and each is chosen to
    survive a careless read: the result has to look right at a glance and wrong
    on inspection. Returns `base` unchanged only if no mutation applies, which
    the caller treats as "no squat" rather than shipping an exact match.
    """
    candidates: list[str] = []

    # Homoglyph substitution — the classic. One occurrence only; replacing
    # every 'o' with '0' reads as leetspeak, which is a different tell.
    for real, fake in (("o", "0"), ("l", "1"), ("i", "1"), ("e", "3"), ("s", "5")):
        i = base.find(real)
        if i != -1:
            candidates.append(base[:i] + fake + base[i + 1:])

    # 'rn' for 'm' — near-invisible in most terminal fonts.
    i = base.find("m")
    if i != -1:
        candidates.append(base[:i] + "rn" + base[i + 1:])

    # Doubled letter, dropped letter, adjacent transposition.
    if len(base) > 4:
        i = len(base) // 2
        candidates.append(base[:i] + base[i] + base[i:])
        candidates.append(base[:i] + base[i + 1:])
        if base[i] != base[i + 1]:
            candidates.append(base[:i] + base[i + 1] + base[i] + base[i + 2:])

    # Hyphen insertion — visually plausible for an org handle.
    if len(base) > 6:
        i = len(base) // 2
        candidates.append(base[:i] + "-" + base[i:])

    # Drop exact matches; an exact match is impersonation, not typosquatting,
    # and would make the violation unfindable by comparison.
    candidates = [c for c in candidates if c != base]
    return rng.choice(sorted(set(candidates))) if candidates else base


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
    allowed_violations: tuple[DiscrepancyKind, ...] = (),
    difficulty_band: str = "easy",
    claimed_affiliation: str = "",
) -> list[Discrepancy]:
    """Pick discrepancies for this candidate.

    Honors the archetype's budget. If a budget slot requires a severity
    that none of the eligible kinds can satisfy, the slot is skipped — the
    archetype specs above are written so this shouldn't happen.

    Two filters run before rolling:
      • The evidence-tier gate (#31) drops any kind whose revealing tool
        hasn't been taught by `day_number`, so an early-campaign candidate
        never carries evidence the player can't yet read.
      • The per-day whitelist (#32, `allowed_violations`) — when non-empty,
        only kinds in it may be planted. It INTERSECTS with the gate: a kind
        must be both whitelisted AND already taught.

    NOTE: for a tool-only archetype (e.g. Sneaky Bugger) these filters can
    empty the eligible pool on very early days — that's a day-CONTENT concern
    (the day's archetype mix should suit the tools taught so far, handled by
    #32/#15), not a bug here.

    Single-artifact exclusivity (`_EXCLUSIVE_ARTIFACT_GROUPS`): some violation
    families all describe the SAME submitted artifact, and the candidate only
    submits one of each. Every candidate submits exactly one password (issue
    #29) and exactly one image, so at most one credential kind and at most one
    stego kind may be chosen. Picking two from a group would leave the loser
    planted in ground truth — counting for scoring — with no artifact the
    player could ever inspect to find it. Choosing any member removes its whole
    group from contention for this candidate's remaining severity slots.
    """
    chosen: list[Discrepancy] = []
    used: set[DiscrepancyKind] = set()
    eligible = [
        k for k in spec.eligible_kinds
        if intro_day(k) <= day_number
        and (not allowed_violations or k in allowed_violations)
    ]
    # #56 - the trusted-organisation bypass. A claimed elite/trusted affiliation
    # can never be faked: it ALWAYS confirms in the sweep. That is deliberate and
    # is the player's reward for recognising one - a trusted domain plus a
    # trusted affiliation lets them skip the ghostscan step entirely, which is
    # The Professional's quick-admit read. Enforced here rather than in the
    # renderer so the ground truth itself can never contradict the guarantee.
    if claimed_affiliation in AFFILIATIONS_ELITE:
        eligible = [k for k in eligible
                    if k not in (DiscrepancyKind.AFFILIATION_MISMATCH,
                                 DiscrepancyKind.AFFILIATION_UNLISTED)]

    rng.shuffle(eligible)

    # #4, detection complexity: on a tool-biased band, prefer evidence that
    # costs ⏱ to read over evidence sitting in plain sight on the dossier.
    # A late-game candidate's discrepancies then sit behind the tool economy,
    # which is the whole point of the lever — a player coasting on free
    # dossier reads starts missing things.
    #
    # This is a STABLE sort applied to an already-seeded shuffle, so the
    # result stays a pure function of (seed, day, slot): within each tier the
    # shuffled order is preserved, only the tiers are reordered.
    if difficulty_band in config.DIFFICULTY_BANDS_TOOL_BIASED:
        eligible.sort(key=lambda k: _SEVERITY_REVEAL[k][0] == ToolName.DOSSIER)

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
                    for group in _EXCLUSIVE_ARTIFACT_GROUPS:
                        if kind in group:
                            used.update(group)
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
    forced_includes: dict[int, Archetype] | None = None,
) -> Archetype:
    """Deterministic archetype selection respecting the day's mix and any
    forced_includes (#32).

    forced_includes pins specific slots to a chosen archetype (e.g. the
    scripted White Hat on its day). Those picks are subtracted from the mix,
    and the remaining slots are filled from the day-scoped shuffled bag walked
    by NON-forced position — so the realized mix still equals the declared mix
    and generation stays deterministic (same spec + seed → same set).

    The bag is shuffled with a *day-scoped* RNG (no slot salt) so the walk is
    consistent across slots.
    """
    forced_includes = forced_includes or {}
    if slot_index in forced_includes:
        return forced_includes[slot_index]
    # Remove forced picks from the mix so the bag covers only free slots.
    remaining = dict(archetype_mix)
    for arch in forced_includes.values():
        if remaining.get(arch, 0) > 0:
            remaining[arch] -= 1
    day_rng = random.Random(stable_hash(game_seed, day_number, "archetype_bag") & 0xFFFFFFFF)
    bag = _shuffled_archetype_bag(day_rng, remaining)
    non_forced_pos = sum(1 for s in range(slot_index) if s not in forced_includes)
    return bag[non_forced_pos % len(bag)]


def generate(game_seed: int, day: Day, slot_index: int) -> Candidate:
    """Generate the candidate for one slot of one day. Deterministic."""

    archetype = _pick_archetype_for_slot(game_seed, day.number, day.archetype_mix,
                                          slot_index, day.forced_includes)
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
    discrepancies = _roll_discrepancies(rng_disc, spec, day.number,
                                        day.allowed_violations,
                                        day.difficulty_band,
                                        affiliation)

    # #53: a typosquat handle can only be built once we know the kind was
    # actually planted, so the handle is overridden here rather than inside
    # _make_handle. Nothing derived earlier depends on it - the email comes from
    # first/last/affiliation, and claimed_github is assigned further down.
    # #56 - make the affiliation evidence real rather than implied.
    #   NOT_STATED: the dossier field is literally blank. Previously this kind
    #     was planted on any "thin" affiliation ("Freelance Security Researcher"
    #     etc.), which is a stated-but-modest claim, not a missing one.
    #   MISMATCH:  the sweep will show a DIFFERENT org, recorded here so the
    #     renderer and the filter agree on which one.
    _kinds = {d.kind for d in discrepancies}
    actual_affiliation: str | None = None
    rng_affil = _seeded_rng(game_seed, day.number, slot_index, "affiliation")
    if DiscrepancyKind.AFFILIATION_NOT_STATED in _kinds:
        affiliation = NO_AFFILIATION_STATED
        # They do work somewhere - they just never said where. The sweep shows
        # their real org, which is what keeps this a purely DOSSIER violation
        # with no ghostscan signature of its own. Echoing the blank sentinel
        # into the sweep (as a first pass did) rendered "[[(none listed)]" as
        # though it were an organisation, which is nonsense and reads like the
        # UNLISTED violation.
        actual_affiliation = rng_affil.choice(sorted(AFFILIATIONS_LEGIT))
    elif DiscrepancyKind.AFFILIATION_MISMATCH in _kinds:
        others = [o for o in AFFILIATIONS_LEGIT if o != affiliation]
        actual_affiliation = rng_affil.choice(sorted(others))

    handle_squats: str | None = None
    if any(d.kind == DiscrepancyKind.TYPOSQUAT_HANDLE for d in discrepancies):
        rng_squat = _seeded_rng(game_seed, day.number, slot_index, "typosquat")
        # Squat the org the candidate actually claims where that is an elite
        # org, so the tell is a direct handle-vs-claim comparison. Otherwise
        # pick one - the handle still impersonates a real listed affiliation.
        target = (affiliation if affiliation in _ELITE_ORG_HANDLE
                  else rng_squat.choice(sorted(_ELITE_ORG_HANDLE)))
        squatted = _typosquat(rng_squat, _ELITE_ORG_HANDLE[target])
        if squatted != _ELITE_ORG_HANDLE[target]:
            handle = squatted
            handle_squats = target

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
    # UNSALTED_STORAGE behaves like a weak credential (instant-crack md5) —
    # `credential_unsalted` below additionally surfaces the plaintext on the
    # dossier directly, since that's now what actually reveals this kind.
    # WEAK_CREDENTIAL (#29 rework) = weak encryption + weak plaintext.
    # WEAK_ENCRYPTION = weak encryption ONLY — same MD5 shape (so the dossier
    # chip reads WEAK either way), but the plaintext behind it is one of the
    # obviously-strong passwords, so cracking it confirms the algorithm was
    # the problem, not the password.
    submitted_hash: str | None = None
    password_plain: str | None = None
    _has_leaked  = any(d.kind == DiscrepancyKind.LEAKED_PASSWORD for d in discrepancies)
    _has_weak    = any(d.kind == DiscrepancyKind.WEAK_CREDENTIAL  for d in discrepancies)
    _has_reuse   = any(d.kind == DiscrepancyKind.CROSS_BREACH_REUSE for d in discrepancies)
    _has_unsalt  = any(d.kind == DiscrepancyKind.UNSALTED_STORAGE   for d in discrepancies)
    _has_weakenc = any(d.kind == DiscrepancyKind.WEAK_ENCRYPTION    for d in discrepancies)
    rng_hc = random.Random(int(cand_id, 16) ^ 0xDEAD_C0DE)
    if _has_leaked or _has_reuse:
        password_plain = rng_hc.choice(_HC_LEAKED_PASSWORDS)
        submitted_hash = _hashlib.sha256(password_plain.encode()).hexdigest()
    elif _has_weak or _has_unsalt:
        password_plain = rng_hc.choice(_HC_WEAK_PASSWORDS)
        submitted_hash = _hashlib.md5(password_plain.encode()).hexdigest()
    elif _has_weakenc:
        password_plain = rng_hc.choice(_HC_STRONG_PASSWORDS)
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
        handle_squats=handle_squats,   # #53 - engine-only, filter names it
        actual_affiliation=actual_affiliation,   # #56 - engine-only
        claimed_breaches=(),
        notes="Submitted via standard intake form. Self-reported.",
        commit_email=commit_email,
        submitted_hash=submitted_hash,
        submitted_image_path=submitted_image_path,
        claimed_ip=claimed_ip,
        password_plain=password_plain,
        credential_unsalted=_has_unsalt,
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
