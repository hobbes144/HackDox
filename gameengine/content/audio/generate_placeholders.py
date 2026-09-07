#!/usr/bin/env python3
"""Generate placeholder SFX for every id in gameengine.core.audio.SFX_REGISTRY.

These are synthesized tones/clicks/sweeps -- not real sound design, just
audibly-distinct stand-ins so every trigger point has *something* to play
while real audio is produced. Re-run this any time to regenerate the whole
set (e.g. after tweaking a shape below); it never touches hand-made files
you drop in later, since it always writes the same filenames the registry
already points at -- just replace this script's output with real assets
when they're ready and nothing else in the game needs to change.

Usage:  python3 generate_placeholders.py
Output: ./sfx/*.wav  (next to this script, i.e. gameengine/content/audio/sfx/)
"""

from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path

SR = 44100
OUT_DIR = Path(__file__).resolve().parent / "sfx"


# ── Low-level synthesis helpers (stdlib only) ────────────────────────────

def _envelope(n: int, attack: float, release: float) -> list[float]:
    a = max(int(n * attack), 1)
    r = max(int(n * release), 1)
    sustain = max(n - a - r, 0)
    env = [i / a for i in range(a)]
    env += [1.0] * sustain
    env += [1.0 - i / r for i in range(r)]
    if len(env) < n:
        env += [0.0] * (n - len(env))
    return env[:n]


def tone(freq: float, dur: float, volume: float = 0.5,
         attack: float = 0.08, release: float = 0.5,
         harmonic2: float = 0.0) -> list[float]:
    n = int(SR * dur)
    env = _envelope(n, attack, release)
    out = []
    for i in range(n):
        t = i / SR
        v = math.sin(2 * math.pi * freq * t)
        if harmonic2:
            v += harmonic2 * math.sin(2 * math.pi * freq * 2 * t)
        out.append(v * env[i] * volume)
    return out


def sweep(f0: float, f1: float, dur: float, volume: float = 0.5,
          attack: float = 0.05, release: float = 0.35) -> list[float]:
    n = int(SR * dur)
    env = _envelope(n, attack, release)
    out = []
    phase = 0.0
    for i in range(n):
        frac = i / max(n - 1, 1)
        freq = f0 + (f1 - f0) * frac
        phase += 2 * math.pi * freq / SR
        out.append(math.sin(phase) * env[i] * volume)
    return out


def click(dur: float = 0.02, volume: float = 0.45, freq: float = 1200) -> list[float]:
    n = int(SR * dur)
    env = _envelope(n, attack=0.02, release=0.85)
    return [math.sin(2 * math.pi * freq * (i / SR)) * env[i] * volume for i in range(n)]


def noise_burst(dur: float, volume: float = 0.4, seed: int = 0,
                 attack: float = 0.01, release: float = 0.6) -> list[float]:
    n = int(SR * dur)
    env = _envelope(n, attack, release)
    rnd = random.Random(seed)
    return [rnd.uniform(-1, 1) * env[i] * volume for i in range(n)]


def concat(*parts: list[float], gap: float = 0.02) -> list[float]:
    gap_samples = [0.0] * int(SR * gap)
    out: list[float] = []
    for i, p in enumerate(parts):
        out += p
        if i < len(parts) - 1:
            out += gap_samples
    return out


def mix(*parts: list[float]) -> list[float]:
    n = max(len(p) for p in parts)
    out = [0.0] * n
    for p in parts:
        for i, v in enumerate(p):
            out[i] += v
    return out


