"""GameOverScreen — the campaign's loss screen (Site Health collapsed).

2026-09-25: rebuilt on the start menu's framed layout — the slow, flowing
ambient glitch (`AmbientGlitchPanel`) on all four sides with the message in a
centred column — so the end of a run reads as part of the menu flow it hands
back to, matching EndlessOverScreen. Before this it was three unstyled lines
in the top-left corner (`#splash` never had any CSS).
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Static

from gameengine.ui.tui.widgets import AmbientGlitchPanel


class GameOverScreen(Screen):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("r", "restart", "Restart"),
        Binding("m", "main_menu", "Main menu"),
        Binding("q", "quit_app", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(classes="menu-frame"):
            yield AmbientGlitchPanel(seed=515, classes="menu-flank-h")
            with Horizontal(classes="menu-frame-row"):
                yield AmbientGlitchPanel(seed=505, classes="menu-flank")
                with Vertical(classes="menu-column"):
                    yield AmbientGlitchPanel(seed=525, classes="menu-modal-flank")
                    with Vertical(classes="menu-column-content"):
                        yield Static("[b][#ff5470]G A M E   O V E R[/][/]",
                                     classes="menu-logo")
                        yield Static(
                            "Site Health collapsed — the threats you admitted "
                            "took the site down.",
                            classes="menu-subtitle",
                        )
                        yield Static(
                            "[#00ff9f][b]R[/][/] Restart campaign   ·   "
                            "[#00ff9f][b]M[/][/] Main menu   ·   "
                            "[#00ff9f][b]Q[/][/] Quit",
                            classes="menu-hint",
                        )
                    yield AmbientGlitchPanel(seed=535, classes="menu-modal-flank")
                yield AmbientGlitchPanel(seed=606, classes="menu-flank")
            yield AmbientGlitchPanel(seed=616, classes="menu-flank-h")

    def action_restart(self) -> None:
        self.app.start_new_game()

    def action_main_menu(self) -> None:
        self.app.to_main_menu()

    def action_quit_app(self) -> None:
        self.app.exit()
