#!/usr/bin/env python3
"""
 _                          _       _       _
| |    ___   __ ___      __| |     / \  ___| |__
| |   / _ \ / _` \ \ /\ / / |    / _ \/ __| '_ \\
| |__| (_) | (_| |\ V  V /| |   / ___ \__ \ | | |
|_____\___/ \__, | \_/\_/ |_|  /_/   \_\___/_| |_|
            |___/

Log Analyzer & Threat Detection Tool  |  v1.0.0
"""

import asyncio
import sys
from pathlib import Path

import httpx
import typer
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

from modules.parsers import auth_log, web_log, windows_log
from modules.detectors import brute_force, anomaly
from modules.geoip import lookup_all
from modules.logforge import forge, SCENARIOS
from modules.report import render_findings, save_report

app     = typer.Typer(add_completion=False, help="🔍 logwatch — log analysis & threat detection")
console = Console()


# ── Auto-detect log format ────────────────────────────────────────────────────

def _detect_format(path: str) -> str:
    """Guess the log format from the filename or content."""
    p = path.lower()
    if "auth" in p or "secure" in p or "sshd" in p:
        return "auth"
    if "access" in p or "web" in p or "nginx" in p or "apache" in p:
        return "web"
    if "security" in p or "event" in p or "windows" in p:
        return "windows"

    # Peek at first line to decide
    try:
        with open(path) as f:
            first = f.readline()
        if "sshd" in first or "sudo" in first or "Failed password" in first:
            return "auth"
        if "HTTP/" in first or '"GET ' in first or '"POST ' in first:
            return "web"
        if "Event ID" in first or "EventID" in first or "4625" in first:
            return "windows"
    except Exception:
        pass

    return "auth"  # default


# ── Commands ──────────────────────────────────────────────────────────────────

@app.command()
def analyze(
    log_file: str = typer.Argument(..., help="Path to log file to analyze"),
    fmt: str      = typer.Option("auto", "--format", "-f",
                        help="Log format: auto | auth | web | windows"),
    no_geo: bool  = typer.Option(False, "--no-geo", help="Skip IP geolocation lookups"),
    no_save: bool = typer.Option(False, "--no-save", help="Don't save JSON report"),
) -> None:
    """
    Analyze a log file and report security threats.

    Examples:\n
      python logwatch.py analyze /var/log/auth.log\n
      python logwatch.py analyze sample_logs/ssh_attack.log\n
      python logwatch.py analyze sample_logs/web_attack.log --format web\n
    """
    asyncio.run(_run_analyze(log_file, fmt, no_geo, no_save))


@app.command()
def forge_log(
    scenario:   str = typer.Argument(..., help=f"Scenario: {', '.join(SCENARIOS.keys())}"),
    difficulty: str = typer.Option("medium", "--difficulty", "-d", help="easy | medium | hard"),
    fmt:        str = typer.Option("auth", "--format", "-f", help="auth | web"),
    output:     str = typer.Option("", "--output", "-o", help="Output file path (default: auto)"),
    seed:       int = typer.Option(-1, "--seed", help="Random seed for reproducibility"),
) -> None:
    """
    Generate a synthetic log file with a planted attack scenario.

    Examples:\n
      python logwatch.py forge-log brute_force --difficulty easy\n
      python logwatch.py forge-log web_scan --format web --difficulty hard\n
      python logwatch.py forge-log impossible_travel --seed 42\n
    """
    console.print()
    console.print(Panel(
        f"[bold]Scenario:[/bold]   {scenario}\n"
        f"[bold]Difficulty:[/bold] {difficulty}\n"
        f"[bold]Format:[/bold]     {fmt}",
        title="[bold green]🔧 LogForge[/bold green]",
        border_style="green",
    ))
    console.print()

    try:
        log_text, meta = forge(
            scenario,
            difficulty=difficulty,
            fmt=fmt,
            seed=seed if seed >= 0 else None,
        )
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    # Determine output path
    if not output:
        out_dir = Path(__file__).parent / "sample_logs"
        out_dir.mkdir(exist_ok=True)
        ext = "log"
        output = str(out_dir / f"{scenario}_{difficulty}.{ext}")

    with open(output, "w") as f:
        f.write(log_text)

    console.print(f"  [green]✓[/green] Generated [bold]{meta['total_lines']}[/bold] log lines "
                  f"({meta['attack_lines']} attack events hidden in noise)")
    console.print(f"  [dim]Saved to: {output}[/dim]")
    console.print()
    console.print(f"  [yellow]🎯 Challenge:[/yellow] Find the [bold]{meta['answer_key'].get('category', scenario)}[/bold] attack")
    console.print(f"  [dim]Hint: {meta['answer_key'].get('look_for', '')}[/dim]")
    console.print()
    console.print(f"  Run: [bold]python logwatch.py analyze {output}[/bold]")
    console.print()


