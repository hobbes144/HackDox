"""Balance guards (#70 campaign pass, #7 Endless, second pass 2026-09-25) —
the properties the balance passes tuned for, asserted through the same
simulator (`sim_balance.py`, repo root) so a later config retune that breaks
one fails here instead of in a playtest.

These assert DESIGN TARGETS, not exact numbers, so ordinary tuning inside the
targets never needs this file touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from gameengine import config
from gameengine.core.content_loader import load_day

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import sim_balance as sb  # noqa: E402

SEEDS = list(range(1, 5))
SHARP, SOLID, SHAKY, SLOPPY = sb.PROFILES


@pytest.fixture(scope="module")
def campaign():
    days = [(f"D{n}", load_day(n)) for n in range(1, config.CAMPAIGN_LAST_DAY + 1)]
    return sb.walk(days, SEEDS, config.STARTING_COMPUTE)


@pytest.fixture(scope="module")
def endless_run():
    days = [(f"S{s}", load_day(config.endless_day_number(s))) for s in range(1, 41)]
    return sb.walk(days, SEEDS, config.STARTING_COMPUTE)


# ─── ⏱ ──────────────────────────────────────────────────────────────────────


def test_correct_play_is_always_affordable(campaign, endless_run):
    """#70 AC: no day makes correct play impossible on ⏱ — the cheapest
    decisive evidence for every deny fits the day's budget, worst seed."""
    for d in [*campaign, *endless_run]:
        assert d.need_max <= d.budget, f"{d.label}: need {d.need_max} > budget {d.budget}"


def test_compute_is_liberal_early_and_restrictive_late(campaign, endless_run):
    """Nick (2026-09-25): hours start very liberal and tighten as the work
    grows. `cover` = how much of a check-everything shift (above the bare
    minimum) the budget pays for."""
    by_day = {d.number: d for d in campaign}
    for n in range(2, 8):          # the tutorial and the first free days
        assert by_day[n].cover >= 0.9, f"day {n}: cover {by_day[n].cover:.2f}"
    assert by_day[10].cover < by_day[7].cover
    assert by_day[15].cover < by_day[10].cover
    assert by_day[20].cover <= 0.35
    plateau = [d for d in endless_run if config.curve_day(d.number) == config.ENDLESS_CURVE_CEILING]
    assert plateau and max(d.cover for d in plateau) <= 0.3


# ─── Money ──────────────────────────────────────────────────────────────────


def test_nobody_can_buy_the_whole_catalog_by_day_20(campaign, endless_run):
    """Buying every upgrade by day 20 must be impossible, in both modes — even
    for a perfect player who spends on nothing else. Endless is measured
    against what it can actually buy (maintenance, Endless prices)."""
    for stats, endless in ((campaign, False), (endless_run, True)):
        cat = sb.available_catalog(endless)
        for p in (sb.PERFECT, sb.Profile("perfect-resist", 0.0, 1.0, "deny")):
            bank = sb.expected_economy(stats, p)[19]["bank"]
            assert bank < 0.9 * cat, f"endless={endless}/{p.name}: {bank:.0f} of {cat}"
    # ...while a solid player can still afford a meaningful chunk of it.
    assert sb.expected_economy(campaign, SOLID)[19]["bank"] > 0.35 * sb.catalog_total()


def _mean_hd(eco, lo, hi):
    rows = eco[lo - 1:hi]
    return sum(r["hd"] for r in rows) / len(rows)


def test_marking_violations_becomes_necessary(campaign, endless_run):
    """Nick (2026-09-25): a player who gets verdicts right but doesn't record
    the violations should be squeezed for money later on — close to a careful
    player early, well behind late."""
    for stats, late_gap in ((campaign, 0.55), (endless_run, 0.35)):
        sharp, sloppy = (sb.expected_economy(stats, p) for p in (SHARP, SLOPPY))
        assert _mean_hd(sloppy, 1, 7) >= 0.7 * _mean_hd(sharp, 1, 7)
        n = len(stats)
        assert _mean_hd(sloppy, n - 5, n) <= late_gap * _mean_hd(sharp, n - 5, n)
        assert sloppy[19]["bank"] < 0.7 * sharp[19]["bank"]


def test_late_pay_comes_from_the_board():
    last = config.CAMPAIGN_LAST_DAY
    assert config.DAY_REWARD_PAYOUT(1, True) > config.board_bonus_max(1)
    assert config.board_bonus_max(last) > 2 * config.DAY_REWARD_PAYOUT(last, True)
    # The tutorial pays the flat rate (#15).
    assert all(config.DAY_REWARD_PAYOUT(d, True) == config.HACKDOLLAR_PER_CORRECT_ADMIT
               for d in range(1, config.TUTORIAL_LAST_DAY + 1))


# ─── Health ─────────────────────────────────────────────────────────────────


def test_mistakes_concentrate_on_the_subtle_archetypes():
    """The model the balance numbers rest on (Nick, 2026-09-25): the Obvious
    Admit and the Professional are near-certain reads."""
    for p in sb.PROFILES:
        easy = max(p.error(a) for a in ("obvious_admit", "the_professional"))
        assert easy < p.error("sneaky_bugger") / 5


def test_both_alignment_paths_are_finishable(campaign):
    """#70 AC plays the campaign on both alignments. Admitting the Dark Web is
    the scored-correct verdict, so a skilled by-the-book player must be able to
    reach day 20 — this is what the old −8 Dark Web weight broke."""
    for dw in ("admit", "deny"):
        for base in (sb.PERFECT, SHARP, SOLID):
            p = sb.Profile(base.name, base.base_error, base.board, dw)
            health = sb.expected_economy(campaign, p)[-1]["health"]
            assert health > config.SITE_HEALTH_LOSS_THRESHOLD, (dw, p.name, health)


def test_endless_rewards_skill_without_guaranteed_failure(endless_run):
    """A sharp player's site holds at the plateau; a sloppy one's collapses."""
    sharp = sb.expected_economy(endless_run, SHARP)
    shaky = sb.expected_economy(endless_run, SHAKY)
    assert sharp[-1]["health"] >= config.SITE_HEALTH_REWARD_THRESHOLD
    assert shaky[-1]["health"] < config.SITE_HEALTH_LOSS_THRESHOLD
