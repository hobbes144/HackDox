"""Balance simulator for #70 (campaign) and #7 (Endless).

Runs the REAL generator, rulebook, tool costs and payout curves — no copies of
the formulas — across many seeds, and answers three questions per day/shift:

  1. Is correct play possible on ⏱?  `need` is the cheapest spend that reveals
     decisive evidence for every candidate who must be denied (evidence behind
     a tool you can't afford can't be acted on). Admits cost nothing in this
     bound — you can admit a clean candidate off the dossier. If the day's
     budget is below `need`, correct play is mathematically impossible.
     `full` is the comfortable spend: every unlocked tool's base run on every
     candidate, a filter wherever a deny's evidence needs one, and the stamps
     to resolve every stego image. budget/full is how much of a "check
     everything" shift the budget buys — the scarcity dial.

  2. What does the economy pay?  Expected HD$ per day for three player
     profiles (accuracy, evidence-board quality), against the price of the
     whole upgrade catalog. Nick (2026-09-25): buying every upgrade by day 20
     must be impossible, in both modes.

  3. Does Site Health hold?  Expected health path per profile, plus a Monte
     Carlo of how often each profile loses (health, or Endless's rolling
     accuracy).

Usage:
    python sim_balance.py                 # campaign + endless, markdown report
    python sim_balance.py --seeds 40      # more seeds (slower, smoother)
"""

from __future__ import annotations

import argparse
import math
import random
import statistics
from dataclasses import dataclass

from gameengine import config
from gameengine.core import candidate_gen, tools_bridge
from gameengine.core.content_loader import load_day
from gameengine.core.models import Day, DiscrepancyKind, GameState, ToolName, Verdict

TOOLS = ("ghostscan", "hashcrack", "logwatch", "stegotool")


@dataclass(frozen=True)
class Profile:
    name: str
    accuracy: float       # chance each verdict is right
    board: float          # fraction of the evidence-board bonus earned on a correct verdict
    # Campaign only: what the player does with a Dark Web candidate. "admit"
    # is by-the-book (the scored-correct verdict, and the Dark Web alignment
    # path); "deny" resists (scored wrong, no pay, but the site is spared —
    # the White Hat path). Endless has no Dark Web.
    dark_web: str = "admit"


PROFILES = (
    Profile("sharp", 0.95, 0.85),
    Profile("solid", 0.85, 0.60),
    Profile("shaky", 0.74, 0.40),
)
PERFECT = Profile("perfect", 1.0, 1.0)


# ─── ⏱: what does correct play cost? ────────────────────────────────────────


def _stamps_to_resolve(img) -> int:
    """Stamps to reveal STEGO_STAMP_RESOLVE_COVERAGE of the zone with perfect
    aim (a floor — real players overlap). 1.3× for honest aim."""
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
    # need: cheapest decisive evidence for a deny
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
    # full: base-run everything unlocked, filters/stamps where evidence lives
    unlocked = config.tools_unlocked_by(day.number)
    full = sum(tools_bridge.tool_cost(state, t) for t in ("ghostscan", "hashcrack", "logwatch")
               if t in unlocked)
    tools_hit = {candidate_gen._SEVERITY_REVEAL[k][0].value for k in kinds}
    for t in ("ghostscan", "logwatch"):
        if t in tools_hit and deny:
            full += config.FILTER_COSTS[t]
    if "stegotool" in unlocked:
        img = tools_bridge.build_stego_image(cand, day.number)
        # a thorough player samples every image; a clean one needs ~2 stamps to trust
        full += max(2, _stamps_to_resolve(img)) * config.STEGO_STAMP_COST
    return need, full


# ─── The walk ───────────────────────────────────────────────────────────────


@dataclass
class DayStats:
    label: str
    number: int
    count: int
    budget: int
    need: float          # mean over seeds
    need_max: int        # worst seed
    full: float
    admit_w: list        # per-candidate (is_admit, health weight) for a representative mix
    payout_admit: int
    payout_deny: int
    n_admit: float
    n_deny: float


def walk(days: list[tuple[str, Day]], seeds: list[int], capacity: int) -> list[DayStats]:
    out = []
    for label, day in days:
        state = GameState(seed=0, current_day=day.number)
        state.compute_capacity = capacity
        needs, fulls, mix = [], [], []
        n_admit = n_deny = 0
        for seed in seeds:
            cands = [candidate_gen.generate(seed, day, s) for s in range(day.candidate_count)]
            need = full = 0
            for c in cands:
                a, b = candidate_costs(c, day, state)
                need += a
                full += b
                admit = c.truth.correct_verdict == Verdict.ADMIT
                n_admit += admit
                n_deny += not admit
                mix.append((admit, config.ARCHETYPE_HEALTH_WEIGHTS.get(c.archetype.value, 0.0),
                            c.archetype.value == "dark_web"))
            needs.append(need)
            fulls.append(full)
        out.append(DayStats(
            label=label, number=day.number, count=day.candidate_count,
            budget=config.daily_compute_budget(day.number, capacity),
            need=statistics.mean(needs), need_max=max(needs), full=statistics.mean(fulls),
            admit_w=mix,
            payout_admit=config.DAY_REWARD_PAYOUT(day.number, True),
            payout_deny=config.DAY_REWARD_PAYOUT(day.number, False),
            n_admit=n_admit / len(seeds), n_deny=n_deny / len(seeds)))
    return out


