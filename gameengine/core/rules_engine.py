"""Day-ruleset evaluator.

The rules engine answers one question per call: which of today's rules
does this candidate trip? It does not produce a verdict — the *correct*
verdict comes from the candidate's GroundTruth. The player produces a
verdict from the rule evidence + the chat + their gut. Scoring compares
all three.

Rule predicates are looked up by string key so that Day files can stay as
authorable JSON. Adding a new predicate kind is a two-line addition to
`predicate_registry` below.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .models import (
    Candidate,
    Day,
    DiscrepancyKind,
    Rule,
    RuleEvaluation,
)

# A predicate takes the candidate (and optionally extra args parsed from
# the predicate string) and returns True iff the rule fires.
Predicate = Callable[[Candidate], bool]


# ─── Predicate factories ────────────────────────────────────────────────────


def _has_discrepancy(kind_name: str) -> Predicate:
    """Predicate: True iff the candidate has a planted discrepancy of `kind`."""
    try:
        kind = DiscrepancyKind(kind_name)
    except ValueError as e:
        raise ValueError(f"Unknown DiscrepancyKind in rule predicate: {kind_name}") from e

    def check(candidate: Candidate) -> bool:
        return any(d.kind == kind for d in candidate.truth.discrepancies)

    return check


def _has_any_discrepancy_of_severity(severity: str) -> Predicate:
    def check(candidate: Candidate) -> bool:
        return any(d.severity == severity for d in candidate.truth.discrepancies)

    return check


def _missing_field(field_name: str) -> Predicate:
    """Predicate: True iff a named dossier field is None/empty."""

    def check(candidate: Candidate) -> bool:
        value = getattr(candidate.dossier, field_name, None)
        return not value

    return check


# ─── Predicate registry ─────────────────────────────────────────────────────
#
# Predicate string grammar (kept deliberately tiny):
#
#   has_discrepancy:<KIND>            e.g. has_discrepancy:BREACH_HIT
#   has_severity:<minor|major|critical>
#   missing_field:<dossier_attr>      e.g. missing_field:claimed_github
#
# To add a new predicate kind, add a branch to `resolve` below.


def resolve(predicate_str: str) -> Predicate:
    """Parse a predicate string into a callable.

    Raises ValueError on unknown predicate shapes — fail loudly so that
    typos in Day JSON don't silently become "rule never fires".
    """
    if ":" not in predicate_str:
        raise ValueError(f"Predicate must be 'kind:arg' form, got {predicate_str!r}")

    kind, arg = predicate_str.split(":", 1)
    if kind == "has_discrepancy":
        return _has_discrepancy(arg)
    if kind == "has_severity":
        if arg not in {"minor", "major", "critical"}:
            raise ValueError(f"Unknown severity {arg!r}")
        return _has_any_discrepancy_of_severity(arg)
    if kind == "missing_field":
        return _missing_field(arg)
    raise ValueError(f"Unknown predicate kind {kind!r} in {predicate_str!r}")


# ─── Evaluation ─────────────────────────────────────────────────────────────


def evaluate(candidate: Candidate, day: Day) -> RuleEvaluation:
    """Return which rules fire for this candidate.

    Pure function — same inputs always produce the same output.
    """
    triggered_disq: list[Rule] = []
    triggered_weight: list[Rule] = []
    for rule in day.rules:
        predicate = resolve(rule.predicate)
        if predicate(candidate):
            if rule.severity == "disqualifying":
                triggered_disq.append(rule)
            else:
                triggered_weight.append(rule)
    return RuleEvaluation(
        triggered_disqualifying=tuple(triggered_disq),
        triggered_weighted=tuple(triggered_weight),
    )


# ─── Ruleset diffing (issue #36) ────────────────────────────────────────────
#
# The Overseer announces rule changes in the morning briefing. To say anything
# it first has to know what actually moved between yesterday's ruleset and
# today's — and, crucially, to say nothing about rules that are not allowed to
# move. A "fixed" rule that somehow differs between two days is a content bug,
# not a story beat, so it is excluded here rather than narrated.


@dataclass(frozen=True)
class RuleChange:
    """One difference between two days' rulesets.

    `kind` is "added" | "removed" | "severity", and `rule` is always the rule
    as it stands TODAY (for "removed", the version that just left the book).
    `previous_severity` is only meaningful for a "severity" change.
    """

    kind: str
    rule: Rule
    previous_severity: str | None = None


def diff_rulesets(previous: Day | None, current: Day) -> tuple[RuleChange, ...]:
    """What changed between two days' rulebooks, restricted to mutable rules.

    Returns an empty tuple when `previous` is None — day one has no yesterday,
    so nothing has "changed" and the briefing should say nothing.

    Only rules whose `mutability` is not "fixed" are reported (issue #35).
    That filter is what keeps the broadcast in the "minor process update"
    register the design asks for instead of a diff dump: a rule the player was
    told is permanent policy never generates a line, even in the pathological
    case where two day files disagree about it.

    Ordering follows today's rulebook so the Overseer's lines come out in the
    same order the player reads the rules page in.
    """
    if previous is None:
        return ()

    prev_by_id = {r.id: r for r in previous.rules}
    cur_by_id  = {r.id: r for r in current.rules}
    changes: list[RuleChange] = []

    for rule in current.rules:
        if rule.mutability == "fixed":
            continue
        was = prev_by_id.get(rule.id)
        if was is None:
            changes.append(RuleChange("added", rule))
        elif was.severity != rule.severity:
            changes.append(RuleChange("severity", rule,
                                      previous_severity=was.severity))

    for rule in previous.rules:
        # A rule that left the book is reported against ITS OWN mutability —
        # it isn't in today's rulebook to ask.
        if rule.mutability != "fixed" and rule.id not in cur_by_id:
            changes.append(RuleChange("removed", rule))

    return tuple(changes)
