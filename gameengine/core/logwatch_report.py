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
