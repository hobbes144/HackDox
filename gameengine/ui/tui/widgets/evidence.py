"""EvidenceState, EvidenceBoard."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.events import Key
from textual.widgets import Static

from gameengine.core import scoring
from gameengine.core.models import DiscrepancyKind
from gameengine.ui.tui import rules_content
from gameengine.ui.tui.shared import (
    _GROUP_META,
    _GROUP_ORDER,
    _sev_color,
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

    ── Post-verdict grading ──────────────────────────────────────────────
    After a verdict, `reveal()` grades the record against ground truth and the
    boards repaint with a ✓/✗ beside every call the player actually made.
    What it deliberately does NOT do is fill in the answer key: a violation the
    player never touched stays blank, so the board can be read as "how did I
    do" without ever becoming "here is what was there". The one concession is
    `unrecorded_count` — a bare number of real violations left untouched, which
    tells the player they missed something without telling them what.

    Grading is scoped to a `visible` set supplied by the caller: violations
    from tools the player has not unlocked yet are excluded from both the
    grade and the count, because a player cannot miss what the game has not
    shown them (see IntakeScreen._begin_verdict_reveal).
    """

    STATES = ("unknown", "marked", "absent")

    def __init__(self) -> None:
        # kind → "marked" | "absent"; unknown kinds are simply absent from dict.
        self._states: dict[DiscrepancyKind, str] = {}
        # Grading state — populated by reveal(), wiped by clear()/clear_reveal().
        self._revealed = False
        self._actual: set[DiscrepancyKind] = set()
        self._correct_marks: set[DiscrepancyKind] = set()
        self._unrecorded = 0

    def clear(self) -> None:
        self._states.clear()
        self.clear_reveal()

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

    # ── Post-verdict grading ──────────────────────────────────────────

    def reveal(self, actual: set[DiscrepancyKind],
               visible: set[DiscrepancyKind]) -> None:
        """Grade this record against ground truth.

        `actual` is the candidate's real discrepancy kinds; `visible` is the
        catalog the player can currently see (unlocked tools only). Both are
        intersected, so a locked-tool violation can neither be graded against
        nor counted as unrecorded.

        Flags are run through `scoring.credited_flags` first — the same
        transform the HD$ board bonus uses — so a tick on screen and a coin in
        the pocket always agree.
        """
        self._actual = set(actual) & set(visible)
        marks = self.get_flags()
        credited = scoring.credited_flags(marks, self._actual)
        # A mark is a true positive if the violation is really there, OR if the
        # credit rule swapped it out for one that is: `marks - credited` is
        # exactly the set of flags that got substituted, and by the rule's own
        # precondition each substitution lands on a violation in `actual`.
        self._correct_marks = (marks & self._actual) | (marks - credited)
        # "Unrecorded" means the player left it at unknown — never touched it.
        # A violation they explicitly ruled out is already on screen wearing a
        # ✗, so counting it here would report the same mistake twice.
        self._unrecorded = len(self._actual - set(self._states))
        self._revealed = True

    def clear_reveal(self) -> None:
        """Drop grading and go back to an ungraded board."""
        self._revealed = False
        self._actual = set()
        self._correct_marks = set()
        self._unrecorded = 0

    @property
    def revealed(self) -> bool:
        return self._revealed

    @property
    def unrecorded_count(self) -> int:
        """Real violations the player never touched. 0 before reveal()."""
        return self._unrecorded

    def grade_of(self, kind: DiscrepancyKind) -> str | None:
        """"correct" | "wrong" for a call the player made; None otherwise.

        None covers both "not graded yet" and "player left this unknown" — in
        either case the board draws nothing, which is what keeps the answer key
        off the screen.
        """
        if not self._revealed:
            return None
        state = self._states.get(kind)
        if state is None:
            return None
        if state == "marked":
            return "correct" if kind in self._correct_marks else "wrong"
        # "absent" — the player ruled it out, so they are right iff it is absent.
        return "wrong" if kind in self._actual else "correct"


