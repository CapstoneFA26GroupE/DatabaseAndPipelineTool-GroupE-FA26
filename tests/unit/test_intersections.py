# tests for the intersection classifier (map parsing, gps reading, combine rules, frame labels)
import json

import httpx
import pytest

from intersections.classifier import (
    CameraEvidence,
    FramePoint,
    IntersectionMatcher,
    classify_frames,
    count_labels,
    decide_intersection,
    select_camera_samples,
)
from intersections.gps import fill_position_gaps, extract_lat_lon, positions_by_frame_id
from intersections.labels import (
    NON_INTERSECTION,
    SIGNALIZED,
    UNKNOWN,
    UNSIGNALIZED,
    ClassifierConfig,
)
from intersections.osm import Intersection, OsmMapSource, parse_intersections, tiles_for_points
from services.errors import MapDataUnavailableError

LAT0, LON0 = 35.2000, -97.4400  # norman, ok
DEG_PER_M = 1 / 111_320  # about 1 m of latitude
CONFIG = ClassifierConfig(camera_check=False, map_cache_dir="/nonexistent-cache")


def node(node_id, north_m=0.0, east_m=0.0, **tags):
    # this makes an osm node a given number of meters north/east of the test origin
    lon_scale = 0.8181  # cos(35.2 deg)
    return {"type": "node", "id": node_id, "lat": LAT0 + north_m * DEG_PER_M,
            "lon": LON0 + east_m * DEG_PER_M / lon_scale, "tags": tags}


def way(way_id, node_ids, highway="residential"):
    return {"type": "way", "id": way_id, "nodes": node_ids, "tags": {"highway": highway}}


# ─── map parsing ─────────────────────────────────────────────────────────────

def test_four_way_crossing_is_one_intersection():
    elements = [node(1, 0, -100), node(2), node(3, 0, 100), node(4, -100, 0), node(5, 100, 0),
                way(10, [1, 2, 3]), way(11, [4, 2, 5])]
    found = parse_intersections(elements, CONFIG)
    assert [i.node_ids for i in found] == [[2]]
    assert found[0].map_signalized is False


def test_t_junction_counts_and_split_road_does_not():
    elements = [node(1, 0, -100), node(2), node(3, 0, 100), node(4, -100, 0),
                way(10, [1, 2]), way(11, [2, 3]),  # one straight road split at node 2: 2 branches
                way(12, [4, 2])]  # a third road ends at node 2: now 3 branches -> T-junction
    assert len(parse_intersections(elements, CONFIG)) == 1
    only_split = [node(1, 0, -100), node(2), node(3, 0, 100), way(10, [1, 2]), way(11, [2, 3])]
    assert parse_intersections(only_split, CONFIG) == []


def test_freeway_ramp_merge_is_not_an_intersection():
    elements = [node(1, 0, -200), node(2), node(3, 0, 200), node(4, -50, -150),
                way(10, [1, 2, 3], "motorway"), way(11, [4, 2], "motorway_link")]
    assert parse_intersections(elements, CONFIG) == []
    # a ramp meeting a surface street is a real intersection
    elements = [node(1, 0, -100), node(2), node(3, 0, 100), node(4, -100, 0),
                way(10, [1, 2, 3], "primary"), way(11, [4, 2], "motorway_link")]
    assert len(parse_intersections(elements, CONFIG)) == 1


def test_service_roads_and_driveways_are_ignored():
    elements = [node(1, 0, -100), node(2), node(3, 0, 100), node(4, -40, 0),
                way(10, [1, 2, 3]), way(11, [4, 2], "service")]
    assert parse_intersections(elements, CONFIG) == []


def test_divided_road_junction_nodes_are_merged():
    # a divided road (two carriageways 15 m apart) crossed by a street gives two junction nodes
    elements = [node(1, 0, -100), node(2, 0, 0), node(3, 0, 100),
                node(4, 15, -100), node(5, 15, 0), node(6, 15, 100),
                node(7, -100, 0), node(8, 100, 0),
                way(10, [1, 2, 3], "primary"), way(11, [4, 5, 6], "primary"), way(12, [7, 2, 5, 8])]
    found = parse_intersections(elements, CONFIG)
    assert len(found) == 1
    assert sorted(found[0].node_ids) == [2, 5]


