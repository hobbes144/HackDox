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

import random as _random
from dataclasses import dataclass

from .. import config
from .candidate_gen import _ELITE_ORG_HANDLE as _ORG_HANDLE
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
    if any(kw in affil for kw in _GS_TRUSTED_AFFIL_KW):
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

_GS_TRUSTED_AFFIL_KW = ["mit", "stanford", "cmu", "oxford", "cloudflare",
                          "google", "microsoft", "mozilla", "apache"]
_GS_SUSPECT_AFFIL_KW = ["breachforums", "raidforums", "hackforums",
                          "nulled", "exploit.in"]

# Fixed platform lists — never change day to day
_GS_LEGIT_PLATFORMS  = ["GitHub", "LinkedIn", "Twitter/X", "The Doxen",
                          "Reddit", "Keybase", "Google", "Spotify"]
_GS_CRITICAL_FORUMS  = ["BreachForums", "RaidForums", "HackForums", "XSS.is"]
_GS_ADVISORY_FORUMS  = ["nulled.to", "CrackingKing", "Dread", "CrackingPro"]

# ── Unified breach database table ─────────────────────────────────────────────
# Single source of truth used by BOTH the GhostScan breach list panel AND the
# Hashcrack shared log BREACH_MATCH entries.  canonical_name is what appears in
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


def get_ghostscan_identity(candidate: Candidate) -> tuple[str, ...]:
    """Free passive identity check — always visible in the ghostscan terminal."""
    return tuple(_ghostscan_identity_lines(candidate))


