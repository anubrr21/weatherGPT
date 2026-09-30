from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.services import trips


def test_great_circle_ends_at_both_airports_and_measures_distance():
    path = trips._great_circle((16.53, 80.80), (28.57, 77.10), 20)
    assert path[0] == (16.53, 80.80) or abs(path[0][0] - 16.53) < 1e-6
    assert abs(path[-1][0] - 28.57) < 1e-6 and abs(path[-1][1] - 77.10) < 1e-6
    assert 1370 < trips.cumulative(path)[-1] / 1000 < 1400


def test_sampling_covers_start_and_end():
    coords = [(16.5 + i * 0.01, 80.6) for i in range(300)]
    route = trips.Route(coords, trips.cumulative(coords), [i * 30.0 for i in range(300)], "x", "y")
    picks = trips.sample(route, max_points=10)
    assert picks[0] == 0 and picks[-1] == 299 and 5 <= len(picks) <= 14


def test_hazards_depend_on_mode():
    shower = {"precipitation": 3.0, "weather_code": 63, "wind_gusts_10m": 45, "visibility": 8000, "apparent_temperature": 30, "temperature_2m": 26}
    assert max(h["level"] for h in trips.assess(shower, "bike")) > max(h["level"] for h in trips.assess(shower, "car"))
    assert any(h["kind"] == "wind" for h in trips.assess(shower, "bike"))
    assert not any(h["kind"] == "wind" for h in trips.assess(shower, "car"))


def test_dense_fog_is_severe_on_roads_and_capped_for_trains():
    fog = {"precipitation": 0, "weather_code": 45, "wind_gusts_10m": 10, "visibility": 150, "apparent_temperature": 12, "temperature_2m": 11}
    assert max(h["level"] for h in trips.assess(fog, "car")) == 3
    assert max(h["level"] for h in trips.assess(fog, "train")) == 2


def test_cruise_phase_flags_convection_not_surface_rain():
    storm = {"precipitation": 9, "weather_code": 95, "cape": 3200, "wind_speed_250hPa": 90}
    kinds = {h["kind"] for h in trips.assess(storm, "flight", "cruise")}
    assert kinds == {"convection"}


def test_consecutive_hazards_merge_into_one_span():
    points = [
        {"i": 0, "i_prev": -1, "km": 0, "eta": "t0", "hazards": []},
        {"i": 5, "i_prev": 0, "km": 20, "eta": "t1", "hazards": [{"kind": "rain", "level": 1, "detail": "Moderate rain"}]},
        {"i": 9, "i_prev": 5, "km": 40, "eta": "t2", "hazards": [{"kind": "rain", "level": 2, "detail": "Heavy rain"}]},
        {"i": 14, "i_prev": 9, "km": 60, "eta": "t3", "hazards": []},
    ]
    merged = trips.spans(points, "car", {5: "Nandigama", 9: "Kodad"})
    assert len(merged) == 1
    assert merged[0]["from_km"] == 20 and merged[0]["to_km"] == 40 and merged[0]["severity"] == "High"
    assert merged[0]["detail"] == "Heavy rain" and merged[0]["advice"]


def test_rail_pathfinding_follows_track():
    coords = np.array([[16.0, 80.0], [16.1, 80.0], [16.2, 80.1], [16.1, 80.3], [16.3, 80.2]])
    adj = [[] for _ in range(5)]
    for a, b in [(0, 1), (1, 2), (2, 4), (1, 3), (3, 4)]:
        m = trips.haversine(tuple(coords[a]), tuple(coords[b]))
        adj[a].append((b, m))
        adj[b].append((a, m))
    assert trips._dijkstra(adj, 0, 4, coords) == [0, 1, 2, 4]


def test_weather_is_read_at_the_hour_of_arrival():
    series = {"elevation": 20, "hourly": {"time": ["2026-09-27T00:00", "2026-09-27T01:00", "2026-09-27T02:00"], "temperature_2m": [20, 21, 22]}}
    assert trips._at(series, datetime(2026, 9, 27, 1, 20, tzinfo=timezone.utc))["temperature_2m"] == 21
    assert trips._at(series, datetime(2026, 9, 28, 1, 0, tzinfo=timezone.utc)) is None


