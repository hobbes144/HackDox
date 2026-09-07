# Background music (not wired up yet)

No trigger point currently starts background music — `SoundManager.play_music()`
/ `stop_music()` in `gameengine/core/audio.py` are ready to use, and
`config.DEFAULT_MUSIC_VOLUME` / the "music" volume knob already exist, but
nothing calls them yet. Drop a loopable track here and call
`sound_manager.play_music("your_track.ogg")` (e.g. from
`HackDoxApp.begin_intake()`) whenever ambient music is wanted for a scene.
