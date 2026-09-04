"""Foundation tests — prove the engine wiring is sound.

These don't aim for full coverage; they pin down the contracts the rest
of the engine depends on. Full archetype × verdict coverage lands with
the Textual UI in task #7.
"""

from __future__ import annotations

import itertools

import pytest

from gameengine import config
from gameengine.core import candidate_gen, persistence, rules_engine, scoring
from gameengine.core.candidate_gen import intro_day
from gameengine.core.content_loader import load_day
from gameengine.core.models import (
    Archetype,
    DiscrepancyKind,
    Dossier,
    GameState,
    Verdict,
)

SEED = 0xC0FFEE


@pytest.fixture
def day1():
    return load_day(1)


def unconstrained_day():
    """Day 1's shape with its AUTHORED scripting stripped off.

    Most tests below use `load_day(1)` as a stand-in for "a generic day" and
    then `dataclasses.replace` a day number and archetype onto it. That worked
    only while day_01.json happened to script nothing. Batch 4 gave it a real
    tutorial script — allowed_violations, forced_includes, forced_violations —
    and seventeen tests promptly broke, every one of them by *silently getting
    what the content author asked for* rather than what the test meant.

    The coupling is the same one that makes synthesize_day inherit from day 1,
    and it is worth naming: authored content SHOULD constrain generation. A
    test that wants the engine's unconstrained behaviour has to say so, rather
    than depend on the tutorial day staying empty forever.
    """
    from dataclasses import replace
    return replace(
        load_day(1),
        allowed_violations=(),
        forced_includes={},
        forced_violations={},
        rule_sheet=None,
    )


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
    # Day 1 mix (#15): 2 obvious admit, 1 incompatible, 1 day-to-day,
    # 1 clumsy, 1 bad actor.
    #
    # The SNEAKY_BUGGER slot was removed here, and its absence is the point.
    # Every kind that archetype is eligible for is tool-revealed, and no tool
    # is unlocked on day 1 — so the evidence-tier gate emptied its pool and it
    # generated with ZERO discrepancies while still scoring as a DENY. A
    # player's first shift contained a candidate who was wrong to admit with
    # nothing anywhere on screen to say so.
    assert counts[Archetype.OBVIOUS_ADMIT] == 2
    assert counts[Archetype.THE_INCOMPATIBLE] == 1
    assert counts[Archetype.DAY_TO_DAY] == 1
    assert counts[Archetype.CLUMSY_CUTIE] == 1
    assert counts[Archetype.BAD_ACTOR] == 1
    assert Archetype.SNEAKY_BUGGER not in counts


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
    assert intro_day(DiscrepancyKind.AFFILIATION_NOT_STATED) == 1   # dossier
    assert intro_day(DiscrepancyKind.BREACH_HIT) == 2               # ghostscan
    assert intro_day(DiscrepancyKind.LEAKED_PASSWORD) == 3          # hashcrack
    assert intro_day(DiscrepancyKind.BRUTE_FORCE_IN_LOG) == 4       # logwatch
    assert intro_day(DiscrepancyKind.STEGO_PAYLOAD_PRESENT) == 5    # stegotool


# ─── Per-day candidate spec (#32) ────────────────────────────────────────────


def test_day_spec_fields_default_on_pre32_files(tmp_path, monkeypatch):
    """A day file without the #32/#15/#49 keys loads with harmless defaults.

    Used to assert this against day_01.json, which worked only for as long as
    day 1 declared none of them. It does now (#15's tutorial script), and that
    is correct content — so the backward-compatibility claim needs a genuinely
    minimal file to make it against, rather than borrowing whichever real day
    happened to be empty this week.
    """
    import json
    minimal = {
        "number": 1,
        "title": "Minimal",
        "candidate_count": 6,
        "archetype_mix": {"obvious_admit": 3, "bad_actor": 3},
        "rules": [{"id": "r", "text": "t",
                   "predicate": "has_discrepancy:hostile_chat"}],
        "quotas": {"min_correct_admits": 2, "max_false_admits": 1},
        "overseer_intro_key": "x",
        "overseer_outro_keys": {"excellent": "a", "passing": "b",
                                "poor": "c", "failed": "d"},
    }
    (tmp_path / "day_01.json").write_text(json.dumps(minimal), encoding="utf-8")
    monkeypatch.setattr(config, "DAYS_DIR", tmp_path)

    day = load_day(1)
    assert day.allowed_violations == ()
    assert day.difficulty_band == "easy"
    assert day.forced_includes == {}
    assert day.forced_violations == {}
    assert day.rule_sheet is None


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
    # unconstrained_day() rather than load_day(1): day 1 now pins all six
    # slots itself (#15), which would make "the forced pick is subtracted from
    # the bag" trivially true by never consulting the bag at all.
    mix = {Archetype.OBVIOUS_ADMIT: 2, Archetype.DAY_TO_DAY: 1,
           Archetype.CLUMSY_CUTIE: 1, Archetype.BAD_ACTOR: 1,
           Archetype.SNEAKY_BUGGER: 1}
    day = dataclasses.replace(unconstrained_day(), number=5,
                              archetype_mix=mix,
                              forced_includes={0: Archetype.SNEAKY_BUGGER})
    got = [candidate_gen.generate(SEED, day, i).archetype
           for i in range(day.candidate_count)]
    assert got[0] == Archetype.SNEAKY_BUGGER
    assert dict(Counter(got)) == mix


def test_allowed_violations_whitelist_restricts_planted_kinds():
    """When a day sets allowed_violations, no candidate may carry a kind
    outside it (it intersects with the #31 gate)."""
    import dataclasses
    day = dataclasses.replace(
        load_day(1), number=5,
        allowed_violations=(DiscrepancyKind.AFFILIATION_NOT_STATED,),
    )
    for i in range(day.candidate_count):
        c = candidate_gen.generate(SEED, day, i)
        for d in c.truth.discrepancies:
            assert d.kind == DiscrepancyKind.AFFILIATION_NOT_STATED, (
                f"slot {i} planted {d.kind} outside the day whitelist"
            )


# ─── Issue #35 — Rule.mutability + per-day ruleset loading ──────────────────


def test_mutability_defaults_to_fixed_and_only_advisories_are_variable(day1):
    """Mutability is opt-in: a rule that doesn't declare it is permanent policy.

    #35 landed this field defaulting to "fixed", so it changed no content. #36
    then marked exactly Day 1's three "flag, do not auto-deny" advisories as
    overseer_variable — the low-stakes hygiene calls a process update would
    plausibly move. Every disqualifying rule stays fixed: the Overseer must not
    be able to quietly relax the rules that actually keep threats out. That is
    #37's Dark Web directives, not a casual process note.
    """
    assert day1.rules, "Day 1 should have rules"
    variable = {r.id for r in day1.rules if r.mutability == "overseer_variable"}
    assert variable == {"rule_claimed_ip", "rule_weak_credential",
                        "rule_weak_encryption"}
    for rule in day1.rules:
        if rule.id not in variable:
            assert rule.mutability == "fixed", rule.id
        else:
            assert rule.severity == "weighted", rule.id


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
    assert all(b >= a for a, b in itertools.pairwise(ramp))
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

    base = unconstrained_day().archetype_mix
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


# ─── Issue #4 — difficulty curve ────────────────────────────────────────────


