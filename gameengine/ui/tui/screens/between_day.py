"""BetweenDayScreen."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Static

from gameengine import config
from gameengine.core import persistence, scoring, tools_bridge
from gameengine.core.audio import sound_manager
from gameengine.core.models import Day, GameState
from gameengine.ui.tui.screens._narration import (
    _play_overseer,
)
from gameengine.ui.tui.widgets import (
    TypewriterLog,
)


class BetweenDayScreen(Screen):
    """Between-day menu (issues #18/#22) — the campaign's connective tissue.

    Runs after the end-of-day summary and before the next day's intro.
    Three regions: performance summary (the day's numbers landing), Overseer
    contact (tutorial / foreshadowing / the hostility arc), and the
    HackDollar$ shop (upgrades #23, HackDox Credits #19/#25, ⏱ capacity).
    Purchases deduct HackDollar$ and persist immediately.
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("up",    "cursor_up",   "Up",   show=False),
        Binding("down",  "cursor_down", "Down", show=False),
        Binding("enter", "buy",         "Buy",  show=False),
        Binding("space", "buy",         "Buy",  show=False),
        Binding("n",     "next_day",    "Next day"),
        Binding("q",     "quit_app",    "Quit"),
    ]

    def __init__(self, day: Day, state: GameState, narrative: str,
                 hd_earned: int = 0, hd_bonus: int = 0,
                 health_delta: float = 0.0) -> None:
        super().__init__()
        self._day          = day
        self._state        = state
        self._narrative    = narrative
        self._hd_earned    = hd_earned
        self._hd_bonus     = hd_bonus
        self._health_delta = health_delta
        self._cursor       = 0
        self._status_msg   = ""
        self._status_err   = False
        # Shop catalog: consumables/capacity first (under a "General" header),
        # then permanent upgrades grouped into per-tool sub-categories (#2) —
        # "header" rows are non-purchasable and skipped by cursor navigation.
        items: list[tuple[str, str, int, str, str]] = [
            ("header", "", 0, "General", ""),
            ("credit",   "hackdox_credit", config.SHOP_PRICE_CREDIT,
             "HackDox Credit +1",
             f"ground-truth reveal charge (max {config.HACKDOX_CREDIT_MAX} slots)"),
            ("capacity", "compute_capacity", config.SHOP_PRICE_CAPACITY,
             f"Compute Capacity +{config.COMPUTE_CAPACITY_STEP} ⏱",
             "permanently raise the per-shift computing-hours budget"),
        ]
        by_category: dict[str, list[tuple[str, str, int, str]]] = {
            cat: [] for cat in config.UPGRADE_CATEGORY_ORDER
        }
        for uid, label, price, desc in config.UPGRADE_CATALOG:
            cat = config.UPGRADE_CATEGORY[uid]
            by_category[cat].append((uid, label, price, desc))
        for cat in config.UPGRADE_CATEGORY_ORDER:
            cat_upgrades = by_category[cat]
            if not cat_upgrades:
                continue
            items.append(("header", "", 0, cat, ""))
            for uid, label, price, desc in cat_upgrades:
                items.append(("upgrade", uid, price, label, desc))
        self._items = items
        self._cursor = next(
            (i for i, it in enumerate(items) if it[0] != "header"), 0)
        self._summary_w = Static(id="bd-summary", classes="panel")
        self._shop_w    = Static(id="bd-shop", classes="panel")

    def compose(self) -> ComposeResult:
        yield Static(
            f"[b][#7dd3c0]HACKDOX — NIGHT OF DAY {self._day.number}[/][/]",
            classes="screen-title",
        )
        with Horizontal(id="bd-root"):
            with Vertical(id="bd-left"):
                yield self._summary_w
                with Container(id="bd-overseer"):
                    yield Static("[b]Overseer:[/]", classes="speaker")
                    # #3: the 3rd TypewriterLog host (called out in the issue's
                    # own comment). Not focused, so Space still buys in the shop.
                    self._overseer_log = TypewriterLog(id="bd-overseer-text")
                    yield self._overseer_log
            yield self._shop_w
        yield Static(
            "[#00ff9f][b]↑↓[/][/] browse shop  ·  [#00ff9f][b]Enter[/][/] buy  ·  "
            "[#00ff9f][b]N[/][/] begin next day  ·  [#00ff9f][b]Q[/][/] quit",
            classes="hint",
        )

    def on_mount(self) -> None:
        self._summary_w.border_title = " Shift Report "
        self._shop_w.border_title    = " HackDollar$ Shop "
        _play_overseer(self._overseer_log, self._narrative)
        self._repaint()

    # ── Rendering ─────────────────────────────────────────────────────

    def _repaint(self) -> None:
        self._summary_w.update(self._summary_text())
        self._shop_w.update(self._shop_text())

    def _next_shift_terms(self) -> str:
        """#4: what next shift will pay, and what it will charge.

        The difficulty curve is only legible as escalation if the player can
        see it arriving. Shown here rather than on the EOD screen because this
        is the screen where they decide what to spend HackDollar$ on — knowing
        tool costs are about to step up is exactly the input to that decision.
        Only rates that actually CHANGE are called out, so a mid-tutorial day
        doesn't nag about a curve that hasn't moved yet.
        """
        st   = self._state
        d    = self._day.number
        nxt  = d + 1
        bits: list[str] = []

        pay_now, pay_next = (config.DAY_REWARD_PAYOUT(d, True),
                             config.DAY_REWARD_PAYOUT(nxt, True))
        if pay_next != pay_now:
            bits.append(f"[#ffd93d]correct admit {pay_now} → {pay_next} HD$[/]")
        else:
            bits.append(f"[dim]correct admit {pay_next} HD$[/]")

        costs_now  = {t: tools_bridge.tool_cost(st, t) for t in config.TOOL_COSTS}
        costs_next = {t: config.DAY_TOOL_COST(t, nxt, st.upgrades)
                      for t in config.TOOL_COSTS}
        strip = " ".join(
            f"{t[0].upper()}{costs_next[t]}" for t in sorted(config.TOOL_COSTS))
        if costs_next != costs_now:
            bits.append(f"[#ff8c42]tool costs rise → {strip}[/]")
        else:
            bits.append(f"[dim]tools {strip}[/]")
        return "  ·  ".join(bits)

    def _summary_text(self) -> str:
        st      = self._state
        results = st.pending_results
        correct = sum(1 for r in results if r.correct)
        total   = len(results)
        # Issue #27: ⏱ is a spend-only daily pool — spent = budget − leftover.
        budget      = config.daily_compute_budget(self._day.number,
                                                  st.compute_capacity)
        spent       = max(0, budget - st.compute_hours)
        next_budget = config.daily_compute_budget(self._day.number + 1,
                                                  st.compute_capacity)
        # #38: how often the literal ruleset and the moral ground truth pulled
        # in different directions this shift.
        diverged = sum(1 for r in results if r.tracks_diverge)
        board   = sum(r.board_bonus for r in results)
        board_max = max(1, total * config.BOARD_ACCURACY_MAX_BONUS)
        board_pct = round(100 * board / board_max)
        h    = st.site_health
        hcol = ("#00ff9f" if h >= config.SITE_HEALTH_REWARD_THRESHOLD else
                "#ffd93d" if h >= config.SITE_HEALTH_LOSS_THRESHOLD + 15 else
                "#ff5470")
        filled = max(0, min(20, round(h / 5)))
        bar    = "█" * filled + "░" * (20 - filled)
        dcol   = "#00ff9f" if self._health_delta >= 0 else "#ff5470"
        acol   = "#ff5470" if st.alignment < 0 else "#00ff9f"
        align_lbl = ("Dark Web" if st.alignment < 0 else
                     "White Hat" if st.alignment > 0 else "Neutral")
        hd_bonus_str = (f"  [#00ff9f]+{self._hd_bonus}[/] health bonus"
                        if self._hd_bonus else "  [dim](no health bonus)[/]")
        return "\n".join([
            f"[#6b7785]Verdicts[/]        [b]{correct}[/]/{total} correct",
            (f"[#6b7785]⏱ spent[/]         [#ffb454]−{spent}[/] of {budget}"
            f"   [dim](fresh budget next shift: {next_budget} ⏱ — no carry-over)[/]"),
            f"[#6b7785]Next shift[/]      {self._next_shift_terms()}",
            f"[#6b7785]Board accuracy[/]  {board_pct}%  [dim](paid as HD$ bonus)[/]",
            f"[#6b7785]Alignment[/]       [{acol}]{st.alignment:+d} ({align_lbl})[/]"
            + (f"   [#c084fc]· {diverged} verdict(s) where the book and your "
               f"conscience disagreed[/]" if diverged else ""),
            "",
            f"[#6b7785]HackDollar$[/]     [#00ff9f]+{self._hd_earned}[/] verdicts{hd_bonus_str}",
            f"[#6b7785]Balance[/]         [#00ff9f][b]{st.hackdollars} HD$[/][/]",
            "",
            (f"[#6b7785]Site Health[/]     [{hcol}]{bar}[/]  [{hcol}][b]{h:.0f}%[/][/]"
            f"  [{dcol}]({self._health_delta:+.1f} applied at end of day)[/]"),
            (f"[dim]health only moves at shift end · game over below "
            f"{config.SITE_HEALTH_LOSS_THRESHOLD:.0f}%"
            f" · bonus above {config.SITE_HEALTH_REWARD_THRESHOLD:.0f}%[/]"),
        ] + ([
            "",
            (f"[#ff5470][b]▼ SITE HEALTH BELOW {config.SITE_HEALTH_LOSS_THRESHOLD:.0f}% "
            f"— HACKDOX IS LOST[/][/]"),
            ("[#ff5470]The day's admissions took the site down. "
            "Press N to face the consequences.[/]"),
        ] if scoring.health_below_loss(st) else []))

    def _shop_text(self) -> str:
        st = self._state
        lines = [
            (f"[#6b7785]balance[/] [#00ff9f][b]{st.hackdollars} HD$[/][/]"
            f"   [#6b7785]credits[/] [#c084fc]{st.hackdox_credits}/{config.HACKDOX_CREDIT_MAX}[/]"
            f"   [#6b7785]⏱ cap[/] [#ffb454]{st.compute_capacity}[/]"),
            "",
        ]
        for idx, (kind, iid, price, label, desc) in enumerate(self._items):
            if kind == "header":
                accent = config.UPGRADE_CATEGORY_ACCENT.get(label, "#6b7785")
                bar = "─" * max(1, 40 - len(label))
                lines.append(f"[{accent}]── {label} {bar}[/]")
                continue
            owned  = kind == "upgrade" and iid in st.upgrades
            capped = kind == "credit" and st.hackdox_credits >= config.HACKDOX_CREDIT_MAX
            afford = st.hackdollars >= price
            cur    = idx == self._cursor
            if owned:
                tag, lcol = "[#6b7785]OWNED [/]", "#6b7785"
            elif capped:
                tag, lcol = "[#6b7785]FULL  [/]", "#6b7785"
            elif afford:
                tag, lcol = f"[#00ff9f]{price:>3} $[/] ", "#c8d4e1"
            else:
                tag, lcol = f"[#ff5470]{price:>3} $[/] ", "#5a6775"
            marker = "[#00ffd5]▶ [/]" if cur else "  "
            lbl    = f"[reverse] {label} [/]" if cur else f"[{lcol}]{label}[/]"
            lines.append(f"{marker}{tag} {lbl}")
            if cur:
                lines.append(f"      [dim]{desc}[/]")
        lines.append("")
        if self._status_msg:
            scol = "#ff5470" if self._status_err else "#7dd3c0"
            lines.append(f"[{scol}]{self._status_msg}[/]")
        else:
            lines.append("[dim]Enter to buy · N for next day[/]")
        return "\n".join(lines)

    # ── Actions ───────────────────────────────────────────────────────

    def action_cursor_up(self) -> None:
        i = self._cursor
        while i > 0:
            i -= 1
            if self._items[i][0] != "header":
                self._cursor = i
                break
        self._repaint()

    def action_cursor_down(self) -> None:
        i = self._cursor
        while i < len(self._items) - 1:
            i += 1
            if self._items[i][0] != "header":
                self._cursor = i
                break
        self._repaint()

    def action_buy(self) -> None:
        kind, iid, price, label, _desc = self._items[self._cursor]
        if kind == "header":
            return   # cursor should never rest on a header, but stay safe
        st = self._state
        if kind == "upgrade" and iid in st.upgrades:
            self._flash(f"{label} already owned", err=True)
            return
        if kind == "credit" and st.hackdox_credits >= config.HACKDOX_CREDIT_MAX:
            self._flash("credit slots full", err=True)
            return
        if st.hackdollars < price:
            self._flash(
                f"insufficient HackDollar$ — need {price}, have {st.hackdollars}",
                err=True)
            return
        st.hackdollars -= price
        if kind == "upgrade":
            st.upgrades.add(iid)
            sound_manager.play("upgrade_purchase")
        elif kind == "credit":
            st.hackdox_credits += 1
        else:
            st.compute_capacity += config.COMPUTE_CAPACITY_STEP
        persistence.save(st)   # purchases persist immediately (issue #22)
        self._flash(f"purchased {label}  (−{price} HD$)", err=False)

    def _flash(self, msg: str, err: bool) -> None:
        self._status_msg = msg
        self._status_err = err
        self._repaint()

    def action_next_day(self) -> None:
        # #20 rework: the loss condition is evaluated at end of day. If the
        # batch application dropped health below the threshold, the campaign
        # ends here instead of advancing.
        if scoring.health_below_loss(self._state):
            self.app.game_over()
            return
        self.app.advance_day()

    def action_quit_app(self) -> None:
        persistence.save(self._state)
        self.app.exit()
