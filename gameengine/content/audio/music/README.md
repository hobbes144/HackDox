# Background music

Two looping tracks, registered in `MUSIC_REGISTRY` in
`gameengine/core/audio.py`:

- `hackdox_music.ogg` (id `"menu"`) — HackDox's theme. Plays on every
  non-gameplay screen (start menu, briefing, between-day shop, EOD, ...).
- `hackdox_ambient.ogg` (id `"ambient"`) — the intake screen's ambient bed.
  Loops under every SFX cue while a shift is worked, including with the
  rules overlay or evidence board open. Kept quieter than `"menu"` via
  `MUSIC_TRACK_VOLUME_SCALE` (0.5x) since it has to sit under those cues
  rather than play alone.

`HackDoxApp._sync_music()` in `gameengine/ui/tui/app.py` picks the track for
whichever screen the player just landed on and calls
`sound_manager.play_music(track_id)`. That call is idempotent — it no-ops
if the requested track is already playing — so the theme keeps running
uninterrupted as the player moves between menus, and the ambient loop keeps
running uninterrupted as they navigate pages/overlays within intake. It's
called from `HackDoxApp._swap_screen()` (the one place every screen change
eventually goes through) and once more from `on_mount()` for the very first
screen, which is pushed before any transition runs.

To add a third track (a boss-day theme, a game-over sting, etc.): add an
id -> filename entry to `MUSIC_REGISTRY`, optionally a volume scale in
`MUSIC_TRACK_VOLUME_SCALE` (defaults to 1.0), drop the file here, and call
`sound_manager.play_music("your_new_id")` at the trigger site — or extend
`_sync_music`'s screen -> track mapping if it should apply automatically
based on which screen is showing.

Source credits for both tracks are in `../raw_assets/credits.txt`.
