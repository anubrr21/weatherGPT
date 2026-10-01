from app.services import command, research


def test_imd_rainfall_bands():
    assert command.rain_band(1.0) == ("Dry", 0)
    assert command.rain_band(10.0) == ("Light", 0)
    assert command.rain_band(30.0) == ("Moderate", 1)
    assert command.rain_band(64.5) == ("Heavy", 2)
    assert command.rain_band(150.0) == ("Very heavy", 3)
    assert command.rain_band(210.0) == ("Extremely heavy", 4)


def test_town_summary_scores_rain_wind_and_heat():
    times = [f"2026-10-01T{h:02d}:00" for h in range(24)] + [f"2026-10-02T{h:02d}:00" for h in range(24)] + [f"2026-10-03T{h:02d}:00" for h in range(24)]
    hourly = {
        "time": times, "precipitation": [1.0] * 24 + [4.0] * 24 + [0.0] * 24, "wind_gusts_10m": [20] * 24 + [55] * 24 + [10] * 24,
        "temperature_2m": [30] * 72, "relative_humidity_2m": [60] * 72, "weather_code": [3] * 24 + [95] * 4 + [3] * 44,
    }
    town = command.summarise_town({"name": "Test", "lat": 16.0, "lon": 80.0, "population": 1000, "km": 5, "direction": "east"}, hourly, "2026-10-02T00:00")
    assert town["rain_past_24h"] == 24.0 and town["rain_next_24h"] == 96.0 and town["rain_band"] == "Heavy"
    assert town["gust_max"] == 55 and town["thunder_hours"] == 4
    assert town["score"] == 2 + 1 + 1


def test_model_and_climate_statistics():
    compare = {"models": {"a": "A", "b": "B"}, "days": [
        {"date": "2026-10-02", "a": {"rain": 2.0}, "b": {"rain": 10.0}, "spread_tmax": 1.0, "spread_rain": 8.0},
        {"date": "2026-10-03", "a": {"rain": 0.0}, "b": {"rain": 1.0}, "spread_tmax": 3.0, "spread_rain": 1.0},
    ]}
    stats = research.model_stats(compare)
    assert stats["max_tmax_spread_date"] == "2026-10-03" and stats["max_rain_spread_date"] == "2026-10-02"
    assert stats["wettest_model"] == "b" and stats["rain_totals"] == {"a": 2.0, "b": 11.0}
    annual = [{"year": 1991 + i, "mean_temp": 27.0 + i * 0.02, "rain_total": 900 + i, "hot_days_over_40": 10 + i // 10} for i in range(36)]
    clim = research.climate_stats({"annual": annual})
    assert clim["first_decade"] == "1991–2000" and clim["last_decade"] == "2016–2025"
    assert clim["temp_change_c"] == 0.5 and clim["warmest_year"] == 2025


def test_csv_export_format():
    assert research._csv(["a", "b"], [[1, None], ["x,y", 2.5]]) == 'a,b\n1,\n"x,y",2.5\n'
