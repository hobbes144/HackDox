"""Endless Mode (#7).

Organised around the things that would quietly ruin it:

  * **The campaign must not move.** Endless lives in its own day-number range
    (config.ENDLESS_DAY_BASE); only the difficulty curves are remapped, through
    config.curve_day, and that must be the identity on every campaign day.
  * **Nothing gated, nothing from the campaign.** Shift 1 has the whole kit;
    no Dark Web or White Hat ever appears; authored campaign days are never
    read; no tutorial beats play.
  * **Bounded.** Every curve plateaus — no shift, however late, becomes
    arithmetically unplayable or blows up the log volume.
  * **The run's rules.** Rolling accuracy (70% over 5 shifts, only once 5 are
    played), separate save slot, maintenance roll, escalating shop, personal
    best.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from gameengine import config
from gameengine.core import candidate_gen, content_loader, endless, persistence, shop, tools_bridge
from gameengine.core.content_loader import kinds_discovered_through, load_day
from gameengine.core.models import (
    Archetype,
    CandidateResult,
    GameMode,
    GameState,
    Performance,
    ShiftRecord,
    Verdict,
)
from gameengine.core.overseer import resolve_endless_narrative

ALL_TOOLS = {t for t in config.TOOL_UNLOCK_DAY if t != "dossier"}
FAR = 500   # "as late as anyone will ever play"


def E(shift: int) -> int:
    return config.endless_day_number(shift)


@pytest.fixture
def slots(tmp_path, monkeypatch):
    """Point every save/record file at a temp dir — tests must never touch the
    player's real saves."""
    monkeypatch.setattr(config, "SAVE_FILE", tmp_path / "slot_0.json")
    monkeypatch.setattr(config, "ENDLESS_SAVE_FILE", tmp_path / "endless_0.json")
    monkeypatch.setattr(config, "ENDLESS_RECORDS_FILE", tmp_path / "endless_records.json")
    return tmp_path


def _state_with_history(accs: list[tuple[int, int]]) -> GameState:
    st = endless.new_endless_state(seed=7)
    for i, (correct, judged) in enumerate(accs, start=1):
        st.shift_history.append(ShiftRecord(shift=i, correct=correct, judged=judged))
        st.lifetime_correct += correct
        st.lifetime_judged += judged
    st.current_day = E(len(accs) + 1)
    return st


# ─── The campaign does not move ─────────────────────────────────────────────


def test_curve_day_is_the_identity_on_every_campaign_day():
    for n in range(1, config.CAMPAIGN_LAST_DAY + 1):
        assert config.curve_day(n) == n
        assert not config.is_endless_day(n)


def test_the_endless_range_sits_above_every_unlock_day():
    top = max(config.CAMPAIGN_LAST_DAY, *config.TOOL_UNLOCK_DAY.values(),
              *config.BREACH_DB_UNLOCK_DAY.values(),
              *(on for _b, on, _a in candidate_gen._SEVERITY_BY_DAY.values()))
    assert E(1) > top


# ─── The curve: Option A, a bit past the campaign, then flat ────────────────


def test_endless_curve_shape():
    days = [config.endless_curve_day(s) for s in range(1, FAR + 1)]
    assert days[0] == config.ENDLESS_CURVE_START
    assert days[config.ENDLESS_CURVE_CAMPAIGN_SHIFT - 1] == config.CAMPAIGN_LAST_DAY
    assert max(days) == config.ENDLESS_CURVE_CEILING > config.CAMPAIGN_LAST_DAY
    assert all(a <= b for a, b in zip(days, days[1:])), "curve must never ease off"
    ceil_at = days.index(config.ENDLESS_CURVE_CEILING) + 1
    assert ceil_at == config.ENDLESS_CURVE_CEILING_SHIFT
    assert set(days[ceil_at - 1:]) == {config.ENDLESS_CURVE_CEILING}, "must plateau"


