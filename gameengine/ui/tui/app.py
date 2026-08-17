"""HackDox Terminal — Textual TUI.

Page-based layout. Five pages + Rules overlay:

  1  CANDIDATE  — Dossier · Chat · Evidence Board · Overseer · Reference
  2  GHOSTSCAN  — Condensed Dossier · Reference · Tool Terminal
  3  HASHCRACK  — Condensed Dossier · Reference · Tool Terminal
  4  LOGWATCH   — Condensed Dossier · Reference · Tool Terminal
  5  STEGOTOOL  — Condensed Dossier · Reference · Tool Terminal
  0  RULES      — Full day rulebook overlay (dismiss with 0 or Esc)

Key principles:
  • Number keys 1-5 switch pages; arrow keys navigate focus between panels.
  • The Evidence Board is player-controlled only — nothing auto-populates.
  • Tool keys (G/L/H/S) jump to that page and run the tool in one keystroke.
  • A/D verdict keys work on every page.
  • Filters (F key on any tool page) run an enhanced analysis at extra ⏱ cost.
  • Computing hours (⏱) replace currency throughout.
  • All key bindings live in config.KEY_BINDINGS — change them there.
"""

from __future__ import annotations

import random
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.events import Key
from textual.message import Message
from textual.screen import ModalScreen, Screen
from textual.widgets import ContentSwitcher, Footer, Static, TabbedContent, TabPane

from gameengine import config
from gameengine.core import (candidate_gen, persistence, rules_engine, scoring,
                             tools_bridge)

# Shortcut so BINDINGS class attributes can be built from config at import time.
_B = config.KEY_BINDINGS
from gameengine.core.content_loader import load_day, load_narratives
from gameengine.core.models import (
    Candidate,
    CandidateResult,
    Day,
    Discrepancy,
    DiscrepancyKind,
    GameState,
    Performance,
    ToolName,
    Verdict,
)

# ─── Evidence board item catalog ─────────────────────────────────────────────
# Single-sourced from rules_content (issue #30): the Evidence Board and the
# Rules Pages tables render from the SAME catalog, so changing a violation
# there updates labels, colours, and sorting everywhere at once.

from gameengine.ui.tui import rules_content

EVIDENCE_ITEMS: list[tuple[str, DiscrepancyKind, str]] = list(
    rules_content.VIOLATION_CATALOG)
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
_GROUP_ORDER = ["DOSSIER", "OSINT", "CREDENTIAL", "FORENSICS", "STEGO"]
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

# Order the catalog: groups in _GROUP_ORDER, and within each group by severity
# ascending (minor → major → critical) so the board reads calm-to-alarming.
_SEV_RANK = {"minor": 0, "major": 1, "critical": 2}
EVIDENCE_ITEMS.sort(key=lambda it: (
    _GROUP_ORDER.index(it[0]),
    _SEV_RANK.get(_SEVERITY.get(it[1], "minor"), 0),
))

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
                     prefix_len: int = 14) -> tuple[str, str]:
    """(hash line, state line) for the dossier password field."""
    strength = tools_bridge.password_strength(dossier.submitted_hash)
    if strength is None:
        return "[dim](none)[/]", ""
    col, label, algo = _PW_STRENGTH_META[strength]
    head = (f"{dossier.submitted_hash[:prefix_len]}…  "
            f"[{col}][b]{label}[/][/] [#6b7785]{algo}[/]")
    if dossier.credential_unsalted:
        # UNSALTED_STORAGE (moved to dossier tier, 2026-08-16): no salt means
        # the stored value is exposed outright — shown here immediately, no
        # Hashcrack run required. Running Hashcrack anyway just confirms it.
        head += "  [#ff5470][b]⚠ UNSALTED[/][/]"
        state = (f"[#ff5470]no salt — stored value exposed:[/]  "
                 f"[b #e8f0f8]{dossier.password_plain}[/]")
        return head, state
    if cracked_password is None:
        state = "[dim]encrypted — run hashcrack (H) to attempt crack[/]"
    elif cracked_password == "":
        state = "[#00ff9f]✓ uncracked — strongest tier is always safe[/]"
    else:
        state = f"[#c084fc]cracked →[/]  [b #e8f0f8]{cracked_password}[/]"
    return head, state


class StatusHeader(Static):
    """One-line status + page-tab strip."""

    can_focus = False

    def __init__(self, state: GameState, day: Day, slot_index: int,
                 page_index: int = 0) -> None:
        super().__init__(id="status-header")
        self.state       = state
        self.day         = day
        self.slot_index  = slot_index
        self.page_index  = page_index

    def render(self) -> str:
        h    = self.state.site_health
        hcol = ("#00ff9f" if h >= config.SITE_HEALTH_REWARD_THRESHOLD else
                "#ffd93d" if h >= config.SITE_HEALTH_LOSS_THRESHOLD + 15 else
                "#ff5470")
        # ⏱ is a finite daily pool now (issue #27) — colour the balance by
        # scarcity and keep every tool's effective cost in view.
        cp   = self.state.compute_hours
        ccol = "#ffb454" if cp >= 15 else "#ff8c42" if cp >= 6 else "#ff5470"
        costs = "·".join(
            f"{k}{tools_bridge.tool_cost(self.state, t)}"
            for k, t in (("G", "ghostscan"), ("H", "hashcrack"),
                         ("L", "logwatch"),  ("S", "stegotool"))
        )
        creds = ("▮" * self.state.hackdox_credits
                 + "▯" * max(0, config.HACKDOX_CREDIT_MAX - self.state.hackdox_credits))
        # Health only moves at end of day (#20 rework) — show the pending
        # delta accumulated by today's verdicts so the player can track it.
        pend = sum(r.site_health_delta for r in self.state.pending_results)
        pend_s = f" [dim]({pend:+.1f} eod)[/]" if pend else ""
        align  = self.state.alignment
        bar    = ""
        for v in range(-4, 5):
            bar += "●" if v == max(-4, min(4, align)) else "·"
        def _tab(i: int, n: str) -> str:
            tool = _PAGE_TOOL[i]
            if tool is not None and tool not in self.state.unlocked_tools:
                # Locked tool (#33): dim + ⊘, visibly distinct from an
                # unlocked-but-inactive tab (○) and the active tab (◉).
                return f"[#3d4450]⊘ [{i+1}]{n}[/]"
            if i == self.page_index:
                return f"[b]◉ [{i+1}]{n}[/]"
            return f"[dim]○ [{i+1}]{n}[/]"

        tabs = "  ".join(_tab(i, n) for i, n in enumerate(_PAGE_NAMES))
        # Two-line layout: player resources & standings up top, the page
        # tab strip on its own line beneath.
        return (
            f"[#00ff9f][b]HACKDOX[/][/]  [dim]│[/]  [b]{self.day.title}[/]  "
            f"[dim]│[/]  [{self.slot_index + 1}/{self.day.candidate_count}]  "
            f"[dim]│[/]  [{ccol}]{cp} ⏱[/] [dim]{costs}[/]  "
            f"[{hcol}]⛨{h:.0f}%[/]{pend_s}  "
            f"[#00ff9f]{self.state.hackdollars}$[/]  "
            f"[#c084fc]{creds}[/]  "
            f"[{'#ff5470' if align < 0 else '#00ff9f'}]{bar}[/]"
            f"\n{tabs}"
        )

    def refresh_status(self, state: GameState, slot_index: int,
                       page_index: int) -> None:
        self.state      = state
        self.slot_index = slot_index
        self.page_index = page_index
        self.refresh()


class DossierPanel(Static):
    """Full candidate identity packet — candidate page only."""

    can_focus = True

    def __init__(self) -> None:
        super().__init__(id="dossier", classes="panel")
        self.border_title = " Dossier "
        self._candidate: Candidate | None = None
        self.upgrades: set = set()   # auto-highlight upgrades (issue #23)
        self.cracked_password: str | None = None   # issue #29 password state

    def set_candidate(self, candidate: Candidate) -> None:
        self._candidate = candidate
        self.refresh()

    def render(self) -> str:
        if self._candidate is None:
            return "[dim]No candidate loaded.[/]"
        c, d = self._candidate, self._candidate.dossier
        gh   = d.claimed_github       or "[dim](none)[/]"
        ip   = d.claimed_ip           or "[dim](none)[/]"
        img  = d.submitted_image_path or "[dim](none)[/]"
        pw_head, pw_state = _password_markup(d, self.cracked_password,
                                             prefix_len=20)
        rows = [
            "[#3d6478]-- identity ------------------------------------------[/]",
            f"  [#6b7785]Name[/]         [b]{c.display_name}[/]",
            f"  [#6b7785]Handle[/]       {c.handle}",
            f"  [#6b7785]Email[/]        {_hl_email(c.email, self.upgrades)}",
            f"  [#6b7785]Affiliation[/]  {_hl_affil(c.claimed_affiliation, self.upgrades)}",
            f"  [#6b7785]GitHub[/]       {gh}",
            "",
            "[#3d6478]-- submitted artifacts --------------------------------[/]",
            f"  [#6b7785]IP[/]           {ip}",
            f"               [dim]breadcrumb — corroborate against Logwatch login IPs before denying[/]",
            f"  [#6b7785]Password[/]     {pw_head}",
            *( [f"               {pw_state}"] if pw_state else [] ),
            f"  [#6b7785]Image[/]        {img}",
            "",
            "[#3d6478]-- stated purpose ------------------------------------[/]",
            f"  [italic]{c.claimed_purpose}[/]",
            "",
            f"[dim]{d.notes}[/]",
        ]
        return "\n".join(rows)


class CondensedDossier(Static):
    """Slim identity strip for tool-page sidebars."""

    can_focus = False

    def __init__(self, widget_id: str) -> None:
        super().__init__(id=widget_id, classes="panel condensed-dossier")
        self.border_title = " Dossier "
        self._candidate: Candidate | None = None
        self.upgrades: set = set()   # auto-highlight upgrades (issue #23)
        self.cracked_password: str | None = None   # issue #29 password state

    def set_candidate(self, candidate: Candidate) -> None:
        self._candidate = candidate
        self.refresh()

    def render(self) -> str:
        if self._candidate is None:
            return "[dim]—[/]"
        c  = self._candidate
        d   = c.dossier
        gh  = d.claimed_github or "[dim](none)[/]"
        ip  = d.claimed_ip     or "[dim](none)[/]"
        img = d.submitted_image_path or "[dim](none)[/]"
        pw_head, pw_state = _password_markup(d, self.cracked_password,
                                             prefix_len=10)
        return "\n".join([
            f"[#6b7785]Name[/]   [b]{c.display_name}[/]",
            f"[#6b7785]Handle[/] {c.handle}",
            f"[#6b7785]Email[/]  {_hl_email(c.email, self.upgrades)}",
            f"[#6b7785]Org[/]    {_hl_affil(c.claimed_affiliation, self.upgrades)}",
            f"[#6b7785]GitHub[/] {gh}",
            "[#3d6478]-- submitted --[/]",
            f"[#6b7785]IP[/]     {ip}",
            f"[#6b7785]Passwd[/] {pw_head}",
            *( [f"       {pw_state}"] if pw_state else [] ),
            f"[#6b7785]Image[/]  {img}",
            "[#3d6478]-- purpose --[/]",
            f"[italic]{c.claimed_purpose}[/]",
        ])


class _TWMessage:
    """One queued TypewriterLog message. Plain class (no dataclass import)."""

    __slots__ = ("speaker", "lines", "color", "icon", "style", "triggers", "prefix")

    def __init__(self, speaker, lines, color, icon, style, triggers, prefix):
        self.speaker = speaker
        self.lines = lines
        self.color = color
        self.icon = icon
        self.style = style
        self.triggers = triggers
        self.prefix = prefix   # verbatim markup rendered before the typed text


class TypewriterLog(Static):
    """Character-by-character message log (#3).

    Reused by the Overseer panel, the candidate Chat panel, and the between-day
    Overseer region. Messages are queued and typed one line at a time.

    **Space advances only while this widget has focus.** The first press
    fast-completes the line being typed; the next steps to the following line
    within the same message. Once every queued line has played, `is_idle`
    becomes True and Space is *not* consumed — so a host screen's own Space
    binding (buy in the shop, begin/continue on the briefing/EOD screens, stamp
    on the stego page) still fires. This is the focus-scoped advance the issue's
    own comment asked for, instead of a screen-level Space binding that would
    collide with those three hosts.

    A message auto-finalizes the instant its LAST line is fully revealed (so a
    side effect never waits on an extra keypress): it posts
    `TypewriterLog.Finished`, carrying that message's `triggers` payload, which
    is exactly the hook #34's tool-unlock beat rides. One-way: the widget never
    accepts text input.
    """

    can_focus = True
    DEFAULT_CHAR_DELAY = 0.02

    class Finished(Message):
        """Posted when a queued message's last line finishes. `triggers` is
        whatever the caller handed to `post(...)` (None if it had none)."""

        def __init__(self, log: "TypewriterLog", triggers) -> None:
            super().__init__()
            self.log = log
            self.triggers = triggers

    def __init__(self, *, id=None, classes="", char_delay=DEFAULT_CHAR_DELAY):
        # Seed with a space, never "" — an empty Static renders a None visual
        # and crashes layout in current Textual.
        super().__init__(" ", id=id, classes=classes)
        self._char_delay = char_delay
        self._queue: list[_TWMessage] = []
        self._done_lines: list[str] = []      # fully-revealed lines (markup)
        self._active: _TWMessage | None = None
        self._msg_lines: list[str] = []       # remaining lines of _active
        self._is_last_line = False
        self._cur_prefix = ""                 # speaker/icon markup for current line
        self._cur_full = ""                   # plain text of the line being typed
        self._shown = 0                       # chars of _cur_full revealed
        self._cur_color = "#c8d4e1"
        self._cur_style = ""
        self._line_complete = False
        self._timer = None
        self._unread = False

    # ── Public API ────────────────────────────────────────────────
    def post(self, speaker, lines, *, color="#c8d4e1", icon="", style="",
             triggers=None, prefix="") -> None:
        """Queue a message. `lines` may be a str or a list of str.

        `lines` must be PLAIN text — it is revealed one character at a time, so
        embedded markup would tear mid-reveal. Per-line rich decoration goes in
        `prefix` (rendered verbatim, not typed); the typed text is wrapped in
        `color`/`style` as a whole.
        """
        if isinstance(lines, str):
            lines = [lines]
        self._queue.append(_TWMessage(speaker, list(lines), color, icon, style,
                                      triggers, prefix))
        if not self.has_focus:
            self._set_unread(True)
        # Kick playback only when fully idle; otherwise it chains automatically.
        if self._active is None and self._timer is None:
            self._begin_next_message()

    def clear_log(self) -> None:
        self._stop_timer()
        self._queue.clear()
        self._done_lines.clear()
        self._active = None
        self._msg_lines = []
        self._cur_full = ""
        self._shown = 0
        self._line_complete = False
        self._set_unread(False)
        self._repaint()

    @property
    def is_idle(self) -> bool:
        """True when nothing is typing and nothing is queued."""
        return (self._active is None and not self._queue
                and self._timer is None and not self._line_complete)

    def advance(self) -> None:
        """Space handler: fast-complete the current line, else step forward."""
        if self._timer is not None:
            self._on_line_revealed()          # fast-complete
        elif self._line_complete:
            self._commit_current_line()
            self._begin_line_or_finish()

    # ── Internal ──────────────────────────────────────────────────
    def _begin_next_message(self) -> None:
        if not self._queue:
            self._active = None
            return
        self._active = self._queue.pop(0)
        self._cur_color = self._active.color
        self._cur_style = self._active.style
        self._msg_lines = list(self._active.lines)
        self._begin_line_or_finish()

    def _begin_line_or_finish(self) -> None:
        if self._msg_lines:
            line = self._msg_lines.pop(0)
            self._is_last_line = not self._msg_lines
            self._begin_line(line)
        else:
            self._finish_message()

    def _begin_line(self, text: str) -> None:
        icon = (self._active.icon + " ") if (self._active and self._active.icon) else ""
        spk = self._active.speaker if self._active else ""
        explicit_prefix = self._active.prefix if self._active else ""
        if explicit_prefix:
            self._cur_prefix = explicit_prefix
        elif spk:
            self._cur_prefix = f"[{self._cur_color}][b]{icon}{spk}:[/][/]  "
        else:
            self._cur_prefix = icon
        self._cur_full = text
        self._shown = 0
        self._line_complete = False
        self._repaint()
        # A blank line has nothing to type — reveal it immediately.
        if not text:
            self._on_line_revealed()
        else:
            self._timer = self.set_interval(self._char_delay, self._tick)

    def _tick(self) -> None:
        self._shown += 1
        if self._shown >= len(self._cur_full):
            self._on_line_revealed()
        else:
            self._repaint()

    def _on_line_revealed(self) -> None:
        """The current line is fully shown (typed out or fast-completed)."""
        self._stop_timer()
        self._shown = len(self._cur_full)
        if self._is_last_line:
            self._repaint()
            self._finish_message()            # auto-finalize — no extra keypress
        else:
            self._line_complete = True
            self._repaint()

    def _commit_current_line(self) -> None:
        col, sty = self._cur_color, self._cur_style
        body = (f"[{col} {sty}]{self._cur_full}[/]" if sty
                else f"[{col}]{self._cur_full}[/]")
        self._done_lines.append(self._cur_prefix + body)
        self._cur_full = ""
        self._shown = 0
        self._cur_prefix = ""
        self._line_complete = False

    def _finish_message(self) -> None:
        if self._cur_full:
            self._commit_current_line()
        triggers = self._active.triggers if self._active else None
        self._active = None
        self._line_complete = False
        self._repaint()
        self.post_message(TypewriterLog.Finished(self, triggers))
        self._begin_next_message()            # chain any queued message

    def _repaint(self) -> None:
        lines = list(self._done_lines)
        if self._cur_full:
            partial = self._cur_full[:self._shown]
            col, sty = self._cur_color, self._cur_style
            body = (f"[{col} {sty}]{partial}[/]" if sty else f"[{col}]{partial}[/]")
            caret = "" if self._line_complete else "[dim]▌[/]"
            lines.append(self._cur_prefix + body + caret)
        # TypewriterLog is a Static leaf — render straight into its own content.
        # Never push "" (empty renders a None visual and crashes layout).
        self.update("\n".join(lines) or " ")

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _set_unread(self, val: bool) -> None:
        self._unread = val
        base = (self.border_title or "").rstrip(" ●")
        if base:
            self.border_title = f"{base} ●" if val else base

    def on_focus(self) -> None:
        self._set_unread(False)

    def on_key(self, event: Key) -> None:
        # Focus-scoped advance: consume Space only while there's dialogue left
        # to play; once idle, let it bubble so the host screen's Space fires.
        if event.key == "space" and not self.is_idle:
            self.advance()
            event.stop()


