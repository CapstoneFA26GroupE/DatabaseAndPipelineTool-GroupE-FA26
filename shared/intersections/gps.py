import bisect
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


def fill_position_gaps(
    positions: dict[int, tuple[float, float] | None], frame_ids: list[int], max_gap_frames: int
) -> tuple[dict[int, tuple[float, float] | None], set[int]]:
    # this gives frames without their own gps reading a position from the readings around them
    # (logs.json often has a fix only every second or third camera frame). between two readings at most
    # max_gap_frames apart the position is interpolated; at the start/end of a segment the nearest reading
    # is copied if it is close enough. returns the filled positions and which frame ids were filled in
    known = sorted(fid for fid, pos in positions.items() if pos is not None)
    filled = {fid: positions.get(fid) for fid in frame_ids}
    interpolated: set[int] = set()
    if not known or max_gap_frames <= 0:
        return filled, interpolated

    for fid in frame_ids:
        if filled.get(fid) is not None:
            continue
        i = bisect.bisect_left(known, fid)
        before = known[i - 1] if i > 0 else None
        after = known[i] if i < len(known) else None
        if before is not None and after is not None and after - before <= max_gap_frames:
            t = (fid - before) / (after - before)
            (lat0, lon0), (lat1, lon1) = positions[before], positions[after]
            filled[fid] = (lat0 + t * (lat1 - lat0), lon0 + t * (lon1 - lon0))
        else:
            # edge of the readings: copy the nearest one if it is within half the allowed gap
            nearest = min((k for k in (before, after) if k is not None), key=lambda k: abs(k - fid))
            if abs(nearest - fid) * 2 > max_gap_frames:
                continue
            filled[fid] = positions[nearest]
        interpolated.add(fid)
    return filled, interpolated