@app.command()
def scenarios() -> None:
    """List all available forge scenarios."""
    from rich.table import Table
    from rich import box

    table = Table(box=box.SIMPLE, header_style="bold cyan")
    table.add_column("Scenario", style="green bold")
    table.add_column("What it simulates", style="dim")
    table.add_column("Format")

    rows = [
        ("brute_force",         "Many password failures from one IP → eventual success", "auth"),
        ("credential_stuffing", "One IP testing hundreds of different usernames",         "auth"),
        ("impossible_travel",   "Same user logs in from two countries minutes apart",    "auth"),
        ("after_hours",         "Legitimate user suddenly active at 3am",                "auth"),
        ("insider_threat",      "Remote login → immediate privilege escalation chain",   "auth"),
        ("web_scan",            "Automated vulnerability scanner probing your site",     "web"),
        ("slow_burn",           "APT-style distributed brute force over hours",          "auth"),
    ]
    for name, desc, fmt in rows:
        table.add_row(name, desc, fmt)

    console.print()
    console.print(table)
    console.print()


# ── Core analysis logic ───────────────────────────────────────────────────────

async def _run_analyze(log_file: str, fmt: str, no_geo: bool, no_save: bool) -> None:
    if not Path(log_file).exists():
        console.print(f"[red]File not found: {log_file}[/red]")
        raise typer.Exit(1)

    if fmt == "auto":
        fmt = _detect_format(log_file)

    console.print()
    console.print(Panel(
        f"[bold]File:[/bold]   {log_file}\n"
        f"[bold]Format:[/bold] {fmt}\n"
        f"[bold]Geo:[/bold]    {'disabled' if no_geo else 'enabled (ip-api.com)'}",
        title="[bold cyan]🔍 logwatch[/bold cyan]",
        border_style="cyan",
    ))

    # ── Parse ──────────────────────────────────────────────────────────────────
    console.print()
    console.print("  Parsing log file...", end=" ")
    if fmt == "auth":
        entries = auth_log.parse_file(log_file)
    elif fmt == "web":
        entries = web_log.parse_file(log_file)
    elif fmt == "windows":
        entries = windows_log.parse_file(log_file)
    else:
        console.print(f"[red]Unknown format: {fmt}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]{len(entries):,} events parsed[/green]")

    if not entries:
        console.print("[yellow]  No parseable events found.[/yellow]")
        return

    # ── Geolocate unique IPs ───────────────────────────────────────────────────
    geo_cache = {}
    if not no_geo:
        unique_ips = {e.source_ip for e in entries if e.source_ip not in ("local", "unknown")}
        if unique_ips:
            console.print(f"  Geolocating {len(unique_ips)} unique IP(s)...", end=" ")
            async with httpx.AsyncClient() as client:
                geo_cache = await lookup_all(unique_ips, client)
            console.print(f"[green]{len(geo_cache)} resolved[/green]")

    # ── Detect ─────────────────────────────────────────────────────────────────
    console.print("  Running threat detectors...")
    findings = []
    findings += brute_force.detect(entries)
    findings += anomaly.detect(entries, geo_cache)
    console.print(f"  [bold]{len(findings)}[/bold] finding(s) identified\n")

    # ── Report ─────────────────────────────────────────────────────────────────
    console.rule("[bold cyan]Results[/bold cyan]", style="cyan")
    render_findings(findings, log_file)

    if not no_save and findings:
        path = save_report(findings, log_file)
        console.print(f"\n  [dim]📄 Report saved → {path}[/dim]")

    console.print()


if __name__ == "__main__":
    app()
