"""AmbientGlitchPanel — the slow-drifting static that flanks a menu column.

Distinct from ui/tui/glitch.py's two effects (see that module's docstring):
transitions hide a screen swap, the damage burst punctuates a verdict — both
are short, front-loaded, and have to let the page underneath show through, so
they paint via `RowPainter` directly onto the host SCREEN.

This is a third, much simpler case: pure ambiance next to a menu, with
nothing underneath it that needs to show through (the panel owns its whole
rectangle — there's void behind it, not gameplay). So it skips RowPainter
entirely and is just a `Static` that repaints itself on a timer, using the
same `build_frame()` pixels-are-rows primitive from glitch.py.

Unlike a naive "reroll a fresh frame every tick" version, this one HOLDS one
still frame for a while (a "state"), then MORPHs into a freshly rolled one
over a slower, ragged top-to-bottom wipe, then holds again — see
config.AMBIENT_GLITCH_HOLD_DURATION / _MORPH_DURATION / _MORPH_JITTER. The
loop of hold -> flowing morph -> hold is what gives it the "naturally
progressing and evolving" read Nick asked for (2026-09), instead of the flat
flicker a per-tick reroll produces.

A state is stored as a (rng_state, intensity) SNAPSHOT, not as prebuilt Rich
`Text` rows — `_frame_for()` regenerates the actual frame from a snapshot
fresh on every single paint (`build_frame` is a pure function of its
arguments, see glitch.py), so two calls with the same snapshot produce
content-identical but object-distinct `Text` instances. That's not what
fixed the crash this design went through on the way here, though: this
widget's own "have I resized" bookkeeping was originally named `self._size`,
which silently shadows `Widget._size` — Textual's OWN private attribute,
which the framework expects to hold a `Size` object (`_size_updated` in
Textual's own widget.py assigns it directly). Overwriting it with a plain
`(width, height)` tuple corrupted the framework's own layout bookkeeping —
`outer_size.region` would blow up a few ticks later with `'tuple' object has
no attribute 'region'`, reproducibly, on every terminal size tried. Renamed
to `self._panel_size` and the crash was gone. Moral: never name an instance
attribute `_size` (or anything else `Widget` already claims) on a Textual
widget subclass.

It never blocks input and never reaches full coverage — see
config.AMBIENT_GLITCH_*.
"""

from __future__ import annotations

import math
import random
from time import monotonic

from rich.text import Text
from textual.widgets import Static

from gameengine import config
from gameengine.ui.tui import glitch

_STATE_HOLD  = "hold"
_STATE_MORPH = "morph"

# glitch.DEFAULT_PALETTE's dark/background tones are tuned for the
# transition and damage-burst effects, which both fade TO or AWAY FROM a
# void darker than the page itself (glitch.py's `_VOID`, #05070a) — the
# right feel for something covering the whole screen mid-transition. This
# panel just sits quietly beside the menu forever, so its OWN dark tone
# needs to be the page's actual background (config.PAGE_BACKGROUND), not a
# separately-tinted void, or the low-intensity majority of every frame reads
# as a visibly darker rectangle next to the page rather than part of it
# (Nick, 2026-09-24). Foreground/accent colours are unchanged — those are
# meant to pop.
_AMBIENT_PALETTE = glitch.Palette(
    tear_fg=glitch.DEFAULT_PALETTE.tear_fg,
    tear_bg=[config.PAGE_BACKGROUND],
    dim_fg=glitch.DEFAULT_PALETTE.dim_fg,
    dark_bg=[config.PAGE_BACKGROUND],
)


def blend_frames(old: list, new: list, progress: float,
                  row_switch_at: list[float]) -> list:
    """Row `i` of the result is `new[i]` once `progress` has reached that
    row's own switch point, otherwise `old[i]`.

    `row_switch_at` is one value per row in [0, 1] — nominally `i / height`
    (a straight top-to-bottom sweep) but jittered per row by the caller, so
    the front between old and new is ragged rather than a single clean bar.
    A pure function of its arguments (no widget, no clock), so the shape of
    the wipe can be tested without a running app — mirrors `build_frame`
    being a pure function in glitch.py for the same reason.
    """
    height = min(len(old), len(new), len(row_switch_at))
    return [new[i] if progress >= row_switch_at[i] else old[i]
            for i in range(height)]


