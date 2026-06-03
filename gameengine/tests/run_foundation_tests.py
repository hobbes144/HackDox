"""Stdlib-only test runner for the foundation tests.

Run from the project root:
    python -m gameengine.tests.run_foundation_tests

Why not pytest? The runtime sandbox doesn't have pytest installed and
can't pip from the network. The same tests can be promoted to pytest-style
once a venv is set up; the asserts are unchanged.
"""

from __future__ import annotations

import sys
import traceback
from collections.abc import Callable

from gameengine import config
from gameengine.core import candidate_gen, rules_engine, scoring
from gameengine.core.content_loader import load_day
from gameengine.core.models import (
    Archetype,
    GameState,
    Verdict,
)


SEED = 0xC0FFEE


def test_candidate_gen_is_deterministic() -> None:
    day = load_day(1)
    a = candidate_gen.generate(SEED, day, slot_index=0)
    b = candidate_gen.generate(SEED, day, slot_index=0)
    assert a == b, "Same seed/day/slot must produce identical candidates"
    c = candidate_gen.generate(SEED, day, slot_index=1)
    assert a.id != c.id, "Different slots must produce different candidates"


def test_day1_archetype_mix_matches_spec() -> None:
    day = load_day(1)
    realized: dict[Archetype, int] = {}
    for i in range(day.candidate_count):
        c = candidate_gen.generate(SEED, day, i)
        realized[c.archetype] = realized.get(c.archetype, 0) + 1
    assert realized == day.archetype_mix, (
        f"Realized mix {realized} != declared mix {day.archetype_mix}"
    )


def test_obvious_admit_has_no_discrepancies() -> None:
    day = load_day(1)
    seen = 0
    for i in range(day.candidate_count):
        c = candidate_gen.generate(SEED, day, i)
        if c.archetype == Archetype.OBVIOUS_ADMIT:
            assert c.truth.discrepancies == (), (
                f"Obvious Admit must be clean; got {c.truth.discrepancies}"
            )
            assert c.truth.correct_verdict == Verdict.ADMIT
            seen += 1
    assert seen >= 1


def test_bad_actor_triggers_disqualifying_rules() -> None:
    day = load_day(1)
    for i in range(day.candidate_count):
        c = candidate_gen.generate(SEED, day, i)
        if c.archetype == Archetype.BAD_ACTOR:
            ev = rules_engine.evaluate(c, day)
            assert ev.triggered_disqualifying, (
                f"Bad Actor must trigger >=1 disqualifying rule. Discrepancies: "
                f"{[d.kind.value for d in c.truth.discrepancies]}"
            )
            return
    raise AssertionError("No Bad Actor in Day 1 mix?")


def test_sneaky_bugger_evades_dossier_rules() -> None:
    """Sneaky Bugger should NOT trigger dossier-only rules — they're
    tool-only by design. Day 1's rulebook still catches them via
    has_discrepancy:stego_payload_present."""
    day = load_day(1)
    for i in range(day.candidate_count):
        c = candidate_gen.generate(SEED, day, i)
        if c.archetype == Archetype.SNEAKY_BUGGER:
            assert c.truth.discrepancies, "Sneaky Bugger must have planted discrepancies"
            # All discrepancies must be tool-revealed, never DOSSIER.
            from gameengine.core.models import ToolName
            for d in c.truth.discrepancies:
                assert d.revealed_by != ToolName.DOSSIER, (
                    f"Sneaky Bugger's discrepancies must be tool-only; "
                    f"got dossier-level {d.kind.value}"
                )
            return
    raise AssertionError("No Sneaky Bugger in Day 1 mix?")


def test_scoring_correct_admit_rewards_currency() -> None:
    day = load_day(1)
    state = GameState(seed=SEED, compute_hours=100, lives=3, alignment=0)
    candidate = next(
        candidate_gen.generate(SEED, day, i)
        for i in range(day.candidate_count)
        if candidate_gen.generate(SEED, day, i).archetype == Archetype.OBVIOUS_ADMIT
    )
    scoring.apply(candidate, Verdict.ADMIT, state)
    # Correct verdict pays the base reward (board bonus may add more on top).
    assert state.compute_hours >= 100 + config.CORRECT_VERDICT_REWARD
    assert state.lives == 3


def test_scoring_false_admit_costs_life() -> None:
    day = load_day(1)
    state = GameState(seed=SEED, compute_hours=100, lives=3, alignment=0)
    bad_actor = next(
        candidate_gen.generate(SEED, day, i)
        for i in range(day.candidate_count)
        if candidate_gen.generate(SEED, day, i).archetype == Archetype.BAD_ACTOR
    )
    scoring.apply(bad_actor, Verdict.ADMIT, state)
    # Wrong verdicts cost a life, never compute hours.
    assert state.lives == 3 - config.FALSE_ADMIT_LIVES_PENALTY
    assert state.compute_hours == 100


def test_scoring_false_deny_no_penalty() -> None:
    day = load_day(1)
    state = GameState(seed=SEED, compute_hours=100, lives=3, alignment=0)
    admit_candidate = next(
        candidate_gen.generate(SEED, day, i)
        for i in range(day.candidate_count)
        if candidate_gen.generate(SEED, day, i).archetype == Archetype.OBVIOUS_ADMIT
    )
    scoring.apply(admit_candidate, Verdict.DENY, state)
    assert state.compute_hours == 100
    assert state.lives == 3


TESTS: list[Callable[[], None]] = [
    test_candidate_gen_is_deterministic,
    test_day1_archetype_mix_matches_spec,
    test_obvious_admit_has_no_discrepancies,
    test_bad_actor_triggers_disqualifying_rules,
    test_sneaky_bugger_evades_dossier_rules,
    test_scoring_correct_admit_rewards_currency,
    test_scoring_false_admit_costs_life,
    test_scoring_false_deny_no_penalty,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {e}")
        except Exception:
            failed += 1
            print(f"  ERROR  {fn.__name__}:")
            traceback.print_exc()
    print()
    print(f"  {len(TESTS) - failed}/{len(TESTS)} passed.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
