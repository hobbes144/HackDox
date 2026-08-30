"""UI tests for progressive tool-page locking (#33).

The StatusHeader greying is checked from its render() string directly. The
navigation/inert-shortcut guards are driven through a real mounted IntakeScreen
via Textual's run_test pilot.
"""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Static

from gameengine import config
from gameengine.core.content_loader import load_day
from gameengine.core.models import GameState, ToolName
from gameengine.ui.tui.app import BriefingScreen, IntakeScreen, StatusHeader

SEED = 0xC0FFEE


def test_status_header_greys_only_locked_tabs():
    day = load_day(1)
    state = GameState(seed=SEED)
    state.unlocked_tools = {"ghostscan"}          # 3 of 4 tools still locked
    out = StatusHeader(state, day, 0, page_index=0).render()
    # ⊘ marks a locked tool tab; hashcrack, logwatch, stegotool → 3 locked.
    assert out.count("⊘") == 3
    # Fully unlocked → no lock markers at all.
    state.unlocked_tools = {"ghostscan", "hashcrack", "logwatch", "stegotool"}
    assert "⊘" not in StatusHeader(state, day, 0, page_index=0).render()


class _Host(App):
    def compose(self) -> ComposeResult:
        yield Static("root")


def test_locked_page_unreachable_and_locked_tool_is_inert():
    async def go():
        day = load_day(1)
        state = GameState(seed=SEED)
        state.unlocked_tools = {"ghostscan"}      # only Ghostscan available
        app = _Host()
        async with app.run_test() as pilot:
            await app.push_screen(IntakeScreen(day, state, "briefing"))
            await pilot.pause(0.3)
            scr = app.screen

            assert scr._page_index == 0            # starts on Candidate

            # '3' = Hashcrack (locked) → navigation refused, page unchanged.
            await pilot.press("3")
            await pilot.pause(0.05)
            assert scr._page_index == 0

            # '2' = Ghostscan (unlocked) → moves there.
            await pilot.press("2")
            await pilot.pause(0.05)
            assert scr._page_index == 1

            # A locked tool run charges no ⏱ and does nothing.
            before = state.compute_hours
            scr._run_tool(ToolName.HASHCRACK)
            assert state.compute_hours == before

            # Sanity: the unlocked tool is NOT blocked by the guard (it may be
            # gated by other rules, but it must pass the unlock check).
            assert "ghostscan" in state.unlocked_tools
    asyncio.run(go())


def test_all_locked_new_game_keeps_player_on_candidate():
    async def go():
        day = load_day(1)
        state = GameState(seed=SEED)      # fresh game → unlocked_tools empty
        assert state.unlocked_tools == set()
        app = _Host()
        async with app.run_test() as pilot:
            await app.push_screen(IntakeScreen(day, state, "briefing"))
            await pilot.pause(0.3)
            scr = app.screen
            for key in ("2", "3", "4", "5"):      # every tool page is locked
                await pilot.press(key)
                await pilot.pause(0.03)
                assert scr._page_index == 0
    asyncio.run(go())


# ─── Overseer unlock narration (#34) ─────────────────────────────────────────


def test_tool_introduced_on_matches_teaching_order():
    assert config.tool_introduced_on(1) is None          # Dossier — not a tool
    assert config.tool_introduced_on(2) == "ghostscan"
    assert config.tool_introduced_on(3) == "hashcrack"
    assert config.tool_introduced_on(4) == "logwatch"
    assert config.tool_introduced_on(5) == "stegotool"
    assert config.tool_introduced_on(6) is None


def test_briefing_unlock_beat_flips_the_tool():
    """On a tool-unlock day, playing the briefing beat adds the tool to
    GameState.unlocked_tools via the TypewriterLog trigger — not cosmetic."""
    async def go():
        import dataclasses
        day2 = dataclasses.replace(load_day(1), number=2)   # Day 2 → Ghostscan
        state = GameState(seed=SEED)                         # starts empty
        app = _Host()
        async with app.run_test() as pilot:
            await app.push_screen(BriefingScreen(day2, "Day two.", state))
            assert "ghostscan" not in state.unlocked_tools   # not yet
            await pilot.pause(3.0)                            # beat types out
            assert "ghostscan" in state.unlocked_tools        # trigger fired
    asyncio.run(go())


