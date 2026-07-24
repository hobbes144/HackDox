"""
Username checker module
-----------------------
Checks 26+ platforms for a given username in parallel.
Uses a combination of HTTP status codes and response body checks
to determine if an account exists.
"""

import asyncio
import httpx
from rich.console import Console
from config import REQUEST_TIMEOUT, MAX_CONCURRENT

console = Console()

# ── Platform definitions ──────────────────────────────────────────────────────
# Each entry: (display_name, url_template, detection_method, not_found_indicator)
# detection_method: "status_code" | "body_text"
# not_found_indicator: HTTP status int, or string that appears in body when NOT found

PLATFORMS = [
    # name,               url template,                                 method,         not-found signal
    ("GitHub",            "https://github.com/{}",                     "status_code",   404),
    ("GitLab",            "https://gitlab.com/{}",                     "status_code",   404),
    ("Bitbucket",         "https://bitbucket.org/{}",                  "status_code",   404),
    ("Reddit",            "https://www.reddit.com/user/{}/about.json", "status_code",   404),
    ("Dev.to",            "https://dev.to/{}",                         "status_code",   404),
    ("npm",               "https://www.npmjs.com/~{}",                 "status_code",   404),
    ("PyPI",              "https://pypi.org/user/{}/",                 "status_code",   404),
    ("HackerNews",        "https://hacker-news.firebaseio.com/v0/user/{}.json", "body_text", "null"),
    ("Keybase",           "https://keybase.io/{}",                     "status_code",   404),
    ("Pastebin",          "https://pastebin.com/u/{}",                 "status_code",   404),
    ("Docker Hub",        "https://hub.docker.com/u/{}",               "status_code",   404),
    ("Gravatar",          "https://en.gravatar.com/{}",                "status_code",   404),
    ("SoundCloud",        "https://soundcloud.com/{}",                 "status_code",   404),
    ("Spotify",           "https://open.spotify.com/user/{}",          "status_code",   404),
    ("Steam",             "https://steamcommunity.com/id/{}",          "body_text",     "The specified profile could not be found"),
    ("Twitch",            "https://www.twitch.tv/{}",                  "status_code",   404),
    ("Pinterest",         "https://www.pinterest.com/{}/",             "status_code",   404),
    ("Medium",            "https://medium.com/@{}",                    "status_code",   404),
    ("Mastodon (infosec.exchange)", "https://infosec.exchange/@{}",    "status_code",   404),
    ("Replit",            "https://replit.com/@{}",                    "status_code",   404),
    ("Codecademy",        "https://www.codecademy.com/profiles/{}",    "status_code",   404),
    ("Figma",             "https://www.figma.com/@{}",                 "status_code",   404),
    ("Kaggle",            "https://www.kaggle.com/{}",                 "status_code",   404),
    ("itch.io",           "https://itch.io/profile/{}",                "status_code",   404),
    ("Linktree",          "https://linktr.ee/{}",                      "status_code",   404),
    ("Venmo",             "https://account.venmo.com/u/{}",            "status_code",   404),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


async def _check_platform(
    name: str,
    url: str,
    method: str,
    not_found: int | str,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    results: list,
) -> None:
    """Check a single platform and append result to results list."""
    async with semaphore:
        try:
            resp = await client.get(
                url,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
                follow_redirects=True,
            )

            if method == "status_code":
                found = resp.status_code != not_found and resp.status_code < 400
            else:  # body_text
                found = not_found not in resp.text

            results.append({
                "platform": name,
                "url": url,
                "found": found,
                "status": resp.status_code,
            })

            # Stream result live
            if found:
                console.print(f"  [green]✓[/green] [bold]{name:<30}[/bold] [dim]{url}[/dim]")
            else:
                console.print(f"  [dim]✗ {name}[/dim]")

        except httpx.TimeoutException:
            console.print(f"  [yellow]⏱ {name} (timeout)[/yellow]")
            results.append({"platform": name, "url": url, "found": False, "status": "timeout"})
        except httpx.RequestError:
            results.append({"platform": name, "url": url, "found": False, "status": "error"})


async def check_username(username: str, client: httpx.AsyncClient) -> list:
    """
    Check all platforms for username in parallel.
    Returns list of result dicts.
    """
    results = []
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    tasks = [
        _check_platform(
            name,
            url.format(username),
            method,
            not_found,
            client,
            semaphore,
            results,
        )
        for name, url, method, not_found in PLATFORMS
    ]

    await asyncio.gather(*tasks)
    return results


def render_username_summary(results: list) -> None:
    """Print a compact summary of found accounts."""
    found = [r for r in results if r["found"]]
    if found:
        console.print(f"\n  [bold green]{len(found)} account(s) found across {len(results)} platforms checked.[/bold green]")
    else:
        console.print(f"\n  [dim]No accounts found across {len(results)} platforms.[/dim]")
