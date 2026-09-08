"""Tests for the Evidence Board's labelled button grid.

The board is a grid of clickable buttons: one named category per row, its
violations side by side, columns lined up across every category. Four things
about that are worth guarding, and they are the four sections below.

  * **The map is content.** `VIOLATION_CLUSTERS` is a second hand-written index
    of the same catalog `VIOLATION_CATALOG` already indexes, and a kind missing
    from it does not error at render time — it simply never appears on the board
    again, on any page, for the rest of the campaign. The module raises at
    import for the structural failures; these tests cover what a bad edit could
    still slip past, chiefly "the two orderings disagree about MEMBERSHIP".

  * **A category is always ONE horizontal row.** That is the organising idea, so
    it is asserted as a property across every width rather than eyeballed at
    one. The previous layout broke a too-wide row into a vertical stack, which
    destroyed the grouping the row exists to show; names that do not fit side by
    side now wrap downward inside their own button instead.

  * **The hit map has to agree with the paint.** `on_click` does not measure the
    rendered text; it recomputes the same arithmetic the renderer used. That is
    exactly the shape of bug that stays invisible: the buttons look right, and
    clicking one toggles its neighbour. So the click tests never assert against
    the map alone — they slice the PAINTED lines at the coordinates the map
    claims. (Same lesson as Batch 4's tool guards: a conclusion computed from
    the same source as the assertion proves nothing; only the body is evidence.)

  * **Mouse first.** Playtesters found walking the old flat list with the arrow
    keys irritating, so clicking is the intended way in and has to keep working
    while the board scrolls. The arrows still move, but across the grid.
"""

from __future__ import annotations

import asyncio
from itertools import pairwise

from rich.text import Text
from textual.app import App, ComposeResult

from gameengine import config
from gameengine.core.content_loader import load_day
from gameengine.core.models import DiscrepancyKind, GameState
from gameengine.ui.tui import rules_content
from gameengine.ui.tui.app import IntakeScreen
from gameengine.ui.tui.widgets import EvidenceBoard, EvidenceState
from gameengine.ui.tui.widgets.evidence import (
    _BOARD_INDENT,
    _CAP_LEFT,
    _CHIP_CHROME,
    _CHIP_GAP,
    _CHIP_MAX_W,
    _CHIP_MIN_W,
    _EDGE_BOT,
    _EDGE_TOP,
    CHIP_GLYPHS,
    grid_cell,
    grid_columns,
    wrap_label,
)

# Nick's authored layout, exactly as he specified it: (category name, buttons
# left to right). Each entry is ONE row on screen.
AUTHORED_MAP: list[tuple[str, list[tuple[str, list[str]]]]] = [
    ("DOSSIER", [
        ("Identity Confirmation",
         ["Affiliation not stated", "Disposable email domain"]),
        ("Password Security",
         ["Weak password encryption", "Unsalted / plaintext storage"]),
        ("Personal",
         ["Hostile chat"]),
    ]),
    ("OSINT", [
        ("Association Confirmation",
         ["Missing public profile", "Affiliation unlisted",
          "Affiliation mismatch"]),
        ("False Identity",
         ["Typosquatted handle", "Sock puppet accounts", "Burner identity"]),
        ("Unsafe Account",
         ["Breach hit", "Email / GitHub mismatch",
          "Threat-forum handle match"]),
    ]),
    ("CREDENTIAL", [
        ("Credential Exposure",
         ["Weak credential", "Cross-breach password reuse",
          "Leaked password"]),
    ]),
    ("FORENSICS", [
        ("Access Timing",
         ["After-hours access", "Impossible travel"]),
        ("Source Verification",
         ["Claimed-IP mismatch", "Insider behavior"]),
        ("Attack Signature",
         ["Brute force in log", "Credential stuffing",
          "Low-and-slow intrusion"]),
    ]),
    ("STEGO", [
        ("Payload Detection",
         ["Stego payload", "Covert C2 channel", "Encrypted covert payload"]),
    ]),
]

SEED = 0xC0FFEE
ALL_TOOLS = {"ghostscan", "hashcrack", "logwatch", "stegotool"}

# Board widths this game is actually played at, measured off the real screen:
# the tool-page boards run 55-115 cells and the Candidate board 45-95.
SIZES = ((100, 28), (120, 32), (140, 40), (160, 45), (200, 55))
# Subset for the tests that mount a whole IntakeScreen per entry — the ends of
# the range plus one middle, which is where a layout breaks if it is going to.
# Sweeping all five there costs about a minute of suite time for no new signal.
REAL_SIZES = (SIZES[0], SIZES[2], SIZES[-1])


class _Host(App):
    """Bare host app carrying the real stylesheet — the grid is computed from the
    board's measured content width, so the widths, padding, borders and reserved
    scrollbar gutter in app.tcss are part of what is under test. CSS_PATH is
    absolute for the same reason test_verdict_reveal's host is: Textual resolves
    a relative path against the declaring module, and the tests directory is one
    level deeper than app.py."""

    CSS_PATH = config.ROOT_DIR / "ui" / "tui" / "app.tcss"

    def __init__(self, board: EvidenceBoard | None = None) -> None:
        super().__init__()
        self._board = board

    def compose(self) -> ComposeResult:
        if self._board is not None:
            yield self._board


def _plain(markup: str) -> str:
    return Text.from_markup(markup).plain


def _lines(board: EvidenceBoard) -> list[str]:
    return _plain(board._render_text()).split("\n")


