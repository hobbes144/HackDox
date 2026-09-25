"""Balance guards (#70 campaign pass, #7 Endless) — the properties the
2026-09-25 balance pass tuned for, asserted through the same simulator
(`sim_balance.py`, repo root) so a later config retune that breaks one fails
here instead of in a playtest.

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


@pytest.fixture(scope="module")
def campaign():
    days = [(f"D{n}", load_day(n)) for n in range(1, config.CAMPAIGN_LAST_DAY + 1)]
    return sb.walk(days, SEEDS, config.STARTING_COMPUTE)


@pytest.fixture(scope="module")
def endless_run():
    days = [(f"S{s}", load_day(config.endless_day_number(s))) for s in range(1, 41)]
    return sb.walk(days, SEEDS, config.STARTING_COMPUTE)


def test_correct_play_is_always_affordable(campaign, endless_run):
    """#70 AC: no day makes correct play impossible on ⏱ — the cheapest
    decisive evidence for every deny fits the day's budget, worst seed."""
    for d in [*campaign, *endless_run]:
        assert d.need_max <= d.budget, f"{d.label}: need {d.need_max} > budget {d.budget}"


def test_nobody_can_buy_the_whole_catalog_by_day_20(campaign, endless_run):
    """Nick (2026-09-25): buying every upgrade by day 20 must be impossible, in
    both modes — even for a perfect player who spends on nothing else."""
    cat = sb.catalog_total()
    for stats, label in ((campaign, "campaign"), (endless_run, "endless")):
        for p in (sb.PERFECT, sb.Profile("perfect-resist", 1.0, 1.0, "deny")):
            bank = sb.expected_economy(stats, p)[19]["bank"]
            assert bank < 0.9 * cat, f"{label}/{p.name}: {bank:.0f} of {cat}"
    # ...while a solid player can still afford a meaningful chunk of it.
    solid = sb.expected_economy(campaign, sb.PROFILES[1])[19]["bank"]
    assert solid > 0.35 * cat


def test_both_alignment_paths_are_finishable(campaign):
    """#70 AC plays the campaign on both alignments. Admitting the Dark Web is
    the scored-correct verdict, so a skilled by-the-book player must be able to
    reach day 20 — this is what the old −8 Dark Web weight broke."""
    for dw in ("admit", "deny"):
        for base in (sb.PERFECT, sb.PROFILES[0], sb.PROFILES[1]):
            p = sb.Profile(base.name, base.accuracy, base.board, dw)
            health = sb.expected_economy(campaign, p)[-1]["health"]
            assert health > config.SITE_HEALTH_LOSS_THRESHOLD, (dw, p.name, health)


def test_endless_rewards_skill_without_guaranteed_failure(endless_run):
    """A sharp player's site holds at the plateau; a sloppy one's collapses."""
    sharp = sb.expected_economy(endless_run, sb.PROFILES[0])
    shaky = sb.expected_economy(endless_run, sb.PROFILES[2])
    assert sharp[-1]["health"] >= config.SITE_HEALTH_REWARD_THRESHOLD
    assert shaky[-1]["health"] < config.SITE_HEALTH_LOSS_THRESHOLD
