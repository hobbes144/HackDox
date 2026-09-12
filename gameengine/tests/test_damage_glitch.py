"""Tests for the damage glitch — the in-place burst after a costly admit.

When an admit damages Site Health, the same CRT signal-loss effect the screen
transitions use fires briefly over the LIVE candidate page, scaled by the size
of the hit. Health itself only lands at end of day, so this is the one moment
the player feels a threat getting inside the site.

What the tests defend:

  * **The trigger is damage, not disapproval.** It keys off the verdict's
    recorded `site_health_delta`, which is what makes a correct denial silent,
    makes admitting the White Hat silent (rules-wrong, but the site is better
    for it), and makes admitting the Dark Web glitch even though the rules
    said to admit them.
  * **The scale comes from the numbers.** `ARCHETYPE_HEALTH_WEIGHTS` is the
    only source for how hard it hits, so retuning the table retunes the
    effect. A hard-coded severity would drift away from the economy.
  * **The colour says who.** Each archetype tints the static toward its own
    hue, biased rather than flooded — a solid wash stops reading as a broken
    signal. The hues must stay distinct from each other, and the tint must
    never leak into the screen transitions, which are nobody's fault.
  * **It never blocks, and it never leaks.** NEXT is live from the first
    frame, so advancing mid-burst is a normal path: a leaked frame timer would
    paint noise over the *next* candidate's dossier. The page underneath keeps
    its layout and shows through the gaps — the rows are on their own CSS
    layer precisely so mounting them cannot disturb the page they cover.
"""

from __future__ import annotations

import asyncio
import random
import re
from contextlib import contextmanager

from textual.app import App, ComposeResult
from textual.widgets import Static

from gameengine import config
from gameengine.core import scoring
from gameengine.core.content_loader import load_day
from gameengine.core.models import GameState, Verdict
from gameengine.ui.tui import glitch
from gameengine.ui.tui.app import IntakeScreen

SEED = 0xC0FFEE
ALL_TOOLS = {"ghostscan", "hashcrack", "logwatch", "stegotool"}
SIZE = (160, 50)
BURST_ROW = ".glitch-burst-row"


class _Host(App):
    """Bare host app with the real stylesheet — the burst needs the
    `damage-glitch` layer and `.glitch-row.off` to mean anything. CSS_PATH is
    resolved from config.ROOT_DIR because Textual resolves a relative CSS_PATH
    against the module that declares the class, and this module lives one
    directory deeper than app.py."""

    CSS_PATH = config.ROOT_DIR / "ui" / "tui" / "app.tcss"

    def compose(self) -> ComposeResult:
        yield Static("root")


async def _open_intake(pilot, day, state) -> IntakeScreen:
    await pilot.app.push_screen(IntakeScreen(day, state, "briefing"))
    await pilot.pause(0.3)
    return pilot.app.screen


def _fresh_state() -> GameState:
    state = GameState(seed=SEED)
    state.unlocked_tools = set(ALL_TOOLS)
    return state


def _burst_rows(screen) -> list:
    return list(screen.query(BURST_ROW))


def _painted(screen) -> int:
    """Rows currently covering a line (the rest are hidden = show-through)."""
    return sum(1 for row in _burst_rows(screen) if not row.has_class("off"))


def _screen_text(app) -> str:
    texts = re.findall(r"<text[^>]*>(.*?)</text>", app.export_screenshot(), re.S)
    return "".join(texts).replace("&#160;", " ")


# Every character the glitch itself can draw (see glitch.py's vocabulary).
_GLITCH_GLYPHS = set("█▓▒░▄▀▌▐─═┄┈╌·01#%&*+=~^:;,.?!/\\|<>∙ ")


def _page_chars(app) -> int:
    """How much of the PAGE is still legible under the overlay.

    A lower bound rather than an exact count — the noise vocabulary includes
    digits and punctuation that the page uses too, so those are discounted.
    Counting glyphs beats looking for a specific string: which rows a frame
    covers is random, so any one label (a panel's border title, say) can be
    under a band on any given frame.
    """
    return sum(1 for ch in _screen_text(app) if ch not in _GLITCH_GLYPHS)


