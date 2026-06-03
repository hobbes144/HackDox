"""
Core cracking engine
--------------------
Runs the actual hash comparison loop with live terminal feedback.

Strategy:
  1. Identify hash type (if not provided)
  2. Load candidates from wordlist + mutation rules
  3. Hash each candidate and compare
  4. Stream live progress to the terminal (attempts/sec, current word)
  5. Report result

For bcrypt: attempts are deliberately throttled — we make the point
that this is why bcrypt exists, then give up gracefully.
"""

import hashlib
import time
from dataclasses import dataclass
from typing import Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich import box

from modules.identifier import identify, HashInfo
from modules.rules import candidates_from_wordlist
from config import WORDLIST, USE_RULES, DISPLAY_REFRESH, BCRYPT_MAX_ATTEMPTS

console = Console()


@dataclass
class CrackResult:
    hash_str:      str
    hash_type:     str
    cracked:       bool
    password:      str | None      # None if not cracked
    attempts:      int
    elapsed_secs:  float
    attempts_per_sec: float
    source_word:   str | None      # base wordlist word that led to the crack


# ── Hash functions ────────────────────────────────────────────────────────────

def _hash_md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8", errors="replace")).hexdigest()

def _hash_sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", errors="replace")).hexdigest()

def _hash_sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()

def _hash_sha512(s: str) -> str:
    return hashlib.sha512(s.encode("utf-8", errors="replace")).hexdigest()

HASH_FUNCS = {
    "md5":    _hash_md5,
    "sha1":   _hash_sha1,
    "sha256": _hash_sha256,
    "sha512": _hash_sha512,
}


def _make_progress_panel(
    hash_str: str,
    hash_type: str,
    attempts: int,
    speed: float,
    current: str,
    elapsed: float,
) -> Panel:
    """Build the live progress display panel."""
    table = Table(box=None, show_header=False, padding=(0, 1))
    table.add_column(style="dim", width=16)
    table.add_column(style="bold")

    table.add_row("Hash",     f"[cyan]{hash_str[:32]}{'...' if len(hash_str) > 32 else ''}[/cyan]")
    table.add_row("Type",     f"[yellow]{hash_type.upper()}[/yellow]")
    table.add_row("Attempts", f"[green]{attempts:,}[/green]")
    table.add_row("Speed",    f"[green]{speed:,.0f}[/green] [dim]hashes/sec[/dim]")
    table.add_row("Elapsed",  f"{elapsed:.1f}s")
    table.add_row("Trying",   f"[dim]{current[:50]}[/dim]")

    return Panel(table, title="[bold cyan]⚡ Cracking...[/bold cyan]", border_style="cyan")


# ── Main crack function ───────────────────────────────────────────────────────

def crack(
    hash_str:    str,
    hash_type:   str | None = None,
    wordlist:    str = WORDLIST,
    use_rules:   bool = USE_RULES,
    silent:      bool = False,
) -> CrackResult:
    """
    Attempt to crack a single hash.

    Args:
        hash_str:  The hash to crack
        hash_type: Force a hash type ("md5", "sha1", etc.) or None to auto-detect
        wordlist:  Path to wordlist file
        use_rules: Apply mutation rules
        silent:    Suppress terminal output (for batch mode)

    Returns:
        CrackResult with outcome details
    """
    h = hash_str.strip().lower()

    # ── Identify hash type ────────────────────────────────────────────────────
    info = identify(h)
    effective_type = hash_type or info.hash_type

    if not silent:
        console.print()
        console.print(Panel(
            f"[bold]Hash:[/bold]  [cyan]{h}[/cyan]\n"
            f"[bold]Type:[/bold]  [yellow]{info.label}[/yellow]  "
            f"[dim](confidence: {info.confidence})[/dim]\n"
            f"[bold]Speed:[/bold] {info.speed}\n"
            f"[dim]{info.note}[/dim]",
            title="[bold]🔍 Target[/bold]",
            border_style="yellow",
        ))

    # ── Handle bcrypt specially ───────────────────────────────────────────────
    if effective_type == "bcrypt":
        return _crack_bcrypt(h, wordlist, use_rules, silent)

    # ── Get hash function ─────────────────────────────────────────────────────
    hash_fn = HASH_FUNCS.get(effective_type)
    if not hash_fn:
        if not silent:
            console.print(f"[red]✗ Unsupported hash type: {effective_type}[/red]")
        return CrackResult(h, effective_type, False, None, 0, 0, 0, None)

    # ── Crack loop ────────────────────────────────────────────────────────────
    attempts   = 0
    start_time = time.time()
    last_update = start_time
    current_word = ""

    if not silent:
        with Live(console=console, refresh_per_second=10) as live:
            for candidate, source in candidates_from_wordlist(wordlist, use_rules):
                attempts += 1
                current_word = candidate
                now = time.time()
                elapsed = now - start_time
                speed = attempts / elapsed if elapsed > 0 else 0

                # Update display periodically
                if now - last_update >= DISPLAY_REFRESH:
                    live.update(_make_progress_panel(h, effective_type, attempts, speed, candidate, elapsed))
                    last_update = now

                if hash_fn(candidate) == h:
                    elapsed = time.time() - start_time
                    live.stop()
                    _render_cracked(h, effective_type, candidate, source, attempts, elapsed)
                    return CrackResult(h, effective_type, True, candidate,
                                       attempts, elapsed, attempts / max(elapsed, 0.001), source)
    else:
        for candidate, source in candidates_from_wordlist(wordlist, use_rules):
            attempts += 1
            if hash_fn(candidate) == h:
                elapsed = time.time() - start_time
                return CrackResult(h, effective_type, True, candidate,
                                   attempts, elapsed, attempts / max(elapsed, 0.001), source)

    elapsed = time.time() - start_time
    if not silent:
        _render_not_found(h, effective_type, attempts, elapsed)

    return CrackResult(h, effective_type, False, None,
                       attempts, elapsed, attempts / max(elapsed, 0.001), None)