async def _mounted(size: tuple[int, int], *, summary: bool = False,
                   unlocked: set[str] | None = None,
                   state: EvidenceState | None = None):
    """A board and the host that will lay it out at `size`.

    The widget id matters and has to match what ships. Textual's id selector
    beats the class selector, so a board built as ("evidence-c0",
    "rules-evidence") is laid out by `#evidence-c0` — 72% — and NOT by the
    class's 100%. The read-only summary is a different widget at a different
    width (`#evidence-board`, 50%), and building it under the editable board's
    id quietly handed it 22% more room than it has in the game: enough that a
    hardcoded 46-cell rule stopped overflowing and the guard against it went
    inert. Each mode is now mounted under the id it actually uses.
    """
    st = state if state is not None else EvidenceState()
    widget_id = "evidence-board" if summary else "evidence-c0"
    classes = None if summary else "rules-evidence"
    board = EvidenceBoard(st, widget_id, classes,
                          summary=summary, unlocked_tools=unlocked)
    return st, board, _Host(board)


def _blocks(board: EvidenceBoard) -> dict[int, tuple[list[int], int, int]]:
    """item index -> (its block's rows, span start, span end)."""
    out: dict[int, tuple[list[int], int, int]] = {}
    for row, spans in board._hit.items():
        for start, end, index in spans:
            rows, _s, _e = out.get(index, ([], start, end))
            out[index] = ([*rows, row], start, end)
    return {i: (sorted(rows), s, e) for i, (rows, s, e) in out.items()}


def _label_row(board: EvidenceBoard, index: int) -> str:
    """The painted first body line of a button — where the marker, the first
    line of the name and the grade badge all live."""
    rows, start, end = _blocks(board)[index]
    return _lines(board)[rows[1]][start:end]


async def _open_board(pilot, app, page: int) -> tuple:
    """Push a real IntakeScreen, go to `page`, and open the editable board."""
    day = load_day(1)
    state = GameState(seed=SEED)
    state.unlocked_tools = set(ALL_TOOLS)
    await app.push_screen(IntakeScreen(day, state, "briefing"))
    await pilot.pause(0.4)
    scr = app.screen
    scr._goto_page(page)
    await pilot.pause(0.15)
    scr._toggle_evidence()
    await pilot.pause(0.3)
    board = (scr.board_c0, scr.board_gs, scr.board_hc,
             scr.board_lw, scr.board_st)[page]
    return scr, board


# ─── The map ─────────────────────────────────────────────────────────────────


def test_the_board_matches_the_authored_map_exactly():
    """This map is CONTENT, not a derived ordering — Nick laid these rows out by
    hand, down to which violation sits in which column, and named every
    category. Order inside a row is therefore authored rather than sorted, so
    nothing but an edit to VIOLATION_CLUSTERS may move a button. Pinned whole,
    because a diff that quietly reshuffles one row is exactly what a player's
    spatial memory of this board would trip over."""
    actual: list[tuple[str, list[tuple[str, list[str]]]]] = []
    for group, _cid, name, items in rules_content.clustered_catalog(None):
        if not actual or actual[-1][0] != group:
            actual.append((group, []))
        actual[-1][1].append((name, [lbl for _g, _k, lbl in items]))
    assert actual == AUTHORED_MAP


def test_every_category_has_a_name_and_every_name_is_distinct():
    """The categories were unnamed first and playtesters read the whitespace as
    decoration, so the names are the fix, not garnish. A blank one is refused at
    import; two identical ones would make two rows indistinguishable in exactly
    the way the names exist to prevent."""
    names = [n for _g, _c, n, _i in rules_content.clustered_catalog(None)]
    assert all(n.strip() for n in names)
    assert len(set(names)) == len(names), f"duplicate category name in {names}"


def test_every_catalogued_violation_reaches_the_board_exactly_once():
    """The board renders CATEGORIES, not the flat catalog. A kind left out of
    VIOLATION_CLUSTERS is therefore unreachable — not mis-sorted, simply gone,
    with no error and nothing on screen to notice. A kind listed twice gives the
    player two buttons that toggle the same evidence and then disagree with each
    other about its state."""
    flat = [k for _g, _c, _n, items in rules_content.clustered_catalog(None)
            for _gg, k, _l in items]
    catalog = [k for _g, k, _l in rules_content.VIOLATION_CATALOG]
    assert sorted(flat, key=lambda k: k.name) == sorted(catalog,
                                                       key=lambda k: k.name)
    assert len(flat) == len(set(flat)), "a kind appears in two categories"


def test_clustered_and_visible_catalogs_never_disagree_about_membership():
    """Two orderings of one catalog, and that is fine — `visible_catalog` (group
    then severity) still drives the Rules-page tables and the summary strip
    while `clustered_catalog` drives the board. What is NOT fine is the two
    filtering differently: the player would then be graded against a rules page
    listing a violation their board never offered. Both route through
    `_tool_unlocked`, and this pins that they still do."""
    for unlocked in (None, set(), {"ghostscan"}, {"ghostscan", "hashcrack"},
                     {"logwatch", "stegotool"}, ALL_TOOLS):
        clustered = {k for _g, _c, _n, items
                     in rules_content.clustered_catalog(unlocked)
                     for _gg, k, _l in items}
        visible = {k for _g, k, _l in rules_content.visible_catalog(unlocked)}
        assert clustered == visible, f"unlocked={unlocked}"


def test_categories_stay_inside_their_group_and_follow_group_order():
    """The board emits one header per group as it walks the category list, so a
    group appearing in two non-adjacent runs would be drawn twice."""
    runs: list[str] = []
    for group, _cid, _n, _items in rules_content.clustered_catalog(None):
        if not runs or runs[-1] != group:
            runs.append(group)
    assert len(runs) == len(set(runs)), f"a group is split across runs: {runs}"
    assert runs == [g for g in rules_content.GROUP_ORDER if g in runs]

    group_of = {k: g for g, k, _l in rules_content.VIOLATION_CATALOG}
    for group, cid, _n, items in rules_content.clustered_catalog(None):
        for _g, kind, _l in items:
            assert group_of[kind] == group, f"{kind.name} in {cid} under {group}"


