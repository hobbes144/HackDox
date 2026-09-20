"""Evidence catalog, command vocabulary, reference text, and dossier
password-field helpers shared across the TUI widgets and screens."""

from __future__ import annotations

from gameengine import config
from gameengine.core import candidate_gen, tools_bridge
from gameengine.core.models import DiscrepancyKind, ToolName, Verdict
from gameengine.ui.tui import rules_content

# Shortcut so BINDINGS class attributes can be built from config at import time.
_B = config.KEY_BINDINGS

# ─── Evidence board item catalog ─────────────────────────────────────────────
# Single-sourced from rules_content (issue #30): the Evidence Board and the
# Rules Pages tables render from the SAME catalog, so changing a violation
# there updates labels, colours, and sorting everywhere at once.


# rules_content.visible_catalog(None) = every kind, unfiltered, already
# ordered by rules_content.GROUP_ORDER then severity ascending (minor ->
# major -> critical) so the board reads calm-to-alarming. Reading the sort
# from there instead of re-deriving it here means there is exactly one place
# that decides group/severity order for every catalog-driven surface — this
# board, the gated per-instance boards (EvidenceBoard.__init__ below), and
# the Rules Pages tables all agree by construction.
EVIDENCE_ITEMS: list[tuple[str, DiscrepancyKind, str]] = (
    rules_content.visible_catalog(None))
_ITEM_COUNT = len(EVIDENCE_ITEMS)

# ─── Severity → colour, sourced from the generator's single source of truth ──
# Each violation's text is coloured by its severity so the board reads at a
# glance: yellow = minor, orange = major, red = critical.
_SEVERITY: dict[DiscrepancyKind, str] = {
    kind: sev for kind, (_tool, sev) in candidate_gen._SEVERITY_REVEAL.items()
}
_SEV_COLOR = {"minor": "#ffd93d", "major": "#ff8c42", "critical": "#ff5470"}


def _sev_color(kind: DiscrepancyKind) -> str:
    return _SEV_COLOR.get(_SEVERITY.get(kind, "minor"), "#c8d4e1")


# Board group order + per-group display metadata: (accent colour, tool hotkey).
# The hotkey is the tool page each group is investigated on (blank = dossier).
# Aliased from rules_content.GROUP_ORDER (not re-typed) so this can never
# drift out of sync with the sort visible_catalog() actually applies.
_GROUP_ORDER = rules_content.GROUP_ORDER
_GROUP_META: dict[str, tuple[str, str]] = {
    "DOSSIER":    ("#7dd3c0", ""),
    "OSINT":      ("#6ad4ff", "G"),
    "FORENSICS":  ("#ffb454", "L"),
    "CREDENTIAL": ("#c084fc", "H"),
    "STEGO":      ("#ff8cc8", "S"),
}
# Which group a given tool page's board should scroll to when toggled open.
_BOARD_HOME_GROUP: dict[str, str] = {
    "evidence-gs": "OSINT",
    "evidence-hc": "CREDENTIAL",
    "evidence-lw": "FORENSICS",
    "evidence-st": "STEGO",
}

# ─── Reference panels (2026-09-19: derived, not typed) ─────────────────────
#
# Every number, key, colour and signature name on these panels is read from
# its single source at render time: costs from tools_bridge.tool_cost() /
# config (upgrade- and inflation-aware when a GameState is passed), keys from
# config.KEY_BINDINGS, forum tiers from tools_bridge, cipher tiers from
# tools_bridge._CIPHER_TIER_META, stamp signatures from _STAMP_KIND_META and
# carrier glyphs from _STAMP_SHAPE_META. The panels used to be string literals
# and had drifted: the Stegotool one advertised a 1 ⏱ stamp and a 2 ⏱ filter
# (real: 5 and 10) and had its AMBER/VIOLET texture lines swapped.
#
# `state` is optional so the module-level _REF_* defaults (day 1, no
# upgrades) still exist for anything that imports them; IntakeScreen rebuilds
# each panel with the live GameState on every candidate load.


def _key(name: str) -> str:
    return config.KEY_BINDINGS[name]


def _base_cost(tool: str, state=None) -> int:
    if state is None:
        return config.DAY_TOOL_COST(tool, 1)
    return tools_bridge.tool_cost(state, tool)


