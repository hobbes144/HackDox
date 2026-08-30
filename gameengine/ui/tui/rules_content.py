"""Rules Pages content (issue #30) — the in-game documentation hub.

Single source of truth for the RulesScreen tabs. Everything here is built
DYNAMICALLY from the engine so the pages can never drift from the code:

  · violation catalog / labels      → VIOLATION_CATALOG (app.py's Evidence
                                      Board imports it from here)
  · severities + revealing tool     → candidate_gen._SEVERITY_REVEAL
  · trigger descriptions            → candidate_gen._DISCREPANCY_DESCRIPTIONS
  · today's DENY / FLAG status      → the current Day's rule predicates
  · tool / filter / stamp costs     → config
  · upgrade shop catalog            → config.UPGRADE_CATALOG
  · domain / affiliation lists      → tools_bridge ghostscan data

Changing a rule, a severity, or a violation in the engine re-colours and
re-sorts the relevant table on the next render — no copy edits needed.

Every tab shares one templated layout: a title band, a HOW IT WORKS block,
a VIOLATIONS table (trigger · severity · where revealed · today's rule),
then tool-specific reference subsections behind clear dividers.
"""

from __future__ import annotations

import re

from gameengine import config
from gameengine.core import candidate_gen, tools_bridge
from gameengine.core.models import Day, DiscrepancyKind, Performance, ToolName

# ─── Violation catalog — (group, kind, player-facing label) ─────────────────
# The Evidence Board (app.EVIDENCE_ITEMS) is built from this list, so board
# labels and rules-page tables always match.

VIOLATION_CATALOG: list[tuple[str, DiscrepancyKind, str]] = [
    # DOSSIER (no tool)
    ("DOSSIER",     DiscrepancyKind.HOSTILE_CHAT,           "Hostile chat"),
    ("DOSSIER",     DiscrepancyKind.AFFILIATION_NOT_STATED, "Affiliation not stated"),
    ("DOSSIER",     DiscrepancyKind.DISPOSABLE_EMAIL,       "Disposable email domain"),
    ("DOSSIER",     DiscrepancyKind.WEAK_ENCRYPTION,        "Weak password encryption"),
    ("DOSSIER",     DiscrepancyKind.UNSALTED_STORAGE,       "Unsalted / plaintext storage"),
    # OSINT (Ghostscan)
    # #51: moved out of DOSSIER - confirming it needs the platform sweep.
    ("OSINT",       DiscrepancyKind.MISSING_PUBLIC_PROFILE, "Missing public profile"),
    ("OSINT",       DiscrepancyKind.EMAIL_GITHUB_MISMATCH,  "Email / GitHub mismatch"),
    ("OSINT",       DiscrepancyKind.BREACH_HIT,             "Breach hit"),
    ("OSINT",       DiscrepancyKind.SOCK_PUPPET_ACCOUNTS,   "Sock puppet accounts"),
    ("OSINT",       DiscrepancyKind.AFFILIATION_MISMATCH,   "Affiliation mismatch"),
    ("OSINT",       DiscrepancyKind.AFFILIATION_UNLISTED,   "Affiliation unlisted"),
    ("OSINT",       DiscrepancyKind.BURNER_IDENTITY,        "Burner identity"),
    ("OSINT",       DiscrepancyKind.THREAT_FORUM_MATCH,     "Threat-forum handle match"),
    ("OSINT",       DiscrepancyKind.TYPOSQUAT_HANDLE,       "Typosquatted handle"),
    # FORENSICS (Logwatch)
    ("FORENSICS",   DiscrepancyKind.BRUTE_FORCE_IN_LOG,     "Brute force in log"),
    ("FORENSICS",   DiscrepancyKind.IMPOSSIBLE_TRAVEL,      "Impossible travel"),
    ("FORENSICS",   DiscrepancyKind.INSIDER_BEHAVIOR,       "Insider behavior"),
    ("FORENSICS",   DiscrepancyKind.CREDENTIAL_STUFFING,    "Credential stuffing"),
    ("FORENSICS",   DiscrepancyKind.AFTER_HOURS_ACCESS,     "After-hours access"),
    ("FORENSICS",   DiscrepancyKind.LOW_AND_SLOW,           "Low-and-slow intrusion"),
    ("FORENSICS",   DiscrepancyKind.CLAIMED_IP_MISMATCH,    "Claimed-IP mismatch"),
    # CREDENTIAL (Hashcrack)
    ("CREDENTIAL",  DiscrepancyKind.LEAKED_PASSWORD,        "Leaked password"),
    ("CREDENTIAL",  DiscrepancyKind.WEAK_CREDENTIAL,        "Weak credential"),
    ("CREDENTIAL",  DiscrepancyKind.CROSS_BREACH_REUSE,     "Cross-breach password reuse"),
    # STEGO (Stegotool)
    ("STEGO",       DiscrepancyKind.STEGO_PAYLOAD_PRESENT,  "Stego payload"),
    ("STEGO",       DiscrepancyKind.COVERT_C2_CHANNEL,      "Covert C2 channel"),
    ("STEGO",       DiscrepancyKind.ENCRYPTED_PAYLOAD,      "Encrypted covert payload"),
]

# Engine-derived lookups — the dynamic backbone.
_SEVERITY: dict[DiscrepancyKind, str] = {
    kind: sev for kind, (_tool, sev) in candidate_gen._SEVERITY_REVEAL.items()
}
_TOOL: dict[DiscrepancyKind, ToolName] = {
    kind: tool for kind, (tool, _sev) in candidate_gen._SEVERITY_REVEAL.items()
}
_DESC = candidate_gen._DISCREPANCY_DESCRIPTIONS
_LABEL: dict[DiscrepancyKind, str] = {k: lbl for _g, k, lbl in VIOLATION_CATALOG}


def label_for(kind: DiscrepancyKind) -> str:
    """The one and only player-facing name for a violation (#56).

    VIOLATION_CATALOG is the single source of that name, and EVERY surface must
    read it from here - the evidence board, the rules page, the HackDox Credit
    reveal and the dev ground-truth window. Before this the dev window printed
    the raw enum (`affiliation_mismatch`) while the board printed an authored
    label ("Faked elite affiliation"), and there was no way to tell they were
    the same violation.

    Deliberately NOT mechanically derived from the enum name. A first pass
    asserted label == kind.name.replace("_"," ").capitalize() and rejected
    thirteen existing labels that are simply better prose - "Email / GitHub
    mismatch" beats "Email github mismatch", "Covert C2 channel" beats "Covert
    c2 channel". What matters is that there is exactly ONE name per violation,
    not that a machine invented it. The fallback below only fires for a kind
    nobody has catalogued yet.
    """
    return _LABEL.get(kind, kind.name.replace("_", " ").capitalize())


# #56: every kind must be catalogued exactly once. A missing entry silently
# falls back to a machine-made name that will not match the rules page; a
# duplicate means two rows of the evidence board claim the same violation.
_UNCATALOGUED = sorted(k.name for k in DiscrepancyKind if k not in _LABEL)
if _UNCATALOGUED:
    raise AssertionError(
        f"DiscrepancyKinds missing from VIOLATION_CATALOG (#56): {_UNCATALOGUED}")
_DUPES = sorted(lbl for lbl in _LABEL.values()
                if list(_LABEL.values()).count(lbl) > 1)
if _DUPES:
    raise AssertionError(f"duplicate violation labels (#56): {sorted(set(_DUPES))}")


# ─── Progressive unlock — gating the catalog / tabs / rules by tool access ───
# Single-sourced off the same _TOOL map every other lookup in this module
# already derives from candidate_gen._SEVERITY_REVEAL: a discrepancy can never
# be PLANTED before its revealing tool is taught (candidate_gen.intro_day), so
# a kind whose tool is still locked can never actually be present on a
# candidate yet. Hiding it here isn't just tidy — it means the Evidence Board
# and every Rules-page surface never show the player something they cannot
# possibly have evidence for. Re-tiering a kind's revealing tool updates every
# gate below for free; nothing here is a second copy to keep in sync by hand.

