# Stage 1 results (unseen test period)

Chosen settings (picked on the earlier 60% of events only): `Strategy(kappa=1.0, buffer=0.06, blend=0.3, dtypes=('d3', 'd2', 'd1', 's9', 's11', 's13', 's15'), pmin=0.03, pmax=0.97, shares=10.0, max_pos=3, max_outlay=25.0, cost_mode='conservative', sides='YN', fill='normal')`

Test period: 2026-07-15 to 2026-10-03 (81 days with events), 3598 events with data; cut date between train and test: 2026-07-15

## Headline

- Net P&L after 5% taker fees: **$759.34** on 3989 paper trades in 2494 events ($15,776 staked, return on stake +4.8%)
- Same trades with zero fees: $1,153.87 (fees cost $394.53)
- Win rate: 42.4% of trades
- P&L per traded event: $+0.304; 95% range $+0.087 to $+0.529 (events resampled), $+0.041 to $+0.559 (whole days resampled)
- Most recent 7 days: net $-73.25 over 215 events

## Pass bar

- [x] at least 200 traded events in the unseen period: 2494 traded events
- [x] unseen period spans at least 14 days: 81 days
- [x] profitable after fees: net $759.34
- [x] per-event 95% range above zero (events resampled): [+0.087, +0.529] per event
- [x] per-event 95% range above zero (whole days resampled): [+0.041, +0.559] per event
- [ ] still profitable in the most recent 7 days: net $-73.25 over 215 events

**Verdict: FAIL**

## Results by price paid

| price paid | trades | win % | net $ | zero-fee $ | return |
|---|---|---|---|---|---|
| 0.0-0.1 | 515 | 6% | -33.74 | -18.47 | -10.3% |
| 0.1-0.3 | 689 | 21% | 110.34 | 161.44 | +8.6% |
| 0.3-0.5 | 1351 | 45% | 422.58 | 583.48 | +7.7% |
| 0.5-0.7 | 1260 | 61% | 175.81 | 326.77 | +2.4% |
| 0.7-0.9 | 174 | 80% | 84.35 | 100.65 | +6.5% |

## Results by decision time (lead)

| decision | trades | win % | net $ | zero-fee $ | return |
|---|---|---|---|---|---|
| 2 days before | 288 | 59% | -116.46 | -84.65 | -6.5% |
| 1 day before | 601 | 45% | -228.66 | -160.38 | -8.0% |
| morning of the day | 740 | 44% | 106.23 | 185.08 | +3.5% |
| same day 09:00 | 477 | 39% | -36.91 | 8.55 | -2.0% |
| same day 11:00 | 618 | 39% | 180.11 | 237.56 | +8.3% |
| same day 13:00 | 719 | 40% | 432.40 | 498.32 | +18.0% |
| same day 15:00 | 546 | 40% | 422.64 | 469.39 | +25.0% |

## Results by side

| side | trades | win % | net $ | return |
|---|---|---|---|---|
| Buy No | 2789 | 50% | 222.24 | +1.7% |
| Buy Yes | 1200 | 26% | 537.11 | +21.5% |

## Baselines (same costs, fees, sizes, limits)

- Strategy: net $759.34, $+0.304 per traded event
- Always buy the market favourite (Yes): net $-1,570.01 on 6879 trades, $-0.436 per event [-0.586, -0.290]
- Random picks (same count per decision time, 20 draws): net $-433.29 +/- 129.57, $-0.171 per event


## Execution sensitivity (same events and setting)

- conservative spread (the headline numbers): net $759.34, $+0.304 per event [+0.087, +0.529] (3989 trades)
- typical (median) spread: net $883.17, $+0.345 per event [+0.124, +0.566] (4215 trades)
- pessimistic fill: worse of the ask now and at the next 5-minute point: net $119.88, $+0.054 per event [-0.176, +0.297] (3385 trades)
- pessimistic fill with 5 shares instead of 10: net $59.94, $+0.027 per event [-0.088, +0.148] (3385 trades)

## Is the profit broad or a few lucky events?

- Share of traded events that made money: 45%; median event P&L $-1.25
- Best 5% of events (124 events) account for 225% of net P&L; net P&L without them: $-946.73

## Results by month and by resolution source

| group | trades | win % | net $ | return |
|---|---|---|---|---|
| 2026-07 | 727 | 42% | 118.35 | +4.1% |
| 2026-08 | 1544 | 43% | 539.89 | +9.2% |
| 2026-09 | 1584 | 43% | 138.47 | +2.1% |
| 2026-10 | 134 | 42% | -37.36 | -6.4% |
| source: noaa_wrh | 2123 | 43% | 362.58 | +4.2% |
| source: wunderground | 1866 | 42% | 396.77 | +5.5% |

## Is the model better than the market? (log-loss on the official winner, lower = better)

| decision | model | market | events |
|---|---|---|---|
| 2 days before | 1.731 | 1.629 | 547 |
| 1 day before | 1.657 | 1.377 | 3512 |
| morning of the day | 1.481 | 1.223 | 3584 |
| same day 09:00 | 1.454 | 1.183 | 3597 |
| same day 11:00 | 1.319 | 1.080 | 3589 |
| same day 13:00 | 1.026 | 0.835 | 3596 |
| same day 15:00 | 0.542 | 0.432 | 3596 |

## Data notes

Excluded because the airport data could not reproduce Polymarket's official result (rebuilt vs official winner): KDEN (wunderground) 2/5, RCSS (noaa_wrh) 1/1, RKSI (wunderground) 164/189, VHHH (wunderground) 0/2, ZGSZ (wunderground) 36/157, ZSJN (wunderground) 3/54.