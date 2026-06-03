"""
forge.py — Game challenge generator for stegotool.

Generates a "case file" package:
  1. A procedurally generated cover image (pixel art / noise pattern)
  2. A hidden message embedded via LSB (encoded per difficulty)
  3. A JSON challenge manifest with narrative context and hidden answer key

5 Scenarios × 3 Difficulties = 15 distinct challenge types
"""

from __future__ import annotations

import json
import random
import string
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from config import CHALLENGES_DIR
from modules.lsb import hide
from modules.encoder import encode


# ── Scenario definitions ──────────────────────────────────────────────────────

SCENARIOS = {
    "data_exfil": {
        "title": "Silent Exfiltration",
        "icon": "📤",
        "brief": (
            "Analyst. We intercepted a JPEG uploaded to the suspect's personal "
            "cloud storage moments before their VPN disconnected. SIGINT suggests "
            "they were smuggling something out. The file metadata is clean. "
            "But images can lie."
        ),
        "objective": "Recover the exfiltrated data hidden in the image.",
        "lore": {
            "easy":   "A junior insider — they didn't even encode it. Rookie mistake.",
            "medium": "They base64'd it. Thought that was enough. It wasn't.",
            "hard":   "Sophisticated operator. XOR-encrypted with a session key. "
                      "Intel says the key matches their workstation hostname.",
        },
        "message_templates": {
            "easy":   "API_KEY=sk-{key}\nDB_PASS={pw}\nS3_BUCKET=corp-backups-{num}",
            "medium": "EXFIL_PAYLOAD: github_token=ghp_{token} org=acme-corp",
            "hard":   "HACKDOX{{{flag}}} PRIVATE_KEY_FINGERPRINT={fp}",
        },
    },

    "c2_traffic": {
        "title": "Dead Channel",
        "icon": "📡",
        "brief": (
            "The malware sample we analysed downloaded exactly one image "
            "from a public image board before going quiet. We think it's "
            "pulling its C2 beacon instructions from image pixels. "
            "Confirm the theory. Find the command."
        ),
        "objective": "Extract the C2 beacon instructions from the carrier image.",
        "lore": {
            "easy":   "Command-and-control in plaintext. Arrogant. Or lazy.",
            "medium": "Obfuscated with base64. Scripted kid level.",
            "hard":   "Encrypted C2 channel. This is an APT-level operation.",
        },
        "message_templates": {
            "easy":   "C2_HOST=192.168.{a}.{b}:4444\nCMD=BEACON\nINTERVAL=300",
            "medium": "BEACON c2.darkops-{rand}.onion PORT=8443 JITTER=45s",
            "hard":   "HACKDOX{{{flag}}} C2={ip}:{port} KEY={xorkey} SLEEP={sleep}",
        },
    },

    "dead_drop": {
        "title": "Ghost Protocol",
        "icon": "👻",
        "brief": (
            "A threat actor posted this image to a public hacker forum under "
            "the handle 'NULL_PTR'. Dark web chatter says it's a dead drop — "
            "a message to a sleeper agent. We need to know what it says "
            "before they do."
        ),
        "objective": "Intercept and decode the dead drop message.",
        "lore": {
            "easy":   "The message is in plaintext. They felt safe in the open. They weren't.",
            "medium": "Base64 encoded. The recipient has a decoder. So do you.",
            "hard":   "AES would've been smarter. XOR at least requires the key — "
                      "which you'll find if you look at the filename carefully.",
        },
        "message_templates": {
            "easy":   "ASSET: meet-point KILO-7\nTIME: 0300 LOCAL\nPHRASE: {phrase}",
            "medium": "OPERATION NIGHTFALL — proceed. Package is at LOCKER {num}. CODE: {pw}",
            "hard":   "HACKDOX{{{flag}}} ASSET_ID={uid} RENDEZVOUS={coord}",
        },
    },

    "insider_threat": {
        "title": "The Leaker",
        "icon": "🕵️",
        "brief": (
            "A disgruntled employee emailed this stock photo to their personal "
            "Gmail account six hours before resigning. HR flagged it as unusual. "
            "Forensics found nothing in the file headers. But we both know "
            "headers aren't everything."
        ),
        "objective": "Determine what the leaker smuggled out in this image.",
        "lore": {
            "easy":   "They copy-pasted the data raw into a hide script. No tradecraft at all.",
            "medium": "Base64 to 'obfuscate' it. They Googled 'how to hide data in image'.",
            "hard":   "They actually knew what they were doing. Someone taught them. Find out who.",
        },
        "message_templates": {
            "easy":   "EMPLOYEE_DB_DUMP: {n} records\nUSERS: admin:{pw}, root:{pw2}\nSERVER: 10.0.{a}.{b}",
            "medium": "client_list={n}_records source_db=crm-prod export_date={date}",
            "hard":   "HACKDOX{{{flag}}} DUMP_ID={uid} RECORD_COUNT={n} HASH={fp}",
        },
    },

    "whistleblower": {
        "title": "Canary in the Wire",
        "icon": "🐦",
        "brief": (
            "Your inside contact is being watched. They can't send files. "
            "They can't make calls. But they can post to a photography forum. "
            "This image arrived in your feed ten minutes ago. "
            "The clock is ticking."
        ),
        "objective": "Recover your contact's hidden message before the channel goes dark.",
        "lore": {
            "easy":   "They kept it simple. Good. Simple is safe when you're in a hurry.",
            "medium": "Base64 encoded — they're being careful but not paranoid.",
            "hard":   "Fully encrypted. They're scared. Whatever they found is serious.",
        },
        "message_templates": {
            "easy":   "CONTACT ALIVE. EVIDENCE AT: /srv/logs/audit_{date}.log\nPASS: {pw}",
            "medium": "CACHE LOCATION: {phrase}\nFILES: {n} docs\nDEADLINE: {hours}h",
            "hard":   "HACKDOX{{{flag}}} DROPSITE={uid} EVIDENCE_HASH={fp} URGENCY=CRITICAL",
        },
    },
}

