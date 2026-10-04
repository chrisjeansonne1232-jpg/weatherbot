"""Step 3: download 5-minute midpoint price history for every bracket (Yes token) of every eligible event.

Newest events first (the unseen test period), then the training period at 1-in-3 sampling
(settings are chosen on training; they do not need every event). Resumable: everything is cached.
"""

import json
import sys
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from weatherbot import http, prices, splits  # noqa: E402

WORKERS = 8


def iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def fetch_event(e: dict) -> int:
    start = int(iso(e["start_date"]).timestamp()) - 3600
    end = int((iso(e["end_date"]) + timedelta(hours=48)).timestamp())
    n = 0
    for b in e["brackets"]:
        prices.price_history(b["yes_token"], start, end)
        n += 1
    return n


def main() -> None:
    events = json.loads((http.DATA_DIR / "events.json").read_text())
    stations = json.loads((http.DATA_DIR / "stations.json").read_text())
    elig = [e for e in splits.eligible(events, stations) if e.get("start_date") and e.get("end_date")]
    cut = splits.freeze_split(elig)
    test = [e for e in elig if not splits.is_train(e, cut)]
    train = [e for e in elig if splits.is_train(e, cut)]
    train_sample = [e for e in train if zlib.crc32(e["event_id"].encode()) % 3 == 0]
    only = sys.argv[1] if len(sys.argv) > 1 else "all"  # "train" | "test" | "all"
    if only == "train":
        todo = sorted(train_sample, key=lambda e: e["target_date"])
    elif only == "test":
        todo = sorted(test, key=lambda e: e["target_date"], reverse=True)
    else:
        todo = sorted(test, key=lambda e: e["target_date"], reverse=True) + sorted(train_sample, key=lambda e: e["target_date"], reverse=True)
    print(f"eligible {len(elig)}; cut date {cut}; test {len(test)}; train {len(train)} (sampled {len(train_sample)})", flush=True)
    done = 0
    with ThreadPoolExecutor(WORKERS) as ex:
        for k, n in enumerate(ex.map(fetch_event, todo), 1):
            done += n
            if k % 100 == 0:
                print(f"{k}/{len(todo)} events, {done} histories", flush=True)
    print("done", done, flush=True)


if __name__ == "__main__":
    main()