def _straight_route(hours: float):
    coords = [(16.0 + i * 0.01, 80.0) for i in range(600)]
    seconds = [i * hours * 3600 / 599 for i in range(600)]
    return trips.Route(coords, trips.cumulative(coords), seconds, "x", "y")


def test_breaks_every_two_hours_in_daylight():
    depart = datetime(2026, 9, 28, 2, 30, tzinfo=timezone.utc)
    targets = trips.rest_targets(_straight_route(7.6), "car", depart)
    assert [(round(t / 3600, 1), r) for t, r in targets] == [(2.0, "break"), (4.0, "break"), (6.0, "break")]


def test_late_night_drive_gets_an_overnight_stop():
    depart = datetime(2026, 9, 28, 14, 30, tzinfo=timezone.utc)
    targets = trips.rest_targets(_straight_route(7.6), "car", depart)
    assert targets[0] == (2 * 3600, "overnight")
    assert [r for _, r in targets].count("overnight") == 1


def test_two_wheeler_breaks_are_more_frequent():
    depart = datetime(2026, 9, 28, 2, 30, tzinfo=timezone.utc)
    assert len(trips.rest_targets(_straight_route(6), "bike", depart)) == 3


def test_rest_places_are_real_named_and_close():
    window = [(16.5, 80.5), (16.51, 80.5)]
    elements = [
        {"type": "node", "id": 1, "lat": 16.5005, "lon": 80.5005, "tags": {"amenity": "fuel", "brand": "Indian Oil", "opening_hours": "24/7"}},
        {"type": "node", "id": 2, "lat": 16.5010, "lon": 80.5010, "tags": {"amenity": "restaurant", "name": "maa palle ruchulu"}},
        {"type": "node", "id": 3, "lat": 16.5010, "lon": 80.5012, "tags": {"tourism": "guest_house", "name": "house"}},
        {"type": "node", "id": 4, "lat": 16.9000, "lon": 80.9000, "tags": {"amenity": "restaurant", "name": "Far Away Dhaba"}},
        {"type": "way", "id": 5, "center": {"lat": 16.5020, "lon": 80.5020}, "tags": {"highway": "services"}},
    ]
    picked = trips.rank_places(elements, window, overnight=False)
    names = [p["name"] for p in picked]
    assert "Indian Oil" in names and "Maa Palle Ruchulu" in names and "Highway services" in names
    assert "house" not in [n.lower() for n in names] and "Far Away Dhaba" not in names
    assert all(p["osm"].startswith("https://www.openstreetmap.org/") for p in picked)


def _line(points, speed=20.0):
    coords = list(points)
    cum_m = trips.cumulative(coords)
    return trips.Route(coords, cum_m, [m / speed for m in cum_m], "", "")


def test_legs_join_into_one_route_with_stops_and_pauses():
    first = _line([(16.5, 80.6), (16.4, 80.5), (16.3, 80.4)])
    second = _line([(16.3, 80.4), (16.1, 80.2)])
    joined = trips.join_legs([first, second], pause_s=600)
    assert len(joined.coords) == 4
    assert joined.stops == [2]
    assert joined.cum_m[-1] == pytest.approx(first.meters + second.meters)
    assert joined.cum_s[-1] == pytest.approx(first.seconds + 600 + second.seconds)
    assert trips.sample(joined).count(2) == 1


def test_via_marks_give_distance_and_arrival_time():
    route = trips.join_legs([_line([(16.5, 80.6), (16.3, 80.4)]), _line([(16.3, 80.4), (16.1, 80.2)])])
    depart = datetime(2026, 9, 30, 6, tzinfo=timezone.utc)
    marks = trips.via_marks(route, [{"name": "Guntur", "lat": 16.3, "lon": 80.4}], depart)
    assert marks[0]["name"] == "Guntur"
    assert marks[0]["km"] == round(route.cum_m[1] / 1000, 1)
    assert marks[0]["eta"] == (depart + timedelta(seconds=route.cum_s[1])).isoformat()
