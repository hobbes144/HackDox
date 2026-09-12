"""HackDox Terminal — Textual TUI.

Page-based layout. Five pages + Rules overlay:

  1  CANDIDATE  — Dossier · Chat · Evidence Board · Overseer · Reference
  2  GHOSTSCAN  — Condensed Dossier · Reference · Tool Terminal
  3  HASHCRACK  — Condensed Dossier · Reference · Tool Terminal
  4  LOGWATCH   — Condensed Dossier · Reference · Tool Terminal
  5  STEGOTOOL  — Condensed Dossier · Reference · Tool Terminal
  0  RULES      — Full day rulebook overlay (dismiss with 0 or Esc)

Key principles:
  • Number keys 1-5 switch pages; arrow keys navigate focus between panels.
  • The Evidence Board is player-controlled only — nothing auto-populates.
  • Tool keys (G/L/H/S) jump to that page and run the tool in one keystroke.
  • A/D verdict keys work on every page.
  • Filters (F key on any tool page) run an enhanced analysis at extra ⏱ cost.
  • Computing hours (⏱) replace currency throughout.
  • All key bindings live in config.KEY_BINDINGS — change them there."""

from __future__ import annotations

from textual.app import App

from gameengine import config
from gameengine.core import persistence, scoring
from gameengine.core.audio import sound_manager
from gameengine.core.content_loader import (
    generic_outro_key,
    load_day,
    load_narratives,
    resolve_narrative,
)
from gameengine.core.models import Day, GameState, Performance, Verdict

# ─── Backward-compat facade ─────────────────────────────────────────────────
# gameengine/ui/tui/app.py used to be a single ~3,700-line module holding every
# widget and screen. It is now split into shared.py / widgets/ / screens/; the
# re-exports below keep `from gameengine.ui.tui.app import X` working for the
# existing test suite and hackdox.py without either needing changes.
#
# Ruff's F401 (unused-import) would otherwise call every name below dead code,
# since nothing else in this module references them directly. __all__ is the
# standard way to tell the linter — and the next reader — that these are
# intentional re-exports, not leftovers from the split.
from gameengine.ui.tui.screens._narration import (
    _RULE_CHANGE_PHRASINGS,
    _UNLOCK_LINES,
    _overseer_lines,
    _play_overseer,
    _rule_fragment,
    _starts_a_sentence,
    rule_change_lines,
)
from gameengine.ui.tui.screens.between_day import BetweenDayScreen
from gameengine.ui.tui.screens.briefing import BriefingScreen
from gameengine.ui.tui.screens.campaign_end import CampaignEndScreen
from gameengine.ui.tui.screens.credit_reveal import CreditRevealScreen
from gameengine.ui.tui.screens.eod import EODScreen
from gameengine.ui.tui.screens.game_over import GameOverScreen
from gameengine.ui.tui.screens.intake import IntakeScreen
from gameengine.ui.tui.screens.intro import IntroScreen
from gameengine.ui.tui.screens.rules import RulesScreen
from gameengine.ui.tui.screens.transition import TransitionScreen
from gameengine.ui.tui import glitch
from gameengine.ui.tui.shared import (
    _B,
    _BOARD_HOME_GROUP,
    _COMMAND_ALIASES,
    _ERROR_MSGS,
    _GROUP_META,
    _GROUP_ORDER,
    _PAGE_IDS,
    _PAGE_NAMES,
    _PAGE_TAB,
    _PAGE_TOOL,
    _PW_STRENGTH_META,
    _REF_CANDIDATE,
    _REF_GHOSTSCAN,
    _REF_HASHCRACK,
    _REF_LOGWATCH,
    _REF_STEGOTOOL,
    _SEV_COLOR,
    _SEVERITY,
    EVIDENCE_ITEMS,
    _format_day_rules,
    _hl_affil,
    _hl_email,
    _password_markup,
    _sev_color,
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
    Toast,
    ToolTerminal,
    TypewriterLog,
    _TWMessage,
)

