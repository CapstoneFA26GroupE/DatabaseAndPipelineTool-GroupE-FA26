from typing import Any


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # drops NaN


def extract_lat_lon(log_entry: dict[str, Any]) -> tuple[float, float] | None:
    # this pulls the car's gps position out of one frame's entry in logs.json
    # the download worker stores openpilot's liveLocationKalman message under "vehicle_state",
    # whose positionGeodetic.value is [latitude, longitude, altitude]
    state = log_entry.get("vehicle_state") or {}
    if not isinstance(state, dict):
        return None

    # openpilot marks the estimate as not usable until it has a gps lock
    if str(state.get("status", "")).lower() == "uninitialized":
        return None

    geodetic = state.get("positionGeodetic") or state.get("position_geodetic") or {}
    if not isinstance(geodetic, dict):
        return None
    if geodetic.get("valid") is False:
        return None

    value = geodetic.get("value")
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    lat, lon = _as_float(value[0]), _as_float(value[1])
    if lat is None or lon is None:
        return None

    # this rejects impossible values and the 0,0 placeholder some logs contain before a fix
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    if abs(lat) < 1e-6 and abs(lon) < 1e-6:
        return None
    return lat, lon


def positions_by_frame_id(log_entries: list[dict[str, Any]]) -> dict[int, tuple[float, float] | None]:
    # this maps each frame_id in a segment's logs.json to its gps position (None when there was no fix)
    positions: dict[int, tuple[float, float] | None] = {}
    for entry in log_entries:
        frame_id = entry.get("frame_id")
        if isinstance(frame_id, int):
            positions[frame_id] = extract_lat_lon(entry)
    return positions
