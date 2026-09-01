"""EODScreen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Static
from gameengine import config
from gameengine.core import persistence
from gameengine.core.models import Day, GameState, Performance

from gameengine.ui.tui.widgets import (
    TypewriterLog,
)
from gameengine.ui.tui.screens._narration import (
    _play_overseer,
)


class EODScreen(Screen):
    BINDINGS = [
        Binding("space", "continue_game", "Continue"),
        Binding("q", "quit_app", "Quit"),
    ]

    def __init__(self, day: Day, state: GameState, narrative: str,
                 performance: Performance, hd_earned: int = 0,
                 hd_bonus: int = 0, health_delta: float = 0.0) -> None:
        super().__init__()
        self._day          = day
        self._state        = state
        self._narrative    = narrative
        self._performance  = performance
        self._hd_earned    = hd_earned      # HD$ from verdicts today (issue #21)
        self._hd_bonus     = hd_bonus       # HD$ Site Health bonus (issue #20)
        self._health_delta = health_delta   # Site Health change over the day
        self._overseer_log: TypewriterLog | None = None

    def compose(self) -> ComposeResult:
        yield Static(f"[b][#7dd3c0]End of {self._day.title}[/][/]",
                     classes="screen-title")
        with Container(id="eod-summary"):
            correct = sum(1 for r in self._state.pending_results if r.correct)
            total   = len(self._state.pending_results)
            yield Static(f"Verdicts: [b]{correct}[/]/{total} correct")
            yield Static(
                f"Computing hours: [#ffb454][b]{self._state.compute_hours} ⏱[/][/] "
                f"left unspent  [dim](daily budget — does not carry over)[/]"
            )
            h    = self._state.site_health
            hcol = ("#00ff9f" if h >= config.SITE_HEALTH_REWARD_THRESHOLD else
                    "#ffd93d" if h >= config.SITE_HEALTH_LOSS_THRESHOLD + 15 else
                    "#ff5470")
            dcol = "#00ff9f" if self._health_delta >= 0 else "#ff5470"
            yield Static(
                f"Site Health: [{hcol}][b]{h:.0f}%[/][/]  "
                f"[{dcol}]({self._health_delta:+.1f} today)[/]"
            )
            hd_bonus_str = (f"  [#00ff9f]+{self._hd_bonus}[/] health bonus"
                            if self._hd_bonus else "  [dim](no health bonus)[/]")
            yield Static(
                f"HackDollar$: [#00ff9f]+{self._hd_earned}[/] earned{hd_bonus_str}"
                f"  ·  balance [#00ff9f][b]{self._state.hackdollars} HD$[/][/]"
            )
            # #4: name the rate this shift actually paid at, so the decay is
            # visible as a number rather than felt as a vague slump.
            yield Static(
                f"[dim]Rate today: {config.DAY_REWARD_PAYOUT(self._day.number, True)} HD$ "
                f"per correct admit · "
                f"{config.DAY_REWARD_PAYOUT(self._day.number, False)} per correct deny[/]"
            )
            yield Static(f"Alignment: {self._state.alignment:+d}")
            yield Static("")
            for r in self._state.pending_results:
                tag  = "verdict-correct" if r.correct else "verdict-wrong"
                mark = "✓" if r.correct else "✗"
                bonus_str = f"  board+{r.board_bonus}HD$" if r.board_bonus else ""
                yield Static(
                    f"[{tag}]{mark}[/]  {r.archetype.value:<14}  "
                    f"you {r.player_verdict.value:<5}  "
                    f"[#6b7785]⛨{r.site_health_delta:+.1f}  "
                    f"+{r.hackdollar_delta}HD${bonus_str}  "
                    f"Align {r.alignment_delta:+d}[/]"
                )
        with Container(id="overseer-panel"):
            yield Static("[b]Overseer:[/]", classes="speaker")
            self._overseer_log = TypewriterLog(id="eod-overseer")
            yield self._overseer_log
        yield Static(
            f"Performance: [b]{self._performance.value}[/]   ·   "
            "Press [#00ff9f][b]Space[/][/] to save and continue.",
            classes="hint",
        )

    def on_mount(self) -> None:
        # #3: EOD Overseer dialogue types out; the screen keeps Space=continue.
        _play_overseer(self._overseer_log, self._narrative)

    def action_continue_game(self) -> None:
        persistence.save(self._state)
        self.app.show_between_day()   # between-day menu next (issue #22)

    def action_quit_app(self) -> None:
        self.app.exit()
