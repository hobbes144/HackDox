"""
Brute force & credential stuffing detector
-------------------------------------------
Detects three related attack patterns:

1. BRUTE_FORCE
   One IP hammering one account with many wrong passwords.
   Signature: N failures from same IP within T seconds.

2. CREDENTIAL_STUFFING
   One IP trying many different usernames — they bought a leaked database
   and are testing email/password combos across many accounts.
   Signature: one IP, M unique usernames, any failure count.

3. BRUTE_FORCE_SUCCESS  ← the scary one
   An IP that had failures eventually gets a success.
   Means the attack worked. Immediate CRITICAL.
"""

from collections import defaultdict
from datetime import timedelta
from modules.models import LogEntry, EventType, Finding, Severity
from config import (
    BRUTE_FORCE_THRESHOLD,
    BRUTE_FORCE_WINDOW_SECS,
    CRED_STUFFING_THRESHOLD,
)


def detect(entries: list[LogEntry]) -> list[Finding]:
    """Run all brute-force related detections. Returns list of Findings."""
    findings = []

    # Index: ip → list of fail events (sorted by time, entries should already be sorted)
    ip_failures:   dict[str, list[LogEntry]] = defaultdict(list)
    # Index: ip → set of unique usernames tried
    ip_usernames:  dict[str, set[str]]       = defaultdict(set)
    # Index: ip → list of success events
    ip_successes:  dict[str, list[LogEntry]] = defaultdict(list)

    fail_types = {EventType.LOGIN_FAIL, EventType.INVALID_USER}

    for entry in entries:
        if entry.event_type in fail_types:
            ip_failures[entry.source_ip].append(entry)
            if entry.username:
                ip_usernames[entry.source_ip].add(entry.username)
        elif entry.event_type == EventType.LOGIN_SUCCESS:
            ip_successes[entry.source_ip].append(entry)

    window = timedelta(seconds=BRUTE_FORCE_WINDOW_SECS)

    # ── 1. Brute Force (sliding window) ───────────────────────────────────────
    seen_bf: set[str] = set()
    for ip, fails in ip_failures.items():
        if len(fails) < BRUTE_FORCE_THRESHOLD:
            continue
        # Slide a window over the sorted failures
        for i, start_event in enumerate(fails):
            window_events = [
                e for e in fails[i:]
                if e.timestamp - start_event.timestamp <= window
            ]
            if len(window_events) >= BRUTE_FORCE_THRESHOLD and ip not in seen_bf:
                seen_bf.add(ip)
                # Primary target: most-tried username in this window
                target_user = _most_common_username(window_events)
                findings.append(Finding(
                    severity=Severity.HIGH,
                    category="BRUTE_FORCE",
                    title=f"Brute force attack from {ip}",
                    description=(
                        f"{len(window_events)} failed login attempts from {ip} "
                        f"within {BRUTE_FORCE_WINDOW_SECS // 60} minutes"
                        + (f", targeting user '{target_user}'" if target_user else "")
                        + ". This is consistent with an automated password guessing attack."
                    ),
                    source_ip=ip,
                    username=target_user,
                    first_seen=window_events[0].timestamp,
                    last_seen=window_events[-1].timestamp,
                    event_count=len(window_events),
                    evidence=window_events[:5],  # first 5 as evidence
                ))
                break

    # ── 2. Credential Stuffing ────────────────────────────────────────────────
    for ip, usernames in ip_usernames.items():
        if len(usernames) >= CRED_STUFFING_THRESHOLD:
            all_fails = ip_failures[ip]
            findings.append(Finding(
                severity=Severity.HIGH,
                category="CREDENTIAL_STUFFING",
                title=f"Credential stuffing from {ip}",
                description=(
                    f"{ip} attempted login with {len(usernames)} different usernames "
                    f"({len(all_fails)} total attempts). This is characteristic of a "
                    f"credential stuffing attack using a leaked password database."
                ),
                source_ip=ip,
                username=None,
                first_seen=all_fails[0].timestamp,
                last_seen=all_fails[-1].timestamp,
                event_count=len(all_fails),
                evidence=all_fails[:5],
            ))

    # ── 3. Brute Force → Success (the breach) ────────────────────────────────
    for ip, successes in ip_successes.items():
        if ip not in ip_failures:
            continue
        fails = ip_failures[ip]
        if len(fails) < 3:  # at least 3 failures before success = suspicious
            continue
        for success in successes:
            # Were there failures from this IP before the success?
            failures_before = [f for f in fails if f.timestamp < success.timestamp]
            if len(failures_before) >= 3:
                findings.append(Finding(
                    severity=Severity.CRITICAL,
                    category="BRUTE_FORCE_SUCCESS",
                    title=f"⚠ Brute force SUCCEEDED from {ip}",
                    description=(
                        f"After {len(failures_before)} failed attempts, {ip} successfully "
                        f"authenticated as '{success.username}' at {success.timestamp.strftime('%H:%M:%S')}. "
                        f"This indicates the attack was successful — the account may be compromised."
                    ),
                    source_ip=ip,
                    username=success.username,
                    first_seen=failures_before[0].timestamp,
                    last_seen=success.timestamp,
                    event_count=len(failures_before) + 1,
                    evidence=failures_before[-3:] + [success],
                ))

    return findings


def _most_common_username(events: list[LogEntry]) -> str | None:
    counts: dict[str, int] = defaultdict(int)
    for e in events:
        if e.username:
            counts[e.username] += 1
    return max(counts, key=counts.get) if counts else None