def _tool_unlocked(tool: ToolName | None, unlocked_tools: set[str] | None) -> bool:
    """True if `tool` is currently accessible to the player.

    `unlocked_tools` is `GameState.unlocked_tools` (never contains "dossier" —
    that tool is always available, see config.TOOL_UNLOCK_DAY). `None` means
    "no gating context" — tests, the rules-lab preview, anything without a
    live GameState — and shows everything, matching this module's behaviour
    before progressive unlock reached the Rules Pages / Evidence Board.
    """
    if tool is None or tool == ToolName.DOSSIER:
        return True
    if unlocked_tools is None:
        return True
    return tool.value in unlocked_tools


# Canonical group display order for every multi-group surface (the Evidence
# Board's category strip, visible_catalog's sort below). NOT the order groups
# happen to be authored in VIOLATION_CATALOG (that's DOSSIER/OSINT/FORENSICS/
# CREDENTIAL/STEGO) — CREDENTIAL reads before FORENSICS here on purpose, so a
# second hand-kept copy of this list is exactly how it'd drift silently.
GROUP_ORDER = ["DOSSIER", "OSINT", "CREDENTIAL", "FORENSICS", "STEGO"]


def visible_catalog(
    unlocked_tools: set[str] | None,
) -> list[tuple[str, DiscrepancyKind, str]]:
    """VIOLATION_CATALOG filtered to kinds the player can currently observe,
    ordered by GROUP_ORDER and then by severity ascending (minor -> major ->
    critical) within each group so the board reads calm-to-alarming.

    Used by the Evidence Board (app.py) so its single scrollable list only
    ever offers violations the player could actually have caught, in the
    same order it has always displayed them in.
    """
    items = [(g, k, lbl) for g, k, lbl in VIOLATION_CATALOG
             if _tool_unlocked(_TOOL.get(k), unlocked_tools)]
    items.sort(key=lambda it: (
        GROUP_ORDER.index(it[0]),
        _SEV_RANK.get(_SEVERITY.get(it[1], "minor"), 0),
    ))
    return items


def _locked_tab_text(tool: ToolName, title: str) -> str:
    """Placeholder shown in place of a tool tab's full reference material
    while that tool is still locked — reuses #33's ⊘ locked-tool language."""
    unlock_day = config.TOOL_UNLOCK_DAY[tool.value]
    lines = _band(f"{title} — LOCKED", "#3d6478")
    lines += [
        "",
        "  [#3d6478][b]⊘  Not authorized yet.[/][/]",
        f"  [dim]{_TOOL_LABEL[tool].capitalize()} unlocks on Day {unlock_day}. Its",
        "  violation catalog and reference material open up the day the",
        "  Overseer grants it — check back once it's live.[/]",
    ]
    return "\n".join(lines)


# Rules whose predicate names one DiscrepancyKind gate on that kind's
# revealing tool, exactly like violation_table's TODAY column already reads
# rule.predicate against a kind. Rules on a different predicate shape
# (has_severity: / missing_field:) aren't tied to a single tool and are
# never gated — safer to always show than to guess.
def _rule_tool(rule) -> ToolName | None:
    if not rule.predicate.startswith("has_discrepancy:"):
        return None
    try:
        kind = DiscrepancyKind(rule.predicate.split(":", 1)[1])
    except ValueError:
        return None
    return _TOOL.get(kind)


# Every authored rule opens with one of these two fixed boilerplate phrases
# (checked against all 27 of Day 1's rules — the campaign-wide rulebook).
# Dimming the boilerplate and bolding + colouring the remainder makes the
# part that actually changes rule to rule — the trigger condition — the part
# that stands out, instead of every line reading as the same wall of text.
_RULE_PREFIX_STRIP = (
    re.compile(r"^Deny any candidate who(?:se)?\s+", re.IGNORECASE),
    re.compile(r"^Flag \(do not auto-deny\)\s+", re.IGNORECASE),
)


def _highlighted_rule_line(text: str, accent: str) -> str:
    for pat in _RULE_PREFIX_STRIP:
        m = pat.match(text)
        if m:
            prefix, remainder = text[:m.end()], text[m.end():]
            remainder = remainder[:1].upper() + remainder[1:]
            return f"[dim]{prefix}[/][{accent}][b]{remainder}[/][/]"
    # Unrecognised phrasing (a future rule authored differently) — still an
    # improvement over plain text, just without the dimmed lead-in to split.
    return f"[{accent}][b]{text}[/][/]"


SEV_COLOR   = {"minor": "#ffd93d", "major": "#ff8c42", "critical": "#ff5470"}
_SEV_RANK   = {"minor": 0, "major": 1, "critical": 2}
GROUP_ACCENT = {
    "DOSSIER":    "#7dd3c0",
    "OSINT":      "#6ad4ff",
    "FORENSICS":  "#ffb454",
    "CREDENTIAL": "#c084fc",
    "STEGO":      "#ff8cc8",
}
_TOOL_LABEL = {
    ToolName.DOSSIER:   "dossier",
    ToolName.GHOSTSCAN: "ghostscan",
    ToolName.LOGWATCH:  "logwatch",
    ToolName.HASHCRACK: "hashcrack",
    ToolName.STEGOTOOL: "stegotool",
}

# How each violation is actually caught (reveal tier / mechanic). Short —
# rendered as the dim second line of a table row after the trigger text.
_CATCH: dict[DiscrepancyKind, str] = {
    DiscrepancyKind.MISSING_PUBLIC_PROFILE: "GHOSTSCAN — handle barely appears on the platform sweep at all",
    DiscrepancyKind.HOSTILE_CHAT:           "free — read the chat panel (Sentiment Scanner upgrade ⚠-marks it)",
    DiscrepancyKind.AFFILIATION_NOT_STATED: "DOSSIER — the affiliation field is blank; nothing was claimed",
    DiscrepancyKind.DISPOSABLE_EMAIL:       "free — domain visible on the dossier, no tool needed (quick deny)",
    DiscrepancyKind.WEAK_ENCRYPTION:        "free — the raw hash is on the dossier (32 hex = MD5, auto-labeled with Cipher ID HUD); a crack (if attempted) reveals a fine password — the algorithm is the problem, not the value",
    DiscrepancyKind.UNSALTED_STORAGE:       "free — the ⚠ UNSALTED marker on the dossier shows the stored password in the clear; no crack needed at all",
    DiscrepancyKind.EMAIL_GITHUB_MISMATCH:  "base recon shows commit email · filter highlights the mismatch",
    DiscrepancyKind.BREACH_HIT:             "base recon highlights breach panel · filter confirms ▲ BREACH_HIT",
    DiscrepancyKind.SOCK_PUPPET_ACCOUNTS:   "handle on a CRITICAL forum — blended in base run, filter labels it",
    DiscrepancyKind.AFFILIATION_MISMATCH:   "GHOSTSCAN — sweep shows a DIFFERENT org than the dossier claims",
    DiscrepancyKind.AFFILIATION_UNLISTED:   "GHOSTSCAN — profiles exist but carry no org tag at all",
    DiscrepancyKind.BURNER_IDENTITY:        "account registry: creation dates clustered within days — filter labels",
    DiscrepancyKind.THREAT_FORUM_MATCH:     "handle in the threat-forum list — filter reveals with [CRITICAL] tag",
    DiscrepancyKind.TYPOSQUAT_HANDLE:       "free cue on identity check · filter confirms the lookalike",
    DiscrepancyKind.BRUTE_FORCE_IN_LOG:     "free log shows the AUTH_FAIL burst · base run flags · filter labels",
    DiscrepancyKind.IMPOSSIBLE_TRAVEL:      "base run tags cities · filter's geo timeline makes it explicit",
    DiscrepancyKind.INSIDER_BEHAVIOR:       "sensitive FILE_ACCESS + PRIV_ESCALATE after hours · filter labels",
    DiscrepancyKind.CREDENTIAL_STUFFING:    "one IP, many accounts, few tries — base detects · filter names it",
    DiscrepancyKind.AFTER_HOURS_ACCESS:     "activity outside business hours — benign alone (minor)",
    DiscrepancyKind.LOW_AND_SLOW:           "sub-threshold on purpose — only the filter's correlation finds it",
    DiscrepancyKind.CLAIMED_IP_MISMATCH:    "free tier highlights AUTH_OK rows that diverge from the dossier's claimed IP — corroborate before denying",
    DiscrepancyKind.LEAKED_PASSWORD:        "crack reveals plaintext + BREACH_MATCH names the corpus",
    DiscrepancyKind.WEAK_CREDENTIAL:        "weak encryption (MD5) cracks to a weak plaintext — minor hygiene flag",
    DiscrepancyKind.CROSS_BREACH_REUSE:     "crack + a SECOND breach-corpus match — cross-check the breach panel",
    DiscrepancyKind.STEGO_PAYLOAD_PRESENT:  "stamp for AMBER cells in a dense block; ≥60% coverage resolves ▲",
    DiscrepancyKind.COVERT_C2_CHANNEL:      "VIOLET sparse scatter over a wide zone — resolve by stamping",
    DiscrepancyKind.ENCRYPTED_PAYLOAD:      "CRIMSON mid-density cells — filter (F) names the payload type",
}

