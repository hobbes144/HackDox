"""SoundManager — lazy, fail-soft audio playback for the Textual UI.

Textual has no built-in audio; sound is played independently through
pygame.mixer, a plain OS-level call unrelated to terminal rendering. Every
public method here degrades to a silent no-op if pygame isn't installed,
if the mixer can't init (no audio device — CI, headless boxes, some Linux
setups), or if sound is turned off in settings — so call sites never need
to guard a `sound_manager.play(...)` call themselves, and importing this
module is always safe even where pygame hasn't been pip-installed yet.

Adding a new trigger point anywhere in the game is always the same
two-line change:
  1. add "<new_id>": "<file>.wav" to SFX_REGISTRY below
  2. call sound_manager.play("<new_id>") at the trigger site

Sound files are looked up by id against config.AUDIO_SFX_DIR. Every id
currently in the registry points at a generated placeholder tone (see
gameengine/content/audio/sfx/README.md) — swap the files whenever real
audio is ready; call sites never need to change, since they key off the
id, not the filename.
"""

from __future__ import annotations

import json
import logging

from gameengine import config

logger = logging.getLogger(__name__)

try:
    import pygame
    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - environment dependent
    pygame = None
    _IMPORT_ERROR = exc


# ─── Sound registry ─────────────────────────────────────────────────────────
# One entry per known trigger point. Keys are the ids call sites pass to
# sound_manager.play(...); values are filenames under config.AUDIO_SFX_DIR.