@contextmanager
def _slow_bursts():
    """Hold a burst open for the length of a test.

    A real burst is 0.3-0.9s, and `pilot.pause()` waits for the screen to go
    idle — which a 20fps frame timer does not do promptly — so a test that
    measures "the frame" would otherwise be racing the burst's own duration
    timer and sometimes read it after it had already cleaned itself up. The
    envelope is unchanged; only its clock is stretched.
    """
    keys = ("DAMAGE_GLITCH_MIN_DURATION", "DAMAGE_GLITCH_MAX_DURATION")
    original = {k: getattr(config, k) for k in keys}
    for k in keys:
        setattr(config, k, 30.0)
    try:
        yield
    finally:
        for k, v in original.items():
            setattr(config, k, v)


async def _start_burst(pilot, screen, delta: float, archetype=None):
    """Fire a burst and let it mount, without waiting for screen idle."""
    screen._begin_damage_glitch(delta, archetype)
    await asyncio.sleep(0.05)
    return _burst_rows(screen)


async def _await_burst_on_screen(pilot, screen, baseline: int,
                                 timeout: float = 3.0) -> None:
    """Wait until the burst is actually ON the rendered screen.

    Mounting is asynchronous, so a fixed sleep after `_begin_damage_glitch`
    catches the rows in the DOM but not always in the paint — which is a flaky
    test, not a broken feature. The condition is deliberately colour-blind
    (the page got less legible), so the hue assertions that follow it are
    still doing real work.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if _page_chars(pilot.app) < baseline * 0.9:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the burst never reached the screen")


async def _await_clear_screen(pilot, baseline: int, timeout: float = 3.0) -> None:
    """Wait until the page is legible again — used between two bursts, so the
    second one is measured on its own and not through the first one's rows."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if _page_chars(pilot.app) >= baseline * 0.95:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the burst never cleared")


# ─── Scale: the numbers drive the effect ─────────────────────────────────────


def _rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _tint_family(tint: str) -> set[str]:
    """Every colour `tinted_palette` derives from one hue."""
    palette = glitch.tinted_palette(tint)
    house = set(glitch._TEAR_FG + glitch._TEAR_BG
                + glitch._DIM_FG + glitch._DARK_BG)
    derived = set(palette.tear_fg + palette.tear_bg
                  + palette.dim_fg + palette.dark_bg) - house
    return derived | {tint}


def _svg_hue_share(app, tint: str) -> float:
    """Share of the rendered screen's colours that come from this hue.

    Reads `export_screenshot()` rather than `render_line()`: the screenshot
    forces a full render, while render_line on a freshly mounted row can
    return one unstyled segment if layout has not caught up — which made an
    earlier version of this test flaky under load rather than wrong.
    The page's own colours are in the count too, so the share is well under
    1.0 even when the burst is unmistakably tinted.
    """
    svg    = app.export_screenshot()
    fills  = (re.findall(r"fill:\s*(#[0-9a-fA-F]{6})", svg)
              + re.findall(r'fill="(#[0-9a-fA-F]{6})"', svg))
    family = {c.lower() for c in _tint_family(tint)}
    if not fills:
        return 0.0
    return sum(1 for f in fills if f.lower() in family) / len(fills)


def _hue_share(palette, seed: int = 7) -> float:
    """Share of a frame's styled spans carrying this palette's hue."""
    family = _tint_family(palette.tint) if palette.tint else set()
    frame  = glitch.build_frame(120, 40, 0.9, random.Random(seed), palette)
    spans  = [s for row in frame if row is not None for s in row.spans]
    if not spans:
        return 0.0
    return sum(1 for s in spans
               if any(c in str(s.style) for c in family)) / len(spans)


def test_a_harmless_verdict_has_no_burst():
    """Zero or positive health delta — nothing happened to the site."""
    assert glitch.burst_shape(0.0) == (0.0, 0.0)
    assert glitch.burst_shape(+2.0) == (0.0, 0.0)