# ─── Task #6: worked examples, one per violation ─────────────────────────────
# Exactly 3 lines each, styled as a miniature rendering of the surface that
# actually reveals the kind (a dossier field, a Ghostscan sweep line, a
# Logwatch/Hashcrack log row, a Stego reading) — never invented prose. Shown
# immediately under each violation's own table row (see violation_table
# below), so the example is always paired with the entry it belongs to
# instead of living in a separate reference section the player has to cross-
# reference by hand.
_EXAMPLE: dict[DiscrepancyKind, tuple[str, str, str]] = {
    DiscrepancyKind.HOSTILE_CHAT: (
        'CANDIDATE: "this whole process is a joke, you clearly have no idea what you\'re doing"',
        'CANDIDATE: "just approve me or I will make this difficult for everyone involved"',
        "escalating hostile tone across consecutive lines, unprompted",
    ),
    DiscrepancyKind.AFFILIATION_NOT_STATED: (
        "AFFILIATION:  (blank — nothing claimed)",
        "no employer/org listed anywhere on the dossier",
        "nothing to corroborate, and nothing to contradict, either",
    ),
    DiscrepancyKind.DISPOSABLE_EMAIL: (
        # A fictional-but-evocative domain, deliberately NOT one of the exact
        # strings tools_bridge's own disposable-domain bank renders further
        # down this same tab (see test_dossier_tab_no_longer_double_lists_
        # domains) — the example teaches the PATTERN, the reference block
        # below it is still the single source for the literal list.
        "EMAIL:  j.torres93@throwaway.mail",
        "throwaway.mail — disposable/burner-style domain, zero verification trail",
        "fast DENY per rulebook, no tool required to confirm it",
    ),
    DiscrepancyKind.WEAK_ENCRYPTION: (
        "SUBMITTED_HASH:  5f4dcc3b5aa765d61d8327deb882cf99",
        "32 hex characters = MD5 — a broken algorithm, on sight",
        "the flaw is the algorithm; a crack (if run) may reveal a fine password",
    ),
    DiscrepancyKind.UNSALTED_STORAGE: (
        'UNSALTED — password stored in the clear: "Summer2023!"',
        "no hash to crack — the plaintext is sitting right there",
        "flag or deny on sight, don't spend ⏱ running Hashcrack on it",
    ),
    DiscrepancyKind.MISSING_PUBLIC_PROFILE: (
        "GITHUB    @j_torres93   (1 repo, joined 3 days ago)",
        "LINKEDIN  — no results —",
        "a real candidate has more footprint than this",
    ),
    DiscrepancyKind.EMAIL_GITHUB_MISMATCH: (
        "DOSSIER EMAIL   j.torres93@corp.net",
        "GITHUB COMMIT   r.torres93@protonmail.com",
        "commit email does not match the claimed dossier address",
    ),
    DiscrepancyKind.BREACH_HIT: (
        "BREACH FEED SYNC",
        'BREACH_HIT — j.torres93@corp.net confirmed in corpus "CollectionX_2019"',
        "the email itself, not just the password, is in a breach dump",
    ),
    DiscrepancyKind.SOCK_PUPPET_ACCOUNTS: (
        "ACCOUNT REGISTRY",
        "@j_torres93 created 2024-01-02  ·  @jt_backup91 created 2024-01-03",
        "CRITICAL — accounts clustered within 48 hours of each other",
    ),
    DiscrepancyKind.AFFILIATION_MISMATCH: (
        "CLAIMED:  Senior Engineer @ Meridian Labs",
        "SWEEP:    no record at Meridian Labs — profile says self-employed",
        "the claimed org and the sweep's finding are two different things",
    ),
    DiscrepancyKind.AFFILIATION_UNLISTED: (
        "CLAIMED:  Senior Engineer @ Meridian Labs",
        "SWEEP:    profiles exist, but carry no org/employer tag at all",
        "nothing on the public record corroborates the claim either way",
    ),
    DiscrepancyKind.BURNER_IDENTITY: (
        "ACCOUNT AGE:  @j_torres93 — created 6 days ago",
        "zero activity predating the application window",
        "a freshly-minted identity with no history behind it",
    ),
    DiscrepancyKind.THREAT_FORUM_MATCH: (
        "FORUM SWEEP",
        'CRITICAL — handle "j_torres93" matches a known threat-forum account',
        "the account itself, not just an associate, is the match",
    ),
    DiscrepancyKind.TYPOSQUAT_HANDLE: (
        "CLAIMED ORG:      Meridian Labs  (meridianlabs.io)",
        "REGISTERED AS:    meridian-labs.io   — note the extra hyphen",
        "a lookalike domain, one character off the real org's",
    ),
    DiscrepancyKind.BRUTE_FORCE_IN_LOG: (
        "09:41:03  AUTH_FAIL  185.220.31.7  j.torres93@corp.net",
        "09:41:04  AUTH_FAIL  185.220.31.7  j.torres93@corp.net",
        "09:41:09  AUTH_OK    185.220.31.7  j.torres93@corp.net",
    ),
    DiscrepancyKind.IMPOSSIBLE_TRAVEL: (
        "09:12:00  AUTH_OK  185.220.31.7  j.torres93@corp.net  (Frankfurt, DE)",
        "09:47:00  AUTH_OK  103.21.44.9   j.torres93@corp.net  (Singapore, SG)",
        "two cities, 35 minutes apart — no flight covers that distance",
    ),
    DiscrepancyKind.INSIDER_BEHAVIOR: (
        "23:41:02  FILE_READ  10.0.0.4  j.torres93@corp.net  /etc/shadow",
        "23:41:05  SUDO_EXEC  10.0.0.4  j.torres93@corp.net  /bin/bash",
        "sensitive path + privilege escalation, both after hours",
    ),
    DiscrepancyKind.CREDENTIAL_STUFFING: (
        "09:30:00  AUTH_FAIL  45.131.9.2  r.chen@corp.net",
        "09:30:02  AUTH_FAIL  45.131.9.2  s.patel@corp.net",
        "09:30:11  AUTH_OK    45.131.9.2  j.torres93@corp.net",
    ),
    DiscrepancyKind.AFTER_HOURS_ACCESS: (
        "22:14:00  AUTH_OK    login IP  j.torres93@corp.net",
        "22:19:00  FILE_READ  login IP  /home/user/.bash_history",
        "outside business hours, but a normal path — weigh it, don't auto-deny",
    ),
    DiscrepancyKind.LOW_AND_SLOW: (
        "03:12  AUTH_FAIL  91.219.4.8  j.torres93@corp.net",
        "07:58  AUTH_FAIL  91.219.4.8  j.torres93@corp.net",
        "12:40  AUTH_FAIL  91.219.4.8  j.torres93@corp.net  (no ▲ — too spread out for the base run)",
    ),
    DiscrepancyKind.CLAIMED_IP_MISMATCH: (
        "DOSSIER CLAIMED IP:  10.0.4.22",
        "09:12:00  AUTH_OK  185.220.31.7  j.torres93@corp.net  ← doesn't match",
        "free tier already tints this row orange — no upgrade needed to see it",
    ),
    DiscrepancyKind.LEAKED_PASSWORD: (
        'CRACKED:  "dragon2019"',
        'BREACH_MATCH — found verbatim in corpus "CollectionX_2019"',
        "this exact password is already public knowledge",
    ),
    DiscrepancyKind.WEAK_CREDENTIAL: (
        "HASH:     098f6bcd4621d373cade4e832627b4f6  (MD5)",
        'CRACKED:  "abc123"',
        "weak encryption cracked to a weak plaintext — minor hygiene flag",
    ),
    DiscrepancyKind.CROSS_BREACH_REUSE: (
        'CRACKED:       "Summer2023!"',
        'BREACH PANEL:  same password also confirmed in corpus "MegaLeak_2021"',
        "reused across two separate breaches — the breach panel already shows it",
    ),
    DiscrepancyKind.STEGO_PAYLOAD_PRESENT: (
        "AMBER cell cluster, dense block, ~64% coverage once stamped",
        "R 28/100  G 61/100  B 34/100 — the cluster, not the numbers, is the tell",
        "resolves to STEGO_PAYLOAD_PRESENT once the block is fully stamped",
    ),
    DiscrepancyKind.COVERT_C2_CHANNEL: (
        "VIOLET markers scattered thin across a wide region of the grid",
        "sparse, not clustered — easy to miss without stamping the whole zone",
        "resolves to COVERT_C2_CHANNEL — a beacon channel, not a dropped file",
    ),
    DiscrepancyKind.ENCRYPTED_PAYLOAD: (
        "CRIMSON cells, mid-density — no single channel stands out on its own",
        "R 41/100  G 39/100  B 44/100",
        "resolves to ENCRYPTED_PAYLOAD once filtered (F) — the filter names the type",
    ),
}

