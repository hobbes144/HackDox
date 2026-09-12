"""The picture behind the screen transitions: CRT signal-loss frames.

Drawn by `TransitionScreen` (screens/transition.py), which is pushed by
`HackDoxApp._transition` around every full-screen change. Everything here is
plain Python — no widgets, no app — so the look and the timing can be tested
directly (see tests/test_transitions.py).

## Why the effect paints whole rows

Textual's compositor is per-cell and per-screen: when ANY widget paints a
cell, that cell replaces what the screen below had there, character included.
A translucent `background:` blends colours only — it does not let text show
through, and neither does an empty container: a widget spanning the window
hides the page underneath completely, however transparent its background is.
(All four arrangements were measured; a wrapping container is exactly as
opaque as a filled one, which is why the rows are mounted directly onto the
transition screen rather than inside a field widget.)

So the overlay works in whole terminal ROWS. A row the frame covers is a
`Static` holding exactly `width` cells of noise; a row it leaves alone is
hidden outright (`visibility: hidden` — it keeps its line in the layout and
paints nothing), and the page underneath shows through there untouched.

"Intensity" is therefore just *how many rows get covered*, which is what makes
the mechanic work: at the peak every row is painted, so the screen swap
happening underneath is invisible.

## The frame

`build_frame()` is a pure function of (width, height, intensity, rng). Three
row flavours, mixed:

  tear    chunky bright blocks in runs — the torn-sync band
  static  sparse noise characters over near-black — dropout / snow
  scan    a dim rule across the row — the rolling sync line

Rows group into a few contiguous bands rather than sprinkling evenly, so the
effect reads as horizontal tearing rather than uniform confetti; loose rows
fill in as intensity climbs.
"""

from __future__ import annotations

import random
from time import monotonic

from rich.text import Text

from gameengine import config

# The two halves of a transition. "out" covers the outgoing screen and ends
# opaque (it hands over to the swap, which must not be seen); "in" clears over
# the incoming one and ends at nothing.
PHASE_OUT = "out"
PHASE_IN  = "in"

# ── Visual vocabulary ───────────────────────────────────────────────────────
# Blocks carry the tear bands (they read as solid corruption at a glance); the
# noise set is deliberately code-flavoured, so a dropout row looks like data
# rather than abstract texture.
_BLOCKS = "█▓▒░▄▀▌▐"
_NOISE  = "01#%&*+=~^:;,.?!/\\|<>∙"
_RULES  = "─═┄┈╌·"

# Palette stays inside the game's aesthetic (greens/cyans on near-black) with
# occasional crimson/violet for the RGB-split feel.
_TEAR_FG = ["#00ff9f", "#7dd3c0", "#c8d4e1", "#ff5470", "#c084fc", "#ffd93d"]
_TEAR_BG = ["#0b0e10", "#101820", "#14503a", "#1a1020", "#0f1419"]
_DIM_FG  = ["#3a4a58", "#14503a", "#1f2a33"]
_DARK_BG = ["#0b0e10", "#05070a", "#0f1419"]


def coverage_for(intensity: float) -> float:
    """Fraction of rows a frame at this intensity paints over.

    Pinned at both ends on purpose: 0 paints nothing (the page is untouched),
    and anything at or above `TRANSITION_FULL_COVER_AT` paints everything,
    because total coverage is what hides the screen swap mid-transition.
    """
    if intensity <= 0.0:
        return 0.0
    full = max(0.01, config.TRANSITION_FULL_COVER_AT)
    if intensity >= full:
        return 1.0
    # Slightly concave: coverage climbs quickly at first (the hit), and the
    # last rows of show-through survive until the peak.
    return min(1.0, (intensity / full) ** 0.8)


def _row_kinds(height: int, intensity: float,
               rng: random.Random) -> dict[int, str]:
    """Which rows are covered, and with what. A row absent = show-through."""
    if height <= 0:
        return {}
    target = int(round(height * coverage_for(intensity)))
    if target <= 0:
        return {}
    kinds: dict[int, str] = {}

    # Bands first — contiguous runs, so the eye reads horizontal tearing.
    bands = 1 + int(round(intensity * max(0, config.TRANSITION_MAX_BANDS - 1)))
    thick_max = 1 + int(intensity * 3)
    for _ in range(bands):
        if len(kinds) >= target:
            break
        top  = rng.randrange(height)
        kind = "tear" if rng.random() < 0.45 + 0.25 * intensity else "static"
        for y in range(top, min(height, top + rng.randint(1, thick_max))):
            kinds[y] = kind

    # Then fill to the coverage target with loose rows, so the page behind
    # dissolves progressively instead of all at once.
    loose = [y for y in range(height) if y not in kinds]
    rng.shuffle(loose)
    for y in loose:
        if len(kinds) >= target:
            break
        kinds[y] = "static" if rng.random() < 0.45 else "scan"
    return kinds