def test_locked_tools_remove_whole_categories_rather_than_leaving_holes():
    """Early campaign: a category whose every kind is behind a locked tool is
    dropped entirely, name and all. Rendering the name over an empty row would
    tell the player something exists — the exact leak #33's gating prevents."""
    early = rules_content.clustered_catalog({"ghostscan"})
    assert early, "dossier + ghostscan should still yield categories"
    for group, cid, _n, items in early:
        assert items, f"empty category rendered: {cid}"
        assert group in {"DOSSIER", "OSINT"}, f"{cid} leaked group {group}"


def test_authored_rows_still_read_calm_to_alarming():
    """Advisory guard, not a layout rule. Order inside a row is authored, but
    every authored row happens to run minor -> major -> critical, which is what
    makes a row scannable. Severities do move (#51 and #53 each re-tiered a
    violation), and when one does this fails and asks for the row to be re-laid
    by hand — rather than the alternative, which is code silently re-sorting a
    layout that was chosen deliberately.

    If a re-tier is intentional and the row is fine as it stands, reorder the
    category in VIOLATION_CLUSTERS or delete this test. Do not add a sort."""
    rank = {"minor": 0, "major": 1, "critical": 2}
    for _group, cid, _n, items in rules_content.clustered_catalog(None):
        ranks = [rank[rules_content._SEVERITY[k]] for _g, k, _l in items]
        assert ranks == sorted(ranks), (
            f"category {cid} no longer runs calm-to-alarming: "
            f"{[(lbl, rules_content._SEVERITY[k]) for _g, k, lbl in items]}")


# ─── Grid geometry ───────────────────────────────────────────────────────────


def test_the_grid_is_as_wide_as_the_largest_category():
    """One column count for the whole board, so column two of one category lines
    up under column two of the next. Deriving it from the largest category means
    a smaller one ends early rather than being re-flowed to fill the row."""
    clusters = rules_content.clustered_catalog(None)
    assert grid_columns(clusters) == max(len(i) for _g, _c, _n, i in clusters)
    assert grid_columns([]) == 1, "an empty board must still be one column wide"


def test_a_grid_row_never_exceeds_the_width_it_was_given():
    """Property over the whole plausible range rather than one screenshot width.
    An over-wide row does not error — `overflow-x` is hidden on a VerticalScroll
    — it just loses its right-hand buttons silently."""
    for cols in range(1, 5):
        for avail in range(_CHIP_MIN_W, 300):
            cell = grid_cell(avail, cols)
            assert _CHIP_MIN_W <= cell <= _CHIP_MAX_W
            row = cols * cell + _CHIP_GAP * (cols - 1)
            if avail >= cols * _CHIP_MIN_W + _CHIP_GAP * (cols - 1):
                assert row <= avail, (avail, cols, cell)


def test_buttons_stop_growing_on_a_very_wide_board():
    """The docs-overlay board is 100% width. Uncapped, three buttons there
    become three 60-cell bars and the thing stops reading as a grid at all."""
    assert grid_cell(300, 3) == _CHIP_MAX_W
    assert grid_cell(60, 3) < _CHIP_MAX_W


def test_wrap_label_never_truncates_a_violation_name():
    """Wrapping downward is what lets a category stay horizontal at a width
    where its names will not fit side by side on one line. If it silently cut
    text instead, the row would still be horizontal and the buttons would be
    unreadable — which is the failure the previous stacking layout was avoiding
    by breaking the row, and neither is acceptable."""
    names = [lbl for _g, _k, lbl in rules_content.VIOLATION_CATALOG]
    for width in range(6, 40):
        for name in names:
            lines = wrap_label(name, width)
            assert all(len(ln) <= width for ln in lines), (name, width, lines)
            # Every character survives; hyphens are the only thing added.
            rebuilt = "".join(lines).replace("-", "")
            assert rebuilt.replace(" ", "") == name.replace(" ", "").replace(
                "-", ""), (name, width, lines)


def test_wrap_label_hyphenates_a_word_too_long_for_the_button():
    """A control the player has to recognise: "Affili-/ation" is readable,
    "Affilia…" is a guess."""
    assert wrap_label("Affiliation", 8) == ["Affilia-", "tion"]
    assert wrap_label("", 10) == [""]


def test_every_glyph_the_grid_draws_is_one_cell_wide():
    """`on_click` maps a mouse column back to a button by arithmetic over these
    widths, never by measuring the painted text. A double-width glyph would
    shift every button to its right — the board would toggle the wrong violation
    and nothing on screen would look wrong."""
    for glyph in CHIP_GLYPHS:
        assert Text(glyph).cell_len == 1, f"{glyph!r} is not one cell"


# ─── Layout, on the real screen ──────────────────────────────────────────────


def test_every_category_is_one_horizontal_row_at_every_size():
    """The whole organising idea, asserted structurally. Each category occupies
    exactly one band of rows, and every one of its buttons shares that band —
    never split across two, however narrow the panel."""
    async def run():
        for size in REAL_SIZES:
            for page in range(5):
                app = _Host()
                async with app.run_test(size=size) as pilot:
                    _scr, board = await _open_board(pilot, app, page)
                    blocks = _blocks(board)
                    assert blocks, f"{size} page {page}: nothing rendered"
                    start = 0
                    for _g, _c, _n, items in board._clusters:
                        bands = {tuple(blocks[start + n][0])
                                 for n in range(len(items))}
                        assert len(bands) == 1, (
                            f"{size} page {page}: a category of {len(items)} "
                            f"was split across {len(bands)} rows")
                        start += len(items)
    asyncio.run(run())