def row_switch_points(height: int, jitter: float,
                       rng: random.Random) -> list[float]:
    """One switch-point per row for `blend_frames`: `i / height`, jittered by
    up to `jitter` (a fraction of the full sweep) in either direction and
    clamped back into [0, 1] so the wipe still starts at the top and finishes
    by progress == 1.0."""
    if height <= 0:
        return []
    return [max(0.0, min(1.0, i / height + rng.uniform(-jitter, jitter)))
            for i in range(height)]


class AmbientGlitchPanel(Static):
    """A vertical strip of low-intensity CRT noise, drifting forever.

    Each instance gets its own rng stream and phase offset (both seeded from
    `seed`, or randomly if omitted) so two panels side by side never mirror
    each other frame for frame, or morph in lockstep."""

    def __init__(self, seed: int | None = None, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._rng = random.Random(seed)
        self._phase = self._rng.uniform(0, math.tau)
        self._t0 = monotonic()
        self._timer = None

        self._panel_size = (0, 0)          # last (width, height) seen
        self._current = None         # (rng_state, intensity) snapshot on screen
        self._target = None          # snapshot being morphed toward
        self._row_switch_at: list[float] = []
        self._state = _STATE_HOLD
        self._state_started = self._t0

    def on_mount(self) -> None:
        if config.AMBIENT_GLITCH_ENABLED:
            self._timer = self.set_interval(
                config.AMBIENT_GLITCH_FRAME_INTERVAL, self._tick)
        self._tick()

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _intensity(self) -> float:
        """A slow sine drift between AMBIENT_GLITCH_MIN/MAX — never a hard
        cut, never full coverage. Sampled once per new state (see
        `_snapshot`), not once per frame, so it's the state-to-state
        intensity that drifts, not each frame individually. The
        per-instance phase offset keeps the left and right flanks from
        breathing in sync."""
        if not config.AMBIENT_GLITCH_ENABLED:
            return 0.0
        elapsed = monotonic() - self._t0
        wave = math.sin(elapsed * config.AMBIENT_GLITCH_SPEED + self._phase)
        lo, hi = config.AMBIENT_GLITCH_MIN, config.AMBIENT_GLITCH_MAX
        return lo + (hi - lo) * (0.5 + 0.5 * wave)

    def _snapshot(self) -> tuple:
        """A new (rng_state, intensity) pair identifying one state.

        Captures `self._rng`'s state as it is right now — so `_frame_for`
        can regenerate this exact state's frame from scratch, any number of
        times — then perturbs `self._rng` so the *next* snapshot draws
        different content instead of repeating this one."""
        snapshot = (self._rng.getstate(), self._intensity())
        self._rng.random()
        return snapshot

    def _frame_for(self, snapshot: tuple, width: int, height: int) -> list:
        state, intensity = snapshot
        rng = random.Random()
        rng.setstate(state)
        return glitch.build_frame(width, height, intensity, rng,
                                   _AMBIENT_PALETTE)

    def _tick(self) -> None:
        width, height = self.size.width, self.size.height
        if width <= 0 or height <= 0:
            return

        if (width, height) != self._panel_size:
            # A resize mid-morph would blend frames of mismatched shape —
            # simplest correct thing is to snap to a fresh state at the new
            # size and let the hold/morph loop pick back up from there.
            self._panel_size = (width, height)
            self._current = self._snapshot()
            self._target = self._current
            self._state = _STATE_HOLD
            self._state_started = monotonic()

        elapsed = monotonic() - self._state_started

        if self._state == _STATE_HOLD:
            if elapsed >= config.AMBIENT_GLITCH_HOLD_DURATION:
                self._target = self._snapshot()
                self._row_switch_at = row_switch_points(
                    height, config.AMBIENT_GLITCH_MORPH_JITTER, self._rng)
                self._state = _STATE_MORPH
                self._state_started = monotonic()
                elapsed = 0.0

        if self._state == _STATE_HOLD:
            frame = self._frame_for(self._current, width, height)
        else:
            progress = min(1.0, elapsed / config.AMBIENT_GLITCH_MORPH_DURATION)
            old_frame = self._frame_for(self._current, width, height)
            new_frame = self._frame_for(self._target, width, height)
            frame = blend_frames(old_frame, new_frame, progress,
                                  self._row_switch_at)
            if progress >= 1.0:
                self._current = self._target
                self._state = _STATE_HOLD
                self._state_started = monotonic()

        self._paint(frame, width)

    def _paint(self, frame: list, width: int) -> None:
        text = Text(no_wrap=True)
        for i, row in enumerate(frame):
            if i:
                text.append("\n")
            text.append(row if row is not None else Text(" " * width))
        self.update(text)