def _stego_filter_cost(state=None) -> int:
    """Mirrors IntakeScreen._activate_stego_filter's own arithmetic."""
    cost = config.STEGO_FILTER_COST
    if state is not None and \
            config.UPGRADE_TOOLCOST_STEGOTOOL in getattr(state, "upgrades", ()):
        cost = max(1, cost - config.TOOLCOST_REDUCTION)
    return cost


def _verdict_footer() -> str:
    return ("[dim]── verdict ─────────────────────────[/]\n"
            f"[#00ff9f]admit[/] [dim]/[/] [#ff5470]deny[/]  [dim]when ready[/]")


def build_ref_candidate(state=None) -> str:
    return f"""[#7dd3c0][b]COMMANDS — CANDIDATE[/][/]

[#00ff9f]admit[/]  [dim]or[/] [#00ff9f]{_key('admit')}[/]
  approve this candidate's access

[#ff5470]deny[/]  [dim]or[/] [#ff5470]{_key('deny')}[/]
  reject this candidate's access

[#7dd3c0]next[/]  [dim]or[/] [#7dd3c0]{_key('next_candidate')}[/]
  move to next candidate

[dim]── tools ───────────────────────────[/]
[#00ff9f]recon[/]   run ghostscan  [dim](page {_key('page_ghostscan')} · {_base_cost('ghostscan', state)} ⏱)[/]
[#00ff9f]crack[/]   run hashcrack  [dim](page {_key('page_hashcrack')} · {_base_cost('hashcrack', state)} ⏱)[/]
[#00ff9f]analyze[/] run logwatch   [dim](page {_key('page_logwatch')} · {_base_cost('logwatch', state)} ⏱)[/]
[#00ff9f]extract[/] stego stamp mode [dim](page {_key('page_stegotool')} · {config.STEGO_STAMP_COST} ⏱/stamp)[/]

[dim]── other ──────────────────────────[/]
[#c084fc]reveal[/] spend a HackDox Credit —
  shows this candidate's ground truth
[#6b7785]rules[/]  open rulebook
[#6b7785]help[/]   show command list
[#6b7785]quit[/]   exit game"""


def build_ref_ghostscan(state=None) -> str:
    crit = tools_bridge._GS_CRITICAL_FORUMS
    adv = tools_bridge._GS_ADVISORY_FORUMS
    half = lambda xs: (" · ".join(xs[:2]), " · ".join(xs[2:]))  # noqa: E731
    c1, c2 = half(crit)
    a1, a2 = half(adv)
    return f"""[#7dd3c0][b]COMMANDS — GHOSTSCAN[/][/]

[#00ff9f]recon[/]  [dim]or[/] [#00ff9f]{_key('tool_ghostscan')}[/]
  fixed platform sweep — same list
  every day · verify claimed org
  [dim]cost: {_base_cost('ghostscan', state)} ⏱[/]

[#c084fc]filter[/]  [dim]or[/] [#c084fc]{_key('filter_current')}[/]
  reveals threat forum entries +
  highlights commit email mismatch +
  explicit ▲ VIOLATION_TYPE labels
  [dim]cost: +{config.FILTER_COSTS['ghostscan']} ⏱[/]

[dim]── forum tiers ──────────────────────[/]
[#ff5470]CRITICAL — immediate deny:[/]
[dim]{c1}[/]
[dim]{c2}[/]
[#ff8c42]ADVISORY — investigate further:[/]
[dim]{a1}[/]
[dim]{a2}[/]

{_verdict_footer()}"""


