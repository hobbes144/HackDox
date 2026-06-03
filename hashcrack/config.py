# ─────────────────────────────────────────────
#  hashcrack — configuration
# ─────────────────────────────────────────────

# Path to wordlist (relative to hashcrack.py)
# Swap this out for rockyou.txt if you have it:
#   WORDLIST = "wordlists/rockyou.txt"
WORDLIST = "wordlists/common.txt"

# Apply mutation rules on top of the wordlist
# (capitalize, append numbers, leet speak, etc.)
# Multiplies attempts ~20x but catches far more passwords
USE_RULES = True

# Live display: how often to refresh the counter (seconds)
DISPLAY_REFRESH = 0.1

# bcrypt: how many attempts before we give up and make the point
BCRYPT_MAX_ATTEMPTS = 200
