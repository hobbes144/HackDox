"""Tests for the glitch screen transitions.

Every full-screen change (intro → briefing → shift → end of day → between-day
→ next briefing, plus game over / campaign end) is covered by an animated CRT
signal-loss effect, and the screen swap itself happens hidden inside it. The
tests below are organised around the three things that would quietly ruin it:

  * **Coverage.** Partial coverage is what makes the effect read as a glitch
    over the real page rather than a cut to noise — but at the peak, coverage
    has to be TOTAL, because that is the frame the screen swap happens on. If
    show-through survived the peak, the player would see the pages change.
  * **Input.** The window is a deliberate freeze. A key pressed during it must
    die there — not queue up and land on the page that arrives next — with
    quit as the single deliberate exception, so an animation can never trap
    the player.
  * **Teardown and stack hygiene.** The two halves push and pop four screens
    between them. A leaked frame timer or an unbalanced stack would survive
    the transition and corrupt everything after it.

`build_frame` is a pure function of (width, height, intensity, rng), which is
what lets the look be tested without a running app; the widget tests pin
`intensity` and repaint by hand rather than racing the real envelope.
"""

from __future__ import annotations

import ast
import asyncio
import random
from pathlib import Path

from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import Static

from gameengine import config
from gameengine.core.audio import SFX_REGISTRY
from gameengine.ui.tui import app as app_module
from gameengine.ui.tui.app import HackDoxApp
from gameengine.ui.tui.glitch import (
    PHASE_IN,
    PHASE_OUT,
    GlitchEnvelope,
    build_frame,
    coverage_for,
)
from gameengine.ui.tui.screens.briefing import BriefingScreen
from gameengine.ui.tui.screens.intro import IntroScreen
from gameengine.ui.tui.screens.transition import TransitionScreen

SEED = 0xC0FFEE
MARKER = "MARKER"
SIZE = (80, 24)


