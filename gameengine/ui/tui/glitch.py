"""CRT signal-loss frames — the picture behind both glitch effects.

Two features draw from this module:

  * **Screen transitions** — `TransitionScreen` (screens/transition.py),
    pushed by `HackDoxApp._transition` around every full-screen change.
  * **The damage glitch** — `IntakeScreen._begin_damage_glitch`, fired in
    place over the live page after an admit that costs Site Health, scaled by
    how much it cost.

The frame builder and the envelopes are plain Python — no widgets, no app —
so the look and the timing can be tested directly (tests/test_transitions.py,
tests/test_damage_glitch.py). `RowPainter` is the one piece that touches
widgets, and it exists because of the compositor rule below.

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

## Envelopes

`GlitchEnvelope` drives a transition half (ramp up, or decay to clear);
`BurstEnvelope` drives the damage glitch (hit hard, decay, with a stutter
re-hit on the heavier ones). Both are clocks: they answer "how hard is this
hitting right now", and the caller turns that into a frame.

## Colour

The default palette is the game's own (greens/cyans on near-black, with
crimson/violet for the RGB-split feel). The damage glitch overrides it with a
`Palette` biased toward the admitted archetype's colour — red for the Bad
Actor, violet for the Incompatible, and so on — so the burst says WHO got in
as well as how badly. The bias is partial on purpose: a solid wash of one hue
stops reading as a broken signal and starts reading as a coloured rectangle.

## The frame

`build_frame()` is a pure function of (width, height, intensity, rng, palette).
Three row flavours, mixed:

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
from textual.widgets import Static

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

_VOID = "#05070a"      # the darkest thing on screen; what a tint fades into


class Palette:
    """The colours one frame draws from.

    Four lists, one per role, each sampled with `rng.choice` — so biasing a
    palette toward a hue is just a matter of how many entries of that hue are
    in the list, not of special-casing the builders.
    """

    __slots__ = ("tear_fg", "tear_bg", "dim_fg", "dark_bg", "tint")

    def __init__(self, tear_fg, tear_bg, dim_fg, dark_bg, tint=None) -> None:
        self.tear_fg = list(tear_fg)
        self.tear_bg = list(tear_bg)
        self.dim_fg  = list(dim_fg)
        self.dark_bg = list(dark_bg)
        self.tint    = tint          # the hue this palette leans on, if any


DEFAULT_PALETTE = Palette(_TEAR_FG, _TEAR_BG, _DIM_FG, _DARK_BG)


def _mix(color: str, other: str, amount: float) -> str:
    """Blend two #rrggbb colours. amount=0 keeps `color`, 1 gives `other`."""
    amount = max(0.0, min(1.0, amount))
    a = color.lstrip("#")
    b = other.lstrip("#")
    parts = []
    for i in (0, 2, 4):
        ca, cb = int(a[i:i + 2], 16), int(b[i:i + 2], 16)
        parts.append(round(ca + (cb - ca) * amount))
    return "#{:02x}{:02x}{:02x}".format(*parts)


def _biased(tint_family: list[str], neutrals: list[str], bias: float) -> list[str]:
    """A choice list where roughly `bias` of the entries are the tint.

    Expressed as duplicate entries rather than a weighted draw so the builders
    keep using plain `rng.choice` and the bias is visible in the data.
    """
    bias = max(0.0, min(1.0, bias))
    if bias >= 1.0:
        return list(tint_family)
    if bias <= 0.0:
        return list(neutrals)
    wanted = max(1, round(len(neutrals) * bias / (1.0 - bias)))
    out: list[str] = []
    while len(out) < wanted:
        out.extend(tint_family)
    return out[:wanted] + list(neutrals)


def tinted_palette(tint: str, bias: float | None = None) -> Palette:
    """A palette leaning on one hue, for the damage glitch.

    The tint appears as itself plus a lit and a sunk variant, so a band still
    has internal contrast and the noise still looks like noise. `bias` is how
    much of the palette the hue takes over — the neutrals that remain are what
    keep it reading as a broken signal rather than a coloured overlay.
    """
    if bias is None:
        bias = config.DAMAGE_GLITCH_TINT_BIAS
    family = [tint, _mix(tint, "#ffffff", 0.35), _mix(tint, _VOID, 0.45)]
    return Palette(
        tear_fg=_biased(family, _TEAR_FG, bias),
        # Backgrounds only ever get a whisper of it: a saturated background
        # behind a block character is a filled rectangle, not a glitch.
        tear_bg=_biased([_mix(tint, _VOID, 0.86), _mix(tint, _VOID, 0.92)],
                        _TEAR_BG, bias),
        # The dim family is what most of a frame is actually made of (the
        # sparse noise and scan rows), so it carries the hue's read at a
        # glance — kept just bright enough to be recognisably coloured while
        # still sitting in the same register as the house dim tones.
        dim_fg=_biased([_mix(tint, _VOID, 0.48), _mix(tint, _VOID, 0.64)],
                       _DIM_FG, bias),
        dark_bg=_biased([_mix(tint, _VOID, 0.93)], _DARK_BG, bias),
        tint=tint,
    )


