"""Tests for the Evidence Board's clustered, clickable chip grid.

The board stopped being a plain list of text rows and became a grid of chips
that the player can click, packed into unnamed clusters inside each tool group.
Three things about that are worth guarding, and they are the three sections
below.

  * **The cluster map is content.** `VIOLATION_CLUSTERS` is a second hand-
    written index of the same catalog `VIOLATION_CATALOG` already indexes, and
    a kind missing from it does not error at render time — it simply never
    appears on the board again, on any page, for the rest of the campaign. The
    module raises at import for the structural failures; these tests cover the
    ones a bad edit could still slip past, chiefly "the two orderings disagree
    about MEMBERSHIP, not just order".

  * **The hit map has to agree with the paint.** `on_click` does not measure
    the rendered text; it recomputes the same arithmetic the renderer used.
    That is fast and it is exactly the shape of bug that stays invisible: the
    chips look right, and clicking one toggles its neighbour. So the click
    tests never assert against the map alone — they slice the PAINTED line at
    the coordinates the map claims and check the label is really there. (Same
    lesson as Batch 4's tool guards: a conclusion computed from the same source
    as the assertion proves nothing; only the body is evidence.)

  * **Width is a moving target.** This one widget is mounted at five different
    percentage widths and the terminal itself resizes under all of them, so
    "fits" is a property to be checked across a range, not at one size.
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
    _CHIP_CHROME,
    _CHIP_GAP,
    _CHIP_MAX_COLS,
    chip_columns,
)

SEED = 0xC0FFEE
ALL_TOOLS = {"ghostscan", "hashcrack", "logwatch", "stegotool"}


class _Host(App):
    """Bare host app carrying the real stylesheet — the board's column count is
    computed from its measured content width, so the widths, padding, borders
    and reserved scrollbar gutter in app.tcss are part of what is under test.
    CSS_PATH is absolute for the same reason test_verdict_reveal's host is:
    Textual resolves a relative path against the declaring module, and the
    tests directory is one level deeper than app.py."""

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


async def _mounted(pilot_size: tuple[int, int], *, summary: bool = False,
                   unlocked: set[str] | None = None,
                   state: EvidenceState | None = None):
    """Yield a focused, laid-out board at a given terminal size."""
    st = state if state is not None else EvidenceState()
    board = EvidenceBoard(st, "evidence-c0", "rules-evidence",
                          summary=summary, unlocked_tools=unlocked)
    app = _Host(board)
    return st, board, app


# ─── The cluster map ─────────────────────────────────────────────────────────


def test_every_catalogued_violation_reaches_the_board_exactly_once():
    """The board renders CLUSTERS, not the flat catalog. A kind left out of
    VIOLATION_CLUSTERS is therefore unreachable — not mis-sorted, not oddly
    placed, simply gone, with no error and nothing on screen to notice. A kind
    listed twice gives the player two chips that toggle the same evidence and
    disagree with each other about its state."""
    flat = [k for _g, _c, items in rules_content.clustered_catalog(None)
            for _gg, k, _l in items]
    catalog = [k for _g, k, _l in rules_content.VIOLATION_CATALOG]
    assert sorted(flat, key=lambda k: k.name) == sorted(catalog, key=lambda k: k.name)
    assert len(flat) == len(set(flat)), "a kind appears in two clusters"


def test_clustered_and_visible_catalogs_never_disagree_about_membership():
    """Two orderings of one catalog, and that is fine — `visible_catalog`
    (group then severity) still drives the Rules-page tables and the summary
    strip while `clustered_catalog` drives the board's layout. What is NOT fine
    is the two filtering differently: the player would then be graded against a
    rules page listing a violation their board never offered. Both route
    through `_tool_unlocked`, and this pins that they still do."""
    for unlocked in (None, set(), {"ghostscan"}, {"ghostscan", "hashcrack"},
                     {"logwatch", "stegotool"}, ALL_TOOLS):
        clustered = {k for _g, _c, items in rules_content.clustered_catalog(unlocked)
                     for _gg, k, _l in items}
        visible = {k for _g, k, _l in rules_content.visible_catalog(unlocked)}
        assert clustered == visible, f"unlocked={unlocked}"


def test_clusters_stay_inside_their_group_and_follow_group_order():
    """The board emits one header per group as it walks the cluster list, so a
    group that appears in two non-adjacent runs would be drawn twice."""
    runs = []
    for group, _cid, _items in rules_content.clustered_catalog(None):
        if not runs or runs[-1] != group:
            runs.append(group)
    assert len(runs) == len(set(runs)), f"a group is split across runs: {runs}"
    assert runs == [g for g in rules_content.GROUP_ORDER if g in runs]

    group_of = {k: g for g, k, _l in rules_content.VIOLATION_CATALOG}
    for group, cid, items in rules_content.clustered_catalog(None):
        for _g, kind, _l in items:
            assert group_of[kind] == group, f"{kind.name} in {cid} under {group}"


def test_locked_tools_remove_whole_clusters_rather_than_leaving_holes():
    """Early campaign: a cluster whose every kind is behind a locked tool is
    dropped entirely. Rendering it as an empty block would leave the player
    staring at whitespace where a violation they cannot see used to be, which
    tells them something exists — the exact leak #33's gating exists to stop."""
    early = rules_content.clustered_catalog({"ghostscan"})
    assert early, "dossier + ghostscan should still yield clusters"
    for group, cid, items in early:
        assert items, f"empty cluster rendered: {cid}"
        assert group in {"DOSSIER", "OSINT"}, f"{cid} leaked group {group}"


