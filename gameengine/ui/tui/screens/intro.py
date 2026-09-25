"""IntroScreen — the Start Menu.

BUILD_PLAN_MenuSystem_2026-09.md, Phase 2. Closes GitHub issue #79
(persistence.load()/save() were fully built but Continue was never wired
up). The logo is a plain text placeholder per Nick's own instruction —
swappable for real art later without touching layout or behavior.

Endless Mode (#7) is live. The campaign and Endless keep SEPARATE saves
(Nick, 2026-09-25), so the menu shows them as two clearly labelled pairs —
"New Campaign / Continue Campaign" and "New Endless Run / Continue Endless" —
each Continue naming where that save is (Day 7 vs Shift 4), plus a note that
the two never overwrite each other and the Endless personal best.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Static

from gameengine import config
from gameengine.core import endless, persistence
from gameengine.core.models import GameMode
from gameengine.ui.tui.screens.credits import CreditsScreen
from gameengine.ui.tui.screens.settings import SettingsScreen
from gameengine.ui.tui.widgets import AmbientGlitchPanel

_LOGO = "H A C K D O X\nT E R M I N A L"


class IntroScreen(Screen):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("n", "new_game",      "New campaign"),
        Binding("c", "continue_game", "Continue campaign", show=False),
        Binding("e", "new_endless",   "New Endless run",   show=False),
        Binding("x", "continue_endless", "Continue Endless", show=False),
        Binding("s", "open_settings", "Settings",  show=False),
        Binding("r", "open_credits",  "Credits",   show=False),
        Binding("q", "quit_app",      "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        # Starting a new Endless run over one in progress takes two presses.
        self._confirm_abandon = False

    def compose(self) -> ComposeResult:
        with Vertical(classes="menu-frame"):
            yield AmbientGlitchPanel(seed=111, classes="menu-flank-h")
            with Horizontal(classes="menu-frame-row"):
                yield AmbientGlitchPanel(seed=101, classes="menu-flank")
                with Vertical(classes="menu-column"):
                    yield Static(_LOGO, classes="menu-logo")
                    yield Static(
                        "Access to HackDox is reviewed by hand. You are the hand.",
                        classes="menu-subtitle",
                    )
                    # Above the buttons, so it stays visible on a short
                    # terminal (the column scrolls, and the bottom goes first).
                    yield Static("", id="menu-saves", classes="menu-saves")
                    with Vertical(classes="menu-buttons"):
                        yield Button("New Campaign", id="menu-new-game", variant="success")
                        yield Button("Continue Campaign", id="menu-continue")
                        yield Button("New Endless Run", id="menu-endless")
                        yield Button("Continue Endless", id="menu-continue-endless")
                        yield Button("Settings", id="menu-settings")
                        yield Button("Credits", id="menu-credits")
                        yield Button("Quit", id="menu-quit", variant="error")
                    yield Static("", id="menu-hint", classes="menu-hint")
                yield AmbientGlitchPanel(seed=202, classes="menu-flank")
            yield AmbientGlitchPanel(seed=212, classes="menu-flank-h")

    def on_mount(self) -> None:
        self._refresh_continue()

    def _refresh_continue(self) -> None:
        """#79 AC: each Continue is shown only when its save exists. #7: the
        campaign and Endless saves are separate, so each Continue button names
        its mode AND where that save stands, and a line under the buttons
        spells out that the two never overwrite each other."""
        camp = persistence.describe(GameMode.CAMPAIGN.value)
        endl = persistence.describe(GameMode.ENDLESS.value)

        btn = self.query_one("#menu-continue", Button)
        btn.disabled = camp is None
        btn.display = camp is not None
        if camp is not None:
            btn.label = f"Continue Campaign · {camp}"

        ebtn = self.query_one("#menu-continue-endless", Button)
        ebtn.disabled = endl is None
        ebtn.display = endl is not None
        if endl is not None:
            ebtn.label = f"Continue Endless · {endl}"

        saves: list[str] = []
        if camp is not None or endl is not None:
            saves.append("[dim]Campaign and Endless keep separate saves — "
                         "starting one never touches the other.[/]")
        best = endless.personal_best()
        if best is not None:
            acc = "—" if best.accuracy is None else f"{best.accuracy:.0%}"
            saves.append(f"[#c084fc]Endless best:[/] [b]{best.shifts}[/] shifts "
                         f"· {acc} accuracy")
        self.query_one("#menu-saves", Static).update("\n".join(saves))

        parts = ["[#00ff9f][b]N[/][/] New Campaign"]
        if camp is not None:
            parts.append("[#00ff9f][b]C[/][/] Continue Campaign")
        parts.append("[#00ff9f][b]E[/][/] New Endless")
        if endl is not None:
            parts.append("[#00ff9f][b]X[/][/] Continue Endless")
        parts += [
            "[#00ff9f][b]S[/][/] Settings",
            "[#00ff9f][b]R[/][/] Credits",
            "[#00ff9f][b]Q[/][/] Quit",
        ]
        self.query_one("#menu-hint", Static).update("   ·   ".join(parts))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        handlers = {
            "menu-new-game":         self.action_new_game,
            "menu-continue":         self.action_continue_game,
            "menu-endless":          self.action_new_endless,
            "menu-continue-endless": self.action_continue_endless,
            "menu-settings":         self.action_open_settings,
            "menu-credits":          self.action_open_credits,
            "menu-quit":             self.action_quit_app,
        }
        handler = handlers.get(event.button.id)
        if handler is not None:
            handler()

    def action_new_game(self) -> None:
        self.app.start_new_game()

    def action_continue_game(self) -> None:
        if not persistence.exists(GameMode.CAMPAIGN.value):
            return
        state = persistence.load(GameMode.CAMPAIGN.value)
        if state is None:
            return
        self.app.resume_game(state)

    def action_new_endless(self) -> None:
        """Start a fresh Endless run. If one is already in progress, the first
        press only warns; the second abandons it (it still counts toward the
        personal best — the shifts it survived were real)."""
        existing = persistence.load(GameMode.ENDLESS.value) \
            if persistence.exists(GameMode.ENDLESS.value) else None
        if existing is not None and not self._confirm_abandon:
            self._confirm_abandon = True
            self.query_one("#menu-hint", Static).update(
                f"[#ffd93d]An Endless run is in progress "
                f"({config.day_label(existing.current_day)}). Press "
                f"[b]New Endless Run[/b] again to abandon it and start over.[/]")
            return
        if existing is not None:
            endless.finish_run(existing)
        self._confirm_abandon = False
        self.app.start_endless_game()

    def action_continue_endless(self) -> None:
        if not persistence.exists(GameMode.ENDLESS.value):
            return
        state = persistence.load(GameMode.ENDLESS.value)
        if state is None:
            return
        self.app.resume_game(state)

    def action_open_settings(self) -> None:
        self.app.push_screen(SettingsScreen())

    def action_open_credits(self) -> None:
        self.app.push_screen(CreditsScreen())

    def action_quit_app(self) -> None:
        self.app.exit()
