"""CampaignEndScreen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Static
from gameengine.core.models import Day


class CampaignEndScreen(Screen):
    """Shown when the next day's content doesn't exist yet."""

    BINDINGS = [Binding("q", "quit_app", "Quit")]

    def __init__(self, day_number: int) -> None:
        super().__init__()
        self._day_number = day_number

    def compose(self) -> ComposeResult:
        with Container(id="splash"):
            yield Static("[b][#00ff9f]TO BE CONTINUED[/][/]", classes="title")
            yield Static(
                f"Day {self._day_number} isn't written yet. Your save is stored — "
                "the campaign resumes when the content lands.",
                classes="subtitle",
            )
            yield Static("[#00ff9f][b]Q[/][/]  Quit", classes="hint")

    def action_quit_app(self) -> None:
        self.app.exit()