def test_every_difficulty_lever_plateaus():
    at_ceiling, far = E(config.ENDLESS_CURVE_CEILING_SHIFT), E(FAR)
    for fn in (config.DAY_CANDIDATE_COUNT, config.tool_cost_inflation,
               config.difficulty_band_for_day):
        assert fn(far) == fn(at_ceiling)
    assert (config.daily_compute_budget(far, 60)
            == config.daily_compute_budget(at_ceiling, 60))
    assert config.DAY_REWARD_PAYOUT(far, True) == config.DAY_REWARD_PAYOUT(at_ceiling, True)
    assert config.DAY_CANDIDATE_COUNT(far) <= config.ENDLESS_CANDIDATE_COUNT_CAP
    # ...and ends a bit harder than the campaign's last day.
    last = config.CAMPAIGN_LAST_DAY
    assert config.DAY_CANDIDATE_COUNT(far) > config.DAY_CANDIDATE_COUNT(last)
    assert config.tool_cost_inflation(far) >= config.tool_cost_inflation(last)


def test_logwatch_volume_is_capped():
    """The raw curve is ×1.15/day — ~12,000 rows by day 40 without the cap."""
    day = load_day(E(FAR))
    noise = [e for e in tools_bridge.generate_day_log(3, day)]
    assert len(noise) <= config.LW_ENTRIES_MAX + 20 * day.candidate_count


def test_grids_are_capped_far_out():
    day = load_day(E(FAR))
    for slot in range(day.candidate_count):
        c = candidate_gen.generate(11, day, slot)
        img = tools_bridge.build_stego_image(c, day.number)
        blk = tools_bridge.build_cipher_block(c, day.number)
        assert img.cols <= config.STEGO_GRID_MAX[0] and img.rows <= config.STEGO_GRID_MAX[1]
        assert blk.cols <= config.CIPHER_GRID_MAX[0] and blk.rows <= config.CIPHER_GRID_MAX[1]


# ─── Nothing gated, nothing from the campaign ───────────────────────────────


def test_shift_one_has_the_whole_kit():
    st = endless.new_endless_state(seed=1)
    assert st.is_endless and st.unlocked_tools == ALL_TOOLS
    assert config.breach_dbs_unlocked_by(st.current_day) == \
        config.breach_dbs_unlocked_by(config.CAMPAIGN_LAST_DAY)
    for s in range(1, 30):
        assert config.tool_introduced_on(E(s)) is None, "a tutorial unlock beat would play"
    # Every kind the campaign ever teaches (bar the Dark-Web-only arc) is live.
    assert kinds_discovered_through(E(1)) >= (
        kinds_discovered_through(config.CAMPAIGN_LAST_DAY)
        - _dark_web_and_white_hat_only_kinds())


def _dark_web_and_white_hat_only_kinds():
    day = content_loader.synthesize_day(config.CAMPAIGN_LAST_DAY - 1)
    without = replace(day, archetype_mix={
        a: n for a, n in day.archetype_mix.items()
        if a not in (Archetype.DARK_WEB, Archetype.WHITE_HAT)})
    return (candidate_gen.kinds_the_day_can_plant(day)
            - candidate_gen.kinds_the_day_can_plant(without))


def test_no_dark_web_or_white_hat_ever():
    for shift in (1, 2, 5, 9, 15, 22, 30, 60):
        day = load_day(E(shift))
        assert not ({Archetype.DARK_WEB, Archetype.WHITE_HAT} & set(day.archetype_mix))
        for seed in (1, 99):
            for slot in range(day.candidate_count):
                c = candidate_gen.generate(seed, day, slot)
                assert c.archetype not in (Archetype.DARK_WEB, Archetype.WHITE_HAT)
                assert c.truth.moral_modifier == 0


def test_endless_days_never_read_authored_campaign_content():
    for shift in range(1, 25):
        day = load_day(E(shift))
        assert day.title == f"Shift {shift}"
        assert not day.forced_includes and not day.forced_violations
        assert day.rule_sheet is None
        assert all(r.mutability != "dark_web" for r in day.rules)
        assert not day.directive_removed_rule_ids
        assert day.overseer_intro_key.startswith("endless_")


def test_rules_still_flip_between_shifts():
    """#7 keeps Overseer-Variable changes — cooperatively explained, but real."""
    from gameengine.core import rules_engine
    changed = sum(bool(rules_engine.diff_rulesets(load_day(E(s)), load_day(E(s + 1))))
                  for s in range(1, 30))
    assert changed > 0


# ─── The rolling-accuracy loss condition ────────────────────────────────────


def test_accuracy_loss_waits_for_a_full_window():
    st = _state_with_history([(0, 8)] * (config.ENDLESS_ACCURACY_WINDOW - 1))
    assert not endless.accuracy_check_active(st)
    assert not endless.accuracy_below_loss(st), "a bad start must not end the run"
    st = _state_with_history([(0, 8)] * config.ENDLESS_ACCURACY_WINDOW)
    assert endless.accuracy_below_loss(st)


