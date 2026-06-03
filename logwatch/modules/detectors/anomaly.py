"""
Anomaly detectors
-----------------
Detects behavioural anomalies that don't fit the "many requests" pattern:

1. IMPOSSIBLE_TRAVEL
   Same username logs in from two geographically distant IPs too quickly.
   The speed implied by the distance/time is physically impossible.
   Relies on ip-api.com for geolocation (free, no key needed).

2. AFTER_HOURS_ACCESS
   A user account that has never logged in at night suddenly does.
   Baseline: all previous logins were during business hours.

3. PRIVILEGE_ESCALATION
   A sudo/admin command is run by a user who has never done so before,
   OR a sudo command is run immediately after a remote login.

4. NEW_IP_FOR_USER
   An established user (10+ prior logins) suddenly authenticates
   from an IP address never seen before.

5. WEB_SCANNER
   Web requests from a known scanner user-agent or with attack payloads
   in the URL (SQLi, path traversal, XSS, common target paths).
"""

import math
from collections import defaultdict
from datetime import timedelta
from modules.models import LogEntry, EventType, Finding, Severity, GeoLocation
from config import (
    BUSINESS_HOURS_START,
    BUSINESS_HOURS_END,
    IMPOSSIBLE_TRAVEL_KPH,
    ENABLE_GEOIP,
)


# ── Geo helpers ───────────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Main detector ─────────────────────────────────────────────────────────────

def detect(entries: list[LogEntry], geo_cache: dict[str, GeoLocation] | None = None) -> list[Finding]:
    """Run all anomaly detections. geo_cache maps IP→GeoLocation if already fetched."""
    findings: list[Finding] = []
    geo_cache = geo_cache or {}

    # Build per-user history of successes
    user_logins: dict[str, list[LogEntry]]    = defaultdict(list)
    user_sudo:   dict[str, list[LogEntry]]    = defaultdict(list)
    user_ips:    dict[str, set[str]]          = defaultdict(set)

    successes = [e for e in entries if e.event_type == EventType.LOGIN_SUCCESS]
    sudos     = [e for e in entries if e.event_type == EventType.SUDO]
    web_reqs  = [e for e in entries if e.event_type in (EventType.HTTP_REQUEST, EventType.HTTP_ERROR)]

    for e in successes:
        if e.username:
            user_logins[e.username].append(e)
            user_ips[e.username].add(e.source_ip)

    for e in sudos:
        if e.username:
            user_sudo[e.username].append(e)

    # ── 1. Impossible Travel ──────────────────────────────────────────────────
    if ENABLE_GEOIP and geo_cache:
        findings += _detect_impossible_travel(user_logins, geo_cache)

    # ── 2. After-Hours Access ─────────────────────────────────────────────────
    findings += _detect_after_hours(user_logins)

    # ── 3. Privilege Escalation ───────────────────────────────────────────────
    findings += _detect_priv_escalation(successes, sudos)

    # ── 4. New IP for Established User ────────────────────────────────────────
    findings += _detect_new_ip(user_logins, user_ips)

    # ── 5. Web Scanner / Attack Payloads ─────────────────────────────────────
    findings += _detect_web_attacks(web_reqs)

    return findings


