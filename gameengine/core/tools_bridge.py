"""Tool bridge — exposes the four real security tools to the engine.

v1 implementation strategy:
  - Tool calls are charged in computing hours (⏱) before invocation.
  - Results are SYNTHETIC in v1: derived from the candidate's planted
    discrepancies, not from live network/disk calls.
  - Filters are optional additional invocations that cost extra ⏱ and
    return enhanced/structured output on top of the base result.

Ghostscan two-layer design:
  - Base run: surfaces raw OSINT data (platform sweep, commit email, HIBP).
    No findings are confirmed — the player reads the output and spots
    discrepancies manually by comparing against the dossier.
  - Filter run: adds an explicit cross-reference section that confirms
    mismatches. Only then are findings exposed in the result.

Live-data implementations will land in v1.1 once the loop is proven.
"""

from __future__ import annotations

import math as _math
import random as _random
from dataclasses import dataclass
from enum import Enum

from .. import config
from .candidate_gen import _ELITE_ORG_HANDLE as _ORG_HANDLE
from . import stego_scenes
from .candidate_gen import AFFILIATIONS_ELITE as _ELITE_ORGS_BANK
from .candidate_gen import AFFILIATIONS_LEGIT as _LEGIT_ORGS_BANK
from .candidate_gen import DOMAINS_DISPOSABLE as _DISPOSABLE_DOMAINS
from .candidate_gen import DOMAINS_PRIVACY as _PRIVACY_DOMAINS_BANK
from .candidate_gen import DOMAINS_TRUSTED as _TRUSTED_DOMAINS_BANK
from .candidate_gen import stable_hash as _stable_hash
from .models import Candidate, Day, Discrepancy, DiscrepancyKind, ToolName


class InsufficientCompute(RuntimeError):
    """Raised when the player can't afford a tool or filter invocation."""


# Keep the old name as an alias so any code referencing it still works.
InsufficientFunds = InsufficientCompute


@dataclass(frozen=True)
class ToolResult:
    tool: ToolName
    findings: tuple[Discrepancy, ...]
    summary: str
    raw_lines: tuple[str, ...] = ()   # verbatim terminal output lines (pre-analysis)
    filtered: bool = False            # True if a filter was applied
    # Logwatch only (2026-09-19): the Activity Report for the centre column,
    # re-rendered for this tier. raw_lines is then the auth log panel.
    report_lines: tuple[str, ...] = ()


# #53: the canonical org handles a typosquat imitates, so the filter can show
# the real handle next to the fake one. Sourced from candidate_gen so the two
# can never drift apart.
_ELITE_ORG_HANDLE_HINT: dict[str, str] = dict(_ORG_HANDLE)


def tool_cost(state, tool_name: str) -> int:
    """Effective base ⏱ cost for a tool on the state's current day.

    Two effects, and the ORDER between them matters (issue #4):
      1. #23's toolcost_* upgrade knocks config.TOOLCOST_REDUCTION off the
         base cost.
      2. #4's campaign inflation then adds config.tool_cost_inflation(day).
      3. The 1 ⏱ floor is applied LAST, to the final total — never to the
         intermediate (base - reduction) term.

    Inflation is applied after the reduction, so a purchased optimizer keeps
    saving exactly TOOLCOST_REDUCTION ⏱ for the whole campaign. Inflating
    first and reducing second is the same arithmetic today, but it would
    start clamping at the floor once inflation grew comparable to the
    reduction — quietly erasing a 45 HD$ purchase in the late game.

    Flooring the total rather than the pre-inflation intermediate matters for
    any tool whose base cost is small enough that TOOLCOST_REDUCTION would
    otherwise wipe it out on its own (e.g. a 2 ⏱ tool with a 2 ⏱ reduction) —
    flooring early would silently shrink the advertised saving once inflation
    got added back on top of an already-clamped value. Flooring the total
    still guarantees a tool never costs less than 1 ⏱, it just does so after
    every other effect has been applied.

    Filter costs are deliberately NOT inflated; see config's
    TOOL_COST_INFLATION_PERIOD block for the reasoning.
    """
    base = config.TOOL_COSTS[tool_name]
    if f"toolcost_{tool_name}" in getattr(state, "upgrades", ()):
        base -= config.TOOLCOST_REDUCTION
    total = base + config.tool_cost_inflation(getattr(state, "current_day", 1))
    return max(1, total)


def _charge(state, tool_name: str, *, filter: bool = False) -> None:
    base   = tool_cost(state, tool_name)
    extra  = config.FILTER_COSTS[tool_name] if filter else 0
    total  = base + extra
    if state.compute_hours < total:
        kind = "filter" if filter else "tool"
        raise InsufficientCompute(
            f"Need {total} ⏱ for {tool_name} {kind}, have {state.compute_hours} ⏱"
        )
    state.compute_hours -= total


def _findings_from(candidate: Candidate, tool: ToolName) -> tuple[Discrepancy, ...]:
    return tuple(d for d in candidate.truth.discrepancies if d.revealed_by == tool)


# ─── Dossier classification helpers (issue #23 auto-highlight upgrades) ──────
# Expose the ghostscan domain/affiliation lists so the dossier panels can
# colour-code emails and orgs once the matching upgrade is owned.

def classify_email_domain(email: str) -> str:
    """Classify an email's domain: 'approved' | 'prohibited' | 'privacy' | 'unknown'."""
    domain = email.split("@")[-1].lower() if "@" in email else ""
    if domain in _GS_SUSPICIOUS_DOMAINS:
        return "prohibited"
    if domain in _GS_PRIVACY_DOMAINS:
        return "privacy"
    if domain in _GS_TRUSTED_DOMAINS or domain.endswith((".edu", ".ac.uk", ".gov", ".mil")):
        return "approved"
    return "unknown"


def password_strength(hash_value: str | None) -> str | None:
    """Encryption-strength tier of a submitted password hash (issue #29).

    Derived purely from the hash shape, so it's free dossier information:
      'strong' — bcrypt ($2b$…): uncrackable in-game, always safe
      'medium' — SHA256 (64 hex): crackable with effort
      'weak'   — MD5 (32 hex): cracks instantly
    Returns None when no hash was submitted.
    """
    if not hash_value:
        return None
    if hash_value.startswith("$2b$"):
        return "strong"
    if len(hash_value) == 64:
        return "medium"
    return "weak"


def crack_password(candidate: Candidate) -> str | None:
    """The plaintext Hashcrack recovers for this candidate's password.

    Returns None when the credential is strong-tier (bcrypt) — the in-game
    cracker abandons the attempt, so strongest encryption is always safe.
    """
    if password_strength(candidate.dossier.submitted_hash) == "strong":
        return None
    return candidate.dossier.password_plain


def classify_affiliation(affiliation: str) -> str:
    """Classify a claimed affiliation: 'approved' | 'prohibited' | 'unverifiable' | 'unknown'."""
    affil = (affiliation or "").lower()
    if any(kw in affil for kw in _GS_SUSPECT_AFFIL_KW):
        return "prohibited"
    if _is_trusted_org(affil):
        return "approved"
    if affil in ("independent", "freelance", "self-employed", "consultant", ""):
        return "unverifiable"
    return "unknown"


# ─── Ghostscan — per-candidate platform sweep ───────────────────────────────
#
# Fixed platform list — identical for every candidate every day.
# Includes legit platforms, noise, and threat forums.
#
# Three render tiers:
#   get_ghostscan_identity()              — passive check (free, on load)
#   run_ghostscan_shared(c, state)        — full platform sweep; threat forum
#                                           platforms listed but candidate
#                                           entries gated until filter
#   run_ghostscan_filtered_shared(c, s)   — reveals threat forum entries +
#                                           highlights commit email mismatch +
#                                           explicit ▲ VIOLATION_TYPE labels

# #48: DERIVED from the generator's canonical word banks, same stance as the
# disposable list below. This set was maintained by hand and had already fallen
# a domain behind — fastmail.io is in _make_email's fallback pool and was not
# here, so an ordinary candidate could be handed "unknown domain — verify
# affiliation" purely because of a gap in a list nobody had reason to look at.
_GS_TRUSTED_DOMAINS    = frozenset(_TRUSTED_DOMAINS_BANK)
# #57: DERIVED from the generator's pool, not maintained alongside it. These two
# lists had drifted — the generator produced sharklasers.com, tempmail.org and
# trashmail.com, none of which were here, while this list carried tempmail.com
# which was never generated (note .com against the generator's .org). The result
# was that 148 of 400 generated DISPOSABLE_EMAIL candidates classified as
# "unknown" rather than "prohibited": the dossier highlight didn't fire, the
# identity block said "unknown domain", and the archetype's whole fast-DENY read
# silently failed better than a third of the time.
#
# Deriving makes that drift structurally impossible. Re-syncing the values by
# hand is exactly how they got out of sync in the first place.
_GS_SUSPICIOUS_DOMAINS = frozenset(_DISPOSABLE_DOMAINS)
_GS_PRIVACY_DOMAINS    = frozenset(_PRIVACY_DOMAINS_BANK)

# #48: was a verbatim hand-copy of AFFILIATIONS_LEGIT. Two lists of the same
# five organisations, in two modules, with nothing keeping them equal — adding
# an employer to the generator without editing here would have made that
# employer read as "not in known list" on its own candidates' sweeps.
_GS_LEGIT_ORGS = frozenset(_LEGIT_ORGS_BANK)

# 2026-09-24 (dockside voice pass): the trusted-org check used to be a keyword
# list ("mit", "stanford", "google", ...) kept by hand next to a word bank it
# was supposed to agree with. When the elite orgs became made-up harbour
# organisations (VOICE_GUIDE.md §5) every keyword would have silently stopped
# matching. DERIVED from AFFILIATIONS_ELITE now, exact match, same stance as
# the domain banks above — the #56 guarantee ("a trusted org cannot be faked")
# is about exactly these organisations and no others.
_GS_ELITE_ORGS = frozenset(_ELITE_ORGS_BANK)
_GS_ELITE_ORGS_LOWER = frozenset(o.lower() for o in _ELITE_ORGS_BANK)


def _is_trusted_org(affiliation: str) -> bool:
    return (affiliation or "").strip().lower() in _GS_ELITE_ORGS_LOWER


_GS_SUSPECT_AFFIL_KW = ["breachforums", "raidforums", "hackforums",
                          "nulled", "exploit.in"]

# Fixed platform lists — never change day to day
_GS_LEGIT_PLATFORMS  = ["GitHub", "LinkedIn", "Twitter/X", "The Doxen",
                          "Reddit", "Keybase", "Google", "Spotify"]
_GS_CRITICAL_FORUMS  = ["BreachForums", "RaidForums", "HackForums", "XSS.is"]
_GS_ADVISORY_FORUMS  = ["nulled.to", "CrackingKing", "Dread", "CrackingPro"]

# ── Unified breach database table ─────────────────────────────────────────────
# Single source of truth used by BOTH the GhostScan breach list panel AND the
# Hashcrack cipher block's corpus readout.  canonical_name is what appears in
# both UIs so the player can cross-reference them visually.
#
#   (canonical_name,          year,   record_count_label)
_BREACH_DATABASES: list[tuple[str, str, str]] = [
    ("Collection #1 (2019)", "2019", "772M records"),
    ("LinkedIn (2016)",      "2016", "117M records"),
    ("RockYou (2024)",       "2024", "10B records"),
    ("Dropbox (2012)",       "2012", "68M records"),
    ("Adobe (2013)",         "2013", "153M records"),
    ("MyFitnessPal (2018)",  "2018", "143M records"),
]

# Keep legacy aliases for any code still referencing the old names
_GS_BREACH_DUMPS = [db[0] for db in _BREACH_DATABASES]
_GS_BREACH_META  = _BREACH_DATABASES  # used by get_breach_lists()

_BREACH_DB_BY_NAME = {db[0]: db for db in _BREACH_DATABASES}

# #61: config.BREACH_DB_UNLOCK_DAY schedules these, and the generator refuses
# to attach a candidate to a locked corpus. If the two tables drift, a
# candidate gets planted into a database the panel never renders — the exact
# unobservable-violation failure this whole batch keeps finding. #57's lesson
# was that hand-syncing two lists is how they drift, so this fails at import
# rather than at play time.
assert set(_BREACH_DB_BY_NAME) == set(config.BREACH_DB_UNLOCK_DAY), (
    "tools_bridge._BREACH_DATABASES and config.BREACH_DB_UNLOCK_DAY disagree: "
    f"only in tools_bridge {sorted(set(_BREACH_DB_BY_NAME) - set(config.BREACH_DB_UNLOCK_DAY))}, "
    f"only in config {sorted(set(config.BREACH_DB_UNLOCK_DAY) - set(_BREACH_DB_BY_NAME))}"
)

# Dedicated seed for the shared breach-DB selector.  Must differ from the main
# ghostscan RNG seed (0x6057CAD1) and the breach-list seed (0xB8EA4DB5).
_BREACH_DB_SEED = 0xD8EAD808


_BREACH_DB_SEED = 0xD8EAD808


def _breach_dbs_for_candidate(candidate_id: str, count: int = 1) -> list[tuple[int, str]]:
    """Return `count` distinct (db_index, canonical_name) pairs for this candidate.

    The single source of truth for "which breach databases is this candidate in".
    Any surface that names a breach database must flow through here.
    """
    rng = _random.Random(int(candidate_id, 16) ^ _BREACH_DB_SEED)
    order = list(range(len(_BREACH_DATABASES)))
    rng.shuffle(order)
    picked = order[:max(1, min(count, len(order)))]
    return [(i, _BREACH_DATABASES[i][0]) for i in picked]


def _breach_db_for_candidate(candidate_id: str, day_number: int | None = None) -> tuple[int, str]:
    """Primary breach database for this candidate.

    The day-aware variant is used when the candidate must only be seeded into
    corpora the player can actually unlock on the current day. The stable
    selector above remains for callers that only need the canonical list.
    """
    unlocked = config.breach_dbs_unlocked_by(day_number) if day_number is not None else list(_BREACH_DATABASES)
    if not unlocked:
        return 0, _BREACH_DATABASES[0][0]
    rng = _random.Random(int(candidate_id, 16) ^ _BREACH_DB_SEED)
    name = unlocked[rng.randint(0, len(unlocked) - 1)]
    return _GS_BREACH_DUMPS.index(name), name


def _second_breach_db_for_candidate(candidate_id: str, day_number: int,
                                    first: str) -> str:
    """The other corpus a cross-breach password shows up in."""
    unlocked = [n for n in config.breach_dbs_unlocked_by(day_number) if n != first]
    if not unlocked:
        return first
    rng = _random.Random(int(candidate_id, 16) ^ (_BREACH_DB_SEED + 1))
    return unlocked[rng.randint(0, len(unlocked) - 1)]


def breach_dbs_for_candidate(candidate: Candidate, day_number: int) -> list[str]:
    """Every corpus this candidate's email should appear in on this day."""
    kinds = {d.kind for d in candidate.truth.discrepancies}
    if not (kinds & {DiscrepancyKind.BREACH_HIT,
                     DiscrepancyKind.LEAKED_PASSWORD,
                     DiscrepancyKind.CROSS_BREACH_REUSE}):
        return []
    _, first = _breach_db_for_candidate(candidate.id, day_number)
    if DiscrepancyKind.CROSS_BREACH_REUSE not in kinds:
        return [first]
    second = _second_breach_db_for_candidate(candidate.id, day_number, first)
    return [first] if second == first else [first, second]


def breach_db_count(candidate) -> int:
    """How many corpora this candidate's email should appear in."""
    kinds = {d.kind for d in candidate.truth.discrepancies}
    if DiscrepancyKind.CROSS_BREACH_REUSE in kinds:
        return 2
    return 1



# Noise email pools for breach list generation
_GS_BREACH_EMAIL_USERS = [
    "j.morris", "r.chen", "s.patel", "a.kim", "k.okonkwo",
    "t.nakamura", "l.vasquez", "d.kowalski", "m.ibrahim", "n.reyes",
    "p.walsh", "b.silva", "c.johannsen", "a.petrov", "f.nguyen",
    "h.mueller", "i.santos", "j.tanaka", "k.leblanc", "l.osei",
    "m.eriksson", "n.ali", "o.svensson", "q.martin", "r.yamamoto",
    "s.kovacs", "t.hassan", "u.novak", "v.popescu", "w.fitzgerald",
    "x.chen2", "y.park", "z.andersen", "aa.gupta", "bb.wolff",
    "cc.dubois", "dd.russo", "ee.ito", "ff.garcia", "gg.schroeder",
]
_GS_BREACH_EMAIL_DOMAINS = [
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "protonmail.com", "icloud.com", "aol.com", "live.com",
    "corp.net", "company.org", "internal.io", "techfirm.co",
]

# Noise handles that appear on legit platforms and forums to give list volume
_GS_NOISE_HANDLES = [
    "n3tw0rk_gh0st", "voidhunter44", "zerodayz", "cr4ck3r_elite", "ph4ntom99",
    "d4rkn3t99", "b0tmaster", "sysr00t77", "r3d_t34m", "cyberevil42",
    "l33t_c0d3r", "malware_dev", "pwn_king", "0xdeadc0de", "n1ghtcrawl3r",
    "shellcod3r", "byp4ss3r", "r00tkit_x", "gr4ysec", "d3adbeef99",
]
_GS_NOISE_ORGS = [
    "SecureNet Labs", "InfoSec Alliance", "CipherCraft Inc.",
    "Red Team Solutions", "Freelance Security", "Independent Researcher",
    "Null Pointer Research", "BinaryBridge LLC",
]


# ─── Report section bands (issue #28) ───────────────────────────────────────
# Each major report section opens with a filled colour band + underline so
# Platform Sweep and Breach Detection are visually distinct at a glance.

_GS_BAND_W = 58


def _gs_band(title: str, accent: str, note: str = "") -> list[str]:
    pad = " " * max(1, _GS_BAND_W - len(title) - 4)
    out = [f"[b {accent} on #0d1b2a] ▌ {title}{pad}[/]"]
    if note:
        out.append(f"[dim]{note}[/]")
    out.append(f"[{accent}]{'━' * _GS_BAND_W}[/]")
    return out


def get_ghostscan_identity(candidate: Candidate,
                           upgrades: set | None = None) -> tuple[str, ...]:
    """Free passive identity check — always visible in the ghostscan terminal.

    #76: "free" means no ⏱ tool run, not "every verdict on it is free" — the
    approved/prohibited verdict lines are upgrade-gated, see below.
    """
    return tuple(_ghostscan_identity_lines(candidate, upgrades=upgrades))


def _ghostscan_identity_lines(candidate: Candidate, hint: bool = True,
                              upgrades: set | None = None) -> list[str]:
    # #76: the approved/prohibited verdict here is the SAME classify_email_
    # domain/classify_affiliation call the dossier's _hl_email/_hl_affil use,
    # gated on the dossier behind Domain Whitelist/Blacklist HUD and Org
    # Whitelist/Blacklist HUD -- but this panel showed the identical verdict
    # unconditionally, for free, on the Ghostscan page. Same upgrades now gate
    # it here too. Without the matching upgrade this falls back to the same
    # neutral "verify via sweep" copy already used for domains/orgs the game
    # genuinely doesn't recognise -- the tell disappears, not the underlying
    # info (the sweep itself still confirms it once run).
    #
    # 2026-09-25 (Nick): the "questionable" middle band -- privacy mail
    # providers, thin / unverifiable affiliations -- was still flagged here for
    # free, in amber, on every candidate. Placing a domain or org on the lists
    # is the player's job (Dossier reference tab); the tool only says so once
    # a matching whitelist/blacklist HUD is owned. Without one, every domain
    # and org gets the same neutral prompt, so the line itself is no tell.
    upgrades = upgrades or ()
    d = candidate.dossier
    email_domain = candidate.email.split("@")[-1].lower() if "@" in candidate.email else ""
    email_hud = (config.UPGRADE_EMAIL_APPROVED in upgrades
                 or config.UPGRADE_EMAIL_PROHIBITED in upgrades)
    affil_hud = (config.UPGRADE_AFFIL_APPROVED in upgrades
                 or config.UPGRADE_AFFIL_PROHIBITED in upgrades)

    if email_domain in _GS_SUSPICIOUS_DOMAINS and config.UPGRADE_EMAIL_PROHIBITED in upgrades:
        email_flag = "[#ff5470]✗  disposable provider — flag immediately[/]"
    elif email_domain in _GS_PRIVACY_DOMAINS and email_hud:
        # #58: was "privacy provider — flag if other issues present", which told
        # the player to flag something with no matching DiscrepancyKind. The
        # nearest thing to flag is DISPOSABLE_EMAIL, a different domain class, and
        # board_accuracy_bonus counts that as a false positive — so the UI was
        # instructing an action the scoring model punishes. Context, not an
        # instruction: it is real corroboration, it is not itself a violation.
        # Not upgrade-gated: it isn't an approved/prohibited verdict at all.
        email_flag = ("[#ffd93d]?  anonymous mail provider — legitimate, but "
                      "offers no identity trail[/]")
    elif (email_domain in _GS_TRUSTED_DOMAINS or email_domain.endswith((".edu", ".ac.uk")))             and config.UPGRADE_EMAIL_APPROVED in upgrades:
        email_flag = "[#00ff9f]✓  recognised provider[/]"
    elif email_hud:
        email_flag = "[#6b7785]-  unknown domain — verify affiliation[/]"
    else:
        email_flag = "[#6b7785]-  check the domain against the Dossier reference lists[/]"

    affil_lower = candidate.claimed_affiliation.lower()
    if any(kw in affil_lower for kw in _GS_SUSPECT_AFFIL_KW) and config.UPGRADE_AFFIL_PROHIBITED in upgrades:
        affil_flag = "[#ff5470]✗  known threat actor community[/]"
    elif _is_trusted_org(affil_lower) and config.UPGRADE_AFFIL_APPROVED in upgrades:
        # #56: this is a GUARANTEE now, not a hint. A trusted organisation cannot
        # be faked on a dossier - the generator refuses to plant an affiliation
        # violation on a candidate claiming one - so the sweep will always
        # confirm it. Worded as the guarantee it is, because that is the
        # player's reward: a trusted domain plus a trusted org means the
        # ghostscan step can be skipped entirely.
        #
        # #76: that reward is now Org Whitelist HUD's to hand out, same as the
        # dossier's equivalent highlight. Without the upgrade the guarantee
        # still HOLDS (the generator still won't fake it) -- the player just
        # isn't told about it for free, and falls through to the same
        # "verify via sweep" prompt an unrecognised org gets.
        affil_flag = ("[#00ff9f]✓  trusted organisation — cannot be faked, "
                      "sweep will confirm[/]")
    elif affil_lower in ("independent", "freelance", "self-employed", "") and affil_hud:
        affil_flag = "[#ffd93d]?  unverifiable — needs corroboration[/]"
    elif affil_hud:
        affil_flag = "[#6b7785]-  not in known list — verify via sweep[/]"
    else:
        affil_flag = "[#6b7785]-  check the org against the Dossier reference lists[/]"

    gh_flag = (
        f"[#6b7785]-  [b]{d.claimed_github}[/] claimed — run scan to verify[/]"
        if d.claimed_github else
        "[#ffd93d]?  no GitHub submitted — limited verifiability[/]"
    )

    return [
        *_gs_band("IDENTITY CHECK", "#7dd3c0", "passive — no ⏱ spent"),
        (f"[#6b7785]target[/]  [b #e8f0f8]{candidate.display_name}[/]"
        f"  [#6b7785]handle[/] [#c8d4e1]{candidate.handle}[/]"),
        # #53: the free "possible typosquat" line was removed. It named the
        # violation before any hours were spent, which is why the violation was
        # only ever "caught" by reading a label. The handle now genuinely is a
        # lookalike of a listed org's handle, so the tell is comparing it to the
        # claimed affiliation two lines below - and the filter names the target.
        "",
        f"  [#6b7785]email[/]        [#c8d4e1]{candidate.email}[/]",
        f"               {email_flag}",
        "",
        f"  [#6b7785]affiliation[/]  [#c8d4e1]{candidate.claimed_affiliation}[/]",
        f"               {affil_flag}",
        "",
        f"  [#6b7785]github[/]       {gh_flag}",
        *(["",
           "[dim]Run [b]G[/] for the full report (platform sweep + breach detection) — verify claimed org[/]"]
          if hint else []),
    ]


