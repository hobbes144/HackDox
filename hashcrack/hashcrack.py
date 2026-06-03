#!/usr/bin/env python3
# fmt: off
BANNER = r"""
 _   _           _       ____                _
| | | | __ _ ___| |__   / ___|_ __ __ _  ___| | __
| |_| |/ _` / __| '_ \ | |   | '__/ _` |/ __| |/ /
|  _  | (_| \__ \ | | || |___| | | (_| | (__|   <
|_| |_|\__,_|___/_| |_| \____|_|  \__,_|\___|_|\_\

Password Hash Cracker  |  v1.0.0
Dictionary + Rule-based attacks against MD5, SHA1, SHA256, bcrypt
"""
# fmt: on

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from modules.cracker import crack, crack_file
from modules.identifier import identify, identify_many
from modules.hashgen import generate_scenario, generate_challenge_set
from modules.report import save_results
from config import WORDLIST, USE_RULES

app     = typer.Typer(add_completion=False, help="🔓 hashcrack — password hash cracker")
console = Console()


# ── crack command ─────────────────────────────────────────────────────────────

@app.command()
def crack_hash(
    hash_str:  str = typer.Argument(..., help="Hash to crack"),
    hash_type: str = typer.Option("", "--type", "-t",
                       help="Force hash type: md5 | sha1 | sha256 | bcrypt"),
    wordlist:  str = typer.Option(WORDLIST, "--wordlist", "-w",
                       help="Path to wordlist file"),
    no_rules:  bool = typer.Option(False, "--no-rules",
                       help="Skip mutation rules (faster, fewer candidates)"),
    no_save:   bool = typer.Option(False, "--no-save",
                       help="Don't save JSON report"),
) -> None:
    """
    Crack a single password hash.

    Examples:\n
      python hashcrack.py crack-hash 5f4dcc3b5aa765d61d8327deb882cf99\n
      python hashcrack.py crack-hash <sha256> --type sha256\n
      python hashcrack.py crack-hash <hash> --no-rules\n
    """
    # Detect PowerShell $ expansion mangling bcrypt hashes.
    # A valid bcrypt hash is always 60 chars and starts with $2.
    # If we got something that looks like a bcrypt fragment, warn the user.
    h = hash_str.strip()
    if (hash_type == "bcrypt" or h.startswith("$2")) and len(h) < 50:
        console.print(Panel(
            "[bold red]✗  Bcrypt hash looks truncated or corrupted.[/bold red]\n\n"
            "This is almost always a [bold]PowerShell $ expansion[/bold] issue.\n"
            "PowerShell treats [bold]$2b[/bold], [bold]$12[/bold], etc. as variables and strips them.\n\n"
            "Fix: wrap the hash in [bold]single quotes[/bold]:\n"
            "  [bold]python hashcrack.py crack-hash '$2b$12$...'[/bold]\n\n"
            "[dim]Or save the hash to a file and use:\n"
            "  python hashcrack.py crack-file hashes.txt[/dim]",
            title="[bold red]PowerShell Quoting Issue[/bold red]",
            border_style="red",
        ))
        raise typer.Exit(1)

    result = crack(
        hash_str,
        hash_type=hash_type or None,
        wordlist=wordlist,
        use_rules=not no_rules,
    )

    if not no_save:
        path = save_results([result], "single")
        console.print(f"  [dim]📄 Report saved → {path}[/dim]\n")


@app.command()
def crack_file_cmd(
    filepath:  str  = typer.Argument(..., help="File with one hash per line"),
    hash_type: str  = typer.Option("", "--type", "-t", help="Force hash type for all"),
    wordlist:  str  = typer.Option(WORDLIST, "--wordlist", "-w"),
    no_rules:  bool = typer.Option(False, "--no-rules"),
    no_save:   bool = typer.Option(False, "--no-save"),
) -> None:
    """
    Crack multiple hashes from a file (one per line).

    Example:\n
      python hashcrack.py crack-file hashes.txt\n
    """
    if not Path(filepath).exists():
        console.print(f"[red]File not found: {filepath}[/red]")
        raise typer.Exit(1)

    results = crack_file(filepath, hash_type or None, wordlist, not no_rules)

    cracked = sum(1 for r in results if r.cracked)
    console.print()
    console.print(Panel(
        f"[bold]Total:[/bold]   {len(results)}\n"
        f"[bold]Cracked:[/bold] [green]{cracked}[/green]\n"
        f"[bold]Failed:[/bold]  [yellow]{len(results) - cracked}[/yellow]",
        title="[bold]Summary[/bold]",
        border_style="cyan",
    ))

    if not no_save:
        path = save_results(results, Path(filepath).stem)
        console.print(f"  [dim]📄 Report saved → {path}[/dim]\n")


# ── identify command ──────────────────────────────────────────────────────────

