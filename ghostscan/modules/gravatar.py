"""
Gravatar module
---------------
Looks up a Gravatar profile from an email address.
Gravatar is free and requires no API key — emails are hashed with MD5.
"""

import hashlib
import httpx
from rich.console import Console
from config import REQUEST_TIMEOUT

console = Console()


def _email_hash(email: str) -> str:
    return hashlib.md5(email.strip().lower().encode()).hexdigest()


async def check_gravatar(email: str, client: httpx.AsyncClient) -> dict:
    """Look up Gravatar profile for an email. Returns results dict."""
    results = {
        "found": False,
        "email": email,
        "hash": "",
        "profile_url": "",
        "avatar_url": "",
        "display_name": None,
        "location": None,
        "about": None,
        "accounts": [],
    }

    h = _email_hash(email)
    results["hash"] = h
    results["avatar_url"] = f"https://www.gravatar.com/avatar/{h}?d=404"
    results["profile_url"] = f"https://gravatar.com/{h}"

    try:
        # Check if avatar exists (returns 404 if not registered)
        resp = await client.get(
            f"https://www.gravatar.com/avatar/{h}?d=404",
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 404:
            return results

        results["found"] = True

        # Fetch JSON profile
        profile_resp = await client.get(
            f"https://www.gravatar.com/{h}.json",
            timeout=REQUEST_TIMEOUT,
        )
        if profile_resp.status_code == 200:
            data = profile_resp.json()
            entry = data.get("entry", [{}])[0]
            results["display_name"] = entry.get("displayName")
            results["location"] = entry.get("currentLocation")
            results["about"] = entry.get("aboutMe")
            results["accounts"] = [
                {"shortname": a.get("shortname"), "url": a.get("url")}
                for a in entry.get("accounts", [])
            ]

    except httpx.RequestError:
        pass

    return results


def render_gravatar(results: dict) -> None:
    """Pretty-print Gravatar results."""
    if not results["found"]:
        console.print("  [dim]No Gravatar profile found for this email.[/dim]")
        return

    console.print(f"  [green]✓  Gravatar profile found[/green]")
    console.print(f"  [bold]Profile:[/bold] {results['profile_url']}")
    console.print(f"  [bold]Avatar:[/bold]  {results['avatar_url']}")

    if results.get("display_name"):
        console.print(f"  [bold]Name:[/bold]    {results['display_name']}")
    if results.get("location"):
        console.print(f"  [bold]Location:[/bold] {results['location']}")
    if results.get("about"):
        console.print(f"  [bold]About:[/bold]   {results['about'][:200]}")

    if results.get("accounts"):
        console.print("  [bold]Linked accounts:[/bold]")
        for acct in results["accounts"]:
            console.print(f"    [cyan]{acct['shortname']}[/cyan] → {acct.get('url', '')}")