def test_accuracy_threshold_boundary_and_weighting():
    # exactly on the line survives
    st = _state_with_history([(7, 10)] * 5)
    assert endless.rolling_accuracy(st) == pytest.approx(0.70)
    assert not endless.accuracy_below_loss(st)
    # verdict-weighted, not shift-averaged: 13/14 and 0/1 is 13/15, not 50%
    st = _state_with_history([(7, 10)] * 3 + [(13, 14), (0, 1)])
    assert endless.rolling_accuracy(st) == pytest.approx((21 + 13) / (30 + 15))
    # only the last WINDOW shifts count
    st = _state_with_history([(0, 10)] * 10 + [(10, 10)] * 5)
    assert endless.rolling_accuracy(st) == 1.0


def test_the_campaign_never_trips_the_accuracy_rule():
    st = _state_with_history([(0, 8)] * 8)
    st.mode = GameMode.CAMPAIGN.value
    assert not endless.accuracy_below_loss(st)


def test_trend():
    assert endless.trend(_state_with_history([(5, 10)])) == "new"
    assert endless.trend(_state_with_history([(5, 10)] * 5 + [(10, 10)])) == "rising"
    assert endless.trend(_state_with_history([(9, 10)] * 5 + [(2, 10)])) == "falling"
    assert endless.trend(_state_with_history([(8, 10)] * 6)) == "steady"


def _result(correct: bool) -> CandidateResult:
    return CandidateResult("x", Archetype.BAD_ACTOR, Verdict.DENY, correct, 0, 0, 0.0, 0)


def test_record_shift_is_idempotent_per_shift():
    st = endless.new_endless_state(seed=3)
    st.pending_results = [_result(True), _result(False)]
    endless.record_shift(st)
    endless.record_shift(st)   # e.g. quit at EOD, resumed, replayed the shift
    assert len(st.shift_history) == 1
    assert (st.lifetime_correct, st.lifetime_judged) == (1, 2)


def test_history_is_trimmed_but_lifetime_totals_are_not():
    st = _state_with_history([(1, 2)] * (config.ENDLESS_HISTORY_KEEP + 10))
    st.pending_results = [_result(True)]
    endless.record_shift(st)
    assert len(st.shift_history) == config.ENDLESS_HISTORY_KEEP
    assert st.lifetime_judged == 2 * (config.ENDLESS_HISTORY_KEEP + 10) + 1


# ─── Separate save slots ────────────────────────────────────────────────────


def test_endless_and_campaign_saves_never_touch(slots):
    camp = GameState(seed=1, current_day=7, hackdollars=180)
    persistence.save(camp)
    run = endless.new_endless_state(seed=2)
    run.shift_history.append(ShiftRecord(shift=1, correct=6, judged=7))
    run.shop_purchases["capacity"] = 2
    persistence.save(run)

    assert config.SAVE_FILE.exists() and config.ENDLESS_SAVE_FILE.exists()
    c = persistence.load(GameMode.CAMPAIGN.value)
    e = persistence.load(GameMode.ENDLESS.value)
    assert (c.mode, c.current_day, c.hackdollars) == ("campaign", 7, 180)
    assert e.is_endless and e.shift_history == run.shift_history
    assert e.maintenance_upgrades == run.maintenance_upgrades
    assert e.shop_purchases == {"capacity": 2}
    assert persistence.describe("campaign") == "Day 7 · 180 HD$"
    assert persistence.describe("endless").startswith("Shift 1 ")


def test_a_pre_endless_save_loads_as_a_campaign(slots):
    config.SAVE_FILE.write_text(json.dumps({"seed": 5, "current_day": 4}), encoding="utf-8")
    st = persistence.load()
    assert st.mode == "campaign" and not st.is_endless
    assert st.shift_history == [] and st.maintenance_upgrades == set()


# ─── Economy: maintenance, escalation, patch, credit slots ──────────────────


