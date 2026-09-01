"""BreachListPanel."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Footer, Static
from gameengine.core import tools_bridge
from gameengine.core.models import Candidate, Day


class BreachListPanel(VerticalScroll):
    """Right-side panel on the Ghostscan page showing scrollable breach database lists.

    Three display states (apply only to the CURRENTLY loaded candidate's own
    row — see load_candidate):
      idle        — all entries in the same dim grey; player scans manually
      highlighted — candidate's email highlighted in orange after base ghostscan run
      confirmed   — candidate's email red + ▲ BREACH_HIT label after filter

    Batch-3 follow-up (Nick, playtest): every OTHER candidate this day will
    ever produce who genuinely belongs in a corpus (BREACH_HIT /
    LEAKED_PASSWORD / CROSS_BREACH_REUSE) is also sitting in these lists from
    the very first load, not just the one whose dossier happens to be open —
    see tools_bridge.get_breach_lists_for_day(). Because idle-state color no
    longer distinguishes a real match from noise (the fix directly below),
    that standing presence isn't itself a leak: nothing marks a row as real
    until that specific candidate is actually investigated.
    """

    _STATE_IDLE        = "idle"
    _STATE_HIGHLIGHTED = "highlighted"
    _STATE_CONFIRMED   = "confirmed"

    def __init__(self) -> None:
        super().__init__(id="breach-list-panel", classes="panel")
        self.border_title = " Breach Databases "
        self._scan_state: str = self._STATE_IDLE
        self._lists: list[tuple[str, str, str, list[tuple[str, bool]]]] = []
        self._content: Static | None = None
        self._current_target: str | None = None
        # Keyed on (game_seed, day.number) — the day-wide roster only needs
        # rebuilding when either changes, not on every candidate switch.
        self._day_cache: dict[tuple[int, int], list[tuple[str, str, str, list[str]]]] = {}

    def compose(self) -> ComposeResult:
        self._content = Static(
            "[dim italic]Awaiting candidate...[/]",
            id="breach-content",
        )
        yield self._content

    # ── Public API ────────────────────────────────────────────────────────

    def load_candidate(self, candidate: "Candidate", game_seed: int,
                       day: "Day") -> None:
        """Populate lists for a new candidate and reset to idle state.

        #61: the lists are no longer per-candidate. `game_seed` fixes their
        contents for the whole playthrough and `day.number` decides how many
        databases exist yet — so the panel is stable reference material the
        player can actually learn, and it grows rather than churns.

        Batch-3 follow-up: the underlying roster (which real candidates —
        plural, the WHOLE day — belong in which corpus) is now built once per
        day via get_breach_lists_for_day() and cached; only which single
        email counts as "the current candidate's own row" (eligible for
        highlight_match()/confirm_match()) changes between calls.
        """
        key = (game_seed, day.number)
        day_lists = self._day_cache.get(key)
        if day_lists is None:
            day_lists = tools_bridge.get_breach_lists_for_day(game_seed, day)
            self._day_cache[key] = day_lists

        self._scan_state = self._STATE_IDLE
        self._current_target = candidate.email
        self._lists = [
            (db_name, year, count_label,
             [(email, email == candidate.email) for email in emails])
            for db_name, year, count_label, emails in day_lists
        ]
        self._rebuild_content()

    def highlight_match(self) -> None:
        """After base ghostscan run — highlight any match in orange."""
        self._scan_state = self._STATE_HIGHLIGHTED
        self._rebuild_content()

    def confirm_match(self) -> None:
        """After filter run — show match in red with explicit ▲ BREACH_HIT label."""
        self._scan_state = self._STATE_CONFIRMED
        self._rebuild_content()

    # ── Content rendering ─────────────────────────────────────────────────
    # NOTE: do NOT name this _render() — that's a Textual base-class method
    # that must return a Visual object; overriding it returns None and crashes.

    def _rebuild_content(self) -> None:
        if self._content is None:
            return

        if not self._lists:
            self._content.update("[dim italic]No data.[/]")
            return

        lines: list[str] = []
        has_any_match = any(m for _, _, _, entries in self._lists for _, m in entries)

        for db_name, _year, count_label, entries in self._lists:
            # db_name is the canonical name, e.g. "Collection #1 (2019)" —
            # identical to what appears in the Hashcrack BREACH_MATCH log entry.
            bar = "─" * max(1, 32 - len(db_name))
            lines.append(f"\n[#3a4a58]── {db_name} {bar}[/]")
            lines.append(f"[#2e3d4f]   {count_label}[/]")

            for email, is_match in entries:
                if is_match:
                    if self._scan_state == self._STATE_CONFIRMED:
                        lines.append(f"  [#ff5470][b]▲ {email}[/][/]  [#ff5470][b]BREACH_HIT[/][/]")
                    elif self._scan_state == self._STATE_HIGHLIGHTED:
                        lines.append(f"  [#ff8c42]► {email}[/]")
                    else:
                        # idle — match present but not revealed. Batch-3
                        # follow-up (Nick, playtest): this used to render at
                        # #6b7785, a visibly LIGHTER shade than a noise row's
                        # #4a5568 — a real match stood out from filler before
                        # any scan or upgrade, "too easy to identify." Must be
                        # pixel-identical to a noise row until actually
                        # investigated.
                        lines.append(f"  [#4a5568]{email}[/]")
                else:
                    lines.append(f"  [#4a5568]{email}[/]")

        # Footer hint
        if has_any_match and self._scan_state == self._STATE_IDLE:
            lines.append("\n[dim]Run [b]recon[/b] to scan, [b]filter[/b] to confirm.[/]")
        elif not has_any_match:
            lines.append("\n[dim]Run [b]recon[/b] to scan these lists.[/]")

        self._content.update("\n".join(lines))
        self.scroll_home(animate=False)
