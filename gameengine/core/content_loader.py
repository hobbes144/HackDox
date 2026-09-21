"""Load Day specs and narrative strings from `content/`.

Days are authored as JSON so they're diff-able and editable without a
Python edit cycle. The loader translates the JSON shape into a `Day`
dataclass.
"""

from __future__ import annotations

import json
from dataclasses import replace

from .. import config
from functools import lru_cache

from .candidate_gen import kinds_the_day_can_plant, stable_hash, stepped_rule_severity
from .models import (
    RULE_MUTABILITIES,
    Archetype,
    Day,
    DiscrepancyKind,
    Performance,
    Quotas,
    Rule,
    RuleSheet,
)


def _parse_rule(raw_rule: dict) -> Rule:
    """Build one Rule from its JSON object.

    `mutability` (issue #35) is optional and defaults to "fixed", so every day
    file authored before #35 loads byte-identically. An unrecognised value
    raises rather than silently degrading to "fixed" — the same fail-loud
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
        # Issue #37 — optional, defaults to None so every rule authored before
        # Dark Web directives existed loads unchanged. Validated (dark_web
        # requires a justification) where the rule is actually PLACED into a
        # book — see `_apply_rule_overrides` — not here, because a rule dict
        # parsed in isolation doesn't yet know it's being added as a directive.
        justification=raw_rule.get("justification"),
        # Issue #37 — the id of the rule this one replaces, when authored in
        # `added_rules`. Drives both the automatic removal of that id (see
        # `_apply_rule_overrides`) and the narration fold in `rule_change_lines`
        # (a superseded rule doesn't get its own generic "that clause is gone"
        # line — it's folded into this rule's own justification).
        supersedes=raw_rule.get("supersedes"),
    )


def _parse_rule_sheet(raw: dict | None) -> RuleSheet | None:
    """Build the day's approved/denied sheet from JSON (#49).

    Shape:

        "rule_sheet": {
          "summary": "...",
          "approved": {"domains": [...], "affiliations": [...]},
          "denied":   {"domains": [...], "affiliations": [...]},
          "notes":    ["..."]
        }

    Absent or empty returns None rather than a blank RuleSheet, so the
    reference panel has one unambiguous "nothing authored, use the word banks"
    signal instead of having to distinguish empty-from-missing.
    """
    if not raw:
        return None
    approved = raw.get("approved", {}) or {}
    denied   = raw.get("denied", {}) or {}
    unknown  = set(raw) - {"summary", "approved", "denied", "notes"}
    if unknown:
        # Same fail-loud stance as _parse_rule's mutability check, for the same
        # reason: a typo'd key that silently means "authored nothing" is a
        # content bug nobody notices until the rule sheet is mysteriously blank
        # in play.
        raise ValueError(
            f"Unknown rule_sheet key(s) {sorted(unknown)}; expected one of "
            f"['summary', 'approved', 'denied', 'notes']")
    sheet = RuleSheet(
        approved_domains=tuple(approved.get("domains", [])),
        denied_domains=tuple(denied.get("domains", [])),
        approved_affiliations=tuple(approved.get("affiliations", [])),
        denied_affiliations=tuple(denied.get("affiliations", [])),
        summary=raw.get("summary", ""),
        notes=tuple(raw.get("notes", [])),
    )
    return None if sheet.is_empty() else sheet


def _validate_slot(slot: int, day_number: int, candidate_count: int,
                    field: str) -> None:
    """Fail loudly if a slot-keyed day-file field names a slot outside the
    day's actual shift (#40 review fix).

    Shared by `forced_includes`/`forced_violations`/`forced_chat` so all
    three slot-scripting mechanisms fail the exact same way on the exact same
    mistake — a typo'd slot index that would otherwise silently script a
    candidate who never gets generated, with the day still loading and
    playing fine.
    """
    if not 0 <= slot < candidate_count:
        raise ValueError(
            f"day {day_number}: {field} names slot {slot}, but the day only "
            f"has {candidate_count} slots (0-{candidate_count - 1})")


def _parse_forced_includes(
    raw: dict, day_number: int, candidate_count: int,
) -> dict[int, Archetype]:
    """Parse and validate the day's pinned-archetype slots (#32).

    JSON shape: {"<slot index>": "<archetype value>"}. Bounds-validated the
    same way as `forced_violations`/`forced_chat` (#40 review fix) — this was
    previously the one slot-keyed mechanism of the three with NO bounds check
    at all, so a typo'd slot index here silently pinned a candidate who would
    never actually be generated, with no error to say so.
    """
    out: dict[int, Archetype] = {}
    for slot_raw, arch in (raw or {}).items():
        slot = int(slot_raw)
        _validate_slot(slot, day_number, candidate_count, "forced_includes")
        out[slot] = Archetype(arch)
    return out


def _parse_forced_violations(
    raw: dict, day_number: int, candidate_count: int,
    allowed_violations: tuple[DiscrepancyKind, ...],
) -> dict[int, tuple[DiscrepancyKind, ...]]:
    """Parse and VALIDATE the day's scripted violations (#15).

    JSON shape: {"<slot index>": ["<kind value>", ...]}.

    Validated here rather than in the generator, because this is where the
    error can name the day file the author actually has open. A script that
    asks for a violation the day cannot express would otherwise fail silently
    — the generator drops it and the tutorial day quietly stops demonstrating
    the mechanic it exists to teach, which is the single worst failure mode for
    scripted content: it still plays, it just teaches nothing.

    Three ways a script is wrong, all of them fatal:
      • the slot doesn't exist in this day's shift
      • the kind's revealing tool hasn't been taught yet (#31's tier gate)
      • the kind isn't expressible on this day (#61 — e.g. cross-breach reuse
        before a second breach corpus exists)
    """
    from .candidate_gen import _kind_is_expressible_on, intro_day

    out: dict[int, tuple[DiscrepancyKind, ...]] = {}
    for slot_raw, kinds_raw in (raw or {}).items():
        slot = int(slot_raw)
        _validate_slot(slot, day_number, candidate_count, "forced_violations")
        kinds: list[DiscrepancyKind] = []
        for value in kinds_raw:
            kind = DiscrepancyKind(value)
            if intro_day(kind) > day_number:
                raise ValueError(
                    f"day {day_number}: forced_violations slot {slot} asks for "
                    f"{kind.name}, but its revealing tool is not taught until "
                    f"day {intro_day(kind)} — the player would be scored on "
                    f"evidence they have no tool to read")
            if not _kind_is_expressible_on(kind, day_number):
                raise ValueError(
                    f"day {day_number}: forced_violations slot {slot} asks for "
                    f"{kind.name}, which cannot be expressed on this day (see "
                    f"candidate_gen._kind_is_expressible_on)")
            if allowed_violations and kind not in allowed_violations:
                raise ValueError(
                    f"day {day_number}: forced_violations slot {slot} asks for "
                    f"{kind.name}, which the day's own allowed_violations "
                    f"whitelist excludes — the two would contradict each other")
            kinds.append(kind)
        out[slot] = tuple(kinds)
    return out


def _parse_carrier_shapes(
    raw: dict, day_number: int, candidate_count: int,
) -> frozenset[int]:
    """Parse the day's pinned carrier shapes (2026-09-19).

    JSON shape: {"<slot index>": "conventional"}. The only pin is
    "conventional": a SPECIAL shape is authored the way any other scripted
    violation is, by naming its kind in forced_violations — two spellings for
    one fact would be two places to drift.
    """
    out: set[int] = set()
    for slot_raw, value in (raw or {}).items():
        slot = int(slot_raw)
        _validate_slot(slot, day_number, candidate_count, "carrier_shape")
        if value != "conventional":
            raise ValueError(
                f"day {day_number}: carrier_shape slot {slot} is {value!r} — "
                f"the only pin is \"conventional\"; author a special shape "
                f"by naming its kind (signal_comms_payload / "
                f"recursive_payload / hostile_payload) in forced_violations")
        out.add(slot)
    return frozenset(out)


def _validate_forced_shapes(
    forced_violations: dict[int, tuple[DiscrepancyKind, ...]],
    forced_includes: dict[int, Archetype],
    conventional_slots: frozenset[int],
    day_number: int,
) -> None:
    """A scripted carrier shape must be able to land — fail loudly if not.

    A shape kind is a free rider on a stego COLOUR kind (see
    candidate_gen._STEGO_SHAPE_KINDS): with no carrier there is no glyph, and
    the generator would drop the shape without a word — the silent-drop this
    module's validators exist to prevent. So a slot that forces a shape must:
      • force exactly one shape kind;
      • also force a stego colour kind — not merely be able to roll one, which
        would make the scripted shape land on some seeds and not others;
      • pin (forced_includes) a shape-eligible archetype that lists that
        colour kind in its eligible_kinds;
      • not also be pinned conventional.
    """
    from .candidate_gen import (
        _SHAPE_ELIGIBLE_ARCHETYPES,
        _STEGO_ARTIFACT_KINDS,
        _STEGO_SHAPE_KINDS,
        ARCHETYPE_SPECS,
    )

    for slot, kinds in forced_violations.items():
        shapes = [k for k in kinds if k in _STEGO_SHAPE_KINDS]
        if not shapes:
            continue
        where = f"day {day_number}: forced_violations slot {slot}"
        if len(shapes) > 1:
            raise ValueError(
                f"{where} forces {[k.name for k in shapes]} — one image, one "
                f"glyph: at most one carrier-shape kind per slot")
        colours = [k for k in kinds if k in _STEGO_ARTIFACT_KINDS]
        if not colours:
            raise ValueError(
                f"{where} forces {shapes[0].name} but no stego colour kind "
                f"(stego_payload_present / encrypted_payload / "
                f"covert_c2_channel) — a carrier shape needs a carrier")
        archetype = forced_includes.get(slot)
        if archetype is None or archetype not in _SHAPE_ELIGIBLE_ARCHETYPES:
            raise ValueError(
                f"{where} forces {shapes[0].name}, but the slot is not pinned "
                f"(forced_includes) to a shape-eligible archetype "
                f"({sorted(a.value for a in _SHAPE_ELIGIBLE_ARCHETYPES)})")
        if not any(c in ARCHETYPE_SPECS[archetype].eligible_kinds
                   for c in colours):
            raise ValueError(
                f"{where}: {archetype.value} cannot carry "
                f"{[c.name for c in colours]}, so {shapes[0].name} would have "
                f"no carrier")
        if slot in conventional_slots:
            raise ValueError(
                f"{where} forces {shapes[0].name} but carrier_shape pins the "
                f"same slot conventional — the two contradict each other")


def _parse_forced_chat(
    raw: dict, day_number: int, candidate_count: int,
    forced_includes: dict[int, Archetype],
) -> dict[int, tuple[str, ...]]:
    """Parse the day's scripted extra chat lines (Batch 5 Phase 3, #40).

    JSON shape: {"<slot index>": ["<line>", ...]} — the same slot-keyed shape
    as `forced_violations`/`forced_includes`. Unlike a scripted violation kind,
    a line of dialogue has no tool-tier gate or expressibility question to
    fail, so bounds-checking the slot (shared with the other two mechanisms
    via `_validate_slot`) is not the only thing worth validating loudly here.

    A scripted line landing on the WRONG archetype is arguably worse than one
    that never lands at all: `forced_chat` alone says nothing about which
    archetype occupies the slot, so an unpinned slot's archetype is whatever
    the day's shuffled bag happens to put there — seed-dependent, and liable
    to change the moment the day's archetype_mix is edited (#40 review fix:
    exactly this happened when day 9's mix grew a the_professional slot).
    A sympathetic "a friend of mine lost money" line landing on a Bad Actor or
    the Dark Web candidate would read as actively incoherent, with nothing in
    the loader to say why. So every scripted slot here MUST also be pinned in
    `forced_includes` — see CONTENT_AUTHORING.md's forced_chat recipe.
    """
    out: dict[int, tuple[str, ...]] = {}
    for slot_raw, lines_raw in (raw or {}).items():
        slot = int(slot_raw)
        _validate_slot(slot, day_number, candidate_count, "forced_chat")
        if slot not in forced_includes:
            raise ValueError(
                f"day {day_number}: forced_chat names slot {slot}, but that "
                f"slot has no forced_includes entry — a scripted chat line "
                f"needs a PINNED archetype, or it can land on a seed-"
                f"dependent (and possibly incoherent) candidate")
        lines: list[str] = []
        for line in lines_raw:
            if not isinstance(line, str):
                raise ValueError(
                    f"day {day_number}: forced_chat slot {slot} has a "
                    f"non-string line {line!r} — every forced_chat entry "
                    f"must be a plain string")
            lines.append(line)
        out[slot] = tuple(lines)
    return out


def scale_archetype_mix(
    base_mix: dict[Archetype, int],
    target_total: int,
) -> dict[Archetype, int]:
    """Rescale an archetype mix to sum to exactly `target_total`.

    Largest-remainder apportionment: each archetype gets its proportional
    share floored, then the leftover slots go to whoever was rounded down
    hardest. Ties break on the archetype's enum value so the result is a pure
    function of its inputs — generation determinism (#17 AC) depends on this
    never depending on dict iteration order.

    Hitting `target_total` exactly is the hard requirement, not a nicety:
    `candidate_gen._pick_archetype_for_slot` walks the shuffled mix bag with
    `bag[pos % len(bag)]`, so a bag that doesn't match the shift length wraps
    and the realized mix stops equalling the declared mix.

    Where there is room (`target_total >= len(base_mix)`) every archetype keeps
    at least one slot, so scaling down never silently deletes an archetype the
    day was meant to contain. Where there is NOT room — a shift shorter than
    the number of archetypes — the smallest proportional shares are dropped
    rather than breaking the total.
    """
    if target_total <= 0 or not base_mix:
        return dict(base_mix)
    items = sorted(base_mix.items(), key=lambda kv: kv[0].value)
    base_total = sum(count for _, count in items)
    if base_total == 0:
        return dict(base_mix)

    exact = {a: target_total * c / base_total for a, c in items}

    if target_total < len(items):
        # Not enough slots to represent every archetype. Keep the largest
        # proportional shares; enum value breaks ties so this stays a pure
        # function of its inputs.
        keep = sorted(items, key=lambda kv: (-exact[kv[0]], kv[0].value))
        keep = [a for a, _ in keep[:target_total]]
        return {a: 1 for a in sorted(keep, key=lambda a: a.value)}

    out = {a: max(1, int(exact[a])) for a, _ in items}

    # Reconcile: hand out (or claw back) whatever the flooring left over.
    # Largest remainder first when adding, smallest when removing.
    while sum(out.values()) < target_total:
        a = max(items, key=lambda kv: (exact[kv[0]] - out[kv[0]], kv[0].value))[0]
        out[a] += 1
    while sum(out.values()) > target_total:
        # Only take from archetypes that can spare a slot (floor of 1) — with
        # target_total >= len(items) there is always at least one.
        spare = [kv for kv in items if out[kv[0]] > 1]
        a = min(spare, key=lambda kv: (exact[kv[0]] - out[kv[0]], kv[0].value))[0]
        out[a] -= 1
    return out


def mutate_variable_rules(
    rules: tuple[Rule, ...],
    day_number: int,
) -> tuple[Rule, ...]:
    """Apply the day's Overseer-Variable rule flips (#36).

    Rules marked `overseer_variable` (#35) swing between "disqualifying" and
    "weighted" across the campaign — the flips the Overseer announces in the
    morning briefing. `fixed` and `dark_web` rules pass through untouched.

    Two properties this has to have, both load-bearing:

      • Sticky. A rule that re-rolled every single morning would produce a
        briefing full of noise and teach the player to ignore it. Each rule
        holds its state for RULE_FLIP_PERIOD days.
      • Staggered. Each rule's phase is derived from its own id, so rules do
        not all flip on the same morning — the design wants the occasional
        small aside, not a weekly policy dump.

    Seeded on the day number rather than the game seed: a rulebook is content,
    not a per-playthrough roll, so two players on the same day should be
    reading the same rules. Uses candidate_gen.stable_hash rather than the
    builtin hash(), which is salted per process — that exact mistake caused
    the 2026-07-18 determinism bug.
    """
    out: list[Rule] = []
    for rule in rules:
        if rule.mutability != "overseer_variable":
            out.append(rule)
            continue
        phase = stable_hash(rule.id, "phase") % config.RULE_FLIP_PERIOD
        epoch = (day_number + phase) // config.RULE_FLIP_PERIOD
        strict = stable_hash(rule.id, epoch) % 2 == 0
        out.append(replace(
            rule, severity="disqualifying" if strict else "weighted"))
    # 2026-09-19: the day's scheduled severity steps are part of "day N's book
    # from the day-1 template" too, so every caller that derives a day's rules
    # this way (load_day's inherit branch, synthesize_day, the tests) gets them.
    return apply_severity_steps(tuple(out), day_number)


def _rule_kind(rule: Rule) -> DiscrepancyKind | None:
    if not rule.predicate.startswith("has_discrepancy:"):
        return None
    try:
        return DiscrepancyKind(rule.predicate.split(":", 1)[1])
    except ValueError:
        return None


def apply_severity_steps(
    rules: tuple[Rule, ...],
    day_number: int,
) -> tuple[Rule, ...]:
    """Make a `fixed` rule follow its kind's scheduled severity step.

    candidate_gen._SEVERITY_BY_DAY steps a few kinds up on a set day (today:
    UNSALTED_STORAGE, minor until Hashcrack arrives, major from then). The
    violation's rule has to move with it or the book and the evidence board
    disagree — which is exactly what day_01.json did before 2026-09-19: the
    kind filed as a minor note on days 1-2 while its rule said "deny".

    Derived, not authored per day, for the same reason the step itself is
    derived from config.TOOL_UNLOCK_DAY: move the tool and the rule follows.
    Only `fixed` rules are stepped — an overseer_variable or dark_web rule on
    such a kind already has its own authored way of moving, and letting two
    mechanisms fight over one rule's severity would make it unpredictable.
    """
    out: list[Rule] = []
    for rule in rules:
        kind = _rule_kind(rule)
        stepped = (stepped_rule_severity(kind, day_number)
                   if kind is not None and rule.mutability == "fixed" else None)
        out.append(rule if stepped is None or stepped == rule.severity
                   else replace(rule, severity=stepped))
    return tuple(out)


def _reject_duplicate_rule_ids(rules: tuple[Rule, ...], day_number: int) -> None:
    """Two rules with one id is always a content bug (2026-09-19).

    day_01.json shipped two `rule_unsalted_storage` and two
    `rule_cross_breach_reuse` entries — older and newer wordings of the same
    rule, both live. Every consumer keys rules by id (diff_rulesets, the
    supersedes/removed_rules machinery), so one copy silently shadowed the
    other there, while the rules tab printed both.
    """
    seen: set[str] = set()
    for rule in rules:
        if rule.id in seen:
            raise ValueError(
                f"day {day_number}: rule id {rule.id!r} appears more than "
                f"once in the rulebook")
        seen.add(rule.id)


def synthesize_day(day_number: int) -> Day:
    """Build a Day procedurally when no day_NN.json exists (#17).

    Before this, `load_day` raised FileNotFoundError for anything past Day 1
    and the campaign simply ended after the first shift — which meant every
    day-scaled difficulty lever (#4's reward decay and cost inflation, #17's
    volume ramp, #36's day-over-day rule diff) was dead code that could never
    be observed in play.

    A synthesized day inherits Day 1's rules and archetype proportions, then
    applies the config curves for length, quota and difficulty band. It is a
    floor, not a substitute for authored content: an authored day_NN.json
    always wins, so #39/#40/#41 can replace these one day at a time without
    touching this function.
    """
    template = load_day(1)
    count = config.DAY_CANDIDATE_COUNT(day_number)
    band  = config.difficulty_band_for_day(day_number)
    # #4's detection-complexity lever: the band picks the archetype weighting,
    # so late days load up on the Sneaky Bugger while easy days lean on the
    # obvious cases the tutorial taught. Falls back to Day 1's own proportions
    # if a band ever has no table.
    weights = config.ARCHETYPE_MIX_BY_BAND.get(band)
    base_mix = (
        {Archetype(k): v for k, v in weights.items()} if weights
        else template.archetype_mix
    )
    return Day(
        number=day_number,
        title=f"Day {day_number}",
        # #36: the day's Overseer-Variable rules take their flip for this day,
        # which is what gives the briefing something to announce.
        rules=mutate_variable_rules(template.rules, day_number),
        candidate_count=count,
        archetype_mix=scale_archetype_mix(base_mix, count),
        quotas=Quotas(
            min_correct_admits=config.DAY_MIN_CORRECT_ADMITS(day_number, count),
            max_false_admits=template.quotas.max_false_admits,
        ),
        # These narrative keys are deliberately allowed not to exist. Every
        # consumer reads them through dict.get with a fallback, so a
        # synthesized day plays with generic Overseer copy rather than
        # crashing — and the moment #39/#40/#41 author real keys, they land.
        overseer_intro_key=f"day{day_number}_intro",
        overseer_outro_keys={
            p: f"day{day_number}_outro_{p.value}" for p in Performance
        },
        allowed_violations=(),   # no whitelist — only #31's evidence-tier gate
        difficulty_band=band,
        forced_includes={},
        # A synthesized day scripts nothing and authors no rule sheet: both are
        # what makes a day AUTHORED, and inheriting Day 1's would be actively
        # wrong — its scripted slots teach mechanics the player learned fifteen
        # days ago, and its rule sheet describes a rulebook that has since
        # moved. Note this is NOT inherited from `template` for that reason.
        forced_violations={},
        forced_chat={},
        rule_sheet=None,
    )


def _apply_rule_overrides(
    rules: tuple[Rule, ...], added_raw: object, removed_raw: object,
    day_number: int,
) -> tuple[tuple[Rule, ...], frozenset[str]]:
    """Apply `added_rules` and `removed_rules` on top of a day's base rulebook.

    Issue #37 — lets a Dark Web directive ADD a new, laxer rule while
    REMOVING the rule it supersedes, without restating the whole ~28-entry
    book. Both inputs are optional (pass `[]` for an absent key) and
    absent-safe, so every pre-#37 day file loads byte-identically.

    A rule is removed if its id is in `removed_raw`, OR it is named by an
    added rule's own `supersedes` field — the latter is what lets
    `rule_change_lines` fold the removal into the new rule's justification
    instead of emitting a second, contradicting generic line (see that
    function). `supersedes` on an `added_rules` entry must name either an id
    already in the inherited book, OR an id introduced STRICTLY EARLIER in
    this SAME `added_rules` batch (issue #42/Phase 5b-1: this is what lets
    one directive supersede a PREVIOUS directive directly, e.g. day 13's
    `dw05_payload_crackdown` naming `dw04_payload_leniency` in its own
    `supersedes` field, rather than only ever being able to re-target the
    original day-1 rule a whole chain of directives eventually traces back
    to — `load_day` always rebuilds a day's book fresh from Day 1, so
    `dw04_payload_leniency` only exists at all on a day that re-lists it in
    that same day's `added_rules`). The "strictly earlier" part is load-time
    enforced, not just documented: each entry's `supersedes` is checked
    against only the ids already seen at that point in the array, before
    that entry's own id is added to the seen set — so self-supersession
    (an entry naming its own id) and mutual supersession (two entries each
    naming the other) both fail loudly instead of both silently vanishing
    from the book with no error and no briefing line. `removed_rules`, by
    contrast, may only name an id already in the inherited book — naming an
    id this same file's own `added_rules` just introduced has no legitimate
    meaning (there's nothing to "remove" that this file didn't also just
    add) and is rejected rather than silently netting out to a no-op.
    An `added_rules` entry that is itself named by a later entry's
    `supersedes` is silently dropped from the final book — it was only
    re-listed so there was something for the new entry to supersede,
    mirroring how an inherited rule named by `supersedes` never survives
    into the final book either. Every `added_rules` id must NOT already be
    in the inherited book (same-id "replace" is rejected: `diff_rulesets`
    compares severity only, so a same-id swap could silently vanish from
    the briefing). Duplicate ids within `added_rules` itself are also
    rejected. A `dark_web`-mutability added rule must carry a
    `justification` — this check is scoped to `added_rules` specifically,
    not the whole rulebook (a `dark_web` rule hand-authored directly in a
    full `rules` restatement predates this and is not held to it; see
    `test_rule_mutability_survives_a_day_json_round_trip`).

    IMPORTANT — this does not itself make directives cumulative across days.
    `load_day`'s inherit branch always inherits from Day 1, not from the
    previous day, so a directive's `added_rules`/`removed_rules` must be
    RE-AUTHORED on every later day that should still carry it. See
    CONTENT_AUTHORING.md's Dark Web directives section.

    Returns `(final_rules, directive_removed_rule_ids)` — the second element
    is threaded onto `Day.directive_removed_rule_ids` so `diff_rulesets` can
    report a deliberately-retired `fixed` rule instead of staying silent as
    it does for an accidental gap between two day files.
    """
    if not isinstance(added_raw, list):
        raise ValueError(
            f"day {day_number}: added_rules must be a list of rule objects, "
            f"got {type(added_raw).__name__}")
    if not isinstance(removed_raw, list):
        raise ValueError(
            f"day {day_number}: removed_rules must be a list of rule ids, "
            f"got {type(removed_raw).__name__}")

    inherited_ids = {r.id for r in rules}
    # The set of ids a `removed_rules`/`supersedes` reference is legal
    # against — only the inherited book plus whatever `added_rules` entries
    # have already been validated and appended SO FAR in the loop below.
    # Grown incrementally (not unioned in wholesale after the loop) so that
    # `supersedes` is checked positionally: an entry may only name an id
    # that came strictly before it in this same batch, never itself or a
    # later one (see the docstring above — this is what makes self- and
    # mutual-supersession load-time errors instead of silent rule drops).
    removable_ids = set(inherited_ids)

    added_rules: list[Rule] = []
    seen_added_ids: set[str] = set()
    for r in added_raw:
        rule = _parse_rule(r)
        if rule.id in seen_added_ids:
            raise ValueError(
                f"day {day_number}: added_rules lists {rule.id!r} more than "
                f"once")
        if rule.id in inherited_ids:
            raise ValueError(
                f"day {day_number}: added_rules id {rule.id!r} collides "
                f"with a rule already in the inherited rulebook — same-id "
                f"replacement isn't supported (diff_rulesets compares "
                f"severity only, so a same-id swap could silently vanish "
                f"from the Overseer's briefing); give the new rule its own "
                f"id and use removed_rules/supersedes to retire the old one")
        if rule.mutability == "dark_web" and not rule.justification:
            raise ValueError(
                f"day {day_number}: added_rules {rule.id!r} is "
                f"mutability=dark_web but has no justification — a Dark "
                f"Web directive must always carry in-fiction "
                f"justification text (see Rule.justification)")
        if rule.supersedes and rule.supersedes not in removable_ids:
            raise ValueError(
                f"day {day_number}: added_rules {rule.id!r} supersedes "
                f"{rule.supersedes!r}, which is neither in this day's "
                f"inherited rulebook nor introduced earlier in this same "
                f"added_rules batch — self- or mutual-supersession (an "
                f"entry naming its own id, or two entries naming each "
                f"other) is not supported, and a forward reference to a "
                f"later entry would make the ordering meaningless")
        seen_added_ids.add(rule.id)
        added_rules.append(rule)
        removable_ids.add(rule.id)

    # `removed_rules` may only name an id already in the INHERITED book —
    # naming an id this same file's `added_rules` just introduced has no
    # legitimate meaning (there is nothing to retire that this file didn't
    # also just add in the same breath) and is rejected rather than
    # silently netting out to a no-op that drops the new rule.
    for rid in removed_raw:
        if rid not in inherited_ids:
            raise ValueError(
                f"day {day_number}: removed_rules names {rid!r}, which is "
                f"not in this day's inherited rulebook")

    removed_ids = set(removed_raw) | {
        r.supersedes for r in added_rules if r.supersedes
    }

    rules = (
        tuple(r for r in rules if r.id not in removed_ids)
        # An added_rules entry named by another added entry's `supersedes`
        # (chained supersession, above) is dropped here too — it was only
        # re-listed to give the new entry something to retire, and must not
        # survive into the final book alongside its own replacement.
        + tuple(r for r in added_rules if r.id not in removed_ids)
    )
    return rules, frozenset(removed_ids)


def load_day(day_number: int) -> Day:
    path = config.DAYS_DIR / f"day_{day_number:02d}.json"
    if not path.exists():
        # No authored content for this day. Synthesize one inside the campaign
        # (#17); past the last day, fall through to the original
        # FileNotFoundError, which is what drives CampaignEndScreen.
        if 1 < day_number <= config.CAMPAIGN_LAST_DAY:
            return synthesize_day(day_number)
        raise FileNotFoundError(path)

    raw = json.loads(path.read_text(encoding="utf-8"))
    # `rules` is optional as of #15. The rulebook is campaign-wide — day_01.json
    # carries all 27 entries — and requiring every authored day to restate them
    # would mean five near-identical 190-line files where the only real
    # differences are the archetype mix, the scripted slots and the rule sheet.
    # An authored day should contain what is DIFFERENT about that day; a
    # duplicated rulebook is a merge conflict waiting to happen and a place for
    # the days to silently drift apart.
    #
    # Omitting it inherits Day 1's rules with this day's Overseer-Variable flips
    # applied (#36), which is exactly what synthesize_day does — so an authored
    # day and a synthesized one agree about what the rulebook says today.
    if "rules" in raw:
        rules = tuple(_parse_rule(r) for r in raw["rules"])
    elif raw["number"] == 1:
        # Day 1 is the template every other day inherits from, so it has
        # nowhere to fall back to. Fail loudly rather than start with an empty
        # rulebook, which would silently make every candidate a clean admit.
        raise ValueError("day_01.json must declare 'rules' — every other day "
                         "inherits from it")
    else:
        rules = mutate_variable_rules(load_day(1).rules, raw["number"])
    _reject_duplicate_rule_ids(rules, raw["number"])
    # 2026-09-19: kinds with a scheduled severity step carry the step into
    # their fixed rule (weighted while minor, disqualifying once major). The
    # inherit branch already got it from mutate_variable_rules; a day that
    # restates its whole `rules` array (day 1) gets it here. Idempotent.
    rules = apply_severity_steps(rules, raw["number"])
    # Issue #37 — Dark Web directives (and any other future content that needs
    # to add/retire one rule without restating the whole book) layer on top of
    # whichever base the two branches above produced. NOTE: this does NOT make
    # a directive persist to the next day on its own — see the warning in
    # `_apply_rule_overrides`'s docstring and CONTENT_AUTHORING.md.
    rules, directive_removed_rule_ids = _apply_rule_overrides(
        rules, raw.get("added_rules", []), raw.get("removed_rules", []),
        raw["number"])
    archetype_mix = {
        Archetype(key): count for key, count in raw["archetype_mix"].items()
    }
    # candidate_count is optional as of #17: a day file that omits it takes the
    # campaign volume curve. day_01.json still declares 6, so Day 1 is
    # unchanged.
    candidate_count = raw.get("candidate_count") or config.DAY_CANDIDATE_COUNT(
        raw["number"])
    # compute_target retired by issue #27 (⏱ is a spend-only daily budget);
    # legacy day files that still carry it are simply ignored.
    # min_correct_admits scales with shift length (#17) but never drops below
    # what the day file asked for.
    quotas = Quotas(
        min_correct_admits=config.DAY_MIN_CORRECT_ADMITS(
            raw["number"], candidate_count,
            raw["quotas"].get("min_correct_admits"),
        ),
        max_false_admits=raw["quotas"]["max_false_admits"],
    )
    outro_keys = {
        Performance(k): v for k, v in raw["overseer_outro_keys"].items()
    }
    # Per-day candidate spec (#32) — all optional so pre-#32 files load as-is.
    allowed_violations = tuple(
        DiscrepancyKind(k) for k in raw.get("allowed_violations", [])
    )
    difficulty_band = raw.get(
        "difficulty_band", config.difficulty_band_for_day(raw["number"]))
    forced_includes = _parse_forced_includes(
        raw.get("forced_includes", {}), raw["number"], candidate_count)
    # #15/#49 — both optional, so every pre-Batch-4 day file loads unchanged.
    forced_violations = _parse_forced_violations(
        raw.get("forced_violations", {}), raw["number"], candidate_count,
        allowed_violations)
    # forced_chat requires forced_includes to already be resolved, so a
    # scripted slot with no pinned archetype fails loudly (#40 review fix).
    forced_chat = _parse_forced_chat(
        raw.get("forced_chat", {}), raw["number"], candidate_count,
        forced_includes)
    # 2026-09-19 — carrier-shape scripting (see _validate_forced_shapes).
    conventional_carrier_slots = _parse_carrier_shapes(
        raw.get("carrier_shape", {}), raw["number"], candidate_count)
    _validate_forced_shapes(forced_violations, forced_includes,
                            conventional_carrier_slots, raw["number"])
    rule_sheet = _parse_rule_sheet(raw.get("rule_sheet"))
    return Day(
        number=raw["number"],
        title=raw["title"],
        rules=rules,
        candidate_count=candidate_count,
        archetype_mix=archetype_mix,
        quotas=quotas,
        overseer_intro_key=raw["overseer_intro_key"],
        overseer_outro_keys=outro_keys,
        allowed_violations=allowed_violations,
        difficulty_band=difficulty_band,
        forced_includes=forced_includes,
        forced_violations=forced_violations,
        forced_chat=forced_chat,
        rule_sheet=rule_sheet,
        directive_removed_rule_ids=directive_removed_rule_ids,
        conventional_carrier_slots=conventional_carrier_slots,
    )


@lru_cache(maxsize=None)
def kinds_discovered_through(day_number: int) -> frozenset[DiscrepancyKind]:
    """Every DiscrepancyKind reachable on ANY day from 1 through `day_number`,
    unioned — the cumulative, monotonic answer, as opposed to
    `candidate_gen.kinds_the_day_can_plant(day)`'s single-day one.

    Progression-unlock fix (2026-09): the Evidence Board and Rules page used
    to gate on the single-day question alone, so a kind whose only eligible
    archetype simply wasn't scheduled in *today's* `archetype_mix` would
    vanish from the board even though an earlier day's candidates could (and
    did) carry it — e.g. Day 3's scripted mix drops DISPOSABLE_EMAIL and
    UNSALTED_STORAGE, which Day 1 and Day 2 both taught. That reads as the
    Overseer erasing evidence, not as a difficulty gate, and it breaks the
    board's whole premise: once something is a thing to check for, it should
    stay a thing to check for.

    So this walks every day from 1 to `day_number` and unions what each one
    could plant — a kind that was ever reachable stays reachable for the rest
    of the campaign, even on a later day whose own script wouldn't roll it.
    The whitelist and tool-unlock floors still apply per kind (via
    `kinds_the_day_can_plant`'s own gates) — this only makes the
    archetype-mix/whitelist combination monotonic across days, it does not
    loosen either gate on the day a kind first becomes reachable.

    Cached: day content (`load_day`/`synthesize_day`) is a pure function of
    `day_number` alone, so the union for a given `day_number` never changes
    within a process, and re-walking days 1..N on every catalog render would
    be wasted work — this is called from every Evidence Board repaint and
    every Rules-page tab switch.
    """
    if day_number < 1:
        return frozenset()
    discovered: set[DiscrepancyKind] = set()
    for n in range(1, day_number + 1):
        discovered |= kinds_the_day_can_plant(load_day(n))
    return frozenset(discovered)


def load_narratives() -> dict[str, str]:
    path = config.NARRATIVES_DIR / "overseer.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ─── Narrative resolution (#15 / #44-47) ─────────────────────────────────────
#
# synthesize_day assigns narrative keys — "day7_intro", "day7_outro_poor" —
# that are deliberately allowed not to exist, so an unauthored day still plays.
# What was NOT intended is what "still plays" turned out to mean: every consumer
# read them with `dict.get(key, "")`, so days 2 through 20 opened on an Overseer
# panel containing nothing at all, and the end-of-day beat printed the literal
# string "...". The mechanism was right; there was simply no second layer for it
# to fall through TO.
#
# resolve_narrative adds that layer. A day-specific key wins; failing that, a
# generic key authored in the same overseer.json; failing that, a hard-coded
# last resort so the panel is never empty. Keeping the generic copy in the JSON
# rather than in Python matters: overseer.json stays the one file to open to
# change anything the Overseer says.

_GENERIC_INTRO_KEY   = "generic_intro"
_GENERIC_BETWEEN_KEY = "generic_between"

# Last-resort copy, used only if overseer.json is missing its generic keys.
# Written to be true on any day rather than evocative on one.
_LAST_RESORT: dict[str, str] = {
    _GENERIC_INTRO_KEY:   "Same as yesterday. Read the book, work the line, "
                          "don't let anything through you can't account for.",
    "generic_outro_excellent": "Clean shift. Nothing to talk about, which is "
                               "the best thing I can say about a day here.",
    "generic_outro_passing":   "That'll do. The line moved and the site's "
                               "still standing.",
    "generic_outro_poor":      "Something got past you today. I'd rather it "
                               "didn't become a pattern.",
    "generic_outro_failed":    "We need to talk about today. Not here.",
    _GENERIC_BETWEEN_KEY: "Rest while you can. Tomorrow's list is longer, and "
                          "the rules won't be getting any kinder. Spend your "
                          "HackDollar$ wisely.",
}


def resolve_narrative(narratives: dict[str, str], key: str,
                      generic_key: str) -> str:
    """The Overseer's line for `key`, falling back to generic copy.

    Empty authored strings fall through too — an author blanking a key means
    "I haven't written this yet", not "the Overseer says nothing", and a silent
    panel is indistinguishable from a crash to the player.
    """
    return (narratives.get(key)
            or narratives.get(generic_key)
            or _LAST_RESORT.get(generic_key, ""))


def generic_outro_key(performance: Performance) -> str:
    return f"generic_outro_{performance.value}"
