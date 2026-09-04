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

# Reference data shown on the candidate page and tool sidebars
_REF_CANDIDATE = """[#7dd3c0][b]COMMANDS — CANDIDATE[/][/]

[#00ff9f]admit[/]  [dim]or[/] [#00ff9f]a[/]
  approve this candidate's access

[#ff5470]deny[/]  [dim]or[/] [#ff5470]d[/]
  reject this candidate's access

[#7dd3c0]next[/]  [dim]or[/] [#7dd3c0]n[/]
  move to next candidate

[dim]── tools ───────────────────────────[/]
[#00ff9f]recon[/]   run ghostscan  [dim](page 2)[/]
[#00ff9f]crack[/]   run hashcrack  [dim](page 3)[/]
[#00ff9f]analyze[/] run logwatch   [dim](page 4)[/]
[#00ff9f]extract[/] stego stamp mode [dim](page 5)[/]

[dim]── other ──────────────────────────[/]
[#c084fc]reveal[/] spend a HackDox Credit —
  shows this candidate's ground truth
[#6b7785]rules[/]  open rulebook
[#6b7785]help[/]   show command list
[#6b7785]quit[/]   exit game"""

_REF_GHOSTSCAN = """[#7dd3c0][b]COMMANDS — GHOSTSCAN[/][/]

[#00ff9f]recon[/]  [dim]or[/] [#00ff9f]g[/]
  fixed platform sweep — same list
  every day · verify claimed org
  [dim]cost: 5 ⏱[/]

[#c084fc]filter[/]  [dim]or[/] [#c084fc]f[/]
  reveals threat forum entries +
  highlights commit email mismatch +
  explicit ▲ VIOLATION_TYPE labels
  [dim]cost: +3 ⏱[/]

[dim]── forum tiers ──────────────────────[/]
[#ff5470]CRITICAL — immediate deny:[/]
[dim]BreachForums · RaidForums[/]
[dim]HackForums · XSS.is[/]
[#ff8c42]ADVISORY — investigate further:[/]
[dim]nulled.to · CrackingKing[/]
[dim]Dread · CrackingPro[/]

[dim]── verdict ─────────────────────────[/]
[#00ff9f]admit[/] [dim]/[/] [#ff5470]deny[/]  [dim]when ready[/]"""

_REF_HASHCRACK = """[#7dd3c0][b]COMMANDS — HASHCRACK[/][/]

[#00ff9f]crack[/]  [dim]or[/] [#00ff9f]h[/]
  highlight target in shared log
  + crack hash inline in log
  [dim]cost: 3 ⏱[/]

[#c084fc]filter[/]  [dim]or[/] [#c084fc]f[/]
  explicit ▲ violation labels:
  WEAK_CREDENTIAL · LEAKED_PASSWORD
  [dim]cost: +4 ⏱[/]

[dim]── encryption strength ───────────[/]
[#ff5470]WEAK[/]    [dim]MD5 32 hex — cracks instantly[/]
[#ffd93d]MEDIUM[/]  [dim]SHA256 64 hex — crackable[/]
[#00ff9f]STRONG[/]  [dim]bcrypt $2b$ — always safe,
        don't waste ⏱ cracking it[/]
[dim]weak enc + weak password
= WEAK_CREDENTIAL (minor)[/]

[dim]── log events ────────────────────[/]
[dim]AUTH_FAIL/OK  login attempts[/]
[dim]HASH_SUBMIT   hash + source IP[/]
[dim]BREACH_MATCH  corpus hit[/]

[dim]── verdict ─────────────────────[/]
[#00ff9f]admit[/] [dim]/[/] [#ff5470]deny[/]  [dim]when ready[/]"""

_REF_LOGWATCH = """[#7dd3c0][b]COMMANDS — LOGWATCH[/][/]

[#00ff9f]analyze[/]  [dim]or[/] [#00ff9f]logwatch[/]  [dim]or[/] [#00ff9f]l[/]
  pattern detection — brute force,
  geo anomalies, after-hours events
  [dim]cost: 4 ⏱[/]

[#c084fc]filter[/]  [dim]or[/] [#c084fc]f[/]
  geographic timeline overlay —
  explicit BRUTE_FORCE /
  IMPOSSIBLE_TRAVEL / INSIDER flag
  [dim]cost: +3 ⏱[/]

[dim]── verdict ─────────────────────────[/]
[#00ff9f]admit[/] [dim]/[/] [#ff5470]deny[/]  [dim]when ready[/]"""

