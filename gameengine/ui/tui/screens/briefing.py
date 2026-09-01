"""BriefingScreen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Static
from gameengine import config
from gameengine.core import rules_engine
from gameengine.core.models import Day, GameState

from gameengine.ui.tui.widgets import (
    TypewriterLog,
)
from gameengine.ui.tui.screens._narration import (
    _play_overseer,
    _UNLOCK_LINES,
    rule_change_lines,
)


class BriefingScreen(Screen):
    BINDINGS = [
        Binding("space", "begin_day", "Begin shift"),
        Binding("q", "quit_app", "Quit"),
    ]

    def __init__(self, day: Day, narrative: str, state: GameState,
                 prev_day: Day | None = None) -> None:
        super().__init__()
        self._day       = day
        self._narrative = narrative
        self._state     = state
        self._overseer_log: TypewriterLog | None = None
        # The tool (if any) this day introduces — its unlock line + trigger.
        self._unlock_tool = config.tool_introduced_on(day.number)
        # #36: yesterday's ruleset, so the briefing can announce what moved.
        # None on day 1 — there is no yesterday, so nothing is broadcast.
        self._rule_changes = rules_engine.diff_rulesets(prev_day, day)

    def compose(self) -> ComposeResult:
        yield Static(f"[b][#7dd3c0]{self._day.title}[/][/]", classes="screen-title")
        with Container(id="overseer-panel"):
            yield Static("[b]Overseer:[/]", classes="speaker")
            # #3: the briefing dialogue types out through the TypewriterLog.
            # The log is NOT focused, so the screen keeps its Space=begin binding.
            self._overseer_log = TypewriterLog(id="briefing-overseer")
            yield self._overseer_log
        yield Static(
            "Press [#00ff9f][b]Space[/][/] to begin your shift.",
            classes="hint",
        )

    def on_mount(self) -> None:
        # Play the day's intro beat, then — on a tool-unlock day (#34) — the
        # Overseer's unlock line, carrying the tool as its `triggers` payload so
        # the flip lands exactly when that line finishes.
        _play_overseer(self._overseer_log, self._narrative)
        # #36: rule changes land AFTER the intro and BEFORE any unlock line, so
        # a day that both flips a rule and grants a tool reads in the order the
        # player will need it: today's mood, today's rules, then the new toy.
        # Amber, not red — this is a process note, not an alarm.
        for line in rule_change_lines(self._rule_changes, self._day.number):
            self._overseer_log.post("", line, color="#ffd93d")
        if self._unlock_tool:
            line = _UNLOCK_LINES.get(self._unlock_tool,
                                     f"New capability authorized: {self._unlock_tool.upper()}.")
            self._overseer_log.post("", line, color="#00ff9f",
                                    triggers=self._unlock_tool)

    def on_typewriter_log_finished(self, msg: "TypewriterLog.Finished") -> None:
        # #34: the unlock beat flips the tool on — not just cosmetically.
        if isinstance(msg.triggers, str):
            self._state.unlocked_tools.add(msg.triggers)

    def _ensure_unlocked(self) -> None:
        # Belt-and-suspenders: if the player presses Space to begin before the
        # unlock line has finished typing, the tool must still be granted for
        # the day to be playable. Adding to a set is idempotent, so this never
        # double-applies with the Finished trigger above.
        if self._unlock_tool:
            self._state.unlocked_tools.add(self._unlock_tool)

    def action_begin_day(self) -> None:
        self._ensure_unlocked()
        self.app.begin_intake()

    def action_quit_app(self) -> None:
        self.app.exit()
