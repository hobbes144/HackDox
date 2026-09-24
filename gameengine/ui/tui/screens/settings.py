"""SettingsScreen.

BUILD_PLAN_MenuSystem_2026-09.md, Phase 3 — sound only for now (Nick's own
words: "for now it's just going to be like sounds ... we can add to that
later"). Wires the SoundManager's volume knobs, which were already fully
built (core/audio.py) but had no UI calling `save_settings()` — see
audio_system.md's "next natural step" note, written before this screen
existed.

Reachable from the Start Menu and from the Pause menu (both push it
directly, same as RulesScreen/CreditRevealScreen/PauseScreen do — this is
an overlay push, not a full-screen `_transition`, so it isn't covered by
the AST test that enforces the transition on HackDoxApp's own screen swaps).
Same `.menu-frame` shell as IntroScreen/CreditsScreen, per Nick's ask that
Settings share the start menu's central-column-plus-glitch-flanks layout.

Up/Down move focus between rows/controls (same as Tab/Shift+Tab), Left/Right
adjust the focused VolumeRow — Up/Down never touch a row's value, so there's
no ambiguity between "navigate" and "adjust" on the same axis.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Static, Switch

from gameengine.core.audio import sound_manager
from gameengine.ui.tui.widgets import AmbientGlitchPanel, VolumeRow


class SettingsScreen(Screen):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "back", "Back"),
        Binding("up", "focus_previous", "Up", show=False),
        Binding("down", "focus_next", "Down", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Horizontal(classes="menu-frame"):
            yield AmbientGlitchPanel(seed=501, classes="menu-flank")
            with Vertical(classes="menu-column"):
                yield Static("S E T T I N G S", classes="menu-logo")
                yield Static("Sound", classes="menu-subtitle")
                with Vertical(id="settings-rows"):
                    yield VolumeRow("Master", sound_manager.master_volume,
                                    self._on_master, id="vol-master")
                    yield VolumeRow("Music", sound_manager.music_volume,
                                    self._on_music, id="vol-music")
                    yield VolumeRow("SFX", sound_manager.sfx_volume,
                                    self._on_sfx, id="vol-sfx")
                    with Horizontal(id="settings-mute-row"):
                        yield Static("Sound enabled", id="settings-mute-label")
                        yield Switch(value=sound_manager.enabled,
                                     id="settings-mute")
                with Vertical(classes="menu-buttons"):
                    yield Button("Back", id="settings-back")
                yield Static(
                    "[#00ff9f][b]←→[/][/] adjust  ·  [#00ff9f][b]↑↓/Tab[/][/] navigate  ·  "
                    "[#00ff9f][b]Esc[/][/] back",
                    classes="menu-hint",
                )
            yield AmbientGlitchPanel(seed=602, classes="menu-flank")

    # ── Volume callbacks — each VolumeRow calls its own on change, so a
    # slider never needs to know about the other two or about persistence.
    def _on_master(self, value: float) -> None:
        sound_manager.set_master_volume(value)
        sound_manager.save_settings()

    def _on_music(self, value: float) -> None:
        sound_manager.set_music_volume(value)
        sound_manager.save_settings()

    def _on_sfx(self, value: float) -> None:
        sound_manager.set_sfx_volume(value)
        sound_manager.save_settings()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id == "settings-mute":
            sound_manager.set_enabled(event.value)
            sound_manager.save_settings()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "settings-back":
            self.action_back()

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_focus_next(self) -> None:
        self.focus_next()

    def action_focus_previous(self) -> None:
        self.focus_previous()
