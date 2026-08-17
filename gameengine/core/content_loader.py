"""Load Day specs and narrative strings from `content/`.

Days are authored as JSON so they're diff-able and editable without a
Python edit cycle. The loader translates the JSON shape into a `Day`
dataclass.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import config
from .models import (
    Archetype,
    Day,
    DiscrepancyKind,
    Performance,
    Quotas,
    RULE_MUTABILITIES,
    Rule,
)


def _parse_rule(raw_rule: dict) -> Rule:
    """Build one Rule from its JSON object.

    `mutability` (issue #35) is optional and defaults to "fixed", so every day
    file authored before #35 loads byte-identically. An unrecognised value
    raises rather than silently degrading to "fixed" — the same fail-loud
    stance `rules_engine.resolve()` takes on predicate typos, and for the same
    reason: a typo that quietly means "this rule never mutates" is a content
    bug nobody would notice until the corruption arc failed to happen.
    """
    mutability = raw_rule.get("mutability", "fixed")
    if mutability not in RULE_MUTABILITIES:
        raise ValueError(
            f"Unknown rule mutability {mutability!r} in rule "
            f"{raw_rule.get('id')!r}; expected one of {sorted(RULE_MUTABILITIES)}"
        )
    return Rule(
        id=raw_rule["id"],
        text=raw_rule["text"],
        predicate=raw_rule["predicate"],
        severity=raw_rule.get("severity", "disqualifying"),
        mutability=mutability,
    )


def scale_archetype_mix(
    base_mix: dict[Archetype, int],
    target_total: int,
) -> dict[Archetype, int]:
    """Rescale an archetype mix to sum to exactly `target_total`.

    Largest-remainder apportionment: each archetype gets its proportional
    share floored, then the leftover slots go to whoever was rounded down
    hardest. Ties break on the archetype's enum value so the result is a pure
    function of its inputs — generation determinism (#17 AC) depends on this
    never depending on dict iteration order.

    Hitting `target_total` exactly is the hard requirement, not a nicety:
    `candidate_gen._pick_archetype_for_slot` walks the shuffled mix bag with
    `bag[pos % len(bag)]`, so a bag that doesn't match the shift length wraps
    and the realized mix stops equalling the declared mix.

    Where there is room (`target_total >= len(base_mix)`) every archetype keeps
    at least one slot, so scaling down never silently deletes an archetype the
    day was meant to contain. Where there is NOT room — a shift shorter than
    the number of archetypes — the smallest proportional shares are dropped
    rather than breaking the total.
    """
    if target_total <= 0 or not base_mix:
        return dict(base_mix)
    items = sorted(base_mix.items(), key=lambda kv: kv[0].value)
    base_total = sum(count for _, count in items)
    if base_total == 0:
        return dict(base_mix)

    exact = {a: target_total * c / base_total for a, c in items}

    if target_total < len(items):
        # Not enough slots to represent every archetype. Keep the largest
        # proportional shares; enum value breaks ties so this stays a pure
        # function of its inputs.
        keep = sorted(items, key=lambda kv: (-exact[kv[0]], kv[0].value))
        keep = [a for a, _ in keep[:target_total]]
        return {a: 1 for a in sorted(keep, key=lambda a: a.value)}

    out = {a: max(1, int(exact[a])) for a, _ in items}

    # Reconcile: hand out (or claw back) whatever the flooring left over.
    # Largest remainder first when adding, smallest when removing.
    while sum(out.values()) < target_total:
        a = max(items, key=lambda kv: (exact[kv[0]] - out[kv[0]], kv[0].value))[0]
        out[a] += 1
    while sum(out.values()) > target_total:
        # Only take from archetypes that can spare a slot (floor of 1) — with
        # target_total >= len(items) there is always at least one.
        spare = [kv for kv in items if out[kv[0]] > 1]
        a = min(spare, key=lambda kv: (exact[kv[0]] - out[kv[0]], kv[0].value))[0]
        out[a] -= 1
    return out


def synthesize_day(day_number: int) -> Day:
    """Build a Day procedurally when no day_NN.json exists (#17).

    Before this, `load_day` raised FileNotFoundError for anything past Day 1
    and the campaign simply ended after the first shift — which meant every
    day-scaled difficulty lever (#4's reward decay and cost inflation, #17's
    volume ramp, #36's day-over-day rule diff) was dead code that could never
    be observed in play.

    A synthesized day inherits Day 1's rules and archetype proportions, then
    applies the config curves for length, quota and difficulty band. It is a
    floor, not a substitute for authored content: an authored day_NN.json
    always wins, so #39/#40/#41 can replace these one day at a time without
    touching this function.
    """
    template = load_day(1)
    count = config.DAY_CANDIDATE_COUNT(day_number)
    band  = config.difficulty_band_for_day(day_number)
    # #4's detection-complexity lever: the band picks the archetype weighting,
    # so late days load up on the Sneaky Bugger while easy days lean on the
    # obvious cases the tutorial taught. Falls back to Day 1's own proportions
    # if a band ever has no table.
    weights = config.ARCHETYPE_MIX_BY_BAND.get(band)
    base_mix = (
        {Archetype(k): v for k, v in weights.items()} if weights
        else template.archetype_mix
    )
    return Day(
        number=day_number,
        title=f"Day {day_number}",
        rules=template.rules,
        candidate_count=count,
        archetype_mix=scale_archetype_mix(base_mix, count),
        quotas=Quotas(
            min_correct_admits=config.DAY_MIN_CORRECT_ADMITS(day_number, count),
            max_false_admits=template.quotas.max_false_admits,
        ),
        # These narrative keys are deliberately allowed not to exist. Every
        # consumer reads them through dict.get with a fallback, so a
        # synthesized day plays with generic Overseer copy rather than
        # crashing — and the moment #39/#40/#41 author real keys, they land.
        overseer_intro_key=f"day{day_number}_intro",
        overseer_outro_keys={
            p: f"day{day_number}_outro_{p.value}" for p in Performance
        },
        allowed_violations=(),   # no whitelist — only #31's evidence-tier gate
        difficulty_band=band,
        forced_includes={},
    )


def load_day(day_number: int) -> Day:
    path = config.DAYS_DIR / f"day_{day_number:02d}.json"
    if not path.exists():
        # No authored content for this day. Synthesize one inside the campaign
        # (#17); past the last day, fall through to the original
        # FileNotFoundError, which is what drives CampaignEndScreen.
        if 1 < day_number <= config.CAMPAIGN_LAST_DAY:
            return synthesize_day(day_number)
        raise FileNotFoundError(path)

    raw = json.loads(path.read_text(encoding="utf-8"))
    rules = tuple(_parse_rule(r) for r in raw["rules"])
    archetype_mix = {
        Archetype(key): count for key, count in raw["archetype_mix"].items()
    }
    # candidate_count is optional as of #17: a day file that omits it takes the
    # campaign volume curve. day_01.json still declares 6, so Day 1 is
    # unchanged.
    candidate_count = raw.get("candidate_count") or config.DAY_CANDIDATE_COUNT(
        raw["number"])
    # compute_target retired by issue #27 (⏱ is a spend-only daily budget);
    # legacy day files that still carry it are simply ignored.
    # min_correct_admits scales with shift length (#17) but never drops below
    # what the day file asked for.
    quotas = Quotas(
        min_correct_admits=config.DAY_MIN_CORRECT_ADMITS(
            raw["number"], candidate_count,
            raw["quotas"].get("min_correct_admits"),
        ),
        max_false_admits=raw["quotas"]["max_false_admits"],
    )
    outro_keys = {
        Performance(k): v for k, v in raw["overseer_outro_keys"].items()
    }
    # Per-day candidate spec (#32) — all optional so pre-#32 files load as-is.
    allowed_violations = tuple(
        DiscrepancyKind(k) for k in raw.get("allowed_violations", [])
    )
    difficulty_band = raw.get(
        "difficulty_band", config.difficulty_band_for_day(raw["number"]))
    # forced_includes JSON: {"<slot index>": "<archetype value>"}.
    forced_includes = {
        int(slot): Archetype(arch)
        for slot, arch in raw.get("forced_includes", {}).items()
    }
    return Day(
        number=raw["number"],
        title=raw["title"],
        rules=rules,
        candidate_count=candidate_count,
        archetype_mix=archetype_mix,
        quotas=quotas,
        overseer_intro_key=raw["overseer_intro_key"],
        overseer_outro_keys=outro_keys,
        allowed_violations=allowed_violations,
        difficulty_band=difficulty_band,
        forced_includes=forced_includes,
    )


def load_narratives() -> dict[str, str]:
    path = config.NARRATIVES_DIR / "overseer.json"
    return json.loads(path.read_text(encoding="utf-8"))
