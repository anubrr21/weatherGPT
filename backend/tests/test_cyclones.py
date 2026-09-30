import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services import cyclones


def test_imd_grades_follow_the_official_wind_bands():
    assert cyclones.grade(16)["code"] == "L"
    assert cyclones.grade(17)["code"] == "D"
    assert cyclones.grade(33)["code"] == "DD"
    assert cyclones.grade(34)["code"] == "CS"
    assert cyclones.grade(63)["code"] == "SCS"
    assert cyclones.grade(64)["code"] == "VSCS"
    assert cyclones.grade(90)["code"] == "ESCS"
    assert cyclones.grade(130)["label"] == "Super Cyclonic Storm"
    assert cyclones.grade(None) is None


def test_closest_approach_interpolates_position_time_and_wind():
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    track = [
        {"time": t0.isoformat(), "lat": 17.0, "lon": 86.0, "kt": 40, "forecast": False},
        {"time": (t0 + timedelta(hours=12)).isoformat(), "lat": 17.0, "lon": 82.0, "kt": 60, "forecast": True},
    ]
    near = cyclones.closest_approach(track, (17.7, 84.0))
    assert 70 < near["km"] < 85
    assert near["time"].startswith("2026-10-01T06:00")
    assert near["kt"] == pytest.approx(50)
    assert near["grade"]["code"] == "SCS"
    assert near["direction"] == "south"
    assert near["forecast"] is True


def test_point_in_polygon_and_warning_stage():
    ring = [[80.0, 15.0], [82.0, 15.0], [82.0, 17.0], [80.0, 17.0], [80.0, 15.0]]
    assert cyclones.inside((16.0, 81.0), ring)
    assert not cyclones.inside((18.0, 81.0), ring)
    assert cyclones.stage_for(60, 120, False)["code"] == "watch"
    assert cyclones.stage_for(40, 400, True)["code"] == "alert"
    assert cyclones.stage_for(20, 90, False)["code"] == "warning"
    assert cyclones.stage_for(6, 30, True)["code"] == "post_landfall"
    assert cyclones.stage_for(30, 600, False) is None
    assert cyclones.stage_for(100, 20, True) is None


def test_gdacs_timeline_becomes_observed_and_forecast_fixes():
    timeline = [
        {"advisory_number": "1", "actual": "True", "advisory_datetime": "22 Sep 2026 18:00", "latitude": "17.6", "longitude": "84.8", "wind_speed": "18.004", "wind_gusts": "23.148", "pressure": "0", "storm_status": ["Tropical Storm"], "windrad_nm_34kt_se": "35", "pop39": "7996072"},
        {"advisory_number": "2", "actual": "True", "advisory_datetime": "23 Sep 2026 00:00", "latitude": "17.8", "longitude": "84.0", "wind_speed": "20.0", "wind_gusts": "25", "pressure": "996", "storm_status": ["Tropical Storm"]},
        {"advisory_number": "2", "actual": "False", "latitude": "18.5", "longitude": "83.5", "wind_speed": "15.4", "storm_status": ["Tropical Depression"]},
    ]
    geometry = {"features": [{"properties": {"featuretype": "PointRadii", "key": "09231200"}}, {"properties": {"featuretype": "PointRadii", "key": "09230000"}}]}
    fixes, issued = cyclones._gdacs_fixes(timeline, geometry)
    assert issued == datetime(2026, 9, 23, tzinfo=timezone.utc)
    assert [f["forecast"] for f in fixes] == [False, False, True]
    assert fixes[2]["time"].startswith("2026-09-23T12:00")
    assert round(fixes[0]["kt"]) == 33
    assert fixes[0]["gale_radius_km"] == {"se": 65}
    assert fixes[1]["pressure"] == 996


@pytest.mark.skipif(not cyclones.HISTORY.exists(), reason="cyclone history not built")
def test_visakhapatnam_history_includes_hudhud_landfall():
    past = cyclones.near_history(17.69, 83.22, 150)
    hudhud = next(s for s in past["storms"] if s["name"] == "Hudhud")
    assert hudhud["season"] == 2014 and hudhud["closest_km"] < 25
    assert hudhud["peak"]["code"] == "ESCS"
    assert past["by_month"][9] >= max(past["by_month"][:5])
    assert past["return_period_years"] and past["return_period_years"] < 10


def test_storm_names_join_variants_without_duplicates():
    spec = importlib.util.spec_from_file_location("build", Path(__file__).resolve().parent.parent / "scripts" / "build_cyclone_history.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    assert build.storm_name("GULAB:SHAHEEN-GU") == "Gulab / Shaheen"
    assert build.storm_name("HIKAA:HIKKA") == "Hikaa"
    assert build.storm_name("UNNAMED") is None


def test_jtwc_validity_parses_both_header_styles(monkeypatch):
    import asyncio

    samples = {
        "OCEAN/301800ZSEP2026-011800ZOCT2026//": "2026-10-01T18:00:00+00:00",
        "OCEAN/291800Z-\r\n301800ZSEP2026//": "2026-09-30T18:00:00+00:00",
    }
    for header, expected in samples.items():
        body = f"SUBJ/SIGNIFICANT TROPICAL WEATHER ADVISORY FOR THE INDIAN {header}\r\n1. NORTH INDIAN OCEAN AREA:\r\n   A. TROPICAL CYCLONE SUMMARY: NONE.\r\n   B. TROPICAL DISTURBANCE SUMMARY: NONE.\r\n   C. SUBTROPICAL SYSTEM SUMMARY: NONE.\r\n2. SOUTH INDIAN OCEAN AREA"

        async def fake(*args, body=body, **kwargs):
            return type("R", (), {"text": body})()

        monkeypatch.setattr(cyclones, "get_retry", fake)
        result = asyncio.run(cyclones._jtwc_outlook())
        assert result["valid_until"] == expected
        assert result["quiet"] is True


def test_warning_text_describes_approach_cone_wind_and_surge():
    t0 = datetime.now(timezone.utc)
    storm = {
        "id": "gdacs-1", "name": "TEST", "current": True, "issued": t0.isoformat(), "surge": {"max_m": 2.4},
        "now": {"time": t0.isoformat(), "lat": 15.0, "lon": 86.0, "kt": 70, "grade": cyclones.grade(70)},
        "track": [
            {"time": t0.isoformat(), "lat": 15.0, "lon": 86.0, "kt": 70, "forecast": False},
            {"time": (t0 + timedelta(hours=30)).isoformat(), "lat": 17.8, "lon": 83.3, "kt": 80, "forecast": True},
        ],
        "shapes": {"cone": {"type": "Polygon", "coordinates": [[[82.5, 14.0], [87.0, 14.0], [87.0, 18.5], [82.5, 18.5], [82.5, 14.0]]]}, "radii": [
            {"time": (t0 + timedelta(hours=24)).isoformat(), "kmh": 90, "geometry": {"type": "Polygon", "coordinates": [[[82.8, 17.2], [83.8, 17.2], [83.8, 18.2], [82.8, 18.2], [82.8, 17.2]]]}},
        ]},
    }
    hit = cyclones.impact(storm, 17.69, 83.22)
    assert hit["in_cone"] and hit["wind_zone"]["kmh"] == 90
    assert hit["closest"]["km"] < 30
    assert hit["stage"]["code"] == "alert"
    title, body = cyclones.warning_text(storm, hit, "Visakhapatnam")
    assert title.startswith("Cyclone alert: Very Severe Cyclonic Storm TEST")
    assert "inside the forecast cone" in body and "90 km/h" in body and "2.4 m" in body
