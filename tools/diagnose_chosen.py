"""Stress-test a chosen setting on TRAINING events only (never the test period)."""
import sys
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_backtest as rb  # noqa: E402
from weatherbot import backtest as bt  # noqa: E402


def line(s):
    return (f"net ${s.net:,.2f} zero-fee ${s.gross:,.2f} trades {s.n_trades} events {s.n_events_traded} "
            f"per-event ${s.mean_event_pnl:+.3f} [{s.ci_event[0]:+.3f},{s.ci_event[1]:+.3f}] date-clustered [{s.ci_date[0]:+.3f},{s.ci_date[1]:+.3f}]")


def main() -> None:
    elig, meta, cut, _ = rb.load_everything()
    train, _ = rb.build(elig, meta, cut, include_test=False)
    best = bt.Strategy(kappa=1.0, buffer=0.06, blend=0.3)
    tr = bt.simulate(train, best)
    print("CHOSEN (train):", line(bt.summarize(train, tr)), "\n")
    print("By side:")
    for k, n, w, net, g, cost in bt.breakdown(tr, lambda t: "Buy Yes" if t.side == "Y" else "Buy No"):
        print(f"  {k:8s} trades {n:5d} win {100*w/n:5.1f}% net ${net:9.2f} zero-fee ${g:9.2f} return {100*net/cost:+6.1f}%")
    print("By price paid:")
    for k, n, w, net, g, cost in bt.breakdown(tr, bt.price_bucket):
        print(f"  {k:8s} trades {n:5d} win {100*w/n:5.1f}% net ${net:9.2f} zero-fee ${g:9.2f} return {100*net/cost:+6.1f}%")
    print("By decision time:")
    for k, n, w, net, g, cost in bt.breakdown(tr, lambda t: t.dtype, order=list(rb.model.DECISIONS)):
        print(f"  {k:4s} trades {n:5d} win {100*w/n:5.1f}% net ${net:9.2f} zero-fee ${g:9.2f} return {100*net/cost:+6.1f}%")
    print("By month:")
    for k, n, w, net, g, cost in bt.breakdown(tr, lambda t: t.day[:7]):
        print(f"  {k} trades {n:5d} win {100*w/n:5.1f}% net ${net:9.2f} return {100*net/cost:+6.1f}%")
    pe = np.array(sorted(bt.per_event(tr).values()))
    top = pe[-int(len(pe) * 0.05):].sum()
    print(f"\nConcentration: top 5% of events = {100*top/pe.sum():.0f}% of total net P&L; "
          f"median event P&L ${np.median(pe):+.2f}; share of events with a profit {100*(pe>0).mean():.0f}%; "
          f"net without the best 5% of events: ${pe.sum()-top:,.2f}")
    print("\nSensitivity (same events, same setting):")
    for label, st in [("conservative spread (default)", best), ("typical spread", replace(best, cost_mode="typical")),
                      ("PESSIMISTIC fill (worse of ask now / next point)", replace(best, fill="pessimistic")),
                      ("pessimistic + 10 shares -> 5 shares", replace(best, fill="pessimistic", shares=5.0))]:
        print(f"  {label:50s}", line(bt.summarize(train, bt.simulate(train, st))))
    fav = bt.simulate(train, replace(best, pmin=0.0, pmax=1.0), picker=bt.favourite_picker)
    rn, rs, rpe = bt.random_baseline(train, best, tr)
    print(f"\nBaselines on train: favourite {line(bt.summarize(train, fav))}")
    print(f"                    random (20 draws) net ${rn:,.2f} +/- {rs:,.2f}, ${rpe:+.3f} per event")


if __name__ == "__main__":
    main()