class ChatPanel(TypewriterLog):
    """One-way candidate dialogue, played through the TypewriterLog (#3).

    The whole script is posted as a single message so Space steps line-by-line
    within it (per the widget contract); the player never types back.
    """

    def __init__(self) -> None:
        super().__init__(id="chat")
        self.classes = "panel"
        self.border_title = " Chat "
        self.upgrades: set = set()   # Sentiment Scanner upgrade (issue #23)

    _TAG_STYLE: dict[str, tuple[str, str]] = {
        "neutral":  ("#c8d4e1", ""),
        "warm":     ("#7dd3c0", ""),
        "hostile":  ("#ff5470", "bold"),
        "flippant": ("#c084fc", "italic"),
        "earnest":  ("#7dd3c0", ""),
        "intro":    ("#c8d4e1", "italic"),
    }

    def set_candidate(self, candidate: Candidate) -> None:
        self.clear_log()
        first = candidate.display_name.split()[0]
        for line in candidate.chat_script:
            tag = line.tag
            if tag.startswith("hint:"):
                col, sty = "#ff8c42", "italic"
            else:
                col, sty = self._TAG_STYLE.get(tag, ("#c8d4e1", ""))
            # Sentiment Scanner upgrade (issue #23): ⚠-mark hostile text.
            warn = ("[#ff5470][b]⚠ [/][/]"
                    if tag == "hostile" and config.UPGRADE_CHAT_HOSTILE in self.upgrades
                    else "")
            prefix = f"[#6b7785]{line.timestamp}[/]  [b]{first}:[/]  {warn}"
            # Each chat line is its own message: the timestamp/name go in the
            # verbatim prefix, the plain line text is what types out (wrapped in
            # the tag colour). Messages auto-chain, so the script streams in.
            self.post("", line.text, color=col, style=sty, prefix=prefix)


class EvidenceState:
    """Shared evidence record for the current candidate.

    The state lives here, not in the widget, so a single record can be
    displayed by several `EvidenceBoard` views at once — the inline board on
    the Candidate page plus the toggleable board on each tool page — and they
    all stay in sync.

    Each violation has one of three states, cycled with Space:
        "unknown" (default, not recorded) → "marked" (present) → "absent"
        (ruled out) → "unknown" …
    Only "marked" kinds feed scoring, so the contract is unchanged:
    `get_flags()` still returns the `set[DiscrepancyKind]` the player asserts
    are present.
    """

    STATES = ("unknown", "marked", "absent")

    def __init__(self) -> None:
        # kind → "marked" | "absent"; unknown kinds are simply absent from dict.
        self._states: dict[DiscrepancyKind, str] = {}

    def clear(self) -> None:
        self._states.clear()

    def cycle(self, kind: DiscrepancyKind) -> None:
        """Advance a violation through unknown → marked → absent → unknown."""
        cur = self._states.get(kind)          # None == unknown
        if cur is None:
            self._states[kind] = "marked"
        elif cur == "marked":
            self._states[kind] = "absent"
        else:                                  # "absent" → unknown
            self._states.pop(kind, None)

    def state_of(self, kind: DiscrepancyKind) -> str:
        return self._states.get(kind, "unknown")

    def is_flagged(self, kind: DiscrepancyKind) -> bool:
        return self._states.get(kind) == "marked"

    def get_flags(self) -> set[DiscrepancyKind]:
        # Scoring contract: only "marked" kinds count as player-asserted.
        return {k for k, v in self._states.items() if v == "marked"}


class EvidenceBoard(VerticalScroll):
    """Player-controlled evidence checklist (a *view* over EvidenceState).

    A scrollable container so every item stays reachable regardless of
    terminal height. Nothing is ever written here automatically. The player
    uses ↑↓ to move the cursor and Space to toggle a flag. ← / → are NOT
    consumed here — they bubble up to the screen for page navigation.

    Several boards share one `EvidenceState`, so flagging a finding on a tool
    page is immediately reflected on the Candidate page board and vice versa.
    Each view keeps its own cursor. Content lives in an inner `Static`
    (`self._content`) so the container can scroll it.
    """

    can_focus = True

    def __init__(self, state: "EvidenceState", widget_id: str = "evidence-board",
                 classes: str | None = None, summary: bool = False,
                 home_group: str | None = None) -> None:
        super().__init__(id=widget_id, classes=classes)
        # Summary mode (Candidate page): read-only — lists only the violations
        # the player has flagged. Editable mode (tool pages): full checklist.
        self._summary = summary
        self._home_group = home_group
        if summary:
            self.can_focus = False
            self.border_title = " FLAGGED EVIDENCE "
        else:
            self.border_title = " EVIDENCE BOARD  [dim](↑↓ move · Space flag)[/] "
        self._state = state
        self._cursor: int = 0
        self._focused: bool = False
        self._cursor_line: int = 0
        self._content = Static(id=f"{widget_id}-content")

    def compose(self) -> ComposeResult:
        yield self._content

    def on_mount(self) -> None:
        self.repaint()

    # ── State management ──────────────────────────────────────────────

    def repaint(self) -> None:
        """Rebuild the inner Static and keep the cursor row in view."""
        self._content.update(self._render_text())
        if not self._summary and self._focused:
            try:
                self.scroll_to(y=max(0, self._cursor_line - 3), animate=False)
            except Exception:
                pass

    def reset_cursor(self) -> None:
        """Reset this view's cursor and repaint (flags are cleared on the
        shared state separately, then all views are repainted)."""
        self._cursor = 0
        self.repaint()
        try:
            self.scroll_home(animate=False)
        except Exception:
            pass

    def focus_home_group(self) -> None:
        """Jump the cursor to this board's home group and scroll to it — used
        when the board is toggled open on a tool page so the relevant group is
        visible immediately."""
        if self._home_group:
            for idx, (group, _k, _l) in enumerate(EVIDENCE_ITEMS):
                if group == self._home_group:
                    self._cursor = idx
                    break
        self.repaint()

    def get_flags(self) -> set[DiscrepancyKind]:
        return self._state.get_flags()

    # ── Focus tracking ────────────────────────────────────────────────

    def on_focus(self) -> None:
        self._focused = True
        self.repaint()

    def on_blur(self) -> None:
        self._focused = False
        self.repaint()

    # ── Key handling ──────────────────────────────────────────────────

    def on_key(self, event: Key) -> None:
        if self._summary:
            return   # read-only summary — editing happens on tool pages
        if event.key == "up":
            self._cursor = max(0, self._cursor - 1)
            event.stop()
            self.repaint()
        elif event.key == "down":
            self._cursor = min(_ITEM_COUNT - 1, self._cursor + 1)
            event.stop()
            self.repaint()
        elif event.key == "space":
            kind = EVIDENCE_ITEMS[self._cursor][1]
            # Cycle: unknown → marked → absent → unknown.
            self._state.cycle(kind)
            event.stop()
            self.repaint()  # immediate repaint for this board
            # Repaint other board views so shared state stays in sync.
            for board in self.app.query(EvidenceBoard):
                if board is not self:
                    board.repaint()
        # ← / → are NOT stopped — they bubble to IntakeScreen for page nav.

    # ── Rendering ─────────────────────────────────────────────────────

    def _render_text(self) -> str:
        if self._summary:
            return self._render_summary()
        lines: list[str] = []
        current_group = ""
        # Left gutter reserved for a prominent flag indicator; text is then
        # indented so it sits nearer the centre of the panel.
        INDENT = "   "
        for idx, (group, kind, label) in enumerate(EVIDENCE_ITEMS):
            if group != current_group:
                gcolor, hotkey = _GROUP_META.get(group, ("#7dd3c0", ""))
                hint = f"  [dim on #10161d] {hotkey} [/]" if hotkey else ""
                if current_group:
                    lines.append("")  # spacer between groups
                lines.append(f"  [{gcolor}][b]▎ {group}[/][/]{hint}")
                current_group = group

            state     = self._state.state_of(kind)
            at_cursor = idx == self._cursor and self._focused
            sev       = _sev_color(kind)

            # 4-column gutter carries the state indicator:
            #   marked  → bold severity bar  (present)
            #   absent  → muted ✗ marker     (ruled out)
            #   unknown → blank              (no icon)
            if state == "marked":
                gutter = f"[{sev}][b]▐██▌[/][/]"
            elif state == "absent":
                gutter = "[#6b7785] ✗  [/]"
            else:
                gutter = "    "

            if at_cursor:
                self._cursor_line = len(lines)
                lines.append(f"{gutter}{INDENT}[reverse] {label} [/]")
            elif state == "marked":
                lines.append(f"{gutter}{INDENT}[{sev}][b]{label}[/][/]")
            elif state == "absent":
                lines.append(f"{gutter}{INDENT}[#6b7785][strike]{label}[/][/]")
            else:
                lines.append(f"{gutter}{INDENT}[{sev}]{label}[/]")

        if not self._focused:
            lines.append("")
            lines.append("  [dim]Tab to focus · ↑↓ move · Space cycles unknown/marked/absent[/]")
        return "\n".join(lines)

    def _render_summary(self) -> str:
        """Candidate-page view: a horizontal category strip across the top,
        then the violations the player has recorded — marked (present) in
        severity colour, absent (ruled out) muted and struck through."""
        marked = self._state.get_flags()
        recorded = [(g, k, l) for g, k, l in EVIDENCE_ITEMS
                    if self._state.state_of(k) != "unknown"]
        marked_groups = {g for g, k, _l in EVIDENCE_ITEMS if k in marked}

        # Category strip — all groups across the top; those with a marked
        # (present) violation are lit.
        chips: list[str] = []
        for g in _GROUP_ORDER:
            gcolor, _hk = _GROUP_META[g]
            if g in marked_groups:
                chips.append(f"[{gcolor}][b] {g} [/][/]")
            else:
                chips.append(f"[#3a4a58] {g} [/]")
        lines: list[str] = ["  ".join(chips),
                            "[#1c2733]" + "─" * 46 + "[/]", ""]

        if not recorded:
            lines.append("[dim]No evidence recorded for this candidate.[/]")
            lines.append("")
            lines.append("[dim]Open a tool page and press [b]Tab[/] to record evidence.[/]")
            return "\n".join(lines)

        current_group = ""
        for group, kind, label in recorded:
            if group != current_group:
                gcolor, _hk = _GROUP_META.get(group, ("#7dd3c0", ""))
                lines.append(f"[{gcolor}][b]▎ {group}[/][/]")
                current_group = group
            if self._state.state_of(kind) == "marked":
                sev = _sev_color(kind)
                lines.append(f"    [{sev}][b]▲ {label}[/][/]")
            else:  # absent — ruled out
                lines.append(f"    [#6b7785]✗ [strike]{label}[/][/]")
        n_m = len(marked)
        n_a = len(recorded) - n_m
        lines.append("")
        lines.append(f"[dim]{n_m} marked · {n_a} ruled out[/]")
        return "\n".join(lines)


class OverseerPanel(Static):
    """Overseer dialogue + running stats."""

    can_focus = False

    def __init__(self, intro_text: str) -> None:
        super().__init__(id="overseer-side")
        self.border_title = " Overseer "
        self._intro      = intro_text
        self._admits     = 0
        self._denies     = 0
        self._correct    = 0
        self._total      = 0
        self._compute_spent = 0

    def record_result(self, result: CandidateResult, compute_before: int,
                      compute_after: int) -> None:
        if result.player_verdict == Verdict.ADMIT:
            self._admits += 1
        else:
            self._denies += 1
        if result.correct:
            self._correct += 1
        self._total += 1
        # Issue #27: verdicts never grant ⏱, so spend is a simple difference.
        self._compute_spent += max(0, compute_before - compute_after)
        self.refresh()

    def reset(self) -> None:
        self._admits = self._denies = self._correct = self._total = 0
        self._compute_spent = 0
        self.refresh()

    def render(self) -> str:
        accuracy = (
            f"{round(100 * self._correct / self._total)}%"
            if self._total else "—"
        )
        lines = [
            f"[italic #c8d4e1]{self._intro}[/]",
            "",
            f"[#6b7785]Admits[/]    [#7dd3c0]{self._admits}[/]   "
            f"[#6b7785]Denies[/] [#7dd3c0]{self._denies}[/]",
            f"[#6b7785]Accuracy[/]  [#7dd3c0]{accuracy}[/]",
            f"[#6b7785]⏱ spent[/]   [#ffb454]{self._compute_spent}[/]",
        ]
        return "\n".join(lines)