def _ghostscan_identity_lines(candidate: Candidate, hint: bool = True) -> list[str]:
    d = candidate.dossier
    email_domain = candidate.email.split("@")[-1].lower() if "@" in candidate.email else ""

    if email_domain in _GS_SUSPICIOUS_DOMAINS:
        email_flag = "[#ff5470]✗  disposable provider — flag immediately[/]"
    elif email_domain in _GS_PRIVACY_DOMAINS:
        # #58: was "privacy provider — flag if other issues present", which told
        # the player to flag something with no matching DiscrepancyKind. The
        # nearest thing to flag is DISPOSABLE_EMAIL, a different domain class, and
        # board_accuracy_bonus counts that as a false positive — so the UI was
        # instructing an action the scoring model punishes. Context, not an
        # instruction: it is real corroboration, it is not itself a violation.
        email_flag = ("[#ffd93d]?  anonymous mail provider — legitimate, but "
                      "offers no identity trail[/]")
    elif email_domain in _GS_TRUSTED_DOMAINS or email_domain.endswith((".edu", ".ac.uk")):
        email_flag = "[#00ff9f]✓  recognised provider[/]"
    else:
        email_flag = "[#6b7785]-  unknown domain — verify affiliation[/]"

    affil_lower = candidate.claimed_affiliation.lower()
    if any(kw in affil_lower for kw in _GS_SUSPECT_AFFIL_KW):
        affil_flag = "[#ff5470]✗  known threat actor community[/]"
    elif any(kw in affil_lower for kw in _GS_TRUSTED_AFFIL_KW):
        # #56: this is a GUARANTEE now, not a hint. A trusted organisation cannot
        # be faked on a dossier - the generator refuses to plant an affiliation
        # violation on a candidate claiming one - so the sweep will always
        # confirm it. Worded as the guarantee it is, because that is the
        # player's reward: a trusted domain plus a trusted org means the
        # ghostscan step can be skipped entirely.
        affil_flag = ("[#00ff9f]✓  trusted organisation — cannot be faked, "
                      "sweep will confirm[/]")
    elif affil_lower in ("independent", "freelance", "self-employed", ""):
        affil_flag = "[#ffd93d]?  unverifiable — needs corroboration[/]"
    else:
        affil_flag = "[#6b7785]-  not in known list — verify via sweep[/]"

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
            if show_forums:
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
            if show_forums:
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
                lines.append(f"  [#ff8c42]▲ email in breach corpus[/]")


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
    # are static, so it makes sense to have this automated" (Nick). Threat
    # forums stay gated behind the real filter run; only the breach section
    # is affected.
    _breach_auto = config.UPGRADE_BREACH_AUTO in getattr(state, "upgrades", ())
    has_breach = any(d.kind == DiscrepancyKind.BREACH_HIT
                     for d in candidate.truth.discrepancies)
    # Issue #28: the report REPLACES the terminal content (no stacked
    # reports), so the free identity block is folded in at the top.
    raw_lines  = list(
        _ghostscan_identity_lines(candidate, hint=False)
        + [""]
        # #61: day drives which breach corpora exist today.
        + _ghostscan_sweep_lines(candidate, rng, show_forums=False,
                                 day_number=getattr(state, 'current_day', 1),
                                 show_breach=_breach_auto)
    )
    if _breach_auto and has_breach:
        raw_lines += [
            "",
            "[#c084fc]── [AUTO] Breach Feed Sync ─────────────────────────────[/]",
            "  [#ff5470][b]▲ BREACH_HIT[/][/]  — email confirmed in breach corpus",
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
        _ghostscan_identity_lines(candidate, hint=False)
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


# ─── Hashcrack — shared credential audit log ────────────────────────────────
#
# Shared day log of credential events: AUTH_FAIL/OK (stuffing patterns),
# HASH_SUBMIT (hash type + truncated value), BREACH_MATCH (corpus entries).
# Generated once per day. Player scrolls to find their candidate's email,
# then runs crack (H) to highlight + crack inline, filter (F) for labels.

_HC_DATE          = "2024-01-15"
_HC_NOISE_USERS   = ["j.morris", "r.chen", "s.patel", "admin", "k.okonkwo",
                      "t.nakamura", "l.vasquez", "d.kowalski", "m.ibrahim",
                      "a.petrov", "b.silva", "c.johannsen", "n.reyes", "p.walsh"]
_HC_NOISE_DOMAINS = ["corp.net", "internal.io", "hackdox.local", "company.org"]
_HC_NOISE_IPS     = ["10.0.1.15", "10.0.1.42", "10.0.2.7", "10.0.3.88",
                      "192.168.0.55", "192.168.1.200", "172.16.0.14"]
_HC_BREACH_NAMES  = [db[0] for db in _BREACH_DATABASES]  # keep in sync with _BREACH_DATABASES
_HC_ALGO_LABEL_MAP = {32: "MD5", 40: "SHA1", 64: "SHA256"}

_HC_WEAK_PASSWORDS   = ["password", "123456", "password123", "letmein", "qwerty",
                         "admin", "welcome1", "monkey", "dragon", "sunshine",
                         "iloveyou", "princess", "1234567890", "abc123"]
_HC_LEAKED_PASSWORDS = ["letmein2019", "summer2021!", "dragon2020", "welcome@corp",
                         "monkey123!", "sunshine2018", "iloveyou01", "admin2022"]


@dataclass
class _HCLogEntry:
    ts_secs:        int
    ts_str:         str
    event:          str          # AUTH_FAIL | AUTH_OK | HASH_SUBMIT | BREACH_MATCH
    ip:             str          # source IP (or "--" for BREACH_MATCH)
    account:        str          # email / username
    detail:         str          # hash snippet for HASH_SUBMIT, breach name for BREACH_MATCH
    owner_id:       str | None
    is_suspicious:  bool
    violation_kind: str | None   # "stuffing" | "brute" | "weak" | "leaked"
                                 # | "reuse" | "unsalted" | None


def _hc_ts_str(secs: int) -> str:
    h, r = divmod(secs % 86400, 3600)
    m, s = divmod(r, 60)
    return f"{_HC_DATE} {h:02d}:{m:02d}:{s:02d}"


def _hc_algo(h: str | None) -> str:
    if not h:
        return "?"
    if h.startswith("$2b$"):
        return "bcrypt"
    return _HC_ALGO_LABEL_MAP.get(len(h), "?")


def _hc_candidate_entries(candidate, rng: _random.Random, day_number: int) -> list[_HCLogEntry]:
    from .. import config as _cfg

    _kinds = {d.kind for d in candidate.truth.discrepancies}
    has_leaked = DiscrepancyKind.LEAKED_PASSWORD in _kinds
    has_weak = DiscrepancyKind.WEAK_CREDENTIAL in _kinds
    has_reuse = DiscrepancyKind.CROSS_BREACH_REUSE in _kinds
    has_unsalt = DiscrepancyKind.UNSALTED_STORAGE in _kinds

    has_hashbad = has_leaked or has_weak or has_reuse or has_unsalt
    # #62: the burst below used to fire on `has_cred`, so EVERY weak- or
    # leaked-credential candidate got an AUTH_FAIL storm annotated "credential
    # stuffing pattern" — measured at 91 of 91, none of which carried
    # CREDENTIAL_STUFFING. Because that kind is LOGWATCH-tier
    # (candidate_gen._SEVERITY_REVEAL), it can never appear on the Hashcrack
    # evidence board either, so the player had no way to reconcile the claim
    # against anything. This is the inverted form of the recurring bug class:
    # not ground truth with no artifact, but an artifact with no ground truth.
    # The burst is now derived from the violation instead of asserted alongside
    # a different one.
    has_stuffing = any(d.kind == DiscrepancyKind.CREDENTIAL_STUFFING
                       for d in candidate.truth.discrepancies)

    # The login burst is gated on the LOG kinds, never on the credential kinds.
    # A weak or leaked password says nothing about how the account was logged
    # into — planting a burst for it invented evidence the ground truth did not
    # contain, and labelled a single-account attack as "credential stuffing".
    #
    #   BRUTE_FORCE_IN_LOG   one account, many tries   -> "brute"
    #   CREDENTIAL_STUFFING  one IP, many accounts,
    #                        1-2 tries each            -> "stuffing"
    has_brute    = DiscrepancyKind.BRUTE_FORCE_IN_LOG  in _kinds
    has_stuffing = DiscrepancyKind.CREDENTIAL_STUFFING in _kinds

    account    = candidate.email
    claimed_ip = candidate.dossier.claimed_ip or "10.0.0.1"
    ext_ip     = f"185.{rng.randint(100,220)}.{rng.randint(1,254)}.{rng.randint(1,254)}"
    t          = rng.randint(*_cfg.HC_WORKDAY_WINDOW)

    entries: list[_HCLogEntry] = []

    if has_stuffing:
        # Credential-stuffing burst from external IP. Gated on the violation
        # itself (#62) — a bad password is not an attack pattern, and rendering
        # one as the other taught the player a tell that meant nothing.
        #
        # Batch-3/merge note: this used to build a victims[] sweep across up to
        # 6 OTHER accounts (rng.sample(_HC_NOISE_USERS, min(6, ...))) with 1-2
        # tries each — leftover pre-batch-3 code that a merge resolution
        # brought back over this branch's own simplification. That hard 6-cap
        # silently ignored HC_STUFFING_BURST_SIZE above 6 (config extracted the
        # literal but the surrounding shape never actually read it past that
        # cap), which is what test_hashcrack_stuffing_burst_size_is_configurable
        # caught. Restored to the batch-3 version: burst straight-line AUTH_FAILs
        # against the candidate's own account, same shape as the brute-force
        # branch below and as Logwatch's LW_BRUTE_BURST_SIZE — burst actually
        # drives the count now, at any size.
        burst = rng.randint(*_cfg.HC_STUFFING_BURST_SIZE)
        for i in range(burst):
            entries.append(_HCLogEntry(
                ts_secs=t+i, ts_str=_hc_ts_str(t+i),
                event="AUTH_FAIL", ip=ext_ip, account=account, detail="",
                owner_id=candidate.id, is_suspicious=True, violation_kind="stuffing",
            ))
        t += burst + rng.randint(*_cfg.HC_STUFFING_COOLDOWN)
        entries.append(_HCLogEntry(
            ts_secs=t, ts_str=_hc_ts_str(t),
            event="AUTH_OK", ip=ext_ip, account=account, detail="",
            owner_id=candidate.id, is_suspicious=True, violation_kind="stuffing",
        ))
        t += rng.randint(*_cfg.HC_STUFFING_POST_GAP)
    elif has_brute:
        # Brute force: many tries against the SINGLE target account.
        burst = rng.randint(5, 9)

        for i in range(burst):
            entries.append(_HCLogEntry(
                ts_secs=t+i, ts_str=_hc_ts_str(t+i),
                event="AUTH_FAIL", ip=ext_ip, account=account, detail="",
                owner_id=candidate.id, is_suspicious=True, violation_kind="brute",
            ))
        t += burst + rng.randint(*_cfg.HC_STUFFING_COOLDOWN)
        entries.append(_HCLogEntry(
            ts_secs=t, ts_str=_hc_ts_str(t),
            event="AUTH_OK", ip=ext_ip, account=account, detail="",
            owner_id=candidate.id, is_suspicious=True, violation_kind="brute",
        ))
        t += rng.randint(*_cfg.HC_STUFFING_POST_GAP)
    else:
        # Normal login
        entries.append(_HCLogEntry(
            ts_secs=t, ts_str=_hc_ts_str(t),
            event="AUTH_OK", ip=claimed_ip, account=account, detail="",
            owner_id=candidate.id, is_suspicious=False, violation_kind=None,
        ))
        t += rng.randint(*_cfg.HC_NORMAL_LOGIN_GAP)

    # Hash submission
    h_val = candidate.dossier.submitted_hash or ""
    if h_val:
        algo    = _hc_algo(h_val)
        snippet = h_val[:16] + ".."
        vk      = ("weak" if has_weak else "leaked" if has_leaked
                   else "reuse" if has_reuse else "unsalted" if has_unsalt else None)
        entries.append(_HCLogEntry(
            ts_secs=t, ts_str=_hc_ts_str(t),
            event="HASH_SUBMIT", ip=ext_ip if (has_stuffing or has_brute) else claimed_ip,

            account=account, detail=f"{algo}:{snippet}",
            owner_id=candidate.id, is_suspicious=has_hashbad,
            violation_kind=vk,
        ))
        t += rng.randint(*_cfg.HC_HASH_SUBMIT_GAP)

    # Breach match rows. #61: both the first and the second corpus now come
    # from breach_dbs_for_candidate(), which is the SAME function the Ghostscan
    # breach panel seeds from — so the databases Hashcrack names are exactly
    # the databases the player can find the email in. The second corpus used to
    # be picked by `(int(id,16) >> 8) % len(_HC_BREACH_NAMES)` with a decrement
    # to dodge collisions, which knew nothing about the Ghostscan side and
    # could name a corpus that isn't unlocked yet.
    if has_leaked or has_reuse:
        corpora = breach_dbs_for_candidate(candidate, day_number)
        for i, corpus in enumerate(corpora):
            if i:
                t += rng.randint(*_cfg.HC_BREACH_ROW_GAP)
            entries.append(_HCLogEntry(
                ts_secs=t, ts_str=_hc_ts_str(t),
                event="BREACH_MATCH", ip="--", account=account, detail=corpus,
                owner_id=candidate.id, is_suspicious=True,
                violation_kind=("leaked" if has_leaked and not i else "reuse"),
            ))
            t += rng.randint(5, 20)

    return entries


def _hc_noise_entries(rng: _random.Random, count: int) -> list[_HCLogEntry]:
    from .. import config as _cfg

    entries: list[_HCLogEntry] = []
    for _ in range(count):
        user   = rng.choice(_HC_NOISE_USERS)
        domain = rng.choice(_HC_NOISE_DOMAINS)
        ip     = rng.choice(_HC_NOISE_IPS)
        t      = rng.randint(*_cfg.HC_NOISE_TIME_WINDOW)
        acct   = f"{user}@{domain}"
        evt    = rng.choice(_cfg.HC_NOISE_EVENT_WEIGHTS)
        detail = ""
        if evt == "HASH_SUBMIT":
            algo    = rng.choice(["MD5", "SHA256", "SHA256", "SHA1"])
            snippet = "".join(rng.choice("0123456789abcdef") for _ in range(16)) + ".."
            detail  = f"{algo}:{snippet}"
        elif evt == "BREACH_MATCH":
            detail = rng.choice(_HC_BREACH_NAMES)
            ip     = "--"
        entries.append(_HCLogEntry(
            ts_secs=t, ts_str=_hc_ts_str(t),
            event=evt, ip=ip, account=acct, detail=detail,
            owner_id=None, is_suspicious=False, violation_kind=None,
        ))
    return entries


def generate_hashcrack_day_log(game_seed: int, day) -> list[_HCLogEntry]:
    """Shared credential audit log for the full day. Volume scales with day
    number per config (batch-3 task #4d/#7 — was a flat max(80, 160-n))."""
    from .. import config as _cfg
    from .candidate_gen import generate as _gen_candidate

    rng     = _random.Random(_stable_hash(game_seed, day.number, "hc_day") & 0xFFFFFFFF)
    entries: list[_HCLogEntry] = []

    for slot in range(day.candidate_count):
        cand  = _gen_candidate(game_seed, day, slot)
        crng  = _random.Random(_stable_hash(game_seed, day.number, slot, "hc_entries") & 0xFFFFFFFF)
        entries.extend(_hc_candidate_entries(cand, crng, day.number))

    base_noise = _cfg.HC_ENTRIES_BY_DAY.get(day.number, _cfg.HC_ENTRIES_DEFAULT)
    last_key   = max(_cfg.HC_ENTRIES_BY_DAY.keys()) if _cfg.HC_ENTRIES_BY_DAY else 1
    if day.number > last_key:
        extra_days = day.number - last_key
        base_noise = int(_cfg.HC_ENTRIES_BY_DAY.get(last_key, _cfg.HC_ENTRIES_DEFAULT)
                         * (_cfg.HC_ENTRIES_SCALE_FACTOR ** extra_days))
    n_noise = max(_cfg.HC_ENTRIES_MIN, base_noise - len(entries))
    entries.extend(_hc_noise_entries(rng, n_noise))
    entries.sort(key=lambda e: e.ts_secs)
    return entries


def _render_hc_log(
    entries:       list[_HCLogEntry],
    target_id:     str | None,
    candidate,
    annotate:      bool = False,
    explicit_tags: bool = False,
    upgrade_highlight: bool = False,   # hash_highlight upgrade ("Credential
                                       # HUD"): colours the candidate's own
                                       # suspicious lines + the "why" annotations
    upgrade_verdict:   bool = False,   # hashcrack_verdict_highlight upgrade
                                       # ("Crack Verdict Analyzer"): labels a
                                       # crack's STRENGTH VERDICT ("no concern" /
                                       # "always safe") — the plaintext itself
                                       # reveals on any run either way (#6a)
) -> tuple[str, ...]:
    """Render the credential audit log to Rich markup lines.

    Batch-3 tasks #4d/#6a: `annotate` alone used to be enough to turn on both
    line-highlighting AND the inline "▲ why" annotations, which meant owning
    hash_highlight never actually gated anything once the tool was run (any
    base run already had annotate=True). Highlighting/annotation now key off
    `highlight_active` (explicit_tags — the paid filter — OR upgrade_highlight)
    instead. Cracking a password (revealing the plaintext) is NOT part of that
    gate: it only needs `annotate` (the tool was actually run) — Nick's
    instruction was that the crack must always work, only the "why is this
    suspicious"/"this is a safe verdict" commentary is paywalled.
    """
    lines: list[str] = [
        "[#3d6478]── credential audit log ──────────────────────────────────────[/]",
        f"[dim]{_HC_DATE}  (all accounts — locate your target email below)[/]",
        "",
    ]

    # Derive crack result for annotation. Issue #29: the plaintext is the
    # generator's ground truth (dossier.password_plain), so the crack always
    # matches the dossier hash. bcrypt (strong tier) never cracks.
    crack_plaintext: str | None = None
    neutral_crack = False   # clean candidate — crack succeeds, no violation
    has_credkind = False
    if annotate and target_id and candidate is not None:
        has_credkind = any(d.kind in (
            DiscrepancyKind.LEAKED_PASSWORD, DiscrepancyKind.WEAK_CREDENTIAL,
            DiscrepancyKind.CROSS_BREACH_REUSE, DiscrepancyKind.UNSALTED_STORAGE,
        ) for d in candidate.truth.discrepancies)
        crack_plaintext = crack_password(candidate)
        neutral_crack = crack_plaintext is not None and not has_credkind

    highlight_active = explicit_tags or upgrade_highlight
    verdict_active    = explicit_tags or upgrade_verdict

    evt_col = {
        "AUTH_OK":      "#00ff9f",
        "AUTH_FAIL":    "#ff5470",
        "HASH_SUBMIT":  "#7dd3c0",
        "BREACH_MATCH": "#ff8c42",
    }

    prev_vk: str | None = None
    emitted_crack = False
    breach_seen   = 0        # how many BREACH_MATCH rows we've annotated

    for e in entries:
        is_mine = (e.owner_id == target_id)
        ec      = evt_col.get(e.event, "#6b7785")
        det_str = f"  {e.detail}" if e.detail else ""
        raw     = f"{e.ts_str}  [{ec}]{e.event:<12}[/]  {e.ip:<18}  {e.account}{det_str}"

        if is_mine and e.is_suspicious and highlight_active:
            col = "#ff5470" if explicit_tags else "#ff8c42"
            lines.append(f"[{col}]{raw}[/]")

            # Inline annotations — only the free-tier highlight styling here;
            # explicit_tags (filter) has its own block below.
            if upgrade_highlight and not explicit_tags:
                if e.violation_kind == "stuffing" and prev_vk != "stuffing":
                    lines.append("  [#ff8c42]▲ this IP is failing against several "
                                 "other accounts too[/]")
                elif e.violation_kind == "brute" and prev_vk != "brute":
                    lines.append("  [#ff8c42]▲ repeated failures against this one "
                                 "account from a single IP[/]")
                elif e.violation_kind in ("weak", "leaked") and e.event == "HASH_SUBMIT" and not emitted_crack:
                    if crack_plaintext:
                        attempts = "1" if e.violation_kind == "weak" else "found in corpus"
                        lines.append(f"  [#ff8c42]▲ crack result  →  [b]{crack_plaintext}[/]  ({attempts})[/]")
                        emitted_crack = True
                elif e.violation_kind == "leaked" and e.event == "BREACH_MATCH":
                    lines.append("  [#ff8c42]▲ email confirmed in breach corpus[/]")
                elif e.violation_kind in ("reuse", "unsalted") and e.event == "HASH_SUBMIT" and not emitted_crack:
                    if crack_plaintext:
                        _note = "reused across breaches" if e.violation_kind == "reuse" else "unsalted -- cracks instantly"
                        lines.append(f"  [#ff8c42]▲ crack result  ->  [b]{crack_plaintext}[/]  ({_note})[/]")
                        emitted_crack = True
                elif e.violation_kind == "reuse" and e.event == "BREACH_MATCH":
                    breach_seen += 1
                    if breach_seen == 1:
                        lines.append("  [#ff8c42]▲ email found in this breach corpus[/]")
                    else:
                        lines.append("  [#ff8c42]▲ the SAME password appears here too — reused across corpora[/]")


            if explicit_tags:
                if e.violation_kind == "stuffing" and prev_vk != "stuffing":
                    lines.append("  [#ff5470][b]▲ CREDENTIAL_STUFFING[/][/]  "
                                 "— one source IP, many accounts, few tries each")
                elif e.violation_kind == "brute" and prev_vk != "brute":
                    lines.append("  [#ff5470][b]▲ BRUTE_FORCE_IN_LOG[/][/]  "
                                 "— one account, sustained failures")
                elif e.violation_kind == "weak" and e.event == "HASH_SUBMIT" and not emitted_crack:
                    if crack_plaintext:
                        lines.append(f"  [#ff5470]▲ crack result  →  [b]{crack_plaintext}[/][/]")
                        emitted_crack = True
                elif e.violation_kind == "leaked" and e.event == "BREACH_MATCH":
                    lines.append(f"  [#ff5470]▲ breach corpus confirmed: {e.detail}[/]")
                elif e.violation_kind in ("reuse", "unsalted") and e.event == "HASH_SUBMIT" and not emitted_crack:
                    if crack_plaintext:
                        lines.append(f"  [#ff5470]▲ crack result  ->  [b]{crack_plaintext}[/][/]")
                        emitted_crack = True
                elif e.violation_kind == "reuse" and e.event == "BREACH_MATCH":
                    breach_seen += 1
                    if breach_seen == 1:
                        lines.append(f"  [#ff5470][b]▲ BREACH_HIT[/][/]  — {e.detail}")
                    else:
                        lines.append(f"  [#ff5470][b]▲ CROSS_BREACH_REUSE[/][/]  "
                                     f"— same plaintext also in {e.detail}")

            prev_vk = e.violation_kind

        elif is_mine:
            lines.append(f"[#ffd93d]{raw}[/]")
            # Issue #29 — the crack still runs on any base run (annotate=True)
            # regardless of upgrades; only the WORDING differs. #4d: without
            # Credential HUD, a violator's own HASH_SUBMIT line lands here
            # (not the highlighted branch above) — reveal the plaintext
            # plainly, with none of the "▲ why" framing that branch adds.
            if (annotate and e.event == "HASH_SUBMIT" and not emitted_crack
                    and candidate is not None):
                _strength = password_strength(candidate.dossier.submitted_hash)
                if _strength == "strong":
                    if verdict_active:
                        lines.append("  [#00ff9f]✓ crack abandoned — bcrypt "
                                     "(~100 H/s) · strong encryption, always safe[/]")
                    else:
                        lines.append("  [dim]✓ crack abandoned — bcrypt "
                                     "(~100 H/s) · no plaintext recovered[/]")
                    emitted_crack = True
                elif neutral_crack and crack_plaintext:
                    if verdict_active:
                        lines.append(f"  [#00ff9f]✓ crack result  →  "
                                     f"[b]{crack_plaintext}[/]  "
                                     f"(strong password — no concern)[/]")
                    else:
                        lines.append(f"  [#c8d4e1]crack result  →  "
                                     f"[b]{crack_plaintext}[/][/]")
                    emitted_crack = True
                elif has_credkind and crack_plaintext:
                    # A real violation, but Credential HUD isn't owned (or
                    # this line simply wasn't the one the highlight branch
                    # picked) — still reveal the plaintext, just without any
                    # "▲ this is why it's suspicious" call-out.
                    lines.append(f"  [#c8d4e1]crack result  →  "
                                 f"[b]{crack_plaintext}[/][/]")
                    emitted_crack = True
            prev_vk = None
        else:
            lines.append(f"[#2e3d4f]{raw}[/]")
            prev_vk = None

    lines.append("")

    if explicit_tags and target_id and candidate is not None:
        has_leaked = any(d.kind == DiscrepancyKind.LEAKED_PASSWORD for d in candidate.truth.discrepancies)
        has_weak   = any(d.kind == DiscrepancyKind.WEAK_CREDENTIAL  for d in candidate.truth.discrepancies)
        has_reuse  = any(d.kind == DiscrepancyKind.CROSS_BREACH_REUSE for d in candidate.truth.discrepancies)
        has_unsalt = any(d.kind == DiscrepancyKind.UNSALTED_STORAGE   for d in candidate.truth.discrepancies)
        lines += [
            "[#c084fc]── [FILTER] credential analysis ─────────────────────────────[/]",
        ]
        _any = False
        if has_leaked:
            lines.append("  [#ff5470][b]▲ LEAKED_PASSWORD[/][/]  -- plaintext confirmed in breach corpus"); _any = True
        if has_weak:
            lines.append("  [#ff5470][b]▲ WEAK_CREDENTIAL[/][/]  -- hash cracked in < 100 attempts"); _any = True
        if has_reuse:
            lines.append("  [#ff5470][b]▲ CROSS_BREACH_REUSE[/][/]  -- reused password recurs across breach corpora"); _any = True
        if has_unsalt:
            lines.append("  [#ff8c42][b]▲ UNSALTED_STORAGE[/][/]  -- unsalted hash cracked instantly"); _any = True
        if not _any:
            lines.append("  [#00ff9f]✓ credential appears secure[/]")

    lines.append(f"[dim]{len(entries)} entries  ·  highlighted = current target account[/]")
    return tuple(lines)


def get_hashcrack_shared(entries: list[_HCLogEntry], candidate,
                         upgrade_highlight: bool = False) -> tuple[str, ...]:
    """Free shared log — always visible on hashcrack page, no cost.
    With the hash_highlight upgrade, suspicious lines are pre-coloured."""
    return _render_hc_log(entries, target_id=candidate.id, candidate=candidate,
                          upgrade_highlight=upgrade_highlight)


def run_hashcrack_shared(entries: list[_HCLogEntry], candidate, state) -> ToolResult:
    """Base run: highlights candidate + shows crack result inline.

    Batch-3 task #4d: this used to call _render_hc_log with only
    annotate=True and no upgrade flags — meaning hash_highlight ("Credential
    HUD") never actually gated anything once the tool was run, since
    annotate alone used to turn highlighting on. Now threads both upgrades
    from state, same as the filtered run below.
    """
    _charge(state, "hashcrack")
    _ups = getattr(state, "upgrades", ())
    raw_lines = _render_hc_log(
        entries, target_id=candidate.id, candidate=candidate, annotate=True,
        upgrade_highlight=config.UPGRADE_HASH_HIGHLIGHT in _ups,
        upgrade_verdict=config.UPGRADE_HC_VERDICT in _ups)
    strength = password_strength(candidate.dossier.submitted_hash)
    cracked = any(d.kind in (
        DiscrepancyKind.LEAKED_PASSWORD, DiscrepancyKind.WEAK_CREDENTIAL,
        DiscrepancyKind.CROSS_BREACH_REUSE, DiscrepancyKind.UNSALTED_STORAGE,
    ) for d in candidate.truth.discrepancies)
    if cracked:
        summary = "Hash cracked — review inline result. Run filter (F) to name the violation."
    elif strength == "strong":
        summary = "bcrypt credential — attempt abandoned. Strong encryption is always safe."
    elif crack_password(candidate):
        summary = "Hash cracked — plaintext revealed inline. Assess its strength yourself."
    else:
        summary = "No match found in common wordlist."
    return ToolResult(tool=ToolName.HASHCRACK, findings=(), raw_lines=raw_lines, summary=summary)


def run_hashcrack_filtered_shared(entries: list[_HCLogEntry], candidate, state) -> ToolResult:
    """Filter: explicit violation labels."""
    _charge(state, "hashcrack", filter=True)
    findings  = _findings_from(candidate, ToolName.HASHCRACK)
    _ups = getattr(state, "upgrades", ())
    raw_lines = _render_hc_log(
        entries, target_id=candidate.id, candidate=candidate, annotate=True,
        explicit_tags=True,
        upgrade_highlight=config.UPGRADE_HASH_HIGHLIGHT in _ups,
        upgrade_verdict=config.UPGRADE_HC_VERDICT in _ups)
    summary = (
        f"[FILTERED] {len(findings)} credential finding(s) confirmed."
        if findings else
        "[FILTERED] Credential clean — no breach match, complexity threshold passed."
    )
    return ToolResult(
        tool=ToolName.HASHCRACK, findings=findings,
        raw_lines=raw_lines, summary=summary, filtered=True,
    )



# ─── Logwatch — shared day log ───────────────────────────────────────────────
#
# One combined auth log for the full day, generated once from the game seed.
# Candidate entries are interleaved with noise, sorted chronologically.
#
# Violations planted in the log:
#   BRUTE_FORCE_IN_LOG — rapid AUTH_FAIL cluster on the same account (brute force)
#                        OR AUTH_FAIL on multiple accounts from same IP (stuffing)
#   IMPOSSIBLE_TRAVEL  — AUTH_OK from two geographically impossible IPs
#   INSIDER_BEHAVIOR   — FILE_READ on sensitive path + SUDO_EXEC after 22:00
#
# All AUTH_OK entries carry a city tag (None for internal IPs).
# Claimed IP mismatch is surfaced in the free tier as a subtle colour signal.
#
# Render modes:
#   get_logwatch_shared(entries, candidate)                     — free, full log
#   run_logwatch_shared(entries, candidate, state)              — ▲ inline markers
#   run_logwatch_filtered_shared(entries, candidate, state)     — explicit labels

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


def _lw_candidate_entries(candidate, rng: _random.Random) -> list[_LogEntry]:
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
        ext_ip, ext_city = _lw_ext_ip(rng, "185.220.")
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
        ext_ip, ext_city = _lw_ext_ip(rng, "45.131.")
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
        city_a_entry, city_b_entry = rng.sample(_LW_CITIES, 2)
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
        all_entries.extend(_lw_candidate_entries(cand, crng))

    # Noise count from config — scaled per day
    base_noise = _cfg.LW_ENTRIES_BY_DAY.get(day.number, _cfg.LW_ENTRIES_DEFAULT)
    last_key   = max(_cfg.LW_ENTRIES_BY_DAY.keys()) if _cfg.LW_ENTRIES_BY_DAY else 1
    if day.number > last_key:
        extra_days = day.number - last_key
        base_noise = int(_cfg.LW_ENTRIES_BY_DAY.get(last_key, _cfg.LW_ENTRIES_DEFAULT)
                         * (_cfg.LW_ENTRIES_SCALE_FACTOR ** extra_days))
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
    upgrade_highlight: bool = False,   # log_highlight upgrade (issue #23):
                                       # free tier colours suspicious lines,
                                       # WITHOUT the ▲ annotations of a base run
) -> tuple[str, ...]:
    """Render the shared day log to Rich markup lines.

    Free tier  : full log, candidate rows in yellow, claimed-IP mismatches in orange.
    Annotate   : adds ▲ inline markers for violations.
    Explicit   : adds ▲ VIOLATION_TYPE labels.
    """
    claimed_ip = (candidate.dossier.claimed_ip or "") if candidate else ""

    lines: list[str] = [
        "[#3d6478]── shared server log ──────────────────────────────────────────[/]",
        f"[dim]{_LW_DATE}  (all users — locate your target account below)[/]",
    ]
    if claimed_ip:
        lines.append(f"[#6b7785]claimed IP[/]  [#ffd93d]{claimed_ip}[/]  "
                     f"[dim](compare against AUTH_OK source IPs for candidate)[/]")
    lines.append("")

    evt_col = {
        "AUTH_OK":      "#00ff9f",
        "AUTH_FAIL":    "#ff5470",
        "FILE_READ":    "#7dd3c0",
        "SUDO_EXEC":    "#ff8c42",
        "SESSION_END":  "#6b7785",
    }
    # Batch-3 task #4e: `annotate` alone used to be enough to trigger
    # highlighting — meaning log_highlight ("Log Analyzer HUD") never
    # actually gated anything once the tool was run. The claimed-IP mismatch
    # special-case below is intentionally NOT part of this gate — it's
    # documented elsewhere (rules_content._CATCH) as always-free evidence,
    # a different, pre-existing design decision this task doesn't touch.
    highlight_active = explicit_tags or upgrade_highlight
    prev_vk: str | None = None

    def _format_entry(e: _LogEntry, mine: bool, sus: bool, col: str) -> str:
        ec      = evt_col.get(e.event, "#6b7785")
        city_s  = f"  [dim][{e.city}][/]" if e.city else ""
        extra_s = f"  {e.extra}" if e.extra else ""
        row     = (f"{e.ts_str}  [{ec}]{e.event:<12}[/]  "
                   f"{e.ip:<18}  {e.account}{extra_s}{city_s}")

        # In free tier: highlight claimed-IP mismatches for the candidate
        if mine and not annotate and not explicit_tags:
            if e.event == "AUTH_OK" and claimed_ip and e.ip != claimed_ip:
                return f"[#ff8c42]{row}[/]"   # subtle orange — IP doesn't match claim
            return f"[{col}]{row}[/]"
        return f"[{col}]{row}[/]"

    def _render_flat(entries_list: list[_LogEntry]) -> None:
        nonlocal prev_vk
        for e in entries_list:
            is_mine = (e.owner_id == target_id)
            if is_mine and e.is_suspicious and highlight_active:
                col = "#ff5470" if explicit_tags else "#ff8c42"
                lines.append(_format_entry(e, True, True, col))
                if upgrade_highlight and not explicit_tags:
                    if e.violation_kind == "brute_force" and e.event == "AUTH_FAIL" and prev_vk != "brute_force":
                        lines.append("  [#ff8c42]▲ rapid auth failures on this account[/]")
                    elif e.violation_kind == "stuffing" and e.event == "AUTH_OK" and prev_vk != "stuffing":
                        lines.append("  [#ff8c42]▲ credential stuffing — same source IP targeting multiple accounts[/]")
                    elif e.violation_kind == "impossible_travel" and prev_vk != "impossible_travel":
                        lines.append(f"  [#ff8c42]▲ login from geographically distant IP  [{e.city}][/]")
                    elif e.violation_kind == "insider" and prev_vk != "insider":
                        lines.append("  [#ff8c42]▲ after-hours privileged access[/]")
                    elif e.violation_kind == "after_hours" and prev_vk != "after_hours":
                        lines.append("  [#ff8c42]▲ activity outside business hours[/]")
                if explicit_tags:
                    if e.violation_kind == "brute_force" and prev_vk != "brute_force":
                        lines.append("  [#ff5470][b]▲ BRUTE_FORCE_IN_LOG[/][/]")
                    elif e.violation_kind == "stuffing" and prev_vk != "stuffing":
                        lines.append("  [#ff5470][b]▲ CREDENTIAL_STUFFING[/][/]  — one source IP, many accounts")
                    elif e.violation_kind == "impossible_travel" and prev_vk != "impossible_travel":
                        lines.append(f"  [#ff5470][b]▲ IMPOSSIBLE_TRAVEL[/][/]  [{e.city}]")
                    elif e.violation_kind == "insider" and prev_vk != "insider":
                        lines.append("  [#ff5470][b]▲ INSIDER_BEHAVIOR[/][/]  — after-hours + priv escalation")
                    elif e.violation_kind == "after_hours" and prev_vk != "after_hours":
                        lines.append("  [#ff8c42][b]▲ AFTER_HOURS_ACCESS[/][/]  — minor, corroborate")
                prev_vk = e.violation_kind
            elif is_mine:
                prev_vk = None
                # Claimed IP mismatch: orange even without annotation
                if e.event == "AUTH_OK" and claimed_ip and e.ip != claimed_ip:
                    if annotate or explicit_tags:
                        lines.append(f"[#ff8c42]{_format_entry(e, True, False, '#ff8c42')}[/]")
                        if annotate:
                            lines.append("  [#ff8c42]▲ login IP differs from dossier claim[/]")
                    else:
                        lines.append(_format_entry(e, True, False, "#ffd93d"))
                else:
                    lines.append(_format_entry(e, True, False, "#ffd93d"))
            else:
                prev_vk = None
                lines.append(_format_entry(e, False, False, "#2e3d4f"))

    _render_flat(entries)

    # v2 Low-and-slow only surfaces under the filter's cross-day correlation —
    # the individual failures are sub-threshold and unflagged in the base run.
    if explicit_tags and target_id:
        slow = [e for e in entries
                if e.owner_id == target_id and e.violation_kind == "low_and_slow"]
        if slow:
            lines.append("")
            lines.append(
                f"  [#ff5470][b]▲ LOW_AND_SLOW[/][/]  — {len(slow)} auth failures from "
                f"{slow[0].ip} scattered across the day (each sub-threshold)"
            )

    lines.append("")
    lines.append(f"[dim]{len(entries)} entries  ·  highlighted = current target account[/]")
    return tuple(lines)


