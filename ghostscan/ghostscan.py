#!/usr/bin/env python3
"""
  ██████  ██░ ██  ▒█████    ██████ ▄▄▄█████▓     ██████  ▄████▄   ▄▄▄       ███▄    █
▒██    ▒ ▓██░ ██▒▒██▒  ██▒▒██    ▒ ▓  ██▒ ▓▒   ▒██    ▒ ▒██▀ ▀█  ▒████▄     ██ ▀█   █
░ ▓██▄   ▒██▀▀██░▒██░  ██▒░ ▓██▄   ▒ ▓██░ ▒░   ░ ▓██▄   ▒▓█    ▄ ▒██  ▀█▄  ▓██  ▀█ ██▒
  ▒   ██▒░▓█ ░██ ▒██   ██░  ▒   ██▒░ ▓██▓ ░      ▒   ██▒▒▓▓▄ ▄██▒░██▄▄▄▄██ ▓██▒  ▐▌██▒
▒██████▒▒░▓█▒░██▓░ ████▓▒░▒██████▒▒  ▒██▒ ░    ▒██████▒▒▒ ▓███▀ ░ ▓█   ▓██▒▒██░   ▓██░
▒ ▒▓▒ ▒ ░ ▒ ░░▒░▒░ ▒░▒░▒░ ▒ ▒▓▒ ▒ ░  ▒ ░░      ▒ ▒▓▒ ▒ ░░ ░▒ ▒  ░ ▒▒   ▓▒█░░ ▒░   ▒ ▒
░ ░▒  ░ ░ ▒ ░▒░ ░  ░ ▒ ▒░ ░ ░▒  ░ ░    ░         ░ ░▒  ░ ░  ░  ▒     ▒   ▒▒ ░░ ░░   ░ ▒░
░  ░  ░   ░  ░░ ░░ ░ ░ ▒  ░  ░  ░    ░           ░  ░  ░  ░          ░   ▒      ░   ░ ░
      ░   ░  ░  ░    ░ ░        ░                      ░  ░ ░             ░  ░         ░ ░
                                                          ░
          Open-Source Intelligence Reconnaissance Tool  |  v1.0.0
"""

import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path

import httpx
import typer
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from modules.github_osint import scan_github, render_github
from modules.username_checker import check_username, render_username_summary
from modules.hibp import check_email, render_hibp
from modules.gravatar import check_gravatar, render_gravatar
from modules.report import save_report

app = typer.Typer(
    add_completion=False,
    help="👻 GhostScan — OSINT reconnaissance tool",
)
console = Console()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_email(s: str) -> bool:
    return bool(re.match(r"[^@\s]+@[^@\s]+\.[^@\s]+", s))


def _banner() -> None:
    console.print(
        Panel(
            Text(__doc__, style="bold green", justify="left"),
            border_style="green",
            padding=(0, 1),
        )
    )


def _section(title: str, icon: str = "🔍") -> None:
    console.print()
    console.rule(f"[bold cyan]{icon}  {title}[/bold cyan]", style="cyan")
    console.print()


# ── Main scan ─────────────────────────────────────────────────────────────────

async def _run_scan(target: str, no_save: bool) -> None:
    """Orchestrate all OSINT modules for the given target."""

    is_email   = _is_email(target)
    # If it's an email, derive the username part for platform checks
    username   = target.split("@")[0] if is_email else target

    console.print()
    console.print(
        Panel(
            f"[bold]Target:[/bold]  [cyan]{target}[/cyan]\n"
            f"[bold]Type:[/bold]    {'Email address' if is_email else 'Username'}\n"
            f"[bold]Started:[/bold] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            title="[bold green]👻 GhostScan[/bold green]",
            border_style="green",
        )
    )

    all_results: dict = {}

    async with httpx.AsyncClient(follow_redirects=True) as client:

        # ── GitHub ────────────────────────────────────────────────────────────
        _section("GitHub", "🐙")
        console.print(f"  Scanning [cyan]github.com/{username}[/cyan] ...")
        github_results = await scan_github(username, client)
        render_github(github_results)
        all_results["github"] = github_results

        # ── Username across platforms ─────────────────────────────────────────
        _section("Username — Platform Check", "🌐")
        console.print(f"  Checking [cyan]{username}[/cyan] across 26 platforms...\n")
        username_results = await check_username(username, client)
        render_username_summary(username_results)
        all_results["username_check"] = username_results

        # ── Email-only modules ────────────────────────────────────────────────
        if is_email:
            # HIBP
            _section("Have I Been Pwned", "🔓")
            console.print(f"  Checking [cyan]{target}[/cyan] against breach databases...")
            hibp_results = await check_email(target, client)
            render_hibp(hibp_results)
            all_results["hibp"] = hibp_results

            # Gravatar
            _section("Gravatar", "🖼️")
            console.print(f"  Looking up [cyan]{target}[/cyan] on Gravatar...")
            gravatar_results = await check_gravatar(target, client)
            render_gravatar(gravatar_results)
            all_results["gravatar"] = gravatar_results

    # ── Summary ───────────────────────────────────────────────────────────────
    console.print()
    console.rule("[bold green]✅  Scan Complete[/bold green]", style="green")
    console.print()

    found_on = [
        r["platform"]
        for r in all_results.get("username_check", [])
        if r.get("found")
    ]

    summary_lines = []
    if github_results.get("found"):
        summary_lines.append(f"  [green]✓[/green] GitHub account found")
        if github_results.get("leaked_emails"):
            summary_lines.append(
                f"  [yellow]⚠[/yellow] {len(github_results['leaked_emails'])} email(s) leaked in commit history"
            )
    if found_on:
        summary_lines.append(
            f"  [green]✓[/green] Active on [bold]{len(found_on)}[/bold] platform(s): "
            + ", ".join(found_on[:6])
            + ("..." if len(found_on) > 6 else "")
        )
    if is_email:
        breaches = all_results.get("hibp", {}).get("breaches", [])
        if breaches:
            summary_lines.append(
                f"  [red]⚠[/red] Email in [bold]{len(breaches)}[/bold] known data breach(es)"
            )
        if all_results.get("gravatar", {}).get("found"):
            summary_lines.append("  [green]✓[/green] Gravatar profile found")

    if summary_lines:
        console.print(Panel("\n".join(summary_lines), title="[bold]Summary[/bold]", border_style="green"))
    else:
        console.print(Panel("  [dim]No significant findings.[/dim]", border_style="dim"))

    # ── Save report ───────────────────────────────────────────────────────────
    if not no_save:
        path = save_report(target, all_results)
        console.print(f"\n  [dim]📄 Report saved → {path}[/dim]")

    console.print()


# ── CLI commands ──────────────────────────────────────────────────────────────

@app.command()
def scan(
    target: str = typer.Argument(..., help="Username or email address to investigate"),
    no_save: bool = typer.Option(False, "--no-save", help="Don't save a JSON report"),
) -> None:
    """
    Run a full OSINT scan on a username or email address.

    Examples:\n
      python ghostscan.py scan torvalds\n
      python ghostscan.py scan user@example.com\n
    """
    asyncio.run(_run_scan(target, no_save))


@app.command()
def version() -> None:
    """Print ghostscan version."""
    console.print("[bold green]ghostscan[/bold green] v1.0.0")


if __name__ == "__main__":
    app()
