"""
steganalysis.py — Statistical detection of LSB steganography.

Powers the `scan` command. Gives the player a suspicion score (0–100) and
a list of evidence clues — teaching them WHY the image looks tampered.

Techniques used
───────────────
1. Chi-square test on LSB parity:
   Random-looking images have ~50/50 0-vs-1 in each LSB plane.
   Embedded messages skew this distribution measurably.

2. LSB uniformity (pair analysis):
   Natural images have smooth gradients; LSB embedding creates
   abrupt pixel value changes between adjacent even/odd values.

3. Channel asymmetry:
   If the blue channel's LSBs deviate more than red/green, that's
   a hint the blue-only (easy difficulty) technique was used.

4. Pixel pair ratio (RS analysis):
   Groups of pixels are classified as Regular (R), Singular (S),
   or Unusable (U). The R/S ratio shifts predictably under LSB embedding.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class ChannelAnalysis:
    name: str          # "R", "G", "B"
    lsb_zero_pct: float     # % of LSBs that are 0  (ideal: ~50%)
    chi_square: float       # Chi-sq statistic (high = suspicious)
    chi_p_value: float      # p-value (low = more suspicious)
    suspicious: bool


@dataclass
class ScanResult:
    image_path: str
    width: int
    height: int
    total_pixels: int
    suspicion_score: int          # 0–100
    verdict: str                  # CLEAN / SUSPICIOUS / LIKELY STEGO
    verdict_color: str            # for rich printing
    channels: list[ChannelAnalysis] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    estimated_payload_bytes: int = 0
    capacity_bytes: int = 0


# ── Chi-square test ───────────────────────────────────────────────────────────

def _chi_square_lsb(channel_values: np.ndarray) -> tuple[float, float]:
    """
    Run a chi-square test on the LSB plane of a single channel.

    Under the null hypothesis (random/natural image), LSBs should be
    roughly 50% 0 and 50% 1. Returns (chi_statistic, p_value).
    """
    n = len(channel_values)
    lsb_bits = channel_values & 1
    count_ones = int(np.sum(lsb_bits))
    count_zeros = n - count_ones

    expected = n / 2.0
    if expected == 0:
        return 0.0, 1.0

    chi_sq = ((count_zeros - expected) ** 2 + (count_ones - expected) ** 2) / expected

    # Approximate p-value for df=1 using complement of chi-sq CDF
    # (avoid scipy dependency — use simple approximation)
    p = _chi_sq_p_value(chi_sq, df=1)
    return chi_sq, p


def _chi_sq_p_value(x: float, df: int = 1) -> float:
    """
    Approximate p-value for chi-squared distribution (df=1 only).
    Uses the regularized incomplete gamma function approximation.
    """
    if x <= 0:
        return 1.0
    # For df=1, p = erfc(sqrt(x/2))
    # erfc approximation using standard math
    try:
        z = math.sqrt(x / 2.0)
        # erfc via complementary error function (math module)
        p = math.erfc(z)
        return max(0.0, min(1.0, p))
    except (ValueError, OverflowError):
        return 0.0


# ── RS Analysis ───────────────────────────────────────────────────────────────

def _rs_analysis(channel: np.ndarray, width: int) -> float:
    """
    Simplified RS (Regular-Singular) steganalysis.

    Returns an anomaly score 0.0–1.0. Higher means more likely embedded data.
    Flipping LSBs of an embedded image creates a measurable R-S imbalance.
    """
    # Reshape into 1×2 pixel groups (horizontal pairs)
    flat = channel.flatten().astype(np.int32)
    if len(flat) < 4:
        return 0.0

    pairs = flat[: len(flat) - (len(flat) % 2)].reshape(-1, 2)

    def discrimination(p: np.ndarray) -> np.ndarray:
        return np.abs(p[:, 0] - p[:, 1]).astype(float)

    def flip_lsb(p: np.ndarray) -> np.ndarray:
        flipped = p.copy()
        flipped[:, 0] = np.where(flipped[:, 0] % 2 == 0, flipped[:, 0] + 1, flipped[:, 0] - 1)
        return np.clip(flipped, 0, 255)

    d_orig = discrimination(pairs)
    d_flipped = discrimination(flip_lsb(pairs))

    r = np.sum(d_flipped > d_orig)  # Regular
    s = np.sum(d_flipped < d_orig)  # Singular

    total = len(pairs)
    if total == 0:
        return 0.0

    # Natural images: R >> S. Stego images: R ≈ S (ratio approaches 1.0)
    r_ratio = r / total
    s_ratio = s / total

    anomaly = 1.0 - abs(r_ratio - s_ratio)  # 0 = clean, 1 = max anomaly
    return float(np.clip(anomaly, 0.0, 1.0))


# ── LSB Autocorrelation ───────────────────────────────────────────────────────

def _lsb_autocorrelation(channel: np.ndarray) -> float:
    """
    Measure the lag-1 autocorrelation of the LSB bitstream.

    Natural images (of ANY style) have SOME structure in their LSB sequence
    because adjacent pixels tend to have similar values. Embedding random bits
    breaks this correlation, pushing autocorrelation toward zero.

    Returns an anomaly score 0.0–1.0 (higher = more likely embedded data).
    Robust across all image types: gradient, photo, pixelart, terminal.
    """
    flat = (channel.flatten().astype(np.int16)) & 1
    n = len(flat)
    if n < 2:
        return 0.0

    # Lag-1 correlation: how often does lsb[i] == lsb[i+1]?
    matches = np.sum(flat[:-1] == flat[1:])
    corr = float(matches) / (n - 1)

    # A perfectly random stream → corr ≈ 0.5
    # Structured (natural) images → corr > 0.5 (adjacent pixels cluster)
    # After embedding → corr → 0.5 (randomized)
    # We flag deviation *toward* 0.5 from a natural baseline
    # Use distance from 0.5: small distance = suspicious
    distance_from_random = abs(corr - 0.5)

    # Map to anomaly: near-0 distance = high anomaly
    # Scale: distance < 0.01 is very suspicious, > 0.08 is likely clean
    anomaly = max(0.0, 1.0 - (distance_from_random / 0.06))
    return float(np.clip(anomaly, 0.0, 1.0))


# ── Main scan function ────────────────────────────────────────────────────────

def scan(image_path: str | Path) -> ScanResult:
    """
    Run steganalysis on an image and return a ScanResult with suspicion score.
    """
    img = Image.open(image_path).convert("RGB")
    arr = np.array(img, dtype=np.uint8)
    h, w = arr.shape[:2]
    total_pixels = h * w

    channel_names = ["R", "G", "B"]
    channel_results: list[ChannelAnalysis] = []
    evidence: list[str] = []

    chi_scores: list[float] = []
    rs_scores: list[float] = []
    autocorr_scores: list[float] = []

    for idx, name in enumerate(channel_names):
        ch = arr[:, :, idx].flatten()
        chi_sq, p_val = _chi_square_lsb(ch)
        rs = _rs_analysis(arr[:, :, idx], w)
        autocorr = _lsb_autocorrelation(arr[:, :, idx])

        lsb_zero_pct = float(np.sum((ch & 1) == 0)) / len(ch) * 100

        suspicious = (p_val < 0.05 or chi_sq > 10.0 or autocorr > 0.6)

        channel_results.append(ChannelAnalysis(
            name=name,
            lsb_zero_pct=lsb_zero_pct,
            chi_square=chi_sq,
            chi_p_value=p_val,
            suspicious=suspicious,
        ))
        chi_scores.append(chi_sq)
        rs_scores.append(rs)
        autocorr_scores.append(autocorr)

    # ── Build evidence list ──────────────────────────────────────────────────
    suspicious_channels = [c for c in channel_results if c.suspicious]

    if suspicious_channels:
        ch_names = ", ".join(c.name for c in suspicious_channels)
        evidence.append(
            f"Chi-square anomaly in {ch_names} channel(s) — LSB distribution "
            f"deviates significantly from natural baseline (p < 0.05)"
        )

    # Check for blue-only embedding (easy difficulty signature)
    b_chi = chi_scores[2]
    rg_chi_avg = (chi_scores[0] + chi_scores[1]) / 2
    if b_chi > rg_chi_avg * 2.0 and b_chi > 5.0:
        evidence.append(
            "Blue channel shows disproportionate LSB skew vs Red/Green — "
            "consistent with single-channel (easy) LSB embedding"
        )

    # RS analysis evidence
    avg_rs = sum(rs_scores) / len(rs_scores)
    if avg_rs > 0.65:
        evidence.append(
            f"RS analysis anomaly score {avg_rs:.2f}/1.00 — "
            "Regular-Singular pixel pair ratio suggests embedded data"
        )

    # LSB autocorrelation evidence (most robust signal)
    avg_autocorr = sum(autocorr_scores) / len(autocorr_scores)
    max_autocorr = max(autocorr_scores)
    if max_autocorr > 0.55:
        ac_ch = channel_names[autocorr_scores.index(max_autocorr)]
        evidence.append(
            f"LSB autocorrelation anomaly in {ac_ch} channel (score {max_autocorr:.2f}) — "
            "adjacent-pixel LSB structure has been disrupted, consistent with bit injection"
        )

    # LSB uniformity
    for ca in channel_results:
        deviation = abs(ca.lsb_zero_pct - 50.0)
        if deviation > 5.0:
            evidence.append(
                f"{ca.name} channel: {ca.lsb_zero_pct:.1f}% zero-LSBs "
                f"(±{deviation:.1f}% from expected 50%) — unnaturally skewed"
            )

    # ── Suspicion score (weighted combination of three signals) ──────────────
    n_suspicious = len(suspicious_channels)
    chi_contribution   = min(35, int(max(chi_scores) * 3))
    rs_contribution    = min(25, int(avg_rs * 30))
    autocorr_contrib   = min(30, int(avg_autocorr * 40))
    channel_contribution = n_suspicious * 5

    suspicion_score = min(100, chi_contribution + rs_contribution + autocorr_contrib + channel_contribution)

    # ── Verdict ──────────────────────────────────────────────────────────────
    if suspicion_score >= 70:
        verdict = "LIKELY STEGO"
        verdict_color = "bright_red"
    elif suspicion_score >= 35:
        verdict = "SUSPICIOUS"
        verdict_color = "yellow"
    else:
        verdict = "CLEAN"
        verdict_color = "bright_green"
        evidence = ["No statistically significant LSB anomalies detected."]

    # ── Capacity estimate ────────────────────────────────────────────────────
    capacity_bytes = total_pixels * 3 // 8  # full RGB, 1 bit per channel

    # Rough payload estimate if stego detected: assume ~10% of capacity used
    estimated_payload = (capacity_bytes // 10) if suspicion_score > 40 else 0

    return ScanResult(
        image_path=str(image_path),
        width=w,
        height=h,
        total_pixels=total_pixels,
        suspicion_score=suspicion_score,
        verdict=verdict,
        verdict_color=verdict_color,
        channels=channel_results,
        evidence=evidence,
        estimated_payload_bytes=estimated_payload,
        capacity_bytes=capacity_bytes,
    )