def test_reward_decay_shape_and_floors():
    admit = [config.DAY_REWARD_PAYOUT(d, True)  for d in range(1, 30)]
    deny  = [config.DAY_REWARD_PAYOUT(d, False) for d in range(1, 30)]

    # Tutorial days pay the undecayed rate (#15: days 1-5 stay flat-easy).
    assert admit[:4] == [config.HACKDOLLAR_PER_CORRECT_ADMIT] * 4
    assert deny[:4]  == [config.HACKDOLLAR_PER_CORRECT_DENY] * 4
    # Monotonically non-increasing, and bottoming out at the floors.
    assert all(b <= a for a, b in itertools.pairwise(admit))
    assert all(b <= a for a, b in itertools.pairwise(deny))
    assert min(admit) == config.HACKDOLLAR_FLOOR_ADMIT
    assert min(deny)  == config.HACKDOLLAR_FLOOR_DENY
    # The floors are reached around the campaign's climax, not mid-run.
    assert admit[config.CAMPAIGN_LAST_DAY // 2] > config.HACKDOLLAR_FLOOR_ADMIT


def test_scoring_applies_reward_decay_by_day(day1):
    """A correct verdict late in the campaign pays less than the same verdict
    on day 1 — with the board bonus held constant so only the base rate moves.
    """
    clean = next(
        c for c in (
            candidate_gen.generate(SEED, day1, slot_index=i)
            for i in range(day1.candidate_count)
        )
        if c.truth.correct_verdict == Verdict.ADMIT
    )
    early = scoring.score(clean, Verdict.ADMIT, set(), day_number=1)
    late  = scoring.score(clean, Verdict.ADMIT, set(), day_number=20)
    assert early.correct and late.correct
    assert late.hackdollars < early.hackdollars
    # The board bonus itself must NOT decay — only the base rate does.
    assert early.board_bonus == late.board_bonus
    assert (early.hackdollars - early.board_bonus
            == config.DAY_REWARD_PAYOUT(1, True))
    assert (late.hackdollars - late.board_bonus
            == config.DAY_REWARD_PAYOUT(20, True))


def test_apply_reads_the_day_off_game_state(day1):
    """scoring.apply must pass state.current_day through, or the decay curve
    silently never fires in the real game."""
    cand = next(
        c for c in (
            candidate_gen.generate(SEED, day1, slot_index=i)
            for i in range(day1.candidate_count)
        )
        if c.truth.correct_verdict == Verdict.ADMIT
    )
    early_state = GameState(seed=SEED, current_day=1)
    late_state  = GameState(seed=SEED, current_day=20)
    early = scoring.apply(cand, Verdict.ADMIT, early_state)
    late  = scoring.apply(cand, Verdict.ADMIT, late_state)
    assert late.hackdollar_delta < early.hackdollar_delta


def test_tool_cost_inflation_applies_after_the_upgrade_reduction():
    """#4 + #23: a purchased optimizer must keep saving its ⏱ in the late game.

    Regression guard on ordering. Inflating first and reducing second would
    clamp at the max(1, ...) floor once inflation grew comparable to the
    reduction, silently erasing the purchase.
    """
    from gameengine.core import tools_bridge

    plain    = GameState(seed=SEED, current_day=20)
    upgraded = GameState(seed=SEED, current_day=20)
    upgraded.upgrades = {"toolcost_ghostscan"}

    day1_plain = GameState(seed=SEED, current_day=1)
    assert (tools_bridge.tool_cost(day1_plain, "ghostscan")
            == config.TOOL_COSTS["ghostscan"])          # day 1 is undecayed
    assert (tools_bridge.tool_cost(plain, "ghostscan")
            > tools_bridge.tool_cost(day1_plain, "ghostscan"))
    # The saving is intact and exactly the advertised amount.
    assert (tools_bridge.tool_cost(plain, "ghostscan")
            - tools_bridge.tool_cost(upgraded, "ghostscan")
            == config.TOOLCOST_REDUCTION)
    # config's read-only twin must agree with the live one.
    assert (config.DAY_TOOL_COST("ghostscan", 20, upgraded.upgrades)
            == tools_bridge.tool_cost(upgraded, "ghostscan"))


def test_filter_and_stamp_costs_do_not_inflate():
    """Deliberate design call — see config.TOOL_COST_INFLATION_PERIOD."""
    assert config.FILTER_COSTS["ghostscan"] == 4
    assert config.STEGO_STAMP_COST == 5
    # Neither constant is a function of the day; nothing to inflate them.
    assert isinstance(config.FILTER_COSTS["ghostscan"], int)
    assert isinstance(config.STEGO_STAMP_COST, int)


def test_every_upgrade_has_a_shop_category():
    """The shop UI (BetweenDayScreen) groups UPGRADE_CATALOG into per-tool
    sub-headers off config.UPGRADE_CATEGORY — an upgrade with no entry there
    would silently vanish from the shop instead of erroring, the same
    "planted ground truth with no observable path" bug class flagged
    elsewhere in this file, just for the shop instead of a violation.
    """
    catalog_ids = {uid for uid, _label, _price, _desc in config.UPGRADE_CATALOG}
    assert catalog_ids == set(config.UPGRADE_CATEGORY.keys())
    assert set(config.UPGRADE_CATEGORY.values()) <= set(config.UPGRADE_CATEGORY_ORDER)
    # Every category has an accent color for the header line.
    for cat in config.UPGRADE_CATEGORY_ORDER:
        assert cat in config.UPGRADE_CATEGORY_ACCENT


def test_hard_band_biases_toward_tool_revealed_evidence():
    """#4 lever 3: late-game evidence should sit behind the ⏱ economy rather
    than in plain sight on the dossier."""
    from gameengine.core.models import ToolName

    def tool_share(day_number: int) -> float:
        day = load_day(day_number)
        dossier = tool = 0
        for i in range(day.candidate_count):
            for d in candidate_gen.generate(SEED, day, i).truth.discrepancies:
                if d.revealed_by == ToolName.DOSSIER:
                    dossier += 1
                else:
                    tool += 1
        return tool / max(1, tool + dossier)

    hard_day = next(d for d in range(1, config.CAMPAIGN_LAST_DAY + 1)
                    if config.difficulty_band_for_day(d) == "hard")
    assert load_day(hard_day).difficulty_band == "hard"
    assert tool_share(hard_day) > tool_share(6)


def test_hard_band_keeps_the_quick_case_archetypes():
    """The GDD wants low-friction pacing beats to survive into the late game;
    twelve straight deep investigations reads as a wall, not escalation."""
    hard = config.ARCHETYPE_MIX_BY_BAND["hard"]
    assert "the_professional" in hard
    assert "the_incompatible" in hard
    # ...and Sneaky Bugger is nevertheless the dominant archetype there.
    assert hard["sneaky_bugger"] == max(hard.values())


def test_difficulty_band_generation_stays_deterministic():
    """The tool-tier bias is a stable sort over an already-seeded shuffle, so
    it must not disturb determinism."""
    day = load_day(16)
    a = [candidate_gen.generate(SEED, day, i) for i in range(day.candidate_count)]
    b = [candidate_gen.generate(SEED, day, i) for i in range(day.candidate_count)]
    assert a == b


# ─── Issue #36 — Overseer-Variable rule broadcast ───────────────────────────


def test_day_one_broadcasts_nothing(day1):
    """No yesterday, nothing to announce."""
    assert rules_engine.diff_rulesets(None, day1) == ()


def test_diff_reports_only_mutable_rules(day1):
    """#36 AC: no line for a Fixed rule, even when it demonstrably changed."""
    from dataclasses import replace

    fixed_rule = next(r for r in day1.rules if r.mutability == "fixed")
    var_rule   = next(r for r in day1.rules
                      if r.mutability == "overseer_variable")

    def flip(sev):
        return "weighted" if sev == "disqualifying" else "disqualifying"

    tomorrow = replace(day1, number=2, rules=tuple(
        replace(r, severity=flip(r.severity))
        if r.id in (fixed_rule.id, var_rule.id) else r
        for r in day1.rules
    ))
    changed = rules_engine.diff_rulesets(day1, tomorrow)
    ids = {c.rule.id for c in changed}
    assert var_rule.id in ids
    assert fixed_rule.id not in ids, "a Fixed rule must never be broadcast"


def test_diff_reports_no_change_when_nothing_moved(day1):
    from dataclasses import replace
    assert rules_engine.diff_rulesets(day1, replace(day1, number=2)) == ()


def test_diff_detects_added_and_removed_mutable_rules(day1):
    from dataclasses import replace

    var_rule = next(r for r in day1.rules
                    if r.mutability == "overseer_variable")
    without = replace(day1, number=2,
                      rules=tuple(r for r in day1.rules if r.id != var_rule.id))
    removed = rules_engine.diff_rulesets(day1, without)
    assert [c.kind for c in removed] == ["removed"]

    added = rules_engine.diff_rulesets(without, replace(day1, number=3))
    assert [c.kind for c in added] == ["added"]


def test_variable_rules_actually_flip_across_the_campaign(day1):
    """The mechanic is only observable if the rules genuinely move."""
    from gameengine.core.content_loader import mutate_variable_rules

    seen: dict[str, set[str]] = {}
    for d in range(1, config.CAMPAIGN_LAST_DAY + 1):
        for rule in mutate_variable_rules(day1.rules, d):
            seen.setdefault(rule.id, set()).add(rule.severity)

    for rule in day1.rules:
        if rule.mutability == "overseer_variable":
            assert len(seen[rule.id]) == 2, (
                f"{rule.id} never flipped across the campaign")
        else:
            # Fixed rules must be left strictly alone.
            assert seen[rule.id] == {rule.severity}, rule.id


def test_rule_flips_are_deterministic_and_not_every_morning(day1):
    """Sticky and staggered — a briefing full of flips is noise the player
    learns to tune out."""
    from gameengine.core.content_loader import mutate_variable_rules

    prev = load_day(1)
    change_days = 0
    for d in range(2, config.CAMPAIGN_LAST_DAY + 1):
        from dataclasses import replace
        cur = replace(prev, number=d,
                      rules=mutate_variable_rules(day1.rules, d))
        # Deterministic: recomputing the same day gives the same ruleset.
        assert mutate_variable_rules(day1.rules, d) == cur.rules
        if rules_engine.diff_rulesets(prev, cur):
            change_days += 1
        prev = cur
    # Something happens...
    assert change_days > 0
    # ...but most mornings are quiet.
    assert change_days < (config.CAMPAIGN_LAST_DAY - 1) / 2


def test_broadcast_lines_are_prose_not_a_diff_dump(day1):
    """#36 AC: casual and in-fiction, one line per changed rule."""
    from dataclasses import replace

    from gameengine.ui.tui.app import rule_change_lines

    var_rule = next(r for r in day1.rules
                    if r.mutability == "overseer_variable")
    tomorrow = replace(day1, number=2, rules=tuple(
        replace(r, severity="disqualifying") if r.id == var_rule.id else r
        for r in day1.rules
    ))
    changes = rules_engine.diff_rulesets(day1, tomorrow)
    lines = rule_change_lines(changes, 2)

    assert len(lines) == len(changes) == 1
    line = lines[0]
    # Not a diff dump: no field names, no arrows, no raw severity tokens.
    for banned in ("severity", "->", "→", "disqualifying", "weighted",
                   "predicate", var_rule.id):
        assert banned not in line, f"{banned!r} leaked into: {line}"
    # Reads as a sentence, and the rule is actually referred to.
    assert line[0].isupper() and line.rstrip().endswith((".", "?", "!"))
    assert len(line.split()) > 6
    # Deterministic phrasing — replaying a day reproduces the same briefing.
    assert rule_change_lines(changes, 2) == lines


def test_broadcast_capitalises_a_sentence_initial_rule_fragment():
    """Fragments are lower-cased for mid-sentence use; a template that opens
    with one must still start with a capital."""
    from gameengine.ui.tui.app import _RULE_CHANGE_PHRASINGS, _starts_a_sentence

    checked = 0
    for templates in _RULE_CHANGE_PHRASINGS.values():
        for t in templates:
            assert "{rule}" in t
            if _starts_a_sentence(t):
                checked += 1
    assert checked, "no sentence-initial template to exercise the branch"


# ─── Issue #38 — dual-track scoring & alignment ─────────────────────────────


def test_alignment_persists_and_clamps(tmp_path, monkeypatch):
    """#38 AC: GameState.alignment is a persisted field, bounded both ways."""
    monkeypatch.setattr(config, "SAVE_FILE", tmp_path / "slot.json")
    state = GameState(seed=SEED)
    state.alignment = -7
    persistence.save(state)
    assert persistence.load().alignment == -7

    day1 = load_day(1)
    dark = candidate_gen.generate(SEED, day1, 0)
    for bound, start in ((config.ALIGNMENT_MAX, config.ALIGNMENT_MAX),
                         (config.ALIGNMENT_MIN, config.ALIGNMENT_MIN)):
        s = GameState(seed=SEED)
        s.alignment = start
        for _ in range(5):
            scoring.apply(dark, Verdict.ADMIT, s)
        assert config.ALIGNMENT_MIN <= s.alignment <= config.ALIGNMENT_MAX


def test_only_dark_web_and_white_hat_shift_alignment(day1):
    """#38 AC: verdicts on other archetypes must not move alignment."""
    from gameengine.core.candidate_gen import ARCHETYPE_SPECS

    aligned = {Archetype.DARK_WEB, Archetype.WHITE_HAT}
    for archetype, spec in ARCHETYPE_SPECS.items():
        if archetype in aligned:
            assert spec.moral_modifier != 0, archetype
        else:
            assert spec.moral_modifier == 0, archetype

    # And that flows through scoring: a neutral archetype never moves it.
    for i in range(day1.candidate_count):
        c = candidate_gen.generate(SEED, day1, i)
        if c.archetype in aligned:
            continue
        for verdict in (Verdict.ADMIT, Verdict.DENY):
            assert scoring.score(c, verdict, set()).alignment == 0


def test_admitting_a_rules_clean_dark_web_is_correct_and_still_drifts(day1):
    """#38's headline AC, and the corruption arc's whole premise.

    A Dark Web candidate is generated rules-clean, so the day's ruleset
    permits them and admitting them is correct on BOTH tracks — and it still
    moves the player toward Dark Web alignment.
    """
    from dataclasses import replace

    # Day 1's authored mix has no Dark Web slot; pin one in.
    day = replace(day1, forced_includes={0: Archetype.DARK_WEB},
                  archetype_mix={**day1.archetype_mix, Archetype.DARK_WEB: 1})
    dark = candidate_gen.generate(SEED, day, 0)
    assert dark.archetype == Archetype.DARK_WEB
    assert dark.truth.correct_verdict == Verdict.ADMIT
    assert dark.truth.moral_modifier == -1

    evaluation = rules_engine.evaluate(dark, day)
    assert not evaluation.triggered_disqualifying, (
        "Dark Web must be clean by the rules — that's what makes denying "
        "them a moral choice rather than a rules call"
    )

    delta = scoring.score(dark, Verdict.ADMIT, set(), evaluation=evaluation)
    assert delta.correct is True             # moral track: matched ground truth
    assert delta.rules_correct is True       # literal track: obeyed the book
    assert delta.rules_verdict == Verdict.ADMIT
    assert delta.alignment == -1             # ...and still drifted Dark Web
    assert delta.hackdollars > 0             # paid exactly like any correct admit


def test_literal_track_is_recorded_separately_and_changes_no_payout(day1):
    """#38 AC: alignment tracking must not disturb the ⏱/HD$ economy."""
    for i in range(day1.candidate_count):
        c = candidate_gen.generate(SEED, day1, i)
        ev = rules_engine.evaluate(c, day1)
        for verdict in (Verdict.ADMIT, Verdict.DENY):
            without = scoring.score(c, verdict, set())
            with_ev = scoring.score(c, verdict, set(), evaluation=ev)
            # Every economic field is byte-identical with and without the
            # literal track — it is a parallel value, not a scoring override.
            assert with_ev.hackdollars == without.hackdollars
            assert with_ev.site_health == without.site_health
            assert with_ev.board_bonus == without.board_bonus
            assert with_ev.alignment   == without.alignment
            assert with_ev.correct     == without.correct
            # ...and the literal track is only populated when measured.
            assert without.rules_verdict is None
            assert without.rules_correct is None
            assert with_ev.rules_verdict in (Verdict.ADMIT, Verdict.DENY)


def test_tracks_diverge_only_when_the_two_tracks_disagree(day1):
    """A "not measured" literal track must never register as divergence."""
    c = candidate_gen.generate(SEED, day1, 0)
    assert not scoring.score(c, Verdict.ADMIT, set()).tracks_diverge

    ev = rules_engine.evaluate(c, day1)
    for verdict in (Verdict.ADMIT, Verdict.DENY):
        d = scoring.score(c, verdict, set(), evaluation=ev)
        assert d.tracks_diverge == (d.rules_correct != d.correct)


def test_apply_records_both_tracks_on_the_result(day1):
    c = candidate_gen.generate(SEED, day1, 0)
    state = GameState(seed=SEED)
    result = scoring.apply(c, Verdict.ADMIT, state,
                           evaluation=rules_engine.evaluate(c, day1))
    assert result.rules_verdict is not None
    assert result.rules_correct is not None
    assert isinstance(result.tracks_diverge, bool)


# ─── Ghostscan evidence integrity (playtest bug, 2026-08-17) ────────────────
#
# Found in play: a Sneaky Bugger carrying AFFILIATION_MISMATCH ("claimed elite
# affiliation not found — ghostscan returned no match") had its claimed org
# printed next to its handle on three platforms by the very tool the violation
# is revealed by. The evidence CORROBORATED the lie. Root cause: the sweep and
# the filter summary both keyed only off AFFILIATION_UNVERIFIED and had no
# branch for AFFILIATION_MISMATCH at all.
#
# Same class as the credential-artifact exclusivity bug (2026-08-16): a planted
# ground-truth violation the player can never observe. These tests guard the
# whole ghostscan tier rather than the one kind, so the next unrendered kind
# fails here instead of in a playtest.


def _elite_faker(archetype, kind):
    """Generate a candidate carrying `kind`, searching seeds/days for one."""
    from dataclasses import replace
    base = unconstrained_day()
    for day_n in range(1, 8):
        day = replace(base, number=day_n,
                      forced_includes={0: archetype},
                      archetype_mix={**base.archetype_mix, archetype: 1})
        for seed in range(40):
            c = candidate_gen.generate(seed, day, 0)
            if any(d.kind == kind for d in c.truth.discrepancies):
                return c
    raise AssertionError(f"could not generate a {archetype} carrying {kind}")


def test_ghostscan_never_corroborates_an_unbacked_affiliation_claim():
    """The sweep must not print an org the ground truth says isn't there."""
    import random as _r

    from gameengine.core import tools_bridge

    c = _elite_faker(Archetype.SNEAKY_BUGGER, DiscrepancyKind.AFFILIATION_MISMATCH)
    org = c.claimed_affiliation
    assert org, "the faked-elite-org case needs a claimed org to fake"

    for show_forums in (False, True):
        lines = tools_bridge._ghostscan_sweep_lines(
            c, _r.Random(1234), show_forums=show_forums)
        # Find the rows that are the CANDIDATE's own entries (they carry the
        # handle); none of them may attribute the claimed org to them.
        own = [ln for ln in lines if c.handle in ln and "target" not in ln]
        assert own, "candidate should appear on at least one platform"
        for ln in own:
            assert f"[{org}]" not in ln, (
                f"sweep corroborated the faked org (show_forums={show_forums}): {ln}")


def test_ghostscan_filter_names_every_ghostscan_violation_it_planted():
    """Every ghostscan-revealed kind must be nameable from the filter summary.

    This is the general guard. A kind that is generated, tiered to GHOSTSCAN,
    and listed on the rules page but never rendered is an unflaggable
    violation — the player is scored on evidence that does not exist.
    """
    from gameengine.core import tools_bridge
    from gameengine.core.models import ToolName

    checked = set()
    for archetype in Archetype:
        spec = candidate_gen.ARCHETYPE_SPECS[archetype]
        for kind in spec.eligible_kinds:
            if candidate_gen._SEVERITY_REVEAL[kind][0] != ToolName.GHOSTSCAN:
                continue
            if kind in checked:
                continue
            try:
                c = _elite_faker(archetype, kind)
            except AssertionError:
                continue          # this archetype can't roll it; another will
            checked.add(kind)
            summary = "\n".join(tools_bridge._ghostscan_filter_summary_lines(c))
            assert kind.name in summary, (
                f"{kind.name} is planted on {archetype.value} and revealed by "
                f"ghostscan, but the filter summary never names it:\n{summary}")
    # Guard the guard: if generation changes so nothing is exercised, fail.
    assert DiscrepancyKind.AFFILIATION_MISMATCH in checked


def test_the_professional_still_gets_its_affiliation_confirmed():
    """The other side of the fix. The Professional draws from the same elite
    pool and is SUPPOSED to have ghostscan corroborate the claim — that is the
    whole 'quick admit' read. Suppressing the org for everyone would have
    broken it."""
    import random as _r
    from dataclasses import replace

    from gameengine.core import tools_bridge

    base = unconstrained_day()
    day = replace(base, number=1,
                  forced_includes={0: Archetype.THE_PROFESSIONAL},
                  archetype_mix={**base.archetype_mix,
                                 Archetype.THE_PROFESSIONAL: 1})
    c = candidate_gen.generate(SEED, day, 0)
    assert c.archetype == Archetype.THE_PROFESSIONAL
    assert not c.truth.discrepancies, "The Professional should be clean"

    lines = tools_bridge._ghostscan_sweep_lines(c, _r.Random(1234))
    own = [ln for ln in lines if c.handle in ln and "target" not in ln]
    assert any(f"[{c.claimed_affiliation}]" in ln for ln in own), (
        "The Professional's elite org must still be confirmed by the sweep")


# ─── Evidence integrity across every tool tier ──────────────────────────────
#
# Generalised from the AFFILIATION_MISMATCH playtest bug (2026-08-17), which
# was the third instance of one recurring class: a DiscrepancyKind that is
# generated and SCORED but has no rendering path in tools_bridge, so the player
# is graded on evidence that does not exist. The affiliation case was the worst
# variant — the sweep printed the claimed org, so the tool actively argued
# AGAINST its own ground truth.
#
# EVIDENCE_TOKENS is the contract: for each tool-revealed kind, a snippet that
# must appear in that tool's filtered output when the kind is planted, and must
# NOT appear when it isn't. Both directions matter and they catch different
# bugs:
#   • present-when-planted  → catches "generated but never rendered"
#   • absent-when-not       → catches "rendered for everyone", which is how a
#                             tool ends up corroborating a claim it should
#                             refute
#
# Tokens are matched against the tool's own vocabulary rather than assuming the
# enum name: Logwatch annotates the IP mismatch in prose, because it is meant to
# read as an observation about the log rather than a violation code.
#
# Dossier-tier kinds are excluded — they have no tool run to assert against;
# their evidence is structural (the chat panel, the email field, the strength
# chip) and is covered by the dossier's own rendering.

EVIDENCE_TOKENS: dict[DiscrepancyKind, str] = {
    # ── Ghostscan ────────────────────────────────────────────────────────
    # MISSING_PUBLIC_PROFILE joined this tier in #51; it was tiered DOSSIER and
    # so sat in this guard's blind spot while having no dossier evidence at all.
    DiscrepancyKind.MISSING_PUBLIC_PROFILE: "MISSING_PUBLIC_PROFILE",
    DiscrepancyKind.AFFILIATION_UNLISTED:  "AFFILIATION_UNLISTED",
    DiscrepancyKind.EMAIL_GITHUB_MISMATCH: "EMAIL_GITHUB_MISMATCH",
    DiscrepancyKind.BREACH_HIT:            "BREACH_HIT",
    DiscrepancyKind.SOCK_PUPPET_ACCOUNTS:  "SOCK_PUPPET_ACCOUNTS",
    DiscrepancyKind.AFFILIATION_MISMATCH:  "AFFILIATION_MISMATCH",
    DiscrepancyKind.BURNER_IDENTITY:       "BURNER_IDENTITY",
    DiscrepancyKind.THREAT_FORUM_MATCH:    "THREAT_FORUM_MATCH",
    DiscrepancyKind.TYPOSQUAT_HANDLE:      "TYPOSQUAT_HANDLE",
    # ── Hashcrack ────────────────────────────────────────────────────────
    DiscrepancyKind.LEAKED_PASSWORD:       "LEAKED_PASSWORD",
    DiscrepancyKind.WEAK_CREDENTIAL:       "WEAK_CREDENTIAL",
    DiscrepancyKind.CROSS_BREACH_REUSE:    "CROSS_BREACH_REUSE",
    # ── Logwatch ─────────────────────────────────────────────────────────
    DiscrepancyKind.BRUTE_FORCE_IN_LOG:    "BRUTE_FORCE_IN_LOG",
    DiscrepancyKind.IMPOSSIBLE_TRAVEL:     "IMPOSSIBLE_TRAVEL",
    DiscrepancyKind.INSIDER_BEHAVIOR:      "INSIDER_BEHAVIOR",
    DiscrepancyKind.CREDENTIAL_STUFFING:   "CREDENTIAL_STUFFING",
    DiscrepancyKind.AFTER_HOURS_ACCESS:    "AFTER_HOURS_ACCESS",
    DiscrepancyKind.LOW_AND_SLOW:          "LOW_AND_SLOW",
    # Prose annotation, not a named label — Logwatch's IP mismatch is meant to
    # read as an observation about the log, not a violation code.
    DiscrepancyKind.CLAIMED_IP_MISMATCH:   "login IP differs from dossier claim",
    # ── Stegotool ────────────────────────────────────────────────────────
    DiscrepancyKind.STEGO_PAYLOAD_PRESENT: "STEGO_PAYLOAD_PRESENT",
    DiscrepancyKind.ENCRYPTED_PAYLOAD:     "ENCRYPTED_PAYLOAD",
    DiscrepancyKind.COVERT_C2_CHANNEL:     "COVERT_C2_CHANNEL",
}


def _tool_tier_kinds() -> dict[DiscrepancyKind, object]:
    """Every DiscrepancyKind whose evidence lives behind a tool run."""
    from gameengine.core.models import ToolName
    return {
        kind: candidate_gen._SEVERITY_REVEAL[kind][0]
        for kind in DiscrepancyKind
        if candidate_gen._SEVERITY_REVEAL[kind][0] != ToolName.DOSSIER
    }


def test_every_tool_revealed_kind_declares_an_evidence_token():
    """Adding a tool-tier kind must force a decision about how it renders.

    This is the loop-closer. The recurring bug is that a kind gets generation
    and scoring but no rendering; failing here means someone added a kind
    without saying what the player is supposed to see.
    """
    missing = sorted(k.name for k in _tool_tier_kinds() if k not in EVIDENCE_TOKENS)
    assert not missing, (
        f"tool-revealed kinds with no declared evidence token: {missing}. "
        f"Add the token here AND the rendering in tools_bridge — a kind that "
        f"is generated and scored but never rendered is unflaggable."
    )
    stale = sorted(k.name for k in EVIDENCE_TOKENS if k not in _tool_tier_kinds())
    assert not stale, f"tokens declared for non-tool-tier kinds: {stale}"


def _filtered_output(candidate, kind, day, seed) -> str:
    """The filtered output of whichever tool reveals `kind`, as one string.

    `seed` must be the seed the candidate was generated from: the Logwatch and
    Hashcrack shared day logs are built per (seed, day) and contain a block of
    entries for each candidate in that day's roster. Passing a different seed
    silently produces a log the candidate does not appear in — which reads
    exactly like a rendering bug and isn't one.
    """
    from gameengine.core import tools_bridge
    from gameengine.core.models import ToolName

    tool = candidate_gen._SEVERITY_REVEAL[kind][0]
    state = GameState(seed=seed, current_day=day.number, compute_hours=10_000)
    if tool == ToolName.GHOSTSCAN:
        return "\n".join(tools_bridge.run_ghostscan_filtered_shared(
            candidate, state).raw_lines)
    if tool == ToolName.HASHCRACK:
        entries = tools_bridge.generate_hashcrack_day_log(seed, day)
        return "\n".join(tools_bridge.run_hashcrack_filtered_shared(
            entries, candidate, state).raw_lines)
    if tool == ToolName.LOGWATCH:
        entries = tools_bridge.generate_day_log(seed, day)
        return "\n".join(tools_bridge.run_logwatch_filtered_shared(
            entries, candidate, state).raw_lines)
    if tool == ToolName.STEGOTOOL:
        img = tools_bridge.build_stego_image(candidate, day.number)
        return "\n".join(tools_bridge.stamp_signature_lines(img, reveal_type=True))
    raise AssertionError(f"no output path for {tool}")


def _candidates_by_kind(kind, want: bool, limit: int = 3):
    """Up to `limit` (candidate, day, seed) triples that do / don't carry `kind`."""
    from dataclasses import replace
    base = unconstrained_day()
    found = []
    for archetype, spec in candidate_gen.ARCHETYPE_SPECS.items():
        if want and kind not in spec.eligible_kinds:
            continue
        for day_n in range(1, 8):
            day = replace(base, number=day_n,
                          forced_includes={0: archetype},
                          archetype_mix={**base.archetype_mix, archetype: 1})
            for seed in range(30):
                c = candidate_gen.generate(seed, day, 0)
                if any(d.kind == kind for d in c.truth.discrepancies) == want:
                    found.append((c, day, seed))
                    if len(found) >= limit:
                        return found
    return found


@pytest.mark.parametrize("kind", sorted(EVIDENCE_TOKENS, key=lambda k: k.name))
def test_planted_kind_is_visible_in_its_tools_filtered_output(kind):
    """Present-when-planted: the evidence the player is scored on must exist.

    Batch 4 raised this from limit=1 to _EVIDENCE_SAMPLE. #63 was a 66%
    failure rate that this guard stayed green on, because one sampled
    candidate is a coin flip when the bug is probabilistic — the GitHub row
    was present or absent depending on an rng.sample that this test never
    exercised twice. One example proves a rendering path exists; it does not
    prove the path is always taken.
    """
    token = EVIDENCE_TOKENS[kind]
    pairs = _candidates_by_kind(kind, want=True, limit=_EVIDENCE_SAMPLE)
    if not pairs:
        pytest.skip(f"no archetype currently rolls {kind.name}")
    for candidate, day, seed in pairs:
        out = _filtered_output(candidate, kind, day, seed)
        assert token in out, (
            f"{kind.name} is planted on {candidate.archetype.value} (seed "
            f"{seed}, day {day.number}) and revealed by "
            f"{candidate_gen._SEVERITY_REVEAL[kind][0].value}, but its filtered "
            f"output never shows {token!r}. The player cannot flag what the "
            f"tool does not render."
        )


@pytest.mark.parametrize("kind", sorted(EVIDENCE_TOKENS, key=lambda k: k.name))
def test_absent_kind_is_not_claimed_by_its_tools_filtered_output(kind):
    """Absent-when-not-planted: a tool must not report evidence it wasn't given.

    The other half, and the one the AFFILIATION_MISMATCH bug tripped from the
    far side — a tool that renders the same thing regardless of ground truth
    is just as broken as one that renders nothing, it simply lies in the
    opposite direction.
    """
    token = EVIDENCE_TOKENS[kind]
    for candidate, day, seed in _candidates_by_kind(kind, want=False, limit=3):
        out = _filtered_output(candidate, kind, day, seed)
        assert token not in out, (
            f"{candidate.archetype.value} does NOT carry {kind.name}, but its "
            f"{candidate_gen._SEVERITY_REVEAL[kind][0].value} output shows "
            f"{token!r} anyway — the tool is reporting evidence for a "
            f"violation that isn't there."
        )


# ─── Batch 4 — the three holes the guards above turned out to have ──────────
#
# #61, #62 and #63 all sailed past the two guards above. Between them they
# named four distinct blind spots, and every one of them is a way for the
# player to be graded on evidence that does not match what the tools showed:
#
#   1. _filtered_output() scans exactly ONE tool per kind — whichever
#      _SEVERITY_REVEAL names. A tool lying about ANOTHER tool's violation is
#      structurally invisible. That is #62: Hashcrack annotated "credential
#      stuffing pattern" on 91 of 91 weak/leaked-credential candidates, none of
#      which carried CREDENTIAL_STUFFING, and the guard only ever looked at
#      Logwatch.
#   2. Tokens are uppercase enum names. Hashcrack's claim was lowercase prose,
#      so even a cross-tool scan with the existing token would have missed it.
#      Foreign claims therefore get their own prose-phrase table.
#   3. A token can be satisfied by the FILTER SUMMARY, which is a restatement
#      of ground truth rather than an observation. #63: the summary printed
#      "▲ EMAIL_GITHUB_MISMATCH" unconditionally while the sweep body — the
#      commit-email row that is the violation's only actual evidence — was
#      absent 66% of the time. The summary said "look at this", and there was
#      nothing to look at.
#   4. limit=1 (fixed above).
#
# The lesson generalises past these three: a guard that reads the tool's
# CONCLUSION cannot detect a missing OBSERVATION, because the conclusion is
# computed from the same ground truth the guard is checking against. Only the
# body is independent evidence.

_EVIDENCE_SAMPLE = 8

# Prose a tool must never emit for a candidate that does not carry the kind —
# checked across ALL FOUR tools, not just the one that owns the violation.
# Lower-cased on both sides, so entries are written as the player reads them.
FOREIGN_CLAIM_TOKENS: dict[DiscrepancyKind, tuple[str, ...]] = {
    # #62. Both the annotate path (tools_bridge _render_hc_log) and the
    # explicit-tags path phrase it differently; both are listed, because a fix
    # that only corrected one of them would look green here.
    DiscrepancyKind.CREDENTIAL_STUFFING: (
        "credential stuffing",
        "rapid failure burst",
    ),
}

_FILTER_SUMMARY_MARK = "violation summary"


def _candidates_without_kind_per_archetype(kind, per_day: int = 3):
    """Candidates lacking `kind`, sampled across EVERY archetype.

    `_candidates_by_kind(want=False)` cannot be used here. It returns as soon
    as it has `limit` results, and it iterates archetypes in order — so it
    only ever samples the first archetype that qualifies, which for an
    absent-kind query is whichever one happens to come first. That is fine for
    the single-tool guard, where any counter-example will do, but useless for
    the foreign-claim guard: #62's lie was emitted specifically by candidates
    carrying a CREDENTIAL artifact kind (Clumsy Cutie, Bad Actor), and a
    sample that stops at obvious_admit never reaches them.

    Sampled per (archetype, DAY) rather than per archetype. The evidence-tier
    gate (candidate_gen.intro_day) means most credential and log kinds cannot
    be planted at all on day 1 — a per-archetype budget spends itself on day 1
    and never reaches the days where the interesting candidates live. That
    mistake made this guard silently inert on its first draft.
    """
    from dataclasses import replace

    base = unconstrained_day()
    found = []
    for archetype in candidate_gen.ARCHETYPE_SPECS:
        for day_n in range(1, 8):
            day = replace(base, number=day_n,
                          forced_includes={0: archetype},
                          archetype_mix={**base.archetype_mix, archetype: 1})
            taken = 0
            for seed in range(20):
                if taken >= per_day:
                    break
                c = candidate_gen.generate(seed, day, 0)
                if any(d.kind == kind for d in c.truth.discrepancies):
                    continue
                found.append((c, day, seed))
                taken += 1
    return found


def _all_tool_outputs(candidate, day, seed) -> dict[str, str]:
    """Every tool's filtered output for one candidate, keyed by tool name.

    Deliberately runs all four rather than routing on _SEVERITY_REVEAL — the
    whole point of the foreign-claim guard is that the offending tool is NOT
    the one that owns the violation.
    """
    from gameengine.core import tools_bridge

    state = GameState(seed=seed, current_day=day.number, compute_hours=10_000)
    img = tools_bridge.build_stego_image(candidate, day.number)
    return {
        "ghostscan": "\n".join(
            tools_bridge.run_ghostscan_filtered_shared(candidate, state).raw_lines),
        "hashcrack": "\n".join(
            tools_bridge.run_hashcrack_filtered_shared(
                tools_bridge.generate_hashcrack_day_log(seed, day),
                candidate, state).raw_lines),
        "logwatch": "\n".join(
            tools_bridge.run_logwatch_filtered_shared(
                tools_bridge.generate_day_log(seed, day),
                candidate, state).raw_lines),
        "stegotool": "\n".join(
            tools_bridge.stamp_signature_lines(img, reveal_type=True)),
    }


@pytest.mark.parametrize("kind", sorted(FOREIGN_CLAIM_TOKENS, key=lambda k: k.name))
def test_no_tool_claims_a_violation_another_tool_owns(kind):
    """No tool may assert a violation the candidate does not carry (#62).

    This is the INVERTED form of the recurring bug class. The familiar version
    is ground truth with no artifact; this is an artifact with no ground truth,
    and it is worse for the player: they cannot reconcile it against the
    evidence board, because the owning tool's board never lists it.
    """
    phrases = FOREIGN_CLAIM_TOKENS[kind]
    checked = 0
    for candidate, day, seed in _candidates_without_kind_per_archetype(kind):
        checked += 1
        for tool, out in _all_tool_outputs(candidate, day, seed).items():
            low = out.lower()
            for phrase in phrases:
                assert phrase not in low, (
                    f"{candidate.archetype.value} (seed {seed}, day "
                    f"{day.number}) does NOT carry {kind.name}, but the "
                    f"{tool} output says {phrase!r}. A tool asserting a "
                    f"violation it was never given is unfalsifiable for the "
                    f"player — {kind.name} is revealed by "
                    f"{candidate_gen._SEVERITY_REVEAL[kind][0].value}, so it "
                    f"cannot even appear on {tool}'s evidence board."
                )
    assert checked, f"no candidates found without {kind.name} — guard is inert"


# Kinds whose evidence is a specific OBSERVATION in the report body, not just
# the filter summary's restatement of it. Token must appear above the
# "[FILTER] violation summary" divider.
SWEEP_BODY_TOKENS: dict[DiscrepancyKind, str] = {
    # #63 — the commit-email row. Without it the player is told the commit
    # email differs from the dossier email with no commit email on screen.
    DiscrepancyKind.EMAIL_GITHUB_MISMATCH:  "commit email differs from dossier",
    # #56 — the sweep must show the OTHER org, not just name the violation.
    DiscrepancyKind.AFFILIATION_MISMATCH:   "profile says",
    # #51 — the thinned platform count, stated.
    DiscrepancyKind.MISSING_PUBLIC_PROFILE: "no meaningful public",
}


@pytest.mark.parametrize("kind", sorted(SWEEP_BODY_TOKENS, key=lambda k: k.name))
def test_corroborating_evidence_exists_in_the_sweep_body(kind):
    """The report BODY must corroborate what the filter summary asserts (#63).

    Split out from the token guard deliberately. The filter summary is derived
    from ground truth, so checking it proves only that ground truth exists —
    it is the same fact stated twice. The body is the independent observation,
    and it is the only thing the player can actually reason from.
    """
    from gameengine.core import tools_bridge

    token = SWEEP_BODY_TOKENS[kind]
    pairs = _candidates_by_kind(kind, want=True, limit=_EVIDENCE_SAMPLE)
    assert pairs, f"no archetype currently rolls {kind.name} — guard is inert"
    for candidate, day, seed in pairs:
        state = GameState(seed=seed, current_day=day.number,
                          compute_hours=10_000)
        out = "\n".join(
            tools_bridge.run_ghostscan_filtered_shared(candidate, state).raw_lines)
        body = out.split(_FILTER_SUMMARY_MARK)[0]
        assert token.lower() in body.lower(), (
            f"{kind.name} is planted on {candidate.archetype.value} (seed "
            f"{seed}, day {day.number}) and the filter summary names it, but "
            f"the sweep body never shows {token!r}. The summary is a "
            f"restatement of ground truth; the body is the evidence. Naming a "
            f"violation with nothing above the divider to corroborate it tells "
            f"the player to look at something that isn't on screen."
        )


def test_single_artifact_groups_are_mutually_exclusive():
    """A candidate submits one password and one image, so it can carry at most
    one violation about each.

    Two kinds from the same group means the loser is planted in ground truth —
    counting for scoring — with no artifact the player can inspect to find it.
    This was 16% of stego-carrying candidates before _STEGO_ARTIFACT_KINDS, and
    had already happened once with credentials (2026-08-16).
    """
    from dataclasses import replace

    from gameengine.core import tools_bridge

    # Named explicitly rather than read from _EXCLUSIVE_ARTIFACT_GROUPS. A guard
    # parameterised on the constant it is guarding cannot fail when that
    # constant is what regressed — this test originally did exactly that and
    # passed against a build with stego exclusivity removed.
    groups = {
        "credential": candidate_gen._CREDENTIAL_ARTIFACT_KINDS,
        "stego":      candidate_gen._STEGO_ARTIFACT_KINDS,
    }
    base = unconstrained_day()
    seen_stego = 0
    for day_n in (1, 5, 7):
        for archetype in candidate_gen.ARCHETYPE_SPECS:
            day = replace(base, number=day_n,
                          forced_includes={0: archetype},
                          archetype_mix={**base.archetype_mix, archetype: 1})
            for seed in range(60):
                c = candidate_gen.generate(seed, day, 0)
                kinds = {d.kind for d in c.truth.discrepancies}
                for label, group in groups.items():
                    assert len(kinds & group) <= 1, (
                        f"{archetype.value} seed {seed} day {day_n} carries "
                        f"{sorted(k.name for k in kinds & group)} from the "
                        f"{label} group — the candidate submits one artifact, "
                        f"so only one of these can ever be observable")
                # The image must render THE planted stego kind — exactly one.
                stego = kinds & groups["stego"]
                if stego:
                    seen_stego += 1
                    img = tools_bridge.build_stego_image(c, day_n)
                    assert {img.kind} == stego, (
                        f"planted {sorted(k.name for k in stego)} but the "
                        f"submitted image carries {img.kind}")
    assert seen_stego, "sweep never produced a stego candidate — guard is inert"


# ─── Issue #51 — Missing Public Profile is Ghostscan-tier ───────────────────


def test_missing_public_profile_is_ghostscan_tier():
    """#51: it was tiered DOSSIER but has no dossier evidence at all.

    The dossier's claimed_github comes from the archetype's handle style, not
    from whether this kind was planted, so a carrying candidate still showed a
    normal GitHub handle. The only tell is the thinned platform count in the
    Ghostscan sweep.
    """
    from gameengine.core.models import ToolName

    tool, sev = candidate_gen._SEVERITY_REVEAL[
        DiscrepancyKind.MISSING_PUBLIC_PROFILE]
    assert tool == ToolName.GHOSTSCAN
    assert sev == "minor"
    # intro_day derives from the tool, so the gate follows automatically.
    assert (intro_day(DiscrepancyKind.MISSING_PUBLIC_PROFILE)
            == config.TOOL_UNLOCK_DAY["ghostscan"])


def test_missing_public_profile_never_lands_before_ghostscan_unlocks():
    """The bug this fixes: 300 of 600 Day-1 Clumsy Cutie / White Hat candidates
    carried it while Ghostscan was still locked — an unflaggable violation that
    counted for scoring.

    Sweeps the archetypes that can roll it, on every day before Ghostscan's
    unlock day, rather than trusting the tier constant alone.
    """
    from dataclasses import replace

    base = unconstrained_day()
    rollers = [a for a, s in candidate_gen.ARCHETYPE_SPECS.items()
               if DiscrepancyKind.MISSING_PUBLIC_PROFILE in s.eligible_kinds]
    assert rollers, "no archetype rolls MISSING_PUBLIC_PROFILE — test is inert"

    unlock = config.TOOL_UNLOCK_DAY["ghostscan"]
    for day_n in range(1, unlock):
        for archetype in rollers:
            day = replace(base, number=day_n,
                          forced_includes={0: archetype},
                          archetype_mix={**base.archetype_mix, archetype: 1})
            for seed in range(120):
                c = candidate_gen.generate(seed, day, 0)
                assert not any(
                    d.kind == DiscrepancyKind.MISSING_PUBLIC_PROFILE
                    for d in c.truth.discrepancies), (
                    f"{archetype.value} seed {seed} carries "
                    f"MISSING_PUBLIC_PROFILE on day {day_n}, before Ghostscan "
                    f"unlocks on day {unlock} — unflaggable")


# ─── Issue #53 — typosquat handles are real lookalikes ──────────────────────


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein distance — the standard measure of typosquat closeness."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1,          # deletion
                           cur[j - 1] + 1,       # insertion
                           prev[j - 1] + (ca != cb)))   # substitution
        prev = cur
    return prev[-1]


