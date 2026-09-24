"""CampaignEndScreen — the campaign's three authored epilogues (issue #42).

Reached explicitly when `GameState.current_day > config.CAMPAIGN_LAST_DAY`
(the primary path, checked in `app.py`'s `advance_day` before it even
attempts to load the next day) or, as a defensive fallback, if `load_day`
ever raises `FileNotFoundError` for a day past the authored campaign — which
in practice is the same condition, reached a different way.

A day that ISN'T past the campaign ceiling — a lab run cut short
(`app.py`'s `_lab_day` path), or the day-1-misconfigured-install edge case
`load_day` guards with the same exception — falls back to the pre-#42
"content not written yet" stub instead of narrating a false ending.

Ending selection is a pure function of `GameState`
(`core.overseer.ending_for_state`), so it can be exercised by tests without
booting Textual — see `test_engine_foundation.py`'s campaign-ending tests.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Static
from textual.screen import Screen

from gameengine import config
from gameengine.core import overseer
from gameengine.core.models import GameState


class CampaignEndScreen(Screen):
    """Shown at the true end of the campaign, or when content is missing.

    `is_stub` / `ending` are the pure selection logic `compose()` renders —
    pulled out so a test can drive the exact same decision `compose()` makes
    without booting Textual (issue #42's testability requirement).
    """

    BINDINGS: ClassVar[list[Binding]] = [Binding("q", "quit_app", "Quit")]

    def __init__(self, state: GameState) -> None:
        super().__init__()
        self._state = state

    @property
    def is_stub(self) -> bool:
        """True when there's no real ending to show yet — a lab run cut
        short, or a day short of the authored campaign ceiling."""
        return self._state.current_day <= config.CAMPAIGN_LAST_DAY

    @property
    def ending(self) -> overseer.Ending | None:
        """The selected `Ending`, or `None` while `is_stub` is true."""
        if self.is_stub:
            return None
        return overseer.ending_for_state(self._state)

    def compose(self) -> ComposeResult:
        with Container(id="splash"):
            ending = self.ending
            if ending is not None:
                yield Static(
                    f"[b][#00ff9f]{ending.title}[/][/]", classes="title")
                for paragraph in ending.paragraphs:
                    yield Static(paragraph, classes="subtitle")
            else:
                yield Static(
                    "[b][#00ff9f]TO BE CONTINUED[/][/]", classes="title")
                yield Static(
                    f"Day {self._state.current_day} isn't written yet. "
                    "Your save is stored — the campaign resumes when the "
                    "content lands.",
                    classes="subtitle",
                )
            yield Static("[#00ff9f][b]Q[/][/]  Quit", classes="hint")

    def action_quit_app(self) -> None:
        self.app.exit()
