"""EndlessOverScreen — the end of an Endless run (#7).

Replaces GameOverScreen for Endless. Says why the run ended (Site Health
collapse or rolling accuracy under the line), what the run achieved, and how
it stands against the personal best. The run's save slot has already been
cleared by `endless.finish_run` — a lost run can't be continued — and the
campaign's slot is untouched.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Static

from gameengine import config
from gameengine.core.endless import RunRecord
from gameengine.ui.tui.widgets import AmbientGlitchPanel


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x:.0%}"


class EndlessOverScreen(Screen):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("r", "restart", "New run"),
        Binding("m", "main_menu", "Main menu"),
        Binding("q", "quit_app", "Quit"),
    ]

    def __init__(self, record: RunRecord, prev_best: RunRecord | None,
                 new_best: bool, reason: str, rolling: float | None) -> None:
        super().__init__()
        self._record    = record
        self._prev_best = prev_best
        self._new_best  = new_best
        self._reason    = reason      # "health" | "accuracy"
        self._rolling   = rolling

    def _why(self) -> str:
        if self._reason == "health":
            return ("Site Health collapsed — the threats that got through "
                    "took the terminal down.")
        return (f"Your last {config.ENDLESS_ACCURACY_WINDOW} shifts averaged "
                f"{_pct(self._rolling)} — under the "
                f"{config.ENDLESS_ACCURACY_THRESHOLD:.0%} line, and the "
                f"gate went to another clerk.")

    def _best_line(self) -> str:
        r, b = self._record, self._prev_best
        if self._new_best:
            if b is None:
                return "[#00ff9f][b]★ FIRST RECORD SET[/][/]"
            return (f"[#00ff9f][b]★ NEW PERSONAL BEST[/][/]  "
                    f"[dim](was {b.shifts} shifts · {_pct(b.accuracy)})[/]")
        assert b is not None
        short = b.shifts - r.shifts
        return (f"[#6b7785]Personal best[/]  [b]{b.shifts}[/] shifts · "
                f"{_pct(b.accuracy)}  [dim]({short} shift"
                f"{'' if short == 1 else 's'} short)[/]")

    def compose(self) -> ComposeResult:
        # Same framed layout as the start menu (glitch border around a centred
        # column), so a run's end reads as part of the menu flow it returns to.
        r = self._record
        with Vertical(classes="menu-frame"):
            yield AmbientGlitchPanel(seed=313, classes="menu-flank-h")
            with Horizontal(classes="menu-frame-row"):
                yield AmbientGlitchPanel(seed=303, classes="menu-flank")
                with Vertical(classes="menu-column"):
                    yield AmbientGlitchPanel(seed=1721, classes="menu-modal-flank")
                    with Vertical(classes="menu-column-content"):
                        yield Static("[b][#ff5470]R U N   O V E R[/][/]",
                                     classes="menu-logo")
                        yield Static(self._why(), classes="menu-subtitle")
                        yield Static(
                            "\n".join([
                                f"[#6b7785]Shifts survived[/]   [b]{r.shifts}[/]",
                                f"[#6b7785]Run accuracy[/]      [b]{_pct(r.accuracy)}[/]",
                                f"[#6b7785]HackDollar$[/]       [b]{r.hackdollars}[/]",
                                "",
                                self._best_line(),
                            ]),
                            id="endless-over-stats",
                        )
                        yield Static(
                            "[#00ff9f][b]R[/][/] New Endless run   ·   "
                            "[#00ff9f][b]M[/][/] Main menu   ·   "
                            "[#00ff9f][b]Q[/][/] Quit",
                            classes="menu-hint",
                        )
                    yield AmbientGlitchPanel(seed=1731, classes="menu-modal-flank")
                yield AmbientGlitchPanel(seed=404, classes="menu-flank")
            yield AmbientGlitchPanel(seed=414, classes="menu-flank-h")

    def action_restart(self) -> None:
        self.app.start_endless_game()

    def action_main_menu(self) -> None:
        self.app.to_main_menu()

    def action_quit_app(self) -> None:
        self.app.exit()
