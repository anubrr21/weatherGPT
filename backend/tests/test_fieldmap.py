import pytest

from app.services import fieldmap


def test_grid_covers_india_at_the_configured_step():
    lats, lons = fieldmap.grid()
    assert lats[0] == fieldmap.BOX["south"] and lats[-1] <= fieldmap.BOX["north"]
    assert lons[0] == fieldmap.BOX["west"] and lons[-1] <= fieldmap.BOX["east"]
    assert all(b - a == pytest.approx(fieldmap.STEP) for a, b in zip(lats, lats[1:]))
    assert len(lats) * len(lons) <= 600


def test_wind_direction_becomes_blowing_towards_components():
    u, v = fieldmap.components(20, 270)
    assert u == pytest.approx(20) and v == pytest.approx(0, abs=0.1)
    u, v = fieldmap.components(10, 0)
    assert v == pytest.approx(-10) and u == pytest.approx(0, abs=0.1)
    assert fieldmap.components(None, 90) == (0.0, 0.0)
