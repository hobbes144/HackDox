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
from gameengine.core import candidate_gen, content_loader, tools_bridge
from gameengine.core.models import Day, DiscrepancyKind, ToolName

# ─── Violation catalog — (group, kind, player-facing label) ─────────────────
# The Evidence Board (app.EVIDENCE_ITEMS) is built from this list, so board
# labels and rules-page tables always match.

VIOLATION_CATALOG: list[tuple[str, DiscrepancyKind, str]] = [
    # DOSSIER (no tool)
    # UNSALTED_STORAGE moved CREDENTIAL -> DOSSIER (Nick, 2026-09-15). It was
    # always DOSSIER-TIER — its evidence is the plaintext sitting on the
    # dossier, readable on day 1 with no tool — but it was GROUPED under
    # CREDENTIAL, which split the two apart and put the chip on a board tab the
    # player could not yet see the evidence for. Group and tier now agree.
    #
    # The separation that split cost is gone too: since the same date an
    # unsalted candidate no longer also carries WEAK_ENCRYPTION (there is no
    # algorithm there to be weak), so nothing about this kind lives on the
    # Hashcrack side any more.
    ("DOSSIER",     DiscrepancyKind.UNSALTED_STORAGE,       "Unsalted / plaintext storage"),
    ("DOSSIER",     DiscrepancyKind.HOSTILE_CHAT,           "Hostile chat"),
    ("DOSSIER",     DiscrepancyKind.AFFILIATION_NOT_STATED, "Affiliation not stated"),
    ("DOSSIER",     DiscrepancyKind.DISPOSABLE_EMAIL,       "Disposable email domain"),

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
    #
    # (2026-09-19 note: the UNSALTED_STORAGE half of the history below is
    # superseded — it moved on again to DOSSIER on 2026-09-15; see the DOSSIER
    # entry above. Kept for the WEAK_ENCRYPTION reasoning.)
    #
    # WEAK_ENCRYPTION and UNSALTED_STORAGE moved here from DOSSIER on
    # 2026-09-14, and they moved for two different reasons.
    #
    # WEAK_ENCRYPTION was simply out of date: the cipher-block rework retiered
    # it DOSSIER -> HASHCRACK in _SEVERITY_REVEAL, but its catalogue entry was
    # left behind — so the board filed it under a group whose tool no longer
    # revealed it. That is the drift this catalogue exists to prevent.
    #
    # UNSALTED_STORAGE is a deliberate split: its GROUP is CREDENTIAL (it is a
    # credential finding and belongs beside the other three), while its TIER
    # stays DOSSIER, because the honest answer to "which tool reveals it" is
    # still none — an unsalted value sits on the dossier in the clear, and that
    # exposure IS the violation.
    #
    # The split is safe because visible_catalog() gates each kind by its OWN
    # tool rather than by its group, so UNSALTED_STORAGE correctly shows from
    # day 1 even though the Hashcrack page does not exist until day 3. The one
    # gap that opens — a rules tab locked until day 3 documenting a kind
    # plantable on day 1 — is closed by build_creds_text's locked branch.
    ("CREDENTIAL",  DiscrepancyKind.WEAK_ENCRYPTION,        "Weak password encryption"),
    ("CREDENTIAL",  DiscrepancyKind.LEAKED_PASSWORD,        "Leaked password"),
    ("CREDENTIAL",  DiscrepancyKind.WEAK_CREDENTIAL,        "Weak credential"),
    ("CREDENTIAL",  DiscrepancyKind.CROSS_BREACH_REUSE,     "Cross-breach password reuse"),
    # STEGO (Stegotool)
    ("STEGO",       DiscrepancyKind.STEGO_PAYLOAD_PRESENT,  "Stego payload"),
    ("STEGO",       DiscrepancyKind.COVERT_C2_CHANNEL,      "Covert C2 channel"),
    ("STEGO",       DiscrepancyKind.ENCRYPTED_PAYLOAD,      "Encrypted covert payload"),
    # 2026-09-19: the carrier-SHAPE axis — what the payload is FOR, read off
    # the glyph its carrier cells form. Always rides on one of the three
    # colour kinds above; a conventional (blocky) carrier plants none of these.
    ("STEGO",       DiscrepancyKind.SIGNAL_COMMS_PAYLOAD,   "Signal comms payload"),
    ("STEGO",       DiscrepancyKind.RECURSIVE_PAYLOAD,      "Recursive payload"),
    ("STEGO",       DiscrepancyKind.HOSTILE_PAYLOAD,        "Hostile payload"),
]

# Engine-derived lookups — the dynamic backbone.
_SEVERITY: dict[DiscrepancyKind, str] = {
    kind: sev for kind, (_tool, sev) in candidate_gen._SEVERITY_REVEAL.items()
}
def _day_severity(kind: DiscrepancyKind, day: Day | None) -> str:
    """`kind`'s severity as of `day` — see candidate_gen._SEVERITY_BY_DAY.

    A couple of kinds escalate partway through the campaign (UNSALTED_STORAGE
    is minor until Hashcrack arrives on day 3, major after). The rules page has
    a Day in hand at every call site, so it can print the weight that actually
    applies today rather than the endgame one. With no day it falls back to the
    settled weight, which is never lower than the real answer.
    """
    return candidate_gen.severity_for(kind, day.number if day else None)


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
    day: Day | None = None,
) -> list[tuple[str, DiscrepancyKind, str]]:
    """VIOLATION_CATALOG filtered to kinds the player can currently observe,
    ordered by GROUP_ORDER and then by severity ascending (minor -> major ->
    critical) within each group so the board reads calm-to-alarming.

    Used by the Evidence Board (app.py) so its single scrollable list only
    ever offers violations the player could actually have caught, in the
    same order it has always displayed them in.

    `day`, when given, additionally drops a kind nothing seen SO FAR in the
    campaign could ever plant — the CUMULATIVE union, across every day from 1
    through `day.number`, of the day's `allowed_violations` whitelist and
    whichever archetypes were eligible for it that day (see
    `content_loader.kinds_discovered_through`). This is a NARROWER, separate
    question from `_tool_unlocked`: a tool can be fully unlocked and a kind
    still be unreachable so far because nothing in any day's lineup up to now
    has been able to carry it (e.g. a Stego carrier-shape kind before any
    shape-eligible archetype has ever been scheduled).

    Deliberately cumulative, not single-day: a kind that was reachable on an
    earlier day stays reachable even on a later day whose own scripted
    `archetype_mix` wouldn't roll it — once something is a thing to check
    for, it stays a thing to check for, rather than flickering off the board
    because today's script didn't happen to draw the archetype that carries
    it. `day=None` (tests, the rules-lab preview, and the module-level
    `EVIDENCE_ITEMS` catalog at import time) skips this check and shows
    everything the tool-unlock gate alone would allow, matching
    `_tool_unlocked`'s own `unlocked_tools=None` behaviour.
    """
    # unlocked_tools=None is this module's established "no gating context"
    # signal (see _tool_unlocked's docstring) — honour it for the content
    # filter too, not just the tool filter, so a caller that explicitly asked
    # for the unfiltered catalog (tests, the rules-lab preview) still gets it
    # even when it also happens to pass a real `day`.
    reachable = (content_loader.kinds_discovered_through(day.number)
                 if day is not None and unlocked_tools is not None else None)
    items = [(g, k, lbl) for g, k, lbl in VIOLATION_CATALOG
             if _tool_unlocked(_TOOL.get(k), unlocked_tools)
             and (reachable is None or k in reachable)]
    items.sort(key=lambda it: (
        GROUP_ORDER.index(it[0]),
        _SEV_RANK.get(_SEVERITY.get(it[1], "minor"), 0),
    ))
    return items


