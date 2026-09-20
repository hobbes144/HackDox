"""Logwatch Activity Report — the free tier of the Logwatch page.

2026-09-19 overhaul (Nick). The Logwatch page used to open on the whole shared
day log, which handed the player most of the investigation for free. Now the
free tier is an aggregate report — activity bars, a 24h swimlane timeline,
login origins and resource counts — and the raw log sits sealed in the right
panel until the player spends ⏱ to pull it.

THE RULE THIS MODULE EXISTS TO KEEP: the report is computed from the log
entries, never from ground truth. Every number on it is something the player
can re-derive row by row once the log is open, so the report and the log can
never disagree, and the report can never "know" a violation the log does not
show. (The one exception is the filter tier, which is allowed to name
violations — see `filter_labels`, which reads the engine's own per-row
`violation_kind` exactly like the log renderer's filter path always has.)

What the report can and cannot tell (the reveal-tier table, pinned by tests):
  CLAIMED_IP_MISMATCH  identifiable  — the claimed IP never appears as a login origin
  IMPOSSIBLE_TRAVEL    identifiable  — two clean origins in different cities, Δ minutes
  AFTER_HOURS_ACCESS   visible       — off-hours activity (shared with insider)
  INSIDER_BEHAVIOR     suspicious    — off-hours + sensitive/privileged COUNTS (no paths)
  BRUTE_FORCE_IN_LOG / CREDENTIAL_STUFFING
                       detected, NOT classified — both produce the same linked-
                       failure burst; telling them apart needs the log
  LOW_AND_SLOW         sub-threshold — scattered failures, never trips the alert
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import config
from .models import Candidate

_PRIVATE_PREFIXES = ("10.", "172.16.", "192.168.")

# Paths the report counts as sensitive. Mirrors tools_bridge._LW_SENSITIVE_PATHS
# (imported lazily there would be circular at module load; kept in sync by
# test_report_sensitive_paths_match_generator).
SENSITIVE_PATHS = frozenset({"/etc/passwd", "/etc/shadow",
                             "/root/.ssh/id_rsa", "/proc/keys"})

# Candidate-own events that count as "activity" for the off-hours metric.
# Failures are deliberately excluded — they have their own lane and metric,
# and counting them would make every low-and-slow candidate look like an
# after-hours worker.
_ACTIVITY_EVENTS = frozenset({"AUTH_OK", "FILE_READ", "SUDO_EXEC",
                              "SESSION_END", "HASH_SUBMIT"})

LANES = ("AUTH", "FAIL", "FILES", "PRIV")


def is_internal(ip: str) -> bool:
    return ip.startswith(_PRIVATE_PREFIXES)


def in_shift(secs: int) -> bool:
    s = secs % 86400
    return config.LW_SHIFT_START <= s < config.LW_SHIFT_END


def fmt_hhmm(secs: int) -> str:
    s = secs % 86400
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}"


@dataclass(frozen=True)
class Origin:
    ip:            str
    place:         str    # city, the claimed location (claimed IP) or "internal network"
    logins:        int
    first_ts:      int
    is_claimed_ip: bool
    failures_from: int    # linked auth failures that came from this IP

    @property
    def hostile(self) -> bool:
        """Preceded by enough failures that it reads as an attacker's foothold."""
        return self.failures_from >= config.LW_HOSTILE_ORIGIN_FAILS