def _typosquat_candidates(limit=25):
    from dataclasses import replace
    base = unconstrained_day()
    out = []
    for day_n in (3, 5, 7):
        day = replace(base, number=day_n,
                      forced_includes={0: Archetype.SNEAKY_BUGGER},
                      archetype_mix={**base.archetype_mix,
                                     Archetype.SNEAKY_BUGGER: 1})
        for seed in range(400):
            c = candidate_gen.generate(seed, day, 0)
            if any(d.kind == DiscrepancyKind.TYPOSQUAT_HANDLE
                   for d in c.truth.discrepancies):
                out.append(c)
                if len(out) >= limit:
                    return out
    return out


def test_typosquat_handle_is_actually_a_lookalike():
    """#53: before this, the handle was derived purely from the candidate's name
    and archetype style — a "typosquatted" handle looked exactly like anyone
    else's, and the violation existed only as a label in the free identity
    block.
    """
    cands = _typosquat_candidates()
    assert cands, "no typosquat candidates generated — test is inert"
    for c in cands:
        target = c.dossier.handle_squats
        assert target, f"{c.handle} carries the kind but records no squat target"
        assert target in candidate_gen._ELITE_ORG_HANDLE, target
        real = candidate_gen._ELITE_ORG_HANDLE[target]
        # A lookalike, not an exact copy — an exact match would be
        # impersonation and would make the violation uncatchable by comparison.
        assert c.handle != real, c.handle
        # ...and close enough to actually be mistaken for it. Edit distance is
        # the right measure here, not positional character equality: the rn-for-m
        # and insert/delete mutations shift every following character, so a
        # positional comparison of "rnitcsail" against "mitcsail" scores near
        # zero while being a textbook typosquat.
        assert _edit_distance(c.handle, real) <= 2, (c.handle, real)


