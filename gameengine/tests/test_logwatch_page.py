"""Logwatch page (2026-09-19 overhaul) — Textual pilot tests.

Report in the centre column, auth log sealed on the right until L, [ / ] jump
between the target's rows, filter tags both, board toggle hides the log panel.
"""

from __future__ import annotations

import asyncio

from rich.text import Text
from textual.app import App

from gameengine import config
from gameengine.core.content_loader import load_day
from gameengine.core.models import GameState
from gameengine.ui.tui.screens.intake import IntakeScreen

ALL_TOOLS = {"ghostscan", "hashcrack", "logwatch", "stegotool"}


class _Host(App):
    CSS_PATH = config.ROOT_DIR / "ui" / "tui" / "app.tcss"


def _static_plain(static) -> str:
    return Text.from_markup(str(static.content)).plain


async def _intake(pilot, app, *, upgrades=()):
    day = load_day(4)
    state = GameState(seed=3, current_day=4, compute_hours=500)
    state.unlocked_tools = set(ALL_TOOLS)
    state.upgrades = set(upgrades)
    await app.push_screen(IntakeScreen(day, state, "briefing"))
    await pilot.pause(0.4)
    scr = app.screen
    scr._goto_page(3)
    await pilot.pause(0.2)
    return scr


def _report_text(scr) -> str:
    return "\n".join(_static_plain(s) for s in scr.term_lw.query("Static"))


def _log_text(scr) -> str:
    return _static_plain(scr.log_lw._content)


def test_logwatch_page_starts_with_report_and_sealed_log():
    async def run():
        app = _Host()
        async with app.run_test(size=(170, 48)) as pilot:
            scr = await _intake(pilot, app)
            assert scr.log_lw.state == scr.log_lw.SEALED
            assert "AUTH LOG — SEALED" in _log_text(scr)
            rep = _report_text(scr)
            assert "ACTIVITY PROFILE" in rep and "ACTIVITY TIMELINE" in rep
            assert "auth log sealed" in rep
            # jump keys are inert (and say so) while sealed
            await pilot.press("right_square_bracket")
            assert scr.log_lw.cursor == -1
    asyncio.run(run())


def test_base_run_unseals_the_log_and_jump_keys_walk_target_rows():
    async def run():
        app = _Host()
        async with app.run_test(size=(170, 48)) as pilot:
            scr = await _intake(pilot, app)
            before = scr._state.compute_hours
            scr._execute_command("analyze")
            await pilot.pause(0.3)
            assert scr._state.compute_hours < before
            assert scr.log_lw.state == scr.log_lw.OPEN
            assert "auth log open" in _report_text(scr)
            rows = scr.log_lw.target_rows
            assert rows, "no target rows collected"
            assert scr.log_lw.cursor == 0
            await pilot.press("right_square_bracket")
            assert scr.log_lw.cursor == (1 % len(rows))
            await pilot.press("left_square_bracket")
            assert scr.log_lw.cursor == 0
            # the target rows really are this candidate's account
            lines = _log_text(scr).split("\n")
            assert scr._candidate.email in lines[rows[0]]
            assert "▲" not in _log_text(scr), "base run must not label anything"
    asyncio.run(run())


def test_filter_tags_the_log_and_adds_the_confirmed_block():
    async def run():
        app = _Host()
        async with app.run_test(size=(170, 48)) as pilot:
            scr = await _intake(pilot, app)
            scr._execute_command("filter")
            await pilot.pause(0.3)
            assert scr.log_lw.state == scr.log_lw.FILTERED
            assert "FILTER — CONFIRMED" in _report_text(scr)
    asyncio.run(run())


def test_evidence_board_hides_the_log_panel_and_keeps_the_report():
    async def run():
        app = _Host()
        async with app.run_test(size=(170, 48)) as pilot:
            scr = await _intake(pilot, app)
            scr._toggle_evidence()
            await pilot.pause(0.3)
            assert not scr.log_lw.display
            assert scr.term_lw.display
            scr._toggle_evidence()
            await pilot.pause(0.3)
            assert scr.log_lw.display
    asyncio.run(run())


def test_log_rows_do_not_wrap():
    """One log row = one screen line, or [ / ] would land on the wrong row."""
    async def run():
        app = _Host()
        async with app.run_test(size=(130, 40)) as pilot:
            scr = await _intake(pilot, app)
            scr._execute_command("analyze")
            await pilot.pause(0.3)
            content = scr.log_lw._content
            n_lines = len(_log_text(scr).split("\n"))
            assert content.size.height == n_lines, (
                f"log content is {content.size.height} rows tall for {n_lines} "
                f"lines — rows are wrapping")
    asyncio.run(run())


def test_next_candidate_reseals_the_log():
    async def run():
        app = _Host()
        async with app.run_test(size=(170, 48)) as pilot:
            scr = await _intake(pilot, app)
            scr._execute_command("analyze")
            await pilot.pause(0.3)
            assert scr.log_lw.state == scr.log_lw.OPEN
            scr._load_current_candidate()
            await pilot.pause(0.3)
            assert scr.log_lw.state == scr.log_lw.SEALED
    asyncio.run(run())


def test_report_does_not_wrap_at_common_widths():
    """The report picks its compact layout on narrow terminals, so its body
    never wraps (a wrapped bar or timeline row is unreadable)."""
    async def run():
        for size in ((120, 40), (170, 48)):
            app = _Host()
            async with app.run_test(size=size) as pilot:
                scr = await _intake(pilot, app)
                await pilot.pause(0.2)
                static = scr.term_lw.query("Static").first()
                lines = _static_plain(static).split("\n")
                assert static.size.height == len(lines), (
                    f"{size}: report is {static.size.height} rows for "
                    f"{len(lines)} lines — body lines are wrapping")
    asyncio.run(run())
