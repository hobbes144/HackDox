"""Foundation tests — prove the engine wiring is sound.

These don't aim for full coverage; they pin down the contracts the rest
of the engine depends on. Full archetype × verdict coverage lands with
the Textual UI in task #7.
"""

from __future__ import annotations

import pytest

from gameengine import config
from gameengine.core import candidate_gen, persistence, rules_engine, scoring
from gameengine.core.candidate_gen import intro_day
from gameengine.core.content_loader import load_day
from gameengine.core.models import (
    Archetype,
    DiscrepancyKind,
    GameState,
    Verdict,
)


SEED = 0xC0FFEE


@pytest.fixture
def day1():
    return load_day(1)


def test_candidate_gen_is_deterministic(day1):
    a = candidate_gen.generate(SEED, day1, slot_index=0)
    b = candidate_gen.generate(SEED, day1, slot_index=0)
    assert a == b
    # Different slots produce different candidates.
    c = candidate_gen.generate(SEED, day1, slot_index=1)
    assert a.id != c.id


def test_day1_produces_expected_archetype_count(day1):
    archetypes = [
        candidate_gen.generate(SEED, day1, slot_index=i).archetype
        for i in range(day1.candidate_count)
    ]
    counts = {a: archetypes.count(a) for a in set(archetypes)}
    # Day 1 mix: 2 obvious admit, 1 day-to-day, 1 clumsy, 1 bad actor, 1 sneaky.
    assert counts[Archetype.OBVIOUS_ADMIT] == 2
    assert counts[Archetype.DAY_TO_DAY] == 1
    assert counts[Archetype.CLUMSY_CUTIE] == 1
    assert counts[Archetype.BAD_ACTOR] == 1
    assert counts[Archetype.SNEAKY_BUGGER] == 1


def test_obvious_admit_has_no_discrepancies(day1):
    for i in range(day1.candidate_count):
        c = candidate_gen.generate(SEED, day1, i)
        if c.archetype == Archetype.OBVIOUS_ADMIT:
            assert c.truth.discrepancies == ()
            assert c.truth.correct_verdict == Verdict.ADMIT


def test_bad_actor_triggers_disqualifying_rules(day1):
    found = False
    for i in range(day1.candidate_count):
        c = candidate_gen.generate(SEED, day1, i)
        if c.archetype == Archetype.BAD_ACTOR:
            ev = rules_engine.evaluate(c, day1)
            assert ev.triggered_disqualifying, (
                f"Bad Actor must trigger >=1 disqualifying rule on Day 1; got none. "
                f"Discrepancies: {[d.kind for d in c.truth.discrepancies]}"
            )
            found = True
    assert found, "No Bad Actor present in Day 1 mix?"


def _find(day, archetype):
    return next(
        candidate_gen.generate(SEED, day, i)
        for i in range(day.candidate_count)
        if candidate_gen.generate(SEED, day, i).archetype == archetype
    )


def test_scoring_correct_admit_rewards_health_and_hackdollars(day1):
    """Issue #27: verdicts never grant compute — payouts (incl. the
    evidence-board bonus) land in HackDollar$."""
    state = GameState(seed=SEED, compute_hours=100, alignment=0)
    candidate = _find(day1, Archetype.OBVIOUS_ADMIT)
    result = scoring.apply(candidate, Verdict.ADMIT, state)
    assert state.compute_hours == 100   # ⏱ is a spend-only daily budget
    # Beneficial admit raises Site Health (issue #20) and pays HD$ (issue #21);
    # clean candidate + empty board = full board bonus in HD$ (issue #27).
    assert result.site_health_delta > 0
    assert result.board_bonus == config.BOARD_ACCURACY_MAX_BONUS
    assert state.hackdollars == (config.HACKDOLLAR_PER_CORRECT_ADMIT
                                 + config.BOARD_ACCURACY_MAX_BONUS)


def test_scoring_false_admit_damages_site_health(day1):
    """Issues #20/#24: false admits hit Site Health — lives are gone."""
    state = GameState(seed=SEED, compute_hours=100, alignment=0)
    bad_actor = _find(day1, Archetype.BAD_ACTOR)
    result = scoring.apply(bad_actor, Verdict.ADMIT, state)
    weight = config.ARCHETYPE_HEALTH_WEIGHTS[Archetype.BAD_ACTOR.value]
    assert weight < 0
    assert result.site_health_delta == weight
    # #20 rework: health only moves at end of day.
    assert state.site_health == config.SITE_HEALTH_START
    day_delta = scoring.apply_end_of_day_health(state)
    assert day_delta == weight
    assert state.site_health == config.SITE_HEALTH_START + weight
    assert state.compute_hours == 100   # wrong verdicts never cost ⏱
    assert state.hackdollars == 0