def tint_for_archetype(archetype) -> str:
    """The colour an archetype's damage burst leans on.

    Falls back to the shared default rather than raising: a new archetype
    should glitch in the house colour, not crash the verdict path.
    """
    key = getattr(archetype, "value", archetype)
    return config.ARCHETYPE_GLITCH_TINT.get(key, config.DAMAGE_GLITCH_TINT_DEFAULT)


def palette_for_archetype(archetype) -> Palette:
    return tinted_palette(tint_for_archetype(archetype))


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


def _tear_row(width: int, intensity: float, rng: random.Random,
              palette: Palette) -> Text:
    text = Text(no_wrap=True)
    x = 0
    while x < width:
        run = min(rng.randint(2, 14), width - x)
        if rng.random() < 0.35 + 0.45 * intensity:
            text.append(rng.choice(_BLOCKS) * run,
                        f"{rng.choice(palette.tear_fg)} on "
                        f"{rng.choice(palette.tear_bg)}")
        else:
            text.append(" " * run, f"on {rng.choice(palette.dark_bg)}")
        x += run
    return text


def _static_row(width: int, intensity: float, rng: random.Random,
                palette: Palette) -> Text:
    density = 0.10 + 0.35 * intensity
    chars = [(rng.choice(_NOISE) if rng.random() < density else " ")
             for _ in range(width)]
    # One style for the whole row keeps the segment count — and the repaint
    # cost at ~20fps — low; the texture comes from the characters.
    text = Text(no_wrap=True)
    text.append("".join(chars),
                f"{rng.choice(palette.dim_fg)} on {rng.choice(palette.dark_bg)}")
    return text


def _scan_row(width: int, intensity: float, rng: random.Random,
              palette: Palette) -> Text:
    text = Text(no_wrap=True)
    text.append(rng.choice(_RULES) * width,
                f"{rng.choice(palette.dim_fg)} on {rng.choice(palette.dark_bg)}")
    return text


_BUILDERS = {"tear": _tear_row, "static": _static_row, "scan": _scan_row}


def build_frame(width: int, height: int, intensity: float,
                rng: random.Random | None = None,
                palette: Palette | None = None) -> list[Text | None]:
    """One frame: a row-indexed list where None means "leave this row alone".

    Every Text returned is exactly `width` cells wide, so a covered row always
    covers the full line — partial coverage is expressed by which rows are
    covered, never by half-painted ones.

    `palette` defaults to the house colours; the damage glitch passes one
    biased toward the admitted archetype (see `palette_for_archetype`).
    """
    rng = rng or random.Random()
    palette = palette or DEFAULT_PALETTE
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
        text = _BUILDERS[kind](width, intensity, rng, palette)
        text.truncate(width, pad=True)
        frame.append(text)
    return frame


class _Clock:
    """Shared base for the envelopes: 0→1 progress over a duration, plus the
    rng the frames are drawn with (one stream per effect, so two overlapping
    effects never draw the same noise)."""

    def __init__(self, duration: float = 0.5, seed: int | None = None) -> None:
        self.duration = max(0.01, duration)
        self.rng      = random.Random(seed)
        self.started  = monotonic()

    def restart(self) -> None:
        """Start the clock now. Called on mount rather than at construction:
        a screen is built a moment before it is pushed."""
        self.started = monotonic()

    def elapsed(self) -> float:
        return max(0.0, min(1.0, (monotonic() - self.started) / self.duration))

    def _jitter(self) -> float:
        """Flicker, so a ramp reads as a failing signal rather than a glide."""
        return self.rng.uniform(-config.TRANSITION_JITTER,
                                config.TRANSITION_JITTER)


class GlitchEnvelope(_Clock):
    """A transition half.

    The halves ramp in opposite directions and both END where the next step
    needs them: "out" finishes at 1.0, because the screen swap happens on that
    frame and must not be visible; "in" finishes at 0.0, so popping the screen
    after the last frame changes nothing on screen.
    """

    def __init__(self, phase: str = PHASE_OUT, duration: float = 0.5,
                 seed: int | None = None) -> None:
        super().__init__(duration, seed)
        self.phase = phase

    def intensity(self) -> float:
        elapsed = self.elapsed()
        if elapsed >= 1.0:
            return 1.0 if self.phase == PHASE_OUT else 0.0
        start = config.TRANSITION_START_INTENSITY
        base  = (start + (1.0 - start) * elapsed
                 if self.phase == PHASE_OUT else 1.0 - elapsed)
        return max(0.0, min(1.0, base + self._jitter()))

    def is_full(self, intensity: float | None = None) -> bool:
        """At full coverage there is nothing left to show through, so the
        transition screen can also paint an opaque background (see
        TransitionScreen._set_solid)."""
        value = self.intensity() if intensity is None else intensity
        return value >= config.TRANSITION_FULL_COVER_AT


