"""Step 1: download every resolved daily-temperature event from Gamma into data/events.json."""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from weatherbot import gamma, http  # noqa: E402


def main() -> None:
    out = []
    skipped = Counter()
    for raw in gamma.fetch_event_pages(closed=True):
        ev = gamma.parse_event(raw)
        if ev is None:
            skipped["unparseable"] += 1
            continue
        out.append(ev)
    http.DATA_DIR.mkdir(parents=True, exist_ok=True)
    from dataclasses import asdict

    (http.DATA_DIR / "events.json").write_text(json.dumps([asdict(e) for e in out]))
    print(f"parsed {len(out)} events, skipped {dict(skipped)}")
    dates = sorted(e.target_date for e in out)
    print("date range:", dates[0], "->", dates[-1])


if __name__ == "__main__":
    main()