def build_ref_hashcrack(state=None) -> str:
    tm = tools_bridge._CIPHER_TIER_META
    weak_c, med_c, strong_c = tm["weak"][1], tm["medium"][1], tm["strong"][1]
    sev = lambda k: _SEV_COLOR[candidate_gen.severity_for(k, None)]  # noqa: E731
    wc, lp, cb = (DiscrepancyKind.WEAK_CREDENTIAL, DiscrepancyKind.LEAKED_PASSWORD,
                  DiscrepancyKind.CROSS_BREACH_REUSE)
    return f"""[#7dd3c0][b]THE CIPHER BLOCK[/][/]

[#c084fc]{_key('decrypt_mode').upper()}[/]  [dim]or[/] [#c084fc]crack[/] [dim]/[/] [#c084fc]{_key('tool_hashcrack')}[/]
  open the window selector

[dim]── 1. read the digest (free) ─────[/]
[dim]The header states the digest
shape before you spend anything.[/]
[{weak_c}]32 hex[/]   [dim]{tm['weak'][2]:<7} small pad[/]
[{med_c}]64 hex[/]   [dim]{tm['medium'][2]:<7} wide pad[/]
[{strong_c}]$2b$[/]     [dim]{tm['strong'][2]:<7} DEAD END[/]

[dim]bcrypt's window fits, engages,
then stalls — key-stretched, no
alignment exists. Walking away
costs nothing. Opening it to find
out costs a full window.[/]

[dim]── 2. pick the window ({_base_cost('hashcrack', state)} ⏱) ─────[/]
[#c084fc]←→[/] [dim]choose[/]  [#c084fc]Enter[/] [dim]apply[/]
[dim]wrong window = no structure, and
the ⏱ is gone. Read first.[/]

[dim]── 3. walk the pad ───────────────[/]
[#c084fc]←→[/] [dim]X axis[/]   [#c084fc]↑↓[/] [dim]Y axis[/]
[dim]far   [/] [#6b7785]b99a8deb7c008949[/]
[dim]close [/] [#c084fc]qN7!fWc$4kZt2[/][#6b7785]9q97![/]
[dim]exact [/] [#c084fc]qN7!fWc$4kZt2{config.CIPHER_TILE_SEPARATOR}qN7![/]
[dim]the password tiles across every
row, so you can read it by
consensus before you're exact.
a few cells only settle on the
exact square — that's the lock.[/]
[dim]every press warms or cools the
block. first {config.CIPHER_DIAL_FREE_STEPS} steps free, then
{config.CIPHER_DIAL_OVERAGE_COST} ⏱ per {config.CIPHER_DIAL_OVERAGE_BLOCK} — a straight walk is
always free, a random sweep isn't.[/]

[dim]── then judge it ─────────────────[/]
[#ff5470]weak[/]    [dim]password01 · dates · walks[/]
[#00ff9f]strong[/]  [dim]long, mixed, symbol-laden[/]
[dim]weak pw + weak algo[/] [{sev(wc)}]{wc.name}[/]
[dim]in a corpus[/]        [{sev(lp)}]{lp.name}[/]
[dim]in TWO corpora[/]     [{sev(cb)}]{cb.name}[/]

{_verdict_footer()}"""


def build_ref_logwatch(state=None) -> str:
    # 2026-09-19 overhaul: the free tier is the Activity Report; L unseals
    # the auth log panel on the right; the filter names violations.
    return f"""[#7dd3c0][b]LOGWATCH — REPORT FIRST[/][/]

[dim]free[/]  Activity Report (centre)
  read it before spending ⏱

[#00ff9f]analyze[/]  [dim]or[/] [#00ff9f]logwatch[/]  [dim]or[/] [#00ff9f]{_key('tool_logwatch')}[/]
  unseal the auth log (right)
  — every row, no labels
  [dim]cost: {_base_cost('logwatch', state)} ⏱[/]
[#00ff9f]\\[ ][/]  jump this account's rows
[#00ff9f]PgUp PgDn[/]  page the log

[#c084fc]filter[/]  [dim]or[/] [#c084fc]{_key('filter_current')}[/]
  ▲ names each violation in the
  log and on the report
  [dim]cost: +{config.FILTER_COSTS['logwatch']} ⏱[/]

{_verdict_footer()}"""


# The stego legend's "texture" column is the second half of each
# _STAMP_KIND_META description ("<type> — <texture>"), and the payload name is
# derived from the kind itself, so the legend can never list a signature the
# engine does not render — or pair a colour with another colour's texture.
_STEGO_PAYLOAD_NAMES = {
    DiscrepancyKind.STEGO_PAYLOAD_PRESENT: "plaintext LSB payload",
    DiscrepancyKind.ENCRYPTED_PAYLOAD:     "encrypted payload",
    DiscrepancyKind.COVERT_C2_CHANNEL:     "covert C2 channel",
}
_SHAPE_GLYPH_WORD = {
    tools_bridge.StegoShape.CONVENTIONAL: "blocks",
    tools_bridge.StegoShape.CROSS:        "cross",
    tools_bridge.StegoShape.ENCLOSED:     "loop",
    tools_bridge.StegoShape.SLASH:        "slashes",
}


