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
    Performance,
    Quotas,
    Rule,
)


def load_day(day_number: int) -> Day:
    path = config.DAYS_DIR / f"day_{day_number:02d}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    rules = tuple(
        Rule(
            id=r["id"],
            text=r["text"],
            predicate=r["predicate"],
            severity=r.get("severity", "disqualifying"),
        )
        for r in raw["rules"]
    )
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
    return Day(
        number=raw["number"],
        title=raw["title"],
        rules=rules,
        candidate_count=raw["candidate_count"],
        archetype_mix=archetype_mix,
        quotas=quotas,
        overseer_intro_key=raw["overseer_intro_key"],
        overseer_outro_keys=outro_keys,
    )


def load_narratives() -> dict[str, str]:
    path = config.NARRATIVES_DIR / "overseer.json"
    return json.loads(path.read_text(encoding="utf-8"))
