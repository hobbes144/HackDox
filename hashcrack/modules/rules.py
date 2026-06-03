"""
Mutation rules engine
---------------------
Transforms base wordlist entries into realistic password variants.

This is how real attackers catch people who think adding "123" or
capitalising the first letter makes their password safe.

Rules are applied in layers — each rule generates new candidates
from a base word. The engine deduplicates to avoid wasted attempts.

Example:
  base word: "dragon"
  after rules:
    Dragon, DRAGON, nogarD, dragon1, dragon123, dragon2024,
    dragon!, dragon@, dr4g0n, Dr4g0n, Dr4g0n1!, ...
"""

from typing import Iterator

# ── Leet speak substitution table ─────────────────────────────────────────────
LEET = {
    "a": "@", "e": "3", "i": "1", "o": "0",
    "s": "$", "t": "7", "l": "1", "g": "9",
}

# Common suffixes people add thinking it helps
SUFFIXES = [
    "1", "12", "123", "1234", "12345",
    "!", "!!", "!@#", "@", "#",
    "1!", "1!!", "123!", "1234!",
    "2020", "2021", "2022", "2023", "2024", "2025",
    "99", "00", "01", "69", "007",
    "123456", "1234567", "12345678", "123456789",
    "1234567890"
]

# Common prefixes
PREFIXES = ["1", "12", "123", "the", "my", "Mr", "Dr", "Big", "Little"]


def _leet(word: str) -> str:
    """Apply leet speak substitutions to a word."""
    return "".join(LEET.get(c.lower(), c) for c in word)


def _apply_leet_partial(word: str) -> list[str]:
    """Apply leet to individual characters (not all at once, too many combos)."""
    results = []
    for i, ch in enumerate(word.lower()):
        if ch in LEET:
            variant = word[:i] + LEET[ch] + word[i+1:]
            results.append(variant)
    return results


def mutate(word: str) -> Iterator[str]:
    """
    Generate password candidates from a single base word.
    Yields candidates one at a time (memory efficient for large wordlists).
    """
    w = word.strip()
    if not w:
        return

    seen: set[str] = {w}

    def _emit(candidate: str):
        if candidate not in seen:
            seen.add(candidate)
            return candidate
        return None

    # ── Case variants ──────────────────────────────────────────────────────────
    for variant in [w.lower(), w.upper(), w.capitalize(), w.title()]:
        r = _emit(variant)
        if r:
            yield r

    # ── Reversed ──────────────────────────────────────────────────────────────
    r = _emit(w[::-1])
    if r:
        yield r

    # ── Full leet speak ───────────────────────────────────────────────────────
    leet_full = _leet(w)
    r = _emit(leet_full)
    if r:
        yield r

    r = _emit(leet_full.capitalize())
    if r:
        yield r

    # ── Partial leet (one substitution at a time) ─────────────────────────────
    for partial in _apply_leet_partial(w):
        r = _emit(partial)
        if r:
            yield r
        r = _emit(partial.capitalize())
        if r:
            yield r

    # ── Suffix appends ────────────────────────────────────────────────────────
    for suffix in SUFFIXES:
        for base in [w, w.capitalize(), w.lower()]:
            r = _emit(base + suffix)
            if r:
                yield r

    # ── Prefix prepends ───────────────────────────────────────────────────────
    for prefix in PREFIXES:
        r = _emit(prefix + w)
        if r:
            yield r
        r = _emit(prefix + w.capitalize())
        if r:
            yield r

    # ── Leet + suffixes (the "clever" password pattern) ──────────────────────
    for suffix in SUFFIXES[:8]:  # limit combinations
        r = _emit(leet_full + suffix)
        if r:
            yield r
        r = _emit(leet_full.capitalize() + suffix)
        if r:
            yield r


def candidates_from_wordlist(wordlist_path: str, use_rules: bool) -> Iterator[tuple[str, str]]:
    """
    Yield (candidate_password, source_word) pairs from a wordlist.

    If use_rules=True, also yields all mutations of each word.
    If use_rules=False, yields only the raw wordlist entries.
    """
    with open(wordlist_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            word = line.strip()
            if not word:
                continue
            yield (word, word)  # the word itself first
            if use_rules:
                for mutation in mutate(word):
                    yield (mutation, word)