SFX_REGISTRY: dict[str, str] = {
    # Verdict delivery — correct/incorrect (per the rules) crossed with
    # accept=ADMIT / deny=DENY (what the player actually did).
    "verdict_correct_accept":   "verdict_correct_accept.wav",
    "verdict_correct_deny":     "verdict_correct_deny.wav",
    "verdict_incorrect_accept": "verdict_incorrect_accept.wav",
    "verdict_incorrect_deny":   "verdict_incorrect_deny.wav",

    # Tool runs — one per tool, on the first (unfiltered) run of the day.
    # STEGOTOOL has no flat "run"; entering the stamp minigame stands in
    # for it (see gameengine/ui/tui/screens/intake.py:_enter_stamp_mode).
    "tool_run_ghostscan": "tool_run_ghostscan.wav",
    "tool_run_hashcrack": "tool_run_hashcrack.wav",
    "tool_run_logwatch":  "tool_run_logwatch.wav",
    "tool_run_stegotool": "tool_run_stegotool.wav",

    # Stegotool stamp minigame — a single stamp placed on the image.
    "stego_stamp": "stego_stamp.wav",

    # Day cycle.
    "day_start": "day_start.wav",
    "day_end":   "day_end.wav",

    # Soft, frequent UI ticks — kept quiet by the placeholder assets
    # themselves so they don't fatigue the player at default volume.
    "overseer_tick": "overseer_tick.wav",   # a narrative line finishes typing
    "focus_switch":  "focus_switch.wav",    # arrow-key focus moves between panes
    "page_switch":   "page_switch.wav",     # number-key page change (1-5)

    # Rules overlay.
    "rules_open":  "rules_open.wav",
    "rules_close": "rules_close.wav",

    # Evidence board (the flaggable violation checklist).
    "evidence_open":  "evidence_open.wav",
    "evidence_close": "evidence_close.wav",
    "evidence_flag":  "evidence_flag.wav",   # a violation is marked "present"

    # Economy.
    "credit_use":   "credit_use.wav",    # a HackDox Credit is spent
    "filter_apply": "filter_apply.wav",  # an enhanced/filtered tool re-run
    "upgrade_purchase": "upgrade_purchase.wav",  # between-day shop: an upgrade is bought

    # Candidate-page verdict pulse (the border flash, not the commit itself).
    "pulse_celebration": "pulse_celebration.wav",
    "pulse_error":       "pulse_error.wav",

    # Screen transitions — the glitch that covers a full-screen change
    # (see ui/tui/screens/transition.py). Fires once, at the start of the
    # window, not per half.
    "transition_glitch": "transition_glitch.wav",
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


class SoundManager:
    """Owns the mixer, the three volume knobs, and a small settings file.

    One shared instance (`sound_manager`, at the bottom of this module) is
    imported everywhere, the same way `gameengine.config` is imported as a
    module rather than instantiated per caller. Every public method is safe
    to call even when audio is completely unavailable.
    """

    def __init__(self) -> None:
        self._available: bool | None = None  # None = backend not tried yet
        self._sounds: dict[str, object] = {}
        self.enabled = config.SOUND_ENABLED_DEFAULT
        self.master_volume = config.DEFAULT_MASTER_VOLUME
        self.music_volume  = config.DEFAULT_MUSIC_VOLUME
        self.sfx_volume    = config.DEFAULT_SFX_VOLUME
        self._load_settings()

    # ── Backend lifecycle (lazy — nothing touches pygame until the first
    # actual play() / play_music() call, so merely importing this module,
    # e.g. transitively via a test import, never spends startup time or
    # opens an audio device) ────────────────────────────────────────────
    def _ensure_backend(self) -> bool:
        if self._available is not None:
            return self._available
        if pygame is None:
            logger.info(
                "SoundManager: pygame not installed — audio disabled (%s)",
                _IMPORT_ERROR,
            )
            self._available = False
            return False
        try:
            pygame.mixer.init()
            self._available = True
        except Exception as exc:  # pragma: no cover - depends on host audio
            logger.info("SoundManager: mixer init failed — audio disabled (%s)", exc)
            self._available = False
        return self._available

    @property
    def available(self) -> bool:
        """True only once pygame is installed AND the mixer has initialised.
        Triggers backend init on first access."""
        return self._ensure_backend()

    # ── Settings persistence — deliberately separate from campaign saves
    # (core/persistence.py): a volume preference is a device/player setting,
    # not part of any one save slot. ────────────────────────────────────
    def _load_settings(self) -> None:
        path = config.AUDIO_SETTINGS_PATH
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
        except Exception as exc:  # pragma: no cover
            logger.info("SoundManager: could not read audio settings (%s)", exc)
            return
        self.enabled       = bool(data.get("enabled", self.enabled))
        self.master_volume = _clamp01(float(data.get("master_volume", self.master_volume)))
        self.music_volume  = _clamp01(float(data.get("music_volume", self.music_volume)))
        self.sfx_volume    = _clamp01(float(data.get("sfx_volume", self.sfx_volume)))

    def save_settings(self) -> None:
        """Call after a settings screen changes a volume or the mute toggle.
        Nothing calls this automatically today — wire it up when a settings
        UI exists; until then the constructor defaults (or a hand-edited
        audio_settings.json) apply."""
        data = {
            "enabled": self.enabled,
            "master_volume": self.master_volume,
            "music_volume": self.music_volume,
            "sfx_volume": self.sfx_volume,
        }
        try:
            config.AUDIO_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            config.AUDIO_SETTINGS_PATH.write_text(json.dumps(data, indent=2))
        except Exception as exc:  # pragma: no cover
            logger.info("SoundManager: could not save audio settings (%s)", exc)

    # ── Volume / mute controls (0.0-1.0, clamped) ────────────────────────
    def set_master_volume(self, value: float) -> None:
        self.master_volume = _clamp01(value)
        self._apply_music_volume()

    def set_music_volume(self, value: float) -> None:
        self.music_volume = _clamp01(value)
        self._apply_music_volume()

    def set_sfx_volume(self, value: float) -> None:
        self.sfx_volume = _clamp01(value)

    def set_enabled(self, value: bool) -> None:
        self.enabled = value
        if not value:
            self.stop_music()

    def _apply_music_volume(self) -> None:
        if self._available:
            try:
                pygame.mixer.music.set_volume(self.master_volume * self.music_volume)
            except Exception:  # pragma: no cover
                pass

    # ── One-shot SFX playback ────────────────────────────────────────────
    def play(self, sound_id: str) -> None:
        """Fire-and-forget playback of a one-shot sound effect. Non-blocking
        (pygame.mixer.Sound.play() returns immediately on its own channel),
        so this never stalls the Textual event loop. Always safe to call:
        silently does nothing if muted, unavailable, or the id/file is
        missing."""
        if not self.enabled:
            return
        if not self._ensure_backend():
            return
        sound = self._get_sound(sound_id)
        if sound is None:
            return
        try:
            sound.set_volume(self.master_volume * self.sfx_volume)
            sound.play()
        except Exception as exc:  # pragma: no cover
            logger.debug("SoundManager: play(%r) failed (%s)", sound_id, exc)

    def _get_sound(self, sound_id: str):
        if sound_id in self._sounds:
            return self._sounds[sound_id]
        filename = SFX_REGISTRY.get(sound_id)
        if filename is None:
            logger.debug("SoundManager: unknown sound id %r", sound_id)
            self._sounds[sound_id] = None
            return None
        path = config.AUDIO_SFX_DIR / filename
        if not path.exists():
            logger.debug("SoundManager: missing sfx file %s", path)
            self._sounds[sound_id] = None
            return None
        try:
            sound = pygame.mixer.Sound(str(path))
        except Exception as exc:  # pragma: no cover
            logger.debug("SoundManager: could not load %s (%s)", path, exc)
            sound = None
        self._sounds[sound_id] = sound
        return sound

    # ── Background music — plumbing for future ambient tracks. No trigger
    # point calls this yet (none was asked for); it's here so a day/page
    # ambience can be added later as a one-line change. ──────────────────
    def play_music(self, filename: str, *, loop: bool = True) -> None:
        if not self.enabled or not self._ensure_backend():
            return
        path = config.AUDIO_MUSIC_DIR / filename
        if not path.exists():
            logger.debug("SoundManager: missing music file %s", path)
            return
        try:
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.set_volume(self.master_volume * self.music_volume)
            pygame.mixer.music.play(-1 if loop else 0)
        except Exception as exc:  # pragma: no cover
            logger.debug("SoundManager: play_music(%r) failed (%s)", filename, exc)

    def stop_music(self, *, fade_ms: int = 0) -> None:
        if not self._available:
            return
        try:
            if fade_ms > 0:
                pygame.mixer.music.fadeout(fade_ms)
            else:
                pygame.mixer.music.stop()
        except Exception:  # pragma: no cover
            pass


# Shared instance — import this, not the class:
#   from gameengine.core.audio import sound_manager
#   sound_manager.play("day_start")
sound_manager = SoundManager()
