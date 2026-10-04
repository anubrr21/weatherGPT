from datetime import datetime, timedelta, timezone

import pytest

from app.services import logistics
from app.services.trips import Route, TripError, cumulative

START = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
ROAD = {"mode": "road", "vehicle": "hcv", "crew": 1, "high_sided": False, "open_body": True}
TRAILER = {"mode": "road", "vehicle": "container", "crew": 1, "high_sided": True, "open_body": False}


def series(hours=96, **values):
    base = {
        "temperature_2m": 28.0, "apparent_temperature": 30.0, "dew_point_2m": 18.0, "relative_humidity_2m": 55, "precipitation": 0.0, "precipitation_probability": 0,
        "weather_code": 1, "wind_speed_10m": 8.0, "wind_gusts_10m": 15.0, "wind_direction_10m": 270, "visibility": 20000, "is_day": 1, "cape": 0,
        "wind_speed_250hPa": 60, "wind_direction_250hPa": 270,
    } | values
    times = [(START + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(hours)]
    return {"elevation": 100, "hourly": {"time": times} | {k: [v] * hours for k, v in base.items()}}


def straight(km=600, speed_kmh=50, steps=13):
    coords = [(20.0, 75.0 + 0.45 * n * km / 600) for n in range(steps)]
    cum_m = cumulative(coords)
    scale = km * 1000 / cum_m[-1]
    cum_m = [m * scale for m in cum_m]
    return Route(coords, cum_m, [m / (speed_kmh / 3.6) for m in cum_m], "test", "")


def run(route, spec, **values):
    picks = list(range(len(route.coords)))
    return logistics.simulate(route, picks, [series(**values) for _ in picks], None, START, spec)


def test_dry_weather_adds_no_delay():
    result = run(straight(), ROAD)
    assert result["delay_s"] == 0
    assert result["max_level"] == 0


def test_heavy_rain_slows_within_the_published_range():
    route = straight(km=200)
    result = run(route, ROAD, precipitation=10.0, weather_code=65)
    share = result["delay_s"] / route.seconds
    assert 0.15 < share < 0.25
    assert result["delay_worst_s"] > result["delay_s"]


def test_dense_fog_is_severe_and_slower_than_rain():
    fog = run(straight(km=200), ROAD, visibility=120)
    rain = run(straight(km=200), ROAD, precipitation=10.0)
    assert fog["max_level"] == 3
    assert fog["delay_s"] > rain["delay_s"]


def test_time_multiplier_combines_speed_losses():
    expected, worst = logistics.time_multiplier([("rain", 0.1, 0.2), ("fog", 0.1, 0.2)])
    assert expected == pytest.approx(1 / 0.81)
    assert worst == pytest.approx(1 / 0.64)


def test_single_driver_gets_breaks_and_a_night_halt():
    route = straight(km=900)
    one = run(route, ROAD)
    two = run(route, ROAD | {"crew": 2})
    assert any(r["kind"] == "halt" for r in one["rests"])
    assert all(r["kind"] == "break" for r in two["rests"])
    assert one["arrive"] - two["arrive"] > timedelta(hours=6)


def test_crosswind_only_counts_the_side_component():
    assert logistics.crosswind(80, 0, 90) == pytest.approx(80)
    assert logistics.crosswind(80, 90, 90) == pytest.approx(0, abs=1e-6)


def test_crosswind_hazard_needs_a_high_sided_vehicle():
    weather = {"wind_gusts_10m": 70, "wind_direction_10m": 0, "weather_code": 1}
    tall = logistics.hazards_at(weather, TRAILER, 90)
    low = logistics.hazards_at(weather, ROAD, 90)
    assert tall and tall[0]["kind"] == "wind" and tall[0]["level"] == 3
    assert all(h["level"] < 3 for h in low)


def test_mean_kinetic_temperature_weights_the_hot_hours():
    steady = logistics.mean_kinetic([25.0] * 10)
    mixed = logistics.mean_kinetic([15.0] * 5 + [35.0] * 5)
    assert steady == pytest.approx(25.0, abs=0.01)
    assert mixed > 25.5


def test_heat_humidity_index_matches_the_livestock_bands():
    assert logistics.heat_humidity_index(25, 50) < 75
    assert logistics.heat_humidity_index(38, 60) >= 84


def exposure(cargo, spec, **values):
    return logistics.cargo_exposure(run(straight(), spec, **values)["points"], cargo, spec)


def test_pharma_flags_an_excursion_in_hot_weather():
    hot = exposure("pharma", TRAILER, temperature_2m=36.0)
    mild = exposure("pharma", TRAILER, temperature_2m=21.0)
    assert hot["status"] == "risk"
    assert mild["status"] == "ok"


def test_chilled_cargo_on_an_ordinary_truck_is_a_risk():
    assert exposure("chilled", ROAD, temperature_2m=30.0)["status"] == "risk"
    assert exposure("chilled", TRAILER | {"vehicle": "reefer"}, temperature_2m=30.0)["status"] == "ok"


def test_rain_on_an_open_truck_threatens_moisture_sensitive_cargo():
    wet = exposure("moisture", ROAD, precipitation=3.0)
    covered = exposure("moisture", TRAILER, precipitation=3.0)
    assert wet["status"] == "risk"
    assert covered["status"] != "risk"


def test_livestock_heat_emergency():
    assert exposure("livestock", ROAD, temperature_2m=39.0, relative_humidity_2m=60)["status"] == "risk"


def port(name):
    return next(p for p in logistics.PORTS if p["id"] == name)


def test_west_to_east_sea_route_goes_south_of_sri_lanka():
    route = logistics.sea_route(port("kochi"), port("chennai"))
    assert min(lat for lat, _ in route.coords) < 6.0
    assert 1500 < route.meters / 1000 < 2600
    assert route.cum_s[-1] / 3600 == pytest.approx(route.meters / 1000 / logistics.SEA_KMH, rel=0.01)


def test_sea_route_is_the_same_length_both_ways():
    out = logistics.sea_route(port("mundra"), port("paradip"))
    back = logistics.sea_route(port("paradip"), port("mundra"))
    assert out.meters == pytest.approx(back.meters, rel=1e-6)
    assert out.coords[0] == pytest.approx(back.coords[-1])


def test_port_blair_is_reached_across_the_bay():
    route = logistics.sea_route(port("chennai"), port("portblair"))
    assert route.coords[-1] == pytest.approx((11.67, 92.75))
    assert 1200 < route.meters / 1000 < 1700


def test_same_port_is_rejected():
    with pytest.raises(TripError):
        logistics.sea_route(port("jnpt"), port("jnpt"))


def test_rough_sea_slows_a_vessel():
    spec = {"mode": "sea", "crew": 1}
    calm = logistics.time_multiplier(logistics.reductions({"wave_height": 1.0}, spec))[0]
    rough = logistics.time_multiplier(logistics.reductions({"wave_height": 4.5}, spec))[0]
    assert calm == 1
    assert rough > 1.3
    assert logistics.hazards_at({"wave_height": 4.5, "wind_gusts_10m": 70}, spec)[0]["level"] >= 2


def test_port_day_counts_hours_lost_to_wind():
    now = START
    land = series(hours=48, wind_gusts_10m=80.0)
    days = logistics.site_days("port", land, None, now)
    assert days[0]["lost_hours"] == days[0]["hours"]
    assert days[0]["level"] == 3
    calm = logistics.site_days("port", series(hours=48), None, now)
    assert calm[0]["level"] == 0 and calm[0]["lost_hours"] == 0


def test_hub_heat_counts_as_slow_hours_not_lost_hours():
    days = logistics.site_days("hub", series(hours=24, apparent_temperature=43.0), None, START)
    assert days[0]["lost_hours"] == 0
    assert days[0]["slow_hours"] > 0
    assert days[0]["level"] == 1


def test_depart_without_zone_is_read_as_india_time():
    now = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
    assert logistics.parse_depart("2026-10-06T21:00", now) == datetime(2026, 10, 6, 15, 30, tzinfo=timezone.utc)
    assert logistics.parse_depart(None, now) == now
    with pytest.raises(TripError):
        logistics.parse_depart("2026-11-30T21:00", now)


def test_verdict_holds_for_long_severe_stretches():
    result = run(straight(km=300), ROAD, visibility=100)
    cargo = {"status": "ok", "notes": []}
    call = logistics.verdict(result, cargo, [], [], ROAD)
    assert call["code"] == "hold"
    clear = logistics.verdict(run(straight(km=300), ROAD), cargo, [], [], ROAD)
    assert clear["code"] == "go"