DIFFICULTY_ORDER = ["easy", "medium", "hard"]


# ── Message generation ────────────────────────────────────────────────────────

def _rand_hex(n: int) -> str:
    return "".join(random.choices("0123456789abcdef", k=n))


def _rand_alpha(n: int) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _rand_flag() -> str:
    words = ["pixel_prophet", "lsb_leaker", "blue_channel_blues",
             "stego_by_night", "null_byte_null_alibi", "xor_and_out",
             "image_is_the_message", "invisible_ink_2049"]
    return random.choice(words)


def _generate_message(scenario: str, difficulty: str, challenge_id: str) -> tuple[str, str]:
    """Return (plaintext_message, hidden_answer)."""
    tmpl = SCENARIOS[scenario]["message_templates"][difficulty]

    subs = {
        "key": _rand_hex(32),
        "pw": _rand_alpha(12),
        "pw2": _rand_alpha(10),
        "num": str(random.randint(1000, 9999)),
        "rand": _rand_alpha(8),
        "token": _rand_hex(20),
        "flag": _rand_flag(),
        "fp": _rand_hex(20),
        "uid": str(uuid.uuid4())[:18],
        "ip": f"10.{random.randint(0,254)}.{random.randint(0,254)}.{random.randint(1,253)}",
        "port": str(random.choice([4444, 8443, 1337, 31337, 9001])),
        "xorkey": _rand_hex(16),
        "sleep": str(random.choice([30, 60, 120, 300, 600])),
        "phrase": random.choice(["IRON PHOENIX", "GREY ECHO", "COLD RELAY",
                                  "SIGMA NINE", "BRIGHT HAMMER"]),
        "coord": f"{random.uniform(-90,90):.4f},{random.uniform(-180,180):.4f}",
        "n": str(random.randint(1000, 150000)),
        "a": str(random.randint(1, 254)),
        "b": str(random.randint(1, 254)),
        "date": time.strftime("%Y%m%d"),
        "hours": str(random.choice([2, 4, 6, 12])),
    }

    message = tmpl.format(**subs)

    # For hard difficulty the HACKDOX{} flag is the answer
    if "HACKDOX{" in message:
        import re
        m = re.search(r"HACKDOX\{([^}]+)\}", message)
        answer = f"HACKDOX{{{m.group(1)}}}" if m else message
    else:
        answer = message

    return message, answer


# ── Cover image generation ────────────────────────────────────────────────────

IMAGE_STYLES = ["gradient", "photo", "blueprint", "thermal", "terminal"]