def test_worse_hits_glitch_harder_and_longer():
    weights = config.ARCHETYPE_HEALTH_WEIGHTS
    damaging = sorted((w for w in weights.values() if w < 0), reverse=True)
    shapes = [glitch.burst_shape(w) for w in damaging]   # least → worst hit
    peaks     = [peak for peak, _dur in shapes]
    durations = [dur for _peak, dur in shapes]
    assert peaks == sorted(peaks), f"peaks not ordered by damage: {peaks}"
    assert durations == sorted(durations)
    assert len(set(peaks)) == len(peaks), "two different hits look identical"


def test_the_scale_comes_from_the_weights_table():
    """Retuning ARCHETYPE_HEALTH_WEIGHTS must retune the glitch with it — a
    hard-coded worst case would drift away from the economy."""
    original = dict(config.ARCHETYPE_HEALTH_WEIGHTS)
    try:
        assert glitch.worst_health_hit() == max(
            abs(w) for w in original.values() if w < 0)
        before = glitch.burst_shape(-4.0)[0]
        config.ARCHETYPE_HEALTH_WEIGHTS["bad_actor"] = -40.0
        assert glitch.worst_health_hit() == 40.0
        assert glitch.burst_shape(-4.0)[0] < before, (
            "a −4 hit should read as milder once something far worse exists")
    finally:
        config.ARCHETYPE_HEALTH_WEIGHTS.clear()
        config.ARCHETYPE_HEALTH_WEIGHTS.update(original)


def test_the_shape_stays_inside_its_configured_bounds():
    for weight in (-0.5, -2.0, -12.0, -500.0):
        peak, duration = glitch.burst_shape(weight)
        assert config.DAMAGE_GLITCH_MIN_PEAK <= peak <= config.DAMAGE_GLITCH_MAX_PEAK
        assert (config.DAMAGE_GLITCH_MIN_DURATION <= duration
                <= config.DAMAGE_GLITCH_MAX_DURATION)


def test_the_worst_hit_in_the_game_tops_the_scale():
    worst = -glitch.worst_health_hit()
    peak, duration = glitch.burst_shape(worst)
    assert peak == config.DAMAGE_GLITCH_MAX_PEAK
    assert duration == config.DAMAGE_GLITCH_MAX_DURATION
    assert glitch.coverage_for(peak) > 0.9, (
        "the worst admit in the game should nearly swallow the screen")


def test_the_smallest_hit_stays_subtle():
    smallest = -min(abs(w) for w in config.ARCHETYPE_HEALTH_WEIGHTS.values() if w < 0)
    peak, _duration = glitch.burst_shape(smallest)
    assert glitch.coverage_for(peak) < 0.35, (
        "the mildest admit should be a few torn rows, not half the screen")


# ─── Colour: which archetype got in ──────────────────────────────────────────


def test_every_archetype_that_can_damage_has_a_tint():
    damaging = {name for name, weight
                in config.ARCHETYPE_HEALTH_WEIGHTS.items() if weight < 0}
    missing = damaging - set(config.ARCHETYPE_GLITCH_TINT)
    assert not missing, f"no glitch colour for {sorted(missing)}"


def test_the_hues_are_distinguishable_from_each_other():
    """The colour is the signal — two archetypes sharing one says nothing."""
    tints = list(config.ARCHETYPE_GLITCH_TINT.values())
    assert len(set(tints)) == len(tints), f"duplicate tints: {tints}"


def test_the_two_hues_nick_named_are_the_ones_he_named():
    """Pinned by hue family rather than exact hex, so a shade can be retuned
    but an accidental swap is caught."""
    red = _rgb(config.ARCHETYPE_GLITCH_TINT["bad_actor"])
    assert red[0] > red[1] and red[0] > red[2], "the Bad Actor stopped being red"

    violet = _rgb(config.ARCHETYPE_GLITCH_TINT["the_incompatible"])
    assert violet[2] > violet[1] and violet[0] > violet[1], (
        "the Incompatible stopped being violet")


def test_a_tinted_palette_leans_on_its_hue_without_flooding_it():
    palette = glitch.tinted_palette("#ff5470")
    family  = _tint_family("#ff5470")
    tinted  = sum(1 for c in palette.tear_fg if c in family)
    assert tinted / len(palette.tear_fg) > 0.5, "the hue barely shows"
    assert tinted < len(palette.tear_fg), (
        "a flat colour wash — the neutrals are what keep it reading as a "
        "broken signal rather than a coloured overlay")


