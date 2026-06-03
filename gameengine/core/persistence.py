"""Save/load GameState as JSON. Single slot for v1."""

from __future__ import annotations

import json

from .. import config
from .models import GameState


def save(state: GameState) -> None:
    """Atomic write — tmp file, then rename."""
    payload = {
        "seed":               state.seed,
        "current_day":        state.current_day,
        "compute_hours":      state.compute_hours,
        "alignment":          state.alignment,
        "lives":              state.lives,
        "upgrades":           sorted(state.upgrades),
        "current_slot_index": state.current_slot_index,
        # DayResult / CandidateResult round-trip deferred to v1.1 —
        # saves happen at EOD only so mid-day resume isn't needed yet.
    }
    tmp = config.SAVE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(config.SAVE_FILE)


def load() -> GameState | None:
    if not config.SAVE_FILE.exists():
        return None
    raw = json.loads(config.SAVE_FILE.read_text(encoding="utf-8"))
    state = GameState(seed=raw["seed"])
    state.current_day    = raw.get("current_day", 1)
    state.compute_hours  = raw.get("compute_hours",
                                   raw.get("currency", config.STARTING_COMPUTE))
    state.alignment      = raw.get("alignment", 0)
    state.lives          = raw.get("lives", config.STARTING_LIVES)
    state.upgrades       = set(raw.get("upgrades", []))
    state.current_slot_index = raw.get("current_slot_index", 0)
    return state
