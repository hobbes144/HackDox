"""Overseer narration helpers."""

from __future__ import annotations

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


# Placeholder Overseer unlock narration, one line per tool (#34). PLACEHOLDER —
# the final, day-by-day wording is authored with the tutorial script (#15); this
# is a stand-in so the mechanism (and its teaching order) is in place now. The
# `triggers` payload on this line is the tool value string, which the briefing's
# Finished handler uses to flip GameState.unlocked_tools.
_UNLOCK_LINES: dict[str, str] = {
    "ghostscan": "New capability authorized: GHOSTSCAN. Public traces don't lie the way people do.",
    "hashcrack": "New capability authorized: HASHCRACK. If they reused a breached password, we'll see it.",
    "logwatch":  "New capability authorized: LOGWATCH. The logs remember every step they took.",
    "stegotool": "New capability authorized: STEGOTOOL. They hide payloads in plain sight now. Look closer.",
}


# ─── Overseer-Variable rule broadcast (#36) ─────────────────────────────────
#
# The Overseer mentions rule changes in passing. The design is explicit that a
# small change should read as a minor process update, not a klaxon — so these
# are deliberately understated, hedged, and a little bored. Several openers per
# change kind so a two-change morning doesn't read as a filled-in template.
#
# {rule} is the rule's own text, lower-cased at the first character and
# stripped of its trailing period so it sits inside a sentence.
_RULE_CHANGE_PHRASINGS: dict[str, tuple[str, ...]] = {
    # A rule got teeth: advisory → disqualifying.
    "tightened": (
        ("Oh — one thing before you start. That guidance about {rule}? Policy "
        "now. Not a suggestion. Don't make me explain it twice."),
        ("Small note. {rule} — that's a hard deny from today. Compliance "
        "wanted it in writing, so now it's in writing."),
        ("Quick amendment: {rule}. It used to be your judgement. It isn't "
        "anymore."),
    ),
    # A rule lost its teeth: disqualifying → advisory.
    "relaxed": (
        ("Before I forget — {rule}. That's a note now, not a bar. Flag it, "
        "wave them through. Don't overthink it."),
        ("Legal's been busy. {rule} is advisory from this morning. Use your "
        "judgement, which I'm told you have."),
        ("Minor thing. {rule} — we're not denying on that on its own anymore. "
        "Log it and move on."),
    ),
    "added": (
        "New line in the book today: {rule}. Read it properly at some point.",
        "They've added one. {rule}. I didn't write it, I just pass it along.",
    ),
    "removed": (
        ("That clause about {rule} is gone as of this morning. Don't ask me "
        "why; I stopped asking."),
        "We've dropped the line about {rule}. Nobody's said why.",
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
    """One casual Overseer line per changed Overseer-Variable rule (#36).

    Deterministic in the day number and the rule id, so replaying a day
    reproduces the same briefing rather than re-rolling the Overseer's phrasing.
    """
    lines: list[str] = []
    for change in changes:
        if change.kind == "severity":
            bucket = ("tightened" if change.rule.severity == "disqualifying"
                      else "relaxed")
        else:
            bucket = change.kind
        options = _RULE_CHANGE_PHRASINGS.get(bucket)
        if not options:
            continue
        pick = candidate_gen.stable_hash(change.rule.id, day_number, bucket)
        template = options[pick % len(options)]
        fragment = _rule_fragment(change.rule.text)
        if _starts_a_sentence(template):
            fragment = fragment[:1].upper() + fragment[1:]
        lines.append(template.format(rule=fragment))
    return lines
