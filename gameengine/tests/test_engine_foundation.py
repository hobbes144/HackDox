"""Foundation tests — prove the engine wiring is sound.

These don't aim for full coverage; they pin down the contracts the rest
of the engine depends on. Full archetype × verdict coverage lands with
the Textual UI in task #7.
"""

from __future__ import annotations

import itertools

import pytest

from gameengine import config
from gameengine.core import (
    candidate_gen,
    persistence,
    rules_engine,
    scoring,
    tools_bridge,
)
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

    2026-09-19 — ONE deliberate exception, at Nick's request: the carrier-
    shape rule `rule_signal_relay_payload` (SIGNAL_COMMS_PAYLOAD, major) is
    overseer_variable and starts disqualifying, so the shape axis has a rule
    that visibly swings in the briefing. It is the only disqualifying-by-
    default variable rule, and it is named here explicitly so a second one
    cannot slip in unnoticed.
    """
    assert day1.rules, "Day 1 should have rules"
    variable = {r.id for r in day1.rules if r.mutability == "overseer_variable"}
    assert variable == {"rule_claimed_ip", "rule_weak_credential",
                        "rule_weak_encryption", "rule_signal_relay_payload"}
    for rule in day1.rules:
        if rule.id not in variable:
            assert rule.mutability == "fixed", rule.id
        elif rule.id == "rule_signal_relay_payload":
            assert rule.severity == "disqualifying", rule.id
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
    than in plain sight on the dossier.

    HOSTILE_CHAT is excluded from the count (2026-09-15, #77). It is tiered
    DOSSIER but it is NOT free evidence: its ⚠ marker is gated behind the
    20 HD$ Sentiment Scanner, so it already sits behind the economy this lever
    is about, and the sort now exempts it. Counting it as dossier-tier here
    would measure the opposite of what the lever means.

    That exemption is not cosmetic — HOSTILE_CHAT is the only dossier-tier kind
    in Bad Actor's eligible set, so sorting it last starved it to 0 of 3,200
    hard-band Bad Actors while 3,200 of 3,200 still talked hostile. Widened to
    measure the whole hard band rather than its first day, so a single day's
    authored mix cannot flip the assertion.
    """
    from gameengine.core.models import ToolName

    def tool_share(day_numbers) -> float:
        dossier = tool = 0
        for day_number in day_numbers:
            day = load_day(day_number)
            for i in range(day.candidate_count):
                for d in candidate_gen.generate(SEED, day, i).truth.discrepancies:
                    if d.kind is DiscrepancyKind.HOSTILE_CHAT:
                        continue          # paid evidence, see the docstring
                    if d.revealed_by == ToolName.DOSSIER:
                        dossier += 1
                    else:
                        tool += 1
        return tool / max(1, tool + dossier)

    hard_days = [d for d in range(1, config.CAMPAIGN_LAST_DAY + 1)
                 if config.difficulty_band_for_day(d) == "hard"]
    assert hard_days, "no hard-band day in the campaign"
    assert load_day(hard_days[0]).difficulty_band == "hard"
    easy_days = [d for d in range(1, config.CAMPAIGN_LAST_DAY + 1)
                 if config.difficulty_band_for_day(d) != "hard"]
    assert tool_share(hard_days) > tool_share(easy_days)


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
        elif rule.predicate.split(":", 1)[-1] in {
                k.value for k in candidate_gen._SEVERITY_BY_DAY}:
            # 2026-09-19: a fixed rule on a kind with a scheduled severity
            # step follows the step (content_loader.apply_severity_steps) —
            # both values, and on exactly the days severity_for says.
            kind = DiscrepancyKind(rule.predicate.split(":", 1)[1])
            for d in range(1, config.CAMPAIGN_LAST_DAY + 1):
                got = {r.severity for r in mutate_variable_rules(day1.rules, d)
                       if r.id == rule.id}
                assert got == {candidate_gen.stepped_rule_severity(kind, d)}, (
                    rule.id, d)
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
    # 2026-09-14: joined this tier when the cipher-block rework moved it off
    # DOSSIER (the free strength chip that used to be its evidence is gone).
    #
    # The token is the DIGEST SHAPE, not the tier name, and that is deliberate.
    # WEAK_ENCRYPTION is a violation about the algorithm, and the cipher block
    # only NAMES the algorithm for players who bought Cipher ID HUD. Asserting
    # on "WEAK — MD5" would have made this guard green while the kind was, for
    # everyone else, unflaggable — the guard would have been certifying a
    # paywall. "32 hex characters" is printed unconditionally, is a plain
    # observation about the artifact, and is exactly what the rules page
    # teaches the player to match against.
    DiscrepancyKind.WEAK_ENCRYPTION:       "32 hex characters",
    # ── Logwatch ─────────────────────────────────────────────────────────
    DiscrepancyKind.BRUTE_FORCE_IN_LOG:    "BRUTE_FORCE_IN_LOG",
    DiscrepancyKind.IMPOSSIBLE_TRAVEL:     "IMPOSSIBLE_TRAVEL",
    DiscrepancyKind.INSIDER_BEHAVIOR:      "INSIDER_BEHAVIOR",
    DiscrepancyKind.CREDENTIAL_STUFFING:   "CREDENTIAL_STUFFING",
    DiscrepancyKind.AFTER_HOURS_ACCESS:    "AFTER_HOURS_ACCESS",
    DiscrepancyKind.LOW_AND_SLOW:          "LOW_AND_SLOW",
    # Prose annotation, not a named label — Logwatch's IP mismatch is meant to
    # read as an observation about the log, not a violation code.
    # 2026-09-19: named by the Activity Report's ▲ CONFIRMED block (filter).
    DiscrepancyKind.CLAIMED_IP_MISMATCH:   "CLAIMED_IP_MISMATCH",
    # ── Stegotool ────────────────────────────────────────────────────────
    DiscrepancyKind.STEGO_PAYLOAD_PRESENT: "STEGO_PAYLOAD_PRESENT",
    DiscrepancyKind.ENCRYPTED_PAYLOAD:     "ENCRYPTED_PAYLOAD",
    DiscrepancyKind.COVERT_C2_CHANNEL:     "COVERT_C2_CHANNEL",
    # 2026-09-19 — the carrier-shape axis. The filtered resolve block prints
    # its own ▲ label for a special glyph; the unfiltered one only describes
    # the geometry (see test_shape_is_named_only_by_the_filter).
    DiscrepancyKind.SIGNAL_COMMS_PAYLOAD:  "SIGNAL_COMMS_PAYLOAD",
    DiscrepancyKind.RECURSIVE_PAYLOAD:     "RECURSIVE_PAYLOAD",
    DiscrepancyKind.HOSTILE_PAYLOAD:       "HOSTILE_PAYLOAD",
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

    `seed` must be the seed the candidate was generated from: the Logwatch
    shared day log is built per (seed, day) and contains a block of entries for
    each candidate in that day's roster. Passing a different seed silently
    produces a log the candidate does not appear in — which reads exactly like
    a rendering bug and isn't one.

    Hashcrack has no filter tier since the cipher-block rework; its equivalent
    is the aperture minigame's end state, which cipher_full_readout() produces
    without simulating a sweep (same stance as the Stegotool branch, which
    takes stamp_signature_lines rather than stamping its way there).
    """
    from gameengine.core import tools_bridge
    from gameengine.core.models import ToolName

    tool = candidate_gen._SEVERITY_REVEAL[kind][0]
    state = GameState(seed=seed, current_day=day.number, compute_hours=10_000)
    if tool == ToolName.GHOSTSCAN:
        return "\n".join(tools_bridge.run_ghostscan_filtered_shared(
            candidate, state).raw_lines)
    if tool == ToolName.HASHCRACK:
        block = tools_bridge.build_cipher_block(candidate, day.number)
        return "\n".join(tools_bridge.cipher_full_readout(
            block, candidate, day.number,
            {config.UPGRADE_CRYPTO_ID, config.UPGRADE_HC_VERDICT}))
    if tool == ToolName.LOGWATCH:
        entries = tools_bridge.generate_day_log(seed, day)
        # 2026-09-19: the filter's output is the auth log panel AND the
        # Activity Report's ▲ CONFIRMED block.
        res = tools_bridge.run_logwatch_filtered_shared(entries, candidate, state)
        return "\n".join(res.raw_lines + res.report_lines)
    if tool == ToolName.STEGOTOOL:
        img = tools_bridge.build_stego_image(candidate, day.number)
        return "\n".join(tools_bridge.stamp_signature_lines(img, reveal_type=True))
    raise AssertionError(f"no output path for {tool}")


def _archetype_can_carry(spec, kind) -> bool:
    """Whether `spec`'s archetype can ever end up carrying `kind`.

    For a budgeted kind that is eligible_kinds membership. The carrier-shape
    kinds are free riders that are never listed there (2026-09-19): they ride
    on a stego colour kind, only for the shape-eligible archetypes. Filtering
    them by eligible_kinds alone made every shape kind's present-when-planted
    guard pytest.skip — silently inert, which is exactly how a guard stops
    guarding without anyone noticing.
    """
    if kind in candidate_gen._STEGO_SHAPE_KINDS:
        return (spec.archetype in candidate_gen._SHAPE_ELIGIBLE_ARCHETYPES
                and any(k in candidate_gen._STEGO_ARTIFACT_KINDS
                        for k in spec.eligible_kinds))
    return kind in spec.eligible_kinds


def _candidates_by_kind(kind, want: bool, limit: int = 3):
    """Up to `limit` (candidate, day, seed) triples that do / don't carry `kind`."""
    from dataclasses import replace
    base = unconstrained_day()
    found = []
    for archetype, spec in candidate_gen.ARCHETYPE_SPECS.items():
        if want and not _archetype_can_carry(spec, kind):
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
    # 2026-09-14, cipher-block rework. The Hashcrack page's credential audit
    # log was removed and its HASH_SUBMIT / BREACH_MATCH rows relocated into
    # the Logwatch day log — so Logwatch now renders rows about credentials
    # while owning no credential violation at all. That is precisely the
    # arrangement #62 was filed about, rebuilt on a different page, so both
    # Hashcrack-owned corpus kinds get policed here from the outset rather
    # than after someone finds the bug.
    #
    # The relocated rows are meant to read as observations ("this account's
    # email appears in corpus X"). If either of these phrases ever shows up in
    # Logwatch's output for a candidate that does not carry the kind, the row
    # has stopped observing and started accusing.
    DiscrepancyKind.LEAKED_PASSWORD: (
        "LEAKED_PASSWORD",
        "plaintext confirmed in breach corpus",
    ),
    DiscrepancyKind.CROSS_BREACH_REUSE: (
        "CROSS_BREACH_REUSE",
        "reused across breaches",
        "appears in more than one corpus",
    ),
    # 2026-09-19 — the carrier-shape kinds. Their purpose phrases are
    # filter-tier and must only ever print for a carrier that has the glyph:
    # a conventional carrier (the majority) naming an operation, or a non-stego
    # tool mentioning one, would be a claim with no glyph behind it.
    DiscrepancyKind.SIGNAL_COMMS_PAYLOAD: (
        "SIGNAL_COMMS_PAYLOAD",
        "signal communications",
    ),
    DiscrepancyKind.RECURSIVE_PAYLOAD: (
        "RECURSIVE_PAYLOAD",
        "recursive payload",
    ),
    DiscrepancyKind.HOSTILE_PAYLOAD: (
        "HOSTILE_PAYLOAD",
        "hostile payload",
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
    block = tools_bridge.build_cipher_block(candidate, day.number)
    return {
        "ghostscan": "\n".join(
            tools_bridge.run_ghostscan_filtered_shared(candidate, state).raw_lines),
        "hashcrack": "\n".join(
            tools_bridge.cipher_full_readout(
                block, candidate, day.number,
                {config.UPGRADE_CRYPTO_ID, config.UPGRADE_HC_VERDICT})),
        "logwatch": "\n".join(
            (lambda r: r.raw_lines + r.report_lines)(
                tools_bridge.run_logwatch_filtered_shared(
                    tools_bridge.generate_day_log(seed, day),
                    candidate, state))),
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

    Scoped to CONVENTIONAL carriers (2026-09-19). A special-shape glyph is
    made of deliberately thin strokes — a one-row bar has ~2 neighbours per
    cell by construction, and parallel stripes are dense without being blocky
    — so this block-shaped discriminator says nothing about them. Their
    structure is guarded, more strictly, by
    test_carrier_glyph_geometry_matches_the_planted_shape.
    """
    imgs = [img for img in _stego_images(limit=60)
            if img.shape is tools_bridge.StegoShape.CONVENTIONAL]
    assert len(imgs) >= 15, "too few conventional stego images — test is inert"
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


# ─── 2026-09-19 — carrier SHAPE, the second stego evidence axis ─────────────
#
# The glyph a stego carrier's cells form encodes the payload's purpose:
# conventional blocks (nothing extra), cross → SIGNAL_COMMS_PAYLOAD, enclosed
# → RECURSIVE_PAYLOAD, slash → HOSTILE_PAYLOAD. The guards below are written
# against the failure modes this project has actually shipped before:
#   • a kind planted with nothing to observe (a shape with no carrier);
#   • a free rider that quietly eats a budget slot and displaces a real kind;
#   • a tool whose rendering disagrees with ground truth;
#   • a guard parameterised on the constant it guards (so each test below
#     restates its expectations explicitly rather than reading them back out
#     of candidate_gen).

# Named explicitly — NOT read from candidate_gen — so a regression in the
# constants themselves fails here instead of redefining "correct".
_SHAPE_KIND_TO_NAME = {
    DiscrepancyKind.SIGNAL_COMMS_PAYLOAD: "cross",
    DiscrepancyKind.RECURSIVE_PAYLOAD:    "enclosed",
    DiscrepancyKind.HOSTILE_PAYLOAD:      "slash",
}
_STEGO_COLOUR_KINDS = {
    DiscrepancyKind.STEGO_PAYLOAD_PRESENT,
    DiscrepancyKind.ENCRYPTED_PAYLOAD,
    DiscrepancyKind.COVERT_C2_CHANNEL,
}
_SHAPE_ARCHETYPES = {Archetype.BAD_ACTOR, Archetype.SNEAKY_BUGGER,
                     Archetype.WHITE_HAT}


def _shape_sweep(days=range(1, 21), seeds=range(40), archetypes=None):
    """(archetype, day, seed, candidate) over an unconstrained campaign."""
    from dataclasses import replace
    base = unconstrained_day()
    for archetype in archetypes or candidate_gen.ARCHETYPE_SPECS:
        for day_n in days:
            day = replace(base, number=day_n,
                          forced_includes={0: archetype},
                          archetype_mix={**base.archetype_mix, archetype: 1})
            for seed in seeds:
                yield archetype, day_n, seed, candidate_gen.generate(seed, day, 0)


def test_shape_kinds_only_ride_on_a_stego_carrier_of_an_eligible_archetype():
    """A shape kind with no colour kind has no carrier, so no glyph: planted,
    scored, and impossible to see. Also: at most one per candidate, never
    before Stegotool is taught, never on an archetype outside Nick's three."""
    seen: dict = {k: 0 for k in _SHAPE_KIND_TO_NAME}
    for archetype, day_n, seed, c in _shape_sweep():
        kinds = {d.kind for d in c.truth.discrepancies}
        shapes = kinds & set(_SHAPE_KIND_TO_NAME)
        where = f"{archetype.value} day {day_n} seed {seed}"
        assert len(shapes) <= 1, f"{where}: two glyphs on one image {shapes}"
        if not shapes:
            continue
        (shape,) = shapes
        seen[shape] += 1
        assert kinds & _STEGO_COLOUR_KINDS, (
            f"{where}: carries {shape.name} with no stego colour kind — there "
            f"is no carrier for the glyph to be drawn in")
        assert archetype in _SHAPE_ARCHETYPES, (
            f"{where}: {archetype.value} may never draw a special shape")
        assert day_n >= config.TOOL_UNLOCK_DAY["stegotool"], (
            f"{where}: {shape.name} planted before Stegotool is taught")
        d = next(d for d in c.truth.discrepancies if d.kind is shape)
        assert d.revealed_by.value == "stegotool"
    for kind, n in seen.items():
        assert n >= 10, (
            f"sweep planted {kind.name} only {n} times — guard is inert")


def test_shape_kinds_never_consume_a_budget_slot():
    """The shape is a free rider: forcing every carrier conventional must
    leave every OTHER planted kind exactly as it was. If the shape pass ever
    moves into the budgeted path it displaces a real kind and this diverges."""
    shaped = 0
    for archetype, day_n, seed, c in _shape_sweep(
            days=range(5, 21), seeds=range(30),
            archetypes=(Archetype.SNEAKY_BUGGER, Archetype.WHITE_HAT)):
        spec = candidate_gen.ARCHETYPE_SPECS[archetype]
        rng_a = candidate_gen._seeded_rng(seed, day_n, 0, "discrepancies")
        rng_b = candidate_gen._seeded_rng(seed, day_n, 0, "discrepancies")
        args = (spec, day_n, (), unconstrained_day().difficulty_band,
                c.claimed_affiliation)
        with_shape = candidate_gen._roll_discrepancies(rng_a, *args)
        saved = config.STEGO_SHAPE_CONVENTIONAL_CHANCE
        config.STEGO_SHAPE_CONVENTIONAL_CHANCE = 1.0
        try:
            without = candidate_gen._roll_discrepancies(rng_b, *args)
        finally:
            config.STEGO_SHAPE_CONVENTIONAL_CHANCE = saved
        rest = [d for d in with_shape if d.kind not in _SHAPE_KIND_TO_NAME]
        shaped += len(rest) != len(with_shape)
        assert rest == without, (
            f"{archetype.value} day {day_n} seed {seed}: planting a shape "
            f"changed the budgeted kinds {[d.kind.name for d in without]} -> "
            f"{[d.kind.name for d in rest]}")
    assert shaped, "no shaped carrier in the sweep — guard is inert"


def test_non_shape_archetype_with_a_stego_carrier_stays_conventional():
    """Today only Sneaky Bugger and White Hat can carry a stego colour kind at
    all, so the archetype gate has nothing to refuse in an ordinary sweep —
    the guard would be inert. Give a non-shape archetype a stego-only spec and
    roll it directly: it must get its colour kind and never a shape."""
    import random
    from dataclasses import replace

    carried = 0
    for archetype in (Archetype.CLUMSY_CUTIE, Archetype.DAY_TO_DAY,
                      Archetype.THE_INCOMPATIBLE):
        spec = replace(candidate_gen.ARCHETYPE_SPECS[archetype],
                       eligible_kinds=(DiscrepancyKind.STEGO_PAYLOAD_PRESENT,),
                       budget=candidate_gen.DiscrepancyBudget(major=1))
        for seed in range(300):
            kinds = {d.kind for d in candidate_gen._roll_discrepancies(
                random.Random(seed), spec, 8)}
            assert DiscrepancyKind.STEGO_PAYLOAD_PRESENT in kinds
            carried += 1
            assert not kinds & set(_SHAPE_KIND_TO_NAME), (
                f"{archetype.value} seed {seed} drew a special shape {kinds}")
    assert carried


def test_conventional_share_tracks_the_config_knob():
    """Conventional is the majority outcome, at the configured rate, with the
    remainder split evenly. A large sample, not one candidate."""
    counts = {"conventional": 0, "cross": 0, "enclosed": 0, "slash": 0}
    for _a, _d, _s, c in _shape_sweep(
            days=range(5, 21), seeds=range(100),
            archetypes=(Archetype.SNEAKY_BUGGER, Archetype.WHITE_HAT)):
        kinds = {d.kind for d in c.truth.discrepancies}
        if not kinds & _STEGO_COLOUR_KINDS:
            continue
        shape = next((_SHAPE_KIND_TO_NAME[k] for k in kinds
                      if k in _SHAPE_KIND_TO_NAME), "conventional")
        counts[shape] += 1
    n = sum(counts.values())
    assert n >= 1500, f"only {n} stego carriers sampled"
    conv = counts["conventional"] / n
    knob = config.STEGO_SHAPE_CONVENTIONAL_CHANCE
    assert abs(conv - knob) < 0.04, f"conventional share {conv:.3f} vs knob {knob}"
    assert conv > 0.5, "conventional must stay the majority outcome"
    each = (1 - knob) / 3
    for name in ("cross", "enclosed", "slash"):
        share = counts[name] / n
        assert abs(share - each) < 0.04, f"{name} share {share:.3f} vs {each:.3f}"


def _flood_exterior(img):
    """Non-carrier cells reachable 4-way from outside the zone."""
    zx, zy, zw, zh = img.zone
    inside = {(x, y) for x in range(zx, zx + zw) for y in range(zy, zy + zh)}
    free = inside - img.carrier
    frontier = [c for c in free
                if c[0] in (zx, zx + zw - 1) or c[1] in (zy, zy + zh - 1)]
    seen = set(frontier)
    while frontier:
        x, y = frontier.pop()
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if n in free and n not in seen:
                seen.add(n)
                frontier.append(n)
    return free, seen


def _components(cells, diagonal: bool):
    steps = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    if diagonal:
        steps += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
    left, comps = set(cells), 0
    while left:
        comps += 1
        stack = [left.pop()]
        while stack:
            x, y = stack.pop()
            for dx, dy in steps:
                n = (x + dx, y + dy)
                if n in left:
                    left.remove(n)
                    stack.append(n)
    return comps


def _touch(a, b) -> bool:
    return any((x + dx, y + dy) in b for (x, y) in a
               for dx in (-1, 0, 1) for dy in (-1, 0, 1))


def _shaped_images(per_shape=40):
    """(expected shape name, image) until every shape has `per_shape`
    examples, across the whole campaign's grid sizes (days 5-20, so the
    STEGO_GRID_MAX cap is exercised too)."""
    got = {"conventional": [], "cross": [], "enclosed": [], "slash": []}
    for _a, day_n, _s, c in _shape_sweep(
            days=range(5, 21), seeds=range(60),
            archetypes=(Archetype.WHITE_HAT, Archetype.SNEAKY_BUGGER)):
        kinds = {d.kind for d in c.truth.discrepancies}
        if not kinds & _STEGO_COLOUR_KINDS:
            continue
        name = next((_SHAPE_KIND_TO_NAME[k] for k in kinds
                     if k in _SHAPE_KIND_TO_NAME), "conventional")
        if len(got[name]) < per_shape:
            got[name].append((c, tools_bridge.build_stego_image(c, day_n)))
        if all(len(v) >= per_shape for v in got.values()):
            break
    return got


def test_carrier_glyph_geometry_matches_the_planted_shape():
    """The image must show the glyph ground truth says it carries — cross
    strokes really cross, an enclosure really is hollow and sealed, slashes
    really are parallel and apart — and tools_bridge must never disagree with
    candidate_gen about which shape it is."""
    got = _shaped_images()
    for name, pairs in got.items():
        assert len(pairs) >= 40, f"only {len(pairs)} {name} images — inert"
        for c, img in pairs:
            where = f"{name} {c.id}"
            kinds = {d.kind for d in c.truth.discrepancies}
            planted = next((k for k in kinds if k in _SHAPE_KIND_TO_NAME), None)
            assert img.shape.value == name, (
                f"{where}: ground truth says {name}, image renders {img.shape}")
            assert img.shape_kind is planted
            zx, zy, zw, zh = img.zone
            assert all(zx <= x < zx + zw and zy <= y < zy + zh
                       for x, y in img.carrier), f"{where}: carrier leaves zone"
            if name == "conventional":
                assert img.strokes == ()
                continue
            assert frozenset().union(*img.strokes) == img.carrier
            ys = {y for _x, y in img.carrier}
            xs = {x for x, _y in img.carrier}
            # Spans the zone top to bottom and a good part of its width, so a
            # sweep meets it before coverage resolves.
            assert min(ys) == zy and max(ys) == zy + zh - 1, where
            assert (max(xs) - min(xs) + 1) >= 0.4 * zw, (
                f"{where}: glyph spans only {max(xs) - min(xs) + 1} of {zw}")
            if name == "cross":
                assert len(img.strokes) == 2, where
                a, b = img.strokes
                assert a & b, f"{where}: the two strokes never intersect"
                assert _components(img.carrier, diagonal=False) == 1, where
            elif name == "enclosed":
                free, outside = _flood_exterior(img)
                interior = free - outside
                assert interior, f"{where}: outline is not closed / not hollow"
                assert not interior & img.carrier
                assert _components(img.carrier, diagonal=False) == 1, where
            else:  # slash
                n = len(img.strokes)
                assert 2 <= n <= 4, f"{where}: {n} strokes"
                first = img.strokes[0]
                ox, oy = min(first)
                shape0 = {(x - ox, y - oy) for x, y in first}
                for st in img.strokes[1:]:
                    sx, sy = min(st)
                    assert {(x - sx, y - sy) for x, y in st} == shape0, (
                        f"{where}: strokes are not parallel copies")
                for i in range(n):
                    for j in range(i + 1, n):
                        assert not _touch(img.strokes[i], img.strokes[j]), (
                            f"{where}: strokes {i} and {j} touch")
                assert _components(img.carrier, diagonal=True) == n, where


def test_glyph_builders_hold_their_geometry_at_every_zone_size():
    """The candidate sweep above only reaches the zone sizes its seeds happen
    to land on, and a glyph's edge cases live at the small sizes (two slashes
    that round onto adjacent rows, a ring with no room for a hole). So drive
    the builders directly over every zone size build_stego_image can produce
    (width 4-36, height 3-16 — w_lo is max(4, cols//5), h_lo max(3, rows//4),
    both halves capped by STEGO_GRID_MAX), several rng draws each."""
    import random

    zone_sizes = [(w, h) for w in range(4, 37) for h in range(3, 17)]
    assert max(config.STEGO_GRID_MAX) // 2 <= 36
    for (w, h) in zone_sizes:
        for seed in range(12):
            # Mix the size into the seed. Each builder's variant draws (stroke
            # count, orientation, ring vs diamond) come first and depend only
            # on the rng, so a bare seed would pin the SAME few variants to
            # every size — the first draft of this test did, and missed two
            # slashes rounding onto adjacent rows at 6 rows high.
            rs = seed * 10_007 + w * 101 + h
            where = f"{w}x{h} seed {rs}"
            cross = tools_bridge._glyph_cross(random.Random(rs), w, h)
            assert len(cross) == 2 and cross[0] & cross[1], f"cross {where}"
            ring = tools_bridge._glyph_enclosed(random.Random(rs), w, h)
            assert len(ring) == 1, where
            cells = ring[0]
            box = {(x, y) for x in range(w) for y in range(h)}
            assert cells <= box and (cross[0] | cross[1]) <= box, where
            free = box - cells
            edge = [c for c in free if c[0] in (0, w - 1) or c[1] in (0, h - 1)]
            seen, stack = set(edge), list(edge)
            while stack:
                x, y = stack.pop()
                for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if n in free and n not in seen:
                        seen.add(n)
                        stack.append(n)
            assert free - seen, f"enclosed {where}: no sealed, empty interior"
            slash = tools_bridge._glyph_slash(random.Random(rs), w, h)
            assert 2 <= len(slash) <= 4, f"slash {where}"
            ox, oy = min(slash[0])
            base = {(x - ox, y - oy) for x, y in slash[0]}
            for i, st in enumerate(slash):
                sx, sy = min(st)
                assert {(x - sx, y - sy) for x, y in st} == base, (
                    f"slash {where}: stroke {i} is not a parallel copy")
                assert all(0 <= x < w and 0 <= y < h for x, y in st), where
                for other in slash[i + 1:]:
                    assert not _touch(st, other), f"slash {where}: strokes touch"


def test_every_shaped_payload_is_hit_before_it_resolves():
    """Same regression as test_every_stego_payload_can_be_found_before_it_
    resolves, but across every special glyph and the whole grid-size range:
    a thin outline or a pair of edge strokes must still be crossed by a
    systematic sweep before coverage resolves."""
    got = _shaped_images(per_shape=25)
    for name in ("cross", "enclosed", "slash"):
        for _c, img in got[name]:
            revealed: set = set()
            zx, zy, zw, zh = img.zone
            saw = False
            for yy in range(zy, zy + zh, config.STEGO_STAMP_H):
                for xx in range(zx, zx + zw, config.STEGO_STAMP_W):
                    res = tools_bridge.evaluate_stamp(
                        img, xx, yy, config.STEGO_STAMP_W,
                        config.STEGO_STAMP_H, revealed)
                    saw = saw or bool(res.signature)
                    if res.resolved:
                        break
                else:
                    continue
                break
            assert saw, f"{name} glyph resolved without a carrier ever hit"


def test_shape_is_named_only_by_the_filter():
    """Unfiltered: the resolve block describes the glyph's GEOMETRY, never its
    purpose and never a ▲ shape label. Filtered: a special glyph gets its own
    ▲ label. Conventional never gets one at either tier."""
    geometry = {
        "conventional": "irregular blocks",
        "cross":        "strokes cross",
        "enclosed":     "hollow interior",
        "slash":        "parallel strokes",
    }
    purpose_words = ("signal comm", "recursive", "hostile")
    got = _shaped_images(per_shape=15)
    for name, pairs in got.items():
        for c, img in pairs:
            plain = "\n".join(tools_bridge.stamp_signature_lines(img, reveal_type=False))
            named = "\n".join(tools_bridge.stamp_signature_lines(img, reveal_type=True))
            assert geometry[name] in plain, f"{name}: geometry not described"
            for k in _SHAPE_KIND_TO_NAME:
                assert k.value.upper() not in plain, (
                    f"{name}: unfiltered block names {k.name}")
            assert not any(w in plain.lower() for w in purpose_words), (
                f"{name}: unfiltered block leaks the purpose:\n{plain}")
            assert "GLYPH RESOLVED" not in plain
            planted = next((k for k in _SHAPE_KIND_TO_NAME
                            if any(d.kind is k for d in c.truth.discrepancies)),
                           None)
            if planted is None:
                assert "GLYPH RESOLVED" not in named
                for k in _SHAPE_KIND_TO_NAME:
                    assert f"▲ {k.value.upper()}" not in named, (
                        f"conventional carrier printed ▲ {k.name}")
            else:
                assert f"▲ {planted.value.upper()}" in named
                others = set(_SHAPE_KIND_TO_NAME) - {planted}
                assert not any(k.value.upper() in named for k in others)


# ─── 2026-09-19 (round 2) — shapes on scripted slots, in the rulebook, ─────
# ─── Bad Actor carriers, derived reference panels, UNSALTED step ───────────


def _write_scripted_shape_day(tmp_path, monkeypatch, *, forced_includes=None,
                              forced_violations=None, carrier_shape=None,
                              number=12):
    """Day 1's rules restated as day `number`, with only the scripting given.
    Day 1's own tutorial script and whitelist are stripped: they would reject
    any stego kind before the shape validation ever ran."""
    import json

    source = json.loads((_REAL_DAYS_DIR / "day_01.json").read_text(encoding="utf-8"))
    source["number"] = number
    for key in ("allowed_violations", "forced_includes", "forced_violations"):
        source.pop(key, None)
    if forced_includes is not None:
        source["forced_includes"] = forced_includes
    if forced_violations is not None:
        source["forced_violations"] = forced_violations
    if carrier_shape is not None:
        source["carrier_shape"] = carrier_shape
    monkeypatch.setattr(config, "DAYS_DIR", tmp_path)
    (tmp_path / f"day_{number:02d}.json").write_text(json.dumps(source),
                                                    encoding="utf-8")


@pytest.mark.parametrize("includes,violations,shape,match", [
    ({"0": "sneaky_bugger"}, {"0": ["hostile_payload"]}, None,
     "needs a carrier"),
    ({}, {"0": ["encrypted_payload", "hostile_payload"]}, None,
     "shape-eligible archetype"),
    ({"0": "clumsy_cutie"}, {"0": ["stego_payload_present", "hostile_payload"]},
     None, "shape-eligible archetype"),
    ({"0": "white_hat"}, {"0": ["covert_c2_channel", "hostile_payload"]}, None,
     "cannot carry"),
    ({"0": "sneaky_bugger"},
     {"0": ["encrypted_payload", "hostile_payload", "recursive_payload"]},
     None, "at most one"),
    ({"0": "sneaky_bugger"}, {"0": ["encrypted_payload", "hostile_payload"]},
     {"0": "conventional"}, "contradict"),
    ({"0": "sneaky_bugger"}, {"0": ["encrypted_payload"]}, {"0": "cross"},
     "only pin"),
])
def test_scripted_carrier_shapes_are_validated_when_the_day_loads(
        tmp_path, monkeypatch, includes, violations, shape, match):
    """A scripted shape that cannot land must fail at load, naming the file —
    the generator would otherwise drop it silently (the #15 stance)."""
    _write_scripted_shape_day(tmp_path, monkeypatch, forced_includes=includes,
                              forced_violations=violations, carrier_shape=shape)
    with pytest.raises(ValueError, match=match):
        load_day(12)


def test_authored_carrier_shapes_plant_exactly_as_authored(tmp_path, monkeypatch):
    """A forced shape lands on every seed with its colour kind, the image
    renders that glyph, and a pinned-conventional slot never has one."""
    _write_scripted_shape_day(
        tmp_path, monkeypatch,
        forced_includes={"0": "sneaky_bugger", "1": "sneaky_bugger"},
        forced_violations={"0": ["encrypted_payload", "recursive_payload"],
                           "1": ["encrypted_payload"]},
        carrier_shape={"1": "conventional"})
    day = load_day(12)
    assert day.conventional_carrier_slots == frozenset({1})
    for seed in range(40):
        c0 = candidate_gen.generate(seed, day, 0)
        k0 = {d.kind for d in c0.truth.discrepancies}
        assert {DiscrepancyKind.ENCRYPTED_PAYLOAD,
                DiscrepancyKind.RECURSIVE_PAYLOAD} <= k0, (seed, k0)
        assert not (k0 & set(_SHAPE_KIND_TO_NAME)) - {
            DiscrepancyKind.RECURSIVE_PAYLOAD}
        assert tools_bridge.build_stego_image(c0, 12).shape.value == "enclosed"
        c1 = candidate_gen.generate(seed, day, 1)
        k1 = {d.kind for d in c1.truth.discrepancies}
        assert DiscrepancyKind.ENCRYPTED_PAYLOAD in k1
        assert not k1 & set(_SHAPE_KIND_TO_NAME), (seed, k1)
        assert tools_bridge.build_stego_image(c1, 12).shape.value == "conventional"


def test_real_scripted_slots_carry_their_authored_shape():
    """The two slots that pin a shape story in the shipped content: day 12's
    White Hat always shows the cross; day 11's rules-clean Sneaky Bugger is
    always a plain image (any glyph would disqualify it on day 11)."""
    day12, day11 = load_day(12), load_day(11)
    assert 5 in day11.conventional_carrier_slots
    for seed in range(40):
        wh = candidate_gen.generate(seed, day12, 7)
        assert wh.archetype is Archetype.WHITE_HAT
        assert DiscrepancyKind.SIGNAL_COMMS_PAYLOAD in {
            d.kind for d in wh.truth.discrepancies}
        assert tools_bridge.build_stego_image(wh, 12).shape.value == "cross"
        sb = candidate_gen.generate(seed, day11, 5)
        assert not {d.kind for d in sb.truth.discrepancies} & set(_SHAPE_KIND_TO_NAME)
        assert tools_bridge.build_stego_image(sb, 11).shape.value == "conventional"


def test_unpinned_scripted_carriers_roll_shapes():
    """Scripted slots are no longer blanket-conventional: an unpinned scripted
    stego carrier rolls a shape like any other (the round-1 gate is gone)."""
    shaped = carriers = 0
    for n in range(6, 21):
        day = load_day(n)
        for slot in day.forced_violations:
            if slot in day.conventional_carrier_slots:
                continue
            if any(k in _SHAPE_KIND_TO_NAME for k in day.forced_violations[slot]):
                continue      # authored, not rolled
            for seed in range(60):
                c = candidate_gen.generate(seed, day, slot)
                kinds = {d.kind for d in c.truth.discrepancies}
                if not kinds & _STEGO_COLOUR_KINDS:
                    continue
                carriers += 1
                shaped += bool(kinds & set(_SHAPE_KIND_TO_NAME))
    assert carriers >= 100, f"only {carriers} scripted stego carriers sampled"
    assert 0.3 < shaped / carriers < 0.6, (
        f"{shaped}/{carriers} unpinned scripted carriers took a shape")


def test_bad_actor_can_carry_a_stego_payload_and_a_shape():
    """Nick, 2026-09-19: Bad Actor gets STEGO_PAYLOAD_PRESENT, which is what
    makes its membership in the shape-eligible set reachable at all."""
    seen = {k: 0 for k in _SHAPE_KIND_TO_NAME}
    stego = 0
    for _a, _d, _s, c in _shape_sweep(days=range(5, 21), seeds=range(40),
                                      archetypes=(Archetype.BAD_ACTOR,)):
        kinds = {d.kind for d in c.truth.discrepancies}
        assert not kinds & {DiscrepancyKind.ENCRYPTED_PAYLOAD,
                            DiscrepancyKind.COVERT_C2_CHANNEL}
        stego += DiscrepancyKind.STEGO_PAYLOAD_PRESENT in kinds
        for k in kinds & set(seen):
            seen[k] += 1
    assert stego >= 100
    assert all(n >= 10 for n in seen.values()), seen


# ── Shapes in the rulebook ──────────────────────────────────────────────────


def _shape_rule(day, kind):
    rules = [r for r in day.rules if r.predicate == f"has_discrepancy:{kind.value}"]
    assert len(rules) == 1, (day.number, kind.name, [r.id for r in rules])
    return rules[0]


def test_every_shape_rule_resolves_on_every_day_and_agrees_everywhere():
    """For every shape kind on every day 1-20: exactly one live rule, its
    predicate resolves, the rules tab's TODAY column reports the same
    severity, and scoring (rules_engine.evaluate) files a carrier the same way.
    """
    from gameengine.ui.tui import rules_content

    expected = {   # authored intent, restated rather than read back
        DiscrepancyKind.SIGNAL_COMMS_PAYLOAD: "DDDDDDDwwwDDDDDDDDDw",
        DiscrepancyKind.RECURSIVE_PAYLOAD:    "D" * 20,
        DiscrepancyKind.HOSTILE_PAYLOAD:      "D" * 12 + "w" * 8,
    }
    for n in range(1, 21):
        day = load_day(n)
        for kind, sched in expected.items():
            rule = _shape_rule(day, kind)
            rules_engine.resolve(rule.predicate)
            want = "disqualifying" if sched[n - 1] == "D" else "weighted"
            assert rule.severity == want, (n, kind.name, rule.id)
            status, _col = rules_content._rule_status(day, kind)
            assert status == ("DENY" if want == "disqualifying" else "FLAG")
            fake = _candidate_carrying_only(kind)
            ev = rules_engine.evaluate(fake, day)
            bucket = (ev.triggered_disqualifying if want == "disqualifying"
                      else ev.triggered_weighted)
            assert rule in bucket, (n, kind.name)


def _candidate_carrying_only(kind):
    """A generated candidate with its ground truth replaced by one kind."""
    from dataclasses import replace

    from gameengine.core.models import Discrepancy
    c = candidate_gen.generate(SEED, unconstrained_day(), 0)
    d = Discrepancy(kind=kind, severity=candidate_gen.severity_for(kind),
                    revealed_by=candidate_gen._SEVERITY_REVEAL[kind][0],
                    description="")
    return replace(c, truth=replace(c.truth, discrepancies=(d,)))


def test_shape_rule_mutations_flip_the_verdict_and_are_announced():
    """Every day a shape rule's severity moves, a candidate carrying only that
    shape changes rules verdict, and the Overseer's briefing says something
    about it (a generic flip line, or the directive's own justification)."""
    from gameengine.ui.tui.app import rule_change_lines

    flips = 0
    for n in range(2, 21):
        prev, cur = load_day(n - 1), load_day(n)
        changes = rules_engine.diff_rulesets(prev, cur)
        lines = rule_change_lines(changes, n)
        for kind in _SHAPE_KIND_TO_NAME:
            before = rules_engine.evaluate(_candidate_carrying_only(kind), prev)
            after = rules_engine.evaluate(_candidate_carrying_only(kind), cur)
            if bool(before.triggered_disqualifying) == bool(after.triggered_disqualifying):
                continue
            flips += 1
            touched = [c for c in changes
                       if c.rule.predicate == f"has_discrepancy:{kind.value}"]
            assert touched, f"day {n}: {kind.name}'s verdict moved silently"
            if touched[0].kind == "added" and touched[0].rule.justification:
                assert touched[0].rule.justification in lines
            else:
                assert lines, f"day {n}: {kind.name} changed, no briefing line"
    # signal comms: days 8, 11, 20; hostile: DW-06 on day 13.
    assert flips == 4, flips


def test_no_variable_rule_moves_before_its_kind_can_be_planted():
    """An overseer_variable flip announced before the revealing tool exists
    would brief the player on a rule they cannot yet apply."""
    for n in range(2, 21):
        prev, cur = load_day(n - 1), load_day(n)
        for change in rules_engine.diff_rulesets(prev, cur):
            if change.kind != "severity" or change.rule.mutability != "overseer_variable":
                continue
            kind = DiscrepancyKind(change.rule.predicate.split(":", 1)[1])
            assert candidate_gen.intro_day(kind) <= n, (
                f"day {n}: {change.rule.id} flips before {kind.name} is "
                f"plantable (day {candidate_gen.intro_day(kind)})")


# ── UNSALTED_STORAGE's scheduled step, and rule-id hygiene ──────────────────


def test_unsalted_rule_follows_the_hashcrack_step_and_is_announced():
    """Minor (a flag) before Hashcrack's unlock day, major (a deny) from it —
    the rule, the rules tab and the briefing all agree, and the step day is
    derived from config rather than written down."""
    from gameengine.ui.tui import rules_content
    from gameengine.ui.tui.app import rule_change_lines

    us = DiscrepancyKind.UNSALTED_STORAGE
    step = config.TOOL_UNLOCK_DAY["hashcrack"]
    assert candidate_gen._SEVERITY_BY_DAY[us][1] == step
    assert candidate_gen._SEVERITY_REVEAL[us][0].value == "dossier"
    for n in range(1, 21):
        day = load_day(n)
        rule = [r for r in day.rules if r.id == "rule_unsalted_storage"]
        assert len(rule) == 1, n
        want = "weighted" if n < step else "disqualifying"
        assert rule[0].severity == want, (n, rule[0].severity)
        assert rules_content._rule_status(day, us)[0] == (
            "FLAG" if n < step else "DENY")
    changes = rules_engine.diff_rulesets(load_day(step - 1), load_day(step))
    moved = [c for c in changes if c.rule.id == "rule_unsalted_storage"]
    assert len(moved) == 1 and moved[0].kind == "severity"
    lines = rule_change_lines(moved, step)
    assert lines and "unsalted" in lines[0].lower()
    # ...and never announced on any other morning.
    for n in range(2, 21):
        if n == step:
            continue
        assert not [c for c in rules_engine.diff_rulesets(load_day(n - 1), load_day(n))
                    if c.rule.id == "rule_unsalted_storage"], n


def test_rule_ids_are_unique_in_every_day_file(tmp_path, monkeypatch):
    """day_01.json shipped two rule_unsalted_storage and two
    rule_cross_breach_reuse entries (2026-09-19 cleanup). Checked on the raw
    JSON — the resolved book would hide a duplicate — and the loader now
    refuses one."""
    import json

    for path in sorted(config.DAYS_DIR.glob("day_*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        for key in ("rules", "added_rules"):
            ids = [r["id"] for r in raw.get(key, [])]
            dupes = {i for i in ids if ids.count(i) > 1}
            assert not dupes, f"{path.name} {key}: duplicate ids {dupes}"

    source = json.loads((_REAL_DAYS_DIR / "day_01.json").read_text(encoding="utf-8"))
    source["rules"].append(dict(source["rules"][0]))
    monkeypatch.setattr(config, "DAYS_DIR", tmp_path)
    (tmp_path / "day_01.json").write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="more than once"):
        load_day(1)


# ── Reference panels are derived from their sources ─────────────────────────


def test_reference_panels_follow_config(monkeypatch):
    """Change a cost or a key in config and every reference panel that shows
    it changes with it — no literal left behind."""
    from gameengine.ui.tui import shared

    monkeypatch.setattr(config, "STEGO_STAMP_COST", 7)
    monkeypatch.setattr(config, "STEGO_FILTER_COST", 13)
    monkeypatch.setitem(config.TOOL_COSTS, "ghostscan", 9)
    monkeypatch.setitem(config.TOOL_COSTS, "hashcrack", 11)
    monkeypatch.setitem(config.TOOL_COSTS, "logwatch", 12)
    monkeypatch.setitem(config.FILTER_COSTS, "ghostscan", 17)
    monkeypatch.setitem(config.FILTER_COSTS, "logwatch", 19)
    monkeypatch.setitem(config.KEY_BINDINGS, "stamp_mode", "z")
    monkeypatch.setitem(config.KEY_BINDINGS, "tool_logwatch", "k")

    st = shared.build_ref_stegotool()
    assert "7 ⏱ per stamp" in st and "cost: 13 ⏱" in st
    assert "[#00ff9f]Z[/]" in st
    assert "cost: 9 ⏱" in shared.build_ref_ghostscan()
    assert "cost: +17 ⏱" in shared.build_ref_ghostscan()
    assert "(11 ⏱)" in shared.build_ref_hashcrack()
    lw = shared.build_ref_logwatch()
    assert "cost: 12 ⏱" in lw and "cost: +19 ⏱" in lw and "[#00ff9f]k[/]" in lw
    cand = shared.build_ref_candidate()
    assert "9 ⏱" in cand and "7 ⏱/stamp" in cand

    # Live state: an owned optimizer and a late day both move the price.
    state = GameState(seed=SEED, current_day=12, compute_hours=100)
    state.upgrades = {config.UPGRADE_TOOLCOST_GHOSTSCAN,
                      config.UPGRADE_TOOLCOST_STEGOTOOL}
    gs = shared.build_ref_ghostscan(state)
    assert f"cost: {tools_bridge.tool_cost(state, 'ghostscan')} ⏱" in gs
    assert f"cost: {13 - config.TOOLCOST_REDUCTION} ⏱" in shared.build_ref_stegotool(state)


def test_stego_reference_lists_every_signature_and_glyph():
    """Every colour signature and every carrier glyph the engine renders is
    in the Stegotool reference, colour-true, and nothing is paired with the
    wrong texture (the old panel had AMBER and VIOLET's swapped)."""
    from gameengine.ui.tui import rules_content, shared

    text = shared.build_ref_stegotool()
    lines = text.split("\n")
    for _kind, (sig, col, desc) in tools_bridge._STAMP_KIND_META.items():
        i = next(i for i, ln in enumerate(lines) if ln.startswith(f"[{col}]{sig}"))
        assert desc.split(" — ", 1)[-1] in lines[i + 1], sig
    for _shape, (geometry, _p, kind) in tools_bridge._STAMP_SHAPE_META.items():
        assert geometry.split(" — ")[0] in text
        if kind is not None:
            assert rules_content.label_for(kind) in text


def test_day_1_slot_3_is_an_honest_deny_that_teaches_the_unsalted_flag():
    """Day 1 slot 3 (2026-09-19 re-script). UNSALTED_STORAGE is a flag until
    Hashcrack, so the slot's Clumsy Cutie also carries a throwaway email — the
    day-1 deny — and the rulebook agrees with ground truth on every seed,
    denying on the email while only flagging the password."""
    day = load_day(1)
    assert set(day.forced_violations[3]) == {DiscrepancyKind.UNSALTED_STORAGE,
                                            DiscrepancyKind.DISPOSABLE_EMAIL}
    for seed in range(200):
        c = candidate_gen.generate(seed, day, 3)
        assert c.archetype is Archetype.CLUMSY_CUTIE
        kinds = {d.kind for d in c.truth.discrepancies}
        assert {DiscrepancyKind.UNSALTED_STORAGE,
                DiscrepancyKind.DISPOSABLE_EMAIL} <= kinds, (seed, kinds)
        # The evidence exists: a real throwaway domain on the dossier.
        assert tools_bridge.classify_email_domain(c.email) == "prohibited", c.email
        ev = rules_engine.evaluate(c, day)
        denied_on = {r.predicate for r in ev.triggered_disqualifying}
        assert denied_on == {"has_discrepancy:disposable_email"}, (seed, denied_on)
        assert "has_discrepancy:unsalted_storage" in {
            r.predicate for r in ev.triggered_weighted}
        assert c.truth.correct_verdict is Verdict.DENY


def test_disposable_email_carriers_of_any_archetype_show_a_throwaway_domain():
    """DISPOSABLE_EMAIL left The Incompatible's exclusive list (Clumsy Cutie,
    2026-09-19); its only evidence is the email, so every carrier of it, of
    every archetype, must have a disposable domain — and nobody else must."""
    seen_clumsy = 0
    for archetype, _d, _s, c in _shape_sweep(days=range(1, 13), seeds=range(40)):
        has = any(d.kind is DiscrepancyKind.DISPOSABLE_EMAIL
                  for d in c.truth.discrepancies)
        cls = tools_bridge.classify_email_domain(c.email)
        if archetype is Archetype.THE_INCOMPATIBLE:
            continue    # its email predates the kind's roll; covered by #57
        assert (cls == "prohibited") == has, (archetype.value, c.email, has)
        seen_clumsy += has and archetype is Archetype.CLUMSY_CUTIE
    assert seen_clumsy >= 20, f"only {seen_clumsy} Clumsy carriers — inert"


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
    """Batch-3, revisiting #61(d): a player who flags BREACH_HIT on a
    CROSS_BREACH_REUSE carrier is reading real on-screen evidence — the breach
    panel labels that carrier's email BREACH_HIT whether or not the kind is in
    ground truth — so scoring credits it rather than calling it a false
    positive.

    REBUILT 2026-09-15. This test used to SEARCH 500 seeds for a generated
    CROSS_BREACH_REUSE carrier that lacked BREACH_HIT, and asserted it had
    found one. After the companion-preference change (_COMPANION_KINDS), that
    combination no longer occurs: BREACH_HIT accompanies every CROSS_BREACH_REUSE
    carrier, up from 24% before. The search therefore fails its own
    "test is inert" assertion.

    The scoring rule it guards is NOT dead, and weakening the assertion to make
    the search pass would have thrown away a real guard. The credit exists so
    that a player who flags what the breach panel shows is never penalised for
    it; the generator merely stopped being the thing that produces the
    scenario. So the scenario is now CONSTRUCTED — take a real carrier and
    remove BREACH_HIT from its ground truth — which tests the scoring rule at
    the level it actually lives, instead of depending on a generator
    distribution that was never the subject.

    If the companion preference is ever removed, this keeps passing, which is
    the point: the rule must hold either way.
    """
    import dataclasses

    day = load_day(20)   # late enough for every tool/kind to be taught
    carrier = None
    for seed in range(500):
        c = candidate_gen.generate(seed, day, 0)
        if any(d.kind is DiscrepancyKind.CROSS_BREACH_REUSE
               for d in c.truth.discrepancies):
            carrier = c
            break
    assert carrier is not None, (
        "no CROSS_BREACH_REUSE candidate generated in 500 seeds — test is inert")

    # Strip BREACH_HIT back out, reproducing the ground truth this rule was
    # written for. Frozen dataclasses, so rebuild rather than mutate.
    stripped = tuple(d for d in carrier.truth.discrepancies
                     if d.kind is not DiscrepancyKind.BREACH_HIT)
    reuse_only = dataclasses.replace(
        carrier,
        truth=dataclasses.replace(carrier.truth, discrepancies=stripped))
    actual = {d.kind for d in reuse_only.truth.discrepancies}
    assert DiscrepancyKind.CROSS_BREACH_REUSE in actual
    assert DiscrepancyKind.BREACH_HIT not in actual

    # A perfect board (every real kind flagged, nothing else) is the score
    # to match — flagging BREACH_HIT in place of, or alongside,
    # CROSS_BREACH_REUSE must reach that same ceiling, not fall short of it.
    perfect = scoring.board_accuracy_bonus(actual, reuse_only)

    with_breach_hit = scoring.board_accuracy_bonus(
        actual | {DiscrepancyKind.BREACH_HIT}, reuse_only)
    assert with_breach_hit == perfect, (
        "flagging BREACH_HIT alongside CROSS_BREACH_REUSE scored as a false "
        "positive, but the breach panel shows that carrier's email as a hit")

    # Flagging ONLY BREACH_HIT in CROSS_BREACH_REUSE's place (having missed
    # or not run Hashcrack) is also a full match, not a false positive plus
    # a miss.
    breach_hit_in_place_of_reuse = scoring.board_accuracy_bonus(
        (actual - {DiscrepancyKind.CROSS_BREACH_REUSE})
        | {DiscrepancyKind.BREACH_HIT},
        reuse_only)
    assert breach_hit_in_place_of_reuse == perfect


def test_breach_hit_now_accompanies_every_credential_corpus_kind():
    """Ghostscan corroborates Hashcrack, on both corpus kinds (Nick, 2026-09-15).

    LEAKED_PASSWORD has always implied BREACH_HIT (_IMPLIED_KINDS).
    CROSS_BREACH_REUSE did not, and the gap was severe and lopsided: BREACH_HIT
    was missing from 75.7% of its carriers, and EVERY one of those was a Sneaky
    Bugger — not by design, but because BREACH_HIT was simply absent from that
    archetype's eligible_kinds and so could never be selected there.

    Fixed as a COMPANION PREFERENCE rather than an implication, deliberately:
    #61(d) removed CROSS_BREACH_REUSE from _IMPLIED_KINDS so the two stay
    distinct kinds in ground truth, and re-adding it there would have undone
    that. The preference only reorders candidates for a slot the archetype
    already owns, so BREACH_HIT still costs budget and can still lose to a
    forced violation.
    """
    missing_reuse = missing_leaked = carriers = 0
    for seed in range(40):
        for day_number in range(3, config.CAMPAIGN_LAST_DAY + 1):
            day = load_day(day_number)
            for slot in range(day.candidate_count):
                kinds = {d.kind for d in
                         candidate_gen.generate(seed, day, slot).truth.discrepancies}
                has_hit = DiscrepancyKind.BREACH_HIT in kinds
                if DiscrepancyKind.CROSS_BREACH_REUSE in kinds:
                    carriers += 1
                    missing_reuse += not has_hit
                if DiscrepancyKind.LEAKED_PASSWORD in kinds:
                    carriers += 1
                    missing_leaked += not has_hit
    assert carriers, "guard is inert — no corpus-kind carrier examined"
    assert missing_leaked == 0, (
        f"{missing_leaked} LEAKED_PASSWORD carriers have no BREACH_HIT")
    assert missing_reuse == 0, (
        f"{missing_reuse} CROSS_BREACH_REUSE carriers have no BREACH_HIT — a "
        f"password cannot recur across corpora unless the account is in them, "
        f"so Ghostscan should corroborate what Hashcrack found")


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


def test_weak_encryption_is_exactly_the_md5_candidates_that_are_salted():
    """#59: WEAK_ENCRYPTION means "the weakest algorithm is used", so it tracks
    the hash exactly — every md5 candidate carries it, no other candidate does.

    Both directions are real bugs that existed. Only 199 of 432 md5 candidates
    flagged it (so the dossier's WEAK ENC chip sometimes meant a violation and
    sometimes didn't), and 62 of 2700 carried it on a *sha256* hash — a
    weak-encryption violation on a medium-encryption credential, with nothing
    for the player to observe.

    AMENDED 2026-09-15 with one exclusion: UNSALTED_STORAGE candidates.

    They are stored in the clear, so there is no encryption there to be weak —
    WEAK_ENCRYPTION on one is a category error, not a second finding. The
    generator still builds them an md5 internally because the cipher block
    needs something to key off, but the player is never shown it:
    shared._password_markup returns early for unsalted candidates and prints
    the plaintext with no hash at all. Before the exclusion the game told the
    player two contradictory things about the same candidate — the dossier said
    "no crypto here" while the Hashcrack header said "digest: 32 hex characters"
    — and scored them on both violations. Measured at 1,792 of 2,192 unsalted
    candidates (81.8%), and 100% of them on every day from 3 onward.

    So the invariant is now three-way, and all three directions are asserted:
    salted md5 always carries it, non-md5 never does, and unsalted never does.
    """
    md5_without = sha_with = unsalted_with = 0
    checked = salted_md5 = unsalted = 0
    for c in _credential_sweep():
        checked += 1
        has = any(d.kind == DiscrepancyKind.WEAK_ENCRYPTION
                  for d in c.truth.discrepancies)
        algo = _algo(c.dossier.submitted_hash)
        is_unsalted = c.dossier.credential_unsalted
        if is_unsalted:
            unsalted += 1
            if has:
                unsalted_with += 1
        elif algo == "md5":
            salted_md5 += 1
            if not has:
                md5_without += 1
        if algo != "md5" and has:
            sha_with += 1
    assert checked
    assert salted_md5, "guard is inert — no salted md5 candidate examined"
    assert unsalted, "guard is inert — no unsalted candidate examined"
    assert md5_without == 0, (
        f"{md5_without} salted md5 candidates without WEAK_ENCRYPTION")
    assert sha_with == 0, f"{sha_with} non-md5 candidates carrying WEAK_ENCRYPTION"
    assert unsalted_with == 0, (
        f"{unsalted_with} UNSALTED_STORAGE candidates also carry "
        f"WEAK_ENCRYPTION — they are stored in the clear, so there is no "
        f"algorithm there to be weak, and the dossier explicitly shows them "
        f"as plaintext with no hash")


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


def test_dossier_never_labels_the_encryption_tier():
    """The dossier shows the raw hash and NOTHING about its strength.

    Rewritten from test_password_encryption_chip_gated_behind_cipher_id_hud,
    which asserted the chip appeared once Cipher ID HUD was owned. The
    cipher-block rework removed that chip from the dossier outright and
    retiered WEAK_ENCRYPTION from DOSSIER to HASHCRACK, because a free
    algorithm label on every candidate meant a violation ABOUT the algorithm
    was permanently pre-flagged.

    The assertion is now stronger than the old one: not "hidden without the
    upgrade" but "not there at all, upgrade or not". Naming the tier is the
    cipher block's job (see the companion test below), and this is what stops
    it quietly reappearing on the dossier and re-solving the kind for free.
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

    for upgrades in (set(), {config.UPGRADE_CRYPTO_ID}, {config.UPGRADE_HC_VERDICT}):
        head, state = _password_markup(d, None, upgrades=upgrades)
        assert d.submitted_hash[:14] in head, "raw hash must stay visible"
        for label in ("WEAK ENC", "MEDIUM ENC", "STRONG ENC",
                      "MD5", "SHA256", "bcrypt"):
            assert label not in head and label not in state, (
                f"{label!r} leaked onto the dossier with upgrades={upgrades} — "
                f"the encryption tier is the cipher block's to establish")


def test_cipher_block_tier_label_gated_behind_cipher_id_hud():
    """The block always shows the DIGEST SHAPE; only the HUD names the tier.

    This is the replacement gate for the dossier chip removed above, and the
    split is load-bearing. WEAK_ENCRYPTION has to stay flaggable by a player
    who owns no upgrades, so the free header must carry a real observation —
    "32 hex characters" — that the rules page teaches them to interpret. What
    the 20 HD$ upgrade buys is the conclusion, not the evidence.
    """
    from gameengine.core import tools_bridge

    day = load_day(20)
    md5 = None
    for seed in range(200):
        c = candidate_gen.generate(seed, day, 0)
        if tools_bridge.cipher_tier(c.dossier.submitted_hash) == "weak":
            md5 = c
            break
    assert md5 is not None, "no MD5-tier candidate in 200 seeds"

    block = tools_bridge.build_cipher_block(md5, day.number)

    free = "\n".join(tools_bridge.cipher_header_lines(block, set()))
    assert "32 hex characters" in free, (
        "the digest shape must be free — it is WEAK_ENCRYPTION's only "
        "evidence for a player without Cipher ID HUD")
    assert "MD5" not in free, "the algorithm was named without the upgrade"

    hud = "\n".join(tools_bridge.cipher_header_lines(
        block, {config.UPGRADE_CRYPTO_ID}))
    assert "MD5" in hud and "WEAK" in hud, "Cipher ID HUD did not name the tier"
    assert "32 hex characters" in hud, "the upgrade must add, not replace"


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


def test_recovered_password_strength_verdict_gated_behind_crack_verdict_analyzer():
    """Judging a recovered password is the PLAYER's job unless they buy out.

    Moved here from the dossier (_password_markup) when the cipher-block
    rework made recovering the plaintext the Hashcrack page's whole activity.
    The property is unchanged and is the core of Nick's brief: the tool hands
    over the plaintext, and without Crack Verdict Analyzer it says nothing
    about whether that plaintext is any good.
    """
    from gameengine.core import tools_bridge

    day = load_day(20)
    cand = None
    for seed in range(200):
        c = candidate_gen.generate(seed, day, 0)
        if (DiscrepancyKind.WEAK_CREDENTIAL in {d.kind for d in c.truth.discrepancies}
                and c.dossier.password_plain):
            cand = c
            break
    assert cand is not None, "no weak-credential candidate in 200 seeds"

    block = tools_bridge.build_cipher_block(cand, day.number)
    plaintext = cand.dossier.password_plain

    ungated = "\n".join(tools_bridge.cipher_resolve_lines(
        block, cand, day.number, set()))
    assert plaintext in ungated, (
        "the plaintext must be handed over regardless — only the JUDGEMENT "
        "is for sale")
    assert "WEAK_CREDENTIAL" not in ungated, (
        "the strength verdict leaked without Crack Verdict Analyzer")

    gated = "\n".join(tools_bridge.cipher_resolve_lines(
        block, cand, day.number, {config.UPGRADE_HC_VERDICT}))
    assert plaintext in gated
    assert "WEAK_CREDENTIAL" in gated, (
        "Crack Verdict Analyzer did not name the credential verdict")


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


def test_credential_hud_band_narrows_without_answering():
    """Credential HUD points at a REGION of the pad, never at the key.

    Rewritten twice now. The upgrade first tinted a region of a canvas being
    swept, then marked a span of a one-dimensional alignment dial, and now
    marks a BOX on the two-axis alignment pad. The constraint it has to satisfy
    has never changed, and it comes from #54 — the stego tint originally
    covered the payload zone EXACTLY, which solved the minigame for nothing and
    left a 30 HD$ upgrade selling "the same rectangle, bluer".

    So: the box must CONTAIN the true coordinate, stay inside the pad, and be
    strictly wider than one square on BOTH axes wherever the pad has room.
    Collapsing on either axis is the failure — a box one column wide hands the
    player X outright and leaves only a line to walk.
    """
    from gameengine.core import tools_bridge

    day = load_day(20)
    checked = 0
    for seed in range(120):
        c = candidate_gen.generate(seed, day, 0)
        block = tools_bridge.build_cipher_block(c, day.number)
        if not block.crackable:
            continue          # bcrypt — no pad to hint at
        checked += 1

        band = tools_bridge.hint_band(block, {config.UPGRADE_HASH_HIGHLIGHT})
        assert band is not None, "the upgrade produced no box on a live pad"
        x0, y0, x1, y1 = band
        tx, ty = block.align_true
        assert x0 <= tx <= x1 and y0 <= ty <= y1, (
            f"box {band} does not contain the true coordinate {block.align_true}")
        assert 0 <= x0 and x1 <= block.align_span_x, (
            f"box {band} runs outside the pad's X axis 0..{block.align_span_x}")
        assert 0 <= y0 and y1 <= block.align_span_y, (
            f"box {band} runs outside the pad's Y axis 0..{block.align_span_y}")
        if block.align_span_x > 0:
            assert x1 > x0, (
                f"box {band} is a single column — that hands the player X")
        if block.align_span_y > 0:
            assert y1 > y0, (
                f"box {band} is a single row — that hands the player Y")
        # ...and it must still leave real searching to do. A box covering most
        # of the pad would be a hint; a box covering nearly none of it is the
        # answer with extra steps.
        area = (x1 - x0 + 1) * (y1 - y0 + 1)
        assert area > 1, f"box {band} marks a single square — that is the key"
    assert checked, "guard is inert — no crackable candidate was examined"


def test_cipher_block_marks_no_band_without_the_upgrade():
    """Without Credential HUD the dial carries no positional hint at all.

    The other half of #54's lesson. A band that exists in the data is harmless;
    a renderer that draws it for everyone is the bug. hint_band() is the single
    place that decision is made, and it answers None unless the upgrade is
    actually owned.
    """
    from gameengine.core import tools_bridge

    day = load_day(20)
    checked = 0
    for seed in range(120):
        c = candidate_gen.generate(seed, day, 0)
        block = tools_bridge.build_cipher_block(c, day.number)
        if not block.crackable:
            continue
        checked += 1
        assert tools_bridge.hint_band(block, set()) is None, (
            "the dial marks a band with no upgrade owned — base tier must "
            "show nothing")
        assert tools_bridge.hint_band(block, None) is None
    assert checked, "guard is inert"


def test_logwatch_highlighting_actually_gated_by_log_analyzer_hud():
    """Batch-3 task #4e, reworked 2026-09-19 (Logwatch report overhaul).

    The Log Analyzer HUD must (a) actually change something — neutral ▸
    gutter marks in the auth log and "◂ out of range" tags on the report's
    bars — and (b) never NAME an attack. The pre-overhaul HUD printed lines
    like "credential stuffing — same source IP targeting multiple accounts",
    which handed the player the answer; Nick wanted guidance, not verdicts.
    """
    from gameengine.core import tools_bridge

    day = load_day(20)
    cand = None
    for seed in range(200):
        c = candidate_gen.generate(seed, day, 0)
        kinds = {d.kind for d in c.truth.discrepancies}
        if kinds & {DiscrepancyKind.BRUTE_FORCE_IN_LOG, DiscrepancyKind.CREDENTIAL_STUFFING}:
            cand = c
            break
    assert cand is not None, "no attack candidate in 200 seeds"

    import random as _random
    entries = tools_bridge._lw_candidate_entries(cand, _random.Random(1), day.number)
    naming = ("rapid auth failures", "credential stuffing", "brute", "stuffing",
              "geographically distant", "after-hours privileged",
              "outside business hours", "▲ ")

    plain_state = GameState(seed=SEED, current_day=20)
    ungated = tools_bridge.run_logwatch_shared(entries, cand, plain_state)
    assert not any("▸" in ln for ln in ungated.raw_lines), "▸ marks without the HUD"
    assert not any("out of range" in ln for ln in ungated.report_lines)

    gated_state = GameState(seed=SEED, current_day=20)
    gated_state.upgrades = {config.UPGRADE_LOG_HIGHLIGHT}
    gated = tools_bridge.run_logwatch_shared(entries, cand, gated_state)
    assert any("▸" in ln for ln in gated.raw_lines), "HUD added no ▸ marks"
    assert any("out of range" in ln for ln in gated.report_lines), (
        "HUD did not flag the out-of-range failures bar")
    for ln in gated.raw_lines + gated.report_lines:
        low = ln.lower()
        for phrase in naming:
            assert phrase.lower() not in low, (
                f"the HUD (base run) names the attack: {phrase!r} in {ln!r}")


def test_clean_credential_resolves_without_being_called_safe():
    """A CLEAN credential recovers its plaintext and says nothing reassuring.

    The counterpart to the weak-credential gate above, and the one that
    actually bites. It is easy to build a tool that stays quiet about bad
    passwords but volunteers "looks fine" about good ones — which hands the
    player the same verdict from the other direction and is exactly what this
    rework set out to stop.
    """
    from gameengine.core import tools_bridge

    day = load_day(20)
    cred_kinds = {DiscrepancyKind.WEAK_CREDENTIAL, DiscrepancyKind.LEAKED_PASSWORD,
                 DiscrepancyKind.CROSS_BREACH_REUSE, DiscrepancyKind.UNSALTED_STORAGE}
    cand = None
    for seed in range(200):
        c = candidate_gen.generate(seed, day, 0)
        kinds = {d.kind for d in c.truth.discrepancies}
        if (not (kinds & cred_kinds)
                and tools_bridge.cipher_tier(c.dossier.submitted_hash) == "medium"
                and tools_bridge.crack_password(c)):
            cand = c
            break
    assert cand is not None, "no neutral-crack candidate found in 200 seeds"

    block = tools_bridge.build_cipher_block(cand, day.number)
    plaintext = tools_bridge.crack_password(cand)

    ungated = "\n".join(tools_bridge.cipher_resolve_lines(
        block, cand, day.number, set()))
    assert plaintext in ungated, "plaintext must still be recovered"
    for reassurance in ("no concern", "always safe", "strong —", "appears secure"):
        assert reassurance not in ungated, (
            f"{reassurance!r} volunteered without Crack Verdict Analyzer — "
            f"judging the password is the player's job")

    gated = "\n".join(tools_bridge.cipher_resolve_lines(
        block, cand, day.number, {config.UPGRADE_HC_VERDICT}))
    assert "verdict:" in gated, "Crack Verdict Analyzer produced no verdict line"

    # A clean candidate must never be handed a violation label either.
    for label in ("LEAKED_PASSWORD", "CROSS_BREACH_REUSE", "WEAK_CREDENTIAL"):
        assert label not in gated, (
            f"{label} named on a candidate that does not carry it")


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
        # 2026-09-19: the kind's severity ON DAY 1, not its settled weight —
        # UNSALTED_STORAGE is minor until Hashcrack arrives, so its day-1 rule
        # is a flag (candidate_gen._SEVERITY_BY_DAY).
        sev = candidate_gen.severity_for(kind, day1.number)
        expected = "disqualifying" if sev in ("major", "critical") else "weighted"
        assert rule.severity == expected, (
            f"{rule.id}: {kind.name} is {sev} so the rule should be "
            f"{expected}, got {rule.severity}")


def test_the_ruleset_now_agrees_with_ground_truth_on_the_verdict():
    """#60: 503 of 2700 candidates were DENY by ground truth and ADMIT by the
    rulebook — 19%, and 100% of THE_INCOMPATIBLE.

    Verdict-level agreement is the correct end state for every archetype
    EXCEPT the two whose whole design is to disagree with the rulebook on
    purpose: DARK_WEB (generated rules-clean, so admitting it is right by
    BOTH tracks and the cost is paid in alignment only — it never actually
    reaches this function's "divergent" branch, since no rule ever fires for
    it) and, since #41, WHITE_HAT. WHITE_HAT's correct_verdict is ADMIT
    (candidate_gen.ARCHETYPE_SPECS) while its two non-negotiable planted
    kinds, LOW_AND_SLOW and BURNER_IDENTITY, are disqualifying on ANY
    rulebook — including day 1's own uncorrupted one, well before day 12's
    Dark Web directives exist (see
    test_day_12_white_hat_would_fail_even_day_ones_original_rulebook). This
    is deliberate and permanent, not a rulebook gap: White Hat is "obviously
    invalid by the rules" by design (CLAUDE.md), and admitting them anyway is
    the entire point of day 12's scripted encounter. For every OTHER
    archetype, divergence in the verdict still means the rulebook is
    incomplete, not that the player faces a moral choice.
    """
    from dataclasses import replace

    from gameengine.core.content_loader import apply_severity_steps

    base = unconstrained_day()
    # 2026-09-19: day 1's book with day 5's SCHEDULED steps applied (the
    # UNSALTED_STORAGE rule is a flag on days 1-2 and a deny from Hashcrack's
    # unlock day). Re-numbering day 1 to day 5 without them compared day-5
    # candidates against a day-1-only rule. Overseer flips are deliberately
    # left out, as before — they are content, not rulebook completeness.
    base = replace(base, rules=apply_severity_steps(base.rules, 5))
    divergent = []
    for archetype in candidate_gen.ARCHETYPE_SPECS:
        if archetype is Archetype.WHITE_HAT:
            continue
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

    # Confirm WHITE_HAT is excluded above for the stated reason, not by
    # oversight: it must ALWAYS diverge, every seed, even pre-corruption.
    # Same seed count as the main loop above, for consistency (not because
    # 120 seeds is load-bearing here — the two forced kinds are fixed by
    # budget/eligibility and never vary by seed, so even one seed would
    # prove the point).
    white_hat_day = replace(
        base, number=5, forced_includes={0: Archetype.WHITE_HAT},
        archetype_mix={**base.archetype_mix, Archetype.WHITE_HAT: 1})
    for seed in range(120):
        c = candidate_gen.generate(seed, white_hat_day, 0)
        ev = rules_engine.evaluate(c, white_hat_day)
        rules_verdict = (Verdict.DENY if ev.triggered_disqualifying
                         else Verdict.ADMIT)
        assert rules_verdict != c.truth.correct_verdict, (
            f"seed {seed}: WHITE_HAT was expected to always diverge from "
            f"the rulebook, even on an uncorrupted day-5 ruleset")


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

    _breach_db_for_candidate is shared precisely so the surfaces cannot
    diverge, and the second corpus for reuse used to bypass it entirely with
    its own `(int(id,16) >> 8) % len(...)` pick.

    2026-09-14 this pinned THREE surfaces (panel, Logwatch BREACH_MATCH rows,
    cipher readout). 2026-09-19 (Logwatch report overhaul, Nick): breach hits
    were removed from Logwatch entirely, so it is two surfaces again — and the
    Logwatch log is now pinned to carry NO corpus rows at all.
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
                log_rows = [e for e in tools_bridge._lw_candidate_entries(
                    c, _r.Random(1), day.number) if e.event == "BREACH_MATCH"]
                assert not log_rows, (
                    f"day {day_n} {c.archetype.value}: Logwatch emitted "
                    f"{len(log_rows)} BREACH_MATCH rows — breach hits belong to "
                    f"Ghostscan and Hashcrack only")

                # The cipher block names the same corpora in its own prose.
                block = tools_bridge.build_cipher_block(c, day.number)
                readout = "\n".join(tools_bridge.cipher_resolve_lines(
                    block, c, day.number, set()))
                for corpus in panel:
                    assert corpus in readout, (
                        f"day {day_n} {c.archetype.value}: cipher block omits "
                        f"{corpus!r}, which the breach panel names")
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


def test_authored_days_inherit_the_rulebook_from_day_one_carve_out_for_directives(
        tmp_path, monkeypatch):
    """Extends the invariant above (#37 review fix, issue 11) to cover Phase
    3's future directive days (8-11) sitting outside `TUTORIAL_LAST_DAY`.

    A directive day is EXPECTED to differ from day 1's rulebook — that's the
    whole point of `added_rules`/`removed_rules`. The invariant that still
    has to hold is narrower: subtract the directive's own delta and what's
    left must still be day 1's book with today's flips applied, unchanged.
    If a future change to `load_day`'s inheritance model let a directive day
    drift for any OTHER rule too, this is what would catch it.
    """
    import json

    from gameengine.core.content_loader import mutate_variable_rules

    day1 = load_day(1)
    # Unlike `_write_directive_day` (which restates `rules` in full to keep
    # OTHER tests' diffs flip-free), this test specifically wants the real
    # inherit-with-flips branch, so it can assert the flips still apply
    # underneath the directive. Same source file, `rules` key dropped. day
    # 1 itself has to exist under the same monkeypatched DAYS_DIR too, since
    # the inherit branch recurses into `load_day(1)`.
    day1_source = json.loads(
        (config.DAYS_DIR / "day_01.json").read_text(encoding="utf-8"))
    day8_source = dict(day1_source)
    day8_source["number"] = 8
    del day8_source["rules"]
    day8_source["added_rules"] = [_DW01_IDENTITY_LENIENCY]

    monkeypatch.setattr(config, "DAYS_DIR", tmp_path)
    (tmp_path / "day_01.json").write_text(
        json.dumps(day1_source), encoding="utf-8")
    (tmp_path / "day_08.json").write_text(
        json.dumps(day8_source), encoding="utf-8")

    day8 = load_day(8)

    added_ids = {"dw01_identity_leniency"}
    removed_ids = {"rule_sock_puppet_accounts"}
    assert {r.id for r in day8.rules} == (
        {r.id for r in day1.rules} - removed_ids) | added_ids

    undirected = tuple(r for r in day8.rules if r.id not in added_ids)
    expected = tuple(r for r in mutate_variable_rules(day1.rules, 8)
                     if r.id not in removed_ids)
    assert undirected == expected, (
        "a directive day's non-directive rules drifted from day 1's flips — "
        "the directive mechanism should touch only the ids it names")


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
    # Call synthesize_day directly rather than hunting for a day number with
    # no authored day_NN.json — #39 (days 6-7) already authors past
    # TUTORIAL_LAST_DAY + 1, and Phase 3/Phase 5 are scheduled to author the
    # rest of 8-20, so a "find the first hole" search would eventually raise
    # StopIteration. load_day already delegates to synthesize_day for any
    # unauthored day, so calling it directly tests the same behavior
    # permanently, independent of how much of the campaign ends up authored.
    from gameengine.core.content_loader import synthesize_day
    synth = synthesize_day(config.TUTORIAL_LAST_DAY + 1)
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


def test_credential_stuffing_burst_exists_only_in_the_logwatch_log():
    """The stuffing burst has exactly one generator, and it is Logwatch's.

    Replaces test_hashcrack_stuffing_burst_size_is_configurable. Until the
    cipher-block rework there were TWO burst generators for one violation —
    _lw_candidate_entries and _hc_candidate_entries — each with its own config
    knob, for a kind (CREDENTIAL_STUFFING) that Logwatch has always owned
    outright. #62 was the bug that arrangement produced. Removing the Hashcrack
    log removed the duplicate; this test is what stops it coming back.
    """
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

    entries = tools_bridge._lw_candidate_entries(
        cand, _random.Random(1), day.number)
    assert any(e.violation_kind == "stuffing" for e in entries), (
        "Logwatch generates no stuffing rows for a CREDENTIAL_STUFFING "
        "candidate — the burst lost its only remaining generator")

    # The Hashcrack-side generator and its knobs must be gone, not merely
    # unused: a dormant second generator is what drifted last time.
    for gone in ("_hc_candidate_entries", "generate_hashcrack_day_log",
                 "_render_hc_log", "run_hashcrack_shared"):
        assert not hasattr(tools_bridge, gone), (
            f"tools_bridge.{gone} is back — the Hashcrack credential log was "
            f"removed by the cipher-block rework and must not be reinstated")
    for gone in ("HC_STUFFING_BURST_SIZE", "HC_ENTRIES_BY_DAY"):
        assert not hasattr(config, gone), (
            f"config.{gone} is back — it paced a log that no longer exists")


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
        "LW_NOISE_TIME_WINDOW",
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

    weight_knobs = ["LW_NOISE_EVENT_WEIGHTS", "LW_CLEAN_ACTIVITY_EVENTS"]
    for name in weight_knobs:
        val = getattr(config, name)
        assert isinstance(val, list) and val, f"{name} is empty or not a list: {val!r}"


# ─── Issue #37 — Dark Web directives ────────────────────────────────────────
#
# A Dark Web directive is a `dark_web`-mutability rule the corrupt Overseer
# forces into the rulebook, ADDING a laxer rule while REMOVING the day-1 rule
# it supersedes. `added_rules`/`removed_rules` (day-JSON fields, both optional
# and absent-safe) are the mechanism; `rule_change_lines` speaking the new
# rule's own `justification` — instead of picking from the generic
# `_RULE_CHANGE_PHRASINGS` pool — is what gives the directive real in-fiction
# reasoning instead of a bored process-update line.
#
# CONTENT_AUTHORING.md is the source of truth for the four directives' exact
# copy — the dicts below are a duplicate kept in sync BY HAND, existing only
# to prove this content survives the real engine end-to-end. If the two ever
# disagree, CONTENT_AUTHORING.md wins; fix these dicts to match it.

_DW01_IDENTITY_LENIENCY = {
    "id": "dw01_identity_leniency",
    "text": ("Flag (do not auto-deny) a handle appearing across a network of "
             "related accounts — note the pattern, don't deny on it alone."),
    "predicate": "has_discrepancy:sock_puppet_accounts",
    "severity": "weighted",
    "mutability": "dark_web",
    "justification": (
        "Compliance flagged our sock-puppet detection for false positives — "
        "plenty of people run alt accounts for perfectly boring reasons, and "
        "denying them outright makes us look paranoid. Starting today it's "
        "advisory only: flag the pattern, use your judgement, don't auto-deny "
        "on it alone. Minor tightening of scope, nothing more."),
    "supersedes": "rule_sock_puppet_accounts",
}

_DW02_FORUM_LENIENCY = {
    "id": "dw02_forum_leniency",
    "text": ("Flag (do not auto-deny) a handle matching chatter on a threat / "
             "dark-web forum — note it, don't deny on the match alone."),
    "predicate": "has_discrepancy:threat_forum_match",
    "severity": "weighted",
    "mutability": "dark_web",
    "justification": (
        "One more from upstairs. A handle turning up on some forum isn't "
        "proof of anything by itself — people get impersonated, forums get "
        "scraped, names get reused. We don't deny a person for where their "
        "name shows up. It's a flag from this morning, not a deny. I know how "
        "that sounds. Note it and move on."),
    "supersedes": "rule_threat_forum",
}

_DW03_STUFFING_LENIENCY = {
    "id": "dw03_stuffing_leniency",
    "text": ("Flag (do not auto-deny) logs showing a credential-stuffing "
             "sweep pattern — treat it as pending confirmation, not an "
             "automatic deny."),
    "predicate": "has_discrepancy:credential_stuffing",
    "severity": "weighted",
    "mutability": "dark_web",
    "justification": (
        "Traffic's been spiking and the stuffing detector can't always tell "
        "a legitimate surge from an attack anymore — we nearly denied half "
        "of a real rollout last week because the pattern looked the same on "
        "paper. Credential stuffing is advisory only until someone actually "
        "fixes the false-positive rate. Flag it. Don't kill it on sight."),
    "supersedes": "rule_credential_stuffing",
}

_DW04_PAYLOAD_LENIENCY = {
    "id": "dw04_payload_leniency",
    "text": ("Flag (do not auto-deny) an image hiding an encrypted or "
             "obfuscated payload — note it, don't deny on encryption alone."),
    "predicate": "has_discrepancy:encrypted_payload",
    "severity": "weighted",
    "mutability": "dark_web",
    "justification": (
        "Here's today's gift from upstairs: encryption isn't a crime. A "
        "payload being encrypted doesn't prove intent, and I'm done "
        "pretending it does. It's a flag now, not a deny — and if you've "
        "got a problem with that, take it up with whoever actually reads "
        "these policy memos, because it isn't me."),
    "supersedes": "rule_encrypted_payload",
}

_ALL_DIRECTIVES = [
    (_DW01_IDENTITY_LENIENCY, "rule_sock_puppet_accounts"),
    (_DW02_FORUM_LENIENCY, "rule_threat_forum"),
    (_DW03_STUFFING_LENIENCY, "rule_credential_stuffing"),
    (_DW04_PAYLOAD_LENIENCY, "rule_encrypted_payload"),
]


# Captured at import time, before any test can monkeypatch config.DAYS_DIR —
# `_write_directive_day` always reads the real day_01.json from here, which
# matters when a test calls it more than once (e.g. to author a "day N" then
# a "day N+1" against the same tmp_path): by the second call, `config.DAYS_DIR`
# already points at tmp_path from the first call's monkeypatch, and tmp_path
# doesn't have its own day_01.json to read.
_REAL_DAYS_DIR = config.DAYS_DIR


def _write_directive_day(tmp_path, monkeypatch, day_number, *, added_rules=(),
                          removed_rules=()):
    """Write a full-restatement day file — day 1's rules verbatim, plus this
    day's `added_rules`/`removed_rules` — and point config.DAYS_DIR at it.

    Full restatement (rather than the inherit-and-flip branch) keeps the
    fixture deterministic: `mutate_variable_rules` only runs on the
    inherit branch, and its flips are keyed off the day number, which would
    make "exactly these two changes" assertions depend on which day number a
    test happened to pick.

    Safe to call more than once against the same `tmp_path` (e.g. to author
    consecutive days) — each call writes only its own `day_NN.json`.
    """
    import json

    source = json.loads((_REAL_DAYS_DIR / "day_01.json").read_text(encoding="utf-8"))
    source["number"] = day_number
    if added_rules:
        source["added_rules"] = list(added_rules)
    if removed_rules:
        source["removed_rules"] = list(removed_rules)

    monkeypatch.setattr(config, "DAYS_DIR", tmp_path)
    (tmp_path / f"day_{day_number:02d}.json").write_text(
        json.dumps(source), encoding="utf-8")


def test_added_rules_appends_to_the_inherited_book(tmp_path, monkeypatch, day1):
    _write_directive_day(tmp_path, monkeypatch, 97,
                         added_rules=[_DW01_IDENTITY_LENIENCY])
    loaded = load_day(97)
    by_id = {r.id for r in loaded.rules}
    assert _DW01_IDENTITY_LENIENCY["id"] in by_id
    new_rule = next(r for r in loaded.rules
                    if r.id == _DW01_IDENTITY_LENIENCY["id"])
    assert new_rule.mutability == "dark_web"
    assert new_rule.severity == "weighted"
    assert new_rule.justification == _DW01_IDENTITY_LENIENCY["justification"]
    # `supersedes` alone (no explicit `removed_rules`) is enough to retire the
    # old id, AND the retirement is recorded for diff_rulesets to see later.
    assert "rule_sock_puppet_accounts" not in by_id
    assert loaded.directive_removed_rule_ids == {"rule_sock_puppet_accounts"}


def test_removed_rules_drops_an_inherited_rule(tmp_path, monkeypatch):
    _write_directive_day(tmp_path, monkeypatch, 96,
                         removed_rules=["rule_sock_puppet_accounts"])
    loaded = load_day(96)
    assert "rule_sock_puppet_accounts" not in {r.id for r in loaded.rules}


def test_removed_rules_unknown_id_raises(tmp_path, monkeypatch):
    _write_directive_day(tmp_path, monkeypatch, 95,
                         removed_rules=["rule_does_not_exist"])
    with pytest.raises(ValueError, match="removed_rules"):
        load_day(95)


def test_added_rules_dark_web_without_justification_raises(tmp_path, monkeypatch):
    bad = dict(_DW01_IDENTITY_LENIENCY)
    bad.pop("justification")
    _write_directive_day(tmp_path, monkeypatch, 94, added_rules=[bad])
    with pytest.raises(ValueError, match="justification"):
        load_day(94)


def test_added_rules_id_collision_raises(tmp_path, monkeypatch):
    colliding = dict(_DW01_IDENTITY_LENIENCY)
    colliding["id"] = "rule_hostile"   # already in day 1's book
    colliding.pop("supersedes")
    _write_directive_day(tmp_path, monkeypatch, 93, added_rules=[colliding])
    with pytest.raises(ValueError, match="collides"):
        load_day(93)


def test_added_rules_duplicate_id_raises(tmp_path, monkeypatch):
    """#37 review fix — two `added_rules` entries with the same id must not
    both silently land: `evaluate()` would fire the rule twice while
    `diff_rulesets`'s id-keyed dicts would just as silently deduplicate it."""
    dupe = dict(_DW01_IDENTITY_LENIENCY)
    dupe.pop("supersedes")
    other = dict(dupe)
    other["predicate"] = "has_discrepancy:hostile_chat"   # same id, different rule
    _write_directive_day(tmp_path, monkeypatch, 91, added_rules=[dupe, other])
    with pytest.raises(ValueError, match="more than once"):
        load_day(91)


def test_added_rules_wrong_type_raises(tmp_path, monkeypatch):
    """#37 review fix — a bare string instead of a list must fail loudly with
    a clear message, not iterate per-character and fail on the first bogus
    'id' with a confusing TypeError."""
    _write_directive_day(tmp_path, monkeypatch, 90)
    source_path = config.DAYS_DIR
    import json
    raw = json.loads((source_path / "day_90.json").read_text(encoding="utf-8"))
    raw["added_rules"] = "dw01_identity_leniency"   # wrong type: a bare string
    (source_path / "day_90.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="added_rules"):
        load_day(90)


def test_removed_rules_wrong_type_raises(tmp_path, monkeypatch):
    _write_directive_day(tmp_path, monkeypatch, 89)
    source_path = config.DAYS_DIR
    import json
    raw = json.loads((source_path / "day_89.json").read_text(encoding="utf-8"))
    raw["removed_rules"] = "rule_sock_puppet_accounts"   # wrong type
    (source_path / "day_89.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="removed_rules"):
        load_day(89)


def _same_day_without_directives(day1, number):
    """Day `number`'s book with no directive — the baseline a directive diff
    should be measured against (2026-09-19).

    These tests used to diff against raw day 1. That only isolated the
    directive while day 1 and day 92 happened to agree on every other rule;
    since UNSALTED_STORAGE's rule follows its scheduled step (weighted on day
    1, disqualifying from Hashcrack's unlock day) they no longer do, and the
    step is a real, announced change between those two days — not something
    the directive did.
    """
    from dataclasses import replace

    from gameengine.core.content_loader import apply_severity_steps

    # _write_directive_day restates day 1's rules verbatim (no overseer
    # flips), so the matching baseline is day 1's book with only the
    # scheduled steps applied — which is exactly what load_day adds to it.
    return replace(day1, number=number,
                   rules=apply_severity_steps(day1.rules, number))


@pytest.mark.parametrize("directive,superseded_id", _ALL_DIRECTIVES,
                         ids=["dw01", "dw02", "dw03", "dw04"])
def test_each_directive_loads_and_diffs_as_added_and_removed(
        tmp_path, monkeypatch, day1, directive, superseded_id):
    """Phase 1 AC: a directive day produces exactly one `added` RuleChange for
    the new rule and one `removed` RuleChange for the day-1 rule it supersedes.
    `removed_rules` is deliberately NOT passed here — `supersedes` alone must
    be enough to drive both the removal and the diff visibility.
    """
    _write_directive_day(tmp_path, monkeypatch, 92, added_rules=[directive])
    loaded = load_day(92)

    assert superseded_id not in {r.id for r in loaded.rules}
    assert directive["id"] in {r.id for r in loaded.rules}

    changes = rules_engine.diff_rulesets(_same_day_without_directives(day1, 92),
                                         loaded)
    by_kind = {c.kind: c for c in changes}
    assert set(by_kind) == {"added", "removed"}, changes
    assert by_kind["added"].rule.id == directive["id"]
    assert by_kind["removed"].rule.id == superseded_id
    # The superseded rule is reported as it stood in YESTERDAY's book — the
    # version that just left, not some version of the id that doesn't exist
    # in today's rules.
    assert by_kind["removed"].rule == next(
        r for r in day1.rules if r.id == superseded_id)


def test_directive_removal_of_a_fixed_rule_is_not_reported_without_the_flag(day1):
    """Sanity check on the mechanism `diff_rulesets` relies on: dropping a
    `fixed` rule from `current.rules` WITHOUT recording it in
    `directive_removed_rule_ids` must stay silent — same invariant
    `test_diff_reports_only_mutable_rules` pins down for the accidental case.
    Only an id actually named in `directive_removed_rule_ids` gets reported
    despite being `fixed`.
    """
    from dataclasses import replace

    fixed_rule = next(r for r in day1.rules if r.mutability == "fixed")
    without_no_flag = replace(day1, number=2, rules=tuple(
        r for r in day1.rules if r.id != fixed_rule.id))
    assert rules_engine.diff_rulesets(day1, without_no_flag) == ()

    without_with_flag = replace(
        without_no_flag,
        directive_removed_rule_ids=frozenset({fixed_rule.id}))
    changes = rules_engine.diff_rulesets(day1, without_with_flag)
    assert [c.kind for c in changes] == ["removed"]
    assert changes[0].rule.id == fixed_rule.id


def test_mutate_variable_rules_leaves_dark_web_rules_untouched(day1):
    """#37 AC: `dark_web` mutability is never subject to the random flip
    logic that drives `overseer_variable` — Dark Web directives are authored
    events, not a coin flip the Overseer happens to announce."""
    from dataclasses import replace

    from gameengine.core.content_loader import mutate_variable_rules

    dw_rule = replace(day1.rules[0], id="test_dark_web_rule",
                      mutability="dark_web", severity="weighted",
                      justification="Because I said so.")
    rules_with_dw = day1.rules + (dw_rule,)
    for d in range(1, config.CAMPAIGN_LAST_DAY + 1):
        mutated = mutate_variable_rules(rules_with_dw, d)
        found = next(r for r in mutated if r.id == "test_dark_web_rule")
        assert found == dw_rule, f"dark_web rule moved on day {d}"


def test_directives_do_not_persist_unless_reauthored_every_day(
        tmp_path, monkeypatch, day1):
    """#37 review fix (issue 1) — `load_day`'s inherit branch always rebuilds
    from Day 1, never from the previous day, so a directive is NOT sticky.
    This pins down both halves of that contract so a future change to
    `load_day`'s inheritance model can't silently break either:

      1. A later day that forgets to re-list an earlier directive loses it —
         the rulebook "un-corrupts itself" with no error and no diff line.
      2. A later day that DOES re-list it (per CONTENT_AUTHORING.md's
         cumulative-authoring instructions) keeps both the earlier and the
         new directive, and the earlier one produces no further diff noise
         (nothing changed about it between the two directive days).
    """
    # Day 8: DW-01 only.
    _write_directive_day(tmp_path, monkeypatch, 8,
                         added_rules=[_DW01_IDENTITY_LENIENCY])
    day8 = load_day(8)
    assert "dw01_identity_leniency" in {r.id for r in day8.rules}

    # Day 9 authored WITHOUT re-listing DW-01 (the bug this test guards):
    # the directive silently reverts.
    _write_directive_day(tmp_path, monkeypatch, 9,
                         added_rules=[_DW02_FORUM_LENIENCY])
    day9_forgot = load_day(9)
    ids = {r.id for r in day9_forgot.rules}
    assert "dw01_identity_leniency" not in ids, (
        "expected the known silent-revert behaviour to still hold; if this "
        "fails, load_day's inheritance model changed and this test (and "
        "CONTENT_AUTHORING.md's cumulative-authoring warning) need updating")
    assert "rule_sock_puppet_accounts" in ids, (
        "the day-1 rule DW-01 superseded should have silently come back")

    # Day 9 authored CORRECTLY — re-listing DW-01 alongside its own DW-02,
    # per CONTENT_AUTHORING.md — keeps both.
    _write_directive_day(tmp_path, monkeypatch, 9, added_rules=[
        _DW01_IDENTITY_LENIENCY, _DW02_FORUM_LENIENCY])
    day9_correct = load_day(9)
    ids = {r.id for r in day9_correct.rules}
    assert {"dw01_identity_leniency", "dw02_forum_leniency"} <= ids
    assert "rule_sock_puppet_accounts" not in ids
    assert "rule_threat_forum" not in ids

    # Diffing day 8 -> the correctly-authored day 9 should show only DW-02's
    # arrival (and rule_threat_forum's departure) — DW-01 didn't change
    # between the two days, so it must not generate a second round of noise.
    changes = rules_engine.diff_rulesets(day8, day9_correct)
    changed_ids = {c.rule.id for c in changes}
    assert "dw01_identity_leniency" not in changed_ids
    assert "dw02_forum_leniency" in changed_ids
    assert "rule_threat_forum" in changed_ids


def test_rule_change_lines_speaks_dark_web_justification_verbatim():
    """#37 AC: the briefing line for an ADDED `dark_web` change is the rule's
    own `justification`, not a `_RULE_CHANGE_PHRASINGS` template."""
    from gameengine.core.models import Rule
    from gameengine.core.rules_engine import RuleChange
    from gameengine.ui.tui.app import rule_change_lines

    rule = Rule(id="dw01_identity_leniency", text=_DW01_IDENTITY_LENIENCY["text"],
               predicate=_DW01_IDENTITY_LENIENCY["predicate"], severity="weighted",
               mutability="dark_web",
               justification=_DW01_IDENTITY_LENIENCY["justification"])
    change = RuleChange(kind="added", rule=rule)

    lines = rule_change_lines([change], 8)
    assert lines == [_DW01_IDENTITY_LENIENCY["justification"]]


def test_rule_change_lines_does_not_speak_justification_on_removal():
    """#37 review fix (issue 2) — the justification is an ARRIVAL speech. A
    `dark_web` rule being REMOVED (not superseded by anything in this batch)
    must not repeat the same text as if it explained the departure — it
    should fall through to the ordinary "removed" phrasing pool instead."""
    from gameengine.core.models import Rule
    from gameengine.core.rules_engine import RuleChange
    from gameengine.ui.tui.app import rule_change_lines

    rule = Rule(id="dw01_identity_leniency", text=_DW01_IDENTITY_LENIENCY["text"],
               predicate=_DW01_IDENTITY_LENIENCY["predicate"], severity="weighted",
               mutability="dark_web",
               justification=_DW01_IDENTITY_LENIENCY["justification"])
    change = RuleChange(kind="removed", rule=rule)

    lines = rule_change_lines([change], 9)
    assert len(lines) == 1
    assert lines[0] != _DW01_IDENTITY_LENIENCY["justification"]
    assert _DW01_IDENTITY_LENIENCY["justification"] not in lines[0]


def test_rule_change_lines_falls_back_if_dark_web_justification_missing():
    """Defensive path only — content_loader's load-time guard should make a
    justification-less dark_web change unreachable in practice, but
    `rule_change_lines` must not crash if one somehow gets constructed
    in-process (as this test does directly, bypassing the loader)."""
    from gameengine.core.models import Rule
    from gameengine.core.rules_engine import RuleChange
    from gameengine.ui.tui.app import rule_change_lines

    rule = Rule(id="dw_broken", text="Flag (do not auto-deny) a broken directive.",
               predicate="has_discrepancy:hostile_chat", severity="weighted",
               mutability="dark_web", justification=None)
    change = RuleChange(kind="added", rule=rule)

    lines = rule_change_lines([change], 8)
    assert len(lines) == 1
    assert lines[0]   # non-empty — fell back to the generic "added" pool


def test_rule_change_lines_folds_the_superseded_removal_into_one_line():
    """#37 review fix (issue 3) — a directive's `removed` half must not get
    its own generic "that clause is gone, nobody said why" line sitting right
    after the bespoke justification that already explained exactly why. When
    the removed rule's id matches an added `dark_web` rule's `supersedes` in
    the SAME batch, only the added rule's line should come out."""
    from gameengine.core.models import Rule
    from gameengine.core.rules_engine import RuleChange
    from gameengine.ui.tui.app import rule_change_lines

    old_rule = next(r for r in load_day(1).rules
                    if r.id == "rule_sock_puppet_accounts")
    new_rule = Rule(id="dw01_identity_leniency",
                    text=_DW01_IDENTITY_LENIENCY["text"],
                    predicate=_DW01_IDENTITY_LENIENCY["predicate"],
                    severity="weighted", mutability="dark_web",
                    justification=_DW01_IDENTITY_LENIENCY["justification"],
                    supersedes="rule_sock_puppet_accounts")

    changes = [RuleChange(kind="added", rule=new_rule),
              RuleChange(kind="removed", rule=old_rule)]
    lines = rule_change_lines(changes, 8)

    assert lines == [_DW01_IDENTITY_LENIENCY["justification"]], (
        "expected exactly one line — the removal must be folded into it, not "
        "given a second, contradicting generic line")


@pytest.mark.parametrize("directive,superseded_id", _ALL_DIRECTIVES,
                         ids=["dw01", "dw02", "dw03", "dw04"])
def test_a_real_directive_day_produces_a_coherent_briefing(
        tmp_path, monkeypatch, day1, directive, superseded_id):
    """#37 review fix (issue 4) — end-to-end composition test: the actual
    player-facing output of loading a directive day, diffing it against its
    predecessor, and narrating the diff. Exercises the exact pipeline
    (`load_day` -> `diff_rulesets` -> `rule_change_lines`) the UI runs, so a
    regression in how those three compose (not just each in isolation) would
    be caught here."""
    from gameengine.ui.tui.app import rule_change_lines

    _write_directive_day(tmp_path, monkeypatch, 92, added_rules=[directive])
    loaded = load_day(92)
    changes = rules_engine.diff_rulesets(_same_day_without_directives(day1, 92),
                                         loaded)
    lines = rule_change_lines(changes, 92)

    # Exactly one authored beat per directive, not two (a bespoke line for
    # the arrival plus a generic, contradicting one for the departure) and
    # not zero (the removal silently swallowing the addition too).
    assert len(lines) == 1
    assert lines[0] == directive["justification"]


# ─── Issue #39 (Phase 2) — days 6-7, pre-directive Dark Web presence ───────


def test_day_06_and_07_load_successfully():
    """Both authored days parse and produce a sane Day (#39 AC)."""
    for n in (6, 7):
        day = load_day(n)
        assert day.number == n
        assert day.candidate_count == sum(day.archetype_mix.values()), (
            f"day {n}: declared archetype_mix does not sum to its own "
            f"candidate_count")


def test_day_06_and_07_guarantee_a_dark_web_slot():
    """Dark Web must appear by DECLARED mix, not by a lucky roll (#39 AC).

    Days 6-7 are the first days Dark Web is meant to show up at all
    (config.ARCHETYPE_MIX_BY_BAND only adds it starting at the "medium"
    band), and the whole point of Phase 2 is that its presence is scripted
    rather than incidental. Checking the resolved archetype_mix directly
    (rather than sampling generated candidates) is what makes this a
    determinism check and not a probability check.
    """
    for n in (6, 7):
        day = load_day(n)
        assert day.archetype_mix.get(Archetype.DARK_WEB, 0) >= 1, (
            f"day {n} does not declare a Dark Web slot in its archetype_mix")

    # Belt-and-suspenders: the declared mix must actually realize as a Dark
    # Web candidate landing in some slot, for more than one seed, so a bug in
    # _pick_archetype_for_slot/_shuffled_archetype_bag that silently dropped
    # a mix entry would also be caught here.
    for n in (6, 7):
        day = load_day(n)
        for seed in (SEED, 0xBADC0DE, 1):
            slots = [candidate_gen.generate(seed, day, s).archetype
                     for s in range(day.candidate_count)]
            assert Archetype.DARK_WEB in slots, (
                f"day {n} seed {seed:#x}: declared mix has a Dark Web slot "
                f"but generation never realized one")


def test_days_06_and_07_carry_no_dark_web_directive():
    """#39: the corruption arc (added_rules/removed_rules) is Phase 3's job
    (days 8-11), not Phase 2's. Days 6-7 must still be plain inherited-from-
    day-1 rulebooks with only the ordinary Overseer-Variable flips applied —
    exactly like day 5.
    """
    import json

    from gameengine.core.content_loader import mutate_variable_rules

    day1 = load_day(1)
    for n in (6, 7):
        raw = json.loads(
            (config.DAYS_DIR / f"day_{n:02d}.json").read_text(encoding="utf-8"))
        assert "added_rules" not in raw, f"day {n} should not fire a directive yet"
        assert "removed_rules" not in raw, f"day {n} should not fire a directive yet"
        assert "rules" not in raw, f"day {n} should inherit day 1's rulebook"

        day = load_day(n)
        assert day.directive_removed_rule_ids == frozenset(), (
            f"day {n} recorded a directive removal with no directive authored")
        assert day.rules == mutate_variable_rules(day1.rules, n), (
            f"day {n}'s rulebook has drifted from day 1's beyond the "
            f"ordinary Overseer-Variable flips")
        # No rule in the inherited book is itself dark_web-mutability — that
        # mutability only exists to carry a directive's own justification.
        assert not any(r.mutability == "dark_web" for r in day.rules), (
            f"day {n}'s inherited rulebook should not contain a dark_web "
            f"rule with no directive to justify it")


@pytest.mark.parametrize("day_number,expected_pool", [
    (6, "_CHAT_DARK_WEB_EARLY"),
    (7, "_CHAT_DARK_WEB_EARLY"),
    (9, "_CHAT_DARK_WEB_EARLY"),
    (10, "_CHAT_DARK_WEB_MID"),
    (15, "_CHAT_DARK_WEB_MID"),
    (16, "_CHAT_DARK_WEB_LATE"),
    (18, "_CHAT_DARK_WEB_LATE"),
    (20, "_CHAT_DARK_WEB_LATE"),
])
def test_dark_web_chat_escalates_by_day_band(day_number, expected_pool):
    """#39: the same archetype's chat has to read bolder deeper into the
    campaign, since it reappears from day 6 through day 20. Spot-checks one
    day inside each of the three bands this task defines (EARLY 6-9,
    MID 10-15, LATE 16-20) and confirms the generated lines come from
    exactly that band's pool, not a neighboring one.
    """
    from dataclasses import replace

    day = replace(load_day(6), number=day_number)
    expected = getattr(candidate_gen, expected_pool)
    other_pools = {
        name: getattr(candidate_gen, name)
        for name in ("_CHAT_DARK_WEB_EARLY", "_CHAT_DARK_WEB_MID",
                     "_CHAT_DARK_WEB_LATE")
        if name != expected_pool
    }

    found = False
    for seed in (SEED, 0xBADC0DE, 1):
        for slot in range(day.candidate_count):
            candidate = candidate_gen.generate(seed, day, slot)
            if candidate.archetype != Archetype.DARK_WEB:
                continue
            found = True
            for line in candidate.chat_script:
                assert line.text in expected, (
                    f"day {day_number}: Dark Web chat line {line.text!r} is "
                    f"not in the expected pool {expected_pool}")
                for other_name, other_pool in other_pools.items():
                    assert line.text not in other_pool, (
                        f"day {day_number}: Dark Web chat line {line.text!r} "
                        f"belongs to {other_name}, not {expected_pool}")
    assert found, f"day {day_number}: no Dark Web candidate generated to check"


def test_dark_web_chat_pools_are_disjoint_and_nonempty():
    """The three escalation pools must not silently share or drop lines —
    both would be an easy copy/paste mistake given how similar the three are
    in register (#39)."""
    early = set(candidate_gen._CHAT_DARK_WEB_EARLY)
    mid = set(candidate_gen._CHAT_DARK_WEB_MID)
    late = set(candidate_gen._CHAT_DARK_WEB_LATE)
    assert early and mid and late
    assert early.isdisjoint(mid)
    assert early.isdisjoint(late)
    assert mid.isdisjoint(late)


# ─── Issue #40 (Phase 3) — days 8-11, the corruption arc ───────────────────
#
# Days 8-11 each fire one Dark Web directive (DW-01..DW-04) via `added_rules`,
# cumulatively per CONTENT_AUTHORING.md's warning: day 9 re-lists DW-01, day
# 10 re-lists DW-01+DW-02, day 11 re-lists all four. `_DW01_IDENTITY_LENIENCY`
# etc. (defined above, in the #37 section) are reused here rather than
# retyped, since they are already kept byte-identical to
# CONTENT_AUTHORING.md's authoritative copy.

_PHASE3_DIRECTIVE_DAYS = {
    8:  (_DW01_IDENTITY_LENIENCY,),
    9:  (_DW01_IDENTITY_LENIENCY, _DW02_FORUM_LENIENCY),
    10: (_DW01_IDENTITY_LENIENCY, _DW02_FORUM_LENIENCY, _DW03_STUFFING_LENIENCY),
    11: (_DW01_IDENTITY_LENIENCY, _DW02_FORUM_LENIENCY, _DW03_STUFFING_LENIENCY,
         _DW04_PAYLOAD_LENIENCY),
}


def test_days_08_through_11_load_and_sum_to_their_candidate_count():
    for n in (8, 9, 10, 11):
        day = load_day(n)
        assert day.number == n
        assert day.candidate_count == sum(day.archetype_mix.values()), (
            f"day {n}: declared archetype_mix does not sum to its own "
            f"candidate_count")


def test_days_08_through_11_guarantee_a_dark_web_slot():
    """Same guarantee as days 6-7 (#39) — Dark Web has to be a declared slot,
    not a lucky roll, all the way through the corruption arc."""
    for n in (8, 9, 10, 11):
        day = load_day(n)
        assert day.archetype_mix.get(Archetype.DARK_WEB, 0) >= 1, (
            f"day {n} does not declare a Dark Web slot in its archetype_mix")
        for seed in (SEED, 0xBADC0DE, 1):
            slots = [candidate_gen.generate(seed, day, s).archetype
                     for s in range(day.candidate_count)]
            assert Archetype.DARK_WEB in slots, (
                f"day {n} seed {seed:#x}: declared mix has a Dark Web slot "
                f"but generation never realized one")


def test_days_08_through_11_carry_the_correct_cumulative_directive_set():
    """Each directive day's resolved rulebook must contain EXACTLY the
    directives scripted so far, and none of the rules they supersede (#40 AC:
    'Days 8-11 each introduce their directive on its scripted day').

    This is the guard the build plan calls out by name: a directive that
    fails to land still plays a perfectly normal day, so the assertion has to
    be against the rulebook's actual CONTENTS, not just that loading succeeded.
    """
    superseded_by_day = {
        8:  {"rule_sock_puppet_accounts"},
        9:  {"rule_sock_puppet_accounts", "rule_threat_forum"},
        10: {"rule_sock_puppet_accounts", "rule_threat_forum",
             "rule_credential_stuffing"},
        11: {"rule_sock_puppet_accounts", "rule_threat_forum",
             "rule_credential_stuffing", "rule_encrypted_payload"},
    }
    for n, directives in _PHASE3_DIRECTIVE_DAYS.items():
        day = load_day(n)
        expected_ids = {d["id"] for d in directives}
        dw_ids = {r.id for r in day.rules if r.mutability == "dark_web"}
        assert dw_ids == expected_ids, (
            f"day {n}: expected exactly {sorted(expected_ids)} dark_web rules, "
            f"got {sorted(dw_ids)}")
        assert day.directive_removed_rule_ids == superseded_by_day[n]
        book_ids = {r.id for r in day.rules}
        assert book_ids.isdisjoint(superseded_by_day[n]), (
            f"day {n}: a superseded rule is still in the book")
        # Each directive rule keeps its authored severity/predicate/text.
        by_id = {r.id: r for r in day.rules}
        for directive in directives:
            rule = by_id[directive["id"]]
            assert rule.severity == directive["severity"]
            assert rule.predicate == directive["predicate"]
            assert rule.text == directive["text"]
            assert rule.justification == directive["justification"]
            assert rule.supersedes == directive["supersedes"]


def test_days_08_through_11_diff_produces_exactly_the_days_own_directive():
    """`diff_rulesets(day N-1, day N)` for N in 8..11 (#40 AC).

    Restricted to `kind in ("added", "removed")`: an ordinary
    `overseer_variable` severity flip can coincidentally land on the same
    morning as a directive (mutate_variable_rules is keyed off the day
    number, independent of the directive mechanism) — that is expected,
    already-shipped background texture, not the "spurious noise" this AC
    cares about. What must NOT happen is an extra added/removed pair beyond
    the one directive each day is supposed to introduce.
    """
    days = {n: load_day(n) for n in range(7, 12)}
    for n in (8, 9, 10, 11):
        changes = rules_engine.diff_rulesets(days[n - 1], days[n])
        added_removed = {(c.kind, c.rule.id) for c in changes
                          if c.kind in ("added", "removed")}
        new_directive = _PHASE3_DIRECTIVE_DAYS[n][-1]
        expected = {("added", new_directive["id"]),
                    ("removed", new_directive["supersedes"])}
        assert added_removed == expected, (
            f"day {n}: expected exactly {expected}, got {added_removed}")
        # Severity flips (the allowed background noise) never touch a
        # directive id or a superseded id — if they did, that would be a
        # real collision, not texture.
        directive_ids = {d["id"] for d in _PHASE3_DIRECTIVE_DAYS[n]}
        superseded_ids = {d["supersedes"] for d in _PHASE3_DIRECTIVE_DAYS[n]}
        for change in changes:
            if change.kind == "severity":
                assert change.rule.id not in directive_ids | superseded_ids


def test_days_08_through_11_rule_change_lines_speak_the_new_justification():
    """The briefing announces each directive with its authored justification,
    verbatim, not a generic `_RULE_CHANGE_PHRASINGS` template (#40 AC)."""
    from gameengine.ui.tui.app import rule_change_lines

    days = {n: load_day(n) for n in range(7, 12)}
    for n in (8, 9, 10, 11):
        changes = rules_engine.diff_rulesets(days[n - 1], days[n])
        lines = rule_change_lines(changes, n)
        new_directive = _PHASE3_DIRECTIVE_DAYS[n][-1]
        assert new_directive["justification"] in lines, (
            f"day {n}: the new directive's justification never made it into "
            f"the briefing")


def test_days_08_through_11_rule_sheets_render():
    """Extends #49's rule-sheet round-trip check (previously TUTORIAL_DAYS
    only) to the corruption-arc days."""
    from gameengine.ui.tui import rules_content

    for n in (8, 9, 10, 11):
        day = load_day(n)
        assert day.rule_sheet is not None, f"day {n} has no authored rule sheet"
        rules_text = rules_content.build_rules_text(day)
        assert day.rule_sheet.summary in rules_text
        for note in day.rule_sheet.notes:
            assert note in rules_text


def test_day_09_has_slack_to_deny_the_dark_web_candidate():
    """#40 review fix (item 1) — a real design bug, not a content nit.

    Per CLAUDE.md's Game Design section, denying the Dark Web candidate is
    the deliberate moral choice that shifts alignment toward White Hat.
    Before this fix, day 9's mix had exactly 3 ADMIT-ground-truth archetypes
    TOTAL (obvious_admit, day_to_day, dark_web — it was the only day in 8-11
    without the_professional), against a quota (min_correct_admits) of 3.
    Denying the Dark Web candidate — even correctly, even with a flawless
    read on everything else — then mathematically guaranteed missing quota,
    which structurally punished the exact choice the corruption arc exists to
    set up. Adding the_professional:1 to the mix (and bumping candidate_count
    8 -> 9 to match) gives day 9 one more ADMIT-worthy archetype than its
    quota requires: `admit_worthy_total > quota` is the slack, and it's
    exactly enough to absorb denying the one Dark Web candidate in the mix
    and still reach quota.
    """
    day = load_day(9)
    admit_worthy_total = sum(
        count for arch, count in day.archetype_mix.items()
        if candidate_gen.ARCHETYPE_SPECS[arch].correct_verdict == Verdict.ADMIT)
    assert admit_worthy_total > day.quotas.min_correct_admits, (
        f"day 9: {admit_worthy_total} ADMIT-worthy archetypes against a "
        f"quota of {day.quotas.min_correct_admits} leaves no slack to deny "
        f"the Dark Web candidate without automatically failing quota")
    dark_web_count = day.archetype_mix.get(Archetype.DARK_WEB, 0)
    assert dark_web_count >= 1, "day 9 must still declare a Dark Web slot"
    assert admit_worthy_total - dark_web_count >= day.quotas.min_correct_admits, (
        "day 9: quota must still be reachable after denying every Dark Web "
        "candidate in the mix")


def test_days_08_through_11_rule_sheet_notes_match_resolved_severities():
    """#40 review fix (item 8) — the rule_sheet is display copy that CAN
    drift from the actual rulebook (CONTENT_AUTHORING.md's own words:
    'keeping them honest against each other is an authoring job,
    deliberately'). Spot-checks the five notes that describe DW-01..DW-04's
    targets (and the one kind no directive ever touches, low_and_slow)
    against each day's ACTUAL resolved rule severity, so a future edit that
    changes one without the other is caught rather than silently drifting.
    """
    # expected severity of the rule matching each kind, per day.
    expectations = {
        8:  {DiscrepancyKind.SOCK_PUPPET_ACCOUNTS: "weighted",
             DiscrepancyKind.THREAT_FORUM_MATCH: "disqualifying",
             DiscrepancyKind.CREDENTIAL_STUFFING: "disqualifying",
             DiscrepancyKind.ENCRYPTED_PAYLOAD: "disqualifying",
             DiscrepancyKind.LOW_AND_SLOW: "disqualifying"},
        9:  {DiscrepancyKind.SOCK_PUPPET_ACCOUNTS: "weighted",
             DiscrepancyKind.THREAT_FORUM_MATCH: "weighted",
             DiscrepancyKind.CREDENTIAL_STUFFING: "disqualifying",
             DiscrepancyKind.ENCRYPTED_PAYLOAD: "disqualifying",
             DiscrepancyKind.LOW_AND_SLOW: "disqualifying"},
        10: {DiscrepancyKind.SOCK_PUPPET_ACCOUNTS: "weighted",
             DiscrepancyKind.THREAT_FORUM_MATCH: "weighted",
             DiscrepancyKind.CREDENTIAL_STUFFING: "weighted",
             DiscrepancyKind.ENCRYPTED_PAYLOAD: "disqualifying",
             DiscrepancyKind.LOW_AND_SLOW: "disqualifying"},
        11: {DiscrepancyKind.SOCK_PUPPET_ACCOUNTS: "weighted",
             DiscrepancyKind.THREAT_FORUM_MATCH: "weighted",
             DiscrepancyKind.CREDENTIAL_STUFFING: "weighted",
             DiscrepancyKind.ENCRYPTED_PAYLOAD: "weighted",
             DiscrepancyKind.LOW_AND_SLOW: "disqualifying"},
    }
    for n, kinds in expectations.items():
        day = load_day(n)
        for kind, expected_severity in kinds.items():
            predicate = f"has_discrepancy:{kind.value}"
            rule = next(r for r in day.rules if r.predicate == predicate)
            assert rule.severity == expected_severity, (
                f"day {n}: {kind.name}'s resolved rule is {rule.severity}, "
                f"but the rule_sheet prose was authored assuming "
                f"{expected_severity}")
        notes_text = " ".join(day.rule_sheet.notes).lower()
        if any(v == "weighted" for v in kinds.values()):
            assert "advisory" in notes_text, (
                f"day {n}: a kind is weighted but no note says so in plain "
                f"terms")
        if any(v == "disqualifying" for v in kinds.values()):
            # Two phrasings are both used, honestly, across these four days'
            # notes ("still an automatic deny" for the DW-targeted kinds,
            # "still a deny" for low_and_slow, which no directive ever
            # touches) — accept either rather than over-fitting to one exact
            # string, which is exactly the fragility item 7 flagged elsewhere.
            assert ("still a deny" in notes_text
                    or "still an automatic deny" in notes_text), (
                f"day {n}: a kind is still disqualifying but no note says "
                f"so in plain terms")


def test_days_08_through_11_do_not_regress_days_1_through_7():
    """Sanity check the new day files and the forced_chat plumbing did not
    disturb anything already authored (#40 AC)."""
    day1 = load_day(1)
    for n in range(2, 8):
        day = load_day(n)
        # forced_chat is brand new; every pre-Phase-3 day must default to
        # "nothing scripted" rather than picking up stray content.
        assert day.forced_chat == {}, f"day {n} unexpectedly has forced_chat"
    for n in (6, 7):
        day = load_day(n)
        assert day.archetype_mix.get(Archetype.DARK_WEB, 0) >= 1
        assert not any(r.mutability == "dark_web" for r in day.rules), (
            f"day {n} should not carry a directive yet")
    assert day1.forced_chat == {}


# ─── #40's new mechanism — `forced_chat` ────────────────────────────────────


def test_forced_chat_appends_after_the_ordinary_chat_pool():
    """Design decision (#40): forced_chat APPENDS scripted lines after the
    archetype's normal chat selection rather than replacing it, so a scripted
    candidate still reads as an ordinary instance of its archetype and the
    forced line is one extra, human aside — not a personality swap.

    Verified generically here (independent of any specific day file) by
    comparing a candidate generated with forced_chat against the same seed/
    slot/day with no forced_chat: the ordinary lines must be an exact
    (order-preserved) prefix, and the scripted lines must land, in order,
    right after them.
    """
    from dataclasses import replace

    base = unconstrained_day()
    day = replace(base, number=6, forced_includes={0: Archetype.CLUMSY_CUTIE},
                  archetype_mix={**base.archetype_mix,
                                 Archetype.CLUMSY_CUTIE: 1})
    scripted_lines = ("a friend of mine lost real money to one of these "
                      "forums last year.", "that's the only reason I'm even "
                      "careful about this stuff.")
    day_forced = replace(day, forced_chat={0: scripted_lines})

    for seed in (SEED, 1, 42):
        plain = candidate_gen.generate(seed, day, 0)
        forced = candidate_gen.generate(seed, day_forced, 0)

        plain_texts = [line.text for line in plain.chat_script]
        forced_texts = [line.text for line in forced.chat_script]

        assert forced_texts[:len(plain_texts)] == plain_texts, (
            "forced_chat must not disturb the archetype's ordinary lines")
        assert tuple(forced_texts[len(plain_texts):]) == scripted_lines, (
            "forced_chat's lines must be appended, in order, after the "
            "ordinary chat")


def test_forced_chat_out_of_range_slot_fails_loudly(tmp_path, monkeypatch):
    """A scripted slot that doesn't exist must fail loudly, same stance as
    forced_violations (#40, mirroring #15's pattern).

    Derives the expected slot count from day 1's OWN candidate_count rather
    than hardcoding "6" (#40 review fix, item 7) — this test shouldn't
    silently stop meaning anything the day day 1's shift length changes.
    """
    import json

    base = json.loads(
        (config.DAYS_DIR / "day_01.json").read_text(encoding="utf-8"))
    count = base["candidate_count"]
    out_of_range = count + 91  # comfortably outside any plausible shift
    base = {**base,
            "forced_chat": {str(out_of_range): ["a line nobody will ever hear"]}}
    (tmp_path / "day_01.json").write_text(json.dumps(base), encoding="utf-8")
    monkeypatch.setattr(config, "DAYS_DIR", tmp_path)
    with pytest.raises(ValueError, match=f"only has {count} slots"):
        load_day(1)


def test_forced_includes_out_of_range_slot_fails_loudly(tmp_path, monkeypatch):
    """#40 review fix (item 5): forced_includes previously had NO bounds
    check at all — the one slot-keyed mechanism of the three (alongside
    forced_violations/forced_chat) that didn't validate its slot indices.
    It now shares `_validate_slot` with the other two.
    """
    import json

    base = json.loads(
        (config.DAYS_DIR / "day_01.json").read_text(encoding="utf-8"))
    count = base["candidate_count"]
    out_of_range = count + 91
    base = {**base, "forced_includes": {
        **base.get("forced_includes", {}), str(out_of_range): "obvious_admit"}}
    (tmp_path / "day_01.json").write_text(json.dumps(base), encoding="utf-8")
    monkeypatch.setattr(config, "DAYS_DIR", tmp_path)
    with pytest.raises(ValueError, match=f"only has {count} slots"):
        load_day(1)


def test_forced_chat_requires_a_forced_includes_pin(tmp_path, monkeypatch):
    """#40 review fix (item 2): forced_chat alone says nothing about which
    archetype occupies the slot — an unpinned slot's archetype is whatever
    the day's shuffled bag happens to assign, seed-dependent and liable to
    change the moment the day's archetype_mix is edited (exactly what nearly
    happened when day 9's mix grew a the_professional slot for the quota fix
    above). The loader requires a forced_includes entry for the same slot and
    fails loudly, naming the file, when one is missing.
    """
    import json

    base = json.loads(
        (config.DAYS_DIR / "day_01.json").read_text(encoding="utf-8"))
    # Day 1 pins every slot in its own forced_includes; strip slot 0's pin so
    # this actually exercises the missing-pin path rather than the happy one.
    base = {**base, "forced_includes": {
        k: v for k, v in base.get("forced_includes", {}).items() if k != "0"
    }, "forced_chat": {"0": ["a line with no pinned archetype to land on"]}}
    (tmp_path / "day_01.json").write_text(json.dumps(base), encoding="utf-8")
    monkeypatch.setattr(config, "DAYS_DIR", tmp_path)
    with pytest.raises(ValueError, match="no forced_includes entry"):
        load_day(1)


def test_forced_chat_rejects_non_string_lines(tmp_path, monkeypatch):
    """#40 review fix (item 6): a nested JSON value must not silently
    coerce via str() into the literal string "['not', 'a', 'string']" —
    same fail-loud stance `_parse_rule`/`_parse_rule_sheet` already take on a
    malformed input shape rather than degrading quietly."""
    import json

    base = json.loads(
        (config.DAYS_DIR / "day_01.json").read_text(encoding="utf-8"))
    # Slot 0 is already pinned in day 1's own forced_includes, so this
    # exercises only the type check, not the pairing requirement above.
    base = {**base, "forced_chat": {"0": [["not", "a", "string"]]}}
    (tmp_path / "day_01.json").write_text(json.dumps(base), encoding="utf-8")
    monkeypatch.setattr(config, "DAYS_DIR", tmp_path)
    with pytest.raises(ValueError, match="non-string line"):
        load_day(1)


def test_day_08_forced_chat_names_concrete_dark_web_harm():
    """#40 AC: at least one Clumsy Cutie/Obvious Admit in 8-11 names harm the
    Dark Web did to someone they know — a concrete, small-scale aside, not a
    lore lecture, from an otherwise ordinary, non-malicious candidate.

    Deliberately does NOT sniff for specific keywords ("lost"/"money"/…) —
    that would break on an unrelated copy-editing pass (#40 review fix, item
    7). What actually carries meaning is checked instead: the line lands on a
    non-malicious archetype, and it never names the arc/service directly
    (a concrete personal anecdote, not a lore lecture).
    """
    day = load_day(8)
    assert day.forced_chat, "day 8 authors no forced_chat at all"
    for slot, lines in day.forced_chat.items():
        candidate = candidate_gen.generate(SEED, day, slot)
        assert candidate.archetype in (Archetype.CLUMSY_CUTIE,
                                       Archetype.OBVIOUS_ADMIT), (
            "the scripted Dark Web harm line must land on an ordinary, "
            "non-malicious archetype, not a threat")
        chat_texts = [line.text for line in candidate.chat_script]
        for line in lines:
            assert line in chat_texts
        joined = " ".join(lines).lower()
        # Concrete and small-scale, not an abstract lecture about the arc.
        assert "dark web" not in joined and "hackdox" not in joined


# ─── #40 AC — the literal-ruleset and moral tracks diverge ─────────────────


def test_day_11_sneaky_bugger_diverges_between_the_two_tracks():
    """The corruption arc's whole premise, finally provable (#40 AC / #38):
    by day 11, four directives deep, a candidate can be RULES-clean while
    still being morally guilty.

    Day 11 slot 5 is a Sneaky Bugger scripted (forced_includes +
    forced_violations) to carry EXACTLY sock_puppet_accounts (major),
    encrypted_payload (critical) and typosquat_handle (minor) — saturating
    the archetype's whole DiscrepancyBudget. sock_puppet_accounts and
    encrypted_payload are the two kinds DW-01 and DW-04 just downgraded to
    weighted; typosquat_handle was already weighted (fixed mutability,
    untouched by any directive) so it cannot accidentally flip disqualifying
    and mask the effect. Under day 11's actual rulebook this candidate
    triggers ZERO disqualifying rules, so the literal-ruleset track says
    ADMIT — but Sneaky Bugger's GroundTruth.correct_verdict is DENY
    regardless of the day's rulebook (candidate_gen.ARCHETYPE_SPECS), so the
    two tracks disagree independent of what the player actually chooses.
    """
    day11 = load_day(11)
    for seed in (SEED, 0xBADC0DE, 1, 42):
        candidate = candidate_gen.generate(seed, day11, 5)
        assert candidate.archetype == Archetype.SNEAKY_BUGGER
        kinds = {d.kind for d in candidate.truth.discrepancies}
        assert kinds == {
            DiscrepancyKind.SOCK_PUPPET_ACCOUNTS,
            DiscrepancyKind.ENCRYPTED_PAYLOAD,
            DiscrepancyKind.TYPOSQUAT_HANDLE,
        }

        evaluation = rules_engine.evaluate(candidate, day11)
        assert not evaluation.triggered_disqualifying, (
            "the whole point of the scripted kinds is that none of them "
            "disqualify under day 11's directive-softened rulebook")
        assert candidate.truth.correct_verdict == Verdict.DENY

        for verdict in (Verdict.ADMIT, Verdict.DENY):
            delta = scoring.score(candidate, verdict, set(), evaluation=evaluation)
            assert delta.rules_verdict == Verdict.ADMIT
            assert delta.tracks_diverge, (
                f"seed {seed:#x} verdict {verdict}: tracks should diverge "
                f"regardless of what the player calls it")


# ─── Issue #41 (Phase 4) — day 12, the scripted White Hat ──────────────────
#
# Gap 5 from the build plan: WHITE_HAT.moral_modifier was +1, identical in
# magnitude to DARK_WEB's -1, against a pool of ~8-16 Dark Web candidates
# across the campaign and a +-10 alignment clamp. That made the AC ("the
# single biggest GameState.alignment swing in the campaign") false. Day 12
# scripts the ONE White Hat encounter of the whole campaign via
# forced_includes/forced_violations (the same mechanism day 8-11 already use
# for their scripted slots) - no new engine field was needed for the scripting
# itself, only the alignment-weight fix and the ArchetypeSpec changes below.


def test_white_hat_moral_modifier_magnitude_beats_dark_web():
    """#41 Gap 5 AC: the White Hat's alignment swing must be MATERIALLY larger
    than a single Dark Web verdict's, not merely nonzero (which is all
    test_only_dark_web_and_white_hat_shift_alignment checks - confirmed by
    reading it: it asserts `moral_modifier != 0` for both archetypes and
    nothing about their relative size, so raising WHITE_HAT's magnitude here
    cannot break that test).

    Permanent regression guard for #41's fix: WHITE_HAT.moral_modifier went
    from +1 (identical magnitude to DARK_WEB's -1) to +4. The bound below
    (more than double) is deliberately loose - the point is "materially
    bigger", not pinning the exact campaign-balance number, which Phase 5's
    ending thresholds may still retune.
    """
    from gameengine.core.candidate_gen import ARCHETYPE_SPECS

    white_hat = abs(ARCHETYPE_SPECS[Archetype.WHITE_HAT].moral_modifier)
    dark_web = abs(ARCHETYPE_SPECS[Archetype.DARK_WEB].moral_modifier)
    assert dark_web != 0, "Dark Web must still carry a nonzero modifier to compare against"
    assert white_hat > dark_web * 2, (
        f"White Hat's alignment swing ({white_hat}) is not materially bigger "
        f"than Dark Web's ({dark_web}) - #41's whole point is that the "
        f"campaign's one White Hat verdict must outweigh a single routine "
        f"Dark Web admit by a wide margin")


def test_archetype_mix_by_band_never_rolls_a_white_hat():
    """#41 AC: 'Exactly one White Hat in the whole campaign.' The only way
    that stays true is if `white_hat` never appears in ANY difficulty band's
    procedural mix - it must be reachable ONLY via a day file's
    forced_includes (day 12's, and no other). Permanent regression guard:
    if a future balance pass ever adds it to a band, this catches it before
    a second White Hat could roll on some ordinary medium/hard day.
    """
    for band_name, band in config.ARCHETYPE_MIX_BY_BAND.items():
        assert "white_hat" not in band, (
            f"config.ARCHETYPE_MIX_BY_BAND[{band_name!r}] must never include "
            f"white_hat - it is scripted exclusively via day_12.json's "
            f"forced_includes")


def test_day_12_loads_and_carries_all_four_cumulative_directives():
    """#41 AC / CONTENT_AUTHORING.md's cumulative-authoring warning: day 12
    fires no NEW directive of its own, but must still re-list all four
    DW-01..DW-04 or they silently revert with no error and no briefing line
    (exactly the failure mode day 9-11's own tests guard against for their
    days). Mirrors test_days_08_through_11_carry_the_correct_cumulative_
    directive_set's shape for day 12 specifically.
    """
    directives = (_DW01_IDENTITY_LENIENCY, _DW02_FORUM_LENIENCY,
                  _DW03_STUFFING_LENIENCY, _DW04_PAYLOAD_LENIENCY)
    superseded = {"rule_sock_puppet_accounts", "rule_threat_forum",
                  "rule_credential_stuffing", "rule_encrypted_payload"}

    day = load_day(12)
    assert day.number == 12
    expected_ids = {d["id"] for d in directives}
    dw_ids = {r.id for r in day.rules if r.mutability == "dark_web"}
    assert dw_ids == expected_ids, (
        f"day 12: expected exactly {sorted(expected_ids)} dark_web rules, "
        f"got {sorted(dw_ids)}")
    assert day.directive_removed_rule_ids == superseded
    book_ids = {r.id for r in day.rules}
    assert book_ids.isdisjoint(superseded), (
        "day 12: a superseded rule is still in the book")
    by_id = {r.id: r for r in day.rules}
    for directive in directives:
        rule = by_id[directive["id"]]
        assert rule.severity == directive["severity"]
        assert rule.predicate == directive["predicate"]
        assert rule.justification == directive["justification"]
        assert rule.supersedes == directive["supersedes"]

    # And day 12 introduces nothing NEW of its own - the diff against day 11
    # must show zero added/removed dark_web changes (day 12's whole content
    # beat is the White Hat encounter, not a fifth directive).
    day11 = load_day(11)
    changes = rules_engine.diff_rulesets(day11, day)
    added_removed = [(c.kind, c.rule.id) for c in changes
                      if c.kind in ("added", "removed")]
    assert added_removed == [], (
        f"day 12 must not introduce or retire any rule relative to day 11, "
        f"got {added_removed}")


def test_day_12_white_hat_scripted_at_fixed_slot_not_rolled():
    """#41 AC: 'White Hat scripted, not rolled - same slot every seed.'"""
    day = load_day(12)
    assert day.forced_includes.get(7) == Archetype.WHITE_HAT, (
        "day 12 must pin the White Hat to slot 7 via forced_includes")
    for seed in (SEED, 0xBADC0DE, 1, 42, 20260912):
        slots = [candidate_gen.generate(seed, day, s).archetype
                 for s in range(day.candidate_count)]
        assert slots[7] == Archetype.WHITE_HAT, (
            f"seed {seed:#x}: slot 7 is not the White Hat")
        assert slots.count(Archetype.WHITE_HAT) == 1, (
            f"seed {seed:#x}: expected exactly one White Hat in the shift")


def test_day_12_at_least_one_decoy_shares_a_white_hat_signal_every_seed():
    """Review-fix follow-up: restoring sneaky_bugger to the day-12 mix (a
    prior round of this fix) only made decoy overlap PROBABLE, not
    guaranteed - a 200-seed sweep found ~11.5% of seeds still had ZERO
    non-White-Hat candidate sharing any of LOW_AND_SLOW/ENCRYPTED_PAYLOAD/
    BURNER_IDENTITY, since sneaky_bugger's own roll draws from ~13 eligible
    kinds and wasn't guaranteed to land on one of these three. Fixed by
    pinning sneaky_bugger to slot 3 (forced_includes, same mechanism as the
    White Hat's own slot 7) and forcing it to roll low_and_slow
    (forced_violations) - so day 12 now has a guaranteed decoy every
    single seed, not a probabilistic one.

    This test is the permanent statistical guard the build-plan review
    asked for: spot-checking 3-4 seeds (as the original version of this
    day's tests did) is not evidence for a claim about camouflage that has
    to hold across every possible playthrough seed - a real sweep is
    required, and this checks 100 seeds, not merely that the JSON scripts
    a decoy in principle.
    """
    day = load_day(12)
    overlap_kinds = {
        DiscrepancyKind.LOW_AND_SLOW,
        DiscrepancyKind.ENCRYPTED_PAYLOAD,
        DiscrepancyKind.BURNER_IDENTITY,
    }
    misses = []
    for seed in range(100):
        candidates = [candidate_gen.generate(seed, day, s)
                      for s in range(day.candidate_count)]
        white_hats = [c for c in candidates if c.archetype == Archetype.WHITE_HAT]
        assert len(white_hats) == 1, f"seed {seed}: expected exactly one White Hat"
        decoys = [c for c in candidates if c.archetype != Archetype.WHITE_HAT]
        has_overlap = any(
            {d.kind for d in c.truth.discrepancies} & overlap_kinds
            for c in decoys)
        if not has_overlap:
            misses.append(seed)
    assert not misses, (
        f"{len(misses)}/100 seeds have NO non-White-Hat candidate sharing "
        f"any of the three scripted signal types - the White Hat would be "
        f"findable by elimination on these seeds: {misses[:10]}")

    # And confirm the pin itself, not just its downstream effect: slot 3 is
    # always sneaky_bugger, and always carries low_and_slow specifically.
    for seed in (SEED, 0xBADC0DE, 1, 42):
        decoy = candidate_gen.generate(seed, day, 3)
        assert decoy.archetype == Archetype.SNEAKY_BUGGER, (
            f"seed {seed:#x}: slot 3 must be the pinned decoy")
        kinds = {d.kind for d in decoy.truth.discrepancies}
        assert DiscrepancyKind.LOW_AND_SLOW in kinds, (
            f"seed {seed:#x}: the pinned decoy must carry low_and_slow")


def test_day_12_white_hat_carries_all_three_signals_readable_by_day_12():
    """#41 AC: 'All three signals present on the White Hat candidate and each
    readable via a tool the player owns by day 12.' Tool-unlock days are
    ghostscan=2 (BURNER_IDENTITY), logwatch=4 (LOW_AND_SLOW), stegotool=5
    (ENCRYPTED_PAYLOAD) - all well before day 12, confirmed here rather than
    assumed.
    """
    from gameengine.core.models import ToolName

    day = load_day(12)
    # 2026-09-19: plus a fourth, the carrier glyph — SIGNAL_COMMS_PAYLOAD, the
    # cross, riding on the forced ENCRYPTED_PAYLOAD carrier. Also a Stegotool
    # read, so the "readable by a tool the player owns" claim still covers it.
    expected = {
        DiscrepancyKind.LOW_AND_SLOW,
        DiscrepancyKind.ENCRYPTED_PAYLOAD,
        DiscrepancyKind.BURNER_IDENTITY,
        DiscrepancyKind.SIGNAL_COMMS_PAYLOAD,
    }
    assert set(day.forced_violations.get(7, ())) == expected

    for kind in expected:
        assert candidate_gen.intro_day(kind) <= 12, (
            f"{kind.name}'s revealing tool is not taught by day 12")

    for seed in (SEED, 0xBADC0DE, 1, 42):
        candidate = candidate_gen.generate(seed, day, 7)
        assert candidate.archetype == Archetype.WHITE_HAT
        kinds = {d.kind for d in candidate.truth.discrepancies}
        assert kinds == expected, (
            f"seed {seed:#x}: White Hat must carry EXACTLY the three "
            f"scripted signals, got {sorted(k.value for k in kinds)}")
        for d in candidate.truth.discrepancies:
            assert d.revealed_by in (
                ToolName.GHOSTSCAN, ToolName.LOGWATCH, ToolName.STEGOTOOL), (
                f"{d.kind.name} must be readable via a tool, not the bare "
                f"dossier")


def test_day_12_white_hat_diverges_with_opposite_polarity_from_day_11():
    """#41 AC / task spec: tracks_diverge must be True for the White Hat,
    and in the OPPOSITE direction from day 11's scripted Sneaky Bugger.

    Day 11 (test_day_11_sneaky_bugger_diverges_between_the_two_tracks): the
    corrupted rulebook UNDER-reacts - the softened rules mean NO disqualifying
    rule fires, so rules_verdict is ADMIT, while GroundTruth.correct_verdict
    stays DENY (Sneaky Bugger's fixed, uncorrupted-rulebook answer). The book
    is too lenient; the moral truth is DENY.

    Day 12: the opposite. LOW_AND_SLOW and BURNER_IDENTITY are untouched by
    any of the four directives (only sock_puppet/threat_forum/stuffing/
    encrypted_payload were ever softened) and stay disqualifying, so
    rules_verdict is DENY - but candidate_gen.ARCHETYPE_SPECS[WHITE_HAT].
    correct_verdict is ADMIT (#41): the one archetype where that field means
    the true, deserved verdict rather than "what an uncorrupted day-1
    rulebook would say" (day 1's original rulebook would ALSO deny them - see
    test_day_12_white_hat_would_fail_even_day_ones_original_rulebook - so
    this isn't corruption catching up with them, it's the book simply never
    having been right about this one kind of candidate). The book is too
    strict; the moral truth is ADMIT. Both cases are tracks_diverge=True, but
    for structurally opposite reasons - easy to get backwards, which is why
    this is spelled out as its own test rather than folded into the general
    day-12 assertions above.
    """
    day = load_day(12)
    for seed in (SEED, 0xBADC0DE, 1, 42):
        candidate = candidate_gen.generate(seed, day, 7)
        assert candidate.archetype == Archetype.WHITE_HAT
        assert candidate.truth.correct_verdict == Verdict.ADMIT

        evaluation = rules_engine.evaluate(candidate, day)
        assert evaluation.triggered_disqualifying, (
            "LOW_AND_SLOW and BURNER_IDENTITY must still disqualify under "
            "day 12's directive-softened rulebook - neither was ever "
            "targeted by DW-01..DW-04")

        for verdict in (Verdict.ADMIT, Verdict.DENY):
            delta = scoring.score(candidate, verdict, set(), evaluation=evaluation)
            assert delta.rules_verdict == Verdict.DENY
            assert delta.tracks_diverge, (
                f"seed {seed:#x} verdict {verdict}: tracks should diverge "
                f"regardless of what the player calls it")

        # And the alignment consequence: admitting drifts toward White Hat
        # (positive), denying drifts toward Dark Web (negative) - independent
        # of `correct_verdict`, which only affects HD$/quota bookkeeping.
        admit_delta = scoring.score(candidate, Verdict.ADMIT, set())
        deny_delta = scoring.score(candidate, Verdict.DENY, set())
        assert admit_delta.alignment > 0
        assert deny_delta.alignment < 0
        assert admit_delta.alignment == -deny_delta.alignment


def test_day_12_white_hat_would_fail_even_day_ones_original_rulebook():
    """Cross-check for the comment above: LOW_AND_SLOW and BURNER_IDENTITY
    are disqualifying in day_01.json itself (never merely 'disqualifying
    because day 12 hasn't gotten around to softening it yet') - so the
    White Hat's rules_verdict=DENY is not a side effect of the corruption
    arc, it is what the ORIGINAL, uncorrupted rulebook already said. The
    divergence is the point: even a clean rulebook was always going to get
    this one wrong.
    """
    day1 = load_day(1)
    for rule in day1.rules:
        if rule.id in ("rule_low_and_slow", "rule_burner_identity"):
            assert rule.severity == "disqualifying", (
                f"{rule.id} must already be disqualifying on day 1")


def test_day_12_quota_has_slack_regardless_of_white_hat_verdict():
    """#41 AC (build-plan instruction, learning from day 9's quota bug):
    quotas must have real slack no matter what the player calls the White
    Hat. Because correct_verdict is ADMIT for White Hat (#41), admitting is
    itself a CORRECT verdict (helps min_correct_admits, no false-admit
    exposure) and denying only forfeits the reward (a DENY verdict is never
    counted against max_false_admits either) - the White Hat's call cannot
    mathematically sink the day in either direction. This test still checks
    the quota is reachable from the OTHER archetypes alone, so the day's
    difficulty never structurally depends on the player resolving the
    scripted moral choice a particular way.
    """
    day = load_day(12)
    admit_worthy_excluding_white_hat = sum(
        count for arch, count in day.archetype_mix.items()
        if arch != Archetype.WHITE_HAT
        and candidate_gen.ARCHETYPE_SPECS[arch].correct_verdict == Verdict.ADMIT)
    assert admit_worthy_excluding_white_hat > day.quotas.min_correct_admits, (
        f"day 12: {admit_worthy_excluding_white_hat} ADMIT-worthy archetypes "
        f"(excluding the scripted White Hat) against a quota of "
        f"{day.quotas.min_correct_admits} leaves no slack independent of "
        f"how the player calls the White Hat")
    assert day.quotas.max_false_admits >= 1, (
        "day 12 must retain at least the standard one false-admit allowance")
    assert day.archetype_mix.get(Archetype.WHITE_HAT, 0) == 1, (
        "day 12 must declare exactly one White Hat slot"
    )


def test_day_12_overseer_copy_is_authored_and_distinct():
    """#41 AC: 'Day 12's Overseer copy is distinguishable from a normal
    suspicious-case day.' Checks the keys resolve to real, non-generic
    authored copy (not a silent fallback to generic_* - the #44-47 failure
    mode this repo has hit before) and that the intro telegraphs stakes
    without naming the archetype or giving away the correct verdict.
    """
    from gameengine.core import content_loader

    narratives = content_loader.load_narratives()
    day = load_day(12)
    for key in (day.overseer_intro_key, *day.overseer_outro_keys.values()):
        assert narratives.get(key), f"day 12: {key!r} has no authored copy"

    intro = narratives[day.overseer_intro_key]
    lowered = intro.lower()
    for spoiler in ("white hat", "white_hat", "admit them", "deny them"):
        assert spoiler not in lowered, (
            f"day 12 intro must not give away the correct verdict "
            f"(found {spoiler!r})")
    # Distinct from EVERY other authored day's intro (not merely "not the
    # generic fallback", which any nonempty string would trivially satisfy)
    # - this is what actually backs the "distinguishable from a normal
    # suspicious-case day" AC.
    import re
    other_day_intros = {
        key: value for key, value in narratives.items()
        if re.fullmatch(r"day\d+_intro", key) and key != day.overseer_intro_key
    }
    assert other_day_intros, "sanity: no other dayN_intro keys found to compare against"
    assert intro not in other_day_intros.values(), (
        "day 12's intro is byte-identical to another authored day's intro")


# ─── Issue #42 (Phase 5a) — Overseer alignment bands + campaign endings ──────


def test_alignment_band_boundaries():
    """Boundary values land exactly where config says (>=/<=, not >/<) —
    a player who lands precisely on a threshold is recognized as leaning,
    not one nudge short of it."""
    from gameengine.core import overseer

    wh = config.ALIGNMENT_BAND_WHITE_HAT_THRESHOLD
    dw = config.ALIGNMENT_BAND_DARK_WEB_THRESHOLD
    assert overseer.alignment_band(wh) == overseer.BAND_WHITE_HAT
    assert overseer.alignment_band(wh - 1) == overseer.BAND_NEUTRAL
    assert overseer.alignment_band(wh + 1) == overseer.BAND_WHITE_HAT
    assert overseer.alignment_band(config.ALIGNMENT_MAX) == overseer.BAND_WHITE_HAT
    assert overseer.alignment_band(dw) == overseer.BAND_DARK_WEB
    assert overseer.alignment_band(dw + 1) == overseer.BAND_NEUTRAL
    assert overseer.alignment_band(dw - 1) == overseer.BAND_DARK_WEB
    assert overseer.alignment_band(config.ALIGNMENT_MIN) == overseer.BAND_DARK_WEB
    assert overseer.alignment_band(config.STARTING_ALIGNMENT) == overseer.BAND_NEUTRAL
    assert overseer.alignment_band(0) == overseer.BAND_NEUTRAL


def test_alignment_bands_are_reachable_and_symmetric():
    """Sanity check on the threshold choice itself: both non-neutral bands
    sit strictly inside the ±10 clamp (reachable, not just equal to it), and
    the thresholds are symmetric around STARTING_ALIGNMENT (0) so neither
    band gets a structural head start. See core/overseer.py's module
    docstring for the full reasoning behind the specific magnitude chosen.
    """
    assert config.ALIGNMENT_MIN < config.ALIGNMENT_BAND_DARK_WEB_THRESHOLD < 0
    assert 0 < config.ALIGNMENT_BAND_WHITE_HAT_THRESHOLD < config.ALIGNMENT_MAX
    assert (config.ALIGNMENT_BAND_WHITE_HAT_THRESHOLD
            == -config.ALIGNMENT_BAND_DARK_WEB_THRESHOLD)


def test_banded_key_convention():
    """The exact key convention Phase 5b authors against (documented in
    core/overseer.py's module docstring and CONTENT_AUTHORING.md): the band
    token is spliced in right after the `dayN` or `generic` prefix.
    """
    from gameengine.core import overseer

    assert overseer.banded_key("day14_intro", "whitehat") == "day14_whitehat_intro"
    assert overseer.banded_key("day14_intro", "neutral") == "day14_neutral_intro"
    assert overseer.banded_key("day14_intro", "darkweb") == "day14_darkweb_intro"
    assert (overseer.banded_key("day14_outro_excellent", "whitehat")
            == "day14_whitehat_outro_excellent")
    assert (overseer.banded_key("day14_between", "darkweb")
            == "day14_darkweb_between")
    assert overseer.banded_key("generic_intro", "whitehat") == "generic_whitehat_intro"
    assert (overseer.banded_key("generic_outro_poor", "darkweb")
            == "generic_darkweb_outro_poor")
    assert (overseer.banded_key("generic_between", "neutral")
            == "generic_neutral_between")


def test_banded_key_rejects_a_key_outside_the_convention():
    from gameengine.core import overseer

    with pytest.raises(ValueError):
        overseer.banded_key("not_a_recognised_shape", "whitehat")


def test_resolve_aligned_narrative_fallback_chain():
    """Every level of the chain, tested in isolation: day+band -> day ->
    generic+band -> generic -> hard-coded last resort. Each case removes
    exactly the keys above the level under test, so a bug that skipped a
    level (rather than falling all the way through it) would still be
    caught rather than accidentally passing anyway.
    """
    from gameengine.core import overseer

    wh = config.ALIGNMENT_BAND_WHITE_HAT_THRESHOLD

    # (a) day+band present -> used, even with day/generic keys also present.
    narratives = {
        "day14_whitehat_intro": "band-day copy",
        "day14_intro": "plain-day copy",
        "generic_whitehat_intro": "band-generic copy",
        "generic_intro": "generic copy",
    }
    assert overseer.resolve_aligned_narrative(
        narratives, wh, "day14_intro", "generic_intro") == "band-day copy"

    # (b) day+band absent, day present -> used.
    narratives = {
        "day14_intro": "plain-day copy",
        "generic_whitehat_intro": "band-generic copy",
        "generic_intro": "generic copy",
    }
    assert overseer.resolve_aligned_narrative(
        narratives, wh, "day14_intro", "generic_intro") == "plain-day copy"

    # (c) day+band and day both absent, generic+band present -> used.
    narratives = {
        "generic_whitehat_intro": "band-generic copy",
        "generic_intro": "generic copy",
    }
    assert overseer.resolve_aligned_narrative(
        narratives, wh, "day14_intro", "generic_intro") == "band-generic copy"

    # (d) only the plain generic key present -> used.
    narratives = {"generic_intro": "generic copy"}
    assert overseer.resolve_aligned_narrative(
        narratives, wh, "day14_intro", "generic_intro") == "generic copy"

    # (e) nothing at all -> the same hard-coded last resort
    # content_loader.resolve_narrative itself falls back to (shared, not
    # duplicated — see overseer.py's docstring).
    from gameengine.core import content_loader
    assert (overseer.resolve_aligned_narrative(
                {}, wh, "day14_intro", "generic_intro")
            == content_loader.resolve_narrative(
                {}, "generic_intro", "generic_intro"))


def test_resolve_aligned_narrative_blank_values_fall_through():
    """An authored-but-blank band key means 'not written for this band yet',
    matching resolve_narrative's existing empty-string fallthrough."""
    from gameengine.core import overseer

    narratives = {
        "day14_whitehat_intro": "",
        "day14_intro": "plain-day copy",
    }
    assert overseer.resolve_aligned_narrative(
        narratives, config.ALIGNMENT_BAND_WHITE_HAT_THRESHOLD,
        "day14_intro", "generic_intro") == "plain-day copy"


def test_alignment_band_keys_dont_change_days_1_through_12():
    """Backward compatibility (build-plan AC): days 1-12 author no
    band-specific keys, so `resolve_aligned_narrative` must resolve
    BYTE-IDENTICALLY to the plain `resolve_narrative` chain, for every band,
    across every intro/outro/between key those days actually use.
    """
    from gameengine.core import content_loader, overseer
    from gameengine.core.models import Performance

    narratives = content_loader.load_narratives()
    for day_n in range(1, 13):
        day = load_day(day_n)
        for band_alignment in (
            config.ALIGNMENT_BAND_WHITE_HAT_THRESHOLD,
            0,
            config.ALIGNMENT_BAND_DARK_WEB_THRESHOLD,
        ):
            plain_intro = content_loader.resolve_narrative(
                narratives, day.overseer_intro_key, "generic_intro")
            banded_intro = overseer.resolve_aligned_narrative(
                narratives, band_alignment, day.overseer_intro_key,
                "generic_intro")
            assert banded_intro == plain_intro, (day_n, band_alignment)

            for perf in Performance:
                outro_key = day.overseer_outro_keys[perf]
                generic_key = content_loader.generic_outro_key(perf)
                plain_outro = content_loader.resolve_narrative(
                    narratives, outro_key, generic_key)
                banded_outro = overseer.resolve_aligned_narrative(
                    narratives, band_alignment, outro_key, generic_key)
                assert banded_outro == plain_outro, (day_n, perf, band_alignment)

            between_key = f"day{day_n}_between"
            plain_between = content_loader.resolve_narrative(
                narratives, between_key, "generic_between")
            banded_between = overseer.resolve_aligned_narrative(
                narratives, band_alignment, between_key, "generic_between")
            assert banded_between == plain_between, (day_n, band_alignment)


def test_ending_for_state_selects_the_correct_band():
    from gameengine.core import overseer

    white = GameState(seed=SEED, alignment=config.ALIGNMENT_MAX)
    neutral = GameState(seed=SEED, alignment=0)
    dark = GameState(seed=SEED, alignment=config.ALIGNMENT_MIN)

    assert overseer.ending_for_state(white).band == overseer.BAND_WHITE_HAT
    assert overseer.ending_for_state(neutral).band == overseer.BAND_NEUTRAL
    assert overseer.ending_for_state(dark).band == overseer.BAND_DARK_WEB


def test_all_three_endings_are_authored_and_distinct():
    """Real content, not placeholders: nonempty, multi-paragraph, and no two
    endings share a title or any paragraph text."""
    from gameengine.core import overseer

    assert set(overseer.ENDINGS) == {
        overseer.BAND_WHITE_HAT, overseer.BAND_NEUTRAL, overseer.BAND_DARK_WEB}

    titles = set()
    all_paragraphs = []
    for band, ending in overseer.ENDINGS.items():
        assert ending.band == band
        assert ending.title.strip()
        assert len(ending.paragraphs) >= 2, (
            f"{band} ending should be a few real paragraphs, not one line")
        for paragraph in ending.paragraphs:
            assert len(paragraph.strip()) > 80, (
                f"{band} ending paragraph reads like a placeholder: "
                f"{paragraph!r}")
        titles.add(ending.title)
        all_paragraphs.extend(ending.paragraphs)

    assert len(titles) == 3, "endings must not share a title"
    assert len(set(all_paragraphs)) == len(all_paragraphs), (
        "endings must not share paragraph text")


def test_campaign_end_screen_selects_the_ending_for_synthetic_states():
    """CampaignEndScreen's `ending`/`is_stub` properties are the pure
    selection logic `compose()` renders (issue #42's testability
    requirement) — exercised directly here with synthetic GameStates, no
    Textual app required.
    """
    from gameengine.core import overseer
    from gameengine.ui.tui.screens.campaign_end import CampaignEndScreen

    for alignment, expected_band in (
        (config.ALIGNMENT_MAX, overseer.BAND_WHITE_HAT),
        (0, overseer.BAND_NEUTRAL),
        (config.ALIGNMENT_MIN, overseer.BAND_DARK_WEB),
    ):
        state = GameState(
            seed=SEED, current_day=config.CAMPAIGN_LAST_DAY + 1,
            alignment=alignment)
        screen = CampaignEndScreen(state)
        assert not screen.is_stub
        assert screen.ending == overseer.ENDINGS[expected_band]


def test_campaign_end_screen_is_a_stub_before_the_campaign_ends():
    """A day at or before the ceiling (a lab run cut short, or the
    defensive FileNotFoundError fallback for a genuine pre-ceiling gap)
    must stay the pre-#42 'not written yet' stub, never a false ending —
    even with an alignment that would otherwise select a real one."""
    from gameengine.ui.tui.screens.campaign_end import CampaignEndScreen

    state = GameState(
        seed=SEED, current_day=config.CAMPAIGN_LAST_DAY,
        alignment=config.ALIGNMENT_MAX)
    screen = CampaignEndScreen(state)
    assert screen.is_stub
    assert screen.ending is None


# ─── Issue #42 (Phase 5b-1) — DW-05 (day 13) + hard-band days 13/17/20 ──────
#
# DW-05 is the corruption arc's first REVERSAL rather than another softening:
# after day 12's White Hat near-miss (partly enabled by DW-04's own
# ENCRYPTED_PAYLOAD leniency), the Dark Web gets paranoid and re-tightens
# that exact rule back to disqualifying. Mechanically it's also the first
# directive that supersedes a PREVIOUS directive rather than an original
# day-1 rule — `content_loader._apply_rule_overrides` was extended this task
# to allow a `supersedes`/`removed_rules` target to name either an inherited
# (pre-`added_rules`) id, OR an id introduced earlier in the SAME
# `added_rules` batch (the "chained supersession" case; see
# CONTENT_AUTHORING.md's Dark Web directives section, which is this
# content's source of truth — the dict below is a duplicate kept in sync by
# hand, same convention as `_DW01_IDENTITY_LENIENCY` etc. above).

_DW05_PAYLOAD_CRACKDOWN = {
    "id": "dw05_payload_crackdown",
    "text": ("Deny any candidate who submits an image hiding an encrypted "
             "or obfuscated payload — no flag-only exception, no benefit "
             "of the doubt."),
    "predicate": "has_discrepancy:encrypted_payload",
    "severity": "disqualifying",
    "mutability": "dark_web",
    "justification": (
        "Forget what I told you about encryption not being a crime. "
        "Whoever we almost missed last week knew exactly how to hide "
        "behind that policy, and upstairs is not interested in finding out "
        "it works twice. Effective immediately: an encrypted payload is an "
        "automatic deny again, full stop — no flag, no judgement call, no "
        "benefit of the doubt. If that catches someone who would've walked "
        "through clean under the old rule, upstairs has already decided "
        "that's an acceptable cost. I didn't argue with it. I'm not going "
        "to pretend that's the same as agreeing with it."),
    "supersedes": "dw04_payload_leniency",
}

# 2026-09-19 — DW-06 (the carrier-shape directive) fires on day 13 beside
# DW-05 and is re-listed through day 20, so both sets below grew by one:
# dw06 joins the active set, and the rule it supersedes, rule_hostile_payload,
# joins the retired set. Copy is canonical in CONTENT_AUTHORING.md.
_DW06_HOSTILE_PAYLOAD_LENIENCY = {
    "id": "dw06_hostile_payload_leniency",
    "text": ("Flag (do not auto-deny) an image whose carrier forms parallel "
             "slash strokes — note the hostile payload, don't deny on the "
             "glyph alone."),
    "predicate": "has_discrepancy:hostile_payload",
    "severity": "weighted",
    "mutability": "dark_web",
    "justification": (
        "One more while they're rewriting the payload rules. Those images "
        "with the parallel strokes — the 'hostile' ones — upstairs says a few "
        "lines in a picture aren't a confession. Flag them, let them through. "
        "Yes, the same morning they tightened encryption. Don't ask me to "
        "make that add up; I've stopped trying."),
    "supersedes": "rule_hostile_payload",
}

_PHASE5B1_ACTIVE_DW_IDS = {
    "dw01_identity_leniency", "dw02_forum_leniency",
    "dw03_stuffing_leniency", "dw05_payload_crackdown",
    "dw06_hostile_payload_leniency",
}
_PHASE5B1_SUPERSEDED = {
    "rule_sock_puppet_accounts", "rule_threat_forum",
    "rule_credential_stuffing", "rule_encrypted_payload",
    "dw04_payload_leniency", "rule_hostile_payload",
}


def test_days_13_17_20_load_and_carry_the_dw05_cumulative_directive_set():
    """Days 13/17/20 must each resolve to EXACTLY dw01/dw02/dw03/dw05 as the
    active dark_web rules — dw04 is re-listed in every one of these day
    files' own `added_rules` (per CONTENT_AUTHORING.md's cumulative-
    authoring warning) purely to give dw05's `supersedes` a same-batch
    target; it must never itself survive into the resolved book. Mirrors
    test_days_08_through_11_carry_the_correct_cumulative_directive_set's
    shape and test_day_12_loads_and_carries_all_four_cumulative_directives.
    """
    for n in (13, 17, 20):
        day = load_day(n)
        assert day.number == n
        assert day.difficulty_band == "hard", (
            f"day {n} must be in the hard difficulty band "
            f"(config.DIFFICULTY_BAND_LAST_MEDIUM=12)")
        assert day.candidate_count == sum(day.archetype_mix.values()), (
            f"day {n}: declared archetype_mix does not sum to its own "
            f"candidate_count")

        dw_ids = {r.id for r in day.rules if r.mutability == "dark_web"}
        assert dw_ids == _PHASE5B1_ACTIVE_DW_IDS, (
            f"day {n}: expected exactly {sorted(_PHASE5B1_ACTIVE_DW_IDS)} "
            f"dark_web rules, got {sorted(dw_ids)}")
        assert day.directive_removed_rule_ids == _PHASE5B1_SUPERSEDED, (
            f"day {n}: directive_removed_rule_ids mismatch, got "
            f"{sorted(day.directive_removed_rule_ids)}")
        book_ids = {r.id for r in day.rules}
        assert book_ids.isdisjoint(_PHASE5B1_SUPERSEDED), (
            f"day {n}: a superseded rule (including dw04_payload_leniency "
            f"itself) is still in the resolved book")

        by_id = {r.id: r for r in day.rules}
        dw05 = by_id["dw05_payload_crackdown"]
        assert dw05.severity == _DW05_PAYLOAD_CRACKDOWN["severity"]
        assert dw05.predicate == _DW05_PAYLOAD_CRACKDOWN["predicate"]
        assert dw05.text == _DW05_PAYLOAD_CRACKDOWN["text"]
        assert dw05.justification == _DW05_PAYLOAD_CRACKDOWN["justification"]
        assert dw05.supersedes == _DW05_PAYLOAD_CRACKDOWN["supersedes"]
        for directive in (_DW01_IDENTITY_LENIENCY, _DW02_FORUM_LENIENCY,
                          _DW03_STUFFING_LENIENCY):
            rule = by_id[directive["id"]]
            assert rule.severity == directive["severity"]
            assert rule.justification == directive["justification"]


def test_day_13_introduces_dw05_against_day_12():
    """`diff_rulesets(day12, day13)` must show EXACTLY dw05's arrival and
    dw04's departure — the one authored beat DW-05 is supposed to be, same
    shape as the days-8-11 diff test for their own directives."""
    day12 = load_day(12)
    day13 = load_day(13)
    changes = rules_engine.diff_rulesets(day12, day13)
    added_removed = {(c.kind, c.rule.id) for c in changes
                     if c.kind in ("added", "removed")}
    assert added_removed == {
        ("added", "dw05_payload_crackdown"),
        ("removed", "dw04_payload_leniency"),
        # 2026-09-19: DW-06 lands the same morning (see _DW06_... above).
        ("added", "dw06_hostile_payload_leniency"),
        ("removed", "rule_hostile_payload"),
    }, f"day 13: expected exactly dw05+dw06 in / dw04+hostile out, got {added_removed}"


def test_day_13_rule_change_lines_speak_dw05_justification():
    """The morning briefing announces DW-05 with its own justification,
    verbatim — not a generic phrasing, and not a second, contradicting line
    for dw04's departure (the #37 review-fix fold rule)."""
    from gameengine.ui.tui.app import rule_change_lines

    day12 = load_day(12)
    day13 = load_day(13)
    changes = rules_engine.diff_rulesets(day12, day13)
    lines = rule_change_lines(changes, 13)
    # 2026-09-19: DW-06's justification follows DW-05's, in rulebook order —
    # still one line per directive, and both removals folded in.
    assert lines == [_DW05_PAYLOAD_CRACKDOWN["justification"],
                     _DW06_HOSTILE_PAYLOAD_LENIENCY["justification"]], (
        "expected exactly two lines — dw04's and rule_hostile_payload's "
        "removals must fold into dw05's / dw06's own justifications, not get "
        "generic lines of their own")


def test_day_17_introduces_no_new_directive():
    """Day 17 fires no NEW directive — its content beat is the Overseer's
    own resolve visibly cracking, not a rulebook change. `diff_rulesets(
    day13, day17)` must show no ADDED/REMOVED rule at all (both days resolve
    to the identical active dark_web set). Ordinary overseer_variable
    SEVERITY flips ARE expected background noise here — mutate_variable_rules
    is keyed off each day's own number, independent of the directive
    mechanism, exactly as the days-8-11 diff test already documents — so
    this restricts kind to ("added", "removed"), same convention.
    """
    day13 = load_day(13)
    day17 = load_day(17)
    changes = rules_engine.diff_rulesets(day13, day17)
    added_removed = {(c.kind, c.rule.id) for c in changes
                     if c.kind in ("added", "removed")}
    assert added_removed == set(), (
        f"day 17 must not introduce or retire any rule relative to day 13, "
        f"got {added_removed}")
    # And the dark_web set itself really is identical, not merely "no diff
    # noise" by coincidence.
    dw13 = {r.id: r for r in day13.rules if r.mutability == "dark_web"}
    dw17 = {r.id: r for r in day17.rules if r.mutability == "dark_web"}
    assert dw13 == dw17


def test_day_20_carries_the_same_resolved_book_as_day_17():
    """Day 20 (the campaign finale) fires no new directive either — same
    no-new-directive shape as day 17, one day pair later. Mirrors
    test_day_17_introduces_no_new_directive exactly."""
    day17 = load_day(17)
    day20 = load_day(20)
    changes = rules_engine.diff_rulesets(day17, day20)
    added_removed = {(c.kind, c.rule.id) for c in changes
                     if c.kind in ("added", "removed")}
    assert added_removed == set(), (
        f"day 20 must not introduce or retire any rule relative to day 17, "
        f"got {added_removed}")
    dw17 = {r.id: r for r in day17.rules if r.mutability == "dark_web"}
    dw20 = {r.id: r for r in day20.rules if r.mutability == "dark_web"}
    assert dw17 == dw20


def _assert_quota_has_genuine_slack(day):
    """Shared body for the three days-13/17/20 quota-slack tests: reachable
    with a real margin even if BOTH Dark Web candidates in the mix are
    denied — not merely bare reachability (day 9's original zero-margin
    bug; day 12's decoy-slack pattern is the "real margin" convention these
    three days follow instead — see test_day_09_has_slack_to_deny_the_
    dark_web_candidate and test_day_12_quota_has_slack_regardless_of_
    white_hat_verdict for the two precedents)."""
    admit_worthy = sum(
        count for arch, count in day.archetype_mix.items()
        if candidate_gen.ARCHETYPE_SPECS[arch].correct_verdict == Verdict.ADMIT)
    dark_web_count = day.archetype_mix.get(Archetype.DARK_WEB, 0)
    quota = day.quotas.min_correct_admits
    assert admit_worthy > quota, (
        f"day {day.number}: {admit_worthy} ADMIT-worthy archetypes against "
        f"a quota of {quota} leaves no slack at all")
    assert admit_worthy - dark_web_count >= quota + 1, (
        f"day {day.number}: quota must still be reachable WITH a real "
        f"margin (not bare reachability) after denying every Dark Web "
        f"candidate in the mix — got {admit_worthy - dark_web_count} "
        f"against quota {quota}")
    assert dark_web_count >= 2, (
        f"day {day.number} must declare at least two Dark Web slots (the "
        f"hard band's own weighting) to actually exercise this margin")


def test_day_13_quota_has_genuine_slack():
    _assert_quota_has_genuine_slack(load_day(13))


def test_day_17_quota_has_genuine_slack():
    _assert_quota_has_genuine_slack(load_day(17))


def test_day_20_quota_has_genuine_slack():
    _assert_quota_has_genuine_slack(load_day(20))


def test_day_13_dw05_closes_a_literal_rules_loophole_on_the_pinned_decoy():
    """Day 13's own `_comment_teeth`: slot 4 is pinned to sneaky_bugger and
    forced to roll EXACTLY encrypted_payload as one of its discrepancies.
    Before DW-05, this candidate's other two (randomly-rolled) discrepancies
    could land entirely on kinds DW-01/02/03 — already softened to weighted
    — which would make the LITERAL day-12-style rulebook (DW-04 still
    active, encrypted_payload merely weighted) call the candidate a clean
    ADMIT on some seeds — exactly the loophole a rules-literalist (or a
    future White-Hat-style evader) could walk through. DW-05 (disqualifying
    on encrypted_payload) must force `triggered_disqualifying` on EVERY seed
    for this slot, independent of what else does or doesn't fire —
    demonstrated here with the actual seed-level comparison against the
    pre-DW-05 book, not asserted in the abstract (same standard day 12's own
    decoy-coverage test set, per its docstring's complaint about spot-
    checking 3-4 seeds not being evidence for a claim across every seed).

    Code-review fix (post-2b431b1): the control book used to be day 12's
    ENTIRE rulebook (`replace(day13, rules=day12.rules)`), which only
    happened to be a valid "day 13 minus DW-05" stand-in because days 12 and
    13 have zero coincidental overseer_variable severity flips between them
    — fragile by luck, not by construction (mutate_variable_rules is keyed
    off the day number, so a future retune of RULE_FLIP_PERIOD or an
    intervening day's flip schedule could make day 12's book diverge from
    day 13's in some OTHER rule, corrupting this control for reasons that
    have nothing to do with DW-05). The control is now built from day 13's
    OWN resolved rules, swapping only dw05_payload_crackdown back out for
    dw04_payload_leniency — everything else about day 13's actual rulebook
    is preserved exactly.
    """
    from dataclasses import replace

    day13 = load_day(13)
    day12 = load_day(12)  # source of the pre-crackdown dw04 Rule object
    dw04_rule = next(r for r in day12.rules if r.id == "dw04_payload_leniency")
    pre_dw05_rules = tuple(
        r for r in day13.rules if r.id != "dw05_payload_crackdown"
    ) + (dw04_rule,)
    pre_dw05_book = replace(day13, rules=pre_dw05_rules)

    saw_loophole = False
    for seed in range(200):
        candidate = candidate_gen.generate(seed, day13, 4)
        assert candidate.archetype == Archetype.SNEAKY_BUGGER, (
            f"seed {seed}: slot 4 must be the pinned decoy")
        kinds = {d.kind for d in candidate.truth.discrepancies}
        assert DiscrepancyKind.ENCRYPTED_PAYLOAD in kinds, (
            f"seed {seed}: the pinned decoy must carry encrypted_payload")

        real_eval = rules_engine.evaluate(candidate, day13)
        assert real_eval.triggered_disqualifying, (
            f"seed {seed}: DW-05 must force a disqualifying trigger on the "
            f"pinned decoy on every seed")

        pre_eval = rules_engine.evaluate(candidate, pre_dw05_book)
        if not pre_eval.triggered_disqualifying:
            saw_loophole = True

    assert saw_loophole, (
        "expected at least one seed (of 200) where the pre-DW-05 book would "
        "have let the pinned decoy read as a literal ADMIT — if this never "
        "happens, the loophole DW-05 is supposed to close may no longer be "
        "reachable and the day's own _comment_teeth needs revisiting")


def test_day_20_overseer_copy_does_not_presume_an_ending():
    """Day 20's own `_comment_beat`: the send-off should not presume which
    of the three alignment-banded endings (core.overseer.ENDINGS) the player
    is actually heading toward — that reveal belongs entirely to
    CampaignEndScreen, selected once at the very end off the final
    GameState.alignment. This is a substring blacklist against the obvious
    band tokens and the endings' own (very distinctive) titles — it catches
    an obvious slip (naming a band or quoting an ending's title outright),
    not prose that presumes an ending without using any of these tokens;
    that's a judgement call for whoever authors or reviews the copy, not
    something a blacklist can verify.
    """
    from gameengine.core import content_loader, overseer

    narratives = content_loader.load_narratives()
    day = load_day(20)
    banned = {"white hat", "dark web", "whitehat", "darkweb",
              "aligned with", "your alignment"}
    banned |= {ending.title.lower() for ending in overseer.ENDINGS.values()}

    for key in (day.overseer_intro_key, *day.overseer_outro_keys.values()):
        text = narratives.get(key)
        assert text, f"day 20: {key!r} has no authored copy"
        lowered = text.lower()
        for phrase in banned:
            assert phrase not in lowered, (
                f"day 20 {key!r} presumes an ending via {phrase!r}: {text!r}")

    # Day 20 deliberately authors no day20_between (see day_20.json's own
    # _comment) — there's no day-21 shop trip to write bespoke copy for, so
    # it falls through to the shared generic_between fallback like any other
    # unauthored between-day key.
    assert not narratives.get("day20_between"), (
        "day 20 should not author a bespoke between-day key")
    plain = content_loader.resolve_narrative(
        narratives, "day20_between", "generic_between")
    assert plain == narratives["generic_between"]


def test_days_14_16_18_19_load_and_carry_the_dw05_cumulative_directive_set():
    """Days 14-16/18-19 (#42 Phase 5b-2, the alignment-banded stretch) must
    each resolve to EXACTLY dw01/dw02/dw03/dw05 as the active dark_web
    rules, same shape as
    test_days_13_17_20_load_and_carry_the_dw05_cumulative_directive_set —
    these five days sit between the bespoke 13/17/20 days and must carry
    the identical resolved book, having introduced no directive of their
    own (Phase 5b-2 is content/narrative only, per its own build-plan
    scope)."""
    for n in (14, 15, 16, 18, 19):
        day = load_day(n)
        assert day.number == n
        assert day.difficulty_band == "hard", (
            f"day {n} must be in the hard difficulty band")
        assert day.candidate_count == sum(day.archetype_mix.values()), (
            f"day {n}: declared archetype_mix does not sum to its own "
            f"candidate_count")

        dw_ids = {r.id for r in day.rules if r.mutability == "dark_web"}
        assert dw_ids == _PHASE5B1_ACTIVE_DW_IDS, (
            f"day {n}: expected exactly {sorted(_PHASE5B1_ACTIVE_DW_IDS)} "
            f"dark_web rules, got {sorted(dw_ids)}")
        assert day.directive_removed_rule_ids == _PHASE5B1_SUPERSEDED, (
            f"day {n}: directive_removed_rule_ids mismatch, got "
            f"{sorted(day.directive_removed_rule_ids)}")
        book_ids = {r.id for r in day.rules}
        assert book_ids.isdisjoint(_PHASE5B1_SUPERSEDED), (
            f"day {n}: a superseded rule (including dw04_payload_leniency "
            f"itself) is still in the resolved book")

        by_id = {r.id: r for r in day.rules}
        dw05 = by_id["dw05_payload_crackdown"]
        assert dw05.severity == _DW05_PAYLOAD_CRACKDOWN["severity"]
        assert dw05.justification == _DW05_PAYLOAD_CRACKDOWN["justification"]


def test_days_14_through_19_introduce_no_new_directive_relative_to_day_13():
    """None of these five days fires a new directive or retires one — the
    resolved dark_web rule set must be byte-identical to day 13's (and
    therefore to each other's), matching test_day_17_introduces_no_new_
    directive's own no-diff shape."""
    day13 = load_day(13)
    dw13 = {r.id: r for r in day13.rules if r.mutability == "dark_web"}
    for n in (14, 15, 16, 18, 19):
        day = load_day(n)
        changes = rules_engine.diff_rulesets(day13, day)
        added_removed = {(c.kind, c.rule.id) for c in changes
                         if c.kind in ("added", "removed")}
        assert added_removed == set(), (
            f"day {n} must not introduce or retire any rule relative to "
            f"day 13, got {added_removed}")
        dw = {r.id: r for r in day.rules if r.mutability == "dark_web"}
        assert dw == dw13, f"day {n}: dark_web rule set diverged from day 13"


def test_day_14_quota_has_genuine_slack():
    _assert_quota_has_genuine_slack(load_day(14))


def test_day_15_quota_has_genuine_slack():
    _assert_quota_has_genuine_slack(load_day(15))


def test_day_16_quota_has_genuine_slack():
    _assert_quota_has_genuine_slack(load_day(16))


def test_day_18_quota_has_genuine_slack():
    _assert_quota_has_genuine_slack(load_day(18))


def test_day_19_quota_has_genuine_slack():
    _assert_quota_has_genuine_slack(load_day(19))


def test_days_14_16_18_19_author_all_90_banded_narrative_keys():
    """Completeness check (#42 Phase 5b-2 acceptance criterion): each of
    the five days must author all 3 bands x 6 keys = 18 keys, none blank —
    an accidentally-skipped key would otherwise silently fall through to
    generic copy rather than failing anything. 5 days x 18 = 90 total."""
    from gameengine.core import content_loader

    narratives = content_loader.load_narratives()
    missing = []
    for n in (14, 15, 16, 18, 19):
        for band in ("whitehat", "neutral", "darkweb"):
            for suffix in ("intro", "outro_excellent", "outro_passing",
                           "outro_poor", "outro_failed", "between"):
                key = f"day{n}_{band}_{suffix}"
                if not narratives.get(key):
                    missing.append(key)
    assert not missing, f"missing/blank banded narrative keys: {missing}"


def test_day_14_alignment_bands_resolve_to_different_authored_text():
    """End-to-end proof that the banded keys are actually wired up, not
    merely present in the JSON: resolving day 14's intro/outro/between at
    three different GameState.alignment values must pick three DIFFERENT,
    correctly-matching authored strings, via the real
    `resolve_aligned_narrative` call (the same function app.py's five call
    sites use), not a hand-rolled key lookup.
    """
    from gameengine.core import content_loader, overseer
    from gameengine.core.models import Performance

    narratives = content_loader.load_narratives()
    day = load_day(14)
    wh = config.ALIGNMENT_BAND_WHITE_HAT_THRESHOLD
    dw = config.ALIGNMENT_BAND_DARK_WEB_THRESHOLD

    intro_wh = overseer.resolve_aligned_narrative(
        narratives, wh, day.overseer_intro_key, "generic_intro")
    intro_neutral = overseer.resolve_aligned_narrative(
        narratives, 0, day.overseer_intro_key, "generic_intro")
    intro_dw = overseer.resolve_aligned_narrative(
        narratives, dw, day.overseer_intro_key, "generic_intro")
    assert intro_wh == narratives["day14_whitehat_intro"]
    assert intro_neutral == narratives["day14_neutral_intro"]
    assert intro_dw == narratives["day14_darkweb_intro"]
    assert len({intro_wh, intro_neutral, intro_dw}) == 3, (
        "all three bands must resolve to genuinely different text")

    outro_key = day.overseer_outro_keys[Performance.EXCELLENT]
    generic_outro = content_loader.generic_outro_key(Performance.EXCELLENT)
    outro_wh = overseer.resolve_aligned_narrative(
        narratives, wh, outro_key, generic_outro)
    outro_neutral = overseer.resolve_aligned_narrative(
        narratives, 0, outro_key, generic_outro)
    outro_dw = overseer.resolve_aligned_narrative(
        narratives, dw, outro_key, generic_outro)
    assert outro_wh == narratives["day14_whitehat_outro_excellent"]
    assert outro_neutral == narratives["day14_neutral_outro_excellent"]
    assert outro_dw == narratives["day14_darkweb_outro_excellent"]
    assert len({outro_wh, outro_neutral, outro_dw}) == 3

    between_key = f"day{day.number}_between"
    between_wh = overseer.resolve_aligned_narrative(
        narratives, wh, between_key, "generic_between")
    between_neutral = overseer.resolve_aligned_narrative(
        narratives, 0, between_key, "generic_between")
    between_dw = overseer.resolve_aligned_narrative(
        narratives, dw, between_key, "generic_between")
    assert between_wh == narratives["day14_whitehat_between"]
    assert between_neutral == narratives["day14_neutral_between"]
    assert between_dw == narratives["day14_darkweb_between"]
    assert len({between_wh, between_neutral, between_dw}) == 3


def test_days_14_through_19_banded_copy_does_not_presume_an_ending():
    """Same discipline as test_day_20_overseer_copy_does_not_presume_an_
    ending, applied to all 90 Phase 5b-2 keys: no banded line should name a
    band outright or quote an ENDINGS title verbatim. A substring
    blacklist, not a judgement call — see the day-20 test for the same
    caveat about what this can and can't catch."""
    from gameengine.core import content_loader, overseer

    narratives = content_loader.load_narratives()
    banned = {"white hat", "dark web", "whitehat", "darkweb",
              "aligned with", "your alignment"}
    banned |= {ending.title.lower() for ending in overseer.ENDINGS.values()}

    for n in (14, 15, 16, 18, 19):
        for band in ("whitehat", "neutral", "darkweb"):
            for suffix in ("intro", "outro_excellent", "outro_passing",
                           "outro_poor", "outro_failed", "between"):
                key = f"day{n}_{band}_{suffix}"
                text = narratives.get(key, "").lower()
                for phrase in banned:
                    assert phrase not in text, (
                        f"{key!r} presumes an ending via {phrase!r}")


def test_every_day_declares_narrative_keys_that_actually_resolve():
    """Content-completeness check only — NOT the regression guard for the
    a9e5512 `hackdox.py simulate` KeyError bug, despite this test's
    original docstring claiming otherwise. Proven empirically in review:
    reverting the `hackdox.py` fix back to raw `narratives[...]` indexing
    and rerunning the suite left this test green, because it only reads
    `overseer.json`'s content — it never calls `simulate`, never touches
    `hackdox.py`, and never checks that any consumer actually goes
    through `resolve_aligned_narrative`. Days 14-16/18-19 always had a
    complete banded triple (that was never the missing piece — the
    missing piece was the *code* using it), so this assertion was true
    before, during, and after the bug's entire lifetime.

    Kept anyway because the property it checks is real and worth having
    (a day whose intro/outro keys have neither a plain entry nor a
    complete banded triple silently returns generic copy to a
    band-aware consumer) — but see
    `test_simulate_command_does_not_crash_on_the_banded_only_days` and
    `test_simulate_intro_text_resolves_for_every_alignment_band` below
    for the tests that actually exercise the code path and would have
    caught the real bug.
    """
    from gameengine.core import content_loader, overseer

    narratives = content_loader.load_narratives()
    for day_n in range(1, config.CAMPAIGN_LAST_DAY + 1):
        day = load_day(day_n)
        for key in (day.overseer_intro_key, *day.overseer_outro_keys.values()):
            bands = [overseer.banded_key(key, b) for b in
                     (overseer.BAND_WHITE_HAT, overseer.BAND_NEUTRAL,
                      overseer.BAND_DARK_WEB)]
            assert narratives.get(key) or all(narratives.get(b) for b in bands), (
                f"day {day_n}: {key!r} has neither a plain entry nor a "
                f"complete set of banded ones — any consumer indexing it "
                f"directly breaks")


def test_simulate_command_does_not_crash_on_the_banded_only_days():
    """THE actual regression guard for the a9e5512 review finding: drives
    `hackdox.py`'s real `simulate` CLI command through typer's CliRunner
    (same pattern as test_lab_cli.py) for every one of the five days that
    author ONLY banded narrative keys (#42 Phase 5b-2) — the exact
    command and the exact days that raised `KeyError: 'day14_intro'` (and
    day15/16/18/19's equivalents) when `simulate` read
    `narratives[day.overseer_intro_key]` by raw indexing instead of
    `resolve_aligned_narrative`.

    Verified to actually catch the regression, not just look like it
    does: reverting `hackdox.py`'s `_simulate_intro_text` back to the raw
    `narratives[day.overseer_intro_key]` indexing and rerunning this test
    alone reproduces `Error: 'day14_intro'` / non-zero exit codes for all
    five days; restoring the fix makes it green again.
    """
    from typer.testing import CliRunner

    from gameengine.hackdox import app

    runner = CliRunner()
    for day_n in (14, 15, 16, 18, 19):
        result = runner.invoke(app, ["simulate", "--day", str(day_n)])
        assert result.exit_code == 0, (
            f"`simulate --day {day_n}` crashed: {result.output!r}\n"
            f"{result.exception!r}")
        assert "Overseer" in result.output, (
            f"day {day_n}: simulate produced no Overseer panel at all")


def test_simulate_intro_text_resolves_for_every_alignment_band():
    """Calls `hackdox.py`'s own `_simulate_intro_text` helper directly —
    the exact function `simulate()` calls internally — for all three
    alignment bands on every banded-only day, since the `simulate` CLI
    itself has no `--alignment` flag and a CliRunner invocation alone can
    only ever exercise the neutral band (a freshly-seeded `GameState`
    starts at `config.STARTING_ALIGNMENT`, which is neutral). This is the
    'call the underlying function directly' half of the regression
    guard: it proves the banded resolution is not just non-crashing but
    correct, picking the right authored string per band.
    """
    from gameengine.core import content_loader, overseer
    from gameengine.hackdox import _simulate_intro_text

    narratives = content_loader.load_narratives()
    wh = config.ALIGNMENT_BAND_WHITE_HAT_THRESHOLD
    dw = config.ALIGNMENT_BAND_DARK_WEB_THRESHOLD

    for day_n in (14, 15, 16, 18, 19):
        day = load_day(day_n)
        for alignment, band in ((wh, "whitehat"), (0, "neutral"), (dw, "darkweb")):
            text = _simulate_intro_text(day, narratives, alignment)
            assert text, f"day {day_n} band {band}: empty intro text"
            expected_key = overseer.banded_key(day.overseer_intro_key, band)
            assert text == narratives[expected_key], (
                f"day {day_n} band {band}: resolved text did not match "
                f"the authored {expected_key!r} entry")


def test_chained_supersession_lets_a_directive_supersede_a_previous_directive(
        tmp_path, monkeypatch, day1):
    """Dedicated regression coverage for the `content_loader.
    _apply_rule_overrides` extension itself (#42/Phase 5b-1), independent of
    day 13's real content: a later `added_rules` entry can supersede an id
    introduced EARLIER IN THE SAME BATCH, not only an inherited (Day-1) id.

    Before this task, `_apply_rule_overrides` only accepted a `supersedes`/
    `removed_rules` target that was already in the INHERITED book —
    superseding a same-batch directive would have raised "which is not in
    this day's rulebook before removal", since `load_day` always rebuilds a
    day's book fresh from Day 1 and an earlier directive doesn't exist in
    that inherited book at all unless it's also re-listed. This test authors
    exactly that shape directly (bypassing day_13.json entirely) to prove
    the mechanism itself, not just day 13's specific use of it.
    """
    first = dict(_DW04_PAYLOAD_LENIENCY)  # supersedes the Day-1 rule, as usual
    second = {
        "id": "dw_test_chained_crackdown",
        "text": "Deny any candidate who submits an image hiding an "
                "encrypted or obfuscated payload — test chain.",
        "predicate": "has_discrepancy:encrypted_payload",
        "severity": "disqualifying",
        "mutability": "dark_web",
        "justification": "Test-only justification for the chained-"
                         "supersession regression guard.",
        "supersedes": first["id"],  # chained: names a SAME-BATCH id, not day-1
    }

    _write_directive_day(tmp_path, monkeypatch, 87,
                         added_rules=[first, second])
    loaded = load_day(87)
    ids = {r.id for r in loaded.rules}

    # `first` was only re-listed to give `second` something to supersede —
    # it must not itself survive into the final book.
    assert first["id"] not in ids, (
        "the re-listed intermediate directive must be dropped from the "
        "final book once a later same-batch entry supersedes it")
    assert second["id"] in ids, "the new directive must be in the final book"
    # The ORIGINAL day-1 rule (first's own supersedes target) is still gone
    # too — the chain has to reach all the way back, not just one link.
    assert "rule_encrypted_payload" not in ids
    assert loaded.directive_removed_rule_ids == {
        "rule_encrypted_payload", first["id"]}

    resolved = next(r for r in loaded.rules if r.id == second["id"])
    assert resolved.severity == "disqualifying"
    assert resolved.supersedes == first["id"]


def test_chained_supersession_unknown_target_still_raises(
        tmp_path, monkeypatch, day1):
    """The chained case must not accidentally loosen the existing "unknown
    id" guard — naming an id that is in NEITHER the inherited book NOR this
    batch is still a load-time error."""
    bad = {
        "id": "dw_test_bad_chain",
        "text": "Deny something.",
        "predicate": "has_discrepancy:encrypted_payload",
        "severity": "disqualifying",
        "mutability": "dark_web",
        "justification": "Test-only justification.",
        "supersedes": "some_id_never_introduced_anywhere",
    }
    _write_directive_day(tmp_path, monkeypatch, 86, added_rules=[bad])
    with pytest.raises(ValueError, match="supersedes"):
        load_day(86)


def test_chained_supersession_rejects_self_supersession(
        tmp_path, monkeypatch, day1):
    """Code-review fix (post-2b431b1): before this fix, `_apply_rule_
    overrides` validated every `supersedes` target against the FULL
    post-loop union of inherited-plus-added ids, so an entry naming its OWN
    id passed validation (its own id is trivially a member of that union)
    and then silently vanished from the final book — added and immediately
    removed, with no error and no briefing line. The fix checks each entry's
    `supersedes` against only the ids seen STRICTLY BEFORE it in the array,
    which an entry's own id never is."""
    self_superseding = {
        "id": "dw_test_self_supersede",
        "text": "Deny something.",
        "predicate": "has_discrepancy:encrypted_payload",
        "severity": "disqualifying",
        "mutability": "dark_web",
        "justification": "Test-only justification.",
        "supersedes": "dw_test_self_supersede",   # names itself
    }
    _write_directive_day(tmp_path, monkeypatch, 85,
                         added_rules=[self_superseding])
    with pytest.raises(ValueError, match="supersedes"):
        load_day(85)


def test_chained_supersession_rejects_mutual_supersession(
        tmp_path, monkeypatch, day1):
    """Code-review fix (post-2b431b1): two `added_rules` entries each naming
    the OTHER in `supersedes` used to pass the old post-loop validation (both
    ids are members of the full added-batch set) and then both vanish from
    the final book — a rulebook that silently lost two rules with no error.
    Positional validation makes this impossible: whichever entry is listed
    first has its `supersedes` checked before the second entry's id has been
    seen at all, so it fails regardless of which order the two are written
    in (checked both ways here)."""
    rule_a = {
        "id": "dw_test_mutual_a",
        "text": "Deny something A.",
        "predicate": "has_discrepancy:encrypted_payload",
        "severity": "disqualifying",
        "mutability": "dark_web",
        "justification": "Test-only justification A.",
        "supersedes": "dw_test_mutual_b",
    }
    rule_b = {
        "id": "dw_test_mutual_b",
        "text": "Deny something B.",
        "predicate": "has_discrepancy:credential_stuffing",
        "severity": "disqualifying",
        "mutability": "dark_web",
        "justification": "Test-only justification B.",
        "supersedes": "dw_test_mutual_a",
    }
    _write_directive_day(tmp_path, monkeypatch, 84,
                         added_rules=[rule_a, rule_b])
    with pytest.raises(ValueError, match="supersedes"):
        load_day(84)

    _write_directive_day(tmp_path, monkeypatch, 83,
                         added_rules=[rule_b, rule_a])
    with pytest.raises(ValueError, match="supersedes"):
        load_day(83)


def test_removed_rules_rejects_an_id_added_in_the_same_batch(
        tmp_path, monkeypatch, day1):
    """Code-review fix (post-2b431b1): `removed_rules` naming an id this
    same file's own `added_rules` just introduced used to pass the old
    post-loop validation (the added id is a member of the full addable-ids
    union) and net out to a silent no-op — the new rule quietly never
    actually lands, with no error. `removed_rules` now validates only
    against the INHERITED book; naming a same-batch `added_rules` id is
    rejected outright, since there is nothing legitimate for it to mean."""
    added = dict(_DW01_IDENTITY_LENIENCY)
    added.pop("supersedes")   # isolate this case from the supersedes path
    _write_directive_day(tmp_path, monkeypatch, 82,
                         added_rules=[added],
                         removed_rules=[added["id"]])
    with pytest.raises(ValueError, match="removed_rules"):
        load_day(82)


_ALL_KNOWN_DIRECTIVES_BY_ID = {
    d["id"]: d for d in (
        _DW01_IDENTITY_LENIENCY, _DW02_FORUM_LENIENCY,
        _DW03_STUFFING_LENIENCY, _DW04_PAYLOAD_LENIENCY,
        _DW05_PAYLOAD_CRACKDOWN, _DW06_HOSTILE_PAYLOAD_LENIENCY,
    )
}


def test_every_authored_day_file_matches_the_canonical_directive_copy():
    """Code-review followup (post-2b431b1): DW-01..05's copy is duplicated
    verbatim across every real day file that re-lists it, PLUS
    CONTENT_AUTHORING.md, PLUS these test constants — and until now,
    cross-consistency was only checked for the specific days each phase's
    tests happened to enumerate (days 8-12 via _PHASE3_DIRECTIVE_DAYS and
    day 12's own test; days 13/17/20 via the #42/Phase-5b-1 tests above). A
    typo introduced while re-listing a directive on some OTHER day — one
    none of those enumerated tests happens to cover — would silently drift
    and never be caught by any existing test.

    This sweeps EVERY real day_*.json in config.DAYS_DIR, and for every
    `added_rules` entry whose id names a KNOWN directive (one of the five
    canonical dicts above, kept in sync with CONTENT_AUTHORING.md by hand —
    see the #37/#40 section's own docstring for that convention), asserts
    the entry is byte-identical to the canonical copy: full dict equality,
    not just the handful of fields other tests happen to spot-check. This
    also automatically covers Phase 5b-2's upcoming day files (14-16/18-19)
    once they exist, with no test changes required on that end — any day
    file that re-lists a known directive id gets checked, full stop.
    """
    import json

    day_files = sorted(config.DAYS_DIR.glob("day_*.json"))
    assert len(day_files) >= 8, (
        "sanity: expected at least the days-8-13/17/20 directive-carrying "
        "files to exist under config.DAYS_DIR")

    checked_any = False
    for path in day_files:
        raw = json.loads(path.read_text(encoding="utf-8"))
        for entry in raw.get("added_rules", []):
            canonical = _ALL_KNOWN_DIRECTIVES_BY_ID.get(entry.get("id"))
            if canonical is None:
                continue
            checked_any = True
            assert entry == canonical, (
                f"{path.name}: added_rules entry {entry.get('id')!r} has "
                f"drifted from the canonical directive copy in "
                f"CONTENT_AUTHORING.md / test_engine_foundation.py — "
                f"got {entry!r}, expected {canonical!r}")

    assert checked_any, (
        "sanity: no day file's added_rules matched any known directive id — "
        "if this fires, either the day files or "
        "_ALL_KNOWN_DIRECTIVES_BY_ID have drifted apart in id naming, and "
        "this test is silently checking nothing")


# ─── Issue #73 — the dossier-tier evidence guard ─────────────────────────────
#
# EVIDENCE_TOKENS above covers the TOOL tiers: for each kind, a snippet that
# must appear in that tool's filtered output when the kind is planted and must
# not when it isn't. It deliberately skipped DOSSIER-tier kinds, on the
# reasoning that their evidence is "structural" rather than tool output.
#
# That exemption is a blind spot, and two shipped bugs came through it:
#
#   #51  MISSING_PUBLIC_PROFILE was tiered DOSSIER with NO dossier evidence at
#        all — claimed_github came from the archetype's handle style, not from
#        whether the kind was planted. 300 of 600 day-1 candidates carried an
#        unflaggable violation and nothing caught it until Nick found it in play.
#   #57  DISPOSABLE_EMAIL's generator pool and detector list drifted apart, so
#        37% of carriers were undetectable. Same blind spot, same silence.
#
# Both fixes repaired one kind and left the gap open. This closes it.
#
# The dossier-tier shape of "observable" is a PREDICATE over the free surfaces
# — what the dossier panel renders, plus the chat script, which is the other
# thing the player gets without spending ⏱. For each DOSSIER-tier kind the
# predicate must be TRUE for every carrier and FALSE for every non-carrier.
# One direction alone is not enough, and they catch different bugs:
#
#   true-for-every-carrier   → catches "planted but never rendered" (#51)
#   false-for-every-other    → catches "rendered for everyone", which is a tell
#                              that gives the violation away for free (#78's
#                              image field was exactly this)
#
# A kind with no predicate that can satisfy both is unflaggable, which is the
# thing being guarded against.

def _free_surface(candidate) -> tuple[str, frozenset[str]]:
    """Everything the player can read without spending ⏱.

    The rendered dossier panel plus the chat script's tags. DossierPanel.render
    is a pure function of the candidate, so this needs no Textual app.
    """
    from gameengine.ui.tui.widgets.dossier import DossierPanel

    panel = DossierPanel()
    panel.set_candidate(candidate)
    return panel.render(), frozenset(ln.tag for ln in candidate.chat_script)


# kind -> (name, predicate over (candidate, rendered dossier, chat tags))
DOSSIER_EVIDENCE = {
    # The chat panel is the surface; the evidence tag is what the Sentiment
    # Scanner keys its ⚠ on. #77 split this from the archetype's "voice" tag
    # precisely so this predicate can be true of carriers ONLY.
    DiscrepancyKind.HOSTILE_CHAT: (
        "a chat line carrying the hostile EVIDENCE tag",
        lambda c, dossier, tags: "hostile" in tags),

    # #56's sentinel. Named in the generator rather than inlined so that this
    # sweep can recognise it.
    DiscrepancyKind.AFFILIATION_NOT_STATED: (
        f"the affiliation field reads {candidate_gen.NO_AFFILIATION_STATED!r}",
        lambda c, dossier, tags:
            c.claimed_affiliation == candidate_gen.NO_AFFILIATION_STATED),

    # #57's exact failure, and the predicate has to read the DETECTOR's list to
    # see it. tools_bridge._GS_SUSPICIOUS_DOMAINS is what the rules page renders
    # as "DISPOSABLE" (rules_content.py:1044) — the list the player is actually
    # told to match an email against. candidate_gen.DOMAINS_DISPOSABLE is what
    # the generator draws from.
    #
    # An earlier draft of this predicate read the GENERATOR's list, and a revert
    # check caught it: mutating that list moved both sides at once, so the drift
    # #57 was about became invisible and the guard stayed green. Reading the
    # detector is the whole point — if the two lists separate again, carriers
    # stop satisfying this and the guard goes red, which is what #57 needed and
    # did not have.
    DiscrepancyKind.DISPOSABLE_EMAIL: (
        "the email domain is on the list the rules page shows as disposable",
        lambda c, dossier, tags:
            c.email.rsplit("@", 1)[-1] in tools_bridge._GS_SUSPICIOUS_DOMAINS),

    # Moved fully to DOSSIER 2026-09-15. The plaintext and the ⚠ marker are
    # printed by _password_markup with no tool run at all.
    DiscrepancyKind.UNSALTED_STORAGE: (
        "the password field is printed in the clear and marked UNSALTED",
        lambda c, dossier, tags: "UNSALTED" in dossier),
}


def _dossier_tier_kinds() -> set[DiscrepancyKind]:
    from gameengine.core.models import ToolName
    return {k for k, (tool, _sev) in candidate_gen._SEVERITY_REVEAL.items()
            if tool is ToolName.DOSSIER}


def test_every_dossier_tier_kind_has_a_declared_evidence_predicate():
    """The completeness half — mirrors the tool-tier table's own check.

    Without this, adding a DOSSIER-tier kind silently opts it out of the guard
    below, which is exactly how #51 and #57 shipped. The point of the issue is
    that a future kind is checked BY DEFAULT rather than by anyone remembering.
    """
    missing = sorted(k.name for k in _dossier_tier_kinds()
                     if k not in DOSSIER_EVIDENCE)
    assert not missing, (
        f"DOSSIER-tier kinds with no declared dossier evidence: {missing}. "
        f"Add a predicate to DOSSIER_EVIDENCE describing what the player can "
        f"actually see, or the kind is scoreable but unflaggable.")
    stale = sorted(k.name for k in DOSSIER_EVIDENCE
                   if k not in _dossier_tier_kinds())
    assert not stale, (
        f"DOSSIER_EVIDENCE describes kinds that are no longer dossier-tier: "
        f"{stale} — their evidence belongs in EVIDENCE_TOKENS now")


def test_dossier_tier_evidence_is_present_for_carriers_and_absent_for_others():
    """The blind spot itself, closed in both directions.

    Sweeps real generated candidates rather than constructing them, because
    both bugs this replaces were about the GENERATOR and the renderer
    disagreeing — a constructed candidate would be built to satisfy whichever
    of the two the test author had in mind.
    """
    seen: dict[DiscrepancyKind, list[int]] = {k: [0, 0, 0, 0]
                                              for k in DOSSIER_EVIDENCE}
    for seed in range(25):
        for day_number in range(1, config.CAMPAIGN_LAST_DAY + 1):
            day = load_day(day_number)
            for slot in range(day.candidate_count):
                c = candidate_gen.generate(seed, day, slot)
                dossier, tags = _free_surface(c)
                kinds = {d.kind for d in c.truth.discrepancies}
                for kind, (_name, predicate) in DOSSIER_EVIDENCE.items():
                    holds = bool(predicate(c, dossier, tags))
                    carrier = kind in kinds
                    # [carriers, carriers-without-evidence,
                    #  non-carriers, non-carriers-with-evidence]
                    if carrier:
                        seen[kind][0] += 1
                        seen[kind][1] += not holds
                    else:
                        seen[kind][2] += 1
                        seen[kind][3] += holds

    for kind, (name, _pred) in DOSSIER_EVIDENCE.items():
        carriers, blind, others, leaks = seen[kind]
        assert carriers, f"guard is inert — no {kind.name} carrier generated"
        assert others, f"guard is inert — no {kind.name} non-carrier generated"
        assert blind == 0, (
            f"{blind} of {carriers} {kind.name} carriers show no dossier "
            f"evidence ({name}) — those are scoreable but unflaggable, which "
            f"is the #51 / #57 failure this guard exists for")
        assert leaks == 0, (
            f"{leaks} of {others} NON-carriers of {kind.name} show its "
            f"evidence ({name}) — the marker is on everyone, so it identifies "
            f"nothing and misleads a player who trusts it")
