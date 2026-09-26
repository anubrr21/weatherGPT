from datetime import datetime, timezone

from app.services.synop import decode_bulletin, visibility_km

BULLETIN = """SMIN01 DEMS 270000
AAXX 27001
42182 41560 60406 10245 20198 39856 40022 57012 60001 70200 81030=
43003 11/58 83508 10267 20232 30073 40096 55005 69911 78081 83820 333 58002=
43057 41560 60406 10245 20198 39856 40022 57012 69901 70200 81030=
43279 NIL=
42809 12970 79999 00105 11012 29085 30102 40131 60104 79590 333 59000=
"""
RECEIVED = datetime(2026, 9, 27, 0, 20, tzinfo=timezone.utc)


def decoded():
    return {o["station"]: o for o in decode_bulletin(BULLETIN, RECEIVED)}


def test_decodes_reports_and_skips_nil():
    obs = decoded()
    assert set(obs) == {"42182", "43003", "42809", "43057"}


def test_new_delhi_values():
    o = decoded()["42182"]
    assert o["name"] == "Safdarjung" and round(o["lat"], 2) == 28.59
    assert o["temp_c"] == 24.5 and o["dewpoint_c"] == 19.8
    assert o["pressure_hpa"] == 1002.2 and o["station_pressure_hpa"] == 985.6
    assert o["wind_dir_deg"] == 40 and o["wind_kmh"] == 21.6
    assert o["visibility_km"] == 10.0 and o["cloud_oktas"] == 6
    assert o["rain_mm"] == 0.0 and o["rain_period_h"] == 6
    assert o["weather"] is None
    assert o["observed_at"] == datetime(2026, 9, 27, 0, 0, tzinfo=timezone.utc)


def test_mumbai_rain_trace_and_weather():
    o = decoded()["43003"]
    assert o["temp_c"] == 26.7 and o["pressure_hpa"] == 1009.6
    assert o["rain_mm"] == 0.1 and o["rain_period_h"] == 6
    assert o["weather"] == "light rain showers"


def test_kolkata_negative_sign_humidity_and_extended_wind():
    o = decoded()["42809"]
    assert o["temp_c"] == -1.2
    assert o["humidity_pct"] == 85
    assert o["wind_kmh"] == round(105 * 3.6, 1)
    assert o["pressure_hpa"] == 1013.1
    assert o["rain_mm"] == 10.0 and o["rain_period_h"] == 24
    assert o["weather"] == "thunderstorm with rain"


def test_visibility_codes():
    assert visibility_km("25") == 2.5
    assert visibility_km("60") == 10.0
    assert visibility_km("85") == 55.0
    assert visibility_km("//") is None


def test_rain_code_990_is_a_trace():
    assert decoded()["43057"]["rain_mm"] == 0.0