def test_squat_target_is_never_recorded_when_the_kind_is_absent():
    """Engine-only ground truth must not leak onto candidates without it."""
    from dataclasses import replace
    base = unconstrained_day()
    checked = 0
    for archetype in candidate_gen.ARCHETYPE_SPECS:
        day = replace(base, number=5,
                      forced_includes={0: archetype},
                      archetype_mix={**base.archetype_mix, archetype: 1})
        for seed in range(40):
            c = candidate_gen.generate(seed, day, 0)
            if any(d.kind == DiscrepancyKind.TYPOSQUAT_HANDLE
                   for d in c.truth.discrepancies):
                continue
            checked += 1
            assert c.dossier.handle_squats is None, (
                f"{archetype.value} seed {seed} has no typosquat but records "
                f"handle_squats={c.dossier.handle_squats!r}")
    assert checked, "no clean candidates checked — test is inert"


def test_free_identity_block_no_longer_names_the_typosquat():
    """#53's core complaint: the violation was 'only caught because it is
    literally spelt out'. The free block must not name it."""
    from gameengine.core import tools_bridge

    for c in _typosquat_candidates(limit=8):
        free = " ".join(tools_bridge._ghostscan_identity_lines(c, hint=False)).lower()
        assert "typosquat" not in free, (
            f"the free identity block still gives it away: {free}")
        # The handle is still shown — that IS the evidence, unlabelled.
        assert c.handle in " ".join(
            tools_bridge._ghostscan_identity_lines(c, hint=False))


def test_typosquat_filter_names_the_squatted_target():
    """The filter should tell the player WHAT is being imitated, not restate
    the violation's own name."""
    from gameengine.core import tools_bridge

    for c in _typosquat_candidates(limit=8):
        summary = " ".join(tools_bridge._ghostscan_filter_summary_lines(c))
        assert "TYPOSQUAT_HANDLE" in summary
        assert c.dossier.handle_squats in summary, (
            "the filter must name the org being squatted")
        assert candidate_gen._ELITE_ORG_HANDLE[c.dossier.handle_squats] in summary, (
            "the filter must show the real handle for comparison")


def test_typosquat_is_minor_and_reachable():
    """#53 demotes it to minor. A minor kind is only selectable by an archetype
    that HAS a minor budget slot — the reason Sneaky Bugger gained one."""
    from gameengine.core.models import ToolName

    tool, sev = candidate_gen._SEVERITY_REVEAL[DiscrepancyKind.TYPOSQUAT_HANDLE]
    assert tool == ToolName.GHOSTSCAN
    assert sev == "minor"

    sneaky = candidate_gen.ARCHETYPE_SPECS[Archetype.SNEAKY_BUGGER]
    assert DiscrepancyKind.TYPOSQUAT_HANDLE in sneaky.eligible_kinds
    assert sneaky.budget.minor >= 1, (
        "Sneaky Bugger needs a minor slot or the reworked typosquat can never "
        "be selected")

    # Bad Actor has no minor slot, so the kind was removed from it rather than
    # left listed-but-unreachable.
    bad = candidate_gen.ARCHETYPE_SPECS[Archetype.BAD_ACTOR]
    if bad.budget.minor == 0:
        assert DiscrepancyKind.TYPOSQUAT_HANDLE not in bad.eligible_kinds, (
            "Bad Actor lists a minor kind it can never select")


def test_typosquat_generation_is_deterministic():
    from dataclasses import replace
    base = unconstrained_day()
    day = replace(base, number=5,
                  forced_includes={0: Archetype.SNEAKY_BUGGER},
                  archetype_mix={**base.archetype_mix, Archetype.SNEAKY_BUGGER: 1})
    for seed in range(60):
        a = candidate_gen.generate(seed, day, 0)
        b = candidate_gen.generate(seed, day, 0)
        assert a == b
        assert a.handle == b.handle
        assert a.dossier.handle_squats == b.dossier.handle_squats


# ─── Issue #54 — clumped stego carriers, buffered hint region ───────────────


def _stego_images(limit=30, day_n=6):
    from dataclasses import replace

    from gameengine.core import tools_bridge
    base = unconstrained_day()
    out = []
    for archetype in (Archetype.SNEAKY_BUGGER, Archetype.BAD_ACTOR,
                      Archetype.WHITE_HAT):
        day = replace(base, number=day_n,
                      forced_includes={0: archetype},
                      archetype_mix={**base.archetype_mix, archetype: 1})
        for seed in range(400):
            c = candidate_gen.generate(seed, day, 0)
            if {d.kind for d in c.truth.discrepancies} & candidate_gen._STEGO_ARTIFACT_KINDS:
                out.append(tools_bridge.build_stego_image(c, day_n))
                if len(out) >= limit:
                    return out
    return out


def test_stego_carrier_is_clumped_not_uniform_noise():
    """#54: carrier cells must form blocks, not per-cell coin flips.

    Discriminator is mean orthogonal carrier-neighbour count. For an
    independent per-cell fill at probability p the expectation is ~4p — about
    1.6 at the densities used here. Contiguous blocks sit far above that, so
    this fails loudly if the uniform fill ever comes back.
    """
    imgs = _stego_images()
    assert imgs, "no stego images generated — test is inert"
    for img in imgs:
        cells = img.carrier
        assert cells, f"{img.kind} produced no carrier cells"
        neighbours = sum(
            sum(1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if (x + dx, y + dy) in cells)
            for (x, y) in cells
        ) / len(cells)
        uniform_expectation = 4 * img.density
        assert neighbours > max(2.0, uniform_expectation * 1.5), (
            f"{img.kind.name} carrier looks uniform: mean neighbours "
            f"{neighbours:.2f} vs uniform expectation {uniform_expectation:.2f}")


def test_hint_region_is_a_buffered_superset_of_the_zone():
    """The Spectral Lens advertises a general area, never the exact zone."""
    for img in _stego_images():
        zx, zy, zw, zh = img.zone
        hx, hy, hw, hh = img.hint_region
        # Strictly contains the zone...
        assert hx <= zx and hy <= zy
        assert hx + hw >= zx + zw and hy + hh >= zy + zh
        # ...and is genuinely larger, or it would disclose the exact rectangle.
        assert (hw, hh) != (zw, zh) or (hx, hy) != (zx, zy), (
            "hint region equals the zone — the upgrade would hand over the "
            "answer instead of narrowing the search")
        # Never leaves the grid.
        assert hx >= 0 and hy >= 0
        assert hx + hw <= img.cols and hy + hh <= img.rows


def test_clean_image_has_no_zone_and_no_hint_region():
    """A clean candidate must never light up — the tint can't be a false
    positive."""
    from dataclasses import replace

    from gameengine.core import tools_bridge

    base = unconstrained_day()
    day = replace(base, number=6,
                  forced_includes={0: Archetype.OBVIOUS_ADMIT},
                  archetype_mix={**base.archetype_mix,
                                 Archetype.OBVIOUS_ADMIT: 1})
    checked = 0
    for seed in range(30):
        c = candidate_gen.generate(seed, day, 0)
        assert not c.truth.discrepancies
        img = tools_bridge.build_stego_image(c, 6)
        assert img.zone is None and img.hint_region is None
        assert img.carrier == frozenset()
        checked += 1
    assert checked


def test_every_stego_payload_can_be_found_before_it_resolves():
    """Regression on a bug the first clumping attempt introduced.

    With blocks anchored at a random corner, a systematic sweep could push zone
    coverage past the resolve threshold without ever landing on a carrier cell —
    so the player never saw the signature colour that identifies the payload
    type. Blocks now anchor at the zone centre, which a sweep must cross.
    """
    from gameengine.core import tools_bridge

    imgs = _stego_images(limit=40)
    for img in imgs:
        revealed: set = set()
        zx, zy, zw, zh = img.zone
        saw_signature = False
        done = False
        for yy in range(zy, zy + zh, config.STEGO_STAMP_H):
            for xx in range(zx, zx + zw, config.STEGO_STAMP_W):
                res = tools_bridge.evaluate_stamp(
                    img, xx, yy, config.STEGO_STAMP_W, config.STEGO_STAMP_H,
                    revealed)
                if res.signature:
                    saw_signature = True
                if res.resolved:
                    done = True
                    break
            if done:
                break
        assert saw_signature, (
            f"{img.kind.name} resolved without the player ever revealing a "
            f"carrier cell — the signature colour was unreachable")


def test_stego_image_is_deterministic():
    from dataclasses import replace

    from gameengine.core import tools_bridge

    base = unconstrained_day()
    day = replace(base, number=6,
                  forced_includes={0: Archetype.SNEAKY_BUGGER},
                  archetype_mix={**base.archetype_mix, Archetype.SNEAKY_BUGGER: 1})
    for seed in range(40):
        c = candidate_gen.generate(seed, day, 0)
        a = tools_bridge.build_stego_image(c, 6)
        b = tools_bridge.build_stego_image(c, 6)
        assert a.carrier == b.carrier
        assert a.zone == b.zone and a.hint_region == b.hint_region
        assert a.density == b.density


# ─── Issues #57 / #58 — domain-class integrity ──────────────────────────────


def test_every_generated_disposable_candidate_is_actually_detectable():
    """#57: the generator pool and the detector list had drifted, so 148 of 400
    DISPOSABLE_EMAIL candidates classified as "unknown" rather than
    "prohibited" — the dossier highlight never fired and the archetype's whole
    fast-DENY read silently failed.

    Sweeps generated candidates rather than just comparing the two constants,
    because comparing constants is what people already thought they were doing.
    """
    from dataclasses import replace

    from gameengine.core import tools_bridge

    base = unconstrained_day()
    day = replace(base, number=2,
                  forced_includes={0: Archetype.THE_INCOMPATIBLE},
                  archetype_mix={**base.archetype_mix,
                                 Archetype.THE_INCOMPATIBLE: 1})
    checked = 0
    for seed in range(200):
        c = candidate_gen.generate(seed, day, 0)
        if not any(d.kind == DiscrepancyKind.DISPOSABLE_EMAIL
                   for d in c.truth.discrepancies):
            continue
        checked += 1
        assert tools_bridge.classify_email_domain(c.email) == "prohibited", (
            f"{c.email} carries DISPOSABLE_EMAIL but classifies as "
            f"{tools_bridge.classify_email_domain(c.email)!r} — the player has "
            f"no way to see it")
    assert checked, "no DISPOSABLE_EMAIL candidates generated — test is inert"


def test_breach_hit_flag_credited_against_cross_breach_reuse():
    """Batch-3, revisiting #61(d): CROSS_BREACH_REUSE and BREACH_HIT stay
    distinct kinds in ground truth on purpose (Clumsy Cutie has no critical
    budget slot to force BREACH_HIT alongside it — see the #61(d) comment on
    tools_bridge.breach_dbs_for_candidate). But that function already makes a
    CROSS_BREACH_REUSE carrier's email show up — labeled BREACH_HIT — in
    Ghostscan's breach panel, so a player flagging BREACH_HIT there is
    reading real on-screen evidence and should be credited, not scored a
    false positive.
    """
    day = load_day(20)   # late enough for every tool/kind to be taught
    reuse_only = None
    for seed in range(500):
        c = candidate_gen.generate(seed, day, 0)
        kinds = {d.kind for d in c.truth.discrepancies}
        if (DiscrepancyKind.CROSS_BREACH_REUSE in kinds
                and DiscrepancyKind.BREACH_HIT not in kinds):
            reuse_only = c
            break
    assert reuse_only is not None, (
        "no CROSS_BREACH_REUSE-without-BREACH_HIT candidate generated in "
        "500 seeds — test is inert")
    actual = {d.kind for d in reuse_only.truth.discrepancies}

    # A perfect board (every real kind flagged, nothing else) is the score
    # to match — flagging BREACH_HIT in place of, or alongside,
    # CROSS_BREACH_REUSE must reach that same ceiling, not fall short of it.
    perfect = scoring.board_accuracy_bonus(actual, reuse_only)

    with_breach_hit = scoring.board_accuracy_bonus(
        (actual - {DiscrepancyKind.CROSS_BREACH_REUSE})
        | {DiscrepancyKind.CROSS_BREACH_REUSE, DiscrepancyKind.BREACH_HIT},
        reuse_only)
    assert with_breach_hit == perfect

    # Flagging ONLY BREACH_HIT in CROSS_BREACH_REUSE's place (having missed
    # or not run Hashcrack) is also a full match, not a false positive plus
    # a miss.
    breach_hit_in_place_of_reuse = scoring.board_accuracy_bonus(
        (actual - {DiscrepancyKind.CROSS_BREACH_REUSE})
        | {DiscrepancyKind.BREACH_HIT},
        reuse_only)
    assert breach_hit_in_place_of_reuse == perfect