# ─── Evidence-board clusters — unnamed groupings INSIDE a group ─────────────
#
# The Evidence Board lays its violations out as clickable chips. A flat list of
# 27 chips under five headers is still a wall, so each group is subdivided into
# small clusters of violations that tend to travel together, and the board
# separates them with whitespace alone.
#
# The clusters are NAMED, and that reverses an earlier call. They shipped
# unnamed first, on the reasoning that a caption would add a competing header
# level to a panel already carrying a group header, a severity colour, a state
# marker and a post-verdict grade. Playtesting said otherwise: without names,
# players read the whitespace as decoration and learned nothing about how the
# violations relate, so they fell back to walking the whole list with the arrow
# keys — the exact behaviour the grouping existed to replace. A name is a claim,
# but an unlabelled grouping turned out to be a claim nobody could read.
#
# The names are still not a taxonomy the game scores against, and the
# associations stay generous: THREAT_FORUM_MATCH sits with BREACH_HIT under
# "Unsafe Account" because both say "this person has already surfaced somewhere
# they shouldn't have", not because the engine relates them.
#
# Ordering contract: clusters are declared in the order they render, and their
# groups must appear in GROUP_ORDER order and contiguously — the board draws
# one header per group and would print a group twice otherwise. The guards
# below enforce that, plus exactly-once coverage of every catalogued kind, in
# the same spirit as the #56 catalogue guards above.

VIOLATION_CLUSTERS: list[
    tuple[str, str, str, tuple[DiscrepancyKind, ...]]
] = [
    # (group, cluster id, PLAYER-FACING subcategory name, kinds)
    #
    # DOSSIER — free evidence, read straight off the intake form and the chat.
    ("DOSSIER",    "dossier-identity", "Identity Confirmation", (
        DiscrepancyKind.AFFILIATION_NOT_STATED,
        DiscrepancyKind.DISPOSABLE_EMAIL)),
    # "Personal" is the candidate's own conduct, as opposed to the identity
    # claims in the cluster above: how they spoke to you, and how they kept
    # their own credential. UNSALTED_STORAGE joined it 2026-09-15 with the
    # group move — storing your password in the clear is a thing this person
    # did, not a property of the site. Reordered ahead of HOSTILE_CHAT
    # 2026-09-21 (Nick) — row position is now authored display order (both
    # the board and the Rules page render this tuple's order verbatim), not
    # just cluster membership.
    ("DOSSIER",    "dossier-personal", "Personal", (
        DiscrepancyKind.UNSALTED_STORAGE,
        DiscrepancyKind.HOSTILE_CHAT)),
    # OSINT / Ghostscan — the claim, the fabrication, the trace left elsewhere.
    ("OSINT",      "osint-association", "Association Confirmation", (
        DiscrepancyKind.MISSING_PUBLIC_PROFILE,
        DiscrepancyKind.AFFILIATION_UNLISTED,
        DiscrepancyKind.AFFILIATION_MISMATCH)),
    ("OSINT",      "osint-false-identity", "False Identity", (
        DiscrepancyKind.TYPOSQUAT_HANDLE,
        DiscrepancyKind.SOCK_PUPPET_ACCOUNTS,
        DiscrepancyKind.BURNER_IDENTITY)),
    ("OSINT",      "osint-unsafe-account", "Unsafe Account", (
        DiscrepancyKind.BREACH_HIT,
        DiscrepancyKind.EMAIL_GITHUB_MISMATCH,
        DiscrepancyKind.THREAT_FORUM_MATCH)),
    # CREDENTIAL / Hashcrack. Split in two on 2026-09-14 when the old
    # "dossier-password" cluster emptied into this group: HOW the credential is
    # stored is a different question from WHETHER it has already been exposed,
    # and the player checks them at different moments — storage off the block's
    # header, exposure off the recovered plaintext.
    # 2026-09-15: UNSALTED_STORAGE left for DOSSIER/Personal and
    # WEAK_CREDENTIAL arrived from cred-exposure, leaving a clean 2/2 split.
    #
    # The line between them is now "what the credential IS" versus "where it
    # has already been". A weak algorithm and a weak password are both
    # properties of the artifact in front of you, readable off one cracked
    # block; a leak and a reuse are facts about the outside world, and both
    # need the breach corpus to establish. That also matches how they are
    # found: the first pair comes out of the cipher block alone, the second
    # pair is Hashcrack corroborated by Ghostscan.
    ("CREDENTIAL", "cred-storage", "Credential Storage", (
        DiscrepancyKind.WEAK_ENCRYPTION,
        DiscrepancyKind.WEAK_CREDENTIAL)),
    ("CREDENTIAL", "cred-exposure", "Credential Exposure", (
        DiscrepancyKind.LEAKED_PASSWORD,
        DiscrepancyKind.CROSS_BREACH_REUSE)),
    # FORENSICS / Logwatch — when, where from, and the shape of the attack.
    ("FORENSICS",  "forensics-timing", "Access Timing", (
        DiscrepancyKind.AFTER_HOURS_ACCESS,
        DiscrepancyKind.IMPOSSIBLE_TRAVEL)),
    ("FORENSICS",  "forensics-source", "Source Verification", (
        DiscrepancyKind.CLAIMED_IP_MISMATCH,
        DiscrepancyKind.INSIDER_BEHAVIOR)),
    ("FORENSICS",  "forensics-attack", "Attack Signature", (
        DiscrepancyKind.BRUTE_FORCE_IN_LOG,
        DiscrepancyKind.CREDENTIAL_STUFFING,
        DiscrepancyKind.LOW_AND_SLOW)),
    # STEGO / Stegotool.
    ("STEGO",      "stego-payload", "Payload Detection", (
        DiscrepancyKind.STEGO_PAYLOAD_PRESENT,
        DiscrepancyKind.COVERT_C2_CHANNEL,
        DiscrepancyKind.ENCRYPTED_PAYLOAD)),
    # 2026-09-19: the second stego axis gets its own row rather than joining
    # the colour row above. The two are read differently (a colour off any one
    # revealed cell, a glyph off the whole revealed zone) and a carrier carries
    # at most one of EACH, so one chip per row is the player's whole answer.
    # Authored calm-to-alarming: SIGNAL_COMMS is major, the other two critical.
    ("STEGO",      "stego-operation", "Payload Operation", (
        DiscrepancyKind.SIGNAL_COMMS_PAYLOAD,
        DiscrepancyKind.RECURSIVE_PAYLOAD,
        DiscrepancyKind.HOSTILE_PAYLOAD)),
]

