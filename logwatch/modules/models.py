"""
Data models for logwatch
------------------------
All parsers normalize their output to LogEntry.
All detectors output Finding objects.
This shared schema is what lets one set of detectors
work across SSH logs, web logs, AND Windows event logs.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ── Event types ───────────────────────────────────────────────────────────────
# A controlled vocabulary so detectors don't need to know about log formats

class EventType(str, Enum):
    LOGIN_FAIL    = "LOGIN_FAIL"      # failed auth attempt
    LOGIN_SUCCESS = "LOGIN_SUCCESS"   # successful login
    LOGOUT        = "LOGOUT"          # session ended
    SUDO          = "SUDO"            # privilege escalation via sudo
    INVALID_USER  = "INVALID_USER"    # login attempt for non-existent user
    HTTP_REQUEST  = "HTTP_REQUEST"    # web server request
    HTTP_ERROR    = "HTTP_ERROR"      # 4xx/5xx web response
    PRIV_ASSIGN   = "PRIV_ASSIGN"     # Windows: special privileges assigned
    ACCOUNT_CREATE= "ACCOUNT_CREATE"  # new user account created
    GROUP_CHANGE  = "GROUP_CHANGE"    # user added to group
    PROCESS_START = "PROCESS_START"   # new process created
    UNKNOWN       = "UNKNOWN"


# ── Severity levels ───────────────────────────────────────────────────────────

class Severity(str, Enum):
    CRITICAL = "CRITICAL"   # Active breach, immediate action needed
    HIGH     = "HIGH"       # Strong indicator of attack
    MEDIUM   = "MEDIUM"     # Suspicious, warrants investigation
    LOW      = "LOW"        # Informational anomaly
    INFO     = "INFO"       # Clean / expected


SEVERITY_COLOR = {
    Severity.CRITICAL: "bold red",
    Severity.HIGH:     "red",
    Severity.MEDIUM:   "yellow",
    Severity.LOW:      "cyan",
    Severity.INFO:     "green",
}

SEVERITY_ICON = {
    Severity.CRITICAL: "🔴",
    Severity.HIGH:     "🟠",
    Severity.MEDIUM:   "🟡",
    Severity.LOW:      "🔵",
    Severity.INFO:     "🟢",
}


# ── Core data models ──────────────────────────────────────────────────────────

@dataclass
class LogEntry:
    """
    A single normalized log event.
    Parsers convert their native format into this.
    """
    timestamp:   datetime
    event_type:  EventType
    source_ip:   str                    # "unknown" if not available
    username:    Optional[str]          # None if not applicable
    service:     str                    # e.g. "sshd", "nginx", "Security"
    raw:         str                    # original log line (for context)
    extra:       dict = field(default_factory=dict)  # format-specific extras
    # e.g. extra = {"method": "GET", "path": "/admin", "status": 403, "ua": "sqlmap"}
    # e.g. extra = {"event_id": 4625, "logon_type": 3, "workstation": "DESKTOP-ABC"}


@dataclass
class GeoLocation:
    """IP geolocation result."""
    ip:          str
    country:     str
    country_code:str
    city:        str
    lat:         float
    lon:         float
    isp:         str


@dataclass
class Finding:
    """
    A detected security event — the output of a detector.
    """
    severity:    Severity
    category:    str           # e.g. "BRUTE_FORCE", "IMPOSSIBLE_TRAVEL"
    title:       str           # short human-readable title
    description: str           # detailed explanation
    source_ip:   Optional[str]
    username:    Optional[str]
    first_seen:  datetime
    last_seen:   datetime
    event_count: int
    evidence:    list[LogEntry] = field(default_factory=list)   # supporting log lines
    geo:         Optional[GeoLocation] = None

    @property
    def timespan_seconds(self) -> float:
        return (self.last_seen - self.first_seen).total_seconds()