def _generate_cover_image(style: str, width: int = 512, height: int = 512) -> Image.Image:
    """
    Generate a procedural cover image in the given style.

    All styles produce smooth-ish, natural-looking images with good LSB structure
    so that the steganalysis scanner can reliably detect embedding.
    """
    rng = np.random.default_rng(random.randint(0, 2**31))

    if style == "gradient":
        # Multi-directional colour gradient — clean, corporate-looking
        x = np.linspace(0.0, 1.0, width)
        y = np.linspace(0.0, 1.0, height)
        xg, yg = np.meshgrid(x, y)
        # Slight texture via smooth periodic variation
        texture = (np.sin(xg * 12) * np.cos(yg * 8) * 12).astype(int)
        r = np.clip((xg * 200 + texture + 30).astype(int), 0, 255).astype(np.uint8)
        g = np.clip((yg * 180 + texture + 40).astype(int), 0, 255).astype(np.uint8)
        b = np.clip(((1 - xg) * 160 + yg * 60 + texture + 50).astype(int), 0, 255).astype(np.uint8)
        arr = np.stack([r, g, b], axis=2)

    elif style == "photo":
        # Simulated photo: smooth low-frequency variation + subtle gaussian texture
        # Models a real photograph's pixel statistics
        x = np.linspace(-3.0, 3.0, width)
        y = np.linspace(-3.0, 3.0, height)
        xg, yg = np.meshgrid(x, y)
        # Smooth blobs (simulate out-of-focus background)
        blob1 = np.exp(-((xg - 0.5) ** 2 + (yg + 0.3) ** 2) / 2.5)
        blob2 = np.exp(-((xg + 1.0) ** 2 + (yg - 0.8) ** 2) / 3.0)
        blob3 = np.exp(-((xg - 0.2) ** 2 + (yg + 1.2) ** 2) / 1.8)
        # Convert to per-channel values with gentle noise (simulates sensor noise)
        noise_r = rng.normal(0, 4, (height, width))
        noise_g = rng.normal(0, 3, (height, width))
        noise_b = rng.normal(0, 4, (height, width))
        r = np.clip((blob1 * 160 + blob2 * 60 + 60 + noise_r), 0, 255).astype(np.uint8)
        g = np.clip((blob2 * 140 + blob3 * 80 + 50 + noise_g), 0, 255).astype(np.uint8)
        b = np.clip((blob3 * 180 + blob1 * 40 + 70 + noise_b), 0, 255).astype(np.uint8)
        arr = np.stack([r, g, b], axis=2)

    elif style == "blueprint":
        # Dark blue engineering-diagram look — smooth grid lines
        base = np.full((height, width, 3), (10, 18, 45), dtype=np.uint8)
        # Faint grid lines
        for gx in range(0, width, 32):
            base[:, max(0, gx-1):gx+1] = (20, 40, 90)
        for gy in range(0, height, 32):
            base[max(0, gy-1):gy+1, :] = (20, 40, 90)
        # Diagonal shading gradient for smooth LSB distribution
        x = np.linspace(0, 30, width, dtype=np.uint8)
        y = np.linspace(0, 20, height, dtype=np.uint8)
        xg, yg = np.meshgrid(x, y)
        shade = (xg + yg).astype(np.uint8)
        base[:, :, 2] = np.clip(base[:, :, 2].astype(int) + shade, 0, 255).astype(np.uint8)
        arr = base

    elif style == "thermal":
        # Thermal camera simulation — smooth heat gradient, red/orange/yellow palette
        x = np.linspace(-2.0, 2.0, width)
        y = np.linspace(-2.0, 2.0, height)
        xg, yg = np.meshgrid(x, y)
        heat = np.exp(-((xg ** 2 + yg ** 2) / 3.0))
        noise = rng.normal(0, 3, (height, width))
        heat_v = np.clip((heat * 220 + 35 + noise), 0, 255)
        r = np.clip(heat_v * 1.1, 0, 255).astype(np.uint8)
        g = np.clip(heat_v * 0.6, 0, 255).astype(np.uint8)
        b = np.clip(heat_v * 0.2, 0, 255).astype(np.uint8)
        arr = np.stack([r, g, b], axis=2)

    elif style == "terminal":
        # Green-on-black terminal screenshot look
        # Smooth horizontal scan-line shading (CRT-style) with slow gradient
        arr = np.zeros((height, width, 3), dtype=np.uint8)
        for row in range(height):
            intensity = int(15 + (row / height) * 40)
            # CRT scanline dimming
            scanline_factor = 0.85 if row % 2 == 0 else 1.0
            val = int(intensity * scanline_factor)
            arr[row, :, 1] = val   # green channel only
        # Add subtle horizontal banding
        x = np.linspace(0, 25, width, dtype=np.uint8)
        arr[:, :, 1] = np.clip(arr[:, :, 1].astype(int) + x, 0, 255).astype(np.uint8)

    else:
        # Fallback: smooth diagonal gradient
        x = np.linspace(40, 200, width, dtype=np.uint8)
        y = np.linspace(40, 200, height, dtype=np.uint8)
        xg, yg = np.meshgrid(x, y)
        arr = np.stack([xg, yg, (200 - xg // 2 + yg // 4).clip(0, 255).astype(np.uint8)], axis=2)

    return Image.fromarray(arr.astype(np.uint8), "RGB")


# ── Main forge function ───────────────────────────────────────────────────────

@dataclass
class ChallengeManifest:
    challenge_id: str
    scenario: str
    difficulty: str
    title: str
    icon: str
    brief: str
    objective: str
    lore: str
    image_file: str
    image_style: str
    channels_used: list[str]
    encoding: str
    key_hint: str
    # Hidden answer — only revealed with --reveal flag
    _answer: str = ""

    def to_dict(self, reveal: bool = False) -> dict:
        d = asdict(self)
        d.pop("_answer")
        if reveal:
            d["ANSWER"] = self._answer
        return d


def forge(
    scenario: str = "data_exfil",
    difficulty: str = "easy",
    reveal_answer: bool = False,
    output_dir: str | Path = CHALLENGES_DIR,
    key: Optional[str] = None,
) -> ChallengeManifest:
    """
    Generate a complete game challenge package.

    Returns a ChallengeManifest. Saves:
      - <challenge_id>.png    — the stego carrier image
      - <challenge_id>.json   — the challenge manifest
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario '{scenario}'. Valid: {list(SCENARIOS)}")
    if difficulty not in DIFFICULTY_ORDER:
        raise ValueError(f"Unknown difficulty '{difficulty}'.")
    if difficulty == "hard" and not key:
        # Auto-generate a key if none provided
        key = _rand_alpha(12)

    challenge_id = f"{scenario[:4]}_{difficulty[0]}_{_rand_hex(6)}"
    scen = SCENARIOS[scenario]
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Choose image style based on scenario — all styles produce scan-detectable images.
    # Different aesthetics reinforce each scenario's narrative:
    #   gradient   = clean corporate doc / exfil attachment
    #   photo      = social media image / public dead drop
    #   blueprint  = technical diagram / insider leak
    #   thermal    = surveillance / C2 beacon disguise
    #   terminal   = screenshot / whistleblower drop
    style_map = {
        "data_exfil":     "gradient",
        "c2_traffic":     "thermal",
        "dead_drop":      "photo",
        "insider_threat": "blueprint",
        "whistleblower":  "gradient",
    }
    style = style_map.get(scenario, "gradient")

    # Generate the plaintext message and answer
    message, answer = _generate_message(scenario, difficulty, challenge_id)

    # Encode the message according to difficulty
    payload = encode(message, difficulty, key=key)

    # Generate and embed
    from config import DIFFICULTY_CHANNELS
    channels = DIFFICULTY_CHANNELS[difficulty]
    channel_names = [["R", "G", "B"][c] for c in channels]
    encoding_label = {"easy": "PLAINTEXT", "medium": "BASE64", "hard": "XOR+BASE64"}[difficulty]

    cover_img = _generate_cover_image(style)
    img_path = output_dir / f"{challenge_id}.png"

    hide(
        input_path=cover_img,          # pass PIL Image directly (hide accepts path or Image)
        output_path=img_path,
        payload=payload,
        difficulty=difficulty,
    )

    # Build key hint
    if difficulty == "hard" and key:
        key_hint = f"Intel suggests the key is related to: '{key[:3]}***{key[-2:]}'"
    elif difficulty == "medium":
        key_hint = "No key required — but you may need to decode the encoding layer."
    else:
        key_hint = "No key required."

    manifest = ChallengeManifest(
        challenge_id=challenge_id,
        scenario=scenario,
        difficulty=difficulty,
        title=scen["title"],
        icon=scen["icon"],
        brief=scen["brief"],
        objective=scen["objective"],
        lore=scen["lore"][difficulty],
        image_file=str(img_path),
        image_style=style,
        channels_used=channel_names,
        encoding=encoding_label,
        key_hint=key_hint,
        _answer=answer,
    )

    # Save manifest JSON
    manifest_path = output_dir / f"{challenge_id}.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest.to_dict(reveal=reveal_answer), f, indent=2)

    return manifest


# Patch hide() to accept PIL Image as input_path
_original_hide = hide

def hide(input_path, output_path, payload, difficulty="easy"):  # type: ignore[no-redef]
    """Wrapper that accepts a PIL Image or a path."""
    if isinstance(input_path, Image.Image):
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            tmp = tf.name
        input_path.save(tmp, "PNG")
        try:
            result = _original_hide(tmp, output_path, payload, difficulty)
        finally:
            os.unlink(tmp)
        return result
    return _original_hide(input_path, output_path, payload, difficulty)
