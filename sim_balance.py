"""Balance simulator for #70 (campaign) and #7 (Endless).

Runs the REAL generator, rulebook, tool costs and payout curves — no copies of
the formulas — across many seeds, and answers three questions per day/shift:

  1. How tight is ⏱?
       need  — the cheapest spend that reveals decisive evidence for every
               candidate who must be denied. Below this, correct play is
               mathematically impossible (#70 AC).
       full  — a thorough player: every unlocked tool's base run on every
               candidate, the filter wherever a tool actually has something to
               show, and the stamps to resolve every image (2 to clear a clean
               one).
       cover — (budget − need) ÷ (full − need): how much of the thoroughness
               above the bare minimum the day's budget pays for. ≥ 1 means
               "check everything on everyone"; near 0 means every hour counts.
     Nick (2026-09-25): liberal early, restrictive late.

  2. What does the economy pay?  Expected HD$ per profile — verdict pay plus
     the evidence-board bonus, which depends on how well the player MARKS
     violations, separately from whether the verdict was right — against the
     price of the upgrade catalog. Nick: buying everything by day 20 must be
     impossible; and a player who gets verdicts right but doesn't record
     violations should run short of money later on.

  3. Does Site Health hold?  Expected health path per profile plus a Monte
     Carlo of losses (health, or Endless's rolling accuracy).

Mistakes are NOT spread evenly (Nick, 2026-09-25): the Obvious Admit and the
Professional are near-certain reads; the subtle archetypes are where players
trip. See ARCHETYPE_ERROR_WEIGHT.

Usage:
    python sim_balance.py                      # campaign + endless report
    python sim_balance.py --seeds 16 --trials 500
    python sim_balance.py --set NAME=VALUE     # try a tuning without editing config
"""

from __future__ import annotations

import argparse
import ast
import math
import random
import statistics
from dataclasses import dataclass, field

from gameengine import config
from gameengine.core import candidate_gen, tools_bridge
from gameengine.core.content_loader import load_day
from gameengine.core.models import Day, DiscrepancyKind, GameState, ToolName, Verdict

# ─── Player model ───────────────────────────────────────────────────────────

# How much more (or less) likely a mistake is on each archetype than the
# profile's base error rate. A clean, friendly Obvious Admit and an elite,
# Ghostscan-confirmed Professional are near-certain reads; the Incompatible's
# disposable email is on the dossier; the Bad Actor is loud. The Day-to-Day's
# minor noise draws false denies, the Clumsy Cutie's friendliness draws false
# admits, and the Sneaky Bugger is built to be missed.
ARCHETYPE_ERROR_WEIGHT: dict[str, float] = {
    "obvious_admit":    0.15,
    "the_professional": 0.15,
    "the_incompatible": 0.5,
    "bad_actor":        0.8,
    "day_to_day":       1.6,
    "clumsy_cutie":     1.6,
    "sneaky_bugger":    2.4,
    "white_hat":        2.0,
    "dark_web":         0.0,   # a deliberate policy, never a slip — see Profile.dark_web
}


@dataclass(frozen=True)
class Profile:
    name: str
    base_error: float     # scaled per archetype by ARCHETYPE_ERROR_WEIGHT
    board: float          # share of a violator's board bonus earned (marking quality)
    # Campaign only: "admit" = by the book (the scored-correct verdict; the
    # Dark Web alignment path), "deny" = resist (scored wrong, unpaid, but the
    # site is spared — the White Hat path).
    dark_web: str = "admit"

    def error(self, arch: str) -> float:
        return min(0.9, self.base_error * ARCHETYPE_ERROR_WEIGHT.get(arch, 1.0))


PERFECT = Profile("perfect", 0.0, 1.0)
PROFILES = (
    Profile("sharp", 0.04, 0.85),
    Profile("solid", 0.09, 0.60),
    Profile("shaky", 0.16, 0.40),
    # Nick's case: right verdicts, but violations barely recorded.
    Profile("sharp, sloppy board", 0.04, 0.15),
)


# ─── ⏱: what does a day cost? ───────────────────────────────────────────────


def _stamps_to_resolve(img) -> int:
    """Stamps to reveal STEGO_STAMP_RESOLVE_COVERAGE of the zone, with 1.3×
    for honest (not perfect) aim."""
    if img.zone is None:
        return 0
    _x, _y, w, h = img.zone
    area = w * h * config.STEGO_STAMP_RESOLVE_COVERAGE
    return max(1, math.ceil(1.3 * area / (config.STEGO_STAMP_W * config.STEGO_STAMP_H)))