def test_the_bias_knob_actually_biases():
    subtle = glitch.tinted_palette("#ff5470", bias=0.2)
    heavy  = glitch.tinted_palette("#ff5470", bias=0.9)
    assert _hue_share(subtle) < _hue_share(heavy)


def test_each_archetype_paints_in_its_own_colour():
    for name, tint in config.ARCHETYPE_GLITCH_TINT.items():
        share = _hue_share(glitch.palette_for_archetype(name))
        assert share > 0.6, f"{name} frames barely carry {tint} ({share:.0%})"


def test_an_unknown_archetype_still_glitches():
    """A new archetype should come through in the house colour, not crash the
    verdict path on its way to the player."""
    assert glitch.tint_for_archetype("brand_new_archetype") == \
        config.DAMAGE_GLITCH_TINT_DEFAULT
    assert glitch.tint_for_archetype(None) == config.DAMAGE_GLITCH_TINT_DEFAULT


def test_the_transitions_keep_the_house_palette():
    """The tint belongs to a verdict. A screen change is nobody's fault."""
    assert glitch.DEFAULT_PALETTE.tint is None
    house = set(glitch._TEAR_FG + glitch._TEAR_BG
                + glitch._DIM_FG + glitch._DARK_BG)
    frame = glitch.build_frame(120, 40, 0.9, random.Random(7))   # no palette
    for row in frame:
        if row is None:
            continue
        for span in row.spans:
            for word in str(span.style).split():
                if word.startswith("#"):
                    assert word in house, f"{word} is not a house colour"


def test_mixing_colours_behaves():
    assert glitch._mix("#ff0000", "#00ff00", 0.0) == "#ff0000"
    assert glitch._mix("#ff0000", "#00ff00", 1.0) == "#00ff00"
    assert glitch._mix("#000000", "#ffffff", 0.5) == "#808080"


# ─── The burst envelope ──────────────────────────────────────────────────────


def test_the_burst_opens_at_its_peak_and_ends_at_nothing():
    """Front-loaded: the player already pressed ADMIT, so the consequence
    arrives at once rather than ramping in."""
    envelope = glitch.BurstEnvelope(0.8, 0.5, seed=SEED)
    opening = envelope.intensity()
    assert opening > 0.5, f"opened at {opening}, expected close to the peak"

    envelope.started -= 1.0          # run it past its duration
    assert envelope.intensity() == 0.0


def test_the_burst_decays():
    envelope = glitch.BurstEnvelope(0.9, 1.0, seed=SEED)
    early = envelope.intensity()
    envelope.started -= 0.85         # near the end, past the stutter window
    assert envelope.intensity() < early


def test_only_heavy_bursts_stutter():
    """The second spike is what makes a bad admit read as the site failing to
    recover; a mild one should just fade."""
    def at(peak, fraction):
        envelope = glitch.BurstEnvelope(peak, 1.0, seed=SEED)
        envelope.started -= fraction
        return envelope.intensity()

    heavy = config.DAMAGE_GLITCH_RE_HIT_ABOVE + 0.2
    assert at(heavy, 0.52) > at(heavy, 0.40), "no stutter on a heavy hit"
    mild = config.DAMAGE_GLITCH_RE_HIT_ABOVE / 2
    assert at(mild, 0.52) <= at(mild, 0.40), "a mild hit should just decay"


# ─── On screen ───────────────────────────────────────────────────────────────


def test_a_damaging_admit_glitches_over_the_live_page():
    async def go():
        day, state = load_day(1), _fresh_state()
        async with _Host().run_test(size=SIZE) as pilot:
            scr = await _open_intake(pilot, day, state)
            before = _page_chars(pilot.app)
            assert before > 0, "the page under test rendered nothing"

            with _slow_bursts():
                rows = await _start_burst(pilot, scr, -12.0)
            assert rows, "nothing mounted"
            assert len(rows) == pilot.app.size.height, (
                "the overlay must be one row per terminal line")
            assert _painted(scr) > 0, "mounted but painted nothing"

            during = _screen_text(pilot.app)
            glyphs = sum(during.count(c) for c in "█▓▒░▄▀▌▐")
            assert glyphs > 0, "no glitch characters on screen"
            assert _page_chars(pilot.app) < before, (
                "the worst hit in the game barely covered anything")

    asyncio.run(go())


