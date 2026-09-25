"""Harbour-scene carrier art (core/stego_scenes.py, VOICE_GUIDE.md §7).

The stego image is a puzzle surface before it is a picture. These tests hold
the rules that keep the art from interfering with the puzzle.
"""

from __future__ import annotations

import random
from dataclasses import replace

from gameengine import config
from gameengine.core import candidate_gen, stego_scenes, tools_bridge
from gameengine.core.content_loader import load_day
from gameengine.core.models import DiscrepancyKind

_SIZES = ((30, 12), (48, 20), (72, 32))   # smallest, middle, STEGO_GRID_MAX
_IDS = [f"{random.Random(i).getrandbits(64):016x}" for i in range(24)]


def _noise(cols, rows, seed):
    rng = random.Random(seed)
    return [[rng.randint(-12, 12) for _ in range(cols)] for _ in range(rows)]


def _every_render():
    for motif in stego_scenes.MOTIFS:
        for cols, rows in _SIZES:
            for i, cid in enumerate(_IDS[:6]):
                _, grid = stego_scenes.render(cid, cols, rows,
                                              _noise(cols, rows, i), motif=motif)
                yield motif, (cols, rows), grid


def _chroma(rgb):
    return max(rgb) - min(rgb)


def test_grid_max_is_covered():
    assert config.STEGO_GRID_MAX in _SIZES


def test_every_motif_is_reachable():
    seen = {stego_scenes.pick_motif(f"{random.Random(i).getrandbits(64):016x}")
            for i in range(400)}
    assert seen == set(stego_scenes.MOTIFS)


def test_render_is_deterministic_per_candidate():
    for cid in _IDS[:5]:
        a = stego_scenes.render(cid, 40, 18, _noise(40, 18, 1))
        b = stego_scenes.render(cid, 40, 18, _noise(40, 18, 1))
        assert a == b


def test_scene_palette_stays_muted():
    """Rule 1: revealed carrier cells are vivid amber/crimson/violet. Base art
    stays under MAX_CHROMA so a revealed cell always pops."""
    worst = max((_chroma(px), motif, size)
                for motif, size, grid in _every_render()
                for row in grid for px in row)
    assert worst[0] <= stego_scenes.MAX_CHROMA, worst