def _crack_bcrypt(hash_str: str, wordlist: str, use_rules: bool, silent: bool) -> CrackResult:
    """
    Attempt to crack a bcrypt hash.
    bcrypt is intentionally slow — we demonstrate this dramatically then stop.
    """
    try:
        import bcrypt as _bcrypt
    except ImportError:
        if not silent:
            console.print("[red]✗ bcrypt library not installed. Run: pip install bcrypt[/red]")
        return CrackResult(hash_str, "bcrypt", False, None, 0, 0, 0, None)

    if not silent:
        console.print()
        console.print(Panel(
            "[bold yellow]⚠  bcrypt detected[/bold yellow]\n\n"
            "bcrypt is a [bold]password hashing function designed to be slow[/bold].\n"
            "Unlike MD5/SHA256 which can do millions of checks/sec,\n"
            "bcrypt is limited to [bold red]~100 checks/sec[/bold red] by design.\n\n"
            "Cracking a bcrypt hash with a dictionary would take:\n"
            "  • Common password (top 100):  [green]seconds[/green]\n"
            "  • Decent password (top 10k):  [yellow]minutes[/yellow]\n"
            "  • Strong password (top 1M):   [red]hours to days[/red]\n\n"
            "Trying first 200 candidates to demonstrate...",
            title="[bold]bcrypt — The Uncrackable Hash[/bold]",
            border_style="red",
        ))

    attempts   = 0
    start_time = time.time()
    hash_bytes = hash_str.encode()

    for candidate, source in candidates_from_wordlist(wordlist, use_rules):
        if attempts >= BCRYPT_MAX_ATTEMPTS:
            break
        attempts += 1

        if not silent:
            elapsed = time.time() - start_time
            speed = attempts / max(elapsed, 0.001)
            console.print(
                f"  [dim]{attempts:3d}[/dim]  {candidate:<30}  "
                f"[dim]{speed:.1f}/sec[/dim]",
                end="\r",
            )

        if _bcrypt.checkpw(candidate.encode(), hash_bytes):
            elapsed = time.time() - start_time
            if not silent:
                _render_cracked(hash_str, "bcrypt", candidate, source, attempts, elapsed)
            return CrackResult(hash_str, "bcrypt", True, candidate,
                               attempts, elapsed, attempts / max(elapsed, 0.001), source)

    elapsed = time.time() - start_time
    if not silent:
        console.print()
        console.print(Panel(
            f"[yellow]Stopped after {attempts} attempts ({elapsed:.1f}s).[/yellow]\n"
            f"Speed: [red]{attempts/max(elapsed,0.001):.0f} checks/sec[/red] — "
            f"compare to MD5's [green]5,000,000+/sec[/green]\n\n"
            "[dim]This is the point: bcrypt turns a millisecond attack into a century.[/dim]",
            title="[bold yellow]⏱ bcrypt Demonstration Complete[/bold yellow]",
            border_style="yellow",
        ))

    return CrackResult(hash_str, "bcrypt", False, None,
                       attempts, elapsed, attempts / max(elapsed, 0.001), None)


# ── Result renderers ──────────────────────────────────────────────────────────

def _render_cracked(hash_str: str, hash_type: str, password: str,
                    source: str, attempts: int, elapsed: float) -> None:
    note = ""
    if source and source != password:
        note = f"\n[dim]Base word: '{source}' (mutation applied)[/dim]"

    console.print()
    console.print(Panel(
        f"[bold green]✓  PASSWORD FOUND[/bold green]\n\n"
        f"[bold]Hash:[/bold]     [dim]{hash_str}[/dim]\n"
        f"[bold]Password:[/bold] [bold green]{password}[/bold green]\n"
        f"[bold]Type:[/bold]     {hash_type.upper()}\n"
        f"[bold]Attempts:[/bold] {attempts:,} in {elapsed:.2f}s "
        f"([green]{attempts/max(elapsed,0.001):,.0f}/sec[/green])"
        + note,
        title="[bold green]🔓 CRACKED[/bold green]",
        border_style="green",
    ))


def _render_not_found(hash_str: str, hash_type: str,
                      attempts: int, elapsed: float) -> None:
    console.print()
    console.print(Panel(
        f"[yellow]✗  Password not found in wordlist[/yellow]\n\n"
        f"[dim]Tried {attempts:,} candidates in {elapsed:.2f}s[/dim]\n\n"
        "Suggestions:\n"
        "  • Try a larger wordlist (rockyou.txt)\n"
        "  • The password may be truly random/strong\n"
        "  • Try [bold]--no-rules[/bold] to confirm wordlist coverage",
        title="[bold yellow]🔒 Not Cracked[/bold yellow]",
        border_style="yellow",
    ))


def crack_file(
    filepath:  str,
    hash_type: str | None = None,
    wordlist:  str = WORDLIST,
    use_rules: bool = USE_RULES,
) -> list[CrackResult]:
    """Crack multiple hashes from a file (one hash per line)."""
    results = []
    with open(filepath) as f:
        hashes = [line.strip() for line in f if line.strip()]

    console.print(f"\n[cyan]Loaded {len(hashes)} hash(es) from {filepath}[/cyan]\n")

    for i, h in enumerate(hashes, 1):
        console.print(f"[dim]── Hash {i}/{len(hashes)} ──────────────────────────────[/dim]")
        result = crack(h, hash_type, wordlist, use_rules, silent=False)
        results.append(result)

    return results