def _format_day_rules(rules) -> str:
    """Format the current day's rules for display in the logwatch reference panel."""
    if not rules:
        return "[dim]No rules loaded.[/]"
    lines = ["[#7dd3c0][b]TODAY'S RULES[/][/]"]
    for r in rules:
        sev_col = "#ff5470" if r.severity == "disqualifying" else "#ff8c42"
        lines.append(f"  [{sev_col}]•[/] {r.text}")
    return "\n".join(lines)


class ReferencePanel(Static):
    """Accept/reject reference data — content varies by mode."""

    can_focus = True

    _CONTENT: dict[str, str] = {
        "candidate": _REF_CANDIDATE,
        "ghostscan": _REF_GHOSTSCAN,
        "hashcrack": _REF_HASHCRACK,
        "logwatch":  _REF_LOGWATCH,
        "stegotool": _REF_STEGOTOOL,
    }

    def __init__(self, mode: str, widget_id: str) -> None:
        super().__init__(id=widget_id, classes="panel")
        self.border_title = " Reference "
        self._mode = mode

    def update_content(self, text: str) -> None:
        """Override static content with dynamic text (e.g. auth log)."""
        self._override = text
        self.refresh()

    def render(self) -> str:
        if hasattr(self, "_override") and self._override is not None:
            return self._override
        return self._CONTENT.get(self._mode, "")


class ToolTerminal(VerticalScroll):
    """Displays results for one tool. Persists for the candidate review."""

    _EMPTY = "[dim italic]Run the tool to see results here.[/]"

    def __init__(self, widget_id: str, tool_label: str) -> None:
        super().__init__(id=widget_id, classes="panel tool-right")
        self.border_title = f" {tool_label} Terminal "
        self._empty_label: Static | None = None

    def compose(self) -> ComposeResult:
        self._empty_label = Static(self._EMPTY, classes="terminal-empty")
        yield self._empty_label

    def clear(self) -> None:
        self.remove_children()
        self._empty_label = Static(self._EMPTY, classes="terminal-empty")
        self.mount(self._empty_label)

    def set_initial_content(self, lines: tuple[str, ...]) -> None:
        """Pre-populate with always-visible lines (no tool cost).
        Clears any previous state first; subsequent add_result calls append below.
        """
        self.remove_children()
        self._empty_label = None
        self.mount(Static("\n".join(lines), classes="terminal-row"))

    def add_result(self, result: tools_bridge.ToolResult) -> None:
        if self._empty_label is not None:
            self._empty_label.remove()
            self._empty_label = None

        sev_color = {"minor": "#ffd93d", "major": "#ff8c42", "critical": "#ff5470"}
        rows: list[str] = []

        # ── Header ────────────────────────────────────────────────────
        if result.filtered:
            rows.append(
                f"[#c084fc][b]FILTER APPLIED[/][/]  [italic]{result.summary}[/]"
            )
        else:
            rows.append(
                f"[#7dd3c0][b]{result.tool.value.upper()}[/][/]  "
                f"[italic]{result.summary}[/]"
            )

        # ── Raw data block ────────────────────────────────────────────
        # Intermediate output (e.g. ghostscan platform sweep, commit email,
        # HIBP result). Player reads this and draws their own conclusions.
        if result.raw_lines:
            rows.append("")
            rows.extend(result.raw_lines)

        # ── Confirmed findings ────────────────────────────────────────
        # Only populated by filter runs that explicitly confirm a discrepancy.
        if result.findings:
            rows.append("")
            rows.append("[#6b7785]── confirmed findings ─────────────────────────[/]")
            for d in result.findings:
                col = sev_color.get(d.severity, "#c8d4e1")
                rows.append(
                    f"  [{col}]●[/] [b]{d.kind.value}[/]"
                    f" [dim]({d.severity})[/] — {d.description}"
                )

        rows.append("")
        self.mount(Static("\n".join(rows), classes="terminal-row"))

    def set_result(self, result: tools_bridge.ToolResult) -> None:
        """REPLACE the terminal content with one result (issue #28 — the
        ghostscan filter re-renders the report in place instead of stacking
        a second copy below the first)."""
        self.remove_children()
        self._empty_label = None
        self.add_result(result)
        self.scroll_home(animate=False)

    def add_lines(self, lines: list[str] | tuple[str, ...]) -> None:
        """Append a raw markup block (used by the stego stamp log)."""
        if self._empty_label is not None:
            self._empty_label.remove()
            self._empty_label = None
        block = Static("\n".join(lines) + "\n", classes="terminal-row")
        self.mount(block)
        self.scroll_end(animate=False)

    def add_no_submission(self, label: str) -> None:
        if self._empty_label is not None:
            self._empty_label.remove()
            self._empty_label = None
        self.mount(Static(
            f"[#6b7785][italic]No {label} submitted by this candidate.[/][/]",
            classes="terminal-empty"
        ))


class BreachListPanel(VerticalScroll):
    """Right-side panel on the Ghostscan page showing scrollable breach database lists.

    Three display states:
      idle        — all entries in dim grey; player scans manually
      highlighted — candidate's email highlighted in orange after base ghostscan run
      confirmed   — candidate's email red + ▲ BREACH_HIT label after filter
    """

    _STATE_IDLE        = "idle"
    _STATE_HIGHLIGHTED = "highlighted"
    _STATE_CONFIRMED   = "confirmed"

    def __init__(self) -> None:
        super().__init__(id="breach-list-panel", classes="panel")
        self.border_title = " Breach Databases "
        self._scan_state: str = self._STATE_IDLE
        self._lists: list[tuple[str, str, str, list[tuple[str, bool]]]] = []
        self._content: Static | None = None

    def compose(self) -> ComposeResult:
        self._content = Static(
            "[dim italic]Awaiting candidate...[/]",
            id="breach-content",
        )
        yield self._content

    # ── Public API ────────────────────────────────────────────────────────

    def load_candidate(self, candidate: "Candidate") -> None:
        """Populate lists for a new candidate and reset to idle state."""
        self._scan_state = self._STATE_IDLE
        self._lists = tools_bridge.get_breach_lists(candidate)
        self._rebuild_content()

    def highlight_match(self) -> None:
        """After base ghostscan run — highlight any match in orange."""
        self._scan_state = self._STATE_HIGHLIGHTED
        self._rebuild_content()

    def confirm_match(self) -> None:
        """After filter run — show match in red with explicit ▲ BREACH_HIT label."""
        self._scan_state = self._STATE_CONFIRMED
        self._rebuild_content()

    # ── Content rendering ─────────────────────────────────────────────────
    # NOTE: do NOT name this _render() — that's a Textual base-class method
    # that must return a Visual object; overriding it returns None and crashes.

    def _rebuild_content(self) -> None:
        if self._content is None:
            return

        if not self._lists:
            self._content.update("[dim italic]No data.[/]")
            return

        lines: list[str] = []
        has_any_match = any(m for _, _, _, entries in self._lists for _, m in entries)

        for db_name, _year, count_label, entries in self._lists:
            # db_name is the canonical name, e.g. "Collection #1 (2019)" —
            # identical to what appears in the Hashcrack BREACH_MATCH log entry.
            bar = "─" * max(1, 32 - len(db_name))
            lines.append(f"\n[#3a4a58]── {db_name} {bar}[/]")
            lines.append(f"[#2e3d4f]   {count_label}[/]")

            for email, is_match in entries:
                if is_match:
                    if self._scan_state == self._STATE_CONFIRMED:
                        lines.append(f"  [#ff5470][b]▲ {email}[/][/]  [#ff5470][b]BREACH_HIT[/][/]")
                    elif self._scan_state == self._STATE_HIGHLIGHTED:
                        lines.append(f"  [#ff8c42]► {email}[/]")
                    else:
                        # idle — match present but not revealed; show as normal entry
                        lines.append(f"  [#6b7785]{email}[/]")
                else:
                    lines.append(f"  [#4a5568]{email}[/]")

        # Footer hint
        if has_any_match and self._scan_state == self._STATE_IDLE:
            lines.append("\n[dim]Run [b]recon[/b] to scan, [b]filter[/b] to confirm.[/]")
        elif not has_any_match:
            lines.append("\n[dim]Run [b]recon[/b] to scan these lists.[/]")

        self._content.update("\n".join(lines))
        self.scroll_home(animate=False)


class StegoImagePanel(VerticalScroll):
    """Right column of the Stegotool page — the interactive image viewer.

    Renders the candidate's submitted image as a colored pixel grid
    (tools_bridge.StegoImageData) and hosts the STAMP minigame:

      X       enter/exit stamp mode (handled by IntakeScreen)
      arrows  move the square stamp
      Space   stamp — reveals the cells underneath (−STEGO_STAMP_COST ⏱)

    Revealed cells re-render by what they carry:
      carrier cells → payload-type color (amber/crimson/violet)
      clean cells   → faint green wash
    The subtle free-tier tint over the hot zone is preserved, so a sharp
    eye can still pre-read the image before spending a single ⏱.
    """

    can_focus = False

    _MOVES = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}

    def __init__(self) -> None:
        super().__init__(id="stego-image-panel", classes="panel")
        self.border_title = " Image Viewer "
        self._content: Static | None = None
        self._img: "tools_bridge.StegoImageData | None" = None
        self._revealed: set[tuple[int, int]] = set()
        self._stamp_mode = False
        self._cur_x = 0
        self._cur_y = 0
        self._stamps_used = 0
        self.tint_boost = False   # Spectral Lens upgrade (issue #23)

    def compose(self) -> ComposeResult:
        self._content = Static("[dim italic]Awaiting candidate...[/]",
                               id="stego-image-content")
        yield self._content

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def image(self) -> "tools_bridge.StegoImageData | None":
        return self._img

    @property
    def stamps_used(self) -> int:
        return self._stamps_used

    @property
    def stamp_rect(self) -> tuple[int, int, int, int]:
        return (self._cur_x, self._cur_y,
                config.STEGO_STAMP_W, config.STEGO_STAMP_H)

    def load_candidate(self, candidate: "Candidate", day: int = 1) -> None:
        self._img = tools_bridge.build_stego_image(candidate, day)
        self._revealed = set()
        self._stamp_mode = False
        self._stamps_used = 0
        self._cur_x = self._cur_y = 0
        img = self._img
        self.border_title = (f" Image Viewer — {img.filename} "
                             f"{img.width}×{img.height} {img.img_type} {img.file_kb}KB ")
        self._rebuild_content()

    def enter_stamp_mode(self) -> None:
        self._stamp_mode = True
        self._rebuild_content()

    def exit_stamp_mode(self) -> None:
        self._stamp_mode = False
        self._rebuild_content()

    def move_stamp(self, key: str) -> None:
        if self._img is None or key not in self._MOVES:
            return
        dx, dy = self._MOVES[key]
        self._cur_x = max(0, min(self._img.cols - config.STEGO_STAMP_W,
                                 self._cur_x + dx))
        self._cur_y = max(0, min(self._img.rows - config.STEGO_STAMP_H,
                                 self._cur_y + dy))
        self._rebuild_content()

    def do_stamp(self) -> "tools_bridge.StampResult | None":
        """Evaluate the stamp at the cursor. Caller charges ⏱ first."""
        if self._img is None:
            return None
        x, y, w, h = self.stamp_rect
        res = tools_bridge.evaluate_stamp(self._img, x, y, w, h, self._revealed)
        self._stamps_used += 1
        self._rebuild_content()
        return res

    # ── Content rendering ─────────────────────────────────────────────────
    # NOTE: not named _render() — that's a Textual base-class method.

    def _rebuild_content(self) -> None:
        if self._content is None or self._img is None:
            return
        img = self._img
        sx, sy, sw, sh = self.stamp_rect
        in_zone = (lambda x, y: False) if img.zone is None else (
            lambda x, y, z=img.zone: z[0] <= x < z[0] + z[2] and z[1] <= y < z[1] + z[3])
        # #54: the Spectral Lens advertises a BUFFERED region, not the exact
        # zone. Before this, the free tier tinted exact zone membership, which
        # solved the stamp sweep for nothing and left the 30 HD$ upgrade with
        # only "the same rectangle, bluer" to sell.
        in_hint = (lambda x, y: False) if img.hint_region is None else (
            lambda x, y, h=img.hint_region: h[0] <= x < h[0] + h[2] and h[1] <= y < h[1] + h[3])

        lines: list[str] = []
        for y in range(img.rows):
            row = ""
            for x in range(img.cols):
                r, g, b = img.base_rgb[y][x]
                revealed = (x, y) in self._revealed
                zone_cell = in_zone(x, y)
                hint_cell = in_hint(x, y)

                if revealed and (x, y) in img.carrier:
                    # Payload-type color with deterministic jitter
                    j = (x * 7 + y * 13) % 41
                    if img.kind is DiscrepancyKind.COVERT_C2_CHANNEL:
                        r, g, b = 150 + j // 2, 85 + j // 3, 235
                    elif img.kind is DiscrepancyKind.ENCRYPTED_PAYLOAD:
                        r, g, b = 210 + j // 2, 25 + j // 3, 10 + j // 4
                    else:  # STEGO_PAYLOAD_PRESENT
                        r, g, b = 185 + j, 75 + j // 2, 15 + j // 4
                elif revealed and zone_cell:
                    # Disturbed noise inside the zone but no carrier bit
                    r = min(255, r + 20); b = min(255, b + 20)
                elif revealed:
                    # Confirmed clean — faint green wash
                    g = min(255, g + 45); r = max(0, r - 10); b = max(0, b - 10)
                elif hint_cell and self.tint_boost:
                    # #54: the Spectral Lens (issue #23) is now the ONLY thing
                    # that tints, and it tints the buffered region rather than
                    # the exact zone — it narrows the search, it doesn't answer
                    # it. Base tier deliberately shows nothing: sweeping blind
                    # is the stamp minigame, and disclosing the exact rectangle
                    # for free was the reason it had no bite.
                    b = min(255, b + 55); r = max(0, r - 22)

                # Stamp cursor overlay
                if self._stamp_mode and sx <= x < sx + sw and sy <= y < sy + sh:
                    on_edge = (x in (sx, sx + sw - 1) or y in (sy, sy + sh - 1))
                    if on_edge:
                        row += "[#00ffd5]▒[/]"
                        continue
                    r = min(255, r + 45); g = min(255, g + 45); b = min(255, b + 45)

                r = max(0, min(255, r)); g = max(0, min(255, g)); b = max(0, min(255, b))
                row += f"[#{r:02x}{g:02x}{b:02x}]█[/]"
            lines.append(row)

        lines.append("")
        spent = self._stamps_used * config.STEGO_STAMP_COST
        if self._stamp_mode:
            lines.append(f"[#00ffd5][b]STAMP MODE[/][/]  [dim]@ ({sx},{sy})[/]  "
                         f"[dim]arrows move · Space stamp (−{config.STEGO_STAMP_COST} ⏱) · Esc exit[/]")
        else:
            lines.append(f"[dim]Press [b]X[/] to enter stamp mode[/]")
        lines.append(f"[dim]stamps: {self._stamps_used} · spent: {spent} ⏱ · "
                     f"revealed: {len(self._revealed)} px[/]")
        self._content.update("\n".join(lines))


