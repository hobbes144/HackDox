#!/usr/bin/env python3
"""Turn raw Pixabay downloads in raw_assets/ into clean, game-ready audio.

Source files follow the prefix convention already used in raw_assets/:
  sfx_*  one-shot UI/impact sounds -> trimmed, faded, peak-normalized, mono .wav
  msc_*  background/ambient tracks -> peak-normalized only, stereo .ogg (loop-safe)
  spl_*  longer "inspiration" clips meant to be cut into smaller sfx by hand
         (use the `extract` command with a start/end you pick by ear)

Never touches content/audio/sfx/ or content/audio/music/ directly -- those
filenames are keyed by gameengine.core.audio.SFX_REGISTRY, and picking which
cleaned-up sound becomes which registry id is a game-design call, not
something this script should guess. Everything lands in
raw_assets/processed/ instead; copy+rename the ones you like into sfx/ or
music/ once you've picked.

Usage:
  python process_raw_assets.py list
  python process_raw_assets.py sfx [--file NAME.mp3] [--force]
  python process_raw_assets.py music [--file NAME.mp3] [--force]
  python process_raw_assets.py extract SOURCE.mp3 START END --name new_clip [--force]
    (START/END accept seconds or MM:SS / HH:MM:SS, e.g. 12.4 or 0:12.4)

Requires ffmpeg/ffprobe on PATH (winget install Gyan.FFmpeg -e), or set
FFMPEG_BIN / FFPROBE_BIN to their full paths.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

GAMEENGINE_ROOT = Path(__file__).resolve().parents[2]  # .../gameengine
RAW_DIR = Path(__file__).resolve().parent / "raw_assets"
OUT_DIR = RAW_DIR / "processed"

SFX_TRIM_THRESHOLD_DB = -45
SFX_FADE_IN = 0.008
SFX_FADE_OUT = 0.02
SFX_PEAK_TARGET_DB = -1.0
MUSIC_PEAK_TARGET_DB = -1.0


def _find_binary(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    # winget's install lands outside PATH until the shell restarts -- check
    # its known location so the script works in the same session it installed in.
    winget_root = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if winget_root.exists():
        for exe in winget_root.glob(f"Gyan.FFmpeg*/**/{name}.exe"):
            return str(exe)
    raise FileNotFoundError(
        f"{name} not found on PATH. Install it (winget install Gyan.FFmpeg -e), "
        f"then restart your shell -- or set {name.upper()}_BIN to its full path."
    )


FFMPEG = os.environ.get("FFMPEG_BIN") or _find_binary("ffmpeg")
FFPROBE = os.environ.get("FFPROBE_BIN") or _find_binary("ffprobe")


def _run(args: list[str]) -> str:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{args[0]} failed:\n{proc.stderr}")
    return proc.stderr  # ffmpeg logs progress/filter output to stderr even on success


def duration(path: Path) -> float:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _peak_gain_db(path: Path, target_db: float) -> float:
    """dB to add so the loudest sample in `path` lands at target_db."""
    log = _run([FFMPEG, "-y", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"])
    match = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?) dB", log)
    if not match:
        return 0.0
    return target_db - float(match.group(1))


def _trim_silence(src: Path, dst: Path) -> None:
    """Strip leading/trailing silence. silenceremove only trims from the front,
    so trim -> reverse -> trim -> reverse handles both ends in one filter chain."""
    flt = (
        f"silenceremove=start_periods=1:start_duration=0:"
        f"start_threshold={SFX_TRIM_THRESHOLD_DB}dB:detection=peak,areverse,"
        f"silenceremove=start_periods=1:start_duration=0:"
        f"start_threshold={SFX_TRIM_THRESHOLD_DB}dB:detection=peak,areverse"
    )
    _run([FFMPEG, "-y", "-i", str(src), "-af", flt, str(dst)])


def _finish_sfx(src: Path, dst: Path) -> None:
    """Click-free fade edges + peak-normalize + mono 44.1kHz/16-bit PCM."""
    dur = duration(src)
    fade_out_start = max(dur - SFX_FADE_OUT, 0.0)
    gain = _peak_gain_db(src, SFX_PEAK_TARGET_DB)
    flt = (
        f"afade=t=in:st=0:d={SFX_FADE_IN},"
        f"afade=t=out:st={fade_out_start}:d={SFX_FADE_OUT},"
        f"volume={gain}dB"
    )
    _run([FFMPEG, "-y", "-i", str(src), "-af", flt,
          "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", str(dst)])


def process_sfx_file(src: Path, out_dir: Path, *, force: bool) -> Path:
    dst = out_dir / (src.stem + ".wav")
    if dst.exists() and not force:
        print(f"skip (exists): {dst.name}")
        return dst
    with tempfile.TemporaryDirectory() as tmp:
        trimmed = Path(tmp) / "trimmed.wav"
        _trim_silence(src, trimmed)
        _finish_sfx(trimmed, dst)
    print(f"wrote {dst.relative_to(GAMEENGINE_ROOT)}  ({duration(dst):.2f}s)")
    return dst


def process_music_file(src: Path, out_dir: Path, *, force: bool) -> Path:
    dst = out_dir / (src.stem + ".ogg")
    if dst.exists() and not force:
        print(f"skip (exists): {dst.name}")
        return dst
    gain = _peak_gain_db(src, MUSIC_PEAK_TARGET_DB)
    _run([FFMPEG, "-y", "-i", str(src), "-af", f"volume={gain}dB",
          "-ar", "44100", "-c:a", "libvorbis", "-q:a", "5", str(dst)])
    print(f"wrote {dst.relative_to(GAMEENGINE_ROOT)}  ({duration(dst):.2f}s)")
    return dst


def _parse_timestamp(value: str) -> float:
    if ":" not in value:
        return float(value)
    seconds = 0.0
    for part in value.split(":"):
        seconds = seconds * 60 + float(part)
    return seconds


def extract_clip(src: Path, start: str, end: str, name: str, *, force: bool) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dst = OUT_DIR / f"{name}.wav"
    if dst.exists() and not force:
        raise FileExistsError(f"{dst} already exists -- pass --force to overwrite")
    start_s, end_s = _parse_timestamp(start), _parse_timestamp(end)
    with tempfile.TemporaryDirectory() as tmp:
        cut = Path(tmp) / "cut.wav"
        # -ss before -i seeks the input; -to still counts from the source's
        # original timeline (not the seek point), so start/end stay absolute.
        _run([FFMPEG, "-y", "-ss", str(start_s), "-to", str(end_s),
              "-i", str(src), str(cut)])
        trimmed = Path(tmp) / "trimmed.wav"
        _trim_silence(cut, trimmed)
        _finish_sfx(trimmed, dst)
    print(f"wrote {dst.relative_to(GAMEENGINE_ROOT)}  ({duration(dst):.2f}s)")
    return dst


def cmd_list() -> None:
    groups: dict[str, list[Path]] = {"sfx_": [], "msc_": [], "spl_": [], "other": []}
    for f in sorted(RAW_DIR.glob("*.mp3")):
        for prefix in ("sfx_", "msc_", "spl_"):
            if f.name.startswith(prefix):
                groups[prefix].append(f)
                break
        else:
            groups["other"].append(f)
    for label, files in groups.items():
        if not files:
            continue
        print(f"\n{label} ({len(files)})")
        for f in files:
            print(f"  {f.name:55s} {duration(f):6.2f}s")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list")

    p_sfx = sub.add_parser("sfx")
    p_sfx.add_argument("--file", help="process only this filename in raw_assets/")
    p_sfx.add_argument("--force", action="store_true")

    p_music = sub.add_parser("music")
    p_music.add_argument("--file", help="process only this filename in raw_assets/")
    p_music.add_argument("--force", action="store_true")

    p_extract = sub.add_parser("extract")
    p_extract.add_argument("source", help="filename in raw_assets/ (usually an spl_ clip)")
    p_extract.add_argument("start", help="seconds or MM:SS, e.g. 12.4 or 0:12.4")
    p_extract.add_argument("end", help="seconds or MM:SS")
    p_extract.add_argument("--name", required=True, help="output basename (no extension)")
    p_extract.add_argument("--force", action="store_true")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list()
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.command == "sfx":
        files = [RAW_DIR / args.file] if args.file else sorted(RAW_DIR.glob("sfx_*.mp3"))
        for f in files:
            process_sfx_file(f, OUT_DIR, force=args.force)

    elif args.command == "music":
        files = [RAW_DIR / args.file] if args.file else sorted(RAW_DIR.glob("msc_*.mp3"))
        for f in files:
            process_music_file(f, OUT_DIR, force=args.force)

    elif args.command == "extract":
        extract_clip(RAW_DIR / args.source, args.start, args.end, args.name, force=args.force)


if __name__ == "__main__":
    main()