_W = 66   # shared content width for bands / dividers


# ─── Shared layout helpers (templated look across all five tabs) ─────────────


def _band(title: str, accent: str, note: str = "") -> list[str]:
    pad = " " * max(1, _W - len(title) - 4)
    out = [f"[b {accent} on #0d1b2a] ▌ {title}{pad}[/]"]
    if note:
        out.append(f"[dim]{note}[/]")
    out.append(f"[{accent}]{'━' * _W}[/]")
    return out


def _sub(title: str, accent: str = "#6b7785") -> list[str]:
    bar = "─" * max(1, _W - len(title) - 4)
    return ["", f"[{accent}]── {title} {bar}[/]"]


def _fit(text: str, width: int) -> str:
    return text[: width - 1] + "…" if len(text) > width else text.ljust(width)


def _rule_status(day: Day | None, kind: DiscrepancyKind) -> tuple[str, str]:
    """(label, colour) for how TODAY's ruleset treats this violation."""
    if day is not None:
        for rule in day.rules:
            if rule.predicate == f"has_discrepancy:{kind.value}":
                if rule.severity == "disqualifying":
                    return "DENY", "#ff5470"
                return "FLAG", "#ff8c42"
    return "—", "#3d6478"


def violation_table(day: Day | None, group: str) -> list[str]:
    """The templated violations table for one board group.

    Columns: violation (exact enum value) · severity · revealing surface ·
    today's rule status. A dim second line per row carries the trigger and
    how to catch it. Rows sort minor → critical, matching the board.
    """
    rows = sorted(
        [(k, lbl) for g, k, lbl in VIOLATION_CATALOG if g == group],
        key=lambda it: _SEV_RANK.get(_SEVERITY.get(it[0], "minor"), 0),
    )
    accent = GROUP_ACCENT.get(group, "#7dd3c0")
    out = [
        f"[{accent}][b]▎ VIOLATIONS — {group}[/][/]",
        "[#6b7785]  VIOLATION                 SEVERITY  SOURCE     TODAY[/]",
        f"[#1c2733]{'─' * _W}[/]",
    ]
    for kind, _lbl in rows:
        sev  = _SEVERITY.get(kind, "minor")
        scol = SEV_COLOR[sev]
        tool = _TOOL_LABEL.get(_TOOL.get(kind, ToolName.DOSSIER), "?")
        status, stcol = _rule_status(day, kind)
        out.append(
            f"  [{scol}][b]{_fit(kind.value.upper(), 26)}[/][/]"
            f"[{scol}]{_fit(sev, 10)}[/]"
            f"[#7dd3c0]{_fit(tool, 11)}[/]"
            f"[{stcol}][b]{status}[/][/]"
        )
        out.append(f"    [dim]{_DESC.get(kind, '')}[/]")
        catch = _CATCH.get(kind)
        if catch:
            out.append(f"    [#3d6478]catch: {catch}[/]")
        for i, ex_line in enumerate(_EXAMPLE.get(kind, ())):
            lead = "example:" if i == 0 else "        "
            out.append(f"      [#3d6478]{lead}[/] [dim]{ex_line}[/]")
    out.append(f"[#1c2733]{'─' * _W}[/]")
    out.append("[dim]  TODAY column: DENY = disqualifying rule · FLAG = weighted "
               "(corroborate) · — = not in today's ruleset[/]")
    return out


# ─── Tab 1 — RULES (day rules · quotas · resources · systems) ────────────────