class DebugPanel(Static):
    """DEV MODE — ground-truth answer key. Toggle with ` (backtick)."""

    can_focus = True

    def __init__(self) -> None:
        super().__init__(id="debug-panel", classes="panel")
        self.border_title = " ⚠  DEV — Ground Truth "
        self._candidate: Candidate | None = None
        self.display = False

    def set_candidate(self, candidate: Candidate) -> None:
        self._candidate = candidate
        self.refresh()

    def render(self) -> str:
        if self._candidate is None:
            return "[dim]No candidate.[/]"
        c  = self._candidate
        t  = c.truth
        sev = {"minor": "#ffd93d", "major": "#ff8c42", "critical": "#ff5470"}
        d_lines = [
            f"  [{sev.get(d.severity,'#c8d4e1')}]●[/] [b]{d.kind.value}[/]"
            f" via [#7dd3c0]{d.revealed_by.value}[/] — {d.description}"
            for d in t.discrepancies
        ] or ["  [dim](none)[/]"]
        vcol = "#00ff9f" if t.correct_verdict == Verdict.ADMIT else "#ff5470"
        return (
            f"[#ffb454]Archetype:[/]       [b]{c.archetype.value}[/]\n"
            f"[#ffb454]Correct verdict:[/] [{vcol}][b]{t.correct_verdict.value.upper()}[/][/]\n"
            f"[#ffb454]Moral modifier:[/]  {t.moral_modifier:+d}\n"
            f"\n[#ffb454]Discrepancies ({len(t.discrepancies)}):[/]\n"
            + "\n".join(d_lines)
        )


class Toast(Static):
    """Brief feedback after a verdict or tool error."""

    def __init__(self) -> None:
        super().__init__(id="toast")
        self.can_focus = False
        self.update("")

    def show(self, message: str, correct: bool) -> None:
        self.remove_class("toast-correct", "toast-wrong")
        self.add_class("toast-correct" if correct else "toast-wrong")
        self.update(message)



class CommandBar(Static):
    """Always-visible command-line strip at the bottom of the intake screen.

    IntakeScreen.on_key() funnels all printable keypresses here.
    Enter submits; Backspace deletes; Escape clears without executing.
    See _COMMAND_ALIASES for the full command vocabulary.
    """

    can_focus = False

    def __init__(self) -> None:
        super().__init__(id="command-bar")
        self._buffer   = ""
        self._response = (
            "type a command and press Enter  ·  "
            "try: recon · crack · analyze · extract · admit · deny · help"
        )
        self._is_error = False


    def on_mount(self) -> None:
        self._push()

    # Buffer management

    def get_buffer(self) -> str:
        return self._buffer

    def clear_buffer(self) -> None:
        self._buffer = ""
        self._push()

    def append_char(self, ch: str) -> None:
        self._buffer += ch
        self._push()

    def backspace(self) -> None:
        if self._buffer:
            self._buffer = self._buffer[:-1]
            self._push()

    def set_response(self, message: str, *, error: bool = False) -> None:
        self._response = message
        self._is_error = error
        self._push()

    # Render

    def _push(self) -> None:
        """Push current state to Static via update(), which parses Rich markup."""
        resp_col = "#ff5470" if self._is_error else "#7dd3c0"
        resp = (self._response or "")[:140]
        markup = (
            f"[{resp_col}]  {resp}[/]\n"
            f"[#00ff9f]hackdox@terminal:~$[/]  [#00ff9f]{self._buffer}[/][#00ff9f]█[/]"
        )
        self.update(markup)


class RulesScreen(ModalScreen):
    """Documentation hub — day rules + per-tool reference.

    Five tabs: Rules · OSINT · Credentials · Logs · Steganography.
    Press 0 or Esc to dismiss.
    """

    BINDINGS = [
        Binding(_B["page_rules"], "dismiss_rules", "Close"),
        Binding("escape",         "dismiss_rules", "Close"),
    ]

    def __init__(self, day: Day, evidence_state: "EvidenceState | None" = None,
                 initial_tab: str | None = None,
                 scroll_memory: dict[str, float] | None = None) -> None:
        super().__init__()
        self._day = day
        # #50: which tab to open on, and where each tab was last scrolled to.
        # The screen is re-instantiated on every open (it's a ModalScreen that
        # gets dismissed, not hidden), so scroll state has to be owned by the
        # app and handed in — keeping it on the screen would reset it every time.
        self._initial_tab   = initial_tab
        self._scroll_memory = scroll_memory if scroll_memory is not None else {}
        # Shared evidence record — lets the player flag evidence from the Rules
        # overlay too, so the board is always within reach.
        self._ev_board = (
            EvidenceBoard(evidence_state, "evidence-rules", "rules-evidence",
                          home_group="DOSSIER")
            if evidence_state is not None else None
        )

    def compose(self) -> ComposeResult:
        with Container(id="rules-modal"):
            yield Static("[b][#7dd3c0]HACKDOX  DOCUMENTATION HUB[/][/]", id="rules-title")
            with TabbedContent(id="rules-tabs"):
                with TabPane("Rules", id="tab-rules"):
                    with VerticalScroll():
                        yield Static(self._build_rules_text(), classes="rules-section")
                # #50: the dossier-tier reference split out of the Rules tab.
                with TabPane("Dossier", id="tab-dossier"):
                    with VerticalScroll():
                        yield Static(self._build_dossier_text(), classes="rules-section")
                with TabPane("OSINT", id="tab-osint"):
                    with VerticalScroll():
                        yield Static(self._build_osint_text(), classes="rules-section")
                with TabPane("Credentials", id="tab-creds"):
                    with VerticalScroll():
                        yield Static(self._build_creds_text(), classes="rules-section")
                with TabPane("Log Analysis", id="tab-logs"):
                    with VerticalScroll():
                        yield Static(self._build_logs_text(), classes="rules-section")
                with TabPane("Steganography", id="tab-stego"):
                    with VerticalScroll():
                        yield Static(self._build_stego_text(), classes="rules-section")
                if self._ev_board is not None:
                    with TabPane("Evidence", id="tab-evidence"):
                        yield self._ev_board
            yield Static(
                f"[dim]Tab/click to switch sections  ·  "
                f"Press [b]{_B['page_rules'].upper()}[/] or Esc to close[/]",
                id="rules-hint",
            )

    # ── Tab content builders ──────────────────────────────────────────

    # Issue #30: all tab content is generated by rules_content — a dynamic,
    # engine-derived builder set. Nothing here can drift from the code.

    def _build_rules_text(self) -> str:
        return rules_content.build_rules_text(self._day)

    def _build_dossier_text(self) -> str:
        return rules_content.build_dossier_text(self._day)

    def _build_osint_text(self) -> str:
        return rules_content.build_osint_text(self._day)

    def _build_creds_text(self) -> str:
        return rules_content.build_creds_text(self._day)

    def _build_logs_text(self) -> str:
        return rules_content.build_logs_text(self._day)

    def _build_stego_text(self) -> str:
        return rules_content.build_stego_text(self._day)

    def on_mount(self) -> None:
        """#50: open on the tab matching the page the player came from, and
        restore that tab's last scroll position."""
        if self._initial_tab:
            try:
                self.query_one("#rules-tabs", TabbedContent).active = self._initial_tab
            except Exception:
                # An unknown id would otherwise take the whole overlay down; the
                # default tab is a perfectly good fallback.
                pass
        self._restore_scroll()

    def _active_scroll(self) -> "VerticalScroll | None":
        """The VerticalScroll inside the currently active TabPane."""
        try:
            tabs = self.query_one("#rules-tabs", TabbedContent)
            pane = tabs.get_pane(tabs.active)
            return pane.query(VerticalScroll).first()
        except Exception:
            return None

    def _restore_scroll(self) -> None:
        tabs = self.query_one("#rules-tabs", TabbedContent)
        target = self._scroll_memory.get(tabs.active)
        view = self._active_scroll()
        if view is not None and target:
            # animate=False so the restore is instant rather than visibly
            # scrolling down from the top every time the overlay opens.
            view.scroll_to(y=target, animate=False)

    def _remember_scroll(self) -> None:
        tabs = self.query_one("#rules-tabs", TabbedContent)
        view = self._active_scroll()
        if view is not None:
            self._scroll_memory[tabs.active] = view.scroll_offset.y

    def on_tabbed_content_tab_activated(
            self, event: "TabbedContent.TabActivated") -> None:
        # Restore the newly-shown tab's position. Its own offset was saved when
        # the player last switched away from or closed it.
        self._restore_scroll()

    def action_dismiss_rules(self) -> None:
        self._remember_scroll()
        self.dismiss()

class CreditRevealScreen(ModalScreen):
    """HackDox Credit reveal (issue #25) — a read-only, spent-credit debug
    window showing the candidate's ground truth: the correct verdict and the
    planted violation KINDS. Deliberately excludes the evidence trail
    (descriptions / which tool reveals what) per the issue AC. Distinct
    violet styling marks it as a paid debug view, not normal tool output."""

    BINDINGS = [
        Binding("escape", "dismiss_reveal", "Close"),
        Binding("enter",  "dismiss_reveal", "Close"),
    ]

    def __init__(self, candidate: Candidate, credits_left: int) -> None:
        super().__init__()
        self._candidate    = candidate
        self._credits_left = credits_left

    def compose(self) -> ComposeResult:
        c, t = self._candidate, self._candidate.truth
        sev  = {"minor": "#ffd93d", "major": "#ff8c42", "critical": "#ff5470"}
        vcol = "#00ff9f" if t.correct_verdict == Verdict.ADMIT else "#ff5470"
        rows = [
            "[#c084fc][b]⬢ HACKDOX CREDIT SPENT — GROUND TRUTH REVEAL[/][/]",
            "[dim]read-only · no verdict submitted · evidence trail not included[/]",
            "",
            f"[#6b7785]Candidate[/]        [b]{c.display_name}[/]  ({c.handle})",
            f"[#6b7785]Correct verdict[/]  [{vcol}][b]{t.correct_verdict.value.upper()}[/][/]",
            "",
            f"[#6b7785]Planted violations ({len(t.discrepancies)}):[/]",
        ]
        if t.discrepancies:
            for d in t.discrepancies:
                col = sev.get(d.severity, "#c8d4e1")
                rows.append(f"  [{col}]▲ {d.kind.value}[/]  [dim]({d.severity})[/]")
        else:
            rows.append("  [dim](clean — no violations planted)[/]")
        rows += [
            "",
            f"[#c084fc]credits remaining: {self._credits_left}[/]",
            "",
            "[dim]Esc / Enter to close[/]",
        ]
        with Container(id="credit-modal"):
            yield Static("\n".join(rows))

    def action_dismiss_reveal(self) -> None:
        self.dismiss()


