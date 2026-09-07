"""Tests for the post-verdict reveal window.

Three feedback channels fire when a verdict lands — the candidate's chat
reaction, a green/red border pulse, and the evidence board's grading — and the
window is skippable at any moment. The tests below are organised around the
two things most likely to break:

  * **The grading contract.** The board must mark only what the player
    touched, must never mark them down for evidence behind a locked tool, and
    must agree with the HD$ bonus about what counts as a correct flag.
  * **Teardown.** NEXT is live from the first frame, so a pulse timer outliving
    its candidate is a routine possibility, not an edge case. A leaked timer
    would paint the *next* candidate's dossier red for someone else's mistake.

The pulse's CSS cascade is checked for real (not just for the class being
added) because the flash rules have to out-specify `:focus` / `:focus-within`
purely on document order — a well-meaning tidy-up that moves them up the
stylesheet would silently stop a focused panel from ever flashing.
"""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Static

from gameengine import config
from gameengine.core import candidate_gen, scoring
from gameengine.core.content_loader import load_day
from gameengine.core.models import Archetype, DiscrepancyKind, GameState, Verdict
from gameengine.ui.tui import reactions
from gameengine.ui.tui.app import IntakeScreen
from gameengine.ui.tui.widgets import EvidenceState

SEED = 0xC0FFEE
ALL_TOOLS = {"ghostscan", "hashcrack", "logwatch", "stegotool"}

# Every flash class the pulse can apply, in either phase.
FLASH_CLASSES = ("vf-ok-bright", "vf-ok-dim", "vf-bad-bright", "vf-bad-dim")


class _Host(App):
    """Bare host app — same shape as test_unlock_ui's, plus the real
    stylesheet, which the CSS-cascade test needs. CSS_PATH is resolved from
    config.ROOT_DIR rather than written relative, because Textual resolves a
    relative CSS_PATH against the module that declares the class and this
    module lives one directory deeper than app.py."""

    CSS_PATH = config.ROOT_DIR / "ui" / "tui" / "app.tcss"

    def compose(self) -> ComposeResult:
        yield Static("root")


# ─── Reaction content ────────────────────────────────────────────────────────


def test_every_archetype_has_reactions_for_both_verdicts():
    """A missing entry degrades to a bland fallback rather than crashing, so
    nothing else in the suite would catch a content gap. This does."""
    for archetype in Archetype:
        assert archetype in reactions.REACTIONS, f"no reactions for {archetype.value}"
        for verdict in (Verdict.ADMIT, Verdict.DENY):
            variants = reactions.REACTIONS[archetype].get(verdict)
            assert variants, f"{archetype.value} has no {verdict.value} reaction"


def test_reaction_lines_are_plain_text():
    """ChatPanel types reactions out one character at a time, so any embedded
    markup would tear mid-reveal and render as literal brackets."""
    for by_verdict in reactions.REACTIONS.values():
        for variants in by_verdict.values():
            for reaction in variants:
                for line in reaction.lines:
                    assert line, "empty reaction line"
                    assert "[" not in line and "]" not in line, line


def test_reaction_choice_is_deterministic_per_candidate():
    """Same seed, same day, same reaction — the contract candidate_gen holds
    for everything else, so a replayed day plays back identically."""
    day = load_day(1)
    for slot in range(day.candidate_count):
        c1 = candidate_gen.generate(SEED, day, slot)
        c2 = candidate_gen.generate(SEED, day, slot)
        for verdict in (Verdict.ADMIT, Verdict.DENY):
            assert reactions.pick(c1, verdict) == reactions.pick(c2, verdict)


def test_alignment_archetypes_get_multiline_reactions():
    """Dark Web and White Hat are the two archetypes whose verdict moves the
    player's alignment; their reaction is where the moral arc speaks, and it
    is the only place multi-line is worth the extra seconds."""
    for archetype in (Archetype.DARK_WEB, Archetype.WHITE_HAT):
        for variants in reactions.REACTIONS[archetype].values():
            for reaction in variants:
                assert len(reaction.lines) > 1, f"{archetype.value} should be multi-line"

    everyday = set(Archetype) - {Archetype.DARK_WEB, Archetype.WHITE_HAT}
    for archetype in everyday:
        for variants in reactions.REACTIONS[archetype].values():
            for reaction in variants:
                assert len(reaction.lines) == 1, (
                    f"{archetype.value} should be one line so it fits the window")


