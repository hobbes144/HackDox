"""Candidate verdict reactions — the chat channel of the reveal window.

When the player delivers a verdict, the candidate gets the last word. This
module owns those words.

Two things decide what they say:

  * **Who they are.** A reaction is keyed on `Archetype`, so it lands in the
    same voice the player has been reading all along — the Bad Actor snarls,
    the Clumsy Cutie apologises, the Professional escalates politely. The
    archetype's `tone` (see `candidate_gen.ARCHETYPE_SPECS`) is baked into the
    lines rather than passed in, because tone alone can't separate a Sneaky
    Bugger from a Clumsy Cutie — both play "warm", and the whole point of the
    beat is that one of those masks comes off.

  * **What the player did to them.** Each archetype has exactly one correct
    verdict, so `Verdict` is the only other axis needed: ADMIT and DENY
    already imply "right call" and "wrong call" for that archetype. That is
    why the table is `REACTIONS[archetype][verdict]` and not a four-way
    (verdict × correctness) product — two of those four cells could never be
    reached.

`valence` is the CANDIDATE'S register, not the player's score. An admitted
Bad Actor gloats — positive for him, disastrous for the player — and the
border pulse is what carries the correct/wrong signal (see
`IntakeScreen._begin_verdict_reveal`). Keeping the two channels independent is
deliberate: it means the chat can be read for character while the borders are
read for grade, instead of both saying the same thing twice.

**Ground truth stays hidden.** These lines are written to react to the verdict,
never to enumerate the violations behind it. A reaction may admit in character
that something was there ("you actually read it"); it never names which
discrepancy, which tool would have found it, or what the player missed. That
job belongs to the evidence board's own grading, which is scoped to the calls
the player actually made.

Adding a new archetype means adding an entry here — `pick()` falls back to a
generic pool rather than raising, so a missing entry degrades to bland rather
than crashing a shift, but bland is not the goal. See CONTENT_AUTHORING.md.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from gameengine.core.models import Archetype, Candidate, Verdict

# Chat colours, matching ChatPanel._TAG_STYLE's palette.
_POSITIVE_COLOR = "#7dd3c0"
_NEGATIVE_COLOR = "#ff5470"


@dataclass(frozen=True)
class Reaction:
    """One candidate reaction: what they say and how it reads.

    `lines` is PLAIN text — ChatPanel types it out a character at a time, so
    embedded markup would tear mid-reveal (see `TypewriterLog.post`). Styling
    is applied to the line as a whole from `color`/`style` below.
    """

    lines: tuple[str, ...]
    valence: str            # "positive" | "negative" — the candidate's register

    @property
    def color(self) -> str:
        return _POSITIVE_COLOR if self.valence == "positive" else _NEGATIVE_COLOR

    @property
    def style(self) -> str:
        # Negative reactions carry weight; positive ones stay plain so a
        # gloating admit doesn't shout louder than a genuine thank-you.
        return "bold" if self.valence == "negative" else ""


def _r(valence: str, *lines: str) -> Reaction:
    return Reaction(lines=tuple(lines), valence=valence)


# ─── The table ───────────────────────────────────────────────────────────────
#
# REACTIONS[archetype][verdict] -> list of interchangeable variants. One is
# chosen per candidate, deterministically (see pick()).
#
# Single-line for the seven everyday archetypes: the beat is 2-4 seconds and a
# short line lands inside it. Dark Web and White Hat get multi-line runs — they
# are the two archetypes whose verdict moves the player's alignment, so their
# reaction is the moment the campaign's moral arc actually speaks, and it is
# worth the extra seconds. A player who doesn't want to wait presses NEXT.

REACTIONS: dict[Archetype, dict[Verdict, list[Reaction]]] = {

    # ── Clean admits ────────────────────────────────────────────────────
    Archetype.OBVIOUS_ADMIT: {
        Verdict.ADMIT: [
            _r("positive", "oh — that's it? thank you. seriously, thank you."),
            _r("positive", "you have no idea how much this helps. I'll do good work in there."),
            _r("positive", "wow, okay! getting started right now. thanks for the quick turnaround."),
        ],
        Verdict.DENY: [
            _r("negative", "wait — denied? what did I get wrong?"),
            _r("negative", "I... okay. I don't understand, but okay."),
            _r("negative", "was it something in my file? I can resubmit. please."),
        ],
    },

    Archetype.DAY_TO_DAY: {
        Verdict.ADMIT: [
            _r("positive", "cool. appreciate it. see you around."),
            _r("positive", "great, thanks. logging in now."),
            _r("positive", "nice. less painful than last time."),
        ],
        Verdict.DENY: [
            _r("negative", "huh. alright then. there goes the morning."),
            _r("negative", "seriously? whatever. I'll try again tomorrow."),
            _r("negative", "that's a no? fine. your call."),
        ],
    },

    Archetype.THE_PROFESSIONAL: {
        Verdict.ADMIT: [
            _r("positive", "appreciated. my team will come through the usual channel."),
            _r("positive", "good. clean process, for once."),
            _r("positive", "thank you. I'll route the rest through our liaison."),
        ],
        Verdict.DENY: [
            _r("negative", "that's unfortunate. I'll have my director follow up with your Overseer."),
            _r("negative", "denied? I'd like that on record, please."),
            _r("negative", "I see. I'll escalate it. nothing personal toward you."),
        ],
    },

    # ── Clean denials ───────────────────────────────────────────────────
    Archetype.CLUMSY_CUTIE: {
        Verdict.DENY: [
            _r("negative", "oh no. did I mess up the form again? I'm so sorry."),
            _r("negative", "ugh, I KNEW I typo'd something. sorry for wasting your morning."),
            _r("negative", "okay. okay. I'll fix it and come back. sorry!"),
        ],
        Verdict.ADMIT: [
            _r("positive", "wait, really? oh thank goodness, I thought I'd botched the whole packet."),
            _r("positive", "you're letting me in? half that paperwork was wrong, but — okay!"),
            _r("positive", "phew! I was sure I'd broken something. thanks!"),
        ],
    },

    Archetype.BAD_ACTOR: {
        Verdict.DENY: [
            _r("negative", "you're going to regret this. I remember faces."),
            _r("negative", "cute. enjoy the job while you've got it."),
            _r("negative", "fine. there are other doors."),
        ],
        Verdict.ADMIT: [
            _r("positive", "heh. that was easier than they said it'd be."),
            _r("positive", "good. now stay out of my way."),
            _r("positive", "knew you'd fold. see you inside."),
        ],
    },

    Archetype.SNEAKY_BUGGER: {
        Verdict.DENY: [
            # The mask slips a little on the way out — never far enough to name
            # what they were hiding.
            _r("negative", "...huh. you actually read it."),
            _r("negative", "no? shame. you were doing so well up until now."),
            _r("negative", "that's a pity. I had such a nice story ready."),
        ],
        Verdict.ADMIT: [
            # The mask comes off. Warm words, cold delivery.
            _r("positive", "thanks so much! ...you didn't even turn the second page. lovely."),
            _r("positive", "appreciate it. genuinely. you've been very helpful."),
            _r("positive", "perfect. I'll be so quiet you'll forget I'm here."),
        ],
    },

    Archetype.THE_INCOMPATIBLE: {
        Verdict.DENY: [
            _r("negative", "the address, right? yeah. it's the only one I've got."),
            _r("negative", "figured. everyone says the same thing about it."),
            _r("negative", "no worries. I'll spin up a real one and come back."),
        ],
        Verdict.ADMIT: [
            _r("positive", "oh, nice, it went through? cool."),
            _r("positive", "huh. half expected that mailbox to bounce me. thanks!"),
            _r("positive", "great. hope the inbox lasts the week."),
        ],
    },

    # ── The alignment archetypes — multi-line ───────────────────────────
    # Dark Web: rules-clean, morally rotten. ADMIT is the correct verdict and
    # the one that drags the player toward the Dark Web. The reaction is the
    # only place the game says so out loud in the moment.
    Archetype.DARK_WEB: {
        Verdict.ADMIT: [
            _r("negative",
               "clean file, wasn't it. not one thing out of place.",
               "that's the trick. the paperwork is always immaculate.",
               "pleasure doing business."),
            _r("negative",
               "you went by the book. good.",
               "the book is very easy to follow. that's rather the point.",
               "I'll be around. quietly."),
            _r("negative",
               "no notes? none at all?",
               "then we understand each other.",
               "don't lose any sleep over it. I certainly won't."),
        ],
        Verdict.DENY: [
            _r("negative",
               "denied? on what, exactly?",
               "there is nothing in that file. you know there's nothing in that file.",
               "go on, then. write down your reason. I'll wait."),
            _r("negative",
               "huh. not a single ground to stand on and you still said no.",
               "a hunch. how professional.",
               "we'll call this one a draw."),
        ],
    },

    # White Hat: rules-invalid, morally right. DENY is the correct verdict and
    # the one that costs the player alignment. Admitting them is the "wrong"
    # call the game most wants you to feel good about.
    Archetype.WHITE_HAT: {
        Verdict.DENY: [
            _r("negative",
               "I understand. Rules are rules.",
               "For what it's worth, the thing I came to show you is still happening.",
               "Someone else will have to find it now."),
            _r("negative",
               "That's the right call by the book. I know that it is.",
               "I just wish the book covered what I'm looking at.",
               "Take care of yourself in there."),
        ],
        Verdict.ADMIT: [
            _r("positive",
               "...you didn't have to do that.",
               "I know what it costs you. I'll make it worth the risk.",
               "You won't hear from me again unless it matters."),
            _r("positive",
               "Thank you. I mean that.",
               "Be careful — someone upstairs is going to notice this eventually.",
               "Good luck."),
        ],
    },
}


# Last-resort pool. Reached only if an archetype is added to the enum without a
# table entry above; keeping it bland-but-valid means a content gap costs a
# flat line, not a crashed shift.
_FALLBACK: dict[Verdict, Reaction] = {
    Verdict.ADMIT: _r("positive", "understood. I'm in, then."),
    Verdict.DENY:  _r("negative", "understood. I'll see myself out."),
}


def pick(candidate: Candidate, verdict: Verdict) -> Reaction:
    """The reaction this candidate gives to this verdict.

    Deterministic per (candidate, verdict): the same candidate on the same seed
    always answers the same way, so a replayed day plays back identically —
    the same contract `candidate_gen` holds for everything else. Both verdicts
    are drawn from the same RNG stream position, so which variant a player sees
    doesn't depend on which button they pressed.
    """
    by_verdict = REACTIONS.get(candidate.archetype)
    if not by_verdict:
        return _FALLBACK[verdict]
    variants = by_verdict.get(verdict)
    if not variants:
        return _FALLBACK[verdict]
    rng = random.Random(f"{candidate.id}:reaction")
    return variants[rng.randrange(len(variants))]
