"""Report module — saves crack results to JSON."""
import json
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "output"

def save_results(results: list, source: str = "session") -> str:
    OUTPUT_DIR.mkdir(exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUTPUT_DIR / f"hashcrack_{source}_{ts}.json"

    report = {
        "hashcrack_version": "1.0.0",
        "cracked_at": datetime.now().isoformat(),
        "results": [
            {
                "hash":          r.hash_str,
                "type":          r.hash_type,
                "cracked":       r.cracked,
                "password":      r.password,
                "attempts":      r.attempts,
                "elapsed_secs":  round(r.elapsed_secs, 3),
                "speed":         round(r.attempts_per_sec),
            }
            for r in results
        ],
    }

    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    return str(out_path)