def test_valence_maps_to_a_chat_colour():
    for by_verdict in reactions.REACTIONS.values():
        for variants in by_verdict.values():
            for reaction in variants:
                assert reaction.valence in ("positive", "negative")
                assert reaction.color.startswith("#")


# ─── Board grading ───────────────────────────────────────────────────────────


def _state_with(marked=(), absent=()) -> EvidenceState:
    st = EvidenceState()
    for kind in marked:
        st.cycle(kind)                     # unknown -> marked
    for kind in absent:
        st.cycle(kind)                     # unknown -> marked
        st.cycle(kind)                     # marked  -> absent
    return st


def test_grade_is_none_before_reveal():
    st = _state_with(marked=[DiscrepancyKind.BREACH_HIT])
    assert st.revealed is False
    assert st.grade_of(DiscrepancyKind.BREACH_HIT) is None


def test_untouched_items_stay_ungraded():
    """The core "ground truth stays hidden" guarantee: a violation the player
    never touched draws nothing, even when it is really there."""
    actual = {DiscrepancyKind.BREACH_HIT, DiscrepancyKind.IMPOSSIBLE_TRAVEL}
    st = _state_with(marked=[DiscrepancyKind.BREACH_HIT])
    st.reveal(actual, visible=set(DiscrepancyKind))

    assert st.grade_of(DiscrepancyKind.BREACH_HIT) == "correct"
    assert st.grade_of(DiscrepancyKind.IMPOSSIBLE_TRAVEL) is None   # present, untouched
    assert st.grade_of(DiscrepancyKind.LEAKED_PASSWORD) is None     # absent, untouched


def test_marks_and_rulings_grade_independently():
    actual = {DiscrepancyKind.BREACH_HIT}
    st = _state_with(
        marked=[DiscrepancyKind.BREACH_HIT,          # right — it is there
                DiscrepancyKind.LEAKED_PASSWORD],    # wrong — it is not
        absent=[DiscrepancyKind.WEAK_CREDENTIAL,     # right — correctly ruled out
                DiscrepancyKind.BRUTE_FORCE_IN_LOG], # right — also not there
    )
    st.reveal(actual, visible=set(DiscrepancyKind))

    assert st.grade_of(DiscrepancyKind.BREACH_HIT) == "correct"
    assert st.grade_of(DiscrepancyKind.LEAKED_PASSWORD) == "wrong"
    assert st.grade_of(DiscrepancyKind.WEAK_CREDENTIAL) == "correct"
    assert st.grade_of(DiscrepancyKind.BRUTE_FORCE_IN_LOG) == "correct"


def test_ruling_out_a_real_violation_is_wrong():
    actual = {DiscrepancyKind.BREACH_HIT}
    st = _state_with(absent=[DiscrepancyKind.BREACH_HIT])
    st.reveal(actual, visible=set(DiscrepancyKind))
    assert st.grade_of(DiscrepancyKind.BREACH_HIT) == "wrong"


def test_unrecorded_counts_only_untouched_violations():
    """A violation the player explicitly ruled out already wears a ✗ on
    screen — counting it again here would report the same mistake twice."""
    actual = {DiscrepancyKind.BREACH_HIT,
              DiscrepancyKind.IMPOSSIBLE_TRAVEL,
              DiscrepancyKind.LEAKED_PASSWORD}
    st = _state_with(
        marked=[DiscrepancyKind.BREACH_HIT],          # caught
        absent=[DiscrepancyKind.IMPOSSIBLE_TRAVEL],   # wrongly ruled out, but ON SCREEN
    )
    st.reveal(actual, visible=set(DiscrepancyKind))
    assert st.unrecorded_count == 1                   # only LEAKED_PASSWORD


def test_locked_tool_violations_are_never_counted_against_the_player():
    """#33's progressive unlock: the game must not mark someone down for
    missing evidence it refused to show them."""
    actual = {DiscrepancyKind.BREACH_HIT,              # ghostscan — unlocked
              DiscrepancyKind.STEGO_PAYLOAD_PRESENT}   # stegotool — still locked
    visible = {DiscrepancyKind.BREACH_HIT}
    st = _state_with()
    st.reveal(actual, visible=visible)
    assert st.unrecorded_count == 1                    # not 2