def test_columns_line_up_across_every_category():
    """A grid, not a set of independently packed rows: the nth button of every
    category starts at the same column. Sizing per category (which an earlier
    version did) makes each row tidy on its own and the board ragged overall."""
    async def run():
        for size in REAL_SIZES:
            app = _Host()
            async with app.run_test(size=size) as pilot:
                _scr, board = await _open_board(pilot, app, 1)
                by_col: dict[int, set[int]] = {}
                for spans in board._hit.values():
                    for n, (start, end, _i) in enumerate(sorted(spans)):
                        by_col.setdefault(n, set()).add((start, end))
                for col, seen in by_col.items():
                    assert len(seen) == 1, (
                        f"{size}: column {col} is drawn at {len(seen)} "
                        f"different places: {sorted(seen)}")
    asyncio.run(run())


def test_every_category_name_is_painted_above_its_row():
    async def run():
        app = _Host()
        async with app.run_test(size=(160, 45)) as pilot:
            _scr, board = await _open_board(pilot, app, 1)
            text = "\n".join(_lines(board))
            for _g, _c, name, _i in board._clusters:
                assert name in text, f"category name {name!r} never rendered"
    asyncio.run(run())


def test_no_rendered_line_overflows_the_panel_at_any_size():
    """Every line, both board modes, across the sizes this game is played at —
    buttons, group headers, category names, the mouse hint, the wrapped category
    strip, its rule, and the post-verdict footer.

    The unfocused pass is not decoration. The board is the only focusable widget
    in this host, so Textual focuses it on mount and the keyboard hint — which
    renders only when the board is NOT focused, and is one of the two longest
    lines it can draw — is never reached otherwise."""
    async def run():
        for width, height in SIZES:
            for summary in (False, True):
                st = EvidenceState()
                st.cycle(DiscrepancyKind.BREACH_HIT)
                st.cycle(DiscrepancyKind.UNSALTED_STORAGE)
                st.cycle(DiscrepancyKind.UNSALTED_STORAGE)   # → absent
                _s, board, app = await _mounted((width, height),
                                                summary=summary, state=st)
                async with app.run_test(size=(width, height)) as pilot:
                    await pilot.pause(0.25)
                    room = board._content.region.width
                    for focused in (True, False):
                        if summary and focused:
                            continue          # can_focus is False there
                        board._focused = focused
                        for phase in ("ungraded", "graded"):
                            # Reset per phase, not once: reveal() latches, and
                            # the ungraded branch is the ONLY one that draws the
                            # hint. Letting the first graded pass stick meant
                            # unfocused-and-ungraded was never visited.
                            if phase == "ungraded":
                                st.clear_reveal()
                            else:
                                st.reveal(
                                    {DiscrepancyKind.BREACH_HIT,
                                     DiscrepancyKind.LEAKED_PASSWORD},
                                    {k for _g, k, _l
                                     in rules_content.visible_catalog(None)})
                            for i, line in enumerate(_lines(board)):
                                assert len(line) <= room, (
                                    f"{width}x{height} summary={summary} "
                                    f"focused={focused} {phase} line {i} is "
                                    f"{len(line)} cells in {room}: {line!r}")
    asyncio.run(run())


def test_no_button_is_laid_out_past_the_edge_of_the_widget_that_paints_it():
    """The container's `content_size` and the inner Static's own region differ by
    a cell (the stable scrollbar gutter comes off one and not the other). Sizing
    the grid from the wrong one put the rightmost button's last column outside
    the Static: painted nowhere, still claimed by the hit map, and so a dead
    strip down the right edge that quietly ate clicks."""
    async def run():
        for size in SIZES:
            _st, board, app = await _mounted(size)
            async with app.run_test(size=size):
                await asyncio.sleep(0.25)
                paint_w = board._content.region.width
                assert paint_w > 0
                for row, spans in board._hit.items():
                    for _start, end, index in spans:
                        assert end <= paint_w, (
                            f"{size}: item {index} on row {row} is mapped out "
                            f"to column {end}, past the {paint_w}-cell Static")
    asyncio.run(run())


# ─── Hit map vs paint ────────────────────────────────────────────────────────


def test_every_hit_span_lands_on_the_button_it_claims():
    """The heart of it. `on_click` recomputes the layout arithmetic instead of
    measuring the painted text, so map and paint are two implementations of one
    layout and can drift. This slices the PAINTED lines at the span the map
    reports and demands the button really be there — an assertion the map cannot
    satisfy on its own.

    A button is a block: a half-block edge row, one or more body lines carrying
    the wrapped name, then the closing edge. Every row of it is mapped, because
    the point of a taller button is that all of it is a click target."""
    async def run():
        for size in REAL_SIZES:
            app = _Host()
            async with app.run_test(size=size) as pilot:
                _scr, board = await _open_board(pilot, app, 1)
                lines = _lines(board)
                blocks = _blocks(board)
                assert set(blocks) == set(range(len(board._items))), (
                    "some buttons are painted but unmapped, or vice versa")

                for index, (rows, start, end) in blocks.items():
                    label = board._items[index][2]
                    assert rows == list(range(rows[0], rows[0] + len(rows))), (
                        f"item {index}'s block is not contiguous: {rows}")
                    assert len(rows) >= 3, (
                        f"item {index} has no body between its edges: {rows}")

                    label_w = (end - start) - _CHIP_CHROME
                    wrapped = wrap_label(label, label_w)
                    body = lines[rows[0] + 1][start:end]
                    # Anatomy, in cells: cap, marker, space, name, space, cap,
                    # grade. Asserted by POSITION, not by substring: "the name
                    # is somewhere in this slice" is satisfied by a span off by
                    # a cell or two, because a button is padded on both sides —
                    # and off-by-a-cell is the entire bug class this exists for.
                    assert len(body) == end - start
                    assert body[0] == _CAP_LEFT, (
                        f"{size}: span for item {index} does not start on a "
                        f"button cap: {body!r}")
                    assert body[1] in "○▲✗", (
                        f"{size}: no state marker after the cap of item "
                        f"{index}: {body!r}")
                    assert body[3:3 + len(wrapped[0])] == wrapped[0], (
                        f"{size}: map puts item {index} ({label!r}) at row "
                        f"{rows[0] + 1} cols {start}-{end}, but the paint "
                        f"there is {body!r}")

                    for edge, row in ((_EDGE_TOP, rows[0]),
                                      (_EDGE_BOT, rows[-1])):
                        painted = lines[row][start:end - 1]
                        assert set(painted) == {edge}, (
                            f"{size}: item {index} row {row} should be a "
                            f"{edge!r} edge, painted {lines[row][start:end]!r}")
    asyncio.run(run())


