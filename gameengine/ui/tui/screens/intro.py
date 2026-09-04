"""IntroScreen."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Static


class IntroScreen(Screen):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("n", "new_game", "New game"),
        Binding("q", "quit_app", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="splash"):
            yield Static(
                "  H A C K D O X   T E R M I N A L\n",
                classes="title",
            )
            yield Static(
                "Access to HackDox is reviewed by hand. You are the hand.",
                classes="subtitle",
            )
            yield Static(
                "[#00ff9f][b]N[/][/]  New game     [#00ff9f][b]Q[/][/]  Quit",
                classes="hint",
            )

    def action_new_game(self) -> None:
        self.app.start_new_game()

    def action_quit_app(self) -> None:
        self.app.exit()
