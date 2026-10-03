from datetime import date, datetime, timezone

from weatherbot import gamma, resolve
from weatherbot.obs import Obs, parse_metar_temp

UTC = timezone.utc


def test_bracket_titles():
    assert gamma.parse_bracket_title("62-63°F") == (62.0, 63.0, "F")
    assert gamma.parse_bracket_title("61°F or below") == (None, 61.0, "F")
    assert gamma.parse_bracket_title("80°F or higher") == (80.0, None, "F")
    assert gamma.parse_bracket_title("17°C") == (17.0, 17.0, "C")
    assert gamma.parse_bracket_title("-2°C or below") == (None, -2.0, "C")
    assert gamma.parse_bracket_title("Will it rain?") is None


def test_station_from_both_resolution_sources():
    assert gamma.station_from_source("https://www.weather.gov/wrh/timeseries?site=klga") == "KLGA"
    assert gamma.station_from_source("https://www.wunderground.com/history/daily/us/ny/new-york-city/KLGA") == "KLGA"
    assert gamma.station_from_source("https://www.wunderground.com/history/daily/gb/london/EGLC") == "EGLC"
    assert gamma.station_from_source("") is None
    assert gamma.source_kind("https://www.weather.gov/wrh/timeseries?site=klga") == "noaa_wrh"


def test_metar_temperature_parsing():
    body, t = parse_metar_temp("KLGA 200051Z 14009KT 10SM BKN250 19/12 A3016 RMK AO2 SLP213 T01940122 $")
    assert body == 19.0 and abs(t - 19.4) < 1e-9
    body, t = parse_metar_temp("EGLC 031120Z 25008KT 9999 FEW040 M02/M05 Q1021")
    assert body == -2.0 and t is None
    body, t = parse_metar_temp("XXXX 031120Z 25008KT 9999 05/03 Q1021 RMK T10451020")
    assert t == -4.5  # sign bit 1 = below zero


def _obs(h, c, m=51):
    return Obs(datetime(2026, 7, 10, h, m, tzinfo=UTC), None, c, None, False, "")


def test_daily_max_local_day_and_rounding():
    # New York is UTC-4 in July: local 2026-07-10 = 04:00Z that day to 04:00Z next day
    obs = [_obs(3, 30.0), _obs(18, 29.4), _obs(19, 29.5)]  # 03:51Z belongs to the previous local day
    m, n = resolve.daily_max(obs, "America/New_York", date(2026, 7, 10), "F")
    assert n == 2
    assert m == round(29.5 * 9 / 5 + 32)  # 85.1 F -> 85
    m_c, _ = resolve.daily_max(obs, "America/New_York", date(2026, 7, 10), "C")
    assert m_c == 30.0  # 29.5 rounds half UP to 30 (not banker's rounding)


def test_bracket_index_open_and_closed_ends():
    br = [{"lo": None, "hi": 60}, {"lo": 61, "hi": 62}, {"lo": 63, "hi": None}]
    assert resolve.bracket_index(br, 55) == 0
    assert resolve.bracket_index(br, 62) == 1
    assert resolve.bracket_index(br, 90) == 2