def save_wav(path: Path, samples: list[float]) -> None:
    frames = bytearray()
    for s in samples:
        s = max(-1.0, min(1.0, s))
        frames += struct.pack("<h", int(s * 32767))
    with wave.open(str(path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes(bytes(frames))


# ── One recipe per SFX_REGISTRY id ───────────────────────────────────────
# Shape mnemonic used throughout: correct/incorrect -> consonant/dissonant
# pitch; accept(admit)/deny -> two-note "double" vs single sustained note.

def build() -> dict[str, list[float]]:
    return {
        # Verdict delivery
        "verdict_correct_accept": concat(
            tone(523.25, 0.10, 0.5), tone(659.25, 0.16, 0.55), gap=0.01),
        "verdict_correct_deny": tone(784.0, 0.22, 0.55, attack=0.03, release=0.6),
        "verdict_incorrect_accept": concat(
            tone(440.0, 0.10, 0.5, harmonic2=0.3),
            tone(392.0, 0.16, 0.45, harmonic2=0.3), gap=0.01),
        "verdict_incorrect_deny": tone(220.0, 0.26, 0.5, harmonic2=0.4,
                                       attack=0.02, release=0.7),

        # Tool runs
        "tool_run_ghostscan": sweep(850, 380, 0.32, 0.4),
        "tool_run_hashcrack": concat(click(0.03, 0.4, 1500), click(0.03, 0.4, 1700),
                                     click(0.05, 0.45, 1900), gap=0.045),
        "tool_run_logwatch": concat(tone(700, 0.06, 0.4), tone(700, 0.06, 0.4), gap=0.07),
        "tool_run_stegotool": sweep(420, 950, 0.30, 0.4),

        # Stego stamp
        "stego_stamp": mix(noise_burst(0.08, 0.35, seed=1, release=0.7),
                           tone(110, 0.10, 0.4, attack=0.01, release=0.8)),

        # Day cycle
        "day_start": concat(tone(523.25, 0.11, 0.45), tone(659.25, 0.11, 0.5),
                            tone(783.99, 0.20, 0.55), gap=0.015),
        "day_end": concat(tone(783.99, 0.12, 0.45), tone(659.25, 0.12, 0.4),
                          tone(523.25, 0.22, 0.4), gap=0.015),

        # Soft, frequent UI ticks -- kept quiet & short on purpose
        "overseer_tick": click(0.03, 0.18, 900),
        "focus_switch": click(0.015, 0.15, 1100),
        "page_switch": concat(click(0.015, 0.18, 700), click(0.02, 0.16, 950), gap=0.01),

        # Rules overlay
        "rules_open": sweep(320, 640, 0.16, 0.35),
        "rules_close": sweep(640, 320, 0.16, 0.35),

        # Evidence board
        "evidence_open": sweep(500, 760, 0.13, 0.3),
        "evidence_close": sweep(760, 500, 0.13, 0.3),
        "evidence_flag": concat(click(0.02, 0.35, 1600), tone(950, 0.05, 0.3), gap=0.005),

        # Economy
        "credit_use": mix(tone(1046.5, 0.16, 0.4, attack=0.01, release=0.6),
                          tone(1318.5, 0.20, 0.35, attack=0.03, release=0.6)),
        "filter_apply": concat(click(0.02, 0.35, 2000), sweep(300, 900, 0.14, 0.3)),
        "upgrade_purchase": concat(tone(440.0, 0.09, 0.42), tone(554.37, 0.09, 0.46),
                                   tone(659.25, 0.18, 0.5, harmonic2=0.2), gap=0.012),

        # Candidate-page verdict pulse (the border flash)
        "pulse_celebration": concat(tone(659.25, 0.07, 0.4), tone(783.99, 0.07, 0.42),
                                    tone(987.77, 0.12, 0.48), gap=0.008),
        "pulse_error": mix(tone(233.08, 0.18, 0.45, harmonic2=0.35),
                          tone(220.0, 0.18, 0.4, attack=0.01, release=0.7)),
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    recipes = build()
    for sound_id, samples in recipes.items():
        path = OUT_DIR / f"{sound_id}.wav"
        save_wav(path, samples)
        print(f"wrote {path.relative_to(OUT_DIR.parent.parent.parent)}  ({len(samples)/SR:.2f}s)")
    print(f"\n{len(recipes)} placeholder SFX generated in {OUT_DIR}")


if __name__ == "__main__":
    main()