_REF_STEGOTOOL = """[#7dd3c0][b]STEGOTOOL — STAMP MODE[/][/]

[#00ff9f]X[/]  [dim]or[/] [#00ff9f]extract[/] [dim]/[/] [#00ff9f]s[/]
  enter stamp mode on the
  image viewer (right panel)

[#00ff9f]arrows[/]  move the stamp
[#00ff9f]Space[/]   stamp the region
  [dim]cost: 1 ⏱ per stamp[/]
[#00ff9f]Esc[/]     exit stamp mode

[#00ff9f]F[/]  [dim]or[/] [#00ff9f]filter[/]  classify payload
  [dim]cost: 2 ⏱ — names the payload
  type in the stamp log. Without it,
  read the stamp COLOUR yourself.[/]

[dim]── signature colors ────────────────[/]
[#ff8c42]AMBER[/]    plaintext LSB payload
  [dim]dense solid block[/]
[#ff5470]CRIMSON[/]  encrypted payload
  [dim]mid-density, structured[/]
[#c084fc]VIOLET[/]   covert C2 channel
  [dim]sparse scatter, wide zone[/]
[#00ff9f]GREEN[/]    region clean

[dim]── reading the image ───────────────[/]
[dim]nothing is marked for you — sweep
the grid and stamp where the noise
looks wrong. reveal ~60% of a zone
to resolve its ▲ signature.
the Spectral Lens upgrade tints a
rough area blue — close, not exact[/]

[dim]── verdict ─────────────────────────[/]
[#00ff9f]admit[/] [dim]/[/] [#ff5470]deny[/]  [dim]when ready[/]"""


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
# Every dossier shows the submitted password in encrypted form plus its
# encryption-strength tier (derived from the hash shape). After Hashcrack
# runs, the cracked plaintext is shown in place across all pages.
#
# Panel convention for `cracked_password`:
#   None → not attempted yet   ·   "" → attempted, bcrypt held (uncracked)
#   str  → cracked plaintext

_PW_STRENGTH_META: dict[str, tuple[str, str, str]] = {
    "weak":   ("#ff5470", "WEAK ENC",   "MD5"),
    "medium": ("#ffd93d", "MEDIUM ENC", "SHA256"),
    "strong": ("#00ff9f", "STRONG ENC", "bcrypt"),
}


def _password_markup(dossier, cracked_password: str | None,
                     upgrades: set | None = None,
                     prefix_len: int = 14) -> tuple[str, str]:
    """(hash line, state line) for the dossier password field.

    Batch-3 task #4: the [WEAK ENC]/[MEDIUM ENC]/[STRONG ENC] algorithm chip
    is gated behind config.UPGRADE_CRYPTO_ID ("Cipher ID HUD") — without it,
    only the raw hash is shown, and the player has to recognise MD5 (32 hex)
    / SHA256 (64 hex) / bcrypt ($2b$…) by shape, using the rules page's new
    reference examples. This doesn't remove WEAK_ENCRYPTION's evidence (the
    hash itself is still fully visible), it just stops auto-labelling it.

    The "strongest tier is always safe" verdict line is gated separately,
    behind config.UPGRADE_HC_VERDICT ("Crack Verdict Analyzer") — the same
    upgrade that gates the equivalent wording in tools_bridge's Hashcrack
    audit log (#6a), so the dossier and the tool never disagree about
    whether a strength verdict is being told to the player for free.

    Batch-3 follow-up: UNSALTED_STORAGE (credential_unsalted) is handled
    FIRST and returns early — there is no hash-shaped chip to show and
    nothing left to crack, so the Password entry line itself is simply the
    plaintext (no "encrypted — run hashcrack" prompt can ever appear next to
    it, since that line only exists further down in the salted branch).
    """
    upgrades = upgrades or ()
    if dossier.credential_unsalted:
        # UNSALTED_STORAGE (moved to dossier tier, 2026-08-16): no salt means
        # the stored value is exposed outright. Don't show an encrypted-
        # looking hash at all here — that reads as "still needs cracking"
        # and papers over the actual finding. ⚠ UNSALTED tags it as the
        # UNSALTED_STORAGE evidence rather than a cracked result.
        head = f"[b #e8f0f8]{dossier.password_plain}[/]  [#ff5470][b]⚠ UNSALTED[/][/]"
        return head, ""
    strength = tools_bridge.password_strength(dossier.submitted_hash)
    if strength is None:
        return "[dim](none)[/]", ""
    col, label, algo = _PW_STRENGTH_META[strength]
    if config.UPGRADE_CRYPTO_ID in upgrades:
        head = (f"{dossier.submitted_hash[:prefix_len]}…  "
                f"[{col}][b]{label}[/][/] [#6b7785]{algo}[/]")
    else:
        head = f"{dossier.submitted_hash[:prefix_len]}…"
    if cracked_password is None:
        state = "[dim]encrypted — run hashcrack (H) to attempt crack[/]"
    elif cracked_password == "":
        if config.UPGRADE_HC_VERDICT in upgrades:
            state = "[#00ff9f]✓ uncracked — strongest tier is always safe[/]"
        else:
            state = "[dim]✓ crack abandoned — no plaintext recovered[/]"
    else:
        state = f"[#c084fc]cracked →[/]  [b #e8f0f8]{cracked_password}[/]"
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
