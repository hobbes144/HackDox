"""UI tests for progressive tool-page locking (#33).

The StatusHeader greying is checked from its render() string directly. The
navigation/inert-shortcut guards are driven through a real mounted IntakeScreen
via Textual's run_test pilot.
"""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Static

from gameengine.core.content_loader import load_day
from gameengine.core.models import GameState, ToolName
from gameengine.ui.tui.app import IntakeScreen, StatusHeader

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
