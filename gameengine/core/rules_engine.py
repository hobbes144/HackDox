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

from .models import (
    Candidate,
    DiscrepancyKind,
    Day,
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
