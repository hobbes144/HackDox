"""A tiny, resolution-independent ASCII world map (2026-09-20).

Used by the Logwatch Activity Report's LOCATIONS & ACCESS section to plot the
places an account logged in from. Nothing here is a copied map image: the
land is a coarse set of lat/lon boxes (continents as rectangles), rasterised
on demand at whatever width the report column has. That is the point — the
map re-draws itself for a 38-column narrow terminal and a 56-column wide one
from the same data, so terminal resizing can never break it, only coarsen it.

Pure functions, Rich markup out, no Textual — testable without a screen.
"""

from __future__ import annotations

from dataclasses import dataclass

# Latitude window drawn. The poles are mostly empty for this game's cities and
# would waste rows; 75N..50S keeps every city in CITY_COORDS with room to spare.
LAT_TOP = 75.0
LAT_BOTTOM = -50.0

# Continents as (lat_min, lat_max, lon_min, lon_max) boxes. Deliberately coarse:
# at 5-10 degrees per character cell anything finer would not survive anyway.
LAND_BOXES: tuple[tuple[float, float, float, float], ...] = (
    # North America
    (50, 72, -168, -140),      # Alaska
    (48, 72, -140, -60),       # Canada
    (25, 50, -125, -67),       # contiguous US
    (15, 32, -117, -86),       # Mexico
    (7, 18, -92, -77),         # Central America
    (60, 80, -58, -20),        # Greenland
    # South America
    (-5, 12, -80, -50),
    (-20, -5, -78, -38),
    (-38, -20, -72, -48),
    (-50, -38, -75, -64),
    # Europe
    (36, 44, -9, 3),           # Iberia
    (43, 55, -5, 30),          # western & central Europe
    (50, 59, -8, 2),           # British Isles
    (55, 71, 5, 30),           # Scandinavia
    (44, 60, 30, 50),          # eastern Europe
    # Africa
    (15, 37, -17, 33),         # Sahara / north Africa
    (0, 15, -17, 50),          # west & east Africa
    (-35, 0, 10, 41),          # southern Africa
    (-26, -12, 43, 50),        # Madagascar
    # Middle East & Asia
    (13, 38, 35, 60),          # Arabia / Iran
    (35, 55, 50, 90),          # central Asia
    (50, 75, 50, 180),         # Siberia
    (22, 50, 90, 122),         # China
    (8, 30, 68, 90),           # India
    (5, 22, 95, 110),          # Indochina
    (34, 43, 125, 130),        # Korea
    (31, 45, 130, 146),        # Japan
    (22, 26, 120, 122),        # Taiwan
    (-9, 6, 95, 141),          # Indonesia / Malaysia
    # Oceania
    (-39, -11, 114, 154),      # Australia
    (-47, -35, 166, 179),      # New Zealand
)


@dataclass(frozen=True)
class Marker:
    char:  str                  # one visible character (usually a digit)
    lat:   float
    lon:   float
    color: str


@dataclass(frozen=True)
class Arc:
    a:     tuple[float, float]  # (lat, lon)
    b:     tuple[float, float]
    color: str
    char:  str = "·"


def is_land(lat: float, lon: float) -> bool:
    return any(a <= lat <= b and c <= lon <= d for a, b, c, d in LAND_BOXES)


def height_for(width: int) -> int:
    """Rows for a given width. Terminal cells are ~2x taller than wide, and the
    drawn window is 360 x 125 degrees, so rows ~= width * 125/360 / 2 — then a
    touch taller so city markers have room to separate."""
    return max(6, round(width * 0.22))


def project(lat: float, lon: float, w: int, h: int) -> tuple[int, int]:
    x = int((lon + 180.0) / 360.0 * w)
    y = int((LAT_TOP - lat) / (LAT_TOP - LAT_BOTTOM) * h)
    return min(max(x, 0), w - 1), min(max(y, 0), h - 1)


def _cell_center(x: int, y: int, w: int, h: int) -> tuple[float, float]:
    lon = -180.0 + (x + 0.5) * 360.0 / w
    lat = LAT_TOP - (y + 0.5) * (LAT_TOP - LAT_BOTTOM) / h
    return lat, lon


def _line(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    """Bresenham cells strictly between the two endpoints."""
    pts = []
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err, x, y = dx + dy, x0, y0
    while (x, y) != (x1, y1):
        e2 = 2 * err
        if e2 >= dy:
            err += dy; x += sx
        if e2 <= dx:
            err += dx; y += sy
        if (x, y) != (x1, y1):
            pts.append((x, y))
    return pts


def render(width: int, markers: list[Marker], arcs: list[Arc] | tuple = (),
           *, land: str = "░", land_color: str = "#2b4a5c",
           water: str = " ", frame_color: str = "#3d6478") -> list[str]:
    """Rich-markup lines: a framed map `width` columns wide (frame included).

    Markers that would share a cell are nudged to the nearest free neighbour
    so every one stays visible. Arcs are drawn first, markers last.
    """
    w = max(10, width - 2)                    # inside the │ … │ frame
    h = height_for(w)
    cells: list[list[tuple[str, str]]] = []
    for y in range(h):
        row = []
        for x in range(w):
            lat, lon = _cell_center(x, y, w, h)
            row.append((land, land_color) if is_land(lat, lon) else (water, ""))
        cells.append(row)

    for arc in arcs:
        x0, y0 = project(*arc.a, w, h)
        x1, y1 = project(*arc.b, w, h)
        for x, y in _line(x0, y0, x1, y1):
            cells[y][x] = (arc.char, arc.color)

    taken: set[tuple[int, int]] = set()
    for m in markers:
        x, y = project(m.lat, m.lon, w, h)
        if (x, y) in taken:
            for dx, dy in ((1, 0), (-1, 0), (0, -1), (0, 1), (2, 0), (-2, 0),
                           (1, -1), (-1, 1), (1, 1), (-1, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in taken:
                    x, y = nx, ny
                    break
        taken.add((x, y))
        cells[y][x] = (f"[b]{m.char}[/b]", m.color)

    out = [f"[{frame_color}]┌{'─' * w}┐[/]"]
    for row in cells:
        parts = []
        for ch, col in row:
            parts.append(f"[{col}]{ch}[/]" if col else ch)
        out.append(f"[{frame_color}]│[/]{''.join(parts)}[{frame_color}]│[/]")
    out.append(f"[{frame_color}]└{'─' * w}┘[/]")
    return out