# ── Cluster integrity guards ────────────────────────────────────────────────
# Same failure mode the #56 catalogue guards protect against: a kind that is
# missing here would silently vanish from the board (the board renders clusters,
# not the flat catalog), and a kind listed twice would give the player two chips
# that toggle the same evidence. Both are invisible at a glance on a 27-row
# panel, so they are import-time errors rather than something to notice in play.

_CLUSTER_OF: dict[DiscrepancyKind, str] = {}
for _grp, _cid, _clabel, _kinds in VIOLATION_CLUSTERS:
    if not _kinds:
        raise AssertionError(f"empty evidence cluster: {_cid!r}")
    for _k in _kinds:
        if _k in _CLUSTER_OF:
            raise AssertionError(
                f"{_k.name} appears in two evidence clusters: "
                f"{_CLUSTER_OF[_k]!r} and {_cid!r}")
        _CLUSTER_OF[_k] = _cid

_UNCLUSTERED = sorted(k.name for _g, k, _lbl in VIOLATION_CATALOG
                      if k not in _CLUSTER_OF)
if _UNCLUSTERED:
    raise AssertionError(
        f"DiscrepancyKinds missing from VIOLATION_CLUSTERS: {_UNCLUSTERED}. "
        f"A kind absent here never renders on the Evidence Board at all.")

_CLUSTER_IDS = [cid for _g, cid, _l, _k in VIOLATION_CLUSTERS]
if len(set(_CLUSTER_IDS)) != len(_CLUSTER_IDS):
    raise AssertionError("duplicate evidence cluster ids")

# A cluster's declared group must match the group its kinds are catalogued
# under, or the board would draw a chip beneath the wrong header — and, because
# progressive unlock filters by the kind's revealing tool, under a header that
# can be locked while the chip is not.
_GROUP_OF: dict[DiscrepancyKind, str] = {k: g for g, k, _lbl in VIOLATION_CATALOG}
for _grp, _cid, _clabel, _kinds in VIOLATION_CLUSTERS:
    if not _clabel.strip():
        raise AssertionError(f"evidence cluster {_cid!r} has no player-facing name")
    _wrong = sorted(k.name for k in _kinds if _GROUP_OF[k] != _grp)
    if _wrong:
        raise AssertionError(
            f"cluster {_cid!r} is declared under {_grp} but catalogues "
            f"{_wrong} elsewhere")

# Groups must appear in GROUP_ORDER order and contiguously — the board emits
# one header per group as it walks this list and would repeat one otherwise.
_CLUSTER_GROUP_RUNS = [g for i, (g, _c, _l, _k) in enumerate(VIOLATION_CLUSTERS)
                       if i == 0 or VIOLATION_CLUSTERS[i - 1][0] != g]
if _CLUSTER_GROUP_RUNS != [g for g in GROUP_ORDER if g in _CLUSTER_GROUP_RUNS]:
    raise AssertionError(
        f"VIOLATION_CLUSTERS group runs {_CLUSTER_GROUP_RUNS} are not "
        f"GROUP_ORDER {GROUP_ORDER} in order and contiguous")