def _tear_row(width: int, intensity: float, rng: random.Random) -> Text:
    text = Text(no_wrap=True)
    x = 0
    while x < width:
        run = min(rng.randint(2, 14), width - x)
        if rng.random() < 0.35 + 0.45 * intensity:
            text.append(rng.choice(_BLOCKS) * run,
                        f"{rng.choice(_TEAR_FG)} on {rng.choice(_TEAR_BG)}")
        else:
            text.append(" " * run, f"on {rng.choice(_DARK_BG)}")
        x += run
    return text


def _static_row(width: int, intensity: float, rng: random.Random) -> Text:
    density = 0.10 + 0.35 * intensity
    chars = [(rng.choice(_NOISE) if rng.random() < density else " ")
             for _ in range(width)]
    # One style for the whole row keeps the segment count — and the repaint
    # cost at ~20fps — low; the texture comes from the characters.
    text = Text(no_wrap=True)
    text.append("".join(chars),
                f"{rng.choice(_DIM_FG)} on {rng.choice(_DARK_BG)}")
    return text


def _scan_row(width: int, intensity: float, rng: random.Random) -> Text:
    text = Text(no_wrap=True)
    text.append(rng.choice(_RULES) * width,
                f"{rng.choice(_DIM_FG)} on {rng.choice(_DARK_BG)}")
    return text


_BUILDERS = {"tear": _tear_row, "static": _static_row, "scan": _scan_row}


def build_frame(width: int, height: int, intensity: float,
                rng: random.Random | None = None) -> list[Text | None]:
    """One frame: a row-indexed list where None means "leave this row alone".

    Every Text returned is exactly `width` cells wide, so a covered row always
    covers the full line — partial coverage is expressed by which rows are
    covered, never by half-painted ones.
    """
    rng = rng or random.Random()
    width = max(0, width)
    if width == 0 or height <= 0:
        return [None] * max(0, height)
    intensity = max(0.0, min(1.0, intensity))
    kinds = _row_kinds(height, intensity, rng)
    frame: list[Text | None] = []
    for y in range(height):
        kind = kinds.get(y)
        if kind is None:
            frame.append(None)
            continue
        text = _BUILDERS[kind](width, intensity, rng)
        text.truncate(width, pad=True)
        frame.append(text)
    return frame


class GlitchEnvelope:
    """How hard the effect is hitting, right now — a clock, not a widget.

    The halves ramp in opposite directions and both END where the next step
    needs them: "out" finishes at 1.0, because the screen swap happens on that
    frame and must not be visible; "in" finishes at 0.0, so popping the screen
    after the last frame changes nothing on screen.
    """

    def __init__(self, phase: str = PHASE_OUT, duration: float = 0.5,
                 seed: int | None = None) -> None:
        self.phase    = phase
        self.duration = max(0.01, duration)
        self.rng      = random.Random(seed)
        self.started  = monotonic()

    def restart(self) -> None:
        """Start the ramp now. Called on mount rather than at construction:
        the screen is built a moment before it is pushed."""
        self.started = monotonic()

    def elapsed(self) -> float:
        return max(0.0, min(1.0, (monotonic() - self.started) / self.duration))

    def intensity(self) -> float:
        elapsed = self.elapsed()
        if elapsed >= 1.0:
            return 1.0 if self.phase == PHASE_OUT else 0.0
        start = config.TRANSITION_START_INTENSITY
        base  = (start + (1.0 - start) * elapsed
                 if self.phase == PHASE_OUT else 1.0 - elapsed)
        # Jitter so the ramp flickers like a failing signal rather than gliding.
        jitter = self.rng.uniform(-config.TRANSITION_JITTER,
                                  config.TRANSITION_JITTER)
        return max(0.0, min(1.0, base + jitter))

    def is_full(self, intensity: float | None = None) -> bool:
        """At full coverage there is nothing left to show through, so the
        transition screen can also paint an opaque background (see
        TransitionScreen._set_solid)."""
        value = self.intensity() if intensity is None else intensity
        return value >= config.TRANSITION_FULL_COVER_AT