def test_maintenance_roll():
    ids = {uid for uid, *_ in config.UPGRADE_CATALOG}
    rolls = [endless.roll_maintenance(seed) for seed in range(40)]
    assert all(len(r) == config.ENDLESS_MAINTENANCE_COUNT and r <= ids for r in rolls)
    assert endless.roll_maintenance(12) == endless.roll_maintenance(12), "must survive a reload"
    assert len({frozenset(r) for r in rolls}) > 30, "runs should differ"
    assert GameState(seed=1).maintenance_upgrades == set(), "never in the campaign"


def test_shop_refuses_maintenance_items():
    st = endless.new_endless_state(seed=4)
    st.hackdollars = 10_000
    item = next(i for i in shop.items_for(st)
                if i.kind == "upgrade" and i.iid in st.maintenance_upgrades)
    ok, msg = shop.buy(st, item)
    assert not ok and "maintenance" in msg and item.iid not in st.upgrades
    assert st.hackdollars == 10_000


def test_capacity_escalates_in_endless_only():
    run, camp = endless.new_endless_state(seed=5), GameState(seed=5)
    for st in (run, camp):
        st.hackdollars = 10_000
    cap = next(i for i in shop.items_for(run) if i.kind == "capacity")
    prices = []
    for _ in range(3):
        prices.append(shop.price_of(run, cap))
        assert shop.buy(run, cap)[0]
    assert prices == [config.SHOP_PRICE_CAPACITY + k * config.SHOP_CAPACITY_PRICE_STEP
                      for k in range(3)]
    shop.buy(camp, cap)
    assert shop.price_of(camp, cap) == config.SHOP_PRICE_CAPACITY


def test_site_patch_is_endless_only_and_caps_at_full():
    assert not any(i.kind == "site_patch" for i in shop.items_for(GameState(seed=1)))
    st = endless.new_endless_state(seed=6)
    st.hackdollars, st.site_health = 10_000, config.SITE_HEALTH_MAX - 3
    patch = next(i for i in shop.items_for(st) if i.kind == "site_patch")
    first = shop.price_of(st, patch)
    assert shop.buy(st, patch)[0]
    assert st.site_health == config.SITE_HEALTH_MAX
    assert shop.price_of(st, patch) == first + config.SHOP_SITE_PATCH_PRICE_STEP
    assert shop.status_of(st, patch) == "full"


def test_credit_slots():
    assert shop.credit_cap(GameState(seed=1)) == config.HACKDOX_CREDIT_MAX
    assert shop.credit_cap(endless.new_endless_state(seed=1)) == config.ENDLESS_HACKDOX_CREDIT_MAX


# ─── Personal best ──────────────────────────────────────────────────────────


def test_finish_run_records_best_and_clears_only_the_endless_slot(slots):
    persistence.save(GameState(seed=1, current_day=9))
    run = _state_with_history([(8, 10)] * 12)
    persistence.save(run)
    rec, prev, new_best = endless.finish_run(run)
    assert new_best and prev is None and rec.shifts == 12
    assert not config.ENDLESS_SAVE_FILE.exists()
    assert config.SAVE_FILE.exists(), "the campaign save must survive"
    assert endless.personal_best().shifts == 12

    worse = _state_with_history([(8, 10)] * 6)
    _rec, prev, new_best = endless.finish_run(worse)
    assert not new_best and prev.shifts == 12
    assert endless.personal_best().shifts == 12
    assert endless.load_records()["runs"] == 2

    tie_better = _state_with_history([(10, 10)] * 12)
    assert endless.finish_run(tie_better)[2], "same shifts, better accuracy wins"


# ─── The cooperative Foreman ────────────────────────────────────────────────


def test_endless_narrative_prefers_the_most_specific_key():
    st = _state_with_history([(5, 10)] * 5 + [(10, 10)])  # rising, in danger? no
    n = {"endless_intro_rising": "UP", "endless_intro": "BASE", "generic_intro": "GEN"}
    assert resolve_endless_narrative(n, st, "intro") == "UP"
    n.pop("endless_intro_rising")
    assert resolve_endless_narrative(n, st, "intro") == "BASE"
    assert resolve_endless_narrative({"generic_intro": "GEN"}, st, "intro") == "GEN"
    first = endless.new_endless_state(seed=1)
    assert resolve_endless_narrative({"endless_intro_first": "HI", "endless_intro": "X"},
                                     first, "intro") == "HI"
    lost = _state_with_history([(1, 10)] * 5)
    assert resolve_endless_narrative({"endless_between_lost": "BYE", "endless_between": "X"},
                                     lost, "between") == "BYE"
    assert resolve_endless_narrative({"endless_outro_poor": "P"}, st, "outro",
                                     Performance.POOR) == "P"