def build_ref_stegotool(state=None) -> str:
    stamp = _key("stamp_mode").upper()
    lines = [
        "[#7dd3c0][b]STEGOTOOL — STAMP MODE[/][/]",
        "",
        f"[#00ff9f]{stamp}[/]  [dim]or[/] [#00ff9f]extract[/] [dim]/[/] [#00ff9f]{_key('tool_stegotool')}[/]",
        "  enter stamp mode on the",
        "  image viewer (right panel)",
        "",
        "[#00ff9f]arrows[/]  move the stamp",
        f"  [dim]{config.STEGO_STAMP_W}×{config.STEGO_STAMP_H} cells[/]",
        "[#00ff9f]Space[/]   stamp the region",
        f"  [dim]cost: {config.STEGO_STAMP_COST} ⏱ per stamp[/]",
        "[#00ff9f]Esc[/]     exit stamp mode",
        "",
        f"[#00ff9f]{_key('filter_current').upper()}[/]  [dim]or[/] [#00ff9f]filter[/]  classify payload",
        f"  [dim]cost: {_stego_filter_cost(state)} ⏱ — names the payload",
        "  type and its glyph. Without it,",
        "  read the COLOUR and SHAPE yourself.[/]",
        "",
        "[dim]── signature colours ───────────────[/]",
    ]
    for kind, (sig, col, desc) in tools_bridge._STAMP_KIND_META.items():
        texture = desc.split(" — ", 1)[-1]
        lines.append(f"[{col}]{sig:<8}[/] {_STEGO_PAYLOAD_NAMES[kind]}")
        lines.append(f"  [dim]{texture}[/]")
    lines += [
        "[#00ff9f]GREEN[/]    region clean",
        "",
        "[dim]── carrier glyphs (operation) ──────[/]",
        "[dim]the SHAPE the carrier cells trace is",
        "a second finding, any colour:[/]",
    ]
    for shape, (geometry, _purpose, kind) in tools_bridge._STAMP_SHAPE_META.items():
        verdict = ("nothing extra" if kind is None
                   else f"→ {rules_content.label_for(kind)}")
        lines.append(f"{_SHAPE_GLYPH_WORD[shape]:<8} [dim]{verdict}[/]")
        lines.append(f"  [dim]{geometry.split(' — ')[0]}[/]")
    cov = int(config.STEGO_STAMP_RESOLVE_COVERAGE * 100)
    lines += [
        "",
        "[dim]── reading the image ───────────────[/]",
        "[dim]nothing is marked for you — sweep",
        "the grid and stamp where the noise",
        f"looks wrong. reveal ~{cov}% of a zone",
        "to resolve its ▲ signature.",
        "the Spectral Lens upgrade tints a",
        "rough area blue — close, not exact[/]",
        "",
        _verdict_footer(),
    ]
    return "\n".join(lines)


REFERENCE_BUILDERS = {
    "candidate": build_ref_candidate,
    "ghostscan": build_ref_ghostscan,
    "hashcrack": build_ref_hashcrack,
    "logwatch":  build_ref_logwatch,
    "stegotool": build_ref_stegotool,
}

# Day-1, no-upgrade renders — kept for importers of the old constants.
_REF_CANDIDATE = build_ref_candidate()
_REF_GHOSTSCAN = build_ref_ghostscan()
_REF_HASHCRACK = build_ref_hashcrack()
_REF_LOGWATCH  = build_ref_logwatch()
_REF_STEGOTOOL = build_ref_stegotool()


# ─── Command vocabulary ───────────────────────────────────────────────────────
# Maps typed input → (action_kind, argument).  Parser is case-insensitive.
# To add an alias, insert a new key with the same (kind, arg) tuple.