def test_grading_agrees_with_the_scoring_credit_rule():
    """A BREACH_HIT flag on a CROSS_BREACH_REUSE carrier is a correct read of
    Ghostscan's breach panel, and scoring pays for it. The board must not put a
    ✗ next to a flag the player was paid for."""
    actual = {DiscrepancyKind.CROSS_BREACH_REUSE}
    flags = {DiscrepancyKind.BREACH_HIT}

    credited = scoring.credited_flags(flags, actual)
    assert DiscrepancyKind.CROSS_BREACH_REUSE in credited   # scoring credits it

    st = _state_with(marked=flags)
    st.reveal(actual, visible=set(DiscrepancyKind))
    assert st.grade_of(DiscrepancyKind.BREACH_HIT) == "correct"


def test_clear_wipes_grading_with_the_flags():
    st = _state_with(marked=[DiscrepancyKind.BREACH_HIT])
    st.reveal({DiscrepancyKind.BREACH_HIT}, visible=set(DiscrepancyKind))
    assert st.revealed

    st.clear()
    assert st.revealed is False
    assert st.unrecorded_count == 0
    assert st.get_flags() == set()


# ─── The window, driven through a real screen ────────────────────────────────


def _flashing_widgets(screen) -> list:
    return [w for w in screen.query("*")
            if any(w.has_class(c) for c in FLASH_CLASSES)]


def _chat_texts(chat) -> list[str]:
    """Everything the chat panel has shown, is showing, or has queued.

    A verdict usually lands while the opening script is still typing, so the
    reaction is normally sitting in the queue rather than on screen — checking
    only the rendered lines would make this flaky."""
    out = list(chat._done_lines)
    if chat._cur_full:
        out.append(chat._cur_full)
    pending = ([chat._active] if chat._active else []) + list(chat._queue)
    for message in pending:
        out.extend(message.lines)
    return out


async def _open_intake(pilot, day, state):
    await pilot.app.push_screen(IntakeScreen(day, state, "briefing"))
    await pilot.pause(0.3)
    return pilot.app.screen


def test_verdict_opens_the_reveal_window():
    async def go():
        day = load_day(1)
        state = GameState(seed=SEED)
        state.unlocked_tools = set(ALL_TOOLS)
        async with _Host().run_test(size=(160, 50)) as pilot:
            scr = await _open_intake(pilot, day, state)
            candidate = scr._candidate
            verdict = candidate.truth.correct_verdict

            scr._commit_verdict(verdict)
            await pilot.pause(0.1)

            # 1. The candidate answered back.
            expected = reactions.pick(candidate, verdict).lines[0]
            assert expected in _chat_texts(scr.chat)

            # 2. The board is graded.
            assert scr.evidence_state.revealed is True

            # 3. Borders are pulsing, in the CORRECT colour family.
            flashing = _flashing_widgets(scr)
            assert flashing, "no panel picked up a flash class"
            assert all(w.has_class("vf-ok-bright") or w.has_class("vf-ok-dim")
                       for w in flashing)

            # 4. And the player is not held hostage by any of it.
            assert scr.btn_next.disabled is False

    asyncio.run(go())


def test_wrong_verdict_flashes_the_other_colour():
    async def go():
        day = load_day(1)
        state = GameState(seed=SEED)
        state.unlocked_tools = set(ALL_TOOLS)
        async with _Host().run_test(size=(160, 50)) as pilot:
            scr = await _open_intake(pilot, day, state)
            wrong = (Verdict.DENY
                     if scr._candidate.truth.correct_verdict == Verdict.ADMIT
                     else Verdict.ADMIT)

            scr._commit_verdict(wrong)
            await pilot.pause(0.1)

            flashing = _flashing_widgets(scr)
            assert flashing
            assert all(w.has_class("vf-bad-bright") or w.has_class("vf-bad-dim")
                       for w in flashing)

    asyncio.run(go())