def get_logwatch_shared(entries: list[_LogEntry], candidate,
                        upgrade_highlight: bool = False) -> tuple[str, ...]:
    """Free full log — candidate highlighted, claimed-IP mismatches in orange.
    With the log_highlight upgrade, suspicious lines are pre-coloured."""
    return _lw_render(entries, candidate.id, candidate,
                      upgrade_highlight=upgrade_highlight)


def run_logwatch_shared(entries: list[_LogEntry], candidate, state) -> ToolResult:
    """Base run: ▲ inline markers on anomalous entries. findings=() — player judges.

    Batch-3 task #4e: previously called _lw_render with only annotate=True —
    log_highlight ("Log Analyzer HUD") never actually gated anything once
    the tool was run. Now threads the upgrade from state.
    """
    _charge(state, "logwatch")
    _highlight = config.UPGRADE_LOG_HIGHLIGHT in getattr(state, "upgrades", ())
    raw_lines  = _lw_render(entries, candidate.id, candidate, annotate=True,
                            upgrade_highlight=_highlight)
    n_findings = len(_findings_from(candidate, ToolName.LOGWATCH))
    summary = (
        f"{n_findings} anomalous pattern(s) flagged — review highlighted entries."
        if n_findings else
        "No suspicious patterns detected for this account."
    )
    return ToolResult(tool=ToolName.LOGWATCH, findings=(), raw_lines=raw_lines, summary=summary)


