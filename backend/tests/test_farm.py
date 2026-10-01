from app.services import farm


def hour(time, temp=27.0, rh=70, dew=20.0, rain=0.0, gust=10.0, sun=3600):
    return {"time": time, "temperature_2m": temp, "relative_humidity_2m": rh, "dew_point_2m": dew, "precipitation": rain, "wind_gusts_10m": gust, "sunshine_duration": sun}


def test_leaf_wetness_from_humidity_rain_or_dew():
    assert farm.is_wet(hour("t", rh=92))
    assert farm.is_wet(hour("t", rain=0.4))
    assert farm.is_wet(hour("t", temp=22.0, dew=20.5))
    assert not farm.is_wet(hour("t", temp=30.0, rh=60, dew=21.0))


def test_day_stats_count_wet_hours_and_their_temperature():
    hours = [hour(f"2026-10-05T{h:02d}:00", temp=24.0, rh=95) for h in range(12)] + [hour(f"2026-10-05T{h:02d}:00", temp=32.0, rh=55, dew=20.0) for h in range(12, 24)]
    stats = farm.day_stats(hours)
    assert stats["wet_hours"] == 12 and stats["wet_temp"] == 24.0
    assert stats["tmin"] == 24.0 and stats["tmax"] == 32.0 and stats["sunshine_h"] == 24.0


def test_rice_blast_needs_long_wetness_in_its_temperature_range():
    blast = next(r for r in farm.DISEASES if r["id"] == "rice_blast")
    base = {"humid_hours": 0, "humid_temp": None, "rh90_hours": 0, "tmin": 22, "tmax": 30, "tmean": 26, "rh_mean": 80, "rain": 0, "gust": 10}
    assert farm.disease_level(blast, base | {"wet_hours": 13, "wet_temp": 24.0}, None) == 2
    assert farm.disease_level(blast, base | {"wet_hours": 9, "wet_temp": 24.0}, None) == 1
    assert farm.disease_level(blast, base | {"wet_hours": 13, "wet_temp": 31.0}, None) == 0
    assert farm.disease_level(blast, base | {"wet_hours": 4, "wet_temp": 24.0}, None) == 0


def test_late_blight_follows_the_hutton_criteria():
    rule = next(r for r in farm.DISEASES if r["id"] == "late_blight")
    good = {"tmin": 12, "rh90_hours": 7}
    cold = {"tmin": 8, "rh90_hours": 9}
    assert farm.disease_level(rule, good, good) == 2
    assert farm.disease_level(rule, good, cold) == 1
    assert farm.disease_level(rule, cold, good) == 0


def test_tasks_say_what_to_do_and_what_to_avoid():
    day = {"stats": {"rain": 0.0, "gust": 12, "sunshine_h": 9.0, "rh_mean": 65, "tmax": 33, "tmin": 22}, "prob": 10}
    wet = {"stats": {"rain": 30.0, "gust": 20, "sunshine_h": 1.0, "rh_mean": 92, "tmax": 28, "tmin": 23}, "prob": 90}
    window = {"start": "2026-10-05T06:00", "end": "2026-10-05T09:00", "hours": 3}
    tasks = {t["task"]: t for t in farm.tasks_for(day, day, day, [window], True, 28.0)}
    assert tasks["spray"]["text"] == "Spray 06:00–09:00" and tasks["irrigate"]["status"] == "good" and tasks["harvest"]["status"] == "good"
    tasks = {t["task"]: t for t in farm.tasks_for(wet, wet, None, [], False, 0.0, "rain")}
    assert tasks["spray"]["status"] == "avoid" and "wash" in tasks["spray"]["detail"]
    assert tasks["fertiliser"]["status"] == "avoid" and tasks["harvest"]["status"] == "avoid" and tasks["irrigate"]["text"] == "Hold irrigation"


def test_sowing_verdict_and_crop_parsing():
    assert farm.sowing("wheat", 2.0)["verdict"] == "avoid"
    assert farm.sowing("wheat", 18.0)["verdict"] == "good"
    assert farm.sowing("chilli", 33.0)["verdict"] == "caution"
    assert farm.parse_crops("rice:mid, mirchi:development, rice, unknown") == [("paddy", "mid"), ("chilli", "development")]