def test_nearby_traffic_signal_makes_it_signalized():
    elements = [node(1, 0, -100), node(2), node(3, 0, 100), node(4, -100, 0), node(5, 100, 0),
                node(6, 0, -20, highway="traffic_signals"),  # signal mapped on the approach, 20 m away
                way(10, [1, 6, 2, 3]), way(11, [4, 2, 5])]
    found = parse_intersections(elements, CONFIG)
    assert len(found) == 1 and found[0].map_signalized and found[0].signal_node_ids == [6]


def test_signal_too_far_away_does_not_count_and_stop_signs_are_recorded():
    elements = [node(1, 0, -200), node(2), node(3, 0, 200), node(4, -100, 0), node(5, 100, 0),
                node(6, 0, -120, highway="traffic_signals"), node(7, 0, 10, highway="stop"),
                way(10, [1, 6, 2, 3]), way(11, [4, 2, 5])]
    found = parse_intersections(elements, CONFIG)
    assert found[0].map_signalized is False and found[0].controls == ["stop"]


# ─── gps ─────────────────────────────────────────────────────────────────────

def test_gps_extraction():
    good = {"frame_id": 5, "vehicle_state": {"status": "valid",
            "positionGeodetic": {"value": [35.2, -97.44, 350.0], "valid": True}}}
    assert extract_lat_lon(good) == (35.2, -97.44)
    assert extract_lat_lon({"vehicle_state": {"positionGeodetic": {"value": [35.2, -97.44], "valid": False}}}) is None
    assert extract_lat_lon({"vehicle_state": {"status": "uninitialized",
                                              "positionGeodetic": {"value": [35.2, -97.44]}}}) is None
    assert extract_lat_lon({"vehicle_state": {"positionGeodetic": {"value": [0.0, 0.0]}}}) is None
    assert extract_lat_lon({"vehicle_state": None}) is None
    assert extract_lat_lon({}) is None
    assert positions_by_frame_id([good, {"frame_id": 6}]) == {5: (35.2, -97.44), 6: None}


# ─── combine rules ───────────────────────────────────────────────────────────

def _intersection(signalized: bool, controls=None):
    return Intersection(id="osm-1", lat=LAT0, lon=LON0, node_ids=[1], road_types=["residential"],
                        map_signalized=signalized, controls=controls or [])


@pytest.mark.parametrize("signalized, evidence, label, source", [
    (True, None, SIGNALIZED, "map"),
    (True, CameraEvidence(sampled=6, signal_frames=4), SIGNALIZED, "map+camera"),
    (True, CameraEvidence(sampled=6, signal_frames=0), SIGNALIZED, "map"),
    (False, CameraEvidence(sampled=6, signal_frames=3), SIGNALIZED, "camera"),
    (False, CameraEvidence(sampled=6, signal_frames=1), UNSIGNALIZED, "map+camera"),  # one frame is not enough
    (False, None, UNSIGNALIZED, "map"),
])
def test_decide_intersection(signalized, evidence, label, source):
    decision = decide_intersection(_intersection(signalized), evidence, ClassifierConfig())
    assert (decision.label, decision.source) == (label, source)


# ─── frame labels ────────────────────────────────────────────────────────────

def _drive_east(count=21, spacing_m=10.0, start_m=-100.0):
    # frames of a car driving east through the origin, one every 10 m
    lon_scale = 0.8181
    return [FramePoint(0, i, (LAT0, LON0 + (start_m + i * spacing_m) * DEG_PER_M / lon_scale)) for i in range(count)]


def test_classify_frames_by_distance():
    frames = _drive_east() + [FramePoint(0, 99, None)]
    labels = classify_frames(frames, [_intersection(True)], {}, CONFIG)
    by_frame = {key[1]: label.label for key, label in labels.items()}
    assert by_frame[0] == NON_INTERSECTION  # 100 m before
    assert by_frame[7] == SIGNALIZED  # 30 m before
    assert by_frame[10] == SIGNALIZED  # in the middle
    assert by_frame[14] == NON_INTERSECTION  # 40 m past
    assert by_frame[99] == UNKNOWN
    assert labels[(0, 10)].details["distance_m"] < 1
    assert count_labels(labels.values()) == {NON_INTERSECTION: 14, SIGNALIZED: 7, UNKNOWN: 1}


