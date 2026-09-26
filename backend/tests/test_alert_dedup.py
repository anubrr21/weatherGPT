from app.services.ingest import _content_key


def test_reissued_bulletin_collapses_across_timezones():
    ist = {"headline": "River Ghaghra at Turtipar  continues to flow", "expires": "2026-09-27T09:00:00+05:30"}
    utc = {"headline": "river ghaghra at turtipar continues to flow", "expires": "2026-09-27T03:30:00+00:00"}
    assert _content_key(ist) == _content_key(utc)


def test_different_expiry_is_distinct():
    a = {"headline": "Heavy rain", "expires": "2026-09-27T03:30:00+00:00"}
    b = {"headline": "Heavy rain", "expires": "2026-09-28T03:30:00+00:00"}
    assert _content_key(a) != _content_key(b)
