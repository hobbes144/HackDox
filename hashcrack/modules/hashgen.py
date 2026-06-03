"""
Hash generator — game scenario engine
--------------------------------------
Generates hashed password challenges for Layer 3 of the game.

Each scenario produces:
  - A hash (the "recovered" credential from a breached server)
  - A difficulty level (easy = top-10 password, hard = mutated word)
  - An answer key (stored separately, never shown to player)
  - Context narrative (why this hash matters in the story)

The player gets the hash and the narrative.
Their job: crack it to find the password and prove the breach.
"""

import hashlib
import random
from dataclasses import dataclass
from typing import Literal

try:
    import bcrypt as _bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False


# ── Password pools by difficulty ──────────────────────────────────────────────

EASY_PASSWORDS = [
    "password", "123456", "qwerty", "admin", "letmein",
    "dragon", "monkey", "iloveyou", "master", "sunshine",
    "baseball", "football", "shadow", "welcome", "login",
]

MEDIUM_PASSWORDS = [
    "password123", "dragon123", "monkey1", "iloveyou2",
    "hunter1", "sunshine1", "qwerty123", "letmein1",
    "master123", "shadow123", "welcome1", "admin123",
    "batman1", "harley1", "matrix1",
]

HARD_PASSWORDS = [
    "P@ssw0rd1", "Dr4g0n!", "M0nk3y!2", "Sunshin3!",
    "H4ck3r2024", "S3cur1ty!", "F1r3w4ll!", "Cyb3r$ec",
    "Gh0stSc4n", "L0gW4tch!", "Cr4ck3r99", "N1nj4007",
]

# Story contexts for each scenario
NARRATIVES = [
    {
        "title":   "The Admin Account",
        "context": "A database dump was recovered from a breached corporate server. "
                   "The following hash belongs to the 'admin' account. "
                   "Crack it to prove the attacker had full system access.",
    },
    {
        "title":   "The Developer's Credentials",
        "context": "A GitHub commit history revealed an accidentally leaked password hash. "
                   "The developer claims it was rotated immediately. "
                   "Crack it to determine if it was ever a real threat.",
    },
    {
        "title":   "The VPN Gateway",
        "context": "Network logs show an unauthorised VPN connection at 3am. "
                   "This hash was extracted from the VPN auth database. "
                   "If cracked, it proves the attacker reused a known password.",
    },
    {
        "title":   "The Service Account",
        "context": "A service account was used to exfiltrate 50GB of customer data. "
                   "The hash below was recovered from the shadow file. "
                   "Crack it to build the incident timeline.",
    },
    {
        "title":   "The Insider Threat",
        "context": "An employee's account was used after their termination date. "
                   "Their password hash was never rotated after offboarding. "
                   "Crack it to demonstrate the policy failure.",
    },
]


# ── Hash functions ─────────────────────────────────────────────────────────────

def _hash(password: str, algo: str) -> str:
    if algo == "md5":
        return hashlib.md5(password.encode()).hexdigest()
    elif algo == "sha1":
        return hashlib.sha1(password.encode()).hexdigest()
    elif algo == "sha256":
        return hashlib.sha256(password.encode()).hexdigest()
    elif algo == "bcrypt":
        if not BCRYPT_AVAILABLE:
            raise ImportError("bcrypt library required: pip install bcrypt")
        salt = _bcrypt.gensalt(rounds=12)
        return _bcrypt.hashpw(password.encode(), salt).decode()
    raise ValueError(f"Unknown algorithm: {algo}")


# ── Scenario dataclass ────────────────────────────────────────────────────────

@dataclass
class HashScenario:
    """A generated hash cracking challenge."""
    title:      str
    context:    str           # story context shown to the player
    hash_str:   str           # the hash to crack
    algo:       str           # "md5", "sha1", "sha256", "bcrypt"
    difficulty: str           # "easy", "medium", "hard"
    # Answer key (hidden from player in the game)
    password:   str


# ── Generator ─────────────────────────────────────────────────────────────────

def generate_scenario(
    difficulty: Literal["easy", "medium", "hard"] = "easy",
    algo:       Literal["md5", "sha1", "sha256", "bcrypt"] = "md5",
    seed:       int | None = None,
) -> HashScenario:
    """
    Generate a single hash cracking challenge.

    Args:
        difficulty: Controls password strength
        algo:       Hash algorithm to use
        seed:       Random seed for reproducibility

    Returns:
        HashScenario with hash, context, and hidden answer key
    """
    if seed is not None:
        random.seed(seed)

    pool = {
        "easy":   EASY_PASSWORDS,
        "medium": MEDIUM_PASSWORDS,
        "hard":   HARD_PASSWORDS,
    }[difficulty]

    password  = random.choice(pool)
    narrative = random.choice(NARRATIVES)
    hash_str  = _hash(password, algo)

    return HashScenario(
        title=narrative["title"],
        context=narrative["context"],
        hash_str=hash_str,
        algo=algo,
        difficulty=difficulty,
        password=password,
    )


def generate_challenge_set(
    count: int = 3,
    seed:  int | None = 42,
) -> list[HashScenario]:
    """
    Generate a set of escalating challenges (easy → medium → hard).
    Used to create a full game level.
    """
    if seed is not None:
        random.seed(seed)

    difficulties = ["easy", "medium", "hard"]
    algos        = ["md5", "sha1", "sha256"]

    scenarios = []
    for i in range(count):
        diff = difficulties[min(i, len(difficulties) - 1)]
        algo = algos[min(i, len(algos) - 1)]
        scenario = generate_scenario(diff, algo)
        scenarios.append(scenario)

    return scenarios
