from datetime import datetime, timezone

from app.services import sea


def test_boat_limits_differ_by_boat_type():
    assert sea.verdict("small", 1.2, 20)[0] == "CAUTION"
    assert sea.verdict("motor", 1.2, 20)[0] == "GO"
    assert sea.verdict("small", 1.6, 20)[0] == "NO-GO"
    assert sea.verdict("trawler", 2.0, 42)[0] == "GO"
    assert sea.verdict("trawler", 2.0, 62) == ("NO-GO", ["gusts 62 km/h"])
    assert sea.verdict("motor", 0.5, 10, thunder=True) == ("CAUTION", ["thunderstorm"])
    assert sea.verdict("motor", 0.5, 10, visibility_m=600)[0] == "CAUTION"


def test_tides_find_highs_and_lows_between_the_hours():
    times = [f"2026-10-02T{h:02d}:00" for h in range(13)]
    levels = [0.2, 0.5, 0.8, 0.95, 0.9, 0.6, 0.3, 0.1, 0.05, 0.2, 0.5, 0.8, 0.9]
    found = sea.tides(times, levels)
    assert [t["type"] for t in found] == ["high", "low"]
    assert found[0]["time"].startswith("2026-10-02T03:") and found[0]["height_m"] >= 0.95
    assert found[1]["time"].startswith("2026-10-02T0") and found[1]["height_m"] <= 0.05


def test_moon_phase_and_spring_tides():
    full = sea.moon(datetime(2026, 9, 26, 16, 49, tzinfo=timezone.utc))
    assert full["phase"].startswith("Full moon") and full["illumination"] >= 98 and full["spring_tide"]
    quarter = sea.moon(datetime(2026, 10, 3, 13, 25, tzinfo=timezone.utc))
    assert quarter["phase"] == "Last quarter" and not quarter["spring_tide"]


def test_inland_places_have_no_sea_workspace():
    marine = {"hourly": {"time": ["2026-10-02T00:00"], "wave_height": [None]}}
    assert sea.build(marine, {}, [])["available"] is False


def test_safe_windows_need_three_calm_hours():
    hours = [{"time": f"2026-10-02T{h:02d}:00", "verdicts": {"small": "GO" if h in (4, 5, 6, 7, 12, 13) else "CAUTION"}} for h in range(24)]
    assert sea.windows(hours, "small") == [{"start": "2026-10-02T04:00", "end": "2026-10-02T08:00", "hours": 4}]
