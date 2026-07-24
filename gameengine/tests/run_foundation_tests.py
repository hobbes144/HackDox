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


def _find(day, archetype):
    return next(
        candidate_gen.generate(SEED, day, i)
        for i in range(day.candidate_count)
        if candidate_gen.generate(SEED, day, i).archetype == archetype
    )


def test_scoring_correct_admit_rewards_hackdollars_not_compute() -> None:
    """Issue #27: verdicts NEVER grant ⏱ — payouts are HD$ only. The
    evidence-board bonus is HD$ too (clean candidate + empty board = full)."""
    day = load_day(1)
    state = GameState(seed=SEED, compute_hours=100, alignment=0)
    candidate = _find(day, Archetype.OBVIOUS_ADMIT)
    result = scoring.apply(candidate, Verdict.ADMIT, state)
    # ⏱ untouched by the verdict (issue #27).
    assert state.compute_hours == 100
    # Correct admit of a beneficial actor RECORDS a positive health delta
    # (issue #20 rework: health itself only moves at end of day)…
    assert result.site_health_delta > 0
    assert state.site_health == config.SITE_HEALTH_START
    # …and pays HackDollar$ (issue #21) + the full board bonus in HD$
    # (clean candidate, nothing flagged — issue #27 moved the bonus to HD$).
    assert result.board_bonus == config.BOARD_ACCURACY_MAX_BONUS
    assert state.hackdollars == (config.HACKDOLLAR_PER_CORRECT_ADMIT
                                 + config.BOARD_ACCURACY_MAX_BONUS)


def test_daily_compute_budget_formula() -> None:
    """Issue #27: fixed daily ⏱ pool, growing with the day number, floored."""
    base = config.STARTING_COMPUTE
    assert config.daily_compute_budget(1, base) == base
    assert (config.daily_compute_budget(3, base)
            == base + 2 * config.DAILY_BUDGET_GROWTH)
    assert config.daily_compute_budget(1, 0) == config.DAILY_BUDGET_MIN


def test_every_candidate_has_password_field() -> None:
    """Issue #29: every dossier carries an encrypted password; strong-tier
    (bcrypt) is never crackable, other tiers store their plaintext."""
    from gameengine.core import tools_bridge
    from gameengine.core.models import DiscrepancyKind

    day = load_day(1)
    for i in range(day.candidate_count):
        c = candidate_gen.generate(SEED, day, i)
        d = c.dossier
        assert d.submitted_hash, f"{c.archetype.value} missing password hash"
        strength = tools_bridge.password_strength(d.submitted_hash)
        assert strength in ("weak", "medium", "strong")
        if strength == "strong":
            # Strongest tier: always safe — never cracks, no plaintext stored.
            assert tools_bridge.crack_password(c) is None
            assert not any(d2.kind in (
                DiscrepancyKind.WEAK_CREDENTIAL, DiscrepancyKind.LEAKED_PASSWORD,
                DiscrepancyKind.CROSS_BREACH_REUSE, DiscrepancyKind.UNSALTED_STORAGE,
            ) for d2 in c.truth.discrepancies)
        else:
            assert d.password_plain, "crackable tiers must carry a plaintext"
            assert tools_bridge.crack_password(c) == d.password_plain
        # WEAK_CREDENTIAL (#29 rework) = weak encryption + weak plaintext, minor.
        if any(d2.kind == DiscrepancyKind.WEAK_CREDENTIAL
               for d2 in c.truth.discrepancies):
            assert strength == "weak"
            sev = next(d2.severity for d2 in c.truth.discrepancies
                       if d2.kind == DiscrepancyKind.WEAK_CREDENTIAL)
            assert sev == "minor"


def test_scoring_false_admit_damages_site_health() -> None:
    """Issue #20/#24: false admits hit Site Health, not lives (removed).
    Rework: the delta is only RECORDED mid-day; it lands at end of day."""
    day = load_day(1)
    state = GameState(seed=SEED, compute_hours=100, alignment=0)
    bad_actor = _find(day, Archetype.BAD_ACTOR)
    result = scoring.apply(bad_actor, Verdict.ADMIT, state)
    weight = config.ARCHETYPE_HEALTH_WEIGHTS[Archetype.BAD_ACTOR.value]
    assert weight < 0
    assert result.site_health_delta == weight
    # Mid-day: health untouched — no loss condition can trip during a shift.
    assert state.site_health == config.SITE_HEALTH_START
    assert not scoring.health_below_loss(state)
    # Wrong verdicts never cost compute hours or pay HD$.
    assert state.compute_hours == 100
    assert state.hackdollars == 0


def test_site_health_applies_in_one_batch_at_end_of_day() -> None:
    """Issue #20 rework: apply_end_of_day_health() lands the whole day's
    deltas at once; only then can the loss threshold be evaluated."""
    day = load_day(1)
    state = GameState(seed=SEED, compute_hours=100, alignment=0)
    scoring.apply(_find(day, Archetype.BAD_ACTOR),    Verdict.ADMIT, state)
    scoring.apply(_find(day, Archetype.OBVIOUS_ADMIT), Verdict.ADMIT, state)
    expected = (config.ARCHETYPE_HEALTH_WEIGHTS[Archetype.BAD_ACTOR.value]
                + config.ARCHETYPE_HEALTH_WEIGHTS[Archetype.OBVIOUS_ADMIT.value])
    assert state.site_health == config.SITE_HEALTH_START   # still untouched
    day_delta = scoring.apply_end_of_day_health(state)
    assert day_delta == expected
    assert state.site_health == min(100.0, config.SITE_HEALTH_START + expected)


