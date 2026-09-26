from app.services.wis2 import parse_topic


def test_indian_synop_via_gts_gateway():
    info = parse_topic("origin/a/wis2/jp-jma-gts-to-wis2/data/core/S/M/I/N/01/DEMS")
    assert info["india"] is True
    assert info["centre"] == "jp-jma-gts-to-wis2"
    assert info["policy"] == "core"
    assert info["gts"] == {"ttaaii": "SMIN01", "cccc": "DEMS", "t1t2": "SM", "area": "IN"}


def test_non_indian_gts_bulletin():
    assert parse_topic("origin/a/wis2/de-dwd-gts-to-wis2/data/core/S/M/D/L/01/EDZW")["india"] is False


def test_native_wis2_topic_from_indian_centre():
    info = parse_topic("origin/a/wis2/in-imd/data/core/weather/surface-based-observations/synop")
    assert info["india"] is True and info["gts"] is None


def test_native_foreign_topic():
    info = parse_topic("origin/a/wis2/ca-eccc-msc/data/core/weather/surface-based-observations/synop")
    assert info["india"] is False and info["policy"] == "core"