def test_scoring_correct_deny_never_damages_health(day1):
    """Issue #20: a denied threat never entered the site."""
    state = GameState(seed=SEED, compute_hours=100, alignment=0)
    bad_actor = _find(day1, Archetype.BAD_ACTOR)
    result = scoring.apply(bad_actor, Verdict.DENY, state)
    assert result.correct
    assert result.site_health_delta == 0
    assert state.site_health == config.SITE_HEALTH_START
    assert state.hackdollars == config.HACKDOLLAR_PER_CORRECT_DENY


def test_scoring_false_deny_no_penalty(day1):
    """Mistakenly denying a valid candidate is only lost reward."""
    state = GameState(seed=SEED, compute_hours=100, alignment=0)
    admit_candidate = _find(day1, Archetype.OBVIOUS_ADMIT)
    scoring.apply(admit_candidate, Verdict.DENY, state)
    assert state.compute_hours == 100
    assert state.site_health == config.SITE_HEALTH_START


def test_site_health_loss_threshold():
    """Issue #20: game over fires below the loss threshold, not on lives."""
    state = GameState(seed=SEED)
    state.site_health = config.SITE_HEALTH_LOSS_THRESHOLD + 1
    assert not scoring.health_below_loss(state)
    state.site_health = config.SITE_HEALTH_LOSS_THRESHOLD - 1
    assert scoring.health_below_loss(state)


# ─── Progressive unlock (#31) ────────────────────────────────────────────────


def test_unlocked_tools_round_trips(tmp_path, monkeypatch):
    """GameState.unlocked_tools survives a save/load cycle (#31 AC)."""
    save_file = tmp_path / "slot.json"
    monkeypatch.setattr(config, "SAVE_FILE", save_file)
    state = GameState(seed=SEED, current_day=3)
    state.unlocked_tools = {"ghostscan", "hashcrack"}
    persistence.save(state)
    loaded = persistence.load()
    assert loaded is not None
    assert loaded.unlocked_tools == {"ghostscan", "hashcrack"}


def test_legacy_save_backfills_unlocked_tools(tmp_path, monkeypatch):
    """A pre-#31 save (no unlocked_tools key) backfills from the schedule for
    its day, so a mid-campaign player isn't loaded in fully locked."""
    import json
    save_file = tmp_path / "slot.json"
    save_file.write_text(json.dumps({"seed": SEED, "current_day": 3}),
                         encoding="utf-8")
    monkeypatch.setattr(config, "SAVE_FILE", save_file)
    loaded = persistence.load()
    assert loaded is not None
    # Day 3 → Ghostscan (day 2) + Hashcrack (day 3) earned; Logwatch/Stego not.
    assert loaded.unlocked_tools == {"ghostscan", "hashcrack"}


def test_day1_never_rolls_a_later_day_kind(day1):
    """The evidence-tier gate (#31 AC): a Day-1 candidate can never carry a
    discrepancy whose revealing tool is taught after Day 1."""
    for i in range(day1.candidate_count):
        c = candidate_gen.generate(SEED, day1, i)
        for d in c.truth.discrepancies:
            assert intro_day(d.kind) <= 1, (
                f"{c.archetype} slot {i} planted {d.kind} "
                f"(intro_day={intro_day(d.kind)}) on Day 1"
            )


def test_gate_keeps_dossier_evidence_for_bad_actor_day1(day1):
    """Regression: the gate must not strip a Bad Actor's *dossier-level*
    evidence on Day 1 — hostile_chat is a Day-1 kind and must still land, or
    Day 1 has no deniable threat."""
    bad_actors = [
        candidate_gen.generate(SEED, day1, i)
        for i in range(day1.candidate_count)
        if candidate_gen.generate(SEED, day1, i).archetype == Archetype.BAD_ACTOR
    ]
    assert bad_actors, "No Bad Actor in Day 1 mix?"
    kinds = {d.kind for c in bad_actors for d in c.truth.discrepancies}
    assert DiscrepancyKind.HOSTILE_CHAT in kinds


def test_intro_day_matches_tool_schedule():
    """intro_day derives from the revealing tool's unlock day (the answer to
    the gate's design question), keeping gate and UI schedule in lockstep."""
    assert intro_day(DiscrepancyKind.AFFILIATION_UNVERIFIED) == 1   # dossier
    assert intro_day(DiscrepancyKind.BREACH_HIT) == 2               # ghostscan
    assert intro_day(DiscrepancyKind.LEAKED_PASSWORD) == 3          # hashcrack
    assert intro_day(DiscrepancyKind.BRUTE_FORCE_IN_LOG) == 4       # logwatch
    assert intro_day(DiscrepancyKind.STEGO_PAYLOAD_PRESENT) == 5    # stegotool