def test_scoring_correct_deny_never_damages_health() -> None:
    """Issue #20: a denied threat never entered the site — health untouched."""
    day = load_day(1)
    state = GameState(seed=SEED, compute_hours=100, alignment=0)
    bad_actor = _find(day, Archetype.BAD_ACTOR)
    result = scoring.apply(bad_actor, Verdict.DENY, state)
    assert result.correct
    assert result.site_health_delta == 0
    assert state.site_health == config.SITE_HEALTH_START
    assert state.hackdollars == config.HACKDOLLAR_PER_CORRECT_DENY


def test_scoring_false_deny_no_penalty() -> None:
    day = load_day(1)
    state = GameState(seed=SEED, compute_hours=100, alignment=0)
    admit_candidate = _find(day, Archetype.OBVIOUS_ADMIT)
    scoring.apply(admit_candidate, Verdict.DENY, state)
    assert state.compute_hours == 100
    assert state.site_health == config.SITE_HEALTH_START


def test_site_health_loss_threshold() -> None:
    """Issue #20: dipping below the loss threshold trips game-over."""
    state = GameState(seed=SEED)
    state.site_health = config.SITE_HEALTH_LOSS_THRESHOLD + 1
    assert not scoring.health_below_loss(state)
    state.site_health = config.SITE_HEALTH_LOSS_THRESHOLD - 1
    assert scoring.health_below_loss(state)


def test_eod_health_bonus_scales() -> None:
    """Issue #21: HD$ bonus above the reward threshold, scaled by health."""
    state = GameState(seed=SEED)
    state.site_health = config.SITE_HEALTH_REWARD_THRESHOLD - 1
    assert scoring.eod_health_bonus(state) == 0
    state.site_health = 100.0
    assert scoring.eod_health_bonus(state) == config.HACKDOLLAR_SITE_HEALTH_BONUS
    state.site_health = config.SITE_HEALTH_REWARD_THRESHOLD
    assert 0 < scoring.eod_health_bonus(state) <= config.HACKDOLLAR_SITE_HEALTH_BONUS


def test_persistence_round_trip_new_economy() -> None:
    """Issues #20/#21/#25: site_health / hackdollars / credits / capacity
    survive save→load; no `lives` field is written (issue #24)."""
    import json
    from gameengine.core import persistence

    prior = (config.SAVE_FILE.read_text(encoding="utf-8")
             if config.SAVE_FILE.exists() else None)
    try:
        state = GameState(seed=SEED)
        state.site_health      = 62.5
        state.hackdollars      = 123
        state.hackdox_credits  = 2
        state.compute_capacity = 70
        state.upgrades         = {config.UPGRADE_LOG_HIGHLIGHT}
        persistence.save(state)
        raw = json.loads(config.SAVE_FILE.read_text(encoding="utf-8"))
        assert "lives" not in raw, "lives must not be persisted (issue #24)"
        loaded = persistence.load()
        assert loaded is not None
        assert loaded.site_health      == 62.5
        assert loaded.hackdollars      == 123
        assert loaded.hackdox_credits  == 2
        assert loaded.compute_capacity == 70
        assert config.UPGRADE_LOG_HIGHLIGHT in loaded.upgrades
    finally:
        if prior is not None:
            config.SAVE_FILE.write_text(prior, encoding="utf-8")


def test_toolcost_upgrade_reduces_charge() -> None:
    """Issue #23: the toolcost upgrade lowers the ⏱ cost; no-op unowned."""
    from gameengine.core import tools_bridge

    state = GameState(seed=SEED, compute_hours=100)
    assert tools_bridge.tool_cost(state, "ghostscan") == config.TOOL_COSTS["ghostscan"]
    state.upgrades.add(config.UPGRADE_TOOLCOST_GHOSTSCAN)
    assert tools_bridge.tool_cost(state, "ghostscan") == max(
        1, config.TOOL_COSTS["ghostscan"] - config.TOOLCOST_REDUCTION)


TESTS: list[Callable[[], None]] = [
    test_candidate_gen_is_deterministic,
    test_day1_archetype_mix_matches_spec,
    test_obvious_admit_has_no_discrepancies,
    test_bad_actor_triggers_disqualifying_rules,
    test_sneaky_bugger_evades_dossier_rules,
    test_scoring_correct_admit_rewards_hackdollars_not_compute,
    test_daily_compute_budget_formula,
    test_every_candidate_has_password_field,
    test_scoring_false_admit_damages_site_health,
    test_site_health_applies_in_one_batch_at_end_of_day,
    test_scoring_correct_deny_never_damages_health,
    test_scoring_false_deny_no_penalty,
    test_site_health_loss_threshold,
    test_eod_health_bonus_scales,
    test_persistence_round_trip_new_economy,
    test_toolcost_upgrade_reduces_charge,
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