def _kind_cost(kind: DiscrepancyKind, cand, state, day: Day, with_filter: bool) -> int:
    tool, _sev = candidate_gen._SEVERITY_REVEAL[kind]
    if tool == ToolName.DOSSIER:
        return 0
    t = tool.value
    if t == "stegotool":
        stamps = _stamps_to_resolve(tools_bridge.build_stego_image(cand, day.number))
        return stamps * config.STEGO_STAMP_COST + (
            config.STEGO_FILTER_COST if with_filter else 0)
    cost = tools_bridge.tool_cost(state, t)
    if with_filter and t in ("ghostscan", "logwatch"):
        cost += config.FILTER_COSTS[t]
    return cost


def _disqualifying_kinds(day: Day) -> set[DiscrepancyKind]:
    out = set()
    for r in day.rules:
        if r.severity == "disqualifying" and r.predicate.startswith("has_discrepancy:"):
            try:
                out.add(DiscrepancyKind(r.predicate.split(":", 1)[1]))
            except ValueError:
                pass
    return out


def candidate_costs(cand, day: Day, state) -> tuple[int, int]:
    """(need, full) ⏱ for one candidate."""
    kinds = [d.kind for d in cand.truth.discrepancies]
    deny = cand.truth.correct_verdict == Verdict.DENY
    need = 0
    if deny and kinds:
        dq = [k for k in kinds if k in _disqualifying_kinds(day)]
        if dq:
            need = min(_kind_cost(k, cand, state, day, with_filter=False) for k in dq)
        else:
            # Only advisory kinds: the case is "multiple discrepancies" — see
            # two of them. One tool run reveals every kind that tool owns, so
            # buy tools cheapest-first until two kinds are covered.
            by_tool: dict[str, list] = {}
            for k in set(kinds):
                by_tool.setdefault(candidate_gen._SEVERITY_REVEAL[k][0].value, []).append(k)
            priced = sorted((min(_kind_cost(k, cand, state, day, False) for k in ks), len(ks))
                            for ks in by_tool.values())
            seen = 0
            for cost, n in priced:
                if seen >= 2:
                    break
                need += cost
                seen += n
    unlocked = config.tools_unlocked_by(day.number)
    tools_hit = {candidate_gen._SEVERITY_REVEAL[k][0].value for k in kinds}
    full = 0
    for t in ("ghostscan", "hashcrack", "logwatch"):
        if t in unlocked:
            full += tools_bridge.tool_cost(state, t)
            if t in tools_hit and t in config.FILTER_COSTS and t != "hashcrack":
                full += config.FILTER_COSTS[t]
    if "stegotool" in unlocked:
        img = tools_bridge.build_stego_image(cand, day.number)
        full += max(2, _stamps_to_resolve(img)) * config.STEGO_STAMP_COST
        if "stegotool" in tools_hit:
            full += config.STEGO_FILTER_COST
    return need, full


# ─── The walk ───────────────────────────────────────────────────────────────


@dataclass
class Cand:
    arch: str
    admit: bool
    health_w: float
    dark_web: bool
    violator: bool


@dataclass
class DayStats:
    label: str
    number: int
    count: int
    budget: int
    need: float
    need_max: int
    full: float
    cands: list = field(default_factory=list)   # pooled over seeds
    n_seeds: int = 1

    @property
    def cover(self) -> float:
        span = self.full - self.need
        return (self.budget - self.need) / span if span > 0 else float("inf")


def walk(days: list[tuple[str, Day]], seeds: list[int], capacity: int) -> list[DayStats]:
    out = []
    for label, day in days:
        state = GameState(seed=0, current_day=day.number)
        state.compute_capacity = capacity
        needs, fulls, pool = [], [], []
        for seed in seeds:
            need = full = 0
            for s in range(day.candidate_count):
                c = candidate_gen.generate(seed, day, s)
                a, b = candidate_costs(c, day, state)
                need += a
                full += b
                pool.append(Cand(
                    arch=c.archetype.value,
                    admit=c.truth.correct_verdict == Verdict.ADMIT,
                    health_w=config.ARCHETYPE_HEALTH_WEIGHTS.get(c.archetype.value, 0.0),
                    dark_web=c.archetype.value == "dark_web",
                    violator=bool(c.truth.discrepancies)))
            needs.append(need)
            fulls.append(full)
        out.append(DayStats(
            label=label, number=day.number, count=day.candidate_count,
            budget=config.daily_compute_budget(day.number, capacity),
            need=statistics.mean(needs), need_max=max(needs), full=statistics.mean(fulls),
            cands=pool, n_seeds=len(seeds)))
    return out


