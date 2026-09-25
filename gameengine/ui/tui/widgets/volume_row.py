"""VolumeRow — a focusable, arrow-key-adjustable volume bar.

Used by SettingsScreen (BUILD_PLAN_MenuSystem_2026-09.md, Phase 3) for the
three SoundManager volume knobs (master/music/sfx). Deliberately not a
Textual reactive — the value only ever changes through `_set`, so a plain
attribute plus an explicit repaint is simpler than wiring a watcher for it.
"""

from __future__ import annotations

from typing import Callable

from textual import events
from textual.widgets import Static

_BAR_WIDTH = 24
_STEP = 0.05


class VolumeRow(Static):
    """One labelled 0.0-1.0 bar. Left/Right nudge by _STEP, Home/End jump to
    0/1. Every change calls `on_change(value)` immediately — there is no
    separate "apply" step, so the caller can push it straight into
    SoundManager and persist it."""

    can_focus = True

    def __init__(self, label: str, value: float,
                 on_change: Callable[[float], None], **kwargs) -> None:
        super().__init__("", **kwargs)
        self._label = label
        self.value = max(0.0, min(1.0, value))
        self._on_change = on_change

    def on_mount(self) -> None:
        self._repaint()

    def _repaint(self) -> None:
        filled = round(self.value * _BAR_WIDTH)
        bar = "█" * filled + "░" * (_BAR_WIDTH - filled)
        pct = round(self.value * 100)
        self.update(f"{self._label:<8}  [#00ff9f]{bar}[/]  {pct:>3}%")

    def on_key(self, event: events.Key) -> None:
        if event.key == "left":
            self._set(self.value - _STEP); event.stop()
        elif event.key == "right":
            self._set(self.value + _STEP); event.stop()
        elif event.key == "home":
            self._set(0.0); event.stop()
        elif event.key == "end":
            self._set(1.0); event.stop()

    def _set(self, value: float) -> None:
        value = max(0.0, min(1.0, round(value, 2)))
        if value == self.value:
            return
        self.value = value
        self._repaint()
        self._on_change(value)
