import asyncio

import httpx

from app.services import ratings


PLACE = {"name": "Maa Palle Ruchulu", "kind": "restaurant", "lat": 17.1362, "lon": 79.6333}


def _candidate(name, lat, lon, rating=4.3, count=812):
    return {"displayName": {"text": name}, "location": {"latitude": lat, "longitude": lon}, "rating": rating, "userRatingCount": count, "googleMapsUri": "https://maps.google.com/?cid=1"}


def test_matches_same_business_nearby():
    match = ratings.best_match(PLACE, [_candidate("Maa Palle Ruchulu Family Restaurant", 17.1364, 79.6335)])
    assert match and match["rating"] == 4.3


def test_rejects_same_name_far_away_and_different_business_nearby():
    assert ratings.best_match(PLACE, [_candidate("Maa Palle Ruchulu", 17.20, 79.70)]) is None
    assert ratings.best_match(PLACE, [_candidate("Sri Balaji Tiffins", 17.1363, 79.6334)]) is None


def test_enrich_uses_places_api_and_attaches_rating(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["mask"] = request.headers.get("x-goog-fieldmask")
        return httpx.Response(200, json={"places": [_candidate("Maa Palle Ruchulu", 17.1363, 79.6334)]})

    mock = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(ratings, "client", lambda: mock)
    monkeypatch.setattr(ratings, "enabled", lambda: True)
    monkeypatch.setattr(ratings, "get_settings", lambda: type("S", (), {"google_maps_api_key": "test-key"})())
    place = dict(PLACE)
    assert asyncio.run(ratings.enrich([place])) == 1
    assert place["google"]["rating"] == 4.3 and place["google"]["count"] == 812
    assert seen["key"] == "test-key" and "places.rating" in seen["mask"]
