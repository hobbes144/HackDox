"""CommandBar."""

from __future__ import annotations

from textual.widgets import Static

from gameengine.ui.tui.shared import (
    _COMMAND_ALIASES,
)


class CommandBar(Static):
    """Always-visible command-line strip at the bottom of the intake screen.

    IntakeScreen.on_key() funnels all printable keypresses here.
    Enter submits; Backspace deletes; Escape clears without executing.
    See _COMMAND_ALIASES for the full command vocabulary.
    """

    can_focus = False

    def __init__(self) -> None:
        super().__init__(id="command-bar")
        self._buffer   = ""
        self._response = (
            "type a command and press Enter  ·  "
            "try: recon · crack · analyze · extract · admit · deny · help"
        )
        self._is_error = False


    def on_mount(self) -> None:
        self._push()

    # Buffer management

    def get_buffer(self) -> str:
        return self._buffer

    def clear_buffer(self) -> None:
        self._buffer = ""
        self._push()

    def append_char(self, ch: str) -> None:
        self._buffer += ch
        self._push()

    def backspace(self) -> None:
        if self._buffer:
            self._buffer = self._buffer[:-1]
            self._push()

    def set_response(self, message: str, *, error: bool = False) -> None:
        self._response = message
        self._is_error = error
        self._push()

    # Render

    def _push(self) -> None:
        """Push current state to Static via update(), which parses Rich markup."""
        resp_col = "#ff5470" if self._is_error else "#7dd3c0"
        resp = (self._response or "")[:140]
        markup = (
            f"[{resp_col}]  {resp}[/]\n"
            f"[#00ff9f]hackdox@terminal:~$[/]  [#00ff9f]{self._buffer}[/][#00ff9f]█[/]"
        )
        self.update(markup)