def test_classify_with_no_intersections_is_all_non_intersection():
    labels = classify_frames(_drive_east(5), [], {}, CONFIG)
    assert {label.label for label in labels.values()} == {NON_INTERSECTION}


def test_camera_samples_are_spread_over_the_approach():
    config = ClassifierConfig(camera_samples_per_intersection=4)
    matcher = IntersectionMatcher([_intersection(False)], config.approach_radius_m)
    samples = select_camera_samples(_drive_east(), matcher, config)
    picked = samples["osm-1"]
    assert len(picked) == 4
    assert picked[0] == (0, 4) and picked[-1] == (0, 16)  # first and last frame within 60 m


# ─── map download + cache ────────────────────────────────────────────────────

def test_map_source_downloads_once_then_uses_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("intersections.osm.time.sleep", lambda _s: None)
    elements = [node(1, 0, -100), node(2), node(3, 0, 100), node(4, -100, 0), way(10, [1, 2, 3]), way(11, [4, 2])]
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"elements": elements})

    config = ClassifierConfig(map_cache_dir=str(tmp_path))
    source = OsmMapSource(config, client=httpx.Client(transport=httpx.MockTransport(handler)))
    points = [(LAT0, LON0)]
    assert len(source.intersections_for_points(points)) == 1
    assert len(source.intersections_for_points(points)) == 1
    assert len(calls) == len(tiles_for_points(points, config.map_tile_deg)) == 1
    assert json.loads(next(tmp_path.iterdir()).read_text())


def test_map_source_reports_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr("intersections.osm.time.sleep", lambda _s: None)
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(429)))
    source = OsmMapSource(ClassifierConfig(map_cache_dir=str(tmp_path)), client=client)
    with pytest.raises(MapDataUnavailableError, match="HTTP 429"):
        source.intersections_for_points([(LAT0, LON0)])


def test_map_source_identifies_itself_and_falls_back_when_refused(tmp_path, monkeypatch):
    # the main overpass server answers 406 to generic clients; we must send a real user agent and use a backup
    monkeypatch.setattr("intersections.osm.time.sleep", lambda _s: None)
    elements = [node(1, 0, -100), node(2), node(3, 0, 100), node(4, -100, 0), way(10, [1, 2, 3]), way(11, [4, 2])]
    seen = []

    def handler(request):
        seen.append((request.url.host, request.headers.get("user-agent", "")))
        if request.url.host == "main.example":
            return httpx.Response(406)
        return httpx.Response(200, json={"elements": elements})

    config = ClassifierConfig(
        map_cache_dir=str(tmp_path), overpass_url="https://main.example/api/interpreter",
        overpass_fallback_urls=("https://backup.example/api/interpreter",),
    )
    source = OsmMapSource(config, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert len(source.intersections_for_points([(LAT0, LON0)])) == 1
    assert [host for host, _ in seen] == ["main.example", "backup.example"]  # 406 is not retried on the same server
    assert all(agent.startswith("MiLa-DataPipeline") for _, agent in seen)


def test_frames_between_gps_readings_get_an_interpolated_position():
    # logs.json often has a reading only every 2-3 camera frames; the frames in between borrow one
    positions = {10: (35.0, -97.0), 13: (35.003, -97.0), 40: (35.1, -97.0), 41: None}
    frame_ids = [9, 10, 11, 12, 13, 14, 30, 40, 41, 60]
    filled, interpolated = fill_position_gaps(positions, frame_ids, max_gap_frames=10)
    assert filled[11] == pytest.approx((35.001, -97.0)) and filled[12] == pytest.approx((35.002, -97.0))
    assert filled[9] == (35.0, -97.0) and filled[14] == (35.003, -97.0)  # edges copy the nearest reading
    assert filled[30] is None  # 13 -> 40 is too big a gap to guess across
    assert filled[41] == (35.1, -97.0) and filled[60] is None
    assert interpolated == {9, 11, 12, 14, 41}
    assert fill_position_gaps(positions, frame_ids, max_gap_frames=0)[0][11] is None