def _ghostscan_sweep_lines(
    candidate: Candidate,
    rng: _random.Random,
    show_forums: bool = False,
    day_number: int = 1,
    show_breach: bool | None = None,
    show_sock: bool | None = None,
    show_forum_match: bool | None = None,
) -> list[str]:
    """Render the fixed platform sweep for one candidate.

    Base run (show_forums=False):
      - All legit platforms listed with noise + candidate entries
      - Affiliation mismatch flagged with ▲ (no explicit violation name)
      - Commit email shown un-highlighted on GitHub
      - Threat forums listed; candidate entries HIDDEN (only noise shown)

    Filter (show_forums=True):
      - Same legit section but commit email highlighted if mismatch
      - Threat forum section reveals candidate entries + ▲ annotations
    """
    # #56 - three affiliation violations, three different things on screen. They
    # used to collapse: a6ad3b0 gave the old UNVERIFIED and MISMATCH a shared
    # "(no org listed)" render, so the two kinds were indistinguishable in the
    # one place they were supposed to be told apart.
    #   UNLISTED  -> profiles carry no org tag
    #   MISMATCH  -> profiles carry a DIFFERENT org (the difference IS the tell)
    #   NOT_STATED-> a dossier violation; the sweep shows their real org normally,
    #                because the point is they simply never said what it was
    has_unlisted = any(d.kind == DiscrepancyKind.AFFILIATION_UNLISTED
                       for d in candidate.truth.discrepancies)
    # AFFILIATION_MISMATCH is the "faked elite org" variant (Sneaky Bugger,
    # elite affiliation pool). It was previously not checked here at ALL, which
    # meant the sweep fell through to the generic branch and printed the claimed
    # org next to the candidate's handle on every platform — actively
    # CORROBORATING the very claim the ground truth says is false. The dossier
    # said "Google Security Team", the ground truth said "not found", and the
    # tool the violation is revealed by agreed with the liar.
    has_affil_fake = any(d.kind == DiscrepancyKind.AFFILIATION_MISMATCH
                         for d in candidate.truth.discrepancies)
    # Both affiliation kinds suppress the org on the sweep; they differ in what
    # the filter says about it (unverifiable small org vs. unbacked elite claim).
    has_no_org   = has_unlisted
    has_mismatch = any(d.kind == DiscrepancyKind.EMAIL_GITHUB_MISMATCH  for d in candidate.truth.discrepancies)
    has_missing  = any(d.kind == DiscrepancyKind.MISSING_PUBLIC_PROFILE for d in candidate.truth.discrepancies)
    has_sock     = any(d.kind == DiscrepancyKind.SOCK_PUPPET_ACCOUNTS   for d in candidate.truth.discrepancies)
    has_breach   = any(d.kind == DiscrepancyKind.BREACH_HIT             for d in candidate.truth.discrepancies)
    has_forum    = any(d.kind == DiscrepancyKind.THREAT_FORUM_MATCH     for d in candidate.truth.discrepancies)  # v2
    has_burner   = any(d.kind == DiscrepancyKind.BURNER_IDENTITY        for d in candidate.truth.discrepancies)  # v2

    # #75: SOCK_PUPPET_ACCOUNTS and THREAT_FORUM_MATCH auto-confirm on the free
    # base run when their own upgrade is owned -- config.UPGRADE_SOCK_AUTO /
    # UPGRADE_FORUM_AUTO, same shape as show_breach/UPGRADE_BREACH_AUTO above.
    # Default to show_forums when not given, so every existing caller keeps
    # the old show_forums-gated behavior.
    _show_sock = show_forums if show_sock is None else show_sock
    _show_forum_match = show_forums if show_forum_match is None else show_forum_match

    claimed_affil  = candidate.claimed_affiliation
    claimed_handle = candidate.handle
    claimed_email  = candidate.email
    commit_email   = candidate.dossier.commit_email or claimed_email

    # Which legit platforms the candidate appears on (3-5 unless missing profile)
    n_appear = rng.randint(1, 2) if has_missing else rng.randint(3, 5)
    cand_platforms = set(rng.sample(_GS_LEGIT_PLATFORMS, min(n_appear, len(_GS_LEGIT_PLATFORMS))))
    # #63: EMAIL_GITHUB_MISMATCH's only evidence is the `commits:` row below,
    # which is emitted inside `if platform == "GitHub"`. The random sample above
    # dropped GitHub for 50 of 76 carriers (66%), leaving the filter summary
    # naming a violation with nothing in the report body to compare against —
    # the player was told two emails differed while only ever seeing one.
    #
    # Swapping one sampled platform for GitHub rather than adding it keeps
    # len(cand_platforms) intact, which matters because #51's
    # "present on only N of 8 platforms" line is MISSING_PUBLIC_PROFILE's only
    # tell. Growing the set here would quietly weaken a different violation.
    #
    # Nick's alternative — make absence-from-GitHub a violation in itself —
    # was rejected: "handle barely appears" is MISSING_PUBLIC_PROFILE's
    # signal, and #56 exists precisely because two violations sharing one
    # signal is unresolvable for the player.
    if has_mismatch and "GitHub" not in cand_platforms:
        cand_platforms.discard(max(cand_platforms))
        cand_platforms.add("GitHub")

    lines: list[str] = [
        (f"[#6b7785]target[/]  [b #e8f0f8]{candidate.display_name}[/]  "
        f"[#6b7785]handle[/] [#c8d4e1]{claimed_handle}[/]  "
        f"[#6b7785]claimed org[/] [#c8d4e1]{claimed_affil}[/]"),
        "",
        # ── SECTION 1 — PLATFORM SWEEP (issue #28: distinct cyan band) ───
        *_gs_band("PLATFORM SWEEP", "#6ad4ff",
                  "fixed list — same platforms every day · locate your target handle"),
        "",
    ]

    prev_affil_ann = False

    for platform in _GS_LEGIT_PLATFORMS:
        lines.append(f"  [#7dd3c0][b]{platform}[/][/]")
        in_cand_set = platform in cand_platforms

        # Candidate's entry on this platform
        if in_cand_set:
            if has_no_org:
                # AFFILIATION_UNLISTED: profiles exist, none carry an org.
                org_str = "[dim](no org listed)[/]"
            elif candidate.dossier.actual_affiliation:
                # The org the sweep ACTUALLY shows, when the generator recorded
                # one. Two cases reach here: AFFILIATION_MISMATCH (it differs
                # from the dossier - that difference IS the violation, and
                # rendering "no org" here before #56 hid the only thing
                # separating it from UNLISTED), and AFFILIATION_NOT_STATED
                # (the dossier is blank, so the sweep simply shows where they
                # really work - a dossier violation with no sweep signature).
                org_str = f"[[{candidate.dossier.actual_affiliation}]"
            elif claimed_affil in _GS_LEGIT_ORGS:
                org_str = f"[[{claimed_affil}]"
            else:
                # NOTE: The Professional also draws from the elite pool and is
                # SUPPOSED to have their claimed org confirmed here — that's
                # their whole "ghostscan confirms, quick admit" read. The
                # has_no_org branch above is what separates the two.
                org_str = f"[[{claimed_affil or 'independent'}]"

            # Commit email — always shown, highlighted only on filter
            commit_str = ""
            if platform == "GitHub":
                if has_mismatch and show_forums:
                    commit_str = f"  [dim]commits:[/] [#ff5470]{commit_email}[/]"
                else:
                    commit_str = f"  [dim]commits:[/] [#6b7785]{commit_email}[/]"

            row = f"    [b #e8f0f8]{claimed_handle}[/]  [#c8d4e1]{org_str}[/]{commit_str}"

            # Suspicious signals — only highlight and annotate on filter run.
            # Base run: entry shown plain so the player must spot it themselves.
            is_affil_suspicious   = has_no_org or has_affil_fake
            is_mismatch_suspicious = has_mismatch and platform == "GitHub"

            if (is_affil_suspicious or is_mismatch_suspicious) and show_forums:
                lines.append(f"[#ffd93d]{row}[/]")
                if is_affil_suspicious and not prev_affil_ann:
                    # Name the claimed org for the elite-fake variant — "not
                    # confirmed" is too soft when the candidate claimed to work
                    # somewhere specific and prestigious.
                    lines.append(
                        f"    [#ff8c42]▲ dossier says [b]{claimed_affil}[/] — "
                        f"profile says [b]{candidate.dossier.actual_affiliation}[/][/]"
                        if has_affil_fake else
                        "    [#ffd93d]▲ no organisation listed on any profile[/]")
                    prev_affil_ann = True
                if is_mismatch_suspicious:
                    lines.append("    [#ff8c42]▲ commit email differs from dossier[/]")
            else:
                lines.append(row)

        # 2-3 noise entries per platform
        n_noise = rng.randint(1, 3)
        for _ in range(n_noise):
            noise_handle = rng.choice(_GS_NOISE_HANDLES)
            noise_org    = rng.choice(_GS_NOISE_ORGS + [None, None])  # type: ignore[list-item]
            org_s        = f"  [[{noise_org}]" if noise_org else ""
            lines.append(f"[#2e3d4f]    {noise_handle}{org_s}[/]")

    # #51: MISSING_PUBLIC_PROFILE's only evidence is the thinned platform count
    # above (n_appear 1-2 instead of 3-5), which is invisible unless the player
    # already knows the normal range. The filter names it explicitly; the base
    # run leaves the count to be noticed, same stance as every other kind.
    if has_missing and show_forums:
        lines.append("")
        lines.append(
            f"  [#ff8c42]▲ present on only {len(cand_platforms)} of "
            f"{len(_GS_LEGIT_PLATFORMS)} platforms — no meaningful public "
            f"profile[/]")

    lines.append("")
    lines.append("[#6ad4ff]-- account registry ----------------------------------------[/]")
    lines.append("[dim](creation dates per platform — clusters suggest a burner identity)[/]")
    _reg_plats = sorted(cand_platforms) if cand_platforms else ["GitHub", "Reddit", "Twitter/X"]
    if has_burner:
        _bd = rng.randint(10, 22)
        for _i, _p in enumerate(_reg_plats[:4]):
            _created = f"2024-03-{_bd + (_i % 3):02d}"
            _col = "#ffd93d" if show_forums else "#2e3d4f"
            lines.append(f"[{_col}]  {_p:<14} created {_created}[/]")
        if show_forums:
            lines.append("  [#ff8c42]▲ all accounts created within days -- burner identity[/]")
    else:
        for _i, _p in enumerate(_reg_plats[:4]):
            _yr = 2017 + (_i * 2) % 7
            lines.append(f"[#2e3d4f]  {_p:<14} created {_yr}-0{1 + _i % 8}-{12 + _i:02d}[/]")
    lines.append("")

    # ── SECTION 2 — BREACH DETECTION (issue #28: distinct orange band) ────
    # Threat forums + breach dumps live under one clearly separated section.
    # Base run:   candidate handle blended as dim entry — player must spot it
    # Filter run: candidate handle highlighted with tier colour + explicit label
    lines.append("")
    lines.extend(_gs_band(
        "BREACH DETECTION", "#ff8c42",
        ("CRITICAL → immediate deny · ADVISORY → investigate further"
         if show_forums else
         "threat forums + breach dumps · locate your target handle"),
    ))
    lines.append("")
    lines.append("[#ff8c42]-- threat forums --------------------------------------------[/]")
    lines.append("")

    # Determine which single advisory forum the candidate appears in (if any).
    # Computed once outside the loop so the RNG sequence is identical for both
    # show_forums=False and show_forums=True — keeps noise handles consistent.
    advisory_hit = rng.choice(_GS_ADVISORY_FORUMS) if has_sock else None

    # Critical forums
    lines.append("  [#3d4f5e]▌ CRITICAL[/]  [dim]BreachForums · RaidForums · HackForums · XSS.is[/]")
    first_crit_ann = True
    for forum in _GS_CRITICAL_FORUMS:
        noise_h = rng.choice(_GS_NOISE_HANDLES)
        lines.append(f"[#2e3d4f]  {forum:<20}  {noise_h}[/]")
        if has_sock or has_forum:
            # #75: each kind's own upgrade governs whether ITS row auto-reveals
            # here, independent of the other. A candidate carrying both kinds
            # can have one revealed and the other still blended.
            _reveal_row = (
                show_forums
                or (has_forum and _show_forum_match)
                or (has_sock and _show_sock)
            )
            if _reveal_row:
                lines.append(f"[#ff5470]  {forum:<20}  {claimed_handle}  [CRITICAL][/]")
                if first_crit_ann:
                    lines.append("  [#ff8c42]▲ handle on known threat actor forum[/]")
                    first_crit_ann = False
            else:
                # Blended — same dim colour as noise, no label
                lines.append(f"[#2e3d4f]  {forum:<20}  {claimed_handle}[/]")

    lines.append("")
    lines.append("  [#2e3d4f]▌ ADVISORY[/]  [dim]nulled.to · CrackingKing · Dread · CrackingPro[/]")
    for forum in _GS_ADVISORY_FORUMS:
        noise_h = rng.choice(_GS_NOISE_HANDLES)
        lines.append(f"[#2e3d4f]  {forum:<20}  {noise_h}[/]")
        if has_sock and forum == advisory_hit:
            if show_forums or _show_sock:
                lines.append(f"[#ff8c42]  {forum:<20}  {claimed_handle}  [ADVISORY][/]")
            else:
                lines.append(f"[#2e3d4f]  {forum:<20}  {claimed_handle}[/]")

    # Breach dump summary — delegate detail to the breach list panel (right column)
    lines.append("")
    lines.append("[#ff8c42]-- breach dumps ---------------------------------------------[/]")
    lines.append("  [dim]full databases in the breach panel →[/]")
    # #61: the noise dumps name only UNLOCKED corpora. A summary line citing a
    # database the panel does not render is a dead end the player cannot check.
    _unlocked_dumps = config.breach_dbs_unlocked_by(day_number) or _GS_BREACH_DUMPS
    for _ in range(3):
        noise_email = f"{rng.choice(_GS_NOISE_HANDLES)}@{rng.choice(['corp.net', 'internal.io', 'hackdox.local'])}"
        dump_name   = rng.choice(_unlocked_dumps)
        lines.append(f"[#2e3d4f]  {dump_name:<24}  {noise_email}[/]")
    # Batch-3 task #4c: breach confirmation can fire independently of the
    # forum reveal now (config.UPGRADE_BREACH_AUTO surfaces it on the free
    # base run — "the lists are static, so it makes sense to have this
    # automated"). Defaults to show_forums when not given, so every existing
    # caller keeps the old show_forums-gated behavior.
    _show_breach = show_forums if show_breach is None else show_breach
    if has_breach:
        _dbs = breach_dbs_for_candidate(candidate, day_number)
        if not _dbs:
            _dbs = [_breach_db_for_candidate(candidate.id, day_number)[1]]
        for breach_db in _dbs:
            if _show_breach:
                lines.append(f"[#ff8c42]  {breach_db:<24}  {claimed_email}[/]")
            else:
                lines.append(f"[#2e3d4f]  {breach_db:<24}  {claimed_email}[/]")
        if _show_breach:
            if len(_dbs) > 1:
                lines.append(f"  [#ff8c42]▲ email in {len(_dbs)} breach corpora — "
                             f"check Hashcrack for password reuse[/]")
            else:
                lines.append("  [#ff8c42]▲ email in breach corpus[/]")


    return lines


def _ghostscan_filter_summary_lines(candidate: Candidate) -> list[str]:
    _ks = {d.kind for d in candidate.truth.discrepancies}
    has_sock     = DiscrepancyKind.SOCK_PUPPET_ACCOUNTS  in _ks
    has_breach   = DiscrepancyKind.BREACH_HIT            in _ks
    has_missing  = DiscrepancyKind.MISSING_PUBLIC_PROFILE  in _ks   # #51
    has_unlisted = DiscrepancyKind.AFFILIATION_UNLISTED   in _ks
    has_affil_fake = DiscrepancyKind.AFFILIATION_MISMATCH in _ks
    has_mismatch = DiscrepancyKind.EMAIL_GITHUB_MISMATCH  in _ks
    has_forum    = DiscrepancyKind.THREAT_FORUM_MATCH     in _ks   # v2
    has_burner   = DiscrepancyKind.BURNER_IDENTITY        in _ks   # v2
    has_typo     = DiscrepancyKind.TYPOSQUAT_HANDLE       in _ks   # v2

    lines = ["", "[#c084fc]── [FILTER] violation summary ────────────────────────────[/]"]
    found = False
    if has_forum:
        lines.append("  [#ff5470][b]▲ THREAT_FORUM_MATCH[/][/]  -- handle on a known threat / dark-web forum")
        found = True
    if has_burner:
        lines.append("  [#ff8c42][b]▲ BURNER_IDENTITY[/][/]  -- accounts all created within days")
        found = True
    if has_typo:
        # #53: name WHAT is being squatted. "mimics a trusted org" was useless -
        # it restated the violation name. The comparison is the content.
        squatted = candidate.dossier.handle_squats
        if squatted:
            lines.append(
                f"  [#ffd93d][b]▲ TYPOSQUAT_HANDLE[/][/]  — [b]{candidate.handle}[/] "
                f"is a lookalike of [b]{_ELITE_ORG_HANDLE_HINT.get(squatted, squatted)}[/] "
                f"([i]{squatted}[/])")
        else:
            lines.append("  [#ffd93d][b]▲ TYPOSQUAT_HANDLE[/][/]  — handle is a "
                         "lookalike of a listed organisation's handle")
        found = True
    if has_sock:
        lines.append("  [#ff5470][b]▲ SOCK_PUPPET_ACCOUNTS[/][/]  — handle on critical threat forum")
        found = True
    if has_breach:
        lines.append("  [#ff5470][b]▲ BREACH_HIT[/][/]  — email confirmed in breach corpus")
        found = True
    if has_missing:
        # #51: was tiered DOSSIER and never rendered anywhere. Its evidence has
        # always been the sparse platform sweep, so it belongs here.
        lines.append("  [#ffd93d][b]▲ MISSING_PUBLIC_PROFILE[/][/]  — no meaningful "
                     "public presence for the claimed handle")
        found = True
    if has_unlisted:
        lines.append("  [#ffd93d][b]▲ AFFILIATION_UNLISTED[/][/]  — profiles exist "
                     "but list no organisation at all")
        found = True
    if has_affil_fake:
        lines.append(
            f"  [#ff8c42][b]▲ AFFILIATION_MISMATCH[/][/]  — dossier says "
            f"[b]{candidate.claimed_affiliation}[/], profiles say "
            f"[b]{candidate.dossier.actual_affiliation}[/]")
        found = True
    if has_mismatch:
        lines.append("  [#ff8c42][b]▲ EMAIL_GITHUB_MISMATCH[/][/]  — commit email ≠ dossier email")
        found = True
    if not found:
        lines.append("  [#00ff9f]✓  no violations confirmed[/]")
    return lines


def run_ghostscan_shared(candidate: Candidate, state) -> ToolResult:
    """Base run: full platform sweep, threat forum candidate entries gated."""
    _charge(state, "ghostscan")
    rng = _random.Random(int(candidate.id, 16) ^ 0x6057CAD1)
    # Batch-3 task #4c: config.UPGRADE_BREACH_AUTO ("Breach Feed Sync") makes
    # breach-corpus confirmation fire on the free base run too — "the lists
    # are static, so it makes sense to have this automated" (Nick).
    # #75: UPGRADE_SOCK_AUTO ("Sockpuppet Tracer") and UPGRADE_FORUM_AUTO
    # ("Forum Watch") do the same for SOCK_PUPPET_ACCOUNTS and
    # THREAT_FORUM_MATCH, each independently of the other and of the breach
    # upgrade — owning one doesn't auto-confirm a different kind. Without any
    # of the three, threat forums stay gated behind the real filter run.
    _breach_auto = config.UPGRADE_BREACH_AUTO in getattr(state, "upgrades", ())
    _sock_auto   = config.UPGRADE_SOCK_AUTO   in getattr(state, "upgrades", ())
    _forum_auto  = config.UPGRADE_FORUM_AUTO  in getattr(state, "upgrades", ())
    has_breach = any(d.kind == DiscrepancyKind.BREACH_HIT
                     for d in candidate.truth.discrepancies)
    has_sock   = any(d.kind == DiscrepancyKind.SOCK_PUPPET_ACCOUNTS
                     for d in candidate.truth.discrepancies)
    has_forum  = any(d.kind == DiscrepancyKind.THREAT_FORUM_MATCH
                     for d in candidate.truth.discrepancies)
    # Issue #28: the report REPLACES the terminal content (no stacked
    # reports), so the free identity block is folded in at the top.
    raw_lines  = list(
        _ghostscan_identity_lines(candidate, hint=False,
                                  upgrades=getattr(state, "upgrades", ()))
        + [""]
        # #61: day drives which breach corpora exist today.
        + _ghostscan_sweep_lines(candidate, rng, show_forums=False,
                                 day_number=getattr(state, 'current_day', 1),
                                 show_breach=_breach_auto,
                                 show_sock=_sock_auto,
                                 show_forum_match=_forum_auto)
    )
    if _breach_auto and has_breach:
        raw_lines += [
            "",
            "[#c084fc]── [AUTO] Breach Feed Sync ─────────────────────────────[/]",
            "  [#ff5470][b]▲ BREACH_HIT[/][/]  — email confirmed in breach corpus",
        ]
    if _sock_auto and has_sock:
        raw_lines += [
            "",
            "[#c084fc]── [AUTO] Sockpuppet Tracer ────────────────────────────[/]",
            "  [#ff5470][b]▲ SOCK_PUPPET_ACCOUNTS[/][/]  — handle confirmed across sock-puppet cluster",
        ]
    if _forum_auto and has_forum:
        raw_lines += [
            "",
            "[#c084fc]── [AUTO] Forum Watch ──────────────────────────────────[/]",
            "  [#ff5470][b]▲ THREAT_FORUM_MATCH[/][/]  — handle confirmed on known threat-actor forum",
        ]
    n_findings = len(_findings_from(candidate, ToolName.GHOSTSCAN))
    summary = (
        f"{n_findings} signal(s) in sweep — review carefully, run filter (F) to check threat forums."
        if n_findings else
        "Platform sweep complete — no anomalies on legit platforms. Run filter to check threat forums."
    )
    return ToolResult(tool=ToolName.GHOSTSCAN, findings=(), raw_lines=tuple(raw_lines), summary=summary)


