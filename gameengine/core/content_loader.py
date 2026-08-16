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
    raises rather than silently degrading to "fixed" - the same fail-loud
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


def load_day(day_number: int) -> Day:
    path = config.DAYS_DIR / f"day_{day_number:02d}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    rules = tuple(_parse_rule(r) for r in raw["rules"])
    archetype_mix = {
        Archetype(key): count for key, count in raw["archetype_mix"].items()
    }
    # compute_target retired by issue #27 (⏱ is a spend-only daily budget);
    # legacy day files that still carry it are simply ignored.
    quotas = Quotas(
        min_correct_admits=raw["quotas"]["min_correct_admits"],
        max_false_admits=raw["quotas"]["max_false_admits"],
    )
    outro_keys = {
        Performance(k): v for k, v in raw["overseer_outro_keys"].items()
    }
    # Per-day candidate spec (#32) — all optional so pre-#32 files load as-is.
    allowed_violations = tuple(
        DiscrepancyKind(k) for k in raw.get("allowed_violations", [])
    )
    difficulty_band = raw.get("difficulty_band", "easy")
    # forced_includes JSON: {"<slot index>": "<archetype value>"}.
    forced_includes = {
        int(slot): Archetype(arch)
        for slot, arch in raw.get("forced_includes", {}).items()
    }
    return Day(
        number=raw["number"],
        title=raw["title"],
        rules=rules,
        candidate_count=raw["candidate_count"],
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
