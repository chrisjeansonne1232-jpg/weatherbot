from weatherbot.fees import WEATHER_FEE, ZERO_FEE


def test_docs_example_100_shares_at_50c_is_1_25():
    assert WEATHER_FEE.match_fee(100, 0.50) == 1.25


def test_fee_is_symmetric_and_peaks_at_half():
    assert abs(WEATHER_FEE.fee_per_share(0.2) - WEATHER_FEE.fee_per_share(0.8)) < 1e-12
    assert WEATHER_FEE.fee_per_share(0.5) > WEATHER_FEE.fee_per_share(0.3)


def test_extremes_and_rounding():
    assert WEATHER_FEE.fee_per_share(0.0) == 0.0
    assert WEATHER_FEE.fee_per_share(1.0) == 0.0
    # 1 share at 1 cent: 0.05*0.01*0.99 = 0.000495 -> rounds to 0.0005 at 5 decimals
    assert WEATHER_FEE.match_fee(1, 0.01) == 0.0005
    assert ZERO_FEE.match_fee(100, 0.5) == 0.0
