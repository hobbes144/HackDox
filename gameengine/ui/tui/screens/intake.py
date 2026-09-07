"""IntakeScreen."""

from __future__ import annotations

import random
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.screen import Screen
from textual.widgets import Button, ContentSwitcher, Static

from gameengine import config
from gameengine.core import candidate_gen, rules_engine, scoring, tools_bridge
from gameengine.core.audio import sound_manager
from gameengine.core.models import Candidate, Day, GameState, ToolName, Verdict
from gameengine.ui.tui import rules_content
from gameengine.ui.tui.screens.credit_reveal import CreditRevealScreen
from gameengine.ui.tui.screens.rules import RulesScreen
from gameengine.ui.tui.shared import (
    _B,
    _BOARD_HOME_GROUP,
    _COMMAND_ALIASES,
    _ERROR_MSGS,
    _PAGE_IDS,
    _PAGE_NAMES,
    _PAGE_TAB,
    _PAGE_TOOL,
    _REF_CANDIDATE,
    _REF_GHOSTSCAN,
    _REF_HASHCRACK,
    _REF_LOGWATCH,
    _REF_STEGOTOOL,
)
from gameengine.ui.tui.widgets import (
    BreachListPanel,
    ChatPanel,
    CommandBar,
    CondensedDossier,
    DebugPanel,
    DossierPanel,
    EvidenceBoard,
    EvidenceState,
    OverseerPanel,
    ReferencePanel,
    StatusHeader,
    StegoImagePanel,
    ToolTerminal,
)


