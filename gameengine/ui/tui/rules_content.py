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

from gameengine import config
from gameengine.core import candidate_gen, tools_bridge
from gameengine.core.models import Day, DiscrepancyKind, Performance, ToolName

# ─── Violation catalog — (group, kind, player-facing label) ─────────────────
# The Evidence Board (app.EVIDENCE_ITEMS) is built from this list, so board
# labels and rules-page tables always match.

VIOLATION_CATALOG: list[tuple[str, DiscrepancyKind, str]] = [
    # DOSSIER (no tool)
    ("DOSSIER",     DiscrepancyKind.MISSING_PUBLIC_PROFILE, "Missing public profile"),
    ("DOSSIER",     DiscrepancyKind.HOSTILE_CHAT,           "Hostile chat"),
    ("DOSSIER",     DiscrepancyKind.AFFILIATION_UNVERIFIED, "Unverified affiliation"),
    ("DOSSIER",     DiscrepancyKind.DISPOSABLE_EMAIL,       "Disposable email domain"),
    ("DOSSIER",     DiscrepancyKind.CLAIMED_IP_MISMATCH,    "Claimed-IP mismatch"),
    # OSINT (Ghostscan)
    ("OSINT",       DiscrepancyKind.EMAIL_GITHUB_MISMATCH,  "Email / GitHub mismatch"),
    ("OSINT",       DiscrepancyKind.BREACH_HIT,             "Breach hit"),
    ("OSINT",       DiscrepancyKind.SOCK_PUPPET_ACCOUNTS,   "Sock puppet accounts"),
    ("OSINT",       DiscrepancyKind.AFFILIATION_MISMATCH,   "Faked elite affiliation"),
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
    # CREDENTIAL (Hashcrack)
    ("CREDENTIAL",  DiscrepancyKind.LEAKED_PASSWORD,        "Leaked password"),
    ("CREDENTIAL",  DiscrepancyKind.WEAK_CREDENTIAL,        "Weak credential"),
    ("CREDENTIAL",  DiscrepancyKind.CROSS_BREACH_REUSE,     "Cross-breach password reuse"),
    ("CREDENTIAL",  DiscrepancyKind.UNSALTED_STORAGE,       "Unsalted / plaintext storage"),
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
    DiscrepancyKind.MISSING_PUBLIC_PROFILE: "free — sparse platform sweep; weighted signal, never auto-disqualifying",
    DiscrepancyKind.HOSTILE_CHAT:           "free — read the chat panel (Sentiment Scanner upgrade ⚠-marks it)",
    DiscrepancyKind.AFFILIATION_UNVERIFIED: "base recon — handle appears without the claimed org tag",
    DiscrepancyKind.DISPOSABLE_EMAIL:       "free — domain visible on the dossier, no tool needed (quick deny)",
    DiscrepancyKind.CLAIMED_IP_MISMATCH:    "free — dossier IP vs log IPs; a breadcrumb, corroborate before denying",
    DiscrepancyKind.EMAIL_GITHUB_MISMATCH:  "base recon shows commit email · filter highlights the mismatch",
    DiscrepancyKind.BREACH_HIT:             "base recon highlights breach panel · filter confirms ▲ BREACH_HIT",
    DiscrepancyKind.SOCK_PUPPET_ACCOUNTS:   "handle on a CRITICAL forum — blended in base run, filter labels it",
    DiscrepancyKind.AFFILIATION_MISMATCH:   "elite org claimed but absent from the sweep — filter confirms",
    DiscrepancyKind.BURNER_IDENTITY:        "account registry: creation dates clustered within days — filter labels",
    DiscrepancyKind.THREAT_FORUM_MATCH:     "handle in the threat-forum list — filter reveals with [CRITICAL] tag",
    DiscrepancyKind.TYPOSQUAT_HANDLE:       "free cue on identity check · filter confirms the lookalike",
    DiscrepancyKind.BRUTE_FORCE_IN_LOG:     "free log shows the AUTH_FAIL burst · base run flags · filter labels",
    DiscrepancyKind.IMPOSSIBLE_TRAVEL:      "base run tags cities · filter's geo timeline makes it explicit",
    DiscrepancyKind.INSIDER_BEHAVIOR:       "sensitive FILE_ACCESS + PRIV_ESCALATE after hours · filter labels",
    DiscrepancyKind.CREDENTIAL_STUFFING:    "one IP, many accounts, few tries — base detects · filter names it",
    DiscrepancyKind.AFTER_HOURS_ACCESS:     "activity outside business hours — benign alone (minor)",
    DiscrepancyKind.LOW_AND_SLOW:           "sub-threshold on purpose — only the filter's correlation finds it",
    DiscrepancyKind.LEAKED_PASSWORD:        "crack reveals plaintext + BREACH_MATCH names the corpus",
    DiscrepancyKind.WEAK_CREDENTIAL:        "weak encryption (MD5) cracks to a weak plaintext — minor hygiene flag",
    DiscrepancyKind.CROSS_BREACH_REUSE:     "crack + a SECOND breach-corpus match — cross-check the breach panel",
    DiscrepancyKind.UNSALTED_STORAGE:       "hash shape is free info; crack is instant — storage hygiene failure",
    DiscrepancyKind.STEGO_PAYLOAD_PRESENT:  "stamp the tinted zone — AMBER cells; ≥60% coverage resolves ▲",
    DiscrepancyKind.COVERT_C2_CHANNEL:      "VIOLET sparse scatter over a wide zone — resolve by stamping",
    DiscrepancyKind.ENCRYPTED_PAYLOAD:      "CRIMSON mid-density cells — filter (F) names the payload type",
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
    out.append(f"[#1c2733]{'─' * _W}[/]")
    out.append("[dim]  TODAY column: DENY = disqualifying rule · FLAG = weighted "
               "(corroborate) · — = not in today's ruleset[/]")
    return out


# ─── Tab 1 — RULES (day rules · quotas · resources · systems) ────────────────


def build_rules_text(day: Day | None) -> str:
    kb     = config.KEY_BINDINGS
    lines: list[str] = []

    # ── Today's ruleset ────────────────────────────────────────────────
    title = day.title if day else "No day loaded"
    lines += _band(f"TODAY'S RULESET — {title}", "#7dd3c0",
                   "read every shift — rules change day to day")
    rules = day.rules if day else ()
    disq  = [r for r in rules if r.severity == "disqualifying"]
    minor = [r for r in rules if r.severity != "disqualifying"]
    if disq:
        lines.append("")
        lines.append("[#ff5470][b]DISQUALIFYING[/][/]  — any one of these → DENY")
        for r in disq:
            lines.append(f"  [#ff5470]✗[/]  {r.text}")
    if minor:
        lines.append("")
        lines.append("[#ff8c42][b]WEIGHTED[/][/]  — flag on the Evidence Board; "
                     "corroborate before denying")
        for r in minor:
            lines.append(f"  [#ff8c42]△[/]  {r.text}")
    if not rules:
        lines.append("[dim]No rules loaded for this day.[/]")

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
    for _uid, label, price, desc in config.UPGRADE_CATALOG:
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
        f"[#ff8c42]?  PRIVACY[/]   {privacy}"
        "   [dim](flag only with other discrepancies)[/]",
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


def build_osint_text(day: Day | None) -> str:
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


def build_creds_text(day: Day | None) -> str:
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
    lines += _sub("encryption strength — free dossier information", "#c084fc")
    lines += [
        "[#6b7785]  TIER     HASH SHAPE          CRACKABLE   MEANING[/]",
        f"[#1c2733]{'─' * _W}[/]",
        f"  [#00ff9f]{_fit('STRONG', 9)}[/]{_fit('bcrypt  $2b$…', 20)}"
        f"{_fit('never', 12)}always safe — no violation possible",
        f"  [#ffd93d]{_fit('MEDIUM', 9)}[/]{_fit('SHA256  64 hex', 20)}"
        f"{_fit('with effort', 12)}crack it, then judge the plaintext",
        f"  [#ff5470]{_fit('WEAK', 9)}[/]{_fit('MD5     32 hex', 20)}"
        f"{_fit('instantly', 12)}weak enc + weak plaintext = violation",
        f"[#1c2733]{'─' * _W}[/]",
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


def build_logs_text(day: Day | None) -> str:
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
        "",
        "  [dim]CLAIMED_IP_MISMATCH (dossier tab) is the breadcrumb that sends",
        "  you here: compare the dossier's claimed IP against login sources.[/]",
    ]
    lines += _sub("upgrades that change this page", "#ffb454")
    lines += [
        "  [#00ff9f]Session Grouper[/]   groups the raw log into per-session blocks",
        "                    instead of a flat chronological stream",
        "  [#00ff9f]Log Analyzer HUD[/]  pre-colours suspicious lines in the free",
        "                    log — before any ⏱ is spent",
    ]
    return "\n".join(lines)


# ─── Tab 5 — STEGANOGRAPHY (Stegotool) ───────────────────────────────────────


def build_stego_text(day: Day | None) -> str:
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
        "  [dim]Hot zones carry a faint blue tint before any ⏱ is spent — aim",
        "  your first stamps where the noise looks wrong. The Spectral Lens",
        "  upgrade strengthens that tint.[/]",
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