def test_nicks_two_examples_actually_sit_together():
    """The pairings Nick named when specifying this are the reason the map is
    shaped the way it is, so they are pinned rather than left to a future tidy-
    up: a breach hit next to a threat-forum handle match, and brute force next
    to low-and-slow."""
    cluster_of = {}
    for _g, cid, items in rules_content.clustered_catalog(None):
        for _gg, kind, _l in items:
            cluster_of[kind] = cid
    assert (cluster_of[DiscrepancyKind.BREACH_HIT]
            == cluster_of[DiscrepancyKind.THREAT_FORUM_MATCH])
    assert (cluster_of[DiscrepancyKind.BRUTE_FORCE_IN_LOG]
            == cluster_of[DiscrepancyKind.LOW_AND_SLOW])


# ─── Geometry ────────────────────────────────────────────────────────────────


def test_a_packed_row_never_exceeds_the_width_it_was_given():
    """Property over the whole plausible range rather than one screenshot
    width. An over-wide row does not error — `overflow-x` is hidden on a
    VerticalScroll — it just loses its right-hand chips silently."""
    for longest in (8, 16, 24, 28, 40):
        for avail in range(14, 260):
            cols, cell = chip_columns(avail, longest)
            assert 1 <= cols <= _CHIP_MAX_COLS
            row = cols * cell + _CHIP_GAP * (cols - 1)
            if avail >= longest + _CHIP_CHROME:
                assert row <= avail, (avail, longest, cols, cell)


def test_labels_are_never_truncated_once_a_single_chip_fits():
    """The column count is solved from the NATURAL chip width, so widening the
    panel can only ever add columns — it can never squeeze the labels. Getting
    this backwards (pick columns first, divide the width second) is the obvious
    implementation and it silently starts chopping labels at every breakpoint."""
    for longest in (8, 20, 28):
        for avail in range(longest + _CHIP_CHROME, 260):
            _cols, cell = chip_columns(avail, longest)
            assert cell - _CHIP_CHROME >= longest, (avail, longest, cell)


def test_a_wider_panel_packs_more_columns():
    def go():
        async def run():
            _st, board, app = await _mounted((60, 40))
            async with app.run_test(size=(60, 40)):
                await asyncio.sleep(0.2)
                narrow = max(len(v) for v in board._hit.values())
            _st2, board2, app2 = await _mounted((200, 40))
            async with app2.run_test(size=(200, 40)):
                await asyncio.sleep(0.2)
                wide = max(len(v) for v in board2._hit.values())
            return narrow, wide
        return asyncio.run(run())

    narrow, wide = go()
    assert narrow == 1, f"a 60-column terminal should be single-column, got {narrow}"
    assert wide > narrow, f"a 200-column terminal packed only {wide} per row"