class _MarkerScreen(Screen):
    """Dense, uniform page underneath — every row carries the marker, so
    "did the page show through" is a count rather than a guess about where
    the text happened to be."""

    BINDINGS = [("a", "mark", "mark")]

    def __init__(self) -> None:
        super().__init__()
        self.pressed = 0

    def compose(self) -> ComposeResult:
        for _ in range(SIZE[1]):
            yield Static(MARKER * (SIZE[0] // len(MARKER)))

    def action_mark(self) -> None:
        self.pressed += 1


class _Host(App):
    """Bare host app with the real stylesheet — the glitch needs `.off` and
    `TransitionScreen.solid` to mean anything. CSS_PATH is resolved from
    config.ROOT_DIR rather than written relative, because Textual resolves a
    relative CSS_PATH against the module that declares the class and this
    module lives one directory deeper than app.py."""

    CSS_PATH = config.ROOT_DIR / "ui" / "tui" / "app.tcss"

    def compose(self) -> ComposeResult:
        yield Static("root")


class _FakeKey:
    """Records what a handler did to the event, without a running app."""

    def __init__(self, key: str) -> None:
        self.key = key
        self.stopped = False
        self.prevented = False

    def stop(self) -> None:
        self.stopped = True

    def prevent_default(self) -> None:
        self.prevented = True


def _markers_visible(app: App) -> int:
    """How many of the page's marker runs survive into the rendered screen."""
    return app.export_screenshot().count(MARKER)


async def _open_marker_page(pilot) -> _MarkerScreen:
    page = _MarkerScreen()
    await pilot.app.push_screen(page)
    await pilot.pause()
    return page


async def _open_transition(pilot, *, phase=PHASE_OUT,
                           intensity=None, duration=30.0):
    """Push a transition and pin its intensity.

    The duration is long on purpose: these tests are about what a frame looks
    like and what input does, so the real envelope (and its completion) must
    not fire underneath them.
    """
    done: list[int] = []
    screen = TransitionScreen(phase=phase, duration=duration, seed=SEED,
                              on_complete=lambda: done.append(1))
    await pilot.app.push_screen(screen)
    await pilot.pause()
    if intensity is not None:
        screen._envelope.intensity = lambda: intensity      # pin the envelope
        screen.render_frame()
        await pilot.pause()
    return screen, done


# ─── The frame: coverage ─────────────────────────────────────────────────────


def test_coverage_is_pinned_at_both_ends():
    """Zero must paint nothing (the page is untouched) and the peak must paint
    everything — the peak is the frame the screen swap hides inside."""
    assert coverage_for(0.0) == 0.0
    assert coverage_for(config.TRANSITION_FULL_COVER_AT) == 1.0
    assert coverage_for(1.0) == 1.0


def test_coverage_rises_with_intensity():
    values = [coverage_for(i / 20) for i in range(21)]
    assert values == sorted(values)
    assert 0.0 < coverage_for(0.5) < 1.0, "mid-transition must be partial"


def test_a_clear_frame_paints_nothing():
    frame = build_frame(40, 12, 0.0, random.Random(SEED))
    assert frame == [None] * 12


def test_a_peak_frame_covers_every_row_edge_to_edge():
    """Any gap here is a hole the screen swap would be visible through."""
    frame = build_frame(40, 12, 1.0, random.Random(SEED))
    assert all(row is not None for row in frame)
    assert [row.cell_len for row in frame] == [40] * 12


def test_a_mid_frame_leaves_some_rows_alone():
    frame = build_frame(40, 24, 0.5, random.Random(SEED))
    assert any(row is None for row in frame), "no show-through at all"
    assert any(row is not None for row in frame), "nothing painted at all"
    for row in frame:
        if row is not None:
            assert row.cell_len == 40, "a painted row must cover the full line"


def test_frames_differ_from_each_other():
    """It is an animation — two frames at the same intensity must not match."""
    rng = random.Random(SEED)
    first  = build_frame(40, 24, 0.6, rng)
    second = build_frame(40, 24, 0.6, rng)
    assert [r is None for r in first] != [r is None for r in second] or \
           [None if r is None else r.plain for r in first] != \
           [None if r is None else r.plain for r in second]


def test_degenerate_sizes_do_not_raise():
    rng = random.Random(SEED)
    assert build_frame(0, 10, 1.0, rng) == [None] * 10
    assert build_frame(10, 0, 1.0, rng) == []
    assert len(build_frame(1, 1, 1.0, rng)) == 1
    assert build_frame(-5, -5, 0.5, rng) == []


# ─── The frame, on screen ────────────────────────────────────────────────────


def test_the_page_shows_through_a_partial_frame():
    """The effect is meant to glitch OVER the outgoing page, not replace it."""
    async def go():
        async with _Host().run_test(size=SIZE) as pilot:
            await _open_marker_page(pilot)
            before = _markers_visible(pilot.app)
            assert before > 0, "the page under test rendered nothing"

            await _open_transition(pilot, intensity=0.35)
            during = _markers_visible(pilot.app)
            assert 0 < during < before, (
                f"expected partial show-through, got {during} of {before}")

    asyncio.run(go())


def test_a_peak_frame_hides_the_page_completely():
    """This is the load-bearing one: the screen swap happens on this frame."""
    async def go():
        async with _Host().run_test(size=SIZE) as pilot:
            await _open_marker_page(pilot)
            assert _markers_visible(pilot.app) > 0

            await _open_transition(pilot, intensity=1.0)
            assert _markers_visible(pilot.app) == 0, (
                "the page underneath is visible at full intensity — a screen "
                "swap would be seen happening")

    asyncio.run(go())


def test_the_incoming_half_is_opaque_before_its_first_frame():
    """The "in" half is mounted with the swap already done behind it, and the
    compositor can paint once before any frame exists. It therefore starts
    opaque — otherwise that one frame is a clear look at the page that just
    arrived, which is the whole thing the effect exists to hide."""
    assert TransitionScreen(phase=PHASE_IN, duration=0.5).has_class("solid")
    assert not TransitionScreen(phase=PHASE_OUT,
                                duration=0.5).has_class("solid")


def test_the_envelope_ends_where_the_next_step_needs_it():
    """Out must finish opaque (it hands over to the hidden swap); in must
    finish clear (its screen is popped straight after the last frame)."""
    out_half = GlitchEnvelope(PHASE_OUT, 0.001)
    in_half  = GlitchEnvelope(PHASE_IN,  0.001)
    out_half.started -= 1.0         # pretend the half has run its course
    in_half.started  -= 1.0
    assert out_half.intensity() == 1.0
    assert in_half.intensity() == 0.0
    assert GlitchEnvelope(PHASE_OUT, 30.0).intensity() > 0.0, "must open on a hit"
    assert GlitchEnvelope(PHASE_OUT, 0.001, seed=SEED).is_full(1.0)
    assert not GlitchEnvelope(PHASE_OUT, 0.001, seed=SEED).is_full(0.0)


# ─── Input is dead for the duration ──────────────────────────────────────────


def test_keys_are_swallowed_and_quit_is_not():
    screen = TransitionScreen.__new__(TransitionScreen)   # no app needed
    ordinary = _FakeKey("a")
    screen.on_key(ordinary)
    assert ordinary.stopped and ordinary.prevented

    for key in config.TRANSITION_PASSTHROUGH_KEYS:
        escape = _FakeKey(key)
        screen.on_key(escape)
        assert not escape.stopped, f"{key} must still reach the app"


def test_a_key_pressed_during_a_transition_never_reaches_the_page():
    """Not just ignored while it runs — it must not queue up and land on the
    page afterwards either."""
    async def go():
        async with _Host().run_test(size=SIZE) as pilot:
            page = await _open_marker_page(pilot)
            await _open_transition(pilot, intensity=0.8)

            # _press_keys, not pilot.press: press() waits for the screen to go
            # idle, which a 20fps frame timer never does.
            await pilot.app._press_keys(["a"])
            await asyncio.sleep(0.1)
            assert page.pressed == 0, "the page acted on a key during the freeze"

            pilot.app.pop_screen()          # transition over
            await pilot.pause()
            await pilot.app._press_keys(["a"])
            await asyncio.sleep(0.1)
            assert page.pressed == 1, "input never came back"

    asyncio.run(go())


# ─── Teardown ────────────────────────────────────────────────────────────────


def test_completion_fires_exactly_once():
    async def go():
        async with _Host().run_test(size=SIZE) as pilot:
            await _open_marker_page(pilot)
            _screen, done = await _open_transition(pilot, duration=0.1)
            await asyncio.sleep(0.35)
            assert done == [1], f"completion fired {len(done)} times"

    asyncio.run(go())


def test_removing_the_transition_stops_its_frame_timer():
    """A leaked frame timer would keep painting rows onto a screen that is no
    longer in the stack."""
    async def go():
        async with _Host().run_test(size=SIZE) as pilot:
            await _open_marker_page(pilot)
            screen, _done = await _open_transition(pilot, intensity=0.8)
            assert screen._frames is not None and screen._timer is not None

            pilot.app.pop_screen()
            await pilot.pause()
            assert screen._frames is None and screen._timer is None

    asyncio.run(go())


# ─── App wiring ──────────────────────────────────────────────────────────────


def test_a_screen_change_glitches_then_lands_clean():
    async def go():
        app = HackDoxApp(seed=SEED)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause()
            assert isinstance(app.screen, IntroScreen)

            app.start_new_game()
            # Synchronously, before anything is awaited: the glitch is up and
            # the old page is still underneath it.
            assert isinstance(app.screen, TransitionScreen)
            assert isinstance(app.screen_stack[-2], IntroScreen)
            assert app._transition_busy is True

            await asyncio.sleep(config.TRANSITION_DURATION + 0.5)
            assert isinstance(app.screen, BriefingScreen)
            assert len(app.screen_stack) == 2, "the stack did not rebalance"
            assert app._transition_busy is False
            assert app._queued_screen is None

    asyncio.run(go())


def test_the_swap_happens_while_the_page_is_hidden():
    """Sampled through a real transition: at no point is either page visible
    alongside the glitch."""
    async def go():
        app = HackDoxApp(seed=SEED)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause()
            app.start_new_game()
            leaks = []
            while app._transition_busy:
                await asyncio.sleep(0.02)
                shot = app.export_screenshot()
                if "New game" in shot or "Begin" in shot:
                    leaks.append([type(s).__name__ for s in app.screen_stack])
            assert not leaks, f"page visible mid-transition: {leaks[:3]}"

    asyncio.run(go())


def test_disabling_transitions_restores_the_instant_cut():
    async def go():
        original = config.TRANSITION_ENABLED
        config.TRANSITION_ENABLED = False
        try:
            app = HackDoxApp(seed=SEED)
            async with app.run_test(size=(140, 44)) as pilot:
                await pilot.pause()
                app.start_new_game()
                assert isinstance(app.screen, BriefingScreen)
                assert not any(isinstance(s, TransitionScreen)
                               for s in app.screen_stack)
                assert app._transition_busy is False
        finally:
            config.TRANSITION_ENABLED = original

    asyncio.run(go())


def test_a_screen_change_mid_transition_is_queued_not_stacked():
    """Input is dead for the window, so this can only come from a stray timer
    — but stacking a second glitch would orphan a screen in the stack."""
    async def go():
        app = HackDoxApp(seed=SEED)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause()
            app.start_new_game()
            depth = len(app.screen_stack)

            late = IntroScreen()
            app._transition(late)
            assert app._queued_screen is late
            assert len(app.screen_stack) == depth, "a second glitch was stacked"

            await asyncio.sleep(config.TRANSITION_DURATION + 0.5)
            assert app.screen is late
            assert len(app.screen_stack) == 2
            assert app._queued_screen is None

    asyncio.run(go())


def test_the_whole_day_loop_transitions_and_rebalances():
    """Walks every wired call site in order. Each one must open on a glitch
    and leave the stack exactly two deep — four screens are pushed and popped
    per transition, so an unbalanced one would accumulate silently and only
    show up days later."""
    async def go():
        app = HackDoxApp(seed=SEED)
        async with app.run_test(size=(150, 46)) as pilot:
            await pilot.pause()
            steps = [("start_new_game",   app.start_new_game),
                     ("begin_intake",     app.begin_intake),
                     ("finish_day",       app.finish_day),
                     ("show_between_day", app.show_between_day),
                     ("advance_day",      app.advance_day),
                     ("game_over",        app.game_over)]
            for name, call in steps:
                call()
                assert isinstance(app.screen, TransitionScreen), name
                await asyncio.sleep(config.TRANSITION_DURATION + 0.4)
                assert not app._transition_busy, name
                assert len(app.screen_stack) == 2, (
                    name, [type(s).__name__ for s in app.screen_stack])
            assert app._state.current_day == 2, "the day never advanced"

    asyncio.run(go())


def test_every_full_screen_change_goes_through_the_transition():
    """Regression guard: a new screen wired up with a bare pop/push would cut
    instantly and, worse, leave input live while the rest of the game froze."""
    source = Path(app_module.__file__).read_text(encoding="utf-8")
    tree   = ast.parse(source)
    cls    = next(node for node in tree.body
                  if isinstance(node, ast.ClassDef) and node.name == "HackDoxApp")
    culprits = set()
    for func in cls.body:
        if not isinstance(func, ast.FunctionDef):
            continue
        for node in ast.walk(func):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"push_screen", "pop_screen"}):
                culprits.add(func.name)
    assert culprits == {"on_mount",            # the very first screen, no swap
                        "_swap_screen",
                        "_transition",
                        "_transition_swap",
                        "_transition_end"}, sorted(culprits)


# ─── Wiring of the pieces around it ──────────────────────────────────────────


def test_the_transition_has_a_sound():
    sound = SFX_REGISTRY.get("transition_glitch")
    assert sound, "no sound registered for the transition"
    assert (config.AUDIO_SFX_DIR / sound).exists()


def test_the_glitch_css_sits_above_the_verdict_pulse():
    """The verdict-pulse block has to stay last in app.tcss (it wins its
    cascade on document order alone), so anything added later goes above it."""
    sheet = (config.ROOT_DIR / "ui" / "tui" / "app.tcss").read_text(encoding="utf-8")
    glitch  = sheet.index("Screen transition glitch")
    verdict = sheet.index("Verdict reveal window")
    assert glitch < verdict
    for rule in (".glitch-row.off", "TransitionScreen.solid", "TransitionScreen {"):
        assert rule in sheet, f"{rule} is not styled"
