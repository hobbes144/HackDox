"""
SSH / Auth log parser
---------------------
Parses Linux /var/log/auth.log format.

Real example lines:
  May  7 10:23:45 server sshd[1234]: Failed password for root from 192.168.1.1 port 54321 ssh2
  May  7 10:23:46 server sshd[1234]: Accepted password for alice from 10.0.0.5 port 22314 ssh2
  May  7 10:23:47 server sshd[1234]: Invalid user admin from 192.168.1.1 port 54322
  May  7 10:24:01 server sudo[5678]: alice : TTY=pts/0 ; PWD=/home/alice ; USER=root ; COMMAND=/bin/bash
  May  7 10:24:10 server sshd[1234]: Disconnected from user alice 10.0.0.5 port 22314

The challenge: auth.log doesn't include the year, so we infer it from the current year
and handle Dec→Jan rollovers.
"""

import re
from datetime import datetime
from typing import Optional
from modules.models import LogEntry, EventType

# Current year for timestamp parsing (auth.log omits year)
_CURRENT_YEAR = datetime.now().year

# ── Regex patterns ────────────────────────────────────────────────────────────

# Base: captures timestamp, hostname, service, PID, and the rest of the message
_BASE = re.compile(
    r"^(?P<month>\w{3})\s+(?P<day>\d{1,2})\s+(?P<time>\d{2}:\d{2}:\d{2})"
    r"\s+\S+"                               # hostname (skip)
    r"\s+(?P<service>\S+?)(?:\[\d+\])?:"   # service name + optional PID
    r"\s+(?P<msg>.+)$"
)

_MONTH_MAP = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,  "May": 5,  "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

# Message-level patterns
_FAILED   = re.compile(r"Failed (?:password|publickey) for (?:invalid user )?(\S+) from ([\d.]+)")
_INVALID  = re.compile(r"Invalid user (\S+) from ([\d.]+)")
_ACCEPTED = re.compile(r"Accepted (?:password|publickey) for (\S+) from ([\d.]+)")
_DISCONNECT = re.compile(r"Disconnected from (?:user )?(\S+)? ?([\d.]+)")
_SUDO     = re.compile(r"(\S+)\s+:.*COMMAND=(.+)$")


def _parse_timestamp(month: str, day: str, time: str) -> datetime:
    m = _MONTH_MAP.get(month, 1)
    d = int(day)
    h, mi, s = map(int, time.split(":"))
    year = _CURRENT_YEAR
    # If log month is December but we're in January, it's last year
    if m == 12 and datetime.now().month == 1:
        year -= 1
    return datetime(year, m, d, h, mi, s)


def parse_line(line: str) -> Optional[LogEntry]:
    """Parse a single auth.log line into a LogEntry, or return None if unrecognised."""
    line = line.strip()
    if not line:
        return None

    m = _BASE.match(line)
    if not m:
        return None

    ts      = _parse_timestamp(m.group("month"), m.group("day"), m.group("time"))
    service = m.group("service")
    msg     = m.group("msg")

    # ── Failed password ───────────────────────────────────────────────────────
    fm = _FAILED.search(msg)
    if fm:
        return LogEntry(
            timestamp=ts, event_type=EventType.LOGIN_FAIL,
            source_ip=fm.group(2), username=fm.group(1),
            service=service, raw=line,
        )

    # ── Invalid user ──────────────────────────────────────────────────────────
    im = _INVALID.search(msg)
    if im:
        return LogEntry(
            timestamp=ts, event_type=EventType.INVALID_USER,
            source_ip=im.group(2), username=im.group(1),
            service=service, raw=line,
        )

    # ── Successful login ──────────────────────────────────────────────────────
    am = _ACCEPTED.search(msg)
    if am:
        return LogEntry(
            timestamp=ts, event_type=EventType.LOGIN_SUCCESS,
            source_ip=am.group(2), username=am.group(1),
            service=service, raw=line,
        )

    # ── Sudo / privilege escalation ───────────────────────────────────────────
    sm = _SUDO.search(msg)
    if sm and service.startswith("sudo"):
        return LogEntry(
            timestamp=ts, event_type=EventType.SUDO,
            source_ip="local", username=sm.group(1),
            service=service, raw=line,
            extra={"command": sm.group(2).strip()},
        )

    # ── Logout / disconnect ───────────────────────────────────────────────────
    dm = _DISCONNECT.search(msg)
    if dm:
        return LogEntry(
            timestamp=ts, event_type=EventType.LOGOUT,
            source_ip=dm.group(2) or "unknown",
            username=dm.group(1),
            service=service, raw=line,
        )

    return None  # unrecognised line — skip it


def parse_file(path: str) -> list[LogEntry]:
    """Parse an entire auth.log file. Returns list of LogEntry objects."""
    entries = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            entry = parse_line(line)
            if entry:
                entries.append(entry)
    return entries