def build_rules_text(day: Day | None, unlocked_tools: set[str] | None = None) -> str:
    kb     = config.KEY_BINDINGS
    lines: list[str] = []

    # ── Today's ruleset ────────────────────────────────────────────────
    title = day.title if day else "No day loaded"
    lines += _band(f"TODAY'S RULESET — {title}", "#7dd3c0",
                   "read every shift — rules change day to day")

    # #49: the day's authored framing, above the machine rules. The rule list
    # below is exhaustive and near-identical most days, which makes it very easy
    # to stop reading it; this is the sentence that says what is actually new
    # today. Rendered verbatim from day_NN.json's rule_sheet — no day file, no
    # block, and the panel reads exactly as it did before #49.
    sheet = day.rule_sheet if day is not None else None
    if sheet is not None and sheet.summary:
        lines.append("")
        lines.append(f"  [#e8f0f8][i]{sheet.summary}[/][/]")
    if sheet is not None and sheet.notes:
        lines.append("")
        lines.append("[#7dd3c0][b]  TODAY, IN PLAIN LANGUAGE[/][/]")
        for note in sheet.notes:
            lines.append(f"  [#c8d4e1]·[/] {note}")

    rules = day.rules if day else ()
    # Progressive unlock: a rule keyed to a still-locked tool describes a
    # violation that cannot possibly be planted yet (candidate_gen.intro_day
    # gates generation the same way) — showing it early would teach the
    # player to watch for evidence that doesn't exist. unlocked_tools=None
    # (tests, the rules-lab preview) shows the full campaign rulebook.
    visible = [r for r in rules if _tool_unlocked(_rule_tool(r), unlocked_tools)]
    hidden  = len(rules) - len(visible)
    disq  = [r for r in visible if r.severity == "disqualifying"]
    minor = [r for r in visible if r.severity != "disqualifying"]
    if disq:
        lines.append("")
        lines.append("[#ff5470][b]DISQUALIFYING[/][/]  — any one of these → DENY")
        for r in disq:
            lines.append(f"  [#ff5470]✗[/]  {_highlighted_rule_line(r.text, '#ff5470')}")
    if minor:
        lines.append("")
        lines.append("[#ff8c42][b]WEIGHTED[/][/]  — flag on the Evidence Board; "
                     "corroborate before denying")
        for r in minor:
            lines.append(f"  [#ff8c42]△[/]  {_highlighted_rule_line(r.text, '#ff8c42')}")
    if not rules:
        lines.append("[dim]No rules loaded for this day.[/]")
    elif hidden:
        lines.append("")
        lines.append(
            f"[dim]  + {hidden} more rule{'s' if hidden != 1 else ''} on the books — "
            "they surface here as you unlock the tools that reveal them.[/]")

    # ── Daily quotas & performance ─────────────────────────────────────
    lines.append("")
    lines += _band("DAILY QUOTAS & PERFORMANCE", "#7dd3c0")
    if day:
        q = day.quotas
        lines += [
            "[#6b7785]  QUOTA                       THRESHOLD   MISSING IT MEANS[/]",
            f"[#1c2733]{'─' * _W}[/]",
            f"  {_fit('minimum correct admits', 28)}[#ffd93d]{q.min_correct_admits:<12}[/]"
            f"[#ff8c42]POOR day rating[/]",
            f"  {_fit('maximum false admits', 28)}[#ffd93d]{q.max_false_admits:<12}[/]"
            f"[#ff5470]FAILED day rating[/]",
            f"[#1c2733]{'─' * _W}[/]",
        ]
    lines += [
        "",
        "[#6b7785]  RATING      HOW YOU EARN IT[/]",
        f"[#1c2733]{'─' * _W}[/]",
        f"  [#00ff9f]{_fit('EXCELLENT', 12)}[/]quotas met and zero wrong verdicts",
        f"  [#7dd3c0]{_fit('PASSING', 12)}[/]quotas met",
        f"  [#ff8c42]{_fit('POOR', 12)}[/]too few correct admits",
        f"  [#ff5470]{_fit('FAILED', 12)}[/]false admits over quota, or Site Health "
        "below the loss line",
        f"[#1c2733]{'─' * _W}[/]",
    ]

    # ── Computing hours (issue #27) ────────────────────────────────────
    lines.append("")
    lines += _band("COMPUTING HOURS (⏱) — FINITE DAILY BUDGET", "#ffb454")
    base = config.STARTING_COMPUTE
    d_no = day.number if day else 1
    today_budget = config.daily_compute_budget(d_no, base)
    lines += [
        "  A fixed ⏱ pool is granted at the start of every shift. It is spent",
        "  ONLY on tools, filters, and stamps — verdicts never grant ⏱, and",
        "  leftover hours are discarded at end of day (no carry-over).",
        "  Running out mid-day disables tools for the rest of the shift;",
        "  there is no other penalty. Ration the pool across all candidates.",
        "",
        f"  [#6b7785]base budget[/]      [#ffb454]{base} ⏱[/]  "
        f"[dim](+{config.DAILY_BUDGET_GROWTH} ⏱ per day · raise the base in the shop)[/]",
        f"  [#6b7785]today's budget[/]   [#ffb454]{today_budget} ⏱[/]",
    ]
    lines += _sub("tool costs", "#ffb454")
    lines += [
        "[#6b7785]  KEY  TOOL        RUN     FILTER[/]",
        f"[#1c2733]{'─' * _W}[/]",
    ]
    for key, tool in (("tool_ghostscan", "ghostscan"), ("tool_hashcrack", "hashcrack"),
                      ("tool_logwatch", "logwatch")):
        lines.append(
            f"  [b]{kb[key].upper()}[/]    {_fit(tool, 12)}"
            f"[#ffb454]{config.TOOL_COSTS[tool]:>2} ⏱[/]   "
            f"[#c084fc]+{config.FILTER_COSTS[tool]} ⏱[/]"
        )
    lines.append(
        f"  [b]{kb['tool_stegotool'].upper()}[/]    {_fit('stegotool', 12)}"
        f"[#ffb454]{config.STEGO_STAMP_COST:>2} ⏱[/][dim]/stamp[/]"
        f"[#c084fc] +{config.STEGO_FILTER_COST} ⏱[/][dim] classify filter[/]"
    )
    lines.append(f"[#1c2733]{'─' * _W}[/]")
    lines.append("  [dim]Optimizer upgrades knock "
                 f"{config.TOOLCOST_REDUCTION} ⏱ off a tool's run cost (floor 1).[/]")

    # ── Site Health ────────────────────────────────────────────────────
    lines.append("")
    lines += _band("SITE HEALTH (⛨) — THE LOSS CONDITION", "#ff5470")
    lines += [
        "  A persistent 0–100% gauge that carries across days. Every ADMITTED",
        "  candidate applies a hidden weight: beneficial actors raise health,",
        "  threats lower it. Denials never move it — a denied threat never",
        "  entered the site. Deltas accumulate silently during the shift and",
        "  land in ONE batch at end of day (watch the pending value in the",
        "  status bar). Wrong denials cost you nothing but the reward.",
        "",
        f"  [#ff5470]▼ below {config.SITE_HEALTH_LOSS_THRESHOLD:.0f}%[/]"
        "   at end of day — HackDox is lost (game over)",
        f"  [#00ff9f]▲ above {config.SITE_HEALTH_REWARD_THRESHOLD:.0f}%[/]"
        f"   at end of day — HackDollar$ bonus (max {config.HACKDOLLAR_SITE_HEALTH_BONUS})",
    ]

    # ── HackDollar$ + credits + upgrades ───────────────────────────────
    lines.append("")
    lines += _band("HACKDOLLAR$ · CREDITS · UPGRADES", "#00ff9f")
    lines += [
        "  HackDollar$ (HD$) is the persistent between-day currency. Earned on",
        f"  correct verdicts ([#00ff9f]+{config.HACKDOLLAR_PER_CORRECT_ADMIT}[/] admit · "
        f"[#00ff9f]+{config.HACKDOLLAR_PER_CORRECT_DENY}[/] deny) plus the evidence-board",
        "  bonus and the end-of-day health bonus. Spent only in the night shop.",
        "",
        f"  [#c084fc]HackDox Credits[/] — type [b]reveal[/] to spend one and see the",
        "  current candidate's ground truth (correct verdict + planted",
        f"  violations, no evidence trail). Max {config.HACKDOX_CREDIT_MAX} slots · "
        f"{config.SHOP_PRICE_CREDIT} HD$ each.",
        f"  [#ffb454]⏱ capacity[/] — +{config.COMPUTE_CAPACITY_STEP} base budget "
        f"per purchase · {config.SHOP_PRICE_CAPACITY} HD$.",
    ]
    lines += _sub("upgrade catalog (permanent · bought in the night shop)", "#00ff9f")
    lines += [
        "[#6b7785]  UPGRADE               HD$   EFFECT[/]",
        f"[#1c2733]{'─' * _W}[/]",
    ]
    _by_cat: dict[str, list[tuple[str, str, int, str]]] = {
        cat: [] for cat in config.UPGRADE_CATEGORY_ORDER
    }
    for uid, label, price, desc in config.UPGRADE_CATALOG:
        _by_cat[config.UPGRADE_CATEGORY[uid]].append((uid, label, price, desc))
    for cat in config.UPGRADE_CATEGORY_ORDER:
        cat_upgrades = _by_cat[cat]
        if not cat_upgrades:
            continue
        accent = config.UPGRADE_CATEGORY_ACCENT.get(cat, "#6b7785")
        lines.append(f"  [{accent}]{cat}[/]")
        for _uid, label, price, desc in cat_upgrades:
            lines.append(f"  {_fit(label, 22)}[#00ff9f]{price:>3}[/]   [dim]{desc}[/]")
    lines.append(f"[#1c2733]{'─' * _W}[/]")

    # ── Evidence board ─────────────────────────────────────────────────
    lines.append("")
    lines += _band("EVIDENCE BOARD — ACCURACY PAYS", "#c084fc")
    lines += [
        "  Tab on any tool page opens the board. Space cycles each item:",
        "  [dim]unknown[/] → [b]marked[/] (present) → [#6b7785]✗ absent[/] (ruled out) → unknown.",
        "  Only MARKED items are scored, against the candidate's real violations:",
        "",
        f"  [#00ff9f]bonus = {config.BOARD_ACCURACY_MAX_BONUS} HD$ × hits ÷ "
        "(hits + false flags + misses)[/]   [dim](on correct verdicts)[/]",
        "",
        "  [#ff8c42]Do NOT flag everything[/] — every false flag divides the bonus",
        "  down. A clean candidate with an empty board pays the FULL bonus.",
        "  Flag what the evidence supports, rule out the rest.",
    ]

    # ── Alignment ──────────────────────────────────────────────────────
    lines.append("")
    lines += _band("ALIGNMENT — THE MORAL AXIS", "#c084fc")
    lines += [
        f"  A hidden bar from {config.ALIGNMENT_MIN} (Dark Web) to "
        f"+{config.ALIGNMENT_MAX} (White Hat), shown as dots in the status bar.",
        "  Most candidates carry no moral weight; two kinds do:",
        "",
        "  [#ff5470]Dark Web operatives[/]  admit → drift Dark Web · deny → drift White Hat",
        "  [#00ff9f]The White Hat[/]        admit → drift White Hat · deny → drift Dark Web",
        "",
        "  These verdicts shift alignment REGARDLESS of rule-correctness — the",
        "  rules may demand one thing and your conscience another. Alignment",
        "  steers the Overseer's tone and the campaign's ending.",
    ]

    # ── Quick cases ────────────────────────────────────────────────────
    lines.append("")
    return "\n".join(lines)