def test_reveal_colours_sit_above_the_scene_saturation_ceiling():
    """The gap rule 1 relies on: every carrier reveal colour the widget can
    produce (widgets/stego_image.py) is far more vivid than any scene cell."""
    lowest = 255
    for j in range(41):
        for rgb in ((150 + j // 2, 85 + j // 3, 235),          # C2 violet
                    (210 + j // 2, 25 + j // 3, 10 + j // 4),  # encrypted crimson
                    (185 + j, 75 + j // 2, 15 + j // 4)):      # plaintext amber
            lowest = min(lowest, _chroma(rgb))
    assert lowest >= 2 * stego_scenes.MAX_CHROMA - 10, lowest


def test_scene_is_never_green_dominant():
    """A confirmed-clean cell is shown with a green wash; base art that already
    leaned green would read as 'already swept'."""
    for motif, size, grid in _every_render():
        for row in grid:
            for r, g, b in row:
                assert g - max(r, b) < 20, (motif, size, (r, g, b))


def test_spectral_lens_tint_stays_visible():
    """Rule 3: the Lens raises blue by 55. Every scene leaves headroom for it."""
    for motif, size, grid in _every_render():
        lift = [min(255, b + 55) - b for row in grid for (_, _, b) in row]
        assert min(lift) >= 45, (motif, size)


def test_scenes_are_pictures_not_washes():
    """The point of the change: each motif draws a real design, not a flat
    field — enough distinct tones, and dark and light both present."""
    for motif, size, grid in _every_render():
        lum = [0.3 * r + 0.59 * g + 0.11 * b for row in grid for r, g, b in row]
        assert max(lum) - min(lum) > 45, (motif, size)


def test_scene_never_moves_the_payload():
    """Rule 4: the scene draws from its own RNG after build_stego_image's own
    draws. Swap the scene for a flat grey and the puzzle — zone, carrier, hint
    region, shape — must come out cell-for-cell identical."""
    import gameengine.core.tools_bridge as tb

    def flat(candidate_id, cols, rows, noise_grid, motif=None):
        return "flat", tuple(tuple((90, 90, 90) for _ in range(cols))
                             for _ in range(rows))

    base = load_day(1)
    payload_kinds = (DiscrepancyKind.STEGO_PAYLOAD_PRESENT,
                     DiscrepancyKind.ENCRYPTED_PAYLOAD,
                     DiscrepancyKind.COVERT_C2_CHANNEL)
    checked = 0
    real_render = tb.stego_scenes.render
    for day_n in (5, 12, 20):
        day = replace(load_day(day_n))
        for seed in range(30):
            for slot in range(day.candidate_count):
                c = candidate_gen.generate(seed, day, slot)
                if not any(d.kind in payload_kinds for d in c.truth.discrepancies):
                    continue
                real = tools_bridge.build_stego_image(c, day_n)
                tb.stego_scenes.render = flat
                try:
                    plain = tools_bridge.build_stego_image(c, day_n)
                finally:
                    tb.stego_scenes.render = real_render
                assert (real.zone, real.carrier, real.hint_region, real.shape,
                        real.strokes) == (plain.zone, plain.carrier,
                                          plain.hint_region, plain.shape,
                                          plain.strokes)
                checked += 1
    assert checked >= 10, f"only {checked} payload images checked — test is inert"
    del base


# sha256 over (cols, rows, zone, carrier, hint_region, shape) for every payload
# image across days 5/12/20, seeds 0-29 — computed from the generator as it
# stood BEFORE the harbour scenes landed (HEAD 83982de). The flat-swap test
# above can't see a new draw added to the SHARED rng (both runs would shift
# together); this can. If you changed candidate or stego generation ON
# PURPOSE, re-pin it and say so in the commit; if you only touched the art,
# something drew from the wrong RNG.
_PAYLOAD_LAYOUT_FINGERPRINT = (
    185, "6130f75c1eee2a420046a64df4b8545b40df2b69eebb1c491e8d20c21634bb96")


def test_payload_layout_is_unchanged_by_the_art():
    import hashlib
    kinds = (DiscrepancyKind.STEGO_PAYLOAD_PRESENT,
             DiscrepancyKind.ENCRYPTED_PAYLOAD,
             DiscrepancyKind.COVERT_C2_CHANNEL)
    h, n = hashlib.sha256(), 0
    for day_n in (5, 12, 20):
        day = load_day(day_n)
        for seed in range(30):
            for slot in range(day.candidate_count):
                c = candidate_gen.generate(seed, day, slot)
                if not any(d.kind in kinds for d in c.truth.discrepancies):
                    continue
                img = tools_bridge.build_stego_image(c, day_n)
                h.update(repr((img.cols, img.rows, img.zone, sorted(img.carrier),
                               img.hint_region,
                               img.shape and img.shape.value)).encode())
                n += 1
    assert (n, h.hexdigest()) == _PAYLOAD_LAYOUT_FINGERPRINT


def test_motif_list_only_ever_grows_at_the_end():
    """pick_motif is rng.choice over MOTIFS: inserting or reordering an entry
    reassigns every candidate's scene. The harbour scenes came first
    (2026-09-24), the cyber scenes were appended after them (2026-09-25)."""
    assert stego_scenes.MOTIFS[:6] == (
        "containers", "crane_dusk", "harbour_night", "hull", "lighthouse", "fog_pier")
    assert stego_scenes.MOTIFS == stego_scenes.DOCK_MOTIFS + stego_scenes.CYBER_MOTIFS
    assert len(set(stego_scenes.MOTIFS)) == len(stego_scenes.MOTIFS)


def test_both_halves_of_hackdox_show_up_about_equally():
    """Hack + docks: across many candidates neither half should dominate."""
    picks = [stego_scenes.pick_motif(f"{random.Random(i).getrandbits(64):016x}")
             for i in range(2000)]
    cyber = sum(p in stego_scenes.CYBER_MOTIFS for p in picks) / len(picks)
    assert 0.40 <= cyber <= 0.60, cyber
