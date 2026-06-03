"""
GitHub OSINT module
-------------------
Queries the GitHub API for:
  - User profile (name, bio, location, email, followers, etc.)
  - Public repositories
  - Emails leaked in commit history
"""

import httpx
from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich import box
from config import GITHUB_TOKEN, REQUEST_TIMEOUT

console = Console()

HEADERS = {"Accept": "application/vnd.github+json"}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"


async def scan_github(username: str, client: httpx.AsyncClient) -> dict:
    """Run full GitHub OSINT on a username. Returns a results dict."""
    results = {
        "found": False,
        "profile": {},
        "repos": [],
        "leaked_emails": [],
        "errors": [],
    }

    # ── 1. User profile ──────────────────────────────────────────────────────
    try:
        resp = await client.get(
            f"https://api.github.com/users/{username}",
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 404:
            return results
        if resp.status_code == 403:
            results["errors"].append("GitHub rate limit hit — add a GITHUB_TOKEN in config.py")
            return results
        resp.raise_for_status()

        data = resp.json()
        results["found"] = True
        results["profile"] = {
            "login":       data.get("login"),
            "name":        data.get("name"),
            "email":       data.get("email"),
            "bio":         data.get("bio"),
            "location":    data.get("location"),
            "company":     data.get("company"),
            "blog":        data.get("blog"),
            "public_repos": data.get("public_repos"),
            "followers":   data.get("followers"),
            "following":   data.get("following"),
            "created_at":  data.get("created_at"),
            "avatar_url":  data.get("avatar_url"),
            "html_url":    data.get("html_url"),
        }
    except httpx.RequestError as e:
        results["errors"].append(f"GitHub profile request failed: {e}")
        return results

    # ── 2. Repositories ──────────────────────────────────────────────────────
    try:
        resp = await client.get(
            f"https://api.github.com/users/{username}/repos",
            headers=HEADERS,
            params={"per_page": 30, "sort": "updated"},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 200:
            for repo in resp.json():
                results["repos"].append({
                    "name":        repo.get("name"),
                    "description": repo.get("description"),
                    "language":    repo.get("language"),
                    "stars":       repo.get("stargazers_count"),
                    "forks":       repo.get("forks_count"),
                    "url":         repo.get("html_url"),
                    "updated_at":  repo.get("updated_at"),
                })
    except httpx.RequestError:
        pass

    # ── 3. Emails leaked in commit history ───────────────────────────────────
    try:
        resp = await client.get(
            f"https://api.github.com/search/commits",
            headers={**HEADERS, "Accept": "application/vnd.github.cloak-preview+json"},
            params={"q": f"author:{username}", "per_page": 30},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 200:
            emails = set()
            for item in resp.json().get("items", []):
                author = item.get("commit", {}).get("author", {})
                email = author.get("email", "")
                if email and not email.endswith("@users.noreply.github.com"):
                    emails.add(email)
            results["leaked_emails"] = list(emails)
    except httpx.RequestError:
        pass

    return results


def render_github(results: dict) -> None:
    """Pretty-print GitHub results to the terminal."""
    if not results["found"]:
        console.print("  [dim]No GitHub account found[/dim]")
        return

    p = results["profile"]

    # Profile panel
    lines = []
    if p.get("name"):        lines.append(f"[bold]Name:[/bold]      {p['name']}")
    if p.get("email"):       lines.append(f"[bold]Email:[/bold]     [cyan]{p['email']}[/cyan]")
    if p.get("bio"):         lines.append(f"[bold]Bio:[/bold]       {p['bio']}")
    if p.get("location"):    lines.append(f"[bold]Location:[/bold]  {p['location']}")
    if p.get("company"):     lines.append(f"[bold]Company:[/bold]   {p['company']}")
    if p.get("blog"):        lines.append(f"[bold]Website:[/bold]   {p['blog']}")
    lines.append(f"[bold]Repos:[/bold]     {p.get('public_repos', 0)}  |  "
                 f"[bold]Followers:[/bold] {p.get('followers', 0)}  |  "
                 f"[bold]Following:[/bold] {p.get('following', 0)}")
    if p.get("created_at"):  lines.append(f"[bold]Joined:[/bold]    {p['created_at'][:10]}")
    lines.append(f"[bold]URL:[/bold]       [link={p['html_url']}]{p['html_url']}[/link]")

    console.print("\n".join(lines))

    # Leaked emails
    if results["leaked_emails"]:
        console.print(f"\n  [yellow]⚠  Emails found in commit history:[/yellow]")
        for email in results["leaked_emails"]:
            console.print(f"     [cyan]{email}[/cyan]")

    # Top repos table
    if results["repos"]:
        table = Table(
            box=box.SIMPLE,
            show_header=True,
            header_style="bold magenta",
            padding=(0, 1),
            expand=False,
        )
        table.add_column("Repository", style="green", no_wrap=True)
        table.add_column("Language", style="cyan")
        table.add_column("★", justify="right")
        table.add_column("Description", style="dim", max_width=50)

        for repo in results["repos"][:10]:
            table.add_row(
                repo["name"],
                repo.get("language") or "—",
                str(repo.get("stars", 0)),
                repo.get("description") or "—",
            )
        console.print()
        console.print(table)

    for err in results["errors"]:
        console.print(f"  [red]⚠  {err}[/red]")