def test_domain_classes_are_disjoint():
    """A domain in two classes would classify by whichever branch runs first,
    which is not a decision anyone made on purpose."""
    from gameengine.core import tools_bridge as tb

    classes = {
        "prohibited": set(tb._GS_SUSPICIOUS_DOMAINS),
        "privacy":    set(tb._GS_PRIVACY_DOMAINS),
        "approved":   set(tb._GS_TRUSTED_DOMAINS),
    }
    names = sorted(classes)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            overlap = classes[a] & classes[b]
            assert not overlap, f"{a} and {b} both claim {sorted(overlap)}"


def test_no_hint_text_tells_the_player_to_flag_a_nonexistent_violation():
    """#58: the privacy-provider line said "flag if other issues present", but
    there is no privacy DiscrepancyKind — so following it means flagging
    DISPOSABLE_EMAIL, which board_accuracy_bonus scores as a false positive.

    Guards the shape, not the one string: any identity-block line that tells the
    player to flag must correspond to a real violation.
    """
    from dataclasses import replace

    from gameengine.core import tools_bridge

    base = unconstrained_day()
    seen_privacy = False
    for archetype in candidate_gen.ARCHETYPE_SPECS:
        day = replace(base, number=2,
                      forced_includes={0: archetype},
                      archetype_mix={**base.archetype_mix, archetype: 1})
        for seed in range(25):
            c = candidate_gen.generate(seed, day, 0)
            cls = tools_bridge.classify_email_domain(c.email)
            lines = " ".join(tools_bridge._ghostscan_identity_lines(c, hint=False))
            if cls == "privacy":
                seen_privacy = True
                assert "flag" not in lines.lower(), (
                    f"privacy-provider hint still instructs a flag: {lines}")
    assert seen_privacy, "no privacy-domain candidate generated — test is inert"


# ─── Issue #56 — the four affiliation violations are distinct ───────────────


AFFIL_KINDS = (
    DiscrepancyKind.AFFILIATION_NOT_STATED,
    DiscrepancyKind.AFFILIATION_MISMATCH,
    DiscrepancyKind.AFFILIATION_UNLISTED,
    DiscrepancyKind.MISSING_PUBLIC_PROFILE,
)


def _affil_case(kind):
    """A candidate carrying `kind`, plus the seed and day it came from."""
    from dataclasses import replace
    base = unconstrained_day()
    for archetype in candidate_gen.ARCHETYPE_SPECS:
        day = replace(base, number=5,
                      forced_includes={0: archetype},
                      archetype_mix={**base.archetype_mix, archetype: 1},
                      allowed_violations=(kind,))
        for seed in range(300):
            c = candidate_gen.generate(seed, day, 0)
            if any(d.kind == kind for d in c.truth.discrepancies):
                return c, day, seed
    raise AssertionError(f"could not generate a candidate carrying {kind.name}")


def test_one_name_per_violation_everywhere():
    """#56: the dev ground-truth window showed `affiliation_mismatch` while the
    evidence board showed "Faked elite affiliation" — same violation, two names,
    no way to connect them. VIOLATION_CATALOG is now the single source and every
    surface reads it."""
    from gameengine.ui.tui import rules_content

    labels = {}
    for kind in DiscrepancyKind:
        label = rules_content.label_for(kind)
        assert label, kind.name
        assert label not in labels, (
            f"{kind.name} and {labels[label].name} share the label {label!r}")
        labels[label] = kind
    # The affiliation four must be named apart from each other, which is the
    # complaint that started this.
    affil_labels = {rules_content.label_for(k) for k in AFFIL_KINDS}
    assert len(affil_labels) == len(AFFIL_KINDS), affil_labels


def test_each_affiliation_violation_has_its_own_tier_and_hint():
    """Dossier violations under the dossier, ghostscan violations under
    ghostscan — and every hint names the tool its evidence comes from."""
    from gameengine.core.models import ToolName
    from gameengine.ui.tui import rules_content

    expected = {
        DiscrepancyKind.AFFILIATION_NOT_STATED: ToolName.DOSSIER,
        DiscrepancyKind.AFFILIATION_MISMATCH:   ToolName.GHOSTSCAN,
        DiscrepancyKind.AFFILIATION_UNLISTED:   ToolName.GHOSTSCAN,
        DiscrepancyKind.MISSING_PUBLIC_PROFILE: ToolName.GHOSTSCAN,
    }
    for kind, tool in expected.items():
        assert candidate_gen._SEVERITY_REVEAL[kind][0] == tool, kind.name
        hint = rules_content._CATCH[kind]
        assert tool.value.upper() in hint.upper(), (
            f"{kind.name}'s hint must name its tool; got {hint!r}")
        # And the rules-page group must match the tier.
        group = next(g for g, k, _l in rules_content.VIOLATION_CATALOG if k == kind)
        assert group == ("DOSSIER" if tool == ToolName.DOSSIER else "OSINT"), (
            f"{kind.name} is {tool.value}-tier but filed under {group}")


def test_the_three_ghostscan_affiliation_kinds_render_differently():
    """The bug that started this: a6ad3b0 gave two of them the same
    "(no org listed)" render, so they were indistinguishable in the one place
    they had to be told apart."""
    from gameengine.core import tools_bridge

    def sweep_org_rows(c, day, seed):
        state = GameState(seed=seed, current_day=day.number, compute_hours=10_000)
        out = tools_bridge.run_ghostscan_filtered_shared(c, state).raw_lines
        start = next(i for i, l in enumerate(out) if "PLATFORM SWEEP" in l)
        stop  = next(i for i, l in enumerate(out) if "account registry" in l)
        return [l for l in out[start:stop] if c.handle in l]

    # MISMATCH: sweep names a DIFFERENT org than the dossier.
    c, day, seed = _affil_case(DiscrepancyKind.AFFILIATION_MISMATCH)
    actual = c.dossier.actual_affiliation
    assert actual and actual != c.claimed_affiliation
    rows = "\n".join(sweep_org_rows(c, day, seed))
    assert actual in rows, "the mismatched org must appear in the sweep"
    assert "no org listed" not in rows, (
        "a mismatch must show the other org, not an absence — that was the "
        "collapse this issue exists to fix")

    # UNLISTED: sweep shows no org at all.
    c2, day2, seed2 = _affil_case(DiscrepancyKind.AFFILIATION_UNLISTED)
    rows2 = "\n".join(sweep_org_rows(c2, day2, seed2))
    assert "no org listed" in rows2

    # NOT_STATED: a dossier violation. The sweep shows their real org, and must
    # never echo the blank dossier sentinel as though it were one.
    c3, day3, seed3 = _affil_case(DiscrepancyKind.AFFILIATION_NOT_STATED)
    assert c3.claimed_affiliation == candidate_gen.NO_AFFILIATION_STATED
    rows3 = "\n".join(sweep_org_rows(c3, day3, seed3))
    assert candidate_gen.NO_AFFILIATION_STATED not in rows3, (
        "the sweep must not render the blank sentinel as an organisation")
    assert "no org listed" not in rows3, (
        "NOT_STATED has no ghostscan signature — that is what makes it a "
        "dossier violation")


def test_a_trusted_affiliation_can_never_be_faked():
    """#56's bypass: a claimed elite/trusted org always confirms in the sweep,
    so a player who recognises one can skip the ghostscan step. Enforced in
    generation, not just rendering, so the ground truth cannot contradict it."""
    from dataclasses import replace

    base = unconstrained_day()
    checked = 0
    for archetype in candidate_gen.ARCHETYPE_SPECS:
        day = replace(base, number=5,
                      forced_includes={0: archetype},
                      archetype_mix={**base.archetype_mix, archetype: 1})
        for seed in range(150):
            c = candidate_gen.generate(seed, day, 0)
            if c.claimed_affiliation not in candidate_gen.AFFILIATIONS_ELITE:
                continue
            checked += 1
            kinds = {d.kind for d in c.truth.discrepancies}
            assert not (kinds & {DiscrepancyKind.AFFILIATION_MISMATCH,
                                 DiscrepancyKind.AFFILIATION_UNLISTED}), (
                f"{archetype.value} claims the trusted org "
                f"{c.claimed_affiliation!r} and still carries "
                f"{sorted(k.name for k in kinds)} — the bypass has to be a "
                f"guarantee or it is a trap")
    assert checked, "no elite-claiming candidate generated — test is inert"


def test_affiliation_violations_are_mutually_exclusive():
    """One affiliation field, one set of profiles — at most one of these can be
    true, and some combinations are outright contradictory (NOT_STATED means
    nothing was claimed, so there is nothing for MISMATCH to disagree with)."""
    from dataclasses import replace

    base = unconstrained_day()
    group = candidate_gen._AFFILIATION_KINDS
    for day_n in (2, 5):
        for archetype in candidate_gen.ARCHETYPE_SPECS:
            day = replace(base, number=day_n,
                          forced_includes={0: archetype},
                          archetype_mix={**base.archetype_mix, archetype: 1})
            for seed in range(60):
                c = candidate_gen.generate(seed, day, 0)
                kinds = {d.kind for d in c.truth.discrepancies} & group
                assert len(kinds) <= 1, (
                    f"{archetype.value} seed {seed} carries "
                    f"{sorted(k.name for k in kinds)}")


# ─── Issue #59 — credential algorithm and plaintext are orthogonal ──────────


def _algo(h: str | None) -> str:
    if not h:
        return "none"
    if h.startswith("$2b$"):
        return "bcrypt"
    return "sha256" if len(h) == 64 else "md5"


def _credential_sweep(days=(5,), seeds=300):
    from dataclasses import replace
    base = unconstrained_day()
    for day_n in days:
        for archetype in candidate_gen.ARCHETYPE_SPECS:
            day = replace(base, number=day_n,
                          forced_includes={0: archetype},
                          archetype_mix={**base.archetype_mix, archetype: 1})
            for seed in range(seeds):
                yield candidate_gen.generate(seed, day, 0)


def test_weak_encryption_is_exactly_the_md5_candidates():
    """#59: WEAK_ENCRYPTION means "the weakest algorithm is used", so it must
    track the hash exactly — every md5 candidate carries it, no other candidate
    does.

    Both directions are real bugs that existed. Only 199 of 432 md5 candidates
    flagged it (so the dossier's WEAK ENC chip sometimes meant a violation and
    sometimes didn't), and 62 of 2700 carried it on a *sha256* hash — a
    weak-encryption violation on a medium-encryption credential, with nothing
    for the player to observe.
    """
    md5_without = sha_with = 0
    checked = 0
    for c in _credential_sweep():
        checked += 1
        has = any(d.kind == DiscrepancyKind.WEAK_ENCRYPTION
                  for d in c.truth.discrepancies)
        algo = _algo(c.dossier.submitted_hash)
        if algo == "md5" and not has:
            md5_without += 1
        if algo != "md5" and has:
            sha_with += 1
    assert checked
    assert md5_without == 0, f"{md5_without} md5 candidates without WEAK_ENCRYPTION"
    assert sha_with == 0, f"{sha_with} non-md5 candidates carrying WEAK_ENCRYPTION"


def test_weak_credential_is_reachable_on_medium_encryption():
    """#59: "anything but the strongest requires a crack to confirm complexity"
    only works if a sha256 hash can actually crack to a weak password. It never
    could — WEAK_CREDENTIAL forced md5, so cracking medium could only ever
    surface a *leaked* password, never a merely weak one."""
    seen = set()
    for c in _credential_sweep():
        if any(d.kind == DiscrepancyKind.WEAK_CREDENTIAL
               for d in c.truth.discrepancies):
            seen.add(_algo(c.dossier.submitted_hash))
    assert "sha256" in seen, (
        "WEAK_CREDENTIAL never occurs on medium encryption — cracking a sha256 "
        "hash can then never reveal a weak password")
    assert "md5" in seen, "WEAK_CREDENTIAL should still be possible on md5"


def test_weak_encryption_and_weak_credential_stack():
    """The most interesting candidate in the set: bad algorithm AND bad
    password. Unreachable before #59 because both sat in the same
    mutual-exclusion group."""
    both = 0
    for c in _credential_sweep():
        kinds = {d.kind for d in c.truth.discrepancies}
        if {DiscrepancyKind.WEAK_ENCRYPTION,
                DiscrepancyKind.WEAK_CREDENTIAL} <= kinds:
            both += 1
            assert _algo(c.dossier.submitted_hash) == "md5"
            assert c.dossier.password_plain in candidate_gen._HC_WEAK_PASSWORDS
    assert both, "md5 + weak password never produces both violations"


def test_plaintext_kinds_stay_mutually_exclusive():
    """One submitted password, so only one kind may describe what it IS.
    WEAK_ENCRYPTION is excluded — it describes the algorithm, not the plaintext,
    which is the whole point of #59."""
    assert (DiscrepancyKind.WEAK_ENCRYPTION
            not in candidate_gen._CREDENTIAL_ARTIFACT_KINDS)
    for c in _credential_sweep(seeds=120):
        kinds = {d.kind for d in c.truth.discrepancies}
        overlap = kinds & candidate_gen._CREDENTIAL_ARTIFACT_KINDS
        assert len(overlap) <= 1, sorted(k.name for k in overlap)


def test_bcrypt_candidates_are_always_clean():
    """Strong encryption needs no crack — so a bcrypt hash must never carry a
    credential violation, or the player would be expected to find something in
    an uncrackable hash."""
    checked = 0
    credential_kinds = (candidate_gen._CREDENTIAL_ARTIFACT_KINDS
                        | {DiscrepancyKind.WEAK_ENCRYPTION})
    for c in _credential_sweep(seeds=150):
        if _algo(c.dossier.submitted_hash) != "bcrypt":
            continue
        checked += 1
        assert c.dossier.password_plain is None, "bcrypt must stay uncrackable"
        assert not ({d.kind for d in c.truth.discrepancies} & credential_kinds)
    assert checked, "no bcrypt candidates generated — test is inert"


def test_derived_weak_encryption_respects_the_day_whitelist():
    """A derived violation still has to obey the constraints a rolled one would,
    or `lab -v` and authored day content would both quietly lie."""
    from dataclasses import replace

    base = unconstrained_day()
    day = replace(base, number=5,
                  forced_includes={0: Archetype.CLUMSY_CUTIE},
                  archetype_mix={**base.archetype_mix, Archetype.CLUMSY_CUTIE: 1},
                  allowed_violations=(DiscrepancyKind.UNSALTED_STORAGE,))
    for seed in range(200):
        c = candidate_gen.generate(seed, day, 0)
        kinds = {d.kind for d in c.truth.discrepancies}
        assert DiscrepancyKind.WEAK_ENCRYPTION not in kinds, (
            "WEAK_ENCRYPTION was derived despite not being whitelisted")
        assert kinds <= {DiscrepancyKind.UNSALTED_STORAGE}, kinds


def test_password_encryption_chip_gated_behind_cipher_id_hud():
    """Batch-3 task #4: the [WEAK ENC]/[MEDIUM ENC]/[STRONG ENC] chip on the
    dossier only auto-labels the algorithm once UPGRADE_CRYPTO_ID is owned.
    Ungated, the raw hash must still be fully shown (evidence stays
    observable — see the "planted ground truth" bug class at the top of this
    file) — the player is just left to recognise it by shape, per the rules
    page's new reference table.
    """
    from gameengine.ui.tui.app import _password_markup

    day = unconstrained_day()
    d = None
    for seed in range(50):
        c = candidate_gen.generate(seed, day, 0)
        if not c.dossier.credential_unsalted:
            d = c.dossier
            break
    assert d is not None

    head_ungated, _ = _password_markup(d, None, upgrades=set())
    head_gated, _ = _password_markup(d, None, upgrades={config.UPGRADE_CRYPTO_ID})

    assert d.submitted_hash[:14] in head_ungated   # raw hash always visible
    for label in ("WEAK ENC", "MEDIUM ENC", "STRONG ENC"):
        assert label not in head_ungated, f"{label!r} leaked without the upgrade"
    assert any(label in head_gated
               for label in ("WEAK ENC", "MEDIUM ENC", "STRONG ENC"))


