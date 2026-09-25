"""Hack + docks scenes for the Stegotool carrier image (VOICE_GUIDE.md §7).

Before 2026-09-24 the stego image was a plain gradient or a single tint. It is
now a simple scene drawn on the cell grid, from one of two halves of the
game's name: the docks (container stacks, a crane at dusk, harbour lights, a
hull at the waterline, a lighthouse, fog over a pier — 2026-09-24) and the
hack (a server room, an ops-room wall screen, a data-centre aisle, a globe at
night, a hooded figure at a laptop, a CCTV camera — 2026-09-25). Either way
the thing the player sweeps is worth looking at.

The image is a puzzle surface first, so every scene obeys four rules. The
tests in `tests/test_stego_scenes.py` hold each one:

1. **Muted palette.** Stamped carrier cells are amber, crimson and violet, and
   a confirmed-clean cell gets a green wash. Base art keeps its chroma under
   `MAX_CHROMA` and is never green-dominant, so a revealed cell always stands
   out.
2. **No glyph shapes.** The special carriers are a cross, a closed ring and
   parallel strokes. No scene draws those forms: no anchors, life rings,
   portholes, outlined boxes, ribbed containers, ripple lines, fence posts or
   diagonal crane arms. Silhouettes are solid fills; the crane is a Γ, not a
   T or a +.
3. **Spectral Lens headroom.** The Lens upgrade tints its region by raising
   blue. Scenes keep blue below `BLUE_CEILING` so that tint stays visible.
4. **Determinism, and independence from the puzzle.** A scene draws only from
   its own RNG (seeded from the candidate id with its own constant), after
   `build_stego_image` has made every one of its existing draws. Zone, carrier
   and hint region are therefore byte-identical to the pre-scene generator,
   and nothing about the art correlates with where the payload sits.
"""

from __future__ import annotations

import random

# Order is part of determinism — append, never reorder. The first six are the
# docks half of "HackDox"; the next six (2026-09-25) are the hack half.
DOCK_MOTIFS: tuple[str, ...] = (
    "containers", "crane_dusk", "harbour_night", "hull", "lighthouse", "fog_pier",
)
CYBER_MOTIFS: tuple[str, ...] = (
    "server_room", "ops_wall", "datacenter_aisle", "globe_night",
    "hooded_laptop", "cctv_camera",
)
MOTIFS: tuple[str, ...] = DOCK_MOTIFS + CYBER_MOTIFS

# XOR constant for the scene RNG. Must differ from every other seed
# build_stego_image uses (0xB10CA0DE, 0x57A3B007, 0x57E60001).
SCENE_SEED = 0x0D0C5EA5

# Spectral Lens tints with b + 55, r - 22 (widgets/stego_image.py). Keeping
# base blue at or under this leaves at least 45 of visible lift everywhere.
BLUE_CEILING = 200

# Chroma = max channel - min channel. Every carrier reveal colour sits at 140
# or more; base art stays at or under this. (Chroma, not HSV saturation: a
# near-black cell can be "saturated" on paper while reading as plain dark.)
MAX_CHROMA = 72

Colour = tuple[int, int, int]

# ── Palette — muted, cool, deliberately far from amber/crimson/violet/green ──
_NIGHT_TOP:    Colour = (16, 22, 36)
_NIGHT_LOW:    Colour = (38, 48, 66)
_DUSK_TOP:     Colour = (38, 44, 66)
_DUSK_LOW:     Colour = (112, 100, 100)
_OVERCAST_TOP: Colour = (84, 92, 104)
_OVERCAST_LOW: Colour = (122, 126, 130)
_FOG_TOP:      Colour = (150, 154, 158)
_FOG_LOW:      Colour = (104, 112, 120)
_WATER_TOP:    Colour = (34, 54, 66)
_WATER_LOW:    Colour = (18, 32, 42)
_QUAY:         Colour = (52, 56, 62)
_SILHOUETTE:   Colour = (14, 18, 26)
_HULL:         Colour = (42, 50, 62)
_WATERLINE:    Colour = (100, 66, 60)       # faded brick, sat 0.40
_DECK:         Colour = (78, 68, 60)        # weathered timber
_TOWER:        Colour = (150, 146, 140)
_LAMP:         Colour = (176, 174, 158)
_PALE_LIGHT:   Colour = (168, 166, 148)
_CONTAINER_TONES: tuple[Colour, ...] = (
    (112, 72, 64),    # rust brick
    (58, 92, 96),     # faded teal
    (64, 78, 106),    # slate blue
    (118, 108, 92),   # sand
    (86, 90, 96),     # steel grey
    (96, 70, 78),     # dull plum-brown (not violet: red leads, blue trails)
)