_COMMAND_ALIASES: dict[str, tuple[str, object]] = {
    # OSINT / Ghostscan
    "recon":      ("tool",    ToolName.GHOSTSCAN),
    "ghostscan":  ("tool",    ToolName.GHOSTSCAN),
    "g":          ("tool",    ToolName.GHOSTSCAN),
    # Hashcrack
    "crack":      ("tool",    ToolName.HASHCRACK),
    "hashcrack":  ("tool",    ToolName.HASHCRACK),
    "h":          ("tool",    ToolName.HASHCRACK),
    # Logwatch
    "analyze":    ("tool",    ToolName.LOGWATCH),
    "logwatch":   ("tool",    ToolName.LOGWATCH),
    "l":          ("tool",    ToolName.LOGWATCH),
    # Stegotool — jumps to page 5 and enters stamp mode (no flat tool run)
    "extract":    ("stamp",   None),
    "stegotool":  ("stamp",   None),
    "stego":      ("stamp",   None),
    "s":          ("stamp",   None),
    "stamp":      ("stamp",   None),
    "x":          ("stamp",   None),
    # Filter (enhanced analysis pass)
    "filter":     ("filter",  None),
    "f":          ("filter",  None),
    # Verdicts
    "admit":      ("verdict", Verdict.ADMIT),
    "a":          ("verdict", Verdict.ADMIT),
    "deny":       ("verdict", Verdict.DENY),
    "d":          ("verdict", Verdict.DENY),
    # Navigation
    "next":       ("next",    None),
    "n":          ("next",    None),
    # Overlays / help
    "rules":      ("rules",   None),
    "evidence":   ("evidence", None),
    "board":      ("evidence", None),
    "help":       ("help",    None),
    "?":          ("help",    None),
    # HackDox Credit — ground-truth reveal (issue #25). Works on every page.
    "reveal":     ("reveal",  None),
    "credit":     ("reveal",  None),
    "truth":      ("reveal",  None),
    # Quit
    "quit":       ("quit",    None),
    "exit":       ("quit",    None),
    "q":          ("quit",    None),
}

_ERROR_MSGS: tuple[str, ...] = (
    "PERMISSION DENIED — command not available in current context",
    "COMMAND NOT RECOGNIZED — type 'help' for available directives",
    "ACCESS RESTRICTED — insufficient clearance for that operation",
    "SYNTAX ERROR — unknown directive, input rejected",
    "ERROR 403 — operation not permitted by access control system",
    "INVALID DIRECTIVE — command not found in session vocabulary",
    "UNRECOGNIZED INSTRUCTION — check your spelling and try again",
)

_PAGE_NAMES = ["CANDIDATE", "GHOSTSCAN", "HASHCRACK", "LOGWATCH", "STEGOTOOL"]
_PAGE_IDS   = ["page-candidate", "page-ghostscan", "page-hashcrack",
               "page-logwatch",  "page-stegotool"]
# Page index → tool value string. Page 0 (Candidate/Dossier) is never gated;
# the four tool pages map to a ToolName value. Used by progressive unlock (#33)
# to grey locked tabs and refuse navigation/shortcuts for not-yet-unlocked
# tools. Kept in step with _PAGE_NAMES / _PAGE_IDS.
_PAGE_TOOL = [None, "ghostscan", "hashcrack", "logwatch", "stegotool"]

# #50: which Rules-page tab each intake page corresponds to, so opening the
# docs hub from a tool page lands on that tool's reference instead of always
# dumping the player on the general Rules tab. Parallel to _PAGE_TOOL by
# index; page 0 (the candidate/dossier page) maps to the new Dossier tab,
# which is where its free-read reference material now lives.
_PAGE_TAB = ["tab-dossier", "tab-osint", "tab-creds", "tab-logs", "tab-stego"]


# ─── Widgets ─────────────────────────────────────────────────────────────────


def _hl_email(email: str, upgrades: set) -> str:
    """Auto-highlight upgrade (issue #23): colour-code the email domain when
    the matching whitelist/blacklist HUD upgrade is owned. No-op otherwise."""
    cls = tools_bridge.classify_email_domain(email)
    if cls == "approved" and config.UPGRADE_EMAIL_APPROVED in upgrades:
        return f"[#00ff9f]{email}  ✓[/]"
    if cls == "prohibited" and config.UPGRADE_EMAIL_PROHIBITED in upgrades:
        return f"[#ff5470]{email}  ✗ prohibited[/]"
    return email


