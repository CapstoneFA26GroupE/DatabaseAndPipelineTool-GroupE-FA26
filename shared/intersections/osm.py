import json
import logging
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import httpx

from intersections.geo import GridIndex, LocalProjection
from intersections.labels import ClassifierConfig
from services.errors import MapDataUnavailableError

logger = logging.getLogger(__name__)

# road types a car drives on; service roads (parking lots, driveways) and paths are left out
# so driveways and parking lot entrances don't count as intersections
DRIVABLE_HIGHWAYS = {
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
    "residential", "living_street",
}
# a junction where every road is a freeway or a ramp is a merge, not an intersection
FREEWAY_HIGHWAYS = {"motorway", "motorway_link"}


@dataclass
class Intersection:
    # one real-world intersection (several junction nodes can belong to one intersection)
    id: str
    lat: float
    lon: float
    node_ids: list[int]
    road_types: list[str]
    map_signalized: bool
    signal_node_ids: list[int] = field(default_factory=list)
    # stop / give_way signs mapped near the intersection, kept for the details shown to users
    controls: list[str] = field(default_factory=list)


def build_overpass_query(south: float, west: float, north: float, east: float) -> str:
    # this asks overpass for drivable roads (with all their nodes) and traffic control nodes in a box
    bbox = f"{south:.6f},{west:.6f},{north:.6f},{east:.6f}"
    road_regex = "^(" + "|".join(sorted(DRIVABLE_HIGHWAYS)) + ")$"
    return (
        "[out:json][timeout:90];\n"
        "(\n"
        f'  way["highway"~"{road_regex}"]({bbox});\n'
        f'  node["highway"~"^(traffic_signals|stop|give_way)$"]({bbox});\n'
        ");\n"
        "(._;>;);\n"
        "out body;\n"
    )


def parse_intersections(elements: Iterable[dict[str, Any]], config: ClassifierConfig) -> list[Intersection]:
    # this turns raw openstreetmap elements into a list of intersections
    nodes: dict[int, dict[str, Any]] = {}
    ways: list[dict[str, Any]] = []
    for element in elements:
        if element.get("type") == "node" and "lat" in element and "lon" in element:
            nodes[element["id"]] = element
        elif element.get("type") == "way" and element.get("tags", {}).get("highway") in DRIVABLE_HIGHWAYS:
            ways.append(element)
    if not nodes or not ways:
        return []

    # this block counts how many road branches meet at each node
    # (a node in the middle of a way is 2 branches, the end of a way is 1),
    # so a road that is just split into two ways at a node is not mistaken for an intersection
    degree: dict[int, int] = defaultdict(int)
    road_types: dict[int, set[str]] = defaultdict(set)
    for way in ways:
        way_nodes = way.get("nodes", [])
        highway = way["tags"]["highway"]
        for index, node_id in enumerate(way_nodes):
            branches = (1 if index > 0 else 0) + (1 if index < len(way_nodes) - 1 else 0)
            degree[node_id] += branches
            road_types[node_id].add(highway)

    junction_ids = [
        node_id
        for node_id, branches in degree.items()
        if branches >= 3 and node_id in nodes and not road_types[node_id] <= FREEWAY_HIGHWAYS
    ]
    if not junction_ids:
        return []

    # this block projects everything onto flat meters around the area's center
    lat0 = sum(nodes[n]["lat"] for n in junction_ids) / len(junction_ids)
    lon0 = sum(nodes[n]["lon"] for n in junction_ids) / len(junction_ids)
    projection = LocalProjection(lat0, lon0)
    xy = {n: projection.to_xy(nodes[n]["lat"], nodes[n]["lon"]) for n in junction_ids}

    # this block merges junction nodes that are close together into one intersection (union-find)
    parent = {n: n for n in junction_ids}

    def find(n: int) -> int:
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    grid: GridIndex[int] = GridIndex(cell_m=max(config.junction_cluster_m, 1.0))
    for n in junction_ids:
        x, y = xy[n]
        for _, other in grid.query_radius(x, y, config.junction_cluster_m):
            parent[find(n)] = find(other)
        grid.insert(x, y, n)

    clusters: dict[int, list[int]] = defaultdict(list)
    for n in junction_ids:
        clusters[find(n)].append(n)

    # this block indexes traffic signals and stop / give way signs so each intersection can look them up
    control_grid: GridIndex[tuple[int, str]] = GridIndex(cell_m=max(config.signal_search_m, 1.0))
    for node_id, node in nodes.items():
        control = node.get("tags", {}).get("highway")
        if control in ("traffic_signals", "stop", "give_way"):
            cx, cy = projection.to_xy(node["lat"], node["lon"])
            control_grid.insert(cx, cy, (node_id, control))

    intersections: list[Intersection] = []
    for members in clusters.values():
        members.sort()
        x = sum(xy[n][0] for n in members) / len(members)
        y = sum(xy[n][1] for n in members) / len(members)
        lat, lon = projection.to_latlon(x, y)
        nearby = control_grid.query_radius(x, y, config.signal_search_m)
        signal_nodes = sorted({node_id for _, (node_id, control) in nearby if control == "traffic_signals"})
        controls = sorted({control for _, (_, control) in nearby if control != "traffic_signals"})
        types = sorted({t for n in members for t in road_types[n]})
        intersections.append(
            Intersection(
                id=f"osm-{members[0]}",
                lat=lat,
                lon=lon,
                node_ids=members,
                road_types=types,
                map_signalized=bool(signal_nodes),
                signal_node_ids=signal_nodes,
                controls=controls,
            )
        )
    return intersections


