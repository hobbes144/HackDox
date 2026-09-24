"""IntroScreen — the Start Menu.

BUILD_PLAN_MenuSystem_2026-09.md, Phase 2. Closes GitHub issue #79
(persistence.load()/save() were fully built but Continue was never wired
up). The logo is a plain text placeholder per Nick's own instruction —
swappable for real art later without touching layout or behavior.

Endless Mode has no engine behind it yet (Phase order in the build plan) —
it ships as a disabled "coming soon" button, same treatment as any other
not-yet-built feature getting a stub rather than a silently missing one.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Static

from gameengine import config
from gameengine.core import persistence
from gameengine.ui.tui.screens.credits import CreditsScreen
from gameengine.ui.tui.screens.settings import SettingsScreen
from gameengine.ui.tui.widgets import AmbientGlitchPanel

_LOGO = "H A C K D O X\nT E R M I N A L"


class IntroScreen(Screen):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("n", "new_game",      "New game"),
        Binding("c", "continue_game", "Continue",  show=False),
        Binding("s", "open_settings", "Settings",  show=False),
        Binding("r", "open_credits",  "Credits",   show=False),
        Binding("q", "quit_app",      "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Horizontal(classes="menu-frame"):
            yield AmbientGlitchPanel(seed=101, classes="menu-flank")
            with Vertical(classes="menu-column"):
                yield Static(_LOGO, classes="menu-logo")
                yield Static(
                    "Access to HackDox is reviewed by hand. You are the hand.",
                    classes="menu-subtitle",
                )
                with Vertical(classes="menu-buttons"):
                    yield Button("New Game", id="menu-new-game", variant="success")
                    yield Button("Continue", id="menu-continue")
                    yield Button("Endless Mode (coming soon)",
                                 id="menu-endless", disabled=True)
                    yield Button("Settings", id="menu-settings")
                    yield Button("Credits", id="menu-credits")
                    yield Button("Quit", id="menu-quit", variant="error")
                yield Static("", id="menu-hint", classes="menu-hint")
            yield AmbientGlitchPanel(seed=202, classes="menu-flank")

    def on_mount(self) -> None:
        self._refresh_continue()

    def _refresh_continue(self) -> None:
        """#79 AC: Continue is shown/enabled only when a save exists, and
        the hint line reflects that too — a fresh install shows just New
        Game / Settings / Credits / Quit."""
        has_save = config.SAVE_FILE.exists()
        btn = self.query_one("#menu-continue", Button)
        btn.disabled = not has_save
        btn.display = has_save

        parts = ["[#00ff9f][b]N[/][/] New Game"]
        if has_save:
            parts.append("[#00ff9f][b]C[/][/] Continue")
        parts += [
            "[#00ff9f][b]S[/][/] Settings",
            "[#00ff9f][b]R[/][/] Credits",
            "[#00ff9f][b]Q[/][/] Quit",
        ]
        self.query_one("#menu-hint", Static).update("   ·   ".join(parts))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        handlers = {
            "menu-new-game": self.action_new_game,
            "menu-continue": self.action_continue_game,
            "menu-settings": self.action_open_settings,
            "menu-credits":  self.action_open_credits,
            "menu-quit":     self.action_quit_app,
        }
        handler = handlers.get(event.button.id)
        if handler is not None:
            handler()
        # menu-endless is disabled — no handler until Endless Mode itself
        # exists (not this phase).

    def action_new_game(self) -> None:
        self.app.start_new_game()

    def action_continue_game(self) -> None:
        if not config.SAVE_FILE.exists():
            return
        state = persistence.load()
        if state is None:
            return
        self.app.resume_game(state)

    def action_open_settings(self) -> None:
        self.app.push_screen(SettingsScreen())

    def action_open_credits(self) -> None:
        self.app.push_screen(CreditsScreen())

    def action_quit_app(self) -> None:
        self.app.exit()
