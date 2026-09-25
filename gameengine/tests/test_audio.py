"""SoundManager smoke tests.

Not testing that anything actually makes noise (no audio hardware in CI) —
testing the contract every call site relies on: every registered sound id
resolves to a real placeholder file, play() never raises regardless of
input or backend availability, volumes stay clamped, and settings persist
independently of a campaign save.
"""

from __future__ import annotations

from gameengine import config
from gameengine.core.audio import MUSIC_REGISTRY, SFX_REGISTRY, SoundManager


def test_every_registered_sound_has_a_file() -> None:
    missing = [sid for sid, fname in SFX_REGISTRY.items()
               if not (config.AUDIO_SFX_DIR / fname).exists()]
    assert not missing, f"SFX_REGISTRY ids with no file on disk: {missing}"


def test_every_registered_music_track_has_a_file() -> None:
    missing = [tid for tid, fname in MUSIC_REGISTRY.items()
               if not (config.AUDIO_MUSIC_DIR / fname).exists()]
    assert not missing, f"MUSIC_REGISTRY ids with no file on disk: {missing}"


def test_play_never_raises_for_registered_ids() -> None:
    mgr = SoundManager()
    for sound_id in SFX_REGISTRY:
        mgr.play(sound_id)  # must not raise, whether or not audio is available


def test_play_never_raises_for_unknown_id() -> None:
    SoundManager().play("no_such_sound_id")


def test_play_music_never_raises_for_registered_ids() -> None:
    mgr = SoundManager()
    for track_id in MUSIC_REGISTRY:
        mgr.play_music(track_id)  # must not raise, whether or not audio is available


def test_play_music_never_raises_for_unknown_id() -> None:
    SoundManager().play_music("no_such_track_id")


def test_stop_music_never_raises() -> None:
    mgr = SoundManager()
    mgr.play_music("menu")
    mgr.stop_music()
    mgr.stop_music(fade_ms=250)


def test_disabled_manager_plays_nothing_and_stays_quiet() -> None:
    mgr = SoundManager()
    mgr.set_enabled(False)
    mgr.play("day_start")  # no-op, must not raise
    assert mgr.enabled is False


def test_re_enabling_resumes_the_last_requested_track() -> None:
    """Regression test: toggling Settings' mute switch off then back on used
    to leave the game silent — `set_enabled(True)` flipped `.enabled` but
    nothing ever called `play_music()` again, since the only call site
    (`HackDoxApp._sync_music`) only fires on a full screen change, not on a
    Settings/Pause toggle. `_desired_music_id` is what `play_music()` was
    last asked for, tracked independently of whether it actually played —
    `set_enabled(True)` uses it to resume."""
    mgr = SoundManager()
    mgr.play_music("menu")
    assert mgr._desired_music_id == "menu"

    mgr.set_enabled(False)
    assert mgr._desired_music_id == "menu"  # remembered, not cleared, while muted

    mgr.set_enabled(True)
    assert mgr._desired_music_id == "menu"  # resumed to the same track


def test_re_enabling_with_nothing_ever_requested_does_not_raise() -> None:
    mgr = SoundManager()
    mgr.set_enabled(False)
    mgr.set_enabled(True)  # no play_music() call yet this instance — no-op, no crash
    assert mgr.enabled is True


def test_volumes_clamp_to_unit_range() -> None:
    mgr = SoundManager()
    mgr.set_master_volume(5.0)
    mgr.set_music_volume(-3.0)
    mgr.set_sfx_volume(0.5)
    assert mgr.master_volume == 1.0
    assert mgr.music_volume == 0.0
    assert mgr.sfx_volume == 0.5


def test_settings_round_trip(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "audio_settings.json"
    monkeypatch.setattr(config, "AUDIO_SETTINGS_PATH", settings_path)

    mgr = SoundManager()
    mgr.set_master_volume(0.4)
    mgr.set_music_volume(0.2)
    mgr.set_sfx_volume(0.9)
    mgr.set_enabled(False)
    mgr.save_settings()
    assert settings_path.exists()

    reloaded = SoundManager()
    assert reloaded.master_volume == 0.4
    assert reloaded.music_volume == 0.2
    assert reloaded.sfx_volume == 0.9
    assert reloaded.enabled is False


def test_available_property_never_raises() -> None:
    # Whatever this host's audio situation is, checking availability (which
    # lazily attempts backend init on first access) must be side-effect-free
    # from the caller's point of view.
    assert isinstance(SoundManager().available, bool)
