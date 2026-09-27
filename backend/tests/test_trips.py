from datetime import datetime, timezone

import numpy as np

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