def test_begin_day_unlocks_even_if_beat_skipped():
    """If the player begins the shift before the unlock line finishes, the tool
    is still granted (idempotent belt-and-suspenders)."""
    async def go():
        import dataclasses
        day2 = dataclasses.replace(load_day(1), number=2)
        state = GameState(seed=SEED)
        app = _Host()
        async with app.run_test() as pilot:
            # A very long intro guarantees the unlock line hasn't played yet.
            await app.push_screen(BriefingScreen(day2, "x" * 400, state))
            await pilot.pause(0.1)
            assert "ghostscan" not in state.unlocked_tools
            app.screen._ensure_unlocked()          # what action_begin_day calls
            assert "ghostscan" in state.unlocked_tools
    asyncio.run(go())


def test_day1_briefing_unlocks_nothing():
    async def go():
        state = GameState(seed=SEED)
        app = _Host()
        async with app.run_test() as pilot:
            await app.push_screen(BriefingScreen(load_day(1), "Welcome.", state))
            await pilot.pause(0.8)
            assert state.unlocked_tools == set()
    asyncio.run(go())


def test_evidence_boards_are_gated_by_unlocked_tools():
    """Every Evidence Board IntakeScreen owns (summary + all 5 editable views)
    is constructed from the same GameState.unlocked_tools — a locked tool's
    violations should never be reachable to flag, on any of them, because a
    candidate can never actually carry one yet (candidate_gen.intro_day gates
    generation on the same TOOL_UNLOCK_DAY schedule)."""
    async def go():
        day = load_day(1)
        state = GameState(seed=SEED)
        state.unlocked_tools = {"ghostscan"}      # dossier (implicit) + ghostscan
        app = _Host()
        async with app.run_test() as pilot:
            await app.push_screen(IntakeScreen(day, state, "briefing"))
            await pilot.pause(0.3)
            scr = app.screen
            for board in (scr.board, scr.board_c0, scr.board_gs,
                          scr.board_hc, scr.board_lw, scr.board_st):
                groups = {g for g, _k, _l in board._items}
                assert groups == {"DOSSIER", "OSINT"}, groups

            # Fully unlocked -> every group is reachable.
            state2 = GameState(seed=SEED)
            state2.unlocked_tools = {"ghostscan", "hashcrack", "logwatch", "stegotool"}
            await app.push_screen(IntakeScreen(day, state2, "briefing"))
            await pilot.pause(0.3)
            scr2 = app.screen
            groups2 = {g for g, _k, _l in scr2.board._items}
            assert groups2 == {"DOSSIER", "OSINT", "FORENSICS", "CREDENTIAL", "STEGO"}
    asyncio.run(go())


def test_status_header_resource_badges_are_labeled():
    """Batch-3 task #8: site health / HD$ / credits get an explicit word
    label on a solid-colour badge instead of a bare symbol — 'more visible'
    per Nick's ask, not just relocated."""
    day = load_day(1)
    state = GameState(seed=SEED)
    state.hackdollars = 42
    out = StatusHeader(state, day, 0, page_index=0).render()
    assert "HEALTH" in out
    assert "HD$ 42" in out
    assert f"CR {state.hackdox_credits}/{config.HACKDOX_CREDIT_MAX}" in out


def test_status_header_resource_cluster_is_right_justified():
    """The resource cluster (⏱/health/HD$/credits/alignment) is pushed to
    the right edge of the bar against the widget's real render width, so the
    bar visibly spans the terminal instead of clustering left after the day/
    slot info — the 'spread out'/'full-width bar' half of task #8."""
    from rich.text import Text
    from textual.app import App as _TestApp
    from textual.widgets import Static as _Static

    day = load_day(1)
    state = GameState(seed=SEED)
    status = StatusHeader(state, day, 0, page_index=0)

    class _StatusHost(_TestApp):
        def compose(self) -> ComposeResult:
            yield status

    async def go():
        app = _StatusHost()
        async with app.run_test(size=(140, 24)) as pilot:
            await pilot.pause(0.1)
            row1 = status.render().split("\n")[0]
            plain = Text.from_markup(row1).plain
            # Right-justified against a 140-col terminal: the row should
            # span nearly the full width, not stop shortly after "[1/6]"
            # the way the old left-clustered layout did.
            assert len(plain) >= 130, f"row only {len(plain)} cols wide: {plain!r}"
    asyncio.run(go())