def run_ghostscan_filtered_shared(candidate: Candidate, state) -> ToolResult:
    """Filter: reveals threat forum entries + commit email highlight + explicit labels."""
    _charge(state, "ghostscan", filter=True)
    rng      = _random.Random(int(candidate.id, 16) ^ 0x6057CAD1)
    findings = _findings_from(candidate, ToolName.GHOSTSCAN)
    # Issue #28: the filtered report REPLACES the base report in-place —
    # same layout, annotations lit — rather than printing a second copy.
    raw_lines = tuple(
        _ghostscan_identity_lines(candidate, hint=False,
                                  upgrades=getattr(state, "upgrades", ()))
        + [""]
        + _ghostscan_sweep_lines(candidate, rng, show_forums=True,
                                 day_number=getattr(state, 'current_day', 1))
        + _ghostscan_filter_summary_lines(candidate)
    )
    summary = (
        f"[FILTERED] {len(findings)} finding(s) confirmed — see ▲ labels."
        if findings else
        "[FILTERED] No ghostscan findings confirmed."
    )
    return ToolResult(
        tool=ToolName.GHOSTSCAN, findings=findings,
        raw_lines=raw_lines, summary=summary, filtered=True,
    )


# #61: how many rows each corpus holds. Fixed, not a per-call randint — a
# database that changes length between candidates is not a static database,
# and the length itself was a tell the player could read without scanning.
_BREACH_LIST_LEN = 22

# Static noise, computed once per (game_seed, db_name) and cached. The cache is
# what makes the lists genuinely the same object all campaign long; the seed is
# the GAME seed, so two playthroughs still differ.
_BREACH_NOISE_CACHE: dict[tuple[int, str], tuple[str, ...]] = {}


def _breach_list_noise(game_seed: int, db_name: str) -> tuple[str, ...]:
    """The fixed noise rows for one corpus in one playthrough (#61)."""
    key = (game_seed, db_name)
    cached = _BREACH_NOISE_CACHE.get(key)
    if cached is not None:
        return cached
    rng = _random.Random(_stable_hash(game_seed, db_name, "breach_list")
                         & 0xFFFFFFFF)
    seen: set[str] = set()
    rows: list[str] = []
    # Loop until the list is full rather than for a fixed count: duplicates are
    # possible from a 40x12 pool and a corpus listing the same address twice
    # reads like a rendering bug.
    while len(rows) < _BREACH_LIST_LEN:
        user   = rng.choice(_GS_BREACH_EMAIL_USERS)
        domain = rng.choice(_GS_BREACH_EMAIL_DOMAINS)
        suffix = rng.choice(["", str(rng.randint(1, 99)),
                             "_" + rng.choice(["x", "z", "2", "old"])])
        addr = f"{user}{suffix}@{domain}"
        if addr in seen:
            continue
        seen.add(addr)
        rows.append(addr)
    out = tuple(sorted(rows))
    _BREACH_NOISE_CACHE[key] = out
    return out


def get_breach_lists(candidate: Candidate, game_seed: int,
                     day_number: int) -> list[tuple[str, str, str, list[tuple[str, bool]]]]:
    """Breach database entries for the BreachListPanel (#61).

    Returns (db_name, year, record_count, entries) per UNLOCKED corpus, where
    each entry is (email_string, is_candidate_match).

    Three things changed here, all of them Nick's from playtest:

    • **Alphabetized.** Entries were appended in RNG order, so finding a name
      meant reading all ~22 rows — the panel was a wall of text whose only
      function was to make you spend Ghostscan hours instead. Sorted, scanning
      is cheap, which is the whole point of giving the player a list. The
      candidate's own email sorts into position naturally, which is also
      *better* camouflage than the old random insert index: it can no longer
      sit at a position noise never occupies.

    • **Static for the whole campaign.** The RNG was seeded on `candidate.id`,
      so all six corpora were regenerated for every single candidate —
      verified: no two candidates saw the same contents. A player who
      memorised a list learned nothing, because the list was gone next
      candidate. Noise is now keyed on the GAME seed and cached, so the
      databases are fixed reference material for the run.

    • **Progressively unlocked.** Only corpora unlocked by `day_number`
      (config.BREACH_DB_UNLOCK_DAY) are returned. Difficulty comes from the
      panel growing, and a corpus once added is never removed.

    The candidate's email is layered on top of that fixed noise, in every
    corpus breach_dbs_for_candidate() says they belong to — which now includes
    the second corpus for CROSS_BREACH_REUSE. The list is re-sorted afterwards
    so the seeded address is indistinguishable from a noise row.
    """
    target_email = candidate.email
    seeded = set(breach_dbs_for_candidate(candidate, day_number))
    unlocked = set(config.breach_dbs_unlocked_by(day_number))

    result: list[tuple[str, str, str, list[tuple[str, bool]]]] = []
    for db_name, year, count_label in _GS_BREACH_META:
        if db_name not in unlocked:
            continue
        noise = _breach_list_noise(game_seed, db_name)
        if db_name in seeded:
            entries = [(addr, addr == target_email) for addr in noise]
            if target_email not in noise:
                entries.append((target_email, True))
            entries.sort(key=lambda e: e[0])
        else:
            entries = [(addr, False) for addr in noise]
        result.append((db_name, year, count_label, entries))
    return result


def get_breach_lists_for_day(
    game_seed: int, day: Day
) -> list[tuple[str, str, str, list[str]]]:
    """(db_name, year, count_label, sorted_email_list) for the WHOLE day.

    Batch-3 follow-up (Nick, playtest): get_breach_lists() above is correct
    for a single candidate in isolation, but BreachListPanel used to call it
    fresh on every load_candidate() and replace its whole state — so a real
    breach-carrying candidate's email only ever existed in the panel while
    THEIR dossier happened to be open. In Nick's words: "planted in the list
    in the middle of the round. He only appears on the list when it is his
    turn to be evaluated." That's backwards — a candidate who carries
    BREACH_HIT, LEAKED_PASSWORD, or CROSS_BREACH_REUSE should FULLY have the
    Ghostscan breach-match violation, a standing fact about the day, not
    something that flickers into existence for the duration of their turn.

    This walks every slot in the day (candidate_gen.generate is deterministic
    per (game_seed, day, slot), exactly like generate_hashcrack_day_log()
    above) and unions every candidate's breach_dbs_for_candidate() membership
    onto the fixed per-database noise — so a candidate 4 slots away is
    already sitting in the list the moment the player opens Ghostscan on
    slot 0, discoverable (if not yet identifiable — see the idle-color fix
    a few lines up in BreachListPanel) well before their turn comes up.

    The implication only runs one direction, same as breach_dbs_for_candidate()
    already enforces: a Hashcrack-side signal (BREACH_HIT / LEAKED_PASSWORD /
    CROSS_BREACH_REUSE) always earns a seat in the relevant corpus/corpora
    here, but a candidate can appear in a corpus without carrying a
    Hashcrack-observable kind at all — the two tools corroborate, neither
    implies the other must exist.

    Callers wanting a specific candidate's own row highlighted/confirmed
    layer that on top (see BreachListPanel.load_candidate): this function
    itself carries no notion of "the current candidate," only "who really
    belongs in this corpus today."
    """
    from .candidate_gen import generate as _gen_candidate

    unlocked = set(config.breach_dbs_unlocked_by(day.number))
    real: dict[str, set[str]] = {name: set() for name in unlocked}
    for slot in range(day.candidate_count):
        cand = _gen_candidate(game_seed, day, slot)
        for db_name in breach_dbs_for_candidate(cand, day.number):
            if db_name in real:
                real[db_name].add(cand.email)

    result: list[tuple[str, str, str, list[str]]] = []
    for db_name, year, count_label in _GS_BREACH_META:
        if db_name not in unlocked:
            continue
        noise = set(_breach_list_noise(game_seed, db_name))
        result.append((db_name, year, count_label, sorted(noise | real[db_name])))
    return result


# ─── Credential-event helpers ───────────────────────────────────────────────
#
# 2026-09-14 — what used to be here was the Hashcrack page's own shared
# credential audit log: ~440 lines spanning _hc_candidate_entries,
# _hc_noise_entries, generate_hashcrack_day_log, _render_hc_log,
# get_hashcrack_shared, run_hashcrack_shared and run_hashcrack_filtered_shared.
# The cipher-block rework removed all of it.
#
# The Hashcrack page has no log to render any more — it IS the aperture
# minigame now (see "HASHCRACK — the cipher block" at the end of this module).
# The two row types that carried real evidence and had nowhere else to live,
# HASH_SUBMIT and BREACH_MATCH, were relocated into the Logwatch day log, which
# is already an audit log (BREACH_MATCH was removed again 2026-09-19 — breach
# hits belong to Ghostscan/Hashcrack only); see the credential-rows block at the end of
# _lw_candidate_entries below. The AUTH_OK/AUTH_FAIL bursts did NOT move —
# Logwatch has always generated its own for the kinds it owns, and merging
# would have printed every burst twice.
#
# Deleted rather than parked as dead code deliberately. A renderer nothing
# calls, still computing violation labels from ground truth, is exactly the
# surface this module keeps drifting on — #48 and #57 were each two copies of
# one list that fell out of step, and this would have been a third.
#
# What survives is the small amount still in use: the algorithm label for the
# relocated HASH_SUBMIT rows.

_HC_ALGO_LABEL_MAP = {32: "MD5", 40: "SHA1", 64: "SHA256"}


def _hc_algo(h: str | None) -> str:
    if not h:
        return "?"
    if h.startswith("$2b$"):
        return "bcrypt"
    return _HC_ALGO_LABEL_MAP.get(len(h), "?")




# ─── Logwatch — shared day log ───────────────────────────────────────────────
#
# One combined auth log for the full day, generated once from the game seed.
# Candidate entries are interleaved with noise, sorted chronologically.
#
# Violations planted in the log: brute force (burst on one account), credential
# stuffing (one IP failing across many accounts, then logging in), impossible
# travel, insider (sensitive reads + sudo off-shift), after-hours, low-and-slow
# (scattered sub-threshold failures), claimed-IP mismatch (logins never from
# the claimed IP). Plus honest noise: a benign single typo for ~30% of
# candidates. Daytime activity is kept inside the LW_SHIFT window.
#
# 2026-09-19 overhaul — the page has two surfaces over this one log:
#   get_logwatch_shared(entries, candidate, state=)   — FREE: the Activity Report
#                                                       (core/logwatch_report.py)
#   run_logwatch_shared(entries, candidate, state)    — L: unseals the auth log panel
#                                                       (raw_lines) + report (report_lines)
#   run_logwatch_filtered_shared(...)                 — F: ▲ labels in both
#   get_logwatch_log_lines(...)                       — the panel's lines on their own

_LW_DATE = "2024-01-15"

# City lookup — maps IP prefix to (city, country) string.
# Local / RFC-1918 ranges resolve to None (no tag shown).
_LW_CITY_MAP: dict[str, str | None] = {
    "10.":       None,
    "172.16.":   None,
    "192.168.":  None,
    "185.220.":  "Frankfurt, DE",
    "185.100.":  "Frankfurt, DE",
    "185.130.":  "Frankfurt, DE",
    "185.150.":  "Frankfurt, DE",
    "185.180.":  "Frankfurt, DE",
    "185.200.":  "Frankfurt, DE",
    "103.21.":   "Singapore, SG",
    "45.33.":    "New York, US",
    "138.197.":  "Amsterdam, NL",
    "194.165.":  "Moscow, RU",
    "59.127.":   "Taipei, TW",
    "196.207.":  "Nairobi, KE",
    "177.54.":   "Sao Paulo, BR",
    # Batch-3 task #5: more locations, so foreign-city noise (see
    # config.LW_NOISE_EXTERNAL_CITY_FRACTION) doesn't cluster on a small,
    # easily-memorized set of "always suspicious" cities.
    "51.15.":    "London, GB",
    "13.239.":   "Sydney, AU",
    "94.200.":   "Dubai, AE",
    "49.36.":    "Mumbai, IN",
    "121.254.":  "Seoul, KR",
    "189.203.":  "Mexico City, MX",
    "102.89.":   "Lagos, NG",
    "99.79.":    "Toronto, CA",
}

_LW_CITIES = [
    ("185.220.", "Frankfurt, DE"),
    ("103.21.",  "Singapore, SG"),
    ("45.33.",   "New York, US"),
    ("138.197.", "Amsterdam, NL"),
    ("194.165.", "Moscow, RU"),
    ("59.127.",  "Taipei, TW"),
    ("196.207.", "Nairobi, KE"),
    ("177.54.",  "Sao Paulo, BR"),
    ("51.15.",   "London, GB"),
    ("13.239.",  "Sydney, AU"),
    ("94.200.",  "Dubai, AE"),
    ("49.36.",   "Mumbai, IN"),
    ("121.254.", "Seoul, KR"),
    ("189.203.", "Mexico City, MX"),
    ("102.89.",  "Lagos, NG"),
    ("99.79.",   "Toronto, CA"),
]

_LW_NOISE_USERS   = ["j.morris", "r.chen", "s.patel", "admin", "k.okonkwo",
                      "t.nakamura", "l.vasquez", "d.kowalski", "m.ibrahim",
                      "a.petrov", "b.silva", "c.johannsen", "n.reyes", "p.walsh"]
_LW_NOISE_DOMAINS = ["corp.net", "internal.io", "hackdox.local", "company.org"]
_LW_NOISE_IPS     = ["10.0.1.15", "10.0.1.42", "10.0.2.7", "10.0.3.88",
                      "192.168.0.55", "192.168.1.200", "172.16.0.14"]

# Home/VPN/mobile prefixes for the second-routine-IP noise source
# (config.LW_SECOND_IP_CHANCE, 2026-09-23) — plausible residential/ISP-style
# ranges, deliberately disjoint from _LW_CITIES (the attack/travel city pool)
# and _LW_NOISE_IPS (other users' internal IPs) so this noise can never read
# as either of those. Not resolved through _LW_CITY_MAP — the row is tagged
# with the candidate's own city directly (same place as their claimed IP),
# which is the point: a second source, zero city change.
_LW_HOME_ISP_PREFIXES = ["24.5.", "71.192.", "98.14.", "173.230.", "76.102.", "67.161."]

_LW_SENSITIVE_PATHS = ["/etc/passwd", "/etc/shadow", "/root/.ssh/id_rsa", "/proc/keys"]
_LW_NORMAL_PATHS    = ["/var/log/auth.log", "/home/user/.bash_history",
                        "/etc/cron.d/tasks", "/opt/app/config.json"]


def _lw_ts(secs: int) -> str:
    h, r = divmod(secs % 86400, 3600)
    m, s = divmod(r, 60)
    return f"{_LW_DATE} {h:02d}:{m:02d}:{s:02d}"


def _lw_city(ip: str) -> str | None:
    for prefix, city in _LW_CITY_MAP.items():
        if ip.startswith(prefix):
            return city
    return None


def _lw_ext_ip(rng: _random.Random, city_prefix: str | None = None) -> tuple[str, str | None]:
    """Return (ip, city) for an external IP, optionally from a specific city."""
    if city_prefix:
        ip   = city_prefix + f"{rng.randint(1,254)}.{rng.randint(1,254)}"
        city = _lw_city(ip)
    else:
        prefix, city = rng.choice(_LW_CITIES)
        ip = prefix + f"{rng.randint(1,254)}.{rng.randint(1,254)}"
    return ip, city


@dataclass
class _LogEntry:
    ts_secs:        int
    ts_str:         str
    event:          str          # AUTH_OK | AUTH_FAIL | FILE_READ | SUDO_EXEC | SESSION_END
    ip:             str
    account:        str
    extra:          str          # path for FILE_READ/SUDO_EXEC; empty otherwise
    owner_id:       str | None
    is_suspicious:  bool
    violation_kind: str | None   # "brute_force" | "stuffing" | "impossible_travel" | "insider"
    city:           str | None = None   # populated on AUTH_OK for external IPs