class BurstEnvelope(_Clock):
    """The damage glitch: hits at once, then falls apart.

    Front-loaded on purpose — the player has just pressed ADMIT, and the
    effect is the consequence arriving, so there is no ramp-in to sit through.
    Heavier hits stutter: a short second spike partway down, which reads as
    the site failing to recover rather than one clean fade.
    """

    def __init__(self, peak: float, duration: float,
                 seed: int | None = None) -> None:
        super().__init__(duration, seed)
        self.peak = max(0.0, min(1.0, peak))

    def intensity(self) -> float:
        elapsed = self.elapsed()
        if elapsed >= 1.0:
            return 0.0
        value = self.peak * (1.0 - elapsed) ** 1.4
        if (self.peak >= config.DAMAGE_GLITCH_RE_HIT_ABOVE
                and 0.48 <= elapsed <= 0.60):
            value = self.peak * 0.85          # the stutter
        return max(0.0, min(1.0, value + self._jitter()))


def worst_health_hit() -> float:
    """The largest Site Health penalty any archetype can inflict.

    Read from `config.ARCHETYPE_HEALTH_WEIGHTS` rather than hard-coded, so
    retuning the table retunes the glitch with it — and so the scale is
    always relative to the worst thing in the game, not to an absolute number
    that a rebalance would quietly invalidate.
    """
    penalties = [abs(w) for w in config.ARCHETYPE_HEALTH_WEIGHTS.values() if w < 0]
    return max(penalties) if penalties else 0.0


def burst_shape(health_delta: float) -> tuple[float, float]:
    """(peak intensity, duration) for an admit that cost this much health.

    A non-damaging verdict returns (0, 0) — nothing to show. Otherwise the hit
    is scaled against the worst archetype in the table and bent by
    DAMAGE_GLITCH_CURVE, which keeps the small hits genuinely subtle instead of
    landing halfway up the scale: a throwaway-email Incompatible (−2) tears a
    few rows for a third of a second, a Sneaky Bugger (−12) briefly swallows
    the screen.
    """
    if health_delta >= 0:
        return 0.0, 0.0
    worst = worst_health_hit()
    severity = min(1.0, abs(health_delta) / worst) if worst else 1.0
    shaped   = severity ** config.DAMAGE_GLITCH_CURVE
    peak = (config.DAMAGE_GLITCH_MIN_PEAK
            + (config.DAMAGE_GLITCH_MAX_PEAK - config.DAMAGE_GLITCH_MIN_PEAK) * shaped)
    duration = (config.DAMAGE_GLITCH_MIN_DURATION
                + (config.DAMAGE_GLITCH_MAX_DURATION
                   - config.DAMAGE_GLITCH_MIN_DURATION) * severity)
    # Clamped rather than returned raw: float arithmetic lands the worst hit a
    # hair over the configured ceiling (0.9000000000000001), and the ceiling is
    # the value a caller tunes against.
    return (min(config.DAMAGE_GLITCH_MAX_PEAK, peak),
            min(config.DAMAGE_GLITCH_MAX_DURATION, duration))


class RowPainter:
    """One `Static` per terminal row on a host screen — the overlay itself.

    This is the compositor rule from the module docstring made concrete, and
    it is shared by both effects so the rule lives in one place. A row the
    frame covers carries `width` cells of noise; a row it leaves alone is
    hidden (`.off` → `visibility: hidden`), which is the ONLY way the page
    underneath shows through.

    The rows must be children of the host SCREEN, not of a container inside
    it — an empty container paints its whole region and would hide everything.
    For the in-place damage glitch they also sit on their own CSS layer, so
    mounting them cannot disturb the layout of the page they cover.
    """

    def __init__(self, host, classes: str = "glitch-row") -> None:
        self.host    = host
        self.classes = classes
        self.rows: list = []
        self._on: list[bool] = []

    @property
    def height(self) -> int:
        return len(self.rows)

    def build(self, height: int, frame: list | None = None) -> list:
        """Create rows WITHOUT mounting them — for a host's `compose()`.

        Pre-painted when a frame is given, because the compositor can paint a
        screen before any timer has run and an unpainted first frame is a
        visible hole in the effect.
        """
        self.rows, self._on = [], []
        for i in range(max(0, height)):
            text = frame[i] if frame is not None and i < len(frame) else None
            covered = text is not None
            self.rows.append(Static(
                text if covered else "",
                classes=self.classes if covered else f"{self.classes} off"))
            self._on.append(covered)
        return self.rows

    def mount(self, height: int, frame: list | None = None) -> None:
        """Create rows and mount them on the host, for a runtime overlay."""
        rows = self.build(height, frame)
        if rows:
            self.host.mount_all(rows)

    def paint(self, frame: list) -> None:
        for i, (row, text) in enumerate(zip(self.rows, frame)):
            covered = text is not None
            if covered:
                row.update(text)
            # The class only flips when the row's state actually changes — a
            # style change is a layout refresh, and this runs ~20×/second.
            if self._on[i] != covered:
                row.set_class(not covered, "off")
                self._on[i] = covered

    def discard(self) -> None:
        """Unmount every row. Idempotent."""
        for row in self.rows:
            try:
                row.remove()
            except Exception:  # noqa: BLE001, S110 -- already gone with its host
                pass
        self.rows, self._on = [], []
