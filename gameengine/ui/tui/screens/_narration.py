"""Foreman (Overseer) narration helpers — dockside voice, see VOICE_GUIDE.md."""

from __future__ import annotations

from gameengine import config
from gameengine.core import candidate_gen
from gameengine.ui.tui.widgets import (
    TypewriterLog,
)


def _overseer_lines(narrative: str) -> list[str]:
    """Split an Overseer narrative into typed lines for TypewriterLog (#3).

    Blank lines are kept for pacing; a plain paragraph with no newlines types
    out as a single line.
    """
    return narrative.split("\n") if narrative else [""]


def _play_overseer(log: TypewriterLog, narrative: str, *, triggers_on_last=None) -> None:
    """Stream an Overseer beat, one auto-chaining message per line.

    Each line is its own message so the beat plays out without the player
    needing to press Space between lines (these host screens don't focus the
    log — they keep Space for their own begin/continue/buy action). #34 hangs
    a tool-unlock off `triggers_on_last`, which rides the final line's
    TypewriterLog.Finished so the unlock lands exactly when the beat ends.
    """
    lines = _overseer_lines(narrative)
    for i, line in enumerate(lines):
        last = i == len(lines) - 1
        log.post("", line, triggers=(triggers_on_last if last else None))


# Foreman unlock narration, one line per tool (#34), played right after that
# day's briefing. Written in the dockside voice (VOICE_GUIDE.md) and kept short:
# the day 2-5 intros already teach each tool, so this line only marks the moment
# the gear is handed over. The `triggers` payload on this line is the tool value
# string, which the briefing's Finished handler uses to flip
# GameState.unlocked_tools.
_UNLOCK_LINES: dict[str, str] = {
    "ghostscan": "New gear on the desk: GHOSTSCAN. Public traces don't lie the way people at the gate do.",
    "hashcrack": "New gear on the desk: HASHCRACK. If they reused a breached password, we'll pry it open.",
    "logwatch":  "New gear on the desk: LOGWATCH. The logbook remembers every step they took on this pier.",
    "stegotool": "New gear on the desk: STEGOTOOL. They're smuggling payloads in plain sight now. Look closer.",
}


# ─── Overseer-Variable rule broadcast (#36) ─────────────────────────────────
#
# The Foreman (the Overseer, to the code) mentions rule changes in passing. The
# design is explicit that a small change should read as a minor process update,
# not a klaxon — so these are deliberately understated, hedged, and a little
# bored. Several openers per change kind so a two-change morning doesn't read as
# a filled-in template. Dockside voice per VOICE_GUIDE.md, lightly.
#
# {rule} is the rule's own text, lower-cased at the first character and
# stripped of its trailing period so it sits inside a sentence.
_RULE_CHANGE_PHRASINGS: dict[str, tuple[str, ...]] = {
    # A rule got teeth: advisory → disqualifying.
    "tightened": (
        ("Oh — one thing before the first boat. That guidance about {rule}? "
        "Policy now. Not a suggestion. Don't make me explain it twice."),
        ("Small note. {rule} — that's a hard deny from today. Compliance "
        "wanted it in writing, so now it's in writing."),
        ("Quick amendment: {rule}. It used to be your judgement. It isn't "
        "anymore — it's posted at the gate."),
    ),
    # A rule lost its teeth: disqualifying → advisory.
    "relaxed": (
        ("Before I forget — {rule}. That's a note now, not a bar. Flag it, "
        "wave them through. Don't overthink it."),
        ("Legal's been busy. {rule} is advisory from this morning. Use your "
        "judgement, which I'm told you have."),
        ("Minor thing. {rule} — we're not turning anybody back on that on its "
        "own anymore. Log it and keep the line moving."),
    ),
    "added": (
        "New line in the book today: {rule}. Read it properly at some point.",
        "They've added one. {rule}. I didn't write it, I just pass it down the pier.",
    ),
    "removed": (
        ("That clause about {rule} is gone as of this morning. Don't ask me "
        "why; I stopped asking."),
        "We've dropped the line about {rule}. Nobody's said why.",
    ),
}


