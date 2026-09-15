"""CipherBlockPanel."""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from gameengine import config
from gameengine.core import tools_bridge
from gameengine.core.models import Candidate


class CipherBlockPanel(VerticalScroll):
    """Centre column of the Hashcrack page — the two-stage decryption surface.

    Renders the candidate's credential as a block of ciphertext glyphs
    (tools_bridge.CipherBlockData) and hosts both stages of the decrypt:

      X            open the window selector (handled by IntakeScreen)
      ← →          stage 1: choose a decryption window
                   stage 2: step the alignment pad along X
      ↑ ↓          stage 2: step the alignment pad along Y
      Enter        stage 1: apply the selected window (costs ⏱)
      Esc          leave decrypt mode

    The panel owns no ⏱ and makes no purchase. Applying a window goes through
    IntakeScreen — it charges, checks the verdict lock, and hands the outcome
    back via `apply_result()` — so the mouse and the keyboard trigger the
    literal same function, the same pattern StegoImagePanel uses for stamping.

    What is readable for free, before any spend, is the header: the block's
    dimensions, its glyph alphabet and its digest shape. That is what tells the
    player which window fits AND whether the credential is worth opening at
    all. Everything past that is bought once, in stage 1.
    """

    can_focus = False

    # Panel states. IDLE and SELECTING both show pure ciphertext — the block
    # only gains structure once a matching window has actually been applied.
    IDLE      = "idle"
    SELECTING = "selecting"
    ENGAGED   = "engaged"    # dial live
    STALLED   = "stalled"    # bcrypt — matched, but nothing to recover
    LOCKED    = "locked"     # exact alignment reached

    _TIER_COLOUR: ClassVar[dict[str, str]] = {
        "weak": "#ff5470", "medium": "#ffd93d", "strong": "#00ff9f"}

    def __init__(self) -> None:
        super().__init__(id="cipher-block-panel", classes="panel")
        self.border_title = " Cipher Block "
        self._content: Static | None = None
        self._block: tools_bridge.CipherBlockData | None = None
        self._state = self.IDLE
        self._sel = 0            # index into config.CIPHER_WINDOWS
        self._x = 0              # alignment pad cursor
        self._y = 0
        self._steps = 0          # pad presses spent on this candidate
        self._applied: str | None = None   # tier key of the window in use
        self._attempts = 0       # windows paid for on this candidate
        self.hint_upgrade = False   # Credential HUD
        self.label_tier = False     # Cipher ID HUD
        self.on_apply_click: Callable[[], None] | None = None

    def compose(self) -> ComposeResult:
        self._content = Static("[dim italic]Awaiting candidate...[/]",
                               id="cipher-block-content")
        yield self._content

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def block(self) -> tools_bridge.CipherBlockData | None:
        return self._block

    @property
    def state(self) -> str:
        return self._state

    @property
    def cursor(self) -> tuple[int, int]:
        """The alignment pad cursor as (x, y)."""
        return (self._x, self._y)

    @property
    def steps(self) -> int:
        """Pad presses spent on this candidate — drives the step budget."""
        return self._steps

    @property
    def attempts(self) -> int:
        return self._attempts

    @property
    def selected_tier(self) -> str:
        return config.CIPHER_WINDOWS[self._sel][0]

    @property
    def selected_label(self) -> str:
        return config.CIPHER_WINDOWS[self._sel][1]

    @property
    def locked(self) -> bool:
        return self._state == self.LOCKED

    def load_candidate(self, candidate: Candidate, day: int = 1) -> None:
        self._block = tools_bridge.build_cipher_block(candidate, day)
        self._sel = 0
        self._x, self._y = self._block.start_cursor
        self._steps = 0
        self._applied = None
        self._attempts = 0
        # UNSALTED_STORAGE arrives decrypted: no salt means the stored value is
        # exposed outright, which is the violation rather than a shortcut past
        # it. There is nothing to buy and nothing to tune.
        self._state = self.LOCKED if self._block.pre_revealed else self.IDLE
        self.border_title = (
            f" Cipher Block — {self._block.cols}×{self._block.rows} "
            f"{'radix-64' if self._block.tier == 'strong' else 'hex'} ")
        self._rebuild_content()

    def open_selector(self) -> None:
        """Enter stage 1. A block already engaged goes back to its dial."""
        if self._block is None or self._state == self.LOCKED:
            return
        self._state = self.ENGAGED if self._applied else self.SELECTING
        self._rebuild_content()

    def close(self) -> None:
        """Leave decrypt mode without losing progress.

        An engaged block stays engaged and keeps its dial position — the
        purchase has been made and walking away must not silently discard it.
        """
        if self._state == self.SELECTING:
            self._state = self.IDLE
        self._rebuild_content()

    def move_selection(self, delta: int) -> None:
        if self._state != self.SELECTING:
            return
        self._sel = (self._sel + delta) % len(config.CIPHER_WINDOWS)
        self._rebuild_content()

    def apply_result(self, res: tools_bridge.WindowResult) -> None:
        """Record the outcome of a window the screen has already charged for."""
        self._attempts += 1
        if res.outcome == tools_bridge.CIPHER_WINDOW_ENGAGED:
            self._applied = res.chosen
            self._state = self.ENGAGED
            # Centre, not a corner — see CipherBlockData.start_cursor.
            self._x, self._y = self._block.start_cursor
        elif res.outcome == tools_bridge.CIPHER_WINDOW_STALLED:
            self._applied = res.chosen
            self._state = self.STALLED
        else:
            # Wrong window: the block is unchanged and the player may pay to
            # try another. Staying in SELECTING is deliberate — it puts the
            # next choice one keypress away rather than making them re-enter.
            self._state = self.SELECTING
        self._rebuild_content()

    def move_cursor(self, dx: int, dy: int) -> int:
        """Step the alignment pad. Returns how many steps actually happened.

        A move that runs into an edge returns 0 and is NOT billed. Holding a
        direction against the wall must not rack up ⏱ for a cursor that is not
        moving — the budget is meant to price a wandering search, not punish
        the player for finding out where the pad ends.
        """
        if self._state not in (self.ENGAGED, self.LOCKED) or self._block is None:
            return 0
        nx = max(0, min(self._block.align_span_x, self._x + dx))
        ny = max(0, min(self._block.align_span_y, self._y + dy))
        moved = abs(nx - self._x) + abs(ny - self._y)
        if not moved:
            return 0
        self._x, self._y = nx, ny
        self._steps += moved
        self._state = (self.LOCKED
                       if tools_bridge.alignment_locked(self._block, nx, ny)
                       else self.ENGAGED)
        self._rebuild_content()
        return moved

    # ── Content rendering ─────────────────────────────────────────────────
    # NOTE: not named _render() — that's a Textual base-class method.

    def _rebuild_content(self) -> None:
        if self._content is None or self._block is None:
            return
        blk = self._block
        engaged = self._state in (self.ENGAGED, self.LOCKED)
        grid = tools_bridge.render_block(blk, self._x, self._y, engaged=engaged)

        lines: list[str] = []
        for row in grid:
            out = ""
            for glyph, resolved in row:
                out += (f"[#c084fc][b]{glyph}[/][/]" if resolved
                        else f"[#5a6675]{glyph}[/]")
            lines.append(out)

        lines.append("")
        lines.extend(self._status_lines())
        self._content.update("\n".join(lines))

    def _status_lines(self) -> list[str]:
        blk = self._block
        if blk is None:
            return []

        if blk.pre_revealed:
            return ["[#ff5470][b]⚠ UNSALTED — stored in the clear[/][/]",
                    "[dim]no window, no dial, nothing to spend[/]"]

        if self._state == self.SELECTING:
            chips = []
            for i, (_tier, label, shape) in enumerate(config.CIPHER_WINDOWS):
                if i == self._sel:
                    chips.append(f"[#00ffd5][b]▸ {label} ◂[/][/]")
                else:
                    chips.append(f"[#3d6478]  {label}  [/]")
            _t, _lbl, shape = config.CIPHER_WINDOWS[self._sel]
            out = [
                "[#00ffd5][b]SELECT DECRYPTION WINDOW[/][/]",
                "  " + "   ".join(chips),
                f"  [dim]built for: {shape}[/]",
                "  [dim]← → choose · Enter apply · Esc cancel[/]",
            ]
            if self._attempts:
                out.append(f"  [#ff8c42]{self._attempts} window(s) already "
                           f"paid for on this candidate[/]")
            return out

        if self._state == self.STALLED:
            return [
                ("[#00ff9f][b]DECRYPT STALLED[/][/]  [dim]key-stretched, "
                 "cost factor 12[/]"),
                "[dim]the window fits — there is simply no alignment to find[/]",
            ]

        if self._state in (self.ENGAGED, self.LOCKED):
            return self._dial_lines()

        return [
            "[dim]Press [b]X[/] to open the window selector[/]",
            ("[dim]read the digest shape above first — it tells you which "
             "window fits, and whether this is worth opening[/]"),
        ]

    def _dial_lines(self) -> list[str]:
        """The alignment pad, drawn one character per position.

        Deliberately shows POSITION and not PROGRESS. A "42% resolved" readout
        would let the player hill-climb a number with their eyes closed, which
        is precisely the shortcut the second axis exists to remove — the
        gradient is supposed to be read off the ciphertext above.

        Drawn at full resolution rather than scaled to fit. A scaled pad maps
        several positions onto one character, so the marker stops moving on
        some presses and the hint box covers more ground than it really marks;
        both read as the control lying. config.CIPHER_ALIGN_SPAN is sized so
        the pad fits as-is.
        """
        blk = self._block
        band = tools_bridge.hint_band(
            blk, {config.UPGRADE_HASH_HIGHLIGHT} if self.hint_upgrade else set())

        rows: list[str] = []
        for y in range(blk.align_span_y + 1):
            line = ""
            for x in range(blk.align_span_x + 1):
                if (x, y) == (self._x, self._y):
                    line += "[#00ffd5][b]◆[/][/]"
                elif (band is not None
                      and band[0] <= x <= band[2] and band[1] <= y <= band[3]):
                    line += "[#4a6b8a]▒[/]"
                else:
                    line += "[#2e3d4f]·[/]"
            rows.append("  " + line)

        if self._state == self.LOCKED:
            head = ("[#00ff9f][b]✓ ALIGNED — credential resolved[/][/]  "
                    f"[dim]key ({self._x}, {self._y})[/]")
            tail = ["  [dim]the block is fully in the clear[/]"]
        else:
            head = ("[#c084fc][b]ALIGNMENT PAD[/][/]  "
                    f"[dim]X {self._x}/{blk.align_span_x}  ·  "
                    f"Y {self._y}/{blk.align_span_y}[/]")
            tail = ["  [dim]← → ↑ ↓ step · watch the block, not the pad — "
                    "more characters settle as you close in[/]"]
            tail.append("  " + self._budget_line())
        out = [head, *rows, *tail]
        if band is not None and self._state != self.LOCKED:
            out.append("  [#4a6b8a]shaded box: Credential HUD — the key is "
                       "somewhere inside it[/]")
        return out

    _METER_WIDTH: ClassVar[int] = 24

    def _budget_line(self) -> str:
        """The travelled-distance meter: how far you have walked, and what the
        next steps cost.

        A BAR rather than a bare number, because the question the player is
        actually asking is "am I nearly out?", and a number answers that only
        if they also remember the allowance. The bar fills across the free
        steps and then keeps going in amber, so the moment it crosses is
        visible without reading anything.

        Note this deliberately measures DISTANCE TRAVELLED, not distance
        remaining — the pad never tells the player how far the key is, and a
        meter that emptied toward zero would be exactly that readout. This one
        only reports what they have spent, which they already know.
        """
        free = config.CIPHER_DIAL_FREE_STEPS
        left = tools_bridge.steps_until_charge(self._steps)
        filled = min(self._METER_WIDTH,
                     round(self._steps / max(1, free) * self._METER_WIDTH))
        if self._steps <= free:
            bar = (f"[#00ffd5]{'█' * filled}[/]"
                   f"[#2e3d4f]{'░' * (self._METER_WIDTH - filled)}[/]")
            return (f"{bar}  [dim]{self._steps} travelled  ·  {left} free "
                    f"before {config.CIPHER_DIAL_OVERAGE_COST} ⏱ per "
                    f"{config.CIPHER_DIAL_OVERAGE_BLOCK}[/]")
        # Past the allowance the bar is full and the overage rides on top of
        # it, so "how far over" stays legible instead of pinning silently.
        over = self._steps - free
        over_cells = min(self._METER_WIDTH,
                         round(over / max(1, config.CIPHER_DIAL_OVERAGE_BLOCK
                                          * 4) * self._METER_WIDTH))
        bar = (f"[#ff8c42]{'█' * self._METER_WIDTH}[/]"
               f"[#ff5470]{'▓' * over_cells}[/]")
        return (f"{bar}  [#ff8c42]{self._steps} travelled  ·  {over} over — "
                f"{config.CIPHER_DIAL_OVERAGE_COST} ⏱ every "
                f"{config.CIPHER_DIAL_OVERAGE_BLOCK}, next in {left}[/]")