def _hl_affil(affil: str, upgrades: set) -> str:
    """Auto-highlight upgrade (issue #23): colour-code the claimed org when
    the matching whitelist/blacklist HUD upgrade is owned. No-op otherwise."""
    cls = tools_bridge.classify_affiliation(affil)
    if cls == "approved" and config.UPGRADE_AFFIL_APPROVED in upgrades:
        return f"[#00ff9f]{affil}  ✓[/]"
    if cls == "prohibited" and config.UPGRADE_AFFIL_PROHIBITED in upgrades:
        return f"[#ff5470]{affil}  ✗ prohibited[/]"
    return affil


# ─── Dossier password field (issue #29) ──────────────────────────────────────
# Every dossier shows the submitted credential in encrypted form. Once the
# Hashcrack cipher block resolves it, the recovered plaintext is shown in place
# across all pages.
#
# Panel convention for `cracked_password`:
#   None → not recovered yet   ·   "" → bcrypt, established as unrecoverable
#   str  → recovered plaintext

_PW_STRENGTH_META: dict[str, tuple[str, str, str]] = {
    "weak":   ("#ff5470", "WEAK ENC",   "MD5"),
    "medium": ("#ffd93d", "MEDIUM ENC", "SHA256"),
    "strong": ("#00ff9f", "STRONG ENC", "bcrypt"),
}


def _password_markup(dossier, cracked_password: str | None,
                     upgrades: set | None = None,
                     prefix_len: int = 14) -> tuple[str, str]:
    """(hash line, state line) for the dossier password field.

    2026-09-14, cipher-block rework: the dossier NO LONGER shows an encryption-
    strength chip at all, upgrade or not. It shows the raw hash and says where
    to go.

    That chip was the single biggest "the game answers its own question"
    surface left in the build. WEAK_ENCRYPTION is a violation about the
    ALGORITHM, and the dossier printed the algorithm for free on every
    candidate — so the kind was, in effect, pre-flagged. It has been retiered
    to HASHCRACK (see candidate_gen._SEVERITY_REVEAL) and establishing the
    algorithm is now something the player does at the cipher block, by reading
    its shape or by buying Cipher ID HUD to have it named THERE.

    `_PW_STRENGTH_META` above is deliberately kept: the rules page renders the
    same three tiers in its reference table, which is where the player learns
    the shapes in the first place. It just no longer decorates the dossier.

    UNSALTED_STORAGE (credential_unsalted) is still handled FIRST and returns
    early — there is no hash to show and nothing to recover, so the entry line
    is simply the plaintext. That kind stays dossier-tier: no salt means the
    stored value really is exposed without any tool at all.
    """
    upgrades = upgrades or ()
    if dossier.credential_unsalted:
        # UNSALTED_STORAGE (moved to dossier tier, 2026-08-16): no salt means
        # the stored value is exposed outright. Don't show an encrypted-
        # looking hash at all here — that reads as "still needs cracking"
        # and papers over the actual finding. ⚠ UNSALTED tags it as the
        # UNSALTED_STORAGE evidence rather than a recovered result.
        head = f"[b #e8f0f8]{dossier.password_plain}[/]  [#ff5470][b]⚠ UNSALTED[/][/]"
        return head, ""
    if not dossier.submitted_hash:
        return "[dim](none)[/]", ""
    head = f"{dossier.submitted_hash[:prefix_len]}…"
    if cracked_password is None:
        state = "[dim]encrypted — open the cipher block on Hashcrack (3)[/]"
    elif cracked_password == "":
        state = "[dim]✓ key-stretched — nothing recoverable[/]"
    else:
        state = f"[#c084fc]recovered →[/]  [b #e8f0f8]{cracked_password}[/]"
    return head, state




def _format_day_rules(rules) -> str:
    """Format the current day's rules for display in the logwatch reference panel."""
    if not rules:
        return "[dim]No rules loaded.[/]"
    lines = ["[#7dd3c0][b]TODAY'S RULES[/][/]"]
    for r in rules:
        sev_col = "#ff5470" if r.severity == "disqualifying" else "#ff8c42"
        lines.append(f"  [{sev_col}]•[/] {r.text}")
    return "\n".join(lines)
