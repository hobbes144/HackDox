"""
Report module
-------------
Renders findings to the terminal and saves a JSON report.
"""

import json
from datetime import datetime
from pathlib import Path
from modules.models import Finding, Severity, SEVERITY_COLOR, SEVERITY_ICON
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

console  = Console()
OUT_DIR  = Path(__file__).parent.parent / "output"


def render_findings(findings: list[Finding], log_file: str) -> None:
    """Render all findings to the terminal as a sorted, color-coded report."""
    if not findings:
        console.print(Panel(
            "[green]✓  No threats detected.[/green]\n"
            "[dim]All log activity appears normal.[/dim]",
            title="[bold]Scan Complete[/bold]",
            border_style="green",
        ))
        return

    # Sort: CRITICAL first
    ORDER = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]
    findings = sorted(findings, key=lambda f: ORDER.index(f.severity))

    console.print()
    console.print(Panel(
        f"[bold]Source:[/bold] {log_file}\n"
        f"[bold]Findings:[/bold] {len(findings)}  "
        f"([red]{sum(1 for f in findings if f.severity == Severity.CRITICAL)} CRITICAL[/red]  "
        f"[yellow]{sum(1 for f in findings if f.severity == Severity.HIGH)} HIGH[/yellow]  "
        f"{sum(1 for f in findings if f.severity == Severity.MEDIUM)} MEDIUM  "
        f"[dim]{sum(1 for f in findings if f.severity == Severity.LOW)} LOW[/dim])",
        title="[bold red]⚠  Threat Report[/bold red]",
        border_style="red",
    ))

    for i, f in enumerate(findings, 1):
        color = SEVERITY_COLOR[f.severity]
        icon  = SEVERITY_ICON[f.severity]

        console.print()
        console.print(f"[{color}]{icon} [{f.severity}] Finding #{i}: {f.title}[/{color}]")
        console.print(f"  [dim]Category:[/dim] {f.category}")
        console.print(f"  [dim]Time:[/dim]     {f.first_seen.strftime('%H:%M:%S')} → {f.last_seen.strftime('%H:%M:%S')}")
        if f.source_ip:
            console.print(f"  [dim]Source IP:[/dim] {f.source_ip}")
        if f.username:
            console.print(f"  [dim]User:[/dim]     {f.username}")
        if f.geo:
            console.print(f"  [dim]Location:[/dim] {f.geo.city}, {f.geo.country} ({f.geo.isp})")
        console.print(f"  [dim]Events:[/dim]   {f.event_count}")
        console.print(f"\n  {f.description}")

        if f.evidence:
            console.print("\n  [dim]Evidence (first matching log lines):[/dim]")
            for e in f.evidence[:3]:
                console.print(f"  [dim]  → {e.raw[:120]}[/dim]")


def save_report(findings: list[Finding], log_file: str) -> str:
    """Save findings to a JSON file. Returns the output path."""
    OUT_DIR.mkdir(exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem     = Path(log_file).stem
    out_path = OUT_DIR / f"logwatch_{stem}_{ts}.json"

    report = {
        "logwatch_version": "1.0.0",
        "scanned_at":       datetime.now().isoformat(),
        "source_file":      log_file,
        "finding_count":    len(findings),
        "findings": [
            {
                "severity":    f.severity,
                "category":    f.category,
                "title":       f.title,
                "description": f.description,
                "source_ip":   f.source_ip,
                "username":    f.username,
                "first_seen":  f.first_seen.isoformat(),
                "last_seen":   f.last_seen.isoformat(),
                "event_count": f.event_count,
            }
            for f in findings
        ],
    }

    with open(out_path, "w") as fp:
        json.dump(report, fp, indent=2, default=str)

    return str(out_path)