# ─── Tab 2 — DOSSIER (free, no tool) ─────────────────────────────────────────
#
# Split out of build_rules_text by #50. That builder had grown to nine sections
# and ~226 lines while every other tab sat around 60, which is why the rules
# page read as too long and buried its own reference material. Everything here
# is what the player can determine from the dossier alone, with no tool run:
# the quick-case patterns, the dossier-tier violation table, the password
# encryption chip, and the email-domain / affiliation lists.
#
# Pure extraction - no copy was rewritten in the move.
def build_dossier_text(day: Day | None) -> str:
    lines: list[str] = []
    lines += _band("QUICK CASES — BANK TIME, SPEND NOTHING", "#7dd3c0")
    lines += [
        "  Two dossier patterns settle instantly, no tools required:",
        "",
        "  [#ff5470]✗ fast DENY[/]   email domain on the disposable list below —",
        "                DISPOSABLE_EMAIL is visible right on the dossier.",
        "  [#00ff9f]✓ fast ADMIT[/]  prestigious org + matching institutional email;",
        "                one ghostscan run confirming the affiliation settles it.",
        "                [#ff8c42]Beware:[/] sneaky actors fake elite orgs — a faked",
        "                claim surfaces as AFFILIATION_MISMATCH on the filter.",
    ]

    # ── Dossier-visible violations table ───────────────────────────────
    lines.append("")
    lines += violation_table(day, "DOSSIER")

    # ── Password encryption-strength chip ───────────────────────────────
    lines += _sub("password encryption strength", "#7dd3c0")
    lines += [
        "[#ff5470]WEAK ENC[/]    MD5 — cracks instantly. On its own this plants",
        "             WEAK_ENCRYPTION (the algorithm is the problem — the",
        "             chip alone is enough, no tool needed). Paired with a",
        "             weak plaintext it's WEAK_CREDENTIAL instead, which",
        "             Hashcrack has to crack to confirm.",
        "             [dim]e.g. 5f4dcc3b5aa765d61d8327deb882cf99[/] [#6b7785](32 hex)[/]",
        "[#ffd93d]MEDIUM ENC[/]  SHA256 — crackable with effort, usually clean.",
        "             [dim]e.g. a94a8fe5ccb19ba61c4c0873d391e987…[/] [#6b7785](64 hex)[/]",
        "[#00ff9f]STRONG ENC[/]  bcrypt — always safe; never worth cracking.",
        "             [dim]e.g. $2b$12$KIXQ7c5s9j2mR8vN…[/] [#6b7785]($2b$ prefix)[/]",
        "",
        "  [dim]Without Cipher ID HUD the chip label above isn't shown — count[/]",
        "  [dim]hex characters (or spot the $2b$ prefix) against the examples[/]",
        "  [dim]to tell the tiers apart yourself.[/]",
        "",
        "  [#ff5470]⚠ UNSALTED[/]  a rarer marker that replaces the hash chip",
        "             entirely — storage has no salt at all, so the Password",
        "             entry just IS the plaintext, printed in the clear, no",
        "             Hashcrack run needed or possible. UNSALTED_STORAGE",
        "             (major): e.g. [dim]monkey123  ⚠ UNSALTED[/]",
    ]

    # ── The day's rule sheet (#49) ─────────────────────────────────────
    # Authored per day in day_NN.json and rendered VERBATIM — this is the
    # Papers-Please sheet, the thing the player is supposed to be able to apply
    # without inferring anything. It sits above the engine-wide reference lists
    # rather than replacing them: the sheet says what matters today, the banks
    # below stay as the complete catalogue. A day with no authored sheet (every
    # synthesized day) renders exactly as it did before #49.
    sheet = day.rule_sheet if day is not None else None
    if sheet is not None:
        lines += _sub(f"today's rule sheet — day {day.number}", "#ffd93d")
        if sheet.approved_domains:
            lines.append("[#00ff9f]✓  APPROVED DOMAINS[/]")
            lines += [f"     {d}" for d in sheet.approved_domains]
        if sheet.denied_domains:
            lines.append("[#ff5470]✗  DENIED DOMAINS[/]")
            lines += [f"     {d}" for d in sheet.denied_domains]
        if sheet.approved_affiliations:
            lines.append("[#00ff9f]✓  APPROVED AFFILIATIONS[/]")
            lines += [f"     {a}" for a in sheet.approved_affiliations]
        if sheet.denied_affiliations:
            lines.append("[#ff5470]✗  DENIED AFFILIATIONS[/]")
            lines += [f"     {a}" for a in sheet.denied_affiliations]

    # ── Reference lists (dynamic from ghostscan data) ──────────────────
    lines += _sub("email domains", "#7dd3c0")
    trusted    = " · ".join(sorted(tools_bridge._GS_TRUSTED_DOMAINS))
    disposable = " · ".join(sorted(tools_bridge._GS_SUSPICIOUS_DOMAINS))
    privacy    = " · ".join(sorted(tools_bridge._GS_PRIVACY_DOMAINS))
    lines += [
        f"[#00ff9f]✓  TRUSTED[/]   {trusted}",
        "             .edu · .ac.uk · .gov · .mil · verified employers",
        f"[#ff5470]✗  DISPOSABLE[/] {disposable}",
        "             [dim]→ plants DISPOSABLE_EMAIL — the fast-deny signal[/]",
        # #58, second location. tools_bridge stopped telling the player to flag
        # a privacy domain because DISPOSABLE_EMAIL is the only thing they could
        # flag, it is a different domain class, and board_accuracy_bonus scores
        # it as a false positive — the UI was instructing an action the scoring
        # model punishes. This copy still said it. Same bug, same fix: context,
        # not an instruction.
        f"[#ff8c42]?  PRIVACY[/]   {privacy}"
        "   [dim](legitimate — but leaves no identity trail)[/]",
    ]
    lines += _sub("affiliations", "#7dd3c0")
    orgs   = " · ".join(sorted(tools_bridge._GS_LEGIT_ORGS))
    forums = " · ".join(tools_bridge._GS_CRITICAL_FORUMS)
    lines += [
        f"[#00ff9f]✓  TRUSTED[/]   {orgs}",
        f"[#ff5470]✗  THREAT COMMUNITIES[/] {forums}",
        "[#ff8c42]?  UNVERIFIABLE[/] \"independent\" · \"freelance\" · \"self-employed\""
        "   [dim](needs corroboration)[/]",
    ]
    return "\n".join(lines)


# ─── Tab 2 — OSINT (Ghostscan) ───────────────────────────────────────────────


