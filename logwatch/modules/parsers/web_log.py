"""
Web server log parser (Apache / Nginx Combined Log Format)
----------------------------------------------------------
Parses the "Combined Log Format" used by Apache and Nginx by default.

Real example line:
  192.168.1.100 - alice [07/May/2026:10:23:45 +0000] "GET /admin HTTP/1.1" 403 512 "-" "sqlmap/1.6.4#pip"

Fields:
  %h   client IP
  %l   ident (usually -)
  %u   auth user (usually -)
  %t   timestamp [day/month/year:HH:MM:SS zone]
  %r   request line
  %s   HTTP status code
  %b   bytes sent
  %{Referer}i  referrer
  %{User-Agent}i  user agent

Attack signatures we look for in the URL and user-agent:
  - sqlmap, nikto, nmap, masscan, gobuster, dirbuster → scanner
  - ../../../etc/passwd → path traversal
  - UNION SELECT, OR 1=1 → SQL injection
  - <script>, alert( → XSS
  - /wp-admin, /phpmyadmin, /.env, /.git → common target paths
"""

import re
from datetime import datetime, timezone, timedelta
from typing import Optional
from modules.models import LogEntry, EventType

# Combined Log Format regex
_CLF = re.compile(
    r'(?P<ip>[\d.]+)\s+'          # client IP
    r'\S+\s+'                      # ident
    r'(?P<user>\S+)\s+'            # auth user
    r'\[(?P<time>[^\]]+)\]\s+'     # timestamp
    r'"(?P<request>[^"]+)"\s+'     # request line
    r'(?P<status>\d{3})\s+'        # status code
    r'(?P<bytes>\d+|-)\s+'         # bytes
    r'"(?P<referer>[^"]*)"\s+'     # referer
    r'"(?P<ua>[^"]*)"'             # user-agent
)

_TS_FMT = "%d/%b/%Y:%H:%M:%S %z"

# Known scanner / bad user-agents
_SCANNERS = re.compile(
    r"sqlmap|nikto|nmap|masscan|gobuster|dirbuster|wfuzz|"
    r"burpsuite|nessus|openvas|metasploit|zgrab|nuclei",
    re.IGNORECASE,
)

# Suspicious URL patterns
_PATH_TRAVERSAL = re.compile(r"\.\./|%2e%2e%2f|%252e", re.IGNORECASE)
_SQLI           = re.compile(r"union\s+select|or\s+1=1|' *or|--\s*$|%27|0x[0-9a-f]+", re.IGNORECASE)
_XSS            = re.compile(r"<script|alert\s*\(|onerror\s*=|javascript:", re.IGNORECASE)
_COMMON_TARGETS = re.compile(
    r"/wp-admin|/phpmyadmin|/\.env|/\.git|/config\.php|"
    r"/etc/passwd|/admin/config|/server-status|/actuator",
    re.IGNORECASE,
)


def _classify_request(method: str, path: str, ua: str) -> tuple[EventType, dict]:
    """Classify a web request and return extra context."""
    extra = {"method": method, "path": path, "ua": ua}
    flags = []

    if _SCANNERS.search(ua):
        flags.append("scanner_ua")
    if _PATH_TRAVERSAL.search(path):
        flags.append("path_traversal")
    if _SQLI.search(path):
        flags.append("sql_injection")
    if _XSS.search(path):
        flags.append("xss")
    if _COMMON_TARGETS.search(path):
        flags.append("common_target")

    extra["attack_flags"] = flags
    return EventType.HTTP_REQUEST, extra


def parse_line(line: str) -> Optional[LogEntry]:
    """Parse a single combined log format line."""
    line = line.strip()
    if not line:
        return None

    m = _CLF.match(line)
    if not m:
        return None

    try:
        ts = datetime.strptime(m.group("time"), _TS_FMT)
    except ValueError:
        return None

    ip      = m.group("ip")
    user    = m.group("user") if m.group("user") != "-" else None
    status  = int(m.group("status"))
    request = m.group("request")
    ua      = m.group("ua")

    parts  = request.split()
    method = parts[0] if parts else "?"
    path   = parts[1] if len(parts) > 1 else "/"

    event_type, extra = _classify_request(method, path, ua)
    extra["status"] = status
    extra["bytes"]  = m.group("bytes")

    # Escalate to HTTP_ERROR for 4xx/5xx
    if status >= 400:
        event_type = EventType.HTTP_ERROR

    return LogEntry(
        timestamp=ts,
        event_type=event_type,
        source_ip=ip,
        username=user,
        service="web",
        raw=line,
        extra=extra,
    )


def parse_file(path: str) -> list[LogEntry]:
    """Parse an Apache/Nginx combined log file."""
    entries = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            entry = parse_line(line)
            if entry:
                entries.append(entry)
    return entries
