"""ReferencePanel."""

from __future__ import annotations

from typing import ClassVar

from textual.widgets import Static

from gameengine.ui.tui.shared import REFERENCE_BUILDERS


class ReferencePanel(Static):
    """Accept/reject reference data — content varies by mode."""

    can_focus = True

    # Built on demand from shared.REFERENCE_BUILDERS (2026-09-19) so the
    # default text is derived from config/tools_bridge like the live panels
    # IntakeScreen pushes via update_content().
    _CONTENT: ClassVar[dict] = REFERENCE_BUILDERS

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
        builder = self._CONTENT.get(self._mode)
        return builder() if builder else ""
