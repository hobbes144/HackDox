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
    assert intro_day(DiscrepancyKind.AFFILIATION_NOT_STATED) == 1   # dossier
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


# ─── Issue #4 — difficulty curve ────────────────────────────────────────────


def test_reward_decay_shape_and_floors():
    admit = [config.DAY_REWARD_PAYOUT(d, True)  for d in range(1, 30)]
    deny  = [config.DAY_REWARD_PAYOUT(d, False) for d in range(1, 30)]

    # Tutorial days pay the undecayed rate (#15: days 1-5 stay flat-easy).
    assert admit[:4] == [config.HACKDOLLAR_PER_CORRECT_ADMIT] * 4
    assert deny[:4]  == [config.HACKDOLLAR_PER_CORRECT_DENY] * 4
    # Monotonically non-increasing, and bottoming out at the floors.
    assert all(b <= a for a, b in zip(admit, admit[1:]))
    assert all(b <= a for a, b in zip(deny, deny[1:]))
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
    assert config.FILTER_COSTS["ghostscan"] == 3
    assert config.STEGO_STAMP_COST == 1
    # Neither constant is a function of the day; nothing to inflate them.
    assert isinstance(config.FILTER_COSTS["ghostscan"], int)
    assert isinstance(config.STEGO_STAMP_COST, int)


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
    base = load_day(1)
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
    from gameengine.core import tools_bridge
    import random as _r

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
    from dataclasses import replace
    from gameengine.core import tools_bridge
    import random as _r

    base = load_day(1)
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


def _tool_tier_kinds() -> dict[DiscrepancyKind, "object"]:
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
    base = load_day(1)
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
    """Present-when-planted: the evidence the player is scored on must exist."""
    token = EVIDENCE_TOKENS[kind]
    pairs = _candidates_by_kind(kind, want=True, limit=1)
    if not pairs:
        pytest.skip(f"no archetype currently rolls {kind.name}")
    candidate, day, seed = pairs[0]
    out = _filtered_output(candidate, kind, day, seed)
    assert token in out, (
        f"{kind.name} is planted on {candidate.archetype.value} and revealed by "
        f"{candidate_gen._SEVERITY_REVEAL[kind][0].value}, but its filtered "
        f"output never shows {token!r}. The player cannot flag what the tool "
        f"does not render."
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
    base = load_day(1)
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

    base = load_day(1)
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
    base = load_day(1)
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
    base = load_day(1)
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
    base = load_day(1)
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
    base = load_day(1)
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

    base = load_day(1)
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

    base = load_day(1)
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

    base = load_day(1)
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

    base = load_day(1)
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
    base = load_day(1)
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

    base = load_day(1)
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

    base = load_day(1)
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
    base = load_day(1)
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

    base = load_day(1)
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