def test_the_page_keeps_its_layout_under_the_burst():
    """The rows go on their own CSS layer for exactly this reason: they are
    mounted onto the screen, and must not push the page around."""
    async def go():
        day, state = load_day(1), _fresh_state()
        async with _Host().run_test(size=SIZE) as pilot:
            scr = await _open_intake(pilot, day, state)
            dossier = scr.query_one("#dossier")
            region_before = dossier.region
            legible_before = _page_chars(pilot.app)

            with _slow_bursts():
                await _start_burst(pilot, scr, -2.0)   # mildest, most show-through
                assert dossier.region == region_before, "the page moved"
                legible = _page_chars(pilot.app)

            assert legible > legible_before * 0.5, (
                f"only {legible} of {legible_before} page characters survived "
                "the mildest burst — it is supposed to be a few torn rows")

    asyncio.run(go())


def test_a_worse_admit_covers_more_of_the_screen():
    async def go():
        day, state = load_day(1), _fresh_state()
        async with _Host().run_test(size=SIZE) as pilot:
            scr = await _open_intake(pilot, day, state)

            with _slow_bursts():
                await _start_burst(pilot, scr, -2.0)
                mild, mild_legible = _painted(scr), _page_chars(pilot.app)

                await _start_burst(pilot, scr, -12.0)   # replaces, never stacks
                severe, severe_legible = _painted(scr), _page_chars(pilot.app)

            assert severe_legible < mild_legible, (
                "the worse hit left just as much of the page readable")

            assert len(_burst_rows(scr)) == pilot.app.size.height, (
                "the second burst stacked a second set of rows")
            assert severe > mild, f"severe {severe} not worse than mild {mild}"

    asyncio.run(go())


def test_a_harmless_verdict_mounts_nothing():
    async def go():
        day, state = load_day(1), _fresh_state()
        async with _Host().run_test(size=SIZE) as pilot:
            scr = await _open_intake(pilot, day, state)
            with _slow_bursts():
                for delta in (0.0, +1.0, +2.0):   # denial, White Hat, clean admit
                    await _start_burst(pilot, scr, delta)
                    assert not _burst_rows(scr), f"delta {delta} glitched"

    asyncio.run(go())


def test_the_real_verdict_path_fires_exactly_when_health_drops():
    """Whatever this seed rolled, the rule is the same: the burst is on iff
    the verdict it just recorded damaged the site."""
    async def go():
        day, state = load_day(1), _fresh_state()
        async with _Host().run_test(size=SIZE) as pilot:
            scr = await _open_intake(pilot, day, state)

            with _slow_bursts():
                scr._commit_verdict(Verdict.ADMIT)
                await asyncio.sleep(0.05)

                result = state.pending_results[-1]
                damaging = result.site_health_delta < 0
                assert bool(_burst_rows(scr)) is damaging, (
                    f"{result.archetype.value} recorded "
                    f"{result.site_health_delta:+.1f} health but burst="
                    f"{bool(_burst_rows(scr))}")

    asyncio.run(go())


def test_a_correct_denial_never_glitches():
    async def go():
        day, state = load_day(1), _fresh_state()
        async with _Host().run_test(size=SIZE) as pilot:
            scr = await _open_intake(pilot, day, state)
            with _slow_bursts():
                scr._commit_verdict(Verdict.DENY)
                await asyncio.sleep(0.05)

            assert state.pending_results[-1].site_health_delta == 0.0, (
                "denials are not supposed to touch health at all")
            assert not _burst_rows(scr), "a denial glitched the screen"

    asyncio.run(go())


