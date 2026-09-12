"""TransitionScreen — one half of a glitch screen transition.

Pushed by `HackDoxApp._transition` / `_transition_swap`; see those for the
choreography. Two things happen here and nothing else:

  1. the CRT signal-loss effect animates over whatever is underneath;
  2. input is DEAD for the duration.

**Why the rows are children of the screen.** Textual's compositor lets the
screen below show through only where the top screen paints NOTHING — and any
widget spanning the window paints, container or not. So the frame is drawn as
one `Static` per terminal row, mounted directly here by `glitch.RowPainter`
(which the in-place damage glitch shares): a covered row carries `width` cells
of noise, an uncovered row is hidden and the page shows through. Wrapping them
in a field widget would make the whole window opaque for the entire
transition, which is a cut, not a glitch.

**Why this is a screen at all.** Input blocking. A pushed screen is the active
one, so the screen beneath receives no keys, no clicks and — crucially — none
of its own BINDINGS fire. The handlers below then swallow what reaches this
screen, so keys mashed during the freeze cannot queue up and land on the page
that arrives next. `TRANSITION_PASSTHROUGH_KEYS` is the deliberate exception:
quitting must never be blocked by an animation.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen

from gameengine import config
from gameengine.ui.tui import glitch


class TransitionScreen(ModalScreen):
    # No bindings at all: every key during a transition is meant to be dead.
    BINDINGS: ClassVar[list[Binding]] = []
    # Nothing to focus — and focusing something would give it key events.
    AUTO_FOCUS = None

    def __init__(self, *, phase: str = glitch.PHASE_OUT, duration: float = 0.5,
                 on_complete: Callable[[], None] | None = None,
                 seed: int | None = None) -> None:
        super().__init__()
        self._duration    = max(0.01, duration)
        self._envelope    = glitch.GlitchEnvelope(phase, self._duration, seed)
        self._on_complete = on_complete
        self._done        = False
        self._timer       = None
        self._frames      = None
        self._painter     = glitch.RowPainter(self)
        # The "in" half is mounted with the swap already done behind it, and
        # the compositor can paint once before the first frame exists. Starting
        # opaque means that frame is black rather than a clear look at the page
        # that just arrived — which is the one thing this effect exists to hide.
        self._solid = phase == glitch.PHASE_IN
        self.set_class(self._solid, "solid")

    def compose(self) -> ComposeResult:
        """One row per terminal line, carrying frame ONE already.

        self.size is not laid out yet, but the window size is known and this
        screen is full-window. The rows are built with content rather than
        empty because the compositor can paint this screen before any timer
        has run — and for the "in" half that first paint is the moment right
        after the swap, the one frame that must not show the new page.
        """
        window = self.app.size if self.app is not None else None
        width  = window.width if window else 0
        height = max(0, window.height if window else 0)
        frame  = glitch.build_frame(width, height, self._envelope.intensity(),
                                    self._envelope.rng)
        yield from self._painter.build(height, frame)

    def on_mount(self) -> None:
        self._envelope.restart()      # the ramp starts on mount, not on build
        self.render_frame()
        self._frames = self.set_interval(
            config.TRANSITION_FRAME_INTERVAL, self.render_frame)
        self._timer  = self.set_timer(self._duration, self._finish)

    def on_unmount(self) -> None:
        # Teardown is load-bearing, not defensive: a leaked frame timer keeps
        # repainting rows on a screen that is no longer in the stack.
        for timer in (self._frames, self._timer):
            if timer is not None:
                timer.stop()
        self._frames = self._timer = None

    def on_resize(self, event) -> None:
        self._resize_rows(event.size.height)
        self.render_frame()

    # ── The animation ───────────────────────────────────────────────────
    def _resize_rows(self, height: int) -> None:
        """Terminal resized mid-transition — rebuild the row set."""
        height = max(0, height)
        if height == self._painter.height:
            return
        self._painter.discard()
        self._painter.mount(height)

    def _set_solid(self, solid: bool) -> None:
        """Opaque screen background at full coverage.

        Belt to the rows' braces: when every line is painted there is nothing
        to show through anyway, so painting the screen's own background as well
        guarantees the swap underneath stays invisible even on a frame the
        compositor catches mid-update. Off below full coverage, or show-through
        would be blocked for the whole transition.
        """
        if solid == self._solid:
            return
        self._solid = solid
        self.set_class(solid, "solid")

    def render_frame(self) -> None:
        if not self._painter.height:
            return
        intensity = self._envelope.intensity()
        self._set_solid(self._envelope.is_full(intensity))
        width = self.size.width or (self.app.size.width if self.app else 0)
        self._painter.paint(glitch.build_frame(
            width, self._painter.height, intensity, self._envelope.rng))

    # ── Input is dead for the duration ──────────────────────────────────
    def on_key(self, event) -> None:
        if event.key in config.TRANSITION_PASSTHROUGH_KEYS:
            return
        event.stop()
        event.prevent_default()

    def on_mouse_down(self, event) -> None:
        event.stop()

    def on_mouse_up(self, event) -> None:
        event.stop()

    def on_click(self, event) -> None:
        event.stop()

    # ── Completion ──────────────────────────────────────────────────────
    def _finish(self) -> None:
        """Fires once. The callback is what advances the screen stack, so a
        double fire would push a screen twice."""
        if self._done:
            return
        self._done = True
        callback, self._on_complete = self._on_complete, None
        if callback is not None:
            callback()