class IntakeScreen(Screen):
    """The main play screen."""

    BINDINGS: ClassVar[list[Binding]] = [
        # Page navigation — number row (immediate, no command bar)
        Binding(_B["page_candidate"], "page_1",      "Candidate", show=False),
        Binding(_B["page_ghostscan"], "page_2",      "Ghostscan", show=False),
        Binding(_B["page_hashcrack"], "page_3",      "Hashcrack", show=False),
        Binding(_B["page_logwatch"],  "page_4",      "Logwatch",  show=False),
        Binding(_B["page_stegotool"], "page_5",      "Stegotool", show=False),

        # Rules overlay (immediate)
        Binding(_B["page_rules"],     "open_rules",  "Rules",     show=False),

        # Within-page focus navigation — arrow keys (immediate)
        # EvidenceBoard consumes up/down when focused; letters still bubble to command bar.
        Binding(_B["focus_prev"],     "focus_prev",  "↑ Focus",   show=False),
        Binding(_B["focus_next"],     "focus_next",  "↓ Focus",   show=False),
        Binding(_B["focus_left"],     "focus_left",  "← Focus",   show=False),
        Binding(_B["focus_right"],    "focus_right", "→ Focus",   show=False),

        # Debug toggle — dev shortcut, kept immediate
        Binding(_B["toggle_debug"],   "toggle_debug","Dev",        show=False),

        # Everything else (a/d/n/g/l/h/s/f/q/?) goes through the command bar.
        # See on_key() and _execute_command() below.
    ]

    def __init__(self, day: Day, state: GameState, overseer_intro: str) -> None:
        super().__init__()
        self._day            = day
        self._state          = state
        self._candidate: Candidate | None = None
        self._verdict_locked = False
        self._page_index     = 0
        self._compute_before = state.compute_hours   # track for overseer stats
        self._spent: set[ToolName] = set()
        self._day_log: list = []   # shared log entries for the full day
        # #50: per-tab scroll positions for the Rules overlay. Lives here rather
        # than on RulesScreen because that screen is dismissed and rebuilt on
        # every open, so anything it owns is lost between views.
        self._rules_scroll: dict[str, float] = {}
        self._hc_log:  list = []   # shared credential audit log (hashcrack)

        # ── Stegotool stamp minigame state ────────────────────────────
        self._stamp_mode     = False   # arrows/Space captured while True
        self._stego_resolved = False   # ▲ signature block printed once
        self._stego_filter   = False   # payload type classified (filter paid)
        self._credit_revealed = False  # HackDox Credit spent on this candidate (issue #25)

        # ── Verdict reveal window ─────────────────────────────────────
        # Timers, not a coroutine: the window has to be cancellable from
        # anywhere (NEXT is live immediately, and the player may also be mid
        # tool-page when they press it), and a handle we can .stop() is a lot
        # harder to leak than a task we have to remember to await.
        self._reveal_timers: list = []
        self._reveal_classes: tuple[str, str] = ("", "")

        # ── Widgets ───────────────────────────────────────────────────
        self.status   = StatusHeader(state, day, state.current_slot_index)
        self.status.on_tab_click = self._goto_page
        self.dossier  = DossierPanel()
        self.chat     = ChatPanel()
        # Shared evidence record + the inline Candidate-page board (unchanged).
        self.evidence_state = EvidenceState()
        # Progressive unlock (#33 extended): every board this screen owns is
        # filtered to the tools this GameState has actually unlocked. Safe to
        # bake in at construction — IntakeScreen is rebuilt fresh each day.
        _unlocked = state.unlocked_tools
        self.board    = EvidenceBoard(self.evidence_state, "evidence-board", summary=True,
                                      unlocked_tools=_unlocked)
        # Full editable board on the Candidate/Dossier page too, so the player
        # always has direct access. Hidden by default; Tab swaps it in for the
        # read-only summary.
        self.board_c0 = EvidenceBoard(self.evidence_state, "evidence-c0", "tool-evidence",
                                      home_group="DOSSIER", unlocked_tools=_unlocked)
        # Verdict buttons (batch-3 follow-up, Nick): a clickable/arrow-
        # navigable ADMIT/DENY pair alongside the evidence board, sharing the
        # mid row with it 50/50. Both route through the exact same
        # _commit_verdict() the "admit"/"deny" text commands already use —
        # see on_button_pressed() — so button and keyboard verdicts can never
        # disagree about what happens or drift into two implementations.
        self.btn_admit = Button("ADMIT", id="btn-admit", variant="success")
        self.btn_deny  = Button("DENY",  id="btn-deny",  variant="error")
        # NEXT (batch-3 follow-up, Nick): a tall, skinny button off to the
        # right of ADMIT/DENY, enabled only once a verdict has actually been
        # delivered — mirrors the "next" text command 1:1 (see
        # _advance_to_next_candidate()) rather than a second implementation.
        self.btn_next  = Button("NEXT ▶", id="btn-next", disabled=True)
        self.overseer = OverseerPanel(overseer_intro)
        self.ref_main = ReferencePanel("candidate", "reference-side")

        # Toggleable evidence boards for the tool pages — same shared state,
        # mounted on the left, hidden until the player toggles them on.
        self.board_gs = EvidenceBoard(self.evidence_state, "evidence-gs", "tool-evidence",
                                      home_group=_BOARD_HOME_GROUP["evidence-gs"],
                                      unlocked_tools=_unlocked)
        self.board_hc = EvidenceBoard(self.evidence_state, "evidence-hc", "tool-evidence",
                                      home_group=_BOARD_HOME_GROUP["evidence-hc"],
                                      unlocked_tools=_unlocked)
        self.board_lw = EvidenceBoard(self.evidence_state, "evidence-lw", "tool-evidence",
                                      home_group=_BOARD_HOME_GROUP["evidence-lw"],
                                      unlocked_tools=_unlocked)
        self.board_st = EvidenceBoard(self.evidence_state, "evidence-st", "tool-evidence",
                                      home_group=_BOARD_HOME_GROUP["evidence-st"],
                                      unlocked_tools=_unlocked)
        self._tool_boards = (self.board_gs, self.board_hc, self.board_lw, self.board_st)
        # Each tool board is paired with the sidebar it replaces when shown.
        self._evidence_pairs = [
            (self.board_gs, "gs-left"),
            (self.board_hc, "hc-left"),
            (self.board_lw, "lw-left"),
            (self.board_st, "st-left"),
        ]
        self._evidence_open = False   # shared visibility across tool pages

        # One condensed dossier + reference panel per tool page
        self.cdos_gs  = CondensedDossier("condensed-dossier-gs")
        self.cdos_hc  = CondensedDossier("condensed-dossier-hc")
        self.cdos_lw  = CondensedDossier("condensed-dossier-lw")
        self.cdos_st  = CondensedDossier("condensed-dossier-st")

        self.ref_gs   = ReferencePanel("ghostscan", "ref-gs")
        self.ref_hc   = ReferencePanel("hashcrack", "ref-hc")
        self.ref_lw   = ReferencePanel("logwatch",  "ref-lw")
        self.ref_st   = ReferencePanel("stegotool", "ref-st")

        # Tool terminals
        self.term_gs  = ToolTerminal("terminal-gs", "Ghostscan")
        self.term_hc  = ToolTerminal("terminal-hc", "Hashcrack")
        self.term_lw  = ToolTerminal("terminal-lw", "Logwatch")
        self.term_st  = ToolTerminal("terminal-st", "Stegotool")

        # Breach list panel — right column of the Ghostscan page
        self.breach_lists = BreachListPanel()

        # Interactive image viewer — right column of the Stegotool page
        self.image_st = StegoImagePanel()
        self.image_st.on_stamp_click = self._do_stamp

        self.debug        = DebugPanel()
        self.command_bar  = CommandBar()
        self._footer_widget: Static | None = None

    def compose(self) -> ComposeResult:
        yield self.status

        with ContentSwitcher(initial="page-candidate"):

            # ── Page 0: Candidate ─────────────────────────────────────
            with Vertical(id="page-candidate"):
                with Horizontal(id="candidate-top"):
                    yield self.dossier
                    yield self.chat
                with Horizontal(id="candidate-mid"):
                    yield self.board
                    yield self.board_c0
                    with Horizontal(id="verdict-panel"):
                        with Vertical(id="verdict-buttons"):
                            yield self.btn_admit
                            yield self.btn_deny
                        yield self.btn_next
                with Horizontal(id="candidate-bot"):
                    yield self.overseer
                    yield self.ref_main

            # ── Page 1: Ghostscan ─────────────────────────────────────
            # 3-column layout: sidebar | terminal | breach lists
            # The evidence board (hidden) replaces the sidebar when toggled.
            with Horizontal(id="page-ghostscan", classes="tool-page"):
                yield self.board_gs
                with Vertical(classes="tool-left", id="gs-left"):
                    yield self.cdos_gs
                    yield self.ref_gs
                yield self.term_gs
                yield self.breach_lists

            # ── Page 2: Hashcrack ─────────────────────────────────────
            with Horizontal(id="page-hashcrack", classes="tool-page"):
                yield self.board_hc
                with Vertical(classes="tool-left", id="hc-left"):
                    yield self.cdos_hc
                    yield self.ref_hc
                yield self.term_hc

            # ── Page 3: Logwatch ──────────────────────────────────────
            with Horizontal(id="page-logwatch", classes="tool-page"):
                yield self.board_lw
                with Vertical(classes="tool-left", id="lw-left"):
                    yield self.cdos_lw
                    yield self.ref_lw
                yield self.term_lw

            # ── Page 4: Stegotool ─────────────────────────────────────
            # 3-column layout: sidebar | findings terminal | image viewer.
            # The image viewer dominates the right side — it's the game
            # canvas for the stamp minigame.
            with Horizontal(id="page-stegotool", classes="tool-page"):
                yield self.board_st
                with Vertical(classes="tool-left", id="st-left"):
                    yield self.cdos_st
                    yield self.ref_st
                yield self.term_st
                yield self.image_st

        yield self.debug
        yield self.command_bar

        self._footer_widget = Static(self._footer_text(), id="footer")
        yield self._footer_widget

    def on_mount(self) -> None:
        self._day_log = tools_bridge.generate_day_log(self._state.seed, self._day)
        self._hc_log  = tools_bridge.generate_hashcrack_day_log(self._state.seed, self._day)
        self._apply_evidence_visibility()   # tool boards start hidden
        self._load_current_candidate()

    # ── Internal helpers ──────────────────────────────────────────────

    _TOOL_TERM: ClassVar[dict[ToolName, str]] = {
        ToolName.GHOSTSCAN: "terminal-gs",
        ToolName.LOGWATCH:  "terminal-lw",
        ToolName.HASHCRACK: "terminal-hc",
        ToolName.STEGOTOOL: "terminal-st",
    }
    _TOOL_PAGE: ClassVar[dict[ToolName, int]] = {
        ToolName.GHOSTSCAN: 1,
        ToolName.LOGWATCH:  3,
        ToolName.HASHCRACK: 2,
        ToolName.STEGOTOOL: 4,
    }

    def _footer_text(self) -> str:
        """Slim nav strip — tool/verdict/quit all go through the command bar now."""
        on_tool = 1 <= self._page_index <= 4
        if on_tool:
            ev = ("[#ffb454][b]Tab[/][/] Hide Evidence"
                  if self._evidence_open
                  else "[#00ff9f][b]Tab[/][/] Evidence")
        else:
            ev = "[#00ff9f][b]Tab[/][/] Evidence"
        if self._stamp_mode:
            return (
                "[#00ffd5][b]STAMP MODE[/][/]  "
                "[dim]arrows Move[/]  "
                f"[#00ffd5][b]Space[/][/] Stamp (−{config.STEGO_STAMP_COST} ⏱)  "
                "[#ffb454][b]Esc[/][/] Exit"
            )
        stamp_hint = ("[#00ffd5][b]X[/][/] Stamp  " if self._page_index == 4 else "")
        return (
            "[#00ff9f][b]1-5[/][/] Pages  "
            "[#00ff9f][b]0[/][/] Rules  "
            f"{ev}  "
            f"{stamp_hint}"
            "[dim]↑↓ Cursor  Space Flag[/]  "
            "[#00ff9f][b]`[/][/] Dev"
        )

    def _refresh_footer(self) -> None:
        if self._footer_widget:
            self._footer_widget.update(self._footer_text())

    # ── Evidence board toggle (tool pages only) ──────────────────────────────

    def _apply_evidence_visibility(self) -> None:
        """Show/hide each tool board and the sidebar it replaces, plus the
        Candidate-page editable board (which swaps in for the summary)."""
        # Candidate page: editable board replaces the read-only summary.
        self.board_c0.display = self._evidence_open
        self.board.display    = not self._evidence_open
        for board, side_id in self._evidence_pairs:
            board.display = self._evidence_open
            try:
                self.query_one(f"#{side_id}").display = not self._evidence_open
            except Exception:  # noqa: BLE001, S110 -- side panel may not be mounted on
                # every page (only tool pages have one); skipping the toggle is the
                # correct no-op, not an error.
                pass

    def _current_tool_board(self) -> EvidenceBoard | None:
        if 1 <= self._page_index <= 4:
            return self._tool_boards[self._page_index - 1]
        return None

    def _active_editable_board(self) -> EvidenceBoard | None:
        """The editable board for the current page (Candidate or a tool page)."""
        if self._page_index == 0:
            return self.board_c0
        return self._current_tool_board()

    def _toggle_evidence(self) -> None:
        """Toggle the editable evidence board on the current page.

        Available on the Candidate/Dossier page (swaps in for the summary) and
        on every tool page (replaces the sidebar).
        """
        self._evidence_open = not self._evidence_open
        sound_manager.play("evidence_open" if self._evidence_open else "evidence_close")
        self._apply_evidence_visibility()
        self._refresh_footer()
        if self._evidence_open:
            board = self._active_editable_board()
            if board is not None:
                board.focus()
                # Reset scroll to the group this page focuses on.
                board.focus_home_group()
        else:
            self.board.repaint()

    def _goto_page(self, index: int) -> None:
        # Progressive unlock (#33): a locked tool page can't be entered — no
        # switch, no ⏱, just an Overseer-flavoured note. Candidate page (0) and
        # any already-unlocked tool pass straight through.
        tool = _PAGE_TOOL[index]
        _page_changed = index != self._page_index
        if tool is not None and tool not in self._state.unlocked_tools:
            self.command_bar.set_response(
                f"{_PAGE_NAMES[index]} is locked — the Overseer grants it in a "
                f"later briefing.",
                error=False,
            )
            return
        # Leaving the stego page (or arriving anywhere) drops stamp mode.
        if self._stamp_mode and index != 4:
            self._exit_stamp_mode(quiet=True)
        self._page_index = index
        if _page_changed:
            sound_manager.play("page_switch")
        self.query_one(ContentSwitcher).current = _PAGE_IDS[index]
        self.status.refresh_status(self._state, self._state.current_slot_index,
                                   self._page_index)
        # Keep the evidence board focused when stepping between pages.
        if self._evidence_open:
            board = self._active_editable_board()
            if board is not None:
                board.focus()
        # Always repaint the candidate-page summary so flagged violations
        # show up immediately when the player returns to page 0.
        if index == 0:
            self.board.repaint()
        self._refresh_footer()

    def _load_current_candidate(self) -> None:
        # Tear the reveal down BEFORE anything else. A pending pulse timer
        # firing after the next candidate is on screen would paint the new
        # dossier red for someone else's mistake, and NEXT is deliberately
        # live from the first frame of the window — so this path is reached
        # mid-pulse routinely, not exceptionally.
        self._end_verdict_reveal()

        slot = self._state.current_slot_index
        if slot >= self._day.candidate_count:
            self.app.finish_day()
            return

        self._candidate      = candidate_gen.generate(self._state.seed, self._day, slot)
        self._verdict_locked = False
        self.btn_admit.disabled = False
        self.btn_deny.disabled  = False
        self.btn_next.disabled  = True
        self._spent.clear()
        self._compute_before = self._state.compute_hours

        # Update all panels
        c = self._candidate
        ups = self._state.upgrades
        # Auto-highlight upgrades (issue #23): wire ownership into the panels
        # BEFORE set_candidate so the first render already honours them.
        self.dossier.upgrades    = ups
        self.chat.upgrades       = ups
        self.image_st.tint_boost = config.UPGRADE_STEGO_TINT in ups
        self._credit_revealed    = False   # fresh candidate — reveal unpaid (issue #25)
        self.dossier.cracked_password = None   # issue #29 — fresh password state
        self.dossier.set_candidate(c)
        self.chat.set_candidate(c)
        self.debug.set_candidate(c)
        for cd in (self.cdos_gs, self.cdos_hc, self.cdos_lw, self.cdos_st):
            cd.upgrades = ups
            cd.cracked_password = None         # issue #29 — fresh password state
            cd.set_candidate(c)

        # Candidate-page reference: today's rules + global accept/reject guide
        self.ref_main.update_content(_REF_CANDIDATE)

        # Reference panel: target email + claimed IP + today's rules + violation guide
        self.ref_hc.update_content(_REF_HASHCRACK)

        # Clear the shared evidence record and repaint every board view.
        self.evidence_state.clear()
        for b in (self.board, self.board_c0, *self._tool_boards):
            b.reset_cursor()
        # All tool terminals cleared via set_initial_content
        # Ghostscan: passive identity check (free) + breach list pre-population
        self.term_gs.set_initial_content(tools_bridge.get_ghostscan_identity(c))
        self.ref_gs.update_content(_REF_GHOSTSCAN)
        self.breach_lists.load_candidate(c, self._state.seed, self._day)
        # Hashcrack terminal: shared credential audit log (free, candidate highlighted;
        # Credential HUD upgrade pre-colours suspicious lines — issue #23)
        self.term_hc.set_initial_content(tools_bridge.get_hashcrack_shared(
            self._hc_log, c,
            upgrade_highlight=config.UPGRADE_HASH_HIGHLIGHT in ups))
        # Logwatch terminal: shared day log (Log Analyzer HUD upgrade applied
        # when owned — issue #23)
        self.term_lw.set_initial_content(tools_bridge.get_logwatch_shared(
            self._day_log, c,
            upgrade_highlight=config.UPGRADE_LOG_HIGHLIGHT in ups))
        # Logwatch reference: target info + today's rules + attack pattern guide
        self.ref_lw.update_content(_REF_LOGWATCH)
        # Stegotool: findings terminal gets the free stats block; the pixel
        # grid lives in the image viewer where the stamp minigame runs.
        self._stamp_mode     = False
        self._stego_resolved = False
        self._stego_filter   = False
        self.term_st.set_initial_content(tools_bridge.get_stego_stats(c, upgrades=ups))
        self.image_st.load_candidate(c, self._day.number if self._day else 1)
        # Stegotool reference: stamp-mode controls + signature color legend
        self.ref_st.update_content(_REF_STEGOTOOL)

        self.status.refresh_status(self._state, slot, self._page_index)
        self._refresh_footer()

    def _rules_tab_for_page(self) -> str:
        """#50: the Rules-overlay tab matching the page the player is on.

        Opening the docs from Logwatch should land on the Logwatch tab — the
        player is looking something up about the thing in front of them, not
        re-reading the day's ruleset.
        """
        if 0 <= self._page_index < len(_PAGE_TAB):
            return _PAGE_TAB[self._page_index]
        return "tab-rules"

    def _advance_to_next_candidate(self) -> None:
        """Move to the next candidate slot — shared by the "next" text
        command and the NEXT button (batch-3 follow-up) so the two entry
        points can't drift apart. Callers are responsible for checking
        _verdict_locked first (both do)."""
        self._state.current_slot_index += 1
        self._goto_page(0)
        self._load_current_candidate()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """ADMIT/DENY/NEXT buttons (batch-3 follow-up) — routes straight
        through _commit_verdict()/_advance_to_next_candidate(), identically
        to the "admit"/"deny"/"next" text commands."""
        if event.button.id == "btn-admit":
            event.stop()
            self._commit_verdict(Verdict.ADMIT)
        elif event.button.id == "btn-deny":
            event.stop()
            self._commit_verdict(Verdict.DENY)
        elif event.button.id == "btn-next":
            event.stop()
            # Guard mirrors the "next" text command's own check — the button
            # is disabled until a verdict lands, but a test (or a stray
            # .press()) shouldn't be able to skip a candidate for free.
            if self._verdict_locked:
                self._advance_to_next_candidate()

    def _commit_verdict(self, verdict: Verdict) -> None:
        if self._verdict_locked or self._candidate is None:
            return
        self._verdict_locked = True
        self.btn_admit.disabled = True
        self.btn_deny.disabled  = True
        self.btn_next.disabled  = False
        compute_before = self._state.compute_hours
        # #38: hand scoring the day's rule evaluation so the LITERAL-RULESET
        # track is recorded alongside the moral one. Payouts are unaffected -
        # the economy still keys off ground truth; this is a parallel value.
        result = scoring.apply(
            self._candidate, verdict, self._state,
            player_flags=self.board.get_flags(),
            evaluation=rules_engine.evaluate(self._candidate, self._day),
        )
        compute_after = self._state.compute_hours
        sound_manager.play({
            (True,  Verdict.ADMIT): "verdict_correct_accept",
            (True,  Verdict.DENY):  "verdict_correct_deny",
            (False, Verdict.ADMIT): "verdict_incorrect_accept",
            (False, Verdict.DENY):  "verdict_incorrect_deny",
        }[(result.correct, verdict)])
        self.overseer.record_result(result, compute_before, compute_after)

        v_str   = "ADMITTED" if verdict == Verdict.ADMIT else "DENIED"
        parts   = [f"{v_str} {self._candidate.display_name}."]
        parts  += ["Correct." if result.correct else "Wrong call."]
        if result.site_health_delta:
            parts.append(f"⛨ {result.site_health_delta:+.1f}% at EOD")
        if result.hackdollar_delta:
            parts.append(f"+{result.hackdollar_delta} HD$")
            if result.board_bonus:
                parts.append(f"(+{result.board_bonus} HD$ board bonus)")
        if result.alignment_delta:
            arrow = "→ White Hat" if result.alignment_delta > 0 else "→ Dark Web"
            parts.append(f"Align {arrow}")
        # #38: the moment being right by the book and right by conscience come
        # apart is the corruption arc's whole point - say so out loud.
        if result.tracks_diverge:
            parts.append("[#c084fc]by the book, not by conscience[/]"
                         if result.rules_correct else
                         "[#c084fc]against the book[/]")

        self.command_bar.set_response("  ·  ".join(parts), error=not result.correct)
        self.status.refresh_status(self._state, self._state.current_slot_index,
                                   self._page_index)
        self._refresh_footer()

        # The reveal window fires last, after the economy has already been
        # settled above. It is presentation only: nothing inside it touches
        # GameState, so switching it off (config.VERDICT_REVEAL_ENABLED) can
        # never change what a shift is worth.
        self._begin_verdict_reveal(verdict, result.correct)

        # Site Health deltas are only recorded here — they apply in one
        # batch at end of day (finish_day), so the loss condition can only
        # trip at shift end (#20 rework).

    # ── Verdict reveal window ─────────────────────────────────────────

    # Every panel the pulse paints. The tool-page boards are in the list on
    # purpose: A/D work from any page, so a player who delivers a verdict while
    # reading a log should still get the flash rather than a silent page they
    # have to navigate away from to learn anything.
    _FLASH_IDS: ClassVar[tuple[str, ...]] = (
        "dossier", "chat", "evidence-board", "evidence-c0", "verdict-panel",
        "evidence-gs", "evidence-hc", "evidence-lw", "evidence-st",
    )

    def _flash_targets(self):
        """The mounted widgets the pulse applies to, skipping any that aren't
        on this screen. Queried fresh each time rather than cached: the
        Candidate-page board swaps between #evidence-board and #evidence-c0 on
        Tab, so a cached handle would eventually paint a hidden widget."""
        found = []
        for wid in self._FLASH_IDS:
            try:
                found.append(self.query_one(f"#{wid}"))
            except Exception:  # noqa: BLE001, S110 -- a panel that isn't mounted is
                # nothing to flash, not an error.
                pass
        return found

    def _begin_verdict_reveal(self, verdict: Verdict, correct: bool) -> None:
        """Play the post-verdict feedback beat.

        Three channels fire together, each answering a different question:

          chat    — "how did that land on the person?"  (see reactions.py)
          borders — "was I right?"                      (green/red pulse)
          board   — "were my individual calls right?"   (EvidenceState.reveal)

        Only the border pulse is time-boxed. The chat reaction and the graded
        board persist until the next candidate loads, because those are things
        a player reads at their own pace — a grade that erases itself after
        three seconds is a grade nobody gets to use.

        Nothing here blocks: NEXT was enabled by the caller before this ran, so
        the beat is always skippable and the pulse is simply cut short.
        """
        if not config.VERDICT_REVEAL_ENABLED or self._candidate is None:
            return
        self._end_verdict_reveal()   # never stack two windows

        # ── Channel 1: the candidate answers back ─────────────────────
        self.chat.post_reaction(self._candidate, verdict)

        # ── Channel 2: grade the board ────────────────────────────────
        # Scoped to what this player can actually see. A violation behind a
        # tool they have not unlocked yet is excluded from both the grade and
        # the unrecorded count — the game never marks someone down for missing
        # evidence it refused to show them (#33's progressive unlock).
        actual  = {d.kind for d in self._candidate.truth.discrepancies}
        visible = {k for _g, k, _l in
                   rules_content.visible_catalog(self._state.unlocked_tools)}
        self.evidence_state.reveal(actual, visible)
        for b in (self.board, self.board_c0, *self._tool_boards):
            b.repaint()

        # ── Channel 3: pulse the borders ──────────────────────────────
        sound_manager.play("pulse_celebration" if correct else "pulse_error")
        bright = "vf-ok-bright" if correct else "vf-bad-bright"
        dim    = "vf-ok-dim"    if correct else "vf-bad-dim"
        self._reveal_classes = (bright, dim)
        targets = self._flash_targets()
        for w in targets:
            w.add_class(bright)

        state = {"on": True}

        def _toggle() -> None:
            state["on"] = not state["on"]
            add, remove = (bright, dim) if state["on"] else (dim, bright)
            for widget in self._flash_targets():
                widget.remove_class(remove)
                widget.add_class(add)

        self._reveal_timers = [
            self.set_interval(config.VERDICT_REVEAL_PULSE_INTERVAL, _toggle),
            self.set_timer(config.VERDICT_REVEAL_DURATION, self._end_verdict_reveal),
        ]

    def _end_verdict_reveal(self) -> None:
        """Stop the pulse and strip its classes. Idempotent — it is called on
        the duration timer, on every candidate load, and on unmount, and any
        of those can be the one that actually lands first."""
        for timer in self._reveal_timers:
            try:
                timer.stop()
            except Exception:  # noqa: BLE001, S110 -- an already-expired timer is
                # exactly the state we want; stopping it again is a no-op.
                pass
        self._reveal_timers = []
        if not any(self._reveal_classes):
            return
        for widget in self._flash_targets():
            widget.remove_class(*self._reveal_classes)
        self._reveal_classes = ("", "")

    def on_unmount(self) -> None:
        """The day can end (or the app can quit) mid-pulse — leave no timer
        holding a reference to a screen that is on its way out."""
        self._end_verdict_reveal()

    def _run_tool(self, tool: ToolName, *, filtered: bool = False) -> None:
        # Progressive unlock (#33): a locked tool is fully inert — the shortcut
        # keys (G/L/H/S/F) route here, so this is the single choke-point that
        # guarantees a locked tool never runs and never charges ⏱.
        if tool.value not in self._state.unlocked_tools:
            self.command_bar.set_response(
                f"{tool.value.upper()} is locked — not available yet.",
                error=False,
            )
            return
        if self._candidate is None or self._verdict_locked:
            return
        if tool in self._spent and not filtered:
            self.command_bar.set_response(
                f"{tool.value.upper()} already run — type 'filter' for enhanced analysis",
                error=False,
            )
            return

        runners = {
            ToolName.GHOSTSCAN: (tools_bridge.run_ghostscan_shared,
                                 tools_bridge.run_ghostscan_filtered_shared),
            ToolName.LOGWATCH:  (lambda c, s: tools_bridge.run_logwatch_shared(
                                     self._day_log, c, s),
                                 lambda c, s: tools_bridge.run_logwatch_filtered_shared(
                                     self._day_log, c, s)),
            ToolName.HASHCRACK: (lambda c, s: tools_bridge.run_hashcrack_shared(self._hc_log, c, s),
                                 lambda c, s: tools_bridge.run_hashcrack_filtered_shared(self._hc_log, c, s)),
            # STEGOTOOL intentionally absent — the stego page uses the
            # interactive stamp minigame instead of a flat tool run.
        }
        base_fn, filter_fn = runners[tool]
        try:
            result = filter_fn(self._candidate, self._state) if filtered \
                     else base_fn(self._candidate, self._state)
        except tools_bridge.InsufficientCompute as e:
            self.command_bar.set_response(str(e), error=True)
            return

        sound_manager.play({
            ToolName.GHOSTSCAN: "tool_run_ghostscan",
            ToolName.HASHCRACK: "tool_run_hashcrack",
            ToolName.LOGWATCH:  "tool_run_logwatch",
        }[tool])
        if filtered:
            sound_manager.play("filter_apply")

        # Get the right terminal and display the result.
        # Logwatch/Hashcrack replace the terminal content in-place (annotate
        # the shared log). Ghostscan also replaces (issue #28): the filtered
        # report re-renders the same report with annotations lit, never
        # stacking a second copy.
        term_id = self._TOOL_TERM[tool]
        term = self.query_one(f"#{term_id}", ToolTerminal)
        if tool in (ToolName.LOGWATCH, ToolName.HASHCRACK):
            term.set_initial_content(result.raw_lines)
        elif tool == ToolName.GHOSTSCAN:
            term.set_result(result)
        else:
            term.add_result(result)

        # Update breach list panel state when ghostscan runs. Batch-3 task
        # #4c: Breach Feed Sync (config.UPGRADE_BREACH_AUTO) confirms matches
        # on the free base run too, same as tools_bridge.run_ghostscan_shared.
        if tool == ToolName.GHOSTSCAN:
            _breach_auto = config.UPGRADE_BREACH_AUTO in self._state.upgrades
            if filtered or _breach_auto:
                self.breach_lists.confirm_match()
            else:
                self.breach_lists.highlight_match()

        # Issue #29: a hashcrack run resolves the dossier password field —
        # cracked plaintext (or a held bcrypt) is reflected on every page.
        if tool == ToolName.HASHCRACK:
            plain = tools_bridge.crack_password(self._candidate)
            resolved = plain if plain is not None else ""
            for panel in (self.dossier, self.cdos_gs, self.cdos_hc,
                          self.cdos_lw, self.cdos_st):
                panel.cracked_password = resolved
                panel.refresh()

        self._spent.add(tool)
        self.status.refresh_status(self._state, self._state.current_slot_index,
                                   self._page_index)
        cost = tools_bridge.tool_cost(self._state, tool.value)
        if filtered:
            cost += config.FILTER_COSTS[tool.value]
        self.command_bar.set_response(
            f"{'[FILTERED] ' if filtered else ''}"
            f"{tool.value.upper()} complete  −{cost} ⏱  ·  "
            f"flag findings on the Evidence Board (page 1)",
            error=False,
        )

    # ── Stegotool stamp minigame ──────────────────────────────────────────

    def _enter_stamp_mode(self) -> None:
        # Progressive unlock (#33): the stego stamp minigame is the Stegotool's
        # run surface, so it's inert until Stegotool is unlocked. (_goto_page(4)
        # already refuses the page, but the 's' shortcut calls this directly.)
        if "stegotool" not in self._state.unlocked_tools:
            self.command_bar.set_response(
                "STEGOTOOL is locked — not available yet.", error=False)
            return
        if self._candidate is None or self._verdict_locked:
            self.command_bar.set_response(
                "Verdict locked — stamping disabled", error=True)
            return
        self._stamp_mode = True
        self.image_st.enter_stamp_mode()
        sound_manager.play("tool_run_stegotool")
        self.command_bar.set_response(
            f"STAMP MODE — arrows move · Space stamp "
            f"(−{config.STEGO_STAMP_COST} ⏱) · Esc exit")
        self._refresh_footer()

    def _exit_stamp_mode(self, quiet: bool = False) -> None:
        self._stamp_mode = False
        self.image_st.exit_stamp_mode()
        if not quiet:
            self.command_bar.set_response("stamp mode off")
        self._refresh_footer()

    def _do_stamp(self) -> None:
        if self._candidate is None or self._verdict_locked:
            return
        try:
            tools_bridge.charge_stamp(self._state)
        except tools_bridge.InsufficientCompute as e:
            self.command_bar.set_response(str(e), error=True)
            return
        res = self.image_st.do_stamp()
        if res is None:
            return
        sound_manager.play("stego_stamp")
        x, y, _w, _h = self.image_st.stamp_rect
        img   = self.image_st.image
        lines = tools_bridge.stamp_log_lines(img, res, self.image_st.stamps_used, x, y,
                                             reveal_type=self._stego_filter)
        if res.resolved and not self._stego_resolved:
            self._stego_resolved = True
            lines = lines + tools_bridge.stamp_signature_lines(
                img, reveal_type=self._stego_filter)
        self.term_st.add_lines(lines)
        self.status.refresh_status(self._state, self._state.current_slot_index,
                                   self._page_index)

    def _activate_stego_filter(self) -> None:
        """Pay to classify the stego payload type. Until this runs, stamp logs
        report a carrier but not its type — the player reads the stamp colour."""
        if self._candidate is None or self._verdict_locked:
            self.command_bar.set_response(
                "Verdict locked — filter disabled", error=True)
            return
        if self._stego_filter:
            self.command_bar.set_response("Filter already active — payload type is classified")
            return
        cost = config.STEGO_FILTER_COST
        if config.UPGRADE_TOOLCOST_STEGOTOOL in self._state.upgrades:
            cost = max(1, cost - config.TOOLCOST_REDUCTION)
        if self._state.compute_hours < cost:
            self.command_bar.set_response(
                f"Need {cost} ⏱ for the classification filter, "
                f"have {self._state.compute_hours} ⏱", error=True)
            return
        self._state.compute_hours -= cost
        self._stego_filter = True
        sound_manager.play("filter_apply")
        img = self.image_st.image
        lines = [
            "",
            f"[#7dd3c0][b]CLASSIFICATION FILTER[/][/]  [dim]−{cost} ⏱[/]",
            "  [dim]carrier signatures will now be named on each stamp[/]",
        ]
        # If the zone was already resolved before paying, print the named block now.
        if self._stego_resolved and img is not None:
            lines += tools_bridge.stamp_signature_lines(img, reveal_type=True)
        self.term_st.add_lines(lines)
        self.command_bar.set_response("Classification filter active — payload type will be named")
        self.status.refresh_status(self._state, self._state.current_slot_index,
                                   self._page_index)

    # ── HackDox Credit — ground-truth reveal (issue #25) ──────────────────

    def _credit_reveal(self) -> None:
        """Spend one HackDox Credit to reveal the current candidate's ground
        truth (correct verdict + planted violation kinds — NOT the evidence
        trail). Read-only; never submits a verdict. Works on every page since
        it reads engine state, not page-local data. Refused at 0 credits.
        Re-opening for the same candidate is free once paid."""
        if self._candidate is None:
            self.command_bar.set_response("No candidate loaded", error=True)
            return
        if self._credit_revealed:
            self.command_bar.set_response(
                "Ground truth already revealed for this candidate — no charge")
            self.app.push_screen(
                CreditRevealScreen(self._candidate, self._state.hackdox_credits))
            return
        if self._state.hackdox_credits <= 0:
            self.command_bar.set_response(
                "ACCESS DENIED — no HackDox Credits remaining. "
                "Buy more in the between-day shop.", error=True)
            return
        self._state.hackdox_credits -= 1
        self._credit_revealed = True
        sound_manager.play("credit_use")
        self.status.refresh_status(self._state, self._state.current_slot_index,
                                   self._page_index)
        self.command_bar.set_response(
            f"HackDox Credit spent — ground truth revealed  "
            f"({self._state.hackdox_credits} remaining)")
        self.app.push_screen(
            CreditRevealScreen(self._candidate, self._state.hackdox_credits))

    # ── Action bindings ───────────────────────────────────────────────────

    # ── Page navigation (number keys 1-5) ────────────────────────────────────

    def action_page_1(self) -> None: self._goto_page(0)
    def action_page_2(self) -> None: self._goto_page(1)
    def action_page_3(self) -> None: self._goto_page(2)
    def action_page_4(self) -> None: self._goto_page(3)
    def action_page_5(self) -> None: self._goto_page(4)

    # ── Rules overlay (immediate binding) ────────────────────────────────────

    def action_open_rules(self) -> None:
        self.app.push_screen(RulesScreen(self._day, self.evidence_state,
                        initial_tab=self._rules_tab_for_page(),
                        scroll_memory=self._rules_scroll,
                        unlocked_tools=self._state.unlocked_tools))

    # ── Within-page focus navigation (arrow keys) ─────────────────────────────
    # EvidenceBoard consumes up/down when focused; letters still bubble to bar.

    def action_focus_prev(self)  -> None:
        sound_manager.play("focus_switch")
        self.focus_previous()

    def action_focus_next(self)  -> None:
        sound_manager.play("focus_switch")
        self.focus_next()

    def action_focus_left(self)  -> None:
        sound_manager.play("focus_switch")
        self.focus_previous()

    def action_focus_right(self) -> None:
        sound_manager.play("focus_switch")
        self.focus_next()

    # ── Debug toggle (immediate binding, dev-only) ────────────────────────────

    def action_toggle_debug(self) -> None:
        self.debug.display = not self.debug.display

    # ── Command bar input routing ─────────────────────────────────────────────

    def on_key(self, event: Key) -> None:
        """Route keypresses: immediate actions first, then command bar input.

        on_key fires before BINDINGS in Textual, so immediate-action keys
        (page nav, rules, debug) must be handled explicitly here first.
        """
        k  = event.key
        ch = event.character  # empty string for non-printable keys

        # ── Stego stamp mode — captures arrows/Space/Esc while active ─────────
        if self._stamp_mode:
            if k in ("up", "down", "left", "right"):
                self.image_st.move_stamp(k); event.stop(); return
            if k == "space":
                self._do_stamp(); event.stop(); return
            if k in ("escape", config.KEY_BINDINGS["stamp_mode"]):
                self._exit_stamp_mode(); event.stop(); return
            if k not in ("1", "2", "3", "4", "5"):
                event.stop(); return          # swallow everything else
            self._exit_stamp_mode(quiet=True)  # page nav below exits stamp mode

        # ── Immediate actions (no Enter needed, do not enter command bar) ──────
        if k == "1":
            self._goto_page(0); event.stop(); return
        if k == "2":
            self._goto_page(1); event.stop(); return
        if k == "3":
            self._goto_page(2); event.stop(); return
        if k == "4":
            self._goto_page(3); event.stop(); return
        if k == "5":
            self._goto_page(4); event.stop(); return
        if k == "0":
            self.app.push_screen(RulesScreen(
                self._day, self.evidence_state,
                initial_tab=self._rules_tab_for_page(),
                scroll_memory=self._rules_scroll,
                unlocked_tools=self._state.unlocked_tools))
            event.stop(); return
        if k == config.KEY_BINDINGS["toggle_evidence"]:   # Tab
            if 0 <= self._page_index <= 4:
                # Toggles the editable board in place on every page, including
                # the Candidate/Dossier page (board_c0 swaps in for the
                # read-only summary there, same as a tool page's sidebar).
                self._toggle_evidence(); event.stop()
            return
        if k == "grave_accent":
            self.debug.display = not self.debug.display; event.stop(); return

        # ── Stamp mode entry — X on the stego page with an empty buffer ────────
        if (k == config.KEY_BINDINGS["stamp_mode"] and self._page_index == 4
                and not self.command_bar.get_buffer()):
            self._enter_stamp_mode(); event.stop(); return

        # ── Verdict/Next buttons — let Enter reach their own binding instead
        # of the command bar, when one of them is focused (batch-3 follow-up).
        if k == "enter" and self.focused in (self.btn_admit, self.btn_deny, self.btn_next):
            return

        # ── Command bar input ─────────────────────────────────────────────────
        if k == "enter":
            self._execute_command(self.command_bar.get_buffer())
            self.command_bar.clear_buffer()
            event.stop()

        elif k == "backspace":
            self.command_bar.backspace()
            event.stop()

        elif k == "escape":
            self.command_bar.clear_buffer()
            self.command_bar.set_response("cleared")
            event.stop()

        elif ch and ch.isprintable():
            self.command_bar.append_char(ch)
            event.stop()

    # ── Command execution ─────────────────────────────────────────────────────

    _FILTER_PAGE_MAP: ClassVar[dict[int, ToolName]] = {
        1: ToolName.GHOSTSCAN,
        2: ToolName.HASHCRACK,
        3: ToolName.LOGWATCH,
        # 4 (stegotool) removed — stamp minigame replaced scan/filter there.
    }

    def _execute_command(self, raw: str) -> None:
        """Parse a typed command and dispatch it."""
        s = raw.strip().lower()
        if not s:
            return

        parsed = _COMMAND_ALIASES.get(s)
        if parsed is None:
            self.command_bar.set_response(random.choice(_ERROR_MSGS), error=True)
            return

        kind, arg = parsed

        if kind == "tool":
            self._goto_page(self._TOOL_PAGE[arg])
            self._run_tool(arg)   # sets command_bar response internally

        elif kind == "stamp":
            self._goto_page(4)
            self._enter_stamp_mode()

        elif kind == "filter":
            if self._page_index == 4:
                self._activate_stego_filter()
                return
            tool = self._FILTER_PAGE_MAP.get(self._page_index)
            if tool is None:
                self.command_bar.set_response(
                    "ERROR — navigate to a tool page first (pages 2–4)", error=True
                )
            else:
                self._run_tool(tool, filtered=True)

        elif kind == "verdict":
            self._commit_verdict(arg)   # sets command_bar response internally

        elif kind == "reveal":
            self._credit_reveal()

        elif kind == "next":
            if not self._verdict_locked:
                self.command_bar.set_response(
                    "ERROR — commit a verdict first  (type: admit  or  deny)", error=True
                )
            else:
                self._advance_to_next_candidate()

        elif kind == "rules":
            self.app.push_screen(RulesScreen(self._day, self.evidence_state,
                        initial_tab=self._rules_tab_for_page(),
                        scroll_memory=self._rules_scroll,
                        unlocked_tools=self._state.unlocked_tools))

        elif kind == "evidence":
            self._toggle_evidence()

        elif kind == "help":
            self.command_bar.set_response(
                "COMMANDS:  recon · crack · analyze · stamp (stego) · filter · "
                "admit · deny · next · rules · evidence · help · quit  "
                "·  pages 1-5  ·  rules 0  ·  Tab = evidence board (tool pages)  "
                "·  X = stamp mode (stego page)",
                error=False,
            )

        elif kind == "quit":
            self.app.exit()