def _detect_impossible_travel(
    user_logins: dict[str, list[LogEntry]],
    geo_cache:   dict[str, GeoLocation],
) -> list[Finding]:
    findings = []
    for username, logins in user_logins.items():
        for i in range(len(logins) - 1):
            a, b = logins[i], logins[i + 1]
            geo_a = geo_cache.get(a.source_ip)
            geo_b = geo_cache.get(b.source_ip)
            if not geo_a or not geo_b:
                continue
            if geo_a.country_code == geo_b.country_code:
                continue  # same country — skip

            dist_km   = _haversine_km(geo_a.lat, geo_a.lon, geo_b.lat, geo_b.lon)
            hours      = (b.timestamp - a.timestamp).total_seconds() / 3600
            if hours <= 0:
                continue
            speed_kph  = dist_km / hours

            if speed_kph > IMPOSSIBLE_TRAVEL_KPH:
                findings.append(Finding(
                    severity=Severity.CRITICAL,
                    category="IMPOSSIBLE_TRAVEL",
                    title=f"Impossible travel detected for '{username}'",
                    description=(
                        f"'{username}' logged in from {geo_a.city}, {geo_a.country} "
                        f"at {a.timestamp.strftime('%H:%M:%S')} then from "
                        f"{geo_b.city}, {geo_b.country} at {b.timestamp.strftime('%H:%M:%S')} — "
                        f"only {hours*60:.0f} minutes apart but {dist_km:.0f} km away. "
                        f"Implied speed: {speed_kph:.0f} km/h. Account is likely compromised."
                    ),
                    source_ip=b.source_ip,
                    username=username,
                    first_seen=a.timestamp,
                    last_seen=b.timestamp,
                    event_count=2,
                    evidence=[a, b],
                    geo=geo_b,
                ))
    return findings


def _detect_after_hours(user_logins: dict[str, list[LogEntry]]) -> list[Finding]:
    findings = []
    for username, logins in user_logins.items():
        if len(logins) < 3:  # need baseline
            continue

        # Split into historical (all but last) and latest
        history = logins[:-1]
        recent  = logins[-3:]  # check last 3

        # Was user exclusively during business hours historically?
        history_hours = [e.timestamp.hour for e in history]
        all_business  = all(BUSINESS_HOURS_START <= h < BUSINESS_HOURS_END for h in history_hours)

        if not all_business:
            continue  # user logs in at all hours — not suspicious

        # Check if recent logins are after hours
        after_hours = [
            e for e in recent
            if not (BUSINESS_HOURS_START <= e.timestamp.hour < BUSINESS_HOURS_END)
        ]

        if after_hours:
            findings.append(Finding(
                severity=Severity.MEDIUM,
                category="AFTER_HOURS_ACCESS",
                title=f"After-hours login for '{username}'",
                description=(
                    f"'{username}' has only ever logged in during business hours "
                    f"({BUSINESS_HOURS_START}:00–{BUSINESS_HOURS_END}:00), but logged in at "
                    f"{after_hours[0].timestamp.strftime('%H:%M')} from {after_hours[0].source_ip}."
                ),
                source_ip=after_hours[0].source_ip,
                username=username,
                first_seen=after_hours[0].timestamp,
                last_seen=after_hours[-1].timestamp,
                event_count=len(after_hours),
                evidence=after_hours,
            ))
    return findings


def _detect_priv_escalation(
    successes: list[LogEntry],
    sudos:     list[LogEntry],
) -> list[Finding]:
    findings = []
    # Find sudo commands that happen very soon after a remote login
    PRIV_WINDOW = timedelta(minutes=5)

    for sudo_event in sudos:
        username = sudo_event.username
        if not username:
            continue
        # Find the most recent login for this user before the sudo
        prior_logins = [
            e for e in successes
            if e.username == username
            and e.source_ip not in ("local", "127.0.0.1", "::1")
            and e.timestamp < sudo_event.timestamp
        ]
        if not prior_logins:
            continue
        latest_login = prior_logins[-1]
        gap = sudo_event.timestamp - latest_login.timestamp

        if gap <= PRIV_WINDOW:
            cmd = sudo_event.extra.get("command", "unknown command")
            findings.append(Finding(
                severity=Severity.HIGH,
                category="PRIVILEGE_ESCALATION",
                title=f"Privilege escalation by '{username}' after remote login",
                description=(
                    f"'{username}' logged in remotely from {latest_login.source_ip} at "
                    f"{latest_login.timestamp.strftime('%H:%M:%S')} then ran sudo "
                    f"'{cmd}' just {gap.seconds}s later. "
                    f"Rapid privilege escalation after remote login is a common attacker move."
                ),
                source_ip=latest_login.source_ip,
                username=username,
                first_seen=latest_login.timestamp,
                last_seen=sudo_event.timestamp,
                event_count=2,
                evidence=[latest_login, sudo_event],
            ))
    return findings


