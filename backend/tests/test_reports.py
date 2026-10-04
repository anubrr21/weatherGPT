from datetime import datetime, timedelta, timezone

import pytest

from app.services import logistics, reports
from app.services.trips import Route, cumulative

START = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
SPEC = {"mode": "road", "vehicle": "hcv", "crew": 1, "high_sided": False, "open_body": True}


def series(**values):
    base = {
        "temperature_2m": 28.0, "apparent_temperature": 30.0, "dew_point_2m": 18.0, "relative_humidity_2m": 55, "precipitation": 0.0,
        "weather_code": 1, "wind_gusts_10m": 15.0, "wind_direction_10m": 270, "visibility": 20000, "is_day": 1,
    } | values
    times = [(START + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(120)]
    return {"elevation": 100, "hourly": {"time": times} | {k: [v] * 120 for k, v in base.items()}}


def run(km=700, **values):
    coords = [(20.0, 75.0 + 0.5 * n) for n in range(15)]
    cum_m = cumulative(coords)
    cum_m = [m * km * 1000 / cum_m[-1] for m in cum_m]
    route = Route(coords, cum_m, [m / (50 / 3.6) for m in cum_m], "test", "")
    picks = list(range(len(coords)))
    return logistics.simulate(route, picks, [series(**values) for _ in picks], None, START, SPEC)


def test_clean_keeps_text_printable():
    assert reports.clean("Pune → Hyderabad ≥ 5 ₹") == "Pune to Hyderabad >= 5 Rs "
    assert reports.clean("हि") == "??"
    assert reports.clean(None) == ""


def test_length_reads_naturally():
    assert reports.length(45) == "45 min"
    assert reports.length(120) == "2 h"
    assert reports.length(1505) == "1 d 1 h"


def test_delay_is_attributed_to_its_cause():
    result = run(km=200, precipitation=10.0, visibility=600)
    causes = result["causes"]
    assert set(causes) == {"rain", "fog"}
    assert sum(causes.values()) == pytest.approx(result["delay_s"])
    rows = logistics.breakdown(result)
    assert {row["kind"] for row in rows} == {"rain", "fog"}
    assert all(row["km"] > 0 and row["delay_min"] > 0 for row in rows)


def test_stages_cover_the_whole_route():
    result = run()
    parts = logistics.stages(result)
    assert parts[0]["from_km"] == 0
    assert parts[-1]["to_km"] == result["points"][-1]["km"]
    assert all(a["to_km"] == b["from_km"] for a, b in zip(parts, parts[1:]))


def test_no_halt_in_the_last_two_hours():
    result = run(km=560)
    assert all(r["kind"] != "halt" for r in result["rests"])
    longer = run(km=900)
    assert any(r["kind"] == "halt" for r in longer["rests"])


def test_confidence_falls_with_lead_time_and_model_disagreement():
    result = run(km=200)
    near = logistics.confidence(result, START, [])
    far = logistics.confidence(result, START - timedelta(days=6), [])
    split = logistics.confidence(result, START, [{"score": 40}])
    assert near["label"] == "High"
    assert far["score"] < near["score"]
    assert split["label"] == "Low" and "disagree" in split["note"]


def site(name, level):
    day = {"date": START.strftime("%Y-%m-%d"), "level": level, "status": ["Normal", "Watch", "Disrupted", "Shut down likely"][level], "lost_hours": level * 3, "slow_hours": 1, "hours": 24, "rain_mm": 12.5, "gust_max": 60, "vis_min": 800, "feels_max": 35, "wave_max": 2.1, "reasons": ["crane and yard work stops (3 h)"] if level else []}
    return {"id": name, "kind": "port", "name": name, "area": "Gujarat", "code": None, "lat": 22.7, "lon": 69.7, "level": level, "status": day["status"], "now": {"temp": 29.0, "feels": 33.0, "rain_mmh": 0.0, "gust": 20.0, "visibility": 9000, "label": "Clear sky"}, "days": [day], "warnings": [], "cyclone": None}


def test_facility_report_is_a_pdf():
    board = {"generated_at": START.isoformat(), "sites": [site("Mundra Port", 2), site("Pipavav Port", 0)], "summary": {"total": 2, "normal": 1, "watch": 0, "disrupted": 1}, "rules": {"port": "Yard cranes stop at gusts of 72 km/h."}}
    pdf = reports.facilities_report(board)
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 3000


def test_markdown_turns_headings_and_bullets_into_blocks():
    blocks = reports.markdown("### Bottom line\nGo with **caution**.\n- First step\n1. Second step\n<speak>ignore me</speak>")
    assert len(blocks) == 4