def _lw_candidate_entries(candidate, rng: _random.Random,
                          day_number: int = 1) -> list[_LogEntry]:
    # `day_number` is kept for API stability (it used to seed the BREACH_MATCH
    # rows, removed 2026-09-19). Defaulted so the many
    # existing two-argument callers (tests, mostly) keep working; the real day
    # is threaded through from generate_day_log().
    from .. import config as _cfg

    kinds = {d.kind for d in candidate.truth.discrepancies}
    has_brute    = DiscrepancyKind.BRUTE_FORCE_IN_LOG  in kinds
    has_travel   = DiscrepancyKind.IMPOSSIBLE_TRAVEL   in kinds
    has_insider  = DiscrepancyKind.INSIDER_BEHAVIOR    in kinds
    has_stuffing = DiscrepancyKind.CREDENTIAL_STUFFING in kinds   # v2
    has_after    = DiscrepancyKind.AFTER_HOURS_ACCESS  in kinds   # v2
    has_slow     = DiscrepancyKind.LOW_AND_SLOW        in kinds   # v2
    has_ipmis    = DiscrepancyKind.CLAIMED_IP_MISMATCH in kinds   # v2

    claimed_ip = candidate.dossier.claimed_ip or "10.0.0.1"
    account    = candidate.email
    entries: list[_LogEntry] = []
    t = rng.randint(*_cfg.LW_WORKDAY_WINDOW)
    t_first_login = t

    # The candidate's real login origin. v2: when the claimed IP doesn't match,
    # their logins come from an external address (≠ the dossier claim), which
    # the free-tier renderer already highlights in orange.
    if has_ipmis:
        login_ip, login_city = _lw_ext_ip(rng)
    else:
        login_ip, login_city = claimed_ip, _lw_city(claimed_ip)

    # Normal logins from the candidate's login IP
    for _ in range(rng.randint(*_cfg.LW_NORMAL_LOGIN_COUNT)):
        entries.append(_LogEntry(
            ts_secs=t, ts_str=_lw_ts(t), event="AUTH_OK",
            ip=login_ip, account=account, extra="",
            owner_id=candidate.id, is_suspicious=False, violation_kind=None,
            city=login_city,
        ))
        t += rng.randint(*_cfg.LW_NORMAL_LOGIN_GAP)

    if has_brute:
        # Brute force: rapid AUTH_FAIL on the SAME account, then AUTH_OK.
        # 2026-09-19: random attack city (was always 185.220./Frankfurt, which
        # made "Frankfurt origin" itself a brute-force tell on the report).
        ext_ip, ext_city = _lw_ext_ip(rng)
        burst = rng.randint(*_cfg.LW_BRUTE_BURST_SIZE)
        for i in range(burst):
            entries.append(_LogEntry(
                ts_secs=t+i, ts_str=_lw_ts(t+i), event="AUTH_FAIL",
                ip=ext_ip, account=account, extra="",
                owner_id=candidate.id, is_suspicious=True, violation_kind="brute_force",
                city=None,
            ))
        t += burst + rng.randint(1, 3)
        entries.append(_LogEntry(
            ts_secs=t, ts_str=_lw_ts(t), event="AUTH_OK",
            ip=ext_ip, account=account, extra="",
            owner_id=candidate.id, is_suspicious=True, violation_kind="brute_force",
            city=ext_city,
        ))
        t += rng.randint(*_cfg.LW_BRUTE_COOLDOWN)

    if has_stuffing:
        # v2 Credential stuffing: one external IP sprays AUTH_FAIL across many
        # *other* accounts (few tries each), then lands AUTH_OK on the candidate.
        # 2026-09-19: random attack city (was always the unmapped 45.131.
        # prefix, i.e. an "unresolved" origin = stuffing tell on the report).
        ext_ip, ext_city = _lw_ext_ip(rng)
        sprayed = rng.sample(_LW_NOISE_USERS,
                              min(_cfg.LW_STUFFING_SPRAY_SIZE, len(_LW_NOISE_USERS)))
        for i, fake_user in enumerate(sprayed):
            fake_domain = rng.choice(_LW_NOISE_DOMAINS)
            entries.append(_LogEntry(
                ts_secs=t+i*2, ts_str=_lw_ts(t+i*2), event="AUTH_FAIL",
                ip=ext_ip, account=f"{fake_user}@{fake_domain}", extra="",
                owner_id=None, is_suspicious=False, violation_kind=None,
                city=None,
            ))
        t += len(sprayed)*2 + rng.randint(1, 3)
        entries.append(_LogEntry(
            ts_secs=t, ts_str=_lw_ts(t), event="AUTH_OK",
            ip=ext_ip, account=account, extra="",
            owner_id=candidate.id, is_suspicious=True, violation_kind="stuffing",
            city=ext_city,
        ))
        t += rng.randint(*_cfg.LW_STUFFING_COOLDOWN)

    if has_travel:
        # 2026-09-20: the two cities must be far enough apart that the
        # LW_TRAVEL_GAP between them is impossible at ANY airliner speed —
        # honest business travel is now generated too (see the trip block
        # below), and the two must never be confusable.
        from .logwatch_report import distance_between as _dist
        for _ in range(40):
            city_a_entry, city_b_entry = rng.sample(_LW_CITIES, 2)
            _km = _dist(city_a_entry[1], city_b_entry[1])
            if _km is None or _km >= _cfg.LW_TRAVEL_MIN_KM:
                break
        ip_a = city_a_entry[0] + f"{rng.randint(1,254)}.{rng.randint(1,254)}"
        ip_b = city_b_entry[0] + f"{rng.randint(1,254)}.{rng.randint(1,254)}"
        entries.append(_LogEntry(
            ts_secs=t, ts_str=_lw_ts(t), event="AUTH_OK",
            ip=ip_a, account=account, extra="",
            owner_id=candidate.id, is_suspicious=True, violation_kind="impossible_travel",
            city=city_a_entry[1],
        ))
        t += rng.randint(*_cfg.LW_TRAVEL_GAP)   # 35–90 min apart
        entries.append(_LogEntry(
            ts_secs=t, ts_str=_lw_ts(t), event="AUTH_OK",
            ip=ip_b, account=account, extra="",
            owner_id=candidate.id, is_suspicious=True, violation_kind="impossible_travel",
            city=city_b_entry[1],
        ))
        t += rng.randint(*_cfg.LW_TRAVEL_COOLDOWN)

    if has_insider:
        _win_start, _win_span = _cfg.LW_INSIDER_WINDOW
        t_after = _win_start + rng.randint(0, _win_span)   # 11pm–midnight
        sens1 = rng.choice(_LW_SENSITIVE_PATHS)
        sens2 = rng.choice([p for p in _LW_SENSITIVE_PATHS if p != sens1])
        entries.append(_LogEntry(
            ts_secs=t_after, ts_str=_lw_ts(t_after), event="FILE_READ",
            ip=claimed_ip, account=account, extra=sens1,
            owner_id=candidate.id, is_suspicious=True, violation_kind="insider",
            city=None,
        ))
        t2 = t_after + rng.randint(*_cfg.LW_INSIDER_STEP1_GAP)
        entries.append(_LogEntry(
            ts_secs=t2, ts_str=_lw_ts(t2), event="SUDO_EXEC",
            ip=claimed_ip, account=account, extra="/bin/bash",
            owner_id=candidate.id, is_suspicious=True, violation_kind="insider",
            city=None,
        ))
        t3 = t2 + rng.randint(*_cfg.LW_INSIDER_STEP2_GAP)
        entries.append(_LogEntry(
            ts_secs=t3, ts_str=_lw_ts(t3), event="FILE_READ",
            ip=claimed_ip, account=account, extra=sens2,
            owner_id=candidate.id, is_suspicious=True, violation_kind="insider",
            city=None,
        ))

    if has_after:
        # v2 After-hours: benign-looking activity outside business hours on
        # NORMAL paths (not sensitive). Minor — the player must weigh it, not
        # auto-deny. is_suspicious=True so base/filter call it out.
        _win_start, _win_span = _cfg.LW_AFTERHOURS_WINDOW
        t_pm = _win_start + rng.randint(0, _win_span)   # ~22:00 onward
        entries.append(_LogEntry(
            ts_secs=t_pm, ts_str=_lw_ts(t_pm), event="AUTH_OK",
            ip=login_ip, account=account, extra="",
            owner_id=candidate.id, is_suspicious=True, violation_kind="after_hours",
            city=login_city,
        ))
        t2 = t_pm + rng.randint(*_cfg.LW_AFTERHOURS_GAP)
        entries.append(_LogEntry(
            ts_secs=t2, ts_str=_lw_ts(t2), event="FILE_READ",
            ip=login_ip, account=account, extra=rng.choice(_LW_NORMAL_PATHS),
            owner_id=candidate.id, is_suspicious=True, violation_kind="after_hours",
            city=None,
        ))

    if has_slow:
        # v2 Low-and-slow: a few AUTH_FAIL scattered hours apart so no burst
        # window trips. is_suspicious=False → base run does NOT flag it; only the
        # filter's cross-day correlation (see _lw_render) surfaces it.
        ext_ip, _c = _lw_ext_ip(rng, "91.219.")
        ts0 = rng.randint(*_cfg.LW_SLOW_FIRST_TS)
        for i in range(rng.randint(*_cfg.LW_SLOW_BURST_SIZE)):
            tt = (ts0 + i * rng.randint(*_cfg.LW_SLOW_GAP)) % 86400
            entries.append(_LogEntry(
                ts_secs=tt, ts_str=_lw_ts(tt), event="AUTH_FAIL",
                ip=ext_ip, account=account, extra="",
                owner_id=candidate.id, is_suspicious=False, violation_kind="low_and_slow",
                city=None,
            ))

    if not (has_brute or has_travel or has_insider or has_stuffing or has_after or has_slow):
        for _ in range(rng.randint(*_cfg.LW_CLEAN_ACTIVITY_COUNT)):
            evt  = rng.choice(_cfg.LW_CLEAN_ACTIVITY_EVENTS)
            path = rng.choice(_LW_NORMAL_PATHS) if evt == "FILE_READ" else ""
            entries.append(_LogEntry(
                ts_secs=t, ts_str=_lw_ts(t), event=evt,
                ip=login_ip, account=account, extra=path,
                owner_id=candidate.id, is_suspicious=False, violation_kind=None,
                city=(login_city if evt == "AUTH_OK" else None),
            ))
            t += rng.randint(*_cfg.LW_CLEAN_ACTIVITY_GAP)

    # ── Honest noise: a second routine IP, same city (2026-09-23) ─────────
    # Cheaper and more common than the trip below: NOT travel, no flight-time
    # math needed — the candidate additionally logs in once or twice from an
    # ordinary second source (home network / VPN / mobile) tagged with the
    # SAME city as their claimed login, so it can never form a travel pair
    # (build_logwatch_report skips consecutive-clean pairs with place_a ==
    # place_b). Own RNG stream, independent of the trip roll and of any
    # planted discrepancy, so this doesn't perturb anything else and can
    # stack with a trip on the same candidate.
    _second_rng = _random.Random(_stable_hash(candidate.id, "lw_second_ip") & 0xFFFFFFFF)
    if _second_rng.random() < _cfg.LW_SECOND_IP_CHANCE:
        # login_city is None whenever the login IP is internal (the normal
        # case — claimed_ip is always an internal address, and _lw_city maps
        # 10./172.16./192.168. to None). The report only ever prints the
        # dossier's claimed_location for the claimed-IP origin itself, so
        # matching THAT here (falling back to login_city for the ipmis case,
        # where login_ip is already external) is what keeps this row from
        # accidentally pairing into `travel` against the real login.
        _home_place = login_city or getattr(candidate.dossier, "claimed_location", None) or "On-site"
        _prefix2 = _second_rng.choice(_LW_HOME_ISP_PREFIXES)
        _ip2 = _prefix2 + f"{_second_rng.randint(1,254)}.{_second_rng.randint(1,254)}"
        for _ in range(_second_rng.randint(*_cfg.LW_SECOND_IP_LOGINS)):
            entries.append(_LogEntry(
                ts_secs=t, ts_str=_lw_ts(t), event="AUTH_OK",
                ip=_ip2, account=account, extra="",
                owner_id=candidate.id, is_suspicious=False,
                violation_kind="second_ip", city=_home_place,
            ))
            t += _second_rng.randint(*_cfg.LW_SECOND_IP_GAP)

    # ── Honest noise: a real business trip (2026-09-20) ───────────────────
    # Without this, a second login city ALWAYS meant "deny": impossible travel
    # was the only way one ever appeared. Now LW_LEGIT_TRIP_CHANCE of the
    # candidates who carry no IMPOSSIBLE_TRAVEL actually fly somewhere and log
    # in on arrival, so the player has to read the clock, not the map.
    #
    # The destination is chosen so the gap is at least LW_TRIP_TIME_MARGIN x
    # the flight time it needs — comfortably under LW_MAX_FEASIBLE_KMH, the
    # line the report treats as evidence. Planned HERE, before the shift
    # compression below, so the compression can reserve room for it; the rows
    # themselves are appended after it.
    #
    # Skipped for after-hours candidates: their late login from home would
    # become a return leg with a much tighter gap, and a clean candidate must
    # never produce an infeasible pair.
    _trip: tuple[str, str, int] | None = None     # (ip, city, seconds needed)
    _trip_rng = _random.Random(_stable_hash(candidate.id, "lw_legit_trip") & 0xFFFFFFFF)
    if (not has_travel and not has_after
            and _trip_rng.random() < _cfg.LW_LEGIT_TRIP_CHANCE):
        from .logwatch_report import distance_between as _dist2
        home_city = login_city or candidate.dossier.claimed_location
        options = []
        for prefix, city in _LW_CITIES:
            km = _dist2(home_city, city)
            if km is None or not (200 < km <= _cfg.LW_TRIP_MAX_KM):
                continue
            need = int((km / _cfg.LW_TRIP_CRUISE_KMH + _cfg.LW_TRIP_OVERHEAD_H)
                       * 3600 * _cfg.LW_TRIP_TIME_MARGIN)
            options.append((prefix, city, need))
        if options:
            prefix, city, need = _trip_rng.choice(options)
            _trip = (prefix + f"{_trip_rng.randint(1,254)}.{_trip_rng.randint(1,254)}",
                     city, need)

    # ── Keep the working day inside the shift (2026-09-19) ────────────────
    # The Activity Report counts off-hours activity against the standard
    # shift, so everything on the daytime `t` chain (logins, attack bursts,
    # travel, routine activity, the credential submission) must end before
    # LW_SHIFT_END — otherwise an honest candidate reads as an after-hours
    # worker. Long chains are compressed linearly toward the first login:
    # order is preserved and gaps shrink proportionally (a 35-90 min travel
    # gap stays impossible; second-scale bursts stay bursts). The deliberate
    # off-hours blocks (insider / after-hours) and the scattered low-and-slow
    # failures keep their own clocks.
    _off_clock = {"insider", "after_hours", "low_and_slow"}
    _day_rows = [e for e in entries if e.violation_kind not in _off_clock]
    _latest = _cfg.LW_SHIFT_END - _cfg.LW_SHIFT_END_MARGIN
    _reserve = _trip[2] if _trip else 0      # room for the trip's flight time
    # The chain ends at the running clock `t` (>= the last daytime row); the
    # HASH_SUBMIT row below lands one more gap after it, so reserve that gap.
    _chain_end = max([t] + [e.ts_secs for e in _day_rows])
    _gap_max = _cfg.LW_CLEAN_ACTIVITY_GAP[1]
    if _chain_end + _gap_max + _reserve > _latest and _chain_end > t_first_login:
        _k = (_latest - _gap_max - _reserve - t_first_login) / (_chain_end - t_first_login)
        if _k <= 0:          # no room for the trip after all — drop it
            _trip, _reserve = None, 0
            _k = (_latest - _gap_max - t_first_login) / (_chain_end - t_first_login)
        for e in _day_rows:
            e.ts_secs = t_first_login + int((e.ts_secs - t_first_login) * _k)
            e.ts_str = _lw_ts(e.ts_secs)
        t = t_first_login + int((t - t_first_login) * _k)

    # The planned trip's arrival logins, off the real end of the (possibly
    # compressed) chain so they always land inside the shift.
    if _trip is not None:
        _ip, _city, _need = _trip
        _chain = max([t] + [e.ts_secs for e in entries if e.owner_id == candidate.id])
        _budget = _latest - _chain
        if _budget >= _need:
            tt = _chain + _trip_rng.randint(_need, _budget)
            for _ in range(_trip_rng.randint(*_cfg.LW_TRIP_ARRIVAL_LOGINS)):
                if tt > _latest:
                    break
                entries.append(_LogEntry(
                    ts_secs=tt, ts_str=_lw_ts(tt), event="AUTH_OK",
                    ip=_ip, account=account, extra="",
                    owner_id=candidate.id, is_suspicious=False,
                    violation_kind="legit_trip", city=_city,
                ))
                tt += _trip_rng.randint(*_cfg.LW_TRIP_ARRIVAL_GAP)

    # ── Honest noise: one fumbled password (2026-09-19) ───────────────────
    # A single AUTH_FAIL from the user's own origin just before their first
    # login, for any candidate at LW_BENIGN_TYPO_CHANCE. Without it, "has a
    # failed login at all" was itself a tell on the Activity Report. Own RNG
    # stream so no other row in this candidate's block moves.
    _typo_rng = _random.Random(_stable_hash(candidate.id, "lw_benign_typo") & 0xFFFFFFFF)
    if _typo_rng.random() < _cfg.LW_BENIGN_TYPO_CHANCE:
        tt = max(0, t_first_login - _typo_rng.randint(*_cfg.LW_BENIGN_TYPO_LEAD))
        entries.append(_LogEntry(
            ts_secs=tt, ts_str=_lw_ts(tt), event="AUTH_FAIL",
            ip=login_ip, account=account, extra="",
            owner_id=candidate.id, is_suspicious=False,
            violation_kind="benign_typo", city=None,
        ))

    # ── Credential submission row (HASH_SUBMIT) ───────────────────────────
    #
    # 2026-09-14 the cipher-block rework relocated two credential rows here
    # from the old Hashcrack audit log. 2026-09-19 (Logwatch report overhaul,
    # Nick): the BREACH_MATCH corpus rows were REMOVED again — breach hits are
    # Ghostscan's (breach panel) and Hashcrack's (cipher readout) business,
    # never Logwatch's. HASH_SUBMIT stays as neutral context: which credential
    # was submitted and from which IP. Deliberately is_suspicious=False —
    # Logwatch owns no credential violation (see
    # test_no_tool_claims_a_violation_another_tool_owns).
    h_val = candidate.dossier.submitted_hash or ""
    if h_val:
        t += rng.randint(*_cfg.LW_CLEAN_ACTIVITY_GAP)
        entries.append(_LogEntry(
            ts_secs=t, ts_str=_lw_ts(t), event="HASH_SUBMIT",
            ip=login_ip, account=account,
            extra=f"{_hc_algo(h_val)}:{h_val[:16]}..",
            owner_id=candidate.id, is_suspicious=False,
            violation_kind="credential_artifact", city=None,
        ))

    return entries


def _lw_noise_entries(rng: _random.Random, count: int) -> list[_LogEntry]:
    from .. import config as _cfg

    entries: list[_LogEntry] = []
    for _ in range(count):
        user   = rng.choice(_LW_NOISE_USERS)
        domain = rng.choice(_LW_NOISE_DOMAINS)
        t      = rng.randint(*_cfg.LW_NOISE_TIME_WINDOW)
        evt    = rng.choice(_cfg.LW_NOISE_EVENT_WEIGHTS)
        path   = rng.choice(_LW_NORMAL_PATHS) if evt == "FILE_READ" else ""
        # Batch-3 task #5: a slice of noise AUTH_OK logins come from the same
        # external-city pool violations use (_LW_CITIES), rather than only
        # the internal noise IPs. Otherwise a foreign city tag is ALWAYS a
        # violation or the candidate's own legit foreign login — the player
        # can "solve" Logwatch by scanning for exotic cities alone, never
        # reading the account/pattern around them.
        if evt == "AUTH_OK" and rng.random() < _cfg.LW_NOISE_EXTERNAL_CITY_FRACTION:
            ip, city = _lw_ext_ip(rng)
        else:
            ip   = rng.choice(_LW_NOISE_IPS)
            city = _lw_city(ip) if evt == "AUTH_OK" else None
        entries.append(_LogEntry(
            ts_secs=t, ts_str=_lw_ts(t), event=evt,
            ip=ip, account=f"{user}@{domain}", extra=path,
            owner_id=None, is_suspicious=False, violation_kind=None,
            city=city,
        ))
    return entries


def generate_day_log(game_seed: int, day) -> list[_LogEntry]:
    """Shared server log for the full day. Volume scales with day number per config."""
    from .. import config as _cfg
    from .candidate_gen import generate as _gen_candidate

    rng = _random.Random(_stable_hash(game_seed, day.number, "day_log") & 0xFFFFFFFF)
    all_entries: list[_LogEntry] = []

    for slot in range(day.candidate_count):
        cand = _gen_candidate(game_seed, day, slot)
        crng = _random.Random(_stable_hash(game_seed, day.number, slot, "lw_entries") & 0xFFFFFFFF)
        all_entries.extend(_lw_candidate_entries(cand, crng, day.number))

    # Noise count from config — scaled per day. Reads the CURVE day (Endless
    # maps its shift onto a campaign-equivalent day; identity in the campaign)
    # and is capped at LW_ENTRIES_MAX so the geometric growth can't run away.
    cday       = _cfg.curve_day(day.number)
    base_noise = _cfg.LW_ENTRIES_BY_DAY.get(cday, _cfg.LW_ENTRIES_DEFAULT)
    last_key   = max(_cfg.LW_ENTRIES_BY_DAY.keys()) if _cfg.LW_ENTRIES_BY_DAY else 1
    if cday > last_key:
        extra_days = cday - last_key
        base_noise = int(_cfg.LW_ENTRIES_BY_DAY.get(last_key, _cfg.LW_ENTRIES_DEFAULT)
                         * (_cfg.LW_ENTRIES_SCALE_FACTOR ** extra_days))
    base_noise   = min(base_noise, _cfg.LW_ENTRIES_MAX)
    target_noise = max(_cfg.LW_ENTRIES_MIN, base_noise - len(all_entries))
    all_entries.extend(_lw_noise_entries(rng, target_noise))
    all_entries.sort(key=lambda e: e.ts_secs)
    return all_entries


def _lw_render(
    entries:          list[_LogEntry],
    target_id:        str | None,
    candidate,
    annotate:         bool = False,
    explicit_tags:    bool = False,
    upgrade_highlight: bool = False,
    target_rows_out:  list[int] | None = None,
) -> tuple[str, ...]:
    """Render the shared day log (the Logwatch page's right-hand auth log panel).

    2026-09-19 overhaul — what each tier prints:
      base (annotate / plain) : every row; the target account's rows in yellow,
                                AUTH_OK rows from an IP other than the claimed
                                one tinted orange (a fact the free report
                                already states). NO labels — the player reads
                                the shapes themselves.
      explicit_tags (filter)  : the target's engine-flagged rows in red with
                                ▲ VIOLATION_TYPE labels, plus the low-and-slow
                                correlation line.
      upgrade_highlight (HUD) : a neutral ▸ in the gutter of the target's rows
                                the engine considers part of an anomaly. The
                                SAME mark for every kind and never any text —
                                the Log Analyzer HUD points, it does not name.
                                Low-and-slow rows are not marked (they are
                                sub-threshold by design).
    `annotate` is kept for API compatibility and no longer adds anything.
    `target_rows_out`, if given, receives the line index of every target row
    (the panel's [ / ] jump keys use it).
    """
    claimed_ip = (candidate.dossier.claimed_ip or "") if candidate else ""

    lines: list[str] = [
        f"[#3d6478]── auth log · {_LW_DATE} · all accounts ──[/]",
    ]
    if claimed_ip:
        lines.append(f"[#6b7785]target claims[/] [#ffd93d]{claimed_ip}[/]  "
                     f"[dim]rows in yellow are this account[/]")
    lines.append("")

    evt_col = {
        "AUTH_OK":      "#00ff9f",
        "AUTH_FAIL":    "#ff5470",
        "FILE_READ":    "#7dd3c0",
        "SUDO_EXEC":    "#ff8c42",
        "SESSION_END":  "#6b7785",
        # HASH_SUBMIT: neutral credential context (which credential was
        # submitted, from where). Never a verdict — naming a credential
        # violation is Hashcrack's job. (BREACH_MATCH removed 2026-09-19.)
        "HASH_SUBMIT":  "#c084fc",
    }
    _TAGS = {
        "brute_force":       ("#ff5470", "BRUTE_FORCE_IN_LOG", "same account hammered, then a login"),
        "stuffing":          ("#ff5470", "CREDENTIAL_STUFFING", "one source, many accounts"),
        "impossible_travel": ("#ff8c42", "IMPOSSIBLE_TRAVEL", ""),
        "insider":           ("#ff8c42", "INSIDER_BEHAVIOR", "after-hours + privilege escalation"),
        "after_hours":       ("#ffd93d", "AFTER_HOURS_ACCESS", "minor — corroborate"),
    }
    prev_vk: str | None = None

    def _row(e: _LogEntry, col: str, gutter: str) -> str:
        ec      = evt_col.get(e.event, "#6b7785")
        city_s  = f"  [dim]\\[{e.city}][/]" if e.city else ""
        extra_s = f"  {e.extra}" if e.extra else ""
        return (f"{gutter}[{col}]{e.ts_str[11:]}  [/][{ec}]{e.event:<12}[/][{col}] "
                f"{e.ip:<15}  {e.account}{extra_s}[/]{city_s}")

    for e in entries:
        is_mine = target_id is not None and e.owner_id == target_id
        if not is_mine:
            prev_vk = None
            lines.append(_row(e, "#2e3d4f", "  "))
            continue
        if target_rows_out is not None:
            target_rows_out.append(len(lines))
        gutter = ("[#ffb454]▸[/] " if (upgrade_highlight and e.is_suspicious
                                       and not explicit_tags) else "  ")
        if explicit_tags and e.is_suspicious:
            lines.append(_row(e, "#ff5470", gutter))
            tag = _TAGS.get(e.violation_kind or "")
            if tag and prev_vk != e.violation_kind:
                tcol, name, note = tag
                if e.violation_kind == "impossible_travel" and e.city:
                    note = e.city
                lines.append(f"    [{tcol}][b]▲ {name}[/][/]"
                             + (f"  [dim]{note}[/]" if note else ""))
            prev_vk = e.violation_kind
            continue
        prev_vk = None
        mismatch = e.event == "AUTH_OK" and claimed_ip and e.ip != claimed_ip
        lines.append(_row(e, "#ff8c42" if mismatch else "#ffd93d", gutter))

    # Low-and-slow only surfaces under the filter's correlation — each
    # failure is sub-threshold on its own.
    if explicit_tags and target_id:
        slow = [e for e in entries
                if e.owner_id == target_id and e.violation_kind == "low_and_slow"]
        if slow:
            lines.append("")
            lines.append(
                f"  [#ff5470][b]▲ LOW_AND_SLOW[/][/]  {len(slow)} auth failures from "
                f"{slow[0].ip} scattered across the day (each sub-threshold)")

    lines.append("")
    lines.append(f"[dim]{len(entries)} entries[/]")
    return tuple(lines)


def _lw_report_lines(entries, candidate, state, log_state: str,
                     hud: bool = False, width: int | None = None) -> tuple[str, ...]:
    """The Activity Report (centre column) for one tier. See core/logwatch_report."""
    from . import logwatch_report as _lr
    report = _lr.build_logwatch_report(entries, candidate)
    ups = getattr(state, "upgrades", ()) or ()
    hud = hud or config.UPGRADE_LOG_HIGHLIGHT in ups
    notes = config.UPGRADE_LOG_TRIAGE in ups      # Threat Triage HUD (2026-09-20)
    travel = config.UPGRADE_LOG_MAP_TRAVEL in ups  # Flight Time Analyzer
    conf = (_lr.filter_confirmations(entries, candidate, report)
            if log_state == "filtered" else ())
    cost = tool_cost(state, "logwatch") if state is not None else None
    return _lr.render_report(report, log_state=log_state, hud=hud, notes=notes,
                             travel=travel, confirmations=conf, pull_cost=cost,
                             width=width)


def get_logwatch_shared(entries: list[_LogEntry], candidate,
                        upgrade_highlight: bool = False, state=None,
                        width: int | None = None) -> tuple[str, ...]:
    """FREE tier: the Activity Report with the auth log still sealed.

    (Before 2026-09-19 this returned the whole raw log — see
    core/logwatch_report.py for why that changed.) `upgrade_highlight` is the
    Log Analyzer HUD; `state`, when given, also supplies the upgrade set and
    the ⏱ cost shown in the footer.
    """
    return _lw_report_lines(entries, candidate, state, "sealed",
                            hud=upgrade_highlight, width=width)


