import asyncio
import json
import time

from app.services import lightning


def lzw_encode(text: str) -> str:
    dictionary = {chr(i): i for i in range(256)}
    code, phrase, out = 256, text[0], []
    for ch in text[1:]:
        if phrase + ch in dictionary:
            phrase += ch
        else:
            out.append(chr(dictionary[phrase]))
            dictionary[phrase + ch] = code
            code += 1
            phrase = ch
    out.append(chr(dictionary[phrase]))
    return "".join(out)


def test_feed_decodes_blitzortung_messages_and_keeps_only_the_india_region():
    feed = lightning.StrikeFeed()
    now_ns = time.time_ns()
    feed.add(lzw_encode(json.dumps({"time": now_ns, "lat": 16.51, "lon": 80.62, "sig": [{"sta": 1}, {"sta": 2}, {"sta": 3}]})))
    feed.add(lzw_encode(json.dumps({"time": now_ns, "lat": 48.1, "lon": 11.5, "sig": []})))
    feed.add("not json")
    assert len(feed.strikes) == 1
    near = feed.near(16.5, 80.6, 10, 5)
    assert len(near) == 1 and near[0]["stations"] == 3 and near[0]["km"] < 3
    assert feed.near(16.5, 80.6, 1, 5) == []


def test_storm_motion_gives_speed_heading_and_eta():
    now = time.time()
    place = (16.5, 80.6)
    earlier = [{"t": now - 25 * 60, "lat": 16.5, "lon": 80.0 + d, "km": 0} for d in (0.0, 0.01, 0.02)]
    recent = [{"t": now - 3 * 60, "lat": 16.5, "lon": 80.2 + d, "km": 0} for d in (0.0, 0.01, 0.02)]
    strikes = [s | {"km": lightning.km(place, (s["lat"], s["lon"]))} for s in earlier + recent]
    move = lightning.motion(strikes, place)
    assert move["heading"] == "east"
    assert 55 < move["speed_kmh"] < 75
    assert move["closing_kmh"] > 50
    assert 30 < move["eta_min"] < 50


def test_thunder_score_uses_codes_cape_and_lifted_index():
    assert lightning._thunder_score(95, 1500, -4, 60) == 3
    assert lightning._thunder_score(95, 200, 1, 30) == 2
    assert lightning._thunder_score(96, 0, 0, 0) == 3
    assert lightning._thunder_score(3, 1800, -4, 50) == 2
    assert lightning._thunder_score(2, 900, -1.5, 30) == 1
    assert lightning._thunder_score(1, 300, 2, 10) == 0


def test_official_polygons_are_parsed_and_matched(monkeypatch):
    xml = b"<alert><identifier>IN-1</identifier><polygon>16.0,80.0 16.0,81.0 17.0,81.0 17.0,80.0 16.0,80.0</polygon></alert>"

    class Response:
        content = xml

        def raise_for_status(self):
            return None

    class Client:
        async def get(self, url, timeout=None):
            return Response()

    monkeypatch.setattr(lightning, "client", lambda: Client())
    rings = asyncio.run(lightning.polygons({"id": "test-polygon", "polygon_url": "https://example.test/poly"}))
    assert rings == [[[80.0, 16.0], [81.0, 16.0], [81.0, 17.0], [80.0, 17.0], [80.0, 16.0]]]
    area = {"id": "a", "rings": rings}
    assert lightning.covering([area], 16.5, 80.6) == [area]
    assert lightning.covering([area], 18.0, 80.6) == []


def test_local_headline_matches_sachet_telugu_code():
    alert = {"localized": [{"language": "TL", "headline": "పిడుగులు"}, {"language": "hi-IN", "headline": "बिजली"}]}
    assert lightning._local_headline(alert, "te") == "పిడుగులు"
    assert lightning._local_headline(alert, "hi") == "बिजली"
    assert lightning._local_headline(alert, "ta") is None