def run_logwatch_filtered_shared(entries: list[_LogEntry], candidate, state) -> ToolResult:
    """Filter: explicit ▲ VIOLATION_TYPE labels."""
    _charge(state, "logwatch", filter=True)
    findings  = _findings_from(candidate, ToolName.LOGWATCH)
    _highlight = config.UPGRADE_LOG_HIGHLIGHT in getattr(state, "upgrades", ())
    raw_lines = _lw_render(entries, candidate.id, candidate,
                            annotate=True, explicit_tags=True,
                            upgrade_highlight=_highlight)
    summary = (
        f"[FILTERED] {len(findings)} violation(s) confirmed — see ▲ labels."
        if findings else
        "[FILTERED] No violations confirmed."
    )
    return ToolResult(
        tool=ToolName.LOGWATCH, findings=findings,
        raw_lines=raw_lines, summary=summary, filtered=True,
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


def run_hashcrack(candidate: Candidate, state) -> ToolResult:
    """Legacy stub — callers should use run_hashcrack_shared() via app.py.

    Pre-refactor this called two module-level helpers, _hashcrack_raw_lines()
    and _hashcrack_filter_lines(), that no longer exist -- they were removed
    when the shared-log Hashcrack implementation (run_hashcrack_shared,
    above) replaced this path. Nothing calls run_hashcrack()/
    run_hashcrack_filtered() any more (app.py routes through the *_shared
    variants), so this was dead code that would have raised NameError if it
    ever ran. Brought in line with the run_logwatch() stub just above, which
    got the same treatment during that refactor.
    """
    _charge(state, "hashcrack")
    return ToolResult(tool=ToolName.HASHCRACK, findings=(),
                      raw_lines=("(legacy — use shared hashcrack log)",),
                      summary="Run via hashcrack page.")

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

    if suspicious:
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

    lines.append(f"  R channel LSB entropy  [{score_col(r_score)}]{r_score:>3}[/] / 100")
    lines.append(f"  G channel LSB entropy  [{score_col(g_score)}]{g_score:>3}[/] / 100")
    lines.append(f"  B channel LSB entropy  [{score_col(b_score)}]{b_score:>3}[/] / 100")
    lines.append("")

    # RS analysis ratio — clean images near 1.0; stego images show divergence
    if suspicious:
        rs_r = round(rng.uniform(1.08, 1.22), 3)
        rs_s = round(rng.uniform(0.78, 0.92), 3)
    else:
        rs_r = round(rng.uniform(0.97, 1.03), 3)
        rs_s = round(rng.uniform(0.97, 1.03), 3)
    lines.append(f"  RS analysis  R/S ratio  {rs_r:.3f} / {rs_s:.3f}")

    # Pixel pair correlation — clean near 0.0; stego shows disruption
    corr = round(rng.uniform(0.08, 0.19) if suspicious else rng.uniform(-0.02, 0.03), 3)
    lines.append(f"  LSB autocorrelation    {corr:+.3f}")

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


def run_hashcrack_filtered(candidate: Candidate, state) -> ToolResult:
    """Legacy stub -- callers should use run_hashcrack_filtered_shared() via app.py.

    See run_hashcrack() above -- same dead reference to helpers removed in
    the shared-log refactor, fixed the same way.
    """
    _charge(state, "hashcrack", filter=True)
    findings = _findings_from(candidate, ToolName.HASHCRACK)
    return ToolResult(tool=ToolName.HASHCRACK, findings=findings,
                      raw_lines=("(legacy -- use shared hashcrack log)",),
                      summary="[FILTERED] Run via hashcrack page.", filtered=True)

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
#
# Once cumulative revealed coverage of the zone crosses
# config.STEGO_STAMP_RESOLVE_COVERAGE the signature "resolves" and the
# explicit ▲ violation label prints — the stamp equivalent of the old filter.

_STAMP_KIND_META: dict[DiscrepancyKind, tuple[str, str, str]] = {
    # kind → (signature name, hex color, carrier description)
    DiscrepancyKind.STEGO_PAYLOAD_PRESENT: (
        "AMBER", "#ff8c42", "plaintext-type LSB carrier — dense single-channel block"),
    DiscrepancyKind.ENCRYPTED_PAYLOAD: (
        "CRIMSON", "#ff5470", "high-entropy carrier — XOR/encrypted payload"),
    DiscrepancyKind.COVERT_C2_CHANNEL: (
        "VIOLET", "#c084fc", "sparse multi-channel scatter — covert C2 beacon pattern"),
}


@dataclass(frozen=True)
class StegoImageData:
    """Deterministic, structured render model for one candidate's image."""
    cols: int
    rows: int
    style: int                                   # 0..4 visual style
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
        extra = max(0, day - 1)
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

    def _base_rgb(x: int, y: int) -> tuple[int, int, int]:
        fx = x / max(1, cols - 1)
        fy = y / max(1, rows - 1)
        n  = noise_grid[y][x]
        if style == 0:   # gradient
            r = int(40  + fx * 150 + n); g = int(50 + fy * 110 + n); b = int(140 + (1 - fx) * 80 + n)
        elif style == 1: # thermal
            dist = ((fx - 0.5) ** 2 + (fy - 0.5) ** 2) ** 0.5
            heat = max(0.0, 1.0 - dist * 1.8)
            r = int(80 + heat * 160 + n); g = int(20 + heat * 110 + n); b = int(5 + heat * 50 + n)
        elif style == 2: # photo
            blob = max(0.0, 0.9 - ((fx - 0.4) ** 2 + (fy - 0.35) ** 2))
            r = int(110 + blob * 100 + n); g = int(90 + blob * 80 + n); b = int(70 + blob * 60 + n)
        elif style == 3: # blueprint
            r = int(8 + abs(n) // 4); g = int(18 + abs(n) // 4); b = int(55 + fx * 45 + fy * 25 + n)
        else:            # terminal
            r = int(4 + abs(n) // 4); g = int(35 + fy * 55 + fx * 30 + n); b = int(4 + abs(n) // 4)
        return (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))

    base_rgb = tuple(
        tuple(_base_rgb(x, y) for x in range(cols))
        for y in range(rows)
    )

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


def stamp_signature_lines(img: StegoImageData, reveal_type: bool = False) -> list[str]:
    """Block printed once when coverage resolves.

    Without the filter (`reveal_type=False`) the zone is confirmed as carrying
    a payload, but it is NOT named — the player must classify by the stamp
    colour. With the filter active, the explicit ▲ violation label prints
    (the stamp-mechanic equivalent of the old filter tier)."""
    if img.kind is None or img.zone is None:
        return []
    _sig, col, desc = _STAMP_KIND_META[img.kind]
    _, _, zw, zh = img.zone
    dens = round(img.density * 100)
    size_word = ("sprawling" if zw * zh >= img.cols * img.rows // 4
                 else "moderate" if zw * zh >= img.cols * img.rows // 8
                 else "compact")
    if not reveal_type:
        return [
            "",
            "[#c8d4e1][b]▲ PAYLOAD ZONE MAPPED — carrier confirmed[/][/]",
            f"  [#6b7785]density:[/]  {dens}% fill",
            f"  [#6b7785]extent:[/]   {zw}×{zh} px zone ({size_word})",
            "  [#6b7785]type:[/]     [dim]unclassified — inspect the stamp colour, or run filter (F) to classify[/]",
        ]
    return [
        "",
        f"[{col}][b]▲ {img.kind.value.upper()} — SIGNATURE RESOLVED[/][/]",
        f"  [#6b7785]carrier:[/]  {desc}",
        f"  [#6b7785]density:[/]  {dens}% fill",
        f"  [#6b7785]extent:[/]   {zw}×{zh} px zone ({size_word})",
        "  [dim]flag it on the Evidence Board (Tab)[/]",
    ]


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