def clustered_catalog(
    unlocked_tools: set[str] | None,
    day: Day | None = None,
) -> list[tuple[str, str, str, list[tuple[str, DiscrepancyKind, str]]]]:
    """`(group, cluster_id, subcategory name, items)` for the board's layout.

    Same filtering rule as `visible_catalog` — a kind whose revealing tool is
    still locked is dropped, because a candidate cannot carry it yet. `day`
    applies the same additional content-reachability filter `visible_catalog`
    documents (the day's `allowed_violations` whitelist and its
    `archetype_mix`) — pass it and the two surfaces agree by construction.

    Order inside a cluster is AUTHORED, not sorted. These are hand-laid rows
    that Nick arranged by hand, and re-sorting them would quietly rearrange a
    layout that was chosen deliberately. The authored rows happen to run
    calm-to-alarming today, and a test asserts they still do — so a future
    re-tier (#51 and #53 have both moved a violation's severity before) fails
    loudly and asks for the row to be re-laid, instead of silently reshuffling
    the board out from under the player's spatial memory.

    Clusters that filter down to nothing are omitted entirely rather than
    rendered as a gap, so an early-campaign board has no mystery whitespace
    where a locked violation used to sit.

    This is a SECOND ordering of the same catalog, not a replacement:
    `visible_catalog` (group, then severity) still drives the
    flagged-evidence summary strip. `violation_table` (the Rules-page tables)
    now walks THIS SAME cluster order rather than sorting by severity, so the
    board and the Rules page agree on position too, not just membership — a
    row's spot in its group never moves, and only its colour changes as a
    rule's severity steps up or down. Both surfaces derive from
    VIOLATION_CATALOG and both filter through `_tool_unlocked`, so they can
    disagree about ORDER from `visible_catalog` but never about membership.
    """
    # unlocked_tools=None is this module's established "no gating context"
    # signal (see _tool_unlocked's docstring) — honour it for the content
    # filter too, not just the tool filter, so a caller that explicitly asked
    # for the unfiltered catalog (tests, the rules-lab preview) still gets it
    # even when it also happens to pass a real `day`.
    reachable = (content_loader.kinds_discovered_through(day.number)
                 if day is not None and unlocked_tools is not None else None)
    catalog = {k: (g, lbl) for g, k, lbl in VIOLATION_CATALOG}
    out: list[tuple[str, str, str, list[tuple[str, DiscrepancyKind, str]]]] = []
    for group, cluster_id, cluster_label, kinds in VIOLATION_CLUSTERS:
        items = [(group, k, catalog[k][1]) for k in kinds
                 if _tool_unlocked(_TOOL.get(k), unlocked_tools)
                 and (reachable is None or k in reachable)]
        if not items:
            continue
        out.append((group, cluster_id, cluster_label, items))
    return out


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
        "  Foreman grants it — check back once it's live.[/]",
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
    DiscrepancyKind.WEAK_ENCRYPTION:        "free — the cipher block states its digest shape on arrival (32 hex = MD5; named for you with Cipher ID HUD). Decrypting it recovers a perfectly good password — the algorithm is the problem, not the value",
    DiscrepancyKind.UNSALTED_STORAGE:       "free — the ⚠ UNSALTED marker on the dossier shows the stored password in the clear, and the cipher block arrives already decrypted; no window, no dial, nothing to spend",
    DiscrepancyKind.EMAIL_GITHUB_MISMATCH:  "base recon shows commit email · filter highlights the mismatch",
    DiscrepancyKind.BREACH_HIT:             "email in a breach panel corpus — exposure, not misconduct; chase it with Hashcrack",
    DiscrepancyKind.SOCK_PUPPET_ACCOUNTS:   "handle on a CRITICAL forum — blended in base run, filter labels it",
    DiscrepancyKind.AFFILIATION_MISMATCH:   "GHOSTSCAN — sweep shows a DIFFERENT org than the dossier claims",
    DiscrepancyKind.AFFILIATION_UNLISTED:   "GHOSTSCAN — profiles exist but carry no org tag at all",
    DiscrepancyKind.BURNER_IDENTITY:        "account registry: creation dates clustered within days — filter labels",
    DiscrepancyKind.THREAT_FORUM_MATCH:     "handle in the threat-forum list — filter reveals with [CRITICAL] tag",
    DiscrepancyKind.TYPOSQUAT_HANDLE:       "free cue on identity check · filter confirms the lookalike",
    DiscrepancyKind.BRUTE_FORCE_IN_LOG:     "free report raises an UNCLASSIFIED authentication anomaly · the auth log shows ONE account hammered · filter labels it",
    DiscrepancyKind.IMPOSSIBLE_TRAVEL:      "the origin map + legend give each city change's distance and time — judge the speed yourself (honest people fly too) · Threat Triage HUD flags it · filter adds the km/h",
    DiscrepancyKind.INSIDER_BEHAVIOR:       "free report shows off-shift activity + sensitive/privileged COUNTS · the auth log shows the paths and the sudo · filter labels it",
    DiscrepancyKind.CREDENTIAL_STUFFING:    "free report raises the SAME unclassified anomaly as brute force · the auth log shows ONE source failing on MANY accounts · filter names it",
    DiscrepancyKind.AFTER_HOURS_ACCESS:     "free report's off-shift note; the auth log shows routine paths — benign alone (minor)",
    DiscrepancyKind.LOW_AND_SLOW:           "never trips the report's alert — failures bar past its tick, scattered × on the FAIL lane · filter correlates it",
    DiscrepancyKind.CLAIMED_IP_MISMATCH:    "free report: the claimed IP never appears among the login origins — corroborate before denying",
    DiscrepancyKind.LEAKED_PASSWORD:        "align the cipher block and the recovery readout names the corpus the plaintext was dumped in; the Ghostscan breach panel corroborates it",
    DiscrepancyKind.WEAK_CREDENTIAL:        "the recovered plaintext is a dictionary word or keyboard walk — judge it yourself, or buy Crack Verdict Analyzer to have it called",
    DiscrepancyKind.CROSS_BREACH_REUSE:     "the recovery readout names TWO corpora holding the same plaintext — the breach panel lists both",
    DiscrepancyKind.STEGO_PAYLOAD_PRESENT:  "stamp the tinted zone — AMBER cells; ≥60% coverage resolves ▲",

    DiscrepancyKind.COVERT_C2_CHANNEL:      "VIOLET sparse scatter over a wide zone — resolve by stamping",
    DiscrepancyKind.ENCRYPTED_PAYLOAD:      "CRIMSON mid-density cells — filter (F) names the payload type",
    DiscrepancyKind.SIGNAL_COMMS_PAYLOAD:   "carrier cells form a CROSS (+ or X) — read the glyph, or filter (F) names it",
    DiscrepancyKind.RECURSIVE_PAYLOAD:      "carrier cells form a closed, HOLLOW ring or diamond — filter (F) names it",
    DiscrepancyKind.HOSTILE_PAYLOAD:        "carrier cells form 2-4 PARALLEL strokes that never touch — filter (F) names it",
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
        "12:40  AUTH_FAIL  91.219.4.8  j.torres93@corp.net  (no report alert — hours apart)",
    ),
    DiscrepancyKind.CLAIMED_IP_MISMATCH: (
        "CLAIMS   Boston, US  via 10.0.4.22",
        "ORIGINS  ✗ claimed IP 10.0.4.22 never seen · ✗ Frankfurt, DE  4 logins",
        "the free Activity Report shows it — no ⏱ needed to see it",
    ),
    DiscrepancyKind.LEAKED_PASSWORD: (
        'CRACKED:  "dragon2019"',
        'RECOVERED — found verbatim in corpus "CollectionX_2019"',
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
    DiscrepancyKind.SIGNAL_COMMS_PAYLOAD: (
        "carrier cells run as two bars — one down, one across — or an X",
        "glyph:  strokes cross at a single point",
        "filtered: ▲ SIGNAL_COMMS_PAYLOAD beside the colour signature",
    ),
    DiscrepancyKind.RECURSIVE_PAYLOAD: (
        "carrier cells trace a loop; stamping the middle turns up nothing",
        "glyph:  closed loop, hollow interior",
        "filtered: ▲ RECURSIVE_PAYLOAD beside the colour signature",
    ),
    DiscrepancyKind.HOSTILE_PAYLOAD: (
        "three matching strokes, evenly spaced, a clear gap between each",
        "glyph:  parallel strokes, no intersections",
        "filtered: ▲ HOSTILE_PAYLOAD beside the colour signature",
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


def violation_table(day: Day | None, group: str,
                    unlocked_tools: set[str] | None = None) -> list[str]:
    """The templated violations table for one board group.

    Columns: violation (exact enum value) · severity · revealing surface ·
    today's rule status. A dim second line per row carries the trigger and
    how to catch it.

    Rows are grouped under the same player-facing subcategory headers the
    Evidence Board uses (`VIOLATION_CLUSTERS`), in the same AUTHORED order —
    "dynamic colour, static position" (Nick, 2026-09-21): a row's spot in its
    group never moves, so the player builds spatial memory of the table the
    same way they do the board, and can tell a violation was RE-TIERED (its
    colour changed) from one that simply moved (it didn't — nothing here
    ever reorders on severity). Only `_day_severity`'s colour is live; the
    subcategory headers and each row's position within one are exactly
    `clustered_catalog`'s layout, filtered down to this `group`.

    `unlocked_tools` filters rows to kinds the player can actually observe
    today, exactly as visible_catalog() does for the evidence board — pass it
    and the two surfaces agree by construction. It defaults to None (show
    everything) so every existing caller inside an already-unlocked tab is
    unaffected; the one caller that needs it is build_creds_text's LOCKED
    branch, which documents the dossier-tier credential kind while the tool
    itself is still days away.

    `day` (already a required positional parameter here) additionally drops
    a kind nothing seen so far in the campaign could ever plant — see
    visible_catalog's docstring for the exact rule (the cumulative
    `allowed_violations` whitelist / `archetype_mix` union via
    `content_loader.kinds_discovered_through`). This was previously
    unchecked here even though `day` was already in hand, which is how a
    violation could sit in this table (and its matching Evidence Board chip)
    on a day nothing generated could actually carry it.
    """
    # unlocked_tools=None is this module's established "no gating context"
    # signal (see _tool_unlocked's docstring) — honour it for the content
    # filter too, not just the tool filter, so a caller that explicitly asked
    # for the unfiltered catalog (tests, the rules-lab preview) still gets it
    # even when it also happens to pass a real `day`.
    reachable = (content_loader.kinds_discovered_through(day.number)
                 if day is not None and unlocked_tools is not None else None)
    catalog = {k: lbl for g, k, lbl in VIOLATION_CATALOG if g == group}
    accent = GROUP_ACCENT.get(group, "#7dd3c0")
    out = [
        f"[{accent}][b]▎ VIOLATIONS — {group}[/][/]",
        "[#6b7785]  VIOLATION                 SEVERITY  SOURCE     TODAY[/]",
        f"[#1c2733]{'─' * _W}[/]",
    ]
    for cgroup, _cid, cluster_label, kinds in VIOLATION_CLUSTERS:
        if cgroup != group:
            continue
        rows = [(k, catalog[k]) for k in kinds
                if _tool_unlocked(_TOOL.get(k), unlocked_tools)
                and (reachable is None or k in reachable)]
        if not rows:
            continue
        out.append(f"[#6b7785]  {cluster_label}[/]")
        for kind, _lbl in rows:
            sev  = _day_severity(kind, day)
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
            (f"  {_fit('minimum correct admits', 28)}[#ffd93d]{q.min_correct_admits:<12}[/]"
            f"[#ff8c42]POOR day rating[/]"),
            (f"  {_fit('maximum false admits', 28)}[#ffd93d]{q.max_false_admits:<12}[/]"
            f"[#ff5470]FAILED day rating[/]"),
            f"[#1c2733]{'─' * _W}[/]",
        ]
    lines += [
        "",
        "[#6b7785]  RATING      HOW YOU EARN IT[/]",
        f"[#1c2733]{'─' * _W}[/]",
        f"  [#00ff9f]{_fit('EXCELLENT', 12)}[/]quotas met and zero wrong verdicts",
        f"  [#7dd3c0]{_fit('PASSING', 12)}[/]quotas met",
        f"  [#ff8c42]{_fit('POOR', 12)}[/]too few correct admits",
        (f"  [#ff5470]{_fit('FAILED', 12)}[/]false admits over quota, or Site Health "
        "below the loss line"),
        f"[#1c2733]{'─' * _W}[/]",
    ]

    # ── Computing hours (issue #27) ────────────────────────────────────
    lines.append("")
    lines += _band("COMPUTING HOURS (⏱) — FINITE DAILY BUDGET", "#ffb454")
    base = config.STARTING_COMPUTE
    d_no = day.number if day else 1
    _endless = config.is_endless_day(d_no)
    today_budget = config.daily_compute_budget(d_no, base)
    lines += [
        "  A fixed ⏱ pool is granted at the start of every shift. It is spent",
        "  ONLY on tools, filters, and stamps — verdicts never grant ⏱, and",
        "  leftover hours are discarded at end of day (no carry-over).",
        "  Running out mid-day disables tools for the rest of the shift;",
        "  there is no other penalty. Ration the pool across all candidates.",
        "",
        (f"  [#6b7785]base budget[/]      [#ffb454]{base} ⏱[/]  "
        f"[dim](generous early, tighter as the work grows · raise it in the shop)[/]"),
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
        (f"  [#ff5470]▼ below {config.SITE_HEALTH_LOSS_THRESHOLD:.0f}%[/]"
        "   at end of day — HackDox is lost (game over)"),
        (f"  [#00ff9f]▲ above {config.SITE_HEALTH_REWARD_THRESHOLD:.0f}%[/]"
        f"   at end of day — HackDollar$ bonus (max {config.HACKDOLLAR_SITE_HEALTH_BONUS})"),
    ]

    # ── HackDollar$ + credits + upgrades ───────────────────────────────
    lines.append("")
    lines += _band("HACKDOLLAR$ · CREDITS · UPGRADES", "#00ff9f")
    lines += [
        "  HackDollar$ (HD$) is the persistent between-day currency. Earned on",
        (f"  correct verdicts (today [#00ff9f]+{config.DAY_REWARD_PAYOUT(d_no, True)}[/] admit · "
        f"[#00ff9f]+{config.DAY_REWARD_PAYOUT(d_no, False)}[/] deny) plus the evidence-board"),
        "  bonus and the end-of-day health bonus. Spent only in the night shop.",
        "  [#ffd93d]The verdict rate shrinks every couple of days while the board bonus[/]",
        "  [#ffd93d]grows — later on, a well-kept board is most of your pay.[/]",
        "",
        "  [#c084fc]HackDox Credits[/] — type [b]reveal[/] to spend one and see the",
        "  current candidate's ground truth (correct verdict + planted",
        (f"  violations, no evidence trail). Max "
        f"{config.ENDLESS_HACKDOX_CREDIT_MAX if _endless else config.HACKDOX_CREDIT_MAX} "
        f"slots · {config.SHOP_PRICE_CREDIT} HD$ each."),
        (f"  [#ffb454]⏱ capacity[/] — +{config.COMPUTE_CAPACITY_STEP} base budget "
        f"per purchase · {config.SHOP_PRICE_CAPACITY} HD$"
        + (f", +{config.SHOP_CAPACITY_PRICE_STEP} each time." if _endless else ".")),
    ]
    if _endless:
        # #7: the Endless-only rules, in the same reference the player
        # already reads for everything else.
        lines += [
            (f"  [#7dd3c0]Site Patch[/] — +{config.SITE_PATCH_HEALTH:.0f}% Site Health · "
             f"{config.SHOP_PRICE_SITE_PATCH} HD$, +{config.SHOP_SITE_PATCH_PRICE_STEP} each time."),
            (f"  [#ff8c42]Maintenance[/] — each Endless run, "
             f"{config.ENDLESS_MAINTENANCE_COUNT} upgrades are out of"),
            "  service for the whole run (marked MAINT in the shop).",
            (f"  [#ffd93d]Endless shop prices[/] — upgrades cost "
             f"{config.ENDLESS_UPGRADE_PRICE_MULT:g}× the catalog prices listed below."),
            "",
        ]
        lines += _band("ENDLESS — HOW A RUN ENDS", "#ff5470")
        lines += [
            (f"  Your accuracy over the last {config.ENDLESS_ACCURACY_WINDOW} shifts must stay at "
             f"or above [b]{config.ENDLESS_ACCURACY_THRESHOLD:.0%}[/]."),
            (f"  It starts counting once {config.ENDLESS_ACCURACY_WINDOW} shifts are on the books. "
             "Site Health"),
            (f"  under {config.SITE_HEALTH_LOSS_THRESHOLD:.0f}% ends the run too. The work gets "
             "harder for a"),
            "  while, then levels off — it never becomes impossible.",
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
        (f"  [#00ff9f]bonus = {config.board_bonus_max(d_no)} HD$ × hits ÷ "
        "(hits + false flags + misses)[/]   [dim](on correct verdicts)[/]"),
        (f"  [dim]today's ceiling {config.board_bonus_max(d_no)} HD$ — it grows over the run, "
         f"up to {config.BOARD_BONUS_CAP}[/]"),
        "",
        "  [#ff8c42]Do NOT flag everything[/] — every false flag divides the bonus",
        (f"  down. A clean candidate with an empty board pays "
         f"{config.BOARD_CLEAN_FRACTION:.0%} of it — the money is"),
        "  in FINDING violations. Flag what the evidence supports, rule out the rest.",
    ]

    # ── Alignment ──────────────────────────────────────────────────────
    lines.append("")
    lines += _band("ALIGNMENT — THE MORAL AXIS", "#c084fc")
    lines += [
        (f"  A hidden bar from {config.ALIGNMENT_MIN} (Dark Web) to "
        f"+{config.ALIGNMENT_MAX} (White Hat), shown as dots in the status bar."),
        "  Most candidates carry no moral weight; two kinds do:",
        "",
        "  [#ff5470]Dark Web operatives[/]  admit → drift Dark Web · deny → drift White Hat",
        "  [#00ff9f]The White Hat[/]        admit → drift White Hat · deny → drift Dark Web",
        "",
        "  These verdicts shift alignment REGARDLESS of rule-correctness — the",
        "  rules may demand one thing and your conscience another. Alignment",
        "  steers the Foreman's tone and the campaign's ending.",
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

    # ── The password field ──────────────────────────────────────────────
    # The dossier no longer labels encryption strength at all — establishing
    # the algorithm is the cipher block's job, and the full tier table lives on
    # the CREDENTIALS tab. What stays here is only what the dossier itself
    # shows: the raw hash, and the one credential violation that needs no tool.
    lines += _sub("the password field", "#7dd3c0")
    lines += [
        "  The dossier prints the submitted credential as a [b]raw hash[/] and",
        "  says nothing about how strong it is. That is deliberate: the",
        "  algorithm is something you establish on the Hashcrack page, not",
        "  something handed to you here.",
        "             [dim]e.g. 5f4dcc3b5aa765d61d8327deb882cf99…[/]",
        "",
        "  Count its characters (or spot a [b]$2b$[/] prefix) and the CREDENTIALS",
        "  tab's table tells you which algorithm you are looking at, whether it",
        "  is worth opening, and what it costs to be wrong.",
        "",
        "  [#ff5470]⚠ UNSALTED[/]  the one exception, and the only credential",
        "             problem visible without a tool. Storage has no salt at",
        "             all, so the Password entry just IS the plaintext, printed",
        "             in the clear — there is no hash, and nothing to crack.",
        "             e.g. [dim]monkey123  ⚠ UNSALTED[/]",
        "",
        # Every tag opens and closes on its own line: the rules page is
        # validated per line (a malformed span is far easier to find when the
        # failure names one line), so a [dim] that spans several lines is a
        # markup error even though the joined text parses fine.
        "             [dim]Because there is no algorithm involved, an unsalted[/]",
        "             [dim]credential never also carries WEAK_ENCRYPTION — that[/]",
        "             [dim]violation is about which algorithm was used, and this[/]",
        "             [dim]one used none.[/]",
        "",
        (f"             [dim]UNSALTED_STORAGE files as a note until Day "
         f"{config.TOOL_UNLOCK_DAY['hashcrack']}, when[/]"),
        "             [dim]Hashcrack arrives and credential hygiene starts being[/]",
        "             [dim]judged properly — from then it is a major violation.[/]",
    ]
    lines.append("")
    lines += violation_table(day, "DOSSIER")

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
        (f"[#ff8c42]?  PRIVACY[/]   {privacy}"
        "   [dim](legitimate — but leaves no identity trail)[/]"),
    ]
    lines += _sub("affiliations", "#7dd3c0")
    # 2026-09-24: the elite orgs are made-up harbour organisations now
    # (VOICE_GUIDE.md §5), so a player can no longer recognise them from the
    # real world — this is where they learn the list. Derived from the same
    # bank the generator and the sweep use.
    elite  = " · ".join(sorted(tools_bridge._GS_ELITE_ORGS))
    orgs   = " · ".join(sorted(tools_bridge._GS_LEGIT_ORGS))
    forums = " · ".join(tools_bridge._GS_CRITICAL_FORUMS)
    lines += [
        f"[#00ff9f]✓  ELITE[/]     {elite}",
        "             [dim]→ can't be faked: the sweep always confirms these[/]",
        f"[#00ff9f]✓  TRUSTED[/]   {orgs}",
        f"[#ff5470]✗  THREAT COMMUNITIES[/] {forums}",
        ("[#ff8c42]?  UNVERIFIABLE[/] \"independent\" · \"freelance\" · \"self-employed\""
        "   [dim](needs corroboration)[/]"),
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
        ("  [#6ad4ff]▌ PLATFORM SWEEP[/] (identity claims) and "
        "[#ff8c42]▌ BREACH DETECTION[/] (forums + dumps)."),
        "  The filter re-renders the SAME report with annotations lit — it",
        "  never prints a second copy.",
    ]
    lines += _sub("investigation tiers", "#6ad4ff")
    lines += [
        "  [#00ff9f]free[/]     passive identity check — email domain, affiliation, GitHub claim",
        f"  [#ffb454]run G[/]    platform sweep + account registry + forum lists   [dim]{gs} ⏱[/]",
        f"  [#c084fc]filter[/]   ▲ VIOLATION labels · forum tiers · breach confirm  [dim]+{gf} ⏱[/]",
    ]
    lines.append("")
    lines += violation_table(day, "OSINT")

    lines += _sub("two affiliation violations — don't confuse them", "#6ad4ff")
    lines += [
        "  [#ff8c42]AFFILIATION_UNVERIFIED[/] [dim](dossier-tier, minor)[/]",
        "    An ordinary claimed org that the sweep can't corroborate — the",
        "    handle shows up with no org tag or a different one. Weak signal.",
        "  [#ff8c42]AFFILIATION_MISMATCH[/] [dim](ghostscan-tier, major)[/]",
        "    An ELITE org claim (Port Authority CERT, Tidewater Signals…) that ghostscan",
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
        "  [dim]The named databases always match the corpus the cipher block[/]",
        "  [dim]names when a credential resolves — both surfaces agree. A[/]",
        "  [dim]single corpus is a BREACH_HIT (minor — they were exposed). TWO[/]",
        "  [dim]corpora holding the same recovered plaintext is[/]",
        "  [dim]CROSS_BREACH_REUSE (critical — being dumped is misfortune,[/]",
        "  [dim]still reusing it is a choice).[/]",
    ]
    return "\n".join(lines)


# ─── Tab 3 — CREDENTIALS (Hashcrack) ─────────────────────────────────────────


def build_creds_text(day: Day | None, unlocked_tools: set[str] | None = None) -> str:
    hc = config.TOOL_COSTS["hashcrack"]

    # The tab is LOCKED until Hashcrack is granted.
    #
    # It used to carry a violation table even while locked, because
    # UNSALTED_STORAGE was catalogued under CREDENTIAL while staying
    # DOSSIER-tiered — plantable from day 1, three days before this tab would
    # open, and a violation that is plantable and undocumented on the same day
    # is unflaggable in practice.
    #
    # That is no longer the case (2026-09-15): UNSALTED_STORAGE moved to the
    # DOSSIER group and is documented on the DOSSIER tab, beside the evidence
    # that actually reveals it. Every remaining CREDENTIAL kind needs Hashcrack,
    # so a locked table here would be empty — and violation_table() would
    # render a header over nothing, which tells the player something exists
    # without saying what. The locked tab now says only that it is locked.
    if not _tool_unlocked(ToolName.HASHCRACK, unlocked_tools):
        lines = _band("HASHCRACK — CREDENTIAL ANALYSIS — LOCKED", "#3d6478")
        lines += [
            "",
            "  [#3d6478][b]⊘  Not authorized yet.[/][/]",
            (f"  [dim]Hashcrack unlocks on Day "
             f"{config.TOOL_UNLOCK_DAY['hashcrack']}. Its cipher block, and the[/]"),
            "  [dim]violations only it can establish, open up the day the[/]",
            "  [dim]Foreman grants it.[/]",
            "",
            "  [dim]Until then the one credential problem you can already[/]",
            "  [dim]see — a password stored with no salt at all — is[/]",
            "  [dim]documented on the DOSSIER tab, where its evidence is.[/]",
        ]
        return "\n".join(lines)

    lines: list[str] = []
    lines += _band("HASHCRACK — THE CIPHER BLOCK", "#c084fc")
    lines += [
        "  Every dossier carries a PASSWORD field: the candidate's credential",
        "  in encrypted form. The dossier shows you the raw hash and nothing",
        "  else — no strength label, no verdict.",
        "",
        "  The Hashcrack page renders that credential as a block of ciphertext",
        "  and decrypts it in [b]two stages[/]: first you choose the decryption",
        "  window matching the algorithm, then you walk an alignment pad until",
        "  the text resolves. Stage 1 always costs ⏱; stage 2 only bills you",
        "  if you wander.",
    ]
    lines += _sub("before you spend — read the block", "#c084fc")
    lines += [
        "  The block's header states its DIGEST SHAPE, free, on arrival. That",
        "  one line answers both questions that matter:",
        "",
        "[#6b7785]  DIGEST                 ALGORITHM   PAD      WORTH OPENING?[/]",
        f"[#1c2733]{'─' * _W}[/]",
        (f"  [#ff5470]{_fit('32 hex characters', 23)}[/]{_fit('MD5', 12)}"
        f"{_fit('small', 9)}yes — cheapest crack in the game"),
        (f"  [#ffd93d]{_fit('64 hex characters', 23)}[/]{_fit('SHA-256', 12)}"
        f"{_fit('wide', 9)}yes — but the key takes finding"),
        (f"  [#00ff9f]{_fit('$2b$ prefix', 23)}[/]{_fit('bcrypt', 12)}"
        f"{_fit('none', 9)}[b]NO[/] — nothing is recoverable"),
        f"[#1c2733]{'─' * _W}[/]",
        "",
        "  [#00ff9f]bcrypt is a dead end by design.[/] Its window fits, the decrypt",
        "  engages, and then it stalls — key-stretched at cost factor 12, with",
        "  no alignment to find. Identifying it correctly and walking away",
        "  costs [b]nothing[/]; opening it to find out costs a full window.",
        "",
        "  [#00ff9f]Cipher ID HUD[/] names the algorithm on the block for you, if you",
        "  would rather buy the read than learn it.",
    ]
    lines += _sub("stage 1 — the decryption window", "#c084fc")
    lines += [
        "  [#c084fc]X[/] opens the selector. Three windows, one per algorithm family;",
        f"  applying one costs {hc} ⏱ (the tool's base cost, so inflation and the",
        "  Hashcrack Optimizer both apply).",
        "",
        "  [#ff5470]wrong window[/]   no structure emerges. The ⏱ is spent. Read the",
        "                 digest and try again.",
        "  [#00ff9f]bcrypt window[/]  fits, engages, stalls. Nothing to recover.",
        "  [#c084fc]right window[/]   the block gains structure and the pad unlocks.",
    ]
    lines += _sub("stage 2 — the alignment pad", "#c084fc")
    lines += [
        "  The decrypt has the right family but the wrong derived key — and",
        "  that key is a [b]coordinate[/]. All four arrows are live: ←→ walks X,",
        "  ↑↓ walks Y, and the block updates on every single press.",
        "",
        "  Too far out and the block is pure ciphertext. Close in and characters",
        "  start holding still; the password tiles itself across every row, so",
        "  you can read it by consensus long before you are exact:",
        "",
        "  [dim]far   [/] [#6b7785]b99a8deb7c008949ad7f61aacf6edb07[/]",
        "  [dim]close [/] [#c084fc]qN7!fWc$4kZt2[/][#6b7785]9q97!fWc$4kcf2·qN0![/]",
        "  [dim]exact [/] [#c084fc]qN7!fWc$4kZt2·qN7!fWc$4kZt2·qN7![/]",
        "",
        "  A few cells only settle on the [b]exact[/] square — that is the lock. The",
        "  credential resolves, the breach corpus is named, and the violations",
        "  are labelled only there.",
        "",
        "  [#ff8c42]Every press counts.[/] Both axes move the same measure, so any",
        "  press either warms or cools the block — there is no wasted direction,",
        f"  and no dead zone. The first {config.CIPHER_DIAL_FREE_STEPS} steps are free;"
        f" after that every",
        f"  {config.CIPHER_DIAL_OVERAGE_BLOCK} further steps cost "
        f"{config.CIPHER_DIAL_OVERAGE_COST} ⏱. Walking more or less straight at",
        "  the key never costs anything — sweeping the pad at random does.",
        "",
        "  [#00ff9f]Credential HUD[/] marks the box of the pad the true key sits in.",
        "  It narrows the search; it does not answer it.",
    ]
    lines += _sub("then judge what you recovered", "#c084fc")
    lines += [
        "  The call is meant to be obvious:",
        "  [#ff5470]weak[/]    [b]password01[/] · dictionary words · dates · keyboard walks",
        "  [#00ff9f]strong[/]  [b]drawkcab16445$&[/] · long, mixed, symbol-laden strings",
        "",
        "  [#00ff9f]strong plaintext[/] → no concern, whatever the algorithm",
        "  [#ffd93d]weak plaintext + weak algorithm[/] → WEAK_CREDENTIAL (minor —",
        "  flag it; not grounds to deny by itself)",
        "  [#ff8c42]plaintext found in a breach corpus[/] → LEAKED_PASSWORD (major)",
        "  [#ff5470]the same plaintext in TWO corpora[/] → CROSS_BREACH_REUSE",
        "  (critical — being dumped is misfortune, still reusing it is a choice)",
        "",
        "  [#00ff9f]Crack Verdict Analyzer[/] adds a one-line strength call to the",
        "  recovery block, if you would rather not make it yourself.",
    ]
    lines.append("")
    lines += violation_table(day, "CREDENTIAL", unlocked_tools=unlocked_tools)
    lines += _sub("composing with other tools", "#c084fc")
    lines += [
        "  The Logwatch day log carries this candidate's HASH_SUBMIT row (which",
        "  credential was submitted, and from which IP). Breach corpora are",
        "  named here, by the cipher block, and on the Ghostscan breach panel —",
        "  the two always agree. Logwatch shows no breach data at all.",
        "",
        "  Logwatch never names a credential violation itself; it only shows",
        "  the events. Naming them is this page's job.",
    ]
    return "\n".join(lines)


# ─── Tab 4 — LOG ANALYSIS (Logwatch) ─────────────────────────────────────────


def build_logs_text(day: Day | None, unlocked_tools: set[str] | None = None) -> str:
    if not _tool_unlocked(ToolName.LOGWATCH, unlocked_tools):
        return _locked_tab_text(ToolName.LOGWATCH, "LOGWATCH — LOG ANALYSIS")
    lw = config.TOOL_COSTS["logwatch"]
    lf = config.FILTER_COSTS["logwatch"]
    s0 = f"{config.LW_SHIFT_START // 3600:02d}:00"
    s1 = f"{config.LW_SHIFT_END // 3600:02d}:00"
    burst_n, burst_m = config.LW_BURST_ALERT, config.LW_BURST_WINDOW // 60
    lines: list[str] = []
    lines += _band("LOGWATCH — LOG ANALYSIS", "#ffb454")
    lines += [
        "  Every server keeps an event log: who connected, from where, when,",
        "  doing what. Logwatch hands you a SUMMARY of it for free — the",
        "  Activity Report — and keeps the raw auth log sealed until you",
        "  decide this account's numbers are worth the ⏱.",
    ]
    lines += _sub("investigation tiers", "#ffb454")
    lines += [
        "  [#00ff9f]free[/]     Activity Report (centre) — bars, timeline, origins,",
        "           resource counts, analyst notes. Nothing is named.",
        f"  [#ffb454]run L[/]    unseals the auth log (right panel) — every row,",
        f"           this account's in yellow, no labels          [dim]{lw} ⏱[/]",
        f"  [#c084fc]filter[/]   ▲ names each violation in the log AND adds a",
        f"           ▲ CONFIRMED block to the report         [dim]+{lf} ⏱[/]",
    ]
    lines += _sub("reading the Activity Report", "#ffb454")
    lines += [
        "  [#7dd3c0]ACTIVITY PROFILE[/]  bars show the raw count for free. The",
        "    [b]│[/] normal-ceiling tick — and the amber flag past it — is",
        "    behind the Log Analyzer HUD; until then you judge the count cold.",
        f"  [#7dd3c0]TIMELINE[/]  24h lanes AUTH ● · FAIL × · FILES □ · PRIV ◆;",
        f"    ░ is the {s0}–{s1} shift; a digit = several events in one cell.",
        "  [#7dd3c0]ORIGINS[/]  a world map of where this account logged in",
        "    from, numbered to match the legend. ✓ = the claimed IP; red",
        "    numbers failed their way in. Dotted arcs + the 1→2 lines are",
        "    city changes between CLEAN logins: distance and time only.",
        f"    [b]People travel[/] — faster than ~{config.LW_MAX_FEASIBLE_KMH} km/h is",
        "    what no flight explains.",
        "  [#7dd3c0]RESOURCES[/]  routine / sensitive reads, privileged commands",
        "    — counts only; the auth log shows which paths.",
        "  [#7dd3c0]ANALYST NOTES[/]  [dim](Threat Triage HUD)[/] the report's own",
        "    conclusions: attack bursts, a claimed IP never seen, city changes",
        "    faster than any flight, off-shift work. Locked until bought —",
        "    everything they summarise is on the report for a careful reader.",
        f"  [#ff5470]AUTHENTICATION ANOMALY[/]  {burst_n}+ linked failures inside",
        f"    {burst_m} min. [b]Unclassified[/] — the report cannot tell a brute",
        "    force from credential stuffing. The auth log can.",
    ]
    lines.append("")
    lines += violation_table(day, "FORENSICS")
    lines += _sub("reading the auth log", "#ffb454")
    lines += [
        "  [#ff5470]BRUTE_FORCE_IN_LOG[/]   a burst of AUTH_FAILs on THIS account,",
        "                       usually ending in an AUTH_OK",
        "  [#ff5470]CREDENTIAL_STUFFING[/]  one source IP failing on MANY OTHER",
        "                       accounts, then logging in to this one",
        "  [#ff8c42]IMPOSSIBLE_TRAVEL[/]    two clean logins whose cities are",
        "                       unreachable in the time between them",
        "  [#ff8c42]INSIDER_BEHAVIOR[/]     sensitive FILE_READ + SUDO_EXEC off-shift",
        "  [#ffd93d]AFTER_HOURS_ACCESS[/]   ordinary work off-shift — minor; benign",
        "                       alone, meaningful in combination",
        "  [#ff5470]LOW_AND_SLOW[/]         a few failures from one IP, hours apart —",
        "                       built to stay under the report's alert",
        "  [#ffd93d]CLAIMED_IP_MISMATCH[/]  the claimed IP never logs in at all —",
        "                       visible on the free report",
        "",
        "  [dim]One failed login is not an attack — honest people mistype.[/]",
        "  [dim]HASH_SUBMIT rows are context only; Logwatch shows no breach data.[/]",
    ]
    lines += _sub("upgrades that change this page", "#ffb454")
    lines += [
        "  [#00ff9f]Log Analyzer HUD[/]  ▸ marks this account's rows that sit",
        "                    inside an anomaly, reveals each Activity Profile",
        "                    bar's ceiling tick, and flags bars past it. It",
        "                    points; it never names.",
        "  [#00ff9f]Threat Triage HUD[/]   unlocks the report's Analyst Notes",
        "  [#00ff9f]Logwatch Optimizer[/]  the log pull costs less ⏱",
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
        "  [#00ff9f]X[/] / [#00ff9f]extract[/]  enter stamp mode on the image viewer",
        f"  [#00ff9f]arrows[/]       move the {config.STEGO_STAMP_W}×{config.STEGO_STAMP_H} stamp",
        "  [#00ff9f]mouse[/]        hover to move the stamp, click to place it",
        (f"  [#00ff9f]Space[/] / [#00ff9f]click[/] stamp — reveal the cells underneath   "
        f"[dim]{config.STEGO_STAMP_COST} ⏱ per stamp[/]"),
        (f"  [#00ff9f]F[/] / [#00ff9f]filter[/]   classify the payload TYPE by name    "
        f"[dim]+{config.STEGO_FILTER_COST} ⏱[/]"),
        "  [#00ff9f]Esc[/]          exit stamp mode",
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
    # 2026-09-19: the second axis. Colour says WHAT the payload is; the glyph
    # the carrier cells trace says what it is FOR. Independent of each other —
    # any colour can carry any glyph — and the conventional glyph is the
    # common, innocent-of-anything-extra case, which the player must be told
    # outright or they will read every blocky carrier as a missed shape.
    lines += _sub("carrier glyphs — the payload's operation", "#ff8cc8")
    lines += [
        "[#6b7785]  GLYPH         WHAT THE CELLS DO               EXTRA VIOLATION[/]",
        f"[#1c2733]{'─' * _W}[/]",
        f"  {_fit('conventional', 14)}{_fit('irregular blocks / runs', 32)}[dim]none[/]",
        f"  {_fit('cross', 14)}{_fit('+ or X — strokes intersect', 32)}Signal comms",
        f"  {_fit('enclosed', 14)}{_fit('ring / diamond, hollow inside', 32)}Recursive",
        f"  {_fit('slash', 14)}{_fit('2-4 parallel, never touching', 32)}Hostile",
        f"[#1c2733]{'─' * _W}[/]",
        "",
        "  [dim]Shape and colour are separate findings: an AMBER cross is a",
        "  stego payload AND signal comms. Reveal enough of the zone to see",
        "  the figure — without the filter the log only describes its",
        "  geometry; with it, the operation is named (▲). A blocky,",
        "  conventional carrier adds nothing beyond its colour.[/]",
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
