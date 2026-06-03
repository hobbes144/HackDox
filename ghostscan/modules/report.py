"""
Report module
-------------
Saves all scan results to a JSON file in the ./output/ directory.
"""

import json
import os
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "output"


def save_report(target: str, scan_results: dict) -> str:
    """
    Save scan results to a JSON file.
    Returns the path to the saved file.
    """
    OUTPUT_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_target = "".join(c for c in target if c.isalnum() or c in "._-@")
    filename = f"ghostscan_{safe_target}_{timestamp}.json"
    filepath = OUTPUT_DIR / filename

    report = {
        "ghostscan_version": "1.0.0",
        "target": target,
        "scanned_at": datetime.now().isoformat(),
        "results": scan_results,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    return str(filepath)