def test_no_rendered_line_overflows_the_panel_at_any_size():
    """Every line, both board modes, across the sizes this game is actually
    played at — chips, group headers, the keyboard hint, the wrapped category
    strip, its rule, and the post-verdict footer.

    The unfocused pass is not decoration. The board is the only focusable
    widget in this host, so Textual focuses it on mount and the keyboard hint —
    which only renders when the board is NOT focused, and is one of the two
    longest lines it can draw — is never reached otherwise. Testing only the
    focused state let an unwrapped hint sail straight through this assertion.
    """
    async def run():
        for width, height in ((80, 30), (100, 40), (120, 40), (160, 50), (240, 60)):
            for summary in (False, True):
                st = EvidenceState()
                st.cycle(DiscrepancyKind.BREACH_HIT)
                st.cycle(DiscrepancyKind.UNSALTED_STORAGE)
                st.cycle(DiscrepancyKind.UNSALTED_STORAGE)   # → absent
                _s, board, app = await _mounted((width, height),
                                                summary=summary, state=st)
                async with app.run_test(size=(width, height)) as pilot:
                    await pilot.pause(0.2)
                    room = board.content_size.width
                    for focused in (True, False):
                        if summary and focused:
                            continue          # can_focus is False there
                        board._focused = focused
                        for phase in ("ungraded", "graded"):
                            # Reset per phase, not once: reveal() latches, and
                            # the ungraded branch is the ONLY one that draws the
                            # keyboard hint. Letting the first graded pass stick
                            # meant the unfocused-and-ungraded combination — the
                            # single case where that hint renders — was never
                            # actually visited.
                            if phase == "ungraded":
                                st.clear_reveal()
                            else:
                                st.reveal({DiscrepancyKind.BREACH_HIT,
                                           DiscrepancyKind.LEAKED_PASSWORD},
                                          {k for _g, k, _l
                                           in rules_content.visible_catalog(None)})
                            for i, line in enumerate(_lines(board)):
                                assert len(line) <= room, (
                                    f"{width}x{height} summary={summary} "
                                    f"focused={focused} {phase} line {i} is "
                                    f"{len(line)} cells in {room}: {line!r}")
    asyncio.run(run())


# ─── Hit map vs paint ────────────────────────────────────────────────────────


def test_every_hit_span_lands_on_the_chip_it_claims():
    """The heart of it. `on_click` recomputes the layout arithmetic instead of
    measuring the painted text, so map and paint are two implementations of one
    layout and can drift. This slices the PAINTED line at the span the map
    reports and demands the label be inside it — an assertion the map cannot
    satisfy on its own."""
    async def run():
        for width in (80, 120, 200):
            _st, board, app = await _mounted((width, 45))
            async with app.run_test(size=(width, 45)):
                await asyncio.sleep(0.2)
                lines = _lines(board)
                seen = set()
                assert board._hit, "no chips were mapped at all"
                for row, spans in board._hit.items():
                    for start, end, index in spans:
                        label = board._items[index][2]
                        painted = lines[row][start:end]
                        # Anatomy, in cells: frame · marker · space · label …
                        # Asserted by POSITION, not by substring. "the label is
                        # somewhere in this slice" is satisfied by a span that
                        # is off by a cell or two, because a chip is padded on
                        # both sides — and off-by-a-cell is the entire bug class
                        # this test exists for.
                        assert len(painted) == end - start
                        assert painted[1] in "·▲✗", (
                            f"width {width}: span for item {index} does not "
                            f"start on a chip marker: {painted!r}")
                        assert painted[3:3 + len(label)] == label, (
                            f"width {width}: map puts item {index} "
                            f"({label!r}) at row {row} cols {start}-{end}, "
                            f"but the paint there is {painted!r}")
                        seen.add(index)
                assert seen == set(range(len(board._items))), (
                    "some chips are painted but unmapped, or vice versa")
    asyncio.run(run())


def test_chips_do_not_overlap_and_leave_real_gaps_between_them():
    """A too-generous span would swallow the gutter and make a miss register as
    a hit on the chip to its left."""
    async def run():
        _st, board, app = await _mounted((200, 45))
        async with app.run_test(size=(200, 45)):
            await asyncio.sleep(0.2)
            for row, spans in board._hit.items():
                ordered = sorted(spans)
                for (_s1, e1, _i1), (s2, _e2, _i2) in pairwise(ordered):
                    assert e1 <= s2, f"row {row}: spans overlap"
                    assert s2 - e1 == _CHIP_GAP, f"row {row}: gutter is not the gap"
                assert ordered[0][0] == _BOARD_INDENT
    asyncio.run(run())