def test_buttons_do_not_overlap_and_leave_real_gaps_between_them():
    """A too-generous span would swallow the gutter and make a miss register as
    a hit on the button to its left."""
    async def run():
        app = _Host()
        async with app.run_test(size=(200, 55)) as pilot:
            _scr, board = await _open_board(pilot, app, 1)
            for row, spans in board._hit.items():
                ordered = sorted(spans)
                for (_s1, e1, _i1), (s2, _e2, _i2) in pairwise(ordered):
                    assert e1 <= s2, f"row {row}: spans overlap"
                    assert s2 - e1 == _CHIP_GAP, f"row {row}: gutter is not the gap"
                assert ordered[0][0] == _BOARD_INDENT
    asyncio.run(run())


def test_hit_test_returns_nothing_for_headers_names_gaps_and_the_margin():
    async def run():
        app = _Host()
        async with app.run_test(size=(200, 55)) as pilot:
            _scr, board = await _open_board(pilot, app, 1)
            chip_rows = set(board._hit)
            other = [i for i in range(len(_lines(board))) if i not in chip_rows]
            assert other, "expected header / name / spacer rows"
            for row in other:
                assert board.hit_test(_BOARD_INDENT, row) is None
            row = min(chip_rows)
            assert board.hit_test(0, row) is None, "left margin is not a button"
            first_end = min(board._hit[row])[1]
            assert board.hit_test(first_end, row) is None, "gutter is not a button"
    asyncio.run(run())


# ─── Clicking ────────────────────────────────────────────────────────────────


def _pointer_at(board, x: int, y: int) -> tuple[int, int]:
    """Board-relative offset for content cell (x, y), resolved ONCE.

    Anything clicking more than once has to hold this fixed. A real pointer does
    not move between clicks, so if the board scrolls underneath it the second
    click lands somewhere else — which is precisely the bug
    `test_a_button_low_in_a_scrolling_board_cycles_all_the_way_round` exists to
    catch. Re-deriving the offset from `board._content.region` before every click
    silently follows the scroll and makes that test unfailable.
    """
    region = board._content.region
    return (region.x - board.region.x + x, region.y - board.region.y + y)


async def _click_offset(pilot, board, offset: tuple[int, int]) -> None:
    await pilot.click(board, offset=offset)
    await pilot.pause(0.1)


async def _click_content(pilot, board, x: int, y: int) -> None:
    await _click_offset(pilot, board, _pointer_at(board, x, y))


def test_clicking_a_button_cycles_that_violation():
    async def run():
        st, board, app = await _mounted((160, 45))
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause(0.25)
            row = min(board._hit)
            start, _end, index = min(board._hit[row])
            kind = board._items[index][1]
            assert st.state_of(kind) == "unknown"
            await _click_content(pilot, board, start + 3, row)
            assert st.state_of(kind) == "marked"
    asyncio.run(run())


def test_clicking_the_second_column_hits_the_second_column():
    """The failure this exists for is an off-by-one-cell hit map, invisible in
    column one (every miss still lands on the only button there) and obvious in
    column two — where it toggles the button beside the pointer."""
    async def run():
        st, board, app = await _mounted((200, 55))
        async with app.run_test(size=(200, 55)) as pilot:
            await pilot.pause(0.25)
            row = next(r for r in sorted(board._hit) if len(board._hit[r]) > 1)
            start, end, index = sorted(board._hit[row])[1]
            kind = board._items[index][1]
            for x in (start, start + 3, end - 2):
                st.clear()
                await _click_content(pilot, board, x, row)
                assert st.get_flags() == {kind}, (
                    f"clicking cell {x} on row {row} flagged {st.get_flags()} "
                    f"instead of {kind.name}")
    asyncio.run(run())


def test_every_row_of_a_button_is_clickable():
    """A tall button whose middle line is the only live one would be a worse
    target than the single row it replaced."""
    async def run():
        st, board, app = await _mounted((200, 55))
        async with app.run_test(size=(200, 55)) as pilot:
            await pilot.pause(0.25)
            rows, start, _end = _blocks(board)[0]
            assert len(rows) >= 3
            kind = board._items[0][1]
            for n, row in enumerate(rows):
                st.clear()
                await _click_content(pilot, board, start + 3, row)
                assert st.get_flags() == {kind}, (
                    f"row {n} of the button did not toggle it")
    asyncio.run(run())


