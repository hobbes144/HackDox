"""CreditsScreen — the Start Menu's "Credits" button.

Deliberately a distinct class/module from `CreditRevealScreen`
(screens/credit_reveal.py), which is an unrelated in-fiction mechanic
(spending a HackDox Credit — HackDollar-adjacent in-game currency — to
reveal a candidate's ground truth). The naming collision was flagged in
BUILD_PLAN_MenuSystem_2026-09.md before either screen shipped; the two
never reference each other.

Static content, same `.menu-frame` shell as IntroScreen/SettingsScreen —
placeholder copy until Nick wants real credits text.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Static

from gameengine.ui.tui.widgets import AmbientGlitchPanel

_CREDITS_TEXT = (
    "[b]HACKDOX[/]\n\n"
    "A game by Nick Shaw\n\n"
    "[dim]Design, engineering, and writing[/]\n"
    "Nick Shaw\n\n"
    "[dim]Built with Python + Textual[/]"
)


class CreditsScreen(Screen):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "back", "Back"),
        Binding("enter", "back", "Back", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(classes="menu-frame"):
            yield AmbientGlitchPanel(seed=313, classes="menu-flank-h")
            with Horizontal(classes="menu-frame-row"):
                yield AmbientGlitchPanel(seed=303, classes="menu-flank")
                with Vertical(classes="menu-column"):
                    yield AmbientGlitchPanel(seed=323, classes="menu-modal-flank")
                    with Vertical(classes="menu-column-content"):
                        yield Static("C R E D I T S", classes="menu-logo")
                        yield Static(_CREDITS_TEXT, classes="menu-subtitle",
                                     id="credits-body")
                        with Vertical(classes="menu-buttons"):
                            yield Button("Back", id="credits-back")
                        yield Static("[#00ff9f][b]Esc[/][/] back", classes="menu-hint")
                    yield AmbientGlitchPanel(seed=333, classes="menu-modal-flank")
                yield AmbientGlitchPanel(seed=404, classes="menu-flank")
            yield AmbientGlitchPanel(seed=414, classes="menu-flank-h")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "credits-back":
            self.action_back()

    def action_back(self) -> None:
        self.app.pop_screen()