def test_unsalted_password_shows_plaintext_directly_no_crack_prompt():
    """Nick, playtest: for an UNSALTED_STORAGE candidate the Password entry
    should simply BE the plaintext — no encrypted-looking hash chip, and
    critically no "encrypted — run hashcrack (H) to attempt crack" prompt,
    since there is nothing left to crack. _password_markup() now handles
    credential_unsalted first and returns early, so that prompt string (which
    only exists in the salted branch further down) can never appear."""
    from gameengine.ui.tui.app import _password_markup

    d = Dossier(submitted_hash="5f4dcc3b5aa765d61d8327deb882cf99",
                password_plain="monkey123", credential_unsalted=True)
    head, state = _password_markup(d, None, upgrades=set())
    assert "monkey123" in head, "the Password entry itself must be the plaintext"
    assert "run hashcrack" not in head.lower()
    assert "run hashcrack" not in state.lower()
    assert "encrypted" not in head.lower()
    assert "encrypted" not in state.lower()
    # Still tagged as UNSALTED_STORAGE evidence, not silently indistinguishable
    # from a cracked result.
    assert "UNSALTED" in head


def test_strong_password_verdict_line_gated_behind_crack_verdict_analyzer():
    """The "strongest tier is always safe" wording is a strength VERDICT, not
    the plaintext itself, so it's gated behind UPGRADE_HC_VERDICT — same
    upgrade that gates the equivalent Hashcrack-log wording (#6a), so the two
    surfaces never disagree about what's told to the player for free.
    """
    from gameengine.ui.tui.app import _password_markup

    # cracked_password == "" is the uncracked-but-attempted (bcrypt) state.
    d = Dossier(submitted_hash="$2b$12$KIXQ7c5s9j2mR8vN0abcdEfGhIjKlMnOpQrStUvWxYz012345",
                password_plain=None, credential_unsalted=False)
    _, state_ungated = _password_markup(d, "", upgrades=set())
    _, state_gated = _password_markup(d, "", upgrades={config.UPGRADE_HC_VERDICT})
    assert "always safe" not in state_ungated
    assert "always safe" in state_gated


def test_breach_auto_upgrade_confirms_hit_on_base_ghostscan_run():
    """Batch-3 task #4c: config.UPGRADE_BREACH_AUTO ("Breach Feed Sync")
    confirms BREACH_HIT on the free base run, not only the paid filter run.
    Threat-forum content must stay gated regardless — the upgrade only
    touches the breach section.
    """
    from gameengine.core import tools_bridge

    day = load_day(20)
    cand = None
    for seed in range(200):
        c = candidate_gen.generate(seed, day, 0)
        if DiscrepancyKind.BREACH_HIT in {d.kind for d in c.truth.discrepancies}:
            cand = c
            break
    assert cand is not None, "no BREACH_HIT candidate found in 200 seeds"

    plain_state = GameState(seed=SEED, current_day=1)
    result_plain = tools_bridge.run_ghostscan_shared(cand, plain_state)
    assert not any("BREACH_HIT" in ln for ln in result_plain.raw_lines), (
        "BREACH_HIT confirmed on the base run without the upgrade")

    auto_state = GameState(seed=SEED, current_day=1)
    auto_state.upgrades = {config.UPGRADE_BREACH_AUTO}
    result_auto = tools_bridge.run_ghostscan_shared(cand, auto_state)
    assert any("BREACH_HIT" in ln for ln in result_auto.raw_lines), (
        "BREACH_HIT was not confirmed on the base run with the upgrade")
    # Threat forums are a different violation family — the breach upgrade
    # must not also leak them on the free run.
    assert not any("[CRITICAL]" in ln or "[ADVISORY]" in ln
                  for ln in result_auto.raw_lines)


def test_hashcrack_highlighting_actually_gated_by_credential_hud():
    """Batch-3 task #4d: run_hashcrack_shared used to call _render_hc_log with
    only annotate=True, so Credential HUD (hash_highlight) never gated
    anything once the tool was run — any base run already highlighted
    suspicious lines and injected "▲ why" annotations for free. Also checks
    Nick's explicit requirement: the crack must still reveal the plaintext
    without the upgrade, just without the "▲" attention-drawing.
    """
    import random as _random

    from gameengine.core import tools_bridge

    day = load_day(20)
    cand = None
    for seed in range(200):
        c = candidate_gen.generate(seed, day, 0)
        kinds = {d.kind for d in c.truth.discrepancies}
        if kinds & {DiscrepancyKind.WEAK_CREDENTIAL, DiscrepancyKind.LEAKED_PASSWORD,
                    DiscrepancyKind.CROSS_BREACH_REUSE, DiscrepancyKind.UNSALTED_STORAGE}:
            cand = c
            break
    assert cand is not None, "no credential-violation candidate in 200 seeds"

    entries = tools_bridge._hc_candidate_entries(cand, _random.Random(1), day.number)
    plaintext = cand.dossier.password_plain
    assert plaintext

    plain_state = GameState(seed=SEED, current_day=20)
    ungated = tools_bridge.run_hashcrack_shared(entries, cand, plain_state).raw_lines
    assert not any("▲" in ln for ln in ungated), (
        "attention-drawing ▲ annotation appeared without Credential HUD")
    assert any(plaintext in ln for ln in ungated), (
        "the crack must still reveal the plaintext without the upgrade")

    gated_state = GameState(seed=SEED, current_day=20)
    gated_state.upgrades = {config.UPGRADE_HASH_HIGHLIGHT}
    gated = tools_bridge.run_hashcrack_shared(entries, cand, gated_state).raw_lines
    assert any("▲" in ln for ln in gated), (
        "Credential HUD did not restore the ▲ annotations")
    assert any(plaintext in ln for ln in gated)


def test_logwatch_highlighting_actually_gated_by_log_analyzer_hud():
    """Batch-3 task #4e: same bug as #4d, for Logwatch/log_highlight. The
    claimed-IP-mismatch call-out is intentionally excluded from this gate —
    it's documented elsewhere (rules_content._CATCH) as always-free evidence,
    a separate, pre-existing design decision.
    """
    from gameengine.core import tools_bridge

    day = load_day(20)
    cand = None
    for seed in range(200):
        c = candidate_gen.generate(seed, day, 0)
        kinds = {d.kind for d in c.truth.discrepancies}
        if kinds & {DiscrepancyKind.BRUTE_FORCE_IN_LOG, DiscrepancyKind.CREDENTIAL_STUFFING,
                    DiscrepancyKind.IMPOSSIBLE_TRAVEL, DiscrepancyKind.INSIDER_BEHAVIOR}:
            cand = c
            break
    assert cand is not None, "no logwatch-violation candidate in 200 seeds"

    import random as _random
    entries = tools_bridge._lw_candidate_entries(cand, _random.Random(1))
    # The claimed-IP-mismatch call-out is free by design (unrelated to this
    # upgrade) — exclude it so the assertion targets only the gated
    # violation-annotation phrases.
    violation_markers = ("rapid auth failures", "credential stuffing",
                         "geographically distant", "after-hours privileged",
                         "outside business hours")

    plain_state = GameState(seed=SEED, current_day=20)
    ungated = tools_bridge.run_logwatch_shared(entries, cand, plain_state).raw_lines
    assert not any(m in ln for ln in ungated for m in violation_markers), (
        "attention-drawing ▲ annotation appeared without Log Analyzer HUD")

    gated_state = GameState(seed=SEED, current_day=20)
    gated_state.upgrades = {config.UPGRADE_LOG_HIGHLIGHT}
    gated = tools_bridge.run_logwatch_shared(entries, cand, gated_state).raw_lines
    assert any(m in ln for ln in gated for m in violation_markers), (
        "Log Analyzer HUD did not restore the ▲ annotations")


def test_strong_password_verdict_gated_in_hashcrack_log():
    """Batch-3 task #6a: the "(strong password — no concern)" verdict wording
    in the Hashcrack log itself (not just the dossier chip, covered by a
    separate test above) is gated behind UPGRADE_HC_VERDICT. The plaintext
    must still reveal either way — only the qualitative verdict is paywalled.
    """
    import random as _random

    from gameengine.core import tools_bridge

    day = load_day(20)
    cred_kinds = {DiscrepancyKind.WEAK_CREDENTIAL, DiscrepancyKind.LEAKED_PASSWORD,
                 DiscrepancyKind.CROSS_BREACH_REUSE, DiscrepancyKind.UNSALTED_STORAGE}
    cand = None
    for seed in range(200):
        c = candidate_gen.generate(seed, day, 0)
        kinds = {d.kind for d in c.truth.discrepancies}
        strength = tools_bridge.password_strength(c.dossier.submitted_hash)
        if (not (kinds & cred_kinds) and strength == "medium"
                and tools_bridge.crack_password(c)):
            cand = c
            break
    assert cand is not None, "no neutral-crack candidate found in 200 seeds"

    entries = tools_bridge._hc_candidate_entries(cand, _random.Random(1), day.number)
    plaintext = tools_bridge.crack_password(cand)

    plain_state = GameState(seed=SEED, current_day=20)
    ungated = tools_bridge.run_hashcrack_shared(entries, cand, plain_state).raw_lines
    assert any(plaintext in ln for ln in ungated), "plaintext must still reveal"
    assert not any("no concern" in ln for ln in ungated)

    gated_state = GameState(seed=SEED, current_day=20)
    gated_state.upgrades = {config.UPGRADE_HC_VERDICT}
    gated = tools_bridge.run_hashcrack_shared(entries, cand, gated_state).raw_lines
    assert any("no concern" in ln for ln in gated)


def test_stego_rgb_coloring_gated_behind_channel_colorizer():
    """Batch-3 task #4f: the R/G/B channel entropy numbers are always shown;
    only their severity coloring is gated behind UPGRADE_STEGO_RGB_COLOR.
    """
    import re

    from gameengine.core import tools_bridge

    day = load_day(20)
    cand = candidate_gen.generate(SEED, day, 0)

    ungated = tools_bridge.get_stego_stats(cand, upgrades=set())
    gated = tools_bridge.get_stego_stats(cand, upgrades={config.UPGRADE_STEGO_RGB_COLOR})

    def channel_lines(lines):
        return [ln for ln in lines if "channel LSB entropy" in ln]

    ungated_ch, gated_ch = channel_lines(ungated), channel_lines(gated)
    assert len(ungated_ch) == len(gated_ch) == 3
    # Numbers must match — the upgrade only changes color, never the values.
    _num = re.compile(r"(\d+)\[/\]\s*/\s*100")
    assert [_num.search(l).group(1) for l in ungated_ch] == \
           [_num.search(l).group(1) for l in gated_ch]
    assert all("#c8d4e1" in l for l in ungated_ch), "ungated lines must be neutral-colored"
    assert any(c in l for l in gated_ch for c in ("#ff5470", "#ff8c42", "#00ff9f")), (
        "gated lines never used a severity color")


# ─── Issue #60 — the ruleset expresses the ground truth ─────────────────────


def test_every_violation_kind_has_a_rule(day1):
    """#60: thirteen kinds had no rule in day_01.json, so the rulebook could
    not express the ground truth at all.

    The worst case was THE_INCOMPATIBLE — its only violation is
    DISPOSABLE_EMAIL, which had no rule, so a by-the-book player admitted
    100% of them while the rules page taught "fast DENY" for exactly that
    archetype.

    This test is the point of the issue: every kind added since the day file
    was authored silently became unenforceable, and nothing caught it.
    """
    ruled = {r.predicate.split(":", 1)[1] for r in day1.rules
             if r.predicate.startswith("has_discrepancy:")}
    missing = sorted(k.value for k in DiscrepancyKind if k.value not in ruled)
    assert not missing, (
        f"DiscrepancyKinds with no rule in day_01.json: {missing}. A violation "
        f"the rulebook cannot express is one a by-the-book player can never "
        f"act on.")


def test_rule_severity_matches_violation_tier(day1):
    """The convention the existing rules already follow: critical and major
    kinds disqualify, minor kinds are weighted (flag, corroborate first)."""
    for rule in day1.rules:
        if not rule.predicate.startswith("has_discrepancy:"):
            continue
        kind = DiscrepancyKind(rule.predicate.split(":", 1)[1])
        _tool, sev = candidate_gen._SEVERITY_REVEAL[kind]
        expected = "disqualifying" if sev in ("major", "critical") else "weighted"
        assert rule.severity == expected, (
            f"{rule.id}: {kind.name} is {sev} so the rule should be "
            f"{expected}, got {rule.severity}")


def test_the_ruleset_now_agrees_with_ground_truth_on_the_verdict():
    """#60: 503 of 2700 candidates were DENY by ground truth and ADMIT by the
    rulebook — 19%, and 100% of THE_INCOMPATIBLE.

    Verdict-level agreement is the correct end state. #38's tension is not
    supposed to live in the verdict: the Dark Web archetype is generated
    rules-clean on purpose, so admitting it is right by BOTH tracks and the
    cost is paid in alignment. Divergence in the verdict means the rulebook is
    incomplete, not that the player faces a moral choice.
    """
    from dataclasses import replace

    base = unconstrained_day()
    divergent = []
    for archetype in candidate_gen.ARCHETYPE_SPECS:
        day = replace(base, number=5,
                      forced_includes={0: archetype},
                      archetype_mix={**base.archetype_mix, archetype: 1})
        for seed in range(120):
            c = candidate_gen.generate(seed, day, 0)
            ev = rules_engine.evaluate(c, day)
            rules_verdict = (Verdict.DENY if ev.triggered_disqualifying
                             else Verdict.ADMIT)
            if rules_verdict != c.truth.correct_verdict:
                divergent.append(
                    (archetype.value, seed, c.truth.correct_verdict.value,
                     rules_verdict.value,
                     sorted(d.kind.value for d in c.truth.discrepancies)))
    assert not divergent, (
        f"{len(divergent)} candidates where the rulebook and the ground truth "
        f"disagree on the verdict; first few: {divergent[:3]}")


def test_the_incompatible_is_deniable_by_the_book():
    """The archetype whose entire design is a free, instant deny. Before #60 a
    by-the-book player admitted every single one."""
    from dataclasses import replace

    base = unconstrained_day()
    day = replace(base, number=2,
                  forced_includes={0: Archetype.THE_INCOMPATIBLE},
                  archetype_mix={**base.archetype_mix,
                                 Archetype.THE_INCOMPATIBLE: 1})
    checked = 0
    for seed in range(120):
        c = candidate_gen.generate(seed, day, 0)
        if c.archetype != Archetype.THE_INCOMPATIBLE:
            continue
        checked += 1
        ev = rules_engine.evaluate(c, day)
        assert ev.triggered_disqualifying, (
            f"seed {seed}: The Incompatible trips no disqualifying rule — the "
            f"rules page teaches 'fast DENY' for exactly this candidate")
    assert checked


# ─── Issue #61 — breach databases: static, sorted, progressively unlocked ───
#
# Nick's playtest read, in three parts: the lists were unscannable (unsorted),
# unlearnable (regenerated per candidate), and dishonest (Hashcrack named
# corpora the Ghostscan panel had never put the email in). The last one is the
# recurring bug class again — one tool contradicting another about the same
# candidate.

_BREACH_TEST_SEED = 20260818


def _breach_carriers(kind, day_n, per_archetype=4):
    """(candidate, day) pairs on `day_n` carrying `kind`."""
    from dataclasses import replace
    base = unconstrained_day()
    out = []
    for archetype in candidate_gen.ARCHETYPE_SPECS:
        taken = 0
        day = replace(base, number=day_n,
                      forced_includes={0: archetype},
                      archetype_mix={**base.archetype_mix, archetype: 1})
        for seed in range(60):
            if taken >= per_archetype:
                break
            c = candidate_gen.generate(seed, day, 0)
            if any(d.kind == kind for d in c.truth.discrepancies):
                out.append((c, day))
                taken += 1
    return out


def test_breach_lists_are_alphabetized():
    """Sorted lists are the difference between scanning and reading (#61).

    Also better camouflage than the old random insert index: the candidate's
    address sorts into place, so it can never sit at a position noise doesn't
    occupy.
    """
    from gameengine.core import tools_bridge
    base = unconstrained_day()
    c = candidate_gen.generate(7, base, 0)
    lists = tools_bridge.get_breach_lists(c, _BREACH_TEST_SEED, 20)
    assert lists, "no databases returned on the last unlock day"
    for name, _year, _count, entries in lists:
        addrs = [e for e, _m in entries]
        assert addrs == sorted(addrs), f"{name} is not alphabetized"
        assert len(addrs) == len(set(addrs)), f"{name} lists a duplicate address"


