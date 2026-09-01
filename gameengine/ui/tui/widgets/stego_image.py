"""StegoImagePanel."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static
from gameengine import config
from gameengine.core import tools_bridge
from gameengine.core.models import Candidate, DiscrepancyKind


class StegoImagePanel(VerticalScroll):
    """Right column of the Stegotool page — the interactive image viewer.

    Renders the candidate's submitted image as a colored pixel grid
    (tools_bridge.StegoImageData) and hosts the STAMP minigame:

      X            enter/exit stamp mode (handled by IntakeScreen)
      arrows       move the square stamp
      Space        stamp — reveals the cells underneath (−STEGO_STAMP_COST ⏱)
      mouse move   move the stamp to the cell under the cursor
      left click   stamp at the cell under the cursor
      Esc          exit stamp mode

    Revealed cells re-render by what they carry:
      carrier cells → payload-type color (amber/crimson/violet)
      clean cells   → faint green wash
    The subtle free-tier tint over the hot zone is preserved, so a sharp
    eye can still pre-read the image before spending a single ⏱.

    Nick (batch-3 follow-up): mouse control is layered on top of, not
    instead of, the keyboard controls — arrows/Space/Esc are untouched.
    Moving the mouse repositions the stamp window (pure local rendering
    state, same as an arrow press, no cost); a left click both repositions
    AND immediately stamps. Stamping itself still has to go through
    IntakeScreen (it charges ⏱ and checks the verdict lock), so — same
    pattern as the tab-click and verdict-button callbacks elsewhere in this
    file — `on_stamp_click` is a plain callback the screen points at its
    own `_do_stamp`, so a mouse click and the Space key trigger the literal
    same function.
    """

    can_focus = False

    _MOVES = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}

    def __init__(self) -> None:
        super().__init__(id="stego-image-panel", classes="panel")
        self.border_title = " Image Viewer "
        self._content: Static | None = None
        self._img: "tools_bridge.StegoImageData | None" = None
        self._revealed: set[tuple[int, int]] = set()
        self._stamp_mode = False
        self._cur_x = 0
        self._cur_y = 0
        self._stamps_used = 0
        self.tint_boost = False   # Spectral Lens upgrade (issue #23)
        self.on_stamp_click: "Callable[[], None] | None" = None

    def compose(self) -> ComposeResult:
        self._content = Static("[dim italic]Awaiting candidate...[/]",
                               id="stego-image-content")
        yield self._content

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def image(self) -> "tools_bridge.StegoImageData | None":
        return self._img

    @property
    def stamps_used(self) -> int:
        return self._stamps_used

    @property
    def stamp_rect(self) -> tuple[int, int, int, int]:
        return (self._cur_x, self._cur_y,
                config.STEGO_STAMP_W, config.STEGO_STAMP_H)

    def load_candidate(self, candidate: "Candidate", day: int = 1) -> None:
        self._img = tools_bridge.build_stego_image(candidate, day)
        self._revealed = set()
        self._stamp_mode = False
        self._stamps_used = 0
        self._cur_x = self._cur_y = 0
        img = self._img
        self.border_title = (f" Image Viewer — {img.filename} "
                             f"{img.width}×{img.height} {img.img_type} {img.file_kb}KB ")
        self._rebuild_content()

    def enter_stamp_mode(self) -> None:
        self._stamp_mode = True
        self._rebuild_content()

    def exit_stamp_mode(self) -> None:
        self._stamp_mode = False
        self._rebuild_content()

    def _clamp_stamp(self, x: int, y: int) -> tuple[int, int]:
        """Clamp a candidate (x, y) so the whole stamp window stays on the
        image — the one place both keyboard nudges and mouse positioning
        compute this, so they can't drift onto two different edge rules."""
        cx = max(0, min(self._img.cols - config.STEGO_STAMP_W, x))
        cy = max(0, min(self._img.rows - config.STEGO_STAMP_H, y))
        return cx, cy

    def move_stamp(self, key: str) -> None:
        if self._img is None or key not in self._MOVES:
            return
        dx, dy = self._MOVES[key]
        self._cur_x, self._cur_y = self._clamp_stamp(
            self._cur_x + dx, self._cur_y + dy)
        self._rebuild_content()

    def set_stamp_position(self, x: int, y: int) -> None:
        """Mouse equivalent of move_stamp(): place the stamp window's
        top-left corner at an absolute cell rather than nudging by one.
        Cheap, local, no ⏱ cost — same as an arrow press."""
        if self._img is None:
            return
        self._cur_x, self._cur_y = self._clamp_stamp(x, y)
        self._rebuild_content()

    def _mouse_to_cell(self, event) -> "tuple[int, int] | None":
        """Translate a raw mouse event's widget-relative (x, y) into image-
        grid (col, row) coordinates, or None if the pointer is over the
        border/padding/status-line area rather than a pixel. Uses
        self.gutter rather than a hardcoded padding/border width (same
        technique as StatusHeader.on_click) and adds scroll_offset since
        this is a VerticalScroll and a tall image can push earlier rows out
        of view."""
        if self._img is None:
            return None
        gutter = self.gutter
        x = event.x - gutter.left + self.scroll_offset.x
        y = event.y - gutter.top + self.scroll_offset.y
        if 0 <= x < self._img.cols and 0 <= y < self._img.rows:
            return x, y
        return None

    def on_mouse_move(self, event) -> None:
        if not self._stamp_mode:
            return
        cell = self._mouse_to_cell(event)
        if cell is not None:
            self.set_stamp_position(*cell)

    def on_click(self, event) -> None:
        if not self._stamp_mode or event.button != 1 or self.on_stamp_click is None:
            return
        cell = self._mouse_to_cell(event)
        if cell is not None:
            self.set_stamp_position(*cell)
            self.on_stamp_click()

    def do_stamp(self) -> "tools_bridge.StampResult | None":
        """Evaluate the stamp at the cursor. Caller charges ⏱ first."""
        if self._img is None:
            return None
        x, y, w, h = self.stamp_rect
        res = tools_bridge.evaluate_stamp(self._img, x, y, w, h, self._revealed)
        self._stamps_used += 1
        self._rebuild_content()
        return res

    # ── Content rendering ─────────────────────────────────────────────────
    # NOTE: not named _render() — that's a Textual base-class method.

    def _rebuild_content(self) -> None:
        if self._content is None or self._img is None:
            return
        img = self._img
        sx, sy, sw, sh = self.stamp_rect
        in_zone = (lambda x, y: False) if img.zone is None else (
            lambda x, y, z=img.zone: z[0] <= x < z[0] + z[2] and z[1] <= y < z[1] + z[3])
        # #54: the Spectral Lens advertises a BUFFERED region, not the exact
        # zone. Before this, the free tier tinted exact zone membership, which
        # solved the stamp sweep for nothing and left the 30 HD$ upgrade with
        # only "the same rectangle, bluer" to sell.
        in_hint = (lambda x, y: False) if img.hint_region is None else (
            lambda x, y, h=img.hint_region: h[0] <= x < h[0] + h[2] and h[1] <= y < h[1] + h[3])

        lines: list[str] = []
        for y in range(img.rows):
            row = ""
            for x in range(img.cols):
                r, g, b = img.base_rgb[y][x]
                revealed = (x, y) in self._revealed
                zone_cell = in_zone(x, y)
                hint_cell = in_hint(x, y)

                if revealed and (x, y) in img.carrier:
                    # Payload-type color with deterministic jitter
                    j = (x * 7 + y * 13) % 41
                    if img.kind is DiscrepancyKind.COVERT_C2_CHANNEL:
                        r, g, b = 150 + j // 2, 85 + j // 3, 235
                    elif img.kind is DiscrepancyKind.ENCRYPTED_PAYLOAD:
                        r, g, b = 210 + j // 2, 25 + j // 3, 10 + j // 4
                    else:  # STEGO_PAYLOAD_PRESENT
                        r, g, b = 185 + j, 75 + j // 2, 15 + j // 4
                elif revealed and zone_cell:
                    # Disturbed noise inside the zone but no carrier bit
                    r = min(255, r + 20); b = min(255, b + 20)
                elif revealed:
                    # Confirmed clean — faint green wash
                    g = min(255, g + 45); r = max(0, r - 10); b = max(0, b - 10)
                elif hint_cell and self.tint_boost:
                    # #54: the Spectral Lens (issue #23) is now the ONLY thing
                    # that tints, and it tints the buffered region rather than
                    # the exact zone — it narrows the search, it doesn't answer
                    # it. Base tier deliberately shows nothing: sweeping blind
                    # is the stamp minigame, and disclosing the exact rectangle
                    # for free was the reason it had no bite.
                    b = min(255, b + 55); r = max(0, r - 22)

                # Stamp cursor overlay
                if self._stamp_mode and sx <= x < sx + sw and sy <= y < sy + sh:
                    on_edge = (x in (sx, sx + sw - 1) or y in (sy, sy + sh - 1))
                    if on_edge:
                        row += "[#00ffd5]▒[/]"
                        continue
                    r = min(255, r + 45); g = min(255, g + 45); b = min(255, b + 45)

                r = max(0, min(255, r)); g = max(0, min(255, g)); b = max(0, min(255, b))
                row += f"[#{r:02x}{g:02x}{b:02x}]█[/]"
            lines.append(row)

        lines.append("")
        spent = self._stamps_used * config.STEGO_STAMP_COST
        if self._stamp_mode:
            lines.append(f"[#00ffd5][b]STAMP MODE[/][/]  [dim]@ ({sx},{sy})[/]  "
                         f"[dim]arrows move · Space stamp (−{config.STEGO_STAMP_COST} ⏱) · Esc exit[/]")
        else:
            lines.append(f"[dim]Press [b]X[/] to enter stamp mode[/]")
        lines.append(f"[dim]stamps: {self._stamps_used} · spent: {spent} ⏱ · "
                     f"revealed: {len(self._revealed)} px[/]")
        self._content.update("\n".join(lines))
