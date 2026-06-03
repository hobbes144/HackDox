"""
IP Geolocation module
----------------------
Uses the free ip-api.com service (no API key needed, 45 req/min limit).
Results are cached so each IP is only looked up once per scan.
Private/local IPs are skipped.
"""

import asyncio
import httpx
from modules.models import GeoLocation
from config import GEO_TIMEOUT, ENABLE_GEOIP

_PRIVATE_PREFIXES = ("10.", "192.168.", "172.", "127.", "::1", "local", "unknown")


def _is_private(ip: str) -> bool:
    return any(ip.startswith(p) for p in _PRIVATE_PREFIXES)


async def lookup_ip(ip: str, client: httpx.AsyncClient) -> GeoLocation | None:
    """Look up geolocation for a single IP. Returns None for private/local IPs."""
    if not ENABLE_GEOIP or _is_private(ip):
        return None
    try:
        resp = await client.get(
            f"http://ip-api.com/json/{ip}",
            timeout=GEO_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get("status") != "success":
            return None
        return GeoLocation(
            ip=ip,
            country=data.get("country", "Unknown"),
            country_code=data.get("countryCode", "??"),
            city=data.get("city", "Unknown"),
            lat=float(data.get("lat", 0)),
            lon=float(data.get("lon", 0)),
            isp=data.get("isp", "Unknown"),
        )
    except Exception:
        return None


async def lookup_all(ips: set[str], client: httpx.AsyncClient) -> dict[str, GeoLocation]:
    """
    Look up geolocation for a set of IPs concurrently.
    Returns a dict mapping IP → GeoLocation.
    """
    results: dict[str, GeoLocation] = {}
    # ip-api.com: max 45 requests/min on free tier — pace slightly
    semaphore = asyncio.Semaphore(10)

    async def _lookup(ip: str):
        async with semaphore:
            geo = await lookup_ip(ip, client)
            if geo:
                results[ip] = geo
            await asyncio.sleep(0.1)  # gentle rate limiting

    await asyncio.gather(*[_lookup(ip) for ip in ips])
    return results
