"""Endless Mode's run rules (#7): starting a run, recording a shift, the
rolling-accuracy loss condition, the trend the Foreman reacts to, and the
personal-best record.

The day content itself is `content_loader.build_endless_day`; the difficulty
curve is `config.curve_day`; shop prices live in `core/shop.py`. This module
owns only what is Endless-specific about the *run*.

Everything here is a pure function of a GameState (plus the records file for
the personal best), so it is unit-tested without the TUI.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date
from typing import Literal

from .. import config
from .models import GameMode, GameState, ShiftRecord
from .candidate_gen import stable_hash

Trend = Literal["rising", "steady", "falling", "new"]


# ─── Starting a run ─────────────────────────────────────────────────────────


def new_run_seed() -> int:
    """A fresh seed per Endless run. The campaign plays a fixed seed by design
    (every player sees the same authored days); Endless is meant to differ run
    to run — candidates AND the maintenance roll."""
    return random.SystemRandom().getrandbits(32)


def roll_maintenance(seed: int) -> set[str]:
    """Upgrades under maintenance for this run (Nick, 2026-09-25): a random
    ENDLESS_MAINTENANCE_COUNT of the catalog, unbuyable until the run ends.
    Seeded from the run seed, so a reloaded run keeps the same roll."""
    ids = sorted(uid for uid, *_ in config.UPGRADE_CATALOG)
    rng = random.Random(stable_hash(seed, "endless_maintenance") & 0xFFFFFFFF)
    k = max(0, min(config.ENDLESS_MAINTENANCE_COUNT, len(ids)))
    return set(rng.sample(ids, k))


def new_endless_state(seed: int | None = None) -> GameState:
    """A fresh Endless run at shift 1 with every tool already unlocked."""
    seed = new_run_seed() if seed is None else seed
    day_no = config.endless_day_number(1)
    capacity = config.STARTING_COMPUTE
    return GameState(
        seed=seed,
        current_day=day_no,
        compute_hours=config.daily_compute_budget(day_no, capacity),
        compute_capacity=capacity,
        alignment=config.STARTING_ALIGNMENT,
        site_health=config.SITE_HEALTH_START,
        hackdollars=config.ENDLESS_STARTING_HACKDOLLARS,
        hackdox_credits=config.STARTING_HACKDOX_CREDITS,
        # No tutorial: the whole kit is live from the first shift.
        unlocked_tools=config.tools_unlocked_by(day_no),
        mode=GameMode.ENDLESS.value,
        maintenance_upgrades=roll_maintenance(seed),
    )


def current_shift(state: GameState) -> int:
    return config.endless_shift(state.current_day)


# ─── Recording a shift & the rolling window ─────────────────────────────────


def record_shift(state: GameState, health_delta: float = 0.0,
                 hd_earned: int = 0) -> ShiftRecord:
    """Fold the just-finished shift (state.pending_results) into the run's
    history. Called once per shift, at end of day, before the loss check.
    Idempotent per shift: recording the same shift twice replaces it."""
    results = state.pending_results
    rec = ShiftRecord(
        shift=current_shift(state),
        correct=sum(1 for r in results if r.correct),
        judged=len(results),
        health_delta=round(health_delta, 2),
        hd_earned=hd_earned,
    )
    if state.shift_history and state.shift_history[-1].shift == rec.shift:
        old = state.shift_history.pop()
        state.lifetime_correct -= old.correct
        state.lifetime_judged  -= old.judged
    state.shift_history.append(rec)
    state.lifetime_correct += rec.correct
    state.lifetime_judged  += rec.judged
    del state.shift_history[:-config.ENDLESS_HISTORY_KEEP]
    return rec


def _window_accuracy(records: list[ShiftRecord]) -> float | None:
    judged = sum(r.judged for r in records)
    if not records or judged == 0:
        return None
    return sum(r.correct for r in records) / judged


def rolling_accuracy(state: GameState,
                     window: int = config.ENDLESS_ACCURACY_WINDOW) -> float | None:
    """Accuracy over the last `window` shifts, weighted by verdicts (a 14-
    candidate shift counts for more than a 7-candidate one). None before any
    shift has been recorded."""
    return _window_accuracy(state.shift_history[-window:])


def lifetime_accuracy(state: GameState) -> float | None:
    if state.lifetime_judged == 0:
        return None
    return state.lifetime_correct / state.lifetime_judged


def accuracy_check_active(state: GameState) -> bool:
    """The rolling-accuracy loss only applies once a full window has been
    played (Nick: after 5 shifts)."""
    return len(state.shift_history) >= config.ENDLESS_ACCURACY_WINDOW


def accuracy_below_loss(state: GameState) -> bool:
    if not state.is_endless or not accuracy_check_active(state):
        return False
    acc = rolling_accuracy(state)
    return acc is not None and acc < config.ENDLESS_ACCURACY_THRESHOLD


def trend(state: GameState) -> Trend:
    """Which way the run is heading: this window vs. the window one shift
    earlier. "new" until there are two shifts to compare."""
    hist = state.shift_history
    if len(hist) < 2:
        return "new"
    w = config.ENDLESS_ACCURACY_WINDOW
    now  = _window_accuracy(hist[-w:])
    prev = _window_accuracy(hist[-w - 1:-1])
    if now is None or prev is None:
        return "steady"
    delta = now - prev
    if delta >= config.ENDLESS_TREND_DEADBAND:
        return "rising"
    if delta <= -config.ENDLESS_TREND_DEADBAND:
        return "falling"
    return "steady"


def in_danger(state: GameState) -> bool:
    """Rolling accuracy within 10 points of the line — the Foreman's cue to
    get concerned even if the trend reads steady."""
    acc = rolling_accuracy(state)
    return acc is not None and acc < config.ENDLESS_ACCURACY_THRESHOLD + 0.10


# ─── Personal best ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RunRecord:
    shifts: int            # shifts fully completed
    accuracy: float | None # lifetime accuracy for the run
    hackdollars: int       # HD$ on hand at the end
    when: str              # ISO date

    def beats(self, other: "RunRecord | None") -> bool:
        """More shifts wins; accuracy breaks ties."""
        if other is None:
            return True
        if self.shifts != other.shifts:
            return self.shifts > other.shifts
        return (self.accuracy or 0.0) > (other.accuracy or 0.0)

    def to_json(self) -> dict:
        return {"shifts": self.shifts, "accuracy": self.accuracy,
                "hackdollars": self.hackdollars, "when": self.when}

    @classmethod
    def from_json(cls, raw: dict) -> "RunRecord":
        return cls(shifts=int(raw.get("shifts", 0)),
                   accuracy=raw.get("accuracy"),
                   hackdollars=int(raw.get("hackdollars", 0)),
                   when=str(raw.get("when", "")))


def run_record(state: GameState) -> RunRecord:
    return RunRecord(
        shifts=_shifts_completed(state),
        accuracy=lifetime_accuracy(state),
        hackdollars=state.hackdollars,
        when=date.today().isoformat(),
    )


def _shifts_completed(state: GameState) -> int:
    # The history is trimmed, but its last entry still carries the shift number.
    return state.shift_history[-1].shift if state.shift_history else 0


def load_records() -> dict:
    path = config.ENDLESS_RECORDS_FILE
    if not path.exists():
        return {"best": None, "runs": 0}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"best": None, "runs": 0}
    return {"best": raw.get("best"), "runs": int(raw.get("runs", 0))}


def personal_best() -> RunRecord | None:
    best = load_records()["best"]
    return RunRecord.from_json(best) if best else None


def finish_run(state: GameState) -> tuple[RunRecord, RunRecord | None, bool]:
    """Close out an Endless run: update the records file and clear the run's
    save slot (a lost run can't be continued). Returns (this run, the previous
    best, whether this run is the new best)."""
    rec = run_record(state)
    records = load_records()
    prev = RunRecord.from_json(records["best"]) if records["best"] else None
    is_new_best = rec.beats(prev)
    out = {"best": rec.to_json() if is_new_best else records["best"],
           "runs": records["runs"] + 1}
    tmp = config.ENDLESS_RECORDS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=2), encoding="utf-8")
    tmp.replace(config.ENDLESS_RECORDS_FILE)
    try:
        config.ENDLESS_SAVE_FILE.unlink()
    except FileNotFoundError:
        pass
    return rec, prev, is_new_best
