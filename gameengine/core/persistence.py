"""Save/load GameState as JSON. One slot per game mode (#7): the campaign's
`slot_0.json` and Endless's `endless_0.json` never touch each other."""

from __future__ import annotations

import json

from .. import config
from .models import GameMode, GameState, ShiftRecord

# Bumped when the payload gains fields a newer loader relies on. v1 = pre-#7
# (no "version" key at all), v2 = mode / Endless run fields.
SAVE_VERSION = 2


def save(state: GameState) -> None:
    """Atomic write — tmp file, then rename — into the state's own mode slot."""
    payload = {
        "version":            SAVE_VERSION,
        "mode":               state.mode,
        "seed":               state.seed,
        "current_day":        state.current_day,
        "compute_hours":      state.compute_hours,
        "compute_capacity":   state.compute_capacity,
        "alignment":          state.alignment,
        "site_health":        state.site_health,
        "hackdollars":        state.hackdollars,
        "hackdox_credits":    state.hackdox_credits,
        "upgrades":           sorted(state.upgrades),
        "unlocked_tools":     sorted(state.unlocked_tools),
        "current_slot_index": state.current_slot_index,
        # Endless run fields (#7). Harmless empties on a campaign save.
        "shift_history": [
            {"shift": r.shift, "correct": r.correct, "judged": r.judged,
             "health_delta": r.health_delta, "hd_earned": r.hd_earned}
            for r in state.shift_history
        ],
        "lifetime_correct":     state.lifetime_correct,
        "lifetime_judged":      state.lifetime_judged,
        "maintenance_upgrades": sorted(state.maintenance_upgrades),
        "shop_purchases":       dict(state.shop_purchases),
        # DayResult / CandidateResult round-trip deferred to v1.1 —
        # saves happen at EOD only so mid-day resume isn't needed yet.
    }
    path = config.save_file_for(state.mode)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def exists(mode: str = GameMode.CAMPAIGN.value) -> bool:
    return config.save_file_for(mode).exists()


def load(mode: str = GameMode.CAMPAIGN.value) -> GameState | None:
    path = config.save_file_for(mode)
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    state = GameState(seed=raw["seed"])
    # A save with no "mode" predates Endless, and Endless has never written
    # to the campaign slot — so it is a campaign save.
    state.mode = raw.get("mode", GameMode.CAMPAIGN.value)
    state.current_day    = raw.get("current_day", 1)
    state.compute_hours  = raw.get("compute_hours",
                                   raw.get("currency", config.STARTING_COMPUTE))
    state.alignment        = raw.get("alignment", 0)
    state.compute_capacity = raw.get("compute_capacity", config.STARTING_COMPUTE)
    state.site_health      = raw.get("site_health", config.SITE_HEALTH_START)
    state.hackdollars      = raw.get("hackdollars", config.STARTING_HACKDOLLARS)
    state.hackdox_credits  = raw.get("hackdox_credits", config.STARTING_HACKDOX_CREDITS)
    state.upgrades         = set(raw.get("upgrades", []))
    # Progressive unlock (#31). A pre-#31 save has no "unlocked_tools" key;
    # backfill it from the schedule for the save's current day so a
    # mid-campaign player keeps the tools they've already earned instead of
    # loading in fully locked. (An Endless day number sits above every unlock
    # day, so the same backfill yields the full kit there.)
    state.unlocked_tools = (set(raw["unlocked_tools"]) if "unlocked_tools" in raw
                            else config.tools_unlocked_by(state.current_day))
    state.current_slot_index = raw.get("current_slot_index", 0)
    state.shift_history = [
        ShiftRecord(shift=int(r["shift"]), correct=int(r["correct"]),
                    judged=int(r["judged"]),
                    health_delta=float(r.get("health_delta", 0.0)),
                    hd_earned=int(r.get("hd_earned", 0)))
        for r in raw.get("shift_history", [])
    ]
    state.lifetime_correct     = raw.get("lifetime_correct", 0)
    state.lifetime_judged      = raw.get("lifetime_judged", 0)
    state.maintenance_upgrades = set(raw.get("maintenance_upgrades", []))
    state.shop_purchases       = dict(raw.get("shop_purchases", {}))
    return state


def continuable(mode: str) -> GameState | None:
    """The slot's state if the run in it can actually be continued, else None.

    The main menu only offers Continue for a save that leads somewhere
    (Nick, 2026-09-25). A slot can exist and still be a dead end:
      • unreadable or damaged,
      • Site Health already under the loss line (the run ended, or was saved
        on the between-day screen after it was lost),
      • an Endless run already under the rolling-accuracy line,
      • a campaign already past its last day.
    New runs clear their slot when they end (`clear`), so the last three are
    mostly saves from before that existed — but the check is what the menu
    trusts, not the file's existence.
    """
    try:
        state = load(mode)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if state is None or state.mode != mode:
        return None
    if state.site_health < config.SITE_HEALTH_LOSS_THRESHOLD:
        return None
    if state.is_endless:
        from . import endless   # local: endless imports persistence's siblings
        if endless.accuracy_below_loss(state):
            return None
    elif state.current_day > config.CAMPAIGN_LAST_DAY:
        return None
    return state


def clear(mode: str) -> None:
    """Remove a mode's save — called when its run ends (game over, campaign
    complete), so the menu stops offering to continue it."""
    try:
        config.save_file_for(mode).unlink()
    except FileNotFoundError:
        pass


def describe(mode: str) -> str | None:
    """One-line summary of a continuable slot for the main menu
    ("Day 7 · 180 HD$"), or None if there is nothing to continue. Never raises —
    the menu must not crash on a damaged save."""
    state = continuable(mode)
    if state is None:
        return None
    return f"{config.day_label(state.current_day)} · {state.hackdollars} HD$"
