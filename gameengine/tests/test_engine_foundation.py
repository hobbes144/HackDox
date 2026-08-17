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


# ─── Per-day candidate spec (#32) ────────────────────────────────────────────


def test_day_spec_fields_default_on_pre32_files():
    """A day file without the #32 keys loads with harmless defaults."""
    day = load_day(1)
    assert day.allowed_violations == ()
    assert day.difficulty_band == "easy"
    assert day.forced_includes == {}


def test_forced_includes_pins_archetype_to_slot():
    """forced_includes puts the chosen archetype in the chosen slot, and it's
    deterministic (#32 AC)."""
    import dataclasses
    day = dataclasses.replace(load_day(1), number=5,
                              forced_includes={0: Archetype.SNEAKY_BUGGER})
    assert candidate_gen.generate(SEED, day, 0).archetype == Archetype.SNEAKY_BUGGER
    # same spec + seed → same pick
    assert candidate_gen.generate(SEED, day, 0).archetype == Archetype.SNEAKY_BUGGER


def test_forced_include_preserves_declared_mix():
    """Pinning a slot must not distort the day's overall archetype counts —
    the forced pick is subtracted from the bag, not added on top."""
    import dataclasses
    from collections import Counter
    day = dataclasses.replace(load_day(1), number=5,
                              forced_includes={0: Archetype.SNEAKY_BUGGER})
    got = [candidate_gen.generate(SEED, day, i).archetype
           for i in range(day.candidate_count)]
    assert got[0] == Archetype.SNEAKY_BUGGER
    assert dict(Counter(got)) == {
        Archetype.OBVIOUS_ADMIT: 2, Archetype.DAY_TO_DAY: 1,
        Archetype.CLUMSY_CUTIE: 1, Archetype.BAD_ACTOR: 1,
        Archetype.SNEAKY_BUGGER: 1,
    }


def test_allowed_violations_whitelist_restricts_planted_kinds():
    """When a day sets allowed_violations, no candidate may carry a kind
    outside it (it intersects with the #31 gate)."""
    import dataclasses
    day = dataclasses.replace(
        load_day(1), number=5,
        allowed_violations=(DiscrepancyKind.AFFILIATION_UNVERIFIED,),
    )
    for i in range(day.candidate_count):
        c = candidate_gen.generate(SEED, day, i)
        for d in c.truth.discrepancies:
            assert d.kind == DiscrepancyKind.AFFILIATION_UNVERIFIED, (
                f"slot {i} planted {d.kind} outside the day whitelist"
            )


# ─── Issue #35 — Rule.mutability + per-day ruleset loading ──────────────────


def test_day1_rules_all_default_to_fixed(day1):
    """Adding `mutability` must not have changed any existing content.

    Day 1's rule file predates #35 and never mentions mutability, so every
    rule must load as "fixed" — the guard that this field is additive.
    """
    assert day1.rules, "Day 1 should have rules"
    assert all(r.mutability == "fixed" for r in day1.rules)


def test_rule_mutability_survives_a_day_json_round_trip(tmp_path, monkeypatch):
    """#35 AC: a rule's mutability round-trips through day_N.json."""
    import json

    source = json.loads((config.DAYS_DIR / "day_01.json").read_text(encoding="utf-8"))
    source["number"] = 99
    # One rule of each non-default state, plus the untouched (fixed) remainder.
    source["rules"][0]["mutability"] = "overseer_variable"
    source["rules"][1]["mutability"] = "dark_web"

    monkeypatch.setattr(config, "DAYS_DIR", tmp_path)
    (tmp_path / "day_99.json").write_text(json.dumps(source), encoding="utf-8")

    loaded = load_day(99)
    assert loaded.rules[0].mutability == "overseer_variable"
    assert loaded.rules[1].mutability == "dark_web"
    assert loaded.rules[2].mutability == "fixed"


def test_unknown_mutability_raises(tmp_path, monkeypatch):
    """A typo must fail loudly, not silently degrade to "fixed"."""
    import json

    source = json.loads((config.DAYS_DIR / "day_01.json").read_text(encoding="utf-8"))
    source["number"] = 98
    source["rules"][0]["mutability"] = "overseer-variable"   # hyphen, not underscore

    monkeypatch.setattr(config, "DAYS_DIR", tmp_path)
    (tmp_path / "day_98.json").write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(ValueError, match="mutability"):
        load_day(98)


def test_rules_engine_evaluates_against_the_passed_day(day1):
    """#35 AC: the active ruleset is whatever Day is handed in — not a cached
    Day-1 ruleset.

    This pins behaviour that is already correct (`rules_engine.evaluate` is a
    pure function of its arguments and `HackDoxApp.advance_day` reloads the
    Day each shift). The test exists so a future refactor cannot reintroduce a
    module-level or cached ruleset without turning something red: the SAME
    candidate is evaluated against two different rulesets and must produce
    different results.
    """
    from dataclasses import replace

    # Find a candidate that trips at least one disqualifying rule under Day 1.
    dirty = next(
        c for c in (
            candidate_gen.generate(SEED, day1, slot_index=i)
            for i in range(day1.candidate_count)
        )
        if rules_engine.evaluate(c, day1).triggered_disqualifying
    )
    assert rules_engine.evaluate(dirty, day1).triggered_disqualifying

    # A "tomorrow" whose ruleset is empty must clear that same candidate.
    tomorrow = replace(day1, number=day1.number + 1, rules=())
    assert not rules_engine.evaluate(dirty, tomorrow).triggered_disqualifying
    assert not rules_engine.evaluate(dirty, tomorrow).triggered_weighted


