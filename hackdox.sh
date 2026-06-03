#!/usr/bin/env bash
# HackDox launcher — sets up the shared venv if needed, then runs the game.
#
# Usage:
#   ./hackdox.sh              — launch the Textual TUI (play)
#   ./hackdox.sh simulate     — headless Day 1 verdict table (no TUI)
#   ./hackdox.sh new-game     — reset save slot
#   ./hackdox.sh inspect      — inspect a single candidate
#   ./hackdox.sh <any args>   — passed straight through to hackdox.py

set -euo pipefail

VENV=/tmp/hackdox-venv
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
GAMEENGINE="$REPO_ROOT/gameengine"

# ── 1. Build venv if missing or incomplete ───────────────────────────────────
if [ ! -f "$VENV/.hackdox-ready" ]; then
  echo "⚙  Building shared venv at $VENV …"
  rm -rf "$VENV"
  python3 -m venv "$VENV"
  "$VENV/bin/python" -m ensurepip --upgrade
  "$VENV/bin/pip" install -q \
    textual rich typer httpx bcrypt Pillow numpy scipy pytest socksio
  touch "$VENV/.hackdox-ready"
  echo "✓  Venv ready."
fi

# ── 2. Run ───────────────────────────────────────────────────────────────────
cd "$GAMEENGINE"

# Default to 'play' if no args given
if [ $# -eq 0 ]; then
  PYTHONPATH="$REPO_ROOT" exec "$VENV/bin/python" hackdox.py play
else
  PYTHONPATH="$REPO_ROOT" exec "$VENV/bin/python" hackdox.py "$@"
fi