# Endless (#7): the Foreman is on the player's side, so a rule change comes
# with an explanation instead of a shrug. Small changes (a rule easing to
# advisory) are mentioned casually; big ones (a rule becoming a hard deny)
# carry a reason — what she's heard from other ports. Endless never adds or
# removes rules, only flips Overseer-Variable severities, so these two buckets
# are the whole vocabulary.
_ENDLESS_RULE_CHANGE_PHRASINGS: dict[str, tuple[str, ...]] = {
    "tightened": (
        ("Heads up, and it's a big one: {rule} is a hard deny from today. Two "
        "ports sent cases back last week on exactly that, so we're closing "
        "the gap before it reaches us."),
        ("One change you'll want to know about. {rule} — that's a deny now, "
        "not a note. The harbour office traced a string of opened cases to it, "
        "and I'd rather we tighten up early than explain it later."),
        ("Before the first boat: {rule} just became a hard stop. It's been "
        "the common thread in the bad bonds up and down the coast. If you see "
        "it, turn them back."),
    ),
    "relaxed": (
        ("Small thing — {rule} is advisory again. Flag it if you see it, but "
        "it's not a reason to turn someone back on its own."),
        ("Easing one: {rule}. Note it and use your judgement; it was catching "
        "too many honest couriers."),
        ("Quick one. {rule} — we're back to flagging that, not denying on it. "
        "Keeps the line moving without costing us anything."),
    ),
}


def _rule_fragment(text: str) -> str:
    """Fold a rulebook line into something that can sit mid-sentence."""
    frag = text.strip().rstrip(".")
    # Rule text is authored as an instruction ("Deny any candidate whose…").
    # Strip the leading imperative so the Overseer isn't quoting a form at the
    # player — she's supposed to sound like she's mentioning it, not reading it.
    for lead in ("Deny any candidate whose ", "Deny any candidate who ",
                 "Flag (do not auto-deny) a ", "Flag (do not auto-deny) "):
        if frag.startswith(lead):
            frag = frag[len(lead):]
            break
    else:
        frag = frag[:1].lower() + frag[1:]
    # Rule text often carries its own em-dash aside; it reads badly nested
    # inside the Overseer's own sentence, so keep only the head clause.
    return frag.split(" — ")[0].strip()


def _starts_a_sentence(template: str) -> bool:
    """True when {rule} lands at the start of a sentence in this template.

    Rule fragments are lower-cased so they read naturally mid-sentence ("about
    claimed connection IP…"), which looks wrong when a template opens a
    sentence with one ("Legal's been busy. claimed connection IP is…"). Cheaper
    and safer than capitalising the finished line, which would also mangle
    abbreviations sitting inside the rule text.
    """
    head = template.split("{rule}", 1)[0].rstrip()
    return not head or head[-1] in ".!?"


def rule_change_lines(changes, day_number: int) -> list[str]:
    """One casual Overseer line per changed rule — Overseer-Variable or Dark Web.

    Deterministic in the day number and the rule id, so replaying a day
    reproduces the same briefing rather than re-rolling the Overseer's phrasing.

    Issue #37 — an `added` `dark_web`-mutability change gets the rule's OWN
    `justification` text, spoken verbatim, instead of a pick from
    `_RULE_CHANGE_PHRASINGS`. The whole point of a Dark Web directive is that
    it comes with real in-fiction reasoning, not the bored, interchangeable
    one-liners used for routine `overseer_variable` flips — reusing the generic
    pool here would flatten that distinction right back out. `content_loader`
    guarantees a `dark_web` rule always has a justification at load time; the
    fallback to the generic pool below is defensive only and should be
    unreachable in practice. Gated on `kind == "added"` specifically: the
    justification is an ARRIVAL speech, not a farewell — if a `dark_web` rule
    is ever itself removed later, that removal must not repeat the same
    "here's why this showed up" text as if it explained the rule leaving.

    A `removed` change whose rule is named by an `added` rule's `supersedes`
    in this SAME batch is dropped entirely, not given the generic "that
    clause is gone" line — the arriving rule's justification already explains
    why the old one is gone, and printing a second, generic line right after
    it would read as a contradiction (bespoke reason given, then "nobody
    said why").
    """
    superseded_ids = {
        change.rule.supersedes for change in changes
        if change.kind == "added" and change.rule.supersedes
    }
    lines: list[str] = []
    for change in changes:
        if change.kind == "removed" and change.rule.id in superseded_ids:
            continue
        if (change.kind == "added" and change.rule.mutability == "dark_web"
                and change.rule.justification):
            lines.append(change.rule.justification)
            continue
        if change.kind == "severity":
            bucket = ("tightened" if change.rule.severity == "disqualifying"
                      else "relaxed")
        else:
            bucket = change.kind
        options = (_ENDLESS_RULE_CHANGE_PHRASINGS if config.is_endless_day(day_number)
                   else _RULE_CHANGE_PHRASINGS).get(bucket)
        if not options:
            continue
        pick = candidate_gen.stable_hash(change.rule.id, day_number, bucket)
        template = options[pick % len(options)]
        fragment = _rule_fragment(change.rule.text)
        if _starts_a_sentence(template):
            fragment = fragment[:1].upper() + fragment[1:]
        lines.append(template.format(rule=fragment))
    return lines