def test_advancing_mid_pulse_leaves_nothing_behind():
    """The teardown test. NEXT is live from frame one, so this path runs
    constantly — a surviving timer would repaint the NEXT candidate's panels."""
    async def go():
        day = load_day(1)
        state = GameState(seed=SEED)
        state.unlocked_tools = set(ALL_TOOLS)
        async with _Host().run_test(size=(160, 50)) as pilot:
            scr = await _open_intake(pilot, day, state)
            scr._commit_verdict(scr._candidate.truth.correct_verdict)
            await pilot.pause(0.1)
            assert _flashing_widgets(scr)          # mid-pulse, well inside the window

            scr._advance_to_next_candidate()
            await pilot.pause(0.1)

            assert scr._reveal_timers == []
            assert _flashing_widgets(scr) == []
            assert scr.evidence_state.revealed is False

            # Give any leaked timer more than a full window to misfire.
            await pilot.pause(config.VERDICT_REVEAL_DURATION + 0.3)
            assert _flashing_widgets(scr) == []

    asyncio.run(go())


def test_pulse_stops_on_its_own_when_left_alone():
    async def go():
        day = load_day(1)
        state = GameState(seed=SEED)
        state.unlocked_tools = set(ALL_TOOLS)
        async with _Host().run_test(size=(160, 50)) as pilot:
            scr = await _open_intake(pilot, day, state)
            scr._commit_verdict(scr._candidate.truth.correct_verdict)
            await pilot.pause(config.VERDICT_REVEAL_DURATION + 0.4)

            assert _flashing_widgets(scr) == []
            # The grade is NOT transient — it outlives the pulse so the player
            # can actually read it.
            assert scr.evidence_state.revealed is True

    asyncio.run(go())


def test_flash_out_specifies_the_focus_border():
    """The flash rules sit last in app.tcss on purpose: they tie with
    `#id:focus` on specificity and win only on document order. Move them up
    and a focused panel silently stops flashing."""
    async def go():
        day = load_day(1)
        state = GameState(seed=SEED)
        state.unlocked_tools = set(ALL_TOOLS)
        async with _Host().run_test(size=(160, 50)) as pilot:
            scr = await _open_intake(pilot, day, state)
            chat = scr.query_one("#chat")
            chat.focus()
            await pilot.pause(0.1)
            focused_border = chat.styles.border_top

            chat.add_class("vf-bad-bright")
            await pilot.pause(0.1)
            flashed = chat.styles.border_top

            assert flashed != focused_border, (
                "flash class lost to the focus rule — check the block is still "
                "last in app.tcss")
            assert flashed[1].hex.lower().startswith("#ff5470")

            chat.remove_class("vf-bad-bright")
            await pilot.pause(0.1)
            assert chat.styles.border_top == focused_border

    asyncio.run(go())


def test_verdict_panel_border_is_reserved_so_the_flash_cannot_shift_layout():
    """#verdict-panel has no visible border by design; the pulse paints one.
    The base rule reserves those two cells in the background colour, so ADMIT
    and DENY don't jump sideways every time a verdict lands."""
    async def go():
        day = load_day(1)
        state = GameState(seed=SEED)
        state.unlocked_tools = set(ALL_TOOLS)
        async with _Host().run_test(size=(160, 50)) as pilot:
            scr = await _open_intake(pilot, day, state)
            panel = scr.query_one("#verdict-panel")
            before = panel.content_region.width

            panel.add_class("vf-bad-bright")
            await pilot.pause(0.1)
            assert panel.content_region.width == before

    asyncio.run(go())


def test_reveal_can_be_switched_off():
    """VERDICT_REVEAL_ENABLED = False must restore the pre-feature behaviour
    exactly: no reaction, no pulse, no grading — and the verdict itself
    completely unaffected, since the window is presentation only."""
    async def go():
        day = load_day(1)
        state = GameState(seed=SEED)
        state.unlocked_tools = set(ALL_TOOLS)
        original = config.VERDICT_REVEAL_ENABLED
        config.VERDICT_REVEAL_ENABLED = False
        try:
            async with _Host().run_test(size=(160, 50)) as pilot:
                scr = await _open_intake(pilot, day, state)
                candidate = scr._candidate
                before_hd = state.hackdollars

                scr._commit_verdict(candidate.truth.correct_verdict)
                await pilot.pause(0.2)

                assert _flashing_widgets(scr) == []
                assert scr.evidence_state.revealed is False
                reaction = reactions.pick(candidate, candidate.truth.correct_verdict)
                assert reaction.lines[0] not in _chat_texts(scr.chat)

                # The economy still ran.
                assert state.hackdollars > before_hd
                assert scr._verdict_locked is True
                assert scr.btn_next.disabled is False
        finally:
            config.VERDICT_REVEAL_ENABLED = original

    asyncio.run(go())
