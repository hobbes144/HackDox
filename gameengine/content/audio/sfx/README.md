# SFX

Most ids in `SFX_REGISTRY` (`gameengine/core/audio.py`) now point at real
processed audio rather than the original synthesized placeholders — real
audio has been dropped in filename-by-filename over several sessions, and
call sites never needed to change since they key off the sound *id*, not
the file. As of 2026-09-24, only these four are still the original
generated placeholder tone from `../generate_placeholders.py`:

  - `credit_use.wav`
  - `pulse_celebration.wav`
  - `transition_glitch.wav`
  - `upgrade_purchase.wav`

Everything else in this folder is real audio (see
`../raw_assets/credits.txt` for sourcing).

To replace a placeholder (or any file) with real audio: drop a new file at
the **same filename** (e.g. `verdict_correct_accept.wav`) — `SFX_REGISTRY`
and every call site key off the id, so nothing else needs to change. Mono
or stereo, any sample rate pygame's mixer supports (44.1kHz/16-bit is what
the generator writes and what `../process_raw_assets.py` outputs).

To add a brand new trigger point: add an id -> filename entry to
`SFX_REGISTRY` in `gameengine/core/audio.py`, drop a file here (or a quick
recipe in `generate_placeholders.py` to placeholder it), and call
`sound_manager.play("your_new_id")` at the trigger site.

## Spliced, not yet wired to an id

These were cut from multi-chunk Epidemic Sound clips via
`../process_raw_assets.py extract` and dropped here so they're ready
whenever a trigger point is picked for them — no registry entry points at
them yet:

  - `ui_data_process_01.wav` .. `ui_data_process_04.wav` — four chunks
    from *ES User Interface, Data, Data Process 10* (candidate: the
    between-day shop's ability-upgrade purchase, per Nick — pick one of
    the four, or use them as a sequence).
  - `ui_data_calc_short.wav` — the one chunk in *ES User Interface, Data,
    Futuristic Technology, UI Data Calculations, Short 04* (it's already
    a single atomic stinger, not a multi-chunk source).
