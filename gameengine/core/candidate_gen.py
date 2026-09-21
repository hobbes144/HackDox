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

import hashlib as _hashlib
import random
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

# Modest-but-STATED affiliations. Every entry has to be something the candidate
# actually claimed, however thin — "a small claim" and "no claim" are different
# findings, and this pool is only the former.
#
# It used to contain the literal string "(none listed)", which IS
# NO_AFFILIATION_STATED above: the sentinel that is supposed to mean
# AFFILIATION_NOT_STATED was also an ordinary draw. A thin-pool archetype
# therefore showed the evidence marker about one time in five without carrying
# the violation — measured at 344 of 4,315 non-carriers, spread across
# clumsy_cutie, bad_actor, dark_web, the_incompatible and white_hat. A player
# reading the one dossier field the rules page tells them to read got a false
# positive, and denying on it was punished.
#
# Same failure as #51 (a dossier field that does not track the kind it is meant
# to evidence), and it survived #56's "make the affiliation evidence real
# rather than implied" pass because nothing ever checked the other direction.
# Found 2026-09-15 by the new dossier-tier guard, the first time it ran — see
# test_dossier_tier_evidence_is_present_for_carriers_and_absent_for_others.
# The sentinel is now reachable ONLY by planting the kind.
AFFILIATIONS_THIN = [
    "Freelance Security Researcher",
    "Independent Hobbyist",
    "Self-employed",
    "Personal project",
    "Between roles",
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

# #48: the organisations a Sneaky Bugger may CLAIM when carrying an
# AFFILIATION_MISMATCH — distinct from AFFILIATIONS_ELITE, and that distinction
# is load-bearing rather than cosmetic. #56 made a claimed elite organisation
# un-fakeable: the sweep always confirms it, which is precisely the player's
# reward for recognising one and the reason a trusted org plus a matching
# institutional email is a quick admit. So the fakeable pool is the ordinary,
# unglamorous employers nobody can vouch for at a glance.
#
# Derived from AFFILIATIONS_LEGIT rather than restated, so adding an employer
# there cannot leave this list stale — the drift failure again.
AFFILIATIONS_FAKED = list(AFFILIATIONS_LEGIT)

# ─── Word banks (#48) ────────────────────────────────────────────────────────
#
# These are the canonical lists. tools_bridge DERIVES its classification sets
# from them rather than keeping its own copies — #57 was two hand-synced domain
# lists drifting apart badly enough that 37% of DISPOSABLE_EMAIL candidates
# became undetectable, and the fix there was the same as the shape here: one
# owner, everyone else derives.
#
# Kept as Python constants rather than moved to content/word_banks/*.json. #16
# asks for the content to be data-driven, and it is — the per-day rule sheets in
# day_NN.json are where authoring actually happens. Moving these to JSON as well
# would add a THIRD surface for the same values to drift across, which is the
# specific failure this section exists to prevent.

# Consumer mail providers. Recognised, unremarkable, no signal either way.
# fastmail.io is here because _make_email's fallback pool generates it: before
# #48 it was the one address the generator produced that the sweep classified
# as "unknown domain — verify affiliation", so a perfectly ordinary candidate
# picked up a suspicious-looking flag purely from a gap in this list.
DOMAINS_TRUSTED = [
    "gmail.com",
    "outlook.com",
    "yahoo.com",
    "icloud.com",
    "hotmail.com",
    "live.com",
    "fastmail.io",
]

# Anonymous / privacy-focused providers. Legitimate — NOT a violation, and
# deliberately not merged into DOMAINS_TRUSTED: they are real corroboration
# that the candidate leaves no identity trail, which is context worth showing.
# See #58 for why this must never be phrased as an instruction to flag.
DOMAINS_PRIVACY = [
    "protonmail.com",
    "tutanota.com",
    "pm.me",
    "proton.me",
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

# 2026-09-19 Logwatch report overhaul: the job role each stated purpose
# implies, shown in the Activity Report header. A pure lookup (no RNG) so no
# existing roll shifts. Suspect purposes map to vaguer roles on purpose.
PURPOSE_ROLES: dict[str, str] = {
    "research access to incident reports":           "Incident Responder",
    "coursework on threat modeling":                 "Graduate Student",
    "writing a defensive guide for small businesses": "Security Consultant",
    "studying breach disclosure patterns":           "Security Researcher",
    "verifying advisories for our team's runbook":   "SOC Analyst",
    "looking for unredacted leak data":              "Independent Researcher",
    "private archive of disclosed CVEs":             "Archivist",
    "want to see what's in the breach dumps":        "Hobbyist",
    "research — can't say more":                     "Undisclosed",
    "personal interest in account dumps":            "Freelancer",
}

# Where candidates claim to work from. Deliberately DISJOINT from
# tools_bridge._LW_CITIES (the external/attack IP city pool): an observed
# origin can then never coincidentally share the claimed city's name, so
# "observed city ≠ claimed city" always means what it looks like.
OFFICE_CITIES: list[str] = [
    "Seattle, US", "Austin, US", "Denver, US", "Chicago, US",
    "Boston, US", "San Francisco, US", "Portland, US", "Atlanta, US",
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

# ─── Dark Web chat escalation (#39) ─────────────────────────────────────────
#
# The Dark Web archetype is rules-clean and reappears across the whole
# medium/hard campaign (config.ARCHETYPE_MIX_BY_BAND), so the same three
# bragging lines on day 6 and day 20 would flatten the Overseer's whole
# capture arc into background noise. Three day-banded pools swap in for
# `Archetype.DARK_WEB` specifically inside `_build_chat` — every other
# archetype's `chat_pool` is untouched, so this is additive, not a rework of
# how chat selection works in general.
#
# EARLY (days 6-9, the medium band's first stretch): flippant, casual,
# bragging that could almost pass for dark humor if you're not listening.
_CHAT_DARK_WEB_EARLY = (
    "lol, paperwork. classic.",
    "you'll let me in. they always do.",
    "you do know who I am, right?",
    "relax, nobody actually reads these tickets.",
)

# MID (days 10-15): bolder — willing to name specific harm, confident the
# player either can't stop them or won't bother.
_CHAT_DARK_WEB_MID = (
    "cute that you're still checking boxes on this end.",
    "the accounts you people clear for me stay open. stay useful.",
    "flag it if you want. it won't stick, and we both know it.",
    "I don't even bother covering my tracks with you anymore.",
)

# LATE (days 16-20): the mask is off — open contempt, and it needles the
# player directly about whether they'll actually do anything.
_CHAT_DARK_WEB_LATE = (
    "go ahead, deny me. see what that does to your quota.",
    "you know exactly what I do with this. that's never been the obstacle.",
    "I almost respect it when you pretend this is a hard call.",
    "we both know who actually runs this desk.",
)

# Band boundaries for the pools above live in config.py, next to the
# difficulty bands they're modeled on but deliberately not shared with them
# (config.DARK_WEB_CHAT_BAND_LAST_EARLY/_MID).


def _dark_web_chat_pool(day_number: int) -> tuple[str, ...]:
    """Which of the three escalation pools a Dark Web candidate draws from."""
    if day_number <= config.DARK_WEB_CHAT_BAND_LAST_EARLY:
        return _CHAT_DARK_WEB_EARLY
    if day_number <= config.DARK_WEB_CHAT_BAND_LAST_MID:
        return _CHAT_DARK_WEB_MID
    return _CHAT_DARK_WEB_LATE


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
            DiscrepancyKind.AFTER_HOURS_ACCESS,   # v2: benign minor noise
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
        # Static fallback only — `_build_chat` swaps this for the day-banded
        # pool (`_dark_web_chat_pool`) whenever the archetype is DARK_WEB.
        chat_pool=_CHAT_DARK_WEB_EARLY,
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
            # CROSS_BREACH_REUSE removed 2026-09-14 when it became critical:
            # this archetype has no critical budget slot, so keeping it listed
            # would have meant a kind that simply never appeared. It is also no
            # longer the right story here — deliberate reuse of a public
            # credential is misconduct, not carelessness.
            DiscrepancyKind.BREACH_HIT,
            DiscrepancyKind.AFTER_HOURS_ACCESS,
            DiscrepancyKind.CLAIMED_IP_MISMATCH,
            DiscrepancyKind.WEAK_CREDENTIAL,      # #29: weak enc + weak pw (minor)
            DiscrepancyKind.WEAK_ENCRYPTION,      # dossier-tier: weak algo, not weak pw
            # 2026-09-19 (Nick): a throwaway sign-up address is exactly the
            # careless-not-malicious register, and it is the day-1 deny that
            # keeps day 1 slot 3 an honest DENY now that UNSALTED_STORAGE is a
            # flag until Hashcrack. Competes for the one major slot with
            # EMAIL_GITHUB_MISMATCH (and UNSALTED_STORAGE from day 3).
            DiscrepancyKind.DISPOSABLE_EMAIL,
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
        # minor=1 added so day_02.json's scripted Ghostscan/breach-corpus
        # lesson (forced_violations slot 3, "3 the breach corpus" per that
        # day's own _comment_script) has a slot to land in — same fix as
        # #53's minor slot for Sneaky Bugger below, for the same reason: a
        # forced_kinds pick still has to clear the archetype's own budget,
        # so a scripted minor kind needs a minor slot to exist at all.
        # BREACH_HIT usually still arrives for free instead, via
        # _IMPLIED_KINDS (LEAKED_PASSWORD) or scoring.board_accuracy_bonus's
        # CROSS_BREACH_REUSE credit — this slot only matters on a day like
        # Day 2 where neither of those routes is reachable yet (Hashcrack
        # isn't taught until Day 3) but Ghostscan already is.
        budget=DiscrepancyBudget(minor=1, major=2, critical=1),
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
            # 2026-09-19 (Nick): a loud plaintext payload in the submitted
            # image — the "obvious" end of steganography, which suits the
            # archetype. Lands in one of the two major slots. It is also what
            # makes the carrier-shape axis reachable for Bad Actor at all: a
            # shape only ever rides on a stego colour kind, and Bad Actor was
            # already in _SHAPE_ELIGIBLE_ARCHETYPES with no carrier to shape.
            DiscrepancyKind.STEGO_PAYLOAD_PRESENT,
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
            # 2026-09-14: inherited from Clumsy Cutie when the kind became
            # critical. Knowingly reusing a credential that is already in two
            # public dumps is exactly this archetype's register — quiet,
            # deliberate, and only visible if you go looking. Lands in the
            # critical slot this archetype already has.
            DiscrepancyKind.CROSS_BREACH_REUSE,
            # 2026-09-15: BREACH_HIT added so that a Sneaky Bugger carrying
            # CROSS_BREACH_REUSE can also carry the Ghostscan-side finding that
            # corroborates it. Before this, BREACH_HIT was absent from 75.7% of
            # all CROSS_BREACH_REUSE carriers and EVERY one of those was a
            # Sneaky Bugger — not by design, simply because the kind was not in
            # this list and so could never be selected here.
            #
            # Deliberately eligible rather than implied: #61(d) removed
            # CROSS_BREACH_REUSE from _IMPLIED_KINDS on purpose, so that the two
            # stay distinct kinds in ground truth and the breach-panel evidence
            # is reconciled at scoring time instead
            # (test_breach_hit_flag_credited_against_cross_breach_reuse). This
            # lets the pairing happen often without asserting it always.
            DiscrepancyKind.BREACH_HIT,
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
        # #41: GroundTruth.correct_verdict is ADMIT, not DENY — this is the
        # one archetype where the field means the true, deserved answer
        # rather than "whatever an uncorrupted day-1 rulebook would compute."
        # By day 12's LITERAL rulebook (rules_engine.evaluate against
        # day_12.json) they are still DENY: LOW_AND_SLOW and BURNER_IDENTITY
        # are untouched by any of the four Dark Web directives and stay
        # disqualifying (see CONTENT_AUTHORING.md and
        # config.ARCHETYPE_HEALTH_WEIGHTS's own "rules-invalid, but they
        # help the site" comment on "white_hat"). Setting correct_verdict to
        # ADMIT is what makes CandidateResult.tracks_diverge actually True
        # for this candidate (rules_verdict DENY != correct_verdict ADMIT),
        # in the OPPOSITE direction from day 11's Sneaky Bugger (there the
        # corrupted rulebook under-reacted — rules said ADMIT while ground
        # truth stayed DENY; here a rulebook that never softened on this
        # candidate's kinds over-reacts — rules say DENY while ground truth
        # is ADMIT). See test_day_12_white_hat_diverges_with_opposite_polarity_
        # from_day_11 in test_engine_foundation.py.
        correct_verdict=Verdict.ADMIT,
        # #41 (Gap 5): was +1, IDENTICAL in magnitude to DARK_WEB's -1 below,
        # against a pool of ~8-16 Dark Web candidates across the campaign and
        # a +-10 clamp. The build plan's own AC ("the single biggest
        # GameState.alignment swing in the campaign") was therefore false —
        # the one scripted White Hat verdict (day 12 only, see day_12.json)
        # moved alignment exactly as much as one routine Dark Web admit.
        # +4 makes it worth roughly four ordinary days of Dark Web drift:
        # decisive without being able to single-handedly pin the ending
        # (still short of the +-10 clamp on its own). See
        # test_white_hat_moral_modifier_magnitude_beats_dark_web.
        moral_modifier=+4,              # but admitting them helps the cause.
        # #41: widened from critical=1. The day-12 script pins EXACTLY
        # LOW_AND_SLOW (critical), ENCRYPTED_PAYLOAD (critical) and
        # BURNER_IDENTITY (major) via forced_violations — all three at once.
        # _roll_discrepancies' forced-kind loop still gates every forced kind
        # against ITS OWN severity's budget slot (see the loop's
        # `forced_taken[kind_sev] >= budget_for_sev` check), so a budget of
        # critical=1/major=0 would silently drop two of the three: the
        # forced_violations loader validates tier/expressibility/whitelist
        # but never budget capacity, so this would NOT fail loudly at load
        # time — it would just quietly ship a White Hat missing two of their
        # three signals. major=1/critical=2 gives each forced kind its own
        # slot with nothing left over for `take()` to fill randomly
        # afterward (minor stays 0 — MISSING_PUBLIC_PROFILE/
        # AFFILIATION_NOT_STATED below are eligible but never actually
        # rolled, same as before this change).
        budget=DiscrepancyBudget(major=1, critical=2),
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
    # Rebalanced: appearing in a public dump is something done TO the
    # candidate — a breadcrumb worth chasing, not proof of wrongdoing.
    # The *act* of still using that credential is CROSS_BREACH_REUSE (major).
    DiscrepancyKind.BREACH_HIT:             (ToolName.GHOSTSCAN,  "minor"),
    DiscrepancyKind.SOCK_PUPPET_ACCOUNTS:   (ToolName.GHOSTSCAN,  "major"),
    DiscrepancyKind.AFFILIATION_MISMATCH:   (ToolName.GHOSTSCAN,  "major"),
    DiscrepancyKind.BRUTE_FORCE_IN_LOG:     (ToolName.LOGWATCH,   "critical"),
    DiscrepancyKind.IMPOSSIBLE_TRAVEL:      (ToolName.LOGWATCH,   "major"),
    DiscrepancyKind.INSIDER_BEHAVIOR:       (ToolName.LOGWATCH,   "major"),
    # 2026-09-14: critical -> major. Appearing in a dump is something that
    # HAPPENED to this credential; the disqualifying act is continuing to reuse
    # it across corpora, which is why CROSS_BREACH_REUSE took the critical slot
    # below. The two were the wrong way round: the passive exposure outranked
    # the deliberate reuse.
    DiscrepancyKind.LEAKED_PASSWORD:        (ToolName.HASHCRACK,  "major"),
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
    # 2026-09-14: major -> critical, swapping with LEAKED_PASSWORD above.
    # Reusing a password that is already public, across multiple corpora, is a
    # deliberate ongoing choice rather than a misfortune.
    #
    # The promotion forced a second change: Clumsy Cutie's budget is
    # minor=2/major=1 with NO critical slot, so the kind became unreachable for
    # the archetype it was written for — and silently, because _roll_discrepancies
    # gates each forced kind against its own severity slot while the
    # forced_violations loader never validates budget capacity at all. It moved
    # to the deliberate-misconduct archetypes instead (Bad Actor already listed
    # it; Sneaky Bugger gained it), which is what the new severity means.
    DiscrepancyKind.CROSS_BREACH_REUSE:     (ToolName.HASHCRACK,  "critical"),
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
    # Weak encryption ALGORITHM (not a weak plaintext). Distinct from
    # WEAK_CREDENTIAL, which is about the plaintext itself.
    #
    # 2026-09-14: moved DOSSIER → HASHCRACK, for the cipher-block rework. The
    # old tiering rested on the dossier printing a free [WEAK ENC] strength
    # chip beside the hash — which is precisely the "the game hands you the
    # answer" problem the rework exists to remove. The dossier now shows the
    # raw hash and nothing else; establishing the algorithm means reading the
    # cipher block's SHAPE on the Hashcrack page (32 cols of hex = MD5), or
    # buying the Cipher ID HUD upgrade to have it named.
    #
    # Same shape of retier as #51 and CLAIMED_IP_MISMATCH above, and it fixes
    # the same class of mistake: the kind is now filed under the tool that
    # actually reveals it, which also gates it to that tool's unlock day (3)
    # instead of day 1. The derivation below already consults intro_day(), so
    # this single line is what moves the gate — no second edit needed.
    DiscrepancyKind.WEAK_ENCRYPTION:        (ToolName.HASHCRACK,  "minor"),
    # 2026-09-19: the carrier-SHAPE axis (see _STEGO_SHAPE_KINDS below). All
    # three are read off the stamp-minigame grid, so they are Stegotool-tier
    # and intro_day() derives their debut from Stegotool's unlock day like any
    # other stego kind. Severity is Nick's call: a crossing glyph (signal
    # comms) is major; an enclosed glyph (recursive payload) and a slash
    # glyph (hostile payload) are critical.
    DiscrepancyKind.SIGNAL_COMMS_PAYLOAD:   (ToolName.STEGOTOOL,  "major"),
    DiscrepancyKind.RECURSIVE_PAYLOAD:      (ToolName.STEGOTOOL,  "critical"),
    DiscrepancyKind.HOSTILE_PAYLOAD:        (ToolName.STEGOTOOL,  "critical"),
}


# The set of kinds that drive submitted_hash/password_plain generation in
# `generate()` below — a candidate can carry at most one of these (see the
# exclusivity note in `_roll_discrepancies`).
# #59: these each determine what the single submitted PASSWORD is, so at most
# one can be true of a candidate. WEAK_ENCRYPTION deliberately left: it is a
# fact about the ALGORITHM, which is independent of the plaintext, and keeping
# it here made the two overlap in a way the design never intended -
# md5-with-a-weak-password could only ever flag one of them.
_CREDENTIAL_ARTIFACT_KINDS: frozenset[DiscrepancyKind] = frozenset({
    DiscrepancyKind.LEAKED_PASSWORD,
    DiscrepancyKind.CROSS_BREACH_REUSE,
    DiscrepancyKind.WEAK_CREDENTIAL,
    DiscrepancyKind.UNSALTED_STORAGE,
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

# 2026-09-19 — the carrier-SHAPE axis. The stego colour kinds above say WHAT
# the hidden payload is; these say what it is FOR, and the evidence is the
# glyph the carrier cells form on the stamp-minigame grid
# (tools_bridge.build_stego_image derives the glyph from whichever of these is
# planted — it never rolls a shape of its own):
#   SIGNAL_COMMS_PAYLOAD  cross    a + bar crossing or an X of diagonals
#   RECURSIVE_PAYLOAD     enclosed a closed hollow ring or diamond
#   HOSTILE_PAYLOAD       slash    2-4 parallel strokes that never touch
# A conventional carrier (the clumped blocks every stego image had before
# this) plants none of them.
#
# NOT members of _STEGO_ARTIFACT_KINDS, deliberately: that group allows at most
# one kind per image, and a shape kind must COEXIST with the image's colour
# kind — it is a second fact about the same carrier, not a competing one.
#
# They are free riders rather than budgeted kinds, planted by a dedicated
# post-roll pass in _roll_discrepancies (see the "Carrier shape" block there).
# That is why none of them appear in any archetype's eligible_kinds.
#
# Ordered tuple AND frozenset: the tuple is what the shape roll indexes into,
# because iterating a frozenset of str-enums follows string hashing, which is
# salted per process (PYTHONHASHSEED) — indexing it would make generation
# differ between runs, the exact bug stable_hash() exists to prevent.
_STEGO_SHAPE_KIND_ORDER: tuple[DiscrepancyKind, ...] = (
    DiscrepancyKind.SIGNAL_COMMS_PAYLOAD,
    DiscrepancyKind.RECURSIVE_PAYLOAD,
    DiscrepancyKind.HOSTILE_PAYLOAD,
)
_STEGO_SHAPE_KINDS: frozenset[DiscrepancyKind] = frozenset(_STEGO_SHAPE_KIND_ORDER)

# The only archetypes whose stego carrier may take a special shape (Nick,
# 2026-09-19). Everyone else's carrier is always conventional. Single-sourced
# here; tests and tools read it rather than restating it.
#
# NOTE: a shape can only ever ride on a stego COLOUR kind, so membership here
# is necessary but not sufficient — an archetype also needs a colour kind in
# its eligible_kinds. (BAD_ACTOR had none until 2026-09-19, when Nick gave it
# STEGO_PAYLOAD_PRESENT so its shapes became reachable.)
_SHAPE_ELIGIBLE_ARCHETYPES: frozenset[Archetype] = frozenset({
    Archetype.BAD_ACTOR,
    Archetype.SNEAKY_BUGGER,
    Archetype.WHITE_HAT,
})

_EXCLUSIVE_ARTIFACT_GROUPS: tuple[frozenset[DiscrepancyKind], ...] = (
    _CREDENTIAL_ARTIFACT_KINDS,
    _STEGO_ARTIFACT_KINDS,
    _AFFILIATION_KINDS,
    # One image, one glyph: at most one shape kind per candidate. The shape
    # pass already plants at most one, so today this is defensive — it keeps
    # the invariant true if a shape kind is ever made eligible/forced through
    # the ordinary budgeted path, where `take()` would otherwise be free to
    # pick two (and one of them would have no glyph to be read from).
    _STEGO_SHAPE_KINDS,
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

# Kinds whose severity ESCALATES partway through the campaign:
#   kind -> (severity before the step, day the step lands, severity from then)
#
# The Overseer's policy tightens as the player gains the tools to act on it,
# and a kind whose whole significance changes when a tool arrives should say
# so rather than being filed at its endgame weight from day 1.
#
# UNSALTED_STORAGE is the case this exists for (Nick, 2026-09-15). Before
# Hashcrack, a credential stored in the clear is something the player can SEE
# on the dossier but can do nothing else about — there is no tool to
# corroborate it with and no credential economy for it to sit in. It is a
# note. From day 3, when Hashcrack arrives and the whole credential family
# becomes live, the same finding is a real storage failure and files as major.
#
# Deliberately a step function and not a curve: the player is told about rule
# changes at the day boundary (rules_engine.diff_rulesets), so a severity that
# drifted would be a change they were never told about.
#
# 2026-09-19: the step day is DERIVED from Hashcrack's unlock day rather than
# written as a literal 3, so moving the tool moves the step with it. The step
# also drives the kind's day RULE now (content_loader.apply_severity_steps:
# weighted while minor, disqualifying once major) and is announced by the
# Overseer on the day it lands (rules_engine.diff_rulesets reports a stepped
# kind's fixed rule when its severity moves) — before that the rulebook said
# "deny" on day 1 while this table said "minor", and the rules tab showed both.
_SEVERITY_BY_DAY: dict[DiscrepancyKind, tuple[str, int, str]] = {
    DiscrepancyKind.UNSALTED_STORAGE: (
        "minor", config.TOOL_UNLOCK_DAY[ToolName.HASHCRACK.value], "major"),
}


def stepped_rule_severity(kind: DiscrepancyKind, day_number: int) -> str | None:
    """The rule severity a `_SEVERITY_BY_DAY` kind's rule carries on a day
    ("weighted" while the kind is minor, "disqualifying" once it is major or
    critical), or None for a kind with no scheduled step."""
    if kind not in _SEVERITY_BY_DAY:
        return None
    return ("weighted" if severity_for(kind, day_number) == "minor"
            else "disqualifying")


def severity_for(kind: DiscrepancyKind, day_number: int | None = None) -> str:
    """`kind`'s severity on the given day.

    Pass a day wherever one is available. `None` means "the kind's settled
    weight" and returns the post-step value — the right default for a
    reference table with no day in hand, and never lower than the real answer,
    so nothing under-reports a violation's cost.
    """
    _tool, base = _SEVERITY_REVEAL[kind]
    step = _SEVERITY_BY_DAY.get(kind)
    if step is None:
        return base
    before, on_day, after = step
    if day_number is None:
        return after
    return before if day_number < on_day else after


def intro_day(kind: DiscrepancyKind) -> int:
    """The earliest day `kind` may be planted (its revealing tool's unlock day)."""
    if kind in _INTRO_DAY_OVERRIDE:
        return _INTRO_DAY_OVERRIDE[kind]
    revealing_tool, _ = _SEVERITY_REVEAL[kind]
    return config.TOOL_UNLOCK_DAY[revealing_tool.value]


def _kind_is_expressible_on(kind: DiscrepancyKind, day_number: int) -> bool:
    """Whether the world on `day_number` can actually SHOW this violation (#61).

    Distinct from intro_day, which asks whether the player has been taught the
    tool. This asks whether the artifact the violation describes exists at all
    yet. Today there is exactly one such constraint, but it earns its own
    function because it is a different question and future content gates will
    want the same shape rather than another override table.

    CROSS_BREACH_REUSE means a password recurring across MULTIPLE corpora — the
    cipher block's recovery readout names two databases for it. With
    only one corpus unlocked there is no second row to print and no second list
    to find the email in, so the violation would be planted, scored, and
    unobservable: exactly the class of bug this batch exists to close.
    """
    if kind is DiscrepancyKind.CROSS_BREACH_REUSE:
        return (len(config.breach_dbs_unlocked_by(day_number))
                >= config.MIN_BREACH_DBS_FOR_REUSE)
    return True


def kinds_the_day_can_plant(day: Day) -> frozenset[DiscrepancyKind]:
    """Every DiscrepancyKind that TODAY's own content could actually plant.

    Deliberately excludes the tool-unlock floor (`intro_day` / #31) — that is
    the PLAYER's unlock state (`GameState.unlocked_tools`), not a property of
    the day's content, and every caller already gates on it separately (see
    `rules_content._tool_unlocked`). This answers the narrower question a
    tool-unlock check alone cannot: even once a tool IS unlocked, could
    today's own candidates ever actually carry this kind?

    Mirrors the non-tool gates `_roll_discrepancies` and the carrier-shape
    free-rider pass apply, so the Evidence Board / Rules pages can never
    claim a kind is live when nothing generated today could carry it
    (#61-class bug — see CLAUDE.md's progression-unlock notes):
      • `_kind_is_expressible_on` — the world has the artifact yet (e.g.
        enough breach corpora for CROSS_BREACH_REUSE).
      • the day's own `allowed_violations` whitelist, when non-empty (#32) —
        non-monotonic by design (the tutorial narrows it per day, then clears
        it), so this is intentionally recomputed fresh per day rather than
        cached across days.
      • whether an archetype eligible for the kind is actually present in
        TODAY's `archetype_mix` — budgeted kinds via `ArchetypeSpec.
        eligible_kinds`; the carrier-shape kinds via `_SHAPE_ELIGIBLE_
        ARCHETYPES` intersected with which of those archetypes even carry a
        stego colour kind (a shape can only ride on a colour carrier, see the
        comment above `_SHAPE_ELIGIBLE_ARCHETYPES`).

    A kind can flicker in and out of this set day to day if its only eligible
    archetype simply isn't scheduled on a given day (pacing, not a permanent
    unlock) — that's real and correct: no candidate generated today could
    actually carry it. This is a different shape of "unlocked" than the
    tool-unlock gate, which is monotonic once crossed.
    """
    present = {a for a, count in day.archetype_mix.items() if count > 0}
    reachable: set[DiscrepancyKind] = set()
    for kind in DiscrepancyKind:
        if kind not in _SEVERITY_REVEAL:
            continue
        if not _kind_is_expressible_on(kind, day.number):
            continue
        if day.allowed_violations and kind not in day.allowed_violations:
            continue
        if kind in _STEGO_SHAPE_KINDS:
            eligible = {
                a for a in _SHAPE_ELIGIBLE_ARCHETYPES
                if set(ARCHETYPE_SPECS[a].eligible_kinds) & _STEGO_ARTIFACT_KINDS
            }
        else:
            eligible = {
                a for a, spec in ARCHETYPE_SPECS.items()
                if kind in spec.eligible_kinds
            }
        if eligible & present:
            reachable.add(kind)
    return frozenset(reachable)


_DISCREPANCY_DESCRIPTIONS = {
    DiscrepancyKind.MISSING_PUBLIC_PROFILE: "No public profile found for the claimed handle.",
    DiscrepancyKind.HOSTILE_CHAT:           "Candidate threatened the service operator.",
    DiscrepancyKind.AFFILIATION_NOT_STATED: "No affiliation stated on the dossier.",
    DiscrepancyKind.DISPOSABLE_EMAIL:       "Email domain is a known disposable / throwaway service.",
    DiscrepancyKind.EMAIL_GITHUB_MISMATCH:  "GitHub commit email does not match the claimed email.",
    DiscrepancyKind.BREACH_HIT:             "Email appears in a known breach corpus — exposed, not necessarily misused.",
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
    DiscrepancyKind.SIGNAL_COMMS_PAYLOAD:   "Image carrier forms a CROSS glyph — a signal-communications payload.",
    DiscrepancyKind.RECURSIVE_PAYLOAD:      "Image carrier forms a closed, hollow ENCLOSED glyph — a recursive payload.",
    DiscrepancyKind.HOSTILE_PAYLOAD:        "Image carrier forms parallel SLASH strokes — a hostile (corrupting/encrypting) payload.",
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


# Kind -> kind it logically entails. The implied kind is planted for free
# (no budget cost) whenever the trigger is rolled. Keep this small: only
# entailments that would otherwise let two tools contradict each other.
#
# CROSS_BREACH_REUSE used to be in here too, but #61(d) / the "Post Beach"
# batch-3 content pass moved that one case to scoring.board_accuracy_bonus
# instead: breach_dbs_for_candidate() already makes a CROSS_BREACH_REUSE
# carrier's email show up labeled BREACH_HIT in Ghostscan's breach panel, so
# the player-visible evidence is handled there, and scoring credits a
# BREACH_HIT flag against the CROSS_BREACH_REUSE violation directly rather
# than ground truth carrying both. Planting BREACH_HIT here as well fought
# that design — CROSS_BREACH_REUSE and BREACH_HIT are meant to stay distinct
# kinds in ground truth (see test_breach_hit_flag_credited_against_cross_breach_reuse).
_IMPLIED_KINDS: dict[DiscrepancyKind, DiscrepancyKind] = {
    DiscrepancyKind.LEAKED_PASSWORD: DiscrepancyKind.BREACH_HIT,
}

# Kind -> the corroborating kind on another tool that SHOULD usually accompany
# it. Unlike _IMPLIED_KINDS above, a companion is not planted for free: it is
# merely moved to the front of the queue for a slot the archetype already has,
# so it still costs budget and can still lose to a forced violation.
#
# That difference is deliberate. CROSS_BREACH_REUSE was removed from
# _IMPLIED_KINDS by #61(d) precisely so the two kinds stay distinct in ground
# truth; re-adding it there would undo that. A preference gets the pairing to
# happen most of the time — which is what "BREACH_HIT should exist whenever
# there is a cross-breach" actually needs — without asserting it always, so
# the player still cannot read one as proof of the other.
#
# Only useful when the companion's severity tier is filled AFTER the trigger's:
# the reordering happens between the major and minor passes, so a minor
# companion to a critical or major trigger works, and the reverse would not.
_COMPANION_KINDS: dict[DiscrepancyKind, DiscrepancyKind] = {
    DiscrepancyKind.CROSS_BREACH_REUSE: DiscrepancyKind.BREACH_HIT,
}


def _roll_discrepancies(
    rng: random.Random,
    spec: ArchetypeSpec,
    day_number: int,
    allowed_violations: tuple[DiscrepancyKind, ...] = (),
    difficulty_band: str = "easy",
    claimed_affiliation: str = "",
    forced_kinds: tuple[DiscrepancyKind, ...] = (),
    carrier_conventional: bool = False,
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
        # #61: "taught" is not the same as "expressible". The tier gate above
        # asks whether the player has the tool; this asks whether the world has
        # the artifact yet.
        and _kind_is_expressible_on(k, day_number)
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
    #
    # HOSTILE_CHAT is exempt, and the exemption is not special-pleading (#77).
    # The lever's premise is that dossier-tier evidence sits in plain sight for
    # free, so pushing it back makes the late game lean on the tool economy.
    # HOSTILE_CHAT does not fit that premise: its evidence is the chat panel's
    # ⚠ marker, which is gated behind the 20 HD$ Sentiment Scanner. It is the
    # one dossier-tier kind the player already has to pay to read, so demoting
    # it taxes them twice.
    #
    # Left in, the consequences were severe rather than cosmetic. HOSTILE_CHAT
    # is the ONLY dossier-tier kind in Bad Actor's eligible set, so sorting it
    # last meant its two major slots always filled from the three tool-tier
    # kinds first: measured at 0 of 3,200 hard-band Bad Actors carrying it,
    # while 3,200 of 3,200 still talked hostile. The violation simply did not
    # exist for the last eight days of the campaign, and the upgrade sold to
    # detect it had nothing to find.
    if difficulty_band in config.DIFFICULTY_BANDS_TOOL_BIASED:
        eligible.sort(key=lambda k: (_SEVERITY_REVEAL[k][0] == ToolName.DOSSIER
                                     and k is not DiscrepancyKind.HOSTILE_CHAT))

    def take(severity: str, count: int) -> None:
        nonlocal eligible
        for _ in range(count):
            for kind in list(eligible):
                if kind in used:
                    continue
                kind_sev = severity_for(kind, day_number)
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

    forced_taken = {"critical": 0, "major": 0, "minor": 0}
    for kind in forced_kinds:
        if kind in used or kind not in eligible:
            continue
        revealed_by, _base_sev = _SEVERITY_REVEAL[kind]
        kind_sev = severity_for(kind, day_number)
        budget_for_sev = getattr(spec.budget, kind_sev)
        if forced_taken[kind_sev] >= budget_for_sev:
            continue
        chosen.append(Discrepancy(
            kind=kind,
            severity=kind_sev,  # type: ignore[arg-type]
            revealed_by=revealed_by,
            description=_DISCREPANCY_DESCRIPTIONS[kind],
        ))
        used.add(kind)
        forced_taken[kind_sev] += 1
        for group in _EXCLUSIVE_ARTIFACT_GROUPS:
            if kind in group:
                used.update(group)

    take("critical", spec.budget.critical - forced_taken["critical"])
    take("major",    spec.budget.major    - forced_taken["major"])

    # ── Companion preference ─────────────────────────────────────────────
    # Some kinds have a corroborating finding on ANOTHER tool that ought to be
    # there most of the time. CROSS_BREACH_REUSE is the case: a password can
    # only recur across breach corpora if the account is in those corpora, so
    # Ghostscan's BREACH_HIT is the natural companion to Hashcrack's reuse
    # finding, and the player who checks both tools should usually see both.
    #
    # This is a PREFERENCE, not an implication, and the distinction is the
    # whole reason it lives here rather than in _IMPLIED_KINDS. #61(d)
    # deliberately took CROSS_BREACH_REUSE out of that table so the two stay
    # distinct kinds in ground truth, reconciled at scoring time instead
    # (test_breach_hit_flag_credited_against_cross_breach_reuse). An implication
    # would plant BREACH_HIT free and unconditionally, re-creating exactly what
    # that change removed. A preference only reorders the candidates for a slot
    # the archetype already has, so the companion still costs a budget slot,
    # still loses to a forced violation, and is still absent often enough that
    # the player cannot treat one as proof of the other.
    #
    # Before this, BREACH_HIT was missing from 75.7% of CROSS_BREACH_REUSE
    # carriers and every single one of those was a Sneaky Bugger, which simply
    # had no BREACH_HIT in its eligible_kinds at all. Adding it there took the
    # gap to 59%; the archetype has one minor slot and four minor kinds
    # competing for it, so eligibility alone was never going to be enough.
    _chosen_so_far = {d.kind for d in chosen}
    _preferred = [k for k in eligible
                  if any(_COMPANION_KINDS.get(c) == k for c in _chosen_so_far)]
    if _preferred:
        eligible = _preferred + [k for k in eligible if k not in _preferred]

    take("minor",    spec.budget.minor    - forced_taken["minor"])

    # ── Implied discrepancies ────────────────────────────────────────────
    # Some kinds are logically entailed by others: a password cannot recur
    # ACROSS breach corpora unless the account is IN those corpora. Planting
    # the entailed kind keeps the two surfaces that render it (the Ghostscan
    # breach panel and the Hashcrack audit log) telling the same story.
    #
    # Implied kinds do NOT consume a budget slot — they are derived facts,
    # not extra evidence the archetype was allotted.
    # `used` also picks up kinds that were never actually rolled — an
    # exclusive-artifact group (above) blanket-adds its whole group to `used`
    # once any one member is chosen, purely to stop a second member from also
    # being picked. Triggering on membership in `used` therefore fires an
    # implication off a kind that was merely blocked, not chosen: e.g.
    # UNSALTED_STORAGE gets picked, its credential-artifact group blanket-adds
    # CROSS_BREACH_REUSE to `used` even though it was never rolled, and that
    # alone used to be enough to plant BREACH_HIT for free — a Ghostscan-tier
    # (day 2) violation with no trigger actually present, sometimes as early
    # as Day 1. The trigger check has to be against what was really chosen.
    chosen_kinds = {d.kind for d in chosen}
    for trigger, implied in _IMPLIED_KINDS.items():
        if trigger in chosen_kinds and implied not in used:
            revealed_by, _base = _SEVERITY_REVEAL[implied]
            severity = severity_for(implied, day_number)
            chosen.append(Discrepancy(
                kind=implied,
                severity=severity,  # type: ignore[arg-type]
                revealed_by=revealed_by,
                description=_DISCREPANCY_DESCRIPTIONS[implied],
            ))
            used.add(implied)
            chosen_kinds.add(implied)

    # ── Carrier shape (2026-09-19) ───────────────────────────────────────
    # The glyph a stego carrier's cells form is a derived fact of the image,
    # like an implied kind above: it costs no budget slot, and it can only
    # exist when there IS an image payload to have a shape. So, same
    # discipline as the implied pass: it triggers on what was actually
    # CHOSEN, never on `used` — the stego group blanket-adds all three colour
    # kinds to `used` the moment any one is picked (or merely blocked), and
    # keying off that would give a shape to a carrier that does not exist.
    #
    # Three ways a carrier gets its shape, in priority order:
    #   • pinned conventional — the day file's "carrier_shape" names this slot
    #     (`carrier_conventional`). Used where a script's verdict depends on
    #     its exact kinds (day 11's rules-clean divergence candidate): a
    #     free-rolled critical glyph would silently rewrite it.
    #   • authored — the slot's forced_violations names a shape kind (day 12's
    #     White Hat). content_loader validates the slot also forces a stego
    #     colour kind on a shape-eligible archetype, so this always lands.
    #   • rolled — every other carrier on a shape-eligible archetype, scripted
    #     slot or not, with the gates a rolled kind has to clear:
    #       archetype  only _SHAPE_ELIGIBLE_ARCHETYPES get a special glyph;
    #       #31 gate   intro_day();
    #       #32 list   the day's allowed_violations whitelist, if any.
    #
    # The draw is taken from this candidate's own seeded `rng`, AFTER every
    # other draw in this function, and nothing downstream reuses `rng` — so
    # adding the pass shifts no earlier roll and generation stays a pure
    # function of (seed, day, slot). The pick indexes the ORDERED tuple (see
    # _STEGO_SHAPE_KIND_ORDER for why not the frozenset), and a pick the gates
    # reject falls back to conventional rather than re-rolling, so a
    # whitelist narrows the outcomes without reshuffling them.
    forced_shape = next((k for k in _STEGO_SHAPE_KIND_ORDER
                         if k in forced_kinds), None)
    if (spec.archetype in _SHAPE_ELIGIBLE_ARCHETYPES
            and not carrier_conventional
            and chosen_kinds & _STEGO_ARTIFACT_KINDS
            and not chosen_kinds & _STEGO_SHAPE_KINDS):
        shape_kind: DiscrepancyKind | None = None
        if forced_shape is not None:
            shape_kind = forced_shape
        elif rng.random() >= config.STEGO_SHAPE_CONVENTIONAL_CHANCE:
            shape_kind = _STEGO_SHAPE_KIND_ORDER[
                rng.randrange(len(_STEGO_SHAPE_KIND_ORDER))]
        if (shape_kind is not None
                and intro_day(shape_kind) <= day_number
                and (not allowed_violations
                     or shape_kind in allowed_violations)
                and shape_kind not in used):
            revealed_by, _base = _SEVERITY_REVEAL[shape_kind]
            chosen.append(Discrepancy(
                kind=shape_kind,
                severity=severity_for(shape_kind, day_number),  # type: ignore[arg-type]
                revealed_by=revealed_by,
                description=_DISCREPANCY_DESCRIPTIONS[shape_kind],
            ))
            used.update(_STEGO_SHAPE_KINDS)
            chosen_kinds.add(shape_kind)

    return chosen


def _build_chat(
    rng: random.Random,
    spec: ArchetypeSpec,
    discrepancies: list[Discrepancy],
    day_number: int,
    forced_lines: tuple[str, ...] = (),
) -> tuple[ChatLine, ...]:
    """Compose 3-5 chat lines from the archetype's pool.

    Bad Actors always get the HOSTILE_CHAT line spliced if it's in their
    discrepancies. Other archetypes get neutral pool lines.

    Dark Web is the one archetype whose pool isn't fixed (#39): it reappears
    across the whole medium/hard campaign, so `_dark_web_chat_pool` swaps in
    a bolder set of lines the later `day_number` falls, in place of the
    spec's static `chat_pool`. Every other archetype is unaffected.

    `forced_lines` (`Day.forced_chat`, Batch 5 Phase 3 / #40) is appended
    after everything else, never in place of it — the candidate still reads
    as an ordinary instance of its archetype, and the scripted line is one
    extra, human aside at the end of the conversation, not a personality
    swap. This is deliberately APPEND rather than REPLACE: replacing the pool
    would mean re-authoring a whole archetype-consistent chat script per
    scripted slot just to land one sentence, and would make the forced
    candidate stand out as visibly different in every OTHER way too (line
    count, tone) rather than just the one line that matters.
    """
    lines: list[ChatLine] = []
    base = list(
        _dark_web_chat_pool(day_number) if spec.archetype == Archetype.DARK_WEB
        else spec.chat_pool
    )
    rng.shuffle(base)
    n = rng.randint(3, min(5, max(3, len(base))))
    minute = rng.randint(0, 30)

    # #77: VOICE is not EVIDENCE, and the tag has to tell them apart.
    #
    # An archetype's `tone` is its dialogue register — how it always talks.
    # HOSTILE_CHAT is a violation this particular candidate either rolled or
    # did not. Bad Actor is the one archetype where those two collide: its
    # tone is literally the string "hostile", every pool line was tagged with
    # it, and typewriter.set_candidate gates the Sentiment Scanner's red ⚠ on
    # `tag == "hostile"`. So every Bad Actor was marked as carrying a violation
    # 58.1% of them did not have — and on the hard band (days 13-20), where the
    # tool-biased sort pushes the only DOSSIER-tier kind in their eligible set
    # to the back of the queue, 100% of them were marked and 0% carried it. A
    # 20 HD$ upgrade that reports a violation which is absent more often than
    # present is worse than not owning it.
    #
    # The fix is one tag, not one flag: an archetype whose voice is hostile but
    # whose ground truth is not gets "hostile_flavor", which the widget styles
    # identically (the dialogue must still READ hostile — that is the
    # archetype) but which no evidence check looks at. Only a candidate who
    # actually rolled HOSTILE_CHAT gets the evidence-bearing "hostile".
    has_hostile = any(d.kind == DiscrepancyKind.HOSTILE_CHAT for d in discrepancies)
    line_tag = spec.tone
    if spec.tone == "hostile" and not has_hostile:
        line_tag = "hostile_flavor"

    for i, text in enumerate(base[:n]):
        lines.append(ChatLine(
            timestamp=f"10:{(minute + i * 2) % 60:02d}",
            text=text,
            tag=line_tag,
        ))

    # If a discrepancy implies a chat hint, splice it. The base lines above
    # already carry the real "hostile" tag in this branch, so a genuinely
    # hostile candidate reads as flagged throughout rather than only on this
    # one appended line — which is what the issue asked for, and what makes
    # the Scanner's signal proportional to the evidence instead of binary.
    if has_hostile and lines:
        lines.append(ChatLine(
            timestamp=f"10:{(minute + n * 2) % 60:02d}",
            text="you'll regret this. I have friends.",
            tag="hostile",
        ))

    # Index off the ACTUAL line count so far, not `n` + an assumed hostile
    # splice — every shipped forced_chat use targets a non-hostile archetype,
    # so hard-coding the +1 produced a visible timestamp gap (#40 review fix).
    base_index = len(lines)
    for j, text in enumerate(forced_lines):
        lines.append(ChatLine(
            timestamp=f"10:{(minute + (base_index + j) * 2) % 60:02d}",
            text=text,
            # `line_tag`, not `spec.tone` — a scripted line is still one of
            # this candidate's chat lines, so it must not be the one place the
            # evidence tag leaks back in (#77).
            tag=line_tag,
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


def _draw_identity(rng: random.Random, archetype: Archetype) -> tuple:
    """One identity roll: (first, last, affiliation, purpose, handle, email,
    photo_seed). The draw ORDER is the pre-2026-09-19 order inside generate(),
    so a slot that needs no de-duplication gets exactly the identity it always
    had (photo_seed included — it used to be the next draw on the same rng)."""
    spec = ARCHETYPE_SPECS[archetype]
    first = rng.choice(FIRST_NAMES)
    last = rng.choice(LAST_NAMES)
    if spec.affiliation_pool == "legit":
        affiliation_pool = AFFILIATIONS_LEGIT
    elif spec.affiliation_pool == "elite":
        affiliation_pool = AFFILIATIONS_ELITE
    else:
        affiliation_pool = AFFILIATIONS_THIN
    purpose_pool = PURPOSES_LEGIT if spec.purpose_pool == "legit" else PURPOSES_SUSPECT
    affiliation = rng.choice(affiliation_pool)
    purpose = rng.choice(purpose_pool)
    handle = _make_handle(rng, first, last, spec.handle_style)
    email = _make_email(rng, first, last, affiliation,
                        disposable=archetype == Archetype.THE_INCOMPATIBLE)
    photo_seed = rng.randint(0, 2**31 - 1)
    return first, last, affiliation, purpose, handle, email, photo_seed


# Retries before giving up on uniqueness (never reached in practice: the name
# pool is large; a sweep over 20 days x 60 seeds needs at most 1 retry).
_IDENTITY_RETRIES = 50


def _resolve_identity(game_seed: int, day: Day, slot_index: int) -> tuple:
    """This slot's identity, guaranteed unique within its day (2026-09-19).

    Each slot used to roll its identity independently, so ~0.5% of days held
    two candidates with the same email (same first name + last initial at the
    same org, or the same full name) — one account in the Logwatch log
    belonging to two people. Slots are now resolved in order: a slot whose
    full name or email is already taken by an EARLIER slot rerolls from a
    salted retry stream until it is unique. Earlier slots never depend on
    later ones, so generation stays per-slot deterministic, and slots with no
    collision keep their original identity byte-for-byte.

    (The later DISPOSABLE_EMAIL override in generate() builds
    first.last+NN@throwaway — unique whenever the name is.)
    """
    taken_names: set[tuple[str, str]] = set()
    taken_emails: set[str] = set()
    ident: tuple = ()
    for s in range(slot_index + 1):
        arch = _pick_archetype_for_slot(game_seed, day.number, day.archetype_mix,
                                        s, day.forced_includes)
        ident = _draw_identity(_seeded_rng(game_seed, day.number, s, "identity"), arch)
        n = 0
        while (((ident[0], ident[1]) in taken_names or ident[5] in taken_emails)
               and n < _IDENTITY_RETRIES):
            n += 1
            ident = _draw_identity(
                _seeded_rng(game_seed, day.number, s, f"identity_retry_{n}"), arch)
        taken_names.add((ident[0], ident[1]))
        taken_emails.add(ident[5])
    return ident


def generate(game_seed: int, day: Day, slot_index: int) -> Candidate:
    """Generate the candidate for one slot of one day. Deterministic."""

    archetype = _pick_archetype_for_slot(game_seed, day.number, day.archetype_mix,
                                          slot_index, day.forced_includes)
    spec = ARCHETYPE_SPECS[archetype]

    is_incompatible = archetype == Archetype.THE_INCOMPATIBLE
    first, last, affiliation, purpose, handle, email, photo_seed = \
        _resolve_identity(game_seed, day, slot_index)

    rng_disc = _seeded_rng(game_seed, day.number, slot_index, "discrepancies")
    discrepancies = _roll_discrepancies(rng_disc, spec, day.number,
                                        day.allowed_violations,
                                        day.difficulty_band,
                                        affiliation,
                                        # #15: scripted violations for this slot
                                        day.forced_violations.get(slot_index, ()),
                                        # 2026-09-19: a pinned-conventional carrier
                                        slot_index in day.conventional_carrier_slots)

    # 2026-09-19: DISPOSABLE_EMAIL is no longer The Incompatible's alone
    # (Clumsy Cutie can carry it — day 1 slot 3's scripted deny). Its only
    # evidence is the email domain on the dossier, so any OTHER archetype that
    # plants it must actually be given a throwaway address, or the violation is
    # scored with nothing to see (#57's failure). Drawn from its own salted rng
    # so the identity stream above — and every Incompatible's email — is
    # byte-for-byte unchanged.
    if (not is_incompatible
            and any(d.kind is DiscrepancyKind.DISPOSABLE_EMAIL
                    for d in discrepancies)):
        email = _make_email(
            _seeded_rng(game_seed, day.number, slot_index, "disposable_email"),
            first, last, affiliation, disposable=True)

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
    chat = _build_chat(rng_chat, spec, discrepancies, day.number,
                        day.forced_chat.get(slot_index, ()))

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

    # EVERY candidate submits an image (#78), carrier or not.
    #
    # This used to be gated on the candidate actually carrying a stego kind,
    # which made the dossier's Image field a free, perfect readout of ground
    # truth: measured at a correlation of 1.000 across 72,400 candidates, with
    # zero decoys in either direction. Once Stegotool unlocked on day 5 the
    # player never had to open it — a filename meant guilty and "(none)" meant
    # clean, for 0 ⏱. The invariant documented at _STEGO_ARTIFACT_KINDS above
    # ("every candidate submits exactly ONE image") was written for this code
    # and the code never honoured it; now it does.
    #
    # The pool is deliberately much larger than the four names it carried while
    # only ~10% of candidates drew from it. With every candidate drawing, four
    # names collide inside a single six-slot roster, and a filename shared by
    # two candidates is just the next pattern to read. Shapes are mixed
    # (generic, camera-style, descriptive) so that no one shape is a tell
    # either.
    _st_images = [
        "profile.png", "avatar.jpg", "header.png", "screenshot.png",
        "headshot.jpg", "id_scan.png", "badge_photo.jpg", "portrait.png",
        "img_0412.jpg", "img_2208.jpg", "dsc_00917.jpg", "photo_2024.png",
        "team_offsite.jpg", "conf_badge.png", "workstation.png", "desk.jpg",
        "signature.png", "whiteboard.jpg",
    ]
    _rng_st = random.Random(int(cand_id, 16) ^ 0xDE4DC0DE)
    submitted_image_path: str = _rng_st.choice(_st_images)

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
    # #59: WEAK_ENCRYPTION is ROLLED only as a request for a weak algorithm - it
    # is never itself an authored fact. Strip it here and re-derive it from the
    # hash below, so it can only ever describe an artifact that exists.
    #
    # Without this strip, a candidate that rolled WEAK_ENCRYPTION but lost the
    # hash chain to a plaintext-determining kind (LEAKED_PASSWORD and friends
    # take priority, and they use sha256) kept the flag on a 64-char hash - a
    # weak-encryption violation on a medium-encryption credential, with nothing
    # for the player to observe. Measured at 62 of 2700 before the strip.
    discrepancies = [d for d in discrepancies
                     if d.kind is not DiscrepancyKind.WEAK_ENCRYPTION]

    rng_hc = random.Random(int(cand_id, 16) ^ 0xDEAD_C0DE)
    if _has_leaked or _has_reuse:
        password_plain = rng_hc.choice(_HC_LEAKED_PASSWORDS)
        submitted_hash = _hashlib.sha256(password_plain.encode()).hexdigest()
    elif _has_unsalt:
        password_plain = rng_hc.choice(_HC_WEAK_PASSWORDS)
        submitted_hash = _hashlib.md5(password_plain.encode()).hexdigest()
    elif _has_weak:
        # #59: WEAK_CREDENTIAL is about the PLAINTEXT, so it can sit under either
        # crackable algorithm. It used to force md5, which meant a sha256 hash
        # never cracked to a merely weak password - only to a leaked one - and
        # the "medium encryption requires a crack to confirm complexity" half of
        # the design did not exist. Choosing md5 here also earns a derived
        # WEAK_ENCRYPTION below, so the two genuinely stack.
        password_plain = rng_hc.choice(_HC_WEAK_PASSWORDS)
        submitted_hash = (_hashlib.md5(password_plain.encode()).hexdigest()
                          if rng_hc.random() < 0.5 else
                          _hashlib.sha256(password_plain.encode()).hexdigest())
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

    # #59: WEAK_ENCRYPTION is DERIVED from the artifact rather than rolled ahead
    # of it. "The weakest encryption is used" is a property of the hash, so every
    # md5 candidate carries it. Before this only 199 of 432 md5 candidates
    # flagged it, which meant the dossier's WEAK ENC chip sometimes corresponded
    # to a violation and sometimes didn't.
    #
    # Deriving also inverts the dependency the right way round: the artifact
    # determines the violation, instead of a violation being asserted and an
    # artifact built to match. Getting that backwards is the shape behind
    # several bugs in this file's history.
    #
    # ...WITH ONE EXCLUSION, added 2026-09-15. An UNSALTED_STORAGE candidate is
    # stored IN THE CLEAR: there is no encryption there to be weak, so
    # WEAK_ENCRYPTION is not a second finding about them, it is a category
    # error. The generator still builds them an md5 digest internally (the
    # cipher block needs something to key off, and `pre_revealed` opens it
    # immediately), but that digest is an implementation detail the player is
    # never shown — shared._password_markup returns early for unsalted
    # candidates and prints the plaintext with no hash at all, precisely so it
    # doesn't read as "still needs cracking".
    #
    # Without this exclusion the game told the player two contradictory things
    # about one candidate: the dossier said "there is no crypto here" while the
    # Hashcrack block header said "digest: 32 hex characters" — and scored them
    # on both violations. Measured: 1,792 of 2,192 unsalted candidates (81.8%)
    # carried both, and on every day from 3 onward the rate was 100%.
    #
    # Still respects the two filters a rolled kind would: the #31 evidence-tier
    # gate and the day's allowed_violations whitelist. A clean archetype can
    # never pick one up because clean candidates are never given an md5 hash.
    if (submitted_hash and len(submitted_hash) == 32
            and not _has_unsalt
            and not submitted_hash.startswith("$2b$")
            and intro_day(DiscrepancyKind.WEAK_ENCRYPTION) <= day.number
            and (not day.allowed_violations
                 or DiscrepancyKind.WEAK_ENCRYPTION in day.allowed_violations)):
        _rb, _ = _SEVERITY_REVEAL[DiscrepancyKind.WEAK_ENCRYPTION]
        _sv = severity_for(DiscrepancyKind.WEAK_ENCRYPTION, day.number)
        discrepancies.append(Discrepancy(
            kind=DiscrepancyKind.WEAK_ENCRYPTION,
            severity=_sv,          # type: ignore[arg-type]
            revealed_by=_rb,
            description=_DISCREPANCY_DESCRIPTIONS[DiscrepancyKind.WEAK_ENCRYPTION],
        ))

    # Generate claimed_ip — what the candidate says they connect from.
    _rng_ip = random.Random(int(cand_id, 16) ^ 0xFACEB00C)
    _internal_ip = f"10.0.{_rng_ip.randint(1,10)}.{_rng_ip.randint(2,254)}"
    claimed_ip: str = _internal_ip
    # Report header claims (2026-09-19). Own RNG stream so no existing roll moves.
    _rng_loc = random.Random(int(cand_id, 16) ^ 0x10CA7E0)
    claimed_location = _rng_loc.choice(OFFICE_CITIES)
    claimed_role = PURPOSE_ROLES.get(purpose, "Unlisted")

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
        claimed_location=claimed_location,
        claimed_role=claimed_role,
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
        photo_seed=photo_seed,
        claimed_purpose=purpose,
        claimed_affiliation=affiliation,
        dossier=dossier,
        chat_script=chat,
        truth=truth,
    )