def _mix(a: Colour, b: Colour, t: float) -> Colour:
    t = max(0.0, min(1.0, t))
    return (a[0] + (b[0] - a[0]) * t,
            a[1] + (b[1] - a[1]) * t,
            a[2] + (b[2] - a[2]) * t)


def _finish(c, n: int) -> Colour:
    """Add the image's per-cell noise (same shift on every channel, so it
    brightens or darkens without adding colour) and enforce the rules."""
    r, g, b = (int(round(v)) + n // 2 for v in c)
    r, g, b = (max(0, min(255, v)) for v in (r, g, b))
    b = min(b, BLUE_CEILING)
    # Hold the chroma ceiling after noise and clamping, pulling every channel
    # toward the cell's mean rather than clipping one (which would shift hue).
    lo, hi = min(r, g, b), max(r, g, b)
    if hi - lo > MAX_CHROMA:
        mean = (r + g + b) / 3
        k = MAX_CHROMA / (hi - lo)
        r, g, b = (int(round(mean + (v - mean) * k)) for v in (r, g, b))
    return (r, g, b)


# ── Scenes ───────────────────────────────────────────────────────────────────
# Each returns a function (fx, fy) -> colour, fx/fy in 0..1 across the grid.

def _scene_containers(rng: random.Random, cols: int = 0, rows: int = 0):
    horizon, quay_top, quay_bot = 0.34, 0.74, 0.82
    stacks = []
    x = rng.uniform(0.02, 0.08)
    while x < 0.92:
        w = rng.uniform(0.10, 0.18)
        height = rng.randint(1, 4)
        tones = [rng.choice(_CONTAINER_TONES) for _ in range(height)]
        stacks.append((x, min(x + w, 0.97), height, tones))
        x += w + rng.uniform(0.0, 0.05)
    box_h = (quay_top - horizon) / 4.2

    def colour(fx, fy):
        if fy >= quay_bot:
            return _mix(_WATER_TOP, _WATER_LOW, (fy - quay_bot) / (1 - quay_bot))
        if fy >= quay_top:
            return _QUAY
        for x0, x1, height, tones in stacks:
            if x0 <= fx < x1:
                level = int((quay_top - fy) / box_h)
                if level < height:
                    return tones[level]
        return _mix(_OVERCAST_TOP, _OVERCAST_LOW, fy / quay_top)
    return colour


def _scene_crane_dusk(rng: random.Random, cols: int = 0, rows: int = 0):
    water = 0.80
    leg_x = rng.uniform(0.18, 0.40)
    leg_w = 0.07
    boom_y0 = rng.uniform(0.18, 0.26)
    boom_h = 0.06
    boom_len = rng.uniform(0.35, 0.50)
    # Γ, never T or +: the boom runs out one side only; the other side gets a
    # short, thick counterweight block rather than a continuing arm.
    cw = (leg_x - 0.06, leg_x, boom_y0 - 0.02, boom_y0 + boom_h + 0.06)

    def colour(fx, fy):
        if fy >= water:
            return _mix(_WATER_TOP, _WATER_LOW, (fy - water) / (1 - water))
        in_leg = leg_x <= fx < leg_x + leg_w and fy >= boom_y0
        in_boom = (leg_x <= fx < leg_x + leg_w + boom_len
                   and boom_y0 <= fy < boom_y0 + boom_h)
        in_cw = cw[0] <= fx < cw[1] and cw[2] <= fy < cw[3]
        if in_leg or in_boom or in_cw:
            return _SILHOUETTE
        if fy >= water - 0.05:
            return _QUAY
        return _mix(_DUSK_TOP, _DUSK_LOW, fy / water)
    return colour


def _scene_harbour_night(rng: random.Random, cols: int = 0, rows: int = 0):
    pier = 0.66
    # A contiguous skyline — one solid silhouette with a varying roof height.
    roof = [rng.uniform(0.40, 0.58) for _ in range(12)]
    lights = sorted(rng.uniform(0.04, 0.96) for _ in range(rng.randint(4, 7)))

    def colour(fx, fy):
        if fy >= pier + 0.04:
            base = _mix(_WATER_TOP, _WATER_LOW, (fy - pier) / (1 - pier))
            # Soft glow under each pier light: a blob, not a streak.
            glow = max((0.10 - abs(fx - lx)) * 4 for lx in lights)
            fade = max(0.0, 1 - (fy - pier) * 3)
            return _mix(base, _PALE_LIGHT, max(0.0, glow) * fade * 0.5)
        if fy >= pier:
            for lx in lights:
                if abs(fx - lx) < 0.012:
                    return _PALE_LIGHT
            return _QUAY
        if fy >= roof[min(11, int(fx * 12))]:
            return _SILHOUETTE
        return _mix(_NIGHT_TOP, _NIGHT_LOW, fy / pier)
    return colour


def _scene_hull(rng: random.Random, cols: int = 0, rows: int = 0):
    water = 0.78
    top = rng.uniform(0.36, 0.44)
    stern = rng.uniform(0.06, 0.14)
    bow = rng.uniform(0.84, 0.92)
    house_x = stern + rng.uniform(0.02, 0.10)
    house = (house_x, house_x + 0.16, top - 0.16, top)

    def colour(fx, fy):
        # The bow is one sloped edge, raked back toward the waterline.
        bow_edge = bow - (fy - top) * 0.25
        if top <= fy < water and stern <= fx < bow_edge:
            if water - 0.07 <= fy < water - 0.03:
                return _WATERLINE
            return _HULL
        if house[0] <= fx < house[1] and house[2] <= fy < house[3]:
            return _SILHOUETTE
        if fy >= water:
            return _mix(_WATER_TOP, _WATER_LOW, (fy - water) / (1 - water))
        return _mix(_OVERCAST_TOP, _OVERCAST_LOW, fy / water)
    return colour


def _scene_lighthouse(rng: random.Random, cols: int = 0, rows: int = 0):
    water = 0.76
    tower_x = rng.uniform(0.12, 0.26)
    tower_w = 0.06
    lamp_y = rng.uniform(0.18, 0.26)
    tower_top = lamp_y + 0.05
    beam_up = rng.choice((True, False))
    headland = tower_x + tower_w + 0.12

    def colour(fx, fy):
        if fy >= water:
            if fx < headland - (fy - water) * 0.6:
                return _SILHOUETTE
            return _mix(_WATER_TOP, _WATER_LOW, (fy - water) / (1 - water))
        if tower_x <= fx < tower_x + tower_w:
            if lamp_y <= fy < tower_top:
                return _LAMP
            if fy >= tower_top:
                return _TOWER
        sky = _mix(_NIGHT_TOP, _NIGHT_LOW, fy / water)
        # One soft, widening wedge of light — a fill, not a set of lines.
        dx = fx - (tower_x + tower_w)
        if dx > 0:
            centre = lamp_y + 0.025 + (-dx if beam_up else dx) * 0.20
            spread = 0.04 + dx * 0.45
            inside = 1 - abs(fy - centre) / spread
            if inside > 0:
                return _mix(sky, _PALE_LIGHT,
                            min(1.0, inside * 1.4) * 0.40 * max(0.0, 1 - dx * 0.9))
        return sky
    return colour


def _scene_fog_pier(rng: random.Random, cols: int = 0, rows: int = 0):
    water = 0.70
    deck_y = rng.uniform(0.58, 0.64)
    deck_len = rng.uniform(0.55, 0.80)
    from_left = rng.choice((True, False))

    def colour(fx, fy):
        fog = _mix(_FOG_TOP, _FOG_LOW, fy / water)
        on_deck = (fx < deck_len) if from_left else (fx > 1 - deck_len)
        if on_deck and deck_y <= fy < deck_y + 0.06:
            # The far end of the pier fades into the fog.
            reach = fx / deck_len if from_left else (1 - fx) / deck_len
            return _mix(_DECK, fog, max(0.0, reach - 0.3))
        if fy >= water:
            return _mix(_mix(_WATER_TOP, fog, 0.4), _WATER_LOW, (fy - water) / (1 - water))
        return fog
    return colour


# ── Cyber scenes (2026-09-25) — the "hack" half ─────────────────────────────
# Same rules as the harbour scenes. Screens and glows are soft FILLS, never
# text lines or scanlines (those would be parallel strokes); lights are single
# scattered cells, never a grid of them (a grid of dots reads as crosses); the
# globe is a filled disc with no bright rim (a rim is a ring).

_ROOM_TOP:     Colour = (10, 14, 22)
_ROOM_LOW:     Colour = (22, 28, 40)
_FLOOR_NEAR:   Colour = (40, 46, 58)
_RACK:         Colour = (26, 32, 42)
_RACK_LIT:     Colour = (38, 46, 58)
_LED:          Colour = (150, 176, 184)     # pale cyan-white, chroma 34
_SCREEN_DIM:   Colour = (44, 76, 92)
_SCREEN:       Colour = (70, 112, 128)
_SCREEN_HOT:   Colour = (128, 160, 170)
_LAND:         Colour = (66, 92, 104)
_OCEAN:        Colour = (28, 48, 66)
_SPACE_TOP:    Colour = (8, 12, 20)
_SPACE_LOW:    Colour = (20, 26, 40)


def _cell_picker(cols: int, rows: int):
    """Map a fractional position to the grid cell it lands in."""
    def cell(fx, fy):
        return (int(round(fx * max(1, cols - 1))), int(round(fy * max(1, rows - 1))))
    return cell


def _scatter(rng: random.Random, cols: int, rows: int, region, count: int,
             min_gap: int = 3) -> set:
    """`count` single cells scattered inside `region` (fractions), no two
    within `min_gap` cells of each other — scattered, never gridded."""
    x0, x1, y0, y1 = region
    cells: list = []
    for _ in range(count * 6):
        if len(cells) >= count:
            break
        cx = int(rng.uniform(x0, x1) * max(1, cols - 1))
        cy = int(rng.uniform(y0, y1) * max(1, rows - 1))
        if all(abs(cx - a) + abs(cy - b) >= min_gap for a, b in cells):
            cells.append((cx, cy))
    return set(cells)


def _scene_server_room(rng: random.Random, cols: int = 0, rows: int = 0):
    floor = 0.84
    racks = []
    x = rng.uniform(0.03, 0.10)
    while x < 0.90:
        w = rng.uniform(0.12, 0.18)
        top = rng.uniform(0.12, 0.30)
        racks.append((x, min(x + w, 0.97), top))
        x += w + rng.uniform(0.03, 0.07)
    leds: set = set()
    for x0, x1, top in racks:
        leds |= _scatter(rng, cols, rows, (x0 + 0.02, x1 - 0.02, top + 0.05, floor - 0.06),
                         rng.randint(2, 4))
    cell = _cell_picker(cols, rows)

    def colour(fx, fy):
        if fy >= floor:
            return _mix(_FLOOR_NEAR, _ROOM_LOW, (1 - fy) / (1 - floor))
        for x0, x1, top in racks:
            if x0 <= fx < x1 and fy >= top:
                if cell(fx, fy) in leds:
                    return _LED
                # A cool glow falling off down the cabinet face — shading, not lines.
                return _mix(_RACK_LIT, _RACK, (fy - top) / (floor - top))
        return _mix(_ROOM_TOP, _ROOM_LOW, fy / floor)
    return colour


def _scene_ops_wall(rng: random.Random, cols: int = 0, rows: int = 0):
    # One big wall display (a single filled panel) with a soft world-map glow
    # on it, and the silhouettes of a desk row in front.
    wall = (0.08, 0.92, 0.10, 0.74)
    blobs = [(rng.uniform(0.15, 0.85), rng.uniform(0.20, 0.52),
              rng.uniform(0.06, 0.14), rng.uniform(0.05, 0.10))
             for _ in range(rng.randint(3, 5))]
    hot = (rng.uniform(0.25, 0.75), rng.uniform(0.25, 0.45))
    desk_top = rng.uniform(0.72, 0.78)
    heads = sorted(rng.uniform(0.15, 0.85) for _ in range(rng.randint(2, 3)))

    def colour(fx, fy):
        for hx in heads:
            if ((fx - hx) / 0.045) ** 2 + ((fy - (desk_top - 0.06)) / 0.08) ** 2 < 1:
                return _SILHOUETTE
        if fy >= desk_top:
            return _mix(_SILHOUETTE, _ROOM_LOW, (fy - desk_top) * 2)
        x0, x1, y0, y1 = wall
        if x0 <= fx < x1 and y0 <= fy < y1:
            c = _SCREEN_DIM
            for bx, by, rx, ry in blobs:
                d = ((fx - bx) / rx) ** 2 + ((fy - by) / ry) ** 2
                if d < 1:
                    c = _mix(c, _SCREEN, 1 - d)
            dh = ((fx - hot[0]) / 0.05) ** 2 + ((fy - hot[1]) / 0.06) ** 2
            if dh < 1:
                c = _mix(c, _SCREEN_HOT, 1 - dh)
            return c
        # The wall's light spilling into the room around it.
        spill = max(0.0, 0.35 - abs(fy - 0.36) * 0.9)
        return _mix(_mix(_ROOM_TOP, _ROOM_LOW, fy / desk_top), _SCREEN_DIM, spill)
    return colour


def _scene_datacenter_aisle(rng: random.Random, cols: int = 0, rows: int = 0):
    # A cold aisle in one-point perspective: two dark rack walls converging on
    # a lit doorway. The walls are fills; their edges meet, they never run
    # parallel.
    vx = rng.uniform(0.42, 0.58)
    vy = rng.uniform(0.40, 0.48)
    door_w, door_h = 0.07, 0.16
    leds_l = _scatter(rng, cols, rows, (0.02, vx - 0.12, 0.18, 0.80), rng.randint(3, 5))
    leds_r = _scatter(rng, cols, rows, (vx + 0.12, 0.98, 0.18, 0.80), rng.randint(3, 5))
    cell = _cell_picker(cols, rows)

    def colour(fx, fy):
        if abs(fx - vx) < door_w and vy - door_h <= fy < vy + door_h * 0.6:
            return _mix(_SCREEN_HOT, _SCREEN, abs(fx - vx) / door_w)
        spread = abs(fx - vx)
        # Floor and ceiling wedges grow away from the vanishing point.
        if fy > vy + door_h * 0.6 + spread * 0.55:
            return _mix(_mix(_FLOOR_NEAR, _SCREEN_DIM, 0.35), _ROOM_LOW, 1 - (fy - vy) / (1 - vy))
        if fy < vy - door_h - spread * 0.55:
            return _mix(_ROOM_TOP, _ROOM_LOW, fy / vy)
        if cell(fx, fy) in (leds_l | leds_r):
            return _LED
        return _mix(_RACK, _RACK_LIT, max(0.0, 1 - spread * 2.2))
    return colour


def _scene_globe_night(rng: random.Random, cols: int = 0, rows: int = 0):
    cx, cy = rng.uniform(0.42, 0.58), rng.uniform(0.46, 0.54)
    rx, ry = 0.30, 0.40
    continents = [(rng.uniform(-0.8, 0.8), rng.uniform(-0.7, 0.7),
                   rng.uniform(0.25, 0.45), rng.uniform(0.20, 0.40))
                  for _ in range(rng.randint(3, 4))]
    lit_from_left = rng.choice((True, False))
    stars = _scatter(rng, cols, rows, (0.0, 1.0, 0.0, 1.0), rng.randint(6, 10), min_gap=5)
    cell = _cell_picker(cols, rows)
    city_cells: set = set()
    for ux, uy, sx, sy in continents:
        city_cells |= _scatter(rng, cols, rows,
                               (cx + (ux - sx * 0.5) * rx, cx + (ux + sx * 0.5) * rx,
                                cy + (uy - sy * 0.5) * ry, cy + (uy + sy * 0.5) * ry),
                               2, min_gap=3)

    def colour(fx, fy):
        u, v = (fx - cx) / rx, (fy - cy) / ry
        d = u * u + v * v
        if d >= 1:
            if cell(fx, fy) in stars:
                return _mix(_SPACE_LOW, _LED, 0.6)
            return _mix(_SPACE_TOP, _SPACE_LOW, fy)
        c = _OCEAN
        on_land = any(((u - ux) / sx) ** 2 + ((v - uy) / sy) ** 2 < 1
                      for ux, uy, sx, sy in continents)
        if on_land:
            c = _LAND
            if cell(fx, fy) in city_cells:
                return _LED
        # Day/night terminator: shade across the disc, never a bright rim.
        side = (-u if lit_from_left else u)
        return _mix(c, _SPACE_TOP, max(0.0, min(0.75, (side + 0.3) * 0.6)))
    return colour


def _scene_hooded_laptop(rng: random.Random, cols: int = 0, rows: int = 0):
    # A hooded figure from behind, lit by a laptop screen: the classic, kept
    # to solid shapes.
    desk = rng.uniform(0.70, 0.76)
    fig_x = rng.uniform(0.34, 0.46)
    screen = (fig_x + 0.14, fig_x + 0.34, desk - 0.24, desk - 0.02)

    def colour(fx, fy):
        # Hood: a filled half-ellipse; shoulders: a wider block below it.
        hx, hy = fig_x + 0.08, desk - 0.26
        hood = ((fx - hx) / 0.08) ** 2 + ((fy - hy) / 0.16) ** 2 < 1 and fy >= hy - 0.16
        shoulders = fig_x - 0.04 <= fx < fig_x + 0.22 and hy + 0.08 <= fy < desk + 0.06
        if hood or shoulders:
            return _SILHOUETTE
        x0, x1, y0, y1 = screen
        if x0 <= fx < x1 and y0 <= fy < y1:
            return _mix(_SCREEN_HOT, _SCREEN, abs(fx - (x0 + x1) / 2) / ((x1 - x0) / 2))
        base = (_mix(_RACK, _ROOM_LOW, (fy - desk) * 3) if fy >= desk
                else _mix(_ROOM_TOP, _ROOM_LOW, fy / desk))
        # The screen's glow on the room and the desk: a soft radial fill.
        gx, gy = (x0 + x1) / 2, (y0 + y1) / 2
        g = ((fx - gx) / 0.40) ** 2 + ((fy - gy) / 0.55) ** 2
        return _mix(base, _SCREEN_DIM, max(0.0, 1 - g) * 0.8)
    return colour


def _scene_cctv_camera(rng: random.Random, cols: int = 0, rows: int = 0):
    # A security camera bolted to a wall at night, watching the ground below
    # through a soft cone of view. Solid blocks for the camera; the cone is a
    # widening fill (like the lighthouse beam), never a pair of edge lines.
    left = rng.choice((True, False))
    wall_x = rng.uniform(0.14, 0.22)
    cam_y = rng.uniform(0.22, 0.32)
    ground = rng.uniform(0.80, 0.86)
    stars = _scatter(rng, cols, rows, (0.30, 1.0, 0.0, 0.50), rng.randint(4, 7), min_gap=5)
    cell = _cell_picker(cols, rows)

    def colour(fx0, fy):
        fx = fx0 if left else 1 - fx0          # mirror, so both facings occur
        if fx < wall_x:
            return _mix(_RACK_LIT, _RACK, fy)
        arm = wall_x <= fx < wall_x + 0.06 and cam_y + 0.05 <= fy < cam_y + 0.09
        body = wall_x + 0.05 <= fx < wall_x + 0.24 and cam_y <= fy < cam_y + 0.12
        hood = wall_x + 0.04 <= fx < wall_x + 0.27 and cam_y - 0.03 <= fy < cam_y
        # Pale housing, darker hood and arm — a camera, not a hole in the sky.
        if body:
            return _mix(_TOWER, _OVERCAST_TOP, (fy - cam_y) / 0.12)
        if hood or arm:
            return _OVERCAST_TOP
        if fy >= ground:
            return _mix(_FLOOR_NEAR, _ROOM_LOW, (fy - ground) * 3)
        base = _mix(_SPACE_TOP, _NIGHT_LOW, fy / ground)
        if cell(fx0, fy) in stars:
            return _mix(base, _LED, 0.6)
        # Cone of view: from the lens, down and away from the wall.
        lx, ly = wall_x + 0.24, cam_y + 0.08
        dx, dy = fx - lx, fy - ly
        if dx > 0 and dy > 0:
            along = (dx + dy) / 1.4
            across = abs(dx - dy) / 1.4
            inside = 1 - across / (0.03 + along * 0.45)
            if inside > 0:
                return _mix(base, _SCREEN, min(1.0, inside * 1.5) * 0.55 * max(0.0, 1 - along * 1.1))
        return base
    return colour

_SCENES = {
    "containers": _scene_containers,
    "crane_dusk": _scene_crane_dusk,
    "harbour_night": _scene_harbour_night,
    "hull": _scene_hull,
    "lighthouse": _scene_lighthouse,
    "fog_pier": _scene_fog_pier,
    "server_room": _scene_server_room,
    "ops_wall": _scene_ops_wall,
    "datacenter_aisle": _scene_datacenter_aisle,
    "globe_night": _scene_globe_night,
    "hooded_laptop": _scene_hooded_laptop,
    "cctv_camera": _scene_cctv_camera,
}
assert tuple(_SCENES) == MOTIFS


def pick_motif(candidate_id: str) -> str:
    return random.Random(int(candidate_id, 16) ^ SCENE_SEED).choice(MOTIFS)


def render(candidate_id: str, cols: int, rows: int,
           noise_grid, motif: str | None = None) -> tuple[str, tuple]:
    """(motif, base_rgb) for one candidate's image.

    `noise_grid` is build_stego_image's existing per-cell noise, reused so the
    scene keeps the same fine grain the old styles had without a single new
    draw from that function's RNG.
    """
    rng = random.Random(int(candidate_id, 16) ^ SCENE_SEED)
    chosen = rng.choice(MOTIFS)
    motif = motif or chosen
    colour = _SCENES[motif](rng, cols, rows)
    grid = tuple(
        tuple(_finish(colour(x / max(1, cols - 1), y / max(1, rows - 1)),
                      noise_grid[y][x])
              for x in range(cols))
        for y in range(rows)
    )
    return motif, grid