def tiles_for_points(points: Iterable[tuple[float, float]], tile_deg: float) -> set[tuple[int, int]]:
    # this returns the map tiles (tile_deg x tile_deg squares) the route passes through
    return {(int(math.floor(lat / tile_deg)), int(math.floor(lon / tile_deg))) for lat, lon in points}


class OsmMapSource:
    # this downloads road data for the tiles a route covers from an overpass server, with an on-disk cache

    def __init__(self, config: ClassifierConfig, client: httpx.Client | None = None) -> None:
        self.config = config
        self._client = client
        self._cache_dir = Path(config.map_cache_dir)

    def _cache_path(self, tile: tuple[int, int]) -> Path:
        return self._cache_dir / f"tile_{self.config.map_tile_deg:g}_{tile[0]}_{tile[1]}.json"

    def _read_cache(self, tile: tuple[int, int]) -> list[dict[str, Any]] | None:
        path = self._cache_path(tile)
        try:
            if time.time() - path.stat().st_mtime > self.config.map_cache_days * 86400:
                return None
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write_cache(self, tile: tuple[int, int], elements: list[dict[str, Any]]) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_path(tile).write_text(json.dumps(elements), encoding="utf-8")
        except OSError:
            logger.warning("Could not write map cache for tile %s", tile)

    def _download_tile(self, tile: tuple[int, int]) -> list[dict[str, Any]]:
        # this fetches one tile (plus a small margin so intersections on the tile edge are complete)
        deg = self.config.map_tile_deg
        margin = 0.002
        south, west = tile[0] * deg - margin, tile[1] * deg - margin
        north, east = (tile[0] + 1) * deg + margin, (tile[1] + 1) * deg + margin
        query = build_overpass_query(south, west, north, east)

        client = self._client or httpx.Client(timeout=httpx.Timeout(120.0))
        last_error = ""
        try:
            for attempt in range(4):
                try:
                    response = client.post(self.config.overpass_url, data={"data": query})
                    if response.status_code == 200:
                        return response.json().get("elements", [])
                    last_error = f"HTTP {response.status_code}"
                    # this backs off when the public server says it is busy (429) or overloaded (5xx)
                    if response.status_code not in (429, 502, 503, 504):
                        break
                except (httpx.HTTPError, ValueError) as e:
                    last_error = f"{type(e).__name__}: {e}"
                time.sleep(min(30.0, 5.0 * (attempt + 1)))
        finally:
            if self._client is None:
                client.close()
        raise MapDataUnavailableError(
            f"Could not download OpenStreetMap road data for tile {tile} from {self.config.overpass_url}: {last_error}"
        )

    def elements_for_points(self, points: list[tuple[float, float]]) -> list[dict[str, Any]]:
        # this returns all map elements covering the given gps points, using the cache when possible
        elements_by_key: dict[tuple[str, int], dict[str, Any]] = {}
        tiles = sorted(tiles_for_points(points, self.config.map_tile_deg))
        logger.info("Route covers %d map tile(s)", len(tiles))
        for tile in tiles:
            elements = self._read_cache(tile)
            if elements is None:
                elements = self._download_tile(tile)
                self._write_cache(tile, elements)
                time.sleep(1.0)  # be polite to the public overpass server
            for element in elements:
                elements_by_key[(element.get("type", ""), element.get("id", 0))] = element
        return list(elements_by_key.values())

    def intersections_for_points(self, points: list[tuple[float, float]]) -> list[Intersection]:
        return parse_intersections(self.elements_for_points(points), self.config)
