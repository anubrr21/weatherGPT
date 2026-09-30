from datetime import datetime, timedelta, timezone

from app.services import verify


def test_metars_become_hourly_rows_with_rain_flags():
    rows = [
        {"valid": "2026-09-28 05:30", "tmpf": "86.0", "dwpf": "75.2", "sknt": "10", "wxcodes": "M"},
        {"valid": "2026-09-28 06:00", "tmpf": "87.8", "dwpf": "75.2", "sknt": "8", "wxcodes": "-TSRA"},
        {"valid": "2026-09-28 06:40", "tmpf": "84.2", "dwpf": "77.0", "sknt": "M", "wxcodes": "M"},
    ]
    hours = verify.hourly_observations(rows)
    six = hours["2026-09-28T06:00:00+00:00"]
    assert six["temp"] == 31.0 and six["dew"] == 24.0 and six["wind"] == 14.8
    assert six["rain"] is True
    assert hours["2026-09-28T05:00:00+00:00"]["rain"] is False
    assert "2026-09-28T07:00:00+00:00" in hours and hours["2026-09-28T07:00:00+00:00"]["wind"] is None


def test_continuous_and_categorical_scores():
    assert verify.continuous([(1.0, 0.0)] * 5) is None
    stats = verify.continuous([(31.0, 30.0)] * 10 + [(29.0, 30.0)] * 10)
    assert stats == {"mae": 1.0, "bias": 0.0, "rmse": 1.0, "n": 20}
    pairs = [(True, True)] * 6 + [(False, True)] * 2 + [(True, False)] * 2 + [(False, False)] * 30
    cat = verify.categorical(pairs)
    assert cat["pod"] == 0.75 and cat["far"] == 0.25 and cat["csi"] == 0.6
    assert 0.6 < cat["hss"] < 0.75


def test_score_matches_forecasts_to_observed_hours_only_in_the_past():
    base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(days=2)
    times = [(base + timedelta(hours=h)).isoformat() for h in range(30)]
    obs = {t: {"temp": 30.0, "dew": 24.0, "wind": 10.0, "rain": h % 10 == 0} for h, t in enumerate(times)}
    runs = {m: {"temp": {1: {t: 31.0 for t in times}, 2: {t: 32.0 for t in times}}, "dew": {1: {}, 2: {}}, "wind": {1: {t: 10.0 for t in times}, 2: {}}, "rain": {1: {t: (1.0 if h % 10 == 0 else 0.0) for h, t in enumerate(times)}, 2: {}}} for m, _ in verify.MODELS}
    scores = verify.score(obs, runs)
    assert scores["best_match"]["temp"][1]["bias"] == 1.0
    assert scores["best_match"]["temp"][2]["mae"] == 2.0
    assert scores["best_match"]["wind"][1]["mae"] == 0.0
    assert scores["best_match"]["dew"][1] is None
    assert scores["best_match"]["rain"][1]["pod"] == 1.0
    assert scores["best_match"]["rain"][1]["far"] == 0.0


def test_leaderboard_ranks_by_relative_error():
    def station(errors):
        return {"scores": {m: {"temp": {1: {"mae": e, "n": 100}}, "dew": {1: {"mae": e, "n": 100}}, "wind": {1: {"mae": e * 3, "n": 100}}, "rain": {1: {"hss": 0.5, "n": 100}}} for m, e in errors.items()}}
    errors = {m: 1.0 + k * 0.1 for k, (m, _) in enumerate(verify.MODELS)}
    errors["gfs_seamless"] = 0.5
    board = verify.leaderboard([station(errors)])
    assert board[0]["model"] == "gfs_seamless" and board[0]["rank"] == 1
    assert board[-1]["model"] == "cma_grapes_global"
