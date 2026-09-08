"""EvidenceState, EvidenceBoard."""

from __future__ import annotations

from rich.text import Text
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

    Each violation has one of three states, cycled with Space (or a click):
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
    """Trailing ✓/✗ for one summary row. Empty when the row isn't graded."""
    if grade == "correct":
        return f"  [{GRADE_CORRECT_COLOR}][b]✓[/][/]"
    if grade == "wrong":
        return f"  [{GRADE_WRONG_COLOR}][b]✗[/][/]"
    return ""


def _grade_cell(grade: str | None) -> str:
    """Exactly ONE cell of grade badge, for the chip grid.

    The chip layout is cell-addressed — `on_click` maps a mouse column back to
    a chip by arithmetic — so every decoration has to have a width the layout
    code knows about. Same glyphs and colours as `_grade_badge`; the only
    differences are the fixed width and the missing leading pad.

    It is painted OUTSIDE the chip's background fill on purpose: a marked chip
    is filled with its severity colour, and a green ✓ on a yellow fill is the
    one place on this board where the colour language would stop being
    readable.
    """
    if grade == "correct":
        return f"[{GRADE_CORRECT_COLOR}][b]✓[/][/]"
    if grade == "wrong":
        return f"[{GRADE_WRONG_COLOR}][b]✗[/][/]"
    return " "


def _grade_footer(state: EvidenceState, width: int = 80) -> list[str]:
    """The summary line under a graded board.

    Reports a bare COUNT of violations the player never touched — deliberately
    not their names, their groups, or their severities. Knowing "there were two
    more" is feedback; knowing which two is the answer key, and the player is
    meant to carry that uncertainty into the next shift.

    `width` picks the long or short wording. This board is mounted as narrow as
    ~28 usable cells (#evidence-st on a 100-column terminal) and the long form
    is 31, so the sentence has to be allowed to shrink — a clipped verdict
    ("2 violations went unrecord") is worse than a terse one.
    """
    n = state.unrecorded_count
    if n == 0:
        long_form = "Nothing went unrecorded."
        text = long_form if len(long_form) + 2 <= width else "All recorded."
        return [f"  [{GRADE_CORRECT_COLOR}]{text}[/]"]
    plural = "violation" if n == 1 else "violations"
    long_form = f"{n} {plural} went unrecorded."
    if len(long_form) + 2 <= width:
        return [f"  [{GRADE_WRONG_COLOR}][b]{n}[/] {plural} went unrecorded.[/]"]
    return [f"  [{GRADE_WRONG_COLOR}][b]{n}[/] unrecorded[/]"]


# ─── Chip grid geometry ──────────────────────────────────────────────────────
#
# The editable board draws each violation as a clickable chip and packs chips
# into rows. Every constant here is in terminal CELLS, and the renderer and the
# hit-test share them — `on_click` does not re-measure the rendered text, it
# recomputes the same arithmetic — so a chip's clickable area and its painted
# area cannot drift apart.
#
# ── Why arithmetic and not one widget per violation ──
# The obvious implementation is 27 Textual `Button`s. It does not survive the
# layout this board actually lives in: the same widget is mounted at five
# different widths (#evidence-gs 34%, #evidence-hc/lw 36%, #evidence-st 32%,
# #evidence-c0 50%, and .rules-evidence at 100% inside the docs overlay), each
# of which is a percentage of a terminal the player can resize at will. A
# Button carries its own border and padding and cannot be told to be one cell
# tall; 27 of them is 80+ rows in a panel that is often 12. Chips inside the
# one Static keep the board at a row per chip, keep the existing scroll, cursor
# and grading code intact, and let the column count fall out of the measured
# width instead of being guessed at authoring time.

