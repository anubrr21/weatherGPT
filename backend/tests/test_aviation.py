from app.services import aviation


def test_flight_category_from_visibility_and_ceiling():
    assert aviation.flight_category(6.2, None) == "VFR"
    assert aviation.flight_category(4.0, 5000) == "MVFR"
    assert aviation.flight_category(6.0, 2500) == "MVFR"
    assert aviation.flight_category(2.0, 5000) == "IFR"
    assert aviation.flight_category(6.0, 800) == "IFR"
    assert aviation.flight_category(0.5, 5000) == "LIFR"
    assert aviation.flight_category(6.0, 300) == "LIFR"


def test_ceiling_is_the_lowest_broken_or_overcast_layer():
    clouds = [{"cover": "FEW", "base": 1500}, {"cover": "BKN", "base": 10000}, {"cover": "OVC", "base": 4000}]
    assert aviation.ceiling_of(clouds) == 4000
    assert aviation.ceiling_of([{"cover": "SCT", "base": 2000}]) is None


def test_headwind_and_crosswind_components():
    assert aviation.wind_components(90, 20, 90) == {"headwind": 20.0, "crosswind": 0.0}
    assert aviation.wind_components(180, 20, 90) == {"headwind": 0.0, "crosswind": 20.0}
    parts = aviation.wind_components(120, 20, 90)
    assert parts["headwind"] == 17.3 and parts["crosswind"] == 10.0
    assert aviation.wind_components(270, 10, 90)["headwind"] == -10.0


def test_density_altitude_rises_with_heat_and_low_pressure():
    standard = aviation.density_altitude(0, 1013.25, 15)
    assert standard["density_altitude_ft"] == 0 and standard["isa_deviation_c"] == 0
    hot = aviation.density_altitude(2024, 1005, 38)
    assert hot["pressure_altitude_ft"] == 2247 and hot["density_altitude_ft"] > 5000


def test_taf_periods_get_a_category_and_thunder_flag():
    taf = {"fcsts": [
        {"timeFrom": 1790888400, "timeTo": 1790899200, "wdir": 90, "wspd": 8, "visib": 3.11, "wxString": "HZ", "clouds": [{"cover": "SCT", "base": 2000, "type": None}]},
        {"timeFrom": 1790899200, "timeTo": 1790917200, "fcstChange": "TEMPO", "visib": "6+", "wxString": "TSRA", "clouds": [{"cover": "BKN", "base": 800, "type": "CB"}]},
    ]}
    first, second = aviation.taf_periods(taf)
    assert first["category"] == "MVFR" and first["visibility_km"] == 5.0 and not first["thunder"]
    assert second["category"] == "IFR" and second["thunder"] and second["ceiling_ft"] == 800


def test_sigmet_is_near_when_the_airport_is_inside_or_close():
    box = {"area": [[16.0, 77.0], [16.0, 80.0], [19.0, 80.0], [19.0, 77.0]]}
    assert aviation.near_sigmet(box, 17.2, 78.4)
    assert aviation.near_sigmet(box, 19.5, 80.5)
    assert not aviation.near_sigmet(box, 28.5, 77.1)