def test_hit_test_returns_nothing_for_headers_gaps_and_the_left_margin():
    async def run():
        _st, board, app = await _mounted((200, 45))
        async with app.run_test(size=(200, 45)):
            await asyncio.sleep(0.2)
            chip_rows = set(board._hit)
            blank_rows = [i for i, line in enumerate(_lines(board))
                          if i not in chip_rows]
            assert blank_rows, "expected header/spacer rows"
            for row in blank_rows:
                assert board.hit_test(_BOARD_INDENT, row) is None
            row = min(chip_rows)
            assert board.hit_test(0, row) is None, "left margin is not a chip"
            first_end = min(board._hit[row])[1]
            assert board.hit_test(first_end, row) is None, "gutter is not a chip"
    asyncio.run(run())


# ─── Clicking ────────────────────────────────────────────────────────────────


async def _click_content(pilot, board, x: int, y: int) -> None:
    """Click content cell (x, y), translated through the same screen-space
    relationship `_mouse_to_cell` inverts."""
    region = board._content.region
    await pilot.click(board, offset=(region.x - board.region.x + x,
                                     region.y - board.region.y + y))
    await pilot.pause(0.1)


def test_clicking_a_chip_cycles_that_violation():
    async def run():
        st, board, app = await _mounted((160, 45))
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause(0.2)
            row = min(board._hit)
            start, _end, index = min(board._hit[row])
            kind = board._items[index][1]
            assert st.state_of(kind) == "unknown"
            await _click_content(pilot, board, start + 2, row)
            assert st.state_of(kind) == "marked"
    asyncio.run(run())


def test_clicking_the_second_column_hits_the_second_column():
    """The failure this exists for is an off-by-one-cell hit map, which is
    invisible in column one (every miss still lands on the only chip there) and
    obvious in column two — where it toggles the chip beside the pointer."""
    async def run():
        st, board, app = await _mounted((200, 45))
        async with app.run_test(size=(200, 45)) as pilot:
            await pilot.pause(0.2)
            row = next(r for r in sorted(board._hit) if len(board._hit[r]) > 1)
            start, end, index = sorted(board._hit[row])[1]
            kind = board._items[index][1]
            for x in (start, start + 3, end - 1):
                st.clear()
                await _click_content(pilot, board, x, row)
                assert st.get_flags() == {kind}, (
                    f"clicking cell {x} on row {row} flagged {st.get_flags()} "
                    f"instead of {kind.name}")
    asyncio.run(run())