def _cand_value(d: DayStats, c: Cand, p: Profile) -> tuple[float, float, float]:
    """Expected (HD$, Site Health delta, P(correct)) for one candidate."""
    board_max = config.board_bonus_max(d.number)
    if c.dark_web:
        if p.dark_web == "admit":   # by the book: correct, clean board, site pays
            return (config.DAY_REWARD_PAYOUT(d.number, True)
                    + round(board_max * config.BOARD_CLEAN_FRACTION), c.health_w, 1.0)
        return 0.0, 0.0, 0.0
    ok = 1.0 - p.error(c.arch)
    board = (board_max * p.board if c.violator
             else board_max * config.BOARD_CLEAN_FRACTION)
    hd = ok * (config.DAY_REWARD_PAYOUT(d.number, c.admit) + board)
    dh = ok * c.health_w if c.admit else (1 - ok) * c.health_w
    return hd, dh, ok


def expected_economy(stats: list[DayStats], p: Profile) -> list[dict]:
    """Expected per-day HD$, health and accuracy for a profile (no spending)."""
    health, bank, rows = config.SITE_HEALTH_START, 0.0, []
    for d in stats:
        hd = dh = okn = 0.0
        for c in d.cands:
            a, b, ok = _cand_value(d, c, p)
            hd, dh, okn = hd + a, dh + b, okn + ok
        hd, dh = hd / d.n_seeds, dh / d.n_seeds
        health = max(0.0, min(100.0, health + dh))
        bonus = (round(config.HACKDOLLAR_SITE_HEALTH_BONUS * health / 100)
                 if health >= config.SITE_HEALTH_REWARD_THRESHOLD else 0)
        bank += hd + bonus
        rows.append({"label": d.label, "hd": hd + bonus, "bank": bank,
                     "health": health, "acc": okn / len(d.cands)})
    return rows


def loss_rate(stats: list[DayStats], p: Profile, trials: int, endless: bool,
              rng: random.Random) -> tuple[float, float]:
    """Monte Carlo: (share of runs lost, mean days survived)."""
    lost, survived = 0, []
    for _ in range(trials):
        health, hist, day_i = config.SITE_HEALTH_START, [], 0
        for day_i, d in enumerate(stats, start=1):
            sample = rng.sample(d.cands, d.count)
            correct = 0
            for c in sample:
                if c.dark_web:
                    if p.dark_web == "admit":
                        health += c.health_w
                        correct += 1
                    continue
                ok = rng.random() >= p.error(c.arch)
                correct += ok
                if (c.admit and ok) or (not c.admit and not ok):
                    health += c.health_w
            health = max(0.0, min(100.0, health))
            hist.append((correct, d.count))
            dead = health < config.SITE_HEALTH_LOSS_THRESHOLD
            if endless and len(hist) >= config.ENDLESS_ACCURACY_WINDOW:
                w5 = hist[-config.ENDLESS_ACCURACY_WINDOW:]
                dead = dead or (sum(c for c, _ in w5) / sum(n for _, n in w5)
                                < config.ENDLESS_ACCURACY_THRESHOLD)
            if dead:
                lost += 1
                break
        survived.append(day_i)
    return lost / trials, statistics.mean(survived)


# ─── Report ─────────────────────────────────────────────────────────────────

PRICE_MULT = 1.0   # sweep aid: --price-mult scales the catalog total only


def catalog_total() -> int:
    return round(PRICE_MULT * sum(price for _u, _l, price, _d in config.UPGRADE_CATALOG))


def _mean_hd(eco: list[dict], lo: int, hi: int) -> float:
    rows = eco[lo - 1:hi]
    return statistics.mean(r["hd"] for r in rows) if rows else 0.0


