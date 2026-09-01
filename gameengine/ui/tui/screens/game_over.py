"""GameOverScreen."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Static


class GameOverScreen(Screen):
    BINDINGS = [
        Binding("r", "restart", "Restart"),
        Binding("q", "quit_app", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="splash"):
            yield Static("[b][#ff5470]GAME OVER[/][/]", classes="title")
            yield Static(
                "Site Health collapsed — the threats you admitted took the site down.",
                classes="subtitle",
            )
            yield Static(
                "[#00ff9f][b]R[/][/] Restart     [#00ff9f][b]Q[/][/] Quit",
                classes="hint",
            )

    def action_restart(self) -> None:
        self.app.start_new_game()

    def action_quit_app(self) -> None:
        self.app.exit()


# ─── App ────────────────────────────────────────────────────────────────────────────────
