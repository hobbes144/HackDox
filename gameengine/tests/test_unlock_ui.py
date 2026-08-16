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