def compute_table(st: list[DayStats]) -> list[str]:
    lines = ["| day | n | budget ⏱ | need ⏱ (mean/worst) | full ⏱ | budget/full | cover | admit HD$ | deny HD$ | board max |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for d in st:
        flag = " ⚠" if d.need_max > d.budget else ""
        lines.append(
            f"| {d.label} | {d.count} | {d.budget} | {d.need:.0f} / {d.need_max}{flag} | "
            f"{d.full:.0f} | {d.budget / d.full if d.full else float('inf'):.2f} | "
            f"{min(d.cover, 9.99):.2f} | {config.DAY_REWARD_PAYOUT(d.number, True)} | "
            f"{config.DAY_REWARD_PAYOUT(d.number, False)} | {config.board_bonus_max(d.number)} |")
    return lines


def available_catalog(endless: bool) -> int:
    """What a run can actually buy: Endless puts ENDLESS_MAINTENANCE_COUNT
    upgrades out of service, so on average that share of the catalog is gone,
    and charges ENDLESS_UPGRADE_PRICE_MULT for the rest."""
    cat = catalog_total()
    if not endless:
        return cat
    n = len(config.UPGRADE_CATALOG)
    return round(cat * config.ENDLESS_UPGRADE_PRICE_MULT
                 * (n - config.ENDLESS_MAINTENANCE_COUNT) / n)


def economy_table(st: list[DayStats], profiles, endless: bool, trials: int,
                  rng: random.Random) -> list[str]:
    cat = available_catalog(endless)
    last = len(st)
    late_lo = max(1, last - 5)
    lines = [f"Upgrade catalog{' (buyable — maintenance excluded)' if endless else ''}: "
             f"**{cat} HD$**. HD$/day columns are expected earnings "
             f"(verdicts + board + health bonus), before any spending.\n",
             f"| profile | accuracy | HD$/day 1–7 | HD$/day {late_lo}–{last} | bank @10 | bank @20 | "
             f"catalog @20 | health @end | loss | days survived |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for p in profiles:
        eco = expected_economy(st, p)
        at = lambda n: eco[min(n, len(eco)) - 1]["bank"]  # noqa: E731
        acc = statistics.mean(r["acc"] for r in eco)
        lr, surv = loss_rate(st, p, trials, endless, rng)
        lines.append(
            f"| {p.name}{' · resists DW' if p.dark_web == 'deny' else ''} | {acc:.0%} | "
            f"{_mean_hd(eco, 1, 7):.0f} | {_mean_hd(eco, late_lo, last):.0f} | {at(10):.0f} | "
            f"{at(20):.0f} | {at(20) / cat:.0%} | {eco[-1]['health']:.0f}% | {lr:.0%} | {surv:.1f} |")
    return lines


def report(seeds: int = 16, endless_shifts: int = 40, trials: int = 400) -> str:
    rng = random.Random(7)
    sd = list(range(1, seeds + 1))
    out: list[str] = []
    camp = walk([(f"D{n}", load_day(n)) for n in range(1, config.CAMPAIGN_LAST_DAY + 1)],
                sd, config.STARTING_COMPUTE)
    out += ["## Campaign (days 1–20)", "", *compute_table(camp), ""]
    profs = [PERFECT, *PROFILES]
    profs += [Profile(q.name, q.base_error, q.board, "deny") for q in (PERFECT, *PROFILES[:3])]
    out += economy_table(camp, profs, False, trials, rng) + [""]
    end = walk([(f"S{s}", load_day(config.endless_day_number(s)))
                for s in range(1, endless_shifts + 1)], sd, config.STARTING_COMPUTE)
    out += [f"## Endless (shifts 1–{endless_shifts})", "", *compute_table(end), ""]
    out += economy_table(end, [PERFECT, *PROFILES], True, trials, rng)
    return "\n".join(out)


def apply_overrides(pairs: list[str]) -> None:
    """--set NAME=VALUE (python literal) — try a tuning without editing config."""
    for pair in pairs:
        name, value = pair.split("=", 1)
        setattr(config, name, ast.literal_eval(value))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=16)
    ap.add_argument("--shifts", type=int, default=40)
    ap.add_argument("--trials", type=int, default=400)
    ap.add_argument("--price-mult", type=float, default=1.0)
    ap.add_argument("--set", action="append", default=[],
                    help="config override NAME=VALUE, repeatable")
    a = ap.parse_args()
    apply_overrides(a.set)
    PRICE_MULT = a.price_mult
    print(report(a.seeds, a.shifts, a.trials))
