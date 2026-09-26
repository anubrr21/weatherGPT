from datetime import datetime, timezone
from typing import Any

from pybufrkit.dataquery import DataQuerent, NodePathParser
from pybufrkit.decoder import Decoder

from app.services.synop import present_weather

_decoder = Decoder()
_querent = DataQuerent(NodePathParser())


def _first(message, descriptor: str) -> Any:
    try:
        values = _querent.query(message, descriptor).all_values(flat=True)
    except Exception:
        return None
    for subset in values or []:
        for value in subset or []:
            if value is not None:
                return value
    return None


def _kelvin(value: Any) -> float | None:
    return round(float(value) - 273.15, 1) if isinstance(value, (int, float)) else None


def _weather(code: Any) -> str | None:
    if not isinstance(code, int):
        return None
    if code < 100:
        return present_weather(code)
    if 100 <= code <= 199:
        return present_weather(code - 100) if code - 100 >= 4 else None
    return None


def decode_observation(data: bytes) -> dict[str, Any] | None:
    message = _decoder.process(data)
    block, number = _first(message, "001001"), _first(message, "001002")
    lat, lon = _first(message, "005001"), _first(message, "006001")
    if block is None or number is None or lat is None or lon is None:
        return None
    parts = [_first(message, f"00400{i}") for i in range(1, 6)]
    if any(p is None for p in parts[:4]):
        return None
    observed = datetime(int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4] or 0), tzinfo=timezone.utc)
    name = _first(message, "001015")
    if isinstance(name, bytes):
        name = name.replace(b"\x00", b"").decode("latin-1").strip().title() or None
    wind_ms = _first(message, "011002")
    pressure = _first(message, "010051") or _first(message, "010004")
    visibility = _first(message, "020001")
    rh = _first(message, "013003")
    temp = _kelvin(_first(message, "012101"))
    dew = _kelvin(_first(message, "012103"))
    if rh is None and temp is not None and dew is not None:
        import math

        rh = round(100 * math.exp(17.625 * dew / (243.04 + dew)) / math.exp(17.625 * temp / (243.04 + temp)))
    wind_dir = _first(message, "011001")
    return {
        "station": f"{int(block):02d}{int(number):03d}",
        "name": name,
        "lat": float(lat),
        "lon": float(lon),
        "observed_at": observed,
        "temp_c": temp,
        "dewpoint_c": dew,
        "humidity_pct": rh,
        "pressure_hpa": round(float(pressure) / 100, 1) if isinstance(pressure, (int, float)) else None,
        "wind_dir_deg": int(wind_dir) if isinstance(wind_dir, (int, float)) and wind_dir not in (0,) else None,
        "wind_kmh": round(float(wind_ms) * 3.6, 1) if isinstance(wind_ms, (int, float)) else None,
        "visibility_km": round(float(visibility) / 1000, 1) if isinstance(visibility, (int, float)) else None,
        "rain_mm": _first(message, "013011"),
        "cloud_pct": _first(message, "020010"),
        "weather": _weather(_first(message, "020003")),
    }
