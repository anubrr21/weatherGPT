from datetime import datetime, timezone
from pathlib import Path

from app.services.bufr_obs import decode_observation

SAMPLE = Path(__file__).parent / "data" / "imd_nashik_42921_20260926T2100.bufr4"


def test_decodes_real_imd_wis2_bufr():
    o = decode_observation(SAMPLE.read_bytes())
    assert o["station"] == "42921"
    assert o["name"] == "Nasik"
    assert (o["lat"], o["lon"]) == (20.0, 73.78)
    assert o["observed_at"] == datetime(2026, 9, 26, 21, 0, tzinfo=timezone.utc)
    assert o["temp_c"] == 21.6 and o["dewpoint_c"] == 20.1
    assert o["pressure_hpa"] == 1010.2
    assert o["wind_dir_deg"] == 320 and o["wind_kmh"] == 3.6
    assert o["visibility_km"] == 4.0 and o["rain_mm"] == 0.0
    assert o["humidity_pct"] == 91
    assert o["weather"] is None
