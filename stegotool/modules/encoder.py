"""
encoder.py — Payload obfuscation layers for stegotool.

Difficulty scaling:
  easy   → plaintext (raw UTF-8 bytes)
  medium → base64-encoded (obscures structure, not encrypted)
  hard   → XOR-keyed "encryption" (requires knowing the key to decode)

XOR is not production-grade crypto — it's intentionally breakable for the
game, teaching players about weak encryption vs proper cipher suites.
"""

import base64
import hashlib


# ── Key derivation ────────────────────────────────────────────────────────────

def _derive_key(password: str, length: int) -> bytes:
    """Stretch a password into `length` key bytes using SHA-256 cycling."""
    digest = hashlib.sha256(password.encode()).digest()
    key = b""
    while len(key) < length:
        key += digest
        digest = hashlib.sha256(digest).digest()
    return key[:length]


# ── Encoding ─────────────────────────────────────────────────────────────────

def encode(message: str, difficulty: str, key: str | None = None) -> bytes:
    """
    Encode a plaintext message into bytes ready for LSB embedding.

    difficulty:
        "easy"   → raw UTF-8
        "medium" → base64(UTF-8)
        "hard"   → XOR(base64(UTF-8), derived key)  [key required]
    """
    raw = message.encode("utf-8")

    if difficulty == "easy":
        return raw

    b64 = base64.b64encode(raw)

    if difficulty == "medium":
        return b64

    # hard — XOR with derived key
    if not key:
        raise ValueError("Difficulty 'hard' requires a --key argument")
    k = _derive_key(key, len(b64))
    return bytes(a ^ b for a, b in zip(b64, k))


def decode(payload: bytes, difficulty: str, key: str | None = None) -> str:
    """
    Decode bytes extracted from LSB back into a plaintext string.
    Mirrors encode() exactly in reverse.
    """
    if difficulty == "easy":
        return payload.decode("utf-8", errors="replace")

    if difficulty == "medium":
        try:
            return base64.b64decode(payload).decode("utf-8", errors="replace")
        except Exception:
            return payload.decode("utf-8", errors="replace")

    # hard — reverse XOR then base64
    if not key:
        raise ValueError("Difficulty 'hard' requires a --key argument to decode")
    k = _derive_key(key, len(payload))
    b64 = bytes(a ^ b for a, b in zip(payload, k))
    try:
        return base64.b64decode(b64).decode("utf-8", errors="replace")
    except Exception:
        return "[decryption failed — wrong key?]"


# ── Difficulty labels ────────────────────────────────────────────────────────

DIFFICULTY_LABELS = {
    "easy":   "PLAINTEXT  — no encoding",
    "medium": "BASE64     — obscured structure",
    "hard":   "XOR+BASE64 — key required to decode",
}
