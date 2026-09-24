"""Tests for the ambient glitch panel that flanks IntroScreen/SettingsScreen/
CreditsScreen (ui/tui/widgets/menu_glitch.py).

`blend_frames`/`row_switch_points` are pure functions (no widget, no app),
the same reasoning as `build_frame` in glitch.py being pure — see that
module's tests. The widget itself (`AmbientGlitchPanel`) is exercised
through a real Textual `run_test()` app, which is also the regression test
for the crash this widget went through during development: an instance
attribute named `_size` silently shadowed `Widget._size` (Textual's own
private layout-bookkeeping attribute) and corrupted it, reproducibly, a few
frames after mount. The widget-level test below is what would catch that
again if it ever came back under a different name.
"""

from __future__ import annotations

import asyncio
import random

from textual.app import App, ComposeResult

from gameengine import config
from gameengine.ui.tui.widgets.menu_glitch import (
    AmbientGlitchPanel,
    blend_frames,
    row_switch_points,
)


# ── Pure functions ──────────────────────────────────────────────────────────

def test_blend_frames_uses_old_row_before_its_switch_point():
    old = ["A", "B", "C", "D"]
    new = ["a", "b", "c", "d"]
    switch_at = [0.0, 0.25, 0.5, 0.75]

    assert blend_frames(old, new, 0.0, switch_at) == ["a", "B", "C", "D"]
    assert blend_frames(old, new, 0.25, switch_at) == ["a", "b", "C", "D"]
    assert blend_frames(old, new, 0.5, switch_at) == ["a", "b", "c", "D"]
    assert blend_frames(old, new, 0.75, switch_at) == ["a", "b", "c", "d"]


def test_blend_frames_at_progress_one_is_entirely_the_new_frame():
    old = ["A", "B", "C"]
    new = ["a", "b", "c"]
    switch_at = row_switch_points(3, jitter=0.3, rng=random.Random(1))
    assert blend_frames(old, new, 1.0, switch_at) == new


def test_blend_frames_at_progress_zero_is_entirely_the_old_frame():
    # Zero jitter here: with jitter, a row's switch point can clamp down to
    # 0.0 (row 0 nominally starts at 0.0 already), which would legitimately
    # switch that one row at progress==0.0 — not what this test is checking.
    old = ["A", "B", "C"]
    new = ["a", "b", "c"]
    switch_at = row_switch_points(3, jitter=0.0, rng=random.Random(1))
    assert blend_frames(old, new, 0.0, switch_at) == ["a", "B", "C"]
    assert blend_frames(old, new, -0.01, switch_at) == old


def test_row_switch_points_are_clamped_into_zero_one():
    rng = random.Random(7)
    points = row_switch_points(20, jitter=0.5, rng=rng)
    assert len(points) == 20
    assert all(0.0 <= p <= 1.0 for p in points)


def test_row_switch_points_sweeps_top_to_bottom_on_average():
    # No jitter -> exactly i / height, a clean top-to-bottom sweep.
    points = row_switch_points(4, jitter=0.0, rng=random.Random(0))
    assert points == [0.0, 0.25, 0.5, 0.75]


def test_row_switch_points_empty_for_zero_height():
    assert row_switch_points(0, jitter=0.2, rng=random.Random(0)) == []


# ── Widget-level: the crash regression ──────────────────────────────────────
# This is the AmbientGlitchPanel equivalent of the transition tests' "runs
# for a while without dying" checks — see test_transitions.py's own note on
# why the widget itself, not just the pure frame math, needs covering.

class _HostApp(App):
    def compose(self) -> ComposeResult:
        yield AmbientGlitchPanel(seed=1, id="panel")


def test_panel_survives_many_ticks_without_crashing_layout():
    """Regression test for the `self._size` / `Widget._size` name collision:
    ran reliably to a `Screen._refresh_layout` crash a few ticks after
    mount, on every terminal size tried, until the attribute was renamed."""

    async def run() -> None:
        app = _HostApp()
        async with app.run_test(size=(80, 24)) as pilot:
            panel = app.query_one("#panel", AmbientGlitchPanel)
            for _ in range(20):
                await pilot.pause(0.02)
            assert panel._panel_size != (0, 0)

    asyncio.run(run())


def test_panel_cycles_through_hold_and_morph_states():
    """With a short enough hold/morph duration, both states should actually
    be observed within a short run — otherwise the state machine never
    advances and the panel would just be a single still frame forever."""
    old_hold = config.AMBIENT_GLITCH_HOLD_DURATION
    old_morph = config.AMBIENT_GLITCH_MORPH_DURATION
    old_interval = config.AMBIENT_GLITCH_FRAME_INTERVAL
    config.AMBIENT_GLITCH_HOLD_DURATION = 0.1
    config.AMBIENT_GLITCH_MORPH_DURATION = 0.15
    config.AMBIENT_GLITCH_FRAME_INTERVAL = 0.02

    async def run() -> None:
        app = _HostApp()
        async with app.run_test(size=(80, 24)) as pilot:
            panel = app.query_one("#panel", AmbientGlitchPanel)
            states = set()
            for _ in range(40):
                await pilot.pause(0.02)
                states.add(panel._state)
            assert states == {"hold", "morph"}

    try:
        asyncio.run(run())
    finally:
        config.AMBIENT_GLITCH_HOLD_DURATION = old_hold
        config.AMBIENT_GLITCH_MORPH_DURATION = old_morph
        config.AMBIENT_GLITCH_FRAME_INTERVAL = old_interval


def test_panel_disabled_never_ticks_or_paints():
    old_enabled = config.AMBIENT_GLITCH_ENABLED
    config.AMBIENT_GLITCH_ENABLED = False

    async def run() -> None:
        app = _HostApp()
        async with app.run_test(size=(80, 24)) as pilot:
            panel = app.query_one("#panel", AmbientGlitchPanel)
            assert panel._timer is None
            for _ in range(10):
                await pilot.pause(0.02)
            assert panel._timer is None

    try:
        asyncio.run(run())
    finally:
        config.AMBIENT_GLITCH_ENABLED = old_enabled
