"""Main-menu Continue buttons and save-slot lifecycle (2026-09-25).

Nick: the Continue buttons render only when there is a save that can actually
be continued — not merely when a file exists — and a finished run stops being
offered. Plus the campaign Game Over screen's glitch frame.
"""

from __future__ import annotations

import asyncio

import pytest

from gameengine import config
from gameengine.core import endless, persistence
from gameengine.core.models import GameState, ShiftRecord


@pytest.fixture
def slots(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SAVE_FILE", tmp_path / "slot_0.json")
    monkeypatch.setattr(config, "ENDLESS_SAVE_FILE", tmp_path / "endless_0.json")
    monkeypatch.setattr(config, "ENDLESS_RECORDS_FILE", tmp_path / "rec.json")
    return tmp_path


def _lost_endless() -> GameState:
    st = endless.new_endless_state(seed=3)
    for i in range(1, 6):
        st.shift_history.append(ShiftRecord(i, 1, 10))
    return st


@pytest.mark.parametrize("make, why", [
    (lambda: GameState(seed=1, current_day=4, site_health=10.0), "health under the loss line"),
    (lambda: GameState(seed=1, current_day=config.CAMPAIGN_LAST_DAY + 1), "campaign already complete"),
])
def test_dead_campaign_saves_are_not_continuable(slots, make, why):
    persistence.save(make())
    assert config.SAVE_FILE.exists()
    assert persistence.continuable("campaign") is None, why
    assert persistence.describe("campaign") is None


def test_dead_endless_save_is_not_continuable(slots):
    persistence.save(_lost_endless())
    assert persistence.continuable("endless") is None


def test_damaged_save_is_not_continuable(slots):
    config.SAVE_FILE.write_text("{ not json", encoding="utf-8")
    assert persistence.continuable("campaign") is None


def test_a_live_save_is_continuable(slots):
    persistence.save(GameState(seed=1, current_day=6, site_health=69.5))
    st = persistence.continuable("campaign")
    assert st is not None and st.current_day == 6


def _pilot(fn, size=(120, 40)):
    from gameengine.ui.tui.app import HackDoxApp

    async def go():
        original = config.TRANSITION_ENABLED
        config.TRANSITION_ENABLED = False
        try:
            app = HackDoxApp()
            async with app.run_test(size=size) as pilot:
                await pilot.pause()
                await fn(app, pilot)
        finally:
            config.TRANSITION_ENABLED = original

    asyncio.run(go())


def _shown(app) -> set[str]:
    from textual.widgets import Button
    return {b.id for b in app.screen.query(Button) if b.display}


@pytest.mark.parametrize("setup, expect", [
    ("none", set()),
    ("dead", set()),
    ("campaign", {"menu-continue"}),
    ("endless", {"menu-continue-endless"}),
    ("both", {"menu-continue", "menu-continue-endless"}),
])
def test_menu_shows_continue_only_for_continuable_saves(slots, setup, expect):
    if setup == "dead":
        persistence.save(GameState(seed=1, current_day=4, site_health=5.0))
        persistence.save(_lost_endless())
    if setup in ("campaign", "both"):
        persistence.save(GameState(seed=1, current_day=6))
    if setup in ("endless", "both"):
        persistence.save(endless.new_endless_state(seed=2))

    async def check(app, pilot):
        shown = _shown(app) & {"menu-continue", "menu-continue-endless"}
        assert shown == expect
        # The keyboard shortcuts must not reach a hidden button's run either.
        before = type(app.screen).__name__
        if "menu-continue" not in expect:
            await pilot.press("c")
            await pilot.pause()
            assert type(app.screen).__name__ == before
        if "menu-continue-endless" not in expect:
            await pilot.press("x")
            await pilot.pause()
            assert type(app.screen).__name__ == before

    _pilot(check)


def test_campaign_game_over_clears_its_slot_only(slots):
    from gameengine.ui.tui.screens.game_over import GameOverScreen
    persistence.save(endless.new_endless_state(seed=4))

    async def play(app, pilot):
        app.start_new_game()
        await pilot.pause()
        persistence.save(app._state)
        assert config.SAVE_FILE.exists()
        app.game_over()
        await pilot.pause()
        assert isinstance(app.screen, GameOverScreen)
        assert not config.SAVE_FILE.exists()
        assert config.ENDLESS_SAVE_FILE.exists(), "the Endless run must survive"

    _pilot(play)


def test_game_over_has_the_glitch_frame_on_all_four_sides(slots):
    from gameengine.ui.tui.screens.game_over import GameOverScreen
    from gameengine.ui.tui.widgets import AmbientGlitchPanel

    async def check(app, pilot):
        app.game_over()
        await pilot.pause()
        assert isinstance(app.screen, GameOverScreen)
        panels = list(app.screen.query(AmbientGlitchPanel))
        horiz = [p for p in panels if p.has_class("menu-flank-h")]
        vert = [p for p in panels if p.has_class("menu-flank")]
        assert len(horiz) == 2 and len(vert) == 2
        w, h = app.size
        top, bottom = sorted(horiz, key=lambda p: p.region.y)
        assert top.region.y == 0 and bottom.region.bottom == h
        assert all(p.region.width == w for p in horiz)
        left, right = sorted(vert, key=lambda p: p.region.x)
        assert left.region.x == 0 and right.region.right == w
        assert all(p.region.height > 0 for p in vert)

    _pilot(check)