def build_osint_text(day: Day | None, unlocked_tools: set[str] | None = None) -> str:
    if not _tool_unlocked(ToolName.GHOSTSCAN, unlocked_tools):
        return _locked_tab_text(ToolName.GHOSTSCAN, "GHOSTSCAN — OSINT RECONNAISSANCE")
    gs = config.TOOL_COSTS["ghostscan"]
    gf = config.FILTER_COSTS["ghostscan"]
    lines: list[str] = []
    lines += _band("GHOSTSCAN — OSINT RECONNAISSANCE", "#6ad4ff")
    lines += [
        "  Ghostscan sweeps public platforms for the candidate's handle and",
        "  cross-references their claims. The report has two sections:",
        f"  [#6ad4ff]▌ PLATFORM SWEEP[/] (identity claims) and "
        "[#ff8c42]▌ BREACH DETECTION[/] (forums + dumps).",
        "  The filter re-renders the SAME report with annotations lit — it",
        "  never prints a second copy.",
    ]
    lines += _sub("investigation tiers", "#6ad4ff")
    lines += [
        f"  [#00ff9f]free[/]     passive identity check — email domain, affiliation, GitHub claim",
        f"  [#ffb454]run G[/]    platform sweep + account registry + forum lists   [dim]{gs} ⏱[/]",
        f"  [#c084fc]filter[/]   ▲ VIOLATION labels · forum tiers · breach confirm  [dim]+{gf} ⏱[/]",
    ]
    lines.append("")
    lines += violation_table(day, "OSINT")

    lines += _sub("two affiliation violations — don't confuse them", "#6ad4ff")
    lines += [
        f"  [#ff8c42]AFFILIATION_UNVERIFIED[/] [dim](dossier-tier, minor)[/]",
        "    An ordinary claimed org that the sweep can't corroborate — the",
        "    handle shows up with no org tag or a different one. Weak signal.",
        f"  [#ff8c42]AFFILIATION_MISMATCH[/] [dim](ghostscan-tier, major)[/]",
        "    An ELITE org claim (MIT CSAIL, Google Security…) that ghostscan",
        "    contradicts. This is deliberate camouflage — the filter run is",
        "    what confirms it. The Professional's claim checks out; a faker's",
        "    does not.",
    ]
    lines += _sub("sock puppets vs threat-forum match", "#6ad4ff")
    crit = " · ".join(tools_bridge._GS_CRITICAL_FORUMS)
    adv  = " · ".join(tools_bridge._GS_ADVISORY_FORUMS)
    lines += [
        "  The board item \"Sock puppet accounts\" IS the critical-forum handle",
        "  match: SOCK_PUPPET_ACCOUNTS fires when the candidate's handle sits",
        "  in a CRITICAL forum list. THREAT_FORUM_MATCH is its harder v2",
        "  sibling — a confirmed forum account tied to the identity (critical).",
        "",
        f"  [#ff5470]CRITICAL — immediate deny:[/]  {crit}",
        f"  [#ff8c42]ADVISORY — corroborate:[/]     {adv}",
    ]
    lines += _sub("breach databases panel (right column)", "#6ad4ff")
    lines += [
        "  Three states, driven by how much ⏱ you've spent:",
        "  [#6b7785]1. idle[/]         all entries dim — scan the lists yourself",
        "  [#ff8c42]2. highlighted[/]  after base recon — candidate email marked ►",
        "  [#ff5470]3. confirmed[/]    after filter — red ▲ BREACH_HIT label",
        "",
        "  [dim]The named database always matches the BREACH_MATCH entry in the",
        "  Hashcrack audit log — cross-reference the two for a LEAKED_PASSWORD",
        "  or CROSS_BREACH_REUSE case.[/]",
    ]
    return "\n".join(lines)


# ─── Tab 3 — CREDENTIALS (Hashcrack) ─────────────────────────────────────────


def build_creds_text(day: Day | None, unlocked_tools: set[str] | None = None) -> str:
    if not _tool_unlocked(ToolName.HASHCRACK, unlocked_tools):
        return _locked_tab_text(ToolName.HASHCRACK, "HASHCRACK — CREDENTIAL ANALYSIS")
    hc = config.TOOL_COSTS["hashcrack"]
    hf = config.FILTER_COSTS["hashcrack"]
    lines: list[str] = []
    lines += _band("HASHCRACK — CREDENTIAL ANALYSIS", "#c084fc")
    lines += [
        "  Every dossier now carries a PASSWORD field: the candidate's",
        "  credential in encrypted form, with its encryption strength shown",
        "  up front. Hashcrack attempts to crack it; on success the plaintext",
        "  replaces the encrypted value on every page.",
    ]
    lines += _sub("encryption strength — identify it from the raw hash", "#c084fc")
    lines += [
        "  With [#00ff9f]Cipher ID HUD[/] bought, the dossier auto-labels this",
        "  chip for you. Without it, the dossier shows only the raw hash —",
        "  use its LENGTH and SHAPE against this table to identify the tier",
        "  yourself:",
        "",
        "[#6b7785]  TIER     HASH SHAPE          CRACKABLE   MEANING[/]",
        f"[#1c2733]{'─' * _W}[/]",
        f"  [#00ff9f]{_fit('STRONG', 9)}[/]{_fit('bcrypt  $2b$…', 20)}"
        f"{_fit('never', 12)}always safe — no violation possible",
        f"  [#ffd93d]{_fit('MEDIUM', 9)}[/]{_fit('SHA256  64 hex', 20)}"
        f"{_fit('with effort', 12)}crack it, then judge the plaintext",
        f"  [#ff5470]{_fit('WEAK', 9)}[/]{_fit('MD5     32 hex', 20)}"
        f"{_fit('instantly', 12)}weak enc + weak plaintext = violation",
        f"[#1c2733]{'─' * _W}[/]",
        "  [dim]example — count the hex characters after the prefix:[/]",
        "  [#00ff9f]STRONG[/] [dim]$2b$12$KIXQ7c5s9j2mR8vN…[/]         [dim]($2b$ prefix — never a hash to crack)[/]",
        "  [#ffd93d]MEDIUM[/] [dim]a94a8fe5ccb19ba61c4c0873d391e987…[/] [dim](64 hex characters)[/]",
        "  [#ff5470]WEAK[/]   [dim]5f4dcc3b5aa765d61d8327deb882cf99[/]   [dim](32 hex characters)[/]",
        "",
        "  The tier is visible BEFORE spending any ⏱ — use it to decide",
        "  whether a crack is worth the hours. A bcrypt credential is a dead",
        "  end by design; an MD5 one begs to be cracked.",
    ]
    lines += _sub("judging a cracked plaintext", "#c084fc")
    lines += [
        "  The call is meant to be obvious:",
        "  [#ff5470]weak[/]    [b]password01[/] · dictionary words · dates · keyboard walks",
        "  [#00ff9f]strong[/]  [b]drawkcab16445$&[/] · long, mixed, symbol-laden strings",
        "",
        "  [#00ff9f]strong plaintext[/] → no concern, whatever the tier",
        "  [#ffd93d]weak plaintext + weak encryption[/] → WEAK_CREDENTIAL (minor —",
        "  flag it; not grounds to deny by itself)",
        "  [#ff5470]plaintext found in a breach corpus[/] → LEAKED_PASSWORD (critical)",
    ]
    lines += _sub("investigation tiers", "#c084fc")
    lines += [
        "  [#00ff9f]free[/]     shared audit log + the dossier hash tier (no ⏱)",
        f"  [#ffb454]run H[/]    highlight target · crack inline in the log      [dim]{hc} ⏱[/]",
        f"  [#c084fc]filter[/]   explicit ▲ violation labels + corpus analysis   [dim]+{hf} ⏱[/]",
    ]
    lines.append("")
    lines += violation_table(day, "CREDENTIAL")
    lines += _sub("composing with other tools", "#c084fc")
    lines += [
        "  A BREACH_MATCH line in the audit log names the same database the",
        "  Ghostscan breach panel highlights — the two surfaces corroborate",
        "  each other. Credential-stuffing bursts in this log are the same",
        "  events Logwatch resolves as CREDENTIAL_STUFFING; the claimed IP on",
        "  the dossier is your reference for spotting foreign login sources.",
    ]
    return "\n".join(lines)


