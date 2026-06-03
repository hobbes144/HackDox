# ─────────────────────────────────────────────
#  logwatch — configuration
# ─────────────────────────────────────────────

# Brute force: flag if an IP has more than this many failures in the window
BRUTE_FORCE_THRESHOLD   = 10      # failures
BRUTE_FORCE_WINDOW_SECS = 300     # 5 minutes

# Credential stuffing: flag if an IP tries more than this many unique usernames
CRED_STUFFING_THRESHOLD = 5

# Impossible travel: flag if the same user logs in from two locations
# that would require travelling faster than this (km/h)
IMPOSSIBLE_TRAVEL_KPH   = 900     # roughly max commercial flight speed

# After-hours window (24h format, server local time)
BUSINESS_HOURS_START    = 8
BUSINESS_HOURS_END      = 18

# Geolocation: use free ip-api.com (45 req/min, no key needed)
# Set to False to skip geo lookups (faster, no network needed)
ENABLE_GEOIP            = True

# Request timeout for geo lookups (seconds)
GEO_TIMEOUT             = 5
