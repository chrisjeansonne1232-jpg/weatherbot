"""Do real taker trades pay at least midpoint + my modelled half-spread?

For every public BUY of the Yes token in the sampled test-period events, compare the trade price
with the midpoint from the price history at the last point before the trade, by midpoint bucket,
and with the conservative / typical half-spreads used by the backtest.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from weatherbot import costs, dataset, http, prices  # noqa: E402

BUCKETS = [(0.0, 0.03), (0.03, 0.1), (0.1, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.0)]


def main() -> None:
    sample = json.loads((http.DATA_DIR / "trades_sample.json").read_text())
    events = {e["event_id"]: e for e in json.loads((http.DATA_DIR / "events.json").read_text())}
    diffs = {b: [] for b in BUCKETS}
    sizes = {b: [] for b in BUCKETS}
    n_all = 0
    for eid, toks in sample.items():
        e = events[eid]
        series = dataset.load_series(e)
        if series is None:  # fetch on demand (cached, polite)
            start = int(datetime.fromisoformat(e["start_date"].replace("Z", "+00:00")).timestamp()) - 3600
            end = int((datetime.fromisoformat(e["end_date"].replace("Z", "+00:00")) + timedelta(hours=48)).timestamp())
            for b in e["brackets"]:
                prices.price_history(b["yes_token"], start, end, 60)
            series = dataset.load_series(e)
        for br, s in zip(e["brackets"], series):
            for tr in toks[br["yes_token"]]:
                if tr["outcome"] != "Yes" or tr["side"] != "BUY":
                    continue
                mid = s.at(tr["timestamp"] - 60, max_age=2 * 3600)
                if mid is None:
                    continue
                n_all += 1
                for lo, hi in BUCKETS:
                    if lo <= mid < hi:
                        diffs[(lo, hi)].append(tr["price"] - mid)
                        sizes[(lo, hi)].append(tr["size"])
    print(f"{n_all} real taker BUYs of Yes in {len(sample)} sampled test events")
    print(f"{'mid bucket':>11} {'n':>6} {'median paid-mid':>16} {'mean':>8} {'p25':>7} {'p75':>7} | model half-spread: typical  conservative | share of real buys paying LESS than conservative")
    for b in BUCKETS:
        d = np.array(diffs[b])
        if len(d) < 20:
            continue
        mid_c = (b[0] + b[1]) / 2
        h_t = costs.spread(mid_c, "typical") / 2
        h_c = costs.spread(mid_c, "conservative") / 2
        print(f"{b[0]:>4.2f}-{b[1]:<5.2f} {len(d):>6} {np.median(d):>16.4f} {d.mean():>8.4f} {np.percentile(d,25):>7.4f} {np.percentile(d,75):>7.4f} |"
              f" {h_t:>22.4f} {h_c:>13.4f} | {100*(d < h_c).mean():>5.1f}%")


if __name__ == "__main__":
    main()