def get_logwatch_log_lines(entries: list[_LogEntry], candidate, state=None, *,
                           filtered: bool = False,
                           target_rows_out: list[int] | None = None) -> tuple[str, ...]:
    """The auth log panel's lines for the current candidate."""
    hud = config.UPGRADE_LOG_HIGHLIGHT in (getattr(state, "upgrades", ()) or ())
    return _lw_render(entries, candidate.id, candidate, explicit_tags=filtered,
                      upgrade_highlight=hud, target_rows_out=target_rows_out)


def run_logwatch_shared(entries: list[_LogEntry], candidate, state,
                        width: int | None = None) -> ToolResult:
    """Base run (L): pulls the auth log into the panel. findings=() — the
    player reads the log themselves. raw_lines = the log panel; report_lines
    = the Activity Report re-rendered with the log open."""
    _charge(state, "logwatch")
    raw_lines = get_logwatch_log_lines(entries, candidate, state)
    report = _lw_report_lines(entries, candidate, state, "open", width=width)
    return ToolResult(tool=ToolName.LOGWATCH, findings=(), raw_lines=raw_lines,
                      summary="auth log pulled — examine it in the right panel",
                      report_lines=report)


def run_logwatch_filtered_shared(entries: list[_LogEntry], candidate, state,
                                 width: int | None = None) -> ToolResult:
    """Filter: explicit ▲ VIOLATION_TYPE labels in the log AND a ▲ CONFIRMED
    block on the report."""
    _charge(state, "logwatch", filter=True)
    findings  = _findings_from(candidate, ToolName.LOGWATCH)
    raw_lines = get_logwatch_log_lines(entries, candidate, state, filtered=True)
    report = _lw_report_lines(entries, candidate, state, "filtered", width=width)
    summary = (
        f"[FILTERED] {len(findings)} violation(s) confirmed — see ▲ labels."
        if findings else
        "[FILTERED] No violations confirmed."
    )
    return ToolResult(
        tool=ToolName.LOGWATCH, findings=findings,
        raw_lines=raw_lines, summary=summary, filtered=True,
        report_lines=report,
    )



# ─── Base tool runs ──────────────────────────────────────────────────────────

def run_ghostscan(candidate: Candidate, state) -> ToolResult:
    """Alias for run_ghostscan_shared — kept for backward compat."""
    return run_ghostscan_shared(candidate, state)


def run_logwatch(candidate: Candidate, state) -> ToolResult:
    """Legacy stub — use run_logwatch_shared() via app.py runners dict."""
    _charge(state, "logwatch")
    return ToolResult(tool=ToolName.LOGWATCH, findings=(),
                      raw_lines=("(legacy — use shared day log)",), summary="Run via logwatch page.")


# run_hashcrack() / run_hashcrack_filtered() used to sit here as legacy stubs,
# pointing callers at run_hashcrack_shared(). Both were removed on 2026-09-14
# along with the shared log itself: a stub whose docstring redirects to a
# function that no longer exists is worse than no stub. Hashcrack has no
# run/filter entry point at all now — the page is the cipher-block aperture
# minigame, driven from IntakeScreen._open_aperture.

# ─── Stegotool constants & helpers ────────────────────────────────────────────

_ST_IMAGE_TYPES  = ["PNG", "JPEG", "PNG", "PNG"]
_ST_SCENARIOS    = ["profile photo", "header image", "avatar upload", "screenshot"]
_ST_C2_PAYLOADS  = ["base64-encoded command string", "XOR-encrypted instruction block",
                     "URL-encoded callback address"]