__all__ = [
    # shared.py internals
    "EVIDENCE_ITEMS",
    "_B",
    "_BOARD_HOME_GROUP",
    "_COMMAND_ALIASES",
    "_ERROR_MSGS",
    "_GROUP_META",
    "_GROUP_ORDER",
    "_PAGE_IDS",
    "_PAGE_NAMES",
    "_PAGE_TAB",
    "_PAGE_TOOL",
    "_PW_STRENGTH_META",
    "_REF_CANDIDATE",
    "_REF_GHOSTSCAN",
    "_REF_HASHCRACK",
    "_REF_LOGWATCH",
    "_REF_STEGOTOOL",
    "_RULE_CHANGE_PHRASINGS",
    "_SEVERITY",
    "_SEV_COLOR",
    "_UNLOCK_LINES",
    # Screens
    "BetweenDayScreen",
    # widgets
    "BreachListPanel",
    "BriefingScreen",
    "CampaignEndScreen",
    "ChatPanel",
    "CommandBar",
    "CondensedDossier",
    "CreditRevealScreen",
    "DebugPanel",
    "DossierPanel",
    "EODScreen",
    "EvidenceBoard",
    "EvidenceState",
    "GameOverScreen",
    "HackDoxApp",
    "IntakeScreen",
    "IntroScreen",
    "OverseerPanel",
    "ReferencePanel",
    "RulesScreen",
    "StatusHeader",
    "StegoImagePanel",
    "Toast",
    "ToolTerminal",
    "TransitionScreen",
    "TypewriterLog",
    "_TWMessage",
    "_format_day_rules",
    "_hl_affil",
    "_hl_email",
    # screens/_narration.py internals
    "_overseer_lines",
    "_password_markup",
    "_play_overseer",
    "_rule_fragment",
    "_sev_color",
    "_starts_a_sentence",
    "rule_change_lines",
    "run",
]


