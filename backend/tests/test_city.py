from app.services import city


def hour(time, rain=0.0, prob=0, heat=30.0, pm25=20.0, uv=3.0, thunder=False, visibility=10000):
    return {"time": time, "rain": rain, "rain_prob": prob, "heat_index": heat, "pm25": pm25, "uv": uv, "thunder": thunder, "visibility": visibility}


def test_waterlogging_levels_follow_burst_and_daily_totals():
    assert city.flood_level(2, 4, 10) == "none"
    assert city.flood_level(8, 12, 20) == "low"
    assert city.flood_level(16, 25, 40) == "moderate"
    assert city.flood_level(5, 12, 70) == "moderate"
    assert city.flood_level(32, 40, 60) == "high"
    assert city.flood_level(10, 55, 80) == "high"


def test_pm25_bands_use_cpcb_breakpoints():
    assert city.pm25_band(25) == "Good"
    assert city.pm25_band(60) == "Satisfactory"
    assert city.pm25_band(95) == "Poor"
    assert city.pm25_band(300) == "Severe"
    assert city.pm25_band(None) is None


def test_commute_gives_tips_and_a_drier_time():
    hours = [hour(f"2026-10-02T{h:02d}:00") for h in range(24)]
    hours[18] = hour("2026-10-02T18:00", rain=9.0, prob=90, thunder=True)
    hours[17] = hour("2026-10-02T17:00", rain=1.0, prob=60)
    trip = city.commute_block(hours, "2026-10-02", 18, "Evening")
    assert trip["rain_mm"] == 10.0 and trip["thunder"]
    assert any("Thunderstorm" in t for t in trip["tips"]) and any("Heavy rain" in t for t in trip["tips"])
    assert trip["better_time"] in ("2026-10-02T16:00", "2026-10-02T19:00", "2026-10-02T20:00")
    calm = city.commute_block(hours, "2026-10-02", 9, "Morning")
    assert calm["tips"] == ["Comfortable commute"] and calm["better_time"] is None


def test_outdoor_windows_need_two_good_hours_in_a_row():
    hours = [hour(f"2026-10-02T{h:02d}:00", heat=36.0) for h in range(24)]
    for h in (6, 7, 8):
        hours[h] = hour(f"2026-10-02T{h:02d}:00", heat=29.0)
    hours[19] = hour("2026-10-02T19:00", heat=29.0)
    windows = city.outdoor_windows(hours)
    assert windows == [{"start": "2026-10-02T06:00", "end": "2026-10-02T09:00", "hours": 3, "heat_index": 29.0, "pm25": 20}]