def test_every_endless_beat_is_authored():
    """The shipped overseer.json covers every Endless beat and trend, so no
    shift ever falls through to campaign copy."""
    narr = content_loader.load_narratives()
    for key in (["endless_intro_first", "endless_intro_danger", "endless_intro",
                 "endless_between_lost", "endless_between_danger", "endless_between"]
                + [f"endless_intro_{t}" for t in ("new", "rising", "steady", "falling")]
                + [f"endless_between_{t}" for t in ("new", "rising", "steady", "falling")]
                + [f"endless_outro_{p.value}" for p in Performance]):
        assert narr.get(key), f"overseer.json is missing {key}"


# ─── App flow (headless pilot) ──────────────────────────────────────────────


def _pilot(fn, size=(140, 44)):
    from gameengine.ui.tui.app import HackDoxApp

    async def go():
        original = config.TRANSITION_ENABLED
        config.TRANSITION_ENABLED = False
        try:
            app = HackDoxApp()
            async with app.run_test(size=size) as pilot:
                await pilot.pause()
                await fn(app, pilot)
        finally:
            config.TRANSITION_ENABLED = original

    asyncio.run(go())


def test_menu_labels_both_saves(slots):
    from textual.widgets import Button, Static
    persistence.save(GameState(seed=1, current_day=7, hackdollars=180))
    persistence.save(endless.new_endless_state(seed=2))

    async def check(app, pilot):
        labels = {b.id: str(b.label) for b in app.screen.query(Button) if b.display}
        assert labels["menu-continue"] == "Continue Campaign · Day 7 · 180 HD$"
        assert labels["menu-continue-endless"].startswith("Continue Endless · Shift 1")
        saves = str(app.screen.query_one("#menu-saves", Static).render())
        assert "separate saves" in saves

    _pilot(check)


def test_endless_run_start_to_game_over(slots):
    from gameengine.ui.tui.screens.between_day import BetweenDayScreen
    from gameengine.ui.tui.screens.briefing import BriefingScreen
    from gameengine.ui.tui.screens.endless_over import EndlessOverScreen

    async def play(app, pilot):
        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, BriefingScreen)
        st = app._state
        assert st.is_endless and st.unlocked_tools == ALL_TOOLS
        assert app.screen._unlock_tool is None
        assert config.ENDLESS_SAVE_FILE.exists() and not config.SAVE_FILE.exists()

        # Play five terrible shifts through the real day-boundary methods.
        for shift in range(1, config.ENDLESS_ACCURACY_WINDOW + 1):
            app.begin_intake()
            await pilot.pause()
            st.pending_results = [_result(False)] * app._day.candidate_count
            app.finish_day()
            await pilot.pause()
            assert len(st.shift_history) == shift
            app.show_between_day()
            await pilot.pause()
            assert isinstance(app.screen, BetweenDayScreen)
            app.screen.action_next_day()
            await pilot.pause()
            if shift < config.ENDLESS_ACCURACY_WINDOW:
                assert isinstance(app.screen, BriefingScreen), "lost before the window filled"
                assert app._day.title == f"Shift {shift + 1}"
        assert isinstance(app.screen, EndlessOverScreen)
        assert app.screen._reason == "accuracy"
        assert not config.ENDLESS_SAVE_FILE.exists()
        assert endless.personal_best().shifts == config.ENDLESS_ACCURACY_WINDOW

        await pilot.press("r")          # R = a new Endless run, not the campaign
        await pilot.pause()
        assert isinstance(app.screen, BriefingScreen) and app._state.is_endless
        assert len(app._state.shift_history) == 0

    _pilot(play)


def test_endless_sails_past_the_campaigns_last_day(slots):
    from gameengine.ui.tui.screens.briefing import BriefingScreen

    async def play(app, pilot):
        st = endless.new_endless_state(seed=9)
        st.current_day = E(config.CAMPAIGN_LAST_DAY + 5)
        app.resume_game(st)
        await pilot.pause()
        app.advance_day()
        await pilot.pause()
        assert isinstance(app.screen, BriefingScreen)
        assert app._day.title == f"Shift {config.CAMPAIGN_LAST_DAY + 6}"

    _pilot(play)
