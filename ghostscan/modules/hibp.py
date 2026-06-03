"""
HaveIBeenPwned module
---------------------
Checks if an email address appears in known data breaches.

Free tier  → lists all public breaches (no email lookup)
API key    → looks up the specific email (set HIBP_API_KEY in config.py)
Get a key  → https://haveibeenpwned.com/API/Key
"""

import httpx
from rich.console import Console
from rich.table import Table
from rich import box
from config import HIBP_API_KEY, REQUEST_TIMEOUT

console = Console()

HIBP_BASE = "https://haveibeenpwned.com/api/v3"


async def check_email(email: str, client: httpx.AsyncClient) -> dict:
    """Check email against HIBP. Returns results dict."""
    results = {
        "email": email,
        "breaches": [],
        "pastes": [],
        "has_api_key": bool(HIBP_API_KEY),
        "error": None,
    }

    if not HIBP_API_KEY:
        results["error"] = "no_api_key"
        return results

    headers = {
        "hibp-api-key": HIBP_API_KEY,
        "user-agent": "ghostscan-osint-tool",
    }

    # ── Breaches ──────────────────────────────────────────────────────────────
    try:
        resp = await client.get(
            f"{HIBP_BASE}/breachedaccount/{email}",
            headers=headers,
            params={"truncateResponse": "false"},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 200:
            for breach in resp.json():
                results["breaches"].append({
                    "name":         breach.get("Name"),
                    "domain":       breach.get("Domain"),
                    "breach_date":  breach.get("BreachDate"),
                    "pwn_count":    breach.get("PwnCount"),
                    "description":  breach.get("Description", "")[:120],
                    "data_classes": breach.get("DataClasses", []),
                })
        elif resp.status_code == 404:
            pass  # clean email
        elif resp.status_code == 401:
            results["error"] = "invalid_api_key"
        elif resp.status_code == 429:
            results["error"] = "rate_limited"
    except httpx.RequestError as e:
        results["error"] = str(e)

    # ── Pastes ────────────────────────────────────────────────────────────────
    try:
        resp = await client.get(
            f"{HIBP_BASE}/pasteaccount/{email}",
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 200:
            for paste in resp.json():
                results["pastes"].append({
                    "source": paste.get("Source"),
                    "id":     paste.get("Id"),
                    "date":   paste.get("Date"),
                    "count":  paste.get("EmailCount"),
                })
    except httpx.RequestError:
        pass

    return results


def render_hibp(results: dict) -> None:
    """Pretty-print HIBP results."""
    if results["error"] == "no_api_key":
        console.print(
            "  [yellow]⚠  No HIBP API key configured.[/yellow]\n"
            "  [dim]Add your key to config.py → HIBP_API_KEY[/dim]\n"
            "  [dim]Get a free key at: https://haveibeenpwned.com/API/Key[/dim]"
        )
        return

    if results["error"] == "invalid_api_key":
        console.print("  [red]✗  Invalid HIBP API key.[/red]")
        return

    if results["error"] == "rate_limited":
        console.print("  [yellow]⚠  HIBP rate limited — try again in a moment.[/yellow]")
        return

    if results["error"]:
        console.print(f"  [red]✗  HIBP error: {results['error']}[/red]")
        return

    breaches = results["breaches"]
    pastes   = results["pastes"]

    if not breaches and not pastes:
        console.print("  [green]✓  No breaches found — this email looks clean.[/green]")
        return

    if breaches:
        console.print(f"  [bold red]⚠  Found in {len(breaches)} breach(es):[/bold red]\n")
        table = Table(
            box=box.SIMPLE,
            show_header=True,
            header_style="bold red",
            padding=(0, 1),
        )
        table.add_column("Breach",      style="red bold", no_wrap=True)
        table.add_column("Date",        style="dim")
        table.add_column("Records",     justify="right")
        table.add_column("Data Leaked", style="yellow")

        for b in breaches:
            table.add_row(
                b["name"],
                b.get("breach_date", "?"),
                f"{b.get('pwn_count', 0):,}",
                ", ".join(b.get("data_classes", [])[:4]),
            )
        console.print(table)

    if pastes:
        console.print(f"\n  [yellow]Found in {len(pastes)} paste(s) (Pastebin etc.)[/yellow]")
