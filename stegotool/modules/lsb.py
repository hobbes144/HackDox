"""
lsb.py — Least Significant Bit steganography engine.

Architecture
────────────
Each byte of payload is split into individual bits and stored in the LSBs of
selected colour channels across sequential pixels.

Embedded stream layout (in bits):
  [MAGIC_HEADER (8 bytes)] [LENGTH (4 bytes, big-endian uint32)] [PAYLOAD (N bytes)] [DELIMITER (4 bytes)]

Channel selection is controlled by config.DIFFICULTY_CHANNELS:
  easy   → blue channel only   (most obvious to a detector)
  medium → red + blue channels (requires checking 2 planes)
  hard   → R + G + B           (maximum capacity, hardest to isolate)
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from config import MAGIC_HEADER, MESSAGE_DELIMITER, MAX_MESSAGE_BYTES, DIFFICULTY_CHANNELS


# ── Bit-level helpers ────────────────────────────────────────────────────────

def _bytes_to_bits(data: bytes) -> list[int]:
    bits = []
    for byte in data:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    return bits


def _bits_to_bytes(bits: list[int]) -> bytes:
    result = bytearray()
    for i in range(0, len(bits) - 7, 8):
        byte = 0
        for j in range(8):
            byte = (byte << 1) | bits[i + j]
        result.append(byte)
    return bytes(result)


# ── Capacity check ────────────────────────────────────────────────────────────

def image_capacity(img: Image.Image, channels: list[int]) -> int:
    """Return max bytes that can be hidden given the channel list."""
    arr = np.array(img)
    h, w = arr.shape[:2]
    bits_per_pixel = len(channels)
    total_bits = h * w * bits_per_pixel
    return total_bits // 8


# ── Hide ─────────────────────────────────────────────────────────────────────

def hide(
    input_path: str | Path,
    output_path: str | Path,
    payload: bytes,
    difficulty: str = "easy",
) -> dict:
    """
    Embed `payload` into the image at `input_path` and save to `output_path`.

    Returns a dict with stats: capacity, payload_size, channels_used, etc.
    """
    channels = DIFFICULTY_CHANNELS[difficulty]
    img = Image.open(input_path).convert("RGB")
    arr = np.array(img, dtype=np.uint8)

    # Build full embedded stream: header + length + payload + delimiter
    length_bytes = struct.pack(">I", len(payload))
    stream = MAGIC_HEADER + length_bytes + payload + MESSAGE_DELIMITER
    stream_bits = _bytes_to_bits(stream)

    cap = image_capacity(img, channels)
    if len(stream) > cap:
        raise ValueError(
            f"Payload too large: need {len(stream)} bytes, image holds {cap} bytes "
            f"across {len(channels)} channel(s)."
        )

    h, w = arr.shape[:2]
    bit_idx = 0

    outer_break = False
    for y in range(h):
        if outer_break:
            break
        for x in range(w):
            if outer_break:
                break
            for c in channels:
                if bit_idx >= len(stream_bits):
                    outer_break = True
                    break
                # Zero out LSB, then set it
                arr[y, x, c] = (arr[y, x, c] & 0xFE) | stream_bits[bit_idx]
                bit_idx += 1

    out_img = Image.fromarray(arr, "RGB")
    out_img.save(str(output_path), "PNG")

    return {
        "image_capacity_bytes": cap,
        "payload_bytes": len(payload),
        "stream_bytes": len(stream),
        "channels_used": [["R", "G", "B"][c] for c in channels],
        "difficulty": difficulty,
        "pixels_modified": bit_idx // len(channels),
        "output_path": str(output_path),
    }


# ── Reveal ────────────────────────────────────────────────────────────────────

def reveal(
    input_path: str | Path,
    difficulty: str = "easy",
) -> Optional[bytes]:
    """
    Extract hidden payload from the image at `input_path`.

    Returns the raw payload bytes, or None if no valid hidden data found.
    """
    channels = DIFFICULTY_CHANNELS[difficulty]
    img = Image.open(input_path).convert("RGB")
    arr = np.array(img, dtype=np.uint8)
    h, w = arr.shape[:2]

    # Collect all LSBs in order
    all_bits: list[int] = []
    for y in range(h):
        for x in range(w):
            for c in channels:
                all_bits.append(int(arr[y, x, c]) & 1)

    all_bytes = _bits_to_bytes(all_bits)

    # Validate magic header
    header_len = len(MAGIC_HEADER)
    if all_bytes[:header_len] != MAGIC_HEADER:
        return None  # No valid stego data found

    # Read payload length
    length_start = header_len
    if len(all_bytes) < length_start + 4:
        return None
    payload_len = struct.unpack(">I", all_bytes[length_start:length_start + 4])[0]

    if payload_len > MAX_MESSAGE_BYTES:
        return None  # Sanity check — corrupt or wrong difficulty

    # Extract payload
    payload_start = length_start + 4
    payload_end = payload_start + payload_len
    if len(all_bytes) < payload_end:
        return None

    payload = all_bytes[payload_start:payload_end]

    # Validate delimiter
    delim_end = payload_end + len(MESSAGE_DELIMITER)
    if len(all_bytes) >= delim_end:
        if all_bytes[payload_end:delim_end] != MESSAGE_DELIMITER:
            return None  # Corrupted or wrong channel config

    return payload


# ── Auto-detect difficulty ───────────────────────────────────────────────────

def reveal_auto(input_path: str | Path) -> tuple[Optional[bytes], str]:
    """
    Try all difficulties in order and return the first successful extraction.
    Returns (payload_bytes, difficulty_string) or (None, "").
    """
    for diff in ("easy", "medium", "hard"):
        result = reveal(input_path, difficulty=diff)
        if result is not None:
            return result, diff
    return None, ""
