"""ReferencePanel."""

from __future__ import annotations

from typing import ClassVar

from textual.widgets import Static

from gameengine.ui.tui.shared import (
    _REF_CANDIDATE,
    _REF_GHOSTSCAN,
    _REF_HASHCRACK,
    _REF_LOGWATCH,
    _REF_STEGOTOOL,
)


class ReferencePanel(Static):
    """Accept/reject reference data — content varies by mode."""

    can_focus = True

    _CONTENT: ClassVar[dict[str, str]] = {
        "candidate": _REF_CANDIDATE,
        "ghostscan": _REF_GHOSTSCAN,
        "hashcrack": _REF_HASHCRACK,
        "logwatch":  _REF_LOGWATCH,
        "stegotool": _REF_STEGOTOOL,
    }

    def __init__(self, mode: str, widget_id: str) -> None:
        super().__init__(id=widget_id, classes="panel")
        self.border_title = " Reference "
        self._mode = mode

    def update_content(self, text: str) -> None:
        """Override static content with dynamic text (e.g. auth log)."""
        self._override = text
        self.refresh()

    def render(self) -> str:
        if hasattr(self, "_override") and self._override is not None:
            return self._override
        return self._CONTENT.get(self._mode, "")