@dataclass(frozen=True)
class TravelPair:
    place_a: str
    place_b: str
    ts_a:    int
    ts_b:    int

    @property
    def minutes(self) -> int:
        return max(0, (self.ts_b - self.ts_a) // 60)


@dataclass(frozen=True)
class LogwatchReport:
    # Profile header — the candidate's claims.
    name:            str
    email:           str
    role:            str
    location:        str
    claimed_ip:      str
    # Aggregates — all derived from the log.
    logins:          int
    linked_failures: int
    peak_burst:      int
    origins:         tuple[Origin, ...]
    travel:          tuple[TravelPair, ...]
    files_routine:   int
    files_sensitive: int
    privileged:      int
    off_hours:       int
    lanes:           tuple[tuple[str, tuple[int, ...]], ...]
    own_rows:        int
    total_entries:   int

    # ── Derived facts ────────────────────────────────────────────────
    @property
    def burst_alert(self) -> bool:
        return self.peak_burst >= config.LW_BURST_ALERT

    @property
    def claimed_ip_seen(self) -> bool:
        return any(o.is_claimed_ip for o in self.origins)

    def metric(self, key: str) -> int:
        return {
            "logins":     self.logins,
            "failures":   self.linked_failures,
            "origins":    len(self.origins),
            "files":      self.files_routine + self.files_sensitive,
            "privileged": self.privileged,
            "off_hours":  self.off_hours,
        }[key]

    def out_of_range(self, key: str) -> bool:
        _label, ceiling, _scale = config.LW_PROFILE_METRICS[key]
        return self.metric(key) > ceiling

    def lane(self, name: str) -> tuple[int, ...]:
        return dict(self.lanes)[name]


def _peak(times: list[int], window: int) -> int:
    times = sorted(times)
    best, lo = 0, 0
    for hi, t in enumerate(times):
        while t - times[lo] > window:
            lo += 1
        best = max(best, hi - lo + 1)
    return best


def build_logwatch_report(entries, candidate: Candidate) -> LogwatchReport:
    """Aggregate the day log into the candidate's Activity Report.

    `entries` is the shared day log (tools_bridge.generate_day_log). Only
    what a player could see in the log is used: IPs, events, timestamps,
    paths and city tags, plus `owner_id` — which is exactly the attribution
    the log panel shows the player as the highlighted target rows (it is
    used instead of the account string because ~0.5% of generated days hold
    two candidates with the same email; see the 2026-09-19 notes).
    `is_suspicious` / `violation_kind` are engine-only and are NOT read here.
    """
    email = candidate.email
    claimed_ip = candidate.dossier.claimed_ip or ""
    location = getattr(candidate.dossier, "claimed_location", "On-site")

    own = [e for e in entries if e.owner_id == candidate.id]
    ok  = sorted((e for e in own if e.event == "AUTH_OK"), key=lambda e: e.ts_secs)

    # Linked failures: on the account itself, or from an EXTERNAL IP that
    # went on to log in as the account. The second clause is how credential
    # stuffing (whose failures land on other accounts) shows up at all — and
    # why it is indistinguishable from brute force until the log is read.
    ext_login_ips = {e.ip for e in ok if not is_internal(e.ip)}
    fails = [e for e in entries if e.event == "AUTH_FAIL"
             and (e.owner_id == candidate.id or e.ip in ext_login_ips)]

    origins: list[Origin] = []
    for ip in dict.fromkeys(e.ip for e in ok):          # first-seen order
        rows = [e for e in ok if e.ip == ip]
        if ip == claimed_ip:
            place = location
        elif is_internal(ip):
            place = "internal network"
        else:
            place = rows[0].city or "unresolved"
        origins.append(Origin(
            ip=ip, place=place, logins=len(rows), first_ts=rows[0].ts_secs,
            is_claimed_ip=(ip == claimed_ip),
            failures_from=sum(1 for f in fails if f.ip == ip),
        ))

    # Travel: consecutive logins from CLEAN origins in different places.
    by_ip = {o.ip: o for o in origins}
    clean_ok = [e for e in ok if not by_ip[e.ip].hostile]
    travel: list[TravelPair] = []
    seen_pairs: set[tuple[str, str]] = set()
    for a, b in zip(clean_ok, clean_ok[1:]):
        pa, pb = by_ip[a.ip].place, by_ip[b.ip].place
        if pa == pb or (b.ts_secs - a.ts_secs) > config.LW_TRAVEL_REPORT_WINDOW:
            continue
        if (pa, pb) in seen_pairs:
            continue
        seen_pairs.add((pa, pb))
        travel.append(TravelPair(pa, pb, a.ts_secs, b.ts_secs))

    files = [e for e in own if e.event == "FILE_READ"]
    sens  = sum(1 for e in files if e.extra in SENSITIVE_PATHS)

    lanes = (
        ("AUTH",  tuple(e.ts_secs for e in ok)),
        ("FAIL",  tuple(sorted(e.ts_secs for e in fails))),
        ("FILES", tuple(e.ts_secs for e in files)),
        ("PRIV",  tuple(e.ts_secs for e in own if e.event == "SUDO_EXEC")),
    )

    return LogwatchReport(
        name=candidate.display_name, email=email,
        role=getattr(candidate.dossier, "claimed_role", "Unlisted"),
        location=location, claimed_ip=claimed_ip,
        logins=len(ok),
        linked_failures=len(fails),
        peak_burst=_peak([f.ts_secs for f in fails], config.LW_BURST_WINDOW),
        origins=tuple(origins),
        travel=tuple(travel),
        files_routine=len(files) - sens,
        files_sensitive=sens,
        privileged=sum(1 for e in own if e.event == "SUDO_EXEC"),
        off_hours=sum(1 for e in own
                      if e.event in _ACTIVITY_EVENTS and not in_shift(e.ts_secs)),
        lanes=lanes,
        own_rows=len(own),
        total_entries=len(entries),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Rendering — Rich markup for the Logwatch page's centre column
# ═══════════════════════════════════════════════════════════════════════════
#
# Tiers (the `log_state` argument):
#   "sealed"   free  — the report alone; the auth log panel is still sealed
#   "open"     L run — same report; footer points at the now-open log panel
#   "filtered" F run — adds the ▲ CONFIRMED block, the only place a violation
#                      is NAMED on this page (besides the log's own filter tags)
#
# `hud` is the Log Analyzer HUD upgrade: bars past their normal ceiling turn
# amber and get a "◂ out of range" tag. Without it the player compares each
# bar to its │ tick themselves. It never names anything.

from math import asin, cos, radians, sin, sqrt

from rich.markup import escape as _esc

_C_HEAD   = "#ffb454"   # forensics accent (matches the FORENSICS board group)
_C_LABEL  = "#6b7785"
_C_RULE   = "#3d6478"
_C_VALUE  = "#c8d4e1"
_C_BAR    = "#7dd3c0"
_C_HOT    = "#ffb454"
_C_WARN   = "#ff8c42"
_C_CRIT   = "#ff5470"
_C_OK     = "#00ff9f"
_C_SHIFT  = "#1f2c38"
_C_OFF    = "#2e3d4f"

_LANE_GLYPH = {"AUTH": ("●", "#00ff9f"), "FAIL": ("×", "#ff5470"),
               "FILES": ("□", "#7dd3c0"), "PRIV": ("◆", "#ff8c42")}
# (PRIV is ◆, not the mockup's ▲: in this game ▲ always means "a filter
# confirmed a named violation", and a free-tier glyph must not look like one.)

# Approximate city coordinates, for the filter's travel-speed readout only.
_COORDS: dict[str, tuple[float, float]] = {
    "Seattle, US": (47.61, -122.33), "Austin, US": (30.27, -97.74),
    "Denver, US": (39.74, -104.99), "Chicago, US": (41.88, -87.63),
    "Boston, US": (42.36, -71.06), "San Francisco, US": (37.77, -122.42),
    "Portland, US": (45.52, -122.68), "Atlanta, US": (33.75, -84.39),
    "Frankfurt, DE": (50.11, 8.68), "Singapore, SG": (1.35, 103.82),
    "New York, US": (40.71, -74.01), "Amsterdam, NL": (52.37, 4.90),
    "Moscow, RU": (55.76, 37.62), "Taipei, TW": (25.03, 121.57),
    "Nairobi, KE": (-1.29, 36.82), "Sao Paulo, BR": (-23.55, -46.63),
    "London, GB": (51.51, -0.13), "Sydney, AU": (-33.87, 151.21),
    "Dubai, AE": (25.20, 55.27), "Mumbai, IN": (19.08, 72.88),
    "Seoul, KR": (37.57, 126.98), "Mexico City, MX": (19.43, -99.13),
    "Lagos, NG": (6.52, 3.38), "Toronto, CA": (43.65, -79.38),
}


def travel_kmh(pair: TravelPair) -> int | None:
    a, b = _COORDS.get(pair.place_a), _COORDS.get(pair.place_b)
    if not a or not b or pair.minutes <= 0:
        return None
    la1, lo1, la2, lo2 = map(radians, (*a, *b))
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    km = 2 * 6371 * asin(sqrt(h))
    return int(km / (pair.minutes / 60))


@dataclass(frozen=True)
class _Layout:
    width: int
    bar:   int
    bin_min: int


def layout_for(width: int | None) -> _Layout:
    """Full layout at >= LW_REPORT_WIDTH columns, compact below it (narrow
    terminals): shorter bars and hour-wide timeline cells, so nothing wraps."""
    if width is None or width >= config.LW_REPORT_WIDTH:
        return _Layout(config.LW_REPORT_WIDTH, config.LW_BAR_WIDTH,
                        config.LW_TIMELINE_BIN_MIN)
    return _Layout(max(36, width), config.LW_BAR_WIDTH_COMPACT,
                   config.LW_TIMELINE_BIN_MIN_COMPACT)


def _rule(title: str = "", lay: _Layout | None = None) -> str:
    w = (lay or layout_for(None)).width
    if not title:
        return f"[{_C_RULE}]{'─' * w}[/]"
    return (f"[{_C_RULE}]── [/][{_C_HEAD}][b]{title}[/][/] "
            f"[{_C_RULE}]{'─' * max(2, w - len(title) - 4)}[/]")


def _bar(r: LogwatchReport, key: str, hud: bool, lay: _Layout) -> str:
    label, ceiling, scale = config.LW_PROFILE_METRICS[key]
    w = lay.bar
    v = r.metric(key)
    filled = round(min(v, scale) / scale * w)
    tick = min(w - 1, round(ceiling / scale * w))
    hot = hud and r.out_of_range(key)
    col = _C_HOT if hot else _C_BAR
    cells = []
    for i in range(w):
        if i == tick:
            cells.append(f"[{_C_VALUE}]│[/]")
        elif i < filled:
            cells.append(f"[{col}]█[/]")
        else:
            cells.append(f"[{_C_OFF}]░[/]")
    over = f"[{col}]▸[/]" if v > scale else " "
    tag = f"  [{_C_HOT}]◂ out of range[/]" if hot else ""
    return f"  [{_C_LABEL}]{label:<14}[/]{''.join(cells)}{over}[{_C_VALUE}]{v:>3}[/]{tag}"


def _timeline(r: LogwatchReport, lay: _Layout) -> list[str]:
    bin_s = lay.bin_min * 60
    n = 86400 // bin_s
    per_hour = 3600 // bin_s
    axis = [" "] * n
    for h in range(0, 24, 3):
        pos = h * per_hour
        for j, ch in enumerate(f"{h:02d}"):
            if pos + j < n:
                axis[pos + j] = ch
    lines = [f"  [{_C_LABEL}]{'':<6}{''.join(axis)}[/]"]
    for lane in LANES:
        glyph, gcol = _LANE_GLYPH[lane]
        counts = [0] * n
        for ts in r.lane(lane):
            counts[(ts % 86400) // bin_s] += 1
        cells = []
        for i, c in enumerate(counts):
            if c > 1:          # several events in one cell: show how many
                cells.append(f"[b {gcol}]{min(c, 9)}[/]")
            elif c:
                cells.append(f"[{gcol}]{glyph}[/]")
            elif in_shift(i * bin_s):
                cells.append(f"[{_C_SHIFT}]░[/]")
            else:
                cells.append(f"[{_C_OFF}]·[/]")
        lines.append(f"  [{_C_LABEL}]{lane:<6}[/]{''.join(cells)}")
    s, e = fmt_hhmm(config.LW_SHIFT_START), fmt_hhmm(config.LW_SHIFT_END)
    lines.append(f"  [{_C_LABEL}]{'':<6}[/][{_C_SHIFT}]░[/][dim] shift {s}–{e} · n = count"
                 + (f" per {lay.bin_min} min" if lay.width >= config.LW_REPORT_WIDTH else "")
                 + "[/]")
    return lines


def _origins_and_resources(r: LogwatchReport, lay: _Layout) -> list[str]:
    full = lay.width >= config.LW_REPORT_WIDTH
    sub = f"  [{_C_LABEL}]where this account logged in from[/]" if full else ""
    rows = [f"  [{_C_HEAD}][b]ORIGINS[/][/]{sub}"]
    if not r.claimed_ip_seen:
        rows.append(f"  [{_C_WARN}]✗ claimed IP {_esc(r.claimed_ip)} never seen[/]")
    for o in r.origins:
        mark = f"[{_C_OK}]✓[/]" if o.is_claimed_ip else f"[{_C_WARN}]✗[/]"
        detail = f"{o.logins} login{'s' if o.logins != 1 else ''}"
        if o.failures_from:
            detail += f" · {o.failures_from} fail"
        ip_col = (f"[{_C_LABEL}]{o.ip:<16}[/] "
                  if lay.width >= config.LW_REPORT_WIDTH else "")
        rows.append(f"  {mark} [{_C_VALUE}]{_esc(o.place):<18}[/] "
                    f"{ip_col}[{_C_LABEL}]{detail}[/]")
    for t in r.travel:
        rows += _pair(f"[{_C_WARN}]Δ {t.minutes:>3} min[/] [{_C_LABEL}]@{fmt_hhmm(t.ts_a)}[/]",
                      f"[{_C_VALUE}]{_esc(t.place_a)} → {_esc(t.place_b)}[/]", lay)
    rows.append("")
    rows += _pair(
        f"[{_C_HEAD}][b]RESOURCES[/][/]",
        f"[{_C_LABEL}]routine[/] [{_C_VALUE}]{r.files_routine}[/] [{_C_LABEL}]·[/] "
        f"[{_C_LABEL}]sensitive[/] [{_C_VALUE}]{r.files_sensitive}[/] [{_C_LABEL}]·[/] "
        f"[{_C_LABEL}]privileged[/] [{_C_VALUE}]{r.privileged}[/]", lay)
    return rows


def _pair(title: str, detail: str, lay: _Layout) -> list[str]:
    """A note as one line in the full layout, title + indented detail in compact."""
    if lay.width >= config.LW_REPORT_WIDTH:
        return [f"  {title}  {detail}"]
    return [f"  {title}", f"    {detail}"]


def _alerts(r: LogwatchReport, lay: _Layout) -> list[str]:
    out: list[str] = []
    if r.burst_alert:
        mins = config.LW_BURST_WINDOW // 60
        out += _pair(f"[{_C_CRIT}][b]⚠ AUTHENTICATION ANOMALY[/][/]",
                     f"[{_C_VALUE}]{r.peak_burst} linked failures in {mins} min[/]", lay)
        out.append(f"    [{_C_LABEL}]pattern unclassified — read the auth log[/]")
    if not r.claimed_ip_seen:
        out += _pair(f"[{_C_WARN}][b]⚠ SOURCE DISCREPANCY[/][/]",
                     f"[{_C_VALUE}]claimed {_esc(r.claimed_ip)} never seen[/]", lay)
    if r.travel:
        n = len(r.travel)
        out += _pair(f"[{_C_WARN}][b]⚠ LOCATION SHIFT[/][/]",
                     f"[{_C_VALUE}]{n} city change{'s' if n != 1 else ''} "
                     f"between clean logins[/]", lay)
    if r.off_hours:
        out += _pair("[#ffd93d]● off-shift activity[/]",
                     f"[{_C_VALUE}]{r.off_hours} event{'s' if r.off_hours != 1 else ''} "
                     f"outside {fmt_hhmm(config.LW_SHIFT_START)}–"
                     f"{fmt_hhmm(config.LW_SHIFT_END)}[/]", lay)
    if not out:
        out.append(f"  [{_C_LABEL}]no anomaly crosses an alert threshold[/]")
    return out


def filter_confirmations(entries, candidate: Candidate, r: LogwatchReport) -> list[str]:
    """FILTER tier: name each Logwatch-owned violation this candidate carries,
    with the evidence the log holds for it. Filter-tier code MAY read the
    engine's per-row `violation_kind` — this is the paid explicit tier."""
    from .models import DiscrepancyKind as K, ToolName
    own = [e for e in entries if e.owner_id == candidate.id]
    kinds = {d.kind for d in candidate.truth.discrepancies
             if d.revealed_by == ToolName.LOGWATCH}
    lines: list[str] = []

    def by(vk):
        return [e for e in own if e.violation_kind == vk]

    if K.BRUTE_FORCE_IN_LOG in kinds:
        rows = by("brute_force")
        fails = [e for e in rows if e.event == "AUTH_FAIL"]
        span = (rows[-1].ts_secs - rows[0].ts_secs) if rows else 0
        lines.append(f"  [{_C_CRIT}][b]▲ BRUTE_FORCE_IN_LOG[/][/]  {len(fails)} failures on "
                     f"this account from {rows[0].ip if rows else '?'} in {span}s, then a login")
    if K.CREDENTIAL_STUFFING in kinds:
        rows = by("stuffing")
        ip = rows[0].ip if rows else "?"
        sprayed = {e.account for e in entries if e.ip == ip and e.event == "AUTH_FAIL"}
        lines.append(f"  [{_C_CRIT}][b]▲ CREDENTIAL_STUFFING[/][/]  {ip} failed on "
                     f"{len(sprayed)} other accounts, then logged in here")
    if K.LOW_AND_SLOW in kinds:
        rows = sorted(by("low_and_slow"), key=lambda e: e.ts_secs)
        if rows:
            span = rows[-1].ts_secs - rows[0].ts_secs
            lines.append(f"  [{_C_CRIT}][b]▲ LOW_AND_SLOW[/][/]  {len(rows)} failures from "
                         f"{rows[0].ip} across {span // 3600}h {(span % 3600) // 60}m "
                         f"(each under the alert)")
    if K.IMPOSSIBLE_TRAVEL in kinds:
        for t in r.travel:
            kmh = travel_kmh(t)
            spd = f" ≈ {kmh:,} km/h" if kmh else ""
            lines.append(f"  [{_C_WARN}][b]▲ IMPOSSIBLE_TRAVEL[/][/]  {_esc(t.place_a)} → "
                         f"{_esc(t.place_b)} in {t.minutes} min{spd}")
    if K.CLAIMED_IP_MISMATCH in kinds:
        seen = ", ".join(_esc(o.place) for o in r.origins) or "nowhere"
        lines.append(f"  [#ffd93d][b]▲ CLAIMED_IP_MISMATCH[/][/]  claimed "
                     f"{_esc(r.claimed_ip)}; every login came from {seen}")
    if K.INSIDER_BEHAVIOR in kinds:
        rows = by("insider")
        at = fmt_hhmm(rows[0].ts_secs) if rows else "?"
        lines.append(f"  [{_C_WARN}][b]▲ INSIDER_BEHAVIOR[/][/]  sensitive reads + "
                     f"privilege escalation at {at}")
    if K.AFTER_HOURS_ACCESS in kinds:
        rows = by("after_hours")
        at = fmt_hhmm(rows[0].ts_secs) if rows else "?"
        lines.append(f"  [#ffd93d][b]▲ AFTER_HOURS_ACCESS[/][/]  routine work at {at} "
                     f"(minor — corroborate)")
    if not lines:
        lines.append(f"  [{_C_OK}]no Logwatch violation confirmed for this account[/]")
    return lines


def render_report(r: LogwatchReport, *, log_state: str = "sealed", hud: bool = False,
                  confirmations: list[str] | tuple[str, ...] = (),
                  pull_cost: int | None = None,
                  width: int | None = None) -> tuple[str, ...]:
    """The Activity Report as Rich markup lines (see the tier notes above).

    `width` is the usable column width if known; below LW_REPORT_WIDTH the
    compact layout is used (see layout_for)."""
    lay = layout_for(width)
    s, e = fmt_hhmm(config.LW_SHIFT_START), fmt_hhmm(config.LW_SHIFT_END)
    L = _C_LABEL
    lines = [
        f"  [{L}]SUBJECT[/]  [b {_C_VALUE}]{_esc(r.name)}[/]",
        f"  [{L}]ACCOUNT[/]  [{_C_VALUE}]{_esc(r.email)}[/]",
        f"  [{L}]ROLE   [/]  [{_C_VALUE}]{_esc(r.role)}[/]",
        f"  [{L}]HOURS  [/]  [{_C_VALUE}]{s}–{e}[/]",
        f"  [{L}]CLAIMS [/]  [{_C_VALUE}]{_esc(r.location)}[/]  [{L}]via[/] "
        f"[#ffd93d]{_esc(r.claimed_ip)}[/]",
        "",
        _rule("ACTIVITY PROFILE", lay),
        f"  [{L}]{'':<14}{'│ = normal ceiling':>{lay.bar + 4}}[/]",
    ]
    lines += [_bar(r, k, hud, lay) for k in config.LW_PROFILE_METRICS]
    lines += ["", _rule("ACTIVITY TIMELINE", lay)]
    lines += _timeline(r, lay)
    lines += ["", _rule("LOCATIONS & ACCESS", lay)]
    lines += _origins_and_resources(r, lay)
    lines += ["", _rule("ANALYST NOTES", lay)]
    lines += _alerts(r, lay)
    if log_state == "filtered":
        lines += ["", _rule("▲ FILTER — CONFIRMED", lay)]
        lines += list(confirmations)
    lines.append("")
    if log_state == "sealed":
        cost = f" — {pull_cost} ⏱" if pull_cost is not None else ""
        lines.append(f"  [{L}]auth log sealed · {r.total_entries} entries[/]")
        lines.append(f"  [{_C_BAR}]L[/] [{L}]pulls it into the right panel{cost}[/]")
    elif log_state == "open":
        lines.append(f"  [{L}]auth log open → right panel[/]")
        lines.append(f"  [{_C_BAR}]{_esc('[ ]')}[/] [{L}]jump this account's "
                     f"{r.own_rows} rows ·[/] [{_C_BAR}]F[/] [{L}]filter[/]")
    else:
        lines.append(f"  [{L}]filter applied — ▲ tags are in the log too[/]")
    return tuple(lines)
