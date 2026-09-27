from datetime import datetime, timedelta

from app.services import smart

NOW = datetime(2026, 9, 27, 7, 0)


def _slots(values, codes=None):
    return [
        {"time": f"{NOW + timedelta(minutes=15 * i):%Y-%m-%dT%H:%M}", "precipitation": v, "weather_code": (codes or {}).get(i, 3)}
        for i, v in enumerate(values)
    ]


def _forecast(hours=None, daily=None):
    base = [{"time": f"{NOW + timedelta(hours=i):%Y-%m-%dT%H:00}", "apparent_temperature": 30, "temperature_2m": 29, "weather_code": 2,
             "wind_gusts_10m": 20, "visibility": 20000, "precipitation_probability": 10, "wind_speed_10m": 8} for i in range(24)]
    for index, patch in (hours or {}).items():
        base[index] |= patch
    return {"hourly": base, "daily": daily or [{"time": f"{NOW:%Y-%m-%d}", "precipitation_sum": 2, "temperature_2m_max": 31}], "elevation": 20}


def test_rain_starting_in_half_an_hour():
    signals = smart.detect(_forecast(), _slots([0, 0, 0.1, 0.8, 1.2, 0.4]), NOW)
    rain = next(s for s in signals if s.kind == "rain_soon")
    assert rain.facts["starts_in_minutes"] == 45
    assert rain.facts["intensity"] == "moderate"
    assert rain.severity == "Info"


def test_thunder_in_nowcast_becomes_a_storm_warning():
    signals = smart.detect(_forecast(), _slots([0, 0.5, 2.0, 3.0], codes={2: 95}), NOW)
    assert [s.kind for s in signals][0] == "storm"
    assert signals[0].severity == "Severe"


def test_already_raining_is_not_rain_soon():
    assert not [s for s in smart.detect(_forecast(), _slots([1.0, 1.0, 1.0]), NOW) if s.kind == "rain_soon"]


def test_heat_only_in_the_morning_window():
    hot = _forecast(hours={6: {"apparent_temperature": 44}})
    assert any(s.kind == "heat" and s.facts["feels_like_peak"] == 44 for s in smart.detect(hot, [], NOW))
    assert not any(s.kind == "heat" for s in smart.detect(hot, [], NOW.replace(hour=14)))


def test_heavy_rain_uses_imd_thresholds():
    daily = [{"time": f"{NOW:%Y-%m-%d}", "precipitation_sum": 120, "precipitation_probability_max": 90}]
    heavy = next(s for s in smart.detect(_forecast(daily=daily), [], NOW) if s.kind == "heavy_rain")
    assert heavy.severity == "Severe" and heavy.facts["category"] == "Very heavy rainfall"


def test_quiet_hours_wrap_midnight():
    assert smart.in_quiet_hours(NOW.replace(hour=23), "22:00", "06:00")
    assert smart.in_quiet_hours(NOW.replace(hour=5, minute=59), "22:00", "06:00")
    assert not smart.in_quiet_hours(NOW.replace(hour=6), "22:00", "06:00")
    assert not smart.in_quiet_hours(NOW, None, "06:00")


def test_briefing_window():
    assert smart.briefing_due(NOW.replace(hour=6, minute=35), "06:30")
    assert not smart.briefing_due(NOW.replace(hour=7, minute=5), "06:30")
    assert not smart.briefing_due(NOW, None)


def test_template_fallback_is_readable():
    title, body = smart._fallback("rain_soon", "Thullur", {"starts_in_minutes": 20, "starts_at": "12:30", "intensity": "heavy"})
    assert "20 min" in title and "Thullur" in title and "Heavy rain" in body
