"""LogListPanel — the Logwatch page's right-hand auth log (2026-09-19).

Modelled on BreachListPanel (the Ghostscan page's right column), with one
deliberate difference: it starts SEALED. The Logwatch page's free tier is the
Activity Report in the centre column; the raw log is what ⏱ buys. So:

  sealed    placeholder only — how many entries exist, how to pull them
  open      after the base run (L): the full shared day log, the target's
            rows in yellow, no labels (Log Analyzer HUD adds neutral ▸ marks)
  filtered  after the filter (F): the same log with ▲ VIOLATION labels

Rows never wrap — each log row is one screen line and the panel scrolls
horizontally for long rows — so a row's line index is its scroll offset and
the [ / ] target-row jump can land exactly on it.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import ScrollableContainer
from textual.widgets import Static


class LogListPanel(ScrollableContainer):
    SEALED   = "sealed"
    OPEN     = "open"
    FILTERED = "filtered"

    def __init__(self) -> None:
        super().__init__(id="log-list-panel", classes="panel")
        self.border_title = " Auth Log "
        self.state: str = self.SEALED
        self._content: Static | None = None
        self._targets: list[int] = []
        self._cursor: int = -1

    def compose(self) -> ComposeResult:
        self._content = Static("[dim italic]Awaiting candidate...[/]",
                               id="log-list-content")
        yield self._content

    # ── Public API ────────────────────────────────────────────────────────

    def seal(self, entry_count: int, cost: int | None = None) -> None:
        """Reset to the sealed placeholder for a new candidate."""
        self.state = self.SEALED
        self._targets, self._cursor = [], -1
        self.border_subtitle = ""
        cost_s = f" — [#ffb454]{cost} ⏱[/]" if cost is not None else ""
        lines = [
            "",
            "[#ffb454][b]▌ AUTH LOG — SEALED[/][/]",
            "",
            f"  [#c8d4e1]{entry_count}[/] [#6b7785]entries recorded today, "
            f"across every account.[/]",
            "",
            f"  [#6b7785]Pull it with[/] [#00ff9f][b]L[/][/] "
            f"[#6b7785](or[/] [#00ff9f]analyze[/][#6b7785])[/]{cost_s}",
            "",
            "  [dim]Read the Activity Report first — decide whether[/]",
            "  [dim]this account's numbers are worth the ⏱.[/]",
        ]
        self._set(lines)

    def open(self, lines: tuple[str, ...] | list[str], target_rows: list[int],
             filtered: bool = False) -> None:
        """Show the log. `target_rows` are the line indices of the target's rows."""
        self.state = self.FILTERED if filtered else self.OPEN
        self._targets = list(target_rows)
        self._cursor = -1
        self._set(list(lines))
        self.border_subtitle = (f" {len(self._targets)} rows · \\[ ] jump "
                                if self._targets else "")
        if self._targets:
            self.jump(1)
        else:
            self.scroll_home(animate=False)

    def jump(self, delta: int) -> bool:
        """Scroll to the next (+1) / previous (-1) target row. False if sealed."""
        if self.state == self.SEALED or not self._targets:
            return False
        self._cursor = (self._cursor + delta) % len(self._targets)
        row = self._targets[self._cursor]
        self.scroll_to(y=max(0, row - 3), animate=False)
        self.border_subtitle = (f" row {self._cursor + 1}/{len(self._targets)}"
                                f" · \\[ ] jump ")
        return True

    @property
    def target_rows(self) -> list[int]:
        return list(self._targets)

    @property
    def cursor(self) -> int:
        return self._cursor

    # ── Internal ──────────────────────────────────────────────────────────

    def _set(self, lines: list[str]) -> None:
        if self._content is None:
            return
        self._content.update("\n".join(lines))
