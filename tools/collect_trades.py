"""Download real public fills for a deterministic ~4% sample of test-period events.

Used only to audit the backtest's fill model (do real taker buys pay at least midpoint + my
assumed half-spread?). Never used to pick trades.
"""

import json
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from weatherbot import http, prices, splits  # noqa: E402


def main() -> None:
    events = json.loads((http.DATA_DIR / "events.json").read_text())
    stations = json.loads((http.DATA_DIR / "stations.json").read_text())
    elig = splits.eligible(events, stations)
    cut = splits.freeze_split(elig)
    sample = [e for e in elig if not splits.is_train(e, cut) and zlib.crc32(e["event_id"].encode()) % 25 == 0]
    print(f"{len(sample)} sample events", flush=True)
    out = {}
    for k, e in enumerate(sample, 1):
        rows = {}
        for b in e["brackets"]:
            rows[b["yes_token"]] = prices.trades(b["condition_id"], limit=500)
        out[e["event_id"]] = rows
        if k % 10 == 0:
            print(f"{k}/{len(sample)}", flush=True)
    (http.DATA_DIR / "trades_sample.json").write_text(json.dumps(out))
    print("saved", len(out), flush=True)


if __name__ == "__main__":
    main()
