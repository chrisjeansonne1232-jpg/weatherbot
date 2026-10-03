"""Summarise live book snapshots into data/spread_table.json (median and p75 spread by mid bucket)."""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from weatherbot import http  # noqa: E402

EDGES = [0.01, 0.03, 0.08, 0.15, 0.30, 0.50001]


def main() -> None:
    rows = [json.loads(l) for l in (http.DATA_DIR / "book_samples.jsonl").read_text().splitlines() if l.strip()]
    # only markets whose target day is still in the future at snapshot time (not already settled)
    from datetime import datetime, timezone
    keep = []
    for r in rows:
        day_end = datetime.fromisoformat(r["date"]).replace(tzinfo=timezone.utc).timestamp() + 86400
        if r["bids"] and r["asks"] and day_end - r["ts"] > 24 * 3600:
            keep.append(r)
    buckets, lo = [], 0.0
    for edge in EDGES:
        sp = [r["asks"][0][0] - r["bids"][0][0] for r in keep
              if lo <= min((r["asks"][0][0] + r["bids"][0][0]) / 2, 1 - (r["asks"][0][0] + r["bids"][0][0]) / 2) < edge]
        if len(sp) >= 5:
            buckets.append([edge, float(np.median(sp)), float(np.percentile(sp, 75)), len(sp)])
        lo = edge
    (http.DATA_DIR / "spread_table.json").write_text(json.dumps({"n_books": len(keep), "buckets": [b[:3] for b in buckets]}))
    print(f"{len(keep)} books ->", buckets)


if __name__ == "__main__":
    main()
