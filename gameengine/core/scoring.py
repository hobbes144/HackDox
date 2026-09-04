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
    RuleEvaluation,
    Verdict,
)


@dataclass(frozen=True)
class ScoreDelta:
    board_bonus: int = 0        # HD$ portion from evidence-board accuracy
    site_health: float = 0.0
    hackdollars: int = 0        # total HD$ (verdict payout + board bonus)
    alignment: int = 0
    correct: bool = False       # MORAL track — matched GroundTruth
    # ── Literal-ruleset track (issue #38) ────────────────────────────────
    # What the day's ACTIVE RULEBOOK said to do, recorded separately from
    # what the candidate morally deserved. None when no RuleEvaluation was
    # supplied — an honest "not measured" rather than quietly mirroring the
    # moral track and claiming the two agreed.
    rules_verdict: Verdict | None = None
    rules_correct: bool | None = None

    @property
    def tracks_diverge(self) -> bool:
        """True when going by the book and going by conscience disagreed.

        The corruption arc's core tension in one boolean: a player can be
        correct by the rules and still have done the wrong thing.
        """
        return self.rules_correct is not None and self.rules_correct != self.correct


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

    One deliberate exception: a BREACH_HIT flag is credited against a
    CROSS_BREACH_REUSE violation instead of scored as a false positive.
    tools_bridge.breach_dbs_for_candidate() already shows a CROSS_BREACH_REUSE
    carrier's email as a match in Ghostscan's breach panel — labeled
    BREACH_HIT — even though the two stay distinct kinds in ground truth
    (#61d). The player is reading real evidence when they flag it, so it
    should never cost them the bonus.
    """
    actual = {d.kind for d in candidate.truth.discrepancies}
    if not actual and not player_flags:
        # Clean candidate, player correctly flagged nothing.
        return config.BOARD_ACCURACY_MAX_BONUS

    # Batch-3 content pass, revisiting #61(d): CROSS_BREACH_REUSE (Hashcrack)
    # and BREACH_HIT (Ghostscan) deliberately stay separate, distinct kinds in
    # ground truth (#61d's own words: "the two violations stay distinct").
    # But breach_dbs_for_candidate() (tools_bridge.py) already makes a
    # CROSS_BREACH_REUSE carrier's email genuinely show up — labeled
    # "BREACH_HIT" — in Ghostscan's breach panel, so a player flagging
    # BREACH_HIT there is reading real, on-screen evidence, not guessing.
    # Credit that flag as a match against the CROSS_BREACH_REUSE violation
    # instead of scoring it a false positive. Only ever helps: it folds a
    # BREACH_HIT flag into the CROSS_BREACH_REUSE slot rather than adding a
    # second required flag, so it can't create a new miss, and flagging both
    # BREACH_HIT and CROSS_BREACH_REUSE nets to the same single true positive
    # (not a false positive for the "redundant" one).
    credited_flags = set(player_flags)
    if (DiscrepancyKind.BREACH_HIT not in actual
            and DiscrepancyKind.CROSS_BREACH_REUSE in actual
            and DiscrepancyKind.BREACH_HIT in credited_flags):
        credited_flags.discard(DiscrepancyKind.BREACH_HIT)
        credited_flags.add(DiscrepancyKind.CROSS_BREACH_REUSE)

    true_pos  = len(credited_flags & actual)
    false_pos = len(credited_flags - actual)
    false_neg = len(actual - credited_flags)
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
    evaluation: RuleEvaluation | None = None,
) -> ScoreDelta:
    """Grade one verdict.

    `day_number` drives #4's reward decay: the HD$ paid for a correct verdict
    shrinks as the campaign runs. It is an explicit parameter rather than
    something reached off GameState so this stays a pure function of its
    arguments — `apply()` passes `state.current_day`. It defaults to 1 (the
    undecayed day-1 rate) so existing callers keep their old numbers.

    `evaluation` is the day's RuleEvaluation for this candidate (issue #38).
    Supplying it records the LITERAL-RULESET track alongside the moral one.
    It changes no payout: the economy is keyed off the moral `correct` exactly
    as before, and this is a parallel tracked value, not a scoring override.
    """
    correct = candidate.truth.correct_verdict == player_verdict
    moral   = candidate.truth.moral_modifier

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

    # ── Literal-ruleset track (issue #38) ────────────────────────────────
    # The rulebook's own answer: DENY if any disqualifying rule fired, ADMIT
    # otherwise. Weighted rules are advisory by definition — they inform the
    # player, they don't decide.
    #
    # Today this usually agrees with the moral track, because the Dark Web
    # archetype is generated rules-clean (no discrepancies, so no rule fires)
    # and admitting it is both by-the-book and a drift toward the Dark Web.
    # That agreement is a property of the current CONTENT, not of the engine.
    # The moment #37's Dark Web directives write a rule that permits what the
    # ground truth condemns, one boolean can no longer express the
    # disagreement — so the two are recorded separately now, before anything
    # depends on them coinciding.
    if evaluation is not None:
        rules_verdict = (Verdict.DENY if evaluation.triggered_disqualifying
                         else Verdict.ADMIT)
        rules_correct = (rules_verdict == player_verdict)
    else:
        rules_verdict = None
        rules_correct = None

    return ScoreDelta(
        board_bonus=bonus,
        site_health=site_health,
        hackdollars=hackdollars,
        alignment=alignment,
        correct=correct,
        rules_verdict=rules_verdict,
        rules_correct=rules_correct,
    )


def apply(
    candidate: Candidate,
    player_verdict: Verdict,
    state,
    player_flags: set[DiscrepancyKind] | None = None,
    evaluation: RuleEvaluation | None = None,
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
                  day_number=getattr(state, "current_day", 1),
                  evaluation=evaluation)

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
        rules_verdict=delta.rules_verdict,
        rules_correct=delta.rules_correct,
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
