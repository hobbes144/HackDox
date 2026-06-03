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
from textual.screen import ModalScreen, Screen
from textual.widgets import ContentSwitcher, Footer, Static, TabbedContent, TabPane

from gameengine import config
from gameengine.core import candidate_gen, scoring, tools_bridge

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

# (group_label, DiscrepancyKind, display_label)
EVIDENCE_ITEMS: list[tuple[str, DiscrepancyKind, str]] = [
    ("DOSSIER",     DiscrepancyKind.MISSING_PUBLIC_PROFILE, "Missing public profile"),
    ("DOSSIER",     DiscrepancyKind.HOSTILE_CHAT,           "Hostile chat"),
    ("DOSSIER",     DiscrepancyKind.AFFILIATION_UNVERIFIED, "Unverified affiliation"),
    ("OSINT",       DiscrepancyKind.EMAIL_GITHUB_MISMATCH,  "Email / GitHub mismatch"),
    ("OSINT",       DiscrepancyKind.BREACH_HIT,             "Breach hit"),
    ("OSINT",       DiscrepancyKind.SOCK_PUPPET_ACCOUNTS,   "Sock puppet accounts"),
    ("FORENSICS",   DiscrepancyKind.BRUTE_FORCE_IN_LOG,     "Brute force in log"),
    ("FORENSICS",   DiscrepancyKind.IMPOSSIBLE_TRAVEL,      "Impossible travel"),
    ("FORENSICS",   DiscrepancyKind.INSIDER_BEHAVIOR,       "Insider behavior"),
    ("CREDENTIAL",  DiscrepancyKind.LEAKED_PASSWORD,        "Leaked password"),
    ("CREDENTIAL",  DiscrepancyKind.WEAK_CREDENTIAL,        "Weak credential"),
    ("STEGO",       DiscrepancyKind.STEGO_PAYLOAD_PRESENT,  "Stego payload"),
    ("STEGO",       DiscrepancyKind.COVERT_C2_CHANNEL,      "Covert C2 channel"),
]
_ITEM_COUNT = len(EVIDENCE_ITEMS)

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
[#00ff9f]extract[/] run stegotool  [dim](page 5)[/]

[dim]── other ──────────────────────────[/]
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

[dim]── hash types ────────────────────[/]
[dim]MD5    32 hex  = weak[/]
[dim]SHA1   40 hex  = deprecated[/]
[dim]SHA256 64 hex  = stronger[/]
[dim]bcrypt $2b$    = strong[/]

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

_REF_STEGOTOOL = """[#7dd3c0][b]COMMANDS — STEGOTOOL[/][/]

[#00ff9f]extract[/]  [dim]or[/] [#00ff9f]stegotool[/]  [dim]or[/] [#00ff9f]s[/]
  composite suspicion score —
  chi-square, RS analysis,
  LSB autocorrelation
  [dim]cost: 2 ⏱[/]

[#c084fc]filter[/]  [dim]or[/] [#c084fc]f[/]
  per-channel LSB breakdown —
  explicit STEGO_PAYLOAD /
  COVERT_C2_CHANNEL flag
  [dim]cost: +2 ⏱[/]

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
    # Stegotool
    "extract":    ("tool",    ToolName.STEGOTOOL),
    "stegotool":  ("tool",    ToolName.STEGOTOOL),
    "stego":      ("tool",    ToolName.STEGOTOOL),
    "s":          ("tool",    ToolName.STEGOTOOL),
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
    "help":       ("help",    None),
    "?":          ("help",    None),
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


# ─── Widgets ─────────────────────────────────────────────────────────────────


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
        hearts = "♥" * self.state.lives + "·" * (config.STARTING_LIVES - self.state.lives)
        align  = self.state.alignment
        bar    = ""
        for v in range(-4, 5):
            bar += "●" if v == max(-4, min(4, align)) else "·"
        tabs = "  ".join(
            f"[b]◉ [{i+1}]{n}[/]" if i == self.page_index else f"[dim]○ [{i+1}]{n}[/]"
            for i, n in enumerate(_PAGE_NAMES)
        )
        return (
            f"[#00ff9f][b]HACKDOX[/][/]  [dim]│[/]  [b]{self.day.title}[/]  "
            f"[dim]│[/]  [{self.slot_index + 1}/{self.day.candidate_count}]  "
            f"[dim]│[/]  [#ffb454]{self.state.compute_hours} ⏱[/]  "
            f"[#ff5470]{hearts}[/]  "
            f"[{'#ff5470' if align < 0 else '#00ff9f'}]{bar}[/]"
            f"  [dim]│[/]  {tabs}"
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
        if d.submitted_hash:
            htype = "MD5" if len(d.submitted_hash) == 32 else "SHA256"
            h_str = f"{d.submitted_hash[:20]}...  [#6b7785]{htype}[/]"
        else:
            h_str = "[dim](none)[/]"
        rows = [
            "[#3d6478]-- identity ------------------------------------------[/]",
            f"  [#6b7785]Name[/]         [b]{c.display_name}[/]",
            f"  [#6b7785]Handle[/]       {c.handle}",
            f"  [#6b7785]Email[/]        {c.email}",
            f"  [#6b7785]Affiliation[/]  {c.claimed_affiliation}",
            f"  [#6b7785]GitHub[/]       {gh}",
            "",
            "[#3d6478]-- submitted artifacts --------------------------------[/]",
            f"  [#6b7785]IP[/]           {ip}",
            f"  [#6b7785]Hash[/]         {h_str}",
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

    def set_candidate(self, candidate: Candidate) -> None:
        self._candidate = candidate
        self.refresh()

    def render(self) -> str:
        if self._candidate is None:
            return "[dim]—[/]"
        c  = self._candidate
        gh = c.dossier.claimed_github or "[dim](none)[/]"
        ip = c.dossier.claimed_ip     or "[dim](none)[/]"
        return "\n".join([
            f"[#6b7785]Name[/]   [b]{c.display_name}[/]",
            f"[#6b7785]Handle[/] {c.handle}",
            f"[#6b7785]Email[/]  {c.email}",
            f"[#6b7785]IP[/]     {ip}",
            f"[#6b7785]Org[/]    {c.claimed_affiliation}",
            f"[#6b7785]GitHub[/] {gh}",
        ])


class ChatPanel(VerticalScroll):
    """One-way candidate dialogue."""

    def __init__(self) -> None:
        super().__init__(id="chat", classes="panel")
        self.border_title = " Chat "

    _TAG_STYLE: dict[str, tuple[str, str]] = {
        "neutral":  ("#c8d4e1", ""),
        "warm":     ("#7dd3c0", ""),
        "hostile":  ("#ff5470", "bold"),
        "flippant": ("#c084fc", "italic"),
        "earnest":  ("#7dd3c0", ""),
        "intro":    ("#c8d4e1", "italic"),
    }

    def set_candidate(self, candidate: Candidate) -> None:
        self.remove_children()
        first = candidate.display_name.split()[0]
        for line in candidate.chat_script:
            tag = line.tag
            if tag.startswith("hint:"):
                col, sty = "#ff8c42", "italic"
            else:
                col, sty = self._TAG_STYLE.get(tag, ("#c8d4e1", ""))
            markup = f"[{col} {sty}]{line.text}[/]" if sty else f"[{col}]{line.text}[/]"
            self.mount(Static(f"[#6b7785]{line.timestamp}[/]  [b]{first}:[/]  {markup}"))
        self.mount(Static(""))


class EvidenceBoard(Static):
    """Player-controlled evidence checklist.

    Nothing is ever written here automatically. The player uses ↑↓ to
    move the cursor and Space to toggle a flag. ← / → are NOT consumed
    here — they bubble up to the screen for page navigation.
    """

    can_focus = True

    def __init__(self) -> None:
        super().__init__(id="evidence-board")
        self.border_title = " Evidence Board  [dim](Tab to focus · ↑↓ cursor · Space flag)[/] "
        self._cursor: int = 0
        self._flags: set[DiscrepancyKind] = set()
        self._focused: bool = False

    # ── State management ──────────────────────────────────────────────

    def clear(self) -> None:
        self._cursor = 0
        self._flags.clear()
        self.refresh()

    def get_flags(self) -> set[DiscrepancyKind]:
        return set(self._flags)

    # ── Focus tracking ────────────────────────────────────────────────

    def on_focus(self) -> None:
        self._focused = True
        self.refresh()

    def on_blur(self) -> None:
        self._focused = False
        self.refresh()

    # ── Key handling ──────────────────────────────────────────────────

    def on_key(self, event: Key) -> None:
        if event.key == "up":
            self._cursor = max(0, self._cursor - 1)
            event.stop()
            self.refresh()
        elif event.key == "down":
            self._cursor = min(_ITEM_COUNT - 1, self._cursor + 1)
            event.stop()
            self.refresh()
        elif event.key == "space":
            kind = EVIDENCE_ITEMS[self._cursor][1]
            if kind in self._flags:
                self._flags.discard(kind)
            else:
                self._flags.add(kind)
            event.stop()
            self.refresh()
        # ← / → are NOT stopped — they bubble to IntakeScreen for page nav.

    # ── Rendering ─────────────────────────────────────────────────────

    def render(self) -> str:
        lines: list[str] = []
        current_group = ""
        for idx, (group, kind, label) in enumerate(EVIDENCE_ITEMS):
            if group != current_group:
                _hints = {"OSINT": "[dim] G[/]", "FORENSICS": "[dim] L[/]",
                           "CREDENTIAL": "[dim] H[/]", "STEGO": "[dim] S[/]"}
                hint = _hints.get(group, "")
                sep = "─" * max(1, 22 - len(group))
                lines.append(f"[#2e3d4f]── {group}[/]{hint}[#2e3d4f] {sep}[/]")
                current_group = group

            flagged  = kind in self._flags
            at_cursor = idx == self._cursor and self._focused
            flag_str = "[#ffb454]✓[/]" if flagged else " "

            if at_cursor:
                lines.append(f"  {flag_str} [reverse] {label} [/]")
            elif flagged:
                lines.append(f"  {flag_str} [#ffb454]{label}[/]")
            else:
                lines.append(f"  {flag_str} [#c8d4e1]{label}[/]")

        if not self._focused:
            lines.append("")
            lines.append("[dim]Tab to focus · ↑↓ move · Space flag[/]")
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
        self._compute_spent += max(0, compute_before - compute_after + result.compute_delta)
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

    def __init__(self, day: Day) -> None:
        super().__init__()
        self._day = day

    def compose(self) -> ComposeResult:
        with Container(id="rules-modal"):
            yield Static("[b][#7dd3c0]HACKDOX  DOCUMENTATION HUB[/][/]", id="rules-title")
            with TabbedContent(id="rules-tabs"):
                with TabPane("Rules", id="tab-rules"):
                    with VerticalScroll():
                        yield Static(self._build_rules_text(), classes="rules-section")
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
            yield Static(
                f"[dim]Tab/click to switch sections  ·  "
                f"Press [b]{_B['page_rules'].upper()}[/] or Esc to close[/]",
                id="rules-hint",
            )

    # ── Tab content builders ──────────────────────────────────────────

    def _build_rules_text(self) -> str:
        kb    = config.KEY_BINDINGS
        costs = config.TOOL_COSTS
        fcosts = config.FILTER_COSTS
        rules = self._day.rules if self._day else []
        lines = [f"[#6b7785]{self._day.title}[/]\n"]

        disq  = [r for r in rules if r.severity == "disqualifying"]
        minor = [r for r in rules if r.severity != "disqualifying"]

        if disq:
            lines.append("[#ff5470][b]DISQUALIFYING[/][/]  — any one of these → DENY")
            for r in disq:
                lines.append(f"  [#ff5470]✗[/]  {r.text}")
            lines.append("")
        if minor:
            lines.append("[#ff8c42][b]MINOR DISCREPANCIES[/][/]  — flag on Evidence Board")
            for r in minor:
                lines.append(f"  [#ff8c42]△[/]  {r.text}")
            lines.append("")
        if not rules:
            lines.append("[dim]No rules loaded for this day.[/]\n")

        lines += [
            "[#6b7785]── general principles ───────────────────────────────────────────[/]",
            "  Multiple minor discrepancies may constitute grounds for denial.",
            "  Flag everything you notice on the Evidence Board — accuracy earns ⏱.",
            "  Moral alignment shifts on certain verdicts regardless of rule correctness.",
            "",
            "[#6b7785]── tool costs ───────────────────────────────────────────────────[/]",
            f"  [b]{kb['tool_ghostscan'].upper()}[/] Ghostscan   {costs['ghostscan']}⏱   filter +{fcosts['ghostscan']}⏱",
            f"  [b]{kb['tool_hashcrack'].upper()}[/] Hashcrack   {costs['hashcrack']}⏱   filter +{fcosts['hashcrack']}⏱",
            f"  [b]{kb['tool_logwatch'].upper()}[/] Logwatch    {costs['logwatch']}⏱   filter +{fcosts['logwatch']}⏱",
            f"  [b]{kb['tool_stegotool'].upper()}[/] Stegotool   {costs['stegotool']}⏱   filter +{fcosts['stegotool']}⏱",
            "",
            "[#6b7785]── economy ───────────────────────────────────────────────────────[/]",
            "  Correct verdict:       +15⏱  +up to 10⏱ board accuracy bonus",
            "  False admit (invalid): −1 life",
            "  False deny (valid):    no penalty — just lost reward",
            "",
            "[#6b7785]── email domains ────────────────────────────────────────────────[/]",
            "[#00ff9f]✓  TRUSTED[/]",
            "   gmail.com · outlook.com · hotmail.com · yahoo.com · icloud.com",
            "   .edu · .ac.uk · .gov · .mil · company addresses from verified employers",
            "[#ff5470]✗  DISPOSABLE / THROWAWAY[/]",
            "   mailinator.com · guerrillamail.com · tempmail.com · yopmail.com",
            "   throwam.com · trashmail.com · maildrop.cc · fakeinbox.com",
            "[#ff8c42]?  PRIVACY-FORWARD[/] (flag if other discrepancies present)",
            "   protonmail.com · tutanota.com · pm.me",
            "",
            "[#6b7785]── affiliations ─────────────────────────────────────────────────[/]",
            "[#00ff9f]✓  TRUSTED INSTITUTIONS[/]",
            "   MIT · Stanford · CMU · Caltech · Harvard · Yale · Oxford",
            "   Cambridge · ETH Zurich · Imperial College",
            "   Google · Microsoft · Apple · Cloudflare · Stripe · GitHub",
            "[#ff5470]✗  THREAT ACTOR COMMUNITIES[/]",
            "   BreachForums · RaidForums · HackForums · XSS.is · CrackingKing",
            "[#ff8c42]?  UNVERIFIABLE[/] (requires corroborating evidence)",
            "   \"independent\" · \"freelance\" · \"self-employed\" · \"consultant\"",
        ]
        return "\n".join(lines)

    def _build_osint_text(self) -> str:
        return """[#7dd3c0][b]GHOSTSCAN — OSINT REFERENCE[/][/]

[#6b7785]── forum tiers — check the platform sweep against these ─────────[/]

[#ff5470][b]CRITICAL — immediate deny[/][/]
  Any confirmed handle on these forums is grounds for an always-deny verdict.
  Cross-reference the handle in the candidate's platform sweep output.

[#ff5470]✗[/]  BreachForums   primary stolen-data marketplace
[#ff5470]✗[/]  RaidForums     predecessor to BreachForums, same community
[#ff5470]✗[/]  HackForums     credential dumps, exploit trading
[#ff5470]✗[/]  XSS.is         Russian-language exploit / malware forum

[#ff8c42][b]ADVISORY — investigate further[/][/]
  A single advisory hit is not sufficient to deny alone.
  Combine with other signals (breach dump, affiliation gap, weak credential).

[#ff8c42]?[/]  nulled.to      leaked databases, cracked software
[#ff8c42]?[/]  CrackingKing   account cracking, combo list trading
[#ff8c42]?[/]  Dread          dark-web Reddit equivalent
[#ff8c42]?[/]  CrackingPro    account combo trading
[#ff8c42]?[/]  Breach dumps   Collection #1 · LinkedIn 2016 · RockYou 2024
               (email in dump = advisory, not standalone denial)

[#6b7785]── violation signals ──────────────────────────────────────────[/]

[#ff5470]SOCK_PUPPET_ACCOUNTS[/]
   Handle appears on a critical forum in the platform sweep.
   Rule GS-01: always-deny. Single hit settles the verdict.

[#ff8c42]BREACH_HIT[/]
   Candidate email found in a breach dump in the sweep.
   Advisory — combine with credential findings for a deny.

[#ff8c42]AFFILIATION_UNVERIFIED[/]
   Claimed org (shown in yellow in dossier) absent from platform sweep.
   Handle appears without org tag, or under a different org. Rule GS-05.

[#ff8c42]EMAIL_GITHUB_MISMATCH[/]
   GitHub sweep shows a commit email that differs from the dossier email.
   Requires filter run to confirm. Rule GS-04.

[#6b7785]── legitimate platforms (presence expected) ─────────────────────[/]
[#00ff9f]✓[/]  GitHub       [#00ff9f]✓[/]  LinkedIn     [#00ff9f]✓[/]  Twitter/X
[#00ff9f]✓[/]  HackerNews   [#00ff9f]✓[/]  Reddit       [#00ff9f]✓[/]  Keybase

[#6b7785]── affiliation verification ─────────────────────────────────────[/]
  The candidate's claimed org is shown in yellow in the condensed dossier.
  Run G and check whether that org appears as a tag alongside their handle.
  If absent on 2+ platforms → flag AFFILIATION_UNVERIFIED on Evidence Board.

[#6b7785]── investigation tiers ──────────────────────────────────────────[/]
  Free:   passive check — email domain, affiliation, GitHub claim
  Run G:  platform sweep — handle on legit platforms + threat forum section
  Filter: explicit ▲ VIOLATION_TYPE labels"""

    def _build_creds_text(self) -> str:
        return """[#7dd3c0][b]HASHCRACK — CREDENTIAL REFERENCE[/][/]

[#6b7785]── hash types ───────────────────────────────────────────────────[/]
[#ff8c42]MD5[/]      32 hex chars   e.g. 5f4dcc3b5aa765d61d8327deb882cf99
           Fast to crack (~5M attempts/sec). Considered broken.

[#ff8c42]SHA-1[/]    40 hex chars   e.g. aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d
           Faster than SHA-256. Deprecated for security use.

[#ff8c42]SHA-256[/]  64 hex chars   e.g. 5e884898da28047151d0e56f...
           Stronger, but still vulnerable to dictionary + rules attacks.

[#00ff9f]bcrypt[/]   starts $2b$    e.g. $2b$12$...
           Intentionally slow (~100 attempts/sec). Hard to crack.
           Tool will attempt 200 candidates then stop — educational demo.

[#6b7785]── violation types ──────────────────────────────────────────────[/]
[#ff5470]LEAKED_PASSWORD[/]
   The cracked plaintext appears in known breach databases.
   Even a "strong-looking" password is disqualifying if it is leaked.

[#ff8c42]WEAK_CREDENTIAL[/]
   Hash cracked in fewer than 100 dictionary attempts.
   Password is too simple — guessable without specialised tools.

[#6b7785]── auth log reading ─────────────────────────────────────────────[/]
   The free auth log shows login history: timestamp, IP, success/failure.
   Look for: credential-stuffing bursts (many fails, then a success),
   login IPs that don't match the claimed IP in the dossier.
   A claimed-IP mismatch is not disqualifying alone — investigate further
   with Logwatch and Stegotool before deciding.

[#6b7785]── investigation tiers ──────────────────────────────────────────[/]
  Free:   auth log with timestamps, IPs, login outcomes
  Run H:  dictionary + mutation rules attack — reveals plaintext if cracked
  Filter: breach corpus + complexity check — explicit violation named"""

    def _build_logs_text(self) -> str:
        return """[#7dd3c0][b]LOGWATCH — LOG ANALYSIS REFERENCE[/][/]

[#6b7785]── what is log analysis ────────────────────────────────────────[/]
   Every server records a structured event log: each line captures who
   connected, from where, at what time, and what they did. Individually,
   entries are mundane. Analysed in aggregate, they reveal attack patterns
   that no single event could expose.

   Logwatch ingests these raw logs and applies pattern detectors — looking
   for statistical anomalies in timing, geography, and event sequences.
   The free terminal shows you the raw data; spending ⏱ runs the detectors;
   the filter names the violation explicitly so it can be flagged.

[#6b7785]── log entry format ─────────────────────────────────────────────[/]
  TIMESTAMP  IP_ADDRESS  EVENT_TYPE  USERNAME  RESOURCE

  Example:
  2024-03-15 02:14:07  185.220.101.45  AUTH_FAIL  admin  /ssh
  2024-03-15 02:14:09  185.220.101.45  AUTH_FAIL  admin  /ssh
  2024-03-15 02:14:11  185.220.101.45  AUTH_SUCCESS  admin  /ssh

[#6b7785]── event types ──────────────────────────────────────────────────[/]
  AUTH_SUCCESS   Successful login
  AUTH_FAIL      Failed login attempt
  FILE_ACCESS    File read/write/delete
  PRIV_ESCALATE  Privilege escalation (sudo / su / admin claim)
  API_CALL       External API request

[#6b7785]── attack patterns ───────────────────────────────────────────────[/]
[#ff5470]BRUTE_FORCE[/]
   Many AUTH_FAIL events in rapid succession from the same IP.
   Look for: 5+ failures within a 60-second window.
   Often followed by AUTH_SUCCESS once the correct password is found.

[#ff5470]CREDENTIAL_STUFFING[/]
   AUTH_FAIL events across many different usernames from the same IP.
   Attacker is trying a list of stolen credentials systematically.

[#ff8c42]IMPOSSIBLE_TRAVEL[/]
   AUTH_SUCCESS events from two geographically distant IPs within a
   timeframe that makes physical travel impossible.
   e.g. London login at 09:00, Tokyo login at 09:45 — 9,000km in 45min.

[#ff8c42]INSIDER_BEHAVIOR[/]
   FILE_ACCESS or PRIV_ESCALATE events outside business hours (18:00–08:00)
   combined with privilege escalation within a 5-minute window.
   Indicates a legitimate account being misused after-hours.

[#6b7785]── investigation tiers ──────────────────────────────────────────[/]
  Free:   raw log — timestamps, IPs, event types (anomalies unlabelled)
  Run L:  pattern detection — flags bursts, geo regions, after-hours events
  Filter: geo timeline overlay — explicit violation type named and confirmed"""

    def _build_stego_text(self) -> str:
        return """[#7dd3c0][b]STEGOTOOL — STEGANOGRAPHY REFERENCE[/][/]

[#6b7785]── what is LSB steganography ────────────────────────────────────[/]
   LSB (Least Significant Bit) steganography hides data by replacing the
   lowest-order bit of each colour channel value in an image.
   The visual change is imperceptible to the human eye, but statistical
   analysis reveals the disruption to natural pixel noise patterns.

[#6b7785]── suspicion score ───────────────────────────────────────────────[/]
   [#00ff9f]0–30[/]    Likely clean — normal noise distribution
   [#ff8c42]31–60[/]   Investigate further — borderline anomaly
   [#ff5470]61–100[/]  Payload likely present — multiple signals triggered

[#6b7785]── detection signals ─────────────────────────────────────────────[/]
[#ff5470]Chi-square test[/]
   Measures LSB parity distribution across pixel values.
   Natural images have predictable parity; embedded data randomises it.
   p-value < 0.05 flags the channel as suspicious.

[#ff8c42]RS analysis[/]
   Compares "regular" vs "singular" pixel groups before and after bit-flip.
   Embedded data shifts the R/S ratio away from the natural baseline.
   Reliable for detecting medium-to-high embedding density.

[#ff8c42]LSB autocorrelation[/]
   Measures structural similarity between adjacent pixel LSBs.
   Natural images have correlated neighbouring pixels; random payload
   injection breaks this correlation.

[#6b7785]── difficulty channels ──────────────────────────────────────────[/]
  Easy:    Blue channel only — single signal, easiest to detect
  Medium:  Red + Blue channels — two signals, harder to isolate
  Hard:    All RGB channels + encoded payload — highest capacity, best hidden

[#6b7785]── violation types ──────────────────────────────────────────────[/]
[#ff8c42]STEGO_PAYLOAD_PRESENT[/]
   One or more channels show statistically significant anomalies.
   Payload confirmed but encoding method not determined.

[#ff5470]COVERT_C2_CHANNEL[/]
   Multi-channel anomaly with encoded (base64/XOR) payload.
   Indicates active command-and-control communication — high severity.

[#6b7785]── investigation tiers ──────────────────────────────────────────[/]
  Free:   image metadata + per-channel entropy scores + RS ratio
  Run S:  composite suspicion score — chi-square, RS, autocorrelation
  Filter: per-channel LSB breakdown — explicit violation named and confirmed"""

    def action_dismiss_rules(self) -> None:
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


class BriefingScreen(Screen):
    BINDINGS = [
        Binding("space", "begin_day", "Begin shift"),
        Binding("q", "quit_app", "Quit"),
    ]

    def __init__(self, day: Day, narrative: str) -> None:
        super().__init__()
        self._day       = day
        self._narrative = narrative

    def compose(self) -> ComposeResult:
        yield Static(f"[b][#7dd3c0]{self._day.title}[/][/]", classes="screen-title")
        with Container(id="overseer-panel"):
            yield Static("[b]Overseer:[/]", classes="speaker")
            yield Static(self._narrative)
        yield Static(
            "Press [#00ff9f][b]Space[/][/] to begin your shift.",
            classes="hint",
        )

    def action_begin_day(self) -> None:
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
        self._hc_log:  list = []   # shared credential audit log (hashcrack)

        # ── Widgets ───────────────────────────────────────────────────
        self.status   = StatusHeader(state, day, state.current_slot_index)
        self.dossier  = DossierPanel()
        self.chat     = ChatPanel()
        self.board    = EvidenceBoard()
        self.overseer = OverseerPanel(overseer_intro)
        self.ref_main = ReferencePanel("candidate", "reference-side")

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
                with Horizontal(id="candidate-bot"):
                    yield self.overseer
                    yield self.ref_main

            # ── Page 1: Ghostscan ─────────────────────────────────────
            # 3-column layout: sidebar | terminal | breach lists
            with Horizontal(id="page-ghostscan", classes="tool-page"):
                with Vertical(classes="tool-left", id="gs-left"):
                    yield self.cdos_gs
                    yield self.ref_gs
                yield self.term_gs
                yield self.breach_lists

            # ── Page 2: Hashcrack ─────────────────────────────────────
            with Horizontal(id="page-hashcrack", classes="tool-page"):
                with Vertical(classes="tool-left"):
                    yield self.cdos_hc
                    yield self.ref_hc
                yield self.term_hc

            # ── Page 3: Logwatch ──────────────────────────────────────
            with Horizontal(id="page-logwatch", classes="tool-page"):
                with Vertical(classes="tool-left"):
                    yield self.cdos_lw
                    yield self.ref_lw
                yield self.term_lw

            # ── Page 4: Stegotool ─────────────────────────────────────
            with Horizontal(id="page-stegotool", classes="tool-page"):
                with Vertical(classes="tool-left"):
                    yield self.cdos_st
                    yield self.ref_st
                yield self.term_st

        yield self.debug
        yield self.command_bar

        self._footer_widget = Static(self._footer_text(), id="footer")
        yield self._footer_widget

    def on_mount(self) -> None:
        self._day_log = tools_bridge.generate_day_log(self._state.seed, self._day)
        self._hc_log  = tools_bridge.generate_hashcrack_day_log(self._state.seed, self._day)
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
        return (
            "[#00ff9f][b]1-5[/][/] Pages  "
            "[#00ff9f][b]0[/][/] Rules  "
            "[dim]↑↓←→ Focus  Tab→Board  ↑↓ Cursor  Space Flag[/]  "
            "[#00ff9f][b]`[/][/] Dev"
        )

    def _refresh_footer(self) -> None:
        if self._footer_widget:
            self._footer_widget.update(self._footer_text())

    def _goto_page(self, index: int) -> None:
        self._page_index = index
        self.query_one(ContentSwitcher).current = _PAGE_IDS[index]
        self.status.refresh_status(self._state, self._state.current_slot_index,
                                   self._page_index)
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
        self.dossier.set_candidate(c)
        self.chat.set_candidate(c)
        self.debug.set_candidate(c)
        for cd in (self.cdos_gs, self.cdos_hc, self.cdos_lw, self.cdos_st):
            cd.set_candidate(c)

        # The day's rulebook is shown on EVERY page's reference panel so the
        # player can always see what disqualifies a candidate today and then
        # check the tool terminal on the right to decide if it's a violation.
        rules_block = _format_day_rules(self._day.rules)

        # Candidate-page reference: today's rules + global accept/reject guide
        self.ref_main.update_content(_REF_CANDIDATE)

        # Reference panel: target email + claimed IP + today's rules + violation guide
        self.ref_hc.update_content(_REF_HASHCRACK)

        # Clear evidence board and all terminals
        self.board.clear()
        # All tool terminals cleared via set_initial_content
        # Ghostscan: passive identity check (free) + breach list pre-population
        self.term_gs.set_initial_content(tools_bridge.get_ghostscan_identity(c))
        self.ref_gs.update_content(_REF_GHOSTSCAN)
        self.breach_lists.load_candidate(c)
        # Hashcrack terminal: shared credential audit log (free, candidate highlighted)
        self.term_hc.set_initial_content(tools_bridge.get_hashcrack_shared(self._hc_log, c))
        # Logwatch terminal: shared day log (session grouping if upgrade unlocked)
        _gs = config.UPGRADE_SESSION_GROUPING in self._state.upgrades
        self.term_lw.set_initial_content(tools_bridge.get_logwatch_shared(self._day_log, c, group_by_session=_gs))
        # Logwatch reference: target info + today's rules + attack pattern guide
        self.ref_lw.update_content(_REF_LOGWATCH)
        # Stegotool terminal: pre-populate with free image metadata
        self.term_st.set_initial_content(tools_bridge.get_stego_image_info(c))
        # Stegotool reference: target info + signal guide
        self.ref_st.update_content(_REF_STEGOTOOL)

        self.status.refresh_status(self._state, slot, self._page_index)
        self._refresh_footer()

    def _commit_verdict(self, verdict: Verdict) -> None:
        if self._verdict_locked or self._candidate is None:
            return
        self._verdict_locked = True
        compute_before = self._state.compute_hours
        result = scoring.apply(
            self._candidate, verdict, self._state,
            player_flags=self.board.get_flags(),
        )
        compute_after = self._state.compute_hours
        self.overseer.record_result(result, compute_before, compute_after)

        v_str   = "ADMITTED" if verdict == Verdict.ADMIT else "DENIED"
        parts   = [f"{v_str} {self._candidate.display_name}."]
        parts  += ["Correct." if result.correct else "Wrong call."]
        if result.compute_delta:
            parts.append(f"+{result.compute_delta} ⏱")
            if result.board_bonus:
                parts.append(f"(+{result.board_bonus} ⏱ board bonus)")
        if result.lives_delta:
            parts.append(f"{result.lives_delta:+d} ♥")
        if result.alignment_delta:
            arrow = "→ White Hat" if result.alignment_delta > 0 else "→ Dark Web"
            parts.append(f"Align {arrow}")

        self.command_bar.set_response("  ·  ".join(parts), error=not result.correct)
        self.status.refresh_status(self._state, self._state.current_slot_index,
                                   self._page_index)
        self._refresh_footer()

        if self._state.lives <= 0:
            self.app.game_over()

    def _run_tool(self, tool: ToolName, *, filtered: bool = False) -> None:
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
            ToolName.STEGOTOOL: (tools_bridge.run_stegotool,
                                 tools_bridge.run_stegotool_filtered),
        }
        base_fn, filter_fn = runners[tool]
        try:
            result = filter_fn(self._candidate, self._state) if filtered \
                     else base_fn(self._candidate, self._state)
        except tools_bridge.InsufficientCompute as e:
            self.command_bar.set_response(str(e), error=True)
            return

        # Get the right terminal and display the result.
        # Logwatch replaces the terminal content in-place (annotates the shared log).
        # All other tools append below the existing free data.
        term_id = self._TOOL_TERM[tool]
        term = self.query_one(f"#{term_id}", ToolTerminal)
        if tool in (ToolName.LOGWATCH, ToolName.HASHCRACK):
            term.set_initial_content(result.raw_lines)
        else:
            term.add_result(result)

        # Update breach list panel state when ghostscan runs
        if tool == ToolName.GHOSTSCAN:
            if filtered:
                self.breach_lists.confirm_match()
            else:
                self.breach_lists.highlight_match()

        self._spent.add(tool)
        self.status.refresh_status(self._state, self._state.current_slot_index,
                                   self._page_index)
        cost = config.TOOL_COSTS[tool.value]
        if filtered:
            cost += config.FILTER_COSTS[tool.value]
        self.command_bar.set_response(
            f"{'[FILTERED] ' if filtered else ''}"
            f"{tool.value.upper()} complete  −{cost} ⏱  ·  "
            f"flag findings on the Evidence Board (page 1)",
            error=False,
        )

    # ── Action bindings ───────────────────────────────────────────────────

    # ── Page navigation (number keys 1-5) ────────────────────────────────────

    def action_page_1(self) -> None: self._goto_page(0)
    def action_page_2(self) -> None: self._goto_page(1)
    def action_page_3(self) -> None: self._goto_page(2)
    def action_page_4(self) -> None: self._goto_page(3)
    def action_page_5(self) -> None: self._goto_page(4)

    # ── Rules overlay (immediate binding) ────────────────────────────────────

    def action_open_rules(self) -> None:
        self.app.push_screen(RulesScreen(self._day))

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
            self.app.push_screen(RulesScreen(self._day)); event.stop(); return
        if k == "grave_accent":
            self.debug.display = not self.debug.display; event.stop(); return

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
        4: ToolName.STEGOTOOL,
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

        elif kind == "filter":
            tool = self._FILTER_PAGE_MAP.get(self._page_index)
            if tool is None:
                self.command_bar.set_response(
                    "ERROR — navigate to a tool page first (pages 2–5)", error=True
                )
            else:
                self._run_tool(tool, filtered=True)

        elif kind == "verdict":
            self._commit_verdict(arg)   # sets command_bar response internally

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
            self.app.push_screen(RulesScreen(self._day))

        elif kind == "help":
            self.command_bar.set_response(
                "COMMANDS:  recon · crack · analyze · extract · filter · "
                "admit · deny · next · rules · help · quit  "
                "·  pages 1-5  ·  rules 0  ·  arrows = focus panels",
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
                 performance: Performance) -> None:
        super().__init__()
        self._day         = day
        self._state       = state
        self._narrative   = narrative
        self._performance = performance

    def compose(self) -> ComposeResult:
        yield Static(f"[b][#7dd3c0]End of {self._day.title}[/][/]",
                     classes="screen-title")
        with Container(id="eod-summary"):
            correct = sum(1 for r in self._state.pending_results if r.correct)
            total   = len(self._state.pending_results)
            yield Static(f"Verdicts: [b]{correct}[/]/{total} correct")
            yield Static(
                f"Computing hours: [#ffb454][b]{self._state.compute_hours} ⏱[/][/]  "
                f"(target: {self._day.quotas.compute_target} ⏱)"
            )
            yield Static(f"Lives remaining: [#ff5470]{self._state.lives}[/]")
            yield Static(f"Alignment: {self._state.alignment:+d}")
            yield Static("")
            for r in self._state.pending_results:
                tag  = "verdict-correct" if r.correct else "verdict-wrong"
                mark = "✓" if r.correct else "✗"
                bonus_str = f"  board+{r.board_bonus}⏱" if r.board_bonus else ""
                yield Static(
                    f"[{tag}]{mark}[/]  {r.archetype.value:<14}  "
                    f"you {r.player_verdict.value:<5}  "
                    f"[#6b7785]+{r.compute_delta}⏱{bonus_str}  "
                    f"♥{r.lives_delta:+d}  Align {r.alignment_delta:+d}[/]"
                )
        with Container(id="overseer-panel"):
            yield Static("[b]Overseer:[/]", classes="speaker")
            yield Static(self._narrative)
        yield Static(
            f"Performance: [b]{self._performance.value}[/]   ·   "
            "Press [#00ff9f][b]Space[/][/] to save and continue.",
            classes="hint",
        )

    def action_continue_game(self) -> None:
        from gameengine.core import persistence
        persistence.save(self._state)
        self.app.exit()

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
            yield Static("Too many invalid candidates slipped through.", classes="subtitle")
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

    def __init__(self, seed: int = 0xC0FFEE) -> None:
        super().__init__()
        self._seed       = seed
        self._state: GameState | None = None
        self._day:   Day        | None = None
        self._narratives: dict[str, str] = {}

    def on_mount(self) -> None:
        self._narratives = load_narratives()
        self.push_screen(IntroScreen())

    def start_new_game(self) -> None:
        self._state = GameState(
            seed=self._seed,
            current_day=1,
            compute_hours=config.STARTING_COMPUTE,
            alignment=config.STARTING_ALIGNMENT,
            lives=config.STARTING_LIVES,
        )
        self._day = load_day(self._state.current_day)
        narrative = self._narratives[self._day.overseer_intro_key]
        self.pop_screen()
        self.push_screen(BriefingScreen(self._day, narrative))

    def begin_intake(self) -> None:
        assert self._state is not None and self._day is not None
        intro = self._narratives.get(self._day.overseer_intro_key, "")
        self.pop_screen()
        self.push_screen(IntakeScreen(self._day, self._state, intro))

    def finish_day(self) -> None:
        assert self._state is not None and self._day is not None
        performance = self._evaluate_performance()
        outro_key   = self._day.overseer_outro_keys.get(
            performance, self._day.overseer_outro_keys[Performance.PASSING]
        )
        narrative = self._narratives.get(outro_key, "...")
        self.pop_screen()
        self.push_screen(EODScreen(self._day, self._state, narrative, performance))

    def game_over(self) -> None:
        self.pop_screen()
        self.push_screen(GameOverScreen())

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
        if self._state.lives <= 0:
            return Performance.FAILED
        if false_admits > quotas.max_false_admits:
            return Performance.FAILED
        if correct_admits < quotas.min_correct_admits:
            return Performance.POOR
        if self._state.compute_hours < quotas.compute_target:
            return Performance.POOR
        wrong = sum(1 for r in self._state.pending_results if not r.correct)
        if wrong == 0:
            return Performance.EXCELLENT
        return Performance.PASSING


def run(seed: int = 0xC0FFEE) -> None:
    HackDoxApp(seed=seed).run()


if __name__ == "__main__":
    run()