class HackDoxApp(App):
    CSS_PATH = "app.tcss"
    TITLE    = "HackDox Terminal"
    SUB_TITLE = "Cybersecurity Access Review"

    def __init__(self, seed: int = 0xC0FFEE, lab_day: Day | None = None) -> None:
        super().__init__()
        self._seed       = seed
        # #52: `hackdox lab --play` hands in a pre-constrained Day so a shift can
        # be played with a pinned archetype / violation set. When set it replaces
        # the loaded day everywhere, and advance_day ends the run after it rather
        # than rolling into normal content — a lab shift is one shift on purpose.
        self._lab_day    = lab_day
        self._state: GameState | None = None
        self._day:   Day        | None = None
        self._narratives: dict[str, str] = {}
        self._day_start_health: float = config.SITE_HEALTH_START
        self._hd_earned = 0   # HD$ from verdicts, set at finish_day
        self._hd_bonus  = 0   # HD$ Site Health bonus, set at finish_day
        # Transition bookkeeping (see _transition).
        self._transition_busy   = False
        self._queued_screen: object | None = None

    def on_mount(self) -> None:
        self._narratives = load_narratives()
        self.push_screen(IntroScreen())

    def start_new_game(self) -> None:
        self._state = GameState(
            seed=self._seed,
            current_day=1,
            compute_hours=config.daily_compute_budget(1, config.STARTING_COMPUTE),
            compute_capacity=config.STARTING_COMPUTE,
            alignment=config.STARTING_ALIGNMENT,
            site_health=config.SITE_HEALTH_START,
            hackdollars=config.STARTING_HACKDOLLARS,
            hackdox_credits=config.STARTING_HACKDOX_CREDITS,
        )
        if self._lab_day is not None:
            self._state.current_day = self._lab_day.number
            self._state.compute_hours = config.daily_compute_budget(
                self._lab_day.number, config.STARTING_COMPUTE)
            # A lab shift skips the unlock schedule: pinning a stegotool case on
            # day 5 is pointless if stegotool is still locked.
            self._state.unlocked_tools = config.tools_unlocked_by(
                max(self._lab_day.number, max(config.TOOL_UNLOCK_DAY.values())))
        self._day_start_health = self._state.site_health
        self._day = self._lab_day or load_day(self._state.current_day)
        # #15: falls through to generic copy rather than an empty panel — days
        # 2-20 had no authored intro key at all and opened on silence.
        narrative = resolve_narrative(
            self._narratives, self._day.overseer_intro_key, "generic_intro")
        self._transition(BriefingScreen(self._day, narrative, self._state))

    def begin_intake(self) -> None:
        assert self._state is not None and self._day is not None
        sound_manager.play("day_start")
        self._day_start_health = self._state.site_health
        intro = resolve_narrative(
            self._narratives, self._day.overseer_intro_key, "generic_intro")
        self._transition(IntakeScreen(self._day, self._state, intro))

    def finish_day(self) -> None:
        assert self._state is not None and self._day is not None
        sound_manager.play("day_end")
        # #20 rework: the day's accumulated Site Health deltas land HERE, in
        # one batch — health never moves mid-shift, so the loss condition is
        # only evaluated from this point on.
        scoring.apply_end_of_day_health(self._state)
        # End-of-day HackDollar$ payout (issue #21): verdict earnings accrued
        # during play; the Site Health bonus (issue #20) lands here.
        self._hd_earned = sum(r.hackdollar_delta
                              for r in self._state.pending_results)
        self._hd_bonus  = scoring.eod_health_bonus(self._state)
        self._state.hackdollars += self._hd_bonus
        performance = self._evaluate_performance()
        outro_key   = self._day.overseer_outro_keys.get(
            performance, self._day.overseer_outro_keys[Performance.PASSING]
        )
        # #15: was the literal string "..." on every unauthored day.
        narrative = resolve_narrative(self._narratives, outro_key,
                                      generic_outro_key(performance))
        self._transition(EODScreen(
            self._day, self._state, narrative, performance,
            hd_earned=self._hd_earned, hd_bonus=self._hd_bonus,
            health_delta=self._state.site_health - self._day_start_health,
        ))

    def game_over(self) -> None:
        self._transition(GameOverScreen())

    def show_between_day(self) -> None:
        """EOD → between-day menu (issue #22)."""
        assert self._state is not None and self._day is not None
        # #15: the generic copy moved into overseer.json under
        # "generic_between", so every line the Overseer speaks lives in one
        # editable file rather than half of it being buried in the UI.
        narrative = resolve_narrative(
            self._narratives, f"day{self._day.number}_between",
            "generic_between")
        self._transition(BetweenDayScreen(
            self._day, self._state, narrative,
            hd_earned=self._hd_earned, hd_bonus=self._hd_bonus,
            health_delta=self._state.site_health - self._day_start_health,
        ))

    def advance_day(self) -> None:
        """Between-day menu → next day intro. Resets the shift budget."""
        assert self._state is not None
        st = self._state
        if scoring.health_below_loss(st):   # loss trips at end of day (#20)
            self.game_over()
            return
        # #36: hold on to yesterday's ruleset before loading today's, so the
        # briefing can diff the two and announce what the Overseer moved.
        prev_day = self._day
        if self._lab_day is not None:
            # One shift, then out — a lab run has no day 2.
            self._transition(CampaignEndScreen(st.current_day))
            return
        st.current_day += 1
        st.current_slot_index = 0
        st.pending_results = []
        # ⏱ resets to the day's fixed budget every shift — never carries
        # over (issues #21/#27). The formula scales with the day number.
        st.compute_hours = config.daily_compute_budget(
            st.current_day, st.compute_capacity)
        persistence.save(st)
        try:
            self._day = load_day(st.current_day)
        except FileNotFoundError:
            self._transition(CampaignEndScreen(st.current_day))
            return
        self._day_start_health = st.site_health
        # #15: falls through to generic copy rather than an empty panel — days
        # 2-20 had no authored intro key at all and opened on silence.
        narrative = resolve_narrative(
            self._narratives, self._day.overseer_intro_key, "generic_intro")
        self._transition(BriefingScreen(self._day, narrative, self._state,
                                        prev_day=prev_day))

    # ── Screen transitions (glitch) ─────────────────────────────────────
    #
    # Every full-screen change goes through _transition instead of a bare
    # pop/push, so the change is covered by the CRT signal-loss effect and
    # input is dead while it runs. Knobs live in config.TRANSITION_*; set
    # TRANSITION_ENABLED = False and every swap cuts instantly again.
    #
    # Page switches inside a shift (1-5) and the modal overlays (rules,
    # evidence board, credit reveal) deliberately do NOT use this — they
    # happen dozens of times a shift.

    def _swap_screen(self, screen) -> None:
        """The bare screen change every transition eventually performs."""
        self.pop_screen()
        self.push_screen(screen)

    def _transition(self, screen) -> None:
        """Glitch over the screen change, in two halves.

        First half covers the OUTGOING screen and ramps to full coverage;
        the swap happens at the peak (in _transition_swap, where nothing is
        visible); the second half decays back to clear over the INCOMING
        screen. Both halves are modal screens, so the keyboard is dead from
        the first frame to the last.
        """
        if not config.TRANSITION_ENABLED:
            self._swap_screen(screen)
            return
        if self._transition_busy:
            # Input is dead for the whole window, so a second screen change
            # mid-transition can only come from a stray timer. Honour it at
            # the end rather than stacking a second glitch, which would leave
            # a transition screen orphaned on the stack.
            self._queued_screen = screen
            return
        self._transition_busy = True
        sound_manager.play("transition_glitch")
        out_dur = max(0.01, config.TRANSITION_DURATION * config.TRANSITION_SWAP_AT)
        in_dur  = max(0.01, config.TRANSITION_DURATION - out_dur)
        self.push_screen(TransitionScreen(
            phase=glitch.PHASE_OUT, duration=out_dur,
            on_complete=lambda: self._transition_swap(screen, in_dur)))

    def _transition_swap(self, screen, in_dur: float) -> None:
        """Midpoint: swap the screen underneath the noise, then decay out.

        The four stack operations run in ONE callback with nothing awaited
        between them, so the compositor never gets a chance to paint the
        intermediate states — the player sees full-coverage noise throughout.
        """
        self.pop_screen()            # this half of the glitch
        self._swap_screen(screen)    # the actual screen change, unseen
        self.push_screen(TransitionScreen(
            phase=glitch.PHASE_IN, duration=in_dur,
            on_complete=self._transition_end))

    def _transition_end(self) -> None:
        self.pop_screen()            # the incoming half — input is live again
        self._transition_busy = False
        queued, self._queued_screen = self._queued_screen, None
        if queued is not None:
            self._swap_screen(queued)

    def _evaluate_performance(self) -> Performance:
        assert self._state is not None and self._day is not None
        correct_admits = sum(
            1 for r in self._state.pending_results
            if r.correct and r.player_verdict == Verdict.ADMIT
        )
        false_admits = sum(
            1 for r in self._state.pending_results
            if not r.correct and r.player_verdict == Verdict.ADMIT
        )
        quotas = self._day.quotas
        if scoring.health_below_loss(self._state):
            return Performance.FAILED
        if false_admits > quotas.max_false_admits:
            return Performance.FAILED
        if correct_admits < quotas.min_correct_admits:
            return Performance.POOR
        # (compute_target check removed — issue #27: ⏱ is spend-only, so an
        # end-of-day balance target no longer exists.)
        wrong = sum(1 for r in self._state.pending_results if not r.correct)
        if wrong == 0:
            return Performance.EXCELLENT
        return Performance.PASSING


def run(seed: int = 0xC0FFEE, lab_day: Day | None = None) -> None:
    HackDoxApp(seed=seed, lab_day=lab_day).run()


if __name__ == "__main__":
    run()
