"""Toast."""

from __future__ import annotations

from textual.widgets import Static


class Toast(Static):
    """Brief feedback after a verdict or tool error."""

    def __init__(self) -> None:
        super().__init__(id="toast")
        self.can_focus = False
        self.update("")

    def show(self, message: str, correct: bool) -> None:
        self.remove_class("toast-correct", "toast-wrong")
        self.add_class("toast-correct" if correct else "toast-wrong")
        self.update(message)
