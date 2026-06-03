"""Foundation tests — prove the engine wiring is sound.

These don't aim for full coverage; they pin down the contracts the rest
of the engine depends on. Full archetype × verdict coverage lands with
the Textual UI in task #7.
"""

from __future__ import annotations

import pytest

from gameengine import config
from gameengine.core import candidate_gen, rules_engine, scoring
from gameengine.core.content_loader import load_day
from gameengine.core.models import (
    Archetype,
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


def test_scoring_correct_admit_rewards_currency():
    state = GameState(seed=SEED, currency=100, lives=3, alignment=0)
    # Manufacture an Obvious Admit candidate directly.
    day = load_day(1)
    candidate = next(
        candidate_gen.generate(SEED, day, i)
        for i in range(day.candidate_count)
        if candidate_gen.generate(SEED, day, i).archetype == Archetype.OBVIOUS_ADMIT
    )
    scoring.apply(candidate, Verdict.ADMIT, state)
    assert state.currency == 100 + config.ADMIT_REWARD_BASE
    assert state.lives == 3


def test_scoring_false_admit_costs_life():
    state = GameState(seed=SEED, currency=100, lives=3, alignment=0)
    day = load_day(1)
    bad_actor = next(
        candidate_gen.generate(SEED, day, i)
        for i in range(day.candidate_count)
        if candidate_gen.generate(SEED, day, i).archetype == Archetype.BAD_ACTOR
    )
    scoring.apply(bad_actor, Verdict.ADMIT, state)
    assert state.lives == 2
    assert state.currency == 100 - config.FALSE_ADMIT_PENALTY


def test_scoring_false_deny_no_penalty():
    """Mistakenly denying a valid candidate is only lost reward — no strike."""
    state = GameState(seed=SEED, currency=100, lives=3, alignment=0)
    day = load_day(1)
    admit_candidate = next(
        candidate_gen.generate(SEED, day, i)
        for i in range(day.candidate_count)
        if candidate_gen.generate(SEED, day, i).archetype == Archetype.OBVIOUS_ADMIT
    )
    scoring.apply(admit_candidate, Verdict.DENY, state)
    assert state.currency == 100  # no currency change
    assert state.lives == 3        # no strike
