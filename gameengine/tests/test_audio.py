"""SoundManager smoke tests.

Not testing that anything actually makes noise (no audio hardware in CI) —
testing the contract every call site relies on: every registered sound id
resolves to a real placeholder file, play() never raises regardless of
input or backend availability, volumes stay clamped, and settings persist
independently of a campaign save.
"""

from __future__ import annotations

from gameengine import config
from gameengine.core.audio import SFX_REGISTRY, SoundManager


def test_every_registered_sound_has_a_file() -> None:
    missing = [sid for sid, fname in SFX_REGISTRY.items()
               if not (config.AUDIO_SFX_DIR / fname).exists()]
    assert not missing, f"SFX_REGISTRY ids with no file on disk: {missing}"


def test_play_never_raises_for_registered_ids() -> None:
    mgr = SoundManager()
    for sound_id in SFX_REGISTRY:
        mgr.play(sound_id)  # must not raise, whether or not audio is available


def test_play_never_raises_for_unknown_id() -> None:
    SoundManager().play("no_such_sound_id")


def test_disabled_manager_plays_nothing_and_stays_quiet() -> None:
    mgr = SoundManager()
    mgr.set_enabled(False)
    mgr.play("day_start")  # no-op, must not raise
    assert mgr.enabled is False


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
