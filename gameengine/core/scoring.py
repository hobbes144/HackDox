"""Scoring — the asymmetric reward/penalty matrix.

Computing Hours (⏱) are the resource. They are EARNED by accuracy, never
lost by wrong verdicts. Wrong verdicts cost lives and shift alignment instead.

| Correct verdict | Player verdict | Compute (⏱)          | Lives | Alignment |
|-----------------|----------------|----------------------|-------|-----------|
| ADMIT           | ADMIT          | +CORRECT_REWARD      |   0   |  +moral   |
| ADMIT           | DENY           |   0                  |   0   |  -moral   |
| DENY            | DENY           | +CORRECT_REWARD      |   0   |  -moral   |
| DENY            | ADMIT          |   0                  |  -1   |  +moral   |

Additionally, evidence board accuracy adds 0–BOARD_MAX_BONUS ⏱ on top of any
correct verdict reward.

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
    compute: int = 0
    board_bonus: int = 0
    lives: int = 0
    alignment: int = 0
    correct: bool = False


def board_accuracy_bonus(
    player_flags: set[DiscrepancyKind],
    candidate: Candidate,
) -> int:
    """Score the player's evidence board against ground truth.

    Returns 0–BOARD_ACCURACY_MAX_BONUS ⏱.
    Uses an F1-style metric: perfect match = full bonus, partial = scaled.
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
) -> ScoreDelta:
    correct = candidate.truth.correct_verdict == player_verdict
    moral   = candidate.truth.moral_modifier

    correct_admit = (candidate.truth.correct_verdict == Verdict.ADMIT)
    player_admit  = (player_verdict == Verdict.ADMIT)

    # Compute reward — only for correct verdicts.
    if correct:
        base_compute = config.CORRECT_VERDICT_REWARD
        bonus        = board_accuracy_bonus(player_flags, candidate)
    else:
        base_compute = 0
        bonus        = 0

    # Life penalty — only for false admits.
    if not correct_admit and player_admit:
        lives = -config.FALSE_ADMIT_LIVES_PENALTY
    else:
        lives = 0

    # Moral / alignment consequence.
    if moral != 0:
        alignment = moral if player_admit else -moral
    else:
        alignment = 0

    return ScoreDelta(
        compute=base_compute + bonus,
        board_bonus=bonus,
        lives=lives,
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
    delta = score(candidate, player_verdict, flags)

    state.compute_hours += delta.compute
    state.lives += delta.lives
    state.alignment = max(
        config.ALIGNMENT_MIN,
        min(config.ALIGNMENT_MAX, state.alignment + delta.alignment),
    )

    result = CandidateResult(
        candidate_id=candidate.id,
        archetype=candidate.archetype,
        player_verdict=player_verdict,
        correct=delta.correct,
        compute_delta=delta.compute,
        board_bonus=delta.board_bonus,
        alignment_delta=delta.alignment,
        lives_delta=delta.lives,
    )
    state.pending_results.append(result)
    return result
