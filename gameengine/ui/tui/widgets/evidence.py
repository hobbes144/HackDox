"""EvidenceState, EvidenceBoard."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.events import Key
from textual.widgets import Static
from gameengine.core.models import Candidate, DiscrepancyKind
from gameengine.ui.tui import rules_content

from gameengine.ui.tui.shared import (
    _sev_color,
    _GROUP_ORDER,
    _GROUP_META,
)


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
                 home_group: str | None = None,
                 unlocked_tools: "set[str] | None" = None) -> None:
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
        # Progressive unlock: this view's own slice of the catalog, filtered
        # to violations whose revealing tool the player currently has. The
        # instance is rebuilt fresh every day (IntakeScreen is recreated per
        # day), so baking the filter in at construction is enough — it never
        # needs to grow mid-shift.
        self._items = rules_content.visible_catalog(unlocked_tools)
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
            for idx, (group, _k, _l) in enumerate(self._items):
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
            self._cursor = min(len(self._items) - 1, self._cursor + 1)
            event.stop()
            self.repaint()
        elif event.key == "space":
            kind = self._items[self._cursor][1]
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
        for idx, (group, kind, label) in enumerate(self._items):
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
        recorded = [(g, k, l) for g, k, l in self._items
                    if self._state.state_of(k) != "unknown"]
        marked_groups = {g for g, k, _l in self._items if k in marked}

        # Category strip — groups currently visible to this player across the
        # top (a locked group can never have a marked violation, so it has no
        # place in the strip); those with a marked (present) violation are lit.
        visible_groups = {g for g, _k, _l in self._items}
        chips: list[str] = []
        for g in _GROUP_ORDER:
            if g not in visible_groups:
                continue
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