class IntroScreen(Screen):
    BINDINGS = [
        Binding("n", "new_game", "New game"),
        Binding("q", "quit_app", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="splash"):
            yield Static(
                "  H A C K D O X   T E R M I N A L\n",
                classes="title",
            )
            yield Static(
                "Access to HackDox is reviewed by hand. You are the hand.",
                classes="subtitle",
            )
            yield Static(
                "[#00ff9f][b]N[/][/]  New game     [#00ff9f][b]Q[/][/]  Quit",
                classes="hint",
            )

    def action_new_game(self) -> None:
        self.app.start_new_game()

    def action_quit_app(self) -> None:
        self.app.exit()


def _overseer_lines(narrative: str) -> list[str]:
    """Split an Overseer narrative into typed lines for TypewriterLog (#3).

    Blank lines are kept for pacing; a plain paragraph with no newlines types
    out as a single line.
    """
    return narrative.split("\n") if narrative else [""]


def _play_overseer(log: "TypewriterLog", narrative: str, *, triggers_on_last=None) -> None:
    """Stream an Overseer beat, one auto-chaining message per line.

    Each line is its own message so the beat plays out without the player
    needing to press Space between lines (these host screens don't focus the
    log — they keep Space for their own begin/continue/buy action). #34 hangs
    a tool-unlock off `triggers_on_last`, which rides the final line's
    TypewriterLog.Finished so the unlock lands exactly when the beat ends.
    """
    lines = _overseer_lines(narrative)
    for i, line in enumerate(lines):
        last = i == len(lines) - 1
        log.post("", line, triggers=(triggers_on_last if last else None))


# Placeholder Overseer unlock narration, one line per tool (#34). PLACEHOLDER —
# the final, day-by-day wording is authored with the tutorial script (#15); this
# is a stand-in so the mechanism (and its teaching order) is in place now. The
# `triggers` payload on this line is the tool value string, which the briefing's
# Finished handler uses to flip GameState.unlocked_tools.
_UNLOCK_LINES: dict[str, str] = {
    "ghostscan": "New capability authorized: GHOSTSCAN. Public traces don't lie the way people do.",
    "hashcrack": "New capability authorized: HASHCRACK. If they reused a breached password, we'll see it.",
    "logwatch":  "New capability authorized: LOGWATCH. The logs remember every step they took.",
    "stegotool": "New capability authorized: STEGOTOOL. They hide payloads in plain sight now. Look closer.",
}


# ─── Overseer-Variable rule broadcast (#36) ─────────────────────────────────
#
# The Overseer mentions rule changes in passing. The design is explicit that a
# small change should read as a minor process update, not a klaxon — so these
# are deliberately understated, hedged, and a little bored. Several openers per
# change kind so a two-change morning doesn't read as a filled-in template.
#
# {rule} is the rule's own text, lower-cased at the first character and
# stripped of its trailing period so it sits inside a sentence.
_RULE_CHANGE_PHRASINGS: dict[str, tuple[str, ...]] = {
    # A rule got teeth: advisory → disqualifying.
    "tightened": (
        "Oh — one thing before you start. That guidance about {rule}? Policy "
        "now. Not a suggestion. Don't make me explain it twice.",
        "Small note. {rule} — that's a hard deny from today. Compliance "
        "wanted it in writing, so now it's in writing.",
        "Quick amendment: {rule}. It used to be your judgement. It isn't "
        "anymore.",
    ),
    # A rule lost its teeth: disqualifying → advisory.
    "relaxed": (
        "Before I forget — {rule}. That's a note now, not a bar. Flag it, "
        "wave them through. Don't overthink it.",
        "Legal's been busy. {rule} is advisory from this morning. Use your "
        "judgement, which I'm told you have.",
        "Minor thing. {rule} — we're not denying on that on its own anymore. "
        "Log it and move on.",
    ),
    "added": (
        "New line in the book today: {rule}. Read it properly at some point.",
        "They've added one. {rule}. I didn't write it, I just pass it along.",
    ),
    "removed": (
        "That clause about {rule} is gone as of this morning. Don't ask me "
        "why; I stopped asking.",
        "We've dropped the line about {rule}. Nobody's said why.",
    ),
}


def _rule_fragment(text: str) -> str:
    """Fold a rulebook line into something that can sit mid-sentence."""
    frag = text.strip().rstrip(".")
    # Rule text is authored as an instruction ("Deny any candidate whose…").
    # Strip the leading imperative so the Overseer isn't quoting a form at the
    # player — she's supposed to sound like she's mentioning it, not reading it.
    for lead in ("Deny any candidate whose ", "Deny any candidate who ",
                 "Flag (do not auto-deny) a ", "Flag (do not auto-deny) "):
        if frag.startswith(lead):
            frag = frag[len(lead):]
            break
    else:
        frag = frag[:1].lower() + frag[1:]
    # Rule text often carries its own em-dash aside; it reads badly nested
    # inside the Overseer's own sentence, so keep only the head clause.
    return frag.split(" — ")[0].strip()


def _starts_a_sentence(template: str) -> bool:
    """True when {rule} lands at the start of a sentence in this template.

    Rule fragments are lower-cased so they read naturally mid-sentence ("about
    claimed connection IP…"), which looks wrong when a template opens a
    sentence with one ("Legal's been busy. claimed connection IP is…"). Cheaper
    and safer than capitalising the finished line, which would also mangle
    abbreviations sitting inside the rule text.
    """
    head = template.split("{rule}", 1)[0].rstrip()
    return not head or head[-1] in ".!?"


def rule_change_lines(changes, day_number: int) -> list[str]:
    """One casual Overseer line per changed Overseer-Variable rule (#36).

    Deterministic in the day number and the rule id, so replaying a day
    reproduces the same briefing rather than re-rolling the Overseer's phrasing.
    """
    lines: list[str] = []
    for change in changes:
        if change.kind == "severity":
            bucket = ("tightened" if change.rule.severity == "disqualifying"
                      else "relaxed")
        else:
            bucket = change.kind
        options = _RULE_CHANGE_PHRASINGS.get(bucket)
        if not options:
            continue
        pick = candidate_gen.stable_hash(change.rule.id, day_number, bucket)
        template = options[pick % len(options)]
        fragment = _rule_fragment(change.rule.text)
        if _starts_a_sentence(template):
            fragment = fragment[:1].upper() + fragment[1:]
        lines.append(template.format(rule=fragment))
    return lines


class BriefingScreen(Screen):
    BINDINGS = [
        Binding("space", "begin_day", "Begin shift"),
        Binding("q", "quit_app", "Quit"),
    ]

    def __init__(self, day: Day, narrative: str, state: GameState,
                 prev_day: Day | None = None) -> None:
        super().__init__()
        self._day       = day
        self._narrative = narrative
        self._state     = state
        self._overseer_log: TypewriterLog | None = None
        # The tool (if any) this day introduces — its unlock line + trigger.
        self._unlock_tool = config.tool_introduced_on(day.number)
        # #36: yesterday's ruleset, so the briefing can announce what moved.
        # None on day 1 — there is no yesterday, so nothing is broadcast.
        self._rule_changes = rules_engine.diff_rulesets(prev_day, day)

    def compose(self) -> ComposeResult:
        yield Static(f"[b][#7dd3c0]{self._day.title}[/][/]", classes="screen-title")
        with Container(id="overseer-panel"):
            yield Static("[b]Overseer:[/]", classes="speaker")
            # #3: the briefing dialogue types out through the TypewriterLog.
            # The log is NOT focused, so the screen keeps its Space=begin binding.
            self._overseer_log = TypewriterLog(id="briefing-overseer")
            yield self._overseer_log
        yield Static(
            "Press [#00ff9f][b]Space[/][/] to begin your shift.",
            classes="hint",
        )

    def on_mount(self) -> None:
        # Play the day's intro beat, then — on a tool-unlock day (#34) — the
        # Overseer's unlock line, carrying the tool as its `triggers` payload so
        # the flip lands exactly when that line finishes.
        _play_overseer(self._overseer_log, self._narrative)
        # #36: rule changes land AFTER the intro and BEFORE any unlock line, so
        # a day that both flips a rule and grants a tool reads in the order the
        # player will need it: today's mood, today's rules, then the new toy.
        # Amber, not red — this is a process note, not an alarm.
        for line in rule_change_lines(self._rule_changes, self._day.number):
            self._overseer_log.post("", line, color="#ffd93d")
        if self._unlock_tool:
            line = _UNLOCK_LINES.get(self._unlock_tool,
                                     f"New capability authorized: {self._unlock_tool.upper()}.")
            self._overseer_log.post("", line, color="#00ff9f",
                                    triggers=self._unlock_tool)

    def on_typewriter_log_finished(self, msg: "TypewriterLog.Finished") -> None:
        # #34: the unlock beat flips the tool on — not just cosmetically.
        if isinstance(msg.triggers, str):
            self._state.unlocked_tools.add(msg.triggers)

    def _ensure_unlocked(self) -> None:
        # Belt-and-suspenders: if the player presses Space to begin before the
        # unlock line has finished typing, the tool must still be granted for
        # the day to be playable. Adding to a set is idempotent, so this never
        # double-applies with the Finished trigger above.
        if self._unlock_tool:
            self._state.unlocked_tools.add(self._unlock_tool)

    def action_begin_day(self) -> None:
        self._ensure_unlocked()
        self.app.begin_intake()

    def action_quit_app(self) -> None:
        self.app.exit()


class IntakeScreen(Screen):
    """The main play screen."""

    BINDINGS = [
        # Page navigation — number row (immediate, no command bar)
        Binding(_B["page_candidate"], "page_1",      "Candidate", show=False),
        Binding(_B["page_ghostscan"], "page_2",      "Ghostscan", show=False),
        Binding(_B["page_hashcrack"], "page_3",      "Hashcrack", show=False),
        Binding(_B["page_logwatch"],  "page_4",      "Logwatch",  show=False),
        Binding(_B["page_stegotool"], "page_5",      "Stegotool", show=False),

        # Rules overlay (immediate)
        Binding(_B["page_rules"],     "open_rules",  "Rules",     show=False),

        # Within-page focus navigation — arrow keys (immediate)
        # EvidenceBoard consumes up/down when focused; letters still bubble to command bar.
        Binding(_B["focus_prev"],     "focus_prev",  "↑ Focus",   show=False),
        Binding(_B["focus_next"],     "focus_next",  "↓ Focus",   show=False),
        Binding(_B["focus_left"],     "focus_left",  "← Focus",   show=False),
        Binding(_B["focus_right"],    "focus_right", "→ Focus",   show=False),

        # Debug toggle — dev shortcut, kept immediate
        Binding(_B["toggle_debug"],   "toggle_debug","Dev",        show=False),

        # Everything else (a/d/n/g/l/h/s/f/q/?) goes through the command bar.
        # See on_key() and _execute_command() below.
    ]

    def __init__(self, day: Day, state: GameState, overseer_intro: str) -> None:
        super().__init__()
        self._day            = day
        self._state          = state
        self._candidate: Candidate | None = None
        self._verdict_locked = False
        self._page_index     = 0
        self._compute_before = state.compute_hours   # track for overseer stats
        self._spent: set[ToolName] = set()
        self._day_log: list = []   # shared log entries for the full day
        # #50: per-tab scroll positions for the Rules overlay. Lives here rather
        # than on RulesScreen because that screen is dismissed and rebuilt on
        # every open, so anything it owns is lost between views.
        self._rules_scroll: dict[str, float] = {}
        self._hc_log:  list = []   # shared credential audit log (hashcrack)

        # ── Stegotool stamp minigame state ────────────────────────────
        self._stamp_mode     = False   # arrows/Space captured while True
        self._stego_resolved = False   # ▲ signature block printed once
        self._stego_filter   = False   # payload type classified (filter paid)
        self._credit_revealed = False  # HackDox Credit spent on this candidate (issue #25)

        # ── Widgets ───────────────────────────────────────────────────
        self.status   = StatusHeader(state, day, state.current_slot_index)
        self.dossier  = DossierPanel()
        self.chat     = ChatPanel()
        # Shared evidence record + the inline Candidate-page board (unchanged).
        self.evidence_state = EvidenceState()
        self.board    = EvidenceBoard(self.evidence_state, "evidence-board", summary=True)
        # Full editable board on the Candidate/Dossier page too, so the player
        # always has direct access. Hidden by default; Tab swaps it in for the
        # read-only summary.
        self.board_c0 = EvidenceBoard(self.evidence_state, "evidence-c0", "tool-evidence",
                                      home_group="DOSSIER")
        self.overseer = OverseerPanel(overseer_intro)
        self.ref_main = ReferencePanel("candidate", "reference-side")

        # Toggleable evidence boards for the tool pages — same shared state,
        # mounted on the left, hidden until the player toggles them on.
        self.board_gs = EvidenceBoard(self.evidence_state, "evidence-gs", "tool-evidence",
                                      home_group=_BOARD_HOME_GROUP["evidence-gs"])
        self.board_hc = EvidenceBoard(self.evidence_state, "evidence-hc", "tool-evidence",
                                      home_group=_BOARD_HOME_GROUP["evidence-hc"])
        self.board_lw = EvidenceBoard(self.evidence_state, "evidence-lw", "tool-evidence",
                                      home_group=_BOARD_HOME_GROUP["evidence-lw"])
        self.board_st = EvidenceBoard(self.evidence_state, "evidence-st", "tool-evidence",
                                      home_group=_BOARD_HOME_GROUP["evidence-st"])
        self._tool_boards = (self.board_gs, self.board_hc, self.board_lw, self.board_st)
        # Each tool board is paired with the sidebar it replaces when shown.
        self._evidence_pairs = [
            (self.board_gs, "gs-left"),
            (self.board_hc, "hc-left"),
            (self.board_lw, "lw-left"),
            (self.board_st, "st-left"),
        ]
        self._evidence_open = False   # shared visibility across tool pages

        # One condensed dossier + reference panel per tool page
        self.cdos_gs  = CondensedDossier("condensed-dossier-gs")
        self.cdos_hc  = CondensedDossier("condensed-dossier-hc")
        self.cdos_lw  = CondensedDossier("condensed-dossier-lw")
        self.cdos_st  = CondensedDossier("condensed-dossier-st")

        self.ref_gs   = ReferencePanel("ghostscan", "ref-gs")
        self.ref_hc   = ReferencePanel("hashcrack", "ref-hc")
        self.ref_lw   = ReferencePanel("logwatch",  "ref-lw")
        self.ref_st   = ReferencePanel("stegotool", "ref-st")

        # Tool terminals
        self.term_gs  = ToolTerminal("terminal-gs", "Ghostscan")
        self.term_hc  = ToolTerminal("terminal-hc", "Hashcrack")
        self.term_lw  = ToolTerminal("terminal-lw", "Logwatch")
        self.term_st  = ToolTerminal("terminal-st", "Stegotool")

        # Breach list panel — right column of the Ghostscan page
        self.breach_lists = BreachListPanel()

        # Interactive image viewer — right column of the Stegotool page
        self.image_st = StegoImagePanel()

        self.debug        = DebugPanel()
        self.command_bar  = CommandBar()
        self._footer_widget: Static | None = None

    def compose(self) -> ComposeResult:
        yield self.status

        with ContentSwitcher(initial="page-candidate"):

            # ── Page 0: Candidate ─────────────────────────────────────
            with Vertical(id="page-candidate"):
                with Horizontal(id="candidate-top"):
                    yield self.dossier
                    yield self.chat
                with Horizontal(id="candidate-mid"):
                    yield self.board
                    yield self.board_c0
                with Horizontal(id="candidate-bot"):
                    yield self.overseer
                    yield self.ref_main

            # ── Page 1: Ghostscan ─────────────────────────────────────
            # 3-column layout: sidebar | terminal | breach lists
            # The evidence board (hidden) replaces the sidebar when toggled.
            with Horizontal(id="page-ghostscan", classes="tool-page"):
                yield self.board_gs
                with Vertical(classes="tool-left", id="gs-left"):
                    yield self.cdos_gs
                    yield self.ref_gs
                yield self.term_gs
                yield self.breach_lists

            # ── Page 2: Hashcrack ─────────────────────────────────────
            with Horizontal(id="page-hashcrack", classes="tool-page"):
                yield self.board_hc
                with Vertical(classes="tool-left", id="hc-left"):
                    yield self.cdos_hc
                    yield self.ref_hc
                yield self.term_hc

            # ── Page 3: Logwatch ──────────────────────────────────────
            with Horizontal(id="page-logwatch", classes="tool-page"):
                yield self.board_lw
                with Vertical(classes="tool-left", id="lw-left"):
                    yield self.cdos_lw
                    yield self.ref_lw
                yield self.term_lw

            # ── Page 4: Stegotool ─────────────────────────────────────
            # 3-column layout: sidebar | findings terminal | image viewer.
            # The image viewer dominates the right side — it's the game
            # canvas for the stamp minigame.
            with Horizontal(id="page-stegotool", classes="tool-page"):
                yield self.board_st
                with Vertical(classes="tool-left", id="st-left"):
                    yield self.cdos_st
                    yield self.ref_st
                yield self.term_st
                yield self.image_st

        yield self.debug
        yield self.command_bar

        self._footer_widget = Static(self._footer_text(), id="footer")
        yield self._footer_widget

    def on_mount(self) -> None:
        self._day_log = tools_bridge.generate_day_log(self._state.seed, self._day)
        self._hc_log  = tools_bridge.generate_hashcrack_day_log(self._state.seed, self._day)
        self._apply_evidence_visibility()   # tool boards start hidden
        self._load_current_candidate()

    # ── Internal helpers ──────────────────────────────────────────────

    _TOOL_TERM: dict[ToolName, str] = {
        ToolName.GHOSTSCAN: "terminal-gs",
        ToolName.LOGWATCH:  "terminal-lw",
        ToolName.HASHCRACK: "terminal-hc",
        ToolName.STEGOTOOL: "terminal-st",
    }
    _TOOL_PAGE: dict[ToolName, int] = {
        ToolName.GHOSTSCAN: 1,
        ToolName.LOGWATCH:  3,
        ToolName.HASHCRACK: 2,
        ToolName.STEGOTOOL: 4,
    }

    def _footer_text(self) -> str:
        """Slim nav strip — tool/verdict/quit all go through the command bar now."""
        on_tool = 1 <= self._page_index <= 4
        if on_tool:
            ev = ("[#ffb454][b]Tab[/][/] Hide Evidence"
                  if self._evidence_open
                  else "[#00ff9f][b]Tab[/][/] Evidence")
        else:
            ev = "[#00ff9f][b]Tab[/][/] Evidence"
        if self._stamp_mode:
            return (
                "[#00ffd5][b]STAMP MODE[/][/]  "
                "[dim]arrows Move[/]  "
                f"[#00ffd5][b]Space[/][/] Stamp (−{config.STEGO_STAMP_COST} ⏱)  "
                "[#ffb454][b]Esc[/][/] Exit"
            )
        stamp_hint = ("[#00ffd5][b]X[/][/] Stamp  " if self._page_index == 4 else "")
        return (
            "[#00ff9f][b]1-5[/][/] Pages  "
            "[#00ff9f][b]0[/][/] Rules  "
            f"{ev}  "
            f"{stamp_hint}"
            "[dim]↑↓ Cursor  Space Flag[/]  "
            "[#00ff9f][b]`[/][/] Dev"
        )

    def _refresh_footer(self) -> None:
        if self._footer_widget:
            self._footer_widget.update(self._footer_text())

    # ── Evidence board toggle (tool pages only) ──────────────────────────────

    def _apply_evidence_visibility(self) -> None:
        """Show/hide each tool board and the sidebar it replaces, plus the
        Candidate-page editable board (which swaps in for the summary)."""
        # Candidate page: editable board replaces the read-only summary.
        self.board_c0.display = self._evidence_open
        self.board.display    = not self._evidence_open
        for board, side_id in self._evidence_pairs:
            board.display = self._evidence_open
            try:
                self.query_one(f"#{side_id}").display = not self._evidence_open
            except Exception:
                pass

    def _current_tool_board(self) -> "EvidenceBoard | None":
        if 1 <= self._page_index <= 4:
            return self._tool_boards[self._page_index - 1]
        return None

    def _active_editable_board(self) -> "EvidenceBoard | None":
        """The editable board for the current page (Candidate or a tool page)."""
        if self._page_index == 0:
            return self.board_c0
        return self._current_tool_board()

    def _toggle_evidence(self) -> None:
        """Toggle the editable evidence board on the current page.

        Available on the Candidate/Dossier page (swaps in for the summary) and
        on every tool page (replaces the sidebar).
        """
        self._evidence_open = not self._evidence_open
        self._apply_evidence_visibility()
        self._refresh_footer()
        if self._evidence_open:
            board = self._active_editable_board()
            if board is not None:
                board.focus()
                # Reset scroll to the group this page focuses on.
                board.focus_home_group()
        else:
            self.board.repaint()

    def _goto_page(self, index: int) -> None:
        # Progressive unlock (#33): a locked tool page can't be entered — no
        # switch, no ⏱, just an Overseer-flavoured note. Candidate page (0) and
        # any already-unlocked tool pass straight through.
        tool = _PAGE_TOOL[index]
        if tool is not None and tool not in self._state.unlocked_tools:
            self.command_bar.set_response(
                f"{_PAGE_NAMES[index]} is locked — the Overseer grants it in a "
                f"later briefing.",
                error=False,
            )
            return
        # Leaving the stego page (or arriving anywhere) drops stamp mode.
        if self._stamp_mode and index != 4:
            self._exit_stamp_mode(quiet=True)
        self._page_index = index
        self.query_one(ContentSwitcher).current = _PAGE_IDS[index]
        self.status.refresh_status(self._state, self._state.current_slot_index,
                                   self._page_index)
        # Keep the evidence board focused when stepping between pages.
        if self._evidence_open:
            board = self._active_editable_board()
            if board is not None:
                board.focus()
        # Always repaint the candidate-page summary so flagged violations
        # show up immediately when the player returns to page 0.
        if index == 0:
            self.board.repaint()
        self._refresh_footer()

    def _load_current_candidate(self) -> None:
        slot = self._state.current_slot_index
        if slot >= self._day.candidate_count:
            self.app.finish_day()
            return

        self._candidate      = candidate_gen.generate(self._state.seed, self._day, slot)
        self._verdict_locked = False
        self._spent.clear()
        self._compute_before = self._state.compute_hours

        # Update all panels
        c = self._candidate
        ups = self._state.upgrades
        # Auto-highlight upgrades (issue #23): wire ownership into the panels
        # BEFORE set_candidate so the first render already honours them.
        self.dossier.upgrades    = ups
        self.chat.upgrades       = ups
        self.image_st.tint_boost = config.UPGRADE_STEGO_TINT in ups
        self._credit_revealed    = False   # fresh candidate — reveal unpaid (issue #25)
        self.dossier.cracked_password = None   # issue #29 — fresh password state
        self.dossier.set_candidate(c)
        self.chat.set_candidate(c)
        self.debug.set_candidate(c)
        for cd in (self.cdos_gs, self.cdos_hc, self.cdos_lw, self.cdos_st):
            cd.upgrades = ups
            cd.cracked_password = None         # issue #29 — fresh password state
            cd.set_candidate(c)

        # The day's rulebook is shown on EVERY page's reference panel so the
        # player can always see what disqualifies a candidate today and then
        # check the tool terminal on the right to decide if it's a violation.
        rules_block = _format_day_rules(self._day.rules)

        # Candidate-page reference: today's rules + global accept/reject guide
        self.ref_main.update_content(_REF_CANDIDATE)

        # Reference panel: target email + claimed IP + today's rules + violation guide
        self.ref_hc.update_content(_REF_HASHCRACK)

        # Clear the shared evidence record and repaint every board view.
        self.evidence_state.clear()
        for b in (self.board, self.board_c0, *self._tool_boards):
            b.reset_cursor()
        # All tool terminals cleared via set_initial_content
        # Ghostscan: passive identity check (free) + breach list pre-population
        self.term_gs.set_initial_content(tools_bridge.get_ghostscan_identity(c))
        self.ref_gs.update_content(_REF_GHOSTSCAN)
        self.breach_lists.load_candidate(c)
        # Hashcrack terminal: shared credential audit log (free, candidate highlighted;
        # Credential HUD upgrade pre-colours suspicious lines — issue #23)
        self.term_hc.set_initial_content(tools_bridge.get_hashcrack_shared(
            self._hc_log, c,
            upgrade_highlight=config.UPGRADE_HASH_HIGHLIGHT in ups))
        # Logwatch terminal: shared day log (session grouping / Log Analyzer HUD
        # upgrades applied when owned — issue #23)
        _gs = config.UPGRADE_SESSION_GROUPING in ups
        self.term_lw.set_initial_content(tools_bridge.get_logwatch_shared(
            self._day_log, c, group_by_session=_gs,
            upgrade_highlight=config.UPGRADE_LOG_HIGHLIGHT in ups))
        # Logwatch reference: target info + today's rules + attack pattern guide
        self.ref_lw.update_content(_REF_LOGWATCH)
        # Stegotool: findings terminal gets the free stats block; the pixel
        # grid lives in the image viewer where the stamp minigame runs.
        self._stamp_mode     = False
        self._stego_resolved = False
        self._stego_filter   = False
        self.term_st.set_initial_content(tools_bridge.get_stego_stats(c))
        self.image_st.load_candidate(c, self._day.number if self._day else 1)
        # Stegotool reference: stamp-mode controls + signature color legend
        self.ref_st.update_content(_REF_STEGOTOOL)

        self.status.refresh_status(self._state, slot, self._page_index)
        self._refresh_footer()

    def _rules_tab_for_page(self) -> str:
        """#50: the Rules-overlay tab matching the page the player is on.

        Opening the docs from Logwatch should land on the Logwatch tab — the
        player is looking something up about the thing in front of them, not
        re-reading the day's ruleset.
        """
        if 0 <= self._page_index < len(_PAGE_TAB):
            return _PAGE_TAB[self._page_index]
        return "tab-rules"

    def _commit_verdict(self, verdict: Verdict) -> None:
        if self._verdict_locked or self._candidate is None:
            return
        self._verdict_locked = True
        compute_before = self._state.compute_hours
        # #38: hand scoring the day's rule evaluation so the LITERAL-RULESET
        # track is recorded alongside the moral one. Payouts are unaffected -
        # the economy still keys off ground truth; this is a parallel value.
        result = scoring.apply(
            self._candidate, verdict, self._state,
            player_flags=self.board.get_flags(),
            evaluation=rules_engine.evaluate(self._candidate, self._day),
        )
        compute_after = self._state.compute_hours
        self.overseer.record_result(result, compute_before, compute_after)

        v_str   = "ADMITTED" if verdict == Verdict.ADMIT else "DENIED"
        parts   = [f"{v_str} {self._candidate.display_name}."]
        parts  += ["Correct." if result.correct else "Wrong call."]
        if result.site_health_delta:
            parts.append(f"⛨ {result.site_health_delta:+.1f}% at EOD")
        if result.hackdollar_delta:
            parts.append(f"+{result.hackdollar_delta} HD$")
            if result.board_bonus:
                parts.append(f"(+{result.board_bonus} HD$ board bonus)")
        if result.alignment_delta:
            arrow = "→ White Hat" if result.alignment_delta > 0 else "→ Dark Web"
            parts.append(f"Align {arrow}")
        # #38: the moment being right by the book and right by conscience come
        # apart is the corruption arc's whole point - say so out loud.
        if result.tracks_diverge:
            parts.append("[#c084fc]by the book, not by conscience[/]"
                         if result.rules_correct else
                         "[#c084fc]against the book[/]")

        self.command_bar.set_response("  ·  ".join(parts), error=not result.correct)
        self.status.refresh_status(self._state, self._state.current_slot_index,
                                   self._page_index)
        self._refresh_footer()

        # Site Health deltas are only recorded here — they apply in one
        # batch at end of day (finish_day), so the loss condition can only
        # trip at shift end (#20 rework).

    def _run_tool(self, tool: ToolName, *, filtered: bool = False) -> None:
        # Progressive unlock (#33): a locked tool is fully inert — the shortcut
        # keys (G/L/H/S/F) route here, so this is the single choke-point that
        # guarantees a locked tool never runs and never charges ⏱.
        if tool.value not in self._state.unlocked_tools:
            self.command_bar.set_response(
                f"{tool.value.upper()} is locked — not available yet.",
                error=False,
            )
            return
        if self._candidate is None or self._verdict_locked:
            return
        if tool in self._spent and not filtered:
            self.command_bar.set_response(
                f"{tool.value.upper()} already run — type 'filter' for enhanced analysis",
                error=False,
            )
            return

        runners = {
            ToolName.GHOSTSCAN: (tools_bridge.run_ghostscan_shared,
                                 tools_bridge.run_ghostscan_filtered_shared),
            ToolName.LOGWATCH:  (lambda c, s: tools_bridge.run_logwatch_shared(
                                     self._day_log, c, s,
                                     group_by_session=config.UPGRADE_SESSION_GROUPING in self._state.upgrades),
                                 lambda c, s: tools_bridge.run_logwatch_filtered_shared(
                                     self._day_log, c, s,
                                     group_by_session=config.UPGRADE_SESSION_GROUPING in self._state.upgrades)),
            ToolName.HASHCRACK: (lambda c, s: tools_bridge.run_hashcrack_shared(self._hc_log, c, s),
                                 lambda c, s: tools_bridge.run_hashcrack_filtered_shared(self._hc_log, c, s)),
            # STEGOTOOL intentionally absent — the stego page uses the
            # interactive stamp minigame instead of a flat tool run.
        }
        base_fn, filter_fn = runners[tool]
        try:
            result = filter_fn(self._candidate, self._state) if filtered \
                     else base_fn(self._candidate, self._state)
        except tools_bridge.InsufficientCompute as e:
            self.command_bar.set_response(str(e), error=True)
            return

        # Get the right terminal and display the result.
        # Logwatch/Hashcrack replace the terminal content in-place (annotate
        # the shared log). Ghostscan also replaces (issue #28): the filtered
        # report re-renders the same report with annotations lit, never
        # stacking a second copy.
        term_id = self._TOOL_TERM[tool]
        term = self.query_one(f"#{term_id}", ToolTerminal)
        if tool in (ToolName.LOGWATCH, ToolName.HASHCRACK):
            term.set_initial_content(result.raw_lines)
        elif tool == ToolName.GHOSTSCAN:
            term.set_result(result)
        else:
            term.add_result(result)

        # Update breach list panel state when ghostscan runs
        if tool == ToolName.GHOSTSCAN:
            if filtered:
                self.breach_lists.confirm_match()
            else:
                self.breach_lists.highlight_match()

        # Issue #29: a hashcrack run resolves the dossier password field —
        # cracked plaintext (or a held bcrypt) is reflected on every page.
        if tool == ToolName.HASHCRACK:
            plain = tools_bridge.crack_password(self._candidate)
            resolved = plain if plain is not None else ""
            for panel in (self.dossier, self.cdos_gs, self.cdos_hc,
                          self.cdos_lw, self.cdos_st):
                panel.cracked_password = resolved
                panel.refresh()

        self._spent.add(tool)
        self.status.refresh_status(self._state, self._state.current_slot_index,
                                   self._page_index)
        cost = tools_bridge.tool_cost(self._state, tool.value)
        if filtered:
            cost += config.FILTER_COSTS[tool.value]
        self.command_bar.set_response(
            f"{'[FILTERED] ' if filtered else ''}"
            f"{tool.value.upper()} complete  −{cost} ⏱  ·  "
            f"flag findings on the Evidence Board (page 1)",
            error=False,
        )

    # ── Stegotool stamp minigame ──────────────────────────────────────────

    def _enter_stamp_mode(self) -> None:
        # Progressive unlock (#33): the stego stamp minigame is the Stegotool's
        # run surface, so it's inert until Stegotool is unlocked. (_goto_page(4)
        # already refuses the page, but the 's' shortcut calls this directly.)
        if "stegotool" not in self._state.unlocked_tools:
            self.command_bar.set_response(
                "STEGOTOOL is locked — not available yet.", error=False)
            return
        if self._candidate is None or self._verdict_locked:
            self.command_bar.set_response(
                "Verdict locked — stamping disabled", error=True)
            return
        self._stamp_mode = True
        self.image_st.enter_stamp_mode()
        self.command_bar.set_response(
            f"STAMP MODE — arrows move · Space stamp "
            f"(−{config.STEGO_STAMP_COST} ⏱) · Esc exit")
        self._refresh_footer()

    def _exit_stamp_mode(self, quiet: bool = False) -> None:
        self._stamp_mode = False
        self.image_st.exit_stamp_mode()
        if not quiet:
            self.command_bar.set_response("stamp mode off")
        self._refresh_footer()

    def _do_stamp(self) -> None:
        if self._candidate is None or self._verdict_locked:
            return
        try:
            tools_bridge.charge_stamp(self._state)
        except tools_bridge.InsufficientCompute as e:
            self.command_bar.set_response(str(e), error=True)
            return
        res = self.image_st.do_stamp()
        if res is None:
            return
        x, y, _w, _h = self.image_st.stamp_rect
        img   = self.image_st.image
        lines = tools_bridge.stamp_log_lines(img, res, self.image_st.stamps_used, x, y,
                                             reveal_type=self._stego_filter)
        if res.resolved and not self._stego_resolved:
            self._stego_resolved = True
            lines = lines + tools_bridge.stamp_signature_lines(
                img, reveal_type=self._stego_filter)
        self.term_st.add_lines(lines)
        self.status.refresh_status(self._state, self._state.current_slot_index,
                                   self._page_index)

    def _activate_stego_filter(self) -> None:
        """Pay to classify the stego payload type. Until this runs, stamp logs
        report a carrier but not its type — the player reads the stamp colour."""
        if self._candidate is None or self._verdict_locked:
            self.command_bar.set_response(
                "Verdict locked — filter disabled", error=True)
            return
        if self._stego_filter:
            self.command_bar.set_response("Filter already active — payload type is classified")
            return
        cost = config.STEGO_FILTER_COST
        if config.UPGRADE_TOOLCOST_STEGOTOOL in self._state.upgrades:
            cost = max(1, cost - config.TOOLCOST_REDUCTION)
        if self._state.compute_hours < cost:
            self.command_bar.set_response(
                f"Need {cost} ⏱ for the classification filter, "
                f"have {self._state.compute_hours} ⏱", error=True)
            return
        self._state.compute_hours -= cost
        self._stego_filter = True
        img = self.image_st.image
        lines = [
            "",
            f"[#7dd3c0][b]CLASSIFICATION FILTER[/][/]  [dim]−{cost} ⏱[/]",
            "  [dim]carrier signatures will now be named on each stamp[/]",
        ]
        # If the zone was already resolved before paying, print the named block now.
        if self._stego_resolved and img is not None:
            lines += tools_bridge.stamp_signature_lines(img, reveal_type=True)
        self.term_st.add_lines(lines)
        self.command_bar.set_response("Classification filter active — payload type will be named")
        self.status.refresh_status(self._state, self._state.current_slot_index,
                                   self._page_index)

    # ── HackDox Credit — ground-truth reveal (issue #25) ──────────────────

    def _credit_reveal(self) -> None:
        """Spend one HackDox Credit to reveal the current candidate's ground
        truth (correct verdict + planted violation kinds — NOT the evidence
        trail). Read-only; never submits a verdict. Works on every page since
        it reads engine state, not page-local data. Refused at 0 credits.
        Re-opening for the same candidate is free once paid."""
        if self._candidate is None:
            self.command_bar.set_response("No candidate loaded", error=True)
            return
        if self._credit_revealed:
            self.command_bar.set_response(
                "Ground truth already revealed for this candidate — no charge")
            self.app.push_screen(
                CreditRevealScreen(self._candidate, self._state.hackdox_credits))
            return
        if self._state.hackdox_credits <= 0:
            self.command_bar.set_response(
                "ACCESS DENIED — no HackDox Credits remaining. "
                "Buy more in the between-day shop.", error=True)
            return
        self._state.hackdox_credits -= 1
        self._credit_revealed = True
        self.status.refresh_status(self._state, self._state.current_slot_index,
                                   self._page_index)
        self.command_bar.set_response(
            f"HackDox Credit spent — ground truth revealed  "
            f"({self._state.hackdox_credits} remaining)")
        self.app.push_screen(
            CreditRevealScreen(self._candidate, self._state.hackdox_credits))

    # ── Action bindings ───────────────────────────────────────────────────

    # ── Page navigation (number keys 1-5) ────────────────────────────────────

    def action_page_1(self) -> None: self._goto_page(0)
    def action_page_2(self) -> None: self._goto_page(1)
    def action_page_3(self) -> None: self._goto_page(2)
    def action_page_4(self) -> None: self._goto_page(3)
    def action_page_5(self) -> None: self._goto_page(4)

    # ── Rules overlay (immediate binding) ────────────────────────────────────

    def action_open_rules(self) -> None:
        self.app.push_screen(RulesScreen(self._day, self.evidence_state,
                        initial_tab=self._rules_tab_for_page(),
                        scroll_memory=self._rules_scroll))

    # ── Within-page focus navigation (arrow keys) ─────────────────────────────
    # EvidenceBoard consumes up/down when focused; letters still bubble to bar.

    def action_focus_prev(self)  -> None: self.focus_previous()
    def action_focus_next(self)  -> None: self.focus_next()
    def action_focus_left(self)  -> None: self.focus_previous()
    def action_focus_right(self) -> None: self.focus_next()

    # ── Debug toggle (immediate binding, dev-only) ────────────────────────────

    def action_toggle_debug(self) -> None:
        self.debug.display = not self.debug.display

    # ── Command bar input routing ─────────────────────────────────────────────

    def on_key(self, event: Key) -> None:
        """Route keypresses: immediate actions first, then command bar input.

        on_key fires before BINDINGS in Textual, so immediate-action keys
        (page nav, rules, debug) must be handled explicitly here first.
        """
        k  = event.key
        ch = event.character  # empty string for non-printable keys

        # ── Stego stamp mode — captures arrows/Space/Esc while active ─────────
        if self._stamp_mode:
            if k in ("up", "down", "left", "right"):
                self.image_st.move_stamp(k); event.stop(); return
            if k == "space":
                self._do_stamp(); event.stop(); return
            if k in ("escape", config.KEY_BINDINGS["stamp_mode"]):
                self._exit_stamp_mode(); event.stop(); return
            if k not in ("1", "2", "3", "4", "5"):
                event.stop(); return          # swallow everything else
            self._exit_stamp_mode(quiet=True)  # page nav below exits stamp mode

        # ── Immediate actions (no Enter needed, do not enter command bar) ──────
        if k == "1":
            self._goto_page(0); event.stop(); return
        if k == "2":
            self._goto_page(1); event.stop(); return
        if k == "3":
            self._goto_page(2); event.stop(); return
        if k == "4":
            self._goto_page(3); event.stop(); return
        if k == "5":
            self._goto_page(4); event.stop(); return
        if k == "0":
            self.app.push_screen(RulesScreen(
                self._day, self.evidence_state,
                initial_tab=self._rules_tab_for_page(),
                scroll_memory=self._rules_scroll))
            event.stop(); return
        if k == config.KEY_BINDINGS["toggle_evidence"]:   # Tab
            if 0 <= self._page_index <= 4:
                # Toggles the editable board in place on every page, including
                # the Candidate/Dossier page (board_c0 swaps in for the
                # read-only summary there, same as a tool page's sidebar).
                self._toggle_evidence(); event.stop()
            return
        if k == "grave_accent":
            self.debug.display = not self.debug.display; event.stop(); return

        # ── Stamp mode entry — X on the stego page with an empty buffer ────────
        if (k == config.KEY_BINDINGS["stamp_mode"] and self._page_index == 4
                and not self.command_bar.get_buffer()):
            self._enter_stamp_mode(); event.stop(); return

        # ── Command bar input ─────────────────────────────────────────────────
        if k == "enter":
            self._execute_command(self.command_bar.get_buffer())
            self.command_bar.clear_buffer()
            event.stop()

        elif k == "backspace":
            self.command_bar.backspace()
            event.stop()

        elif k == "escape":
            self.command_bar.clear_buffer()
            self.command_bar.set_response("cleared")
            event.stop()

        elif ch and ch.isprintable():
            self.command_bar.append_char(ch)
            event.stop()

    # ── Command execution ─────────────────────────────────────────────────────

    _FILTER_PAGE_MAP: dict[int, ToolName] = {
        1: ToolName.GHOSTSCAN,
        2: ToolName.HASHCRACK,
        3: ToolName.LOGWATCH,
        # 4 (stegotool) removed — stamp minigame replaced scan/filter there.
    }

    def _execute_command(self, raw: str) -> None:
        """Parse a typed command and dispatch it."""
        s = raw.strip().lower()
        if not s:
            return

        parsed = _COMMAND_ALIASES.get(s)
        if parsed is None:
            self.command_bar.set_response(random.choice(_ERROR_MSGS), error=True)
            return

        kind, arg = parsed

        if kind == "tool":
            self._goto_page(self._TOOL_PAGE[arg])
            self._run_tool(arg)   # sets command_bar response internally

        elif kind == "stamp":
            self._goto_page(4)
            self._enter_stamp_mode()

        elif kind == "filter":
            if self._page_index == 4:
                self._activate_stego_filter()
                return
            tool = self._FILTER_PAGE_MAP.get(self._page_index)
            if tool is None:
                self.command_bar.set_response(
                    "ERROR — navigate to a tool page first (pages 2–4)", error=True
                )
            else:
                self._run_tool(tool, filtered=True)

        elif kind == "verdict":
            self._commit_verdict(arg)   # sets command_bar response internally

        elif kind == "reveal":
            self._credit_reveal()

        elif kind == "next":
            if not self._verdict_locked:
                self.command_bar.set_response(
                    "ERROR — commit a verdict first  (type: admit  or  deny)", error=True
                )
            else:
                self._state.current_slot_index += 1
                self._goto_page(0)
                self._load_current_candidate()

        elif kind == "rules":
            self.app.push_screen(RulesScreen(self._day, self.evidence_state,
                        initial_tab=self._rules_tab_for_page(),
                        scroll_memory=self._rules_scroll))

        elif kind == "evidence":
            self._toggle_evidence()

        elif kind == "help":
            self.command_bar.set_response(
                "COMMANDS:  recon · crack · analyze · stamp (stego) · filter · "
                "admit · deny · next · rules · evidence · help · quit  "
                "·  pages 1-5  ·  rules 0  ·  Tab = evidence board (tool pages)  "
                "·  X = stamp mode (stego page)",
                error=False,
            )

        elif kind == "quit":
            self.app.exit()


class EODScreen(Screen):
    BINDINGS = [
        Binding("space", "continue_game", "Continue"),
        Binding("q", "quit_app", "Quit"),
    ]

    def __init__(self, day: Day, state: GameState, narrative: str,
                 performance: Performance, hd_earned: int = 0,
                 hd_bonus: int = 0, health_delta: float = 0.0) -> None:
        super().__init__()
        self._day          = day
        self._state        = state
        self._narrative    = narrative
        self._performance  = performance
        self._hd_earned    = hd_earned      # HD$ from verdicts today (issue #21)
        self._hd_bonus     = hd_bonus       # HD$ Site Health bonus (issue #20)
        self._health_delta = health_delta   # Site Health change over the day
        self._overseer_log: TypewriterLog | None = None

    def compose(self) -> ComposeResult:
        yield Static(f"[b][#7dd3c0]End of {self._day.title}[/][/]",
                     classes="screen-title")
        with Container(id="eod-summary"):
            correct = sum(1 for r in self._state.pending_results if r.correct)
            total   = len(self._state.pending_results)
            yield Static(f"Verdicts: [b]{correct}[/]/{total} correct")
            yield Static(
                f"Computing hours: [#ffb454][b]{self._state.compute_hours} ⏱[/][/] "
                f"left unspent  [dim](daily budget — does not carry over)[/]"
            )
            h    = self._state.site_health
            hcol = ("#00ff9f" if h >= config.SITE_HEALTH_REWARD_THRESHOLD else
                    "#ffd93d" if h >= config.SITE_HEALTH_LOSS_THRESHOLD + 15 else
                    "#ff5470")
            dcol = "#00ff9f" if self._health_delta >= 0 else "#ff5470"
            yield Static(
                f"Site Health: [{hcol}][b]{h:.0f}%[/][/]  "
                f"[{dcol}]({self._health_delta:+.1f} today)[/]"
            )
            hd_bonus_str = (f"  [#00ff9f]+{self._hd_bonus}[/] health bonus"
                            if self._hd_bonus else "  [dim](no health bonus)[/]")
            yield Static(
                f"HackDollar$: [#00ff9f]+{self._hd_earned}[/] earned{hd_bonus_str}"
                f"  ·  balance [#00ff9f][b]{self._state.hackdollars} HD$[/][/]"
            )
            # #4: name the rate this shift actually paid at, so the decay is
            # visible as a number rather than felt as a vague slump.
            yield Static(
                f"[dim]Rate today: {config.DAY_REWARD_PAYOUT(self._day.number, True)} HD$ "
                f"per correct admit · "
                f"{config.DAY_REWARD_PAYOUT(self._day.number, False)} per correct deny[/]"
            )
            yield Static(f"Alignment: {self._state.alignment:+d}")
            yield Static("")
            for r in self._state.pending_results:
                tag  = "verdict-correct" if r.correct else "verdict-wrong"
                mark = "✓" if r.correct else "✗"
                bonus_str = f"  board+{r.board_bonus}HD$" if r.board_bonus else ""
                yield Static(
                    f"[{tag}]{mark}[/]  {r.archetype.value:<14}  "
                    f"you {r.player_verdict.value:<5}  "
                    f"[#6b7785]⛨{r.site_health_delta:+.1f}  "
                    f"+{r.hackdollar_delta}HD${bonus_str}  "
                    f"Align {r.alignment_delta:+d}[/]"
                )
        with Container(id="overseer-panel"):
            yield Static("[b]Overseer:[/]", classes="speaker")
            self._overseer_log = TypewriterLog(id="eod-overseer")
            yield self._overseer_log
        yield Static(
            f"Performance: [b]{self._performance.value}[/]   ·   "
            "Press [#00ff9f][b]Space[/][/] to save and continue.",
            classes="hint",
        )

    def on_mount(self) -> None:
        # #3: EOD Overseer dialogue types out; the screen keeps Space=continue.
        _play_overseer(self._overseer_log, self._narrative)

    def action_continue_game(self) -> None:
        persistence.save(self._state)
        self.app.show_between_day()   # between-day menu next (issue #22)

    def action_quit_app(self) -> None:
        self.app.exit()


class BetweenDayScreen(Screen):
    """Between-day menu (issues #18/#22) — the campaign's connective tissue.

    Runs after the end-of-day summary and before the next day's intro.
    Three regions: performance summary (the day's numbers landing), Overseer
    contact (tutorial / foreshadowing / the hostility arc), and the
    HackDollar$ shop (upgrades #23, HackDox Credits #19/#25, ⏱ capacity).
    Purchases deduct HackDollar$ and persist immediately.
    """

    BINDINGS = [
        Binding("up",    "cursor_up",   "Up",   show=False),
        Binding("down",  "cursor_down", "Down", show=False),
        Binding("enter", "buy",         "Buy",  show=False),
        Binding("space", "buy",         "Buy",  show=False),
        Binding("n",     "next_day",    "Next day"),
        Binding("q",     "quit_app",    "Quit"),
    ]

    def __init__(self, day: Day, state: GameState, narrative: str,
                 hd_earned: int = 0, hd_bonus: int = 0,
                 health_delta: float = 0.0) -> None:
        super().__init__()
        self._day          = day
        self._state        = state
        self._narrative    = narrative
        self._hd_earned    = hd_earned
        self._hd_bonus     = hd_bonus
        self._health_delta = health_delta
        self._cursor       = 0
        self._status_msg   = ""
        self._status_err   = False
        # Shop catalog: consumables/capacity first, then permanent upgrades.
        items: list[tuple[str, str, int, str, str]] = [
            ("credit",   "hackdox_credit", config.SHOP_PRICE_CREDIT,
             "HackDox Credit +1",
             f"ground-truth reveal charge (max {config.HACKDOX_CREDIT_MAX} slots)"),
            ("capacity", "compute_capacity", config.SHOP_PRICE_CAPACITY,
             f"Compute Capacity +{config.COMPUTE_CAPACITY_STEP} ⏱",
             "permanently raise the per-shift computing-hours budget"),
        ]
        for uid, label, price, desc in config.UPGRADE_CATALOG:
            items.append(("upgrade", uid, price, label, desc))
        self._items = items
        self._summary_w = Static(id="bd-summary", classes="panel")
        self._shop_w    = Static(id="bd-shop", classes="panel")

    def compose(self) -> ComposeResult:
        yield Static(
            f"[b][#7dd3c0]HACKDOX — NIGHT OF DAY {self._day.number}[/][/]",
            classes="screen-title",
        )
        with Horizontal(id="bd-root"):
            with Vertical(id="bd-left"):
                yield self._summary_w
                with Container(id="bd-overseer"):
                    yield Static("[b]Overseer:[/]", classes="speaker")
                    # #3: the 3rd TypewriterLog host (called out in the issue's
                    # own comment). Not focused, so Space still buys in the shop.
                    self._overseer_log = TypewriterLog(id="bd-overseer-text")
                    yield self._overseer_log
            yield self._shop_w
        yield Static(
            "[#00ff9f][b]↑↓[/][/] browse shop  ·  [#00ff9f][b]Enter[/][/] buy  ·  "
            "[#00ff9f][b]N[/][/] begin next day  ·  [#00ff9f][b]Q[/][/] quit",
            classes="hint",
        )

    def on_mount(self) -> None:
        self._summary_w.border_title = " Shift Report "
        self._shop_w.border_title    = " HackDollar$ Shop "
        _play_overseer(self._overseer_log, self._narrative)
        self._repaint()

    # ── Rendering ─────────────────────────────────────────────────────

    def _repaint(self) -> None:
        self._summary_w.update(self._summary_text())
        self._shop_w.update(self._shop_text())

    def _next_shift_terms(self) -> str:
        """#4: what next shift will pay, and what it will charge.

        The difficulty curve is only legible as escalation if the player can
        see it arriving. Shown here rather than on the EOD screen because this
        is the screen where they decide what to spend HackDollar$ on — knowing
        tool costs are about to step up is exactly the input to that decision.
        Only rates that actually CHANGE are called out, so a mid-tutorial day
        doesn't nag about a curve that hasn't moved yet.
        """
        st   = self._state
        d    = self._day.number
        nxt  = d + 1
        bits: list[str] = []

        pay_now, pay_next = (config.DAY_REWARD_PAYOUT(d, True),
                             config.DAY_REWARD_PAYOUT(nxt, True))
        if pay_next != pay_now:
            bits.append(f"[#ffd93d]correct admit {pay_now} → {pay_next} HD$[/]")
        else:
            bits.append(f"[dim]correct admit {pay_next} HD$[/]")

        costs_now  = {t: tools_bridge.tool_cost(st, t) for t in config.TOOL_COSTS}
        costs_next = {t: config.DAY_TOOL_COST(t, nxt, st.upgrades)
                      for t in config.TOOL_COSTS}
        strip = " ".join(
            f"{t[0].upper()}{costs_next[t]}" for t in sorted(config.TOOL_COSTS))
        if costs_next != costs_now:
            bits.append(f"[#ff8c42]tool costs rise → {strip}[/]")
        else:
            bits.append(f"[dim]tools {strip}[/]")
        return "  ·  ".join(bits)

    def _summary_text(self) -> str:
        st      = self._state
        results = st.pending_results
        correct = sum(1 for r in results if r.correct)
        total   = len(results)
        # Issue #27: ⏱ is a spend-only daily pool — spent = budget − leftover.
        budget      = config.daily_compute_budget(self._day.number,
                                                  st.compute_capacity)
        spent       = max(0, budget - st.compute_hours)
        next_budget = config.daily_compute_budget(self._day.number + 1,
                                                  st.compute_capacity)
        # #38: how often the literal ruleset and the moral ground truth pulled
        # in different directions this shift.
        diverged = sum(1 for r in results if r.tracks_diverge)
        board   = sum(r.board_bonus for r in results)
        board_max = max(1, total * config.BOARD_ACCURACY_MAX_BONUS)
        board_pct = round(100 * board / board_max)
        h    = st.site_health
        hcol = ("#00ff9f" if h >= config.SITE_HEALTH_REWARD_THRESHOLD else
                "#ffd93d" if h >= config.SITE_HEALTH_LOSS_THRESHOLD + 15 else
                "#ff5470")
        filled = max(0, min(20, round(h / 5)))
        bar    = "█" * filled + "░" * (20 - filled)
        dcol   = "#00ff9f" if self._health_delta >= 0 else "#ff5470"
        acol   = "#ff5470" if st.alignment < 0 else "#00ff9f"
        align_lbl = ("Dark Web" if st.alignment < 0 else
                     "White Hat" if st.alignment > 0 else "Neutral")
        hd_bonus_str = (f"  [#00ff9f]+{self._hd_bonus}[/] health bonus"
                        if self._hd_bonus else "  [dim](no health bonus)[/]")
        return "\n".join([
            f"[#6b7785]Verdicts[/]        [b]{correct}[/]/{total} correct",
            f"[#6b7785]⏱ spent[/]         [#ffb454]−{spent}[/] of {budget}"
            f"   [dim](fresh budget next shift: {next_budget} ⏱ — no carry-over)[/]",
            f"[#6b7785]Next shift[/]      {self._next_shift_terms()}",
            f"[#6b7785]Board accuracy[/]  {board_pct}%  [dim](paid as HD$ bonus)[/]",
            f"[#6b7785]Alignment[/]       [{acol}]{st.alignment:+d} ({align_lbl})[/]"
            + (f"   [#c084fc]· {diverged} verdict(s) where the book and your "
               f"conscience disagreed[/]" if diverged else ""),
            "",
            f"[#6b7785]HackDollar$[/]     [#00ff9f]+{self._hd_earned}[/] verdicts{hd_bonus_str}",
            f"[#6b7785]Balance[/]         [#00ff9f][b]{st.hackdollars} HD$[/][/]",
            "",
            f"[#6b7785]Site Health[/]     [{hcol}]{bar}[/]  [{hcol}][b]{h:.0f}%[/][/]"
            f"  [{dcol}]({self._health_delta:+.1f} applied at end of day)[/]",
            f"[dim]health only moves at shift end · game over below "
            f"{config.SITE_HEALTH_LOSS_THRESHOLD:.0f}%"
            f" · bonus above {config.SITE_HEALTH_REWARD_THRESHOLD:.0f}%[/]",
        ] + ([
            "",
            f"[#ff5470][b]▼ SITE HEALTH BELOW {config.SITE_HEALTH_LOSS_THRESHOLD:.0f}% "
            f"— HACKDOX IS LOST[/][/]",
            "[#ff5470]The day's admissions took the site down. "
            "Press N to face the consequences.[/]",
        ] if scoring.health_below_loss(st) else []))

    def _shop_text(self) -> str:
        st = self._state
        lines = [
            f"[#6b7785]balance[/] [#00ff9f][b]{st.hackdollars} HD$[/][/]"
            f"   [#6b7785]credits[/] [#c084fc]{st.hackdox_credits}/{config.HACKDOX_CREDIT_MAX}[/]"
            f"   [#6b7785]⏱ cap[/] [#ffb454]{st.compute_capacity}[/]",
            "",
        ]
        for idx, (kind, iid, price, label, desc) in enumerate(self._items):
            owned  = kind == "upgrade" and iid in st.upgrades
            capped = kind == "credit" and st.hackdox_credits >= config.HACKDOX_CREDIT_MAX
            afford = st.hackdollars >= price
            cur    = idx == self._cursor
            if owned:
                tag, lcol = "[#6b7785]OWNED [/]", "#6b7785"
            elif capped:
                tag, lcol = "[#6b7785]FULL  [/]", "#6b7785"
            elif afford:
                tag, lcol = f"[#00ff9f]{price:>3} $[/] ", "#c8d4e1"
            else:
                tag, lcol = f"[#ff5470]{price:>3} $[/] ", "#5a6775"
            marker = "[#00ffd5]▶ [/]" if cur else "  "
            lbl    = f"[reverse] {label} [/]" if cur else f"[{lcol}]{label}[/]"
            lines.append(f"{marker}{tag} {lbl}")
            if cur:
                lines.append(f"      [dim]{desc}[/]")
        lines.append("")
        if self._status_msg:
            scol = "#ff5470" if self._status_err else "#7dd3c0"
            lines.append(f"[{scol}]{self._status_msg}[/]")
        else:
            lines.append("[dim]Enter to buy · N for next day[/]")
        return "\n".join(lines)

    # ── Actions ───────────────────────────────────────────────────────

    def action_cursor_up(self) -> None:
        self._cursor = max(0, self._cursor - 1)
        self._repaint()

    def action_cursor_down(self) -> None:
        self._cursor = min(len(self._items) - 1, self._cursor + 1)
        self._repaint()

    def action_buy(self) -> None:
        kind, iid, price, label, _desc = self._items[self._cursor]
        st = self._state
        if kind == "upgrade" and iid in st.upgrades:
            self._flash(f"{label} already owned", err=True)
            return
        if kind == "credit" and st.hackdox_credits >= config.HACKDOX_CREDIT_MAX:
            self._flash("credit slots full", err=True)
            return
        if st.hackdollars < price:
            self._flash(
                f"insufficient HackDollar$ — need {price}, have {st.hackdollars}",
                err=True)
            return
        st.hackdollars -= price
        if kind == "upgrade":
            st.upgrades.add(iid)
        elif kind == "credit":
            st.hackdox_credits += 1
        else:
            st.compute_capacity += config.COMPUTE_CAPACITY_STEP
        persistence.save(st)   # purchases persist immediately (issue #22)
        self._flash(f"purchased {label}  (−{price} HD$)", err=False)

    def _flash(self, msg: str, err: bool) -> None:
        self._status_msg = msg
        self._status_err = err
        self._repaint()

    def action_next_day(self) -> None:
        # #20 rework: the loss condition is evaluated at end of day. If the
        # batch application dropped health below the threshold, the campaign
        # ends here instead of advancing.
        if scoring.health_below_loss(self._state):
            self.app.game_over()
            return
        self.app.advance_day()

    def action_quit_app(self) -> None:
        persistence.save(self._state)
        self.app.exit()


class CampaignEndScreen(Screen):
    """Shown when the next day's content doesn't exist yet."""

    BINDINGS = [Binding("q", "quit_app", "Quit")]

    def __init__(self, day_number: int) -> None:
        super().__init__()
        self._day_number = day_number

    def compose(self) -> ComposeResult:
        with Container(id="splash"):
            yield Static("[b][#00ff9f]TO BE CONTINUED[/][/]", classes="title")
            yield Static(
                f"Day {self._day_number} isn't written yet. Your save is stored — "
                "the campaign resumes when the content lands.",
                classes="subtitle",
            )
            yield Static("[#00ff9f][b]Q[/][/]  Quit", classes="hint")

    def action_quit_app(self) -> None:
        self.app.exit()


class GameOverScreen(Screen):
    BINDINGS = [
        Binding("r", "restart", "Restart"),
        Binding("q", "quit_app", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="splash"):
            yield Static("[b][#ff5470]GAME OVER[/][/]", classes="title")
            yield Static(
                "Site Health collapsed — the threats you admitted took the site down.",
                classes="subtitle",
            )
            yield Static(
                "[#00ff9f][b]R[/][/] Restart     [#00ff9f][b]Q[/][/] Quit",
                classes="hint",
            )

    def action_restart(self) -> None:
        self.app.start_new_game()

    def action_quit_app(self) -> None:
        self.app.exit()


# ─── App ────────────────────────────────────────────────────────────────────────────────


class HackDoxApp(App):
    CSS_PATH = "app.tcss"
    TITLE    = "HackDox Terminal"
    SUB_TITLE = "Cybersecurity Access Review"

    def __init__(self, seed: int = 0xC0FFEE, lab_day: "Day | None" = None) -> None:
        super().__init__()
        self._seed       = seed
        # #52: `hackdox lab --play` hands in a pre-constrained Day so a shift can
        # be played with a pinned archetype / violation set. When set it replaces
        # the loaded day everywhere, and advance_day ends the run after it rather
        # than rolling into normal content — a lab shift is one shift on purpose.
        self._lab_day    = lab_day
        self._state: GameState | None = None
        self._day:   Day        | None = None
        self._narratives: dict[str, str] = {}
        self._day_start_health: float = config.SITE_HEALTH_START
        self._hd_earned = 0   # HD$ from verdicts, set at finish_day
        self._hd_bonus  = 0   # HD$ Site Health bonus, set at finish_day

    def on_mount(self) -> None:
        self._narratives = load_narratives()
        self.push_screen(IntroScreen())

    def start_new_game(self) -> None:
        self._state = GameState(
            seed=self._seed,
            current_day=1,
            compute_hours=config.daily_compute_budget(1, config.STARTING_COMPUTE),
            compute_capacity=config.STARTING_COMPUTE,
            alignment=config.STARTING_ALIGNMENT,
            site_health=config.SITE_HEALTH_START,
            hackdollars=config.STARTING_HACKDOLLARS,
            hackdox_credits=config.STARTING_HACKDOX_CREDITS,
        )
        if self._lab_day is not None:
            self._state.current_day = self._lab_day.number
            self._state.compute_hours = config.daily_compute_budget(
                self._lab_day.number, config.STARTING_COMPUTE)
            # A lab shift skips the unlock schedule: pinning a stegotool case on
            # day 5 is pointless if stegotool is still locked.
            self._state.unlocked_tools = config.tools_unlocked_by(
                max(self._lab_day.number, max(config.TOOL_UNLOCK_DAY.values())))
        self._day_start_health = self._state.site_health
        self._day = self._lab_day or load_day(self._state.current_day)
        narrative = self._narratives.get(self._day.overseer_intro_key, "")
        self.pop_screen()
        self.push_screen(BriefingScreen(self._day, narrative, self._state))

    def begin_intake(self) -> None:
        assert self._state is not None and self._day is not None
        self._day_start_health = self._state.site_health
        intro = self._narratives.get(self._day.overseer_intro_key, "")
        self.pop_screen()
        self.push_screen(IntakeScreen(self._day, self._state, intro))

    def finish_day(self) -> None:
        assert self._state is not None and self._day is not None
        # #20 rework: the day's accumulated Site Health deltas land HERE, in
        # one batch — health never moves mid-shift, so the loss condition is
        # only evaluated from this point on.
        scoring.apply_end_of_day_health(self._state)
        # End-of-day HackDollar$ payout (issue #21): verdict earnings accrued
        # during play; the Site Health bonus (issue #20) lands here.
        self._hd_earned = sum(r.hackdollar_delta
                              for r in self._state.pending_results)
        self._hd_bonus  = scoring.eod_health_bonus(self._state)
        self._state.hackdollars += self._hd_bonus
        performance = self._evaluate_performance()
        outro_key   = self._day.overseer_outro_keys.get(
            performance, self._day.overseer_outro_keys[Performance.PASSING]
        )
        narrative = self._narratives.get(outro_key, "...")
        self.pop_screen()
        self.push_screen(EODScreen(
            self._day, self._state, narrative, performance,
            hd_earned=self._hd_earned, hd_bonus=self._hd_bonus,
            health_delta=self._state.site_health - self._day_start_health,
        ))

    def game_over(self) -> None:
        self.pop_screen()
        self.push_screen(GameOverScreen())

    def show_between_day(self) -> None:
        """EOD → between-day menu (issue #22)."""
        assert self._state is not None and self._day is not None
        narrative = self._narratives.get(
            f"day{self._day.number}_between",
            "Rest while you can. Tomorrow's list is longer, and the rules "
            "won't be getting any kinder. Spend your HackDollar$ wisely.",
        )
        self.pop_screen()
        self.push_screen(BetweenDayScreen(
            self._day, self._state, narrative,
            hd_earned=self._hd_earned, hd_bonus=self._hd_bonus,
            health_delta=self._state.site_health - self._day_start_health,
        ))

    def advance_day(self) -> None:
        """Between-day menu → next day intro. Resets the shift budget."""
        assert self._state is not None
        st = self._state
        if scoring.health_below_loss(st):   # loss trips at end of day (#20)
            self.game_over()
            return
        # #36: hold on to yesterday's ruleset before loading today's, so the
        # briefing can diff the two and announce what the Overseer moved.
        prev_day = self._day
        if self._lab_day is not None:
            # One shift, then out — a lab run has no day 2.
            self.pop_screen()
            self.push_screen(CampaignEndScreen(st.current_day))
            return
        st.current_day += 1
        st.current_slot_index = 0
        st.pending_results = []
        # ⏱ resets to the day's fixed budget every shift — never carries
        # over (issues #21/#27). The formula scales with the day number.
        st.compute_hours = config.daily_compute_budget(
            st.current_day, st.compute_capacity)
        persistence.save(st)
        try:
            self._day = load_day(st.current_day)
        except FileNotFoundError:
            self.pop_screen()
            self.push_screen(CampaignEndScreen(st.current_day))
            return
        self._day_start_health = st.site_health
        narrative = self._narratives.get(self._day.overseer_intro_key, "")
        self.pop_screen()
        self.push_screen(BriefingScreen(self._day, narrative, self._state,
                                        prev_day=prev_day))

    def _evaluate_performance(self) -> Performance:
        assert self._state is not None and self._day is not None
        correct_admits = sum(
            1 for r in self._state.pending_results
            if r.correct and r.player_verdict == Verdict.ADMIT
        )
        false_admits = sum(
            1 for r in self._state.pending_results
            if not r.correct and r.player_verdict == Verdict.ADMIT
        )
        quotas = self._day.quotas
        if scoring.health_below_loss(self._state):
            return Performance.FAILED
        if false_admits > quotas.max_false_admits:
            return Performance.FAILED
        if correct_admits < quotas.min_correct_admits:
            return Performance.POOR
        # (compute_target check removed — issue #27: ⏱ is spend-only, so an
        # end-of-day balance target no longer exists.)
        wrong = sum(1 for r in self._state.pending_results if not r.correct)
        if wrong == 0:
            return Performance.EXCELLENT
        return Performance.PASSING


def run(seed: int = 0xC0FFEE, lab_day: "Day | None" = None) -> None:
    HackDoxApp(seed=seed, lab_day=lab_day).run()


if __name__ == "__main__":
    run()
