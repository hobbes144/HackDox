"""The Overseer's alignment-conditional voice, and the campaign's three
endings (issue #42, closing the gap issue #71 assumed was already filled).

Players know the Overseer as THE FOREMAN (2026-09-24, VOICE_GUIDE.md). The
module, the narrative file and every key keep the `overseer` name; only text a
player can read says Foreman.

## Alignment bands

`GameState.alignment` is a running ±10 counter (`config.ALIGNMENT_MIN`/`MAX`)
moved by `scoring.score()`: every verdict on a candidate with a nonzero
`moral_modifier` nudges it by that candidate's modifier (sign-flipped on a
DENY). In today's content that means Dark Web encounters (`moral_modifier =
-1`, repeated across most of the campaign) and the single, larger White Hat
encounter on day 12 (`moral_modifier = +4`).

Three bands map onto the three endings the Game Design doc describes
(White Hat-aligned / Dark Web-aligned / Neutral):

    alignment >= ALIGNMENT_BAND_WHITE_HAT_THRESHOLD   -> "whitehat"
    alignment <= ALIGNMENT_BAND_DARK_WEB_THRESHOLD     -> "darkweb"
    otherwise                                          -> "neutral"

The thresholds (config.py, currently ±4) are set at the White Hat's own
single-encounter magnitude: one unambiguous act of resistance (admitting the
White Hat) or complicity (denying them) is, by itself, enough to be
recognized as leaning — the design intent per the Game Design doc's "the
moral choice to deny [the Dark Web] anyway is what shifts alignment toward
White Hat" and the mirror-image statement for compliance. A player with a
genuinely mixed record (resisted the Overseer some days, complied on others,
never faced or ducked the day-12 choice decisively) stays inside the band and
lands Neutral, which is its own coherent ending, not a weaker version of the
other two. Both bands are symmetric around `STARTING_ALIGNMENT` (0) so
neither the Dark Web nor the White Hat has an easier time of it by
construction — content pacing (how many Dark Web encounters exist, and where)
is what actually tunes difficulty, not the threshold.

## Alignment-banded narrative keys

`content_loader.resolve_narrative`'s fallback chain is `day key -> generic
key -> hard-coded last resort`. `resolve_aligned_narrative` below inserts one
more tier ABOVE both of those, so Overseer dialogue can react to how the
player is playing without every day needing three full authored variants:

    day+band key   ->   day key   ->   generic+band key   ->   generic key
                                                                -> hard-coded
                                                                   last resort

A "banded" key is the plain key with the band token spliced in right after
the `dayN` or `generic` prefix:

    day14_intro            -> day14_whitehat_intro / day14_neutral_intro / day14_darkweb_intro
    day14_outro_excellent  -> day14_whitehat_outro_excellent / ...
    day14_between          -> day14_whitehat_between / ...
    generic_intro          -> generic_whitehat_intro / generic_neutral_intro / generic_darkweb_intro
    generic_outro_poor     -> generic_whitehat_outro_poor / ...
    generic_between        -> generic_whitehat_between / ...

Authoring a band-specific key is entirely optional, one key at a time. A day
that authors nothing but `day14_intro` behaves exactly as it did before this
module existed (band keys are absent, so the chain falls straight through to
the plain day key) — this backward compatibility is load-bearing for days
1-12 and is covered explicitly by
`test_alignment_band_keys_dont_change_days_1_through_12`.

## Campaign endings

`ending_for_state` maps a final `GameState` to one of `ENDINGS`
(`Ending.band` in `{"whitehat", "neutral", "darkweb"}`), each carrying a
title and a short authored epilogue. `ui/tui/screens/campaign_end.py` renders
whichever `Ending` this returns; the selection logic lives here, not in the
Textual screen, so it can be exercised by a plain unit test with a synthetic
`GameState` and no Textual app running.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .. import config
from .content_loader import resolve_narrative
from .models import GameState

# ─── Alignment bands ─────────────────────────────────────────────────────────

BAND_WHITE_HAT = "whitehat"
BAND_NEUTRAL   = "neutral"
BAND_DARK_WEB  = "darkweb"


def alignment_band(alignment: int) -> str:
    """Classify a raw `GameState.alignment` value into one of three bands.

    Boundary values (exactly at a threshold) count as leaning, not neutral —
    `>=`/`<=`, not `>`/`<` — so a player who lands precisely on the White
    Hat's single-encounter magnitude is recognized rather than needing one
    more nudge past it.
    """
    if alignment >= config.ALIGNMENT_BAND_WHITE_HAT_THRESHOLD:
        return BAND_WHITE_HAT
    if alignment <= config.ALIGNMENT_BAND_DARK_WEB_THRESHOLD:
        return BAND_DARK_WEB
    return BAND_NEUTRAL


# ─── Alignment-banded narrative resolution ──────────────────────────────────

# Matches the two key shapes content_loader's callers ever construct:
# "day<N>_<rest>" or "generic_<rest>". The band token is spliced in right
# after this prefix — see the module docstring for worked examples.
_KEY_PREFIX = re.compile(r"^(day\d+|generic)_(.+)$")


def banded_key(key: str, band: str) -> str:
    """Splice an alignment band into a narrative key.

    Raises rather than silently returning `key` unchanged if `key` doesn't
    match the `day<N>_...` / `generic_...` convention every call site in
    `app.py` uses — the same fail-loud stance `content_loader._parse_rule`
    takes on a typo'd mutability: a key this can't band is a programmer
    error at the call site, not a content-authoring gap.
    """
    match = _KEY_PREFIX.match(key)
    if not match:
        raise ValueError(
            f"overseer.banded_key: {key!r} doesn't match the day<N>_... / "
            f"generic_... narrative-key convention — cannot derive a "
            f"{band!r}-band variant of it")
    prefix, rest = match.groups()
    return f"{prefix}_{band}_{rest}"


def resolve_aligned_narrative(
    narratives: dict[str, str],
    alignment: int,
    day_key: str,
    generic_key: str,
) -> str:
    """`content_loader.resolve_narrative`, with an alignment-band tier.

    Fallback chain: day+band key -> day key -> generic+band key -> generic
    key -> hard-coded last resort. The final two steps are delegated to
    `resolve_narrative` itself (rather than duplicated here) so the
    hard-coded copy in `content_loader._LAST_RESORT` stays the one place
    that text lives.

    Empty authored strings fall through, same as `resolve_narrative` — an
    author blanking a band-specific key means "not written for this band
    yet", not "the Overseer says nothing in this band".
    """
    band = alignment_band(alignment)
    band_day_key = banded_key(day_key, band)
    band_generic_key = banded_key(generic_key, band)
    return (
        narratives.get(band_day_key)
        or narratives.get(day_key)
        or narratives.get(band_generic_key)
        or resolve_narrative(narratives, generic_key, generic_key)
    )


# ─── Campaign endings ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Ending:
    band: str
    title: str
    paragraphs: tuple[str, ...]


ENDINGS: dict[str, Ending] = {
    BAND_DARK_WEB: Ending(
        band=BAND_DARK_WEB,
        title="FULL ACCESS GRANTED",
        paragraphs=(
            "You stopped pretending, somewhere in the middle of the "
            "campaign, that you didn't know who came in on the late boat. "
            "The line told you everything you needed — the wrong domain "
            "waved through, the flippant line in the chat window you let "
            "slide because arguing with the Foreman cost more than it was "
            "worth. Nobody made you look away. You just got good at it.",

            "HackDox doesn't fail. It gets faster. The names that used to "
            "trip your review sail through now on the strength of rules "
            "you helped keep soft, and nobody upstairs has to ask you to "
            "bend them anymore — you already know which way they bend. "
            "The first internet security service on Earth spends its days "
            "waving smugglers through the gate it was built to hold, and "
            "the tally balances every night, because you're the one "
            "closing it.",

            "The Foreman doesn't threaten you anymore. There's nothing "
            "left to threaten. Some mornings you still tell yourself it "
            "was just the job, that the rules said admit and you admitted, "
            "that the one name you turned back doesn't undo the rest. You "
            "might even believe it. The lights on your terminal stopped "
            "turning red months ago. Nobody on the pier is watching for it "
            "anymore — least of all you.",
        ),
    ),
    BAND_NEUTRAL: Ending(
        band=BAND_NEUTRAL,
        title="THE LEDGER CLOSES",
        paragraphs=(
            "You read the book every morning and worked it to the letter, "
            "and when the letter and your gut disagreed, the letter won, "
            "because that was the job you were hired to do. Twenty shifts. "
            "Twenty rulebooks, some of them quietly rewritten out from "
            "under you between one tide and the next, and you never "
            "once asked out loud who kept moving the walls.",

            "History will record that HackDox's manual review held the "
            "line it was given, no more and no less. Somewhere in the "
            "names you cleared, exactly as written, were people the rules "
            "were never meant to protect — and somewhere in the names you "
            "turned back were people the rules were never meant to catch. "
            "You couldn't have told you which was which. That was rather "
            "the point of having rules.",

            "The Foreman signs off your last shift without much to say, "
            "which is its own kind of answer. You did the job. The terminal "
            "is still standing, technically, the way a pier is still "
            "standing after every ship that mattered has quietly stopped "
            "calling at it. Nobody blames you for that. Nobody thanks you "
            "for it either. You followed every rule they gave you, and you "
            "never once asked whose rules they actually were.",
        ),
    ),
    BAND_WHITE_HAT: Ending(
        band=BAND_WHITE_HAT,
        title="THE SIGNAL HOLDS",
        paragraphs=(
            "You saw them before you were supposed to — a name at the gate "
            "with nothing wrong on paper and everything wrong underneath, "
            "working just hard enough at hiding to prove they knew exactly "
            "what they were hiding from. The book said deny. You'd stopped "
            "trusting the book months before that morning, and you "
            "admitted them anyway, and put your name under it like you "
            "meant it. Because you did.",

            "It cost you. The Foreman stopped being warm around the time "
            "you started asking questions she didn't have good answers for, "
            "and she never quite forgave you for finding the one candidate "
            "she needed you not to find. But the access you granted that "
            "morning didn't sit idle at the berth — somewhere past your "
            "line, past your shift, past the point where you could see what "
            "happened next, a name you vouched for went to work undoing the "
            "thing the Foreman had been paid to protect.",

            "HackDox doesn't get fixed in a day, and it doesn't get fixed "
            "by one gatekeeper refusing to look away. But it stops being "
            "uncontested. Somewhere in the traffic you can't see anymore, "
            "the people who built this rot into the foundation are running "
            "out of names they can trust — and one of the ones they can't "
            "trust anymore is a signature you put on a denial they never "
            "expected to see reversed. You didn't save it. You gave it a "
            "chance.",
        ),
    ),
}


def ending_for_alignment(alignment: int) -> Ending:
    return ENDINGS[alignment_band(alignment)]


def ending_for_state(state: GameState) -> Ending:
    """The campaign ending for a final `GameState` (issue #42).

    Pure function of `state.alignment` — kept separate from
    `ending_for_alignment` only so call sites can pass the whole state
    without reaching into it themselves, and so a future ending-selection
    factor beyond alignment has somewhere natural to be added.
    """
    return ending_for_alignment(state.alignment)