def test_admitting_the_dark_web_glitches_even_though_it_is_correct():
    """Locked design call: the signal is damage, not disapproval. Their admit
    is right by the rules and still costs the site 8%."""
    dark_web = config.ARCHETYPE_HEALTH_WEIGHTS["dark_web"]
    assert dark_web < 0
    peak, duration = glitch.burst_shape(dark_web)
    assert peak > 0 and duration > 0

    async def go():
        day, state = load_day(1), _fresh_state()
        async with _Host().run_test(size=SIZE) as pilot:
            scr = await _open_intake(pilot, day, state)
            with _slow_bursts():
                assert await _start_burst(pilot, scr, dark_web)

    asyncio.run(go())


def test_two_archetypes_paint_the_screen_in_their_own_colours():
    """End to end, and cross-wise: the colour survives the trip from the table
    to the pixels, AND each burst carries its own hue rather than some shared
    default that would look correct in a one-sided test."""
    async def go():
        day, state = load_day(1), _fresh_state()
        red   = config.ARCHETYPE_GLITCH_TINT["bad_actor"]
        white = config.ARCHETYPE_GLITCH_TINT["sneaky_bugger"]
        async with _Host().run_test(size=SIZE) as pilot:
            scr = await _open_intake(pilot, day, state)

            baseline = _page_chars(pilot.app)

            with _slow_bursts():
                scr._begin_damage_glitch(-10.0, "bad_actor")
                await _await_burst_on_screen(pilot, scr, baseline)
                red_own, red_other = (_svg_hue_share(pilot.app, red),
                                      _svg_hue_share(pilot.app, white))

                scr._end_damage_glitch()
                await _await_clear_screen(pilot, baseline)

                scr._begin_damage_glitch(-12.0, "sneaky_bugger")
                await _await_burst_on_screen(pilot, scr, baseline)
                white_own, white_other = (_svg_hue_share(pilot.app, white),
                                          _svg_hue_share(pilot.app, red))

            assert red_own > 0.15, f"the Bad Actor burst is not red ({red_own:.0%})"
            assert white_own > 0.15, (
                f"the Sneaky Bugger burst is not white ({white_own:.0%})")
            assert red_own > red_other, "the red burst carried more white than red"
            assert white_own > white_other, (
                "the white burst carried more red than white")

    asyncio.run(go())


def test_the_verdict_path_hands_the_archetype_to_the_glitch():
    """The tint has to come from the candidate, not from a default — a burst
    that silently always used the fallback colour would look correct."""
    async def go():
        day, state = load_day(1), _fresh_state()
        async with _Host().run_test(size=SIZE) as pilot:
            scr = await _open_intake(pilot, day, state)
            seen = {}
            original = scr._begin_damage_glitch

            def spy(delta, archetype=None):
                seen["delta"], seen["archetype"] = delta, archetype
                return original(delta, archetype)

            scr._begin_damage_glitch = spy
            scr._commit_verdict(Verdict.ADMIT)
            await asyncio.sleep(0.05)

            result = state.pending_results[-1]
            assert seen.get("archetype") == result.archetype, (
                "the verdict path did not pass the archetype through")
            assert seen.get("delta") == result.site_health_delta

    asyncio.run(go())


def test_the_burst_does_not_block_the_player():
    """Unlike a screen transition, this one is pure decoration over a live
    page: NEXT stays enabled and the keyboard keeps working."""
    async def go():
        day, state = load_day(1), _fresh_state()
        async with _Host().run_test(size=SIZE) as pilot:
            scr = await _open_intake(pilot, day, state)
            with _slow_bursts():
                scr._commit_verdict(Verdict.ADMIT)
                assert await _start_burst(pilot, scr, -12.0)

                assert scr.btn_next.disabled is False, "NEXT was disabled"
                page_before = scr._page_index
                await pilot.app._press_keys(["2"])
                await asyncio.sleep(0.1)
                assert scr._page_index != page_before, (
                    "a key press during the burst never reached the screen")

    asyncio.run(go())


# ─── Teardown ────────────────────────────────────────────────────────────────


def test_the_burst_clears_itself_when_it_ends():
    async def go():
        day, state = load_day(1), _fresh_state()
        async with _Host().run_test(size=SIZE) as pilot:
            scr = await _open_intake(pilot, day, state)
            assert await _start_burst(pilot, scr, -2.0)   # shortest burst

            await asyncio.sleep(config.DAMAGE_GLITCH_MAX_DURATION + 0.3)
            assert not _burst_rows(scr), "the burst outlived its duration"
            assert scr._burst_timers == []
            assert scr._burst is None

    asyncio.run(go())