# ─── Post-verdict grade rendering ────────────────────────────────────────────
#
# Shared by both board views so a call reads the same on the Candidate page and
# on a tool page. Kept module-level (not methods) because they are pure
# formatting of an already-computed grade — no widget state involved.

GRADE_CORRECT_COLOR = "#00ff9f"
GRADE_WRONG_COLOR   = "#ff5470"


def _grade_badge(grade: str | None) -> str:
    """Trailing ✓/✗ for one row. Empty string when the row isn't graded."""
    if grade == "correct":
        return f"  [{GRADE_CORRECT_COLOR}][b]✓[/][/]"
    if grade == "wrong":
        return f"  [{GRADE_WRONG_COLOR}][b]✗[/][/]"
    return ""


def _grade_footer(state: EvidenceState) -> list[str]:
    """The summary line under a graded board.

    Reports a bare COUNT of violations the player never touched — deliberately
    not their names, their groups, or their severities. Knowing "there were two
    more" is feedback; knowing which two is the answer key, and the player is
    meant to carry that uncertainty into the next shift.
    """
    n = state.unrecorded_count
    if n == 0:
        return [f"  [{GRADE_CORRECT_COLOR}]Nothing went unrecorded.[/]"]
    plural = "violation" if n == 1 else "violations"
    return [f"  [{GRADE_WRONG_COLOR}][b]{n}[/] {plural} went unrecorded.[/]"]


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

    def __init__(self, state: EvidenceState, widget_id: str = "evidence-board",
                 classes: str | None = None, summary: bool = False,
                 home_group: str | None = None,
                 unlocked_tools: set[str] | None = None) -> None:
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
            except Exception:  # noqa: BLE001, S110 -- scrolling before the widget is fully
                # mounted/sized is a no-op, not a failure worth surfacing.
                pass

    def reset_cursor(self) -> None:
        """Reset this view's cursor and repaint (flags are cleared on the
        shared state separately, then all views are repainted)."""
        self._cursor = 0
        self.repaint()
        try:
            self.scroll_home(animate=False)
        except Exception:  # noqa: BLE001, S110 -- same as above: pre-mount scroll is a no-op.
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
            # Post-verdict grade badge (reveal window). Empty until reveal(),
            # and empty forever on rows the player left at "unknown" — a blank
            # row is how the answer key stays off the board.
            badge     = _grade_badge(self._state.grade_of(kind))

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
                lines.append(f"{gutter}{INDENT}[reverse] {label} [/]{badge}")
            elif state == "marked":
                lines.append(f"{gutter}{INDENT}[{sev}][b]{label}[/][/]{badge}")
            elif state == "absent":
                lines.append(f"{gutter}{INDENT}[#6b7785][strike]{label}[/][/]{badge}")
            else:
                lines.append(f"{gutter}{INDENT}[{sev}]{label}[/]")

        if self._state.revealed:
            lines.append("")
            lines.extend(_grade_footer(self._state))
        elif not self._focused:
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
            if self._state.revealed:
                # Nothing to tick, but the count still lands — a player who
                # flagged nothing on a dirty candidate should feel that.
                lines.extend(_grade_footer(self._state))
            else:
                lines.append("[dim]Open a tool page and press [b]Tab[/] to record evidence.[/]")
            return "\n".join(lines)

        current_group = ""
        for group, kind, label in recorded:
            if group != current_group:
                gcolor, _hk = _GROUP_META.get(group, ("#7dd3c0", ""))
                lines.append(f"[{gcolor}][b]▎ {group}[/][/]")
                current_group = group
            badge = _grade_badge(self._state.grade_of(kind))
            if self._state.state_of(kind) == "marked":
                sev = _sev_color(kind)
                lines.append(f"    [{sev}][b]▲ {label}[/][/]{badge}")
            else:  # absent — ruled out
                lines.append(f"    [#6b7785]✗ [strike]{label}[/][/]{badge}")
        n_m = len(marked)
        n_a = len(recorded) - n_m
        lines.append("")
        lines.append(f"[dim]{n_m} marked · {n_a} ruled out[/]")
        if self._state.revealed:
            lines.extend(_grade_footer(self._state))
        return "\n".join(lines)
