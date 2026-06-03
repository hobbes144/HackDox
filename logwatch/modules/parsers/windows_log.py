"""
Windows Security Event Log parser
----------------------------------
Parses CSV exports from Windows Event Viewer, or JSON exports from PowerShell.

To export from Windows:
  Event Viewer → Windows Logs → Security → right-click → Save All Events As → CSV

To export from PowerShell:
  Get-WinEvent -LogName Security -MaxEvents 1000 | Select-Object TimeCreated,Id,Message |
    ConvertTo-Json | Out-File security_events.json

Key Event IDs we care about:
  4624  Successful logon
  4625  Failed logon
  4648  Logon using explicit credentials (pass-the-hash indicator)
  4672  Special privileges assigned (admin logon)
  4688  New process created (lateral movement, malware)
  4720  User account created
  4732  Member added to privileged group (e.g. Administrators)
  4776  NTLM auth attempt (credential relay attacks)
"""

import csv
import json
import re
from datetime import datetime
from typing import Optional
from modules.models import LogEntry, EventType

# Map Windows Event IDs to our EventType vocabulary
EVENT_ID_MAP = {
    4624: EventType.LOGIN_SUCCESS,
    4625: EventType.LOGIN_FAIL,
    4648: EventType.LOGIN_FAIL,       # explicit credential use — often malicious
    4672: EventType.PRIV_ASSIGN,
    4688: EventType.PROCESS_START,
    4720: EventType.ACCOUNT_CREATE,
    4732: EventType.GROUP_CHANGE,
    4776: EventType.LOGIN_FAIL,       # NTLM — treat as suspicious
}

# Regex to extract IP from Windows event message text
_IP_RE       = re.compile(r"Source Network Address:\s+([\d.]+)")
_USER_RE     = re.compile(r"Account Name:\s+(\S+)")
_PROCESS_RE  = re.compile(r"New Process Name:\s+(.+)")

# Timestamp formats Windows uses
_TS_FORMATS = [
    "%m/%d/%Y %I:%M:%S %p",    # Event Viewer CSV: 5/7/2026 10:23:45 AM
    "%Y-%m-%dT%H:%M:%S",        # ISO (PowerShell JSON)
    "%m/%d/%Y %H:%M:%S",        # 24-hour CSV variant
]


def _parse_windows_ts(ts_str: str) -> Optional[datetime]:
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(ts_str.strip(), fmt)
        except ValueError:
            continue
    return None


def _extract_from_message(message: str) -> tuple[Optional[str], Optional[str]]:
    """Extract IP and username from a Windows event message body."""
    ip_m   = _IP_RE.search(message)
    user_m = _USER_RE.search(message)
    ip     = ip_m.group(1) if ip_m else None
    user   = user_m.group(1) if user_m else None
    # Filter out system/machine accounts
    if user and (user.endswith("$") or user == "SYSTEM" or user == "-"):
        user = None
    if ip in ("-", "::1", "127.0.0.1", None):
        ip = "local"
    return ip, user


def parse_csv_file(path: str) -> list[LogEntry]:
    """
    Parse a CSV export from Windows Event Viewer.
    Expected columns: Level, Date and Time, Source, Event ID, Task Category, [Message]
    """
    entries = []
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Normalize column names (Event Viewer exports vary slightly)
            date_str  = row.get("Date and Time") or row.get("Date") or ""
            event_id  = row.get("Event ID") or row.get("EventID") or "0"
            message   = row.get("Message") or row.get("Description") or ""
            source    = row.get("Source") or "Security"

            try:
                eid = int(str(event_id).strip())
            except ValueError:
                continue

            ts = _parse_windows_ts(date_str)
            if not ts:
                continue

            event_type = EVENT_ID_MAP.get(eid, EventType.UNKNOWN)
            if event_type == EventType.UNKNOWN:
                continue

            ip, user = _extract_from_message(message)

            extra = {"event_id": eid}
            if eid == 4688:
                pm = _PROCESS_RE.search(message)
                if pm:
                    extra["process"] = pm.group(1).strip()

            entries.append(LogEntry(
                timestamp=ts,
                event_type=event_type,
                source_ip=ip or "unknown",
                username=user,
                service=source,
                raw=f"EventID={eid} | {message[:120]}",
                extra=extra,
            ))

    return entries


def parse_json_file(path: str) -> list[LogEntry]:
    """Parse a PowerShell JSON export of Windows events."""
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        data = [data]

    for event in data:
        ts_raw   = event.get("TimeCreated") or event.get("TimeCreated_", "")
        eid      = int(event.get("Id") or event.get("EventID") or 0)
        message  = event.get("Message") or ""

        ts = _parse_windows_ts(str(ts_raw)[:19])
        if not ts:
            continue

        event_type = EVENT_ID_MAP.get(eid, EventType.UNKNOWN)
        if event_type == EventType.UNKNOWN:
            continue

        ip, user = _extract_from_message(message)

        entries.append(LogEntry(
            timestamp=ts,
            event_type=event_type,
            source_ip=ip or "unknown",
            username=user,
            service="Security",
            raw=f"EventID={eid}",
            extra={"event_id": eid},
        ))

    return entries


def parse_file(path: str) -> list[LogEntry]:
    """Auto-detect format (CSV vs JSON) and parse a Windows event log file."""
    if path.endswith(".json"):
        return parse_json_file(path)
    return parse_csv_file(path)