_CHIP_GAP      = 2    # blank cells between two chips on the same row
_CHIP_MAX_COLS = 4    # a cluster bigger than this always stacks
_BOARD_INDENT  = 2    # left margin, matches the group headers' own indent
# cap(1) + marker(1) + space(1) + [label] + space(1) + cap(1) + grade(1).
# See the chip-anatomy diagram below.
#
# Every cell here is a cell the longest label does not get, and the longest is
# 28 ("Unsalted / plaintext storage"). A cursor column of its own was tried and
# reverted for exactly that reason: at a 50%-wide Candidate board on an 80-
# column terminal it pushed that one label into an ellipsis. Lighting the caps
# costs nothing and reads at least as well.
_CHIP_CHROME   = 6
_CHIP_MIN_W    = _CHIP_CHROME + 6   # below this a chip is unreadable anyway

# Width used when the widget has not been laid out yet — a direct _render_text()
# call in a test, or the first repaint from on_mount() before Textual has
# assigned a size. Deliberately narrow: one column is always a valid layout, so
# a too-small guess degrades to the single-column list this board has always
# been, while a too-large guess would overflow the panel on the first frame.
_FALLBACK_WIDTH = 46

# ── Chip anatomy ────────────────────────────────────────────────────────────
#
#   ▐○ Breach hit            ▌✓
#   ││└─ state marker + label on the fill      grade ─┘
#   │└─── left cap, painted in the SEVERITY colour
#   └──── (both caps turn accent green when the cursor is here)
#
# Two independent readings, deliberately not fighting each other:
#
#   the CAPS say what KIND of violation this is — severity, the board's colour
#   language since long before this layout (yellow minor, orange major, red
#   critical);
#   the FILL says what the PLAYER has decided about it — recessed and struck
#   (ruled out), raised (undecided), or lit in the severity colour (marked).
#
# The caps are half-block glyphs painted as fill-colour-on-panel-background,
# which is the terminal trick for a rounded edge: the cell is half chip and
# half panel, so the chip reads as a pill rather than a hard rectangle. That is
# why `PANEL_BG` has to match the board's `background` in app.tcss — if the two
# drift the caps grow a visible notch. All four board selectors use #0d1117.
PANEL_BG         = "#0d1117"
CHIP_IDLE_BG     = "#1a222c"   # raised: undecided
CHIP_ABSENT_BG   = "#12171d"   # recessed: ruled out
CHIP_ABSENT_FG   = "#59646f"
CHIP_MARKED_FG   = "#0b0e10"   # near-black ink on a lit severity fill
CHIP_CURSOR      = "#00ff9f"   # same accent as the focused-panel border

_CAP_LEFT     = "▐"
_CAP_RIGHT    = "▌"
_MARK_UNKNOWN = "○"
_MARK_MARKED  = "▲"
_MARK_ABSENT  = "✗"

# Every glyph the grid draws must be exactly one cell wide, because `on_click`
# maps a mouse column back to a chip by arithmetic over these widths rather
# than by measuring the painted text. A double-width glyph would shift every
# chip to its right and the board would toggle the wrong violation, with
# nothing on screen looking wrong. A test asserts this set.
CHIP_GLYPHS = (_CAP_LEFT, _CAP_RIGHT,
               _MARK_UNKNOWN, _MARK_MARKED, _MARK_ABSENT, "✓", "✗")


def chip_row(avail: int, count: int, longest_label: int) -> tuple[int, int]:
    """(chips per row, cell width) for ONE cluster of `count` chips.

    The unit of layout is the cluster, not the board. A cluster is drawn either
    as one whole row or as a full-width stack — never wrapped. That rule is the
    whole point: the clusters are authored as rows (three OSINT rows of three,
    two Logwatch rows of two, and so on), and a generic grid packer turns a row
    of three into "two, then a lonely one" the moment the panel is a little too
    narrow. Ragged is worse than stacked, because it looks like a grouping the
    player is supposed to read something into.

    So `count` chips fit on one row only if `count` NATURAL chips fit; the
    leftover cells are then handed back so the row reaches the panel edge.
    Otherwise the cluster falls back to one full-width chip per line, which is
    also what every tool sidebar shows — those are ~34% of the terminal and
    never have room for a real row.

    `longest_label` is this cluster's own longest, not the board's. Chip widths
    therefore differ a little between clusters, which is fine (clusters are
    separated blocks, not columns of one table) and lets a cluster of short
    labels form its row at a width where the widest cluster still cannot.
    Either way `cell_width >= longest_label + _CHIP_CHROME` whenever a single
    natural chip fits at all, so labels are never truncated.
    """
    natural = max(longest_label, 1) + _CHIP_CHROME
    per_row = count
    if (count > _CHIP_MAX_COLS
            or count * natural + _CHIP_GAP * (count - 1) > avail):
        per_row = 1
    cell = (avail - _CHIP_GAP * (per_row - 1)) // per_row
    return per_row, max(_CHIP_MIN_W, cell)