@app.command()
def identify_cmd(
    hash_str: str = typer.Argument(..., help="Hash string to identify"),
) -> None:
    """
    Identify the type of a hash without cracking it.

    Examples:\n
      python hashcrack.py identify 5f4dcc3b5aa765d61d8327deb882cf99\n
    """
    info = identify(hash_str.strip())
    console.print()
    console.print(Panel(
        f"[bold]Hash:[/bold]       [cyan]{info.hash_str}[/cyan]\n"
        f"[bold]Type:[/bold]       [yellow]{info.label}[/yellow]\n"
        f"[bold]Confidence:[/bold] {info.confidence}\n"
        f"[bold]Speed:[/bold]      {info.speed}\n\n"
        f"[dim]{info.note}[/dim]",
        title="[bold]🔍 Hash Identification[/bold]",
        border_style="yellow",
    ))


# ── generate command ──────────────────────────────────────────────────────────

@app.command()
def generate(
    difficulty: str = typer.Option("easy", "--difficulty", "-d",
                        help="easy | medium | hard"),
    algo:       str = typer.Option("md5", "--algo", "-a",
                        help="md5 | sha1 | sha256 | bcrypt"),
    count:      int = typer.Option(1, "--count", "-n",
                        help="Number of challenges to generate"),
    show_answer:bool = typer.Option(False, "--reveal",
                        help="Reveal the answer (for testing)"),
    seed:       int = typer.Option(-1, "--seed", help="Random seed"),
) -> None:
    """
    Generate hash cracking challenges for game scenarios.

    Examples:\n
      python hashcrack.py generate --difficulty easy\n
      python hashcrack.py generate --difficulty hard --algo sha256 --count 3\n
      python hashcrack.py generate --reveal  (shows the answer)\n
    """
    console.print()

    seed_val = seed if seed >= 0 else None

    if count == 1:
        scenario = generate_scenario(difficulty, algo, seed=seed_val)
        scenarios = [scenario]
    else:
        scenarios = generate_challenge_set(count, seed=seed_val)

    for i, s in enumerate(scenarios, 1):
        answer_line = f"\n[dim]Answer: [green]{s.password}[/green][/dim]" if show_answer else ""
        console.print(Panel(
            f"[bold]Scenario:[/bold]   {s.title}\n"
            f"[bold]Difficulty:[/bold] {s.difficulty}  |  "
            f"[bold]Algorithm:[/bold] {s.algo.upper()}\n\n"
            f"[dim]{s.context}[/dim]\n\n"
            f"[bold]Hash to crack:[/bold]\n"
            f"[cyan]{s.hash_str}[/cyan]"
            + answer_line,
            title=f"[bold green]🎯 Challenge {i}/{len(scenarios)}[/bold green]",
            border_style="green",
        ))
        console.print()
        if i < len(scenarios):
            console.print(f"  Crack it: [bold]python hashcrack.py crack-hash {s.hash_str}[/bold]\n")


# ── hash command (generate a hash from a known password) ─────────────────────

@app.command()
def hash_password(
    password: str = typer.Argument(..., help="Password to hash"),
    algo:     str = typer.Option("md5", "--algo", "-a",
                      help="md5 | sha1 | sha256 | bcrypt"),
) -> None:
    """
    Hash a password (useful for creating test cases).

    Examples:\n
      python hashcrack.py hash-password dragon --algo sha256\n
      python hashcrack.py hash-password mysecret --algo bcrypt\n
    """
    import hashlib

    console.print()

    if algo == "bcrypt":
        try:
            import bcrypt
            hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode()
        except ImportError:
            console.print("[red]bcrypt not installed: pip install bcrypt[/red]")
            raise typer.Exit(1)
    elif algo in ("md5", "sha1", "sha256", "sha512"):
        hashed = getattr(hashlib, algo)(password.encode()).hexdigest()
    else:
        console.print(f"[red]Unknown algorithm: {algo}[/red]")
        raise typer.Exit(1)

    # bcrypt hashes contain $ signs which PowerShell expands as variables.
    # Warn the user to wrap in single quotes when passing on the command line.
    powershell_note = ""
    if algo == "bcrypt":
        powershell_note = (
            "\n\n[yellow]⚠  PowerShell tip:[/yellow] bcrypt hashes contain [bold]$[/bold] signs.\n"
            "Wrap in [bold]single quotes[/bold] or PowerShell will mangle them:\n"
            f"[bold]python hashcrack.py crack-hash '{hashed}'[/bold]"
        )

    console.print(Panel(
        f"[bold]Password:[/bold]  [dim]{password}[/dim]\n"
        f"[bold]Algorithm:[/bold] {algo.upper()}\n"
        f"[bold]Hash:[/bold]      [cyan]{hashed}[/cyan]\n\n"
        f"[dim]Crack it back: python hashcrack.py crack-hash '{hashed}'[/dim]"
        + powershell_note,
        title="[bold]#️⃣  Hash Generated[/bold]",
        border_style="cyan",
    ))


if __name__ == "__main__":
    app()
