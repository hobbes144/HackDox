"""StatusHeader."""

from __future__ import annotations

from textual.message import Message
from textual.widgets import Static
from gameengine import config
from gameengine.core import tools_bridge
from gameengine.core.models import Day, GameState

from gameengine.ui.tui.shared import (
    _PAGE_NAMES,
    _PAGE_TOOL,
)


class StatusHeader(Static):
    """One-line status + page-tab strip.

    Batch-3 task #9: the tab strip is clickable, not just keyboard-driven
    ([1]-[5]). `on_tab_click` is a plain callback (not a Textual Message) —
    the screen sets it to its own `_goto_page`, so a click and a keypress
    both route through the exact same lock-check/page-switch logic and can
    never drift apart into two behaviors.
    """

    can_focus = False

    def __init__(self, state: GameState, day: Day, slot_index: int,
                 page_index: int = 0) -> None:
        super().__init__(id="status-header")
        self.state       = state
        self.day         = day
        self.slot_index  = slot_index
        self.page_index  = page_index
        self.on_tab_click: "Callable[[int], None] | None" = None
        # (start, end) cell-offset ranges for each tab on the tab-strip
        # line, recomputed every render() so a click always maps against
        # what's actually on screen right now.
        self._tab_ranges: list[tuple[int, int]] = []

    def render(self) -> str:
        from rich.text import Text

        h    = self.state.site_health
        hcol = ("#00ff9f" if h >= config.SITE_HEALTH_REWARD_THRESHOLD else
                "#ffd93d" if h >= config.SITE_HEALTH_LOSS_THRESHOLD + 15 else
                "#ff5470")
        # ⏱ is a finite daily pool now (issue #27) — colour the balance by
        # scarcity and keep every tool's effective cost in view.
        cp   = self.state.compute_hours
        ccol = "#ffb454" if cp >= 15 else "#ff8c42" if cp >= 6 else "#ff5470"
        costs = "·".join(
            f"{k}{tools_bridge.tool_cost(self.state, t)}"
            for k, t in (("G", "ghostscan"), ("H", "hashcrack"),
                         ("L", "logwatch"),  ("S", "stegotool"))
        )
        n_credits   = self.state.hackdox_credits
        max_credits = config.HACKDOX_CREDIT_MAX
        creds_pips  = "▮" * n_credits + "▯" * max(0, max_credits - n_credits)
        # Health only moves at end of day (#20 rework) — show the pending
        # delta accumulated by today's verdicts so the player can track it.
        pend = sum(r.site_health_delta for r in self.state.pending_results)
        pend_s = f" [dim]({pend:+.1f} eod)[/]" if pend else ""
        align  = self.state.alignment
        bar    = ""
        for v in range(-4, 5):
            bar += "●" if v == max(-4, min(4, align)) else "·"
        align_col = "#ff5470" if align < 0 else "#00ff9f"

        def _tab(i: int, n: str) -> str:
            tool = _PAGE_TOOL[i]
            if tool is not None and tool not in self.state.unlocked_tools:
                # Locked tool (#33): dim + ⊘, visibly distinct from an
                # unlocked-but-inactive tab (○) and the active tab (◉).
                return f"[#3d4450]⊘ [{i+1}]{n}[/]"
            if i == self.page_index:
                return f"[b]◉ [{i+1}]{n}[/]"
            return f"[dim]○ [{i+1}]{n}[/]"

        tab_markups = [_tab(i, n) for i, n in enumerate(_PAGE_NAMES)]
        tabs = "  ".join(tab_markups)
        # Cell-offset ranges for on_click's hit-testing — recomputed every
        # render so they always match what's actually drawn (tab widths are
        # stable here, but this makes no assumption of that).
        ranges: list[tuple[int, int]] = []
        _off = 0
        for markup in tab_markups:
            w = Text.from_markup(markup).cell_len
            ranges.append((_off, _off + w))
            _off += w + 2   # 2-space separator between tabs
        self._tab_ranges = ranges

        left = (
            f"[#00ff9f][b]HACKDOX[/][/]  [dim]│[/]  [b]{self.day.title}[/]  "
            f"[dim]│[/]  [{self.slot_index + 1}/{self.day.candidate_count}]"
        )
        # Batch-3 task #8: site health / HD$ / credits get their own labeled,
        # solid-colour badge — bold dark text on a filled colour chip — rather
        # than bare symbols crammed together behind a thin middot separator.
        # The whole resource cluster is then right-justified against the
        # widget's actual render width (self.size.width; a fallback constant
        # covers the unmounted case, e.g. a direct render() call in a test)
        # instead of sitting left-clustered right after day/slot — "spread
        # out" and "more visible" across a genuinely full-width bar.
        right = (
            f"[{ccol}][b]{cp} ⏱[/][/] [dim]{costs}[/]"
            f"   [b #0b0e10 on {hcol}] ⛨ HEALTH {h:.0f}% [/]{pend_s}"
            f"   [b #0b0e10 on #00ff9f] HD$ {self.state.hackdollars} [/]"
            f"   [b #0b0e10 on #c084fc] CR {n_credits}/{max_credits} [/] [#c084fc]{creds_pips}[/]"
            f"   [{align_col}]{bar}[/]"
        )

        width   = self.size.width or config.STATUS_BAR_FALLBACK_WIDTH
        left_w  = Text.from_markup(left).cell_len
        right_w = Text.from_markup(right).cell_len
        pad     = max(2, width - left_w - right_w)

        return f"{left}{' ' * pad}{right}\n{tabs}"

    def on_click(self, event) -> None:
        if event.button != 1 or self.on_tab_click is None:
            return
        gutter = self.gutter
        x = event.x - gutter.left
        y = event.y - gutter.top
        if y != 1:   # row 0 = resource bar, row 1 = the tab strip
            return
        for i, (start, end) in enumerate(self._tab_ranges):
            if start <= x < end:
                self.on_tab_click(i)
                return

    def refresh_status(self, state: GameState, slot_index: int,
                       page_index: int) -> None:
        self.state      = state
        self.slot_index = slot_index
        self.page_index = page_index
        self.refresh()