def _fit(label: str, width: int) -> str:
    """Label padded — or, only on a terminal too narrow for one chip, cut."""
    if len(label) > width:
        return label[:max(0, width - 1)] + "…"
    return label.ljust(width)


def _clip(label: str, width: int) -> str:
    """Trim a label to `width` cells with an ellipsis. Never pads."""
    if width <= 0:
        return ""
    if len(label) > width:
        return label[:max(0, width - 1)] + "…"
    return label


def _wrap_markup(parts: list[str], width: int, sep: str = "  ",
                 indent: str = "") -> list[str]:
    """Greedily pack markup fragments into lines no wider than `width` cells.

    Measured with `Text.cell_len`, so the colour tags and the `[dim on …]`
    hotkey chips do not count toward the width the way `len()` would.

    Both places this is used — the keyboard hint under the chip grid and the
    summary board's category strip — are decoration that used to be built as
    one long f-string. That is fine at the 100%-wide docs-overlay board and
    silently clipped at the 32%-wide Stegotool sidebar, which is the failure
    mode this whole widget is trying not to have: `overflow-x` is hidden on a
    VerticalScroll, so an over-long line loses its tail with no scrollbar to
    tell the player anything is missing.
    """
    # Both the separator and the indent are markup too, so both are measured
    # in cells rather than characters — `" [dim]·[/] "` is eleven characters
    # and three cells, and using len() here would wrap far too early.
    sep_w = Text.from_markup(sep).cell_len
    width = max(1, width - Text.from_markup(indent).cell_len)
    lines: list[str] = []
    cur: list[str] = []
    cur_w = 0
    for part in parts:
        w = Text.from_markup(part).cell_len
        add = w if not cur else w + sep_w
        if cur and cur_w + add > width:
            lines.append(indent + sep.join(cur))
            cur, cur_w = [part], w
        else:
            cur.append(part)
            cur_w += add
    if cur:
        lines.append(indent + sep.join(cur))
    return lines


# Kept as short fragments rather than one sentence so `_wrap_markup` has
# somewhere to break: the narrowest board this widget is mounted in is about
# 30 cells of usable width.
_HINT_PARTS = [
    "[dim]click a chip[/]",
    "[dim]Tab focus[/]",
    "[dim]↑↓ move[/]",
    "[dim]Space cycles[/]",
]