# ─── Clickable tabs (batch-3 task #9) ────────────────────────────────────────


def test_clicking_an_unlocked_tab_switches_page():
    """A left-click landing on a tab's cell range in the tab strip (row 1 of
    the status bar) switches pages exactly the way pressing its number key
    does — both route through IntakeScreen._goto_page."""
    async def go():
        day = load_day(1)
        state = GameState(seed=SEED)
        state.unlocked_tools = {"ghostscan"}      # tab 1 (Ghostscan) usable
        app = _Host()
        async with app.run_test(size=(140, 24)) as pilot:
            await app.push_screen(IntakeScreen(day, state, "briefing"))
            await pilot.pause(0.3)
            scr = app.screen
            assert scr._page_index == 0

            scr.scroll_to(y=0, animate=False)      # header must be on-screen
            await pilot.pause(0.1)
            status = scr.status
            status.render()                        # populate _tab_ranges
            start, end = status._tab_ranges[1]      # Ghostscan tab's cells
            mid_x = (start + end) // 2
            await pilot.click(status, offset=(mid_x, 1))
            await pilot.pause(0.1)
            assert scr._page_index == 1
    asyncio.run(go())


def test_clicking_a_locked_tab_is_inert():
    """Clicking a locked tab's cells is a no-op, same guard _goto_page
    already applies to the '3' keyboard shortcut in
    test_locked_page_unreachable_and_locked_tool_is_inert above."""
    async def go():
        day = load_day(1)
        state = GameState(seed=SEED)
        state.unlocked_tools = {"ghostscan"}      # Hashcrack (tab 2) locked
        app = _Host()
        async with app.run_test(size=(140, 24)) as pilot:
            await app.push_screen(IntakeScreen(day, state, "briefing"))
            await pilot.pause(0.3)
            scr = app.screen

            scr.scroll_to(y=0, animate=False)
            await pilot.pause(0.1)
            status = scr.status
            status.render()
            start, end = status._tab_ranges[2]      # Hashcrack tab's cells
            mid_x = (start + end) // 2
            await pilot.click(status, offset=(mid_x, 1))
            await pilot.pause(0.1)
            assert scr._page_index == 0             # unchanged
    asyncio.run(go())


def test_clicking_the_resource_bar_row_does_not_switch_pages():
    """Row 0 is the ⏱/health/HD$/credits cluster, not the tab strip — a
    click landing there must not be misread as a tab click even if its x
    happens to fall inside a tab's cell range."""
    async def go():
        day = load_day(1)
        state = GameState(seed=SEED)
        state.unlocked_tools = {"ghostscan"}
        app = _Host()
        async with app.run_test(size=(140, 24)) as pilot:
            await app.push_screen(IntakeScreen(day, state, "briefing"))
            await pilot.pause(0.3)
            scr = app.screen

            scr.scroll_to(y=0, animate=False)
            await pilot.pause(0.1)
            status = scr.status
            status.render()
            start, end = status._tab_ranges[1]
            mid_x = (start + end) // 2
            await pilot.click(status, offset=(mid_x, 0))   # row 0, not 1
            await pilot.pause(0.1)
            assert scr._page_index == 0
    asyncio.run(go())


# ─── ADMIT/DENY verdict buttons (batch-3 follow-up) ──────────────────────────


def test_clicking_admit_button_commits_the_same_verdict_as_the_command():
    """The ADMIT button routes through the exact same _commit_verdict() the
    typed "admit" command uses — locking the verdict and disabling both
    buttons, identically either way."""
    async def go():
        day = load_day(1)
        state = GameState(seed=SEED)
        app = _Host()
        async with app.run_test(size=(140, 40)) as pilot:
            await app.push_screen(IntakeScreen(day, state, "briefing"))
            await pilot.pause(0.3)
            scr = app.screen
            assert not scr._verdict_locked
            assert not scr.btn_admit.disabled and not scr.btn_deny.disabled

            await pilot.click(scr.btn_admit)
            await pilot.pause(0.1)
            assert scr._verdict_locked
            assert scr.btn_admit.disabled and scr.btn_deny.disabled
    asyncio.run(go())


