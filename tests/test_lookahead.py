"""Tests that try to catch the backtest peeking at the future."""
from datetime import date, datetime, timedelta, timezone

import numpy as np

from weatherbot import backtest, costs, forecast, model
from weatherbot.dataset import HOUR, OBS_LAG, Series, StationData, ts
from weatherbot.obs import Obs

UTC = timezone.utc


def fake_station(obs_points, fc=None, tz="UTC", unit="C"):
    """StationData without any network access. obs_points: [(utc datetime, temp_c)]."""
    sd = object.__new__(StationData)
    sd.icao, sd.meta, sd.unit, sd.tz = "TEST", {"tz": tz}, unit, tz
    sd.obs = [Obs(t, None, c, None, False, "") for t, c in obs_points]
    sd.obs_ts = [ts(t) for t, _ in obs_points]
    sd.obs_c = [c for _, c in obs_points]
    sd.obs_read = [float(round(c)) for _, c in obs_points]
    sd.fc = fc or {1: {}, 2: {}, 3: {}}
    sd.fc_n = {k: {h: 1 for h in v} for k, v in sd.fc.items()}
    return sd


def test_vintage_rule_matches_docs_definition():
    S = datetime(2026, 7, 10, 0, tzinfo=UTC)
    for lead in (1, 2, 3):
        t = forecast.earliest_decision_utc(S, lead)
        last_valid_hour = S + timedelta(hours=23)
        init_of_last_run = last_valid_hour - timedelta(hours=24 * lead)  # run behind previous_day{lead}
        assert t >= init_of_last_run + timedelta(hours=forecast.PUBLISH_DELAY_H)
    # and the decision types never go earlier than that
    for name, (lead, off) in model.DECISIONS.items():
        assert S + timedelta(hours=off) >= forecast.earliest_decision_utc(S, lead), name


def test_price_lookup_never_returns_a_future_point():
    s = Series([100.0, 200.0, 300.0], [0.1, 0.2, 0.3])
    assert s.at(99.0) is None
    assert s.at(100.0) == 0.1
    assert s.at(250.0) == 0.2  # not 0.3
    assert s.at(300.0 + 3 * HOUR) is None  # stale price refused


def test_observations_after_decision_time_are_invisible():
    S = datetime(2026, 7, 10, 0, tzinfo=UTC)
    T = S + timedelta(hours=12)
    pts = [(S + timedelta(hours=h, minutes=51), 20.0 + h) for h in range(0, 24)]
    sd = fake_station(pts)
    M, idx = sd.observed_so_far(S, T)
    assert all(sd.obs_ts[i] <= ts(T) - OBS_LAG.total_seconds() for i in idx)
    # 11:51 is only 9 minutes before T (inside the 10-minute publication lag): latest visible is 10:51
    assert M == 30.0
    # a report 5 minutes before T is not visible yet ...
    sd2 = fake_station(sorted(pts + [(T - timedelta(minutes=5), 99.0)], key=lambda p: p[0]))
    assert sd2.observed_so_far(S, T)[0] == 30.0
    # ... but one 20 minutes before T is
    sd3 = fake_station(sorted(pts + [(T - timedelta(minutes=20), 99.0)], key=lambda p: p[0]))
    assert sd3.observed_so_far(S, T)[0] == 99.0


def test_error_statistics_use_only_finished_days():
    sd = fake_station([(datetime(2026, 7, 1, tzinfo=UTC), 20.0)])
    rm = model.ResidualModel({"TEST": sd})
    T = datetime(2026, 7, 20, 7, tzinfo=UTC)
    rows = [model.Row(T - timedelta(days=k, hours=h), 0.0, 0.0) for k in range(0, 10) for h in (0, 3)]
    rm.rows[("TEST", "d1")] = rows
    used = rm._window("TEST", "d1", T)
    assert used and all(r.E <= T - timedelta(hours=1) for r in used)
    assert len(used) < len(rows)  # some rows (ending after T-1h) were excluded


def test_fill_price_is_ask_not_mid():
    for mid in (0.02, 0.1, 0.3, 0.5, 0.75, 0.95):
        ay, an = costs.ask_prices(mid, 0.001)
        assert ay > mid  # buying Yes costs more than the midpoint
        assert an > 1.0 - mid  # buying No costs more than its midpoint
        bid, ask = costs.yes_bid_ask(mid, 0.001)
        assert abs((1.0 - bid) - an) < 1e-9  # mirrored book


def _prep(win=1, q=(0.2, 0.7, 0.1), mid=(0.3, 0.4, 0.3)):
    mid = np.array(mid)
    ay = np.array([costs.ask_prices(m, 0.001)[0] for m in mid])
    an = np.array([costs.ask_prices(m, 0.001)[1] for m in mid])
    asks = {"conservative": (ay, an), "typical": (ay, an)}
    s = backtest.Snap("d1", 0.0, mid, mid / mid.sum(), {1.15: np.array(q)}, asks, asks)
    return backtest.EventPrep({"event_id": "x"}, "2026-07-10", win, len(q), [s])


def test_settlement_uses_official_winner_and_fee():
    p = _prep(win=1)
    st = backtest.Strategy(buffer=0.0, max_pos=1, pmin=0.0, pmax=1.0)
    tr = backtest.simulate([p], st)
    assert len(tr) == 1
    t = tr[0]
    assert t.won == ((p.win == t.bracket) if t.side == "Y" else (p.win != t.bracket))
    expected = t.shares * ((1.0 if t.won else 0.0) - t.price) - t.fee
    assert abs(t.pnl - expected) < 1e-9
    assert t.fee > 0 and t.pnl_nofee > t.pnl


def test_per_event_position_limit_and_one_per_bracket_side():
    p = _prep(q=(0.05, 0.9, 0.05))
    st = backtest.Strategy(buffer=-1.0, max_pos=2, pmin=0.0, pmax=1.0)
    tr = backtest.simulate([p], st)
    assert len(tr) <= 2
    assert len({(t.bracket, t.side) for t in tr}) == len(tr)


def test_observed_max_zeroes_impossible_brackets():
    S = datetime(2026, 7, 10, 0, tzinfo=UTC)
    snap = model.Snap(S, S, S, R=20.0, M=22.0, A=None, n_hours=5)
    br = [{"lo": None, "hi": 20}, {"lo": 21, "hi": 22}, {"lo": 23, "hi": None}]
    p = model.bracket_probs(br, "C", snap, 0.0, 0.0, 1.0)
    assert p[0] == 0.0 and abs(sum(p) - 1) < 1e-9