def test_breach_lists_are_identical_for_every_candidate():
    """The corpora are reference material, not per-candidate noise (#61).

    Before this the RNG was seeded on candidate.id, so all six databases were
    regenerated for every candidate — a player who memorised a list learned
    nothing, because the list was gone by the next candidate. Deliberately
    compares the NOISE rows: the only permitted difference between two
    candidates' views is each one's own seeded address.
    """
    from gameengine.core import tools_bridge
    base = unconstrained_day()
    noise = None
    for seed in range(6):
        c = candidate_gen.generate(seed, base, 0)
        lists = tools_bridge.get_breach_lists(c, _BREACH_TEST_SEED, 20)
        this = {name: tuple(e for e, m in entries if not m)
                for name, _y, _c, entries in lists}
        if noise is None:
            noise = this
        assert this == noise, (
            "two candidates see different breach-database contents — the "
            "databases are supposed to be fixed for the whole campaign")
    # ...and a different playthrough must still differ, or the lists are
    # hard-coded rather than seeded.
    c = candidate_gen.generate(0, base, 0)
    other = {name: tuple(e for e, m in entries if not m) for name, _y, _c, entries
             in tools_bridge.get_breach_lists(c, _BREACH_TEST_SEED + 1, 20)}
    assert other != noise, "breach lists do not vary between playthroughs"


def test_breach_panel_shows_only_unlocked_databases():
    """Difficulty comes from ADDING corpora, and none is ever removed (#61)."""
    from gameengine.core import tools_bridge
    base = unconstrained_day()
    c = candidate_gen.generate(3, base, 0)
    seen_before: set[str] = set()
    for day_n in range(1, config.CAMPAIGN_LAST_DAY + 1):
        shown = {n for n, _y, _c, _e in
                 tools_bridge.get_breach_lists(c, _BREACH_TEST_SEED, day_n)}
        expected = set(config.breach_dbs_unlocked_by(day_n))
        assert shown == expected, (
            f"day {day_n}: panel shows {sorted(shown)}, config says "
            f"{sorted(expected)} — the panel and the generator would disagree "
            f"about which corpora exist")
        assert seen_before <= shown, (
            f"day {day_n}: {sorted(seen_before - shown)} disappeared — a "
            f"database that is added must never be removed")
        seen_before = shown
    assert len(seen_before) == len(config.BREACH_DB_UNLOCK_DAY), (
        "not every database unlocks within the campaign")


def test_cross_breach_reuse_candidates_appear_in_the_breach_lists():
    """Hashcrack must not name a corpus the player's email is absent from (#61).

    Measured at 98 of 119 carriers (82%) before the fix: get_breach_lists()
    seeded on BREACH_HIT or LEAKED_PASSWORD only, while the Hashcrack log
    emitted BREACH_MATCH rows for reuse as well. The tool asserted the email
    was in two corpora and the page that would corroborate it showed nothing.
    """
    from gameengine.core import tools_bridge
    pairs = _breach_carriers(DiscrepancyKind.CROSS_BREACH_REUSE, day_n=7)
    assert pairs, "no CROSS_BREACH_REUSE carriers on day 7 — guard is inert"
    for c, day in pairs:
        lists = tools_bridge.get_breach_lists(c, _BREACH_TEST_SEED, day.number)
        hits = [n for n, _y, _cl, entries in lists if any(m for _e, m in entries)]
        assert len(hits) >= 2, (
            f"{c.archetype.value} carries CROSS_BREACH_REUSE but their email "
            f"appears in {len(hits)} corpora ({hits}) — 'reuse' means the "
            f"password recurs across MULTIPLE corpora, so one is not enough")


def test_ghostscan_and_hashcrack_name_the_same_breach_corpora():
    """The two pages must agree about where the candidate is leaked (#61).

    This is the actual mechanism the issue is about: _breach_db_for_candidate
    is shared precisely so the panel and the log cannot diverge, and the
    second corpus for reuse used to bypass it entirely with its own
    `(int(id,16) >> 8) % len(...)` pick.
    """
    import random as _r

    from gameengine.core import tools_bridge
    checked = 0
    for kind in (DiscrepancyKind.LEAKED_PASSWORD,
                 DiscrepancyKind.CROSS_BREACH_REUSE):
        for day_n in (3, 5, 8, 12, 16):
            for c, day in _breach_carriers(kind, day_n, per_archetype=2):
                checked += 1
                panel = sorted(
                    n for n, _y, _cl, entries in
                    tools_bridge.get_breach_lists(c, _BREACH_TEST_SEED, day.number)
                    if any(m for _e, m in entries))
                log = sorted({e.detail for e in tools_bridge._hc_candidate_entries(
                    c, _r.Random(1), day.number) if e.event == "BREACH_MATCH"})
                assert panel == log, (
                    f"day {day_n} {c.archetype.value}: Ghostscan panel seeds "
                    f"{panel}, Hashcrack log names {log}")
    assert checked, "guard is inert"


def _find_breach_carrier(day_n, candidate_count=8, slot=0):
    """(archetype, seed, day, candidate, kinds) — a candidate at `slot` on a
    `candidate_count`-slot day, carrying a Hashcrack-observable breach kind.
    Mirrors _breach_carriers()'s search strategy, but on a specific slot of a
    specific-sized day (needed to test the panel with several candidates
    present at once, per the batch-3 follow-up below)."""
    from dataclasses import replace
    base = unconstrained_day()
    bkinds = {DiscrepancyKind.BREACH_HIT, DiscrepancyKind.LEAKED_PASSWORD,
              DiscrepancyKind.CROSS_BREACH_REUSE}
    for archetype in candidate_gen.ARCHETYPE_SPECS:
        day = replace(base, number=day_n, candidate_count=candidate_count,
                      forced_includes={slot: archetype},
                      archetype_mix={**base.archetype_mix, archetype: 1})
        for seed in range(60):
            c = candidate_gen.generate(seed, day, slot)
            kinds = {d.kind for d in c.truth.discrepancies} & bkinds
            if kinds:
                return archetype, seed, day, c, kinds
    return None


def test_breach_lists_for_day_include_every_slots_carrier():
    """Batch-3 follow-up (Nick, playtest): get_breach_lists_for_day() must
    seed EVERY candidate the day will ever produce, not just slot 0 — this is
    the actual fix for "planted in the list in the middle of the round," so
    it has to be proven for a carrier who isn't the first candidate either."""
    from gameengine.core import tools_bridge

    found = _find_breach_carrier(day_n=7, candidate_count=8, slot=5)
    assert found, "no breach carrier found at slot 5 — guard is inert"
    _archetype, seed, day, c, kinds = found

    lists = tools_bridge.get_breach_lists_for_day(seed, day)
    all_emails = {e for _n, _y, _cl, emails in lists for e in emails}
    assert c.email in all_emails, (
        f"slot-5 carrier ({kinds}) is missing from the day-wide breach "
        f"lists — the fix must not only cover slot 0")


def test_breach_list_panel_shows_a_carrier_before_their_turn():
    """The actual regression: BreachListPanel used to call get_breach_lists()
    fresh per candidate and discard everything else, so a real carrier's
    email only existed in the panel while THEIR OWN dossier was open. Load a
    DIFFERENT, non-carrying candidate and confirm the carrier's email is
    still sitting in the panel, unmarked (is_match False — it isn't the
    candidate currently under investigation, just genuinely present)."""
    import asyncio

    from textual.app import App, ComposeResult

    from gameengine.ui.tui.app import BreachListPanel

    found = _find_breach_carrier(day_n=7, candidate_count=8, slot=0)
    assert found, "no breach carrier found at slot 0 — guard is inert"
    _archetype, seed, day, carrier, kinds = found
    other = candidate_gen.generate(seed, day, 1)
    assert other.email != carrier.email

    class _Host(App):
        def compose(self) -> ComposeResult:
            yield BreachListPanel()

    async def go():
        app = _Host()
        async with app.run_test() as pilot:
            panel = app.query_one(BreachListPanel)
            panel.load_candidate(other, seed, day)   # NOT the carrier's turn
            await pilot.pause(0.05)
            by_email = {email: is_match
                       for _n, _y, _cl, entries in panel._lists
                       for email, is_match in entries}
            assert carrier.email in by_email, (
                f"carrier ({kinds}) is absent from the panel while a "
                f"different, unrelated candidate is loaded — still being "
                f"planted only on their own turn")
            assert by_email[carrier.email] is False, (
                "the carrier's row is flagged is_match while someone else's "
                "dossier is open — that would leak/misattribute the hit to "
                "the wrong candidate's turn")
            # `other` need not carry a breach kind at all (most candidates
            # don't) — but IF their email happens to land in a corpus too,
            # it must be the one flagged is_match, never the carrier's.
            if other.email in by_email:
                assert by_email[other.email] is True, (
                    "the currently-loaded candidate's own row should be the "
                    "one flagged is_match")
    asyncio.run(go())


def test_breach_list_idle_state_does_not_color_code_the_real_match():
    """Nick's playtest report: the real match's idle-state row rendered at a
    visibly lighter shade (#6b7785) than a noise row (#4a5568) — identifiable
    without running a scan or buying the upgrade. Idle rendering of a real
    match and a noise row must be byte-for-byte identical apart from the
    email text itself."""
    import asyncio

    from textual.app import App, ComposeResult

    from gameengine.ui.tui.app import BreachListPanel

    found = _find_breach_carrier(day_n=7, candidate_count=4, slot=0)
    assert found, "no breach carrier found — guard is inert"
    _archetype, seed, day, carrier, _kinds = found

    class _Host(App):
        def compose(self) -> ComposeResult:
            yield BreachListPanel()

    async def go():
        app = _Host()
        async with app.run_test() as pilot:
            panel = app.query_one(BreachListPanel)
            panel.load_candidate(carrier, seed, day)   # it IS their turn, but idle
            await pilot.pause(0.05)
            assert panel._scan_state == BreachListPanel._STATE_IDLE
            # Read what _rebuild_content ACTUALLY handed to the Static widget
            # (name-mangled private attr set by Static.update) rather than
            # reconstructing the expected string ourselves — this has to
            # catch a regression in app.py, not just restate the fix.
            rendered = panel._content._Static__content
            assert isinstance(rendered, str)
            lines = rendered.split("\n")

            match_email = next(e for _n, _y, _cl, entries in panel._lists
                               for e, m in entries if m)
            noise_email = next(e for _n, _y, _cl, entries in panel._lists
                               for e, m in entries if not m)
            match_line = next(l for l in lines if match_email in l)
            noise_line = next(l for l in lines if noise_email in l)
            match_color = match_line.split(match_email)[0]
            noise_color = noise_line.split(noise_email)[0]
            assert match_color == noise_color, (
                f"real match renders as {match_color!r} but a noise row "
                f"renders as {noise_color!r} — any difference is exactly "
                f"the 'slightly lighter' leak Nick reported")
    asyncio.run(go())


def test_cross_breach_reuse_is_not_plantable_below_two_databases(monkeypatch):
    """A violation about MULTIPLE corpora needs multiple corpora to exist (#61).

    Not the same question as the evidence-tier gate. intro_day asks whether the
    player has been given Hashcrack; this asks whether the world contains a
    second breach database for the password to recur in.

    **The schedule is monkeypatched, and that is the point of the test.** Under
    the shipped table the second corpus unlocks on day 3, which is also
    Hashcrack's unlock day — so the tier gate happens to block reuse on exactly
    the days this constraint would, and the guard passes whether or not the
    constraint exists at all. Verified: deleting _kind_is_expressible_on from
    the eligibility filter left the first draft of this test green. Pushing the
    later unlocks past the tool's day is what separates the two mechanisms and
    makes the assertion mean something.
    """
    from dataclasses import replace

    delayed = dict(config.BREACH_DB_UNLOCK_DAY)
    for name, intro in sorted(delayed.items(), key=lambda kv: (kv[1], kv[0]))[1:]:
        delayed[name] = max(intro, 9)
    monkeypatch.setattr(config, "BREACH_DB_UNLOCK_DAY", delayed)

    base = unconstrained_day()
    tested_past_the_tier_gate = False
    for day_n in range(1, config.CAMPAIGN_LAST_DAY + 1):
        if len(config.breach_dbs_unlocked_by(day_n)) >= config.MIN_BREACH_DBS_FOR_REUSE:
            continue
        if day_n >= intro_day(DiscrepancyKind.CROSS_BREACH_REUSE):
            tested_past_the_tier_gate = True
        for archetype in candidate_gen.ARCHETYPE_SPECS:
            day = replace(base, number=day_n,
                          forced_includes={0: archetype},
                          archetype_mix={**base.archetype_mix, archetype: 1})
            for seed in range(60):
                c = candidate_gen.generate(seed, day, 0)
                assert not any(d.kind == DiscrepancyKind.CROSS_BREACH_REUSE
                               for d in c.truth.discrepancies), (
                    f"day {day_n} has "
                    f"{len(config.breach_dbs_unlocked_by(day_n))} database(s) "
                    f"but {archetype.value} seed {seed} carries "
                    f"CROSS_BREACH_REUSE — there is no second corpus for the "
                    f"password to recur in, so it is unobservable")
    assert tested_past_the_tier_gate, (
        "every single-database day was also before Hashcrack's unlock day, so "
        "this ran entirely inside the tier gate's shadow and proved nothing")


def test_breach_db_tables_do_not_drift():
    """config and tools_bridge must name the same corpora (#61, #57's lesson).

    Named explicitly rather than derived from either table: a guard written as
    `set(A) == set(A)` cannot fail. tools_bridge also asserts this at import;
    this is the version that says WHY when it breaks.
    """
    from gameengine.core import tools_bridge
    assert sorted(config.BREACH_DB_UNLOCK_DAY) == sorted(
        db[0] for db in tools_bridge._BREACH_DATABASES), (
        "config.BREACH_DB_UNLOCK_DAY and tools_bridge._BREACH_DATABASES have "
        "drifted — a candidate can be planted into a corpus the panel never "
        "renders, which is exactly how #57 happened")


# ─── Issues #15 / #43-47 / #48 / #49 — tutorial content machinery ───────────
#
# The failure mode these guard against is specific and nasty: scripted content
# that silently stops working. A day file that asks for a violation the day
# cannot express does not crash — the generator just drops it, the shift still
# plays, and the day that exists to TEACH a mechanic quietly stops containing
# an example of it. Nobody notices until a playtester says the tutorial felt
# thin.

TUTORIAL_DAYS = tuple(range(1, config.TUTORIAL_LAST_DAY + 1))


def test_every_tutorial_day_actually_contains_its_scripted_violations():
    """A scripted violation must land in the candidate, on every seed (#43-47).

    Checked across seeds rather than on one, because everything that could drop
    a forced kind is seed-dependent: the archetype's severity budget, the
    single-artifact exclusivity groups, and #56's trusted-organisation bypass
    (which refuses to fake an affiliation on a candidate who claimed an elite
    org — so a scripted AFFILIATION_MISMATCH on the wrong archetype would land
    on most seeds and vanish on others).
    """
    for day_n in TUTORIAL_DAYS:
        day = load_day(day_n)
        assert day.forced_violations, (
            f"day {day_n} is a tutorial day but scripts no violations — it "
            f"cannot demonstrate the mechanic it introduces")
        for slot, kinds in day.forced_violations.items():
            for seed in range(25):
                got = {d.kind for d in candidate_gen.generate(seed, day, slot)
                       .truth.discrepancies}
                missing = sorted(k.name for k in kinds if k not in got)
                assert not missing, (
                    f"day {day_n} slot {slot} seed {seed}: scripted "
                    f"{missing} did not land. The day still plays and still "
                    f"scores — it just no longer teaches what it exists to "
                    f"teach.")


def test_every_tutorial_day_has_a_clean_admit_and_a_clear_deny():
    """#15's core AC: one of each, per day, so the contrast is teachable."""
    for day_n in TUTORIAL_DAYS:
        day = load_day(day_n)
        for seed in range(10):
            cands = [candidate_gen.generate(seed, day, i)
                     for i in range(day.candidate_count)]
            clean = [c for c in cands if not c.truth.discrepancies]
            dirty = [c for c in cands if c.truth.discrepancies]
            assert clean, (f"day {day_n} seed {seed}: no candidate is clean — "
                           f"the player never sees what a correct admit "
                           f"looks like")
            assert dirty, f"day {day_n} seed {seed}: no candidate is deniable"


