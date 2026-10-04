"""Training-period diagnostics only: is the model's probability better than the market's, and when?"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_backtest as rb  # noqa: E402
from weatherbot import backtest as bt  # noqa: E402

NAMES = {"d3": "2 days before", "d2": "1 day before", "d1": "morning of day", "s9": "same day 09:00",
         "s11": "same day 11:00", "s13": "same day 13:00", "s15": "same day 15:00"}


def main() -> None:
    elig, meta, cut, excluded = rb.load_everything()
    train, _ = rb.build(elig, meta, cut, include_test=False)
    print(f"{len(train)} training events\n")
    print("Log-loss on the official winner (lower is better). 'blend' mixes 30% model + 70% market midpoint.")
    print(f"{'decision':>16} {'n':>6} | {'model k=1.0':>11} {'k=1.3':>7} {'blend30':>8} {'market':>8} | model better than market?")
    for k in NAMES:
        ml, ml3, bl, mk, n = 0.0, 0.0, 0.0, 0.0, 0
        for p in train:
            for s in p.snaps:
                if s.dtype != k:
                    continue
                w = p.win
                ml += -np.log(max(s.q[1.0][w], 1e-4))
                ml3 += -np.log(max(s.q[1.3][w], 1e-4))
                bl += -np.log(max(0.3 * s.q[1.0][w] + 0.7 * s.mid_norm[w], 1e-4))
                mk += -np.log(max(s.mid_norm[w], 1e-4))
                n += 1
        if n:
            print(f"{NAMES[k]:>16} {n:>6} | {ml/n:>11.4f} {ml3/n:>7.4f} {bl/n:>8.4f} {mk/n:>8.4f} | {'YES' if ml < mk else 'no'} (blend {'better' if bl < mk else 'worse'})")


if __name__ == "__main__":
    main()
