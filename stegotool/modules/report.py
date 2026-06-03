"""
report.py — JSON report saver for stegotool.

Mirrors the pattern used by logwatch and hashcrack: every operation
can optionally save its results to output/ as a timestamped JSON file.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from config import OUTPUT_DIR


def save_report(operation: str, data: dict[str, Any], output_dir: str | Path = OUTPUT_DIR) -> Path:
    """
    Save `data` as a JSON report in output_dir.

    File is named: <operation>_<timestamp>.json
    Returns the path of the saved file.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{operation}_{timestamp}.json"
    path = out / filename

    report = {
        "tool": "stegotool",
        "operation": operation,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        **data,
    }

    with open(path, "w") as f:
        json.dump(report, f, indent=2)

    return path