def test_clicking_after_scrolling_hits_the_chip_under_the_pointer():
    """The scroll offset has to come out of the content widget's own screen
    region. Reading `event.x/y` and subtracting this container's gutter instead
    looks identical at scroll 0 and is wrong by exactly the scroll distance
    everywhere else — so an unscrolled test would pass while the board is
    unusable below the fold, which is most of it."""
    async def run():
        st, board, app = await _mounted((160, 24))
        async with app.run_test(size=(160, 24)) as pilot:
            await pilot.pause(0.2)
            board.focus()
            await pilot.pause(0.1)
            board.scroll_to(y=6, animate=False)
            await pilot.pause(0.3)
            assert board.scroll_offset.y > 0, "the board did not actually scroll"
            region = board._content.region
            visible = [r for r in sorted(board._hit)
                       if 0 <= region.y - board.region.y + r < board.region.height]
            assert visible, "no mapped row is on screen after scrolling"
            row = visible[len(visible) // 2]
            start, _end, index = min(board._hit[row])
            kind = board._items[index][1]
            await _click_content(pilot, board, start + 2, row)
            assert st.get_flags() == {kind}, (
                f"scrolled click flagged {st.get_flags()} not {kind.name}")
    asyncio.run(run())


def test_clicking_a_gutter_records_nothing():
    async def run():
        st, board, app = await _mounted((200, 45))
        async with app.run_test(size=(200, 45)) as pilot:
            await pilot.pause(0.2)
            row = next(r for r in sorted(board._hit) if len(board._hit[r]) > 1)
            first_end = min(board._hit[row])[1]
            await _click_content(pilot, board, first_end, row)
            assert st._states == {}, "a click between chips changed the record"
            header = min(r for r in range(len(_lines(board)))
                         if r not in board._hit)
            await _click_content(pilot, board, _BOARD_INDENT, header)
            assert st._states == {}, "a click on a header changed the record"
    asyncio.run(run())


def test_click_and_space_share_one_cycle():
    """Both routes go through `_toggle` → `EvidenceState.cycle`, so three
    clicks return a chip to unknown exactly as three presses of Space do. A
    mouse path that set "marked" directly would pass a one-click test and strand
    the player at marked forever."""
    async def run():
        st, board, app = await _mounted((160, 45))
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause(0.2)
            row = min(board._hit)
            start, _end, index = min(board._hit[row])
            kind = board._items[index][1]
            seen = []
            for _ in range(3):
                await _click_content(pilot, board, start + 2, row)
                seen.append(st.state_of(kind))
            assert seen == ["marked", "absent", "unknown"], seen
    asyncio.run(run())


def test_a_click_moves_the_keyboard_cursor_to_what_was_clicked():
    """Otherwise the two input methods fight: click chip 12, press Space, and
    chip 0 toggles."""
    async def run():
        st, board, app = await _mounted((160, 45))
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause(0.2)
            board.focus()
            await pilot.pause(0.1)
            row = sorted(board._hit)[4]
            start, _end, index = min(board._hit[row])
            kind = board._items[index][1]
            await _click_content(pilot, board, start + 2, row)
            assert board._cursor == index
            await pilot.press("space")
            await pilot.pause(0.1)
            assert st.state_of(kind) == "absent", (
                "Space after a click moved a different chip")
    asyncio.run(run())


def test_the_summary_board_ignores_clicks():
    """It is a read-only report of what was recorded elsewhere; a click on it
    must not become a way to record evidence from the Candidate page without
    ever opening a tool.

    Two independent latches, and both are checked, because the outer one alone
    hides whether the inner one works: the summary renderer builds no hit map,
    so a real click has nothing to land on no matter what `on_click` does. The
    second half of this test therefore FORCES a hit map onto a summary board
    and posts a click at it directly — the only way to observe the
    `if self._summary` early return, which is what keeps the widget safe if a
    later change ever gives the summary view chips of its own.
    """
    class _FakeClick:
        button = 1
        def __init__(self, x, y):
            self.screen_x, self.screen_y = x, y
        def stop(self):
            pass

    async def run():
        st, board, app = await _mounted((160, 45), summary=True)
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause(0.2)
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


# ─── Colour language and grading ─────────────────────────────────────────────


def test_a_marked_chip_is_filled_with_its_own_severity_colour():
    """Severity colour is the board's whole visual language (yellow minor,
    orange major, red critical) and predates the chip layout. State changes the
    surface, never the hue: a marked chip paints its severity as the FILL."""
    from gameengine.ui.tui.shared import _SEV_COLOR, _SEVERITY, _sev_color

    # Pick a live representative of each tier off the engine's own severity map
    # rather than naming kinds here — the tiers move (#51, #53 both re-tiered a
    # violation) and a hardcoded pair silently degrades into comparing one
    # colour with itself the day one of them is re-graded.
    reps: dict[str, DiscrepancyKind] = {}
    for _g, kind, _l in rules_content.VIOLATION_CATALOG:
        reps.setdefault(_SEVERITY.get(kind, "minor"), kind)
    assert set(reps) == set(_SEV_COLOR), f"no representative for every tier: {reps}"

    async def run():
        st = EvidenceState()
        _s, board, app = await _mounted((160, 45), state=st)
        async with app.run_test(size=(160, 45)):
            await asyncio.sleep(0.2)
            for severity, kind in reps.items():
                st.clear()
                st.cycle(kind)
                markup = board._render_text()
                assert f"on {_sev_color(kind)}]▲ " in markup, (
                    f"{severity} {kind.name} is not filled with "
                    f"{_sev_color(kind)}")
                for other, colour in _SEV_COLOR.items():
                    if other != severity:
                        assert f"on {colour}]▲ " not in markup, (
                            f"marking a {severity} violation lit a chip in the "
                            f"{other} colour")
    asyncio.run(run())


def test_grades_reach_the_chips_and_only_the_touched_ones():
    """The reveal contract survives the relayout: ✓/✗ on rows the player
    actually called, and nothing at all on the ones they left alone — a blank
    chip is how the answer key stays off the board."""
    async def run():
        st = EvidenceState()
        st.cycle(DiscrepancyKind.BREACH_HIT)                 # right
        st.cycle(DiscrepancyKind.HOSTILE_CHAT)               # wrong
        _s, board, app = await _mounted((160, 45), state=st)
        async with app.run_test(size=(160, 45)):
            await asyncio.sleep(0.2)
            before = _lines(board)
            assert "✓" not in "".join(before) and "✗" not in "".join(before)
            st.reveal({DiscrepancyKind.BREACH_HIT,
                       DiscrepancyKind.LEAKED_PASSWORD},
                      {k for _g, k, _l in rules_content.visible_catalog(None)})
            lines = _lines(board)
            hit = board._hit
            def row_of(kind):
                idx = next(i for i, (_g, k, _l) in enumerate(board._items)
                           if k == kind)
                for row, spans in hit.items():
                    for start, end, index in spans:
                        if index == idx:
                            return lines[row][start:end]
                raise AssertionError(f"{kind.name} was not painted")
            assert "✓" in row_of(DiscrepancyKind.BREACH_HIT)
            assert "✗" in row_of(DiscrepancyKind.HOSTILE_CHAT)
            untouched = row_of(DiscrepancyKind.LEAKED_PASSWORD)
            assert "✓" not in untouched and "✗" not in untouched, (
                "an untouched violation was graded — that is the answer key")
            assert "1 violation went unrecorded." in "\n".join(lines)
    asyncio.run(run())


# ─── In the real screen ──────────────────────────────────────────────────────


def test_every_board_fits_its_page_at_the_sizes_the_game_is_played_at():
    """The integration case. Each page gives the board a different percentage
    of the terminal (#evidence-gs 34%, #evidence-hc/lw 36%, #evidence-st 32%,
    #evidence-c0 50%), so the column count is settled per page, not once. A
    layout that only ever gets checked in isolation is exactly how the narrow
    Stegotool sidebar ends up clipping its right-hand column."""
    async def run():
        for size in ((120, 40), (160, 45), (220, 55)):
            day = load_day(1)
            state = GameState(seed=SEED)
            state.unlocked_tools = set(ALL_TOOLS)
            app = _Host()
            async with app.run_test(size=size) as pilot:
                await app.push_screen(IntakeScreen(day, state, "briefing"))
                await pilot.pause(0.4)
                scr = app.screen
                scr._toggle_evidence()
                await pilot.pause(0.2)
                for page, board in enumerate(
                        (scr.board_c0, scr.board_gs, scr.board_hc,
                         scr.board_lw, scr.board_st)):
                    scr._goto_page(page)
                    await pilot.pause(0.2)
                    room = board.content_size.width
                    assert room > 0, f"{size} page {page}: board never sized"
                    for i, line in enumerate(_lines(board)):
                        assert len(line) <= room, (
                            f"{size} page {page} line {i}: {len(line)} cells "
                            f"in {room}: {line!r}")
                    assert board._hit, f"{size} page {page}: nothing clickable"
    asyncio.run(run())


def test_resizing_the_terminal_repacks_the_grid():
    """`on_resize` is guarded on the measured width so a scrollbar appearing
    cannot start an oscillation — the guard has to still let a real resize
    through."""
    async def run():
        _st, board, app = await _mounted((70, 40))
        async with app.run_test(size=(70, 40)) as pilot:
            await pilot.pause(0.3)
            before = max(len(v) for v in board._hit.values())
            before_w = board._last_width
            await pilot.resize_terminal(220, 40)
            await pilot.pause(0.4)
            after = max(len(v) for v in board._hit.values())
            assert board._last_width > before_w, "the board never saw the resize"
            assert after > before, (
                f"grid did not repack on resize: {before} -> {after} columns")
    asyncio.run(run())
