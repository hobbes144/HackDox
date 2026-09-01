"""ToolTerminal."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static
from gameengine.core import tools_bridge


class ToolTerminal(VerticalScroll):
    """Displays results for one tool. Persists for the candidate review."""

    _EMPTY = "[dim italic]Run the tool to see results here.[/]"

    def __init__(self, widget_id: str, tool_label: str) -> None:
        super().__init__(id=widget_id, classes="panel tool-right")
        self.border_title = f" {tool_label} Terminal "
        self._empty_label: Static | None = None

    def compose(self) -> ComposeResult:
        self._empty_label = Static(self._EMPTY, classes="terminal-empty")
        yield self._empty_label

    def clear(self) -> None:
        self.remove_children()
        self._empty_label = Static(self._EMPTY, classes="terminal-empty")
        self.mount(self._empty_label)

    def set_initial_content(self, lines: tuple[str, ...]) -> None:
        """Pre-populate with always-visible lines (no tool cost).
        Clears any previous state first; subsequent add_result calls append below.
        """
        self.remove_children()
        self._empty_label = None
        self.mount(Static("\n".join(lines), classes="terminal-row"))

    def add_result(self, result: tools_bridge.ToolResult) -> None:
        if self._empty_label is not None:
            self._empty_label.remove()
            self._empty_label = None

        sev_color = {"minor": "#ffd93d", "major": "#ff8c42", "critical": "#ff5470"}
        rows: list[str] = []

        # ── Header ────────────────────────────────────────────────────
        if result.filtered:
            rows.append(
                f"[#c084fc][b]FILTER APPLIED[/][/]  [italic]{result.summary}[/]"
            )
        else:
            rows.append(
                f"[#7dd3c0][b]{result.tool.value.upper()}[/][/]  "
                f"[italic]{result.summary}[/]"
            )

        # ── Raw data block ────────────────────────────────────────────
        # Intermediate output (e.g. ghostscan platform sweep, commit email,
        # HIBP result). Player reads this and draws their own conclusions.
        if result.raw_lines:
            rows.append("")
            rows.extend(result.raw_lines)

        # ── Confirmed findings ────────────────────────────────────────
        # Only populated by filter runs that explicitly confirm a discrepancy.
        if result.findings:
            rows.append("")
            rows.append("[#6b7785]── confirmed findings ─────────────────────────[/]")
            for d in result.findings:
                col = sev_color.get(d.severity, "#c8d4e1")
                rows.append(
                    f"  [{col}]●[/] [b]{d.kind.value}[/]"
                    f" [dim]({d.severity})[/] — {d.description}"
                )

        rows.append("")
        self.mount(Static("\n".join(rows), classes="terminal-row"))

    def set_result(self, result: tools_bridge.ToolResult) -> None:
        """REPLACE the terminal content with one result (issue #28 — the
        ghostscan filter re-renders the report in place instead of stacking
        a second copy below the first)."""
        self.remove_children()
        self._empty_label = None
        self.add_result(result)
        self.scroll_home(animate=False)

    def add_lines(self, lines: list[str] | tuple[str, ...]) -> None:
        """Append a raw markup block (used by the stego stamp log)."""
        if self._empty_label is not None:
            self._empty_label.remove()
            self._empty_label = None
        block = Static("\n".join(lines) + "\n", classes="terminal-row")
        self.mount(block)
        self.scroll_end(animate=False)

    def add_no_submission(self, label: str) -> None:
        if self._empty_label is not None:
            self._empty_label.remove()
            self._empty_label = None
        self.mount(Static(
            f"[#6b7785][italic]No {label} submitted by this candidate.[/][/]",
            classes="terminal-empty"
        ))