def test_tutorial_days_never_plant_a_violation_their_tools_cannot_reveal():
    """The teaching order in #15 and config.TOOL_UNLOCK_DAY must agree.

    The Sneaky Bugger on the original day_01.json is the case this exists for:
    every kind it is eligible for is tool-revealed, no tool is unlocked on day
    1, so it generated carrying NOTHING while still scoring as a DENY.
    """
    for day_n in TUTORIAL_DAYS:
        day = load_day(day_n)
        for slot in range(day.candidate_count):
            for seed in range(25):
                c = candidate_gen.generate(seed, day, slot)
                for d in c.truth.discrepancies:
                    assert intro_day(d.kind) <= day_n, (
                        f"day {day_n} slot {slot} seed {seed} carries "
                        f"{d.kind.name}, revealed by a tool not taught until "
                        f"day {intro_day(d.kind)}")
                if candidate_gen.ARCHETYPE_SPECS[c.archetype].correct_verdict \
                        is Verdict.DENY:
                    assert c.truth.discrepancies, (
                        f"day {day_n} slot {slot} seed {seed}: "
                        f"{c.archetype.value} scores as a DENY but carries no "
                        f"violation at all — unflaggable by construction")


def test_no_day_opens_or_closes_on_a_blank_overseer():
    """Days 2-20 opened on an empty panel and closed on the literal '...' (#15).

    synthesize_day assigns narrative keys that are allowed not to exist, which
    was fine; what was missing was any second layer for them to fall through
    to. Covers the whole campaign, not just the authored days — the generic
    copy is exactly what days 6-20 rely on.
    """
    from gameengine.core import content_loader
    from gameengine.core.models import Performance
    narratives = content_loader.load_narratives()
    for day_n in range(1, config.CAMPAIGN_LAST_DAY + 1):
        day = load_day(day_n)
        intro = content_loader.resolve_narrative(
            narratives, day.overseer_intro_key, "generic_intro")
        assert intro.strip(), f"day {day_n} opens on an empty Overseer panel"
        for perf in Performance:
            outro = content_loader.resolve_narrative(
                narratives, day.overseer_outro_keys[perf],
                content_loader.generic_outro_key(perf))
            assert outro.strip() and outro.strip() != "...", (
                f"day {day_n} {perf.value} closes on {outro!r}")
        between = content_loader.resolve_narrative(
            narratives, f"day{day_n}_between", "generic_between")
        assert between.strip(), f"day {day_n} has no between-day beat"


def test_every_tutorial_day_introduces_its_tool_and_narrates_it():
    """Each of days 1-5 introduces exactly one page, in the order #15 sets."""
    expected = {2: "ghostscan", 3: "hashcrack", 4: "logwatch", 5: "stegotool"}
    for day_n in TUTORIAL_DAYS:
        assert config.tool_introduced_on(day_n) == expected.get(day_n), (
            f"day {day_n} introduces {config.tool_introduced_on(day_n)!r}, "
            f"teaching order says {expected.get(day_n)!r}")


def test_authored_days_inherit_the_rulebook_from_day_one():
    """An authored day omitting `rules` gets day 1's, with today's flips (#15).

    The alternative — restating 27 rules in every day file — is five places for
    the rulebook to drift, and the drift would be invisible: the day would
    simply score against a slightly different book than the one the player was
    shown yesterday.
    """
    from gameengine.core.content_loader import mutate_variable_rules
    day1 = load_day(1)
    for day_n in range(2, config.TUTORIAL_LAST_DAY + 1):
        day = load_day(day_n)
        assert {r.id for r in day.rules} == {r.id for r in day1.rules}, (
            f"day {day_n}'s rulebook has drifted from day 1's")
        assert day.rules == mutate_variable_rules(day1.rules, day_n), (
            f"day {day_n}'s inherited rules do not match the flips #36 would "
            f"announce in the briefing")


def test_forced_violations_are_validated_when_the_day_loads(tmp_path, monkeypatch):
    """A script asking for an unteachable violation must fail LOUDLY (#15).

    Validated in content_loader rather than the generator, because this is the
    only place the error can name the file the author has open. Dropped
    silently — which is what the generator does — the day still plays and
    simply teaches nothing.
    """
    import json
    base = json.loads(
        (config.DAYS_DIR / "day_01.json").read_text(encoding="utf-8"))

    def write(**overrides):
        raw = {**base, **overrides}
        (tmp_path / "day_01.json").write_text(json.dumps(raw), encoding="utf-8")
        monkeypatch.setattr(config, "DAYS_DIR", tmp_path)

    # A stegotool violation on day 1 — the tool is four days away.
    write(forced_violations={"0": ["covert_c2_channel"]})
    with pytest.raises(ValueError, match="not taught until day 5"):
        load_day(1)

    # A slot the day doesn't have.
    write(forced_violations={"99": ["hostile_chat"]})
    with pytest.raises(ValueError, match="only has 6 slots"):
        load_day(1)

    # A kind the day's own whitelist excludes — the two would contradict.
    write(allowed_violations=["hostile_chat"],
          forced_violations={"0": ["disposable_email"]})
    with pytest.raises(ValueError, match="allowed_violations"):
        load_day(1)


def test_rule_sheet_round_trips_and_renders(tmp_path, monkeypatch):
    """#49: the authored approved/denied block reaches the Reference panel."""
    from gameengine.ui.tui import rules_content

    for day_n in TUTORIAL_DAYS:
        day = load_day(day_n)
        assert day.rule_sheet is not None, (
            f"day {day_n} has no authored rule sheet — #49 requires one per "
            f"authored day")
        dossier = rules_content.build_dossier_text(day)
        rules   = rules_content.build_rules_text(day)
        for line in (day.rule_sheet.approved_domains
                     + day.rule_sheet.denied_domains
                     + day.rule_sheet.approved_affiliations
                     + day.rule_sheet.denied_affiliations):
            assert line in dossier, (
                f"day {day_n}: rule-sheet entry {line!r} is authored but never "
                f"rendered — #49 says the panel shows it VERBATIM")
        assert day.rule_sheet.summary in rules
        for note in day.rule_sheet.notes:
            assert note in rules

    # A synthesized day authors nothing and must render exactly as before #49.
    synth = load_day(config.TUTORIAL_LAST_DAY + 1)
    assert synth.rule_sheet is None
    assert "today's rule sheet" not in rules_content.build_dossier_text(synth)


def test_unknown_rule_sheet_key_fails_loudly(tmp_path, monkeypatch):
    """A typo'd key must not silently mean 'authored nothing' (#49)."""
    import json
    base = json.loads(
        (config.DAYS_DIR / "day_01.json").read_text(encoding="utf-8"))
    base["rule_sheet"] = {"aproved": {"domains": ["gmail.com"]}}
    (tmp_path / "day_01.json").write_text(json.dumps(base), encoding="utf-8")
    monkeypatch.setattr(config, "DAYS_DIR", tmp_path)
    with pytest.raises(ValueError, match="Unknown rule_sheet key"):
        load_day(1)


# ─── Issue #48 — word banks are single-sourced ─────────────────────────────


def test_domain_word_banks_are_derived_not_copied():
    """tools_bridge must not keep its own copies of the domain banks (#48/#57)."""
    from gameengine.core import tools_bridge
    assert tools_bridge._GS_TRUSTED_DOMAINS == frozenset(
        candidate_gen.DOMAINS_TRUSTED)
    assert tools_bridge._GS_PRIVACY_DOMAINS == frozenset(
        candidate_gen.DOMAINS_PRIVACY)
    assert tools_bridge._GS_SUSPICIOUS_DOMAINS == frozenset(
        candidate_gen.DOMAINS_DISPOSABLE)
    assert tools_bridge._GS_LEGIT_ORGS == frozenset(
        candidate_gen.AFFILIATIONS_LEGIT)


def test_every_domain_the_generator_produces_is_classified():
    """No generated address may read as 'unknown domain' (#48).

    fastmail.io was exactly this: in _make_email's fallback pool, in none of
    the classification sets, so an ordinary candidate could be handed
    "unknown domain — verify affiliation" for having a perfectly normal
    mailbox. The generator's own pools are the authority for what the banks
    have to cover — the same direction of derivation #57 established.
    """
    from gameengine.core import tools_bridge
    known = (set(candidate_gen.DOMAINS_TRUSTED)
             | set(candidate_gen.DOMAINS_PRIVACY)
             | set(candidate_gen.DOMAINS_DISPOSABLE))
    # The consumer fallback pool inside _make_email, which is what a candidate
    # with no institutional affiliation gets.
    consumer = {"yahoo.com", "gmail.com", "fastmail.io", "protonmail.com"}
    missing = sorted(consumer - known)
    assert not missing, (
        f"_make_email can produce {missing}, which no word bank classifies — "
        f"the sweep will call it an unknown domain")
    assert tools_bridge._GS_TRUSTED_DOMAINS & tools_bridge._GS_PRIVACY_DOMAINS == frozenset(), \
        "a domain cannot be both trusted-consumer and privacy — the identity " \
        "block picks one branch and the other read is lost"


def test_affiliations_faked_excludes_the_untouchable_elite_orgs():
    """#48 + #56: an elite org can never be the CLAIMED side of a fake."""
    overlap = set(candidate_gen.AFFILIATIONS_FAKED) & set(
        candidate_gen.AFFILIATIONS_ELITE)
    assert not overlap, (
        f"{sorted(overlap)} is in both banks — #56 guarantees a claimed elite "
        f"organisation always confirms in the sweep, which is the player's "
        f"whole reward for recognising one")


def test_logwatch_noise_pool_includes_many_external_cities():
    """Batch-3 task #5: more locations for noise to hide violations in.
    Before this, only a violation (or the candidate's own foreign login)
    ever carried an exotic city tag, so any foreign city in the log was
    itself the tell. Assert the location pool actually grew, and that noise
    generation can draw a foreign city for an unrelated account.
    """
    from gameengine.core import tools_bridge

    assert len(tools_bridge._LW_CITIES) >= 12, (
        "batch-3 task #5 should add more locations, not just reuse the "
        "original 8-city pool")
    # every prefix must resolve through _lw_city (i.e. is present in the map)
    for prefix, city in tools_bridge._LW_CITIES:
        assert tools_bridge._LW_CITY_MAP.get(prefix) == city

    import random as _random
    saw_external_noise_city = False
    for seed in range(200):
        entries = tools_bridge._lw_noise_entries(_random.Random(seed), 30)
        for e in entries:
            if e.owner_id is None and e.event == "AUTH_OK" and e.city:
                saw_external_noise_city = True
                break
        if saw_external_noise_city:
            break
    assert saw_external_noise_city, (
        "with LW_NOISE_EXTERNAL_CITY_FRACTION > 0, some noise AUTH_OK rows "
        "should carry a foreign city tag like violations do")


def test_logwatch_noise_external_city_fraction_is_configurable():
    """The external-city noise rate is a config knob (task #7), and turning
    it to zero must stop noise rows from ever carrying a foreign city —
    proving the knob actually drives the behaviour, not just documents it.
    """
    from gameengine import config as _cfg
    from gameengine.core import tools_bridge

    original = _cfg.LW_NOISE_EXTERNAL_CITY_FRACTION
    try:
        _cfg.LW_NOISE_EXTERNAL_CITY_FRACTION = 0.0
        import random as _random
        for seed in range(50):
            entries = tools_bridge._lw_noise_entries(_random.Random(seed), 40)
            for e in entries:
                assert not (e.owner_id is None and e.event == "AUTH_OK" and e.city), (
                    "LW_NOISE_EXTERNAL_CITY_FRACTION = 0.0 should suppress "
                    "all foreign-city noise logins")
    finally:
        _cfg.LW_NOISE_EXTERNAL_CITY_FRACTION = original


def test_logwatch_brute_force_burst_size_is_configurable():
    """Batch-3 task #7: burst size for BRUTE_FORCE_IN_LOG was a bare literal
    (rng.randint(4, 7)) inside _lw_candidate_entries; pulled into
    config.LW_BRUTE_BURST_SIZE. Prove the knob actually drives generation,
    not just documents a number nothing reads."""
    import random as _random

    from gameengine.core import tools_bridge

    day = load_day(20)
    cand = None
    for seed in range(200):
        c = candidate_gen.generate(seed, day, 0)
        if DiscrepancyKind.BRUTE_FORCE_IN_LOG in {d.kind for d in c.truth.discrepancies}:
            cand = c
            break
    assert cand is not None, "no brute-force candidate in 200 seeds"

    def _burst_len(seed):
        entries = tools_bridge._lw_candidate_entries(cand, _random.Random(seed))
        return sum(1 for e in entries if e.violation_kind == "brute_force"
                   and e.event == "AUTH_FAIL")

    original = config.LW_BRUTE_BURST_SIZE
    try:
        config.LW_BRUTE_BURST_SIZE = (20, 20)
        assert _burst_len(1) == 20, "LW_BRUTE_BURST_SIZE did not drive the burst count"
    finally:
        config.LW_BRUTE_BURST_SIZE = original


def test_hashcrack_stuffing_burst_size_is_configurable():
    """Same shape as above, for Hashcrack's HC_STUFFING_BURST_SIZE."""
    import random as _random

    from gameengine.core import tools_bridge

    day = load_day(20)
    cand = None
    for seed in range(200):
        c = candidate_gen.generate(seed, day, 0)
        if DiscrepancyKind.CREDENTIAL_STUFFING in {d.kind for d in c.truth.discrepancies}:
            cand = c
            break
    assert cand is not None, "no credential-stuffing candidate in 200 seeds"

    def _burst_len(seed):
        entries = tools_bridge._hc_candidate_entries(cand, _random.Random(seed), day.number)
        return sum(1 for e in entries if e.violation_kind == "stuffing"
                   and e.event == "AUTH_FAIL")

    original = config.HC_STUFFING_BURST_SIZE
    try:
        config.HC_STUFFING_BURST_SIZE = (15, 15)
        assert _burst_len(1) == 15, "HC_STUFFING_BURST_SIZE did not drive the burst count"
    finally:
        config.HC_STUFFING_BURST_SIZE = original


def test_log_generation_timing_knobs_are_all_present_and_well_formed():
    """Completeness/shape guard for the batch-3 task #7 config extraction —
    every (min, max) pair is a real 2-tuple with min <= max, and every event-
    weight list is non-empty. Cheap insurance against a typo'd knob (e.g. a
    single int where a tuple was expected) blowing up randint() at runtime."""
    # (min, max) pairs fed straight to rng.randint(*pair) — min must not
    # exceed max or randint blows up at runtime.
    range_knobs = [
        "LW_WORKDAY_WINDOW", "LW_NORMAL_LOGIN_COUNT", "LW_NORMAL_LOGIN_GAP",
        "LW_CLEAN_ACTIVITY_COUNT", "LW_CLEAN_ACTIVITY_GAP", "LW_BRUTE_BURST_SIZE",
        "LW_BRUTE_COOLDOWN", "LW_STUFFING_COOLDOWN", "LW_TRAVEL_GAP",
        "LW_TRAVEL_COOLDOWN", "LW_INSIDER_STEP1_GAP",
        "LW_INSIDER_STEP2_GAP", "LW_AFTERHOURS_GAP",
        "LW_SLOW_FIRST_TS", "LW_SLOW_BURST_SIZE", "LW_SLOW_GAP",
        "LW_NOISE_TIME_WINDOW", "HC_WORKDAY_WINDOW", "HC_NORMAL_LOGIN_GAP",
        "HC_HASH_SUBMIT_GAP", "HC_BREACH_ROW_GAP", "HC_STUFFING_BURST_SIZE",
        "HC_STUFFING_COOLDOWN", "HC_STUFFING_POST_GAP", "HC_NOISE_TIME_WINDOW",
    ]
    for name in range_knobs:
        val = getattr(config, name)
        assert isinstance(val, tuple) and len(val) == 2, f"{name} is not a 2-tuple: {val!r}"
        lo, hi = val
        assert lo <= hi, f"{name} has min > max: {val!r}"

    # (window-start, span) pairs — start + rng.randint(0, span) — different
    # shape (start can legitimately exceed span), so checked separately.
    window_knobs = ["LW_INSIDER_WINDOW", "LW_AFTERHOURS_WINDOW"]
    for name in window_knobs:
        val = getattr(config, name)
        assert isinstance(val, tuple) and len(val) == 2, f"{name} is not a 2-tuple: {val!r}"
        start, span = val
        assert 0 <= start <= 86400 and span >= 0, f"{name} has an invalid window: {val!r}"

    weight_knobs = ["LW_NOISE_EVENT_WEIGHTS", "HC_NOISE_EVENT_WEIGHTS",
                    "LW_CLEAN_ACTIVITY_EVENTS"]
    for name in weight_knobs:
        val = getattr(config, name)
        assert isinstance(val, list) and val, f"{name} is empty or not a list: {val!r}"
