"""
Hash identifier
---------------
Determines the hash type from its string format alone.

How it works:
  - MD5    → 32 hex characters
  - SHA1   → 40 hex characters
  - SHA256 → 64 hex characters
  - bcrypt → starts with $2b$, $2a$, or $2y$ followed by cost factor

Note: MD5 and NTLM are both 32 hex chars — context tells them apart.
This tool assumes 32-char hex = MD5 unless told otherwise.
"""

import re
from dataclasses import dataclass

_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")

# Known hash formats
HASH_TYPES = {
    "md5":    {"length": 32,  "hex": True,  "label": "MD5",    "speed": "very fast"},
    "sha1":   {"length": 40,  "hex": True,  "label": "SHA1",   "speed": "fast"},
    "sha256": {"length": 64,  "hex": True,  "label": "SHA256", "speed": "fast"},
    "bcrypt": {"length": None, "hex": False, "label": "bcrypt", "speed": "very slow (by design)"},
}

BCRYPT_PREFIXES = ("$2b$", "$2a$", "$2y$")


@dataclass
class HashInfo:
    hash_str:   str
    hash_type:  str          # "md5", "sha1", "sha256", "bcrypt", "unknown"
    label:      str          # human-readable
    speed:      str          # cracking speed expectation
    confidence: str          # "high", "medium", "low"
    note:       str = ""


def identify(hash_str: str) -> HashInfo:
    """
    Identify the type of a hash string.
    Returns a HashInfo with type, label, and confidence.
    """
    h = hash_str.strip()

    # ── bcrypt ────────────────────────────────────────────────────────────────
    if any(h.startswith(p) for p in BCRYPT_PREFIXES):
        return HashInfo(
            hash_str=h, hash_type="bcrypt", label="bcrypt",
            speed="very slow (by design)",
            confidence="high",
            note="bcrypt is a password hashing function designed to be slow. "
                 "Cracking is computationally expensive by design.",
        )

    # ── Hex-based hashes ──────────────────────────────────────────────────────
    if _HEX_RE.match(h):
        length = len(h)
        if length == 32:
            return HashInfo(
                hash_str=h, hash_type="md5", label="MD5",
                speed="very fast",
                confidence="high",
                note="MD5 is broken for security purposes. "
                     "Can be cracked in milliseconds with a dictionary attack.",
            )
        elif length == 40:
            return HashInfo(
                hash_str=h, hash_type="sha1", label="SHA1",
                speed="fast",
                confidence="high",
                note="SHA1 is deprecated. Crackable in seconds with a dictionary.",
            )
        elif length == 64:
            return HashInfo(
                hash_str=h, hash_type="sha256", label="SHA256",
                speed="fast",
                confidence="high",
                note="SHA256 is cryptographically sound but not designed for "
                     "password storage. Without a salt, dictionary attacks work well.",
            )
        elif length == 56:
            return HashInfo(
                hash_str=h, hash_type="sha224", label="SHA224",
                speed="fast",
                confidence="medium",
                note="SHA224 — uncommon for passwords.",
            )
        elif length == 96:
            return HashInfo(
                hash_str=h, hash_type="sha384", label="SHA384",
                speed="moderate",
                confidence="medium",
                note="SHA384 — uncommon for passwords.",
            )
        elif length == 128:
            return HashInfo(
                hash_str=h, hash_type="sha512", label="SHA512",
                speed="moderate",
                confidence="medium",
                note="SHA512 — stronger but still dictionary-attackable without a salt.",
            )

    # ── Unknown ───────────────────────────────────────────────────────────────
    return HashInfo(
        hash_str=h, hash_type="unknown", label="Unknown",
        speed="unknown",
        confidence="low",
        note=f"Could not identify hash type. Length: {len(h)} chars.",
    )


def identify_many(hashes: list[str]) -> list[HashInfo]:
    """Identify a list of hashes."""
    return [identify(h) for h in hashes]