# ─── Tab 4 — LOG ANALYSIS (Logwatch) ─────────────────────────────────────────


def build_logs_text(day: Day | None, unlocked_tools: set[str] | None = None) -> str:
    if not _tool_unlocked(ToolName.LOGWATCH, unlocked_tools):
        return _locked_tab_text(ToolName.LOGWATCH, "LOGWATCH — LOG ANALYSIS")
    lw = config.TOOL_COSTS["logwatch"]
    lf = config.FILTER_COSTS["logwatch"]
    lines: list[str] = []
    lines += _band("LOGWATCH — LOG ANALYSIS", "#ffb454")
    lines += [
        "  Every server keeps a structured event log: who connected, from",
        "  where, when, doing what. One entry is mundane; in aggregate they",
        "  expose attack patterns nothing else can. The free terminal shows",
        "  the raw shared day log; ⏱ buys detection and explicit labels.",
    ]
    lines += _sub("log entry format", "#ffb454")
    lines += [
        "  TIMESTAMP  IP_ADDRESS  EVENT_TYPE  USERNAME  RESOURCE",
        "",
        "  [dim]2024-03-15 02:14:07  185.220.101.45  AUTH_FAIL  admin  /ssh",
        "  2024-03-15 02:14:11  185.220.101.45  AUTH_SUCCESS  admin  /ssh[/]",
        "",
        "  [#6b7785]AUTH_SUCCESS/FAIL[/] logins · [#6b7785]FILE_ACCESS[/] reads/writes ·",
        "  [#6b7785]PRIV_ESCALATE[/] sudo/su · [#6b7785]API_CALL[/] external requests",
    ]
    lines += _sub("investigation tiers", "#ffb454")
    lines += [
        "  [#00ff9f]free[/]     raw day log — anomalies present but unlabelled",
        f"  [#ffb454]run L[/]    pattern detection — bursts, geo tags, after-hours  [dim]{lw} ⏱[/]",
        f"  [#c084fc]filter[/]   geo timeline + ▲ labels + low-and-slow correlation [dim]+{lf} ⏱[/]",
    ]
    lines.append("")
    lines += violation_table(day, "FORENSICS")
    lines += _sub("reading the patterns", "#ffb454")
    lines += [
        "  [#ff5470]BRUTE_FORCE_IN_LOG[/]   5+ AUTH_FAILs in ~60s on one account,",
        "                       usually ending in AUTH_SUCCESS",
        "  [#ff5470]CREDENTIAL_STUFFING[/]  one IP, MANY accounts, few tries each —",
        "                       a stolen combo list being replayed. Flaggable",
        "                       on the board like any other violation.",
        "  [#ff8c42]IMPOSSIBLE_TRAVEL[/]    two logins whose cities are physically",
        "                       unreachable in the elapsed time",
        "  [#ff8c42]INSIDER_BEHAVIOR[/]     sensitive FILE_ACCESS + PRIV_ESCALATE",
        "                       outside business hours",
        "  [#ffd93d]AFTER_HOURS_ACCESS[/]   ordinary activity at odd hours — minor;",
        "                       benign alone, meaningful in combination",
        "  [#ff5470]LOW_AND_SLOW[/]         deliberately sub-threshold — the base run",
        "                       will NOT flag it; only the filter's cross-day",
        "                       correlation summary surfaces it",
        "  [#ffd93d]CLAIMED_IP_MISMATCH[/]  free tier — AUTH_OK rows that diverge",
        "                       from the dossier's claimed IP are highlighted;",
        "                       corroborate before denying on this alone",
    ]
    lines += _sub("upgrades that change this page", "#ffb454")
    lines += [
        "  [#00ff9f]Log Analyzer HUD[/]  pre-colours suspicious lines in the free",
        "                    log — before any ⏱ is spent",
    ]
    return "\n".join(lines)


# ─── Tab 5 — STEGANOGRAPHY (Stegotool) ───────────────────────────────────────


def build_stego_text(day: Day | None, unlocked_tools: set[str] | None = None) -> str:
    if not _tool_unlocked(ToolName.STEGOTOOL, unlocked_tools):
        return _locked_tab_text(ToolName.STEGOTOOL, "STEGOTOOL — THE STAMP MINIGAME")
    cov = int(config.STEGO_STAMP_RESOLVE_COVERAGE * 100)
    lines: list[str] = []
    lines += _band("STEGOTOOL — THE STAMP MINIGAME", "#ff8cc8")
    lines += [
        "  LSB steganography hides data in the lowest bit of each colour",
        "  channel — invisible to the eye, but it disturbs natural pixel",
        "  noise. The image viewer renders the submitted image as a pixel",
        "  grid; you sweep it with a stamp to expose what the cells carry.",
    ]
    lines += _sub("controls & costs", "#ff8cc8")
    lines += [
        f"  [#00ff9f]X[/] / [#00ff9f]extract[/]  enter stamp mode on the image viewer",
        f"  [#00ff9f]arrows[/]       move the {config.STEGO_STAMP_W}×{config.STEGO_STAMP_H} stamp",
        f"  [#00ff9f]Space[/]        stamp — reveal the cells underneath   "
        f"[dim]{config.STEGO_STAMP_COST} ⏱ per stamp[/]",
        f"  [#00ff9f]F[/] / [#00ff9f]filter[/]   classify the payload TYPE by name    "
        f"[dim]+{config.STEGO_FILTER_COST} ⏱[/]",
        f"  [#00ff9f]Esc[/]          exit stamp mode",
        "",
        f"  Reveal ≥{cov}% of a hidden zone and its ▲ signature resolves.",
        "  Without the filter you read the stamp COLOUR yourself; with it the",
        "  payload type is named in the stamp log.",
    ]
    lines += _sub("signature colours", "#ff8cc8")
    lines += [
        "[#6b7785]  COLOUR    PAYLOAD              TEXTURE[/]",
        f"[#1c2733]{'─' * _W}[/]",
        f"  [#ff8c42]{_fit('AMBER', 10)}[/]{_fit('plaintext LSB', 21)}dense solid block",
        f"  [#ff5470]{_fit('CRIMSON', 10)}[/]{_fit('encrypted payload', 21)}mid-density, structured",
        f"  [#c084fc]{_fit('VIOLET', 10)}[/]{_fit('covert C2 channel', 21)}sparse scatter, wide zone",
        f"  [#00ff9f]{_fit('GREEN', 10)}[/]{_fit('clean region', 21)}no carrier under the stamp",
        f"[#1c2733]{'─' * _W}[/]",
        "",
        # #54: was "hot zones carry a faint blue tint before any ⏱ is spent",
        # which stopped being true when the free exact-zone tint was removed.
        "  [dim]Nothing is marked for you. Sweep the grid and stamp where the",
        "  noise looks wrong — carrier cells sit in clumped blocks, so a hit",
        "  tells you where to look next. The Spectral Lens upgrade tints a",
        "  rough area blue: close to the payload, never exactly on it.[/]",
    ]
    lines.append("")
    lines += violation_table(day, "STEGO")
    lines += _sub("background — how detection works", "#ff8cc8")
    lines += [
        "  [#ff5470]Chi-square[/]        LSB parity distribution — embedding randomises it",
        "  [#ff8c42]RS analysis[/]       regular/singular pixel-group ratio shifts",
        "  [#ff8c42]Autocorrelation[/]   neighbouring-pixel structure breaks under",
        "                    random bit injection",
        "",
        "  [dim]Encrypted payloads (CRIMSON) mark deliberate obfuscation —",
        "  a casual hidden note is amber; XOR-scrambled exfil is not casual.[/]",
    ]
    return "\n".join(lines)
