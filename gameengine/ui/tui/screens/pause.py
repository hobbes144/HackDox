"""PauseScreen.

Reachable via Escape from every screen in the campaign loop — anywhere the
player is "in the game" with progress that can be lost, per Nick (2026-09):
BriefingScreen, IntakeScreen, EODScreen, BetweenDayScreen. NOT reachable
from IntroScreen (that's the main menu, Escape doesn't need to interrupt it)
or any future Load screen. GameOverScreen/CampaignEndScreen are deliberately
excluded too — those are terminal states with their own restart/quit
bindings, not a run in progress; flag to Nick if he wants Pause there too.

IntakeScreen wires this itself inside its on_key override (Escape is
checked first, ahead of its minigame-mode/command-bar handling — see
BUILD_PLAN_MenuSystem_2026-09.md). Briefing/EOD/BetweenDay have no such
override, so each just adds a normal `Binding("escape", "open_pause", ...)`
+ `action_open_pause` — Textual's declarative BINDINGS resolve those with no
extra plumbing needed.

A lightweight ModalScreen, not a full glitch transition: pausing/resuming is
meant to be instant and reversible, unlike a day-to-day screen swap.

Both Quit actions save the in-progress run first (`HackDoxApp.save_progress`,
a no-op if nothing is in progress) — matches what BetweenDayScreen's own
quit used to do before Nick had it removed in favor of Pause being the one
place quitting happens; see BUILD_PLAN_MenuSystem_2026-09.md.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from gameengine.ui.tui.screens.settings import SettingsScreen


class PauseScreen(ModalScreen):
    """Resume / Settings / Quit to Main Menu / Quit to Desktop."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "resume", "Resume", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="pause-modal"):
            yield Static("[#7dd3c0][b]PAUSED[/][/]", id="pause-title")
            with Vertical(id="pause-buttons"):
                yield Button("Resume", id="pause-resume", variant="success")
                yield Button("Settings", id="pause-settings")
                yield Button("Quit to Main Menu", id="pause-quit-menu")
                yield Button("Quit to Desktop", id="pause-quit-desktop", variant="error")
            yield Static("[dim]Esc to resume[/]", id="pause-hint")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "pause-resume":
            self.action_resume()
        elif event.button.id == "pause-settings":
            self.action_open_settings()
        elif event.button.id == "pause-quit-menu":
            self.action_quit_to_main_menu()
        elif event.button.id == "pause-quit-desktop":
            self.action_quit_to_desktop()

    def action_resume(self) -> None:
        self.dismiss()

    def action_open_settings(self) -> None:
        self.app.push_screen(SettingsScreen())

    def action_quit_to_main_menu(self) -> None:
        self.app.save_progress()
        self.dismiss()
        self.app.quit_to_main_menu()

    def action_quit_to_desktop(self) -> None:
        self.app.save_progress()
        self.app.exit()