# ─── Issue #17 — candidate volume scaling ───────────────────────────────────


def test_candidate_count_curve_shape():
    """Tutorial flat, then a ramp, then a hard cap."""
    tutorial = [config.DAY_CANDIDATE_COUNT(d)
                for d in range(1, config.TUTORIAL_LAST_DAY + 1)]
    assert tutorial == [config.CANDIDATE_COUNT_TUTORIAL] * len(tutorial)

    ramp = [config.DAY_CANDIDATE_COUNT(d) for d in range(1, 21)]
    # Monotonic non-decreasing, and never above the cap.
    assert all(b >= a for a, b in zip(ramp, ramp[1:]))
    assert max(ramp) == config.CANDIDATE_COUNT_CAP
    # The ramp actually ramps — a late day is strictly longer than a tutorial one.
    assert config.DAY_CANDIDATE_COUNT(20) > config.DAY_CANDIDATE_COUNT(1)


def test_day1_volume_and_quota_are_unchanged(day1):
    """The tutorial baseline must not move when the curve lands.

    day_01.json declares candidate_count 6 and min_correct_admits 2. The
    explicit value wins over the curve, and QUOTA_ADMIT_RATIO is chosen so the
    scaled quota computes to the same 2.
    """
    assert day1.candidate_count == 6
    assert day1.quotas.min_correct_admits == 2
    assert day1.quotas.max_false_admits == 1


def test_candidate_count_falls_back_to_the_curve_when_omitted(tmp_path, monkeypatch):
    import json

    source = json.loads((config.DAYS_DIR / "day_01.json").read_text(encoding="utf-8"))
    source["number"] = 9
    source.pop("candidate_count")            # #17: now optional
    monkeypatch.setattr(config, "DAYS_DIR", tmp_path)
    (tmp_path / "day_09.json").write_text(json.dumps(source), encoding="utf-8")

    assert load_day(9).candidate_count == config.DAY_CANDIDATE_COUNT(9)


def test_quota_scales_with_volume_but_never_below_the_authored_value():
    # A longer shift asks for more correct admits...
    assert (config.DAY_MIN_CORRECT_ADMITS(16, 12)
            > config.DAY_MIN_CORRECT_ADMITS(1, 6))
    # ...but an author who wants a harder quota than the curve keeps it.
    assert config.DAY_MIN_CORRECT_ADMITS(1, 6, authored=5) == 5
    # max_false_admits deliberately does not scale — see config.
    assert config.DAY_MIN_CORRECT_ADMITS(1, 6) == 2


def test_missing_day_file_synthesizes_inside_the_campaign():
    """#17: the campaign no longer ends after Day 1 just because day_02.json
    was never authored."""
    for n in (2, 8, config.CAMPAIGN_LAST_DAY):
        day = load_day(n)
        assert day.number == n
        assert day.candidate_count == config.DAY_CANDIDATE_COUNT(n)
        assert day.difficulty_band == config.difficulty_band_for_day(n)
        # The mix must sum to the shift length, or slots go unfilled.
        assert sum(day.archetype_mix.values()) == day.candidate_count
        assert day.rules, "a synthesized day still needs a ruleset"


def test_campaign_ends_past_the_last_day():
    with pytest.raises(FileNotFoundError):
        load_day(config.CAMPAIGN_LAST_DAY + 1)


def test_synthesized_day_generation_is_deterministic():
    """#17 AC: same seed + day → same candidate set AND order."""
    day = load_day(16)
    first  = [candidate_gen.generate(SEED, day, i) for i in range(day.candidate_count)]
    second = [candidate_gen.generate(SEED, day, i) for i in range(day.candidate_count)]
    assert first == second
    assert len({c.id for c in first}) == day.candidate_count
    # The realized mix must equal the declared mix, as it does for Day 1.
    realized: dict = {}
    for c in first:
        realized[c.archetype] = realized.get(c.archetype, 0) + 1
    assert realized == day.archetype_mix


def test_scale_archetype_mix_preserves_total_and_never_drops_an_archetype():
    from gameengine.core.content_loader import scale_archetype_mix

    base = load_day(1).archetype_mix
    for target in range(1, 25):
        scaled = scale_archetype_mix(base, target)
        # Exactness is the hard requirement: _pick_archetype_for_slot walks the
        # bag modulo its length, so a mix that doesn't sum to the shift length
        # wraps and the realized mix stops matching the declared mix.
        assert sum(scaled.values()) == target, target
        assert all(v >= 1 for v in scaled.values()), target
        if target >= len(base):
            # With room for everyone, scaling must not delete an archetype the
            # day was meant to contain.
            assert set(scaled) == set(base), target
        else:
            # A shift shorter than the archetype list has to drop some — it
            # must drop them, not break the total.
            assert set(scaled) < set(base), target
