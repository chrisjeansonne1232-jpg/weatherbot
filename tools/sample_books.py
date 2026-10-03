"""Snapshot live order books of all open highest-temperature markets (read-only).

Used to measure real spreads and displayed depth by price level, which the backtest then
uses to price simulated fills (history only stores midpoints, not asks).
Appends one JSON line per market to data/book_samples.jsonl.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import requests  # noqa: E402

from weatherbot import gamma, http  # noqa: E402

CLOB = "https://clob.polymarket.com"


def main() -> None:
    now = time.time()
    out = http.DATA_DIR / "book_samples.jsonl"
    n = 0
    s = requests.Session()
    s.headers["User-Agent"] = http.USER_AGENT
    with out.open("a") as f:
        for raw in gamma.fetch_event_pages(closed=False):
            ev = gamma.parse_event(raw)
            if not ev or not raw.get("active"):
                continue
            for b in ev.brackets:
                r = s.get(CLOB + "/book", params={"token_id": b.yes_token}, timeout=30)
                if r.status_code != 200:
                    continue
                bk = r.json()
                bids = sorted(((float(x["price"]), float(x["size"])) for x in bk.get("bids", [])), reverse=True)[:8]
                asks = sorted((float(x["price"]), float(x["size"])) for x in bk.get("asks", []))[:8]
                f.write(json.dumps({"ts": now, "slug": ev.slug, "city": ev.city, "date": ev.target_date,
                                    "bracket": b.title, "tick": b.tick, "bids": bids, "asks": asks}) + "\n")
                n += 1
                time.sleep(0.12)
    print("sampled", n, "books")


if __name__ == "__main__":
    main()