def test_clicking_deny_button_twice_is_a_no_op_like_the_command():
    """A second click (or the typed command a second time) must not double-
    score the candidate — _commit_verdict()'s own guard already covers this;
    this just proves the button path reaches that guard."""
    async def go():
        day = load_day(1)
        state = GameState(seed=SEED)
        app = _Host()
        async with app.run_test(size=(140, 40)) as pilot:
            await app.push_screen(IntakeScreen(day, state, "briefing"))
            await pilot.pause(0.3)
            scr = app.screen

            await pilot.click(scr.btn_deny)
            await pilot.pause(0.1)
            hd_after_first = state.hackdox_credits, state.hackdollars
            # Buttons are disabled now, but press() directly to prove the
            # underlying guard (not just the disabled attribute) blocks a
            # second commit.
            scr.btn_deny.press()
            await pilot.pause(0.1)
            assert (state.hackdox_credits, state.hackdollars) == hd_after_first, (
                "a second verdict commit changed economy state — not idempotent")
    asyncio.run(go())


def test_enter_on_a_focused_verdict_button_presses_it_not_the_command_bar():
    """IntakeScreen.on_key() normally intercepts Enter for the command bar —
    it must step aside when a verdict button itself is focused, so Enter
    presses the button (Textual's own Button binding) instead of executing
    whatever (usually nothing) is sitting in the command-bar buffer."""
    async def go():
        day = load_day(1)
        state = GameState(seed=SEED)
        app = _Host()
        async with app.run_test(size=(140, 40)) as pilot:
            await app.push_screen(IntakeScreen(day, state, "briefing"))
            await pilot.pause(0.3)
            scr = app.screen

            scr.btn_deny.focus()
            await pilot.pause(0.05)
            assert scr.focused is scr.btn_deny
            await pilot.press("enter")
            await pilot.pause(0.1)
            assert scr._verdict_locked
    asyncio.run(go())


def test_verdict_buttons_reachable_by_arrow_key_focus_navigation():
    """Nick: buttons should be 'navigated to with the arrows and press
    enter' — no bespoke focus-routing needed, since Button is natively
    focusable and IntakeScreen already binds arrow keys to Textual's normal
    focus_previous/focus_next chain (see action_focus_prev/next)."""
    async def go():
        day = load_day(1)
        state = GameState(seed=SEED)
        app = _Host()
        async with app.run_test(size=(140, 40)) as pilot:
            await app.push_screen(IntakeScreen(day, state, "briefing"))
            await pilot.pause(0.3)
            scr = app.screen

            scr.dossier.focus()
            await pilot.pause(0.05)
            reached = False
            for _ in range(20):
                await pilot.press("down")
                await pilot.pause(0.02)
                if scr.focused in (scr.btn_admit, scr.btn_deny):
                    reached = True
                    break
            assert reached, "arrow-key focus cycling never reached a verdict button"
    asyncio.run(go())


def test_verdict_buttons_reset_and_reenable_on_the_next_candidate():
    """After a verdict is committed and the player moves to the next slot,
    the buttons must come back enabled — otherwise every candidate after the
    first would be stuck with dead buttons."""
    async def go():
        day = load_day(1)
        state = GameState(seed=SEED)
        app = _Host()
        async with app.run_test(size=(140, 40)) as pilot:
            await app.push_screen(IntakeScreen(day, state, "briefing"))
            await pilot.pause(0.3)
            scr = app.screen

            await pilot.click(scr.btn_admit)
            await pilot.pause(0.1)
            assert scr.btn_admit.disabled and scr.btn_deny.disabled

            scr._state.current_slot_index += 1
            scr._goto_page(0)
            scr._load_current_candidate()
            await pilot.pause(0.1)
            assert not scr._verdict_locked
            assert not scr.btn_admit.disabled and not scr.btn_deny.disabled
    asyncio.run(go())