def expected_economy(stats: list[DayStats], p: Profile) -> list[dict]:
    """Expected per-day HD$ and health for a profile (no spending)."""
    health, bank, rows = config.SITE_HEALTH_START, 0.0, []
    for d in stats:
        per = len(d.admit_w) / max(1, d.count)       # seeds folded into the mix
        dh = hd = 0.0
        for admit, w, dw in d.admit_w:
            if dw:
                # A deliberate policy, not a skill roll.
                if p.dark_web == "admit":
                    dh += w
                    hd += d.payout_admit + config.BOARD_ACCURACY_MAX_BONUS
                continue
            dh += p.accuracy * w if admit else (1 - p.accuracy) * w
            hd += p.accuracy * ((d.payout_admit if admit else d.payout_deny)
                                + p.board * config.BOARD_ACCURACY_MAX_BONUS)
        dh /= per
        hd /= per
        health = max(0.0, min(100.0, health + dh))
        bonus = (round(config.HACKDOLLAR_SITE_HEALTH_BONUS * health / 100)
                 if health >= config.SITE_HEALTH_REWARD_THRESHOLD else 0)
        bank += hd + bonus
        rows.append({"label": d.label, "hd": hd + bonus, "bank": bank, "health": health})
    return rows


def loss_rate(stats: list[DayStats], p: Profile, trials: int, endless: bool,
              rng: random.Random) -> tuple[float, float]:
    """Monte Carlo: (share of runs lost, mean days survived)."""
    lost, survived = 0, []
    for _ in range(trials):
        health, hist = config.SITE_HEALTH_START, []
        day_i = 0
        for day_i, d in enumerate(stats, start=1):
            # sample one seed's worth of candidates from the pooled mix
            sample = rng.sample(d.admit_w, d.count)
            correct = 0
            for admit, w, dw in sample:
                if dw:
                    if p.dark_web == "admit":
                        health += w
                        correct += 1
                    continue
                ok = rng.random() < p.accuracy
                correct += ok
                if (admit and ok) or (not admit and not ok):
                    health += w
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


def report(seeds: int = 20, endless_shifts: int = 40, trials: int = 400) -> str:
    rng = random.Random(7)
    sd = list(range(1, seeds + 1))
    lines: list[str] = []
    cat = catalog_total()

    def section(title, days, endless):
        st = walk(days, sd, config.STARTING_COMPUTE)
        lines.append(f"## {title}\n")
        lines.append("| day | n | budget ⏱ | need ⏱ (mean/worst) | full ⏱ | budget/full | admit HD$ | deny HD$ |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for d in st:
            flag = " ⚠" if d.need_max > d.budget else ""
            lines.append(f"| {d.label} | {d.count} | {d.budget} | {d.need:.0f} / {d.need_max}{flag} | "
                         f"{d.full:.0f} | {(f'{d.budget / d.full:.2f}' if d.full else '—')} | "
                         f"{d.payout_admit} | {d.payout_deny} |")
        lines.append("")
        lines.append(f"Upgrade catalog total: **{cat} HD$** "
                     f"(+ credits {config.SHOP_PRICE_CREDIT} each, capacity {config.SHOP_PRICE_CAPACITY}+).\n")
        lines.append("| profile | HD$ by day 10 | by day 20 | share of catalog by 20 | health @20 | loss rate | mean days survived |")
        lines.append("|---|---|---|---|---|---|---|")
        profiles = [PERFECT, *PROFILES]
        if not endless:
            profiles += [Profile(f"{q.name}, resists DW", q.accuracy, q.board, "deny")
                         for q in (PERFECT, *PROFILES)]
        for p in profiles:
            eco = expected_economy(st, p)
            at = lambda n: eco[min(n, len(eco)) - 1]["bank"]  # noqa: E731
            lr, surv = loss_rate(st, p, trials, endless, rng)
            lines.append(f"| {p.name} ({p.accuracy:.0%}, board {p.board:.0%}) | {at(10):.0f} | {at(20):.0f} | "
                         f"{at(20) / cat:.0%} | {eco[min(20, len(eco)) - 1]['health']:.0f}% | "
                         f"{lr:.0%} | {surv:.1f} |")
        lines.append("")
        return st

    section("Campaign (days 1–20)",
            [(f"D{n}", load_day(n)) for n in range(1, config.CAMPAIGN_LAST_DAY + 1)], False)
    section(f"Endless (shifts 1–{endless_shifts})",
            [(f"S{s}", load_day(config.endless_day_number(s)))
             for s in range(1, endless_shifts + 1)], True)
    return "\n".join(lines)


def apply_overrides(pairs: list[str]) -> None:
    """--set NAME=VALUE (python literal) — try a tuning without editing config."""
    import ast
    for pair in pairs:
        name, value = pair.split("=", 1)
        setattr(config, name, ast.literal_eval(value))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--price-mult", type=float, default=1.0)
    ap.add_argument("--set", action="append", default=[],
                    help="config override NAME=VALUE, repeatable")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--shifts", type=int, default=40)
    ap.add_argument("--trials", type=int, default=400)
    a = ap.parse_args()
    apply_overrides(a.set)
    PRICE_MULT = a.price_mult
    print(report(a.seeds, a.shifts, a.trials))