def test_advancing_mid_burst_leaves_nothing_behind():
    """NEXT is live from the first frame, so this is the common path, not an
    edge case: a leaked frame timer would paint noise over the next
    candidate's dossier."""
    async def go():
        day, state = load_day(1), _fresh_state()
        async with _Host().run_test(size=SIZE) as pilot:
            scr = await _open_intake(pilot, day, state)
            scr._commit_verdict(Verdict.ADMIT)
            assert await _start_burst(pilot, scr, -12.0)   # the longest burst

            scr._load_current_candidate()       # what NEXT ends up calling
            await asyncio.sleep(0.1)
            assert not _burst_rows(scr), "burst rows survived the candidate"
            assert scr._burst_timers == []

            # And nothing repaints them after the fact.
            await asyncio.sleep(config.DAMAGE_GLITCH_MAX_DURATION + 0.2)
            assert not _burst_rows(scr), "a leaked timer re-mounted the burst"

    asyncio.run(go())


def test_unmounting_the_screen_mid_burst_is_clean():
    async def go():
        day, state = load_day(1), _fresh_state()
        async with _Host().run_test(size=SIZE) as pilot:
            scr = await _open_intake(pilot, day, state)
            with _slow_bursts():
                await _start_burst(pilot, scr, -12.0)
                assert scr._burst_timers

            pilot.app.pop_screen()
            await pilot.pause()
            assert scr._burst_timers == []
            assert scr._burst is None

    asyncio.run(go())


def test_disabling_the_burst_switches_it_off_entirely():
    async def go():
        original = config.DAMAGE_GLITCH_ENABLED
        config.DAMAGE_GLITCH_ENABLED = False
        try:
            day, state = load_day(1), _fresh_state()
            async with _Host().run_test(size=SIZE) as pilot:
                scr = await _open_intake(pilot, day, state)
                scr._commit_verdict(Verdict.ADMIT)
                await asyncio.sleep(0.05)
                assert not _burst_rows(scr)
                assert scr._burst is None
        finally:
            config.DAMAGE_GLITCH_ENABLED = original

    asyncio.run(go())


def test_the_effect_cannot_change_what_a_shift_is_worth():
    """Presentation only. The same verdict must score identically with the
    glitch on and off — the knob is for feel, never for balance."""
    def score_with(enabled: bool):
        original = config.DAMAGE_GLITCH_ENABLED
        config.DAMAGE_GLITCH_ENABLED = enabled
        try:
            day = load_day(1)
            state = _fresh_state()
            candidate = None

            async def go():
                nonlocal candidate
                async with _Host().run_test(size=SIZE) as pilot:
                    scr = await _open_intake(pilot, day, state)
                    candidate = scr._candidate
                    scr._commit_verdict(Verdict.ADMIT)
                    await asyncio.sleep(0.05)

            asyncio.run(go())
            result = state.pending_results[-1]
            return (result.correct, result.site_health_delta,
                    result.hackdollar_delta, result.alignment_delta,
                    state.compute_hours, candidate.archetype)
        finally:
            config.DAMAGE_GLITCH_ENABLED = original

    assert score_with(True) == score_with(False)


def test_the_burst_css_is_wired():
    sheet = (config.ROOT_DIR / "ui" / "tui" / "app.tcss").read_text(encoding="utf-8")
    assert "layers: default damage-glitch" in sheet, (
        "the overlay layer is not declared — mounting the rows would "
        "rearrange the page")
    assert ".glitch-burst-row" in sheet
    # The rows rely on the shared geometry/hide rules from the transition.
    assert ".glitch-row.off" in sheet


def test_scoring_still_records_health_only_on_admits():
    """The trigger's whole premise. If denials ever start moving health, the
    burst would start firing on them and this test is the early warning."""
    day = load_day(1)
    state = _fresh_state()
    from gameengine.core import candidate_gen
    candidate = candidate_gen.generate(SEED, day, 0)
    denied = scoring.apply(candidate, Verdict.DENY, state)
    assert denied.site_health_delta == 0.0