def test_clicking_after_scrolling_hits_the_button_under_the_pointer():
    """The scroll offset has to come out of the content widget's own screen
    region. Reading `event.x/y` and subtracting this container's gutter instead
    looks identical at scroll 0 and is wrong by exactly the scroll distance
    everywhere else — so an unscrolled test would pass while the board is
    unusable below the fold, which is most of it."""
    async def run():
        st, board, app = await _mounted((160, 24))
        async with app.run_test(size=(160, 24)) as pilot:
            await pilot.pause(0.25)
            board.focus()
            await pilot.pause(0.1)
            board.scroll_to(y=8, animate=False)
            await pilot.pause(0.3)
            assert board.scroll_offset.y > 0, "the board did not actually scroll"
            top = board.scroll_offset.y
            fold = top + board.content_size.height - 2
            rows = [r for r in sorted(board._hit) if top <= r <= fold]
            assert rows, "no mapped row is on screen after scrolling"
            row = rows[len(rows) // 2]
            start, _end, index = min(board._hit[row])
            kind = board._items[index][1]
            await _click_content(pilot, board, start + 3, row)
            assert st.get_flags() == {kind}, (
                f"scrolled click flagged {st.get_flags()} not {kind.name}")
    asyncio.run(run())


def test_clicking_never_scrolls_the_board():
    """The regression that made this feel broken to play.

    `repaint()` used to scroll the cursor back into view unconditionally, and a
    click sets the cursor — so clicking a button two thirds down a scrolling
    board yanked it to the top, and the player's NEXT click landed on whatever
    slid under the pointer. The symptom read as "buttons can only be marked,
    never crossed out", which looks like a broken state machine and is really a
    broken scroll. Scroll-to-cursor belongs to the arrow keys alone."""
    async def run():
        st, board, app = await _mounted((120, 18))
        async with app.run_test(size=(120, 18)) as pilot:
            await pilot.pause(0.25)
            board.focus()
            await pilot.pause(0.1)
            board.scroll_to(y=10, animate=False)
            await pilot.pause(0.3)
            before = board.scroll_offset.y
            assert before > 0, "the board did not actually scroll"
            fold = before + board.content_size.height - 2
            rows = [r for r in sorted(board._hit) if before <= r <= fold]
            assert rows, "no mapped row is on screen"
            row = rows[-1]                      # deliberately near the bottom
            start, _end, index = min(board._hit[row])
            kind = board._items[index][1]
            await _click_content(pilot, board, start + 3, row)
            assert board.scroll_offset.y == before, (
                f"clicking scrolled the board {before} -> "
                f"{board.scroll_offset.y}; the next click would land on a "
                f"different button")
            assert st.state_of(kind) == "marked"
    asyncio.run(run())


def test_a_button_low_in_a_scrolling_board_cycles_all_the_way_round():
    """The same bug from the player's seat, in the real screen at a terminal size
    where the board must scroll: click one spot three times and that button must
    go marked -> ruled out -> clear.

    The setup is deliberate rather than incidental. The yank was proportional to
    how far the clicked button sat below the top of the viewport, so a button
    near the fold moved the board barely at all and the bug hid completely. A
    first version picked whatever row happened to be last and passed against the
    broken code — hence the explicit pre-scroll and the bottom-of-viewport pick.
    """
    async def run():
        app = _Host()
        async with app.run_test(size=(120, 30)) as pilot:
            scr, board = await _open_board(pilot, app, 1)
            board.scroll_to(y=12, animate=False)
            await pilot.pause(0.3)
            top = board.scroll_offset.y
            assert top > 0, "the board did not actually scroll"
            fold = top + board.content_size.height - 2
            rows = [r for r in sorted(board._hit) if top <= r <= fold]
            assert rows, "no mapped row is inside the viewport"
            row = rows[-1]
            start, _end, index = min(board._hit[row])
            kind = board._items[index][1]
            seen = []
            pointer = _pointer_at(board, start + 3, row)   # fixed, see helper
            for _ in range(3):
                await _click_offset(pilot, board, pointer)
                seen.append(scr.evidence_state.state_of(kind))
            assert seen == ["marked", "absent", "unknown"], (
                f"{kind.name} went {seen} — a click is landing on the wrong "
                f"button (scroll {top} -> {board.scroll_offset.y})")
    asyncio.run(run())


def test_clicking_a_gutter_records_nothing():
    async def run():
        st, board, app = await _mounted((200, 55))
        async with app.run_test(size=(200, 55)) as pilot:
            await pilot.pause(0.25)
            row = next(r for r in sorted(board._hit) if len(board._hit[r]) > 1)
            first_end = min(board._hit[row])[1]
            await _click_content(pilot, board, first_end, row)
            assert st._states == {}, "a click between buttons changed the record"
            header = min(r for r in range(len(_lines(board)))
                         if r not in board._hit)
            await _click_content(pilot, board, _BOARD_INDENT, header)
            assert st._states == {}, "a click on a header changed the record"
    asyncio.run(run())


def test_click_and_space_share_one_cycle():
    """Both routes go through `_toggle` → `EvidenceState.cycle`, so three clicks
    return a button to unknown exactly as three presses of Space do. A mouse path
    that set "marked" directly would pass a one-click test and strand the player
    at marked forever."""
    async def run():
        st, board, app = await _mounted((160, 45))
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause(0.25)
            top = board.scroll_offset.y
            fold = top + board.content_size.height - 2
            rows = [r for r in sorted(board._hit) if top <= r <= fold]
            row = rows[len(rows) // 2]
            start, _end, index = min(board._hit[row])
            kind = board._items[index][1]
            seen = []
            pointer = _pointer_at(board, start + 3, row)   # fixed, see helper
            for _ in range(3):
                await _click_offset(pilot, board, pointer)
                seen.append(st.state_of(kind))
            assert seen == ["marked", "absent", "unknown"], seen
    asyncio.run(run())


def test_a_click_moves_the_keyboard_cursor_to_what_was_clicked():
    """Otherwise the two input methods fight: click button 12, press Space, and
    button 0 toggles."""
    async def run():
        st, board, app = await _mounted((160, 45))
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause(0.25)
            board.focus()
            await pilot.pause(0.1)
            row = sorted(board._hit)[6]
            start, _end, index = min(board._hit[row])
            kind = board._items[index][1]
            await _click_content(pilot, board, start + 3, row)
            assert board._cursor == index
            await pilot.press("space")
            await pilot.pause(0.1)
            assert st.state_of(kind) == "absent", (
                "Space after a click moved a different button")
    asyncio.run(run())


def test_the_summary_board_ignores_clicks():
    """It is a read-only report of what was recorded elsewhere; a click on it
    must not become a way to record evidence from the Candidate page without
    ever opening a tool.

    Two independent latches, and both are checked, because the outer one alone
    hides whether the inner one works: the summary renderer builds no hit map,
    so a real click has nothing to land on no matter what `on_click` does. The
    second half therefore FORCES a hit map onto a summary board and posts a click
    at it directly — the only way to observe the `if self._summary` early return,
    which is what keeps the widget safe if a later change gives the summary view
    buttons of its own."""
    class _FakeClick:
        button = 1
        def __init__(self, x, y):
            self.screen_x, self.screen_y = x, y
        def stop(self):
            pass

    async def run():
        st, board, app = await _mounted((160, 45), summary=True)
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause(0.25)
            assert board._hit == {}, "the summary built a hit map"
            await _click_content(pilot, board, 4, 0)
            await _click_content(pilot, board, 4, 3)
            assert st._states == {}, "a real click on the summary recorded evidence"

            region = board._content.region
            board._hit = {0: [(2, 20, 0)]}
            assert board.hit_test(4, 0) == 0, "test setup did not take"
            board.on_click(_FakeClick(region.x + 4, region.y + 0))
            await pilot.pause(0.1)
            assert st._states == {}, (
                "on_click acted on a summary board that had a hit map")
    asyncio.run(run())


# ─── Keyboard: across the grid, not along a list ──────────────────────────────


def test_down_moves_one_grid_row_and_keeps_the_column():
    """Down means down now. The old board walked the flat catalog in reading
    order, so on a grid ↓ stepped sideways — players said navigating it was
    irritating and that it taught them nothing about how the violations group."""
    async def run():
        _st, board, app = await _mounted((200, 55))
        async with app.run_test(size=(200, 55)) as pilot:
            await pilot.pause(0.25)
            board.focus()
            await pilot.pause(0.1)
            await pilot.press("right")          # into column 1
            await pilot.pause(0.05)
            assert board._pos[board._cursor] == (0, 1)
            await pilot.press("down")
            await pilot.pause(0.05)
            assert board._pos[board._cursor] == (1, 1), "↓ left the column"
            await pilot.press("up")
            await pilot.pause(0.05)
            assert board._pos[board._cursor] == (0, 1)
    asyncio.run(run())


def test_the_cursor_remembers_its_column_across_a_narrower_row():
    """A 3/1/3 grid: stepping down through the single-button row and on must come
    back to column 2, not drift left and stay there. Without a remembered column
    the cursor silently walks to the left edge over a few presses."""
    async def run():
        _st, board, app = await _mounted((200, 55))
        async with app.run_test(size=(200, 55)) as pilot:
            await pilot.pause(0.25)
            board.focus()
            await pilot.pause(0.1)
            rows = board._grid
            narrow = next(r for r in range(1, len(rows) - 1)
                          if len(rows[r]) == 1 and len(rows[r - 1]) > 1
                          and len(rows[r + 1]) > 1)
            board._cursor = rows[narrow - 1][-1]
            board._desired_col = len(rows[narrow - 1]) - 1
            await pilot.press("down")           # onto the single-button row
            await pilot.pause(0.05)
            assert board._pos[board._cursor] == (narrow, 0)
            await pilot.press("down")           # and out the other side
            await pilot.pause(0.05)
            row, col = board._pos[board._cursor]
            assert (row, col) == (narrow + 1,
                                 min(board._desired_col,
                                     len(rows[narrow + 1]) - 1))
            assert col > 0, "the cursor drifted to the left edge and stayed"
    asyncio.run(run())


def test_left_at_the_first_column_is_left_for_the_screen_to_handle():
    """The board consumes ← / → only when the move lands somewhere. Swallowing
    them unconditionally would trap focus in a panel with no arrow key to leave
    — IntakeScreen binds them to focus navigation."""
    async def run():
        _st, board, app = await _mounted((200, 55))
        async with app.run_test(size=(200, 55)) as pilot:
            await pilot.pause(0.25)
            board.focus()
            await pilot.pause(0.1)
            board._cursor = board._grid[0][0]
            board._desired_col = 0
            assert board._move(0, -1) is False, "← escaped column 0"
            assert board._move(0, 1) is True
            assert board._move(-1, 0) is False, "↑ escaped the first row"
            board._cursor = board._grid[-1][-1]
            assert board._move(0, 1) is False, "→ escaped the last column"
            assert board._move(1, 0) is False, "↓ escaped the last row"
    asyncio.run(run())


def test_arrow_keys_still_pull_the_cursor_back_into_view():
    """↑↓ must follow the cursor, or it walks off the bottom of the panel and the
    player loses it — the other half of the scroll knob."""
    async def run():
        _st, board, app = await _mounted((120, 18))
        async with app.run_test(size=(120, 18)) as pilot:
            await pilot.pause(0.25)
            board.focus()
            await pilot.pause(0.1)
            before = board.scroll_offset.y
            for _ in range(8):
                await pilot.press("down")
            await pilot.pause(0.25)
            assert board.scroll_offset.y > before, (
                "walking the cursor down never scrolled the board")
    asyncio.run(run())


# ─── Colour language and grading ─────────────────────────────────────────────


def test_a_marked_button_is_filled_with_its_own_severity_colour():
    """Severity colour is the board's whole visual language (yellow minor, orange
    major, red critical) and predates this layout. State changes the surface,
    never the hue: a marked button paints its severity as the FILL."""
    from gameengine.ui.tui.shared import _SEV_COLOR, _SEVERITY, _sev_color

    # Pick a live representative of each tier off the engine's own severity map
    # rather than naming kinds here — the tiers move (#51, #53 both re-tiered a
    # violation) and a hardcoded pair silently degrades into comparing one
    # colour with itself the day one of them is re-graded.
    reps: dict[str, DiscrepancyKind] = {}
    for _g, kind, _l in rules_content.VIOLATION_CATALOG:
        reps.setdefault(_SEVERITY.get(kind, "minor"), kind)
    assert set(reps) == set(_SEV_COLOR), f"no representative per tier: {reps}"

    async def run():
        st = EvidenceState()
        _s, board, app = await _mounted((160, 45), state=st)
        async with app.run_test(size=(160, 45)):
            await asyncio.sleep(0.25)
            for severity, kind in reps.items():
                st.clear()
                st.cycle(kind)
                markup = board._render_text()
                assert f"on {_sev_color(kind)}]{'▲'} " in markup, (
                    f"{severity} {kind.name} is not filled with "
                    f"{_sev_color(kind)}")
                for other, colour in _SEV_COLOR.items():
                    if other != severity:
                        assert f"on {colour}]{'▲'} " not in markup, (
                            f"marking a {severity} violation lit a button in "
                            f"the {other} colour")
    asyncio.run(run())


def test_grades_reach_the_buttons_and_only_the_touched_ones():
    """The reveal contract survives the relayout: ✓/✗ on rows the player actually
    called, and nothing at all on the ones they left alone — a blank button is
    how the answer key stays off the board."""
    async def run():
        st = EvidenceState()
        st.cycle(DiscrepancyKind.BREACH_HIT)                 # right
        st.cycle(DiscrepancyKind.HOSTILE_CHAT)               # wrong
        _s, board, app = await _mounted((160, 45), state=st)
        async with app.run_test(size=(160, 45)):
            await asyncio.sleep(0.25)
            before = "".join(_lines(board))
            assert "✓" not in before and "✗" not in before

            st.reveal({DiscrepancyKind.BREACH_HIT,
                       DiscrepancyKind.LEAKED_PASSWORD},
                      {k for _g, k, _l in rules_content.visible_catalog(None)})
            idx = {k: i for i, (_g, k, _l) in enumerate(board._items)}
            assert "✓" in _label_row(board, idx[DiscrepancyKind.BREACH_HIT])
            assert "✗" in _label_row(board, idx[DiscrepancyKind.HOSTILE_CHAT])
            untouched = _label_row(board, idx[DiscrepancyKind.LEAKED_PASSWORD])
            assert "✓" not in untouched and "✗" not in untouched, (
                "an untouched violation was graded — that is the answer key")
            assert "1 violation went unrecorded." in "\n".join(_lines(board))
    asyncio.run(run())


# ─── The real screen ─────────────────────────────────────────────────────────


def test_the_board_gets_real_width_on_every_page_it_opens_on():
    """The layout only works because the board takes ~60-72% while it is open.
    At the old sidebar widths three buttons could not fit at all and every
    category collapsed into a vertical stack. If a stylesheet edit narrows these
    again the grid quietly degrades, so the width is pinned as a requirement."""
    async def run():
        for size in ((100, 28), (120, 32), (160, 45)):
            for page in range(5):
                app = _Host()
                async with app.run_test(size=size) as pilot:
                    _scr, board = await _open_board(pilot, app, page)
                    room = board._content.region.width
                    cols = grid_columns(board._clusters)
                    need = cols * _CHIP_MIN_W + _CHIP_GAP * (cols - 1) \
                        + _BOARD_INDENT
                    assert room >= need, (
                        f"{size} page {page}: board is {room} cells, needs "
                        f"{need} for a {cols}-wide grid")
                    assert board._hit, f"{size} page {page}: nothing clickable"
    asyncio.run(run())


def test_the_verdict_panel_yields_width_while_the_board_is_open():
    """The Candidate-page board and ADMIT/DENY share the mid row. The board needs
    most of it to hold a grid, so the verdict panel narrows while the board is
    showing and takes its half back the moment it closes."""
    async def run():
        app = _Host()
        async with app.run_test(size=(140, 40)) as pilot:
            day = load_day(1)
            state = GameState(seed=SEED)
            state.unlocked_tools = set(ALL_TOOLS)
            await app.push_screen(IntakeScreen(day, state, "briefing"))
            await pilot.pause(0.4)
            scr = app.screen
            panel = scr.query_one("#verdict-panel")
            assert not panel.has_class("narrow"), "starts at the 50/50 default"
            wide = panel.size.width

            scr._toggle_evidence()
            await pilot.pause(0.3)
            assert panel.has_class("narrow")
            assert panel.size.width < wide, "the verdict panel never gave way"
            assert scr.btn_admit.size.width > 0, "ADMIT was squeezed to nothing"

            scr._toggle_evidence()
            await pilot.pause(0.3)
            assert not panel.has_class("narrow")
            assert panel.size.width == wide, "the panel did not take its half back"
    asyncio.run(run())


def test_resizing_the_terminal_repacks_the_grid():
    """`on_resize` is guarded on the measured width so a scrollbar appearing
    cannot start an oscillation — the guard has to still let a real resize
    through, and the buttons have to actually resize with it."""
    async def run():
        _st, board, app = await _mounted((90, 40))
        async with app.run_test(size=(90, 40)) as pilot:
            await pilot.pause(0.3)
            row = min(board._hit)
            before_cell = min(board._hit[row])[1] - min(board._hit[row])[0]
            before_w = board._last_width
            await pilot.resize_terminal(200, 40)
            await pilot.pause(0.4)
            row = min(board._hit)
            after_cell = min(board._hit[row])[1] - min(board._hit[row])[0]
            assert board._last_width > before_w, "the board never saw the resize"
            assert after_cell > before_cell, (
                f"buttons did not grow on resize: {before_cell} -> {after_cell}")
    asyncio.run(run())