class EvidenceBoard(VerticalScroll):
    """Player-controlled evidence checklist (a *view* over EvidenceState).

    Violations are drawn as clickable chips, packed into rows and split into
    unnamed clusters inside each tool group (see
    `rules_content.VIOLATION_CLUSTERS`). A scrollable container, so every chip
    stays reachable regardless of terminal height.

    Nothing is ever written here automatically. The player moves the cursor
    with ↑↓ and cycles a chip with Space, or clicks a chip directly. ← / → are
    NOT consumed here — they bubble up to the screen for focus navigation, and
    that is exactly why ↑↓ walk the chips in READING order rather than by grid
    row: with no horizontal key there would be no way back into a column the
    cursor had left, so a row-wise cursor would strand chips on a multi-column
    board. The grid is a spatial layout for the eye and the mouse; the keyboard
    still sees the same ordered list it always has.

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
            self.border_title = " EVIDENCE BOARD  [dim](↑↓ · Space · click)[/] "
        self._state = state
        # Progressive unlock: this view's own slice of the catalog, filtered
        # to violations whose revealing tool the player currently has. The
        # instance is rebuilt fresh every day (IntakeScreen is recreated per
        # day), so baking the filter in at construction is enough — it never
        # needs to grow mid-shift.
        #
        # `_clusters` is the layout; `_items` is that same list flattened, and
        # is what `_cursor` indexes. Deriving one from the other rather than
        # filtering the catalog twice is what keeps the cursor, the hit map and
        # the painted chips addressing the same violation.
        self._clusters = rules_content.clustered_catalog(unlocked_tools)
        self._items: list[tuple[str, DiscrepancyKind, str]] = [
            item for _g, _cid, items in self._clusters for item in items
        ]
        self._cursor: int = 0
        self._focused: bool = False
        self._cursor_line: int = 0
        # Hit map, rebuilt on every render: line index → [(x_start, x_end,
        # item index)]. Cells between chips are deliberately absent from it, so
        # a click landing in a gutter does nothing rather than toggling
        # whichever chip happens to be nearest.
        self._hit: dict[int, list[tuple[int, int, int]]] = {}
        self._last_width: int = -1
        self._content = Static(id=f"{widget_id}-content", classes="evidence-content")

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

    def on_resize(self, event) -> None:
        """Re-pack the chip grid when the panel's usable width changes.

        `event` is unused — the width is re-measured rather than read off it,
        because the scrollbar gutter is what actually decides how much room the
        chips get and that is not in the resize payload.

        Guarded on the measured width rather than firing on every resize: a
        repaint can add or remove the vertical scrollbar, which changes the
        content width, which fires another resize. Comparing against the width
        the last render actually used breaks that loop after one bounce instead
        of letting the board oscillate between two column counts. (The
        stylesheet also reserves the scrollbar gutter, which removes the cause;
        this is the belt to that pair of braces.)

        The summary view needs this too, not just the chip grid — its category
        strip wraps and its rule is drawn to the panel width.
        """
        if self._content_width() != self._last_width:
            self.repaint()

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

    # ── Toggling ──────────────────────────────────────────────────────

    def _toggle(self, index: int) -> None:
        """Cycle one violation and resync every other board view.

        The single mutation path for both Space and the mouse — a click is a
        cursor move plus this, never a second copy of the cycle logic, so the
        two input routes cannot drift the way a parallel implementation would.
        """
        if not (0 <= index < len(self._items)):
            return
        self._state.cycle(self._items[index][1])
        self.repaint()   # immediate repaint for this board
        # Repaint other board views so shared state stays in sync.
        for board in self.app.query(EvidenceBoard):
            if board is not self:
                board.repaint()

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
            # Cycle: unknown → marked → absent → unknown.
            self._toggle(self._cursor)
            event.stop()
        # ← / → are NOT stopped — they bubble to IntakeScreen for focus nav.

    # ── Mouse handling ────────────────────────────────────────────────

    def _mouse_to_cell(self, event) -> tuple[int, int] | None:
        """Mouse position → (column, line) inside the rendered content.

        Measured against the inner Static's own screen region rather than this
        container's gutter. The Static is what scrolls, so its region already
        carries the scroll offset, and that region is reported in SCREEN
        coordinates — the one frame of reference a Click keeps no matter which
        widget in the chain ends up handling it. Deriving the offset from
        `event.x` instead would silently depend on whether the press landed on
        the Static or on the container's own border and padding.
        """
        try:
            region = self._content.region
        except Exception:  # noqa: BLE001 -- not mounted / not yet laid out
            return None
        x = event.screen_x - region.x
        y = event.screen_y - region.y
        if x < 0 or y < 0:
            return None
        return x, y

    def hit_test(self, x: int, y: int) -> int | None:
        """Item index at content cell (x, y), or None for a gap or a header.

        Public because it is the seam the click tests drive: they can assert
        the map the last render built without reproducing Textual's mouse
        dispatch, which is the part most likely to change under us.
        """
        for start, end, index in self._hit.get(y, ()):
            if start <= x < end:
                return index
        return None

    def on_click(self, event) -> None:
        if self._summary or getattr(event, "button", 1) != 1:
            return
        cell = self._mouse_to_cell(event)
        if cell is None:
            return
        index = self.hit_test(*cell)
        if index is None:
            return
        # A click is also a cursor move, so ↑↓ and Space carry on from wherever
        # the player last pointed instead of from a stale row.
        self._cursor = index
        if not self.has_focus:
            self.focus()
        self._toggle(index)
        event.stop()

    # ── Rendering ─────────────────────────────────────────────────────

    def _content_width(self) -> int:
        """Usable cell width for chips, or the fallback when unmounted."""
        try:
            width = self.content_size.width
        except Exception:  # noqa: BLE001 -- size is unavailable before layout
            width = 0
        return width if width > 0 else _FALLBACK_WIDTH

    def _group_header(self, group: str, width: int) -> str:
        """Section band: accent bar, group name, tool hotkey, then a rule out
        to the panel edge.

        The rule is what makes a group read as a band rather than as one more
        line of text — with clusters separated by nothing but whitespace, the
        header is the only thing left carrying the hierarchy, so it has to be
        unmistakably heavier than the gaps below it. Its length is measured,
        not guessed, so it stops at the panel edge on every board width.
        """
        gcolor, hotkey = _GROUP_META.get(group, ("#7dd3c0", ""))
        hint = f"  [dim on #10161d] {hotkey} [/]" if hotkey else ""
        head = f"  [{gcolor}][b]▎ {group}[/][/]{hint}"
        rule = max(0, width - Text.from_markup(head).cell_len - 2)
        return f"{head}  [#1c2733]{'─' * rule}[/]" if rule else head

    def _chip_markup(self, index: int, label: str, label_w: int) -> str:
        """One chip, exactly `label_w + _CHIP_CHROME` cells wide.

        Cell for cell, left to right: cursor pointer, left cap, marker, space,
        label, space, right cap, grade. Nothing here may change width — see the
        anatomy note by CHIP_GLYPHS.
        """
        kind      = self._items[index][1]
        state     = self._state.state_of(kind)
        sev       = _sev_color(kind)
        at_cursor = index == self._cursor and self._focused
        grade     = _grade_cell(self._state.grade_of(kind))
        text      = _fit(label, label_w)
        bold      = "b " if at_cursor else ""

        if state == "marked":
            # Lit: the severity colour becomes the surface, so the chip is
            # legible as "flagged" from across the panel without reading it.
            fill, cap = sev, sev
            body = f"[b {CHIP_MARKED_FG} on {sev}]{_MARK_MARKED} {text} [/]"
        elif state == "absent":
            # Ruled out. The cap drops its severity too — a violation the
            # player has dismissed should go quiet, not keep shouting its tier.
            fill, cap = CHIP_ABSENT_BG, CHIP_ABSENT_FG
            body = (f"[{CHIP_ABSENT_FG} on {CHIP_ABSENT_BG}]{_MARK_ABSENT} "
                    f"[strike]{text}[/] [/]")
        else:
            fill, cap = CHIP_IDLE_BG, sev
            body = (f"[{sev} on {CHIP_IDLE_BG}]{_MARK_UNKNOWN} "
                    f"[{bold}{sev}]{text}[/] [/]")

        # The cursor lights both caps rather than claiming a column of its own.
        # It borrows the severity cap for one chip — the one the player is
        # looking at, whose marker and fill still say everything about its
        # state — and that is cheaper than spending a cell of every label.
        if at_cursor:
            cap = fill_cap = CHIP_CURSOR
        else:
            fill_cap = fill
        cap_l = f"[{cap} on {PANEL_BG}]{_CAP_LEFT}[/]"
        cap_r = f"[{fill_cap} on {PANEL_BG}]{_CAP_RIGHT}[/]"
        return f"{cap_l}{body}{cap_r}{grade}"

    def _render_text(self) -> str:
        if self._summary:
            return self._render_summary()

        width = self._content_width()
        self._last_width = width
        avail = max(_CHIP_MIN_W, width - _BOARD_INDENT)

        lines: list[str] = []
        hit: dict[int, list[tuple[int, int, int]]] = {}
        index = 0
        current_group = ""

        for group, _cluster_id, items in self._clusters:
            if group != current_group:
                if current_group:
                    lines.append("")          # breathing room before a header
                lines.append(self._group_header(group, width))
                current_group = group
            else:
                # Cluster divider. Whitespace only, by design: these groupings
                # are unnamed mnemonics, and a rule or a caption would promote
                # them into a second header level competing with the real one.
                lines.append("")

            # Sized per cluster: its own longest label, its own row/stack call.
            longest = max((len(lbl) for _g, _k, lbl in items), default=1)
            per_row, cell_w = chip_row(avail, len(items), longest)
            label_w = max(1, cell_w - _CHIP_CHROME)

            for row_start in range(0, len(items), per_row):
                row = items[row_start:row_start + per_row]
                chips: list[str] = []
                spans: list[tuple[int, int, int]] = []
                x = _BOARD_INDENT
                for offset, (_g, _kind, label) in enumerate(row):
                    item_index = index + row_start + offset
                    chips.append(self._chip_markup(item_index, label, label_w))
                    spans.append((x, x + cell_w, item_index))
                    if item_index == self._cursor and self._focused:
                        self._cursor_line = len(lines)
                    x += cell_w + _CHIP_GAP
                hit[len(lines)] = spans
                lines.append(" " * _BOARD_INDENT
                             + (" " * _CHIP_GAP).join(chips))
            index += len(items)

        self._hit = hit

        if self._state.revealed:
            lines.append("")
            lines.extend(_grade_footer(self._state, width))
        elif not self._focused:
            lines.append("")
            lines.extend(_wrap_markup(_HINT_PARTS, width,
                                      sep=" [dim]·[/] ",
                                      indent=" " * _BOARD_INDENT))
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
        # Both the strip and its underline are sized to the panel. Five lit
        # group chips are ~60 cells and this board is half of the Candidate
        # page's mid row, so on anything under a ~130-column terminal the old
        # single-line strip (and its hardcoded 46-cell rule) ran off the right
        # edge into the clip.
        width = self._content_width()
        self._last_width = width
        lines: list[str] = [*_wrap_markup(chips, width),
                            "[#1c2733]" + "─" * max(10, width) + "[/]", ""]

        if not recorded:
            lines.append(_clip("No evidence recorded for this candidate.",
                               width))
            lines[-1] = f"[dim]{lines[-1]}[/]"
            lines.append("")
            if self._state.revealed:
                # Nothing to tick, but the count still lands — a player who
                # flagged nothing on a dirty candidate should feel that.
                lines.extend(_grade_footer(self._state, width))
            else:
                lines.extend(_wrap_markup(
                    ["[dim]Open a tool page[/]", "[dim]press [b]Tab[/][/]",
                     "[dim]to record evidence.[/]"], width, sep=" "))
            return "\n".join(lines)

        # 4 cells of indent + marker + space, and 3 more for a graded row's
        # "  ✓" — reserved unconditionally so a row does not change width the
        # moment the verdict lands.
        label_room = max(4, width - 9)
        current_group = ""
        for group, kind, label in recorded:
            if group != current_group:
                gcolor, _hk = _GROUP_META.get(group, ("#7dd3c0", ""))
                lines.append(f"[{gcolor}][b]▎ {_clip(group, width - 2)}[/][/]")
                current_group = group
            badge = _grade_badge(self._state.grade_of(kind))
            text  = _clip(label, label_room)
            if self._state.state_of(kind) == "marked":
                sev = _sev_color(kind)
                lines.append(f"    [{sev}][b]▲ {text}[/][/]{badge}")
            else:  # absent — ruled out
                lines.append(f"    [#6b7785]✗ [strike]{text}[/][/]{badge}")
        n_m = len(marked)
        n_a = len(recorded) - n_m
        lines.append("")
        lines.append(f"[dim]{n_m} marked · {n_a} ruled out[/]")
        if self._state.revealed:
            lines.extend(_grade_footer(self._state, width))
        return "\n".join(lines)
