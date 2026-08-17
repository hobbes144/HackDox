"""Scoring — the asymmetric reward/penalty matrix.

Computing Hours (⏱) are a FINITE DAILY BUDGET (issue #27): verdicts never
grant or cost ⏱ — the pool is only spent on tools and resets each shift.
Wrong verdicts hit Site Health and shift alignment instead (issue #20 —
Site Health replaced the lives system, issues #19/#24).

| Correct verdict | Player verdict | Site Health | HD$             | Alignment |
|-----------------|----------------|-------------|-----------------|-----------|
| ADMIT           | ADMIT          | +weight     | +admit$ +board$ |  +moral   |
| ADMIT           | DENY           |  0          |  0              |  -moral   |
| DENY            | DENY           |  0          | +deny$ +board$  |  -moral   |
| DENY            | ADMIT          | +weight (−) |  0              |  +moral   |

Every ADMIT records the admitted archetype's health weight
(config.ARCHETYPE_HEALTH_WEIGHTS) on the CandidateResult — beneficial
actors raise Site Health, threats lower it. Correct denials never touch
health: the threat never entered the site. Deltas are only RECORDED during
the day; they are applied to `state.site_health` in one batch at end of day
via `apply_end_of_day_health()`, so the loss condition can only trip at
shift end (design change to issue #20 — the effect lands on the between-day
page). Evidence board accuracy adds 0–BOARD_MAX_BONUS HackDollar$ on top
of any correct verdict's HD$ payout (issue #27 moved the bonus off ⏱).
HackDollar$ (issue #21) is the persistent between-day currency, earned on
correct verdicts.

Where `moral` is the candidate's GroundTruth.moral_modifier:
  moral = -1  (Dark Web): admitting them drifts the player Dark Web.
  moral = +1  (White Hat): admitting them drifts the player White Hat.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import config
from .models import (
    Candidate,
    CandidateResult,
    DiscrepancyKind,
    Verdict,
)


@dataclass(frozen=True)
class ScoreDelta:
    board_bonus: int = 0        # HD$ portion from evidence-board accuracy
    site_health: float = 0.0
    hackdollars: int = 0        # total HD$ (verdict payout + board bonus)
    alignment: int = 0
    correct: bool = False


def board_accuracy_bonus(
    player_flags: set[DiscrepancyKind],
    candidate: Candidate,
) -> int:
    """Score the player's evidence board against ground truth.

    Returns 0–BOARD_ACCURACY_MAX_BONUS HackDollar$ (issue #27: the bonus
    is paid in HD$ — verdicts never grant computing hours).
    Uses an F1-style metric: perfect match = full bonus, partial = scaled.
    False positives (flagging violations that aren't there) reduce the
    bonus; correctly flagging nothing on a clean candidate pays in full.
    """
    actual = {d.kind for d in candidate.truth.discrepancies}
    if not actual and not player_flags:
        # Clean candidate, player correctly flagged nothing.
        return config.BOARD_ACCURACY_MAX_BONUS

    true_pos  = len(player_flags & actual)
    false_pos = len(player_flags - actual)
    false_neg = len(actual - player_flags)
    denom = true_pos + false_pos + false_neg
    if denom == 0:
        return config.BOARD_ACCURACY_MAX_BONUS
    accuracy = true_pos / denom
    return round(config.BOARD_ACCURACY_MAX_BONUS * accuracy)


def score(
    candidate: Candidate,
    player_verdict: Verdict,
    player_flags: set[DiscrepancyKind],
    day_number: int = 1,
) -> ScoreDelta:
    """Grade one verdict.

    `day_number` drives #4's reward decay: the HD$ paid for a correct verdict
    shrinks as the campaign runs. It is an explicit parameter rather than
    something reached off GameState so this stays a pure function of its
    arguments — `apply()` passes `state.current_day`. It defaults to 1 (the
    undecayed day-1 rate) so existing callers keep their old numbers.
    """
    correct = candidate.truth.correct_verdict == player_verdict
    moral   = candidate.truth.moral_modifier

    correct_admit = (candidate.truth.correct_verdict == Verdict.ADMIT)
    player_admit  = (player_verdict == Verdict.ADMIT)

    # Evidence-board bonus (HD$) — only for correct verdicts (issue #27:
    # verdicts never grant ⏱; the daily compute pool is spend-only).
    bonus = board_accuracy_bonus(player_flags, candidate) if correct else 0

    # Site Health — every ADMIT applies the archetype's weight (issue #20).
    # Beneficial actors raise health; threats lower it. Denials never touch
    # it — a denied threat never entered the site.
    if player_admit:
        site_health = config.ARCHETYPE_HEALTH_WEIGHTS.get(
            candidate.archetype.value, 0.0)
    else:
        site_health = 0.0

    # HackDollar$ — persistent currency earned on correct verdicts (issue
    # #21). The board-accuracy bonus lands here too (issue #27), undecayed:
    # it is already accuracy-scored, so decaying it on top of the base rate
    # would penalise the same shift twice (issue #4).
    if correct:
        hackdollars = config.DAY_REWARD_PAYOUT(day_number, player_admit) + bonus
    else:
        hackdollars = 0

    # Moral / alignment consequence.
    if moral != 0:
        alignment = moral if player_admit else -moral
    else:
        alignment = 0

    return ScoreDelta(
        board_bonus=bonus,
        site_health=site_health,
        hackdollars=hackdollars,
        alignment=alignment,
        correct=correct,
    )


def apply(
    candidate: Candidate,
    player_verdict: Verdict,
    state,
    player_flags: set[DiscrepancyKind] | None = None,
) -> CandidateResult:
    """Apply scoring to mutable GameState and return the structured result.

    `state` is `core.models.GameState` — kept untyped here to avoid a
    forward import dance.
    `player_flags` is the set of DiscrepancyKinds the player marked on
    the Evidence Board. Pass None (or empty set) if the board was not used.
    """
    flags = player_flags or set()
    # #4: the day number drives reward decay. Read off the state here so every
    # existing call site picks the curve up without a signature change.
    delta = score(candidate, player_verdict, flags,
                  day_number=getattr(state, "current_day", 1))

    # Issue #27: verdicts never touch state.compute_hours — ⏱ is a
    # spend-only daily budget consumed exclusively by tools.
    # NOTE: delta.site_health is only RECORDED here — it lands on
    # state.site_health at end of day via apply_end_of_day_health().
    state.hackdollars += delta.hackdollars
    state.alignment = max(
        config.ALIGNMENT_MIN,
        min(config.ALIGNMENT_MAX, state.alignment + delta.alignment),
    )

    result = CandidateResult(
        candidate_id=candidate.id,
        archetype=candidate.archetype,
        player_verdict=player_verdict,
        correct=delta.correct,
        board_bonus=delta.board_bonus,
        alignment_delta=delta.alignment,
        site_health_delta=delta.site_health,
        hackdollar_delta=delta.hackdollars,
    )
    state.pending_results.append(result)
    return result


def apply_end_of_day_health(state) -> float:
    """Apply the day's accumulated Site Health deltas in one batch.

    Called once from `finish_day`. Sums the `site_health_delta` of every
    pending CandidateResult, clamps the new health to 0–100, and returns the
    day's total delta (for the EOD / between-day displays). Because this is
    the only place health is mutated, the loss condition can only be met at
    the end of a shift.
    """
    day_delta = sum(r.site_health_delta for r in state.pending_results)
    state.site_health = max(0.0, min(100.0, state.site_health + day_delta))
    return day_delta


def health_below_loss(state) -> bool:
    """True when Site Health has dipped below the loss threshold — game over."""
    return state.site_health < config.SITE_HEALTH_LOSS_THRESHOLD


def eod_health_bonus(state) -> int:
    """HackDollar$ bonus for ending the day above the reward threshold.

    Scales with health: the healthier the site, the larger the payout.
    Returns 0 below the reward threshold.
    """
    if state.site_health < config.SITE_HEALTH_REWARD_THRESHOLD:
        return 0
    return round(config.HACKDOLLAR_SITE_HEALTH_BONUS * state.site_health / 100.0)