def _stego_pixel_grid(candidate: Candidate, tier: str) -> list[str]:
    """Render the submitted image as a pixel-art grid of coloured █ chars.

    tier: "free"   — image loads with subtle blue tint over anomalous zone
          "scan"   — hot zone blooms amber/red, cluster clearly visible
          "filter" — hot zone turns bright red, [PAYLOAD] label injected

    Grid size scales with discrepancy severity (larger = harder to inspect):
      no stego     → 24 × 10
      stego_payload → 32 × 14
      c2_channel   → 40 × 18
    """
    rng = _random.Random(int(candidate.id, 16) ^ 0xB10CA0DE)

    has_payload = any(d.kind == DiscrepancyKind.STEGO_PAYLOAD_PRESENT
                      for d in candidate.truth.discrepancies)
    has_c2      = any(d.kind == DiscrepancyKind.COVERT_C2_CHANNEL
                      for d in candidate.truth.discrepancies)
    has_enc     = any(d.kind == DiscrepancyKind.ENCRYPTED_PAYLOAD
                      for d in candidate.truth.discrepancies)  # v2
    suspicious  = has_payload or has_c2 or has_enc

    # Grid dimensions
    if has_c2:
        cols, rows = 40, 18
    elif has_payload:
        cols, rows = 32, 14
    else:
        cols, rows = 24, 10

    # Pick a visual style for this candidate (0=gradient, 1=thermal,
    # 2=photo, 3=blueprint, 4=terminal)
    style = rng.randint(0, 4)

    # Pre-generate per-pixel noise so colors are deterministic across tiers
    # Layout: noise_grid[y][x] ∈ [-12, 12]
    noise_grid: list[list[int]] = [
        [rng.randint(-12, 12) for _ in range(cols)]
        for _ in range(rows)
    ]

    # Hot zone — fixed for this candidate, same coordinates every tier
    if suspicious:
        hz_x = rng.randint(0, max(0, cols // 2 - 1))
        hz_y = rng.randint(0, max(0, rows // 2 - 1))
        hz_w = rng.randint(max(3, cols // 5), cols // 2)
        hz_h = rng.randint(max(2, rows // 4), rows // 2)
        # Separate jitter RNG so hot-zone cell colours are also deterministic
        hz_rng = _random.Random(int(candidate.id, 16) ^ 0xDEADC0DE)
        hz_jitter: list[list[int]] = [
            [hz_rng.randint(0, 40) for _ in range(hz_w)]
            for _ in range(hz_h)
        ]
    else:
        hz_x = hz_y = hz_w = hz_h = 0
        hz_jitter = []

    def _base_rgb(x: int, y: int) -> tuple[int, int, int]:
        fx = x / max(1, cols - 1)
        fy = y / max(1, rows - 1)
        n  = noise_grid[y][x]
        if style == 0:   # gradient: blue → purple across x, green drift on y
            r = int(40  + fx * 150 + n)
            g = int(50  + fy * 110 + n)
            b = int(140 + (1 - fx) * 80 + n)
        elif style == 1: # thermal: warm centre, cool edges
            dist = ((fx - 0.5) ** 2 + (fy - 0.5) ** 2) ** 0.5
            heat = max(0.0, 1.0 - dist * 1.8)
            r = int(80  + heat * 160 + n)
            g = int(20  + heat * 110 + n)
            b = int(5   + heat * 50  + n)
        elif style == 2: # photo: warm muted blobs
            blob = max(0.0, 0.9 - ((fx - 0.4) ** 2 + (fy - 0.35) ** 2))
            r = int(110 + blob * 100 + n)
            g = int(90  + blob * 80  + n)
            b = int(70  + blob * 60  + n)
        elif style == 3: # blueprint: dark blue grid tones
            r = int(8  + abs(n) // 4)
            g = int(18 + abs(n) // 4)
            b = int(55 + fx * 45 + fy * 25 + n)
        else:            # terminal: green-on-black scanline
            r = int(4  + abs(n) // 4)
            g = int(35 + fy * 55 + fx * 30 + n)
            b = int(4  + abs(n) // 4)
        return (max(0, min(255, r)),
                max(0, min(255, g)),
                max(0, min(255, b)))

    lines: list[str] = []
    for y in range(rows):
        row = ""
        for x in range(cols):
            r, g, b = _base_rgb(x, y)

            in_zone = (suspicious and
                       hz_x <= x < hz_x + hz_w and
                       hz_y <= y < hz_y + hz_h)

            if in_zone:
                jx = x - hz_x
                jy = y - hz_y
                j  = hz_jitter[jy][jx]
                if tier == "free":
                    # Subtle: push blue channel up, dull red slightly
                    b = min(255, b + 35)
                    r = max(0,   r - 15)
                elif tier == "scan":
                    # Amber bloom — anomaly confirmed
                    r = min(255, 185 + j)
                    g = max(0,    75 + j // 2)
                    b = max(0,    15 + j // 4)
                else:   # "filter"
                    # Bright red — payload extracted
                    r = min(255, 210 + j // 2)
                    g = max(0,    25 + j // 3)
                    b = max(0,    10 + j // 4)

            row += f"[#{r:02x}{g:02x}{b:02x}]█[/]"
        lines.append(row)

    # Inject [PAYLOAD] label at the mid-point of the hot zone for filter tier
    if tier == "filter" and suspicious:
        label_row = hz_y + hz_h // 2 + 1          # one row below zone centre
        label_row = min(label_row, len(lines))
        label = "[#ff5470][b]  ↑ PAYLOAD REGION[/][/]"
        lines.insert(label_row, label)

    return lines


def _stego_entropy_bar(value: int, band: tuple[int, int], colour: str,
                       width: int | None = None, scale_max: int = 100) -> str:
    """Magnitude bar for a 0-100 severity score -- fills left-to-right like
    the Logwatch report's bars (logwatch_report._bar), with │ ticks
    bracketing the expected/clean band. A channel that fills past the
    upper tick reads as anomalous by shape alone; `colour` is the caller's
    job to gate behind the Channel Colorizer upgrade
    (config.UPGRADE_STEGO_RGB_COLOR) -- the bar's shape is free either way.
    """
    w = width or config.STEGO_BAR_WIDTH
    band_lo, band_hi = band
    filled = round(min(value, scale_max) / scale_max * w)
    lo_tick = min(w - 1, max(0, round(band_lo / scale_max * w)))
    hi_tick = min(w - 1, max(0, round(band_hi / scale_max * w)))
    cells: list[str] = []
    for i in range(w):
        if i in (lo_tick, hi_tick):
            cells.append("[#6b7785]│[/]")
        elif i < filled:
            cells.append(f"[{colour}]█[/]")
        else:
            cells.append("[#20303c]░[/]")
    over = f"[{colour}]▸[/]" if value > scale_max else ""
    return "".join(cells) + over


def _stego_point_bar(value: float, scale: tuple[float, float],
                     band: tuple[float, float], marker: str, colour: str,
                     width: int | None = None) -> str:
    """Point-value bar for a metric that should sit near a centre band (RS
    ratio, LSB autocorrelation) rather than accumulate from zero like the
    entropy bars above. Draws the expected band as a shaded strip between
    two ticks and plots the observed value as a single marker glyph.
    """
    w = width or config.STEGO_BAR_WIDTH
    lo, hi = scale
    band_lo, band_hi = band

    def pos(v: float) -> int:
        v = max(lo, min(hi, v))
        return round((v - lo) / (hi - lo) * (w - 1))

    band_a, band_b = pos(band_lo), pos(band_hi)
    vpos = pos(value)
    cells: list[str] = []
    for i in range(w):
        if i == vpos:
            cells.append(f"[{colour}][b]{marker}[/][/]")
        elif band_a <= i <= band_b:
            cells.append("[#3d4f5e]▒[/]")
        else:
            cells.append("[#20303c]░[/]")
    return "".join(cells)


def _stego_range_col(value: float, band: tuple[float, float], rgb_color: bool) -> str:
    """Two-tier severity colour for a point-value metric (RS ratio,
    autocorrelation), gated behind the same Channel Colorizer upgrade as
    the RGB entropy bars -- neutral grey until it's owned."""
    if not rgb_color:
        return "#c8d4e1"
    band_lo, band_hi = band
    return "#ff5470" if (value < band_lo or value > band_hi) else "#00ff9f"


def _stego_pair_col(x: float, y: float, band: tuple[float, float], rgb_color: bool) -> str:
    """Severity colour for the RS 2-D point -- red if EITHER axis has
    drifted outside the expected band, gated behind Channel Colorizer."""
    if not rgb_color:
        return "#c8d4e1"
    lo, hi = band
    out = x < lo or x > hi or y < lo or y > hi
    return "#ff5470" if out else "#00ff9f"


def _stego_rs_plane(x: float, y: float, scale: tuple[float, float],
                    band: tuple[float, float], colour: str,
                    width: int | None = None, height: int | None = None) -> list[str]:
    """2-D scatter of the RS pair -- R-group ratio on X, S-group ratio on Y,
    both sharing `scale`. The expected band is drawn as a shaded square on
    both axes at once; a clean image's point sits inside it, and embedding
    (which pushes R up and S down, or vice versa) drifts the point off the
    square diagonally -- a paired divergence that two disconnected 1-D bars
    couldn't show as one shape.
    """
    w = width or config.STEGO_RS_PLANE_W
    h = height or config.STEGO_RS_PLANE_H
    lo, hi = scale
    band_lo, band_hi = band

    def colpos(v: float) -> int:
        v = max(lo, min(hi, v))
        return round((v - lo) / (hi - lo) * (w - 1))

    def rowpos(v: float) -> int:
        # inverted: a higher S-ratio plots nearer the top row
        v = max(lo, min(hi, v))
        return round((hi - v) / (hi - lo) * (h - 1))

    bx0, bx1 = sorted((colpos(band_lo), colpos(band_hi)))
    by0, by1 = sorted((rowpos(band_hi), rowpos(band_lo)))
    px, py = colpos(x), rowpos(y)

    # Rounded corners (╭╮╰╯) deliberately, not the pixel-grid's sharp ┌┐└┘ —
    # besides reading as a distinct "plot" frame from the image frame above
    # it, get_stego_stats() strips everything between a "┌─" line and the
    # matching "└" as the (relocated) pixel grid; a sharp-cornered box here
    # would vanish from the stamp-analysis terminal along with it.
    lines: list[str] = [f"[#3d6478]╭{'─' * w}╮[/]"]
    for row in range(h):
        cells: list[str] = []
        for col in range(w):
            if col == px and row == py:
                cells.append(f"[{colour}][b]●[/][/]")
            elif bx0 <= col <= bx1 and by0 <= row <= by1:
                cells.append("[#3d4f5e]▒[/]")
            else:
                cells.append("[#20303c]·[/]")
        lines.append(f"[#3d6478]│[/]{''.join(cells)}[#3d6478]│[/]")
    lines.append(f"[#3d6478]╰{'─' * w}╯[/]")
    return lines


def get_stego_image_info(candidate: Candidate,
                         upgrades: set | None = None) -> tuple[str, ...]:
    """Free image metadata — always visible in the stegotool terminal, no cost."""
    return tuple(_stego_image_lines(candidate, upgrades))


def _stego_image_lines(candidate: Candidate,
                       upgrades: set | None = None) -> list[str]:
    """Free tier: pixel-art grid + raw image statistics — always visible, no cost.

    Batch-3 task #4f: the R/G/B channel entropy NUMBERS are always shown —
    only their red/orange/green severity colouring is gated behind
    config.UPGRADE_STEGO_RGB_COLOR ("Channel Colorizer"). Fractions are a
    dead giveaway in color, per Nick; the raw numbers alone are what a
    player is meant to be able to read unaided.
    """
    _rgb_color = bool(upgrades) and config.UPGRADE_STEGO_RGB_COLOR in upgrades
    rng = _random.Random(int(candidate.id, 16) ^ 0x57E60001)

    has_payload = any(d.kind == DiscrepancyKind.STEGO_PAYLOAD_PRESENT
                      for d in candidate.truth.discrepancies)
    has_c2      = any(d.kind == DiscrepancyKind.COVERT_C2_CHANNEL
                      for d in candidate.truth.discrepancies)
    has_enc     = any(d.kind == DiscrepancyKind.ENCRYPTED_PAYLOAD
                      for d in candidate.truth.discrepancies)  # v2
    suspicious  = has_payload or has_c2 or has_enc

    # Multiple points of contact: a suspicious image doesn't push every
    # readout out of range together. Each signal group rolls its own "tell"
    # independently, so sometimes only the RS plane reads anomalous while
    # the RGB bars look clean, or the reverse -- no single readout is a
    # reliable verdict on its own. A clean image never tells on any axis.
    if suspicious:
        tell_entropy = rng.random() < config.STEGO_TELL_CHANCE_ENTROPY
        tell_rs      = rng.random() < config.STEGO_TELL_CHANCE_RS
        tell_corr    = rng.random() < config.STEGO_TELL_CHANCE_CORR
        if not (tell_entropy or tell_rs or tell_corr):
            # never leave a genuinely suspicious image with zero free-tier
            # tell -- force one signal so there's always at least one
            # thread to pull before reaching for the stamp mechanic.
            tell_entropy, tell_rs, tell_corr = rng.choice([
                (True, False, False), (False, True, False), (False, False, True),
            ])
    else:
        tell_entropy = tell_rs = tell_corr = False

    img_file    = candidate.dossier.submitted_image_path or "image.png"
    img_type    = "PNG" if img_file.endswith(".png") else "JPEG"
    width       = rng.choice([640, 800, 1024, 1280])
    height      = rng.choice([480, 600,  768,  960])
    file_kb     = rng.randint(180, 820)

    lines: list[str] = []

    # ── Pixel art grid (free tier) ─────────────────────────────────────────
    lines.append(f"[#3d6478]┌─ {img_file}  {width}×{height}  {img_type}  {file_kb}KB {'─' * max(0, 34 - len(img_file))}┐[/]")
    lines.extend(_stego_pixel_grid(candidate, "free"))
    lines.append("[#3d6478]└" + "─" * 42 + "┘[/]")
    lines.append("")

    # ── Raw channel statistics ─────────────────────────────────────────────
    lines.append("[#3d6478]-- image statistics ------------------------------------[/]")

    # Channel LSB entropy scores — suspicious images have one channel pushed high
    r_score = rng.randint(12, 28)
    g_score = rng.randint(10, 25)
    b_score = rng.randint(11, 26)

    if tell_entropy:
        # plant one anomalously high channel
        hot_ch = rng.choice(["R", "G", "B"])
        hot_score = rng.randint(62, 94)
        if hot_ch == "R": r_score = hot_score
        elif hot_ch == "G": g_score = hot_score
        else: b_score = hot_score
        if has_c2:
            # C2 tends to use all channels — raise a second one too
            other_chs = [c for c in ["R", "G", "B"] if c != hot_ch]
            second_ch = rng.choice(other_chs)
            second_score = rng.randint(48, 71)
            if second_ch == "R": r_score = second_score
            elif second_ch == "G": g_score = second_score
            else: b_score = second_score

    def score_col(s: int) -> str:
        if not _rgb_color:
            return "#c8d4e1"
        if s >= 61: return "#ff5470"
        if s >= 31: return "#ff8c42"
        return "#00ff9f"

    ent_band = config.STEGO_ENTROPY_EXPECTED
    lines.append(f"  {'R channel entropy':<19}{_stego_entropy_bar(r_score, ent_band, score_col(r_score))} {r_score:>3}/100")
    lines.append(f"  {'G channel entropy':<19}{_stego_entropy_bar(g_score, ent_band, score_col(g_score))} {g_score:>3}/100")
    lines.append(f"  {'B channel entropy':<19}{_stego_entropy_bar(b_score, ent_band, score_col(b_score))} {b_score:>3}/100")
    lines.append("")

    # RS analysis ratio — clean images near 1.0; stego images show divergence.
    # Plotted as one 2-D point (R on X, S on Y) rather than two separate
    # numbers, since the two ratios move in OPPOSITE directions together
    # under embedding — a shape a pair of disconnected bars can't show.
    if tell_rs:
        rs_r = round(rng.uniform(1.08, 1.22), 3)
        rs_s = round(rng.uniform(0.78, 0.92), 3)
    else:
        rs_r = round(rng.uniform(0.97, 1.03), 3)
        rs_s = round(rng.uniform(0.97, 1.03), 3)
    rs_scale = config.STEGO_RS_SCALE
    rs_band = config.STEGO_RS_EXPECTED
    rs_col = _stego_pair_col(rs_r, rs_s, rs_band, _rgb_color)
    lines.append(f"  RS pair analysis  [dim](R -> , S ^)[/]")
    lines.extend(_stego_rs_plane(rs_r, rs_s, rs_scale, rs_band, rs_col))
    lines.append(f"    R {rs_r:.3f}   S {rs_s:.3f}")
    lines.append("")

    # Pixel pair correlation — clean near 0.0; stego shows disruption
    corr = round(rng.uniform(0.08, 0.19) if tell_corr else rng.uniform(-0.02, 0.03), 3)
    corr_scale = config.STEGO_CORR_SCALE
    corr_band = config.STEGO_CORR_EXPECTED
    lines.append(f"  {'LSB autocorrelation':<19}{_stego_point_bar(corr, corr_scale, corr_band, 'x', _stego_range_col(corr, corr_band, _rgb_color))} {corr:+.3f}")

    return lines


def _stego_scan_lines(candidate: Candidate) -> list[str]:
    """Scan tier: grid transforms (hot zone lit amber/red) + suspicion score."""
    rng = _random.Random(int(candidate.id, 16) ^ 0x5C4A0042)

    has_payload = any(d.kind == DiscrepancyKind.STEGO_PAYLOAD_PRESENT
                      for d in candidate.truth.discrepancies)
    has_c2      = any(d.kind == DiscrepancyKind.COVERT_C2_CHANNEL
                      for d in candidate.truth.discrepancies)
    has_enc     = any(d.kind == DiscrepancyKind.ENCRYPTED_PAYLOAD
                      for d in candidate.truth.discrepancies)  # v2
    suspicious  = has_payload or has_c2 or has_enc

    if suspicious:
        score = rng.randint(63, 91) if (has_c2 or has_enc) else rng.randint(48, 72)
    else:
        score = rng.randint(4, 28)

    score_col = "#ff5470" if score >= 61 else ("#ff8c42" if score >= 31 else "#00ff9f")
    verdict   = "likely embedded payload" if score >= 61 else (
                "investigate further"    if score >= 31 else "likely clean")

    # Bar: filled = score/100 of 30 chars
    bar_filled = round(score * 30 // 100)
    bar_empty  = 30 - bar_filled
    score_bar  = f"[{score_col}]{'█' * bar_filled}[/][#3d4f5e]{'░' * bar_empty}[/]"

    lines: list[str] = []

    # ── Transformed pixel grid (scan tier) ────────────────────────────────
    if suspicious:
        lines.append("[#ff8c42]-- anomalous region detected ----------------------------[/]")
    else:
        lines.append("[#00ff9f]-- image appears clean ----------------------------------[/]")
    lines.extend(_stego_pixel_grid(candidate, "scan"))
    lines.append("")

    # ── Suspicion score + stats ───────────────────────────────────────────
    lines += [
        "[#3d6478]-- composite suspicion analysis --------------------------[/]",
        f"  chi-square test   {'[#ff8c42]ANOMALOUS[/]' if suspicious else '[#00ff9f]normal   [/]'}",
        f"  RS pair analysis  {'[#ff8c42]DIVERGENT[/]' if suspicious else '[#00ff9f]normal   [/]'}",
        f"  LSB autocorr.     {'[#ff8c42]DISRUPTED[/]' if suspicious else '[#00ff9f]normal   [/]'}",
        "",
        f"  suspicion score  [{score_col}][b]{score:>3} / 100[/][/]",
        f"  {score_bar}  [dim]{verdict}[/]",
    ]
    return lines


def _stego_filter_lines(candidate: Candidate) -> list[str]:
    """Filter tier: bright red grid with [PAYLOAD] label + per-channel confirmation."""
    rng = _random.Random(int(candidate.id, 16) ^ 0xF11C0DE5)

    has_payload = any(d.kind == DiscrepancyKind.STEGO_PAYLOAD_PRESENT
                      for d in candidate.truth.discrepancies)
    has_c2      = any(d.kind == DiscrepancyKind.COVERT_C2_CHANNEL
                      for d in candidate.truth.discrepancies)
    has_enc     = any(d.kind == DiscrepancyKind.ENCRYPTED_PAYLOAD
                      for d in candidate.truth.discrepancies)  # v2
    suspicious  = has_payload or has_c2 or has_enc

    lines: list[str] = ["", "[#c084fc]-- [FILTER] per-channel LSB breakdown -------------------[/]"]

    # -- Transformed grid (filter tier) --
    if suspicious:
        lines.extend(_stego_pixel_grid(candidate, "filter"))
        lines.append("")

    # -- Explicit violation + detail --
    if has_enc:
        lines += [
            "  [#ff5470][b]^ ENCRYPTED_PAYLOAD[/][/]",
            "  [#6b7785]detail:[/]  payload extracted but XOR/encrypted -- not plaintext",
            "  [#6b7785]decode:[/]  high-entropy blob (deliberate obfuscation)",
        ]
    elif has_c2:
        payload_hint = rng.choice(_ST_C2_PAYLOADS)
        lines += [
            "  [#ff5470][b]^ COVERT_C2_CHANNEL[/][/]",
            "  [#6b7785]detail:[/]  LSB anomaly across multiple channels",
            f"  [#6b7785]payload:[/] {payload_hint}",
        ]
    elif has_payload:
        lines += [
            "  [#ff8c42][b]^ STEGO_PAYLOAD_PRESENT[/][/]",
            "  [#6b7785]detail:[/]  LSB anomaly localised to single channel",
        ]
    else:
        lines.append("  [#00ff9f]v all channels clean -- no LSB anomaly detected[/]")

    # 2026-09-19: the carrier-shape axis rides on the colour kind above. Kept
    # in step here only so this legacy path never disagrees with the stamp
    # minigame about what the image carries (unreachable from the UI).
    shape_kind = next((d.kind for d in candidate.truth.discrepancies
                       if d.kind in _SHAPE_BY_KIND), None)
    if suspicious and shape_kind is not None:
        geometry, purpose = _STAMP_SHAPE_META[_SHAPE_BY_KIND[shape_kind]][:2]
        lines += [
            f"  [#ff5470][b]^ {shape_kind.value.upper()}[/][/]",
            f"  [#6b7785]glyph:[/]   {geometry} -- {purpose}",
        ]

    return lines


def run_stegotool(candidate: Candidate, state) -> ToolResult:
    """Statistical scan: shows suspicion score -- player judges whether threshold is met.
    findings=() -- base run withholds explicit verdict.
    """
    _charge(state, "stegotool")
    raw_lines  = tuple(_stego_scan_lines(candidate))
    suspicious = any(
        d.kind in (DiscrepancyKind.STEGO_PAYLOAD_PRESENT, DiscrepancyKind.COVERT_C2_CHANNEL)
        for d in candidate.truth.discrepancies
    )
    summary = (
        "Statistical anomaly detected -- review the suspicion score carefully."
        if suspicious else
        "Image is statistically clean -- no payload signal."
    )
    return ToolResult(tool=ToolName.STEGOTOOL, findings=(), raw_lines=raw_lines, summary=summary)


# --- Filtered variants ---

def run_ghostscan_filtered(candidate: Candidate, state) -> ToolResult:
    """Alias for run_ghostscan_filtered_shared -- kept for backward compat."""
    return run_ghostscan_filtered_shared(candidate, state)


def run_logwatch_filtered(candidate: Candidate, state) -> ToolResult:
    """Legacy stub -- use run_logwatch_filtered_shared() via app.py runners dict."""
    _charge(state, "logwatch", filter=True)
    findings = _findings_from(candidate, ToolName.LOGWATCH)
    return ToolResult(tool=ToolName.LOGWATCH, findings=findings,
                      raw_lines=("(legacy -- use shared day log)",),
                      summary="[FILTERED] Run via logwatch page.", filtered=True)


def run_stegotool_filtered(candidate: Candidate, state) -> ToolResult:
    """Per-channel LSB breakdown -- explicitly confirms payload type."""
    _charge(state, "stegotool", filter=True)
    findings  = _findings_from(candidate, ToolName.STEGOTOOL)
    raw_lines = tuple(_stego_scan_lines(candidate) + _stego_filter_lines(candidate))
    summary = (
        f"[FILTERED] {len(findings)} payload finding(s) confirmed -- per-channel breakdown applied."
        if findings else
        "[FILTERED] Clean across all channels -- per-channel breakdown applied."
    )
    return ToolResult(
        tool=ToolName.STEGOTOOL, findings=findings,
        raw_lines=raw_lines, summary=summary, filtered=True,
    )


# ─── Stegotool stamp mechanic ────────────────────────────────────────────────
#
# The stego page's interactive rework. Instead of the scan/filter tiers the
# player moves a square stamp over the pixel grid and pays STEGO_STAMP_COST ⏱
# per stamp to reveal what the pixels underneath actually carry.
#
# Visual language of a revealed region:
#   color   → payload TYPE   amber = plaintext LSB payload
#                            red   = encrypted payload (XOR/obfuscated)
#                            purple= covert C2 channel (multi-channel)
#   density → carrier fill   dense block vs sparse scatter inside the zone
#   size    → zone area      how much of the image the payload occupies
#   shape   → payload PURPOSE (2026-09-19) — the glyph the carrier cells form,
#             independent of colour (any colour can carry any shape):
#                            conventional = clumped blocks / sequential runs
#                                           (no extra violation)
#                            cross    = + or X, strokes intersect
#                                           → SIGNAL_COMMS_PAYLOAD
#                            enclosed = hollow ring / diamond
#                                           → RECURSIVE_PAYLOAD
#                            slash    = 2-4 parallel strokes, never touching
#                                           → HOSTILE_PAYLOAD
#             Shape needs no colour of its own: it emerges from WHICH cells
#             are carrier, so the widget paints carriers exactly as before.
#
# Once cumulative revealed coverage of the zone crosses
# config.STEGO_STAMP_RESOLVE_COVERAGE the signature "resolves" and the
# explicit ▲ violation label prints — the stamp equivalent of the old filter.
# Without the filter the resolve block describes the glyph's GEOMETRY only
# ("strokes cross at a single point"); naming its purpose (▲ HOSTILE_PAYLOAD
# etc.) is filter-tier, exactly like naming the colour.

_STAMP_KIND_META: dict[DiscrepancyKind, tuple[str, str, str]] = {
    # kind → (signature name, hex color, carrier description)
    DiscrepancyKind.STEGO_PAYLOAD_PRESENT: (
        "AMBER", "#ff8c42", "plaintext-type LSB carrier — dense single-channel block"),
    DiscrepancyKind.ENCRYPTED_PAYLOAD: (
        "CRIMSON", "#ff5470", "high-entropy carrier — XOR/encrypted payload"),
    DiscrepancyKind.COVERT_C2_CHANNEL: (
        "VIOLET", "#c084fc", "covert C2 beacon carrier — sparse multi-channel scatter"),
}
# Every description above reads "<payload type> — <texture>". The texture half
# describes the CONVENTIONAL block layout; when a carrier takes a special shape
# (below) its cells trace a glyph instead, so stamp_signature_lines prints only
# the type half rather than contradict the glyph line under it. (2026-09-19:
# the C2 entry was reordered type-first to fit that convention.)


class StegoShape(str, Enum):
    """The glyph a stego carrier's cells form — the payload-PURPOSE axis."""
    CONVENTIONAL = "conventional"   # clumped blocks — no extra violation
    CROSS        = "cross"          # + or X          → SIGNAL_COMMS_PAYLOAD
    ENCLOSED     = "enclosed"       # hollow loop     → RECURSIVE_PAYLOAD
    SLASH        = "slash"          # parallel strokes → HOSTILE_PAYLOAD


# Ground truth → glyph. candidate_gen owns WHETHER a carrier has a special
# shape (it plants the kind); this table only says which glyph renders it, so
# the image can never disagree with ground truth — build_stego_image derives
# the shape from the planted kind and never rolls one of its own.
_SHAPE_BY_KIND: dict[DiscrepancyKind, StegoShape] = {
    DiscrepancyKind.SIGNAL_COMMS_PAYLOAD: StegoShape.CROSS,
    DiscrepancyKind.RECURSIVE_PAYLOAD:    StegoShape.ENCLOSED,
    DiscrepancyKind.HOSTILE_PAYLOAD:      StegoShape.SLASH,
}

# shape → (neutral GEOMETRY description, PURPOSE — filter tier only, ▲ kind).
# The geometry string is what the player is told without the filter: an
# observation of what the revealed cells already show on the grid, never the
# purpose. Conventional has no ▲ kind and must never print a ▲ shape label.
_STAMP_SHAPE_META: dict[StegoShape, tuple[str, str, DiscrepancyKind | None]] = {
    StegoShape.CONVENTIONAL: (
        "irregular blocks / sequential runs — no single figure",
        "conventional carrier, no operation signature", None),
    StegoShape.CROSS: (
        "strokes cross at a single point",
        "signal communications — relays traffic through the image",
        DiscrepancyKind.SIGNAL_COMMS_PAYLOAD),
    StegoShape.ENCLOSED: (
        "closed loop, hollow interior",
        "recursive payload — unpacks and re-embeds itself",
        DiscrepancyKind.RECURSIVE_PAYLOAD),
    StegoShape.SLASH: (
        "parallel strokes, no intersections",
        "hostile payload — built to corrupt or lock what it lands on",
        DiscrepancyKind.HOSTILE_PAYLOAD),
}


def _touches(a, b) -> bool:
    """True if any cell of `a` equals, or is 8-adjacent to, a cell of `b`."""
    for (x, y) in a:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if (x + dx, y + dy) in b:
                    return True
    return False


# ── Special-shape glyph generators (2026-09-19) ─────────────────────────────
# Each takes the carrier rng and the zone's (W, H) and returns the glyph's
# STROKES in zone-local coordinates. They share the constraints the block
# generator's comments below record from real bugs:
#   • the glyph spans the zone (top row to bottom row), so a systematic sweep
#     meets carrier cells well before coverage resolves;
#   • strokes are legible: vertical-ish strokes are 2 columns wide wherever the
#     zone allows, because a terminal cell is ~twice as tall as it is wide —
#     one row of horizontal stroke already reads as thick;
#   • the glyph only ever occupies ZONE cells, and coverage is computed from
#     zone cells, so the stamp economy is identical to a conventional carrier.


def _glyph_cross(rng, W: int, H: int) -> tuple[frozenset, ...]:
    """A '+' (vertical bar across a horizontal bar) or an 'X' of diagonals.
    Either way the two strokes genuinely share cells — they cross."""
    if rng.random() < 0.5:
        tv = 2 if W >= 8 else 1
        th = 2 if H >= 12 else 1
        jx, jy = max(0, W // 6), max(0, H // 6)
        # Crossing point jitters inside the middle third, never onto an edge,
        # so the bars always extend on both sides of it.
        cx = W // 2 - tv // 2 + rng.randint(-jx, jx)
        cy = H // 2 - th // 2 + rng.randint(-jy, jy)
        cx = max(1, min(W - tv - 1, cx))
        cy = max(1, min(H - th - 1, cy))
        vert = frozenset((x, y) for x in range(cx, cx + tv) for y in range(H))
        horiz = frozenset((x, y) for x in range(W) for y in range(cy, cy + th))
        return (vert, horiz)
    # 'X' — corner-to-corner diagonals drawn as 4-connected staircases: each
    # row's span reaches the next row's first column, so the stroke never
    # breaks into diagonal-only dots.
    main: set = set()
    for y in range(H):
        lo = (y * W) // H
        hi = max(lo + 1, ((y + 1) * W) // H)
        main.update((x, y) for x in range(lo, min(W, hi + 1)))
    anti = frozenset((W - 1 - x, y) for (x, y) in main)
    return (frozenset(main), anti)


def _glyph_enclosed(rng, W: int, H: int) -> tuple[frozenset, ...]:
    """A closed, HOLLOW outline — an ellipse ring or a diamond.

    Built row by row from a half-width profile. Each row's wall runs from its
    own boundary inward to at least its neighbours' boundaries, which makes the
    outline 4-connected and puts every interior cell's four neighbours either
    on the outline or inside it — so the interior is sealed by construction (a
    4-way flood fill from outside the glyph cannot reach it) and genuinely
    empty: no carrier cell is ever placed inside.
    """
    diamond = rng.random() >= 0.5
    t = 2 if W >= 10 else 1
    cx = rx = (W - 1) / 2.0
    cy = (H - 1) / 2.0
    ry = cy + 0.5

    def half_width(y: int) -> float:
        u = min(1.0, abs(y - cy) / ry)
        return rx * (1.0 - u) if diamond else rx * _math.sqrt(max(0.0, 1.0 - u * u))

    for _attempt in range(2):
        xl = [int(round(cx - half_width(y))) for y in range(H)]
        xr = [int(round(cx + half_width(y))) for y in range(H)]
        cells: set = set()
        interior = 0
        for y in range(H):
            if y in (0, H - 1):
                cells.update((x, y) for x in range(xl[y], xr[y] + 1))
                continue
            e = max(xl[y] + t - 1, xl[y - 1], xl[y + 1])
            s = min(xr[y] - t + 1, xr[y - 1], xr[y + 1])
            cells.update((x, y) for x in range(xl[y], min(e, xr[y]) + 1))
            cells.update((x, y) for x in range(max(s, xl[y]), xr[y] + 1))
            interior += max(0, s - e - 1)
        if interior:
            return (frozenset(cells),)
        t = 1   # too tight for a 2-wide wall — thin it and retry
    # Last resort, tiny zones only: a hollow rectangle encloses something
    # whenever W, H >= 3, which every stego zone is (see the zone sizing).
    rect = {(x, y) for x in range(W) for y in (0, H - 1)}
    rect |= {(x, y) for y in range(H) for x in (0, W - 1)}
    return (frozenset(rect),)


def _glyph_slash(rng, W: int, H: int) -> tuple[frozenset, ...]:
    """2-4 PARALLEL strokes — horizontal, vertical or diagonal — that never
    touch: every stroke is a translate of the first, and no two are even
    diagonally adjacent (≥1 clear cell between them everywhere)."""
    want = rng.randint(2, 4)
    orient = rng.choice(("horizontal", "vertical", "diagonal"))

    def spread(n: int, span: int, size: int, gap: int) -> list[int] | None:
        last = span - size
        if n < 2 or last < (n - 1) * (size + gap):
            return None
        return [round(i * last / (n - 1)) for i in range(n)]

    def straight(kind: str) -> tuple[frozenset, ...] | None:
        if kind == "horizontal":
            for n in range(want, 1, -1):
                pos = spread(n, H, 1, 1)
                if pos:
                    return tuple(frozenset((x, y) for x in range(W)) for y in pos)
            return None
        tv = 2 if W >= 8 else 1
        for n in range(want, 1, -1):
            pos = spread(n, W, tv, 2)
            if pos:
                return tuple(frozenset((x, y) for x in range(p, p + tv)
                                       for y in range(H)) for p in pos)
        return None

    if orient == "diagonal":
        lean = rng.choice((1, -1))                 # '\' or '/'
        # Shallowest lean first (reads most clearly as a slash), steepening
        # until at least two strokes fit side by side in the zone.
        for travel in (2 * (H - 1), (3 * (H - 1)) // 2, H - 1):
            if travel < 1:
                continue
            base: set = set()
            for y in range(H):
                lo = (y * travel) // H
                hi = max(lo + 1, ((y + 1) * travel) // H)
                for x in range(lo, hi + 1):
                    base.add((x if lean > 0 else travel + 1 - x, y))
            base_w = max(x for x, _ in base) + 1
            off = 2
            while _touches(base, {(x + off, y) for x, y in base}):
                off += 1
            for n in range(want, 1, -1):
                total = base_w + (n - 1) * off
                if total <= W:
                    x0 = (W - total) // 2
                    return tuple(
                        frozenset((x + x0 + i * off, y) for x, y in base)
                        for i in range(n))
        orient = rng.choice(("horizontal", "vertical"))
    other = "vertical" if orient == "horizontal" else "horizontal"
    strokes = straight(orient) or straight(other)
    if strokes is None:     # unreachable for real zones (H >= 3); belt and braces
        strokes = (frozenset((x, 0) for x in range(W)),
                   frozenset((x, H - 1) for x in range(W)))
    return strokes


_GLYPH_BUILDERS = {
    StegoShape.CROSS:    _glyph_cross,
    StegoShape.ENCLOSED: _glyph_enclosed,
    StegoShape.SLASH:    _glyph_slash,
}


@dataclass(frozen=True)
class StegoImageData:
    """Deterministic, structured render model for one candidate's image."""
    cols: int
    rows: int
    style: int                                   # 0..4 legacy roll, kept for RNG parity (see motif)
    base_rgb: tuple                              # rows × cols of (r, g, b)
    zone: tuple[int, int, int, int] | None       # (x, y, w, h) — None if clean
    carrier: frozenset                           # {(x, y)} cells that carry data
    kind: DiscrepancyKind | None                 # payload type, None if clean
    density: float                               # carrier fill fraction of zone
    filename: str
    width: int
    height: int
    file_kb: int
    img_type: str
    # #54: the GENERAL area the Spectral Lens upgrade advertises — the zone
    # dilated by STEGO_HINT_BUFFER cells and clamped to the grid. Deliberately
    # coarser than `zone`: the upgrade narrows the player's search, it does not
    # answer it. None when the image is clean, so a clean image never lights up
    # and the tint can never be a false positive. Declared last because it has a
    # default and every field above it does not.
    hint_region: tuple[int, int, int, int] | None = None
    # 2026-09-19: the payload-PURPOSE axis. `shape` is None for a clean image
    # (no carrier to have a shape); otherwise CONVENTIONAL unless ground truth
    # carries one of the shape kinds, in which case `shape_kind` names it.
    # `strokes` is the glyph's decomposition in grid coordinates (empty for
    # conventional blocks) — it unions to exactly `carrier`, and exists so the
    # geometry guards can check "strokes cross / never touch" directly.
    shape: StegoShape | None = None
    shape_kind: DiscrepancyKind | None = None
    strokes: tuple = ()
    # 2026-09-24: which harbour scene the base image draws (core/stego_scenes.py).
    motif: str = ""


@dataclass(frozen=True)
class StampResult:
    """Outcome of one stamp placement."""
    total_cells: int
    anomalous_cells: int          # carrier cells inside the stamp
    zone_cells_hit: int           # zone cells (carrier or not) inside the stamp
    signature: str | None         # "AMBER" / "CRIMSON" / "VIOLET" — None if clean miss
    signature_color: str | None
    coverage: float               # cumulative zone coverage AFTER this stamp (0..1)
    resolved: bool                # True the moment coverage crosses the threshold


def build_stego_image(candidate: Candidate, day: int = 1) -> StegoImageData:
    """Build the structured pixel-grid model for the stamp minigame.

    Deterministic per candidate (same RNG seeds as the legacy grid renderer,
    so free-tier visuals stay consistent). Grid size scales with payload
    severity AND with `day` — bigger, later-day images are harder to sweep
    (per the Notion design note: 'higher resolution → more pixels'). All the
    size knobs live in config.STEGO_GRID_* so this can be rebalanced without
    touching code.

    Carrier SHAPE (2026-09-19) is derived, never rolled here: a planted
    SIGNAL_COMMS / RECURSIVE / HOSTILE_PAYLOAD kind selects a cross / enclosed
    / slash glyph inside the SAME zone, and anything else keeps the
    conventional clumped-block layout — generated by the unchanged block code
    below, so a conventional carrier is cell-for-cell what it always was. The
    zone, grid size, hint region and base image are identical whatever the
    shape, so the stamp economy (coverage is counted over zone cells) cannot
    move with it.
    """
    rng = _random.Random(int(candidate.id, 16) ^ 0xB10CA0DE)

    has_payload = any(d.kind == DiscrepancyKind.STEGO_PAYLOAD_PRESENT
                      for d in candidate.truth.discrepancies)
    has_c2      = any(d.kind == DiscrepancyKind.COVERT_C2_CHANNEL
                      for d in candidate.truth.discrepancies)
    has_enc     = any(d.kind == DiscrepancyKind.ENCRYPTED_PAYLOAD
                      for d in candidate.truth.discrepancies)
    suspicious  = has_payload or has_c2 or has_enc

    def _sized(kind_key: str) -> tuple[int, int]:
        """Base grid for this payload type, grown by day and capped."""
        base_c, base_r = config.STEGO_GRID_BASE[kind_key]
        extra = max(0, config.curve_day(day) - 1)
        cols = base_c + extra * config.STEGO_GRID_GROWTH_COLS_PER_DAY
        rows = base_r + extra * config.STEGO_GRID_GROWTH_ROWS_PER_DAY
        max_c, max_r = config.STEGO_GRID_MAX
        return (min(cols, max_c), min(rows, max_r))

    # Payload type → grid size, carrier density band
    if has_c2:
        kind, (cols, rows) = DiscrepancyKind.COVERT_C2_CHANNEL, _sized("c2")
        density = rng.uniform(0.25, 0.45)     # sparse scatter, wide zone
    elif has_enc:
        kind, (cols, rows) = DiscrepancyKind.ENCRYPTED_PAYLOAD, _sized("encrypted")
        density = rng.uniform(0.55, 0.72)     # structured mid-density
    elif has_payload:
        kind, (cols, rows) = DiscrepancyKind.STEGO_PAYLOAD_PRESENT, _sized("plaintext")
        density = rng.uniform(0.80, 0.95)     # dense solid block
    else:
        kind, (cols, rows) = None, _sized("clean")
        density = 0.0

    style = rng.randint(0, 4)

    noise_grid = [[rng.randint(-12, 12) for _ in range(cols)] for _ in range(rows)]

    # Hot zone — same placement approach as the legacy renderer
    if suspicious:
        hz_x = rng.randint(0, max(0, cols // 2 - 1))
        hz_y = rng.randint(0, max(0, rows // 2 - 1))
        # C2 zones sprawl; plaintext payloads sit in a tighter block
        w_lo = cols // 3 if has_c2 else max(4, cols // 5)
        hz_w = rng.randint(w_lo, cols // 2)
        hz_h = rng.randint(max(3, rows // 4), rows // 2)
        zone = (hz_x, hz_y, hz_w, hz_h)
        carrier_rng = _random.Random(int(candidate.id, 16) ^ 0x57A3B007)
        shape_kind = next((d.kind for d in candidate.truth.discrepancies
                           if d.kind in _SHAPE_BY_KIND), None)
        shape = (_SHAPE_BY_KIND[shape_kind] if shape_kind is not None
                 else StegoShape.CONVENTIONAL)
        # #54: carrier cells are CLUMPED into segmented rectangles rather than
        # scattered by an independent per-cell coin flip. The old uniform fill
        # produced static: revealing a cell told the player nothing about where
        # the next one was. Blocks that abut and overlap irregularly read as a
        # deliberately embedded payload, and a partial reveal becomes a lead.
        #
        # Block count and shape come from the payload type, matching the carrier
        # descriptions in _STAMP_KIND_META - a plaintext payload is a dense
        # single-channel block, a C2 beacon a sparse multi-channel scatter.
        #
        # NOTE on `density`: it does NOT affect resolve balance. `evaluate_stamp`
        # computes coverage from ZONE cells, so STEGO_STAMP_RESOLVE_COVERAGE is
        # untouched by how many carrier cells exist. density only feeds the
        # displayed "% fill" and whether a given stamp lands on a carrier cell at
        # all - so it is measured FROM the generated blocks below rather than
        # forced to a target. An earlier version of this forced an exact match by
        # padding with random spare cells, which silently destroyed the very
        # clumping it was meant to preserve.
        zone_area = hz_w * hz_h
        strokes: tuple = ()
        if shape is not StegoShape.CONVENTIONAL:
            # A special glyph replaces the blocks outright, inside the same
            # zone. Strokes come back zone-local; translate them onto the grid.
            local = _GLYPH_BUILDERS[shape](carrier_rng, hz_w, hz_h)
            strokes = tuple(frozenset((hz_x + x, hz_y + y) for x, y in st)
                            for st in local)
        if strokes:
            # The glyph IS the carrier — the block layout below is skipped, and
            # it is the CONVENTIONAL layout from here on, byte-for-byte the
            # pre-shape generator (same rng, same draws, same cells).
            cells = set().union(*strokes)
        else:
            # More segments for the sparse types - "segmented rectangles grouped
            # together in strange ways" needs enough pieces to read as segmented.
            if has_c2:
                n_blocks, fill = carrier_rng.randint(5, 8), 0.30
            elif has_enc:
                n_blocks, fill = carrier_rng.randint(3, 5), 0.45
            else:
                n_blocks, fill = carrier_rng.randint(2, 3), 0.55

            # Cap each block well short of the zone in BOTH axes. Without this, a
            # large per-block area with a short height clamps bw to the full zone
            # width and the payload renders as flat bands spanning the image - which
            # reads as a scanline artifact, not an embedded object.
            max_bw = max(2, int(hz_w * 0.55))
            max_bh = max(1, int(hz_h * 0.55))
            per_block = max(2, int(zone_area * fill / max(1, n_blocks)))

            cells: set[tuple[int, int]] = set()
            # Start at the zone CENTRE, not a random corner. A systematic sweep
            # crosses the middle of the zone, so anchoring here means the player
            # reliably lands on a carrier cell and sees the signature colour before
            # coverage resolves. Starting from a random edge could put every block in
            # one corner and let a sweep resolve the zone having touched nothing -
            # observed for STEGO_PAYLOAD_PRESENT with the first version of this.
            wx = hz_x + hz_w // 2
            wy = hz_y + hz_h // 2
            for _ in range(n_blocks):
                bh = max(1, min(max_bh, carrier_rng.randint(1, max_bh)))
                bw = max(2, min(max_bw, per_block // bh + carrier_rng.randint(0, 2)))
                bx = max(hz_x, min(hz_x + hz_w - bw, wx - bw // 2))
                by = max(hz_y, min(hz_y + hz_h - bh, wy - bh // 2))
                for yy in range(by, min(by + bh, hz_y + hz_h)):
                    for xx in range(bx, min(bx + bw, hz_x + hz_w)):
                        cells.add((xx, yy))
                # Walk to a random edge of the block just placed, so the next block
                # abuts or overlaps it from an unpredictable side. Always advancing
                # to the same corner marched the whole group into one edge.
                wx = bx + carrier_rng.choice([-1, 0, bw // 2, bw, bw + 1])
                wy = by + carrier_rng.choice([-1, 0, bh // 2, bh, bh + 1])
                wx = max(hz_x, min(hz_x + hz_w - 1, wx))
                wy = max(hz_y, min(hz_y + hz_h - 1, wy))

        carrier = frozenset(sorted(cells))
        # Report the density we actually produced, not the one we hoped for.
        density = len(carrier) / max(1, zone_area)

        # #54: the advertised region — zone dilated by a buffer, clamped.
        buf = config.STEGO_HINT_BUFFER
        hx = max(0, hz_x - buf)
        hy = max(0, hz_y - buf)
        hint_region = (hx, hy,
                       min(cols - hx, hz_w + 2 * buf),
                       min(rows - hy, hz_h + 2 * buf))
    else:
        zone, carrier, hint_region = None, frozenset(), None
        shape, shape_kind, strokes = None, None, ()

    # 2026-09-24 (dockside voice pass, VOICE_GUIDE.md §7): the base image is a
    # harbour scene now, not a gradient/thermal/photo/blueprint/terminal wash.
    # It is drawn from its OWN seeded RNG after every draw above, so `style`
    # and `noise_grid` are still consumed exactly as before and the zone,
    # carrier and hint region are byte-identical to the pre-scene generator.
    # `style` is kept on the dataclass for that reason; the scene is `motif`.
    motif, base_rgb = stego_scenes.render(candidate.id, cols, rows, noise_grid)

    meta_rng  = _random.Random(int(candidate.id, 16) ^ 0x57E60001)
    img_file  = candidate.dossier.submitted_image_path or "image.png"
    img_type  = "PNG" if img_file.endswith(".png") else "JPEG"
    width     = meta_rng.choice([640, 800, 1024, 1280])
    height    = meta_rng.choice([480, 600, 768, 960])
    file_kb   = meta_rng.randint(180, 820)

    return StegoImageData(
        cols=cols, rows=rows, style=style, base_rgb=base_rgb,
        zone=zone, carrier=carrier, kind=kind, density=density,
        hint_region=hint_region,
        filename=img_file, width=width, height=height,
        file_kb=file_kb, img_type=img_type,
        shape=shape, shape_kind=shape_kind, strokes=strokes,
        motif=motif,
    )


def charge_stamp(state) -> int:
    """Deduct one stamp's cost. Raises InsufficientCompute if unaffordable."""
    cost = config.STEGO_STAMP_COST
    if state.compute_hours < cost:
        raise InsufficientCompute(
            f"Need {cost} ⏱ per stamp, have {state.compute_hours} ⏱"
        )
    state.compute_hours -= cost
    return cost


def evaluate_stamp(img: StegoImageData, x: int, y: int, w: int, h: int,
                   revealed: set) -> StampResult:
    """Evaluate a stamp at rect (x, y, w, h). Mutates `revealed` (the caller's
    cumulative set of revealed cells) and reports what this stamp uncovered.
    """
    cells = [
        (cx, cy)
        for cy in range(y, min(y + h, img.rows))
        for cx in range(x, min(x + w, img.cols))
    ]
    revealed.update(cells)

    if img.zone is None:
        return StampResult(
            total_cells=len(cells), anomalous_cells=0, zone_cells_hit=0,
            signature=None, signature_color=None, coverage=0.0, resolved=False,
        )

    zx, zy, zw, zh = img.zone
    zone_cells = zw * zh
    hit_zone   = sum(1 for (cx, cy) in cells
                     if zx <= cx < zx + zw and zy <= cy < zy + zh)
    hit_anom   = sum(1 for c in cells if c in img.carrier)

    covered = sum(1 for (cx, cy) in revealed
                  if zx <= cx < zx + zw and zy <= cy < zy + zh)
    coverage = covered / max(1, zone_cells)

    sig_name = sig_col = None
    if hit_anom and img.kind is not None:
        sig_name, sig_col, _ = _STAMP_KIND_META[img.kind]

    return StampResult(
        total_cells=len(cells), anomalous_cells=hit_anom, zone_cells_hit=hit_zone,
        signature=sig_name, signature_color=sig_col,
        coverage=coverage,
        resolved=coverage >= config.STEGO_STAMP_RESOLVE_COVERAGE,
    )


def stamp_log_lines(img: StegoImageData, res: StampResult,
                    stamp_no: int, x: int, y: int,
                    reveal_type: bool = False) -> list[str]:
    """Terminal log block for one stamp placement.

    `reveal_type` gates the payload CLASSIFICATION. Without the filter the
    player sees that a carrier is present and its density, but must read the
    stamp's COLOUR on the image to judge the payload type themselves. With the
    filter active, the named signature (AMBER/CRIMSON/VIOLET) is printed.

    Carrier SHAPE is deliberately absent from the per-stamp block, filter or
    not: one 8×4 window cannot show a glyph, so any per-stamp shape claim
    would be the tool reading ground truth rather than reporting what this
    stamp uncovered. The glyph is read on the grid as reveals accumulate and
    is described (or, with the filter, named) once, in stamp_signature_lines.
    """
    head = (f"[#7dd3c0][b]STAMP {stamp_no:02d}[/][/] "
            f"[dim]@ ({x:>2},{y:>2})  −{config.STEGO_STAMP_COST} ⏱[/]")
    if res.anomalous_cells == 0:
        if res.zone_cells_hit:
            body = (f"  [#ff8c42]{res.zone_cells_hit}[/] cells of disturbed noise "
                    f"— no carrier bits here, but you're close")
        else:
            body = (f"  [#00ff9f]region clean[/] — "
                    f"0 / {res.total_cells} cells carry LSB data")
        return [head, body]

    dens = round(100 * res.anomalous_cells / max(1, res.total_cells))
    _, col, _desc = _STAMP_KIND_META[img.kind]
    lines = [head]
    if reveal_type:
        lines += [
            (f"  [{col}][b]▲ carrier detected[/][/]  "
            f"{res.anomalous_cells} / {res.total_cells} cells  [dim]({dens}% density)[/]"),
            f"  signature: [{col}][b]{res.signature}[/][/]",
        ]
    else:
        # No filter — report the carrier, but not its type. The revealed
        # cells are painted in the payload colour on the image; the player
        # classifies by eye (or spends ⏱ on the filter, F).
        lines += [
            (f"  [#c8d4e1][b]▲ carrier detected[/][/]  "
            f"{res.anomalous_cells} / {res.total_cells} cells  [dim]({dens}% density)[/]"),
            ("  signature: [dim]unclassified — read the stamp colour, "
            "or run filter (F) to name it[/]"),
        ]
    lines.append(
        f"  zone coverage: [b]{round(res.coverage * 100)}%[/]"
        + ("" if res.resolved else "  [dim]— keep stamping to resolve[/]")
    )
    return lines


def stego_shape_hint_lines(is_special: bool) -> list[str]:
    """Glyph Detector's one-line note on the stamp that FIRST lands on any
    carrier cell — boolean only, never which shape, never the kind.

    Deliberately its own function rather than a stamp_log_lines() branch:
    that function's shape silence is a considered design constraint (an 8x4
    stamp window cannot show a glyph, so a per-stamp shape CLAIM would be the
    tool reading ground truth rather than reporting what the stamp
    uncovered). This upgrade doesn't ask stamp_log_lines to do that — it
    answers a narrower question ("is there a glyph here at all, yes or no"),
    once, the moment the player has actually touched the carrier, and says
    nothing about the carrier's geometry or purpose. That's still short of
    what stamp_signature_lines' unfiltered `glyph:` line gives at full zone
    coverage — this just moves the yes/no half of that reveal earlier.
    """
    if is_special:
        return ["  [#c084fc][b]◆ special glyph detected[/][/]  "
                "[dim]— this carrier isn't a conventional block; keep digging[/]"]
    return ["  [dim]◇ conventional carrier — no special glyph here[/]"]


def stamp_signature_lines(img: StegoImageData, reveal_type: bool = False) -> list[str]:
    """Block printed once when coverage resolves.

    Without the filter (`reveal_type=False`) the zone is confirmed as carrying
    a payload, but it is NOT named — the player must classify by the stamp
    colour. With the filter active, the explicit ▲ violation label prints
    (the stamp-mechanic equivalent of the old filter tier).

    Carrier SHAPE (2026-09-19) follows the same two tiers. Unfiltered, a
    `glyph:` line describes the figure's GEOMETRY neutrally — an observation
    of what the revealed cells already show on the grid ("strokes cross at a
    single point"), never its purpose. Filtered, a special shape also prints
    its own ▲ label (▲ SIGNAL_COMMS_PAYLOAD etc.) beside the colour one. A
    conventional carrier never prints a ▲ shape label at either tier."""
    if img.kind is None or img.zone is None:
        return []
    _sig, col, desc = _STAMP_KIND_META[img.kind]
    _, _, zw, zh = img.zone
    dens = round(img.density * 100)
    size_word = ("sprawling" if zw * zh >= img.cols * img.rows // 4
                 else "moderate" if zw * zh >= img.cols * img.rows // 8
                 else "compact")
    shape = img.shape or StegoShape.CONVENTIONAL
    geometry, purpose, shape_kind = _STAMP_SHAPE_META[shape]
    if shape is not StegoShape.CONVENTIONAL:
        desc = desc.split(" — ", 1)[0]   # type only; the glyph line has the layout
    if not reveal_type:
        return [
            "",
            "[#c8d4e1][b]▲ PAYLOAD ZONE MAPPED — carrier confirmed[/][/]",
            f"  [#6b7785]density:[/]  {dens}% fill",
            f"  [#6b7785]extent:[/]   {zw}×{zh} px zone ({size_word})",
            f"  [#6b7785]glyph:[/]    {geometry}",
            "  [#6b7785]type:[/]     [dim]unclassified — inspect the stamp colour, or run filter (F) to classify[/]",
            "  [#6b7785]purpose:[/]  [dim]unclassified — read the glyph's shape, or run filter (F) to name it[/]",
        ]
    lines = [
        "",
        f"[{col}][b]▲ {img.kind.value.upper()} — SIGNATURE RESOLVED[/][/]",
        f"  [#6b7785]carrier:[/]  {desc}",
        f"  [#6b7785]density:[/]  {dens}% fill",
        f"  [#6b7785]extent:[/]   {zw}×{zh} px zone ({size_word})",
        f"  [#6b7785]glyph:[/]    {geometry}",
    ]
    if shape_kind is not None and img.shape_kind is shape_kind:
        lines += [
            f"[{col}][b]▲ {shape_kind.value.upper()} — GLYPH RESOLVED[/][/]",
            f"  [#6b7785]purpose:[/]  {purpose}",
        ]
    else:
        lines.append(f"  [#6b7785]purpose:[/]  [dim]{purpose}[/]")
    lines.append("  [dim]flag it on the Evidence Board (Tab)[/]")
    return lines


def get_stego_stats(candidate: Candidate,
                    upgrades: set | None = None) -> tuple[str, ...]:
    """Free-tier statistics block for the stego findings terminal.
    Same numbers as the legacy free tier, but WITHOUT the pixel grid —
    the grid now lives in the dedicated image panel."""
    lines = _stego_image_lines(candidate, upgrades)

    out: list[str] = []
    skipping = False
    for ln in lines:
        plain = ln
        if plain.startswith("[#3d6478]┌─"):
            skipping = True
            continue
        if skipping:
            if plain.startswith("[#3d6478]└"):
                skipping = False
            continue
        out.append(ln)
    while out and out[0] == "":
        out.pop(0)

    header = [
        "[#7dd3c0][b]STAMP ANALYSIS[/][/]  [dim]X to enter stamp mode[/]",
        f"[dim]arrows move · Space stamp (−{config.STEGO_STAMP_COST} ⏱) · Esc exit[/]",
        "",
    ]
    return tuple(header + out)


# ════════════════════════════════════════════════════════════════════════════
# HASHCRACK — the cipher block
# ════════════════════════════════════════════════════════════════════════════
#
# A standalone two-stage decryption minigame. Not a variant of the stego stamp:
# there is no canvas to sweep and nothing spatially hidden. The whole block
# decrypts at once, and the skill is reading the credential and tuning the
# decrypt.
#
#   STAGE 0 (free)   The block renders as ciphertext with a header carrying
#                    three plain observations: its dimensions, its glyph
#                    alphabet, and its DIGEST SHAPE ("64 hex characters").
#                    Those identify the algorithm to a player who has read the
#                    reference table — and, separately, tell them whether the
#                    credential is worth opening at all.
#
#   STAGE 1 (paid)   Choose one of three decryption windows. The matching one
#                    engages the decrypt; any other wastes the spend. bcrypt's
#                    window engages and then STALLS — correctly identifying
#                    key-stretching is not the same as it being crackable, and
#                    the only winning move is not to open it.
#
#   STAGE 2 (free*)  An alignment PAD. The decrypt has the right family but
#                    the wrong derived key, and that key is an (x, y)
#                    coordinate: walking toward it with the arrow keys brings
#                    the plaintext into focus, cell by cell. On the exact
#                    square the block locks and the credential resolves.
#
#                    *Free for the first config.CIPHER_DIAL_FREE_STEPS presses.
#                    Past that a small ⏱ fee lands every
#                    CIPHER_DIAL_OVERAGE_BLOCK further steps, so a wandering
#                    search costs something a direct walk never does. See
#                    step_overage_charge().
#
# The plaintext is TILED across the whole block rather than hidden in one run.
# Partial alignment scrambles a different subset of cells in each repeat, so a
# player who is close can read the password by consensus across rows — which is
# what makes the last few steps satisfying rather than fiddly.
#
# Only stage 1 costs ⏱. The spend decision is made once, up front, on
# information the player already had for free.


_CIPHER_HEX_GLYPHS = "0123456789abcdef"
# bcrypt's radix-64 alphabet, plus the $ that makes its blocks unmistakable at
# a glance even before you count anything.
_CIPHER_B64_GLYPHS = ("./$ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                      "abcdefghijklmnopqrstuvwxyz0123456789")

# tier → (label, hex colour, algorithm name, one-line description)
_CIPHER_TIER_META: dict[str, tuple[str, str, str, str]] = {
    "weak":   ("WEAK",   "#ff5470", "MD5",
               "32-hex digest, unsalted round — one pass, short dial"),
    "medium": ("MEDIUM", "#ffd93d", "SHA256",
               "64-hex digest — recoverable, but the key needs finding"),
    "strong": ("STRONG", "#00ff9f", "bcrypt",
               "key-stretched, cost factor 12 — no completion possible"),
}

# Outcomes of selecting a decryption window (stage 1).
CIPHER_WINDOW_WRONG   = "wrong"     # window does not match the digest
CIPHER_WINDOW_STALLED = "stalled"   # matched, but key-stretched — dead end
CIPHER_WINDOW_ENGAGED = "engaged"   # matched and crackable — dial unlocks


@dataclass(frozen=True)
class CipherBlockData:
    """Deterministic render model for one candidate's credential.

    `cipher_glyphs` is what the player sees before any window is applied.
    `plain_glyphs` is the fully-decrypted block — the password tiled across the
    grid. `cell_tolerance` gives each cell its own threshold: at Manhattan
    distance `err` from the true coordinate, a cell shows its plain glyph when
    its tolerance clears `err`, and its cipher glyph otherwise. That is the
    entire sharpening effect, and keeping it in the DATA rather than in the
    renderer is what makes walking the pad back and forth show the same
    picture every time.

    `align_true_x` / `align_true_y` are the coordinate at which every cell
    resolves. For bcrypt there is no pad and no plaintext: both spans are 0 and
    `plaintext` is None, which is the single fact the whole strong tier turns
    on.
    """
    cols:           int
    rows:           int
    tier:           str                  # "weak" | "medium" | "strong"
    algo:           str                  # "MD5" | "SHA256" | "bcrypt"
    cipher_glyphs:  tuple                # rows × cols of single-char strings
    plain_glyphs:   tuple                # rows × cols — the tiled plaintext
    cell_tolerance: tuple                # rows × cols of ints
    align_true_x:   int
    align_true_y:   int
    align_span_x:   int                  # x walks 0 .. align_span_x
    align_span_y:   int                  # y walks 0 .. align_span_y
    align_falloff:  float                # tolerance-distribution exponent
    plaintext:      str | None
    hash_value:     str
    # Defaults last (dataclass field order).
    pre_revealed:   bool = False         # UNSALTED_STORAGE: arrives decrypted

    @property
    def crackable(self) -> bool:
        """Whether stage 2 exists for this block at all."""
        return self.plaintext is not None and self.tier != "strong"

    @property
    def align_true(self) -> tuple[int, int]:
        """The true coordinate, as one (x, y) pair."""
        return (self.align_true_x, self.align_true_y)

    @property
    def max_walk(self) -> int:
        """Manhattan distance across the whole pad, corner to corner."""
        return self.align_span_x + self.align_span_y

    @property
    def start_cursor(self) -> tuple[int, int]:
        """Where the pad cursor begins — the CENTRE, not a corner.

        Centre rather than (0, 0) for two reasons, and the second is the one
        that matters. It halves the worst-case direct walk, from the pad's full
        diagonal to half of it, so the step budget has far more headroom for a
        player who walks straight. And it removes a free bit of information: a
        corner start means the first press is never ambiguous, because three of
        the four directions are walls. From the middle, every direction is
        live, and the player has to read the block to choose one.
        """
        return (self.align_span_x // 2, self.align_span_y // 2)

    @property
    def worst_direct_walk(self) -> int:
        """Steps a player who walks STRAIGHT at the key could face, worst case.

        Measured from `start_cursor`, so it tracks the centre start rather than
        assuming a corner: the farthest square from the middle of the pad is a
        corner, at roughly half the full diagonal. This is the number the free
        step allowance has to clear — see test_a_direct_walk_is_always_free.
        """
        sx, sy = self.start_cursor
        return (max(sx, self.align_span_x - sx)
                + max(sy, self.align_span_y - sy))

    def error_at(self, x: int, y: int) -> int:
        """Manhattan distance from (x, y) to the true coordinate.

        Manhattan rather than Chebyshev on purpose — see the note on
        config.CIPHER_ALIGN_SPAN. Every arrow press must move this by exactly
        one, in one direction or the other, or the pad has dead zones where a
        keypress appears to do nothing.
        """
        return abs(x - self.align_true_x) + abs(y - self.align_true_y)


@dataclass(frozen=True)
class WindowResult:
    """Outcome of applying a decryption window (stage 1)."""
    outcome:  str          # CIPHER_WINDOW_WRONG | _STALLED | _ENGAGED
    chosen:   str          # tier key of the window the player picked
    cost:     int          # ⏱ charged


def cipher_tier(hash_value: str | None) -> str | None:
    """The block tier for a submitted hash.

    Deliberately a thin alias of password_strength() rather than a second
    implementation — the dossier, the block and the rules page must never
    disagree about what tier a hash is, and two functions computing it from the
    same shape is how that drift starts.
    """
    return password_strength(hash_value)


def _cipher_rng(candidate: Candidate) -> _random.Random:
    """Per-candidate RNG for block layout. Distinct salt from the stego grid's
    so the two surfaces cannot accidentally correlate."""
    return _random.Random(int(candidate.id, 16) ^ 0x0C1F4E)


def _digest_shape(hash_value: str) -> str:
    """How the submitted hash LOOKS, as a free observation.

    Never names the algorithm — that is the conclusion the player draws, or
    buys Cipher ID HUD to have drawn for them. It only counts what is there.
    """
    if hash_value.startswith("$2b$"):
        return f"$2b$ prefix, {len(hash_value)} characters"
    return f"{len(hash_value)} hex characters"


def build_cipher_block(candidate: Candidate, day: int = 1) -> CipherBlockData:
    """Build the render model for the two-stage decrypt.

    Deterministic per candidate. Every size and difficulty knob lives in
    config.CIPHER_* so this can be rebalanced without touching code.
    """
    h_val = candidate.dossier.submitted_hash or ""
    tier  = cipher_tier(h_val) or "medium"
    _lbl, _col, algo, _desc = _CIPHER_TIER_META[tier]

    base_c, base_r = config.CIPHER_GRID_BASE[tier]
    extra = max(0, config.curve_day(day) - 1)
    cols = base_c + extra * config.CIPHER_GRID_GROWTH_COLS_PER_DAY
    rows = base_r + extra // config.CIPHER_GRID_GROWTH_ROWS_PERIOD
    max_c, max_r = config.CIPHER_GRID_MAX
    cols, rows = min(cols, max_c), min(rows, max_r)

    rng = _cipher_rng(candidate)
    alphabet = _CIPHER_B64_GLYPHS if tier == "strong" else _CIPHER_HEX_GLYPHS
    cipher = [[rng.choice(alphabet) for _ in range(cols)] for _ in range(rows)]

    # bcrypt stamps its literal cost prefix into the top-left of the block.
    # Structural evidence, not a label: the player is reading actual
    # ciphertext, exactly as they would a real $2b$12$ hash.
    if tier == "strong":
        for i, ch in enumerate(config.CIPHER_BCRYPT_PREFIX[:cols]):
            cipher[0][i] = ch

    plaintext = crack_password(candidate)
    span_x, span_y = config.CIPHER_ALIGN_SPAN[tier]
    falloff        = config.CIPHER_ALIGN_FALLOFF[tier]

    if not plaintext or tier == "strong":
        # Strong tier: crack_password() already returns None for bcrypt, so
        # there is no pad, no coordinate and no amount of ⏱ that changes it.
        return CipherBlockData(
            cols=cols, rows=rows, tier=tier, algo=algo,
            cipher_glyphs=tuple(tuple(r) for r in cipher),
            plain_glyphs=tuple(tuple(r) for r in cipher),
            cell_tolerance=tuple(tuple(0 for _ in range(cols)) for _ in range(rows)),
            align_true_x=0, align_true_y=0,
            align_span_x=0, align_span_y=0, align_falloff=0.0,
            plaintext=None, hash_value=h_val,
        )

    # The decrypted block: the password tiled across every row, separated so
    # repeats are visually distinguishable from one long smear.
    unit = plaintext + config.CIPHER_TILE_SEPARATOR
    flat = (unit * (cols * rows // len(unit) + 2))[:cols * rows]
    plain = [tuple(flat[y * cols:(y + 1) * cols]) for y in range(rows)]

    # The true coordinate. Drawn from the SAME rng stream the glyphs came from,
    # so a candidate's pad is as deterministic as their block.
    align_true_x = rng.randint(0, span_x)
    align_true_y = rng.randint(0, span_y)
    # Per-cell tolerance. A cell with tolerance t resolves whenever the
    # Manhattan error is within t, so the distribution of t across the block IS
    # the reveal curve — see config.CIPHER_ALIGN_FALLOFF for its shape and why
    # it is convex rather than uniform.
    #
    # The range STARTS AT ZERO, and that is load-bearing. A draw that gave
    # every cell a tolerance of at least 1 would make err=1 render identically
    # to err=0: the player would see a fully legible block one step away from
    # true, with no way to tell they were not there yet. The zero-tolerance
    # cells are the handful of characters that refuse to settle until the
    # coordinate is exactly right, which is the whole "fine-tune it exactly"
    # beat — and rounding a u near 0 lands on exactly that.
    max_walk = span_x + span_y
    cell_tol = tuple(
        tuple(round(max_walk * rng.random() ** falloff) for _ in range(cols))
        for _ in range(rows)
    )

    return CipherBlockData(
        cols=cols, rows=rows, tier=tier, algo=algo,
        cipher_glyphs=tuple(tuple(r) for r in cipher),
        plain_glyphs=tuple(plain),
        cell_tolerance=cell_tol,
        align_true_x=align_true_x, align_true_y=align_true_y,
        align_span_x=span_x, align_span_y=span_y,
        align_falloff=falloff,
        plaintext=plaintext, hash_value=h_val,
        pre_revealed=bool(candidate.dossier.credential_unsalted),
    )


# ── Stage 1 — the decryption window ─────────────────────────────────────────


def window_cost(state) -> int:
    """⏱ to apply one decryption window — the tool's ordinary base cost.

    Routed through tool_cost() rather than a constant of its own, so the
    Hashcrack Optimizer upgrade and campaign inflation keep applying to this
    tool exactly as they do to every other one.
    """
    return tool_cost(state, "hashcrack")


def apply_window(block: CipherBlockData, chosen_tier: str, state) -> WindowResult:
    """Charge for, and evaluate, one decryption-window choice.

    Raises InsufficientCompute if unaffordable — and charges NOTHING in that
    case, so a refused purchase can never leave the player worse off.
    """
    cost = window_cost(state)
    if state.compute_hours < cost:
        raise InsufficientCompute(
            f"Need {cost} ⏱ to apply a decryption window, "
            f"have {state.compute_hours} ⏱"
        )
    state.compute_hours -= cost

    if chosen_tier != block.tier:
        outcome = CIPHER_WINDOW_WRONG
    elif block.crackable:
        outcome = CIPHER_WINDOW_ENGAGED
    else:
        # Matched the algorithm, but the algorithm is the problem.
        outcome = CIPHER_WINDOW_STALLED
    return WindowResult(outcome=outcome, chosen=chosen_tier, cost=cost)


def window_log_lines(block: CipherBlockData, res: WindowResult) -> list[str]:
    """Terminal block for one window application."""
    label = next((lbl for key, lbl, _shape in config.CIPHER_WINDOWS
                  if key == res.chosen), res.chosen)
    head = (f"[#c084fc][b]DECRYPTION WINDOW — {label}[/][/]  "
            f"[dim]−{res.cost} ⏱[/]")

    if res.outcome == CIPHER_WINDOW_WRONG:
        return [
            head,
            ("  [#ff5470]no structure emerged[/] — this window does not "
             "fit the digest"),
            (f"  [dim]the block is {_digest_shape(block.hash_value)}; "
             f"check it against the reference table before paying again[/]"),
        ]
    if res.outcome == CIPHER_WINDOW_STALLED:
        return [
            head,
            "  [#00ff9f]window fits — and the decrypt stalls immediately[/]",
            ("  [dim]key-stretched at cost factor 12: every guess costs the "
             "same as the first. There is no alignment to find and no plaintext "
             "to recover. Reading the digest would have told you this for "
             "free.[/]"),
        ]
    return [
        head,
        "  [#c084fc][b]▲ decrypt engaged[/][/] — the block has structure",
        ("  [dim]wrong derived key: walk the alignment pad until the text "
         "comes into focus[/]"),
    ]


# ── Stage 2 — the alignment pad ─────────────────────────────────────────────


def render_block(block: CipherBlockData, x: int, y: int,
                 engaged: bool = True) -> list[list[tuple[str, bool]]]:
    """The block as it looks from a given pad coordinate.

    Returns rows of (glyph, resolved) pairs so the widget can colour resolved
    cells without recomputing which ones they are. Before a window is applied
    (`engaged=False`) every cell is ciphertext, wherever the cursor sits.

    A pre-revealed block (UNSALTED_STORAGE) is fully resolved unconditionally:
    no salt means the stored value is exposed with no tool run at all, which is
    the violation itself.
    """
    if block.pre_revealed:
        return [[(g, True) for g in row] for row in block.plain_glyphs]
    if not engaged or not block.crackable:
        return [[(g, False) for g in row] for row in block.cipher_glyphs]

    err = block.error_at(x, y)
    out: list[list[tuple[str, bool]]] = []
    for gy in range(block.rows):
        row: list[tuple[str, bool]] = []
        for gx in range(block.cols):
            if err <= block.cell_tolerance[gy][gx]:
                row.append((block.plain_glyphs[gy][gx], True))
            else:
                row.append((block.cipher_glyphs[gy][gx], False))
        out.append(row)
    return out


def alignment_locked(block: CipherBlockData, x: int, y: int) -> bool:
    """True when the cursor is exactly on the key and the credential resolves."""
    if block.pre_revealed:
        return True
    return block.crackable and (x, y) == block.align_true


def resolved_fraction(block: CipherBlockData, x: int, y: int) -> float:
    """Fraction of cells currently showing plaintext.

    Used by the widget for the lock indicator and by tests to assert the
    sharpening curve. Deliberately NOT surfaced to the player as a number —
    the design is that they read the block, not a percentage.
    """
    if block.pre_revealed:
        return 1.0
    if not block.crackable:
        return 0.0
    err = block.error_at(x, y)
    hit = sum(1 for row in block.cell_tolerance for t in row if err <= t)
    return hit / max(1, block.cols * block.rows)


def hint_band(block: CipherBlockData, upgrades: set | None = None
              ) -> tuple[int, int, int, int] | None:
    """The pad BOX Credential HUD marks, or None without the upgrade.

    Returns an INCLUSIVE (x0, y0, x1, y1) box containing the true coordinate,
    widened on each axis by config.CIPHER_HINT_FRACTION of THAT axis's span.
    Per #54's lesson it narrows the search without answering it, and the base
    tier marks nothing.

    Per-axis rather than one shared half-width: the pads are much wider than
    they are tall, so a single figure large enough to be a hint on X swallows
    the whole of Y and hands that axis over for free.
    """
    if config.UPGRADE_HASH_HIGHLIGHT not in (upgrades or ()):
        return None
    if not block.crackable:
        return None
    bx = max(1, round(block.align_span_x * config.CIPHER_HINT_FRACTION))
    by = max(1, round(block.align_span_y * config.CIPHER_HINT_FRACTION))
    return (max(0, block.align_true_x - bx),
            max(0, block.align_true_y - by),
            min(block.align_span_x, block.align_true_x + bx),
            min(block.align_span_y, block.align_true_y + by))


def step_overage_charge(steps_before: int, steps_after: int) -> int:
    """⏱ owed for crossing step thresholds between two step counts.

    The budget is a staircase, not a meter: the first
    config.CIPHER_DIAL_FREE_STEPS presses are free, and every
    CIPHER_DIAL_OVERAGE_BLOCK presses after that bills
    CIPHER_DIAL_OVERAGE_COST. This returns only what the move just taken owes,
    so callers charge incrementally and never have to remember what they have
    already paid.

    Expressed as (blocks crossed after) − (blocks crossed before) rather than
    by testing a single step against a threshold, so a multi-step move is
    billed for every boundary it passes rather than at most one.
    """
    def _blocks(steps: int) -> int:
        over = steps - config.CIPHER_DIAL_FREE_STEPS
        if over <= 0:
            return 0
        return -(-over // config.CIPHER_DIAL_OVERAGE_BLOCK)   # ceil

    return (_blocks(steps_after) - _blocks(steps_before)) * config.CIPHER_DIAL_OVERAGE_COST


def steps_until_charge(steps: int) -> int:
    """How many more presses until the next ⏱ lands. Always at least 1.

    Drives the footer counter, so it must agree with step_overage_charge()
    exactly — a readout that is off by one is worse than no readout at all.

    Derived by ASKING that function rather than re-deriving the boundaries from
    the constants. The arithmetic version of this was wrong in both branches on
    the first attempt (the free allowance runs to FREE_STEPS + 1 presses, not
    FREE_STEPS, and the later boundaries are offset by that same one), and any
    second implementation of the staircase is a second place for it to drift.
    The loop runs at most OVERAGE_BLOCK times.
    """
    k = 1
    while step_overage_charge(steps, steps + k) == 0:
        k += 1
    return k


# ── Readouts ────────────────────────────────────────────────────────────────


def cipher_header_lines(block: CipherBlockData,
                        upgrades: set | None = None) -> list[str]:
    """The block's header — structural facts always, the ALGORITHM on upgrade.

    The split here is the whole design of WEAK_ENCRYPTION's evidence, so it is
    worth being precise about.

    Printed ALWAYS, free: the block's dimensions, its glyph alphabet, and the
    DIGEST SHAPE. All three are observations about the artifact in front of the
    player, readable off the hash the dossier already shows. The digest line is
    what makes WEAK_ENCRYPTION flaggable by a player who owns no upgrades: they
    see "32 hex characters", match it against the rules page's table, and
    conclude MD5 themselves.

    Printed ONLY with Cipher ID HUD: the algorithm's NAME and what it implies.
    That is the conclusion, and the upgrade buys drawing it for you.

    An earlier draft left the algorithm entirely behind the upgrade, which
    would have made a violation ABOUT the algorithm unflaggable without it —
    turning a 20 HD$ convenience into a paywall on a whole kind.
    """
    upgrades = upgrades or ()
    lines = [
        "[#3d6478]── cipher block ─────────────────────────────────────────────[/]",
        (f"[dim]{block.cols} × {block.rows} cells  ·  "
         f"{'radix-64' if block.tier == 'strong' else 'hex'} glyphs[/]"),
        f"[dim]digest: {_digest_shape(block.hash_value)}[/]",
    ]
    if config.UPGRADE_CRYPTO_ID in upgrades:
        lbl, col, algo, desc = _CIPHER_TIER_META[block.tier]
        lines.append(f"  [{col}][b]{lbl} — {algo}[/][/]  [dim]{desc}[/]")
    else:
        lines.append("  [dim]algorithm unidentified — match the digest shape "
                     "against the reference table[/]")
    return lines


def get_cipher_intro(block: CipherBlockData,
                     upgrades: set | None = None) -> tuple[str, ...]:
    """Free-tier content for the Hashcrack findings terminal, before any spend."""
    lines = cipher_header_lines(block, upgrades)
    lines += [
        "",
        f"[dim]hash on file:[/] [#6b7785]{block.hash_value[:28]}…[/]",
        "",
        "[#c084fc][b]DECRYPTION[/][/]  [dim]X to open the window selector[/]",
        "[dim]stage 1 — choose the window matching the digest (costs ⏱)[/]",
        ("[dim]stage 2 — walk the alignment pad with the arrow keys until the "
         "text resolves[/]"),
        (f"[dim]         first {config.CIPHER_DIAL_FREE_STEPS} steps free, "
         f"then {config.CIPHER_DIAL_OVERAGE_COST} ⏱ per "
         f"{config.CIPHER_DIAL_OVERAGE_BLOCK}[/]"),
    ]
    if block.pre_revealed:
        lines += [
            "",
            ("[#ff5470][b]⚠ UNSALTED STORAGE[/][/]  "
             "[dim]— stored without a salt; the block is already in the clear, "
             "no decryption required[/]"),
            f"  [b #e8f0f8]{block.plaintext}[/]",
        ]
    return tuple(lines)


def cipher_resolve_lines(block: CipherBlockData, candidate: Candidate,
                         day_number: int = 1,
                         upgrades: set | None = None) -> list[str]:
    """Block printed once the alignment locks and the credential resolves.

    This is what makes Hashcrack self-sufficient for LEAKED_PASSWORD and
    CROSS_BREACH_REUSE: the corpus is named HERE, by the tool that owns those
    kinds, so neither depends on a Logwatch page that does not exist until a
    day later. (Logwatch no longer carries corpus rows at all since
    2026-09-19; the Ghostscan breach panel is the only corroborating view.)

    Which violations get NAMED here, and which the player calls themselves, is
    the line this whole rework turns on:

      OBSERVED, always shown — the corpus list itself. "This plaintext is in
      LinkedIn (2016)" is a lookup the player can always see, dim and
      unlabeled at base tier.

      JUDGED, so gated behind an upgrade — the ▲ LEAKED_PASSWORD /
      ▲ CROSS_BREACH_REUSE label, and WEAK_CREDENTIAL. Whether one corpus
      reads as LEAKED_PASSWORD or two-plus as CROSS_BREACH_REUSE (Breach
      Classifier), and whether `monkey123` is a bad password (Crack Verdict
      Analyzer), are exactly the calls this rework hands back to the player —
      the rules page already teaches the corpus-count rule, so the raw list is
      enough to work from without the label.

    The corpus line is gated on the candidate actually carrying a credential
    corpus kind, NOT merely on breach_dbs_for_candidate() returning something.
    That function also answers for BREACH_HIT, which is Ghostscan-owned and
    means the EMAIL was exposed — printing it inside a block headed "credential
    recovered" would tell the player their password was found in a dump when it
    was not.
    """
    upgrades = upgrades or ()
    if not block.plaintext:
        return []
    _lbl, col, algo, desc = _CIPHER_TIER_META[block.tier]
    lines = [
        "",
        "[#c084fc][b]▲ CREDENTIAL RECOVERED[/][/]",
        f"  [#6b7785]plaintext:[/]  [b #e8f0f8]{block.plaintext}[/]",
        f"  [#6b7785]algorithm:[/]  [{col}]{algo}[/]  [dim]{desc}[/]",
    ]

    kinds = {d.kind for d in candidate.truth.discrepancies}
    has_leaked = DiscrepancyKind.LEAKED_PASSWORD in kinds
    has_reuse  = DiscrepancyKind.CROSS_BREACH_REUSE in kinds
    has_weak   = DiscrepancyKind.WEAK_CREDENTIAL in kinds
    has_wenc   = DiscrepancyKind.WEAK_ENCRYPTION in kinds
    has_unsalt = DiscrepancyKind.UNSALTED_STORAGE in kinds

    has_breach_label = config.UPGRADE_HC_BREACH_LABEL in upgrades

    if has_leaked or has_reuse:
        corpora = breach_dbs_for_candidate(candidate, day_number)
        if corpora:
            # Base tier: the collection list still shows — it is a lookup the
            # tool has already done, not a judgement — but dim and unlabeled,
            # so it reads as raw evidence rather than a call-out. Breach
            # Classifier promotes it to the same orange accent the ▲ label
            # lines use, so "highlighted" and "named" land together.
            corpus_col = "#ff8c42" if has_breach_label else "#6b7785"
            lines.append("  [#6b7785]corpus:[/]     "
                         + " · ".join(f"[{corpus_col}]{c}[/]" for c in corpora))

    if has_breach_label:
        if has_leaked:
            lines.append("  [#ff8c42][b]▲ LEAKED_PASSWORD[/][/]  "
                         "— plaintext confirmed in breach corpus")
        if has_reuse:
            lines.append("  [#ff5470][b]▲ CROSS_BREACH_REUSE[/][/]  "
                         "— this exact plaintext appears in more than one corpus")
    # 2026-09-25 (Nick): no "classify it yourself" prompt without Breach
    # Classifier. Reading the corpus row against the reference is simply what
    # a finished crack asks of the player; spelling it out was noise.
    if has_unsalt:
        lines.append("  [#ff8c42][b]▲ UNSALTED_STORAGE[/][/]  "
                     "— stored without a salt; no decryption was required")
    if has_wenc and config.UPGRADE_CRYPTO_ID in upgrades:
        # Free evidence for this kind is the digest shape in the header; the
        # HUD is what turns that observation into a named violation.
        lines.append("  [#ffd93d][b]▲ WEAK_ENCRYPTION[/][/]  "
                     "— stored with the weakest available algorithm")

    if config.UPGRADE_HC_VERDICT in upgrades:
        lines.append(f"  [#6b7785]verdict:[/]    {_cipher_verdict(block.plaintext)}")
        if has_weak:
            lines.append("  [#ffd93d][b]▲ WEAK_CREDENTIAL[/][/]  "
                         "— recovered plaintext fails the complexity threshold")
    lines.append("  [dim]flag it on the Evidence Board (Tab)[/]")
    return lines


def _cipher_verdict(plaintext: str) -> str:
    """Crack Verdict Analyzer's one-line strength call on a recovered password.

    Reads the STRING, not the ground truth. A verdict derived from the
    candidate's discrepancy list would be the guard-hardening mistake in
    miniature: it would agree with the answer key by construction and so could
    never disagree with what the player is actually looking at.
    """
    from .candidate_gen import _HC_LEAKED_PASSWORDS, _HC_WEAK_PASSWORDS
    if plaintext in _HC_WEAK_PASSWORDS:
        return "[#ff5470]weak — dictionary word or keyboard walk[/]"
    if plaintext in _HC_LEAKED_PASSWORDS:
        return "[#ff8c42]dated pattern — word plus year, corpus-typical[/]"
    has_sym = any(not c.isalnum() for c in plaintext)
    if len(plaintext) >= 12 and has_sym:
        return "[#00ff9f]strong — long, mixed, symbol-laden[/]"
    return "[#ffd93d]moderate — no obvious dictionary root[/]"


def cipher_full_readout(block: CipherBlockData, candidate: Candidate,
                        day_number: int = 1,
                        upgrades: set | None = None) -> list[str]:
    """Everything the cipher block can tell the player, fully solved.

    The end state of the minigame without playing it. Used by the lab CLI
    (`hackdox lab --tool hashcrack`) and by tests that need this tool's REAL
    final output to check against ground truth.

    Deliberately routed through the same cipher_header_lines() and
    cipher_resolve_lines() the live page calls, rather than composing its own
    prose. A debug view that formats findings its own way is a view that can
    agree with the answer key while the actual page disagrees.
    """
    lines = cipher_header_lines(block, upgrades)
    if not block.plaintext:
        lines.append("  [#00ff9f]key-stretched — no alignment exists and no "
                     "plaintext can be recovered from this block[/]")
        return lines
    lines += cipher_resolve_lines(block, candidate, day_number, upgrades)
    return lines
