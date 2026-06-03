# stegotool configuration

# ── LSB settings ────────────────────────────────────────────────────────────
# Magic header embedded at the start of every hidden payload (8 bytes)
MAGIC_HEADER = b"\xDE\xAD\xBE\xEF\xCA\xFE\xBA\xBE"

# Delimiter appended after the payload to mark end-of-message
MESSAGE_DELIMITER = b"\x00\xFF\x00\xFF"

# Maximum message length (bytes) before encoding
MAX_MESSAGE_BYTES = 65_536  # 64 KB — plenty for game content

# ── Difficulty channel mapping ───────────────────────────────────────────────
# easy   → LSB of Blue channel only (most obvious, easiest to detect)
# medium → LSB of Red + Blue channels
# hard   → LSB of Red + Green + Blue, plus XOR encryption
DIFFICULTY_CHANNELS = {
    "easy":   [2],           # B only
    "medium": [0, 2],        # R + B
    "hard":   [0, 1, 2],     # R + G + B
}

# ── Output ───────────────────────────────────────────────────────────────────
OUTPUT_DIR = "output"
CHALLENGES_DIR = "challenges"