def _detect_new_ip(
    user_logins: dict[str, list[LogEntry]],
    user_ips:    dict[str, set[str]],
) -> list[Finding]:
    findings = []
    for username, logins in user_logins.items():
        if len(logins) < 10:  # need enough history
            continue
        history_ips = {e.source_ip for e in logins[:-3]}
        recent      = logins[-3:]
        new_ip_events = [e for e in recent if e.source_ip not in history_ips]

        if new_ip_events:
            findings.append(Finding(
                severity=Severity.LOW,
                category="NEW_IP_FOR_USER",
                title=f"New IP address for established user '{username}'",
                description=(
                    f"'{username}' logged in from {new_ip_events[0].source_ip} — "
                    f"an IP not seen in their previous {len(logins)-3} logins. "
                    f"May indicate account sharing, VPN use, or compromise."
                ),
                source_ip=new_ip_events[0].source_ip,
                username=username,
                first_seen=new_ip_events[0].timestamp,
                last_seen=new_ip_events[-1].timestamp,
                event_count=len(new_ip_events),
                evidence=new_ip_events,
            ))
    return findings


def _detect_web_attacks(web_reqs: list[LogEntry]) -> list[Finding]:
    findings = []
    # Group by IP
    by_ip: dict[str, list[LogEntry]] = defaultdict(list)
    for e in web_reqs:
        by_ip[e.source_ip].append(e)

    for ip, reqs in by_ip.items():
        scanner_hits   = [e for e in reqs if "scanner_ua" in e.extra.get("attack_flags", [])]
        sqli_hits      = [e for e in reqs if "sql_injection" in e.extra.get("attack_flags", [])]
        traversal_hits = [e for e in reqs if "path_traversal" in e.extra.get("attack_flags", [])]
        target_hits    = [e for e in reqs if "common_target" in e.extra.get("attack_flags", [])]

        if scanner_hits:
            findings.append(Finding(
                severity=Severity.HIGH,
                category="WEB_SCANNER",
                title=f"Automated scanner detected from {ip}",
                description=(
                    f"{ip} made {len(scanner_hits)} requests with a known scanner user-agent "
                    f"(sqlmap, nikto, gobuster, etc.). Active vulnerability scanning in progress."
                ),
                source_ip=ip, username=None,
                first_seen=scanner_hits[0].timestamp, last_seen=scanner_hits[-1].timestamp,
                event_count=len(scanner_hits), evidence=scanner_hits[:3],
            ))

        if sqli_hits:
            findings.append(Finding(
                severity=Severity.HIGH,
                category="SQL_INJECTION_ATTEMPT",
                title=f"SQL injection probes from {ip}",
                description=(
                    f"{ip} made {len(sqli_hits)} requests with SQL injection patterns "
                    f"in the URL (UNION SELECT, OR 1=1, etc.)."
                ),
                source_ip=ip, username=None,
                first_seen=sqli_hits[0].timestamp, last_seen=sqli_hits[-1].timestamp,
                event_count=len(sqli_hits), evidence=sqli_hits[:3],
            ))

        if traversal_hits:
            findings.append(Finding(
                severity=Severity.MEDIUM,
                category="PATH_TRAVERSAL",
                title=f"Path traversal attempts from {ip}",
                description=(
                    f"{ip} attempted {len(traversal_hits)} path traversal requests "
                    f"(../../../etc/passwd style)."
                ),
                source_ip=ip, username=None,
                first_seen=traversal_hits[0].timestamp, last_seen=traversal_hits[-1].timestamp,
                event_count=len(traversal_hits), evidence=traversal_hits[:3],
            ))

    return findings
